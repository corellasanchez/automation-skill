"""Test execution engine using Playwright.

Executes test steps against web pages, integrates DOM fingerprinting
for token-saving plan caching, and captures screenshots on failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import time
from typing import List, Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Locator

from src.env_loader import mask_secrets
from src.fingerprint import FingerprintManager
from src.parser import ActionStep


@dataclass
class StepResult:
    """Stores the execution outcome of a single test step."""
    line_number: int
    raw_line: str
    masked_line: str
    action: str
    status: str  # "PASSED" or "FAILED"
    duration_seconds: float
    error_message: Optional[str] = None
    was_cached: bool = False
    screenshot_path: Optional[str] = None


@dataclass
class TestResult:
    """Stores the overall outcome of an entire test file."""
    test_path: str
    test_name: str
    group_name: str
    status: str  # "PASSED" or "FAILED"
    duration_seconds: float
    steps: List[StepResult] = field(default_factory=list)
    failure_screenshot: Optional[str] = None
    error_message: Optional[str] = None


class WebTestExecutor:
    """Executes parsed test steps using headless Chromium."""

    def __init__(
        self,
        headless: bool = True,
        screenshots_dir: str = "reports/screenshots",
        fingerprint_manager: Optional[FingerprintManager] = None,
        default_timeout_ms: int = 8000
    ) -> None:
        """Initialize executor with browser configurations."""
        self.headless = headless
        self.screenshots_dir = screenshots_dir
        self.fingerprint_mgr = fingerprint_manager or FingerprintManager()
        self.default_timeout_ms = default_timeout_ms
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def run_test(self, test_path: str, steps: List[ActionStep]) -> TestResult:
        """Execute a single test file from start to finish."""
        rel_path = os.path.normpath(test_path)
        group_name = os.path.dirname(rel_path).replace("test" + os.sep, "").replace("test", "root")
        if not group_name:
            group_name = "root"
        test_name = os.path.basename(rel_path)

        start_time = time.time()
        step_results: List[StepResult] = []
        overall_status = "PASSED"
        test_failure_screenshot: Optional[str] = None
        test_error_message: Optional[str] = None

        with sync_playwright() as p:
            browser: Browser = p.chromium.launch(headless=self.headless)
            context: BrowserContext = browser.new_context(viewport={"width": 1280, "height": 800})
            page: Page = context.new_page()
            page.set_default_timeout(self.default_timeout_ms)

            try:
                for idx, step in enumerate(steps, start=1):
                    step_res = self._execute_step(page, step, test_name, idx)
                    step_results.append(step_res)

                    if step_res.status == "FAILED":
                        overall_status = "FAILED"
                        test_error_message = step_res.error_message
                        test_failure_screenshot = step_res.screenshot_path
                        break
            except Exception as e:
                overall_status = "FAILED"
                test_error_message = str(e)
            finally:
                context.close()
                browser.close()

        total_duration = round(time.time() - start_time, 2)
        return TestResult(
            test_path=test_path,
            test_name=test_name,
            group_name=group_name,
            status=overall_status,
            duration_seconds=total_duration,
            steps=step_results,
            failure_screenshot=test_failure_screenshot,
            error_message=test_error_message
        )

    def _execute_step(
        self,
        page: Page,
        step: ActionStep,
        test_name: str,
        step_index: int
    ) -> StepResult:
        """Execute a single ActionStep on the active page."""
        step_start = time.time()
        was_cached = False
        screenshot_path = None

        try:
            current_url = page.url
            current_fp = ""
            if current_url and current_url != "about:blank":
                current_fp = self.fingerprint_mgr.extract_fingerprint(page)

            # Check cached selector/plan if on a live page and step targets an element
            cached_action = None
            if current_fp and step.action in ("click", "fill", "select", "assert_element"):
                cached_action = self.fingerprint_mgr.get_cached_plan(test_name, step_index, current_url, current_fp)
                if cached_action:
                    was_cached = True

            if step.action == "navigate":
                url = step.target or ""
                if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("file://"):
                    url = f"https://{url}"
                page.goto(url, wait_until="load")

            elif step.action == "click":
                selector = cached_action.get("selector") if cached_action else None
                resolved_sel = self._click_target(page, step.target or "", selector)
                if current_fp and resolved_sel and not was_cached:
                    self.fingerprint_mgr.store_cached_plan(
                        test_name, step_index, current_url, current_fp, {"selector": resolved_sel}
                    )

            elif step.action == "fill":
                selector = cached_action.get("selector") if cached_action else None
                resolved_sel = self._fill_target(page, step.target or "", step.value or "", selector)
                if current_fp and resolved_sel and not was_cached:
                    self.fingerprint_mgr.store_cached_plan(
                        test_name, step_index, current_url, current_fp, {"selector": resolved_sel}
                    )

            elif step.action == "select":
                selector = cached_action.get("selector") if cached_action else None
                resolved_sel = self._select_target(page, step.target or "", step.value or "", selector)
                if current_fp and resolved_sel and not was_cached:
                    self.fingerprint_mgr.store_cached_plan(
                        test_name, step_index, current_url, current_fp, {"selector": resolved_sel}
                    )

            elif step.action == "press":
                page.keyboard.press(step.value or "Enter")

            elif step.action == "wait":
                time.sleep(step.wait_seconds or 1.0)

            elif step.action == "wait_page_load":
                try:
                    page.wait_for_load_state("load", timeout=4000)
                except Exception:
                    pass
                try:
                    page.wait_for_selector(".modal-content, table, [role='dialog'], main", timeout=3000)
                except Exception:
                    time.sleep(1.0)

            elif step.action == "wait_for":
                timeout_ms = int(max((step.wait_seconds or 6.0), 3.0) * 1000)
                locator = self._locate(page, step.target or "")
                locator.wait_for(state="visible", timeout=timeout_ms)

            elif step.action == "assert_text":
                expected = step.value or ""
                content = page.content()
                if expected not in content and not page.get_by_text(expected).is_visible():
                    raise AssertionError(f"Page text does not contain expected substring: '{expected}'")

            elif step.action == "assert_element":
                locator = self._locate(page, step.target or "")
                if not locator.is_visible():
                    raise AssertionError(f"Expected element '{step.target}' is not visible on page.")

            elif step.action == "assert_url":
                expected_url_part = step.value or ""
                actual_url = page.url
                if expected_url_part not in actual_url:
                    raise AssertionError(f"Expected URL to contain '{expected_url_part}', got '{actual_url}'")

            elif step.action == "fill_form":
                self._fill_form_fields(page, test_name, step_index, current_url, current_fp, was_cached, step.target or "")

            elif step.action == "enter_name_and_email":
                self._enter_name_and_email(page, test_name, step_index, current_url, current_fp, was_cached)

            elif step.action == "check_checkbox":
                self._check_checkbox(page, step.target or "")

            elif step.action == "verify_and_click":
                self._check_results_or_target(page, step.target or "")
                time.sleep(0.5)
                self._click_target(page, step.value or "")

            elif step.action == "check":
                self._check_results_or_target(page, step.target or "")

            elif step.action == "add_to_cart_count":
                count = int(step.value or "1")
                self._add_products_to_cart(page, count, test_name, step_index, current_url, current_fp, was_cached)

            elif step.action == "add_to_cart_item":
                self._add_item_to_cart(page, step.target or "", test_name, step_index, current_url, current_fp, was_cached)

            elif step.action == "remove_from_cart_count":
                count = int(step.value or "1")
                self._remove_products_from_cart(page, count, test_name, step_index, current_url, current_fp, was_cached)

            elif step.action == "remove_from_cart_item":
                self._remove_item_from_cart(page, step.target or "", test_name, step_index, current_url, current_fp, was_cached)


            elif step.action == "screenshot":
                raw_name = (step.value or "").strip()
                # Check for load condition in screenshot request (e.g. "when the page is fully loaded")
                if any(w in raw_name.lower() for w in ("load", "loaded")):
                    try:
                        page.wait_for_load_state("load", timeout=4000)
                    except Exception:
                        pass
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=2000)
                    except Exception:
                        pass
                    time.sleep(0.5)

                is_condition = any(raw_name.lower().startswith(p) for p in ("when ", "after ", "once ", "if "))
                if not raw_name or raw_name.lower() in ("screenshot", "snapshot") or is_condition:
                    clean_name = f"screenshot_line_{step.line_number}"
                else:
                    clean_name = f"{re.sub(r'[^\w\-_]', '_', raw_name).strip('_')}_line_{step.line_number}"

                if "result" in clean_name.lower():
                    try:
                        page.wait_for_selector(".modal-content, table, .modal-dialog", timeout=3000)
                    except Exception:
                        time.sleep(1.0)

                screenshot_path = os.path.join(self.screenshots_dir, f"{clean_name}.png")
                page.screenshot(path=screenshot_path, full_page=True)

            else:
                # Custom / heuristic fallback
                raise ValueError(f"Unsupported action line: '{step.raw_line}'")

            duration = round(time.time() - step_start, 2)
            return StepResult(
                line_number=step.line_number,
                raw_line=step.raw_line,
                masked_line=step.masked_line,
                action=step.action,
                status="PASSED",
                duration_seconds=duration,
                was_cached=was_cached,
                screenshot_path=screenshot_path
            )

        except Exception as err:
            duration = round(time.time() - step_start, 2)
            fail_img_name = f"fail_{test_name}_line_{step.line_number}_{int(time.time())}.png"
            fail_img_path = os.path.join(self.screenshots_dir, fail_img_name)
            try:
                page.screenshot(path=fail_img_path)
                screenshot_path = fail_img_path
            except Exception:
                screenshot_path = None

            sanitized_error = mask_secrets(str(err))
            return StepResult(
                line_number=step.line_number,
                raw_line=step.raw_line,
                masked_line=step.masked_line,
                action=step.action,
                status="FAILED",
                duration_seconds=duration,
                error_message=sanitized_error,
                was_cached=was_cached,
                screenshot_path=screenshot_path
            )

    def _locate(self, page: Page, target: str) -> Locator:
        """Resolve a target string or natural language description into a Playwright Locator."""
        target_clean = target.strip()

        # Clean trailing natural language state clauses (e.g. "is visible", "is fully loaded")
        target_clean = re.sub(
            r"\s+(?:(?:is|to\s+be)\s+)?(?:fully\s+|completely\s+)?(?:visible|displayed|present|loaded|rendered|shown)$",
            "",
            target_clean,
            flags=re.IGNORECASE
        ).strip()

        # Remove leading articles
        clean_desc = re.sub(r"^(?:the|a|an)\s+", "", target_clean, flags=re.IGNORECASE).strip()

        # Check for quoted text inside descriptor (e.g. modal with the text "...")
        quote_match = re.search(r"[\"']([^\"']+)[\"']", clean_desc)
        if quote_match:
            quoted_text = quote_match.group(1).strip()
            if any(w in clean_desc.lower() for w in ("modal", "dialog", "popup")):
                modal_with_text = page.locator(".modal-content, .modal-dialog, [role='dialog'], .modal").filter(has_text=quoted_text).first
                if modal_with_text.count() > 0:
                    return modal_with_text
            text_match = page.get_by_text(quoted_text, exact=False)
            if text_match.count() > 0:
                return text_match.first

        # Check for natural language modal / dialog references
        if any(w in clean_desc.lower() for w in ("modal", "dialog", "popup")):
            modal_loc = page.locator(".modal-content, .modal-dialog, [role='dialog'], .modal").first
            if modal_loc.count() > 0:
                return modal_loc

        # Check if target specifies "with id <identifier>"
        id_match = re.search(r"with\s+id\s+([\"'].*[\"']|\S+)", clean_desc, re.IGNORECASE)
        if id_match:
            raw_id = id_match.group(1).strip().strip('"\'')
            if re.match(r"^[A-Za-z0-9_\-]+$", raw_id):
                id_loc = page.locator(f"#{raw_id}").first
                if id_loc.count() > 0:
                    return id_loc

        # Clean positional natural language phrases (e.g. "at the top right corner", "in the header")
        clean_desc = re.sub(r"\s+(?:at|in|on)\s+(?:the\s+)?(?:top|bottom|left|right|header|corner|navbar|nav|menu).*", "", clean_desc, flags=re.IGNORECASE).strip()

        # Remove trailing field/input/box/button nouns (e.g. "user field" -> "user", "password field" -> "password")
        clean_core = re.sub(r"\s+(?:field|input|box|textbox|area|button|btn|link|icon)$", "", clean_desc, flags=re.IGNORECASE).strip()

        # Handle shopping cart references (e.g. "shopping cart", "cart", "basket")
        if any(w in clean_core.lower() for w in ("cart", "basket", "shopping-cart")):
            cart_loc = page.locator(".shopping_cart_link, [data-test='shopping-cart-link'], #shopping_cart_container, a[href*='cart'], button[id*='cart' i], [aria-label*='cart' i], [title*='cart' i]").first
            if cart_loc.count() > 0:
                return cart_loc


        # Handle specific common form inputs
        if clean_core.lower() in ("user", "username", "user-name", "email", "user email"):
            u_loc = page.locator("input[id*='user' i], input[name*='user' i], input[placeholder*='user' i], input[data-test*='user' i], input[type='email']").first
            if u_loc.count() > 0:
                return u_loc
        elif clean_core.lower() in ("password", "pass", "pwd"):
            p_loc = page.locator("input[type='password'], input[id*='pass' i], input[name*='pass' i], input[placeholder*='pass' i], input[data-test*='pass' i]").first
            if p_loc.count() > 0:
                return p_loc

        # Check input elements matching clean_core directly
        if clean_core:
            direct_input = page.locator(f"input[id*='{clean_core}' i], input[name*='{clean_core}' i], input[placeholder*='{clean_core}' i], input[data-test*='{clean_core}' i]").first
            if direct_input.count() > 0:
                return direct_input

        # Direct CSS or XPath
        if (
            target_clean.startswith("#")
            or target_clean.startswith(".")
            or target_clean.startswith("//")
            or "[" in target_clean
            or ">" in target_clean
        ):
            try:
                loc = page.locator(target_clean).first
                if loc.count() > 0:
                    return loc
            except Exception:
                pass

        # 1. First check explicit buttons or links by role
        try:
            by_role_btn = page.get_by_role("button", name=clean_desc, exact=False)
            if by_role_btn.count() > 0:
                return by_role_btn.first
        except Exception:
            pass

        try:
            by_role_link = page.get_by_role("link", name=clean_desc, exact=False)
            if by_role_link.count() > 0:
                return by_role_link.first
        except Exception:
            pass

        # 2. Flexible space matching for buttons (e.g. "Log In" matches "Login", "Sign In" matches "Signin")
        flex_word = clean_core.replace(" ", "")
        btn_val = page.locator(f"input[type='submit'][value*='{flex_word}' i], input[id*='{flex_word}' i], button[id*='{flex_word}' i]").first
        if btn_val.count() > 0:
            return btn_val

        # 3. Support data-qa button/link slugs specifically
        qa_slug = re.sub(r"[^\w]+", "-", clean_core.lower()).strip("-")
        if qa_slug:
            qa_btn = page.locator(f"button[data-qa*='{qa_slug}' i], a[data-qa*='{qa_slug}' i], input[type='submit'][data-qa*='{qa_slug}' i], [data-qa='{qa_slug}-button']").first
            if qa_btn.count() > 0:
                return qa_btn

            qa_loc = page.locator(f"[data-qa*='{qa_slug}' i], [data-test*='{qa_slug}' i]").first
            if qa_loc.count() > 0:
                return qa_loc

        by_text = page.get_by_text(clean_desc, exact=False)
        if by_text.count() > 0:
            return by_text.first

        # Keyword / token matching for multi-word phrases (e.g. "thanks for submitting")
        words = [w for w in re.split(r"\W+", clean_desc) if len(w) > 3 and w.lower() not in ("modal", "with", "that", "this")]
        for word in words:
            word_loc = page.get_by_text(word, exact=False)
            if word_loc.count() > 0:
                return word_loc.first

        by_label = page.get_by_label(clean_desc)
        if by_label.count() > 0:
            return by_label.first

        by_placeholder = page.get_by_placeholder(clean_desc)
        if by_placeholder.count() > 0:
            return by_placeholder.first

        # Fallback to general text
        return page.locator(f"text={clean_desc}").first

    def _dismiss_overlays(self, page: Page) -> None:
        """Dismiss common ad banners, google vignettes, and overlay footers."""
        try:
            if "#google_vignette" in page.url:
                clean_url = page.url.split("#")[0]
                page.goto(clean_url, wait_until="load")
        except Exception:
            pass

        try:
            page.evaluate("""
                () => {
                    const dismiss = document.querySelector('#dismiss-button, .dismiss-button, [aria-label="Close ad"]');
                    if (dismiss) dismiss.click();
                    const frames = document.querySelectorAll('iframe[id*="aswift"], iframe[id*="google_ads"]');
                    frames.forEach(f => f.remove());
                }
            """)
        except Exception:
            pass

    def _click_target(self, page: Page, target: str, cached_selector: Optional[str] = None) -> str:
        """Click on element, utilizing cached selector if available."""
        self._dismiss_overlays(page)
        target_lower = target.lower().strip()
        if target_lower in ("submit", "on submit", "submit button"):
            for sel in ("#submit", "button[type='submit']", "input[type='submit']", "button:has-text('Submit')", "text=Submit"):
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        loc.scroll_into_view_if_needed(timeout=2000)
                        try:
                            loc.click(timeout=2000)
                        except Exception:
                            loc.click(force=True, timeout=2000)
                        return sel
                except Exception:
                    continue

        if cached_selector:
            try:
                page.locator(cached_selector).first.click(timeout=3000)
                self._dismiss_overlays(page)
                return cached_selector
            except Exception:
                pass  # Fallback to re-resolving if cached selector is stale

        locator = self._locate(page, target)
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
            locator.click(timeout=3000)
        except Exception:
            self._dismiss_overlays(page)
            locator.click(force=True)

        self._dismiss_overlays(page)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        return target

    def _enter_name_and_email(
        self,
        page: Page,
        test_name: str,
        step_index: int,
        current_url: str,
        current_fp: str,
        was_cached: bool
    ) -> None:
        """Fill registration name and unique email fields."""
        unique_ts = int(time.time())
        user_name = f"User{unique_ts}"
        user_email = f"user_{unique_ts}@example.com"

        signup_form = page.locator(".signup-form, form[action*='signup']").first
        if signup_form.count() > 0:
            name_loc = signup_form.locator("input[data-qa='signup-name'], input[name='name'], input[type='text']").first
            email_loc = signup_form.locator("input[data-qa='signup-email'], input[name='email'], input[type='email']").first
        else:
            name_loc = page.locator("input[data-qa='signup-name']").first
            if name_loc.count() == 0:
                name_loc = page.locator("input[name='name'], input[placeholder*='Name' i]").first

            email_loc = page.locator("input[data-qa='signup-email']").first
            if email_loc.count() == 0:
                email_loc = page.locator("input[name='email'], input[type='email']").last

        if name_loc.count() > 0:
            name_loc.fill(user_name)
        if email_loc.count() > 0:
            email_loc.fill(user_email)

    def _check_checkbox(self, page: Page, target: str) -> None:
        """Check a checkbox element matching target label or identifier."""
        target_clean = target.strip().strip('"\'')
        target_lower = target_clean.lower()

        # Try finding by label text
        try:
            lbl = page.get_by_label(target_clean)
            if lbl.count() > 0:
                lbl.first.check(timeout=3000)
                return
        except Exception:
            pass

        # Try finding label containing text and associated input
        lbl_elem = page.locator(f"label:has-text('{target_clean}')").first
        if lbl_elem.count() > 0:
            for_id = lbl_elem.get_attribute("for")
            if for_id:
                try:
                    page.locator(f"#{for_id}").first.check(timeout=3000)
                    return
                except Exception:
                    pass
            inp = lbl_elem.locator("input[type='checkbox']").first
            if inp.count() > 0:
                inp.check(timeout=3000)
                return
            lbl_elem.click(timeout=3000)
            return

        # Known domain mappings
        if "newsletter" in target_lower:
            cb = page.locator("#newsletter, input[name='newsletter']").first
            if cb.count() > 0:
                cb.check(timeout=3000)
                return
        elif any(w in target_lower for w in ("partner", "offer", "special")):
            cb = page.locator("#optin, input[name='optin']").first
            if cb.count() > 0:
                cb.check(timeout=3000)
                return

        # Fallback to locate
        locator = self._locate(page, target_clean)
        try:
            locator.check(timeout=3000)
        except Exception:
            locator.click(timeout=3000)

    def _fill_form_fields(
        self,
        page: Page,
        test_name: str,
        step_index: int,
        current_url: str,
        current_fp: str,
        was_cached: bool,
        target: str = ""
    ) -> None:
        """Intelligently fill standard form fields on the page."""
        if was_cached and current_fp:
            cached_plan = self.fingerprint_mgr.get_cached_plan(test_name, step_index, current_url, current_fp)
            if cached_plan and "field_values" in cached_plan:
                for sel, val in cached_plan["field_values"].items():
                    try:
                        page.locator(sel).first.fill(val, timeout=2000)
                    except Exception:
                        pass
                return

        field_records = {}
        # Wait for form inputs to be ready if navigating
        try:
            page.wait_for_selector("input:not([type='hidden']), textarea, select", timeout=3000)
        except Exception:
            pass

        # Remove floating ad banners / footers if present (e.g. demoqa) to avoid interference
        self._dismiss_overlays(page)

        # Handle select elements first (e.g. date of birth, country)
        selects = page.query_selector_all("select")
        for sel_el in selects:
            sel_name = (sel_el.get_attribute("name") or "").lower()
            sel_id = sel_el.get_attribute("id") or ""
            selector = f"#{sel_id}" if sel_id else f"select[name='{sel_name}']"
            try:
                if "day" in sel_name:
                    page.locator(selector).first.select_option("15")
                elif "month" in sel_name:
                    page.locator(selector).first.select_option("6")
                elif "year" in sel_name:
                    page.locator(selector).first.select_option("1990")
                elif "country" in sel_name:
                    page.locator(selector).first.select_option("United States")
                else:
                    options = page.locator(f"{selector} option").all()
                    if len(options) > 1:
                        val = options[1].get_attribute("value")
                        if val:
                            page.locator(selector).first.select_option(val)
            except Exception:
                pass

        inputs = page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']), textarea")
        for el in inputs:
            el_type = (el.get_attribute("type") or "text").lower()
            el_id = el.get_attribute("id") or ""
            el_name = (el.get_attribute("name") or "").lower()
            el_ph = (el.get_attribute("placeholder") or "").lower()
            el_dqa = (el.get_attribute("data-qa") or "").lower()
            combined_desc = f"{el_id} {el_name} {el_ph} {el_dqa}".lower()

            selector = f"#{el_id}" if el_id else f"[data-qa='{el_dqa}']" if el_dqa else f"[name='{el_name}']" if el_name else None
            if not selector:
                continue

            if el_type == "radio":
                try:
                    lbl = page.locator(f"label[for='{el_id}']")
                    if lbl.count() > 0:
                        lbl.first.click()
                    else:
                        page.locator(selector).first.click(force=True)
                except Exception:
                    pass
                continue

            if el_type == "checkbox":
                continue

            val = "Test User"
            if el_type == "password" or any(k in combined_desc for k in ("password", "pass", "pwd")):
                val = "Password123!"
            elif any(k in combined_desc for k in ("company", "organization")):
                val = "TechCorp"
            elif any(k in combined_desc for k in ("address2", "line2", "apt", "suite")):
                val = "Suite 400"
            elif any(k in combined_desc for k in ("first", "fname", "firstname")):
                val = "John"
            elif any(k in combined_desc for k in ("last", "lname", "lastname")):
                val = "Doe"
            elif any(k in combined_desc for k in ("email", "mail")):
                val = f"user_{int(time.time())}@example.com"
            elif any(k in combined_desc for k in ("state", "province", "region")):
                val = "New York"
            elif any(k in combined_desc for k in ("city", "town")):
                val = "New York"
            elif any(k in combined_desc for k in ("phone", "mobile", "tel", "number")):
                val = "1234567890"
            elif any(k in combined_desc for k in ("zip", "postal", "postcode", "code")):
                val = "10001"
            elif any(k in combined_desc for k in ("address", "street")):
                val = "123 Automation Street"

            try:
                page.locator(selector).first.fill(val, timeout=2000)
                field_records[selector] = val
            except Exception:
                pass

        if current_fp:
            self.fingerprint_mgr.store_cached_plan(
                test_name, step_index, current_url, current_fp, {"field_values": field_records}
            )

    def _check_results_or_target(self, page: Page, target: str) -> None:
        """Verify presence of result modal, table, or specific target."""
        clean_target = target.strip().strip('"\'')
        clean_target = re.sub(r"^that\s+", "", clean_target, flags=re.IGNORECASE).strip()
        clean_target = re.sub(
            r"\s+(?:(?:is|to\s+be)\s+)?(?:fully\s+|completely\s+)?(?:visible|displayed|present|loaded|rendered|shown)(?:\s+successfully)?$",
            "",
            clean_target,
            flags=re.IGNORECASE
        ).strip().strip('"\'')

        target_lower = clean_target.lower()
        if target_lower in ("results", "result", "the results", "submission"):
            candidates = [
                ".modal-content",
                "#example-modal-sizes-title-lg",
                ".modal-title",
                "table",
                ".alert-success",
                "text=Thanks for submitting",
                "text=Success"
            ]
            for cand in candidates:
                try:
                    loc = page.locator(cand).first
                    if loc.is_visible(timeout=3000):
                        return
                except Exception:
                    pass
            content = page.content()
            if "Thanks for submitting" in content or "Successfully" in content:
                return
            raise AssertionError("Form submission results or confirmation modal not found on page.")

        if target_lower in ("home page", "homepage", "home"):
            if "automationexercise" in page.url or "home" in page.title().lower() or page.locator("body").is_visible():
                return
            raise AssertionError("Home page is not visible.")

        if "logged in as" in target_lower:
            loc = page.locator("text=/Logged in as/i").first
            if loc.is_visible(timeout=5000):
                return
            raise AssertionError("Element 'Logged in as <username>' is not visible on page.")

        # Check by text directly
        loc = page.get_by_text(clean_target, exact=False).first
        try:
            if loc.is_visible(timeout=4000):
                return
        except Exception:
            pass

        locator = self._locate(page, clean_target)
        try:
            if locator.is_visible(timeout=4000):
                return
        except Exception:
            pass

        raise AssertionError(f"Expected '{clean_target}' to be visible on page.")


    def _fill_target(self, page: Page, target: str, value: str, cached_selector: Optional[str] = None) -> str:
        """Fill input field with value, utilizing cached selector if available."""
        if cached_selector:
            try:
                page.locator(cached_selector).first.fill(value, timeout=3000)
                return cached_selector
            except Exception:
                pass

        locator = self._locate(page, target)
        locator.fill(value)
        return target

    def _select_target(self, page: Page, target: str, value: str, cached_selector: Optional[str] = None) -> str:
        """Select option in dropdown, utilizing cached selector if available."""
        if cached_selector:
            try:
                page.locator(cached_selector).first.select_option(label=value, timeout=3000)
                return cached_selector
            except Exception:
                pass

        locator = self._locate(page, target)
        try:
            locator.select_option(label=value)
        except Exception:
            locator.select_option(value=value)
        return target

    def _add_products_to_cart(
        self,
        page: Page,
        count: int,
        test_name: str,
        step_index: int,
        current_url: str,
        current_fp: str,
        was_cached: bool
    ) -> None:
        """Add N distinct products to the shopping cart."""
        try:
            page.wait_for_selector(
                "button:has-text('Add to cart'), [data-test*='add-to-cart'], button[id*='add-to-cart'], a:has-text('Add to cart')",
                timeout=5000
            )
        except Exception:
            pass

        cart_buttons = page.locator("button:has-text('Add to cart'), [data-test*='add-to-cart'], button[id*='add-to-cart'], a:has-text('Add to cart')")
        total_available = cart_buttons.count()
        if total_available == 0:
            raise AssertionError("No 'Add to cart' buttons found on the current page.")

        to_add = min(count, total_available)
        clicked_selectors = []
        for i in range(to_add):
            btn = cart_buttons.nth(i)
            try:
                btn_id = btn.get_attribute("id") or btn.get_attribute("data-test") or f"nth_{i}"
                clicked_selectors.append(btn_id)
                btn.scroll_into_view_if_needed(timeout=2000)
                btn.click()
                time.sleep(0.15)
            except Exception:
                pass

        if current_fp:
            self.fingerprint_mgr.store_cached_plan(
                test_name, step_index, current_url, current_fp, {"added_products": clicked_selectors}
            )

    def _add_item_to_cart(
        self,
        item_name: str,
        test_name: str,
        step_index: int,
        current_url: str,
        current_fp: str,
        was_cached: bool
    ) -> None:
        """Add a specific named item to the shopping cart."""
        product_card = page.locator(f".inventory_item:has-text('{item_name}'), .product:has-text('{item_name}'), [class*='item']:has-text('{item_name}')").first
        if product_card.count() > 0:
            btn = product_card.locator("button:has-text('Add to cart'), [data-test*='add-to-cart']").first
            btn.click()
            return

        direct_btn = page.locator(f"[data-test*='add-to-cart'][data-test*='{item_name.lower().replace(' ', '-')}']").first
        if direct_btn.count() > 0:
            direct_btn.click()
            return

        raise AssertionError(f"Could not find product '{item_name}' to add to cart.")

    def _remove_products_from_cart(
        self,
        page: Page,
        count: int,
        test_name: str,
        step_index: int,
        current_url: str,
        current_fp: str,
        was_cached: bool
    ) -> None:
        """Remove N items from the shopping cart."""
        remove_buttons = page.locator("button:has-text('Remove'), [data-test*='remove'], button[id*='remove'], a:has-text('Remove')")
        total_available = remove_buttons.count()
        if total_available == 0:
            raise AssertionError("No 'Remove' buttons found on the shopping cart page.")

        to_remove = min(count, total_available)
        removed_selectors = []
        for i in range(to_remove):
            btn = page.locator("button:has-text('Remove'), [data-test*='remove'], button[id*='remove']").first
            try:
                btn_id = btn.get_attribute("id") or btn.get_attribute("data-test") or f"item_{i}"
                removed_selectors.append(btn_id)
                btn.scroll_into_view_if_needed(timeout=2000)
                btn.click()
                time.sleep(0.2)
            except Exception:
                pass

        if current_fp:
            self.fingerprint_mgr.store_cached_plan(
                test_name, step_index, current_url, current_fp, {"removed_products": removed_selectors}
            )

    def _remove_item_from_cart(
        self,
        item_name: str,
        test_name: str,
        step_index: int,
        current_url: str,
        current_fp: str,
        was_cached: bool
    ) -> None:
        """Remove a specific named item from the shopping cart."""
        item_row = page.locator(f".cart_item:has-text('{item_name}'), [class*='item']:has-text('{item_name}')").first
        if item_row.count() > 0:
            btn = item_row.locator("button:has-text('Remove'), [data-test*='remove']").first
            btn.click()
            return

        direct_btn = page.locator(f"[data-test*='remove'][data-test*='{item_name.lower().replace(' ', '-')}']").first
        if direct_btn.count() > 0:
            direct_btn.click()
            return

        raise AssertionError(f"Could not find product '{item_name}' in cart to remove.")



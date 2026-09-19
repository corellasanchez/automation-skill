"""Test file parser module.

Parses plain text (.txt) test files containing line-by-line test actions
into structured step definitions with environment variable expansion and secret masking.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import List, Optional

from src.env_loader import mask_secrets


@dataclass
class ActionStep:
    """Represents a single parsed test action."""
    line_number: int
    raw_line: str
    masked_line: str
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    wait_seconds: Optional[float] = None


class TestFileParser:
    """Parses text test files into actionable steps with credential expansion."""

    @classmethod
    def interpolate_env(cls, text: str) -> str:
        """Replace ${VAR_NAME} or $VAR_NAME with its environment variable value."""
        if not text:
            return text

        def _repl(match: re.Match) -> str:
            var_name = match.group(1) or match.group(2)
            val = os.environ.get(var_name)
            return val if val is not None else match.group(0)

        return re.sub(r"\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)", _repl, text)

    @classmethod
    def parse_file(cls, filepath: str) -> List[ActionStep]:
        """Read and parse a .txt test file."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Test file not found: {filepath}")

        steps: List[ActionStep] = []
        with open(filepath, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                clean_line = line.strip()
                if not clean_line or clean_line.startswith("#") or clean_line.startswith("//"):
                    continue

                step = cls.parse_line(clean_line, line_number=idx)
                if step:
                    steps.append(step)

        return steps

    @classmethod
    def parse_line(cls, line: str, line_number: int) -> Optional[ActionStep]:
        """Parse a single text line into an ActionStep with env expansion."""
        raw_original = line
        # First generate a masked representation of the input line
        masked_line = mask_secrets(raw_original)

        # Interpolate variables for actual execution
        expanded_line = cls.interpolate_env(line)

        # 1. Navigate / Goto / Open
        nav_match = re.match(r"^(?:navigate|goto|open)(?:\s+to)?(?:\s+(?:url|the\s+url))?\s+(.+)$", expanded_line, re.IGNORECASE)
        if nav_match:
            url = nav_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="navigate",
                target=url
            )

        # 1.2 Enter name and email credentials (e.g. Enter name and email address)
        enter_creds_match = re.match(
            r"^(?:enter|fill)(?:\s+in)?\s+(?:the\s+)?name\s+and\s+email(?:\s+address)?.*$",
            expanded_line,
            re.IGNORECASE
        )
        if enter_creds_match:
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="enter_name_and_email"
            )

        # 1.3 Select checkbox (e.g. Select checkbox 'Sign up for our newsletter!')
        checkbox_match = re.match(
            r"^(?:select|check)(?:\s+the)?\s+checkbox\s+([\"'].*[\"']|\S.*)$",
            expanded_line,
            re.IGNORECASE
        )
        if checkbox_match:
            target = checkbox_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="check_checkbox",
                target=target
            )

        # 1.4 Compound Verify and Click (e.g. Verify that 'ACCOUNT DELETED!' is visible and click 'Continue' button)
        comp_match = re.match(
            r"^(?:verify|assert|check)\s+(?:that\s+)?(.+?)\s+(?:is\s+visible\s+)?and\s+click(?:\s+on)?(?:\s+(?:the|a)\s+)?\s*(.+?)(?:\s+button)?$",
            expanded_line,
            re.IGNORECASE
        )
        if comp_match:
            chk_target = comp_match.group(1).strip().strip('"\'')
            clk_target = comp_match.group(2).strip().strip('"\'')
            clk_target = re.sub(r"\s+button$", "", clk_target, flags=re.IGNORECASE).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="verify_and_click",
                target=chk_target,
                value=clk_target
            )

        # 1.5 Fill whole form / information (e.g. fill practice form, fill details: ...)
        fill_form_match = re.match(
            r"^(?:fill|complete)\s+(?:the\s+)?(.*?\b(?:form|information|info|details:?|checkout)\b.*)$",
            expanded_line,
            re.IGNORECASE
        )
        if fill_form_match and "with" not in expanded_line.lower():
            target = fill_form_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="fill_form",
                target=target
            )

        # 2. Fill / Type specific field (e.g. fill "#username" with "user")
        fill_match = re.match(r"^(?:fill|type)\s+(.+?)\s+(?:with\s+)?([\"'].*[\"']|\S+)$", expanded_line, re.IGNORECASE)
        if fill_match:
            target = fill_match.group(1).strip().strip('"\'')
            value = fill_match.group(2).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="fill",
                target=target,
                value=value
            )

        # 3. Click
        click_match = re.match(r"^(?:click)(?:\s+on)?(?:\s+(?:the|a)\s+)?(?:\s+button)?\s+(.+?)(?:\s+button)?$", expanded_line, re.IGNORECASE)
        if click_match:
            target = click_match.group(1).strip().strip('"\'')
            target = re.sub(r"\s+button$", "", target, flags=re.IGNORECASE).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="click",
                target=target
            )

        # 4. Press key (e.g. press Enter)
        press_match = re.match(r"^press\s+(\w+)$", expanded_line, re.IGNORECASE)
        if press_match:
            key = press_match.group(1).strip()
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="press",
                value=key
            )

        # 5. Select dropdown option (select "#country" "Canada")
        select_match = re.match(r"^select\s+(.+?)\s+(?:option\s+)?([\"'].*[\"']|\S+)$", expanded_line, re.IGNORECASE)
        if select_match:
            target = select_match.group(1).strip().strip('"\'')
            value = select_match.group(2).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="select",
                target=target,
                value=value
            )

        # 5.5 Add to cart actions (e.g. add 3 diferent products to the cart, add "Backpack" to cart)
        add_cart_count_match = re.match(
            r"^add\s+([0-9]+)\s+(?:diff?er[ea]nt\s+)?(?:products?|items?)\s+to\s+(?:the\s+)?cart.*$",
            expanded_line,
            re.IGNORECASE
        )
        if add_cart_count_match:
            count = int(add_cart_count_match.group(1))
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="add_to_cart_count",
                value=str(count)
            )

        add_cart_item_match = re.match(
            r"^add\s+(.+?)\s+to\s+(?:the\s+)?cart.*$",
            expanded_line,
            re.IGNORECASE
        )
        if add_cart_item_match:
            item_name = add_cart_item_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="add_to_cart_item",
                target=item_name
            )

        # 5.6 Remove from cart actions (e.g. remove one item from the shopping cart, remove 2 products from cart)
        remove_cart_count_match = re.match(
            r"^remove\s+(?:([0-9]+)|one|an?)\s+(?:diff?er[ea]nt\s+)?(?:products?|items?)\s+from\s+(?:the\s+)?(?:shopping\s+)?cart.*$",
            expanded_line,
            re.IGNORECASE
        )
        if remove_cart_count_match:
            num_str = remove_cart_count_match.group(1)
            count = int(num_str) if num_str else 1
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="remove_from_cart_count",
                value=str(count)
            )

        remove_cart_item_match = re.match(
            r"^remove\s+(.+?)\s+from\s+(?:the\s+)?(?:shopping\s+)?cart.*$",
            expanded_line,
            re.IGNORECASE
        )
        if remove_cart_item_match:
            item_name = remove_cart_item_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="remove_from_cart_item",
                target=item_name
            )

        # 6. Wait (wait 2 or wait for "#element")
        wait_sec_match = re.match(r"^wait\s+([0-9]+(?:\.[0-9]+)?)(?:\s*s(?:ec(?:onds)?)?)?$", expanded_line, re.IGNORECASE)
        if wait_sec_match:
            seconds = float(wait_sec_match.group(1))
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="wait",
                wait_seconds=seconds
            )

        # Wait for page load (e.g. wait until the next page is loaded, wait for page load)
        wait_page_match = re.match(
            r"^wait\s+(?:until|for)\s+(?:the\s+)?(?:next\s+)?page\s+(?:is\s+)?loaded?.*$",
            expanded_line,
            re.IGNORECASE
        )
        if wait_page_match:
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="wait_page_load"
            )

        # Wait with timeout duration until target (e.g. wait 2 seconds until ..., wait 2 secconds for ...)
        wait_timeout_target_match = re.match(
            r"^wait\s+([0-9]+(?:\.[0-9]+)?)\s*(?:s(?:ec(?:c?onds?)?)?)?\s+(?:until|for)\s+(.+)$",
            expanded_line,
            re.IGNORECASE
        )
        if wait_timeout_target_match:
            seconds = float(wait_timeout_target_match.group(1))
            target = wait_timeout_target_match.group(2).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="wait_for",
                target=target,
                wait_seconds=seconds
            )

        wait_elem_match = re.match(r"^wait\s+(?:for|until)\s+(.+)$", expanded_line, re.IGNORECASE)
        if wait_elem_match:
            target = wait_elem_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="wait_for",
                target=target
            )

        # 7. Assertions
        assert_text_match = re.match(r"^assert(?:\s+page)?\s+(?:contains|text)\s+([\"'].*[\"']|\S.*)$", expanded_line, re.IGNORECASE)
        if assert_text_match:
            val = assert_text_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="assert_text",
                value=val
            )

        assert_elem_match = re.match(r"^assert\s+(?:element|visible)\s+(.+)$", expanded_line, re.IGNORECASE)
        if assert_elem_match:
            target = assert_elem_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="assert_element",
                target=target
            )

        assert_url_match = re.match(r"^assert\s+url\s+([\"'].*[\"']|\S+)$", expanded_line, re.IGNORECASE)
        if assert_url_match:
            url_part = assert_url_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="assert_url",
                value=url_part
            )

        # 8. Screenshot (supports: screenshot, take a screenshot of ..., capture screenshot)
        snap_match = re.match(
            r"^(?:(?:take\s+(?:a\s+)?)?(?:screenshot|snapshot)|capture\s+(?:a\s+)?screenshot)(?:\s+(?:of\s+)?(?:the\s+)?([\"'].*[\"']|\S.*))?$",
            expanded_line,
            re.IGNORECASE
        )
        if snap_match:
            name = (snap_match.group(1) or "screenshot").strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="screenshot",
                value=name
            )

        # 9. Check / Verify (e.g. check results, verify dashboard, verify 'New User Signup!' is visible)
        check_match = re.match(r"^(?:check|verify)\s+(?:that\s+)?(.+?)(?:\s+(?:is|to\s+be)\s+visible.*)?$", expanded_line, re.IGNORECASE)
        if check_match:
            target = check_match.group(1).strip().strip('"\'')
            return ActionStep(
                line_number=line_number,
                raw_line=raw_original,
                masked_line=masked_line,
                action="check",
                target=target
            )

        # Generic fallback
        return ActionStep(
            line_number=line_number,
            raw_line=raw_original,
            masked_line=masked_line,
            action="custom",
            target=expanded_line
        )

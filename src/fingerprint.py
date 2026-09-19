"""Page DOM fingerprinting and cache management module.

Computes a structural DOM hash for web pages to detect changes and
save LLM/planning tokens by caching resolved test execution steps.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Optional
from playwright.sync_api import Page


class FingerprintManager:
    """Manages structural DOM fingerprints and step caches for web pages."""

    def __init__(self, cache_dir: str = ".test_cache") -> None:
        """Initialize fingerprint manager with a cache directory."""
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(self.cache_dir, "fingerprints.json")
        self._cache: Dict[str, Any] = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        """Load fingerprint cache from JSON file."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_cache(self) -> None:
        """Save fingerprint cache to JSON file."""
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2, ensure_ascii=False)

    def extract_fingerprint(self, page: Page) -> str:
        """Extract a deterministic structural fingerprint of the active page.

        Extracts key interactive elements (buttons, inputs, links, headings,
        forms, ARIA roles, data-testids), stripping volatile dynamic nonces
        and timestamps.
        """
        js_extract_script = """
        () => {
            const elements = Array.from(document.querySelectorAll(
                'button, input, select, textarea, a, form, [role], [data-testid], h1, h2, h3, header, nav, main'
            ));
            
            const sanitize = (val) => {
                if (!val) return '';
                // Remove dynamic uuid, timestamp patterns, or large numeric chunks
                return String(val).trim()
                    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '<uuid>')
                    .replace(/\\b\\d{10,13}\\b/g, '<ts>');
            };

            const signatures = elements.map(el => {
                const tag = el.tagName.toLowerCase();
                const type = el.getAttribute('type') || '';
                const id = sanitize(el.id);
                const name = el.getAttribute('name') || '';
                const role = el.getAttribute('role') || '';
                const testId = el.getAttribute('data-testid') || '';
                const ariaLabel = sanitize(el.getAttribute('aria-label') || '');
                const text = sanitize((el.innerText || el.textContent || '').slice(0, 50));
                
                return `${tag}|${type}|${id}|${name}|${role}|${testId}|${ariaLabel}|${text}`;
            });

            signatures.sort();
            return signatures.join('\\n');
        }
        """
        raw_structure = page.evaluate(js_extract_script)
        hasher = hashlib.sha256()
        hasher.update(raw_structure.encode("utf-8"))
        return hasher.hexdigest()

    def get_cached_plan(self, test_name: str, step_index: int, page_url: str, current_fingerprint: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached step execution plan if page fingerprint matches."""
        key = f"{test_name}::{step_index}::{self._normalize_url(page_url)}"
        entry = self._cache.get(key)
        if entry and entry.get("fingerprint") == current_fingerprint:
            return entry.get("resolved_action")
        return None

    def store_cached_plan(
        self,
        test_name: str,
        step_index: int,
        page_url: str,
        fingerprint: str,
        resolved_action: Dict[str, Any]
    ) -> None:
        """Store resolved step action plan indexed by page fingerprint."""
        key = f"{test_name}::{step_index}::{self._normalize_url(page_url)}"
        self._cache[key] = {
            "fingerprint": fingerprint,
            "url": page_url,
            "resolved_action": resolved_action
        }
        self.save_cache()

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL by stripping dynamic query parameters or session IDs."""
        clean = re.sub(r"[?&](token|session_id|ts|_)=\\w+", "", url)
        return clean.rstrip("/")

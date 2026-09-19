"""Environment variable loader and secret masking utility.

Loads credentials from .env files and ensures secrets are masked
in logs, terminal outputs, and reports.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Set

# Cached set of known sensitive values to mask
_KNOWN_SECRETS: Set[str] = set()


def load_dotenv(filepath: str = ".env") -> Dict[str, str]:
    """Parse a .env file and load variables into os.environ.

    Also tracks sensitive keys to mask them in test reports.
    """
    loaded_vars: Dict[str, str] = {}
    if not os.path.exists(filepath):
        return loaded_vars

    sensitive_patterns = re.compile(r"(pass|secret|key|token|auth|credential)", re.IGNORECASE)

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            if "=" in clean:
                key, val = clean.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"\'')

                if key not in os.environ:
                    os.environ[key] = val
                loaded_vars[key] = val

                if sensitive_patterns.search(key) and len(val) >= 3:
                    _KNOWN_SECRETS.add(val)

    return loaded_vars


def get_known_secrets() -> Set[str]:
    """Return all discovered sensitive secret values."""
    sensitive_patterns = re.compile(r"(pass|secret|key|token|auth|credential)", re.IGNORECASE)
    for k, v in os.environ.items():
        if sensitive_patterns.search(k) and len(v) >= 3:
            _KNOWN_SECRETS.add(v)
    return _KNOWN_SECRETS


def mask_secrets(text: str) -> str:
    """Replace occurrences of sensitive values with '********'."""
    if not text:
        return text

    secrets = get_known_secrets()
    masked = text
    for secret in sorted(secrets, key=len, reverse=True):
        if secret in masked:
            masked = masked.replace(secret, "********")

    # Also mask inline pattern: ${VAR_WITH_SECRET} if it matches password/secret
    masked = re.sub(
        r"\$\{(?:[A-Za-z0-9_]*(?:PASS|SECRET|TOKEN|KEY|CREDENTIAL)[A-Za-z0-9_]*)\}",
        "********",
        masked,
        flags=re.IGNORECASE
    )

    return masked

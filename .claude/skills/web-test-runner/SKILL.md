---
name: web-test-runner
description: >-
  Executes line-by-line web automation tests from the test/ folder, uses DOM
  fingerprinting to optimize token usage and avoid redundant re-planning,
  supports .env credential interpolation with automatic secret masking, and
  generates a comprehensive PDF execution report with failure screenshots.
---

# Web Test Runner Skill

Use this skill whenever the user asks to:
- Run tests (`run tests`, `run test`, `execute tests`)
- Run specific test groups or test files in the `test/` directory
- Check web application behavior and verify functionality
- Use credentials and environment variables in tests securely
- Review test execution reports or analyze test failures

## Directory Structure
The repository organizes tests inside the `test/` folder, with optional subfolders representing test groups or suites:
```
test/
  smoke/
    login.txt
    checkout.txt
  auth/
    credentials_demo.txt
  navigation/
    header_links.txt
```

Each `.txt` file represents a test scenario where each non-empty, non-comment line is an action.

## Credentials & Environment Variables
Credentials and environment variables are loaded automatically from `.env` (git-ignored for security).
Reference variables in `.txt` test files using `${VARIABLE_NAME}` syntax:
```txt
navigate https://app.example.com/login
fill "#email" with "${TEST_USER_EMAIL}"
fill "#password" with "${TEST_USER_PASSWORD}"
click "Sign In"
```
**Automatic Masking**: Any sensitive values (e.g. passwords, API keys, tokens) are automatically masked as `********` in the terminal output, HTML, and PDF reports.

## Action Syntax in `.txt` Files
- `navigate <url>`: Opens a web page (e.g., `navigate https://example.com`)
- `click <selector or text>`: Clicks an element, button, link, or label (e.g., `click "Learn more"`, `click #submit-btn`)
- `fill <target> with "<text>"` or `type <target> "<text>"`: Types text into an input field (e.g., `fill "#username" with "${TEST_USER}"`)
- `select <target> "<value>"`: Selects a dropdown option
- `press <key>`: Presses a keyboard key (e.g., `press Enter`)
- `wait <seconds>`: Pauses execution for the given duration (e.g., `wait 2`)
- `wait for <selector or text>`: Waits until an element becomes visible
- `assert text "<content>"`: Verifies that the page contains the expected text
- `assert element <selector or text>`: Verifies that the target element is visible
- `assert url "<url_part>"`: Verifies that the current URL contains the given substring
- `screenshot "<name>"`: Captures a named screenshot

Lines starting with `#` or `//` are comments and will be ignored.

## How to Run Tests
When the user asks to "run tests" or test the web tool, execute:
```bash
python run_tests.py
```
Or for a specific suite:
```bash
python run_tests.py --dir test/auth
```

## Token Optimization & Page Fingerprinting
The test runner calculates a structural DOM fingerprint (SHA-256) of each visited page:
- **Fingerprint Match (Page Unchanged)**: The runner uses previously cached selector mappings from `.test_cache/fingerprints.json`. Zero LLM tokens are consumed.
- **Fingerprint Change (Page Modified)**: The runner detects the layout change, re-resolves the interactive elements, and updates the cache.

## Execution Reports
Every test run generates:
1. `reports/latest_report.pdf` (and timestamped `reports/test_report_<timestamp>.pdf`) containing:
   - Total tests, passed, failed, and execution timings
   - Detailed step-by-step breakdown (with credentials masked)
   - Embedded screenshots for any step failures
2. `reports/latest_report.html` for quick browser viewing.

Always provide the user with the summary and a clickable link to `reports/latest_report.pdf` after running tests.

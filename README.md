# AI-Driven Web Test Automation Runner

An intelligent, token-efficient web automation and testing engine compatible with **Google Antigravity**, **Claude Code**, and standalone Python workflows.

The engine parses plain-English, line-by-line test action files (`.txt`), executes them via headless Playwright, leverages **DOM fingerprinting** to cache execution plans without redundant LLM calls, safely handles credentials with automatic masking, and produces high-resolution **PDF** and **HTML** test execution reports.

---

## Key Features

- **Natural Language Test Actions**: Write declarative, line-by-line test steps in simple `.txt` files without writing boilerplate automation code.
- **DOM Fingerprint Caching**: Calculates structural hashes of page states to cache resolved selectors and plans. Subsequent test runs reuse cached plans instantaneously, avoiding redundant LLM queries and lowering token costs.
- **Safe Credential Interpolation & Masking**: Reads credentials from `.env` via `${VARIABLE_NAME}` syntax and automatically masks sensitive values (`********`) across all logs, console outputs, HTML reports, and failure dumps.
- **Continuous High-Fidelity PDF & HTML Reports**: Synthesizes standalone, styled HTML reports and converts full-page web previews directly into PDF (`reports/latest_report.pdf`), avoiding page-break splitting bugs and maintaining 100% layout fidelity.
- **Checkpoint & Failure Screenshots**: Automatically captures full-page or element screenshots upon request (`take a screenshot`) and immediately on test failure with stack traces.
- **Multi-Agent Skill Architecture**: Includes ready-to-use agent definitions in `.agents/` and `.claude/` for pair-programming assistants.

---

## Project Structure

```
├── .agents/               # Antigravity agent skills and project rules
├── .claude/               # Claude Code skill configurations
├── reports/               # Generated PDF, HTML reports, and screenshots (gitignored)
│   ├── latest_report.pdf  # Most recent PDF execution report
│   ├── latest_report.html # Most recent responsive HTML report
│   ├── report_preview.png # High-resolution continuous preview
│   └── screenshots/       # Checkpoints and failure captures
├── src/
│   ├── __init__.py
│   ├── env_loader.py      # .env loading and secret masking engine
│   ├── executor.py        # Playwright test execution engine with resilient locators
│   ├── fingerprint.py     # DOM fingerprinting and persistent plan cache
│   ├── parser.py          # Line-by-line action parser and regex matcher
│   └── reporter.py        # HTML & direct image-to-PDF report generator
├── test/                  # Test suite folder (.txt test files)
│   ├── happy path/
│   │   └── shopping card test.txt
│   └── signup.txt
├── .env.example           # Template for environment credentials
├── .gitignore             # Git exclusions (.env, reports, caches, scratch)
├── AGENTS.md              # Project rules for Antigravity agents
├── CLAUDE.md              # Project guidelines for Claude Code
├── GEMINI.md              # Project rules for Gemini agents
├── requirements.txt       # Python dependencies
├── run_tests.py           # Main CLI entrypoint
├── run-tests.bat          # Windows batch runner shortcut
└── run-tests.ps1          # PowerShell runner shortcut
```

---

## Installation & Setup

### 1. Prerequisites
- **Python**: Version 3.9 or higher.
- **Git**: Installed and configured.

### 2. Install Dependencies
Clone the repository and install required packages:
```bash
pip install -r requirements.txt
```

Install Playwright Chromium browser binaries:
```bash
playwright install chromium
```

### 3. Configure Environment Variables
Copy the sample environment file to `.env`:
```bash
copy .env.example .env
```
Edit `.env` with your testing credentials:
```env
TEST_USER=standard_user
TEST_USER_PASSWORD=secret_sauce
```

---

## Running Tests

### Execute All Tests
Run all `.txt` test files located under `test/`:
```bash
python run_tests.py
```
Or using the PowerShell helper:
```powershell
.\run-tests.ps1
```

### Run a Specific Test Suite / Directory
Filter execution to a specific subdirectory:
```bash
python run_tests.py --dir "test/happy path"
```

### Run in Headed (Visible) Mode
To watch the browser actions in real time:
```bash
python run_tests.py --headed
```

---

## Test File Syntax Guide

Tests are written in plain English, with one instruction per line in `.txt` files under `test/`. Comments starting with `#` or `//` and blank lines are ignored.

| Action | Example Syntax | Description |
| :--- | :--- | :--- |
| **Navigation** | `navigate https://www.saucedemo.com/`<br>`Navigate to url 'http://automationexercise.com'` | Navigates the browser to the specified URL. |
| **Fill / Input** | `fill the user field with "${TEST_USER}"`<br>`fill "#email" with "test@example.com"` | Types value into input, resolving environment variables and masking secrets. |
| **Fill Form** | `fill the personal information`<br>`Fill details: Title, Name, Email, Password, Date of birth` | Auto-detects and populates multi-field forms and dropdowns intelligently. |
| **Click** | `click "Log In"`<br>`Click on 'Signup / Login' button`<br>`click on the shopping cart at the top right corner` | Clicks buttons, links, or elements with natural position matching and ad dismissal. |
| **Checkbox** | `Select checkbox 'Sign up for our newsletter!'` | Checks target checkbox by label text or identifier. |
| **Cart Actions** | `add 3 diferent products to the cart`<br>`remove one item from the shopping cart` | Performs multi-item e-commerce additions and removals automatically. |
| **Screenshots** | `take a screenshot`<br>`capture a screenshot of the cart` | Saves a full-page screenshot checkpoint embedded in the execution report. |
| **Verification** | `Verify that home page is visible successfully`<br>`Verify 'New User Signup!' is visible`<br>`assert page contains "Thank you for your order!"` | Asserts visibility of elements, headers, modals, or text content. |
| **Compound Steps** | `Verify that 'ACCOUNT DELETED!' is visible and click 'Continue' button` | Combines verification with immediate subsequent action. |
| **Wait** | `wait 3 seconds`<br>`wait for "#checkout-modal"` | Explicit sleep or element visibility wait. |

---

## Reports & Artifacts

After every test execution, reports are saved to `reports/`:
- **`reports/latest_report.pdf`**: Continuous, high-fidelity PDF report suitable for sharing and review.
- **`reports/latest_report.html`**: Interactive responsive web report with embedded base64 screenshots and status badges.
- **`reports/report_preview.png`**: High-resolution PNG preview of the full execution results.
- **`reports/screenshots/`**: Individual screenshot checkpoints and failure dumps.

---

## License

MIT License. See repository details for more information.

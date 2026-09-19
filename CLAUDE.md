# Project Guidelines for Claude

## Language & Coding Standards
- **Code & Comments**: All code, variable/function/class names, docstrings, and in-code comments must be written strictly in **English**.
- **User Interaction**: Chat responses may be in Spanish (or the language preferred by the user), but any source code, configuration files, and comments generated or edited must always be in **English**.

## Running Tests
When the user asks to "run tests" or execute web tests:
1. Run the test suite:
   ```bash
   python run_tests.py
   ```
   Or for a specific suite:
   ```bash
   python run_tests.py --dir test/<subfolder>
   ```
2. The tests will execute headlessly, use DOM fingerprinting to avoid redundant planning tokens, and output a PDF execution report to `reports/latest_report.pdf`.
3. Provide the user with a concise summary of results and a link to the generated PDF report.

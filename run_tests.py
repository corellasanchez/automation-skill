"""Main CLI entrypoint for running web automation tests.

Discovers .txt test files in test/ directory and its subfolders,
executes tests using Playwright with DOM fingerprint caching,
and produces a PDF execution report.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.env_loader import load_dotenv
from src.executor import TestResult, WebTestExecutor
from src.parser import TestFileParser
from src.reporter import ReportGenerator

# Load credentials from .env if present
load_dotenv()


def discover_test_files(base_dir: str = "test") -> List[str]:
    """Recursively discover all .txt test files under base_dir."""
    test_files: List[str] = []
    if not os.path.exists(base_dir):
        return test_files

    for root, _, files in os.walk(base_dir):
        for f in sorted(files):
            if f.endswith(".txt"):
                test_files.append(os.path.join(root, f))
    return test_files


def run_all(test_dir: str = "test", headless: bool = True) -> int:
    """Execute all discovered tests and generate the report."""
    print("=" * 65)
    print(">> WEB AUTOMATION TEST RUNNER")
    print(f">> Scanning directory: {test_dir}")
    print("=" * 65)

    test_files = discover_test_files(test_dir)
    if not test_files:
        print(f"[!] No .txt test files found in '{test_dir}'.")
        print("Create test files under test/ (e.g. test/smoke/login.txt).")
        return 0

    print(f"Found {len(test_files)} test file(s) to execute.\n")

    executor = WebTestExecutor(headless=headless)
    reporter = ReportGenerator()
    results: List[TestResult] = []

    for idx, filepath in enumerate(test_files, start=1):
        print(f"[{idx}/{len(test_files)}] Running: {filepath}")
        try:
            steps = TestFileParser.parse_file(filepath)
            if not steps:
                print("  -> [!] File has no executable steps. Skipping.")
                continue

            result = executor.run_test(filepath, steps)
            results.append(result)

            status_symbol = "[PASS]" if result.status == "PASSED" else "[FAIL]"
            print(f"  -> {status_symbol} ({result.duration_seconds}s)")
            if result.error_message:
                print(f"     Error: {result.error_message}")
        except Exception as e:
            print(f"  -> [ERROR]: {e}")

    # Generate Reports
    print("\n" + "-" * 65)
    print(">> Generating PDF Execution Report...")
    pdf_path = reporter.generate_report(results)
    abs_pdf_path = os.path.abspath(pdf_path)

    passed_count = sum(1 for r in results if r.status == "PASSED")
    failed_count = len(results) - passed_count

    print("=" * 65)
    print(f"SUMMARY: {len(results)} Tests | {passed_count} Passed | {failed_count} Failed")
    print(f"PDF Report saved at: {abs_pdf_path}")
    print("=" * 65)

    return 1 if failed_count > 0 else 0


def main() -> None:
    """CLI argument parsing and execution."""
    parser = argparse.ArgumentParser(description="Web Test Automation Runner")
    parser.add_argument(
        "--dir", "-d",
        default="test",
        help="Directory to scan for .txt test files (default: test)"
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in visible (headed) mode"
    )
    args = parser.parse_args()

    exit_code = run_all(test_dir=args.dir, headless=not args.headed)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

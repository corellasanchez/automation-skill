"""Local HTTP web server for viewing the latest test automation report.

Serves latest_report.html and accompanying assets from the reports directory,
automatically opening the default web browser and supporting cache-busting headers.
"""

from __future__ import annotations

import argparse
import http.server
import os
import socket
import socketserver
import sys
import webbrowser
from typing import Any


class ReportRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that defaults root requests to latest_report.html."""

    def __init__(self, *args: Any, directory: str = "reports", **kwargs: Any) -> None:
        self.reports_directory = os.path.abspath(directory)
        super().__init__(*args, directory=self.reports_directory, **kwargs)

    def do_GET(self) -> None:
        """Route root and index requests to latest_report.html."""
        clean_path = self.path.split("?")[0].rstrip("/")
        if clean_path in ("", "/index.html"):
            self.path = "/latest_report.html"
        return super().do_GET()

    def end_headers(self) -> None:
        """Add cache control headers to ensure the browser always displays the latest report."""
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Log concise HTTP requests."""
        sys.stdout.write(f"  [HTTP] {args[0]} - {args[1]}\n")
        sys.stdout.flush()


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server with socket reuse enabled."""
    allow_reuse_address = True
    daemon_threads = True


def find_available_port(start_port: int = 8080, max_attempts: int = 50) -> int:
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


def start_report_server(
    reports_dir: str = "reports",
    port: int = 8080,
    open_browser: bool = True
) -> None:
    """Launch a local web server serving latest_report.html."""
    abs_dir = os.path.abspath(reports_dir)
    target_file = os.path.join(abs_dir, "latest_report.html")

    if not os.path.exists(target_file):
        print(f"[!] Warning: Report file not found at: {target_file}")
        print("    Run tests first to generate 'latest_report.html'.")

    actual_port = find_available_port(port)
    url = f"http://localhost:{actual_port}/"

    handler_factory = lambda *args, **kwargs: ReportRequestHandler(  # noqa: E731
        *args,
        directory=abs_dir,
        **kwargs
    )

    print("=" * 65)
    print(">> LOCAL TEST REPORT SERVER")
    print(f">> Report URL : {url}")
    print(f">> Serving    : {target_file}")
    print(">> Press Ctrl+C to terminate the server")
    print("=" * 65)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"[*] Note: Could not auto-launch browser ({e}). Open {url} manually.")

    try:
        with ThreadedTCPServer(("127.0.0.1", actual_port), handler_factory) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n>> Server stopped by user.")
    except Exception as e:
        print(f"\n[!] Server error: {e}")


def main() -> None:
    """CLI entrypoint for running the report server standalone."""
    parser = argparse.ArgumentParser(description="Serve latest test report locally")
    parser.add_argument(
        "--dir", "-d",
        default="reports",
        help="Reports directory containing latest_report.html (default: reports)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8080,
        help="Preferred port for web server (default: 8080)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the default browser"
    )
    args = parser.parse_args()

    start_report_server(
        reports_dir=args.dir,
        port=args.port,
        open_browser=not args.no_browser
    )


if __name__ == "__main__":
    main()

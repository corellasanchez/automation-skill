"""Test report generator.

Builds structured HTML reports with embedded failure screenshots and
exports them to PDF using Playwright with a ReportLab fallback.
"""

from __future__ import annotations

import base64
from datetime import datetime
import os
import shutil
from typing import List
from playwright.sync_api import sync_playwright

from src.executor import TestResult


class ReportGenerator:
    """Generates execution reports in HTML and PDF formats."""

    def __init__(self, output_dir: str = "reports") -> None:
        """Initialize reporter with output directory."""
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_report(self, results: List[TestResult]) -> str:
        """Generate HTML and PDF reports, returning the PDF file path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = os.path.join(self.output_dir, f"report_{timestamp}.html")
        pdf_path = os.path.join(self.output_dir, f"test_report_{timestamp}.pdf")
        latest_pdf = os.path.join(self.output_dir, "latest_report.pdf")
        latest_html = os.path.join(self.output_dir, "latest_report.html")

        # 1. Build and save HTML
        html_content = self._render_html(results)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        with open(latest_html, "w", encoding="utf-8") as f:
            f.write(html_content)

        # 2. Render Full-Page Snapshot & Generate High-Fidelity PDF
        pdf_generated = False
        try:
            from PIL import Image
            preview_path = os.path.join(self.output_dir, "report_preview.png")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(f"file:///{os.path.abspath(html_path).replace(os.sep, '/')}", wait_until="load")
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                page.evaluate("""
                    () => Promise.all(
                        Array.from(document.images).map(img => {
                            if (img.complete) return Promise.resolve();
                            return new Promise(res => { img.onload = img.onerror = res; });
                        })
                    )
                """)
                page.wait_for_timeout(600)
                page.screenshot(path=preview_path, full_page=True)
                browser.close()

            if os.path.exists(preview_path):
                img = Image.open(preview_path).convert("RGB")
                img.save(pdf_path, "PDF", resolution=100.0)
                pdf_generated = True
        except Exception:
            pdf_generated = False

        # Fallback to ReportLab if Playwright PDF failed
        if not pdf_generated:
            self._render_reportlab_pdf(results, pdf_path)

        # Copy to latest_report.pdf
        shutil.copyfile(pdf_path, latest_pdf)

        return pdf_path

    def _render_html(self, results: List[TestResult]) -> str:
        """Render standalone responsive HTML report."""
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r.status == "PASSED")
        failed_tests = total_tests - passed_tests
        total_duration = round(sum(r.duration_seconds for r in results), 2)
        execution_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        status_class = "success" if failed_tests == 0 else "danger"
        status_text = "ALL PASSED" if failed_tests == 0 else f"{failed_tests} FAILED"

        test_rows = []
        for res in results:
            badge_class = "badge-pass" if res.status == "PASSED" else "badge-fail"
            steps_html = []
            num_steps = len(res.steps)
            for s_idx, st in enumerate(res.steps):
                st_badge = "badge-pass" if st.status == "PASSED" else "badge-fail"
                cache_tag = '<span class="tag-cached">⚡ cached</span>' if st.was_cached else ""
                err_block = f'<div class="step-error">⚠️ {st.error_message}</div>' if st.error_message else ""
                screenshot_block = ""
                has_screenshot = False
                if st.screenshot_path and os.path.exists(st.screenshot_path):
                    has_screenshot = True
                    with open(st.screenshot_path, "rb") as img_file:
                        b64_data = base64.b64encode(img_file.read()).decode("utf-8")
                    screenshot_block = f'''
                    <div class="screenshot-box">
                        <img src="data:image/png;base64,{b64_data}" alt="Screenshot" />
                    </div>
                    '''

                # Keep action steps tied to their subsequent screenshot checkpoint
                bind_next = False
                if not has_screenshot:
                    # Look ahead up to 2 steps for a screenshot
                    for ahead in range(1, 3):
                        if s_idx + ahead < num_steps:
                            target_st = res.steps[s_idx + ahead]
                            if target_st.screenshot_path and os.path.exists(target_st.screenshot_path):
                                bind_next = True
                                break

                row_classes = ["step-row"]
                if has_screenshot:
                    row_classes.append("has-screenshot")
                if bind_next:
                    row_classes.append("bind-to-next")

                steps_html.append(f"""
                <div class="{' '.join(row_classes)}">
                    <div class="step-meta-row">
                        <span class="step-num">Line {st.line_number}</span>
                        <span class="step-code"><code>{st.masked_line}</code></span>
                        {cache_tag}
                        <span class="badge {st_badge}">{st.status}</span>
                        <span class="step-time">{st.duration_seconds}s</span>
                    </div>
                    {err_block}
                    {screenshot_block}
                </div>
                """)

            steps_joined = "".join(steps_html)
            test_rows.append(f"""
            <div class="test-card {'card-failed' if res.status == 'FAILED' else ''}">
                <div class="test-card-header">
                    <div class="test-info">
                        <span class="badge badge-group">{res.group_name}</span>
                        <span class="test-name">{res.test_name}</span>
                    </div>
                    <div class="test-meta">
                        <span class="badge {badge_class}">{res.status}</span>
                        <span class="test-time">{res.duration_seconds}s</span>
                    </div>
                </div>
                <div class="steps-container">
                    {steps_joined}
                </div>
            </div>
            """)

        cards_joined = "".join(test_rows)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Web Automation Test Report - {execution_date}</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: #f8fafc;
        color: #1e293b;
        margin: 0;
        padding: 30px;
    }}
    .container {{
        max-width: 1000px;
        margin: 0 auto;
    }}
    .header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #ffffff;
        padding: 24px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        margin-bottom: 24px;
        border-left: 6px solid {'#10b981' if failed_tests == 0 else '#ef4444'};
    }}
    .title {{
        margin: 0 0 6px 0;
        font-size: 24px;
        color: #0f172a;
    }}
    .subtitle {{
        margin: 0;
        color: #64748b;
        font-size: 14px;
    }}
    .metrics {{
        display: flex;
        gap: 16px;
        margin-bottom: 24px;
    }}
    .metric-card {{
        flex: 1;
        background: #ffffff;
        padding: 16px 20px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
        text-align: center;
    }}
    .metric-val {{
        font-size: 26px;
        font-weight: 700;
        color: #0f172a;
    }}
    .metric-label {{
        font-size: 13px;
        color: #64748b;
        margin-top: 4px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .badge {{
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
    }}
    .badge-pass {{
        background: #d1fae5;
        color: #065f46;
    }}
    .badge-fail {{
        background: #fee2e2;
        color: #991b1b;
    }}
    .badge-group {{
        background: #e2e8f0;
        color: #334155;
    }}
    .tag-cached {{
        background: #fef3c7;
        color: #92400e;
        font-size: 11px;
        padding: 2px 6px;
        border-radius: 4px;
        font-weight: 500;
    }}
    .test-card {{
        background: #ffffff;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        margin-bottom: 20px;
        border: 1px solid #e2e8f0;
    }}
    .card-failed {{
        border-color: #fca5a5;
    }}
    .test-card-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        background: #f8fafc;
        border-bottom: 1px solid #e2e8f0;
    }}
    .test-name {{
        font-size: 16px;
        font-weight: 600;
        margin-left: 8px;
    }}
    .steps-container {{
        padding: 14px 20px;
    }}
    .step-row {{
        background: #ffffff;
        border: 1px solid #f1f5f9;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 10px;
        page-break-inside: avoid;
        break-inside: avoid;
    }}
    .step-row:last-child {{
        margin-bottom: 0;
    }}
    .step-meta-row {{
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
    }}
    .step-num {{
        font-size: 11px;
        font-weight: 700;
        color: #1d4ed8;
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        padding: 3px 8px;
        border-radius: 6px;
        flex-shrink: 0;
        letter-spacing: 0.3px;
    }}
    .step-code {{
        flex: 1;
        font-size: 13px;
        word-break: break-word;
    }}
    .step-time {{
        font-size: 12px;
        color: #64748b;
        flex-shrink: 0;
    }}
    .step-error {{
        width: 100%;
        background: #fff1f2;
        border-left: 4px solid #f43f5e;
        padding: 10px 14px;
        border-radius: 6px;
        font-size: 13px;
        color: #881337;
        font-family: monospace;
        margin-top: 8px;
    }}
    .screenshot-box {{
        width: 100%;
        margin-top: 10px;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid #cbd5e1;
        background: #f8fafc;
        page-break-inside: avoid;
        break-inside: avoid;
    }}
    .bind-to-next {{
        page-break-after: avoid !important;
        break-after: avoid !important;
    }}
    .screenshot-box img {{
        max-width: 100%;
        max-height: 290px;
        object-fit: contain;
        display: block;
        margin: 0 auto;
    }}
    @page {{
        size: A4 portrait;
        margin: 15mm 12mm 18mm 12mm;
    }}
    @media print {{
        body {{
            background: #ffffff !important;
            padding: 0 !important;
        }}
        .container {{
            max-width: 100% !important;
            margin: 0 !important;
        }}
        .header, .metrics, .test-card-header {{
            page-break-inside: avoid !important;
            break-inside: avoid !important;
        }}
        .test-card {{
            border: none !important;
            box-shadow: none !important;
            border-radius: 0 !important;
            margin-bottom: 0 !important;
            background: transparent !important;
        }}
        .steps-container {{
            padding: 0 !important;
        }}
        .step-row {{
            page-break-inside: avoid !important;
            break-inside: avoid !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 6px !important;
            margin-bottom: 10px !important;
            padding: 10px 14px !important;
            background: #ffffff !important;
        }}
        .bind-to-next {{
            page-break-after: avoid !important;
            break-after: avoid !important;
        }}
        .screenshot-box {{
            page-break-inside: avoid !important;
            break-inside: avoid !important;
        }}
        .screenshot-box img {{
            max-height: 280px !important;
        }}
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1 class="title">Web Test Automation Report</h1>
            <p class="subtitle">Generated: {execution_date}</p>
        </div>
        <div>
            <span class="badge {'badge-pass' if failed_tests == 0 else 'badge-fail'}" style="font-size:16px; padding:8px 16px;">
                {status_text}
            </span>
        </div>
    </div>

    <div class="metrics">
        <div class="metric-card">
            <div class="metric-val">{total_tests}</div>
            <div class="metric-label">Total Tests</div>
        </div>
        <div class="metric-card">
            <div class="metric-val" style="color: #10b981;">{passed_tests}</div>
            <div class="metric-label">Passed</div>
        </div>
        <div class="metric-card">
            <div class="metric-val" style="color: #ef4444;">{failed_tests}</div>
            <div class="metric-label">Failed</div>
        </div>
        <div class="metric-card">
            <div class="metric-val">{total_duration}s</div>
            <div class="metric-label">Duration</div>
        </div>
    </div>

    <div class="tests-list">
        {cards_joined}
    </div>
</div>
</body>
</html>
"""

    def _render_reportlab_pdf(self, results: List[TestResult], output_pdf_path: str) -> None:
        """Fallback PDF generator using ReportLab."""
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        doc = SimpleDocTemplate(output_pdf_path, pagesize=letter, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
        story = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            name="TitleStyle",
            parent=styles["Heading1"],
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#0f172a")
        )
        story.append(Paragraph("Web Test Automation Report", title_style))
        story.append(Paragraph(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]))
        story.append(Spacer(1, 15))

        total_tests = len(results)
        passed_tests = sum(1 for r in results if r.status == "PASSED")
        failed_tests = total_tests - passed_tests

        # Summary table
        summary_data = [
            ["Total Tests", "Passed", "Failed"],
            [str(total_tests), str(passed_tests), str(failed_tests)]
        ]
        summary_table = Table(summary_data, colWidths=[150, 150, 150])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 20))

        for res in results:
            status_color = "#16a34a" if res.status == "PASSED" else "#dc2626"
            test_title = f"<b>[{res.group_name}] {res.test_name}</b> - <font color='{status_color}'>{res.status}</font> ({res.duration_seconds}s)"
            story.append(Paragraph(test_title, styles["Heading2"]))
            
            step_data = [["Line", "Action", "Status", "Duration"]]
            for st in res.steps:
                cached_str = " (⚡)" if st.was_cached else ""
                step_data.append([str(st.line_number), st.masked_line[:40], f"{st.status}{cached_str}", f"{st.duration_seconds}s"])
            
            t = Table(step_data, colWidths=[40, 320, 90, 60])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ]))
            story.append(t)
            story.append(Spacer(1, 10))

        doc.build(story)

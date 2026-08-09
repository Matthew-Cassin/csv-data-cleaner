"""Human- and machine-readable reporting on top of a CleaningResult."""

from __future__ import annotations

import html as html_module
from typing import Any

from tabulate import tabulate

from .logger import get_logger
from .models import CleaningResult, DataQualityIssue, DataQualityReport

logger = get_logger("reporter")

__all__ = ["QualityReporter"]


class QualityReporter:
    """Builds reports from a :class:`~csv_data_cleaner.models.CleaningResult`.

    Three output shapes, for three audiences: :meth:`generate_report`
    (a dict, for JSON/API consumers), :meth:`generate_summary` (a short
    string, for console output), and :meth:`export_to_html` (a
    self-contained HTML file, for sharing with a non-technical reviewer).
    """

    def generate_report(self, result: CleaningResult) -> dict[str, Any]:
        """Build the full quality report as a plain dict.

        Args:
            result: The result of a
                :meth:`~csv_data_cleaner.cleaner.CSVCleaner.clean` call.

        Returns:
            The same shape as
            :meth:`~csv_data_cleaner.models.DataQualityReport.to_dict`:
            ``timestamp``, ``statistics``, ``issues``,
            ``columns_processed``, and ``suggestions``.
        """
        return DataQualityReport.from_result(result).to_dict()

    def generate_summary(self, result: CleaningResult) -> str:
        """Build a short, human-readable summary table.

        Args:
            result: The result of a
                :meth:`~csv_data_cleaner.cleaner.CSVCleaner.clean` call.

        Returns:
            A ``tabulate``-formatted table (as a string -- the caller
            decides whether/how to print it) showing total rows, rows
            cleaned, rows removed, quality score before/after, and total
            issues found.
        """
        summary = result.summary
        rows: list[list[object]] = [
            ["Total records", result.report.total_rows],
            ["Rows cleaned (kept)", result.report.processed_rows],
            ["Rows removed", len(result.removed_rows)],
            ["Quality score (before)", f"{summary.get('quality_score_before', 0.0):.2f}"],
            ["Quality score (after)", f"{summary.get('quality_score_after', 0.0):.2f}"],
            ["Issues found", len(result.report.issues)],
        ]
        return tabulate(rows, headers=["Metric", "Value"], tablefmt="grid")

    def export_to_html(self, result: CleaningResult, filepath: str) -> None:
        """Write a self-contained HTML quality report.

        Includes summary statistics, a before/after quality-score
        comparison (CSS bar charts -- no JavaScript or external
        resources, so the file works offline and can be emailed as-is),
        an issue breakdown by severity and type, per-column statistics,
        and suggestions.

        Args:
            result: The result of a
                :meth:`~csv_data_cleaner.cleaner.CSVCleaner.clean` call.
            filepath: Path to write the HTML file to.
        """
        report = DataQualityReport.from_result(result)
        html_doc = _render_html_report(report)
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write(html_doc)
        logger.info("Wrote HTML quality report to %s", filepath)


def _esc(value: Any) -> str:
    """HTML-escape a value that may ultimately come from untrusted CSV data."""
    return html_module.escape(str(value))


def _severity_counts(issues: list[DataQualityIssue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


def _issue_type_counts(issues: list[DataQualityIssue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.issue_type] = counts.get(issue.issue_type, 0) + 1
    return counts


def _render_html_report(report: DataQualityReport) -> str:
    """Build the HTML document body for :func:`QualityReporter.export_to_html`."""
    severity_counts = _severity_counts(report.issues)
    type_counts = _issue_type_counts(report.issues)

    score_before_pct = round(report.quality_score_before * 100)
    score_after_pct = round(report.quality_score_after * 100)

    stats_rows = "".join(
        f"<tr><td>{_esc(label)}</td><td>{_esc(value)}</td></tr>"
        for label, value in [
            ("Total rows", report.total_rows),
            ("Processed rows", report.processed_rows),
            ("Rows with issues", report.rows_with_issues),
            ("Rows removed", report.rows_removed),
        ]
    )

    severity_rows = "".join(
        f"<tr><td class='sev-{_esc(sev)}'>{_esc(sev)}</td><td>{_esc(count)}</td></tr>"
        for sev, count in sorted(severity_counts.items())
    ) or "<tr><td colspan='2'>No issues found</td></tr>"

    type_rows = "".join(
        f"<tr><td>{_esc(kind)}</td><td>{_esc(count)}</td></tr>"
        for kind, count in sorted(type_counts.items())
    ) or "<tr><td colspan='2'>No issues found</td></tr>"

    column_rows = "".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(
            _esc(column), _esc(", ".join(f"{k}={v}" for k, v in stats.items()))
        )
        for column, stats in report.columns_processed.items()
    ) or "<tr><td colspan='2'>No columns processed</td></tr>"

    issue_rows = "".join(
        f"<tr><td>{_esc(issue.row_index)}</td><td>{_esc(issue.field)}</td>"
        f"<td class='sev-{_esc(issue.severity)}'>{_esc(issue.severity)}</td>"
        f"<td>{_esc(issue.issue_type)}</td><td>{_esc(issue.original_value)}</td>"
        f"<td>{_esc(issue.message)}</td></tr>"
        for issue in report.issues[:500]
    ) or "<tr><td colspan='6'>No issues found</td></tr>"
    truncation_note = (
        f"<p class='note'>Showing the first 500 of {len(report.issues)} issues.</p>"
        if len(report.issues) > 500
        else ""
    )

    suggestion_items = "".join(f"<li>{_esc(item)}</li>" for item in report.suggestions) or (
        "<li>No suggestions -- data looks clean.</li>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Data Quality Report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
          max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ margin-bottom: 0; }}
  .timestamp {{ color: #666; margin-top: 0.25rem; }}
  h2 {{ margin-top: 2.5rem; border-bottom: 2px solid #eee; padding-bottom: 0.4rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 0.75rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; }}
  tr:hover {{ background: #fafafa; }}
  .sev-error {{ color: #b91c1c; font-weight: 600; }}
  .sev-warning {{ color: #b45309; font-weight: 600; }}
  .sev-info {{ color: #1d4ed8; font-weight: 600; }}
  .score-row {{ display: flex; gap: 2rem; margin-top: 1rem; }}
  .score-block {{ flex: 1; }}
  .score-label {{ font-size: 0.9rem; color: #555; margin-bottom: 0.25rem; }}
  .score-bar-track {{ background: #eee; border-radius: 6px; height: 22px; overflow: hidden; }}
  .score-bar-fill {{ background: #16a34a; height: 100%; color: white; font-size: 0.8rem;
                      text-align: right; padding-right: 6px; box-sizing: border-box;
                      line-height: 22px; white-space: nowrap; }}
  .note {{ color: #666; font-size: 0.9rem; }}
  ul {{ padding-left: 1.25rem; }}
</style>
</head>
<body>
  <h1>Data Quality Report</h1>
  <p class="timestamp">Generated {_esc(report.timestamp)}</p>

  <h2>Summary</h2>
  <table>{stats_rows}</table>

  <h2>Quality Score</h2>
  <div class="score-row">
    <div class="score-block">
      <div class="score-label">Before cleaning</div>
      <div class="score-bar-track">
        <div class="score-bar-fill" style="width:{score_before_pct}%">{score_before_pct}%</div>
      </div>
    </div>
    <div class="score-block">
      <div class="score-label">After cleaning</div>
      <div class="score-bar-track">
        <div class="score-bar-fill" style="width:{score_after_pct}%">{score_after_pct}%</div>
      </div>
    </div>
  </div>

  <h2>Issues by Severity</h2>
  <table><tr><th>Severity</th><th>Count</th></tr>{severity_rows}</table>

  <h2>Issues by Type</h2>
  <table><tr><th>Type</th><th>Count</th></tr>{type_rows}</table>

  <h2>Column Statistics</h2>
  <table><tr><th>Column</th><th>Stats</th></tr>{column_rows}</table>

  <h2>Suggestions</h2>
  <ul>{suggestion_items}</ul>

  <h2>Issue Detail</h2>
  {truncation_note}
  <table>
    <tr>
      <th>Row</th><th>Field</th><th>Severity</th><th>Type</th>
      <th>Original Value</th><th>Message</th>
    </tr>
    {issue_rows}
  </table>
</body>
</html>
"""

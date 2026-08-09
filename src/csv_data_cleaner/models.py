"""Core data structures for csv-data-cleaner.

``CleaningRule`` describes one cleaning operation to apply.
``DataQualityIssue`` records one specific problem found in the data.
``CleaningReport`` and ``CleaningResult`` capture what happened during a
cleaning run; ``DataQualityReport`` is the serializable audit-trail view
of that run, suitable for writing straight to JSON.
``CleaningError`` is the single exception type the package raises.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

__all__ = [
    "CleaningError",
    "CleaningReport",
    "CleaningResult",
    "CleaningRule",
    "DataQualityIssue",
    "DataQualityReport",
]


@dataclass
class CleaningRule:
    """One cleaning operation to apply to a column, as part of a pipeline.

    Attributes:
        field: The column name this rule applies to. Ignored by rule
            types that operate on the whole DataFrame (e.g.
            ``"remove_duplicates"``, ``"standardize_column_names"``).
        rule_type: Which operation to run, e.g. ``"trim"``,
            ``"lowercase"``, ``"uppercase"``, ``"titlecase"``,
            ``"remove_duplicates"``, ``"validate_email"``,
            ``"validate_phone"``, ``"remove_special_chars"``,
            ``"convert_type"``, ``"handle_missing"``,
            ``"standardize_column_names"``. See
            :meth:`~csv_data_cleaner.cleaner.CSVCleaner.clean` for the
            full dispatch table and each type's expected ``parameters``.
        parameters: Rule-specific options, e.g. ``{"keep_chars": "-()"}``
            for ``"remove_special_chars"`` or ``{"type": "int"}`` for
            ``"convert_type"``.

    Example:
        >>> CleaningRule(field="email", rule_type="validate_email", parameters={})
        CleaningRule(field='email', rule_type='validate_email', parameters={})
    """

    field: str
    rule_type: str
    parameters: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class DataQualityIssue:
    """One specific data-quality problem found in a single cell.

    Attributes:
        row_index: The DataFrame index of the affected row.
        field: The column name affected.
        issue_type: e.g. ``"missing_value"``, ``"invalid_format"``,
            ``"duplicate"``, ``"outlier"``, ``"malformed"``,
            ``"conversion_failed"``.
        original_value: The value before cleaning, stringified.
        cleaned_value: The value after cleaning, if any change was made
            (e.g. a normalized email); ``None`` if the value was left
            as-is (flagged but not altered) or removed entirely.
        severity: ``"error"``, ``"warning"``, or ``"info"``.
        message: A human-readable description of the issue.
    """

    row_index: int
    field: str
    issue_type: str
    original_value: str
    cleaned_value: str | None
    severity: str
    message: str


@dataclass
class CleaningReport:
    """In-flight statistics and findings from a single cleaning run.

    Attributes:
        total_rows: Number of rows in the original input.
        processed_rows: Number of rows actually processed (normally
            equal to ``total_rows``; see
            :meth:`~csv_data_cleaner.cleaner.CSVCleaner.clean`).
        rows_with_issues: Number of distinct rows that had at least one
            :class:`DataQualityIssue`.
        issues: Every issue found, across all columns and rules.
        columns_processed: Per-column statistics, e.g.
            ``{"email": {"validation_errors": 2, "trimmed": 5}}``. Keys
            present depend on which rules touched that column.
        suggestions: Human-readable recommendations for further cleanup,
            derived from the issues found (e.g. a column still above a
            missing-value threshold after cleaning).
    """

    total_rows: int
    processed_rows: int
    rows_with_issues: int
    issues: list[DataQualityIssue] = dc_field(default_factory=list)
    columns_processed: dict[str, dict[str, Any]] = dc_field(default_factory=dict)
    suggestions: list[str] = dc_field(default_factory=list)


@dataclass
class CleaningResult:
    """The full outcome of a :meth:`~csv_data_cleaner.cleaner.CSVCleaner.clean` run.

    Attributes:
        cleaned_data: The cleaned DataFrame.
        report: The full :class:`CleaningReport` (issues, per-column
            stats, suggestions).
        removed_rows: Original-index values of rows that were removed
            during cleaning (by ``remove_duplicates`` and/or
            ``handle_missing_values(strategy="drop")``).
        summary: Before/after statistics: ``rows_before``, ``rows_after``,
            ``rows_removed``, ``quality_score_before``,
            ``quality_score_after`` (see
            :meth:`~csv_data_cleaner.analyzer.DataAnalyzer.generate_quality_score`).
    """

    cleaned_data: pd.DataFrame
    report: CleaningReport
    removed_rows: list[int] = dc_field(default_factory=list)
    summary: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class DataQualityReport:
    """The serializable audit-trail view of a :class:`CleaningResult`.

    Where ``CleaningResult`` is the full in-memory result (including the
    actual cleaned ``DataFrame``), ``DataQualityReport`` is specifically
    the *report* artifact -- statistics, quality scores, issues, and
    suggestions, timestamped, in a shape ready for
    :meth:`~csv_data_cleaner.cleaner.CSVCleaner.save_results` to write
    out as JSON. It has no dependency on pandas, so it can be freely
    logged, diffed, or sent over the wire without dragging a DataFrame
    along with it.

    Attributes:
        timestamp: ISO 8601 UTC timestamp of when the report was built.
        total_rows: See :attr:`CleaningReport.total_rows`.
        processed_rows: See :attr:`CleaningReport.processed_rows`.
        rows_with_issues: See :attr:`CleaningReport.rows_with_issues`.
        rows_removed: ``len(result.removed_rows)``.
        quality_score_before: Data quality score (``0.0``-``1.0``)
            computed on the original, unmodified input.
        quality_score_after: Data quality score computed on the cleaned
            output.
        issues: See :attr:`CleaningReport.issues`.
        columns_processed: See :attr:`CleaningReport.columns_processed`.
        suggestions: See :attr:`CleaningReport.suggestions`.
    """

    timestamp: str
    total_rows: int
    processed_rows: int
    rows_with_issues: int
    rows_removed: int
    quality_score_before: float
    quality_score_after: float
    issues: list[DataQualityIssue] = dc_field(default_factory=list)
    columns_processed: dict[str, dict[str, Any]] = dc_field(default_factory=dict)
    suggestions: list[str] = dc_field(default_factory=list)

    @classmethod
    def from_result(cls, result: CleaningResult) -> DataQualityReport:
        """Build a :class:`DataQualityReport` from a :class:`CleaningResult`.

        Args:
            result: The result of a completed
                :meth:`~csv_data_cleaner.cleaner.CSVCleaner.clean` call.

        Returns:
            A new ``DataQualityReport`` timestamped at the moment of the
            call.
        """
        report = result.report
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_rows=report.total_rows,
            processed_rows=report.processed_rows,
            rows_with_issues=report.rows_with_issues,
            rows_removed=len(result.removed_rows),
            quality_score_before=result.summary.get("quality_score_before", 0.0),
            quality_score_after=result.summary.get("quality_score_after", 0.0),
            issues=report.issues,
            columns_processed=report.columns_processed,
            suggestions=report.suggestions,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable ``dict`` representation.

        Returns:
            A dict with ``timestamp``, a ``statistics`` sub-dict, the
            full ``issues`` list (each expanded to a plain dict),
            ``columns_processed``, and ``suggestions``.
        """
        return {
            "timestamp": self.timestamp,
            "statistics": {
                "total_rows": self.total_rows,
                "processed_rows": self.processed_rows,
                "rows_with_issues": self.rows_with_issues,
                "rows_removed": self.rows_removed,
                "quality_score_before": round(self.quality_score_before, 4),
                "quality_score_after": round(self.quality_score_after, 4),
            },
            "issues": [asdict(issue) for issue in self.issues],
            "columns_processed": self.columns_processed,
            "suggestions": self.suggestions,
        }


class CleaningError(Exception):
    """Raised when an operation can't be attempted at all, not just when data is messy.

    Messy or invalid *data* is never an exception -- it's the everyday
    input this library exists to handle, reported through
    :class:`CleaningReport` (``issues``) instead. ``CleaningError`` is
    reserved for cases the caller must fix in code, such as:

    * A CSV file that can't be read at all (missing, empty, or genuinely
      unparseable) -- as opposed to a CSV that reads fine but has messy
      *values*.
    * An unknown ``rule_type``, an unsupported ``case``/``strategy``
      argument, or a column name that doesn't exist in the DataFrame.
    * Calling a method with the wrong argument type or shape.

    Example:
        >>> from csv_data_cleaner import CSVCleaner, CleaningError
        >>> cleaner = CSVCleaner()
        >>> import pandas as pd
        >>> df = pd.DataFrame({"name": ["Alice"]})
        >>> try:
        ...     cleaner.standardize_case(df, case="sideways")
        ... except CleaningError as exc:
        ...     print(exc)
        case must be one of 'lower', 'upper', 'title', got 'sideways'
    """

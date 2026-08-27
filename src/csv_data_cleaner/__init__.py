"""csv-data-cleaner: production-grade CSV data quality and cleaning.

Detects data-quality issues (missing values, duplicates, outliers,
invalid formats), cleans and standardizes data (whitespace, case,
special characters, type conversion), removes duplicates, and produces
a detailed, auditable quality report. Integrates with
``email-phone-validator`` for real email/phone validation.

Public API:
    CSVCleaner: The main entry point -- load a CSV, apply cleaning
        rules, save results.
    CleaningResult: The full in-memory outcome of a cleaning run,
        including the cleaned DataFrame.
    DataQualityReport: The serializable audit-trail view of a
        ``CleaningResult`` (what gets written to the JSON report).
    CleaningError: Raised for unrecoverable errors (bad configuration,
        an unreadable CSV, an unknown rule) as distinct from merely
        messy *data*, which is never an exception -- see its docstring.

Also exported for convenience: ``CleaningRule``, ``DataQualityIssue``,
and ``CleaningReport`` (the dataclasses that make up the results above),
and ``DataAnalyzer`` / ``FieldValidator`` / ``QualityReporter`` (the
lower-level building blocks ``CSVCleaner`` is built from).

Example:
    >>> from csv_data_cleaner import CSVCleaner
    >>> cleaner = CSVCleaner()
    >>> df = cleaner.load_csv("data.csv")  # doctest: +SKIP
    >>> result = cleaner.clean(df, rules=[])  # doctest: +SKIP
"""

from .analyzer import DataAnalyzer
from .cleaner import CSVCleaner
from .models import (
    CleaningError,
    CleaningReport,
    CleaningResult,
    CleaningRule,
    DataQualityIssue,
    DataQualityReport,
)
from .reporter import QualityReporter
from .validators import FieldValidator

__version__ = "1.0.1"

__all__ = [
    "CSVCleaner",
    "CleaningError",
    "CleaningReport",
    "CleaningResult",
    "CleaningRule",
    "DataAnalyzer",
    "DataQualityIssue",
    "DataQualityReport",
    "FieldValidator",
    "QualityReporter",
    "__version__",
]

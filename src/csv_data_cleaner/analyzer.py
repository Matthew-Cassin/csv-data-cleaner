"""Data-quality analysis: encoding detection, type inference, and scoring.

:class:`DataAnalyzer` is read-only -- none of its methods modify the
DataFrame they're given. It's used both directly (to inspect data before
deciding how to clean it) and internally by
:class:`~csv_data_cleaner.cleaner.CSVCleaner` (to compute before/after
quality scores and to auto-detect numeric columns for outlier checks).
"""

from __future__ import annotations

import re

import chardet
import pandas as pd

from .logger import get_logger

logger = get_logger("analyzer")

__all__ = ["DataAnalyzer"]

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Digits plus common separators/punctuation; the digit-count check in
# _infer_column_type does the real work of distinguishing a phone number
# from other punctuated text.
_PHONE_SHAPE_PATTERN = re.compile(r"^[\d\s()+\-.]+$")
_BOOL_VALUES = frozenset(
    ["true", "false", "yes", "no", "1", "0", "on", "off", "t", "f", "y", "n"]
)

# Fraction of non-null values in a column that must match a given
# heuristic for the column to be labeled as that type, rather than
# falling back to "text".
_TYPE_MATCH_THRESHOLD = 0.8

# generate_quality_score weights, summing to 1.0. Missing values are
# weighted heaviest since they're usually the most consequential problem
# for downstream use; duplicates next; outliers and invalid formats are
# comparatively narrower issues (they affect one column/row at a time).
_MISSING_WEIGHT = 0.40
_DUPLICATE_WEIGHT = 0.25
_INVALID_FORMAT_WEIGHT = 0.20
_OUTLIER_WEIGHT = 0.15


class DataAnalyzer:
    """Read-only analysis of a DataFrame's data quality.

    Example:
        >>> import pandas as pd
        >>> analyzer = DataAnalyzer()
        >>> df = pd.DataFrame({"age": ["28", "35", None]})
        >>> analyzer.detect_missing_values(df)
        {'age': 0.3333333333333333}
    """

    def detect_encoding(self, filepath: str) -> str:
        """Detect a file's text encoding.

        Reads up to 1 MB of the file (enough for a reliable detection
        without loading an arbitrarily large file into memory) and runs
        it through ``chardet``.

        Args:
            filepath: Path to the file to inspect.

        Returns:
            The detected encoding name (e.g. ``"utf-8"``,
            ``"ISO-8859-1"``), or ``"utf-8"`` if detection is
            inconclusive.
        """
        with open(filepath, "rb") as handle:
            raw = handle.read(1_000_000)
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        confidence = detected.get("confidence") or 0.0
        logger.info(
            "Detected encoding %s (confidence %.2f) for %s", encoding, confidence, filepath
        )
        return encoding

    def analyze_data_types(self, df: pd.DataFrame) -> dict[str, str]:
        """Infer a likely data type for each column.

        A lightweight, dependency-free heuristic (no email/phone
        validator instances required) -- good enough to guide cleaning
        decisions and quality scoring, not a substitute for real
        validation. See
        :class:`~csv_data_cleaner.validators.FieldValidator` for
        authoritative email/phone/date/etc. validation.

        Args:
            df: The DataFrame to analyze.

        Returns:
            A dict mapping each column name to one of ``"boolean"``,
            ``"numeric"``, ``"email"``, ``"phone"``, ``"date"``, or
            ``"text"`` (the fallback when no other type matches at
            least :data:`_TYPE_MATCH_THRESHOLD` of non-null values).
        """
        return {column: self._infer_column_type(df[column]) for column in df.columns}

    def _infer_column_type(self, column: pd.Series) -> str:
        """Infer the type of a single column. See :meth:`analyze_data_types`."""
        values = column.dropna().astype(str).str.strip()
        values = values[values != ""]
        if len(values) == 0:
            return "text"

        if (values.str.lower().isin(_BOOL_VALUES)).mean() >= _TYPE_MATCH_THRESHOLD:
            return "boolean"

        if pd.to_numeric(values, errors="coerce").notna().mean() >= _TYPE_MATCH_THRESHOLD:
            return "numeric"

        if values.str.match(_EMAIL_PATTERN).mean() >= _TYPE_MATCH_THRESHOLD:
            return "email"

        digit_counts = values.str.replace(r"\D", "", regex=True).str.len()
        phone_like = values.str.match(_PHONE_SHAPE_PATTERN) & digit_counts.between(7, 15)
        if phone_like.mean() >= _TYPE_MATCH_THRESHOLD:
            return "phone"

        # format="mixed" parses each value independently trying several
        # formats, rather than inferring one format from the first
        # values and failing everything that doesn't match it -- CSVs
        # routinely mix "2023-01-15" and "01/15/2023" in the same
        # column, and the single-format inference misreads that as
        # "mostly not dates."
        date_matches = pd.to_datetime(values, errors="coerce", format="mixed").notna()
        if date_matches.mean() >= _TYPE_MATCH_THRESHOLD:
            return "date"

        return "text"

    def detect_missing_values(self, df: pd.DataFrame) -> dict[str, float]:
        """Calculate the fraction of missing values in each column.

        Args:
            df: The DataFrame to analyze.

        Returns:
            A dict mapping each column name to its missing-value
            fraction (``0.0``-``1.0``). All ``0.0`` for an empty
            DataFrame.
        """
        if len(df) == 0:
            return dict.fromkeys((str(column) for column in df.columns), 0.0)
        return {str(column): float(fraction) for column, fraction in df.isna().mean().items()}

    def detect_duplicates(
        self, df: pd.DataFrame, subset: list[str] | None = None
    ) -> list[int]:
        """Find rows that duplicate an earlier row.

        Args:
            df: The DataFrame to check.
            subset: Column(s) to compare on. Defaults to all columns
                (an exact full-row match).

        Returns:
            Index values of duplicate rows -- the *later* occurrence(s)
            of each repeated value, not the first (matching pandas'
            ``duplicated(keep="first")`` convention: the first
            occurrence is treated as the original).
        """
        mask = df.duplicated(subset=subset, keep="first")
        return df.index[mask].tolist()

    def detect_outliers(
        self, df: pd.DataFrame, numeric_columns: list[str] | None = None
    ) -> dict[str, list[int]]:
        """Find numeric outliers using the IQR method.

        A value is an outlier if it falls outside
        ``[Q1 - 1.5*IQR, Q3 + 1.5*IQR]``, where ``IQR = Q3 - Q1`` (the
        standard Tukey's-fences definition).

        Args:
            df: The DataFrame to check.
            numeric_columns: Columns to check. Defaults to every column
                :meth:`analyze_data_types` infers as ``"numeric"``.

        Returns:
            A dict mapping each column with at least one outlier to the
            index values of its outlier rows. Columns with no outliers
            (including columns with zero IQR, e.g. constant columns) are
            omitted entirely.
        """
        if numeric_columns is None:
            types = self.analyze_data_types(df)
            numeric_columns = [column for column, kind in types.items() if kind == "numeric"]

        result: dict[str, list[int]] = {}
        for column in numeric_columns:
            if column not in df.columns:
                continue
            numeric = pd.to_numeric(df[column], errors="coerce")
            q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
            iqr = q3 - q1
            if pd.isna(iqr) or iqr == 0:
                continue
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            mask = ((numeric < lower) | (numeric > upper)).fillna(False)
            indices = df.index[mask].tolist()
            if indices:
                result[column] = indices
        return result

    def generate_quality_score(self, df: pd.DataFrame) -> float:
        """Compute an overall data quality score.

        Combines four signals into a single ``0.0``-``1.0`` score (higher
        is better): the average missing-value rate across columns, the
        duplicate-row rate, the average IQR-outlier rate across numeric
        columns, and the average invalid-format rate across columns that
        heuristically look like emails or phone numbers. Weighted
        ``0.40`` / ``0.25`` / ``0.15`` / ``0.20`` respectively (missing
        data weighted heaviest as the most consequential problem).

        Args:
            df: The DataFrame to score.

        Returns:
            ``1.0`` for a perfectly clean DataFrame (or an empty one --
            there's nothing to be wrong with it), decreasing toward
            ``0.0`` as problems accumulate. Never negative.
        """
        if len(df) == 0:
            return 1.0

        missing = self.detect_missing_values(df)
        avg_missing_rate = sum(missing.values()) / len(missing) if missing else 0.0

        duplicate_rate = len(self.detect_duplicates(df)) / len(df)

        outliers = self.detect_outliers(df)
        outlier_rate = (
            sum(len(rows) for rows in outliers.values()) / (len(outliers) * len(df))
            if outliers
            else 0.0
        )

        invalid_format_rate = self._estimate_invalid_format_rate(df)

        score = 1.0 - (
            _MISSING_WEIGHT * avg_missing_rate
            + _DUPLICATE_WEIGHT * duplicate_rate
            + _OUTLIER_WEIGHT * outlier_rate
            + _INVALID_FORMAT_WEIGHT * invalid_format_rate
        )
        # missing.values() / detect_duplicates() etc. are pandas-derived,
        # so `score` is a numpy float64 at this point, not a native
        # Python float -- cast explicitly rather than let that leak out
        # (numpy scalars are not reliably JSON-serializable, and this is
        # a value that ends up straight in a JSON report).
        return float(max(0.0, min(1.0, score)))

    def _estimate_invalid_format_rate(self, df: pd.DataFrame) -> float:
        """Average invalid-format rate across heuristically email/phone columns.

        Reuses :meth:`analyze_data_types` to find candidate columns, then
        measures how many of that column's values actually match the
        pattern that got it classified that way. Returns ``0.0`` if no
        column looks like an email or phone column.
        """
        types = self.analyze_data_types(df)
        rates: list[float] = []
        for column, kind in types.items():
            if kind not in ("email", "phone"):
                continue
            values = df[column].dropna().astype(str).str.strip()
            values = values[values != ""]
            if len(values) == 0:
                continue
            if kind == "email":
                rates.append((~values.str.match(_EMAIL_PATTERN)).mean())
            else:
                digit_counts = values.str.replace(r"\D", "", regex=True).str.len()
                rates.append((~digit_counts.between(7, 15)).mean())
        return sum(rates) / len(rates) if rates else 0.0

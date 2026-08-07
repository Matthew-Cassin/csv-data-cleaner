"""Core CSV cleaning: load, normalize, validate, convert, and save."""

from __future__ import annotations

import csv as csv_module
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .analyzer import DataAnalyzer
from .logger import get_logger
from .models import (
    CleaningError,
    CleaningReport,
    CleaningResult,
    CleaningRule,
    DataQualityIssue,
    DataQualityReport,
)
from .validators import FieldValidator

logger = get_logger("cleaner")

__all__ = ["CSVCleaner"]

_VALID_CASES = ("lower", "upper", "title")
_VALID_MISSING_STRATEGIES = ("drop", "fill", "forward_fill", "backward_fill")
_VALID_CONVERT_TYPES = ("int", "float", "bool", "datetime", "date", "str")
# Validation types whose normalized value is itself a meaningful string
# to write back into the DataFrame. numeric/boolean normalize to a
# float/bool, which convert_data_types (not validate_column) is
# responsible for actually converting the column to.
_STRING_NORMALIZING_VALIDATION_TYPES = frozenset(["email", "phone", "date", "url"])
_VALIDATION_METHODS = {
    "numeric": "validate_numeric",
    "boolean": "validate_boolean",
    "date": "validate_date",
    "url": "validate_url",
    "email": "validate_email",
    "phone": "validate_phone",
}
# Missing-value tokens beyond a bare empty cell that CSVs commonly use.
_MISSING_NA_VALUES = ["", "NA", "N/A", "n/a", "null", "NULL", "None", "none", "NaN", "-"]


class CSVCleaner:
    """Loads, cleans, validates, and saves CSV data.

    Args:
        email_validator: An optional
            :class:`~email_phone_validator.EmailValidator` instance,
            used by :meth:`validate_column` /
            :meth:`~csv_data_cleaner.validators.FieldValidator.validate_email`
            for real email format + MX validation. Falls back to a basic
            format check when omitted.
        phone_validator: An optional
            :class:`~email_phone_validator.PhoneValidator` instance,
            used the same way for phone numbers.
        remove_empty_rows: Whether :meth:`clean` drops fully-empty rows
            (every field null) as a baseline step before applying rules.
            Defaults to ``True``.

    Example:
        >>> cleaner = CSVCleaner()
        >>> df = cleaner.load_csv("contacts.csv")  # doctest: +SKIP
        >>> from csv_data_cleaner import CleaningRule
        >>> result = cleaner.clean(df, rules=[
        ...     CleaningRule(field="", rule_type="trim", parameters={}),
        ... ])  # doctest: +SKIP
    """

    def __init__(
        self,
        email_validator=None,
        phone_validator=None,
        remove_empty_rows: bool = True,
    ) -> None:
        self.email_validator = email_validator
        self.phone_validator = phone_validator
        self.remove_empty_rows = remove_empty_rows
        self._analyzer = DataAnalyzer()
        self._field_validator = FieldValidator(email_validator, phone_validator)
        # Set by clean(); used by save_results() to look up the original
        # (pre-cleaning) data for rows that got removed, so
        # removed_rows_csv can contain real row data, not just indices.
        # Scoped to "the most recent clean() call on this instance" --
        # call clean() and save_results() as a pair on the same
        # CSVCleaner, as the CLI does.
        self._last_original_data: Optional[pd.DataFrame] = None

    # -- Loading ------------------------------------------------------

    def load_csv(self, filepath: str, encoding: Optional[str] = None) -> pd.DataFrame:
        """Load a CSV file into a DataFrame.

        Args:
            filepath: Path to the CSV file.
            encoding: Text encoding to use. Auto-detected via
                :meth:`~csv_data_cleaner.analyzer.DataAnalyzer.detect_encoding`
                when omitted.

        Returns:
            The loaded data, every column read as ``str`` (no automatic
            numeric/date type inference -- use :meth:`convert_data_types`
            explicitly). Common null tokens (empty cells, ``"NA"``,
            ``"N/A"``, ``"null"``, ``"None"``, ``"-"``) are read as real
            missing values (``NaN``), not the literal string.

        Raises:
            CleaningError: If the file doesn't exist, is empty, or can't
                be parsed as CSV.
        """
        path = Path(filepath)
        if not path.exists():
            raise CleaningError(f"CSV file not found: {filepath}")

        if encoding is None:
            encoding = self._analyzer.detect_encoding(filepath)

        delimiter = self._detect_delimiter(filepath, encoding)

        try:
            df = pd.read_csv(
                filepath,
                encoding=encoding,
                delimiter=delimiter,
                dtype=str,
                keep_default_na=True,
                na_values=_MISSING_NA_VALUES,
            )
        except pd.errors.EmptyDataError as exc:
            raise CleaningError(f"CSV file is empty: {filepath}") from exc
        except (pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise CleaningError(f"Could not parse CSV file {filepath}: {exc}") from exc

        logger.info(
            "Loaded %d row(s), %d column(s) from %s (encoding=%s, delimiter=%r)",
            len(df),
            len(df.columns),
            filepath,
            encoding,
            delimiter,
        )
        return df

    def _detect_delimiter(self, filepath: str, encoding: str) -> str:
        """Sniff the delimiter from a sample of the file; default to comma."""
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as handle:
                sample = handle.read(8192)
            dialect = csv_module.Sniffer().sniff(sample, delimiters=",;\t|")
            return dialect.delimiter
        except (csv_module.Error, OSError):
            return ","

    # -- Column-level cleaning operations ------------------------------

    def _resolve_columns(self, df: pd.DataFrame, columns: Optional[List[str]]) -> List[str]:
        """All columns if none given, else validate they all exist."""
        if columns is None:
            return list(df.columns)
        missing = [column for column in columns if column not in df.columns]
        if missing:
            raise CleaningError(f"Column(s) not found in DataFrame: {missing}")
        return columns

    def trim_whitespace(
        self, df: pd.DataFrame, columns: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """Strip leading/trailing whitespace from string columns.

        Args:
            df: The DataFrame to clean.
            columns: Columns to trim. Defaults to all columns.

        Returns:
            A new DataFrame with the specified columns trimmed. ``NaN``
            values are left as ``NaN`` (pandas' ``.str`` accessor
            propagates nulls rather than erroring on them).

        Raises:
            CleaningError: If any named column doesn't exist.
        """
        target_columns = self._resolve_columns(df, columns)
        result = df.copy()
        for column in target_columns:
            result[column] = result[column].str.strip()
        logger.info("Trimmed whitespace in column(s): %s", target_columns)
        return result

    def standardize_case(
        self, df: pd.DataFrame, columns: Optional[List[str]] = None, case: str = "lower"
    ) -> pd.DataFrame:
        """Convert string columns to a consistent case.

        Args:
            df: The DataFrame to clean.
            columns: Columns to convert. Defaults to all columns.
            case: ``"lower"``, ``"upper"``, or ``"title"``.

        Returns:
            A new DataFrame with the specified columns case-converted.

        Raises:
            CleaningError: If ``case`` isn't one of the supported values,
                or any named column doesn't exist.
        """
        if case not in _VALID_CASES:
            raise CleaningError(f"case must be one of 'lower', 'upper', 'title', got {case!r}")
        target_columns = self._resolve_columns(df, columns)
        result = df.copy()
        for column in target_columns:
            if case == "lower":
                result[column] = result[column].str.lower()
            elif case == "upper":
                result[column] = result[column].str.upper()
            else:
                result[column] = result[column].str.title()
        logger.info("Standardized case to %s in column(s): %s", case, target_columns)
        return result

    def remove_special_characters(
        self, df: pd.DataFrame, columns: Optional[List[str]] = None, keep_chars: str = ""
    ) -> pd.DataFrame:
        """Strip non-alphanumeric characters from string columns.

        Letters, digits, and whitespace are always kept; anything else
        is removed unless listed in ``keep_chars``.

        Args:
            df: The DataFrame to clean.
            columns: Columns to clean. Defaults to all columns.
            keep_chars: Additional characters to preserve, e.g.
                ``"-()"`` to keep phone-number punctuation.

        Returns:
            A new DataFrame with special characters removed from the
            specified columns.

        Raises:
            CleaningError: If any named column doesn't exist.
        """
        target_columns = self._resolve_columns(df, columns)
        result = df.copy()
        pattern = re.compile(rf"[^a-zA-Z0-9\s{re.escape(keep_chars)}]")
        for column in target_columns:
            result[column] = result[column].str.replace(pattern, "", regex=True)
        logger.info(
            "Removed special characters (keep_chars=%r) in column(s): %s",
            keep_chars,
            target_columns,
        )
        return result

    def handle_missing_values(
        self, df: pd.DataFrame, strategy: str = "drop", fill_value: Optional[str] = None
    ) -> pd.DataFrame:
        """Handle missing (``NaN``) values across the whole DataFrame.

        Args:
            df: The DataFrame to clean.
            strategy: ``"drop"`` removes any row with at least one
                missing value; ``"fill"`` replaces every missing value
                with ``fill_value`` (or ``""`` if not given);
                ``"forward_fill"`` / ``"backward_fill"`` propagate the
                previous/next valid value down/up each column.
            fill_value: The value to use when ``strategy="fill"``.

        Returns:
            A new DataFrame with missing values handled per ``strategy``.

        Raises:
            CleaningError: If ``strategy`` isn't one of the supported
                values.
        """
        if strategy not in _VALID_MISSING_STRATEGIES:
            raise CleaningError(
                f"strategy must be one of {_VALID_MISSING_STRATEGIES}, got {strategy!r}"
            )

        if strategy == "drop":
            result = df.dropna()
            logger.info("Dropped %d row(s) with missing values", len(df) - len(result))
            return result
        if strategy == "fill":
            result = df.fillna(fill_value if fill_value is not None else "")
            logger.info("Filled missing values with %r", fill_value)
            return result
        if strategy == "forward_fill":
            result = df.ffill()
            logger.info("Forward-filled missing values")
            return result
        result = df.bfill()
        logger.info("Backward-filled missing values")
        return result

    def remove_duplicates(
        self, df: pd.DataFrame, subset: Optional[List[str]] = None, keep: Any = "first"
    ) -> Tuple[pd.DataFrame, List[int]]:
        """Remove exact duplicate rows.

        Args:
            df: The DataFrame to clean.
            subset: Column(s) to compare on. Defaults to all columns (an
                exact full-row match).
            keep: ``"first"`` keeps the first occurrence of each
                duplicated value and removes the rest; ``"last"`` keeps
                the last; ``False`` removes every row that has at least
                one duplicate, including the first occurrence.

        Returns:
            A ``(cleaned_df, removed_indices)`` tuple.

        Raises:
            CleaningError: If ``keep`` isn't ``"first"``, ``"last"``, or
                ``False``.
        """
        if keep not in ("first", "last", False):
            raise CleaningError(f"keep must be 'first', 'last', or False, got {keep!r}")
        mask = df.duplicated(subset=subset, keep=keep)
        removed = [int(idx) for idx in df.index[mask]]
        result = df[~mask]
        logger.info("Removed %d duplicate row(s)", len(removed))
        return result, removed

    def validate_column(
        self, df: pd.DataFrame, column: str, validation_type: str, validator: Any = None
    ) -> Tuple[pd.DataFrame, List[DataQualityIssue]]:
        """Validate (and where meaningful, normalize) a single column.

        Missing (``NaN``) values are skipped -- that's
        :meth:`handle_missing_values`'s concern, not validation's.
        Invalid values are *flagged*, not removed: they're left in the
        DataFrame unchanged and recorded as an ``"error"``-severity
        :class:`~csv_data_cleaner.models.DataQualityIssue`, so no data is
        silently dropped. Use the returned issues to decide whether to
        remove or otherwise handle them yourself.

        Args:
            df: The DataFrame to validate.
            column: The column to validate.
            validation_type: One of ``"numeric"``, ``"boolean"``,
                ``"date"``, ``"url"``, ``"email"``, ``"phone"``.
            validator: An override validator instance to use instead of
                this ``CSVCleaner``'s configured one, for
                ``validation_type in ("email", "phone")`` only. Ignored
                for other validation types.

        Returns:
            A ``(df, issues)`` tuple. For ``"email"``, ``"phone"``,
            ``"date"``, and ``"url"``, valid values are normalized in
            place (e.g. an email lowercased, a phone formatted to
            E.164). ``"numeric"`` and ``"boolean"`` are validated but
            left as their original string -- use :meth:`convert_data_types`
            to actually change a column's type.

        Raises:
            CleaningError: If ``column`` doesn't exist, or
                ``validation_type`` isn't supported.
        """
        if column not in df.columns:
            raise CleaningError(f"Column not found in DataFrame: {column!r}")
        if validation_type not in _VALIDATION_METHODS:
            raise CleaningError(
                f"validation_type must be one of {sorted(_VALIDATION_METHODS)}, "
                f"got {validation_type!r}"
            )

        field_validator = self._field_validator
        if validator is not None and validation_type in ("email", "phone"):
            field_validator = FieldValidator(
                email_validator=validator if validation_type == "email" else self.email_validator,
                phone_validator=validator if validation_type == "phone" else self.phone_validator,
            )

        method = getattr(field_validator, _VALIDATION_METHODS[validation_type])
        result = df.copy()
        issues: List[DataQualityIssue] = []

        for idx, raw_value in df[column].items():
            if pd.isna(raw_value):
                continue
            is_valid, normalized = method(raw_value)
            if is_valid:
                if (
                    validation_type in _STRING_NORMALIZING_VALIDATION_TYPES
                    and normalized != raw_value
                ):
                    result.at[idx, column] = normalized
            else:
                issues.append(
                    DataQualityIssue(
                        row_index=int(idx),
                        field=column,
                        issue_type="invalid_format",
                        original_value=str(raw_value),
                        cleaned_value=None,
                        severity="error",
                        message=f"{column!r} value {raw_value!r} is not a valid {validation_type}",
                    )
                )

        logger.info("Validated column %r as %s: %d issue(s)", column, validation_type, len(issues))
        return result, issues

    def convert_data_types(
        self, df: pd.DataFrame, type_mapping: Dict[str, str]
    ) -> Tuple[pd.DataFrame, List[DataQualityIssue]]:
        """Convert columns to specified pandas/Python types.

        Args:
            df: The DataFrame to convert.
            type_mapping: Column name -> target type, one of ``"int"``,
                ``"float"``, ``"bool"``, ``"datetime"``, ``"date"``,
                ``"str"``.

        Returns:
            A ``(df, issues)`` tuple. Values that fail conversion become
            ``NaN`` (rather than raising) and are recorded as
            ``"warning"``-severity issues with ``issue_type="conversion_failed"``.

        Raises:
            CleaningError: If a named column doesn't exist, or a target
                type isn't supported.
        """
        result = df.copy()
        issues: List[DataQualityIssue] = []

        for column, target_type in type_mapping.items():
            if column not in df.columns:
                raise CleaningError(f"Column not found in DataFrame: {column!r}")
            if target_type not in _VALID_CONVERT_TYPES:
                raise CleaningError(
                    f"Unsupported type {target_type!r} for column {column!r}; "
                    f"must be one of {_VALID_CONVERT_TYPES}"
                )

            original = result[column]
            was_null = original.isna()
            converted, failed = self._convert_column(original, target_type)
            result[column] = converted

            for idx in original.index[(~was_null) & failed]:
                issues.append(
                    DataQualityIssue(
                        row_index=int(idx),
                        field=column,
                        issue_type="conversion_failed",
                        original_value=str(original.at[idx]),
                        cleaned_value=None,
                        severity="warning",
                        message=(
                            f"Could not convert {column!r} value "
                            f"{original.at[idx]!r} to {target_type}"
                        ),
                    )
                )

        logger.info("Converted type(s) for column(s): %s", list(type_mapping.keys()))
        return result, issues

    def _convert_column(
        self, series: "pd.Series", target_type: str
    ) -> Tuple["pd.Series", "pd.Series"]:
        """Convert one column; returns (converted_series, failure_mask)."""
        if target_type in ("int", "float"):
            numeric = pd.to_numeric(series, errors="coerce")
            if target_type == "int":
                # A value that parses numerically but isn't whole (e.g.
                # "35.5") is a conversion failure for "int", not
                # something to silently truncate -- astype("Int64")
                # would itself raise on exactly this rather than lose
                # precision, so it's handled explicitly here instead of
                # leaking a pandas TypeError to the caller.
                non_whole = numeric.notna() & (numeric % 1 != 0)
                numeric = numeric.mask(non_whole)
                failed = series.notna() & numeric.isna()
                numeric = numeric.astype("Int64")
            else:
                failed = series.notna() & numeric.isna()
            return numeric, failed

        if target_type == "bool":
            parsed = series.apply(self._field_validator.validate_boolean)
            values = parsed.apply(lambda pair: pair[1])
            valid = parsed.apply(lambda pair: pair[0])
            failed = series.notna() & ~valid
            return values, failed

        if target_type in ("datetime", "date"):
            converted = pd.to_datetime(series, errors="coerce", format="mixed")
            failed = series.notna() & converted.isna()
            if target_type == "date":
                converted = converted.dt.date
            return converted, failed

        # str
        return series.astype(str), pd.Series(False, index=series.index)

    def standardize_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names to lowercase-with-underscores.

        Non-alphanumeric runs become a single underscore, and leading/
        trailing underscores are stripped (e.g. ``"E-Mail Address"`` ->
        ``"e_mail_address"``). Collisions after normalization (e.g. two
        columns that both reduce to ``"phone"``) are disambiguated with
        a numeric suffix.

        Args:
            df: The DataFrame whose columns to rename.

        Returns:
            A new DataFrame with standardized column names.
        """
        seen: Dict[str, int] = {}
        new_names: Dict[Any, str] = {}
        for original in df.columns:
            normalized = re.sub(r"[^a-z0-9]+", "_", str(original).strip().lower()).strip("_")
            normalized = normalized or "column"
            if normalized in seen:
                seen[normalized] += 1
                normalized = f"{normalized}_{seen[normalized]}"
            else:
                seen[normalized] = 0
            new_names[original] = normalized
        logger.info("Standardized column names: %s", new_names)
        return df.rename(columns=new_names)

    # -- Pipeline orchestration -----------------------------------------

    def clean(
        self, df: pd.DataFrame, rules: List[CleaningRule], remove_empty_rows: bool = True
    ) -> CleaningResult:
        """Apply a series of cleaning rules and produce a full audit trail.

        Args:
            df: The DataFrame to clean. Never modified in place.
            rules: The rules to apply, in order -- each rule's output
                feeds the next. See the class-level dispatch table in
                :meth:`_apply_rule` for supported ``rule_type`` values
                and their expected ``parameters``.
            remove_empty_rows: Whether to drop fully-empty rows (every
                field null) before applying ``rules``. Independent of
                any ``"handle_missing"`` rule in ``rules`` itself, which
                handles partially-missing rows.

        Returns:
            A :class:`~csv_data_cleaner.models.CleaningResult` with the
            cleaned data, a full issue/statistics report, and before/after
            quality scores in ``summary``.

        Raises:
            CleaningError: If ``rules`` isn't a list, or any rule fails
                (unknown ``rule_type``, bad parameters, missing column).
        """
        if not isinstance(rules, list):
            raise CleaningError(f"rules must be a list, got {type(rules).__name__}")

        original = df.copy()
        self._last_original_data = original
        total_rows = len(original)
        quality_score_before = self._analyzer.generate_quality_score(original)

        working = df.copy()
        removed_rows: List[int] = []
        if remove_empty_rows:
            before_count = len(working)
            working = working.dropna(how="all")
            if before_count != len(working):
                removed_rows.extend(
                    int(idx) for idx in original.index if idx not in working.index
                )
                logger.info("Removed %d fully-empty row(s)", before_count - len(working))

        all_issues: List[DataQualityIssue] = []
        columns_processed: Dict[str, Dict[str, Any]] = {}

        for rule in rules:
            working, issues, rule_removed = self._apply_rule(working, rule, columns_processed)
            all_issues.extend(issues)
            for idx in rule_removed:
                if idx not in removed_rows:
                    removed_rows.append(idx)

        quality_score_after = self._analyzer.generate_quality_score(working)
        rows_with_issues = len({issue.row_index for issue in all_issues})
        suggestions = self._generate_suggestions(working, all_issues, quality_score_after)

        report = CleaningReport(
            total_rows=total_rows,
            processed_rows=len(working),
            rows_with_issues=rows_with_issues,
            issues=all_issues,
            columns_processed=columns_processed,
            suggestions=suggestions,
        )
        summary = {
            "rows_before": total_rows,
            "rows_after": len(working),
            "rows_removed": len(removed_rows),
            "quality_score_before": quality_score_before,
            "quality_score_after": quality_score_after,
        }

        logger.info(
            "Cleaning complete: %d row(s) -> %d row(s), quality %.2f -> %.2f",
            total_rows,
            len(working),
            quality_score_before,
            quality_score_after,
        )

        return CleaningResult(
            cleaned_data=working, report=report, removed_rows=removed_rows, summary=summary
        )

    def _apply_rule(
        self, df: pd.DataFrame, rule: CleaningRule, columns_processed: Dict[str, Dict[str, Any]]
    ) -> Tuple[pd.DataFrame, List[DataQualityIssue], List[int]]:
        """Dispatch one CleaningRule to the matching CSVCleaner method.

        Supported ``rule_type`` values and their ``parameters``:

        * ``"trim"`` -- ``columns`` (default: ``[rule.field]`` if set,
          else all columns).
        * ``"lowercase"`` / ``"uppercase"`` / ``"titlecase"`` -- ``columns``.
        * ``"remove_special_chars"`` -- ``columns``, ``keep_chars``.
        * ``"handle_missing"`` -- ``strategy``, ``fill_value``.
        * ``"remove_duplicates"`` -- ``subset``, ``keep``.
        * ``"validate_email"`` / ``"validate_phone"`` -- applies to
          ``rule.field``; optional ``validator`` override.
        * ``"convert_type"`` -- applies to ``rule.field`` with
          ``parameters["type"]``, or set ``parameters["type_mapping"]``
          directly for multiple columns at once.
        * ``"standardize_column_names"`` -- no parameters.
        """
        params = rule.parameters or {}
        issues: List[DataQualityIssue] = []
        removed: List[int] = []
        columns = params.get("columns", [rule.field] if rule.field else None)

        if rule.rule_type == "trim":
            df = self.trim_whitespace(df, columns=columns)
        elif rule.rule_type in ("lowercase", "uppercase", "titlecase"):
            case = {"lowercase": "lower", "uppercase": "upper", "titlecase": "title"}[
                rule.rule_type
            ]
            df = self.standardize_case(df, columns=columns, case=case)
        elif rule.rule_type == "remove_special_chars":
            df = self.remove_special_characters(df, columns=columns, keep_chars=params.get(
                "keep_chars", ""
            ))
        elif rule.rule_type == "handle_missing":
            df = self.handle_missing_values(
                df, strategy=params.get("strategy", "drop"), fill_value=params.get("fill_value")
            )
        elif rule.rule_type == "remove_duplicates":
            df, removed = self.remove_duplicates(
                df, subset=params.get("subset"), keep=params.get("keep", "first")
            )
        elif rule.rule_type in ("validate_email", "validate_phone"):
            validation_type = "email" if rule.rule_type == "validate_email" else "phone"
            df, issues = self.validate_column(
                df, rule.field, validation_type, validator=params.get("validator")
            )
        elif rule.rule_type == "convert_type":
            type_mapping = params.get("type_mapping")
            if type_mapping is None:
                type_mapping = {rule.field: params["type"]}
            df, issues = self.convert_data_types(df, type_mapping)
        elif rule.rule_type == "standardize_column_names":
            df = self.standardize_column_names(df)
        else:
            raise CleaningError(f"Unknown rule_type: {rule.rule_type!r}")

        if rule.field:
            stats = columns_processed.setdefault(rule.field, {})
            stats[f"{rule.rule_type}_issues"] = len(issues)
            if removed:
                stats["removed_by_rule"] = stats.get("removed_by_rule", 0) + len(removed)

        return df, issues, removed

    def _generate_suggestions(
        self, df: pd.DataFrame, issues: List[DataQualityIssue], quality_score_after: float
    ) -> List[str]:
        """Build human-readable recommendations from the final state."""
        suggestions: List[str] = []

        for column, rate in self._analyzer.detect_missing_values(df).items():
            if rate > 0.1:
                suggestions.append(
                    f"Column '{column}' still has {rate:.0%} missing values after cleaning; "
                    "consider a fill strategy or manual review."
                )

        error_counts: Dict[str, int] = {}
        for issue in issues:
            if issue.severity == "error":
                error_counts[issue.field] = error_counts.get(issue.field, 0) + 1
        for column, count in error_counts.items():
            suggestions.append(
                f"Column '{column}' has {count} unresolved validation issue(s); review before use."
            )

        if quality_score_after < 0.7:
            suggestions.append(
                f"Overall quality score is {quality_score_after:.2f} after cleaning; "
                "consider additional rules or manual review."
            )

        return suggestions

    # -- Output ---------------------------------------------------------

    def save_results(
        self,
        result: CleaningResult,
        output_csv: str,
        report_json: str,
        removed_rows_csv: Optional[str] = None,
    ) -> None:
        """Write the cleaned CSV, JSON quality report, and (optionally) removed rows.

        Args:
            result: The result of a call to :meth:`clean`.
            output_csv: Path to write the cleaned data to.
            report_json: Path to write the JSON quality report to (see
                :meth:`~csv_data_cleaner.models.DataQualityReport.to_dict`).
            removed_rows_csv: If given, path to write the *original* data
                for every removed row to, for manual review. Requires
                calling :meth:`clean` on this same ``CSVCleaner``
                instance first (its original input is what gets looked
                up); an empty file with just headers is written if no
                prior ``clean()`` call is found.
        """
        result.cleaned_data.to_csv(output_csv, index=False)

        quality_report = DataQualityReport.from_result(result)
        with open(report_json, "w", encoding="utf-8") as handle:
            json.dump(quality_report.to_dict(), handle, indent=2, default=str)

        if removed_rows_csv:
            if self._last_original_data is not None and result.removed_rows:
                available = [
                    idx for idx in result.removed_rows if idx in self._last_original_data.index
                ]
                self._last_original_data.loc[available].to_csv(removed_rows_csv, index=False)
            else:
                pd.DataFrame(columns=result.cleaned_data.columns).to_csv(
                    removed_rows_csv, index=False
                )

        logger.info(
            "Saved %d row(s) to %s and report to %s",
            len(result.cleaned_data),
            output_csv,
            report_json,
        )

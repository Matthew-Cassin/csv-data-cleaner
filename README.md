# CSV Data Cleaner

[![CI](https://github.com/Matthew-Cassin/csv-data-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/Matthew-Cassin/csv-data-cleaner/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Types](https://img.shields.io/badge/types-mypy%20strict-brightgreen)

A Python library and CLI for cleaning, validating, and standardizing messy CSV data, with a scored, auditable quality report before and after.

## Installation

```bash
# Install directly from GitHub
pip install git+https://github.com/Matthew-Cassin/csv-data-cleaner.git

# Or clone and install locally for development
git clone https://github.com/Matthew-Cassin/csv-data-cleaner.git
cd csv-data-cleaner
pip install -e .
```

This pulls in [`email-phone-validator`](https://github.com/Matthew-Cassin/email-phone-validator) automatically, which csv-data-cleaner uses for real email/phone validation and normalization.

## Features

- **Auto-detects** file encoding (`chardet`) and CSV delimiter -- no need to know the source format upfront.
- **Infers column types** (text, numeric, date, email, phone, boolean) heuristically, to guide what cleaning it needs.
- **Cleans**: whitespace trimming, case standardization, special-character stripping, missing-value handling (drop/fill/forward-fill/backward-fill), exact-duplicate removal, column-name standardization.
- **Validates**: numeric, boolean, date (multiple formats), URL, and -- via `email-phone-validator` -- real email and phone validation, not just regex guessing.
- **Scores data quality** (0.0-1.0) before and after cleaning, factoring in missing values, duplicates, outliers, and invalid formats.
- **Full audit trail**: every issue found, every field changed, with a JSON report and an optional self-contained HTML report.
- **CLI or library** -- `csv-data-cleaner file.csv --trim-whitespace --remove-duplicates` or drive it programmatically with fine-grained control.

## Quick Start

### 1. Basic Python usage: load, clean, save

```python
from csv_data_cleaner import CSVCleaner
from email_phone_validator import EmailValidator, PhoneValidator

cleaner = CSVCleaner(EmailValidator(check_mx=False), PhoneValidator())
df = cleaner.load_csv("contacts.csv")
result = cleaner.clean(df, rules=[])  # no rules yet -- just scores the data

print(f"{result.report.total_rows} rows loaded, quality score: {result.summary['quality_score_before']:.2f}")
# 10 rows loaded, quality score: 0.92

cleaner.save_results(result, "cleaned.csv", "quality_report.json")
```

### 2. Using cleaning rules

Rules are declarative and run in order -- each rule's output feeds the next:

```python
from csv_data_cleaner import CSVCleaner
from csv_data_cleaner.models import CleaningRule
from email_phone_validator import EmailValidator, PhoneValidator

cleaner = CSVCleaner(EmailValidator(check_mx=False), PhoneValidator())
df = cleaner.load_csv("contacts.csv")

rules = [
    CleaningRule(field="", rule_type="trim", parameters={}),
    CleaningRule(field="email", rule_type="validate_email", parameters={}),
    CleaningRule(field="phone", rule_type="validate_phone", parameters={}),
    CleaningRule(field="", rule_type="remove_duplicates", parameters={}),
]
result = cleaner.clean(df, rules)

print(f"{result.report.total_rows} -> {result.report.processed_rows} rows")
print(f"Quality: {result.summary['quality_score_before']:.2f} -> {result.summary['quality_score_after']:.2f}")
print(f"Issues found: {len(result.report.issues)}")
# 10 -> 9 rows
# Quality: 0.92 -> 0.94
# Issues found: 12
```

(All 12 issues here are phone-related, on this repo's [sample data](tests/fixtures/sample_data.csv) -- every phone number in it uses a `555` area code, which is a *reserved/fictional* NANP area code, not one ever assigned to a real subscriber, so a real validator correctly flags all of them despite looking well-formed. See [Limitations](#limitations).)

### 3. CLI usage with common scenarios

```bash
# Report only -- no flags means nothing gets touched, just scored
csv-data-cleaner contacts.csv

# Clean and validate
csv-data-cleaner contacts.csv --trim-whitespace --remove-duplicates \
    --validate-emails email --validate-phones phone
```

```
+------------------------+---------+
| Metric                 |   Value |
+========================+=========+
| Total records          |   10    |
+------------------------+---------+
| Rows cleaned (kept)    |    9    |
+------------------------+---------+
| Rows removed           |    1    |
+------------------------+---------+
| Quality score (before) |    0.92 |
+------------------------+---------+
| Quality score (after)  |    0.94 |
+------------------------+---------+
| Issues found           |   12    |
+------------------------+---------+

Saved cleaned data to cleaned.csv
Saved quality report to quality_report.json
```

### 4. Validating specific columns directly

Skip the rules pipeline and call validation straight up when you just want the issues:

```python
cleaned_df, issues = cleaner.validate_column(df, "email", "email")
for issue in issues:
    print(f"Row {issue.row_index}: {issue.message}")
# Row 5: 'email' value 'bob@example.com!!!' is not a valid email
# Row 6: 'email' value 'bob@example.com!!!' is not a valid email
# Row 8: 'email' value 'charlie@' is not a valid email
```

Invalid values are *flagged, not removed* -- `cleaned_df` still has all the original rows; only genuinely valid values get normalized in place.

### 5. Handling missing values

```python
print(df.isna().sum().to_dict())
# {'name': 1, 'email': 0, 'phone': 1, 'age': 0, 'address': 1, 'created_date': 0}

filled = cleaner.handle_missing_values(df, strategy="fill", fill_value="Unknown")
print(filled.isna().sum().to_dict())
# {'name': 0, 'email': 0, 'phone': 0, 'age': 0, 'address': 0, 'created_date': 0}
```

## How It Works

**Pipeline flow.** `load_csv` reads the file (auto-detecting encoding and delimiter, everything as strings, common null tokens like `""`/`"NA"`/`"null"`/`"-"` recognized as real missing values). `clean()` then optionally drops fully-empty rows, applies your `CleaningRule` list in order, and produces a `CleaningResult`: the cleaned `DataFrame`, a full `CleaningReport` (every issue found, per-column stats, suggestions), and before/after quality scores.

**Data quality scoring.** `DataAnalyzer.generate_quality_score()` combines four signals into one `0.0`-`1.0` score: average missing-value rate (weighted `0.40`), duplicate-row rate (`0.25`), IQR-outlier rate on numeric columns (`0.15`), and invalid-format rate on columns that heuristically look like emails/phones (`0.20`). `clean()` computes this once on your original input and once on the cleaned output, so you can see the actual improvement, not just trust that cleaning helped.

**Issue detection and reporting.** Two independent mechanisms feed the same `DataQualityIssue` list: validation (`validate_column`, `convert_data_types`) flags values that don't match an expected type or format, and duplicate/missing-value handling removes rows outright (tracked in `removed_rows`, not as issues). Every issue records the row, field, original value, severity (`error`/`warning`/`info`), and a human-readable message -- enough to trace any flagged value straight back to its source row.

## Cleaning Operations

| Operation | Method | What it does |
|---|---|---|
| Trim whitespace | `trim_whitespace(df, columns=None)` | Strips leading/trailing whitespace; `None` values pass through untouched. |
| Standardize case | `standardize_case(df, columns=None, case="lower")` | `"lower"`, `"upper"`, or `"title"`. |
| Remove special characters | `remove_special_characters(df, columns=None, keep_chars="")` | Strips everything but letters/digits/whitespace, plus anything in `keep_chars` (e.g. `"-()"` for phone punctuation). |
| Handle missing values | `handle_missing_values(df, strategy="drop", fill_value=None)` | `"drop"` (any row with a missing value), `"fill"`, `"forward_fill"`, `"backward_fill"`. |
| Remove duplicates | `remove_duplicates(df, subset=None, keep="first")` | Exact-match only; `keep="first"`/`"last"`/`False` (remove every occurrence). |
| Validate columns | `validate_column(df, column, validation_type, validator=None)` | Flags invalid values (doesn't remove them); normalizes valid `email`/`phone`/`date`/`url` values in place. |
| Convert data types | `convert_data_types(df, type_mapping)` | `int`/`float`/`bool`/`datetime`/`date`/`str`; failures become `NaN` + a logged issue, never a crash. |
| Standardize column names | `standardize_column_names(df)` | Lowercase-with-underscores, e.g. `"E-Mail Address"` -> `"e_mail_address"`. |

## Validation Types

| Type | Method | Notes |
|---|---|---|
| Email | `FieldValidator.validate_email` | Uses `EmailValidator` when injected (real format + optional MX check); falls back to a basic `local@domain.tld` shape check otherwise. |
| Phone | `FieldValidator.validate_phone` | Uses `PhoneValidator` when injected (E.164 formatting, international); falls back to a 7-15 digit count check otherwise. |
| Numeric | `FieldValidator.validate_numeric` | `int`/`float` syntax via Python's own `float()`. |
| Boolean | `FieldValidator.validate_boolean` | `true`/`false`, `yes`/`no`, `1`/`0`, `on`/`off`, `t`/`f`, `y`/`n` (case-insensitive). |
| Date | `FieldValidator.validate_date` | Tries several common formats in turn (ISO, US and EU slash/dash, month-name) unless you pass an explicit `format`. Normalizes to `YYYY-MM-DD`. |
| URL | `FieldValidator.validate_url` | Requires an explicit `http`/`https`/`ftp` scheme and a dotted host. |

Custom validation with rules: any `CleaningRule` with `rule_type="validate_email"` or `"validate_phone"` accepts a `parameters={"validator": your_instance}` override, used instead of the `CSVCleaner`'s configured validator for that one rule.

## API Reference

### `CSVCleaner`

```python
CSVCleaner(email_validator=None, phone_validator=None, remove_empty_rows: bool = True)
```

| Method | Description |
|---|---|
| `load_csv(filepath, encoding=None) -> pd.DataFrame` | Load a CSV, auto-detecting encoding/delimiter if not given. |
| `trim_whitespace`, `standardize_case`, `remove_special_characters`, `handle_missing_values`, `remove_duplicates`, `validate_column`, `convert_data_types`, `standardize_column_names` | See [Cleaning Operations](#cleaning-operations) above. |
| `clean(df, rules, remove_empty_rows=True) -> CleaningResult` | Run a full rule pipeline; see [How It Works](#how-it-works). |
| `save_results(result, output_csv, report_json, removed_rows_csv=None)` | Write the cleaned CSV, the JSON report, and (optionally) the *original* data for removed rows. Requires calling `clean()` on this same instance first. |

### `DataAnalyzer`

Read-only; used directly or internally by `CSVCleaner`. `detect_encoding(filepath) -> str`, `analyze_data_types(df) -> Dict[str, str]`, `detect_missing_values(df) -> Dict[str, float]`, `detect_duplicates(df, subset=None) -> List[int]`, `detect_outliers(df, numeric_columns=None) -> Dict[str, List[int]]` (IQR method), `generate_quality_score(df) -> float`.

### `FieldValidator`

```python
FieldValidator(email_validator=None, phone_validator=None)
```

Six `validate_*(value) -> Tuple[bool, Optional[...]]` methods, one per [validation type](#validation-types) above.

### Dataclasses

**`CleaningRule`** -- `field`, `rule_type`, `parameters: Dict[str, Any]`.

**`DataQualityIssue`** -- `row_index`, `field`, `issue_type`, `original_value`, `cleaned_value`, `severity` (`error`/`warning`/`info`), `message`.

**`CleaningReport`** -- `total_rows`, `processed_rows`, `rows_with_issues`, `issues: List[DataQualityIssue]`, `columns_processed: Dict[str, Dict]`, `suggestions: List[str]`.

**`CleaningResult`** -- `cleaned_data: pd.DataFrame`, `report: CleaningReport`, `removed_rows: List[int]`, `summary: Dict[str, Any]` (`rows_before`, `rows_after`, `rows_removed`, `quality_score_before`, `quality_score_after`).

**`DataQualityReport`** -- the serializable audit-report view of a `CleaningResult`, built via `DataQualityReport.from_result(result)`, exported with `.to_dict()`.

## CLI Reference

```
csv-data-cleaner INPUT_CSV [OPTIONS]
```

| Option | Description |
|---|---|
| `--output PATH` | Cleaned CSV path (default `cleaned.csv`). |
| `--report PATH` | JSON quality report path (default `quality_report.json`). |
| `--trim-whitespace` | Trim whitespace from every column. |
| `--lowercase` | Lowercase every column. |
| `--remove-duplicates` | Remove exact duplicate rows. |
| `--remove-empty-rows` | Remove rows where every field is missing. |
| `--validate-emails COLUMN` | Validate and normalize the named email column. |
| `--validate-phones COLUMN` | Validate and normalize the named phone column. |
| `--remove-rows-file` | Also save removed rows to `removed_rows.csv`. |
| `--encoding TEXT` | Force a file encoding instead of auto-detecting. |
| `--verbose` | Enable INFO-level console logging. |

With no flags, `csv-data-cleaner file.csv` loads, scores, and writes the data back out **unchanged** -- every cleaning operation is opt-in, so running the bare command is always safe to try first. A missing file or a bad option exits with status `1` and a plain `Error: ...` message, never a Python traceback.

## Output Files

**Cleaned CSV** -- the cleaned data, same columns as the input.

**Quality report JSON** -- `timestamp`, a `statistics` block (`total_rows`, `processed_rows`, `rows_with_issues`, `rows_removed`, `quality_score_before`, `quality_score_after`), the full `issues` list, `columns_processed`, and `suggestions`.

**HTML report** (via `QualityReporter().export_to_html(result, "report.html")`) -- a self-contained, offline-viewable page: summary stats, a before/after quality-score bar comparison, issues broken down by severity and type, per-column stats, suggestions, and the first 500 issues in full detail.

**Removed rows CSV** (`--remove-rows-file` / `save_results(..., removed_rows_csv=...)`) -- the *original* row data (not just indices) for every row removed by deduplication or `handle_missing_values(strategy="drop")`, for manual review.

## Performance

Benchmarked loading + cleaning (trim, validate email, validate phone, remove duplicates) on synthetic CSVs, on a standard laptop:

| Rows | Time |
|---|---|
| 100 | 0.07s |
| 500 | 0.11s |
| 1,000 | 0.19s |
| 5,000 | 0.86s |

Scales roughly linearly (**O(n)**) -- unlike matching-based tools, every operation here is per-row or a single vectorized pandas pass, with no pairwise comparison. Should comfortably handle CSVs into the hundreds of thousands of rows; very wide files (many columns) will scale roughly linearly in column count too, since most operations loop over target columns.

## Limitations

- **Date parsing is ambiguous by design for some inputs.** `"01/02/2023"` is read as month-first (US) before day-first (EU) is tried, so it becomes January 2nd, not February 1st. Pass an explicit `format` to `validate_date`/`FieldValidator` when you know the source convention.
- **`"Longest wins"` doesn't apply here** (that's `contact-deduplicator`'s merge strategy) -- `remove_duplicates` is exact-match only. Two records that are "the same person" but not byte-identical (e.g. different phone formatting) won't be caught; clean first (trim/case/normalize), *then* deduplicate.
- **The basic email/phone fallbacks are deliberately light.** Without an injected `EmailValidator`/`PhoneValidator`, validation is a shape check, not a real one -- no MX lookups, no libphonenumber area-code data. Always inject real validators for anything client-facing.
- **`analyze_data_types` is a heuristic**, not authoritative validation -- it's there to guide *your* cleaning decisions (which columns need `validate_column`?), not to certify data as correct.
- **`save_results(..., removed_rows_csv=...)` is scoped to one `CSVCleaner` instance's most recent `clean()` call** -- call `clean()` and `save_results()` as a pair on the same instance (as the CLI does).
- **HTML reports cap issue detail at 500 rows** to keep the file a reasonable size; the JSON report has no such limit.

## License

MIT -- see [LICENSE](LICENSE) for the full text.

## Contributing

Contributions are welcome. Please open an issue to discuss a change before submitting a pull request, and make sure `pytest` and `flake8` are clean.

"""Command-line interface for csv-data-cleaner, built on Click."""

from __future__ import annotations

import logging
import sys

import click
from email_phone_validator import EmailValidator, PhoneValidator

from .cleaner import CSVCleaner
from .logger import configure_logging
from .models import CleaningError, CleaningRule
from .reporter import QualityReporter

__all__ = ["clean"]

_DEFAULT_REMOVED_ROWS_FILE = "removed_rows.csv"


@click.command()
@click.argument("input_csv", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output", default="cleaned.csv", show_default=True, help="Path to write the cleaned CSV to."
)
@click.option(
    "--report",
    default="quality_report.json",
    show_default=True,
    help="Path to write the JSON quality report to.",
)
@click.option(
    "--trim-whitespace", is_flag=True, default=False, help="Trim whitespace from every column."
)
@click.option("--lowercase", is_flag=True, default=False, help="Lowercase every column.")
@click.option(
    "--remove-duplicates", is_flag=True, default=False, help="Remove exact duplicate rows."
)
@click.option(
    "--remove-empty-rows",
    is_flag=True,
    default=False,
    help="Remove rows where every field is missing.",
)
@click.option(
    "--validate-emails",
    "validate_emails_column",
    default=None,
    metavar="COLUMN",
    help="Validate and normalize the named email column.",
)
@click.option(
    "--validate-phones",
    "validate_phones_column",
    default=None,
    metavar="COLUMN",
    help="Validate and normalize the named phone column.",
)
@click.option(
    "--remove-rows-file",
    is_flag=True,
    default=False,
    help=f"Also save removed rows to {_DEFAULT_REMOVED_ROWS_FILE} for review.",
)
@click.option("--encoding", default=None, help="File encoding to use. Auto-detected if omitted.")
@click.option(
    "--verbose", is_flag=True, default=False, help="Enable verbose (INFO-level) console logging."
)
def clean(
    input_csv: str,
    output: str,
    report: str,
    trim_whitespace: bool,
    lowercase: bool,
    remove_duplicates: bool,
    remove_empty_rows: bool,
    validate_emails_column: str,
    validate_phones_column: str,
    remove_rows_file: bool,
    encoding: str,
    verbose: bool,
) -> None:
    """Clean and validate the CSV file at INPUT_CSV.

    With no flags, INPUT_CSV is loaded, scored, and written back out
    unchanged (a quality report only, no data touched) -- every cleaning
    operation is opt-in. Combine flags freely, e.g.:

        clean contacts.csv --trim-whitespace --remove-duplicates
        --validate-emails email --validate-phones phone
    """
    if verbose:
        configure_logging(level=logging.INFO)

    try:
        cleaner = CSVCleaner(
            email_validator=EmailValidator(check_mx=False), phone_validator=PhoneValidator()
        )
        df = cleaner.load_csv(input_csv, encoding=encoding)

        rules = []
        if trim_whitespace:
            rules.append(CleaningRule(field="", rule_type="trim", parameters={}))
        if lowercase:
            rules.append(CleaningRule(field="", rule_type="lowercase", parameters={}))
        if validate_emails_column:
            rules.append(
                CleaningRule(
                    field=validate_emails_column, rule_type="validate_email", parameters={}
                )
            )
        if validate_phones_column:
            rules.append(
                CleaningRule(
                    field=validate_phones_column, rule_type="validate_phone", parameters={}
                )
            )
        if remove_duplicates:
            rules.append(CleaningRule(field="", rule_type="remove_duplicates", parameters={}))

        result = cleaner.clean(df, rules, remove_empty_rows=remove_empty_rows)

        removed_rows_csv = _DEFAULT_REMOVED_ROWS_FILE if remove_rows_file else None
        cleaner.save_results(
            result, output_csv=output, report_json=report, removed_rows_csv=removed_rows_csv
        )
    except CleaningError as exc:
        raise click.ClickException(str(exc)) from exc

    reporter = QualityReporter()
    click.echo(reporter.generate_summary(result))
    click.echo(f"\nSaved cleaned data to {output}")
    click.echo(f"Saved quality report to {report}")
    if removed_rows_csv:
        click.echo(f"Saved removed rows to {removed_rows_csv}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(clean())

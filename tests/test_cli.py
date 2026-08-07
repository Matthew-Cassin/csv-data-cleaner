"""Tests for csv_data_cleaner.cli."""

import json
import os
import shutil

from click.testing import CliRunner

from csv_data_cleaner.cli import clean

FIXTURE_CSV = os.path.abspath("tests/fixtures/sample_data.csv")


def run(args):
    return CliRunner().invoke(clean, args)


class TestCliDefaults:
    """No flags: report only, nothing touched."""

    def test_exits_zero(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(clean, ["sample.csv"])
            assert result.exit_code == 0

    def test_no_rows_removed_and_no_issues_without_flags(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(clean, ["sample.csv"])
            assert "Rows removed" in result.output
            assert "Issues found" in result.output
            with open("quality_report.json") as handle:
                data = json.load(handle)
            assert data["statistics"]["rows_removed"] == 0
            assert len(data["issues"]) == 0

    def test_creates_default_output_files(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(clean, ["sample.csv"])
            assert os.path.exists("cleaned.csv")
            assert os.path.exists("quality_report.json")

    def test_does_not_create_removed_rows_file_by_default(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(clean, ["sample.csv"])
            assert not os.path.exists("removed_rows.csv")


class TestCliFlags:
    """Individual and combined cleaning flags."""

    def test_trim_whitespace_flag(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(clean, ["sample.csv", "--trim-whitespace"])
            import pandas as pd

            df = pd.read_csv("cleaned.csv")
            assert df["email"].iloc[0] == "john@example.com"  # was "  john@example.com  "

    def test_remove_duplicates_flag(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(clean, ["sample.csv", "--remove-duplicates"])
            assert "Rows removed" in result.output
            with open("quality_report.json") as handle:
                data = json.load(handle)
            assert data["statistics"]["rows_removed"] == 1

    def test_validate_emails_option_flags_issues(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(clean, ["sample.csv", "--validate-emails", "email"])
            with open("quality_report.json") as handle:
                data = json.load(handle)
            assert any(issue["field"] == "email" for issue in data["issues"])

    def test_validate_phones_option_flags_issues(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(clean, ["sample.csv", "--validate-phones", "phone"])
            with open("quality_report.json") as handle:
                data = json.load(handle)
            assert any(issue["field"] == "phone" for issue in data["issues"])

    def test_remove_empty_rows_flag(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("blank.csv", "w") as handle:
                handle.write("a,b\n1,2\n,\n3,4\n")
            result = runner.invoke(clean, ["blank.csv", "--remove-empty-rows"])
            assert result.exit_code == 0
            import pandas as pd

            assert len(pd.read_csv("cleaned.csv")) == 2

    def test_remove_rows_file_flag_creates_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(clean, ["sample.csv", "--remove-duplicates", "--remove-rows-file"])
            assert os.path.exists("removed_rows.csv")

    def test_custom_output_and_report_paths(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(
                clean, ["sample.csv", "--output", "out.csv", "--report", "rep.json"]
            )
            assert result.exit_code == 0
            assert os.path.exists("out.csv")
            assert os.path.exists("rep.json")
            assert not os.path.exists("cleaned.csv")

    def test_verbose_flag_emits_log_lines(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(clean, ["sample.csv", "--verbose"])
            assert "INFO" in result.output

    def test_without_verbose_no_log_lines(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(clean, ["sample.csv"])
            assert "INFO" not in result.output

    def test_combined_flags_all_take_effect(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(
                clean,
                [
                    "sample.csv", "--trim-whitespace", "--remove-duplicates",
                    "--validate-emails", "email", "--validate-phones", "phone",
                ],
            )
            assert result.exit_code == 0
            with open("quality_report.json") as handle:
                data = json.load(handle)
            assert data["statistics"]["rows_removed"] == 1
            assert len(data["issues"]) > 0


class TestCliErrorHandling:
    def test_missing_file_exits_nonzero_with_friendly_message(self):
        result = run(["does-not-exist.csv"])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_unrecognized_option_is_rejected_by_click(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(clean, ["sample.csv", "--not-a-real-flag"])
            assert result.exit_code != 0

    def test_zero_byte_csv_is_a_clean_error_not_a_traceback(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            open("empty.csv", "w").close()
            result = runner.invoke(clean, ["empty.csv"])
            assert result.exit_code == 1
            assert result.output.startswith("Error:")
            assert "Traceback" not in result.output

"""Tests for csv_data_cleaner.cleaner."""

import json

import pandas as pd
import pytest
from email_phone_validator import EmailValidator, PhoneValidator

from csv_data_cleaner.cleaner import CSVCleaner
from csv_data_cleaner.models import CleaningError, CleaningResult, CleaningRule

FIXTURE_CSV = "tests/fixtures/sample_data.csv"


@pytest.fixture
def cleaner():
    return CSVCleaner(EmailValidator(check_mx=False), PhoneValidator())


def write_csv(tmp_path, text, name="data.csv", encoding="utf-8"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return str(path)


class TestLoadCsv:
    """load_csv: encoding/delimiter detection, null handling, error paths."""

    def test_loads_the_sample_fixture(self, cleaner):
        df = cleaner.load_csv(FIXTURE_CSV)
        assert len(df) == 10
        assert list(df.columns) == ["name", "email", "phone", "age", "address", "created_date"]

    def test_every_column_loaded_as_string(self, cleaner):
        # pandas 3.x has a dedicated string dtype distinct from "object";
        # is_string_dtype recognizes either, which is what actually
        # matters here (no silent numeric/date auto-conversion).
        df = cleaner.load_csv(FIXTURE_CSV)
        assert all(pd.api.types.is_string_dtype(df[col]) for col in df.columns)

    def test_empty_cells_become_real_missing_values(self, cleaner):
        df = cleaner.load_csv(FIXTURE_CSV)
        assert df["name"].isna().sum() == 1  # the row with a blank name

    def test_common_null_tokens_become_missing(self, cleaner, tmp_path):
        path = write_csv(tmp_path, "a,b\n1,NA\n2,N/A\n3,null\n4,-\n")
        df = cleaner.load_csv(path)
        assert df["b"].isna().sum() == 4

    def test_semicolon_delimiter_is_detected(self, cleaner, tmp_path):
        path = write_csv(tmp_path, "name;email\nAlice;alice@example.com\n")
        df = cleaner.load_csv(path)
        assert list(df.columns) == ["name", "email"]

    def test_explicit_encoding_overrides_detection(self, cleaner, tmp_path):
        path = write_csv(tmp_path, "name\nAlice\n", encoding="utf-8")
        df = cleaner.load_csv(path, encoding="utf-8")
        assert df["name"].tolist() == ["Alice"]

    def test_missing_file_raises_cleaning_error(self, cleaner):
        with pytest.raises(CleaningError, match="not found"):
            cleaner.load_csv("/no/such/file.csv")

    def test_zero_byte_file_raises_cleaning_error(self, cleaner, tmp_path):
        path = write_csv(tmp_path, "")
        with pytest.raises(CleaningError, match="empty"):
            cleaner.load_csv(path)


class TestTrimWhitespace:
    def test_trims_all_columns_by_default(self, cleaner):
        df = pd.DataFrame({"a": ["  x  "], "b": [" y "]})
        result = cleaner.trim_whitespace(df)
        assert result["a"].tolist() == ["x"]
        assert result["b"].tolist() == ["y"]

    def test_trims_only_specified_columns(self, cleaner):
        df = pd.DataFrame({"a": ["  x  "], "b": [" y "]})
        result = cleaner.trim_whitespace(df, columns=["a"])
        assert result["a"].tolist() == ["x"]
        assert result["b"].tolist() == [" y "]

    def test_none_values_are_left_alone(self, cleaner):
        df = pd.DataFrame({"a": [None]})
        result = cleaner.trim_whitespace(df)
        assert result["a"].isna().all()

    def test_unknown_column_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["x"]})
        with pytest.raises(CleaningError):
            cleaner.trim_whitespace(df, columns=["zzz"])

    def test_original_dataframe_is_not_mutated(self, cleaner):
        df = pd.DataFrame({"a": ["  x  "]})
        cleaner.trim_whitespace(df)
        assert df["a"].tolist() == ["  x  "]


class TestStandardizeCase:
    def test_lowercase(self, cleaner):
        df = pd.DataFrame({"a": ["ABC"]})
        assert cleaner.standardize_case(df, case="lower")["a"].tolist() == ["abc"]

    def test_uppercase(self, cleaner):
        df = pd.DataFrame({"a": ["abc"]})
        assert cleaner.standardize_case(df, case="upper")["a"].tolist() == ["ABC"]

    def test_titlecase(self, cleaner):
        df = pd.DataFrame({"a": ["john smith"]})
        assert cleaner.standardize_case(df, case="title")["a"].tolist() == ["John Smith"]

    def test_invalid_case_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["x"]})
        with pytest.raises(CleaningError, match="lower.*upper.*title"):
            cleaner.standardize_case(df, case="sideways")


class TestRemoveSpecialCharacters:
    def test_removes_punctuation_by_default(self, cleaner):
        df = pd.DataFrame({"a": ["hello!!!world"]})
        assert cleaner.remove_special_characters(df)["a"].tolist() == ["helloworld"]

    def test_keep_chars_preserves_listed_characters(self, cleaner):
        df = pd.DataFrame({"phone": ["(555) 123-4567!!"]})
        result = cleaner.remove_special_characters(df, keep_chars="-()")
        assert result["phone"].tolist() == ["(555) 123-4567"]

    def test_letters_digits_and_whitespace_always_kept(self, cleaner):
        df = pd.DataFrame({"a": ["abc 123"]})
        assert cleaner.remove_special_characters(df)["a"].tolist() == ["abc 123"]


class TestHandleMissingValues:
    def test_drop_removes_rows_with_any_missing_value(self, cleaner):
        df = pd.DataFrame({"a": ["1", None, "3"], "b": ["x", "y", None]})
        result = cleaner.handle_missing_values(df, strategy="drop")
        assert len(result) == 1

    def test_fill_replaces_missing_with_given_value(self, cleaner):
        df = pd.DataFrame({"a": ["1", None]})
        result = cleaner.handle_missing_values(df, strategy="fill", fill_value="MISSING")
        assert result["a"].tolist() == ["1", "MISSING"]

    def test_fill_defaults_to_empty_string(self, cleaner):
        df = pd.DataFrame({"a": ["1", None]})
        result = cleaner.handle_missing_values(df, strategy="fill")
        assert result["a"].tolist() == ["1", ""]

    def test_forward_fill_propagates_previous_value(self, cleaner):
        df = pd.DataFrame({"a": ["1", None, None, "4"]})
        assert cleaner.handle_missing_values(df, strategy="forward_fill")["a"].tolist() == [
            "1", "1", "1", "4"
        ]

    def test_backward_fill_propagates_next_value(self, cleaner):
        df = pd.DataFrame({"a": ["1", None, None, "4"]})
        assert cleaner.handle_missing_values(df, strategy="backward_fill")["a"].tolist() == [
            "1", "4", "4", "4"
        ]

    def test_invalid_strategy_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError):
            cleaner.handle_missing_values(df, strategy="nope")


class TestRemoveDuplicates:
    def test_keep_first_removes_later_occurrences(self, cleaner):
        df = pd.DataFrame({"a": ["1", "1", "2"]})
        result, removed = cleaner.remove_duplicates(df, keep="first")
        assert len(result) == 2
        assert removed == [1]

    def test_keep_last_removes_earlier_occurrences(self, cleaner):
        df = pd.DataFrame({"a": ["1", "1", "2"]})
        result, removed = cleaner.remove_duplicates(df, keep="last")
        assert removed == [0]

    def test_keep_false_removes_every_duplicate_occurrence(self, cleaner):
        df = pd.DataFrame({"a": ["1", "1", "2"]})
        result, removed = cleaner.remove_duplicates(df, keep=False)
        assert len(result) == 1
        assert set(removed) == {0, 1}

    def test_subset_restricts_comparison_columns(self, cleaner):
        df = pd.DataFrame({"a": ["1", "1"], "b": ["x", "y"]})
        result, removed = cleaner.remove_duplicates(df, subset=["a"])
        assert len(result) == 1

    def test_no_duplicates_removes_nothing(self, cleaner):
        df = pd.DataFrame({"a": ["1", "2", "3"]})
        result, removed = cleaner.remove_duplicates(df)
        assert len(result) == 3
        assert removed == []

    def test_invalid_keep_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError):
            cleaner.remove_duplicates(df, keep="invalid")


class TestValidateColumn:
    def test_valid_email_is_normalized(self, cleaner):
        df = pd.DataFrame({"email": ["John@Example.COM"]})
        result, issues = cleaner.validate_column(df, "email", "email")
        assert result["email"].tolist() == ["john@example.com"]
        assert issues == []

    def test_invalid_email_is_flagged_not_removed(self, cleaner):
        df = pd.DataFrame({"email": ["bob@example.com!!!"]})
        result, issues = cleaner.validate_column(df, "email", "email")
        assert result["email"].tolist() == ["bob@example.com!!!"]  # unchanged
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].issue_type == "invalid_format"

    def test_valid_phone_is_formatted(self, cleaner):
        df = pd.DataFrame({"phone": ["+14158586273"]})
        result, issues = cleaner.validate_column(df, "phone", "phone")
        assert result["phone"].tolist() == ["+14158586273"]
        assert issues == []

    def test_numeric_validation_does_not_rewrite_the_cell(self, cleaner):
        df = pd.DataFrame({"age": ["28"]})
        result, issues = cleaner.validate_column(df, "age", "numeric")
        assert result["age"].tolist() == ["28"]  # still the original string
        assert issues == []

    def test_invalid_numeric_is_flagged(self, cleaner):
        df = pd.DataFrame({"age": ["not-a-number"]})
        result, issues = cleaner.validate_column(df, "age", "numeric")
        assert len(issues) == 1

    def test_missing_values_are_skipped_not_flagged(self, cleaner):
        df = pd.DataFrame({"email": [None]})
        result, issues = cleaner.validate_column(df, "email", "email")
        assert issues == []

    def test_date_column_is_normalized_to_iso(self, cleaner):
        df = pd.DataFrame({"created": ["01/15/2023"]})
        result, issues = cleaner.validate_column(df, "created", "date")
        assert result["created"].tolist() == ["2023-01-15"]

    def test_unknown_column_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError):
            cleaner.validate_column(df, "zzz", "numeric")

    def test_unknown_validation_type_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError):
            cleaner.validate_column(df, "a", "currency")

    def test_validator_override_is_used_for_email(self):
        cleaner = CSVCleaner()  # no validators configured by default
        df = pd.DataFrame({"email": ["bob@example.com!!!"]})
        override = EmailValidator(check_mx=False)
        _, issues = cleaner.validate_column(df, "email", "email", validator=override)
        assert len(issues) == 1  # the strict validator catches it


class TestConvertDataTypes:
    def test_int_conversion(self, cleaner):
        df = pd.DataFrame({"age": ["28", "35"]})
        result, issues = cleaner.convert_data_types(df, {"age": "int"})
        assert result["age"].tolist() == [28, 35]
        assert issues == []

    def test_int_conversion_flags_non_whole_numbers(self, cleaner):
        df = pd.DataFrame({"age": ["28", "35.5"]})
        result, issues = cleaner.convert_data_types(df, {"age": "int"})
        assert len(issues) == 1
        assert issues[0].original_value == "35.5"

    def test_int_conversion_flags_non_numeric(self, cleaner):
        df = pd.DataFrame({"age": ["28", "bad"]})
        _, issues = cleaner.convert_data_types(df, {"age": "int"})
        assert len(issues) == 1
        assert issues[0].issue_type == "conversion_failed"

    def test_float_conversion_accepts_decimals(self, cleaner):
        df = pd.DataFrame({"price": ["19.99", "5"]})
        result, issues = cleaner.convert_data_types(df, {"price": "float"})
        assert result["price"].tolist() == [19.99, 5.0]
        assert issues == []

    def test_bool_conversion(self, cleaner):
        df = pd.DataFrame({"active": ["yes", "no", "maybe"]})
        result, issues = cleaner.convert_data_types(df, {"active": "bool"})
        assert result["active"].tolist()[:2] == [True, False]
        assert len(issues) == 1

    def test_datetime_conversion_handles_mixed_formats(self, cleaner):
        df = pd.DataFrame({"created": ["2023-01-15", "01/15/2023"]})
        result, issues = cleaner.convert_data_types(df, {"created": "datetime"})
        assert issues == []
        assert result["created"].notna().all()

    def test_datetime_conversion_flags_garbage(self, cleaner):
        df = pd.DataFrame({"created": ["2023-01-15", "garbage"]})
        _, issues = cleaner.convert_data_types(df, {"created": "datetime"})
        assert len(issues) == 1

    def test_str_conversion_always_succeeds(self, cleaner):
        df = pd.DataFrame({"a": ["1", "2"]})
        result, issues = cleaner.convert_data_types(df, {"a": "str"})
        assert issues == []

    def test_missing_values_are_not_flagged_as_failures(self, cleaner):
        df = pd.DataFrame({"age": ["28", None]})
        _, issues = cleaner.convert_data_types(df, {"age": "int"})
        assert issues == []

    def test_unknown_column_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError):
            cleaner.convert_data_types(df, {"zzz": "int"})

    def test_unsupported_type_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError):
            cleaner.convert_data_types(df, {"a": "complex128"})


class TestStandardizeColumnNames:
    def test_lowercases_and_underscores(self, cleaner):
        df = pd.DataFrame({"Full Name": [1], "E-Mail": [2]})
        assert cleaner.standardize_column_names(df).columns.tolist() == ["full_name", "e_mail"]

    def test_collisions_get_a_numeric_suffix(self, cleaner):
        df = pd.DataFrame({"Phone#": [1], "Phone!": [2]})
        columns = cleaner.standardize_column_names(df).columns.tolist()
        assert columns == ["phone", "phone_1"]
        assert len(set(columns)) == 2


class TestCleanWorkflow:
    """clean(): the full rule pipeline, using the sample fixture."""

    def test_sample_fixture_with_common_rules(self, cleaner):
        df = cleaner.load_csv(FIXTURE_CSV)
        rules = [
            CleaningRule(field="", rule_type="trim", parameters={}),
            CleaningRule(field="email", rule_type="validate_email", parameters={}),
            CleaningRule(field="", rule_type="remove_duplicates", parameters={}),
        ]
        result = cleaner.clean(df, rules)
        assert isinstance(result, CleaningResult)
        assert result.report.total_rows == 10
        assert result.report.processed_rows == 9  # one exact duplicate removed
        assert result.removed_rows

    def test_email_and_phone_issues_are_collected(self, cleaner):
        df = cleaner.load_csv(FIXTURE_CSV)
        rules = [
            CleaningRule(field="email", rule_type="validate_email", parameters={}),
            CleaningRule(field="phone", rule_type="validate_phone", parameters={}),
        ]
        result = cleaner.clean(df, rules)
        fields_with_issues = {issue.field for issue in result.report.issues}
        assert fields_with_issues == {"email", "phone"}

    def test_remove_empty_rows_true_drops_fully_blank_rows(self, cleaner):
        df = pd.DataFrame({"a": ["1", None], "b": ["x", None]})
        result = cleaner.clean(df, rules=[], remove_empty_rows=True)
        assert result.report.processed_rows == 1

    def test_remove_empty_rows_false_keeps_fully_blank_rows(self, cleaner):
        df = pd.DataFrame({"a": ["1", None], "b": ["x", None]})
        result = cleaner.clean(df, rules=[], remove_empty_rows=False)
        assert result.report.processed_rows == 2

    def test_empty_rules_list_still_scores_quality(self, cleaner):
        df = pd.DataFrame({"a": ["1", "2"]})
        result = cleaner.clean(df, rules=[])
        assert "quality_score_before" in result.summary
        assert "quality_score_after" in result.summary

    def test_empty_dataframe(self, cleaner):
        df = pd.DataFrame({"a": pd.Series([], dtype=str)})
        result = cleaner.clean(df, rules=[])
        assert result.report.total_rows == 0
        assert result.report.processed_rows == 0

    def test_unknown_rule_type_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError, match="Unknown rule_type"):
            cleaner.clean(df, rules=[CleaningRule(field="a", rule_type="teleport")])

    def test_non_list_rules_raises_cleaning_error(self, cleaner):
        df = pd.DataFrame({"a": ["1"]})
        with pytest.raises(CleaningError):
            cleaner.clean(df, rules="not-a-list")  # type: ignore[arg-type]

    def test_suggestions_mention_columns_still_missing_data(self, cleaner):
        df = pd.DataFrame({"a": ["1", None, None, None]})  # 75% missing
        result = cleaner.clean(df, rules=[], remove_empty_rows=False)
        assert any("a" in s for s in result.report.suggestions)

    def test_quality_score_improves_after_deduplication(self, cleaner):
        df = pd.DataFrame({"email": ["a@x.com", "a@x.com", "b@x.com"]})
        rules = [CleaningRule(field="", rule_type="remove_duplicates", parameters={})]
        result = cleaner.clean(df, rules)
        assert result.summary["quality_score_after"] >= result.summary["quality_score_before"]


class TestSaveResults:
    def test_writes_cleaned_csv(self, cleaner, tmp_path):
        df = cleaner.load_csv(FIXTURE_CSV)
        result = cleaner.clean(df, rules=[])
        out_csv = str(tmp_path / "out.csv")
        out_json = str(tmp_path / "report.json")
        cleaner.save_results(result, out_csv, out_json)

        written = pd.read_csv(out_csv)
        assert len(written) == len(result.cleaned_data)

    def test_writes_valid_json_report(self, cleaner, tmp_path):
        df = cleaner.load_csv(FIXTURE_CSV)
        result = cleaner.clean(df, rules=[])
        out_csv = str(tmp_path / "out.csv")
        out_json = str(tmp_path / "report.json")
        cleaner.save_results(result, out_csv, out_json)

        with open(out_json) as handle:
            data = json.load(handle)
        assert data["statistics"]["total_rows"] == 10
        assert "timestamp" in data

    def test_removed_rows_csv_contains_real_row_data(self, cleaner, tmp_path):
        df = cleaner.load_csv(FIXTURE_CSV)
        rules = [CleaningRule(field="", rule_type="remove_duplicates", parameters={})]
        result = cleaner.clean(df, rules)
        out_csv = str(tmp_path / "out.csv")
        out_json = str(tmp_path / "report.json")
        removed_csv = str(tmp_path / "removed.csv")
        cleaner.save_results(result, out_csv, out_json, removed_rows_csv=removed_csv)

        removed = pd.read_csv(removed_csv)
        assert len(removed) == len(result.removed_rows)
        assert "Bob Johnson" in removed["name"].tolist()

    def test_removed_rows_csv_is_empty_but_valid_when_nothing_removed(self, cleaner, tmp_path):
        df = pd.DataFrame({"a": ["1", "2"]})
        result = cleaner.clean(df, rules=[])
        out_csv = str(tmp_path / "out.csv")
        out_json = str(tmp_path / "report.json")
        removed_csv = str(tmp_path / "removed.csv")
        cleaner.save_results(result, out_csv, out_json, removed_rows_csv=removed_csv)

        removed = pd.read_csv(removed_csv)
        assert len(removed) == 0


class TestCSVCleanerConfiguration:
    def test_defaults(self):
        cleaner = CSVCleaner()
        assert cleaner.email_validator is None
        assert cleaner.phone_validator is None
        assert cleaner.remove_empty_rows is True

    def test_stores_injected_validators(self):
        email_validator = EmailValidator(check_mx=False)
        phone_validator = PhoneValidator()
        cleaner = CSVCleaner(email_validator, phone_validator)
        assert cleaner.email_validator is email_validator
        assert cleaner.phone_validator is phone_validator

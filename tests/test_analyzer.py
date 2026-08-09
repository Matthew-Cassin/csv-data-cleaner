"""Tests for csv_data_cleaner.analyzer."""

import pandas as pd
import pytest

from csv_data_cleaner.analyzer import DataAnalyzer


@pytest.fixture
def analyzer():
    return DataAnalyzer()


class TestDetectEncoding:
    def test_detects_ascii_for_plain_text(self, analyzer, tmp_path):
        path = tmp_path / "plain.csv"
        path.write_text("name,email\nAlice,alice@example.com\n", encoding="ascii")
        encoding = analyzer.detect_encoding(str(path))
        assert encoding.lower() in ("ascii", "utf-8")

    def test_detects_utf8_for_unicode_content(self, analyzer, tmp_path):
        path = tmp_path / "unicode.csv"
        path.write_text("name\nJosé García\n", encoding="utf-8")
        encoding = analyzer.detect_encoding(str(path))
        assert encoding is not None
        # Should be readable back with the detected encoding.
        with open(path, encoding=encoding) as handle:
            handle.read()

    def test_returns_a_string(self, analyzer, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("a,b\n1,2\n")
        assert isinstance(analyzer.detect_encoding(str(path)), str)


class TestAnalyzeDataTypes:
    def test_infers_numeric_column(self, analyzer):
        df = pd.DataFrame({"age": ["28", "35", "42"]})
        assert analyzer.analyze_data_types(df)["age"] == "numeric"

    def test_infers_email_column(self, analyzer):
        df = pd.DataFrame({"contact": ["a@example.com", "b@example.com", "c@example.com"]})
        assert analyzer.analyze_data_types(df)["contact"] == "email"

    def test_infers_boolean_column(self, analyzer):
        df = pd.DataFrame({"active": ["yes", "no", "yes", "no"]})
        assert analyzer.analyze_data_types(df)["active"] == "boolean"

    def test_infers_date_column_with_mixed_formats(self, analyzer):
        df = pd.DataFrame({"created": ["2023-01-15", "01/15/2023", "2023-02-20", "03/10/2023"]})
        assert analyzer.analyze_data_types(df)["created"] == "date"

    def test_infers_text_for_free_form_names(self, analyzer):
        df = pd.DataFrame({"name": ["John Smith", "Jane Doe", "Bob Johnson"]})
        assert analyzer.analyze_data_types(df)["name"] == "text"

    def test_mostly_invalid_phone_column_falls_back_to_text(self, analyzer):
        # Below the 80% match threshold because of "invalid-phone".
        df = pd.DataFrame({"phone": ["(555) 123-4567", "555-123-4567", "invalid-phone"]})
        assert analyzer.analyze_data_types(df)["phone"] == "text"

    def test_empty_column_is_text(self, analyzer):
        df = pd.DataFrame({"col": [None, None]})
        assert analyzer.analyze_data_types(df)["col"] == "text"

    def test_all_columns_present_in_result(self, analyzer):
        df = pd.DataFrame({"a": ["1"], "b": ["x"], "c": [None]})
        result = analyzer.analyze_data_types(df)
        assert set(result.keys()) == {"a", "b", "c"}

    def test_no_warnings_raised_for_mixed_date_formats(self, analyzer, recwarn):
        df = pd.DataFrame({"d": ["2023-01-15", "01/15/2023"]})
        analyzer.analyze_data_types(df)
        assert len(recwarn) == 0


class TestDetectMissingValues:
    def test_reports_fraction_missing_per_column(self, analyzer):
        df = pd.DataFrame({"a": ["1", None, "3", None]})
        assert analyzer.detect_missing_values(df)["a"] == 0.5

    def test_zero_for_fully_populated_column(self, analyzer):
        df = pd.DataFrame({"a": ["1", "2", "3"]})
        assert analyzer.detect_missing_values(df)["a"] == 0.0

    def test_empty_dataframe_reports_zero_for_every_column(self, analyzer):
        df = pd.DataFrame({"a": pd.Series([], dtype=str), "b": pd.Series([], dtype=str)})
        result = analyzer.detect_missing_values(df)
        assert result == {"a": 0.0, "b": 0.0}


class TestDetectDuplicates:
    def test_finds_full_row_duplicate(self, analyzer):
        df = pd.DataFrame({"a": ["1", "2", "1"], "b": ["x", "y", "x"]})
        assert analyzer.detect_duplicates(df) == [2]

    def test_first_occurrence_is_not_flagged(self, analyzer):
        df = pd.DataFrame({"a": ["1", "1"]})
        assert 0 not in analyzer.detect_duplicates(df)

    def test_no_duplicates_returns_empty_list(self, analyzer):
        df = pd.DataFrame({"a": ["1", "2", "3"]})
        assert analyzer.detect_duplicates(df) == []

    def test_subset_restricts_comparison_columns(self, analyzer):
        df = pd.DataFrame({"a": ["1", "1"], "b": ["x", "y"]})
        assert analyzer.detect_duplicates(df) == []
        assert analyzer.detect_duplicates(df, subset=["a"]) == [1]


class TestDetectOutliers:
    def test_finds_a_clear_outlier(self, analyzer):
        df = pd.DataFrame({"val": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "1000"]})
        outliers = analyzer.detect_outliers(df)
        assert outliers["val"] == [9]

    def test_no_outliers_for_uniform_data(self, analyzer):
        df = pd.DataFrame({"val": ["10", "11", "12", "13", "14"]})
        assert analyzer.detect_outliers(df) == {}

    def test_constant_column_has_no_outliers(self, analyzer):
        df = pd.DataFrame({"val": ["5", "5", "5", "5"]})
        assert analyzer.detect_outliers(df) == {}

    def test_non_numeric_column_is_skipped_by_default(self, analyzer):
        df = pd.DataFrame({"name": ["Alice", "Bob", "Carol"]})
        assert analyzer.detect_outliers(df) == {}

    def test_explicit_numeric_columns_are_respected(self, analyzer):
        df = pd.DataFrame({"val": ["1", "2", "3", "100"], "other": ["a", "b", "c", "d"]})
        outliers = analyzer.detect_outliers(df, numeric_columns=["val"])
        assert "val" in outliers
        assert "other" not in outliers

    def test_unknown_column_in_numeric_columns_is_ignored(self, analyzer):
        df = pd.DataFrame({"val": ["1", "2"]})
        assert analyzer.detect_outliers(df, numeric_columns=["does_not_exist"]) == {}


class TestGenerateQualityScore:
    def test_perfect_data_scores_1_0(self, analyzer):
        df = pd.DataFrame({"a": ["1", "2", "3"], "b": ["x", "y", "z"]})
        assert analyzer.generate_quality_score(df) == 1.0

    def test_empty_dataframe_scores_1_0(self, analyzer):
        assert analyzer.generate_quality_score(pd.DataFrame()) == 1.0

    def test_messy_data_scores_below_1_0(self, analyzer):
        df = pd.DataFrame({
            "email": ["a@example.com", "bad-email", "a@example.com"],
            "name": ["Alice", None, "Alice"],
        })
        assert analyzer.generate_quality_score(df) < 1.0

    def test_score_never_negative(self, analyzer):
        # Every signal maxed out: all missing, all duplicate, all invalid.
        df = pd.DataFrame({"email": [None, None, None]})
        assert analyzer.generate_quality_score(df) >= 0.0

    def test_score_is_a_native_python_float(self, analyzer):
        df = pd.DataFrame({"a": ["1", None, "3"]})
        score = analyzer.generate_quality_score(df)
        assert type(score) is float

    def test_worse_data_scores_lower_than_better_data(self, analyzer):
        clean_df = pd.DataFrame({"a": ["1", "2", "3"]})
        messy_df = pd.DataFrame({"a": ["1", None, None]})
        assert analyzer.generate_quality_score(messy_df) < analyzer.generate_quality_score(clean_df)

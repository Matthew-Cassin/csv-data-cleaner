"""Tests for csv_data_cleaner.models."""

import dataclasses
import json

import pandas as pd
import pytest

from csv_data_cleaner.models import (
    CleaningError,
    CleaningReport,
    CleaningResult,
    CleaningRule,
    DataQualityIssue,
    DataQualityReport,
)


def make_issue(row_index=0, field="email", issue_type="invalid_format"):
    return DataQualityIssue(
        row_index=row_index,
        field=field,
        issue_type=issue_type,
        original_value="bad@",
        cleaned_value=None,
        severity="error",
        message="not valid",
    )


class TestCleaningRule:
    def test_construction_keeps_all_fields(self):
        rule = CleaningRule(field="email", rule_type="validate_email", parameters={"x": 1})
        assert rule.field == "email"
        assert rule.rule_type == "validate_email"
        assert rule.parameters == {"x": 1}

    def test_parameters_defaults_to_empty_dict(self):
        rule = CleaningRule(field="name", rule_type="trim")
        assert rule.parameters == {}

    def test_default_parameters_not_shared_between_instances(self):
        first = CleaningRule(field="a", rule_type="trim")
        second = CleaningRule(field="b", rule_type="trim")
        first.parameters["x"] = 1
        assert second.parameters == {}


class TestDataQualityIssue:
    def test_construction_keeps_all_fields(self):
        issue = make_issue()
        assert issue.row_index == 0
        assert issue.field == "email"
        assert issue.issue_type == "invalid_format"
        assert issue.severity == "error"
        assert issue.cleaned_value is None

    def test_is_a_dataclass_with_the_documented_fields(self):
        field_names = {f.name for f in dataclasses.fields(DataQualityIssue)}
        assert field_names == {
            "row_index", "field", "issue_type", "original_value",
            "cleaned_value", "severity", "message",
        }


class TestCleaningReport:
    def test_minimal_construction_applies_defaults(self):
        report = CleaningReport(total_rows=0, processed_rows=0, rows_with_issues=0)
        assert report.issues == []
        assert report.columns_processed == {}
        assert report.suggestions == []

    def test_default_lists_not_shared_between_instances(self):
        first = CleaningReport(total_rows=0, processed_rows=0, rows_with_issues=0)
        second = CleaningReport(total_rows=0, processed_rows=0, rows_with_issues=0)
        first.issues.append(make_issue())
        first.suggestions.append("x")
        assert second.issues == []
        assert second.suggestions == []


class TestCleaningResult:
    def test_minimal_construction_applies_defaults(self):
        report = CleaningReport(total_rows=0, processed_rows=0, rows_with_issues=0)
        result = CleaningResult(cleaned_data=pd.DataFrame(), report=report)
        assert result.removed_rows == []
        assert result.summary == {}

    def test_holds_a_real_dataframe(self):
        df = pd.DataFrame({"a": [1, 2]})
        report = CleaningReport(total_rows=2, processed_rows=2, rows_with_issues=0)
        result = CleaningResult(cleaned_data=df, report=report)
        assert result.cleaned_data is df
        assert len(result.cleaned_data) == 2


class TestDataQualityReport:
    def _sample_result(self):
        df = pd.DataFrame({"email": ["a@b.com"]})
        report = CleaningReport(
            total_rows=2,
            processed_rows=1,
            rows_with_issues=1,
            issues=[make_issue()],
            columns_processed={"email": {"validate_email_issues": 1}},
            suggestions=["Review email column"],
        )
        return CleaningResult(
            cleaned_data=df,
            report=report,
            removed_rows=[1],
            summary={"quality_score_before": 0.8, "quality_score_after": 0.95},
        )

    def test_from_result_copies_statistics(self):
        quality = DataQualityReport.from_result(self._sample_result())
        assert quality.total_rows == 2
        assert quality.processed_rows == 1
        assert quality.rows_with_issues == 1
        assert quality.rows_removed == 1
        assert quality.quality_score_before == 0.8
        assert quality.quality_score_after == 0.95
        assert len(quality.issues) == 1
        assert quality.suggestions == ["Review email column"]

    def test_from_result_sets_an_iso_timestamp(self):
        from datetime import datetime

        quality = DataQualityReport.from_result(self._sample_result())
        datetime.fromisoformat(quality.timestamp)  # raises if malformed

    def test_from_result_defaults_missing_scores_to_zero(self):
        df = pd.DataFrame()
        report = CleaningReport(total_rows=0, processed_rows=0, rows_with_issues=0)
        result = CleaningResult(cleaned_data=df, report=report)  # no summary scores
        quality = DataQualityReport.from_result(result)
        assert quality.quality_score_before == 0.0
        assert quality.quality_score_after == 0.0

    def test_to_dict_has_expected_top_level_keys(self):
        data = DataQualityReport.from_result(self._sample_result()).to_dict()
        assert set(data.keys()) == {
            "timestamp", "statistics", "issues", "columns_processed", "suggestions"
        }

    def test_to_dict_statistics_block(self):
        data = DataQualityReport.from_result(self._sample_result()).to_dict()
        assert data["statistics"] == {
            "total_rows": 2,
            "processed_rows": 1,
            "rows_with_issues": 1,
            "rows_removed": 1,
            "quality_score_before": 0.8,
            "quality_score_after": 0.95,
        }

    def test_to_dict_expands_issues_to_plain_dicts(self):
        data = DataQualityReport.from_result(self._sample_result()).to_dict()
        assert data["issues"][0]["field"] == "email"
        assert data["issues"][0]["severity"] == "error"

    def test_to_dict_is_json_serializable(self):
        data = DataQualityReport.from_result(self._sample_result()).to_dict()
        json.dumps(data)  # raises if not serializable


class TestCleaningError:
    def test_is_an_exception_subclass(self):
        assert issubclass(CleaningError, Exception)

    def test_raises_and_preserves_message(self):
        with pytest.raises(CleaningError, match="boom"):
            raise CleaningError("boom")

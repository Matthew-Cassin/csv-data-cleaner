"""Tests for csv_data_cleaner.validators."""

import pytest
from email_phone_validator import EmailValidator, PhoneValidator

from csv_data_cleaner.validators import FieldValidator


@pytest.fixture
def basic():
    return FieldValidator()


@pytest.fixture
def full():
    return FieldValidator(EmailValidator(check_mx=False), PhoneValidator())


class TestValidateNumeric:
    def test_valid_integer_string(self, basic):
        assert basic.validate_numeric("42") == (True, 42.0)

    def test_valid_float_string(self, basic):
        assert basic.validate_numeric("42.5") == (True, 42.5)

    def test_valid_negative_number(self, basic):
        assert basic.validate_numeric("-3.5") == (True, -3.5)

    def test_whitespace_is_stripped(self, basic):
        assert basic.validate_numeric("  28  ") == (True, 28.0)

    def test_invalid_non_numeric_text(self, basic):
        assert basic.validate_numeric("not-a-number") == (False, None)

    def test_none_is_invalid(self, basic):
        assert basic.validate_numeric(None) == (False, None)

    def test_empty_string_is_invalid(self, basic):
        assert basic.validate_numeric("") == (False, None)


class TestValidateBoolean:
    @pytest.mark.parametrize(
        "value,expected", [
            ("true", True), ("TRUE", True), ("yes", True), ("1", True),
            ("on", True), ("t", True), ("y", True),
            ("false", False), ("no", False), ("0", False),
            ("off", False), ("f", False), ("n", False),
        ],
    )
    def test_recognized_values(self, basic, value, expected):
        assert basic.validate_boolean(value) == (True, expected)

    def test_unrecognized_value_is_invalid(self, basic):
        assert basic.validate_boolean("maybe") == (False, None)

    def test_none_is_invalid(self, basic):
        assert basic.validate_boolean(None) == (False, None)

    def test_whitespace_and_case_insensitive(self, basic):
        assert basic.validate_boolean("  YES  ") == (True, True)


class TestValidateDate:
    def test_iso_format(self, basic):
        assert basic.validate_date("2023-01-15") == (True, "2023-01-15")

    def test_us_slash_format(self, basic):
        assert basic.validate_date("01/15/2023") == (True, "2023-01-15")

    def test_dash_format(self, basic):
        assert basic.validate_date("01-15-2023") == (True, "2023-01-15")

    def test_explicit_format_used_when_given(self, basic):
        assert basic.validate_date("15/01/2023", format="%d/%m/%Y") == (True, "2023-01-15")

    def test_explicit_format_rejects_non_matching_value(self, basic):
        assert basic.validate_date("2023-01-15", format="%d/%m/%Y") == (False, None)

    def test_garbage_is_invalid(self, basic):
        assert basic.validate_date("not-a-date") == (False, None)

    def test_none_is_invalid(self, basic):
        assert basic.validate_date(None) == (False, None)

    def test_empty_string_is_invalid(self, basic):
        assert basic.validate_date("") == (False, None)


class TestValidateUrl:
    def test_https_url_is_valid(self, basic):
        is_valid, normalized = basic.validate_url("https://example.com/path")
        assert is_valid is True
        assert normalized == "https://example.com/path"

    def test_scheme_and_host_are_lowercased(self, basic):
        _, normalized = basic.validate_url("HTTPS://Example.COM/Path")
        assert normalized == "https://example.com/Path"

    def test_ftp_scheme_is_valid(self, basic):
        assert basic.validate_url("ftp://files.example.com")[0] is True

    def test_missing_scheme_is_invalid(self, basic):
        assert basic.validate_url("example.com") == (False, None)

    def test_plain_text_is_invalid(self, basic):
        assert basic.validate_url("not a url") == (False, None)

    def test_none_is_invalid(self, basic):
        assert basic.validate_url(None) == (False, None)


class TestValidateEmail:
    def test_basic_fallback_accepts_well_formed_email(self, basic):
        assert basic.validate_email("user@example.com") == (True, "user@example.com")

    def test_basic_fallback_rejects_trailing_junk(self, basic):
        # The real validator's job -- the basic fallback is deliberately
        # tighter than a naive "contains @" check but not exhaustive.
        assert basic.validate_email("bob@example.com!!!") == (False, None)

    def test_basic_fallback_rejects_malformed(self, basic):
        assert basic.validate_email("not-an-email") == (False, None)

    def test_full_validator_rejects_trailing_junk(self, full):
        assert full.validate_email("bob@example.com!!!") == (False, None)

    def test_full_validator_normalizes_case(self, full):
        assert full.validate_email("John@Example.COM") == (True, "john@example.com")

    def test_none_is_invalid(self, basic):
        assert basic.validate_email(None) == (False, None)

    def test_empty_string_is_invalid(self, basic):
        assert basic.validate_email("") == (False, None)


class TestValidatePhone:
    def test_basic_fallback_accepts_plausible_digit_count(self, basic):
        is_valid, formatted = basic.validate_phone("(555) 123-4567")
        assert is_valid is True
        assert formatted == "5551234567"

    def test_basic_fallback_rejects_too_short(self, basic):
        assert basic.validate_phone("123") == (False, None)

    def test_basic_fallback_rejects_non_numeric(self, basic):
        assert basic.validate_phone("invalid-phone") == (False, None)

    def test_full_validator_formats_a_valid_number(self, full):
        is_valid, formatted = full.validate_phone("+14158586273")
        assert is_valid is True
        assert formatted == "+14158586273"

    def test_full_validator_rejects_fictional_area_code(self, full):
        # Area code 555 is reserved/fictional, not a real assigned US
        # area code -- correctly invalid despite the right shape.
        assert full.validate_phone("(555) 123-4567")[0] is False

    def test_full_validator_respects_country_argument(self, full):
        is_valid, formatted = full.validate_phone("020 7031 3000", country="GB")
        assert is_valid is True
        assert formatted == "+442070313000"

    def test_none_is_invalid(self, basic):
        assert basic.validate_phone(None) == (False, None)

    def test_empty_string_is_invalid(self, basic):
        assert basic.validate_phone("") == (False, None)


class TestFieldValidatorConstruction:
    def test_defaults_to_no_validators(self):
        validator = FieldValidator()
        assert validator.email_validator is None
        assert validator.phone_validator is None

    def test_stores_injected_validators(self):
        email_validator = EmailValidator(check_mx=False)
        phone_validator = PhoneValidator()
        validator = FieldValidator(email_validator, phone_validator)
        assert validator.email_validator is email_validator
        assert validator.phone_validator is phone_validator

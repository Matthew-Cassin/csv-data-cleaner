"""Per-value field validation and normalization.

:class:`FieldValidator` checks and normalizes a single raw string value
at a time -- numeric, boolean, date, URL, email, or phone -- returning
``(is_valid, normalized_value)`` rather than raising, since an invalid
value is normal, expected input for a data-cleaning tool. Email and
phone validation delegate to injected ``email-phone-validator`` instances
when available, falling back to a basic format check when not.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse

from .logger import get_logger

logger = get_logger("validators")

__all__ = ["FieldValidator"]

_BOOL_MAP = {
    "true": True,
    "false": False,
    "yes": True,
    "no": False,
    "1": True,
    "0": False,
    "on": True,
    "off": False,
    "t": True,
    "f": False,
    "y": True,
    "n": False,
}

# Tried in order for validate_date when no explicit format is given.
# Ambiguous formats (e.g. day-first vs month-first) are inherently
# lossy without locale context -- month-first (US) is tried before
# day-first, so "01/02/2023" reads as January 2nd, not February 1st.
# See the README's Limitations section.
_DATE_FORMATS: Tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
)

_BASIC_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)*\.[a-zA-Z]{2,}$")
_URL_SCHEMES = ("http", "https", "ftp")


class FieldValidator:
    """Validates and normalizes individual field values.

    Args:
        email_validator: An
            :class:`~email_phone_validator.EmailValidator` instance to
            delegate email validation to. If ``None``, :meth:`validate_email`
            falls back to a basic format check with no normalization
            beyond lowercasing.
        phone_validator: A
            :class:`~email_phone_validator.PhoneValidator` instance to
            delegate phone validation to. If ``None``, :meth:`validate_phone`
            falls back to a digit-count check with no E.164 formatting.

    Example:
        >>> validator = FieldValidator()
        >>> validator.validate_numeric("42.5")
        (True, 42.5)
        >>> validator.validate_boolean("yes")
        (True, True)
    """

    def __init__(self, email_validator=None, phone_validator=None) -> None:
        self.email_validator = email_validator
        self.phone_validator = phone_validator

    def validate_numeric(self, value: object) -> Tuple[bool, Optional[float]]:
        """Check whether a value converts cleanly to a number.

        Args:
            value: The raw value to check.

        Returns:
            ``(True, float_value)`` if ``value`` parses as a number
            (int or float syntax both accepted); ``(False, None)``
            otherwise, including for ``None`` or an empty/whitespace
            string.
        """
        if value is None:
            return False, None
        candidate = str(value).strip()
        if not candidate:
            return False, None
        try:
            return True, float(candidate)
        except ValueError:
            return False, None

    def validate_boolean(self, value: object) -> Tuple[bool, Optional[bool]]:
        """Check whether a value is a recognizable boolean.

        Accepts (case-insensitively): ``true``/``false``, ``yes``/``no``,
        ``1``/``0``, ``on``/``off``, ``t``/``f``, ``y``/``n``.

        Args:
            value: The raw value to check.

        Returns:
            ``(True, bool_value)`` if recognized; ``(False, None)``
            otherwise.
        """
        if value is None:
            return False, None
        candidate = str(value).strip().lower()
        if candidate in _BOOL_MAP:
            return True, _BOOL_MAP[candidate]
        return False, None

    def validate_date(
        self, value: object, format: Optional[str] = None  # noqa: A002 - matches spec's param name
    ) -> Tuple[bool, Optional[str]]:
        """Check whether a value is a recognizable date, and normalize it.

        Args:
            value: The raw value to check.
            format: A ``datetime.strptime``-compatible format string to
                require. If omitted, several common formats are tried in
                turn (see the module's ``_DATE_FORMATS``).

        Returns:
            ``(True, iso_date_string)`` (``"YYYY-MM-DD"``) if a format
            matched; ``(False, None)`` otherwise.
        """
        if value is None:
            return False, None
        candidate = str(value).strip()
        if not candidate:
            return False, None

        formats = (format,) if format else _DATE_FORMATS
        for fmt in formats:
            try:
                parsed = datetime.strptime(candidate, fmt)
            except ValueError:
                continue
            return True, parsed.strftime("%Y-%m-%d")
        return False, None

    def validate_url(self, value: object) -> Tuple[bool, Optional[str]]:
        """Check whether a value is a well-formed, absolute URL.

        Requires an explicit ``http``, ``https``, or ``ftp`` scheme and a
        network location containing a dot (a bare ``"example.com"`` with
        no scheme is not accepted, to avoid false positives on ordinary
        text that happens to contain a dot).

        Args:
            value: The raw value to check.

        Returns:
            ``(True, normalized_url)`` with the scheme and host
            lowercased if valid; ``(False, None)`` otherwise.
        """
        if value is None:
            return False, None
        candidate = str(value).strip()
        if not candidate:
            return False, None

        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in _URL_SCHEMES or "." not in parsed.netloc:
            return False, None

        normalized = urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )
        return True, normalized

    def validate_email(self, value: object) -> Tuple[bool, Optional[str]]:
        """Check whether a value is a valid email address.

        Args:
            value: The raw value to check.

        Returns:
            ``(True, normalized_email)`` if valid; ``(False, None)``
            otherwise. Uses ``self.email_validator`` (format + optional
            MX checking) when available; otherwise falls back to a basic
            ``local@domain.tld`` shape check with simple lowercasing.
        """
        if value is None:
            return False, None
        candidate = str(value).strip()
        if not candidate:
            return False, None

        if self.email_validator is not None:
            result = self.email_validator.validate(candidate)
            if result.is_valid:
                return True, result.formatted
            return False, None

        if _BASIC_EMAIL_PATTERN.match(candidate):
            return True, candidate.lower()
        return False, None

    def validate_phone(self, value: object, country: str = "US") -> Tuple[bool, Optional[str]]:
        """Check whether a value is a valid phone number.

        Args:
            value: The raw value to check.
            country: ISO region code used when ``value`` has no ``+``
                country-code prefix. Ignored by the basic fallback (when
                no ``phone_validator`` was injected).

        Returns:
            ``(True, formatted_phone)`` if valid; ``(False, None)``
            otherwise. Uses ``self.phone_validator`` (E.164 formatting,
            international support) when available; otherwise falls back
            to a digit-count check (7-15 digits) with no reformatting.
        """
        if value is None:
            return False, None
        candidate = str(value).strip()
        if not candidate:
            return False, None

        if self.phone_validator is not None:
            result = self.phone_validator.validate(candidate, country=country)
            if result.is_valid:
                return True, result.formatted
            return False, None

        digits = re.sub(r"\D", "", candidate)
        if 7 <= len(digits) <= 15:
            return True, digits
        return False, None

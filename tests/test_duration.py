"""
时长（有效期）解析与格式化测试。
"""

import pytest

from luckperms.duration import DurationParseError, format_duration, parse_duration


class TestParseDuration:
    def test_plain_seconds(self):
        assert parse_duration("30") == 30

    def test_single_units(self):
        assert parse_duration("1s") == 1
        assert parse_duration("1m") == 60
        assert parse_duration("1h") == 3_600
        assert parse_duration("1d") == 86_400
        assert parse_duration("1w") == 604_800
        assert parse_duration("1mo") == 2_592_000
        assert parse_duration("1y") == 31_536_000

    def test_combined_units(self):
        assert parse_duration("1d2h3m4s") == 86_400 + 7_200 + 180 + 4

    def test_combined_with_month(self):
        expected = 2_592_000 + 3 * 86_400 + 13 * 3_600 + 45 * 60
        assert parse_duration("1mo3d13h45m") == expected

    def test_whitespace_tolerated(self):
        assert parse_duration("1d 2h") == 86_400 + 7_200

    def test_case_insensitive(self):
        assert parse_duration("PERMANENT") is None
        assert parse_duration("1D") == 86_400

    def test_permanent_keywords(self):
        assert parse_duration("permanent") is None
        assert parse_duration("forever") is None
        assert parse_duration("never") is None

    def test_unix_timestamp(self):
        now = 1_700_000_000.0
        assert parse_duration(str(int(now + 120)), now=now) == 120

    def test_expired_timestamp(self):
        now = 1_700_000_000.0
        with pytest.raises(DurationParseError):
            parse_duration(str(int(now - 100)), now=now)

    @pytest.mark.parametrize("value", ["", "   ", "abc", "1x", "0", "d", "1d2"])
    def test_invalid_values(self, value):
        with pytest.raises(DurationParseError):
            parse_duration(value)

    def test_none_rejected(self):
        with pytest.raises(DurationParseError):
            parse_duration(None)  # type: ignore[arg-type]


class TestFormatDuration:
    def test_permanent(self):
        assert format_duration(None) == "Never"

    def test_expired(self):
        assert format_duration(0) == "expired"
        assert format_duration(-5) == "expired"

    def test_days_hours_minutes(self):
        assert format_duration(86_400 + 7_200 + 180) == "1d 2h 3m"

    def test_seconds_only(self):
        assert format_duration(45) == "45s"

    def test_roundtrip_with_parse(self):
        assert format_duration(parse_duration("2h30m")) == "2h 30m"

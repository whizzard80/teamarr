"""Tests for Gold Zone stream date disambiguation."""

from datetime import date
from unittest.mock import patch

import pytest

from teamarr.consumers.gold_zone import (
    _resolve_day_number_to_date,
    _stream_date_check,
)


class TestResolveDayNumberToDate:
    """Test Day ## → calendar date mapping for Milano-Cortina 2026."""

    def test_day_1_is_feb_7(self):
        assert _resolve_day_number_to_date("Gold Zone Day 1") == date(2026, 2, 7)

    def test_day_7_is_feb_13(self):
        assert _resolve_day_number_to_date("Gold Zone Day 7") == date(2026, 2, 13)

    def test_day_15_is_feb_21(self):
        assert _resolve_day_number_to_date("Gold Zone Day 15") == date(2026, 2, 21)

    def test_day_17_is_feb_23(self):
        assert _resolve_day_number_to_date("Gold Zone Day 17") == date(2026, 2, 23)

    def test_day_0_out_of_range(self):
        assert _resolve_day_number_to_date("Gold Zone Day 0") is None

    def test_day_18_out_of_range(self):
        assert _resolve_day_number_to_date("Gold Zone Day 18") is None

    def test_no_day_pattern(self):
        assert _resolve_day_number_to_date("Gold Zone") is None

    def test_no_day_with_time(self):
        assert _resolve_day_number_to_date("Gold Zone @ 1:00 PM ET") is None

    def test_case_insensitive(self):
        assert _resolve_day_number_to_date("Gold Zone DAY 3") == date(2026, 2, 9)

    def test_day_in_middle_of_name(self):
        assert _resolve_day_number_to_date("Winter Olympics 25: Gold Zone Day 10 @ 3 PM") == date(2026, 2, 16)


class TestStreamDateCheck:
    """Test stream date disambiguation logic."""

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_day_number_matches_active_day(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 13)  # Day 7
        ok, date_str = _stream_date_check("Gold Zone Day 7")
        assert ok is True
        assert date_str == "2026-02-13"

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_day_number_does_not_match(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 14)  # Day 8
        ok, date_str = _stream_date_check("Gold Zone Day 7")
        assert ok is False
        assert date_str == "2026-02-13"

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_calendar_date_matches(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 13)
        ok, date_str = _stream_date_check("Gold Zone Feb 13 @ 1:00 PM ET")
        assert ok is True
        assert date_str == "2026-02-13"

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_calendar_date_does_not_match(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 14)
        ok, date_str = _stream_date_check("Gold Zone Feb 13 @ 1:00 PM ET")
        assert ok is False
        assert date_str == "2026-02-13"

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_no_date_includes_stream(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 13)
        ok, date_str = _stream_date_check("Gold Zone")
        assert ok is True
        assert date_str is None

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_no_date_with_time_includes_stream(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 13)
        ok, date_str = _stream_date_check("Gold Zone @ 1:00 PM ET")
        assert ok is True
        assert date_str is None

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_slash_date_matches(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 13)
        ok, date_str = _stream_date_check("Gold Zone 2/13")
        assert ok is True
        assert date_str == "2026-02-13"

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_slash_date_does_not_match(self, mock_active_day):
        mock_active_day.return_value = date(2026, 2, 14)
        ok, date_str = _stream_date_check("Gold Zone 2/13")
        assert ok is False
        assert date_str == "2026-02-13"

    @patch("teamarr.consumers.gold_zone._get_active_day")
    def test_day_number_takes_priority_over_ambiguous_date(self, mock_active_day):
        """Day ## should be resolved first, even if the name also has a date-like pattern."""
        mock_active_day.return_value = date(2026, 2, 13)  # Day 7
        # "Day 7" resolves to Feb 13, which matches
        ok, date_str = _stream_date_check("Gold Zone Day 7 2/12")
        assert ok is True
        assert date_str == "2026-02-13"

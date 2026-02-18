"""Tests for single-mode vs multi-mode league scoping (epic rs6, GitHub #149).

Single-mode groups (group_mode='single') should only search the one configured
league, not all 287+ known leagues. Multi-mode groups search broadly and filter.
"""

from unittest.mock import MagicMock, patch

from teamarr.database.groups import EventEPGGroup


class TestLeagueScopingByGroupMode:
    """Verify _match_streams passes correct search_leagues based on group_mode."""

    def _make_processor(self):
        """Create a minimal EventGroupProcessor with mocked dependencies."""
        with patch(
            "teamarr.consumers.event_group_processor.EventGroupProcessor.__init__",
            return_value=None,
        ):
            from teamarr.consumers.event_group_processor import EventGroupProcessor

            proc = EventGroupProcessor()
            proc._service = MagicMock()
            proc._db_factory = MagicMock()
            proc._shared_events = {}
            proc._generation = 1

            # Mock DB query for include_final_events
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchone.return_value = {
                "include_final_events": 0
            }
            proc._db_factory.return_value = mock_conn

            # Mock cached helpers
            proc._load_sport_durations_cached = MagicMock(return_value={})
            proc._get_all_known_leagues = MagicMock(
                return_value=["nfl", "nba", "college-softball", "mens-college-basketball"]
            )

            return proc

    def _make_group(self, group_mode: str, leagues: list[str]) -> EventEPGGroup:
        """Create a minimal EventEPGGroup."""
        return EventEPGGroup(
            id=1,
            name="Test Group",
            leagues=leagues,
            group_mode=group_mode,
        )

    @patch("teamarr.consumers.event_group_processor.StreamMatcher")
    def test_single_mode_searches_only_configured_league(self, MockMatcher):
        """Single-mode group should pass only its configured league as search_leagues."""
        proc = self._make_processor()
        group = self._make_group("single", ["college-softball"])

        mock_instance = MagicMock()
        mock_instance.match_all.return_value = MagicMock(results=[])
        MockMatcher.return_value = mock_instance

        from datetime import date

        proc._match_streams([], group, date(2026, 2, 12))

        # StreamMatcher should be constructed with search_leagues = configured leagues only
        call_kwargs = MockMatcher.call_args.kwargs
        assert call_kwargs["search_leagues"] == ["college-softball"]
        assert call_kwargs["include_leagues"] == ["college-softball"]

    @patch("teamarr.consumers.event_group_processor.StreamMatcher")
    def test_multi_mode_searches_all_known_leagues(self, MockMatcher):
        """Multi-mode group should pass all known leagues as search_leagues."""
        proc = self._make_processor()
        group = self._make_group("multi", ["nfl", "nba"])

        mock_instance = MagicMock()
        mock_instance.match_all.return_value = MagicMock(results=[])
        MockMatcher.return_value = mock_instance

        from datetime import date

        proc._match_streams([], group, date(2026, 2, 12))

        call_kwargs = MockMatcher.call_args.kwargs
        # Multi-mode: search_leagues = all known leagues (from _get_all_known_leagues)
        assert call_kwargs["search_leagues"] == [
            "nfl", "nba", "college-softball", "mens-college-basketball"
        ]
        # include_leagues = only the group's configured leagues
        assert call_kwargs["include_leagues"] == ["nfl", "nba"]

    @patch("teamarr.consumers.event_group_processor.StreamMatcher")
    def test_multi_mode_with_single_league_still_searches_all(self, MockMatcher):
        """Multi-mode group with 1 league should still search all known leagues."""
        proc = self._make_processor()
        # User explicitly chose multi-mode even with one league
        group = self._make_group("multi", ["nfl"])

        mock_instance = MagicMock()
        mock_instance.match_all.return_value = MagicMock(results=[])
        MockMatcher.return_value = mock_instance

        from datetime import date

        proc._match_streams([], group, date(2026, 2, 12))

        call_kwargs = MockMatcher.call_args.kwargs
        assert call_kwargs["search_leagues"] == [
            "nfl", "nba", "college-softball", "mens-college-basketball"
        ]
        assert call_kwargs["include_leagues"] == ["nfl"]

    @patch("teamarr.consumers.event_group_processor.StreamMatcher")
    def test_single_mode_with_resolved_leagues(self, MockMatcher):
        """Single-mode group with resolved_leagues (child group) uses resolved leagues."""
        proc = self._make_processor()
        group = self._make_group("single", ["college-softball"])

        mock_instance = MagicMock()
        mock_instance.match_all.return_value = MagicMock(results=[])
        MockMatcher.return_value = mock_instance

        from datetime import date

        # Child group inherits resolved_leagues from parent
        proc._match_streams(
            [], group, date(2026, 2, 12), resolved_leagues=["nba"]
        )

        call_kwargs = MockMatcher.call_args.kwargs
        # Single-mode: search_leagues = resolved_leagues (inherited)
        assert call_kwargs["search_leagues"] == ["nba"]
        assert call_kwargs["include_leagues"] == ["nba"]

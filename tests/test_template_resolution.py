"""Test template resolution for managed templates.

Validates that get_template_for_event correctly resolves templates
based on specificity: leagues > sports > default.
"""

import sqlite3
import pytest


@pytest.fixture
def test_db():
    """Create an in-memory database with test schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Create minimal schema
    conn.executescript("""
        CREATE TABLE templates (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE event_epg_groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            template_id INTEGER
        );

        CREATE TABLE group_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            template_id INTEGER NOT NULL,
            sports JSON,
            leagues JSON
        );
    """)

    # Insert test templates
    conn.executescript("""
        INSERT INTO templates (id, name) VALUES
            (1, 'Default Template'),
            (2, 'Soccer Template'),
            (3, 'UFC Template'),
            (4, 'NFL Template'),
            (5, 'Combat Sports Template');

        INSERT INTO event_epg_groups (id, name, template_id) VALUES
            (1, 'Multi-Sport Group', NULL),
            (2, 'Legacy Group', 1);
    """)

    yield conn
    conn.close()


class TestTemplateResolution:
    """Tests for get_template_for_event function."""

    def test_league_match_has_highest_priority(self, test_db):
        """League-specific template should take priority over sport and default."""
        from teamarr.database.groups import add_group_template, get_template_for_event

        # Add templates: default, sport-level, and league-level
        add_group_template(test_db, group_id=1, template_id=1)  # Default
        add_group_template(test_db, group_id=1, template_id=5, sports=["mma"])  # Sport
        add_group_template(test_db, group_id=1, template_id=3, leagues=["ufc"])  # League

        # UFC event should match league-specific template
        result = get_template_for_event(test_db, group_id=1, event_sport="mma", event_league="ufc")
        assert result == 3, "League-specific template should take priority"

    def test_sport_match_over_default(self, test_db):
        """Sport-specific template should take priority over default."""
        from teamarr.database.groups import add_group_template, get_template_for_event

        # Add templates: default and sport-level
        add_group_template(test_db, group_id=1, template_id=1)  # Default
        add_group_template(test_db, group_id=1, template_id=2, sports=["soccer"])  # Sport

        # Soccer event (EPL) should match sport-specific template
        result = get_template_for_event(test_db, group_id=1, event_sport="soccer", event_league="eng.1")
        assert result == 2, "Sport-specific template should take priority over default"

    def test_default_when_no_specific_match(self, test_db):
        """Default template should be used when no specific match."""
        from teamarr.database.groups import add_group_template, get_template_for_event

        # Add templates: default and league-level for different league
        add_group_template(test_db, group_id=1, template_id=1)  # Default
        add_group_template(test_db, group_id=1, template_id=4, leagues=["nfl"])  # NFL only

        # NBA event should fall back to default (no NBA-specific template)
        result = get_template_for_event(test_db, group_id=1, event_sport="basketball", event_league="nba")
        assert result == 1, "Default template should be used when no specific match"

    def test_multiple_leagues_in_one_assignment(self, test_db):
        """Template with multiple leagues should match any of them."""
        from teamarr.database.groups import add_group_template, get_template_for_event

        # Add template for multiple soccer leagues
        add_group_template(test_db, group_id=1, template_id=1)  # Default
        add_group_template(
            test_db, group_id=1, template_id=2,
            leagues=["eng.1", "esp.1", "ger.1", "ita.1", "fra.1"]
        )

        # All should match the soccer template
        assert get_template_for_event(test_db, 1, "soccer", "eng.1") == 2
        assert get_template_for_event(test_db, 1, "soccer", "esp.1") == 2
        assert get_template_for_event(test_db, 1, "soccer", "ger.1") == 2

        # MLS not in list, should fall back to default
        assert get_template_for_event(test_db, 1, "soccer", "usa.1") == 1

    def test_legacy_template_id_fallback(self, test_db):
        """Group with legacy template_id but no group_templates should use it."""
        from teamarr.database.groups import get_template_for_event

        # Group 2 has legacy template_id=1, no group_templates
        result = get_template_for_event(test_db, group_id=2, event_sport="any", event_league="any")
        assert result == 1, "Legacy template_id should be used when no group_templates"

    def test_no_template_configured(self, test_db):
        """Group with no template configuration should return None."""
        from teamarr.database.groups import get_template_for_event

        # Create group with no template
        test_db.execute("INSERT INTO event_epg_groups (id, name) VALUES (3, 'No Template Group')")

        result = get_template_for_event(test_db, group_id=3, event_sport="any", event_league="any")
        assert result is None, "Should return None when no template configured"

    def test_empty_sport_league_in_event(self, test_db):
        """Events with empty sport/league should only match default."""
        from teamarr.database.groups import add_group_template, get_template_for_event

        add_group_template(test_db, group_id=1, template_id=1)  # Default
        add_group_template(test_db, group_id=1, template_id=4, leagues=["nfl"])

        # Event with empty league should match default
        result = get_template_for_event(test_db, group_id=1, event_sport="", event_league="")
        assert result == 1, "Empty sport/league should match default"

    def test_sport_and_league_on_same_assignment(self, test_db):
        """Assignment with both sport and league should match by league first."""
        from teamarr.database.groups import add_group_template, get_template_for_event

        # This shouldn't happen in practice, but test the priority
        add_group_template(test_db, group_id=1, template_id=1)  # Default
        add_group_template(
            test_db, group_id=1, template_id=2,
            sports=["mma"], leagues=["ufc"]
        )

        # UFC should match (league takes priority in resolution)
        result = get_template_for_event(test_db, 1, "mma", "ufc")
        assert result == 2

        # Bellator (different league) should try sport match
        result = get_template_for_event(test_db, 1, "mma", "bellator")
        # Note: Current implementation checks leagues first across ALL templates,
        # then sports. So this might match via sport.
        assert result == 2, "Should match via sport when league doesn't match"


class TestTemplateResolutionIntegration:
    """Integration tests using real database functions."""

    def test_full_workflow(self, test_db):
        """Test complete workflow: create templates, assign, resolve."""
        from teamarr.database.groups import (
            add_group_template,
            get_group_templates,
            get_template_for_event,
        )

        # Setup: Add various template assignments
        add_group_template(test_db, 1, template_id=1)  # Default
        add_group_template(test_db, 1, template_id=2, sports=["soccer"])
        add_group_template(test_db, 1, template_id=3, leagues=["ufc"])
        add_group_template(test_db, 1, template_id=4, leagues=["nfl", "ncaaf"])

        # Verify assignments were created
        assignments = get_group_templates(test_db, 1)
        assert len(assignments) == 4

        # Test resolution for various events
        test_cases = [
            # (sport, league, expected_template, description)
            ("mma", "ufc", 3, "UFC gets UFC template"),
            ("mma", "bellator", 1, "Bellator falls back to default"),
            ("soccer", "eng.1", 2, "EPL gets soccer template"),
            ("soccer", "usa.1", 2, "MLS gets soccer template"),
            ("football", "nfl", 4, "NFL gets NFL template"),
            ("football", "ncaaf", 4, "NCAAF gets NFL template"),
            ("basketball", "nba", 1, "NBA falls back to default"),
        ]

        for sport, league, expected, desc in test_cases:
            result = get_template_for_event(test_db, 1, sport, league)
            assert result == expected, f"Failed: {desc} - got {result}, expected {expected}"

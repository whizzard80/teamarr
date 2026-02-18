"""Tests for exception keyword EPG uniqueness (teamarrv2-a6b).

Verifies that:
1. generate_event_tvg_id produces unique IDs per exception keyword
2. slugify_keyword sanitizes labels correctly
3. TemplateContext extra_vars override registered extractors
4. Backward compatibility: no keyword = unchanged tvg-id
"""

from unittest.mock import patch

import pytest

from teamarr.consumers.lifecycle.types import generate_event_tvg_id, slugify_keyword
from teamarr.templates.context import TemplateContext, TeamChannelContext
from teamarr.templates.resolver import TemplateResolver


# =============================================================================
# SLUGIFY KEYWORD
# =============================================================================


class TestSlugifyKeyword:
    """Test keyword → slug conversion for tvg-id safety."""

    def test_simple_word(self):
        assert slugify_keyword("Spanish") == "spanish"

    def test_multi_word(self):
        assert slugify_keyword("Peyton and Eli") == "peyton-and-eli"

    def test_alphanumeric(self):
        assert slugify_keyword("4K HDR") == "4k-hdr"

    def test_parenthesized(self):
        assert slugify_keyword("(ESP)") == "esp"

    def test_leading_trailing_whitespace(self):
        assert slugify_keyword("  French  ") == "french"

    def test_special_chars(self):
        assert slugify_keyword("En Español") == "en-espa-ol"

    def test_unicode_cjk(self):
        # CJK characters are non-alphanumeric and get replaced with hyphens
        result = slugify_keyword("中文")
        assert result == ""  # All non-ascii-alnum chars stripped

    def test_empty_string(self):
        assert slugify_keyword("") == ""


# =============================================================================
# GENERATE EVENT TVG ID
# =============================================================================


class TestGenerateEventTvgId:
    """Test tvg-id generation with exception keyword support."""

    def test_basic_no_keyword(self):
        assert generate_event_tvg_id("401547679") == "teamarr-event-401547679"

    def test_with_segment(self):
        result = generate_event_tvg_id("401547679", segment="prelims")
        assert result == "teamarr-event-401547679-prelims"

    def test_with_keyword(self):
        result = generate_event_tvg_id("401547679", exception_keyword="Spanish")
        assert result == "teamarr-event-401547679-spanish"

    def test_with_segment_and_keyword(self):
        result = generate_event_tvg_id(
            "401547679", segment="main_card", exception_keyword="French"
        )
        assert result == "teamarr-event-401547679-main_card-french"

    def test_none_keyword_same_as_no_keyword(self):
        assert generate_event_tvg_id("123", exception_keyword=None) == "teamarr-event-123"

    def test_empty_keyword_same_as_no_keyword(self):
        assert generate_event_tvg_id("123", exception_keyword="") == "teamarr-event-123"

    def test_different_keywords_produce_different_ids(self):
        id_spanish = generate_event_tvg_id("123", exception_keyword="Spanish")
        id_french = generate_event_tvg_id("123", exception_keyword="French")
        id_none = generate_event_tvg_id("123")
        assert id_spanish != id_french
        assert id_spanish != id_none
        assert id_french != id_none

    def test_multi_word_keyword(self):
        result = generate_event_tvg_id("123", exception_keyword="4K HDR")
        assert result == "teamarr-event-123-4k-hdr"


# =============================================================================
# TEMPLATE CONTEXT EXTRA_VARS
# =============================================================================


class TestTemplateContextExtraVars:
    """Test that extra_vars on TemplateContext override registered extractors.

    Uses mock on _build_all_variables to avoid needing full service initialization
    (LeagueMappingService, etc.). We only test the extra_vars merge behavior.
    """

    @pytest.fixture
    def minimal_context(self):
        """Create a minimal TemplateContext for testing."""
        return TemplateContext(
            game_context=None,
            team_config=TeamChannelContext(
                team_name="Test",
                team_abbrev="TST",
                team_id="1",
                league="nba",
                sport="basketball",
            ),
            team_stats=None,
        )

    def _make_build_vars(self, base_vars: dict):
        """Create a mock _build_all_variables that returns base_vars + extra_vars."""

        def build(ctx):
            variables = dict(base_vars)
            if ctx.extra_vars:
                for key, val in ctx.extra_vars.items():
                    variables[key.lower()] = val
            return variables

        return build

    def test_extra_vars_default_empty(self, minimal_context):
        assert minimal_context.extra_vars == {}

    def test_extra_vars_override_registered_variable(self, minimal_context):
        """exception_keyword extractor returns '' but extra_vars should override."""
        resolver = TemplateResolver()
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            # Without extra_vars: exception_keyword resolves to ""
            result_without = resolver.resolve("{exception_keyword}", minimal_context)
            assert result_without == ""

            # With extra_vars: exception_keyword resolves to "Spanish"
            minimal_context.extra_vars = {"exception_keyword": "Spanish"}
            result_with = resolver.resolve("{exception_keyword}", minimal_context)
            assert result_with == "Spanish"

    def test_extra_vars_in_title_template(self, minimal_context):
        """Verify exception_keyword works in title-style templates."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"exception_keyword": "French"}
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve(
                "Game ({exception_keyword})", minimal_context
            )
        assert result == "Game (French)"

    def test_extra_vars_empty_keyword_cleaned_up(self, minimal_context):
        """Empty exception_keyword should produce clean output (no empty parens)."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"exception_keyword": ""}
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve(
                "Game ({exception_keyword})", minimal_context
            )
        # Resolver cleans up empty wrappers
        assert result == "Game"

    def test_extra_vars_case_insensitive(self, minimal_context):
        """Variable lookup is case-insensitive."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"Exception_Keyword": "Spanish"}
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve("{exception_keyword}", minimal_context)
        assert result == "Spanish"

    def test_extra_vars_mixed_with_regular_variables(self, minimal_context):
        """Extra vars work alongside normal template variables."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"exception_keyword": "Spanish"}
        mock_build = self._make_build_vars({
            "exception_keyword": "",
            "home_team": "Lakers",
            "away_team": "Celtics",
        })

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve(
                "{away_team} @ {home_team} ({exception_keyword})", minimal_context
            )
        assert result == "Celtics @ Lakers (Spanish)"

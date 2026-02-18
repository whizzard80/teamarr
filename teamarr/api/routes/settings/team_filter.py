"""Team filter settings endpoints.

Provides REST API for managing the global default team filter
that applies to all event groups without their own filter.
"""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.database.settings import get_team_filter_settings, update_team_filter_settings

from .models import TeamFilterSettingsModel, TeamFilterSettingsUpdate

router = APIRouter()


@router.get("/settings/team-filter", response_model=TeamFilterSettingsModel)
def get_team_filter():
    """Get default team filter settings.

    Returns the global default team filter that is applied to
    all event groups that don't have their own filter configured.
    """
    with get_db() as conn:
        settings = get_team_filter_settings(conn)

    return TeamFilterSettingsModel(
        enabled=settings.enabled,
        include_teams=settings.include_teams,
        exclude_teams=settings.exclude_teams,
        mode=settings.mode,
        bypass_filter_for_playoffs=settings.bypass_filter_for_playoffs,
    )


@router.put("/settings/team-filter", response_model=TeamFilterSettingsModel)
def update_team_filter(update: TeamFilterSettingsUpdate):
    """Update default team filter settings.

    Updates the global default team filter. This filter applies to
    all event groups that don't have their own filter configured.

    Priority chain for team filtering:
    1. Group's own filter (if configured)
    2. Parent group's filter (if child and parent has filter)
    3. Global settings default (this setting)
    4. No filtering (default)
    """
    with get_db() as conn:
        update_team_filter_settings(
            conn,
            enabled=update.enabled,
            include_teams=update.include_teams,
            exclude_teams=update.exclude_teams,
            mode=update.mode,
            clear_include_teams=update.clear_include_teams,
            clear_exclude_teams=update.clear_exclude_teams,
            bypass_filter_for_playoffs=update.bypass_filter_for_playoffs,
        )
        settings = get_team_filter_settings(conn)

    return TeamFilterSettingsModel(
        enabled=settings.enabled,
        include_teams=settings.include_teams,
        exclude_teams=settings.exclude_teams,
        mode=settings.mode,
        bypass_filter_for_playoffs=settings.bypass_filter_for_playoffs,
    )

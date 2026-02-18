"""Duration, display, and reconciliation settings endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from teamarr.database import get_db

from .models import (
    DisplaySettingsModel,
    ReconciliationSettingsModel,
)

router = APIRouter()


# =============================================================================
# DURATION SETTINGS
# =============================================================================


@router.get("/settings/durations")
def get_duration_settings() -> dict[str, float]:
    """Get game duration settings.

    Returns all sports and their default durations in hours.
    Sports are defined in DurationSettings dataclass - adding a new sport
    there automatically exposes it here.
    """
    from teamarr.database.settings import get_all_settings

    with get_db() as conn:
        settings = get_all_settings(conn)

    return asdict(settings.durations)


@router.put("/settings/durations")
def update_duration_settings(update: dict[str, float]) -> dict[str, float]:
    """Update game duration settings.

    Accepts a dict of sport names to duration hours.
    Only known sports (defined in DurationSettings) will be updated.
    """
    from teamarr.database.settings import get_all_settings
    from teamarr.database.settings import update_duration_settings as db_update

    with get_db() as conn:
        # Pass all values from the update dict as kwargs
        db_update(conn, **update)

    with get_db() as conn:
        settings = get_all_settings(conn)

    return asdict(settings.durations)


# =============================================================================
# RECONCILIATION SETTINGS
# =============================================================================


@router.get("/settings/reconciliation", response_model=ReconciliationSettingsModel)
def get_reconciliation_settings():
    """Get reconciliation settings."""
    from teamarr.database.settings import get_all_settings

    with get_db() as conn:
        settings = get_all_settings(conn)

    return ReconciliationSettingsModel(
        reconcile_on_epg_generation=settings.reconciliation.reconcile_on_epg_generation,
        reconcile_on_startup=settings.reconciliation.reconcile_on_startup,
        auto_fix_orphan_teamarr=settings.reconciliation.auto_fix_orphan_teamarr,
        auto_fix_orphan_dispatcharr=settings.reconciliation.auto_fix_orphan_dispatcharr,
        auto_fix_duplicates=settings.reconciliation.auto_fix_duplicates,
        default_duplicate_event_handling=settings.reconciliation.default_duplicate_event_handling,
        channel_history_retention_days=settings.reconciliation.channel_history_retention_days,
    )


@router.put("/settings/reconciliation", response_model=ReconciliationSettingsModel)
def update_reconciliation_settings(update: ReconciliationSettingsModel):
    """Update reconciliation settings."""
    from teamarr.database.settings import (
        get_all_settings,
        update_reconciliation_settings,
    )

    valid_modes = {"consolidate", "separate", "ignore"}
    if update.default_duplicate_event_handling not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid duplicate handling mode. Valid: {valid_modes}",
        )

    with get_db() as conn:
        update_reconciliation_settings(
            conn,
            reconcile_on_epg_generation=update.reconcile_on_epg_generation,
            reconcile_on_startup=update.reconcile_on_startup,
            auto_fix_orphan_teamarr=update.auto_fix_orphan_teamarr,
            auto_fix_orphan_dispatcharr=update.auto_fix_orphan_dispatcharr,
            auto_fix_duplicates=update.auto_fix_duplicates,
            default_duplicate_event_handling=update.default_duplicate_event_handling,
            channel_history_retention_days=update.channel_history_retention_days,
        )

    with get_db() as conn:
        settings = get_all_settings(conn)

    return ReconciliationSettingsModel(
        reconcile_on_epg_generation=settings.reconciliation.reconcile_on_epg_generation,
        reconcile_on_startup=settings.reconciliation.reconcile_on_startup,
        auto_fix_orphan_teamarr=settings.reconciliation.auto_fix_orphan_teamarr,
        auto_fix_orphan_dispatcharr=settings.reconciliation.auto_fix_orphan_dispatcharr,
        auto_fix_duplicates=settings.reconciliation.auto_fix_duplicates,
        default_duplicate_event_handling=settings.reconciliation.default_duplicate_event_handling,
        channel_history_retention_days=settings.reconciliation.channel_history_retention_days,
    )


# =============================================================================
# DISPLAY SETTINGS
# =============================================================================


@router.get("/settings/display", response_model=DisplaySettingsModel)
def get_display_settings():
    """Get display/formatting settings."""
    from teamarr.database.settings import get_all_settings
    from teamarr.database.settings.read import get_tsdb_api_key

    with get_db() as conn:
        settings = get_all_settings(conn)
        tsdb_api_key = get_tsdb_api_key(conn)

    return DisplaySettingsModel(
        time_format=settings.display.time_format,
        show_timezone=settings.display.show_timezone,
        channel_id_format=settings.display.channel_id_format,
        xmltv_generator_name=settings.display.xmltv_generator_name,
        xmltv_generator_url=settings.display.xmltv_generator_url,
        tsdb_api_key=tsdb_api_key,
    )


@router.put("/settings/display", response_model=DisplaySettingsModel)
def update_display_settings_endpoint(update: DisplaySettingsModel):
    """Update display/formatting settings."""
    from teamarr.config import set_display_settings as set_config_display
    from teamarr.database.settings import get_all_settings, update_display_settings

    valid_time_formats = {"12h", "24h"}
    if update.time_format not in valid_time_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid time_format. Valid: {valid_time_formats}",
        )

    with get_db() as conn:
        update_display_settings(
            conn,
            time_format=update.time_format,
            show_timezone=update.show_timezone,
            channel_id_format=update.channel_id_format,
            xmltv_generator_name=update.xmltv_generator_name,
            xmltv_generator_url=update.xmltv_generator_url,
            tsdb_api_key=update.tsdb_api_key,
        )

    # Update cached display settings so new values are used immediately
    set_config_display(
        time_format=update.time_format,
        show_timezone=update.show_timezone,
        channel_id_format=update.channel_id_format,
        xmltv_generator_name=update.xmltv_generator_name,
        xmltv_generator_url=update.xmltv_generator_url,
    )

    from teamarr.database.settings.read import get_tsdb_api_key

    with get_db() as conn:
        settings = get_all_settings(conn)
        tsdb_api_key = get_tsdb_api_key(conn)

    return DisplaySettingsModel(
        time_format=settings.display.time_format,
        show_timezone=settings.display.show_timezone,
        channel_id_format=settings.display.channel_id_format,
        xmltv_generator_name=settings.display.xmltv_generator_name,
        xmltv_generator_url=settings.display.xmltv_generator_url,
        tsdb_api_key=tsdb_api_key,
    )

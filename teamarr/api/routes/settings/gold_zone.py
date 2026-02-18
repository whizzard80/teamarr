"""Gold Zone settings endpoints (Olympics Special Feature)."""

from fastapi import APIRouter

from teamarr.database import get_db

from .models import GoldZoneSettingsModel, GoldZoneSettingsUpdate

router = APIRouter()


def _to_model(settings) -> GoldZoneSettingsModel:
    return GoldZoneSettingsModel(
        enabled=settings.enabled,
        channel_number=settings.channel_number,
        channel_group_id=settings.channel_group_id,
        channel_profile_ids=settings.channel_profile_ids,
        stream_profile_id=settings.stream_profile_id,
    )


@router.get("/settings/gold-zone", response_model=GoldZoneSettingsModel)
def get_gold_zone_settings():
    """Get Gold Zone settings."""
    from teamarr.database.settings import get_gold_zone_settings

    with get_db() as conn:
        settings = get_gold_zone_settings(conn)

    return _to_model(settings)


@router.put("/settings/gold-zone", response_model=GoldZoneSettingsModel)
def update_gold_zone_settings(update: GoldZoneSettingsUpdate):
    """Update Gold Zone settings."""
    from teamarr.database.settings import get_gold_zone_settings
    from teamarr.database.settings import update_gold_zone_settings as db_update

    with get_db() as conn:
        db_update(
            conn,
            enabled=update.enabled,
            channel_number=update.channel_number,
            channel_group_id=update.channel_group_id,
            channel_profile_ids=update.channel_profile_ids,
            stream_profile_id=update.stream_profile_id,
        )

    with get_db() as conn:
        settings = get_gold_zone_settings(conn)

    return _to_model(settings)

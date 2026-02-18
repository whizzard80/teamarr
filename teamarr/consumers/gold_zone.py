"""Gold Zone — Olympics special feature.

Unified channel for Gold Zone Olympics coverage with external EPG.
All Gold Zone logic is isolated here for easy deprecation post-Olympics.

History: teamarrv2-4v4 (epic)
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Match terms for Gold Zone streams (case-insensitive)
_GOLD_ZONE_PATTERNS = ["gold zone", "goldzone", "gold-zone"]

# External EPG source
_GOLD_ZONE_EPG_URL = "https://epg.jesmann.com/TeamSports/goldzone.xml"

# XMLTV identifiers (must match the external EPG)
_GOLD_ZONE_TVG_ID = "GoldZone.us"
_GOLD_ZONE_CHANNEL_NAME = "Gold Zone"
_GOLD_ZONE_LOGO = "https://emby.tmsimg.com/assets/p32146358_b_h9_ab.jpg"

# Gold Zone active day rolls over at 0500 UTC (midnight ET).  This must be
# well before broadcast start (1300 UTC) so that EPG generation picks up
# today's streams before the broadcast begins.
_GOLD_ZONE_BROADCAST_START_UTC_HOUR = 5


@dataclass
class GoldZoneResult:
    """Result of Gold Zone processing."""

    epg_xml: str | None = None
    dispatcharr_channel_id: int | None = None


def process_gold_zone(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any,
    gold_zone_settings: Any,
    epg_settings: Any,
    update_progress: Callable,
) -> GoldZoneResult | None:
    """Process Gold Zone: find matching streams in event groups, create channel, fetch EPG.

    Only searches streams within imported event groups (not all providers).
    Excludes stale streams. Filters external EPG to the configured date window.

    Args:
        db_factory: Factory function returning database connection context manager
        dispatcharr_client: Dispatcharr client for stream/channel operations
        gold_zone_settings: GoldZoneSettings with enabled and channel_number
        epg_settings: EPGSettings for date window (epg_output_days_ahead, epg_lookback_hours)
        update_progress: Progress callback

    Returns:
        GoldZoneResult with EPG XML and channel ID, or None if nothing to do
    """
    import httpx

    from teamarr.database.channels import get_managed_channel_by_tvg_id
    from teamarr.database.channels.crud import create_managed_channel, update_managed_channel
    from teamarr.database.groups import get_all_groups

    # Build combined regex pattern for Gold Zone keywords
    pattern = re.compile("|".join(re.escape(p) for p in _GOLD_ZONE_PATTERNS), re.IGNORECASE)

    # Get M3U group IDs from enabled event groups — only search streams
    # in M3U groups that are configured as event groups
    with db_factory() as conn:
        groups = get_all_groups(conn, include_disabled=False)

    m3u_group_ids = {g.m3u_group_id for g in groups if g.m3u_group_id is not None}
    if not m3u_group_ids:
        logger.info("[GOLD_ZONE] No event groups with M3U groups configured")
        return None

    # Fetch all streams once, filter by M3U group + keywords + stale
    try:
        all_streams = dispatcharr_client.m3u.list_streams()
    except Exception as e:
        logger.error("[GOLD_ZONE] Failed to fetch streams: %s", e)
        return None

    # Build M3U group → event group mapping for managed channel registration
    m3u_to_event_group = {g.m3u_group_id: g.id for g in groups if g.m3u_group_id is not None}

    matched_streams = []
    first_event_group_id: int | None = None
    skipped_date = 0
    for s in all_streams:
        if s.channel_group in m3u_group_ids and not s.is_stale and pattern.search(s.name):
            # Date disambiguation: exclude streams with a non-today date in the name
            date_ok, parsed_date = _stream_date_check(s.name)
            if not date_ok:
                skipped_date += 1
                logger.debug(
                    "[GOLD_ZONE] Skipping '%s' — date %s is not active day", s.name, parsed_date
                )
                continue
            matched_streams.append(s)
            if first_event_group_id is None:
                first_event_group_id = m3u_to_event_group.get(s.channel_group)

    if skipped_date:
        logger.info("[GOLD_ZONE] Skipped %d streams with non-active-day dates", skipped_date)

    if not matched_streams:
        logger.info(
            "[GOLD_ZONE] No matching streams found across %d M3U groups",
            len(m3u_group_ids),
        )
        return None

    # Apply stream ordering rules (same priority system as regular channels)
    gold_zone_stream_ids = _order_streams(
        matched_streams, m3u_to_event_group, db_factory,
    )

    logger.info(
        "[GOLD_ZONE] Found %d matching streams (non-stale) across %d M3U groups",
        len(gold_zone_stream_ids), len(m3u_group_ids),
    )

    # Create or update the Gold Zone channel in Dispatcharr
    channel_number = gold_zone_settings.channel_number or 999
    channel_group_id = gold_zone_settings.channel_group_id
    stream_profile_id = gold_zone_settings.stream_profile_id

    # Check for collision with external Dispatcharr channels (#146)
    channel_manager_ref = dispatcharr_client.channels
    existing_at_number = channel_manager_ref.find_by_number(channel_number)
    if existing_at_number:
        # Only warn if it's not our own Gold Zone channel
        existing_gz = channel_manager_ref.find_by_tvg_id(_GOLD_ZONE_TVG_ID)
        if not existing_gz or existing_gz.id != existing_at_number.id:
            logger.warning(
                "[GOLD_ZONE] Channel number %d conflicts with existing channel '%s' "
                "(id=%d). Consider changing Gold Zone channel number in settings.",
                channel_number,
                existing_at_number.name,
                existing_at_number.id,
            )

    # Convert profile IDs: null = all profiles → [0] sentinel for Dispatcharr
    profile_ids = gold_zone_settings.channel_profile_ids
    if profile_ids is None:
        disp_profile_ids = [0]  # All profiles
    else:
        disp_profile_ids = [int(p) for p in profile_ids if not isinstance(p, str)]

    channel_name = _GOLD_ZONE_CHANNEL_NAME
    dispatcharr_channel_id: int | None = None

    try:
        channel_manager = dispatcharr_client.channels

        # Check if channel already exists by tvg_id
        existing = channel_manager.find_by_tvg_id(_GOLD_ZONE_TVG_ID)
        if existing:
            dispatcharr_channel_id = existing.id
            # Update existing channel with current streams + settings
            update_data: dict = {
                "name": channel_name,
                "channel_number": channel_number,
                "streams": gold_zone_stream_ids,
                "tvg_id": _GOLD_ZONE_TVG_ID,
            }
            if channel_group_id is not None:
                update_data["channel_group_id"] = channel_group_id
            if disp_profile_ids:
                update_data["channel_profile_ids"] = disp_profile_ids
            if stream_profile_id is not None:
                update_data["stream_profile_id"] = stream_profile_id

            channel_manager.update_channel(existing.id, data=update_data)
            logger.info(
                "[GOLD_ZONE] Updated channel %d with %d streams",
                existing.id,
                len(gold_zone_stream_ids),
            )
        else:
            # Upload logo
            logo_id = None
            try:
                logo_id = dispatcharr_client.logos.upload_or_find(
                    _GOLD_ZONE_CHANNEL_NAME, _GOLD_ZONE_LOGO
                )
            except Exception as e:
                logger.warning("[GOLD_ZONE] Failed to upload logo: %s", e)

            # Create new channel
            create_result = channel_manager.create_channel(
                name=channel_name,
                channel_number=channel_number,
                stream_ids=gold_zone_stream_ids,
                tvg_id=_GOLD_ZONE_TVG_ID,
                logo_id=logo_id,
                channel_group_id=channel_group_id,
                channel_profile_ids=disp_profile_ids or None,
                stream_profile_id=stream_profile_id,
            )
            if create_result.success:
                dispatcharr_channel_id = (create_result.data or {}).get("id")
                logger.info(
                    "[GOLD_ZONE] Created channel %s with %d streams",
                    dispatcharr_channel_id,
                    len(gold_zone_stream_ids),
                )
            else:
                logger.error("[GOLD_ZONE] Failed to create channel: %s", create_result.error)
    except Exception as e:
        logger.error("[GOLD_ZONE] Channel operation failed: %s", e)

    # Register as managed channel so standard EPG association picks it up
    if dispatcharr_channel_id and first_event_group_id:
        from teamarr.utilities.tz import now_user

        # Default deletion to end of today (same-day lifecycle)
        today_end = now_user().replace(hour=23, minute=59, second=59)
        delete_at = today_end.isoformat()

        mc_fields = {
            "dispatcharr_channel_id": dispatcharr_channel_id,
            "channel_name": channel_name,
            "channel_group_id": channel_group_id,
            "channel_profile_ids": profile_ids or [],
            "event_name": channel_name,
            "league": "Special - Winter Olympics",
            "sync_status": "in_sync",
            "scheduled_delete_at": delete_at,
        }

        try:
            with db_factory() as conn:
                existing_mc = get_managed_channel_by_tvg_id(conn, _GOLD_ZONE_TVG_ID)
                if existing_mc:
                    update_managed_channel(conn, existing_mc.id, mc_fields)
                    logger.info("[GOLD_ZONE] Updated managed channel %d", existing_mc.id)
                else:
                    mc_id = create_managed_channel(
                        conn=conn,
                        event_epg_group_id=first_event_group_id,
                        event_id="gold_zone",
                        event_provider="system",
                        tvg_id=_GOLD_ZONE_TVG_ID,
                        channel_name=channel_name,
                        dispatcharr_channel_id=dispatcharr_channel_id,
                        channel_group_id=channel_group_id,
                        channel_profile_ids=profile_ids or [],
                        logo_url=_GOLD_ZONE_LOGO,
                        sport="olympics",
                        event_name=channel_name,
                        league="Special - Winter Olympics",
                        sync_status="in_sync",
                        scheduled_delete_at=delete_at,
                    )
                    logger.info("[GOLD_ZONE] Created managed channel %d", mc_id)
        except Exception as e:
            logger.error("[GOLD_ZONE] Failed to register managed channel: %s", e)

    gz_result = GoldZoneResult(dispatcharr_channel_id=dispatcharr_channel_id)

    # Fetch external EPG XML and filter by date window
    try:
        response = httpx.get(_GOLD_ZONE_EPG_URL, timeout=30, follow_redirects=True)
        response.raise_for_status()
        raw_xml = response.text
        logger.info("[GOLD_ZONE] Fetched external EPG (%d bytes)", len(raw_xml))
    except Exception as e:
        logger.error("[GOLD_ZONE] Failed to fetch external EPG: %s", e)
        return gz_result  # Return with channel ID but no EPG

    # Filter programmes to EPG date window
    try:
        gz_result.epg_xml = _filter_epg(raw_xml, epg_settings)
    except Exception as e:
        logger.error("[GOLD_ZONE] Failed to filter EPG: %s", e)
        gz_result.epg_xml = raw_xml  # Fall back to unfiltered

    return gz_result


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _get_active_day():
    """Get the active Olympic day as a date, using UTC rollover logic.

    Day rolls over at 0500 UTC (midnight ET), well before broadcast start
    (1300 UTC). Before rollover, the previous day is still "active".

    Returns:
        date: The active Olympic day
    """
    from datetime import UTC, datetime, timedelta

    now_utc = datetime.now(UTC)
    if now_utc.hour < _GOLD_ZONE_BROADCAST_START_UTC_HOUR:
        return (now_utc - timedelta(days=1)).date()
    return now_utc.date()


# Milano-Cortina 2026 Olympics: Feb 7 (Day 1) through Feb 23 (Day 17)
_OLYMPICS_START = None  # Lazy-initialized to avoid import at module level
_OLYMPICS_END = None

# Pattern for "Day ##" in stream names (e.g., "Gold Zone Day 7", "Day 12")
_DAY_NUMBER_PATTERN = re.compile(r"\bDay\s+(\d{1,2})\b", re.IGNORECASE)


def _get_olympics_dates():
    """Get Olympics start/end dates (lazy-initialized)."""
    global _OLYMPICS_START, _OLYMPICS_END
    if _OLYMPICS_START is None:
        from datetime import date
        _OLYMPICS_START = date(2026, 2, 7)
        _OLYMPICS_END = date(2026, 2, 23)
    return _OLYMPICS_START, _OLYMPICS_END


def _resolve_day_number_to_date(stream_name: str):
    """Resolve 'Day ##' in a stream name to a calendar date.

    Milano-Cortina 2026: Day 1 = Feb 7, Day 17 = Feb 23.

    Returns:
        date or None if no Day ## pattern found or day number out of range
    """
    from datetime import timedelta

    match = _DAY_NUMBER_PATTERN.search(stream_name)
    if not match:
        return None

    day_number = int(match.group(1))
    olympics_start, olympics_end = _get_olympics_dates()
    resolved = olympics_start + timedelta(days=day_number - 1)

    if resolved < olympics_start or resolved > olympics_end:
        return None
    return resolved


def _stream_date_check(stream_name: str) -> tuple[bool, str | None]:
    """Check if a Gold Zone stream name contains a date, and if so whether it matches.

    Handles three formats:
    1. "Day ##" → resolved via Olympics day mapping (Day 1 = Feb 7, etc.)
    2. Calendar dates (Feb 9, 2/9, 2026-02-09) → via normalizer
    3. No date at all → include (assumed to be current day)

    Logic:
    - No date found → include (True, None)
    - Date matches active Olympic day → include (True, date_str)
    - Date does NOT match → exclude (False, date_str)

    Returns:
        (is_ok, parsed_date_str) — is_ok=True means include the stream
    """
    from teamarr.consumers.matching.normalizer import extract_and_mask_datetime

    active_day = _get_active_day()

    # First: check for "Day ##" pattern (e.g., "Gold Zone Day 7")
    resolved_date = _resolve_day_number_to_date(stream_name)
    if resolved_date is not None:
        date_str = resolved_date.isoformat()
        if resolved_date == active_day:
            return True, date_str
        return False, date_str

    # Second: check for calendar dates (Feb 13, 2/13, 2026-02-13, etc.)
    _, extracted_date, _, _ = extract_and_mask_datetime(stream_name)

    if extracted_date is None:
        return True, None

    date_str = extracted_date.isoformat()
    if extracted_date.month == active_day.month and extracted_date.day == active_day.day:
        return True, date_str
    return False, date_str


def _filter_epg(raw_xml: str, epg_settings: Any) -> str:
    """Filter Gold Zone EPG to only include programmes within the EPG date window.

    Programmes without datetime info are always included.
    Programmes with datetime are filtered to the configured window
    (epg_lookback_hours back, epg_output_days_ahead forward).

    Args:
        raw_xml: Raw XMLTV XML from external source
        epg_settings: EPGSettings with epg_output_days_ahead and epg_lookback_hours

    Returns:
        Filtered XMLTV XML string
    """
    import xml.etree.ElementTree as ET
    from datetime import UTC, datetime, timedelta

    source = ET.fromstring(raw_xml)

    now = datetime.now(UTC)
    window_start = now - timedelta(hours=epg_settings.epg_lookback_hours)
    window_end = now + timedelta(days=epg_settings.epg_output_days_ahead)

    # Build filtered XML with same structure
    root = ET.Element("tv")

    # Copy channels as-is
    for channel in source.findall("channel"):
        root.append(channel)

    # Filter programmes by date window
    kept = 0
    dropped = 0
    for programme in source.findall("programme"):
        start_str = programme.get("start", "")
        if not start_str:
            # No datetime — always include
            root.append(programme)
            kept += 1
            continue

        # Parse XMLTV datetime: "YYYYMMDDHHmmss +HHMM"
        try:
            prog_start = _parse_xmltv_datetime(start_str)
        except ValueError:
            # Can't parse — include to be safe
            root.append(programme)
            kept += 1
            continue

        if window_start <= prog_start <= window_end:
            root.append(programme)
            kept += 1
        else:
            dropped += 1

    if dropped > 0:
        logger.info("[GOLD_ZONE] EPG filtered: %d kept, %d outside date window", kept, dropped)

    xml_str = ET.tostring(root, encoding="unicode")
    return xml_str


def _parse_xmltv_datetime(dt_str: str):
    """Parse XMLTV datetime string like '20260207130000 +0000' to timezone-aware datetime."""
    from datetime import datetime, timedelta, timezone

    # Format: YYYYMMDDHHmmss +HHMM (or -HHMM)
    dt_str = dt_str.strip()
    if " " in dt_str:
        time_part, tz_part = dt_str.rsplit(" ", 1)
    else:
        time_part = dt_str
        tz_part = "+0000"

    # Parse base datetime
    dt = datetime.strptime(time_part, "%Y%m%d%H%M%S")

    # Parse timezone offset
    tz_sign = 1 if tz_part.startswith("+") else -1
    tz_digits = tz_part.lstrip("+-")
    tz_hours = int(tz_digits[:2])
    tz_minutes = int(tz_digits[2:4]) if len(tz_digits) >= 4 else 0
    tz_offset = timedelta(hours=tz_hours, minutes=tz_minutes) * tz_sign

    return dt.replace(tzinfo=timezone(tz_offset))


def _order_streams(
    streams: list,
    m3u_to_event_group: dict[int, int],
    db_factory: Callable[[], Any],
) -> list[int]:
    """Apply stream ordering rules to Gold Zone streams.

    Creates lightweight ManagedChannelStream adapters from DispatcharrStream
    objects so the existing StreamOrderingService can sort them.

    Args:
        streams: Matched DispatcharrStream objects
        m3u_to_event_group: Mapping of M3U group ID → event group ID
        db_factory: Database connection factory

    Returns:
        Sorted list of Dispatcharr stream IDs
    """
    from teamarr.database.channels.types import ManagedChannelStream
    from teamarr.database.settings import get_stream_ordering_settings
    from teamarr.services.stream_ordering import StreamOrderingService

    with db_factory() as conn:
        ordering_settings = get_stream_ordering_settings(conn)

    if not ordering_settings.rules:
        return [s.id for s in streams]

    # Build adapters so StreamOrderingService can evaluate its rules
    adapters: list[ManagedChannelStream] = []
    for s in streams:
        event_group_id = m3u_to_event_group.get(s.channel_group)
        adapters.append(ManagedChannelStream(
            id=0,
            managed_channel_id=0,
            dispatcharr_stream_id=s.id,
            stream_name=s.name,
            source_group_id=event_group_id,
            m3u_account_id=s.m3u_account_id,
            m3u_account_name=s.m3u_account_name,
        ))

    with db_factory() as conn:
        service = StreamOrderingService(rules=ordering_settings.rules, conn=conn)
        sorted_adapters = service.sort_streams(adapters)

    sorted_ids = [a.dispatcharr_stream_id for a in sorted_adapters]

    if sorted_ids != [s.id for s in streams]:
        logger.info(
            "[GOLD_ZONE] Reordered %d streams by %d ordering rules",
            len(sorted_ids), len(ordering_settings.rules),
        )

    return sorted_ids

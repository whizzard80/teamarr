"""Channel lifecycle types and dataclasses.

Contains timing types, result dataclasses, and helper functions.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# =============================================================================
# TIMING TYPES
# =============================================================================


CreateTiming = Literal[
    "stream_available",
    "same_day",
    "day_before",
    "2_days_before",
    "3_days_before",
    "1_week_before",
]

DeleteTiming = Literal[
    "stream_removed",
    "6_hours_after",
    "same_day",
    "day_after",
    "2_days_after",
    "3_days_after",
    "1_week_after",
]

DuplicateMode = Literal["consolidate", "separate", "ignore"]


# =============================================================================
# RESULT DATACLASSES
# =============================================================================


@dataclass
class LifecycleDecision:
    """Result of a lifecycle check."""

    should_act: bool
    reason: str
    threshold_time: datetime | None = None


@dataclass
class ChannelCreationResult:
    """Result of channel creation."""

    success: bool
    channel_id: int | None = None
    dispatcharr_channel_id: int | None = None
    channel_number: str | None = None
    tvg_id: str | None = None
    error: str | None = None


@dataclass
class StreamProcessResult:
    """Result of processing matched streams."""

    created: list[dict] = field(default_factory=list)
    existing: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)  # Matched but excluded by timing
    errors: list[dict] = field(default_factory=list)
    streams_added: list[dict] = field(default_factory=list)
    streams_removed: list[dict] = field(default_factory=list)  # V1 parity
    logo_updated: list[dict] = field(default_factory=list)
    settings_updated: list[dict] = field(default_factory=list)
    deleted: list[dict] = field(default_factory=list)

    def merge(self, other: "StreamProcessResult") -> None:
        """Merge another result into this one."""
        self.created.extend(other.created)
        self.existing.extend(other.existing)
        self.skipped.extend(other.skipped)
        self.excluded.extend(other.excluded)
        self.errors.extend(other.errors)
        self.streams_added.extend(other.streams_added)
        self.streams_removed.extend(other.streams_removed)
        self.logo_updated.extend(other.logo_updated)
        self.settings_updated.extend(other.settings_updated)
        self.deleted.extend(other.deleted)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "created": self.created,
            "existing": self.existing,
            "skipped": self.skipped,
            "excluded": self.excluded,
            "errors": self.errors,
            "streams_added": self.streams_added,
            "streams_removed": self.streams_removed,
            "logo_updated": self.logo_updated,
            "settings_updated": self.settings_updated,
            "deleted": self.deleted,
            "summary": {
                "created_count": len(self.created),
                "existing_count": len(self.existing),
                "skipped_count": len(self.skipped),
                "excluded_count": len(self.excluded),
                "error_count": len(self.errors),
                "streams_removed_count": len(self.streams_removed),
                "deleted_count": len(self.deleted),
            },
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def slugify_keyword(keyword: str) -> str:
    """Sanitize an exception keyword into a tvg-id-safe slug.

    Converts to lowercase, replaces spaces/special chars with hyphens,
    strips leading/trailing hyphens.

    Examples:
        "Spanish" → "spanish"
        "4K HDR" → "4k-hdr"
        "Peyton and Eli" → "peyton-and-eli"
    """
    slug = keyword.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def generate_event_tvg_id(
    event_id: str,
    provider: str = "espn",
    segment: str | None = None,
    exception_keyword: str | None = None,
) -> str:
    """Generate consistent tvg_id for an event.

    This tvg_id is used:
    1. In XMLTV <channel id="..."> and <programme channel="...">
    2. When creating channels in Dispatcharr
    3. To look up EPGData for channel-EPG association

    When an exception_keyword is provided, the tvg_id is made unique per keyword
    so each variant gets its own XMLTV channel and programme entries, allowing
    {exception_keyword} to resolve correctly in all template fields.

    Args:
        event_id: Provider event ID (e.g., "401547679")
        provider: Provider name (default: espn)
        segment: Optional card segment for UFC/MMA (e.g., "prelims", "main_card")
        exception_keyword: Optional exception keyword label (e.g., "Spanish", "4K")

    Returns:
        Formatted tvg_id. Examples:
        - "teamarr-event-401547679"
        - "teamarr-event-401547679-prelims"
        - "teamarr-event-401547679-spanish"
        - "teamarr-event-401547679-prelims-spanish"
    """
    parts = [f"teamarr-event-{event_id}"]
    if segment:
        parts.append(segment)
    if exception_keyword:
        parts.append(slugify_keyword(exception_keyword))
    return "-".join(parts)

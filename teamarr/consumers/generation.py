"""Unified EPG generation workflow.

This module provides the single source of truth for EPG generation.
Both the streaming API endpoint and the background scheduler call this.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global lock to prevent concurrent EPG generation runs
_generation_lock = threading.Lock()
_generation_running = False


@dataclass
class GenerationResult:
    """Result of a full EPG generation run."""

    success: bool = True
    error: str | None = None

    # Timing
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_seconds: float = 0.0

    # EPG stats
    teams_processed: int = 0
    teams_programmes: int = 0
    groups_processed: int = 0
    groups_programmes: int = 0
    programmes_total: int = 0

    # File output
    file_written: bool = False
    file_path: str | None = None
    file_size: int = 0

    # Sub-task results
    m3u_refresh: dict = field(default_factory=dict)
    stream_ordering: dict = field(default_factory=dict)
    epg_refresh: dict = field(default_factory=dict)
    epg_association: dict = field(default_factory=dict)
    deletions: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)
    cleanup: dict = field(default_factory=dict)
    logo_cleanup: dict = field(default_factory=dict)

    # For stats run tracking
    run_id: int | None = None


# Type alias for progress callback
# (phase: str, percent: int, message: str, current: int, total: int, item_name: str) -> None
ProgressCallback = Callable[[str, int, str, int, int, str], None]


def run_full_generation(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> GenerationResult:
    """Run the complete EPG generation workflow.

    This is the single source of truth for EPG generation. Both the
    streaming API endpoint and the background scheduler call this function.

    Workflow:
    1. Refresh M3U accounts (0-5%)
    2. Process all teams (5-50%) - 45% budget
    3. Process all event groups (50-95%) - 45% budget
    4. Merge and save XMLTV (95-96%)
    5. Dispatcharr EPG refresh + channel association (96-98%)
    6. Process scheduled deletions (98-99%)
    7. Run reconciliation + cleanup (99-100%)

    Args:
        db_factory: Factory function returning database connection context manager
        dispatcharr_client: Optional DispatcharrClient for Dispatcharr operations
        progress_callback: Optional callback for progress updates

    Returns:
        GenerationResult with all stats and sub-task results
    """
    global _generation_running

    # Prevent concurrent generation runs
    if not _generation_lock.acquire(blocking=False):
        logger.warning("[GENERATION] Already in progress, skipping duplicate run")
        result = GenerationResult()
        result.success = False
        result.error = "Generation already in progress"
        return result

    if _generation_running:
        _generation_lock.release()
        logger.warning("[GENERATION] Already in progress (flag check), skipping")
        result = GenerationResult()
        result.success = False
        result.error = "Generation already in progress"
        return result

    _generation_running = True

    from teamarr.consumers import (
        create_lifecycle_service,
        create_reconciler,
        process_all_event_groups,
        process_all_teams,
    )
    from teamarr.consumers.team_processor import get_all_team_xmltv
    from teamarr.database.channels import get_reconciliation_settings
    from teamarr.database.groups import get_all_group_xmltv
    from teamarr.database.settings import (
        get_dispatcharr_settings,
        get_display_settings,
        get_epg_settings,
        get_gold_zone_settings,
    )
    from teamarr.database.stats import create_run
    from teamarr.dispatcharr import EPGManager
    from teamarr.services import create_default_service
    from teamarr.utilities.xmltv import merge_xmltv_content

    result = GenerationResult()
    result.started_at = time.time()

    def update_progress(
        phase: str,
        percent: int,
        message: str,
        current: int = 0,
        total: int = 0,
        item_name: str = "",
    ):
        if progress_callback:
            progress_callback(phase, percent, message, current, total, item_name)

    # Create stats run for tracking with database-level lock
    # Use BEGIN IMMEDIATE to acquire exclusive write lock BEFORE checking
    # This prevents race conditions where two processes both pass the check
    # before either has inserted their row
    with db_factory() as conn:
        try:
            # BEGIN IMMEDIATE acquires write lock immediately, blocking other writers
            conn.execute("BEGIN IMMEDIATE")

            # Now check for in-progress runs - with lock held, this is reliable
            recent_running = conn.execute("""
                SELECT id FROM processing_runs
                WHERE run_type = 'full_epg'
                  AND status = 'running'
                  AND started_at > datetime('now', '-5 minutes')
                LIMIT 1
            """).fetchone()

            if recent_running:
                conn.execute("ROLLBACK")
                _generation_running = False
                _generation_lock.release()
                logger.warning(
                    "[GENERATION] Already in progress (run %d), skipping", recent_running["id"]
                )
                result = GenerationResult()
                result.success = False
                result.error = "Generation already in progress"
                return result

            # No running jobs - create our run (still holding lock)
            stats_run = create_run(conn, run_type="full_epg")
            result.run_id = stats_run.id
            # create_run commits, which releases the lock

        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception as rollback_err:
                logger.debug(
                    "[GENERATION] Rollback failed during lock acquisition: %s", rollback_err
                )
            _generation_running = False
            _generation_lock.release()
            logger.error("[GENERATION] Failed to acquire lock: %s", e)
            result = GenerationResult()
            result.success = False
            result.error = f"Failed to acquire lock: {e}"
            return result

    try:
        # Increment generation counter ONCE at start of full EPG run
        # This ensures all groups in this run share the same generation
        from teamarr.consumers.stream_match_cache import increment_generation_counter

        current_generation = increment_generation_counter(db_factory)
        logger.info("[GENERATION] Starting with cache generation %d", current_generation)

        # Create a single SportsDataService instance to share across all processing
        # This ensures the event cache stays warm throughout the entire run
        # (Previously each consumer created its own service with a cold cache)
        shared_service = create_default_service()

        # Get settings
        with db_factory() as conn:
            settings = get_epg_settings(conn)
            dispatcharr_settings = get_dispatcharr_settings(conn)
            display_settings = get_display_settings(conn)
            gold_zone_settings = get_gold_zone_settings(conn)

        # Step 1: Refresh M3U accounts (0-5%)
        update_progress("init", 3, "Refreshing M3U accounts...")
        if dispatcharr_client:
            result.m3u_refresh = _refresh_m3u_accounts(db_factory, dispatcharr_client)

        # Step 2: Process all teams (5-50%) - 45% budget
        update_progress("teams", 5, "Processing teams...")

        teams_start_time = time.time()

        def team_progress(current: int, total: int, name: str):
            # Maps 0-100% within teams to 5-50% overall
            pct = 5 + int((current / total) * 45) if total > 0 else 5
            elapsed = time.time() - teams_start_time
            remaining = total - current

            # Messages from team_processor already include context
            # (Processing X..., Finished X, now processing: Y, Z)
            # Just add timing and counts
            if remaining > 0:
                msg = f"{name} ({current}/{total}) - {remaining} remaining [{elapsed:.1f}s]"
            else:
                msg = f"{name} ({current}/{total}) [{elapsed:.1f}s]"
            update_progress("teams", pct, msg, current, total, name)

        team_result = process_all_teams(db_factory=db_factory, progress_callback=team_progress)
        result.teams_processed = team_result.teams_processed
        result.teams_programmes = team_result.total_programmes

        # Transition message - teams done, starting groups
        logger.info("[GENERATION] Sending transition message: teams -> groups")
        update_progress(
            "groups",
            50,
            f"Teams complete ({result.teams_processed} processed), loading event groups...",
            0,
            1,
            "Loading event groups...",
        )
        logger.info("[GENERATION] Transition message sent")

        # Step 3: Process all event groups (50-95%) - 45% budget

        groups_start_time = time.time()

        def group_progress(current: int, total: int, name: str):
            # Maps 0-100% within groups to 50-95% overall
            pct = 50 + int((current / total) * 45) if total > 0 else 50
            elapsed = time.time() - groups_start_time

            # Check if this is a stream-level progress update (contains ✓ or ✗)
            if "✓" in name or "✗" in name:
                # Stream-level progress - name contains "GroupName: StreamName ✓/✗ (x/y)"
                # Pass the full message as item_name for display in toast
                update_progress("groups", pct, name, current, total, name)
            else:
                # Group completion - add context
                remaining = total - current
                if remaining > 0:
                    msg = f"Finished {name} ({current}/{total}) - {remaining} remaining [{elapsed:.1f}s]"  # noqa: E501
                else:
                    msg = f"Finished {name} ({current}/{total}) [{elapsed:.1f}s]"
                update_progress("groups", pct, msg, current, total, name)

        group_result = process_all_event_groups(
            db_factory=db_factory,
            dispatcharr_client=dispatcharr_client,
            progress_callback=group_progress,
            generation=current_generation,  # Share generation across all groups
            service=shared_service,  # Reuse service to maintain warm cache
        )
        result.groups_processed = group_result.groups_processed
        result.groups_programmes = group_result.total_programmes
        result.programmes_total = result.teams_programmes + result.groups_programmes

        # Step 3b: Global channel reassignment (if enabled)
        _sync_global_channels(db_factory, dispatcharr_client, update_progress)

        # Step 3b: Apply stream ordering rules to all channels (93-95%)
        update_progress("ordering", 93, "Applying stream ordering rules...")
        result.stream_ordering = _apply_stream_ordering(
            db_factory, dispatcharr_client, update_progress
        )

        # Step 3c: Gold Zone channel (if enabled)
        gold_zone_result: GoldZoneResult | None = None
        if gold_zone_settings.enabled and dispatcharr_client:
            update_progress("gold_zone", 94, "Processing Gold Zone...")
            gold_zone_result = _process_gold_zone(
                db_factory, dispatcharr_client, gold_zone_settings,
                settings, update_progress,
            )

        # Step 4: Merge and save XMLTV (95-96%)
        update_progress("saving", 95, "Saving XMLTV...")

        xmltv_contents: list[str] = []
        with db_factory() as conn:
            team_xmltv = get_all_team_xmltv(conn)
            xmltv_contents.extend(team_xmltv)
            group_xmltv = get_all_group_xmltv(conn)
            xmltv_contents.extend(group_xmltv)

        # Inject Gold Zone external EPG if available
        if gold_zone_result and gold_zone_result.epg_xml:
            xmltv_contents.append(gold_zone_result.epg_xml)
            logger.info(
                "[GOLD_ZONE] Injected EPG into merge (%d bytes, channel_id=%s)",
                len(gold_zone_result.epg_xml),
                gold_zone_result.dispatcharr_channel_id,
            )
        elif gold_zone_result:
            logger.warning("[GOLD_ZONE] Result present but no EPG XML")
        elif gold_zone_settings.enabled:
            logger.warning("[GOLD_ZONE] Enabled but no result returned")

        output_path = settings.epg_output_path
        if xmltv_contents and output_path:
            merged_xmltv = merge_xmltv_content(
                xmltv_contents,
                generator_name=display_settings.xmltv_generator_name,
                generator_url=display_settings.xmltv_generator_url,
            )
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(merged_xmltv, encoding="utf-8")
            result.file_written = True
            result.file_path = str(output_file.absolute())
            result.file_size = len(merged_xmltv)
            logger.info(
                "[GENERATION] EPG written to %s (%s bytes)", output_path, f"{result.file_size:,}"
            )

        # Create lifecycle service once for steps 5-6
        # Reuse shared_service to maintain cache warmth
        lifecycle_service = create_lifecycle_service(
            db_factory,
            shared_service,
            dispatcharr_client=dispatcharr_client,
        )

        # Step 5: Dispatcharr EPG refresh + channel association (96-98%)
        if dispatcharr_client and dispatcharr_settings.epg_id:
            update_progress("dispatcharr", 96, "Refreshing Dispatcharr EPG...")
            from teamarr.dispatcharr.factory import DispatcharrConnection

            raw_client = (
                dispatcharr_client.client
                if isinstance(dispatcharr_client, DispatcharrConnection)
                else dispatcharr_client
            )
            epg_manager = EPGManager(raw_client)
            # Increased timeout from 60s to 120s for large EPGs
            refresh_result = epg_manager.wait_for_refresh(dispatcharr_settings.epg_id, timeout=120)
            result.epg_refresh = {
                "success": refresh_result.success,
                "message": refresh_result.message,
                "duration": refresh_result.duration,
            }

            update_progress("dispatcharr", 97, "Associating EPG with channels...")
            result.epg_association = lifecycle_service.associate_epg_with_channels(
                dispatcharr_settings.epg_id
            )

        # Step 6: Process scheduled deletions (98-99%)
        update_progress("lifecycle", 98, "Processing scheduled deletions...")
        channels_deleted_count = 0
        try:
            deletion_result = lifecycle_service.process_scheduled_deletions()
            channels_deleted_count = len(deletion_result.deleted)
            result.deletions = {
                "deleted_count": channels_deleted_count,
                "error_count": len(deletion_result.errors),
            }
            if deletion_result.deleted:
                logger.info("[GENERATION] Deleted %d expired channel(s)", channels_deleted_count)
        except Exception as e:
            logger.warning("[GENERATION] Scheduled deletions failed: %s", e)
            result.deletions = {"error": str(e)}

        # Step 7: Run reconciliation + cleanup (99-100%)
        update_progress("reconciliation", 99, "Running reconciliation...")
        try:
            with db_factory() as conn:
                recon_settings = get_reconciliation_settings(conn)
            if recon_settings.get("reconcile_on_epg_generation", True):
                reconciler = create_reconciler(db_factory, dispatcharr_client)
                recon_result = reconciler.reconcile(auto_fix=False)
                result.reconciliation = recon_result.summary
                if recon_result.issues_found:
                    logger.info("[RECONCILE] Found %d issue(s)", len(recon_result.issues_found))
        except Exception as e:
            logger.warning("[RECONCILE] Failed: %s", e)
            result.reconciliation = {"error": str(e)}

        # Cleanup (history, old runs, unused logos — part of step 7)
        update_progress("cleanup", 99, "Cleaning up history...")
        cleanup_results = _run_cleanup_tasks(db_factory, dispatcharr_client, update_progress)
        result.cleanup = cleanup_results["history"]
        result.logo_cleanup = cleanup_results["logos"]

        # Update and save stats run
        _finalize_stats_run(
            stats_run, result, team_result, group_result,
            channels_deleted_count, db_factory,
        )

        result.completed_at = time.time()
        result.duration_seconds = round(result.completed_at - result.started_at, 1)
        result.success = True

        update_progress("complete", 100, "Generation complete")

        # Flush the service cache to SQLite for immediate persistence
        from teamarr.services.sports_data import flush_shared_cache

        flushed = flush_shared_cache()
        if flushed > 0:
            logger.debug("[CACHE] Flushed %d entries to SQLite", flushed)

    except Exception as e:
        logger.exception("[GENERATION] Failed: %s", e)
        result.success = False
        result.error = str(e)
        result.completed_at = time.time()
        result.duration_seconds = round(result.completed_at - result.started_at, 1)

        # Save failed run
        try:
            from teamarr.database.stats import save_run as _save_run

            stats_run.complete(status="failed", error=str(e))
            with db_factory() as conn:
                _save_run(conn, stats_run)
        except Exception as save_err:
            logger.warning("[GENERATION] Failed to save failed run stats: %s", save_err)

    finally:
        # Always release the lock
        _generation_running = False
        _generation_lock.release()

    return result


def _refresh_m3u_accounts(db_factory: Callable[[], Any], dispatcharr_client: Any) -> dict:
    """Refresh M3U accounts for all event groups."""
    from teamarr.database.groups import get_all_groups
    from teamarr.dispatcharr import M3UManager

    result = {"refreshed": 0, "skipped": 0, "failed": 0, "account_ids": []}

    # Collect unique M3U account IDs from active groups
    with db_factory() as conn:
        groups = get_all_groups(conn, include_disabled=False)

    account_ids = set()
    for group in groups:
        if group.m3u_account_id:
            account_ids.add(group.m3u_account_id)

    if not account_ids:
        return result

    result["account_ids"] = list(account_ids)

    # Refresh all accounts in parallel
    from teamarr.dispatcharr.factory import DispatcharrConnection

    raw_client = (
        dispatcharr_client.client
        if isinstance(dispatcharr_client, DispatcharrConnection)
        else dispatcharr_client
    )
    m3u_manager = M3UManager(raw_client)
    batch_result = m3u_manager.refresh_multiple(
        list(account_ids),
        timeout=120,
        skip_if_recent_minutes=30,
    )

    result["refreshed"] = batch_result.succeeded_count - batch_result.skipped_count
    result["skipped"] = batch_result.skipped_count
    result["failed"] = batch_result.failed_count
    result["duration"] = batch_result.duration

    if batch_result.succeeded_count > 0:
        logger.info(
            "[M3U] Refresh: %d refreshed, %d skipped (recently updated)",
            result["refreshed"],
            result["skipped"],
        )

    return result


def _sync_global_channels(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
) -> None:
    """Reassign channel numbers globally by sport/league priority if enabled."""
    from teamarr.database.channel_numbers import reassign_channels_globally
    from teamarr.database.settings import get_channel_numbering_settings

    with db_factory() as conn:
        channel_numbering = get_channel_numbering_settings(conn)

    if channel_numbering.sorting_scope != "global":
        return

    update_progress("groups", 94, "Reassigning channels globally by sport/league priority...")
    with db_factory() as conn:
        global_result = reassign_channels_globally(conn)
        if global_result["channels_moved"] == 0:
            return

        logger.info(
            "[GENERATION] Global reassignment: %d channels processed, %d moved",
            global_result["channels_processed"],
            global_result["channels_moved"],
        )

        if not dispatcharr_client:
            return

        synced = 0
        for ch in global_result.get("drift_details", []):
            disp_id = ch.get("dispatcharr_channel_id")
            new_num = ch.get("new_number")
            if disp_id and new_num:
                try:
                    dispatcharr_client.channels.update_channel(
                        disp_id, {"channel_number": new_num}
                    )
                    synced += 1
                except Exception as e:
                    logger.warning(
                        "[GENERATION] Failed to sync channel %s to Dispatcharr: %s",
                        ch.get("channel_name"),
                        e,
                    )
        if synced:
            logger.info("[GENERATION] Synced %d channel numbers to Dispatcharr", synced)


def _apply_stream_ordering(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
) -> dict:
    """Apply stream ordering rules to all managed channels."""
    from teamarr.database.channels import (
        get_all_managed_channels,
        get_channel_streams,
        get_ordered_stream_ids,
        update_stream_priority,
    )
    from teamarr.database.settings import get_stream_ordering_settings
    from teamarr.services.stream_ordering import StreamOrderingService

    reorder_result: dict = {"channels_reordered": 0, "streams_reordered": 0}
    try:
        with db_factory() as conn:
            ordering_settings = get_stream_ordering_settings(conn)
            if not ordering_settings.rules:
                logger.debug("[ORDERING] No stream ordering rules configured, skipping")
                return reorder_result

            ordering_service = StreamOrderingService(
                rules=ordering_settings.rules, conn=conn
            )
            logger.info(
                "[ORDERING] Applying %d ordering rule(s)", len(ordering_settings.rules)
            )

            # Setup Dispatcharr channel manager once if available
            channel_mgr = None
            if dispatcharr_client:
                from teamarr.dispatcharr.factory import DispatcharrConnection
                from teamarr.dispatcharr.managers import ChannelManager

                raw_client = (
                    dispatcharr_client.client
                    if isinstance(dispatcharr_client, DispatcharrConnection)
                    else dispatcharr_client
                )
                channel_mgr = ChannelManager(raw_client)

            all_channels = get_all_managed_channels(conn, include_deleted=False)
            total_channels = len(all_channels)

            for idx, channel in enumerate(all_channels):
                streams = get_channel_streams(conn, channel.id)
                if not streams:
                    continue

                reordered_count = 0
                for stream in streams:
                    new_priority = ordering_service.compute_priority(stream)
                    if stream.priority != new_priority:
                        update_stream_priority(conn, stream.id, new_priority)
                        reordered_count += 1

                if reordered_count > 0:
                    reorder_result["channels_reordered"] += 1
                    reorder_result["streams_reordered"] += reordered_count

                    if channel_mgr and channel.dispatcharr_channel_id:
                        ordered_ids = get_ordered_stream_ids(conn, channel.id)
                        if ordered_ids:
                            sync_result = channel_mgr.update_channel(
                                channel.dispatcharr_channel_id, {"streams": ordered_ids}
                            )
                            if not sync_result.success:
                                logger.warning(
                                    "[ORDERING] Failed to sync channel %s to Dispatcharr: %s",
                                    channel.channel_name,
                                    sync_result.error,
                                )

                if (idx + 1) % 10 == 0 or idx == total_channels - 1:
                    pct = 93 + int(((idx + 1) / total_channels) * 2)
                    update_progress(
                        "ordering",
                        pct,
                        f"Ordering streams ({idx + 1}/{total_channels})",
                        idx + 1,
                        total_channels,
                        channel.channel_name,
                    )

            if reorder_result["channels_reordered"] > 0:
                logger.info(
                    "[ORDERING] Reordered %d streams across %d channels",
                    reorder_result["streams_reordered"],
                    reorder_result["channels_reordered"],
                )
    except Exception as e:
        logger.warning("[ORDERING] Stream ordering failed: %s", e)
        reorder_result["error"] = str(e)

    return reorder_result


def _run_cleanup_tasks(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
) -> dict:
    """Run all post-generation cleanup: history, old runs, unused logos."""
    from teamarr.database.channels import cleanup_old_history, get_reconciliation_settings

    results: dict = {"history": {}, "logos": {}}

    # History cleanup
    try:
        with db_factory() as conn:
            cleanup_settings = get_reconciliation_settings(conn)
            retention_days = cleanup_settings.get("channel_history_retention_days", 90)
            deleted_count = cleanup_old_history(conn, retention_days)
            results["history"] = {"deleted_count": deleted_count}
            if deleted_count > 0:
                logger.info("[CLEANUP] Removed %d old history record(s)", deleted_count)
    except Exception as e:
        logger.warning("[CLEANUP] History cleanup failed: %s", e)
        results["history"] = {"error": str(e)}

    # Old processing runs (>30 days)
    try:
        from teamarr.database.stats import cleanup_old_runs

        with db_factory() as conn:
            runs_deleted = cleanup_old_runs(conn, days=30)
            if runs_deleted > 0:
                logger.info("[CLEANUP] Removed %d old processing run(s)", runs_deleted)
    except Exception as e:
        logger.warning("[CLEANUP] Run history cleanup failed: %s", e)

    # Unused logos
    try:
        from teamarr.database.settings import get_dispatcharr_settings

        with db_factory() as conn:
            dispatcharr_settings = get_dispatcharr_settings(conn)
        if dispatcharr_settings.cleanup_unused_logos and dispatcharr_client:
            update_progress("cleanup", 99, "Cleaning up unused logos...")
            cleanup_result = dispatcharr_client.logos.cleanup_unused()
            if cleanup_result.success:
                logos_deleted = (
                    cleanup_result.data.get("deleted_count", 0) if cleanup_result.data else 0
                )
                results["logos"] = {"deleted_count": logos_deleted}
                if logos_deleted > 0:
                    logger.info("[CLEANUP] Removed %d unused logo(s)", logos_deleted)
            else:
                logger.warning("[CLEANUP] Logo cleanup failed: %s", cleanup_result.error)
                results["logos"] = {"error": cleanup_result.error}
    except Exception as e:
        logger.warning("[CLEANUP] Logo cleanup failed: %s", e)
        results["logos"] = {"error": str(e)}

    return results


def _finalize_stats_run(
    stats_run: Any,
    result: GenerationResult,
    team_result: Any,
    group_result: Any,
    channels_deleted_count: int,
    db_factory: Callable[[], Any],
) -> None:
    """Populate stats run with generation results and save to database."""
    from teamarr.database.channels import get_all_managed_channels
    from teamarr.database.stats import save_run

    stats_run.programmes_total = result.programmes_total
    stats_run.programmes_events = team_result.total_events + group_result.total_events
    stats_run.programmes_pregame = team_result.total_pregame + group_result.total_pregame
    stats_run.programmes_postgame = team_result.total_postgame + group_result.total_postgame
    stats_run.programmes_idle = team_result.total_idle
    stats_run.channels_created = group_result.total_channels_created
    stats_run.channels_deleted = channels_deleted_count + group_result.total_channels_deleted
    stats_run.xmltv_size_bytes = result.file_size
    stats_run.streams_fetched = group_result.total_streams_fetched
    stats_run.streams_matched = group_result.total_streams_matched
    stats_run.streams_unmatched = group_result.total_streams_unmatched
    stats_run.extra_metrics["teams_processed"] = result.teams_processed
    stats_run.extra_metrics["groups_processed"] = result.groups_processed
    stats_run.extra_metrics["file_written"] = result.file_written

    with db_factory() as conn:
        active_channels = get_all_managed_channels(conn, include_deleted=False)
        stats_run.channels_active = len(active_channels)
        logger.info("[GENERATION] %d active managed channels", len(active_channels))

    stats_run.complete(status="completed")

    with db_factory() as conn:
        save_run(conn, stats_run)


# =============================================================================
# GOLD ZONE (Olympics Special Feature)
# =============================================================================

# Match terms for Gold Zone streams (case-insensitive)
_GOLD_ZONE_PATTERNS = ["gold zone", "goldzone", "gold-zone"]

# External EPG source
_GOLD_ZONE_EPG_URL = "https://epg.jesmann.com/TeamSports/goldzone.xml"

# XMLTV identifiers (must match the external EPG)
_GOLD_ZONE_TVG_ID = "GoldZone.us"
_GOLD_ZONE_CHANNEL_NAME = "Gold Zone"
_GOLD_ZONE_LOGO = "https://emby.tmsimg.com/assets/p32146358_b_h9_ab.jpg"


@dataclass
class GoldZoneResult:
    """Result of Gold Zone processing."""

    epg_xml: str | None = None
    dispatcharr_channel_id: int | None = None


def _process_gold_zone(
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
    import re

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
            date_ok, parsed_date = _gold_zone_stream_date_check(s.name)
            if not date_ok:
                skipped_date += 1
                logger.debug(
                    "[GOLD_ZONE] Skipping '%s' — date %s is not today", s.name, parsed_date
                )
                continue
            matched_streams.append(s)
            if first_event_group_id is None:
                first_event_group_id = m3u_to_event_group.get(s.channel_group)

    if skipped_date:
        logger.info("[GOLD_ZONE] Skipped %d streams with non-today dates", skipped_date)

    if not matched_streams:
        logger.info(
            "[GOLD_ZONE] No matching streams found across %d M3U groups",
            len(m3u_group_ids),
        )
        return None

    # Apply stream ordering rules (same priority system as regular channels)
    gold_zone_stream_ids = _order_gold_zone_streams(
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

    # Convert profile IDs: null = all profiles → [0] sentinel for Dispatcharr
    profile_ids = gold_zone_settings.channel_profile_ids
    if profile_ids is None:
        disp_profile_ids = [0]  # All profiles
    else:
        disp_profile_ids = [int(p) for p in profile_ids if not isinstance(p, str)]

    dispatcharr_channel_id: int | None = None

    try:
        channel_manager = dispatcharr_client.channels

        # Check if channel already exists by tvg_id
        existing = channel_manager.find_by_tvg_id(_GOLD_ZONE_TVG_ID)
        if existing:
            dispatcharr_channel_id = existing.id
            # Update existing channel with current streams + settings
            update_data: dict = {
                "name": _GOLD_ZONE_CHANNEL_NAME,
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
                name=_GOLD_ZONE_CHANNEL_NAME,
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
            "channel_name": _GOLD_ZONE_CHANNEL_NAME,
            "channel_group_id": channel_group_id,
            "channel_profile_ids": profile_ids or [],
            "event_name": _GOLD_ZONE_CHANNEL_NAME,
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
                        channel_name=_GOLD_ZONE_CHANNEL_NAME,
                        dispatcharr_channel_id=dispatcharr_channel_id,
                        channel_group_id=channel_group_id,
                        channel_profile_ids=profile_ids or [],
                        logo_url=_GOLD_ZONE_LOGO,
                        sport="olympics",
                        event_name=_GOLD_ZONE_CHANNEL_NAME,
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
        gz_result.epg_xml = _filter_gold_zone_epg(raw_xml, epg_settings)
    except Exception as e:
        logger.error("[GOLD_ZONE] Failed to filter EPG: %s", e)
        gz_result.epg_xml = raw_xml  # Fall back to unfiltered

    return gz_result


def _filter_gold_zone_epg(raw_xml: str, epg_settings: Any) -> str:
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


def _order_gold_zone_streams(
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


def _gold_zone_stream_date_check(stream_name: str) -> tuple[bool, str | None]:
    """Check if a Gold Zone stream name contains a date, and if so whether it's today.

    Reuses the normalizer's extract_and_mask_datetime which already handles:
    YYYY-MM-DD, MM/DD/YYYY, MM/DD, "Feb 9", "9 Feb", etc.

    Logic:
    - No date found → include (True, None)
    - Date matches today (user tz) → include (True, date_str)
    - Date does NOT match today → exclude (False, date_str)

    Returns:
        (is_ok, parsed_date_str) — is_ok=True means include the stream
    """
    from teamarr.consumers.matching.normalizer import extract_and_mask_datetime
    from teamarr.utilities.tz import now_user

    _, extracted_date, _, _ = extract_and_mask_datetime(stream_name)

    if extracted_date is None:
        return True, None

    today = now_user().date()
    date_str = extracted_date.isoformat()
    if extracted_date.month == today.month and extracted_date.day == today.day:
        return True, date_str
    return False, date_str

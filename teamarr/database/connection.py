"""Database connection management.

Simple SQLite connection handling with schema initialization.
"""

import json
import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from teamarr.database.checkpoint_v43 import apply_checkpoint_v43

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "teamarr.db"

# Schema file location
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Global flag for V1 database detection (set during init, checked by migration)
_v1_database_detected = False


def is_v1_database_detected() -> bool:
    """Check if a V1 database was detected during initialization."""
    return _v1_database_detected


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a database connection.

    Args:
        db_path: Path to database file. Uses DEFAULT_DB_PATH if not specified.

    Returns:
        SQLite connection with row factory set to sqlite3.Row
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH

    # timeout=60: Wait up to 60 seconds if database is locked by another connection
    # check_same_thread=False: Allow connection to be used across threads (required for FastAPI)
    conn = sqlite3.connect(path, timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Enable Write-Ahead Logging for better concurrent access
    # WAL allows readers to not block writers and vice versa
    conn.execute("PRAGMA journal_mode=WAL")

    # Wait up to 60 seconds if a table is locked (milliseconds)
    conn.execute("PRAGMA busy_timeout=60000")

    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


@contextmanager
def get_db(db_path: Path | str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections.

    Usage:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM teams")
            teams = cursor.fetchall()
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database with schema.

    Creates tables if they don't exist. Safe to call multiple times.
    Also seeds TSDB cache from distributed seed file if needed.

    Args:
        db_path: Path to database file. Uses DEFAULT_DB_PATH if not specified.

    Raises:
        RuntimeError: If database file exists but is not a valid V2 database
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    schema_sql = SCHEMA_PATH.read_text()

    try:
        with get_db(db_path) as conn:
            # First, verify this is a valid V2-compatible database by checking integrity
            # and querying a core table. This catches both corruption AND V1 databases.
            _verify_database_integrity(conn, path)

            # If V1 database detected, skip schema initialization - only migration endpoints work
            if _v1_database_detected:
                logger.info("[MIGRATE] Skipping V2 schema initialization for V1 database")
                return

            # Pre-migration: rename league_id_alias -> league_id before schema.sql runs
            # (schema.sql references league_id column in INSERT OR REPLACE)
            _rename_league_id_column_if_needed(conn)

            # Pre-migration: add league_alias column before schema.sql runs
            # (schema.sql INSERT OR REPLACE references league_alias column)
            _add_league_alias_column_if_needed(conn)

            # Pre-migration: add gracenote_category column before schema.sql runs
            # (schema.sql INSERT OR REPLACE references gracenote_category column)
            _add_gracenote_category_column_if_needed(conn)

            # Pre-migration: add logo_url_dark column before schema.sql runs
            # (schema.sql INSERT OR REPLACE references logo_url_dark column)
            _add_logo_url_dark_column_if_needed(conn)

            # Pre-migration: add series_slug_pattern column before schema.sql runs
            # (schema.sql UPDATE statements reference series_slug_pattern column)
            _add_series_slug_pattern_column_if_needed(conn)

            # Pre-migration: add fallback_provider and fallback_league_id columns
            # (schema.sql INSERT OR REPLACE references these columns)
            _add_fallback_columns_if_needed(conn)

            # Pre-migration: rename exception keywords columns before schema.sql runs
            # (schema.sql INSERT OR IGNORE references label and match_terms columns)
            _migrate_exception_keywords_columns(conn)

            # Apply schema (creates tables if missing, INSERT OR REPLACE updates seed data)
            conn.executescript(schema_sql)
            # Run remaining migrations for existing databases
            _run_migrations(conn)
            # Seed TSDB cache if empty or incomplete
            _seed_tsdb_cache_if_needed(conn)

            # Final verification: ensure settings table exists and is queryable
            conn.execute("SELECT id FROM settings LIMIT 1")
    except sqlite3.DatabaseError as e:
        if "file is not a database" in str(e):
            logger.error(
                f"Database file '{path}' exists but is not compatible with Teamarr V2. "
                "This usually means you're trying to use a V1 database. "
                "V2 requires a fresh database - please either:\n"
                "  1. Use a different data directory for V2, or\n"
                "  2. Backup and delete the existing database file"
            )
            raise RuntimeError(
                f"Incompatible database file at '{path}'. "
                "V2 is not compatible with V1 databases. "
                "Please use a fresh data directory or delete the existing database."
            ) from e
        raise


def _verify_database_integrity(conn: sqlite3.Connection, path: Path) -> None:
    """Verify database is valid and compatible with V2.

    This runs BEFORE schema initialization to catch:
    1. Corrupt database files ("file is not a database")
    2. V1 databases (different schema, incompatible)

    Args:
        conn: Database connection
        path: Path to database file for error messages

    Raises:
        RuntimeError: If database is a V1 database
        sqlite3.DatabaseError: If database file is corrupt
    """
    # Force an actual read from the file to detect corruption early
    # PRAGMA integrity_check would be thorough but slow; just query sqlite_master
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 100")
        existing_tables = {row["name"] for row in cursor.fetchall()}
    except sqlite3.DatabaseError:
        # Let the outer handler deal with "file is not a database" errors
        raise

    # Check for V1-specific tables that indicate an incompatible database
    # These tables exist only in V1 and NOT in V2
    v1_indicators = {
        "schedule_cache",  # V1 caching
        "league_config",  # V1 league configuration
        "h2h_cache",  # V1 head-to-head (removed in V2)
        "error_log",  # V1 error logging
        "soccer_cache_meta",  # V1 soccer-specific cache
        "team_stats_cache",  # V1 stats cache
    }
    v1_tables_found = v1_indicators & existing_tables

    if v1_tables_found:
        logger.warning(
            f"Database file '{path}' appears to be a V1 database. "
            f"Found V1-specific tables: {v1_tables_found}. "
            "V2 migration page will be shown to the user."
        )
        # Set global flag for V1 detection - don't raise error, let migration handle it
        global _v1_database_detected
        _v1_database_detected = True


def _rename_league_id_column_if_needed(conn: sqlite3.Connection) -> None:
    """Rename league_id_alias -> league_id if needed.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the new column name.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if old column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "league_id_alias" in columns and "league_id" not in columns:
        conn.execute("ALTER TABLE leagues RENAME COLUMN league_id_alias TO league_id")
        logger.info("[MIGRATE] Renamed leagues.league_id_alias -> league_id")


def _add_league_alias_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add league_alias column if it doesn't exist.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the league_alias column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "league_alias" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN league_alias TEXT")
        logger.info("[MIGRATE] Added leagues.league_alias column")


def _add_gracenote_category_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add gracenote_category column if it doesn't exist.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the gracenote_category column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "gracenote_category" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN gracenote_category TEXT")
        logger.info("[MIGRATE] Added leagues.gracenote_category column")


def _add_logo_url_dark_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add logo_url_dark column if it doesn't exist.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the logo_url_dark column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "logo_url_dark" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN logo_url_dark TEXT")
        logger.info("[MIGRATE] Added leagues.logo_url_dark column")


def _add_series_slug_pattern_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add series_slug_pattern column if it doesn't exist.

    This is needed for Cricbuzz auto-discovery of current season series IDs.
    MUST run before schema.sql because UPDATE statements reference this column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "series_slug_pattern" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN series_slug_pattern TEXT")
        logger.info("[MIGRATE] Added leagues.series_slug_pattern column")


def _add_fallback_columns_if_needed(conn: sqlite3.Connection) -> None:
    """Add fallback_provider and fallback_league_id columns if they don't exist.

    These columns enable provider fallback for leagues where the primary provider
    may have limited availability (e.g., TSDB premium vs free tier for cricket).
    MUST run before schema.sql because INSERT OR REPLACE references these columns.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct columns

    # Check which columns exist
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "fallback_provider" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN fallback_provider TEXT")
        logger.info("[MIGRATE] Added leagues.fallback_provider column")

    if "fallback_league_id" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN fallback_league_id TEXT")
        logger.info("[MIGRATE] Added leagues.fallback_league_id column")


def _migrate_exception_keywords_columns(conn: sqlite3.Connection) -> None:
    """Migrate exception keywords table: keywords -> match_terms, display_name -> label.

    MUST run before schema.sql because INSERT OR IGNORE references the new column names.
    This pre-migration recreates the table with new column names and migrates data.
    """
    # Check if table exists
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='consolidation_exception_keywords'"  # noqa: E501
    )
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct columns

    # Check if migration needed (old columns exist)
    cursor = conn.execute("PRAGMA table_info(consolidation_exception_keywords)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "label" in columns and "match_terms" in columns:
        return  # Already migrated

    if "keywords" not in columns:
        return  # Unknown schema, skip

    logger.info(
        "[PRE-MIGRATE] Migrating exception keywords: keywords -> match_terms, display_name -> label"
    )

    # Get existing data
    cursor = conn.execute("""
        SELECT id, created_at, keywords, behavior, display_name, enabled
        FROM consolidation_exception_keywords
    """)
    existing_rows = cursor.fetchall()

    # Drop old table
    conn.execute("DROP TABLE consolidation_exception_keywords")

    # Create new table with updated schema
    conn.execute("""
        CREATE TABLE consolidation_exception_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            label TEXT NOT NULL UNIQUE,
            match_terms TEXT NOT NULL,
            behavior TEXT NOT NULL DEFAULT 'consolidate'
                CHECK(behavior IN ('consolidate', 'separate', 'ignore')),
            enabled BOOLEAN DEFAULT 1
        )
    """)

    # Migrate data - use display_name as label if set, otherwise first keyword
    for row in existing_rows:
        keywords = row["keywords"] or ""
        display_name = row["display_name"]

        # Determine label: use display_name if set, otherwise first keyword
        if display_name:
            label = display_name
        else:
            first_keyword = keywords.split(",")[0].strip() if keywords else "Unknown"
            label = first_keyword

        conn.execute(
            """INSERT INTO consolidation_exception_keywords
               (id, created_at, label, match_terms, behavior, enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                row["id"],
                row["created_at"],
                label,
                keywords,
                row["behavior"],
                row["enabled"],
            ),
        )

    # Recreate indexes
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exception_keywords_enabled
        ON consolidation_exception_keywords(enabled)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exception_keywords_behavior
        ON consolidation_exception_keywords(behavior)
    """)

    logger.info("[PRE-MIGRATE] Migrated %d exception keywords", len(existing_rows))


def _seed_tsdb_cache_if_needed(conn: sqlite3.Connection) -> None:
    """Seed TSDB cache from distributed seed file if needed."""
    from teamarr.database.seed import seed_if_needed

    result = seed_if_needed(conn)
    if result and result.get("seeded"):
        logger.info(
            f"Seeded TSDB cache: {result.get('teams_added', 0)} teams, "
            f"{result.get('leagues_added', 0)} leagues"
        )


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run database migrations for existing databases.

    Uses schema_version in settings table to track applied migrations.
    Safe to call multiple times - checks version before running.

    Schema versions:
    - 2: Initial V2 schema
    - 3: Teams consolidated (league -> primary_league + leagues array)
    - 4: Added eng.2 (Championship), eng.3 (League One), nrl leagues; fixed NRL logo
    - 5: Renamed league_id_alias -> league_id
    - 6: Added league_alias column, fixed managed_channels UNIQUE constraint
    - 7: Added gracenote_category column
    - 8: Added custom_regex_date/time columns to event_epg_groups
    - 9: Added keyword_ordering to change_source CHECK constraint
    - 10: Updated channel timing CHECK constraints
    - 11: Removed UNIQUE constraint from tvg_id
    - 12: Removed per-group timing settings
    - 13: Added display_name to event_epg_groups
    - 14: Added streams_excluded to event_epg_groups
    - 15: Renamed filtered_no_match -> failed_count (clearer stat categories)
    - 16-22: Various additions (see individual migrations)
    - 23: Added default_channel_profile_ids to settings
    - 24: Added excluded and exclusion_reason to epg_matched_streams
    - 25: Changed event_epg_groups name uniqueness from global to per-account
    - 46: Added stream_profile_id to event_epg_groups
    - 47: Added stream_timezone to event_epg_groups
    - 48: Added channel_reset_enabled and channel_reset_cron to settings
    - 49: Added combat sports custom regex columns (fighters, event_name, config)
    """
    # Get current schema version
    try:
        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        current_version = row["schema_version"] if row else 2
    except Exception:
        current_version = 2

    # ==========================================================================
    # CHECKPOINT v43: Consolidated migration for versions 2-43
    # ==========================================================================
    # Instead of running 43 individual procedural migrations, we use a single
    # idempotent checkpoint that ensures the v43 schema state regardless of
    # starting version. This is safer and handles partial migrations better.
    #
    # The checkpoint replaces all v3-v43 migrations below. The old migration
    # code is preserved but will be skipped since version becomes 43.
    # ==========================================================================
    if current_version < 43:
        logger.info("[MIGRATE] Applying v43 checkpoint (from v%d)", current_version)
        apply_checkpoint_v43(conn, current_version)
        current_version = 43
        logger.info("[MIGRATE] Checkpoint complete, now at v43")

    # Legacy v3-v43 migrations removed — checkpoint system stable since v2.1.0.

    # ==========================================================================
    # v44+: NEW MIGRATIONS (using checkpoint patterns)
    # ==========================================================================

    # v44: Update Check Settings
    # Adds settings for update notifications (GitHub releases/commits)
    if current_version < 44:
        _add_column_if_not_exists(conn, "settings", "update_check_enabled", "BOOLEAN DEFAULT 1")
        _add_column_if_not_exists(conn, "settings", "update_notify_stable", "BOOLEAN DEFAULT 1")
        _add_column_if_not_exists(conn, "settings", "update_notify_dev", "BOOLEAN DEFAULT 1")
        _add_column_if_not_exists(
            conn, "settings", "update_github_owner", "TEXT DEFAULT 'Pharaoh-Labs'"
        )
        _add_column_if_not_exists(conn, "settings", "update_github_repo", "TEXT DEFAULT 'teamarr'")
        _add_column_if_not_exists(conn, "settings", "update_dev_branch", "TEXT DEFAULT 'dev'")
        _add_column_if_not_exists(
            conn, "settings", "update_auto_detect_branch", "BOOLEAN DEFAULT 1"
        )
        conn.execute("UPDATE settings SET schema_version = 44 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 44 (update check settings)")
        current_version = 44

    # ==========================================================================
    # v45: Logo Cleanup Setting
    # ==========================================================================
    # Adds cleanup_unused_logos setting to call Dispatcharr's bulk cleanup API
    # after EPG generation instead of per-channel logo deletion
    if current_version < 45:
        _add_column_if_not_exists(
            conn, "settings", "cleanup_unused_logos", "BOOLEAN DEFAULT 0"
        )
        conn.execute("UPDATE settings SET schema_version = 45 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 45 (logo cleanup setting)")
        current_version = 45

    # ==========================================================================
    # v46: Stream Profile Support
    # ==========================================================================
    # Adds stream_profile_id to settings (global default) and event_epg_groups (per-group override)
    if current_version < 46:
        _add_column_if_not_exists(
            conn, "settings", "default_stream_profile_id", "INTEGER"
        )
        _add_column_if_not_exists(
            conn, "event_epg_groups", "stream_profile_id", "INTEGER"
        )
        conn.execute("UPDATE settings SET schema_version = 46 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 46 (stream profile support)")
        current_version = 46

    # ==========================================================================
    # v47: Stream Timezone Support
    # ==========================================================================
    # Adds stream_timezone to event_epg_groups for interpreting dates/times in stream names
    # when providers use a different timezone than the user's local timezone
    if current_version < 47:
        _add_column_if_not_exists(conn, "event_epg_groups", "stream_timezone", "TEXT")
        conn.execute("UPDATE settings SET schema_version = 47 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 47 (stream timezone support)")
        current_version = 47

    # ==========================================================================
    # v48: Scheduled Channel Reset
    # ==========================================================================
    # Adds channel_reset_enabled and channel_reset_cron to settings for scheduling
    # periodic channel purges (helps users with Jellyfin logo caching issues)
    if current_version < 48:
        _add_column_if_not_exists(conn, "settings", "channel_reset_enabled", "BOOLEAN DEFAULT 0")
        _add_column_if_not_exists(conn, "settings", "channel_reset_cron", "TEXT")
        conn.execute("UPDATE settings SET schema_version = 48 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 48 (scheduled channel reset)")
        current_version = 48

    # ==========================================================================
    # v49: Combat Sports Custom Regex Columns
    # ==========================================================================
    # Adds custom regex columns for EVENT_CARD type events (UFC, Boxing, MMA)
    # - custom_regex_fighters: Extract fighter names from stream titles
    # - custom_regex_event_name: Extract event name from stream titles
    # - custom_regex_config: JSON structure for organized event-type regex patterns
    if current_version < 49:
        _add_column_if_not_exists(conn, "event_epg_groups", "custom_regex_fighters", "TEXT")
        _add_column_if_not_exists(
            conn, "event_epg_groups", "custom_regex_fighters_enabled", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(conn, "event_epg_groups", "custom_regex_event_name", "TEXT")
        _add_column_if_not_exists(
            conn, "event_epg_groups", "custom_regex_event_name_enabled", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(conn, "event_epg_groups", "custom_regex_config", "JSON")
        conn.execute("UPDATE settings SET schema_version = 49 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 49 (combat sports custom regex)")
        current_version = 49

    # ==========================================================================
    # v50: Soccer Selection Modes
    # ==========================================================================
    # Adds soccer_mode column for granular soccer league selection:
    # - 'all': Subscribe to all soccer leagues, auto-include new ones
    # - 'teams': Follow selected teams across their competitions
    # - 'manual': Explicit league selection (preserves trimmed selections)
    # - NULL: Non-soccer groups
    #
    # Migration logic:
    # - Groups with ALL available soccer leagues -> 'all'
    # - Groups with a SUBSET of soccer leagues -> 'manual' (preserve user's work)
    if current_version < 50:
        _add_column_if_not_exists(conn, "event_epg_groups", "soccer_mode", "TEXT")

        # Get all available soccer leagues from the leagues table
        # Wrap in try-except for minimal test databases that may not have leagues table
        all_soccer_leagues: set[str] = set()
        try:
            cursor = conn.execute(
                "SELECT league_code FROM leagues WHERE sport = 'soccer' AND enabled = 1"
            )
            all_soccer_leagues = {row[0] for row in cursor.fetchall()}
        except sqlite3.OperationalError:
            # Table doesn't exist or missing columns - skip migration logic
            pass

        total_soccer_count = len(all_soccer_leagues)

        if total_soccer_count > 0:
            # Migrate existing groups that contain soccer leagues
            cursor = conn.execute(
                "SELECT id, leagues FROM event_epg_groups WHERE leagues IS NOT NULL"
            )
            for row in cursor.fetchall():
                group_id = row[0]
                try:
                    leagues_json = row[1]
                    if not leagues_json:
                        continue
                    group_leagues = set(json.loads(leagues_json))

                    # Find soccer leagues in this group
                    group_soccer = group_leagues & all_soccer_leagues

                    if not group_soccer:
                        # No soccer leagues in this group - leave soccer_mode as NULL
                        continue

                    if group_soccer == all_soccer_leagues:
                        # Has ALL soccer leagues -> 'all' mode
                        conn.execute(
                            "UPDATE event_epg_groups SET soccer_mode = 'all' WHERE id = ?",
                            (group_id,),
                        )
                    else:
                        # Has SUBSET of soccer leagues -> 'manual' mode (preserve their selection)
                        conn.execute(
                            "UPDATE event_epg_groups SET soccer_mode = 'manual' WHERE id = ?",
                            (group_id,),
                        )
                except (json.JSONDecodeError, TypeError):
                    # Skip groups with invalid JSON
                    continue

        conn.execute("UPDATE settings SET schema_version = 50 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 50 (soccer selection modes)")
        current_version = 50

    # v51: Add soccer_followed_teams for 'teams' mode
    # Stores [{provider, team_id, name}] for teams the user wants to follow
    # Leagues are auto-discovered from team_cache at processing time
    if current_version < 51:
        _add_column_if_not_exists(conn, "event_epg_groups", "soccer_followed_teams", "TEXT")
        conn.execute("UPDATE settings SET schema_version = 51 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 51 (soccer followed teams)")
        current_version = 51

    # v52: Bypass team filter for playoffs (issue #70)
    # Global default in settings, per-group override in event_epg_groups
    if current_version < 52:
        _add_column_if_not_exists(
            conn, "settings", "default_bypass_filter_for_playoffs", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(
            conn, "event_epg_groups", "bypass_filter_for_playoffs", "BOOLEAN"
        )
        conn.execute("UPDATE settings SET schema_version = 52 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 52 (playoff filter bypass)")
        current_version = 52

    # v53: Bump api_timeout default from 10 to 30
    # The DispatcharrClient always used 30s effectively, but the DB setting
    # (which was never wired up) defaulted to 10. Now that we wire it up,
    # bump existing users from 10 → 30 to avoid a timeout regression.
    if current_version < 53:
        conn.execute("UPDATE settings SET api_timeout = 30 WHERE api_timeout = 10 AND id = 1")
        conn.execute("UPDATE settings SET api_retry_count = 5 WHERE api_retry_count = 3 AND id = 1")
        conn.execute("UPDATE settings SET schema_version = 53 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 53 (api timeout/retry defaults)")
        current_version = 53

    # v54: Add scheduled backup settings columns
    # Automatic database backups with rotation and protection
    if current_version < 54:
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_enabled", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_cron", "TEXT DEFAULT '0 3 * * *'"
        )
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_max_count", "INTEGER DEFAULT 7"
        )
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_path", "TEXT DEFAULT './data/backups'"
        )
        conn.execute("UPDATE settings SET schema_version = 54 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 54 (scheduled backup settings)")
        current_version = 54

    # v55: Gold Zone (Olympics Special Feature)
    # Consolidates "Gold Zone" streams into a single channel with external EPG
    if current_version < 55:
        _add_column_if_not_exists(conn, "settings", "gold_zone_enabled", "BOOLEAN DEFAULT 0")
        _add_column_if_not_exists(conn, "settings", "gold_zone_channel_number", "INTEGER")
        conn.execute("UPDATE settings SET schema_version = 55 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 55 (gold zone)")
        current_version = 55

    if current_version < 56:
        _add_column_if_not_exists(conn, "settings", "gold_zone_channel_group_id", "INTEGER")
        _add_column_if_not_exists(conn, "settings", "gold_zone_channel_profile_ids", "TEXT")
        _add_column_if_not_exists(conn, "settings", "gold_zone_stream_profile_id", "INTEGER")
        conn.execute("UPDATE settings SET schema_version = 56 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 56 (gold zone profiles)")
        current_version = 56


# =============================================================================
# LEGACY MIGRATION HELPER FUNCTIONS
# =============================================================================
# STATUS: DEPRECATED - Scheduled for removal with legacy migrations above
#
# These helper functions are only called by the legacy v3-v43 migrations.
# They are preserved as part of the safety fallback.
# Delete these when removing the legacy migration code above.
# =============================================================================






























def _add_column_if_not_exists(
    conn: sqlite3.Connection, table: str, column: str, column_def: str
) -> None:
    """Add a column to a table if it doesn't exist.

    Args:
        conn: Database connection
        table: Table name
        column: Column name to add
        column_def: Column definition (type and default)
    """
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = {row["name"] for row in cursor.fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")










def reset_db(db_path: Path | str | None = None) -> None:
    """Reset database - drops all tables and reinitializes.

    WARNING: This deletes all data!

    Args:
        db_path: Path to database file. Uses DEFAULT_DB_PATH if not specified.
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH

    if path.exists():
        path.unlink()

    init_db(path)

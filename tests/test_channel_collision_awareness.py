"""Tests for channel number collision awareness (epic wq8, GitHub #146).

Teamarr must skip channel numbers already occupied by non-Teamarr channels
in Dispatcharr to prevent EPG data bleeding between channels.
"""

import sqlite3

import pytest


@pytest.fixture
def conn():
    """Create in-memory SQLite database with required schema."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            channel_range_start INTEGER DEFAULT 101,
            channel_range_end INTEGER,
            channel_numbering_mode TEXT DEFAULT 'strict_block',
            channel_sorting_scope TEXT DEFAULT 'per_group'
        )
    """)
    db.execute("""
        INSERT INTO settings (id, channel_range_start, channel_range_end,
                              channel_numbering_mode, channel_sorting_scope)
        VALUES (1, 101, NULL, 'strict_block', 'per_group')
    """)
    db.execute("""
        CREATE TABLE event_epg_groups (
            id INTEGER PRIMARY KEY,
            name TEXT,
            channel_start_number INTEGER,
            channel_assignment_mode TEXT DEFAULT 'manual',
            sort_order INTEGER DEFAULT 0,
            total_stream_count INTEGER DEFAULT 0,
            parent_group_id INTEGER,
            enabled INTEGER DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE managed_channels (
            id INTEGER PRIMARY KEY,
            event_epg_group_id INTEGER,
            channel_number TEXT,
            deleted_at TEXT,
            dispatcharr_channel_id INTEGER,
            channel_name TEXT,
            primary_stream_id TEXT,
            sport TEXT,
            league TEXT,
            event_date TEXT,
            created_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE channel_sort_priorities (
            id INTEGER PRIMARY KEY,
            sport TEXT,
            league_code TEXT,
            sort_priority INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    db.commit()
    yield db
    db.close()


class TestGetNextChannelNumberWithExternals:
    """Test get_next_channel_number skips external occupied numbers."""

    def test_manual_skips_external_numbers(self, conn):
        """MANUAL mode skips externally occupied channel numbers."""
        from teamarr.database.channel_numbers import get_next_channel_number

        # Group starts at 500
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_start_number, "
            "channel_assignment_mode) VALUES (1, 'NHL', 500, 'manual')"
        )
        conn.commit()

        # External channels at 500, 501, 502
        external = {500, 501, 502}

        result = get_next_channel_number(conn, 1, external_occupied=external)
        assert result == 503

    def test_manual_skips_both_teamarr_and_external(self, conn):
        """MANUAL mode skips both Teamarr managed and external numbers."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_start_number, "
            "channel_assignment_mode) VALUES (1, 'NHL', 500, 'manual')"
        )
        # Teamarr already has 503
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number) "
            "VALUES (1, 1, '503')"
        )
        conn.commit()

        # External at 500, 501, 502
        external = {500, 501, 502}

        result = get_next_channel_number(conn, 1, external_occupied=external)
        # Skips 500-502 (external) and 503 (Teamarr) → 504
        assert result == 504

    def test_no_externals_works_as_before(self, conn):
        """Without external_occupied, behavior is unchanged."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_start_number, "
            "channel_assignment_mode) VALUES (1, 'NHL', 500, 'manual')"
        )
        conn.commit()

        result = get_next_channel_number(conn, 1, external_occupied=None)
        assert result == 500

    def test_empty_externals_works_as_before(self, conn):
        """Empty external set is same as None."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_start_number, "
            "channel_assignment_mode) VALUES (1, 'NHL', 500, 'manual')"
        )
        conn.commit()

        result = get_next_channel_number(conn, 1, external_occupied=set())
        assert result == 500

    def test_large_gap_skips_to_end(self, conn):
        """When externals fill the entire range, assignment lands past them."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_start_number, "
            "channel_assignment_mode) VALUES (1, 'NHL', 100, 'manual')"
        )
        conn.commit()

        # External channels cover 100-15000 (like Bob's 15k IPTV channels)
        external = set(range(100, 15001))

        result = get_next_channel_number(conn, 1, external_occupied=external)
        assert result == 15001

    def test_scattered_externals_finds_first_gap(self, conn):
        """Scattered externals: assignment finds first available number."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_start_number, "
            "channel_assignment_mode) VALUES (1, 'NHL', 500, 'manual')"
        )
        conn.commit()

        # External at 500, 502, 504 — gaps at 501, 503, 505
        external = {500, 502, 504}

        result = get_next_channel_number(conn, 1, external_occupied=external)
        assert result == 501


class TestStrictCompactWithExternals:
    """Test strict_compact mode skips external numbers."""

    def test_compact_skips_externals(self, conn):
        """strict_compact mode skips external channel numbers."""
        from teamarr.database.channel_numbers import get_next_compact_channel_number

        # External channels at 101, 102, 103
        external = {101, 102, 103}

        result = get_next_compact_channel_number(conn, external_occupied=external)
        assert result == 104

    def test_compact_skips_both_teamarr_and_external(self, conn):
        """strict_compact skips both Teamarr AUTO channels and externals."""
        from teamarr.database.channel_numbers import get_next_compact_channel_number

        # Create an AUTO group with a channel at 104
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_assignment_mode, "
            "sort_order, enabled) VALUES (1, 'NHL', 'auto', 1, 1)"
        )
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number) "
            "VALUES (1, 1, '104')"
        )
        conn.commit()

        # External at 101, 102, 103
        external = {101, 102, 103}

        result = get_next_compact_channel_number(conn, external_occupied=external)
        # Skips 101-103 (external) and 104 (Teamarr) → 105
        assert result == 105


class TestGlobalReassignWithExternals:
    """Test global reassignment skips external numbers."""

    def test_global_reassign_skips_externals(self, conn):
        """reassign_channels_globally skips external channel numbers."""
        from teamarr.database.channel_numbers import reassign_channels_globally

        # Create an AUTO group with channels
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_assignment_mode, "
            "sort_order, enabled) VALUES (1, 'NHL', 'auto', 1, 1)"
        )
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number, "
            "dispatcharr_channel_id, channel_name, sport, league) "
            "VALUES (1, 1, 101, 1001, 'Game 1', 'hockey', 'nhl')"
        )
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number, "
            "dispatcharr_channel_id, channel_name, sport, league) "
            "VALUES (2, 1, 102, 1002, 'Game 2', 'hockey', 'nhl')"
        )
        conn.commit()

        # External at 101 — channels should be moved to 102, 103
        # (101 is skipped, first channel goes to 102, second to 103)
        external = {101}

        result = reassign_channels_globally(conn, external_occupied=external)

        # Game 1 was at 101 → moved to 102 (skip 101)
        # Game 2 was at 102 → moved to 103 (next available)
        assert result["channels_moved"] == 2

        # Verify DB state (channel_number stored as int by reassign)
        rows = conn.execute(
            "SELECT channel_number FROM managed_channels ORDER BY id"
        ).fetchall()
        assert int(rows[0]["channel_number"]) == 102
        assert int(rows[1]["channel_number"]) == 103

    def test_global_reassign_no_externals(self, conn):
        """Global reassignment without externals keeps channels at same position."""
        from teamarr.database.channel_numbers import reassign_channels_globally

        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_assignment_mode, "
            "sort_order, enabled) VALUES (1, 'NHL', 'auto', 1, 1)"
        )
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number, "
            "dispatcharr_channel_id, channel_name, sport, league) "
            "VALUES (1, 1, 101, 1001, 'Game 1', 'hockey', 'nhl')"
        )
        conn.commit()

        result = reassign_channels_globally(conn, external_occupied=None)

        # Channel ends up at 101 (same numeric position)
        rows = conn.execute(
            "SELECT channel_number FROM managed_channels ORDER BY id"
        ).fetchall()
        assert int(rows[0]["channel_number"]) == 101


class TestAutoBlockWithExternals:
    """Test AUTO block modes with external numbers."""

    def test_strict_block_skips_externals_in_block(self, conn):
        """AUTO strict_block mode skips external numbers within the block."""
        from teamarr.database.channel_numbers import get_next_channel_number

        # AUTO group
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, channel_assignment_mode, "
            "sort_order, total_stream_count, enabled) "
            "VALUES (1, 'NHL', 'auto', 1, 10, 1)"
        )
        # Teamarr already has channel at 101
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number) "
            "VALUES (1, 1, '101')"
        )
        conn.commit()

        # External at 102
        external = {102}

        result = get_next_channel_number(conn, 1, external_occupied=external)
        # Skips 101 (Teamarr) and 102 (external) → 103
        assert result == 103


class TestComputeExternalOccupied:
    """Test the compute_external_occupied standalone function."""

    def test_empty_dispatcharr(self):
        """No Dispatcharr channels → empty external set."""
        from teamarr.consumers.lifecycle import compute_external_occupied

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        db.commit()

        # No channel_manager → no Dispatcharr channels
        result = compute_external_occupied(lambda: db, channel_manager=None)
        assert result == set()
        db.close()

    def test_all_teamarr_managed(self):
        """All Dispatcharr channels are Teamarr-managed → empty external set."""
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import compute_external_occupied
        from teamarr.dispatcharr.types import DispatcharrChannel

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        # Teamarr manages channels 500, 501
        db.execute("INSERT INTO managed_channels (id, channel_number) VALUES (1, '500')")
        db.execute("INSERT INTO managed_channels (id, channel_number) VALUES (2, '501')")
        db.commit()

        # Dispatcharr also shows channels 500, 501
        mock_mgr = MagicMock()
        mock_mgr.get_channels.return_value = [
            DispatcharrChannel(id=1, uuid="a", name="Game 1", channel_number="500"),
            DispatcharrChannel(id=2, uuid="b", name="Game 2", channel_number="501"),
        ]

        result = compute_external_occupied(lambda: db, channel_manager=mock_mgr)
        assert result == set()
        db.close()

    def test_mixed_channels(self):
        """Mix of Teamarr and external channels → only externals returned."""
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import compute_external_occupied
        from teamarr.dispatcharr.types import DispatcharrChannel

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        # Teamarr manages channel 500
        db.execute("INSERT INTO managed_channels (id, channel_number) VALUES (1, '500')")
        db.commit()

        # Dispatcharr has channels 500 (Teamarr), 100 (external), 200 (external)
        mock_mgr = MagicMock()
        mock_mgr.get_channels.return_value = [
            DispatcharrChannel(id=1, uuid="a", name="Game 1", channel_number="500"),
            DispatcharrChannel(id=2, uuid="b", name="ESPN", channel_number="100"),
            DispatcharrChannel(id=3, uuid="c", name="NBC", channel_number="200"),
        ]

        result = compute_external_occupied(lambda: db, channel_manager=mock_mgr)
        assert result == {100, 200}
        db.close()

    def test_deleted_teamarr_channels_excluded(self):
        """Deleted Teamarr channels don't count — their numbers are external."""
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import compute_external_occupied
        from teamarr.dispatcharr.types import DispatcharrChannel

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        # Teamarr has channel 500 but it's deleted
        db.execute(
            "INSERT INTO managed_channels (id, channel_number, deleted_at) "
            "VALUES (1, '500', '2026-01-01')"
        )
        db.commit()

        # Dispatcharr still has channel 500
        mock_mgr = MagicMock()
        mock_mgr.get_channels.return_value = [
            DispatcharrChannel(id=1, uuid="a", name="Orphan", channel_number="500"),
        ]

        result = compute_external_occupied(lambda: db, channel_manager=mock_mgr)
        assert result == {500}
        db.close()

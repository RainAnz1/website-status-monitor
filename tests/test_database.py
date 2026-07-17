import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

import database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp_dir.name, "monitor.db")
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_connections_enable_foreign_keys_and_create_query_indexes(self):
        with database.get_connection() as conn:
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            check_indexes = {
                row[1] for row in conn.execute("PRAGMA index_list('checks')")
            }
            outage_indexes = {
                row[1] for row in conn.execute("PRAGMA index_list('outages')")
            }

        self.assertEqual(foreign_keys, 1)
        self.assertIn("idx_checks_site_checked", check_indexes)
        self.assertIn("idx_outages_site_started", outage_indexes)

    def test_saved_check_uses_timezone_aware_utc_timestamp(self):
        site_id = database.add_site("官网", "https://example.com")
        database.save_check(site_id, "up", 200, 123.4, 90)

        checked_at = database.get_latest_check(site_id)["checked_at"]
        parsed = datetime.fromisoformat(checked_at)

        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_status_snapshot_returns_latest_check_uptime_and_outages(self):
        site_id = database.add_site("官网", "https://example.com")
        database.save_check(site_id, "up", 200, 100.0, 90)
        database.save_check(site_id, "down", 503, 350.0, 89, "服务异常")

        snapshot = database.get_site_statuses(check_limit=30, outage_limit=20)

        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["id"], site_id)
        self.assertEqual(snapshot[0]["status"], "down")
        self.assertEqual(snapshot[0]["status_code"], 503)
        self.assertEqual(snapshot[0]["uptime"], 50.0)
        self.assertEqual(len(snapshot[0]["outages"]), 1)
        self.assertIsNone(snapshot[0]["outages"][0]["ended_at"])

    def test_get_site_returns_none_for_missing_site(self):
        self.assertIsNone(database.get_site(999))

        site_id = database.add_site("官网", "https://example.com")
        site = database.get_site(site_id)

        self.assertEqual(site["name"], "官网")


if __name__ == "__main__":
    unittest.main()

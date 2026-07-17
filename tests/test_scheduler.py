import unittest
from unittest.mock import patch

import scheduler


class SchedulerTests(unittest.TestCase):
    @patch("scheduler.check_all_sites")
    @patch("scheduler.init_db")
    def test_run_check_initializes_database_before_checking(self, init_db, check_all):
        self.assertTrue(scheduler.run_check())

        init_db.assert_called_once_with()
        check_all.assert_called_once_with()

    @patch("scheduler.check_all_sites", side_effect=RuntimeError("boom"))
    @patch("scheduler.init_db")
    def test_run_check_reports_failure(self, init_db, check_all):
        self.assertFalse(scheduler.run_check())


if __name__ == "__main__":
    unittest.main()

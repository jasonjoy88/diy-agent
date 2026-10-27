from datetime import datetime
import unittest

from pan_sync.scheduler import in_window, next_interval_delay, seconds_until_start


class SchedulerTest(unittest.TestCase):
    def test_in_window_boundaries(self):
        self.assertTrue(in_window(datetime(2026, 9, 29, 8, 0), 8, 23))
        self.assertTrue(in_window(datetime(2026, 9, 29, 22, 59), 8, 23))
        self.assertFalse(in_window(datetime(2026, 9, 29, 7, 59), 8, 23))
        self.assertFalse(in_window(datetime(2026, 9, 29, 23, 0), 8, 23))
        self.assertFalse(in_window(datetime(2026, 9, 29, 3, 0), 8, 23))

    def test_seconds_until_start_same_day_morning(self):
        now = datetime(2026, 9, 29, 7, 30)
        self.assertAlmostEqual(seconds_until_start(now, 8), 30 * 60)

    def test_seconds_until_start_after_window_waits_tomorrow(self):
        now = datetime(2026, 9, 29, 23, 30)
        delay = seconds_until_start(now, 8)
        self.assertAlmostEqual(delay, 8.5 * 3600)

    def test_next_interval_delay_within_window(self):
        now = datetime(2026, 9, 29, 10, 0)
        self.assertAlmostEqual(next_interval_delay(now, 30, 8, 23), 30 * 60)

    def test_next_interval_delay_crossing_window_waits_tomorrow(self):
        now = datetime(2026, 9, 29, 22, 40)
        delay = next_interval_delay(now, 30, 8, 23)
        self.assertAlmostEqual(delay, 9 * 3600 + 20 * 60)

    def test_last_round_at_22_30(self):
        now = datetime(2026, 9, 29, 22, 30)
        delay = next_interval_delay(now, 30, 8, 23)
        self.assertAlmostEqual(delay, 9.5 * 3600)


if __name__ == "__main__":
    unittest.main()

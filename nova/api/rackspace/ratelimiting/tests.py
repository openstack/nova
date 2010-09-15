import ratelimiting
import time
import unittest

class Test(unittest.TestCase):

    def setUp(self):
        self.limits = {
                'a': (5, ratelimiting.PER_SECOND),
                'b': (5, ratelimiting.PER_MINUTE),
                'c': (5, ratelimiting.PER_HOUR),
                'd': (1, ratelimiting.PER_SECOND),
                'e': (100, ratelimiting.PER_SECOND)}
        self.rl = ratelimiting.Limiter(self.limits)

    def exhaust(self, action, times_until_exhausted, **kwargs):
        for i in range(times_until_exhausted):
            when = self.rl.perform(action, **kwargs)
            self.assertEqual(when, None)
        num, period = self.limits[action]
        delay = period * 1.0 / num
        # Verify that we are now thoroughly delayed
        for i in range(10):
            when = self.rl.perform(action, **kwargs)
            self.assertAlmostEqual(when, delay, 2)

    def test_second(self):
        self.exhaust('a', 5)
        time.sleep(0.2)
        self.exhaust('a', 1)
        time.sleep(1)
        self.exhaust('a', 5)

    def test_minute(self):
        self.exhaust('b', 5)

    def test_one_per_period(self):
        def allow_once_and_deny_once():
            when = self.rl.perform('d')
            self.assertEqual(when, None)
            when = self.rl.perform('d')
            self.assertAlmostEqual(when, 1, 2)
            return when
        time.sleep(allow_once_and_deny_once())
        time.sleep(allow_once_and_deny_once())
        allow_once_and_deny_once()

    def test_we_can_go_indefinitely_if_we_spread_out_requests(self):
        for i in range(200):
            when = self.rl.perform('e')
            self.assertEqual(when, None)
            time.sleep(0.01)

    def test_users_get_separate_buckets(self):
        self.exhaust('c', 5, username='alice')
        self.exhaust('c', 5, username='bob')
        self.exhaust('c', 5, username='chuck')
        self.exhaust('c', 0, username='chuck')
        self.exhaust('c', 0, username='bob')
        self.exhaust('c', 0, username='alice')

if __name__ == '__main__':
    unittest.main()

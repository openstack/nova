import time
import unittest
import webob

import nova.api.rackspace.ratelimiting as ratelimiting

class LimiterTest(unittest.TestCase):

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


class WSGIAppTest(unittest.TestCase):

    def setUp(self):
        test = self
        class FakeLimiter(object):
            def __init__(self):
                self._action = self._username = self._delay = None
            def mock(self, action, username, delay):
                self._action = action
                self._username = username
                self._delay = delay
            def perform(self, action, username):
                test.assertEqual(action, self._action)
                test.assertEqual(username, self._username)
                return self._delay
        self.limiter = FakeLimiter()
        self.app = ratelimiting.WSGIApp(self.limiter)

    def test_invalid_methods(self):
        requests = []
        for method in ['GET', 'PUT', 'DELETE']:
            req = webob.Request.blank('/limits/michael/breakdance', 
                                      dict(REQUEST_METHOD=method))
            requests.append(req)
        for req in requests:
            self.assertEqual(req.get_response(self.app).status_int, 405)

    def test_invalid_urls(self):
        requests = []
        for prefix in ['limit', '', 'limiter2', 'limiter/limits', 'limiter/1']:
            req = webob.Request.blank('/%s/michael/breakdance' % prefix,
                                      dict(REQUEST_METHOD='POST'))
        requests.append(req)
        for req in requests:
            self.assertEqual(req.get_response(self.app).status_int, 404)

    def verify(self, url, username, action, delay=None):
        """Make sure that POSTing to the given url causes the given username
        to perform the given action.  Make the internal rate limiter return
        delay and make sure that the WSGI app returns the correct response.
        """
        req = webob.Request.blank(url, dict(REQUEST_METHOD='POST'))
        self.limiter.mock(action, username, delay)
        resp = req.get_response(self.app)
        if not delay:
            self.assertEqual(resp.status_int, 200)
        else:
            self.assertEqual(resp.status_int, 403)
            self.assertEqual(resp.headers['X-Wait-Seconds'], delay)

    def test_good_urls(self):
        self.verify('/limiter/michael/hoot', 'michael', 'hoot')

    def test_escaping(self):
        self.verify('/limiter/michael/jump%20up', 'michael', 'jump up')

    def test_response_to_delays(self):
        self.verify('/limiter/michael/hoot', 'michael', 'hoot', 1)
        self.verify('/limiter/michael/hoot', 'michael', 'hoot', 1.56)
        self.verify('/limiter/michael/hoot', 'michael', 'hoot', 1000)


if __name__ == '__main__':
    unittest.main()

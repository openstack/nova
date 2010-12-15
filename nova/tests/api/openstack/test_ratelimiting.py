import httplib
import StringIO
import time
import unittest
import webob

import nova.api.openstack.ratelimiting as ratelimiting


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


class FakeLimiter(object):
    """Fake Limiter class that you can tell how to behave."""

    def __init__(self, test):
        self._action = self._username = self._delay = None
        self.test = test

    def mock(self, action, username, delay):
        self._action = action
        self._username = username
        self._delay = delay

    def perform(self, action, username):
        self.test.assertEqual(action, self._action)
        self.test.assertEqual(username, self._username)
        return self._delay


class WSGIAppTest(unittest.TestCase):

    def setUp(self):
        self.limiter = FakeLimiter(self)
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
            self.assertEqual(resp.headers['X-Wait-Seconds'], "%.2f" % delay)

    def test_good_urls(self):
        self.verify('/limiter/michael/hoot', 'michael', 'hoot')

    def test_escaping(self):
        self.verify('/limiter/michael/jump%20up', 'michael', 'jump up')

    def test_response_to_delays(self):
        self.verify('/limiter/michael/hoot', 'michael', 'hoot', 1)
        self.verify('/limiter/michael/hoot', 'michael', 'hoot', 1.56)
        self.verify('/limiter/michael/hoot', 'michael', 'hoot', 1000)


class FakeHttplibSocket(object):
    """a fake socket implementation for httplib.HTTPResponse, trivial"""

    def __init__(self, response_string):
        self._buffer = StringIO.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer"""
        return self._buffer


class FakeHttplibConnection(object):
    """A fake httplib.HTTPConnection

    Requests made via this connection actually get translated and routed into
    our WSGI app, we then wait for the response and turn it back into
    an httplib.HTTPResponse.
    """
    def __init__(self, app, host, is_secure=False):
        self.app = app
        self.host = host

    def request(self, method, path, data='', headers={}):
        req = webob.Request.blank(path)
        req.method = method
        req.body = data
        req.headers = headers
        req.host = self.host
        # Call the WSGI app, get the HTTP response
        resp = str(req.get_response(self.app))
        # For some reason, the response doesn't have "HTTP/1.0 " prepended; I
        # guess that's a function the web server usually provides.
        resp = "HTTP/1.0 %s" % resp
        sock = FakeHttplibSocket(resp)
        self.http_response = httplib.HTTPResponse(sock)
        self.http_response.begin()

    def getresponse(self):
        return self.http_response


def wire_HTTPConnection_to_WSGI(host, app):
    """Monkeypatches HTTPConnection so that if you try to connect to host, you
    are instead routed straight to the given WSGI app.

    After calling this method, when any code calls

    httplib.HTTPConnection(host)

    the connection object will be a fake.  Its requests will be sent directly
    to the given WSGI app rather than through a socket.

    Code connecting to hosts other than host will not be affected.

    This method may be called multiple times to map different hosts to
    different apps.
    """
    class HTTPConnectionDecorator(object):
        """Wraps the real HTTPConnection class so that when you instantiate
        the class you might instead get a fake instance."""

        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __call__(self, connection_host, *args, **kwargs):
            if connection_host == host:
                return FakeHttplibConnection(app, host)
            else:
                return self.wrapped(connection_host, *args, **kwargs)

    httplib.HTTPConnection = HTTPConnectionDecorator(httplib.HTTPConnection)


class WSGIAppProxyTest(unittest.TestCase):

    def setUp(self):
        """Our WSGIAppProxy is going to call across an HTTPConnection to a
        WSGIApp running a limiter.  The proxy will send input, and the proxy
        should receive that same input, pass it to the limiter who gives a
        result, and send the expected result back.

        The HTTPConnection isn't real -- it's monkeypatched to point straight
        at the WSGIApp.  And the limiter isn't real -- it's a fake that
        behaves the way we tell it to.
        """
        self.limiter = FakeLimiter(self)
        app = ratelimiting.WSGIApp(self.limiter)
        wire_HTTPConnection_to_WSGI('100.100.100.100:80', app)
        self.proxy = ratelimiting.WSGIAppProxy('100.100.100.100:80')

    def test_200(self):
        self.limiter.mock('conquer', 'caesar', None)
        when = self.proxy.perform('conquer', 'caesar')
        self.assertEqual(when, None)

    def test_403(self):
        self.limiter.mock('grumble', 'proletariat', 1.5)
        when = self.proxy.perform('grumble', 'proletariat')
        self.assertEqual(when, 1.5)

    def test_failure(self):
        def shouldRaise():
            self.limiter.mock('murder', 'brutus', None)
            self.proxy.perform('stab', 'brutus')
        self.assertRaises(AssertionError, shouldRaise)


if __name__ == '__main__':
    unittest.main()

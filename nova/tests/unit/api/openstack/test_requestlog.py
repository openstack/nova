# Copyright 2017 IBM Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

import fixtures as fx
import testtools

from nova.tests import fixtures
from nova.tests.unit import conf_fixture

"""Test request logging middleware under various conditions.

The request logging middleware is needed when running under something
other than eventlet. While Nova grew up on eventlet, and it's wsgi
server, it meant that our user facing data (the log stream) was a mix
of what Nova was emitting, and what eventlet.wsgi was emitting on our
behalf. When running under uwsgi we want to make sure that we have
equivalent coverage.

All these tests use GET / to hit an endpoint that doesn't require the
database setup. We have to do a bit of mocking to make that work.
"""


class TestRequestLogMiddleware(testtools.TestCase):

    def setUp(self):
        super(TestRequestLogMiddleware, self).setUp()
        # this is the minimal set of magic mocks needed to convince
        # the API service it can start on it's own without a database.
        mocks = ['nova.objects.Service.get_by_host_and_binary',
                 'nova.objects.Service.create']
        self.stdlog = fixtures.StandardLogging()
        self.useFixture(self.stdlog)
        for m in mocks:
            p = mock.patch(m)
            self.addCleanup(p.stop)
            p.start()

    @mock.patch('nova.api.openstack.requestlog.RequestLog._should_emit')
    def test_logs_requests(self, emit):
        """Ensure requests are logged.

        Make a standard request for / and ensure there is a log entry.
        """

        emit.return_value = True
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.RPCFixture('nova.test'))
        api = self.useFixture(fixtures.OSAPIFixture()).api

        resp = api.api_request('/', strip_version=True)
        log1 = ('INFO [nova.api.openstack.requestlog] 127.0.0.1 '
                '"GET /v2" status: 204 len: 0 microversion: - time:')
        self.assertIn(log1, self.stdlog.logger.output)

        # the content length might vary, but the important part is
        # what we log is what we return to the user (which turns out
        # to excitingly not be the case with eventlet!)
        content_length = resp.headers['content-length']

        log2 = ('INFO [nova.api.openstack.requestlog] 127.0.0.1 '
                '"GET /" status: 200 len: %s' % content_length)
        self.assertIn(log2, self.stdlog.logger.output)

    @mock.patch('nova.api.openstack.requestlog.RequestLog._should_emit')
    def test_logs_mv(self, emit):
        """Ensure logs register microversion if passed.

        This makes sure that microversion logging actually shows up
        when appropriate.
        """

        emit.return_value = True
        self.useFixture(conf_fixture.ConfFixture())
        # NOTE(sdague): all these tests are using the
        self.useFixture(
            fx.MonkeyPatch(
                'nova.api.openstack.compute.versions.'
                'Versions.support_api_request_version',
            True))

        self.useFixture(fixtures.RPCFixture('nova.test'))

        api = self.useFixture(fixtures.OSAPIFixture()).api
        api.microversion = '2.25'

        resp = api.api_request('/', strip_version=True)
        content_length = resp.headers['content-length']

        log1 = ('INFO [nova.api.openstack.requestlog] 127.0.0.1 '
                '"GET /" status: 200 len: %s microversion: 2.25 time:' %
                content_length)
        self.assertIn(log1, self.stdlog.logger.output)

    @mock.patch('nova.api.openstack.compute.versions.Versions.index')
    @mock.patch('nova.api.openstack.requestlog.RequestLog._should_emit')
    def test_logs_under_exception(self, emit, v_index):
        """Ensure that logs still emit under unexpected failure.

        If we get an unexpected failure all the way up to the top, we should
        still have a record of that request via the except block.
        """

        emit.return_value = True
        v_index.side_effect = Exception("Unexpected Error")
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.RPCFixture('nova.test'))
        api = self.useFixture(fixtures.OSAPIFixture()).api

        api.api_request('/', strip_version=True)
        log1 = ('INFO [nova.api.openstack.requestlog] 127.0.0.1 "GET /"'
                ' status: 500 len: 0 microversion: - time:')
        self.assertIn(log1, self.stdlog.logger.output)

    @mock.patch('nova.api.openstack.requestlog.RequestLog._should_emit')
    def test_no_log_under_eventlet(self, emit):
        """Ensure that logs don't end up under eventlet.

        We still set the _should_emit return value directly to prevent
        the situation where eventlet is removed from tests and this
        preventing that.

        NOTE(sdague): this test can be deleted when eventlet is no
        longer supported for the wsgi stack in Nova.
        """

        emit.return_value = False
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.RPCFixture('nova.test'))
        api = self.useFixture(fixtures.OSAPIFixture()).api

        api.api_request('/', strip_version=True)
        self.assertNotIn("nova.api.openstack.requestlog",
                self.stdlog.logger.output)

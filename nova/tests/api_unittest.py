# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import httplib
import random
import StringIO

from nova import vendor
import boto
from boto.ec2 import regioninfo
from tornado import httpserver
from twisted.internet import defer

from nova import flags
from nova import test
from nova.auth import users
from nova.endpoint import api
from nova.endpoint import cloud


FLAGS = flags.FLAGS


# NOTE(termie): These are a bunch of helper methods and classes to short
#               circuit boto calls and feed them into our tornado handlers,
#               it's pretty damn circuitous so apologies if you have to fix
#               a bug in it
def boto_to_tornado(method, path, headers, data, host, connection=None):
    """ translate boto requests into tornado requests

    connection should be a FakeTornadoHttpConnection instance
    """
    headers = httpserver.HTTPHeaders()
    for k, v in headers.iteritems():
        headers[k] = v

    req = httpserver.HTTPRequest(method=method,
                                 uri=path,
                                 headers=headers,
                                 body=data,
                                 host=host,
                                 remote_ip='127.0.0.1',
                                 connection=connection)
    return req


def raw_to_httpresponse(s):
    """ translate a raw tornado http response into an httplib.HTTPResponse """
    sock = FakeHttplibSocket(s)
    resp = httplib.HTTPResponse(sock)
    resp.begin()
    return resp


class FakeHttplibSocket(object):
    """ a fake socket implementation for httplib.HTTPResponse, trivial """
    def __init__(self, s):
        self.fp = StringIO.StringIO(s)

    def makefile(self, mode, other):
        return self.fp


class FakeTornadoStream(object):
    """ a fake stream to satisfy tornado's assumptions, trivial """
    def set_close_callback(self, f):
        pass


class FakeTornadoConnection(object):
    """ a fake connection object for tornado to pass to its handlers

    web requests are expected to write to this as they get data and call
    finish when they are done with the request, we buffer the writes and
    kick off a callback when it is done so that we can feed the result back
    into boto.
    """
    def __init__(self, d):
        self.d = d
        self._buffer = StringIO.StringIO()

    def write(self, chunk):
        self._buffer.write(chunk)

    def finish(self):
        s = self._buffer.getvalue()
        self.d.callback(s)

    xheaders = None

    @property
    def stream(self):
        return FakeTornadoStream()


class FakeHttplibConnection(object):
    """ a fake httplib.HTTPConnection for boto to use

    requests made via this connection actually get translated and routed into
    our tornado app, we then wait for the response and turn it back into
    the httplib.HTTPResponse that boto expects.
    """
    def __init__(self, app, host, is_secure=False):
        self.app = app
        self.host = host
        self.deferred = defer.Deferred()

    def request(self, method, path, data, headers):
        req = boto_to_tornado
        conn = FakeTornadoConnection(self.deferred)
        request = boto_to_tornado(connection=conn,
                                  method=method,
                                  path=path,
                                  headers=headers,
                                  data=data,
                                  host=self.host)
        handler = self.app(request)
        self.deferred.addCallback(raw_to_httpresponse)

    def getresponse(self):
        @defer.inlineCallbacks
        def _waiter():
            result = yield self.deferred
            defer.returnValue(result)
        d = _waiter()
        # NOTE(termie): defer.returnValue above should ensure that
        #               this deferred has already been called by the time
        #               we get here, we are going to cheat and return
        #               the result of the callback
        return d.result

    def close(self):
        pass


class ApiEc2TestCase(test.BaseTestCase):
    def setUp(self):
        super(ApiEc2TestCase, self).setUp()

        self.users = users.UserManager.instance()
        self.cloud = cloud.CloudController()

        self.host = '127.0.0.1'

        self.app = api.APIServerApplication(self.users, {'Cloud': self.cloud})
        self.ec2 = boto.connect_ec2(
                aws_access_key_id='fake',
                aws_secret_access_key='fake',
                is_secure=False,
                region=regioninfo.RegionInfo(None, 'test', self.host),
                port=FLAGS.cc_port,
                path='/services/Cloud')

        self.mox.StubOutWithMock(self.ec2, 'new_http_connection')

    def expect_http(self, host=None, is_secure=False):
        http = FakeHttplibConnection(
                self.app, '%s:%d' % (self.host, FLAGS.cc_port), False)
        self.ec2.new_http_connection(host, is_secure).AndReturn(http)
        return http

    def test_describe_instances(self):
        self.expect_http()
        self.mox.ReplayAll()
        try:
            self.users.create_user('fake', 'fake', 'fake')
        except Exception, _err:
            pass # User may already exist
        self.assertEqual(self.ec2.get_all_instances(), [])
        self.users.delete_user('fake')


    def test_get_all_key_pairs(self):
        self.expect_http()
        self.mox.ReplayAll()
        keyname = "".join(random.choice("sdiuisudfsdcnpaqwertasd") for x in range(random.randint(4, 8)))
        try:
            self.users.create_user('fake', 'fake', 'fake')
        except Exception, _err:
            pass # User may already exist
        self.users.generate_key_pair('fake', keyname)

        rv = self.ec2.get_all_key_pairs()
        self.assertTrue(filter(lambda k: k.name == keyname, rv))
        self.users.delete_user('fake')


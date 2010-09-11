# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Unit tests for the API endpoint"""

import boto
from boto.ec2 import regioninfo
import httplib
import random
import StringIO
from tornado import httpserver
from twisted.internet import defer

from nova import flags
from nova import test
from nova.auth import manager
from nova.endpoint import api
from nova.endpoint import cloud


FLAGS = flags.FLAGS


# NOTE(termie): These are a bunch of helper methods and classes to short
#               circuit boto calls and feed them into our tornado handlers,
#               it's pretty damn circuitous so apologies if you have to fix
#               a bug in it
# NOTE(jaypipes) The pylint disables here are for R0913 (too many args) which
#                isn't controllable since boto's HTTPRequest needs that many 
#                args, and for the version-differentiated import of tornado's 
#                httputil.
# NOTE(jaypipes): The disable-msg=E1101 and E1103 below is because pylint is
#                 unable to introspect the deferred's return value properly

def boto_to_tornado(method, path, headers, data, # pylint: disable-msg=R0913
                    host, connection=None):
    """ translate boto requests into tornado requests

    connection should be a FakeTornadoHttpConnection instance
    """
    try:
        headers = httpserver.HTTPHeaders()
    except AttributeError:
        from tornado import httputil # pylint: disable-msg=E0611
        headers = httputil.HTTPHeaders()
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


def raw_to_httpresponse(response_string):
    """translate a raw tornado http response into an httplib.HTTPResponse"""
    sock = FakeHttplibSocket(response_string)
    resp = httplib.HTTPResponse(sock)
    resp.begin()
    return resp


class FakeHttplibSocket(object):
    """a fake socket implementation for httplib.HTTPResponse, trivial"""
    def __init__(self, response_string):
        self._buffer = StringIO.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer"""
        return self._buffer


class FakeTornadoStream(object):
    """a fake stream to satisfy tornado's assumptions, trivial"""
    def set_close_callback(self, _func):
        """Dummy callback for stream"""
        pass


class FakeTornadoConnection(object):
    """A fake connection object for tornado to pass to its handlers

    web requests are expected to write to this as they get data and call
    finish when they are done with the request, we buffer the writes and
    kick off a callback when it is done so that we can feed the result back
    into boto.
    """
    def __init__(self, deferred):
        self._deferred = deferred
        self._buffer = StringIO.StringIO()

    def write(self, chunk):
        """Writes a chunk of data to the internal buffer"""
        self._buffer.write(chunk)

    def finish(self):
        """Finalizes the connection and returns the buffered data via the
        deferred callback.
        """
        data = self._buffer.getvalue()
        self._deferred.callback(data)

    xheaders = None

    @property
    def stream(self): # pylint: disable-msg=R0201
        """Required property for interfacing with tornado"""
        return FakeTornadoStream()


class FakeHttplibConnection(object):
    """A fake httplib.HTTPConnection for boto to use

    requests made via this connection actually get translated and routed into
    our tornado app, we then wait for the response and turn it back into
    the httplib.HTTPResponse that boto expects.
    """
    def __init__(self, app, host, is_secure=False):
        self.app = app
        self.host = host
        self.deferred = defer.Deferred()

    def request(self, method, path, data, headers):
        """Creates a connection to a fake tornado and sets
        up a deferred request with the supplied data and
        headers"""
        conn = FakeTornadoConnection(self.deferred)
        request = boto_to_tornado(connection=conn,
                                  method=method,
                                  path=path,
                                  headers=headers,
                                  data=data,
                                  host=self.host)
        self.app(request)
        self.deferred.addCallback(raw_to_httpresponse)

    def getresponse(self):
        """A bit of deferred magic for catching the response
        from the previously deferred request"""
        @defer.inlineCallbacks
        def _waiter():
            """Callback that simply yields the deferred's
            return value."""
            result = yield self.deferred
            defer.returnValue(result)
        d = _waiter()
        # NOTE(termie): defer.returnValue above should ensure that
        #               this deferred has already been called by the time
        #               we get here, we are going to cheat and return
        #               the result of the callback
        return d.result # pylint: disable-msg=E1101

    def close(self):
        """Required for compatibility with boto/tornado"""
        pass


class ApiEc2TestCase(test.BaseTestCase):
    """Unit test for the cloud controller on an EC2 API"""
    def setUp(self): # pylint: disable-msg=C0103,C0111
        super(ApiEc2TestCase, self).setUp()

        self.manager = manager.AuthManager()
        self.cloud = cloud.CloudController()

        self.host = '127.0.0.1'

        self.app = api.APIServerApplication({'Cloud': self.cloud})
        self.ec2 = boto.connect_ec2(
                aws_access_key_id='fake',
                aws_secret_access_key='fake',
                is_secure=False,
                region=regioninfo.RegionInfo(None, 'test', self.host),
                port=FLAGS.cc_port,
                path='/services/Cloud')

        self.mox.StubOutWithMock(self.ec2, 'new_http_connection')

    def expect_http(self, host=None, is_secure=False):
        """Returns a new EC2 connection"""
        http = FakeHttplibConnection(
                self.app, '%s:%d' % (self.host, FLAGS.cc_port), False)
        # pylint: disable-msg=E1103
        self.ec2.new_http_connection(host, is_secure).AndReturn(http)
        return http

    def test_describe_instances(self):
        """Test that, after creating a user and a project, the describe
        instances call to the API works properly"""
        self.expect_http()
        self.mox.ReplayAll()
        user = self.manager.create_user('fake', 'fake', 'fake')
        project = self.manager.create_project('fake', 'fake', 'fake')
        self.assertEqual(self.ec2.get_all_instances(), [])
        self.manager.delete_project(project)
        self.manager.delete_user(user)


    def test_get_all_key_pairs(self):
        """Test that, after creating a user and project and generating
         a key pair, that the API call to list key pairs works properly"""
        self.expect_http()
        self.mox.ReplayAll()
        keyname = "".join(random.choice("sdiuisudfsdcnpaqwertasd") \
                          for x in range(random.randint(4, 8)))
        user = self.manager.create_user('fake', 'fake', 'fake')
        project = self.manager.create_project('fake', 'fake', 'fake')
        self.manager.generate_key_pair(user.id, keyname)

        rv = self.ec2.get_all_key_pairs()
        results = [k for k in rv if k.name == keyname]
        self.assertEquals(len(results), 1)
        self.manager.delete_project(project)
        self.manager.delete_user(user)

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
import webob

from nova import test
from nova import api
from nova.api.ec2 import cloud
from nova.auth import manager


class FakeHttplibSocket(object):
    """a fake socket implementation for httplib.HTTPResponse, trivial"""
    def __init__(self, response_string):
        self._buffer = StringIO.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer"""
        return self._buffer


class FakeHttplibConnection(object):
    """A fake httplib.HTTPConnection for boto to use

    requests made via this connection actually get translated and routed into
    our WSGI app, we then wait for the response and turn it back into
    the httplib.HTTPResponse that boto expects.
    """
    def __init__(self, app, host, is_secure=False):
        self.app = app
        self.host = host

    def request(self, method, path, data, headers):
        req = webob.Request.blank(path)
        req.method = method
        req.body = data
        req.headers = headers
        req.headers['Accept'] = 'text/html'
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

    def close(self):
        """Required for compatibility with boto/tornado"""
        pass


class ApiEc2TestCase(test.BaseTestCase):
    """Unit test for the cloud controller on an EC2 API"""
    def setUp(self): # pylint: disable-msg=C0103,C0111
        super(ApiEc2TestCase, self).setUp()

        self.manager = manager.AuthManager()

        self.host = '127.0.0.1'

        self.app = api.API()
        self.ec2 = boto.connect_ec2(
                aws_access_key_id='fake',
                aws_secret_access_key='fake',
                is_secure=False,
                region=regioninfo.RegionInfo(None, 'test', self.host),
                port=8773,
                path='/services/Cloud')

        self.mox.StubOutWithMock(self.ec2, 'new_http_connection')

    def expect_http(self, host=None, is_secure=False):
        """Returns a new EC2 connection"""
        http = FakeHttplibConnection(
                self.app, '%s:8773' % (self.host), False)
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
        # NOTE(vish): create depends on pool, so call helper directly
        cloud._gen_key(None, user.id, keyname)

        rv = self.ec2.get_all_key_pairs()
        results = [k for k in rv if k.name == keyname]
        self.assertEquals(len(results), 1)
        self.manager.delete_project(project)
        self.manager.delete_user(user)

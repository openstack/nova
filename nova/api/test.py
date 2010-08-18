# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

"""
Test for the root WSGI middleware for all API controllers.
"""

import unittest

import stubout

from nova import api
from nova import wsgi_test


class Test(unittest.TestCase):

    def setUp(self): # pylint: disable-msg=C0103
        self.called = False
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self): # pylint: disable-msg=C0103
        self.stubs.UnsetAll()

    def test_rackspace(self):
        self.stubs.Set(api.rackspace, 'API', get_api_stub(self))
        api.API()(wsgi_test.get_environ({'PATH_INFO': '/v1.0/cloud'}),
                  wsgi_test.start_response)
        self.assertTrue(self.called)

    def test_ec2(self):
        self.stubs.Set(api.ec2, 'API', get_api_stub(self))
        api.API()(wsgi_test.get_environ({'PATH_INFO': '/ec2/cloud'}),
                  wsgi_test.start_response)
        self.assertTrue(self.called)

    def test_not_found(self):
        self.stubs.Set(api.ec2, 'API', get_api_stub(self))
        self.stubs.Set(api.rackspace, 'API', get_api_stub(self))
        api.API()(wsgi_test.get_environ({'PATH_INFO': '/'}),
                  wsgi_test.start_response)
        self.assertFalse(self.called)


def get_api_stub(test_object):
    """Get a stub class that verifies next part of the request."""

    class APIStub(object):
        """Class to verify request and mark it was called."""
        test = test_object

        def __call__(self, environ, start_response):
            self.test.assertEqual(environ['PATH_INFO'], '/cloud')
            self.test.called = True

    return APIStub

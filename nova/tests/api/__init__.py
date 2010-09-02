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
import webob
import webob.dec

from nova import api
from nova.tests.api.test_helper import *

class Test(unittest.TestCase):

    def setUp(self): # pylint: disable-msg=C0103
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self): # pylint: disable-msg=C0103
        self.stubs.UnsetAll()

    def test_rackspace(self):
        self.stubs.Set(api.rackspace, 'API', APIStub)
        result = webob.Request.blank('/v1.0/cloud').get_response(api.API())
        self.assertEqual(result.body, "/cloud")

    def test_ec2(self):
        self.stubs.Set(api.ec2, 'API', APIStub)
        result = webob.Request.blank('/ec2/cloud').get_response(api.API())
        self.assertEqual(result.body, "/cloud")

    def test_not_found(self):
        self.stubs.Set(api.ec2, 'API', APIStub)
        self.stubs.Set(api.rackspace, 'API', APIStub)
        result = webob.Request.blank('/test/cloud').get_response(api.API())
        self.assertNotEqual(result.body, "/cloud")

    def test_query_api_version(self):
        pass

if __name__ == '__main__':
    unittest.main()

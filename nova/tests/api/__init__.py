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

import nova.exception
from nova import api
from nova.tests.api.fakes import APIStub


class Test(unittest.TestCase):

    def setUp(self): # pylint: disable-msg=C0103
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self): # pylint: disable-msg=C0103
        self.stubs.UnsetAll()

    def _request(self, url, subdomain, **kwargs):
        environ_keys = {'HTTP_HOST': '%s.example.com' % subdomain}
        environ_keys.update(kwargs)
        req = webob.Request.blank(url, environ_keys)
        return req.get_response(api.API())

    def test_openstack(self):
        self.stubs.Set(api.openstack, 'API', APIStub)
        result = self._request('/v1.0/cloud', 'rs')
        self.assertEqual(result.body, "/cloud")

    def test_ec2(self):
        self.stubs.Set(api.ec2, 'API', APIStub)
        result = self._request('/services/cloud', 'ec2')
        self.assertEqual(result.body, "/cloud")

    def test_not_found(self):
        self.stubs.Set(api.ec2, 'API', APIStub)
        self.stubs.Set(api.openstack, 'API', APIStub)
        result = self._request('/test/cloud', 'ec2')
        self.assertNotEqual(result.body, "/cloud")

    def test_query_api_versions(self):
        result = self._request('/', 'rs')
        self.assertTrue('CURRENT' in result.body)

    def test_metadata(self):
        def go(url):
            result = self._request(url, 'ec2', 
                                   REMOTE_ADDR='128.192.151.2')
        # Each should get to the ORM layer and fail to find the IP
        self.assertRaises(nova.exception.NotFound, go, '/latest/')
        self.assertRaises(nova.exception.NotFound, go, '/2009-04-04/')
        self.assertRaises(nova.exception.NotFound, go, '/1.0/')

    def test_ec2_root(self):
        result = self._request('/', 'ec2')
        self.assertTrue('2007-12-15\n' in result.body)



if __name__ == '__main__':
    unittest.main()

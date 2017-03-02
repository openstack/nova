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

from keystoneauth1 import exceptions as kse
import webob

from nova.api.openstack import identity
from nova import test


class FakeResponse(object):
    """A basic response constainer that simulates requests.Response.

    One of the critical things is that a success error code makes the
    object return true.

    """
    def __init__(self, status_code, content=""):
        self.status_code = status_code
        self.content = content

    def __bool__(self):
        # python 3
        return self.__nonzero__()

    def __nonzero__(self):
        # python 2
        return self.status_code < 400

    @property
    def text(self):
        return self.content


class IdentityValidationTest(test.NoDBTestCase):

    @mock.patch('keystoneauth1.session.Session.get')
    def test_good_id(self, get):
        get.return_value = FakeResponse(200)
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        get.assert_called_once_with(
            '/v3/projects/foo',
            endpoint_filter={'service_type': 'identity'},
            raise_exc=False)

    @mock.patch('keystoneauth1.session.Session.get')
    def test_no_project(self, get):
        get.return_value = FakeResponse(404)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          identity.verify_project_id,
                          mock.MagicMock(), "foo")
        get.assert_called_once_with(
            '/v3/projects/foo',
            endpoint_filter={'service_type': 'identity'},
            raise_exc=False)

    @mock.patch('keystoneauth1.session.Session.get')
    def test_unknown_id(self, get):
        get.return_value = FakeResponse(403)
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        get.assert_called_once_with(
            '/v3/projects/foo',
            endpoint_filter={'service_type': 'identity'},
            raise_exc=False)

    @mock.patch('keystoneauth1.session.Session.get')
    def test_unknown_error(self, get):
        get.return_value = FakeResponse(500, "Oh noes!")
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        get.assert_called_once_with(
            '/v3/projects/foo',
            endpoint_filter={'service_type': 'identity'},
            raise_exc=False)

    @mock.patch('keystoneauth1.session.Session.get')
    def test_early_fail(self, get):
        get.side_effect = kse.EndpointNotFound()
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))

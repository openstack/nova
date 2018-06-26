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

from keystoneauth1.adapter import Adapter
from keystoneauth1 import exceptions as kse
import webob

from nova.api.openstack import identity
from nova import test
from nova.tests.unit import fake_requests


class IdentityValidationTest(test.NoDBTestCase):
    """Unit tests for our validation of keystone projects.

    There are times when Nova stores keystone project_id and user_id
    in our database as strings. Until the Pike release none of this
    data was validated, so it was very easy for adminstrators to think
    they were adjusting quota for a project (by name) when instead
    they were just inserting keys in a database that would not get used.

    This is only tested in unit tests through mocking out keystoneauth
    responses because a functional test would need a real keystone or
    keystone simulator.

    The functional code works by using the existing keystone
    credentials and trying to make a /v3/projects/{id} get call. It
    will return a 403 if the user doesn't have enough permissions to
    ask about other projects, a 404 if it does and that project does
    not exist.

    """
    def setUp(self):
        super(IdentityValidationTest, self).setUp()
        get_adap_p = mock.patch('nova.utils.get_ksa_adapter')
        self.addCleanup(get_adap_p.stop)
        self.mock_get_adap = get_adap_p.start()
        self.mock_adap = mock.create_autospec(Adapter)
        self.mock_get_adap.return_value = self.mock_adap

    def validate_common(self):
        self.mock_get_adap.assert_called_once_with(
            'identity', ksa_auth=mock.ANY,
            min_version=(3, 0), max_version=(3, 'latest'))
        self.mock_adap.get.assert_called_once_with('/projects/foo')

    def test_good_id(self):
        """Test response 200.

        This indicates we have permissions, and we have definitively
        found the project exists.

        """
        self.mock_adap.get.return_value = fake_requests.FakeResponse(200)
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        self.validate_common()

    def test_no_project(self):
        """Test response 404.

        This indicates that we have permissions, and we have
        definitively found the project does not exist.

        """
        self.mock_adap.get.return_value = fake_requests.FakeResponse(404)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          identity.verify_project_id,
                          mock.MagicMock(), "foo")
        self.validate_common()

    def test_unknown_id(self):
        """Test response 403.

        This indicates we don't have permissions. We fail open here
        and assume the project exists.

        """
        self.mock_adap.get.return_value = fake_requests.FakeResponse(403)
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        self.validate_common()

    def test_unknown_error(self):
        """Test some other return from keystone.

        If we got anything else, something is wrong on the keystone
        side. We don't want to fail on our side.

        """
        self.mock_adap.get.return_value = fake_requests.FakeResponse(
            500, content="Oh noes!")
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        self.validate_common()

    def test_early_fail(self):
        """Test if we get a keystoneauth exception.

        If we get a random keystoneauth exception, fall back and
        assume the project exists.

        """
        self.mock_adap.get.side_effect = kse.ConnectionError()
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        self.validate_common()

    def test_wrong_version(self):
        """Test endpoint not found.

        EndpointNotFound will be made when the keystone v3 API is not
        found in the service catalog, or if the v2.0 endpoint was
        registered as the root endpoint. We treat this the same as 404.

        """
        self.mock_adap.get.side_effect = kse.EndpointNotFound()
        self.assertRaises(webob.exc.HTTPBadRequest,
                          identity.verify_project_id,
                          mock.MagicMock(), "foo")
        self.validate_common()

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
from keystoneauth1 import loading as ks_loading
from keystoneauth1.session import Session
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

    @mock.patch.object(ks_loading, 'load_session_from_conf_options')
    def test_good_id(self, mock_load):
        """Test response 200.

        This indicates we have permissions, and we have definitively
        found the project exists.

        """
        session = mock.create_autospec(Session)
        session.get.return_value = FakeResponse(200)
        mock_load.return_value = session
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        session.get.assert_called_once_with(
            '/projects/foo',
            endpoint_filter={'service_type': 'identity', 'version': (3, 0)},
            raise_exc=False)

    @mock.patch.object(ks_loading, 'load_session_from_conf_options')
    def test_no_project(self, mock_load):
        """Test response 404.

        This indicates that we have permissions, and we have
        definitively found the project does not exist.

        """
        session = mock.create_autospec(Session)
        session.get.return_value = FakeResponse(404)
        mock_load.return_value = session
        self.assertRaises(webob.exc.HTTPBadRequest,
                          identity.verify_project_id,
                          mock.MagicMock(), "foo")
        session.get.assert_called_once_with(
            '/projects/foo',
            endpoint_filter={'service_type': 'identity', 'version': (3, 0)},
            raise_exc=False)

    @mock.patch.object(ks_loading, 'load_session_from_conf_options')
    def test_unknown_id(self, mock_load):
        """Test response 403.

        This indicates we don't have permissions. We fail open here
        and assume the project exists.

        """
        session = mock.create_autospec(Session)
        session.get.return_value = FakeResponse(403)
        mock_load.return_value = session
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        session.get.assert_called_once_with(
            '/projects/foo',
            endpoint_filter={'service_type': 'identity', 'version': (3, 0)},
            raise_exc=False)

    @mock.patch.object(ks_loading, 'load_session_from_conf_options')
    def test_unknown_error(self, mock_load):
        """Test some other return from keystone.

        If we got anything else, something is wrong on the keystone
        side. We don't want to fail on our side.

        """
        session = mock.create_autospec(Session)
        session.get.return_value = FakeResponse(500, "Oh noes!")
        mock_load.return_value = session
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))
        session.get.assert_called_once_with(
            '/projects/foo',
            endpoint_filter={'service_type': 'identity', 'version': (3, 0)},
            raise_exc=False)

    @mock.patch.object(ks_loading, 'load_session_from_conf_options')
    def test_early_fail(self, mock_load):
        """Test if we get a keystoneauth exception.

        If we get a random keystoneauth exception, fall back and
        assume the project exists.

        """
        session = mock.create_autospec(Session)
        session.get.side_effect = kse.ConnectionError()
        mock_load.return_value = session
        self.assertTrue(identity.verify_project_id(mock.MagicMock(), "foo"))

    @mock.patch.object(ks_loading, 'load_session_from_conf_options')
    def test_wrong_version(self, mock_load):
        """Test endpoint not found.

        EndpointNotFound will be made when the keystone v3 API is not
        found in the service catalog, or if the v2.0 endpoint was
        registered as the root endpoint. We treat this the same as 404.

        """
        session = mock.create_autospec(Session)
        session.get.side_effect = kse.EndpointNotFound()
        mock_load.return_value = session
        self.assertRaises(webob.exc.HTTPBadRequest,
                          identity.verify_project_id,
                          mock.MagicMock(), "foo")

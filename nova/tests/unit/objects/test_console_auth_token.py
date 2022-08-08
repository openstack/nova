#    Copyright 2016 Intel Corp.
#    Copyright 2016 Hewlett Packard Enterprise Development Company LP
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

import copy
import mock
import urllib.parse as urlparse

from oslo_db.exception import DBDuplicateEntry
from oslo_utils.fixture import uuidsentinel
from oslo_utils import timeutils

from nova import exception
from nova.objects import console_auth_token as token_obj
from nova.tests.unit import fake_console_auth_token as fakes
from nova.tests.unit.objects import test_objects


class _TestConsoleAuthToken(object):

    @mock.patch('nova.db.main.api.console_auth_token_create')
    def _test_authorize(self, console_type, mock_create, base_url=None):
        # the expires time is calculated from the current time and
        # a ttl value in the object. Fix the current time so we can
        # test expires is calculated correctly as expected
        self.addCleanup(timeutils.clear_time_override)
        timeutils.set_time_override()
        ttl = 10
        expires = timeutils.utcnow_ts() + ttl
        if not base_url:
            base_url = fakes.fake_token_dict['access_url_base']

        db_dict = copy.deepcopy(fakes.fake_token_dict)
        db_dict['expires'] = expires
        db_dict['console_type'] = console_type
        db_dict['access_url_base'] = base_url
        mock_create.return_value = db_dict

        create_dict = copy.deepcopy(fakes.fake_token_dict)
        create_dict['access_url_base'] = base_url
        create_dict['expires'] = expires
        create_dict['console_type'] = console_type
        del create_dict['id']
        del create_dict['created_at']
        del create_dict['updated_at']

        expected = copy.deepcopy(fakes.fake_token_dict)
        del expected['token_hash']
        del expected['expires']
        expected['access_url_base'] = base_url
        expected['token'] = fakes.fake_token
        expected['console_type'] = console_type

        obj = token_obj.ConsoleAuthToken(
            context=self.context,
            console_type=console_type,
            host=fakes.fake_token_dict['host'],
            port=fakes.fake_token_dict['port'],
            internal_access_path=fakes.fake_token_dict['internal_access_path'],
            instance_uuid=fakes.fake_token_dict['instance_uuid'],
            access_url_base=base_url,
        )
        with mock.patch('uuid.uuid4', return_value=fakes.fake_token):
            token = obj.authorize(ttl)

        mock_create.assert_called_once_with(self.context, create_dict)
        self.assertEqual(token, fakes.fake_token)
        self.compare_obj(obj, expected)

        url = obj.access_url
        if console_type != 'novnc':
            expected_url = '%s?token=%s' % (base_url, fakes.fake_token)
        else:
            if 'path=' in base_url:
                expected_url = base_url + urlparse.quote('?token=%s' % token)
            else:
                path = urlparse.urlencode({'path': '?token=%s' %
                                                   fakes.fake_token})
                expected_url = '%s?%s' % (base_url, path)
        self.assertEqual(expected_url, url)

    def test_authorize(self):
        self._test_authorize(fakes.fake_token_dict['console_type'])

    def test_authorize_novnc(self):
        self._test_authorize('novnc')

    def test_authorize_novnc_with_path_in_base_url(self):
        url = fakes.fake_token_dict['access_url_base'] + '?path=fake-path'
        self._test_authorize('novnc', base_url=url)

    @mock.patch('nova.db.main.api.console_auth_token_create')
    def test_authorize_duplicate_token(self, mock_create):
        mock_create.side_effect = DBDuplicateEntry()

        obj = token_obj.ConsoleAuthToken(
            context=self.context,
            console_type=fakes.fake_token_dict['console_type'],
            host=fakes.fake_token_dict['host'],
            port=fakes.fake_token_dict['port'],
            internal_access_path=fakes.fake_token_dict['internal_access_path'],
            instance_uuid=fakes.fake_token_dict['instance_uuid'],
            access_url_base=fakes.fake_token_dict['access_url_base'],
        )

        self.assertRaises(exception.TokenInUse,
                          obj.authorize,
                          100)

    @mock.patch('nova.db.main.api.console_auth_token_create')
    def test_authorize_instance_not_found(self, mock_create):
        mock_create.side_effect = exception.InstanceNotFound(
            instance_id=fakes.fake_token_dict['instance_uuid'])

        obj = token_obj.ConsoleAuthToken(
            context=self.context,
            console_type=fakes.fake_token_dict['console_type'],
            host=fakes.fake_token_dict['host'],
            port=fakes.fake_token_dict['port'],
            internal_access_path=fakes.fake_token_dict['internal_access_path'],
            instance_uuid=fakes.fake_token_dict['instance_uuid'],
            access_url_base=fakes.fake_token_dict['access_url_base'],
        )

        self.assertRaises(exception.InstanceNotFound,
                          obj.authorize,
                          100)

    @mock.patch('nova.db.main.api.console_auth_token_create')
    def test_authorize_object_already_created(self, mock_create):
        # the expires time is calculated from the current time and
        # a ttl value in the object. Fix the current time so we can
        # test expires is calculated correctly as expected
        self.addCleanup(timeutils.clear_time_override)
        timeutils.set_time_override()
        ttl = 10
        expires = timeutils.utcnow_ts() + ttl

        db_dict = copy.deepcopy(fakes.fake_token_dict)
        db_dict['expires'] = expires
        mock_create.return_value = db_dict

        obj = token_obj.ConsoleAuthToken(
            context=self.context,
            console_type=fakes.fake_token_dict['console_type'],
            host=fakes.fake_token_dict['host'],
            port=fakes.fake_token_dict['port'],
            internal_access_path=fakes.fake_token_dict['internal_access_path'],
            instance_uuid=fakes.fake_token_dict['instance_uuid'],
            access_url_base=fakes.fake_token_dict['access_url_base'],
        )
        obj.authorize(100)
        self.assertRaises(exception.ObjectActionError,
                          obj.authorize,
                          100)

    @mock.patch('nova.db.main.api.console_auth_token_destroy_all_by_instance')
    def test_clean_console_auths_for_instance(self, mock_destroy):
        token_obj.ConsoleAuthToken.clean_console_auths_for_instance(
            self.context, uuidsentinel.instance)
        mock_destroy.assert_called_once_with(
            self.context, uuidsentinel.instance)

    @mock.patch('nova.db.main.api.console_auth_token_destroy_expired')
    def test_clean_expired_console_auths(self, mock_destroy):
        token_obj.ConsoleAuthToken.clean_expired_console_auths(self.context)
        mock_destroy.assert_called_once_with(self.context)

    @mock.patch('nova.db.main.api.console_auth_token_destroy_expired_by_host')
    def test_clean_expired_console_auths_for_host(self, mock_destroy):
        token_obj.ConsoleAuthToken.clean_expired_console_auths_for_host(
            self.context, 'fake-host')
        mock_destroy.assert_called_once_with(
            self.context, 'fake-host')


class TestConsoleAuthToken(test_objects._LocalTest,
                           _TestConsoleAuthToken):
    pass


class TestRemoteConsoleAuthToken(test_objects._RemoteTest,
                                 _TestConsoleAuthToken):
    pass

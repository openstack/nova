#    Copyright 2013 IBM Corp.
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

from unittest import mock

from oslo_utils import timeutils

from nova import exception
from nova.objects import keypair
from nova.tests.unit.objects import test_objects

NOW = timeutils.utcnow().replace(microsecond=0)
fake_keypair = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'name': 'foo-keypair',
    'type': 'ssh',
    'user_id': 'fake-user',
    'fingerprint': 'fake-fingerprint',
    'public_key': 'fake\npublic\nkey',
}


class _TestKeyPairObject(object):

    @mock.patch('nova.objects.KeyPair._create_in_db')
    def test_create(self, mock_kp_create):
        mock_kp_create.return_value = fake_keypair

        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.name = 'foo-keypair'
        keypair_obj.public_key = 'keydata'
        keypair_obj.user_id = 'fake-user'
        keypair_obj.create()
        self.compare_obj(keypair_obj, fake_keypair)

        mock_kp_create.assert_called_once_with(self.context,
            {'name': 'foo-keypair', 'public_key': 'keydata',
             'user_id': 'fake-user'})

    @mock.patch('nova.objects.KeyPair._create_in_db')
    def test_recreate_fails(self, mock_kp_create):
        mock_kp_create.return_value = fake_keypair

        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.name = 'foo-keypair'
        keypair_obj.public_key = 'keydata'
        keypair_obj.user_id = 'fake-user'
        keypair_obj.create()
        self.assertRaises(exception.ObjectActionError, keypair_obj.create)

        mock_kp_create.assert_called_once_with(self.context,
            {'name': 'foo-keypair', 'public_key': 'keydata',
             'user_id': 'fake-user'})

    @mock.patch('nova.objects.KeyPair._destroy_in_db')
    def test_destroy(self, mock_kp_destroy):
        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.id = 123
        keypair_obj.user_id = 'fake-user'
        keypair_obj.name = 'foo-keypair'
        keypair_obj.destroy()

        mock_kp_destroy.assert_called_once_with(
            self.context, 'fake-user', 'foo-keypair')

    @mock.patch('nova.objects.KeyPair._destroy_in_db')
    def test_destroy_by_name(self, mock_kp_destroy):
        keypair.KeyPair.destroy_by_name(self.context, 'fake-user',
                                        'foo-keypair')

        mock_kp_destroy.assert_called_once_with(
            self.context, 'fake-user', 'foo-keypair')

    @mock.patch('nova.objects.KeyPairList._get_from_db')
    @mock.patch('nova.objects.KeyPairList._get_count_from_db')
    def test_get_by_user(self, mock_api_count, mock_api_get):
        mock_api_get.return_value = [fake_keypair]
        mock_api_count.return_value = 1

        keypairs = keypair.KeyPairList.get_by_user(self.context, 'fake-user')
        self.assertEqual(1, len(keypairs))
        self.compare_obj(keypairs[0], fake_keypair)

        keypair_count = keypair.KeyPairList.get_count_by_user(
            self.context, 'fake-user')
        self.assertEqual(1, keypair_count)

        mock_api_get.assert_called_once_with(self.context, 'fake-user',
                                             limit=None, marker=None)
        mock_api_count.assert_called_once_with(self.context, 'fake-user')

    def test_obj_make_compatible(self):
        keypair_obj = keypair.KeyPair(context=self.context)
        fake_keypair_copy = dict(fake_keypair)

        keypair_obj.obj_make_compatible(fake_keypair_copy, '1.1')
        self.assertNotIn('type', fake_keypair_copy)

    @mock.patch('nova.objects.KeyPairList._get_from_db')
    def test_get_by_user_limit(self, mock_api_get):
        mock_api_get.return_value = [fake_keypair]

        keypairs = keypair.KeyPairList.get_by_user(
            self.context, 'fake-user', limit=1)
        self.assertEqual(1, len(keypairs))
        self.compare_obj(keypairs[0], fake_keypair)
        mock_api_get.assert_called_once_with(self.context, 'fake-user',
                                             limit=1, marker=None)

    @mock.patch('nova.objects.KeyPairList._get_from_db')
    def test_get_by_user_marker(self, mock_api_get):
        api_kp_name = 'api_kp'
        mock_api_get.return_value = [fake_keypair]

        keypairs = keypair.KeyPairList.get_by_user(self.context, 'fake-user',
                                                   marker=api_kp_name)
        self.assertEqual(1, len(keypairs))
        self.compare_obj(keypairs[0], fake_keypair)
        mock_api_get.assert_called_once_with(self.context, 'fake-user',
                                             limit=None,
                                             marker=api_kp_name)

    @mock.patch('nova.objects.KeyPairList._get_from_db')
    def test_get_by_user_limit_and_marker_api(self, mock_api_get):
        first_api_kp_name = 'first_api_kp'

        mock_api_get.return_value = [fake_keypair]

        keypairs = keypair.KeyPairList.get_by_user(self.context, 'fake-user',
                                                   limit=5,
                                                   marker=first_api_kp_name)
        self.assertEqual(1, len(keypairs))
        self.compare_obj(keypairs[0], fake_keypair)
        mock_api_get.assert_called_once_with(self.context, 'fake-user',
                                             limit=5,
                                             marker=first_api_kp_name)

    @mock.patch('nova.objects.KeyPairList._get_from_db')
    def test_get_by_user_limit_and_marker_invalid_marker(self, mock_api_get):
        kp_name = 'unknown_kp'
        mock_api_get.side_effect = exception.MarkerNotFound(marker=kp_name)

        self.assertRaises(exception.MarkerNotFound,
                          keypair.KeyPairList.get_by_user,
                          self.context, 'fake-user',
                          limit=5, marker=kp_name)


class TestMigrationObject(test_objects._LocalTest, _TestKeyPairObject):
    pass


class TestRemoteMigrationObject(test_objects._RemoteTest, _TestKeyPairObject):
    pass

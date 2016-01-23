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

import mock
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

    @mock.patch('nova.db.key_pair_get')
    def test_get_by_name(self, mock_kp_get):
        mock_kp_get.return_value = fake_keypair

        keypair_obj = keypair.KeyPair.get_by_name(self.context, 'fake-user',
                                                  'foo-keypair')
        self.compare_obj(keypair_obj, fake_keypair)

        mock_kp_get.assert_called_once_with(self.context, 'fake-user',
            'foo-keypair')

    @mock.patch('nova.db.key_pair_create')
    def test_create(self, mock_kp_create):
        mock_kp_create.return_value = fake_keypair

        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.name = 'foo-keypair'
        keypair_obj.public_key = 'keydata'
        keypair_obj.create()
        self.compare_obj(keypair_obj, fake_keypair)

        mock_kp_create.assert_called_once_with(self.context,
            {'name': 'foo-keypair', 'public_key': 'keydata'})

    @mock.patch('nova.db.key_pair_create')
    def test_recreate_fails(self, mock_kp_create):
        mock_kp_create.return_value = fake_keypair

        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.name = 'foo-keypair'
        keypair_obj.public_key = 'keydata'
        keypair_obj.create()
        self.assertRaises(exception.ObjectActionError, keypair_obj.create)

        mock_kp_create.assert_called_once_with(self.context,
            {'name': 'foo-keypair', 'public_key': 'keydata'})

    @mock.patch('nova.db.key_pair_destroy')
    def test_destroy(self, mock_kp_destroy):
        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.id = 123
        keypair_obj.user_id = 'fake-user'
        keypair_obj.name = 'foo-keypair'
        keypair_obj.destroy()

        mock_kp_destroy.assert_called_once_with(
            self.context, 'fake-user', 'foo-keypair')

    @mock.patch('nova.db.key_pair_destroy')
    def test_destroy_by_name(self, mock_kp_destroy):
        keypair.KeyPair.destroy_by_name(self.context, 'fake-user',
                                        'foo-keypair')

        mock_kp_destroy.assert_called_once_with(
            self.context, 'fake-user', 'foo-keypair')

    @mock.patch('nova.db.key_pair_get_all_by_user')
    @mock.patch('nova.db.key_pair_count_by_user')
    def test_get_by_user(self, mock_kp_count, mock_kp_get):
        mock_kp_get.return_value = [fake_keypair]
        mock_kp_count.return_value = 1

        keypairs = keypair.KeyPairList.get_by_user(self.context, 'fake-user')
        self.assertEqual(1, len(keypairs))
        self.compare_obj(keypairs[0], fake_keypair)
        self.assertEqual(1, keypair.KeyPairList.get_count_by_user(self.context,
                                                                  'fake-user'))
        mock_kp_get.assert_called_once_with(self.context, 'fake-user')
        mock_kp_count.assert_called_once_with(self.context, 'fake-user')

    def test_obj_make_compatible(self):
        keypair_obj = keypair.KeyPair(context=self.context)
        fake_keypair_copy = dict(fake_keypair)

        keypair_obj.obj_make_compatible(fake_keypair_copy, '1.1')
        self.assertNotIn('type', fake_keypair_copy)


class TestMigrationObject(test_objects._LocalTest,
                          _TestKeyPairObject):
    pass


class TestRemoteMigrationObject(test_objects._RemoteTest,
                                _TestKeyPairObject):
    pass

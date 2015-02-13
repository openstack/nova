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

from oslo_utils import timeutils

from nova import db
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
    def test_get_by_name(self):
        self.mox.StubOutWithMock(db, 'key_pair_get')
        db.key_pair_get(self.context, 'fake-user', 'foo-keypair').AndReturn(
            fake_keypair)
        self.mox.ReplayAll()
        keypair_obj = keypair.KeyPair.get_by_name(self.context, 'fake-user',
                                                  'foo-keypair')
        self.compare_obj(keypair_obj, fake_keypair)

    def test_create(self):
        self.mox.StubOutWithMock(db, 'key_pair_create')
        db.key_pair_create(self.context,
                           {'name': 'foo-keypair',
                            'public_key': 'keydata'}).AndReturn(fake_keypair)
        self.mox.ReplayAll()
        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.name = 'foo-keypair'
        keypair_obj.public_key = 'keydata'
        keypair_obj.create()
        self.compare_obj(keypair_obj, fake_keypair)

    def test_recreate_fails(self):
        self.mox.StubOutWithMock(db, 'key_pair_create')
        db.key_pair_create(self.context,
                           {'name': 'foo-keypair',
                            'public_key': 'keydata'}).AndReturn(fake_keypair)
        self.mox.ReplayAll()
        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.name = 'foo-keypair'
        keypair_obj.public_key = 'keydata'
        keypair_obj.create()
        self.assertRaises(exception.ObjectActionError, keypair_obj.create,
                          self.context)

    def test_destroy(self):
        self.mox.StubOutWithMock(db, 'key_pair_destroy')
        db.key_pair_destroy(self.context, 'fake-user', 'foo-keypair')
        self.mox.ReplayAll()
        keypair_obj = keypair.KeyPair(context=self.context)
        keypair_obj.id = 123
        keypair_obj.user_id = 'fake-user'
        keypair_obj.name = 'foo-keypair'
        keypair_obj.destroy()

    def test_destroy_by_name(self):
        self.mox.StubOutWithMock(db, 'key_pair_destroy')
        db.key_pair_destroy(self.context, 'fake-user', 'foo-keypair')
        self.mox.ReplayAll()
        keypair.KeyPair.destroy_by_name(self.context, 'fake-user',
                                        'foo-keypair')

    def test_get_by_user(self):
        self.mox.StubOutWithMock(db, 'key_pair_get_all_by_user')
        self.mox.StubOutWithMock(db, 'key_pair_count_by_user')
        db.key_pair_get_all_by_user(self.context, 'fake-user').AndReturn(
            [fake_keypair])
        db.key_pair_count_by_user(self.context, 'fake-user').AndReturn(1)
        self.mox.ReplayAll()
        keypairs = keypair.KeyPairList.get_by_user(self.context, 'fake-user')
        self.assertEqual(1, len(keypairs))
        self.compare_obj(keypairs[0], fake_keypair)
        self.assertEqual(1, keypair.KeyPairList.get_count_by_user(self.context,
                                                                  'fake-user'))

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

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

from nova import context
from nova import exception
from nova import objects
from nova.objects import keypair
from nova import test


class KeyPairObjectTestCase(test.TestCase):

    def setUp(self):
        super().setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def _create_keypair(self, **values):
        kp = objects.KeyPair(context=self.context,
                             user_id=self.context.user_id,
                             name='fookey',
                             fingerprint='fp',
                             public_key='keydata',
                             type='ssh')
        kp.update(values)
        kp.create()
        return kp

    def test_create(self):
        kp = self._create_keypair()
        keypair.KeyPair._get_from_db(self.context, kp.user_id, kp.name)

    def test_create_duplicate(self):
        self._create_keypair()
        self.assertRaises(exception.KeyPairExists, self._create_keypair)

    def test_get(self):
        self._create_keypair(name='key')
        kp = objects.KeyPair.get_by_name(self.context, self.context.user_id,
                                         'key')
        self.assertEqual('key', kp.name)

    def test_get_not_found(self):
        self._create_keypair(name='key')
        self.assertRaises(exception.KeypairNotFound,
                          objects.KeyPair.get_by_name,
                          self.context, self.context.user_id, 'nokey')

    def test_destroy(self):
        kp = self._create_keypair(name='key')
        kp.destroy()
        self.assertRaises(exception.KeypairNotFound,
                          objects.KeyPair.get_by_name,
                          self.context, self.context.user_id, 'key')

    def test_destroy_by_name(self):
        self._create_keypair(name='key')
        objects.KeyPair.destroy_by_name(self.context, self.context.user_id,
                                        'key')
        self.assertRaises(exception.KeypairNotFound,
                          objects.KeyPair.get_by_name,
                          self.context, self.context.user_id, 'key')

    def test_get_by_user(self):
        self._create_keypair(name='key1')
        self._create_keypair(name='key2')
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              self.context.user_id)
        self.assertEqual(2, len(kpl))
        self.assertEqual(set(['key1', 'key2']),
                         set([x.name for x in kpl]))

    def test_get_count_by_user(self):
        self._create_keypair(name='key1')
        self._create_keypair(name='key2')
        count = objects.KeyPairList.get_count_by_user(self.context,
                                                      self.context.user_id)
        self.assertEqual(2, count)

    def test_get_by_user_limit_and_marker(self):
        self._create_keypair(name='key1')
        self._create_keypair(name='key2')
        self._create_keypair(name='key3')
        self._create_keypair(name='key4')

        # check all 4 keypairs
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              self.context.user_id)
        self.assertEqual(4, len(kpl))
        self.assertEqual(set(['key1', 'key2', 'key3', 'key4']),
                         set([x.name for x in kpl]))

        # check only 1 keypair
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              self.context.user_id,
                                              limit=1)
        self.assertEqual(1, len(kpl))
        self.assertEqual(set(['key1']),
                         set([x.name for x in kpl]))

        # check only 3 keypairs
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              self.context.user_id,
                                              limit=3)
        self.assertEqual(3, len(kpl))
        self.assertEqual(set(['key1', 'key2', 'key3']),
                         set([x.name for x in kpl]))

        # check keypairs after 'key1' (3 keypairs)
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              self.context.user_id,
                                              marker='key1')
        self.assertEqual(3, len(kpl))
        self.assertEqual(set(['key2', 'key3', 'key4']),
                         set([x.name for x in kpl]))

        # check keypairs after 'key4' (no keypairs)
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              self.context.user_id,
                                              marker='key4')
        self.assertEqual(0, len(kpl))

        # check only 2 keypairs after 'key1' (2 keypairs)
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              self.context.user_id,
                                              limit=2,
                                              marker='key1')
        self.assertEqual(2, len(kpl))
        self.assertEqual(set(['key2', 'key3']),
                         set([x.name for x in kpl]))

        # check non-existing keypair
        self.assertRaises(exception.MarkerNotFound,
                          objects.KeyPairList.get_by_user,
                          self.context, self.context.user_id,
                          limit=2, marker='unknown_kp')

    def test_get_by_user_different_users(self):
        # create keypairs for two users
        self._create_keypair(name='key1', user_id='user1')
        self._create_keypair(name='key2', user_id='user1')
        self._create_keypair(name='key1', user_id='user2')
        self._create_keypair(name='key2', user_id='user2')

        # check all 2 keypairs for user1
        kpl = objects.KeyPairList.get_by_user(self.context, 'user1')
        self.assertEqual(2, len(kpl))
        self.assertEqual(set(['key1', 'key2']),
                         set([x.name for x in kpl]))

        # check all 2 keypairs for user2
        kpl = objects.KeyPairList.get_by_user(self.context, 'user2')
        self.assertEqual(2, len(kpl))
        self.assertEqual(set(['key1', 'key2']),
                         set([x.name for x in kpl]))

        # check only 1 keypair for user1
        kpl = objects.KeyPairList.get_by_user(self.context, 'user1', limit=1)
        self.assertEqual(1, len(kpl))
        self.assertEqual(set(['key1']),
                         set([x.name for x in kpl]))

        # check keypairs after 'key1' for user2 (1 keypair)
        kpl = objects.KeyPairList.get_by_user(self.context, 'user2',
                                              marker='key1')
        self.assertEqual(1, len(kpl))
        self.assertEqual(set(['key2']),
                         set([x.name for x in kpl]))

        # check only 2 keypairs after 'key1' for user1 (1 keypair)
        kpl = objects.KeyPairList.get_by_user(self.context,
                                              'user1',
                                              limit=2,
                                              marker='key1')
        self.assertEqual(1, len(kpl))
        self.assertEqual(set(['key2']),
                         set([x.name for x in kpl]))

        # check non-existing keypair for user2
        self.assertRaises(exception.MarkerNotFound,
                          objects.KeyPairList.get_by_user,
                          self.context, 'user2',
                          limit=2, marker='unknown_kp')

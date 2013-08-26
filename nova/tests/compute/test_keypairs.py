# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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
"""Tests for keypair API."""

from oslo.config import cfg

from nova.compute import api as compute_api
from nova import context
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _
from nova import quota
from nova.tests.compute import test_compute
from nova.tests.objects import test_keypair

CONF = cfg.CONF
QUOTAS = quota.QUOTAS


class KeypairAPITestCase(test_compute.BaseTestCase):
    def setUp(self):
        super(KeypairAPITestCase, self).setUp()
        self.keypair_api = compute_api.KeypairAPI()
        self.ctxt = context.RequestContext('fake', 'fake')
        self._keypair_db_call_stubs()
        self.existing_key_name = 'fake existing key name'
        self.pub_key = ('ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDLnVkqJu9WVf'
                        '/5StU3JCrBR2r1s1j8K1tux+5XeSvdqaM8lMFNorzbY5iyoBbR'
                        'S56gy1jmm43QsMPJsrpfUZKcJpRENSe3OxIIwWXRoiapZe78u/'
                        'a9xKwj0avFYMcws9Rk9iAB7W4K1nEJbyCPl5lRBoyqeHBqrnnu'
                        'XWEgGxJCK0Ah6wcOzwlEiVjdf4kxzXrwPHyi7Ea1qvnNXTziF8'
                        'yYmUlH4C8UXfpTQckwSwpDyxZUc63P8q+vPbs3Q2kw+/7vvkCK'
                        'HJAXVI+oCiyMMfffoTq16M1xfV58JstgtTqAXG+ZFpicGajREU'
                        'E/E3hO5MGgcHmyzIrWHKpe1n3oEGuz')
        self.fingerprint = '4e:48:c6:a0:4a:f9:dd:b5:4c:85:54:5a:af:43:47:5a'

    def _keypair_db_call_stubs(self):

        def db_key_pair_get_all_by_user(context, user_id):
            return [dict(test_keypair.fake_keypair,
                         name=self.existing_key_name,
                         public_key=self.pub_key,
                         fingerprint=self.fingerprint)]

        def db_key_pair_create(context, keypair):
            return dict(test_keypair.fake_keypair, **keypair)

        def db_key_pair_destroy(context, user_id, name):
            pass

        def db_key_pair_get(context, user_id, name):
            if name == self.existing_key_name:
                return dict(test_keypair.fake_keypair,
                            name=self.existing_key_name,
                            public_key=self.pub_key,
                            fingerprint=self.fingerprint)
            else:
                raise exception.KeypairNotFound(user_id=user_id, name=name)

        self.stubs.Set(db, "key_pair_get_all_by_user",
                       db_key_pair_get_all_by_user)
        self.stubs.Set(db, "key_pair_create",
                       db_key_pair_create)
        self.stubs.Set(db, "key_pair_destroy",
                       db_key_pair_destroy)
        self.stubs.Set(db, "key_pair_get",
                       db_key_pair_get)


class CreateImportSharedTestMixIn(object):
    """Tests shared between create and import_key.

    Mix-in pattern is used here so that these `test_*` methods aren't picked
    up by the test runner unless they are part of a 'concrete' test case.
    """

    def assertKeyNameRaises(self, exc_class, expected_message, name):
        func = getattr(self.keypair_api, self.func_name)

        args = []
        if self.func_name == 'import_key_pair':
            args.append(self.pub_key)

        exc = self.assertRaises(exc_class, func, self.ctxt, self.ctxt.user_id,
                                name, *args)
        self.assertEqual(expected_message, unicode(exc))

    def test_name_too_short(self):
        msg = _('Keypair name must be between 1 and 255 characters long')
        self.assertKeyNameRaises(exception.InvalidKeypair, msg, '')

    def test_name_too_long(self):
        msg = _('Keypair name must be between 1 and 255 characters long')
        self.assertKeyNameRaises(exception.InvalidKeypair, msg, 'x' * 256)

    def test_invalid_chars(self):
        msg = _("Keypair name contains unsafe characters")
        self.assertKeyNameRaises(exception.InvalidKeypair, msg,
                                 '* BAD CHARACTERS!  *')

    def test_already_exists(self):
        def db_key_pair_create_duplicate(context, keypair):
            raise exception.KeyPairExists(key_name=keypair.get('name', ''))

        self.stubs.Set(db, "key_pair_create", db_key_pair_create_duplicate)

        msg = (_("Key pair '%(key_name)s' already exists.") %
               {'key_name': self.existing_key_name})
        self.assertKeyNameRaises(exception.KeyPairExists, msg,
                                 self.existing_key_name)

    def test_quota_limit(self):
        def fake_quotas_count(self, context, resource, *args, **kwargs):
            return CONF.quota_key_pairs

        self.stubs.Set(QUOTAS, "count", fake_quotas_count)

        msg = _("Maximum number of key pairs exceeded")
        self.assertKeyNameRaises(exception.KeypairLimitExceeded, msg, 'foo')


class CreateKeypairTestCase(KeypairAPITestCase, CreateImportSharedTestMixIn):
    func_name = 'create_key_pair'

    def test_success(self):
        keypair, private_key = self.keypair_api.create_key_pair(
            self.ctxt, self.ctxt.user_id, 'foo')
        self.assertEqual('foo', keypair['name'])


class ImportKeypairTestCase(KeypairAPITestCase, CreateImportSharedTestMixIn):
    func_name = 'import_key_pair'

    def test_success(self):
        keypair = self.keypair_api.import_key_pair(self.ctxt,
                                                   self.ctxt.user_id,
                                                   'foo',
                                                   self.pub_key)
        self.assertEqual('foo', keypair['name'])
        self.assertEqual(self.fingerprint, keypair['fingerprint'])
        self.assertEqual(self.pub_key, keypair['public_key'])

    def test_bad_key_data(self):
        exc = self.assertRaises(exception.InvalidKeypair,
                                self.keypair_api.import_key_pair,
                                self.ctxt, self.ctxt.user_id, 'foo',
                                'bad key data')
        self.assertEqual(u'Keypair data is invalid', unicode(exc))


class GetKeypairTestCase(KeypairAPITestCase):
    def test_success(self):
        keypair = self.keypair_api.get_key_pair(self.ctxt,
                                                self.ctxt.user_id,
                                                self.existing_key_name)
        self.assertEqual(self.existing_key_name, keypair['name'])


class GetKeypairsTestCase(KeypairAPITestCase):
    def test_success(self):
        keypairs = self.keypair_api.get_key_pairs(self.ctxt, self.ctxt.user_id)
        self.assertEqual([self.existing_key_name],
                         [k['name'] for k in keypairs])

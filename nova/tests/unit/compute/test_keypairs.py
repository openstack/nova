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

from unittest import mock

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_limit import fixture as limit_fixture

from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova.limit import local as local_limit
from nova.objects import keypair as keypair_obj
from nova import quota
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.compute import test_compute
from nova.tests.unit import fake_crypto
from nova.tests.unit.objects import test_keypair
from nova.tests.unit import utils as test_utils

CONF = cfg.CONF


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
        self.keypair_type = keypair_obj.KEYPAIR_TYPE_SSH
        self.key_destroyed = False

    def _keypair_db_call_stubs(self):

        def db_key_pair_get_all_by_user(context, user_id, limit, marker):
            return [dict(test_keypair.fake_keypair,
                         name=self.existing_key_name,
                         public_key=self.pub_key,
                         fingerprint=self.fingerprint)]

        def db_key_pair_create(context, keypair):
            return dict(test_keypair.fake_keypair, **keypair)

        def db_key_pair_destroy(context, user_id, name):
            if name == self.existing_key_name:
                self.key_destroyed = True

        def db_key_pair_get(context, user_id, name):
            if name == self.existing_key_name and not self.key_destroyed:
                return dict(test_keypair.fake_keypair,
                            name=self.existing_key_name,
                            public_key=self.pub_key,
                            fingerprint=self.fingerprint)
            else:
                raise exception.KeypairNotFound(user_id=user_id, name=name)

        self.stub_out(
            'nova.objects.KeyPairList._get_from_db',
            db_key_pair_get_all_by_user)
        self.stub_out('nova.objects.KeyPair._create_in_db', db_key_pair_create)
        self.stub_out(
            'nova.objects.KeyPair._destroy_in_db', db_key_pair_destroy)
        self.stub_out('nova.objects.KeyPair._get_from_db', db_key_pair_get)

    def _check_notifications(self, action='create', key_name='foo'):
        self.assertEqual(2, len(self.notifier.notifications))

        n1 = self.notifier.notifications[0]
        self.assertEqual('INFO', n1.priority)
        self.assertEqual('keypair.%s.start' % action, n1.event_type)
        self.assertEqual('api.%s' % CONF.host, n1.publisher_id)
        self.assertEqual('fake', n1.payload['user_id'])
        self.assertEqual('fake', n1.payload['tenant_id'])
        self.assertEqual(key_name, n1.payload['key_name'])

        n2 = self.notifier.notifications[1]
        self.assertEqual('INFO', n2.priority)
        self.assertEqual('keypair.%s.end' % action, n2.event_type)
        self.assertEqual('api.%s' % CONF.host, n2.publisher_id)
        self.assertEqual('fake', n2.payload['user_id'])
        self.assertEqual('fake', n2.payload['tenant_id'])
        self.assertEqual(key_name, n2.payload['key_name'])


class CreateImportSharedTestMixIn(object):
    """Tests shared between create and import_key.

    Mix-in pattern is used here so that these `test_*` methods aren't picked
    up by the test runner unless they are part of a 'concrete' test case.
    """

    def assertKeypairRaises(self, exc_class, expected_message, name):
        func = getattr(self.keypair_api, self.func_name)

        args = []
        if self.func_name == 'import_key_pair':
            args.append(self.pub_key)
        args.append(self.keypair_type)

        exc = self.assertRaises(exc_class, func, self.ctxt, self.ctxt.user_id,
                                name, *args)
        self.assertIn(expected_message, str(exc))

    def test_already_exists(self):
        def db_key_pair_create_duplicate(context, keypair):
            raise exception.KeyPairExists(key_name=keypair.get('name', ''))

        self.stub_out(
            'nova.objects.KeyPair._create_in_db', db_key_pair_create_duplicate)

        msg = ("Key pair '%(key_name)s' already exists." %
               {'key_name': self.existing_key_name})
        self.assertKeypairRaises(exception.KeyPairExists, msg,
                                 self.existing_key_name)

    @mock.patch.object(quota.QUOTAS, 'count_as_dict',
                       return_value={'user': {
                                         'key_pairs': CONF.quota.key_pairs}})
    def test_quota_limit(self, mock_count_as_dict):
        msg = "Quota exceeded, too many key pairs."
        self.assertKeypairRaises(exception.KeypairLimitExceeded, msg, 'foo')

    def _test_quota_during_recheck(self, mock_method, msg):
        # Skip for import key pair due to bug 1959732.
        if self.func_name == 'import_key_pair':
            self.skipTest('bug/1959732: import_key_pair missing quota recheck')

        self.assertKeypairRaises(exception.KeypairLimitExceeded, msg, 'foo')
        self.assertEqual(2, mock_method.call_count)

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_quota_during_recheck(self, mock_check):
        """Simulate a race where this request initially has enough quota to
        progress partially through the create path but then fails the quota
        recheck because a parallel request filled up the quota first.
        """
        # First quota check succeeds, second (recheck) fails.
        mock_check.side_effect = [None,
                                  exception.OverQuota(overs='key_pairs')]
        msg = "Quota exceeded, too many key pairs."
        self._test_quota_during_recheck(mock_check, msg)

    def test_quota_unified_limits(self):
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")
        ul_api = self.useFixture(nova_fixtures.UnifiedLimitsFixture())
        ul_api.create_registered_limit(
            resource_name='server_key_pairs', default_limit=0)
        msg = ("Resource %s is over limit" % local_limit.KEY_PAIRS)
        self.assertKeypairRaises(exception.KeypairLimitExceeded, msg, 'foo')

    @mock.patch('nova.limit.local.enforce_db_limit')
    def test_quota_during_recheck_unified_limits(self, mock_enforce):
        """Simulate a race where this request initially has enough quota to
        progress partially through the create path but then fails the quota
        recheck because a parallel request filled up the quota first.
        """
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")
        ul_api = self.useFixture(nova_fixtures.UnifiedLimitsFixture())
        ul_api.create_registered_limit(
            resource_name='server_key_pairs', default_limit=100)
        # First quota check succeeds, second (recheck) fails.
        mock_enforce.side_effect = [
            None, exception.KeypairLimitExceeded('oslo.limit message')]
        msg = 'oslo.limit message'
        self._test_quota_during_recheck(mock_enforce, msg)


class CreateKeypairTestCase(KeypairAPITestCase, CreateImportSharedTestMixIn):
    func_name = 'create_key_pair'

    @mock.patch('nova.compute.utils.notify_about_keypair_action')
    def _check_success(self, mock_notify):
        keypair, private_key = self.keypair_api.create_key_pair(
            self.ctxt, self.ctxt.user_id, 'foo', key_type=self.keypair_type)
        self.assertEqual('foo', keypair['name'])
        self.assertEqual(self.keypair_type, keypair['type'])
        mock_notify.assert_has_calls([
            mock.call(context=self.ctxt, keypair=keypair,
                      action='create', phase='start'),
            mock.call(context=self.ctxt, keypair=keypair,
                      action='create', phase='end')])
        self._check_notifications()

    def test_success_ssh(self):
        self._check_success()

    def test_success_x509(self):
        self.keypair_type = keypair_obj.KEYPAIR_TYPE_X509
        self._check_success()

    def test_x509_subject_too_long(self):
        # X509 keypairs will fail if the Subject they're created with
        # is longer than 64 characters. The previous unit tests could not
        # detect the issue because the ctxt.user_id was too short.
        # This unit tests is added to prove this issue.
        self.keypair_type = keypair_obj.KEYPAIR_TYPE_X509
        self.ctxt.user_id = 'a' * 65
        self.assertRaises(processutils.ProcessExecutionError,
                          self._check_success)

    def test_success_unified_limits(self):
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")
        self.useFixture(limit_fixture.LimitFixture(
            {'server_key_pairs': 1}, {}))
        self._check_success()

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_quota_recheck_disabled(self, mock_check):
        self.flags(recheck_quota=False, group="quota")
        self._check_success()
        self.assertEqual(1, mock_check.call_count)

    @mock.patch('nova.limit.local.enforce_db_limit')
    def test_quota_recheck_disabled_unified_limits(self, mock_enforce):
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")
        self.flags(recheck_quota=False, group="quota")
        self.useFixture(limit_fixture.LimitFixture(
            {'server_key_pairs': 1}, {}))
        self._check_success()
        self.assertEqual(1, mock_enforce.call_count)


class ImportKeypairTestCase(KeypairAPITestCase, CreateImportSharedTestMixIn):
    func_name = 'import_key_pair'

    @mock.patch('nova.compute.utils.notify_about_keypair_action')
    def _check_success(self, mock_notify):
        keypair = self.keypair_api.import_key_pair(self.ctxt,
                                                   self.ctxt.user_id,
                                                   'foo',
                                                   self.pub_key,
                                                   self.keypair_type)

        self.assertEqual('foo', keypair['name'])
        self.assertEqual(self.keypair_type, keypair['type'])
        self.assertEqual(self.fingerprint, keypair['fingerprint'])
        self.assertEqual(self.pub_key, keypair['public_key'])
        self.assertEqual(self.keypair_type, keypair['type'])
        mock_notify.assert_has_calls([
            mock.call(context=self.ctxt, keypair=keypair,
                      action='import', phase='start'),
            mock.call(context=self.ctxt, keypair=keypair,
                      action='import', phase='end')])
        self._check_notifications(action='import')

    def test_success_ssh(self):
        self._check_success()

    def test_success_ssh_ed25519(self):
        self.pub_key = ('ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFl6u75BTi8xGtSPm'
                        '1yVJuLE/oMtCOuEMJJnBSuZEdXz')
        self.fingerprint = '1a:1d:a7:2c:4c:ff:15:c4:70:13:38:b6:ac:4c:dc:12'
        self._check_success()

    def test_success_x509(self):
        self.keypair_type = keypair_obj.KEYPAIR_TYPE_X509
        certif, fingerprint = fake_crypto.get_x509_cert_and_fingerprint()
        self.pub_key = certif
        self.fingerprint = fingerprint
        self._check_success()

    def test_bad_key_data(self):
        exc = self.assertRaises(exception.InvalidKeypair,
                                self.keypair_api.import_key_pair,
                                self.ctxt, self.ctxt.user_id, 'foo',
                                'bad key data')
        msg = u'Keypair data is invalid: failed to generate fingerprint'
        self.assertEqual(msg, str(exc))

    def test_success_unified_limits(self):
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")
        self.useFixture(limit_fixture.LimitFixture(
            {'server_key_pairs': 1}, {}))
        self._check_success()

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_quota_recheck_disabled(self, mock_check):
        self.flags(recheck_quota=False, group="quota")
        self._check_success()
        self.assertEqual(1, mock_check.call_count)

    @mock.patch('nova.limit.local.enforce_db_limit')
    def test_quota_recheck_disabled_unified_limits(self, mock_enforce):
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")
        self.flags(recheck_quota=False, group="quota")
        self.useFixture(limit_fixture.LimitFixture(
            {'server_key_pairs': 1}, {}))
        self._check_success()
        self.assertEqual(1, mock_enforce.call_count)


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


class DeleteKeypairTestCase(KeypairAPITestCase):
    @mock.patch('nova.compute.utils.notify_about_keypair_action')
    def test_success(self, mock_notify):
        self.keypair_api.delete_key_pair(self.ctxt, self.ctxt.user_id,
                self.existing_key_name)
        self.assertRaises(exception.KeypairNotFound,
                self.keypair_api.get_key_pair, self.ctxt, self.ctxt.user_id,
                self.existing_key_name)

        match_by_name = test_utils.CustomMockCallMatcher(
            lambda keypair: keypair['name'] == self.existing_key_name)

        mock_notify.assert_has_calls([
            mock.call(context=self.ctxt,
                      keypair=match_by_name,
                      action='delete', phase='start'),
            mock.call(context=self.ctxt,
                      keypair=match_by_name,
                      action='delete', phase='end')])
        self._check_notifications(action='delete',
                key_name=self.existing_key_name)

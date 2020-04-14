# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils

from nova.objects import keypair as keypair_obj
from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit import fake_crypto


class KeyPairsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    microversion = None
    sample_dir = 'os-keypairs'
    expected_delete_status_code = 202
    expected_post_status_code = 200

    def setUp(self):
        super(KeyPairsSampleJsonTest, self).setUp()
        self.api.microversion = self.microversion

    # TODO(sdague): this is only needed because we randomly choose the
    # uuid each time.
    def generalize_subs(self, subs, vanilla_regexes):
        subs['keypair_name'] = 'keypair-[0-9a-f-]+'
        return subs

    def test_keypairs_post(self):
        return self._check_keypairs_post()

    def _check_keypairs_post(self, **kwargs):
        """Get api sample of key pairs post request."""
        key_name = kwargs.pop('kp_name', None)
        if not key_name:
            key_name = 'keypair-' + uuids.fake

        subs = dict(keypair_name=key_name, **kwargs)
        response = self._do_post('os-keypairs', 'keypairs-post-req', subs)
        subs = {'keypair_name': key_name}

        self._verify_response('keypairs-post-resp', subs, response,
                              self.expected_post_status_code)
        # NOTE(maurosr): return the key_name is necessary cause the
        # verification returns the label of the last compared information in
        # the response, not necessarily the key name.
        return key_name

    def test_keypairs_import_key_post(self):
        public_key = fake_crypto.get_ssh_public_key()
        self._check_keypairs_import_key_post(public_key)

    def _check_keypairs_import_key_post(self, public_key, **kwargs):
        # Get api sample of key pairs post to import user's key.
        key_name = 'keypair-' + uuids.fake
        subs = {
            'keypair_name': key_name,
        }
        params = subs.copy()
        params['public_key'] = public_key
        params.update(**kwargs)
        response = self._do_post('os-keypairs', 'keypairs-import-post-req',
                                 params)
        self._verify_response('keypairs-import-post-resp', subs, response,
                              self.expected_post_status_code)

    def test_keypairs_list(self):
        # Get api sample of key pairs list request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs')
        subs = {'keypair_name': key_name}
        self._verify_response('keypairs-list-resp', subs, response, 200)

    def test_keypairs_get(self):
        # Get api sample of key pairs get request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs/%s' % key_name)
        subs = {'keypair_name': key_name}
        self._verify_response('keypairs-get-resp', subs, response, 200)

    def test_keypairs_delete(self):
        # Get api sample of key pairs delete request.
        key_name = self.test_keypairs_post()
        response = self._do_delete('os-keypairs/%s' % key_name)
        self.assertEqual(self.expected_delete_status_code,
                         response.status_code)


class KeyPairsV22SampleJsonTest(KeyPairsSampleJsonTest):
    microversion = '2.2'
    expected_post_status_code = 201
    expected_delete_status_code = 204
    # NOTE(gmann): microversion tests do not need to run for v2 API
    # so defining scenarios only for v2.2 which will run the original tests
    # by appending '(v2_2)' in test_id.
    scenarios = [('v2_2', {'api_major_version': 'v2.1'})]

    def test_keypairs_post(self):
        # NOTE(claudiub): overrides the method with the same name in
        # KeypairsSampleJsonTest, as it is used by other tests.
        return self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_SSH)

    def test_keypairs_post_x509(self):
        return self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_X509)

    def test_keypairs_post_invalid(self):
        key_name = 'keypair-' + uuids.fake
        subs = dict(keypair_name=key_name, keypair_type='fakey_type')
        response = self._do_post('os-keypairs', 'keypairs-post-req', subs)

        self.assertEqual(400, response.status_code)

    def test_keypairs_import_key_post(self):
        # NOTE(claudiub): overrides the method with the same name in
        # KeypairsSampleJsonTest, since the API sample expects a keypair_type.
        public_key = fake_crypto.get_ssh_public_key()
        self._check_keypairs_import_key_post(
            public_key, keypair_type=keypair_obj.KEYPAIR_TYPE_SSH)

    def test_keypairs_import_key_post_x509(self):
        public_key = fake_crypto.get_x509_cert_and_fingerprint()[0]
        public_key = public_key.replace('\n', '\\n')
        self._check_keypairs_import_key_post(
            public_key, keypair_type=keypair_obj.KEYPAIR_TYPE_X509)

    def _check_keypairs_import_key_post_invalid(self, keypair_type):
        key_name = 'keypair-' + uuids.fake
        subs = {
            'keypair_name': key_name,
            'keypair_type': keypair_type,
            'public_key': fake_crypto.get_ssh_public_key()
        }
        response = self._do_post('os-keypairs', 'keypairs-import-post-req',
                                 subs)

        self.assertEqual(400, response.status_code)

    def test_keypairs_import_key_post_invalid_type(self):
        self._check_keypairs_import_key_post_invalid(
            keypair_type='fakey_type')

    def test_keypairs_import_key_post_invalid_combination(self):
        self._check_keypairs_import_key_post_invalid(
            keypair_type=keypair_obj.KEYPAIR_TYPE_X509)


class KeyPairsV210SampleJsonTest(KeyPairsSampleJsonTest):
    ADMIN_API = True
    microversion = '2.10'
    expected_post_status_code = 201
    expected_delete_status_code = 204
    scenarios = [('v2_10', {'api_major_version': 'v2.1'})]

    def test_keypair_create_for_user(self):
        subs = {
            'keypair_type': keypair_obj.KEYPAIR_TYPE_SSH,
            'public_key': fake_crypto.get_ssh_public_key(),
            'user_id': "fake"
        }
        self._check_keypairs_post(**subs)

    def test_keypairs_post(self):
        return self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_SSH,
            user_id="admin")

    def test_keypairs_import_key_post(self):
        # NOTE(claudiub): overrides the method with the same name in
        # KeypairsSampleJsonTest, since the API sample expects a keypair_type.
        public_key = fake_crypto.get_ssh_public_key()
        self._check_keypairs_import_key_post(
            public_key, keypair_type=keypair_obj.KEYPAIR_TYPE_SSH,
            user_id="fake")

    def test_keypairs_delete_for_user(self):
        # Delete a keypair on behalf of a user
        subs = {
            'keypair_type': keypair_obj.KEYPAIR_TYPE_SSH,
            'public_key': fake_crypto.get_ssh_public_key(),
            'user_id': "fake"
        }
        key_name = self._check_keypairs_post(**subs)
        response = self._do_delete('os-keypairs/%s?user_id=fake' % key_name)
        self.assertEqual(self.expected_delete_status_code,
                         response.status_code)

    def test_keypairs_list_for_different_users(self):
        # Get api sample of key pairs list request.

        # create common kp_name for two users
        kp_name = 'keypair-' + uuids.fake

        keypair_user1 = self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_SSH,
            user_id="user1", kp_name=kp_name)
        keypair_user2 = self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_SSH,
            user_id="user2", kp_name=kp_name)

        # get all keypairs for user1 (only one)
        response = self._do_get('os-keypairs?user_id=user1')
        subs = {'keypair_name': keypair_user1}
        self._verify_response('keypairs-list-resp', subs, response, 200)

        # get all keypairs for user2 (only one)
        response = self._do_get('os-keypairs?user_id=user2')
        subs = {'keypair_name': keypair_user2}
        self._verify_response('keypairs-list-resp', subs, response, 200)


class KeyPairsV210SampleJsonTestNotAdmin(KeyPairsV210SampleJsonTest):
    ADMIN_API = False

    def test_keypairs_post(self):
        return self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_SSH,
            user_id="fake")

    def test_keypairs_post_for_other_user(self):
        rules = {'os_compute_api:os-keypairs:create':
                     'rule:admin_api or user_id:%(user_id)s'}
        self.policy.set_rules(rules, overwrite=False)
        key_name = 'keypair-' + uuids.fake
        subs = dict(keypair_name=key_name,
                    keypair_type=keypair_obj.KEYPAIR_TYPE_SSH,
                    user_id='fake1')
        response = self._do_post('os-keypairs', 'keypairs-post-req', subs)

        self.assertEqual(403, response.status_code)

    def test_keypairs_list_for_different_users(self):
        # get and post for other users is forbidden for non admin
        rules = {'os_compute_api:os-keypairs:index':
                     'rule:admin_api or user_id:%(user_id)s'}
        self.policy.set_rules(rules, overwrite=False)
        response = self._do_get('os-keypairs?user_id=fake1')
        self.assertEqual(403, response.status_code)


class KeyPairsV235SampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = 'os-keypairs'
    microversion = '2.35'
    expected_post_status_code = 201
    scenarios = [('v2_35', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(KeyPairsV235SampleJsonTest, self).setUp()
        self.api.microversion = self.microversion

    # TODO(pkholkin): this is only needed because we randomly choose the
    # uuid each time.
    def generalize_subs(self, subs, vanilla_regexes):
        subs['keypair_name'] = 'keypair-[0-9a-f-]+'
        return subs

    def test_keypairs_post(self, user="admin", kp_name=None):
        return self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_SSH,
            user_id=user, kp_name=kp_name)

    def _check_keypairs_post(self, **kwargs):
        """Get api sample of key pairs post request."""
        key_name = kwargs.pop('kp_name', None)
        if not key_name:
            key_name = 'keypair-' + uuidutils.generate_uuid()

        subs = dict(keypair_name=key_name, **kwargs)
        response = self._do_post('os-keypairs', 'keypairs-post-req', subs)
        subs = {'keypair_name': key_name}

        self._verify_response('keypairs-post-resp', subs, response,
                              self.expected_post_status_code)
        return key_name

    def test_keypairs_list(self):
        # Get api sample of key pairs list request.

        # sort key_pairs by name before paging
        keypairs = sorted([self.test_keypairs_post() for i in range(3)])

        response = self._do_get('os-keypairs?marker=%s&limit=1' % keypairs[1])
        subs = {'keypair_name': keypairs[2]}
        self._verify_response('keypairs-list-resp', subs, response, 200)

    def test_keypairs_list_for_different_users(self):
        # Get api sample of key pairs list request.

        # create common kp_names for two users
        kp_names = ['keypair-' + uuidutils.generate_uuid() for i in range(3)]

        # sort key_pairs by name before paging
        keypairs_user1 = sorted([self.test_keypairs_post(
            user="user1", kp_name=kp_name) for kp_name in kp_names])
        keypairs_user2 = sorted([self.test_keypairs_post(
            user="user2", kp_name=kp_name) for kp_name in kp_names])

        # get all keypairs after the second for user1
        response = self._do_get('os-keypairs?user_id=user1&marker=%s'
                                % keypairs_user1[1])
        subs = {'keypair_name': keypairs_user1[2]}
        self._verify_response('keypairs-list-user1-resp', subs, response, 200)

        # get only one keypair after the second for user2
        response = self._do_get('os-keypairs?user_id=user2&marker=%s&limit=1'
                                % keypairs_user2[1])
        subs = {'keypair_name': keypairs_user2[2]}
        self._verify_response('keypairs-list-user2-resp', subs, response, 200)

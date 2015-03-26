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

import uuid

from nova.objects import keypair as keypair_obj
from nova.tests.functional.v3 import api_sample_base
from nova.tests.unit import fake_crypto


class KeyPairsSampleJsonTest(api_sample_base.ApiSampleTestBaseV3):
    request_api_version = None
    sample_dir = "keypairs"
    expected_delete_status_code = 202
    expected_post_status_code = 200

    def generalize_subs(self, subs, vanilla_regexes):
        subs['keypair_name'] = 'keypair-[0-9a-f-]+'
        return subs

    def test_keypairs_post(self):
        return self._check_keypairs_post()

    def _check_keypairs_post(self, **kwargs):
        """Get api sample of key pairs post request."""
        key_name = 'keypair-' + str(uuid.uuid4())
        subs = dict(keypair_name=key_name, **kwargs)
        response = self._do_post('os-keypairs', 'keypairs-post-req', subs,
                                 api_version=self.request_api_version)

        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
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
        key_name = 'keypair-' + str(uuid.uuid4())
        subs = {
            'keypair_name': key_name,
            'public_key': public_key
        }
        subs.update(**kwargs)
        response = self._do_post('os-keypairs', 'keypairs-import-post-req',
                                 subs, api_version=self.request_api_version)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-import-post-resp', subs, response,
                              self.expected_post_status_code)

    def test_keypairs_list(self):
        # Get api sample of key pairs list request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs',
                                api_version=self.request_api_version)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-list-resp', subs, response, 200)

    def test_keypairs_get(self):
        # Get api sample of key pairs get request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs/%s' % key_name,
                                api_version=self.request_api_version)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-get-resp', subs, response, 200)

    def test_keypairs_delete(self):
        # Get api sample of key pairs delete request.
        key_name = self.test_keypairs_post()
        response = self._do_delete('os-keypairs/%s' % key_name,
                                    api_version=self.request_api_version)
        self.assertEqual(self.expected_delete_status_code,
                         response.status_code)


class KeyPairsV22SampleJsonTest(KeyPairsSampleJsonTest):
    request_api_version = '2.2'
    expected_post_status_code = 201
    expected_delete_status_code = 204

    def test_keypairs_post(self):
        # NOTE(claudiub): overrides the method with the same name in
        # KeypairsSampleJsonTest, as it is used by other tests.
        return self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_SSH)

    def test_keypairs_post_x509(self):
        return self._check_keypairs_post(
            keypair_type=keypair_obj.KEYPAIR_TYPE_X509)

    def test_keypairs_post_invalid(self):
        key_name = 'keypair-' + str(uuid.uuid4())
        subs = dict(keypair_name=key_name, keypair_type='fakey_type')
        response = self._do_post('os-keypairs', 'keypairs-post-req', subs,
                                 api_version=self.request_api_version)

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
        key_name = 'keypair-' + str(uuid.uuid4())
        subs = {
            'keypair_name': key_name,
            'keypair_type': keypair_type,
            'public_key': fake_crypto.get_ssh_public_key()
        }
        response = self._do_post('os-keypairs', 'keypairs-import-post-req',
                                 subs, api_version=self.request_api_version)

        self.assertEqual(400, response.status_code)

    def test_keypairs_import_key_post_invalid_type(self):
        self._check_keypairs_import_key_post_invalid(
            keypair_type='fakey_type')

    def test_keypairs_import_key_post_invalid_combination(self):
        self._check_keypairs_import_key_post_invalid(
            keypair_type=keypair_obj.KEYPAIR_TYPE_X509)

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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import test_servers

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class ServersMetadataJsonTest(test_servers.ServersSampleBase):
    sample_dir = 'server-metadata'

    def _create_and_set(self, subs):
        uuid = self._post_server()
        response = self._do_put('/servers/%s/metadata' % uuid,
                                'server-metadata-all-req',
                                subs)
        self._verify_response('server-metadata-all-resp', subs, response, 200)
        return uuid

    def generalize_subs(self, subs, vanilla_regexes):
        subs['value'] = '(Foo|Bar) Value'
        return subs

    def test_metadata_put_all(self):
        # Test setting all metadata for a server.
        subs = {'value': 'Foo Value'}
        self._create_and_set(subs)

    def test_metadata_post_all(self):
        # Test updating all metadata for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        subs['value'] = 'Bar Value'
        response = self._do_post('servers/%s/metadata' % uuid,
                                 'server-metadata-all-req',
                                 subs)
        self._verify_response('server-metadata-all-resp', subs, response, 200)

    def test_metadata_get_all(self):
        # Test getting all metadata for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_get('servers/%s/metadata' % uuid)
        self._verify_response('server-metadata-all-resp', subs, response, 200)

    def test_metadata_put(self):
        # Test putting an individual metadata item for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        subs['value'] = 'Bar Value'
        response = self._do_put('servers/%s/metadata/foo' % uuid,
                                'server-metadata-req',
                                subs)
        self._verify_response('server-metadata-resp', subs, response, 200)

    def test_metadata_get(self):
        # Test getting an individual metadata item for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_get('servers/%s/metadata/foo' % uuid)
        self._verify_response('server-metadata-resp', subs, response, 200)

    def test_metadata_delete(self):
        # Test deleting an individual metadata item for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_delete('servers/%s/metadata/foo' % uuid)
        self.assertEqual(204, response.status_code)
        self.assertEqual('', response.content)

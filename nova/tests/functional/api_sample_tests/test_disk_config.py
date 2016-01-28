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
from nova.tests.unit.image import fake

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class DiskConfigJsonTest(test_servers.ServersSampleBase):
    extension_name = 'os-disk-config'
    extra_extensions_to_load = ["os-access-ips"]

    def _get_flags(self):
        f = super(DiskConfigJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.keypairs.Keypairs')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.extended_ips.Extended_ips')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.extended_ips_mac.'
            'Extended_ips_mac')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.disk_config.'
            'Disk_config')
        return f

    def test_list_servers_detail(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/detail')
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = ''
        subs['access_ip_v6'] = ''
        subs['id'] = uuid
        self._verify_response('list-servers-detail-get', subs, response, 200)

    def test_get_server(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = ''
        subs['access_ip_v6'] = ''
        self._verify_response('server-get-resp', subs, response, 200)

    def test_resize_server(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-resize-post-req', {})
        self.assertEqual(202, response.status_code)
        # NOTE(tmello): Resize does not return response body
        # Bug #1085213.
        self.assertEqual("", response.content)

    def test_rebuild_server(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        subs = {
            'image_id': fake.get_valid_image_id(),
            'compute_endpoint': self._get_compute_endpoint(),
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-rebuild-req', subs)
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = ''
        subs['access_ip_v6'] = ''
        self._verify_response('server-action-rebuild-resp',
                              subs, response, 202)

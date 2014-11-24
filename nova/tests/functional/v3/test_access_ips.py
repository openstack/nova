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

from nova.tests.functional.v3 import api_sample_base
from nova.tests.unit.image import fake


class AccessIPsSampleJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = 'os-access-ips'

    def _servers_post(self, subs):
        response = self._do_post('servers', 'server-post-req', subs)
        subs.update(self._get_regexes())
        return self._verify_response('server-post-resp', subs, response, 202)

    def test_servers_post(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': 'fe80::'
        }
        self._servers_post(subs)

    def test_servers_get(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': 'fe80::'
        }
        uuid = self._servers_post(subs)
        response = self._do_get('servers/%s' % uuid)
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        self._verify_response('server-get-resp', subs, response, 200)

    def test_servers_details(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': 'fe80::'
        }
        uuid = self._servers_post(subs)
        response = self._do_get('servers/detail')
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        self._verify_response('servers-details-resp', subs, response, 200)

    def test_servers_rebuild(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': 'fe80::'
        }
        uuid = self._servers_post(subs)
        subs['access_ip_v4'] = "4.3.2.1"
        subs['access_ip_v6'] = '80fe::'
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-rebuild', subs)
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        self._verify_response('server-action-rebuild-resp',
                              subs, response, 202)

    def test_servers_update(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': 'fe80::'
        }
        uuid = self._servers_post(subs)
        subs['access_ip_v4'] = "4.3.2.1"
        subs['access_ip_v6'] = '80fe::'
        response = self._do_put('servers/%s' % uuid, 'server-put-req', subs)
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        self._verify_response('server-put-resp', subs, response, 200)

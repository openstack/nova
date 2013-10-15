# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from nova.tests.image import fake
from nova.tests.integrated.v3 import test_servers


class DiskConfigJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-disk-config"

    def test_list_servers_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        self._verify_response('list-servers-detail-get', subs, response, 200)

    def test_get_server(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_update_server(self):
        uuid = self._post_server()
        response = self._do_put('servers/%s' % uuid,
                                'server-update-put-req', {})
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-update-put-resp', subs, response, 200)

    def test_resize_server(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-resize-post-req', {})
        self.assertEqual(response.status, 202)
        # NOTE(tmello): Resize does not return response body
        # Bug #1085213.
        self.assertEqual(response.read(), "")

    def test_rebuild_server(self):
        uuid = self._post_server()
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-rebuild-req', subs)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-action-rebuild-resp',
                              subs, response, 202)


class DiskConfigXmlTest(DiskConfigJsonTest):
    ctype = 'xml'

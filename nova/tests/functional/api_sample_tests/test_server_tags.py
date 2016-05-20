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

from nova.db.sqlalchemy import models
from nova.tests.functional.api_sample_tests import test_servers

TAG = 'sometag'


class ServerTagsJsonTest(test_servers.ServersSampleBase):
    extension_name = 'os-server-tags'
    microversion = '2.26'
    scenarios = [('v2_26', {'api_major_version': 'v2.1'})]

    def _get_create_subs(self):
        return {'tag': TAG}

    def _put_server_tags(self):
        """Verify the response status and returns the UUID of the
        newly created server with tags.
        """
        uuid = self._post_server()
        subs = self._get_create_subs()
        response = self._do_put('servers/%s/tags' % uuid,
                                'server-tags-put-all-req', subs)
        self.assertEqual(200, response.status_code)
        return uuid

    def test_server_tags_update_all(self):
        self._put_server_tags()

    def test_server_tags_show(self):
        uuid = self._put_server_tags()
        response = self._do_get('servers/%s/tags/%s' % (uuid, TAG))
        self.assertEqual(204, response.status_code)

    def test_server_tags_show_with_details_information(self):
        uuid = self._put_server_tags()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['tag'] = '[0-9a-zA-Z]+'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        self._verify_response('server-tags-show-details-resp',
                              subs, response, 200)

    def test_server_tags_list_with_details_information(self):
        self._put_server_tags()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['tag'] = '[0-9a-zA-Z]+'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        self._verify_response('servers-tags-details-resp', subs, response, 200)

    def test_server_tags_index(self):
        uuid = self._put_server_tags()
        response = self._do_get('servers/%s/tags' % uuid)
        subs = self._get_regexes()
        subs['tag'] = '[0-9a-zA-Z]+'
        self._verify_response('server-tags-index-resp', subs, response, 200)

    def test_server_tags_update(self):
        uuid = self._put_server_tags()
        tag = models.Tag()
        tag.resource_id = uuid
        tag.tag = 'OtherTag'
        response = self._do_put('servers/%s/tags/%s' % (uuid, tag.tag))
        self.assertEqual(201, response.status_code)
        expected_location = "%s/servers/%s/tags/%s" % (
            self._get_vers_compute_endpoint(), uuid, tag.tag)
        self.assertEqual(expected_location, response.headers['Location'])

    def test_server_tags_delete(self):
        uuid = self._put_server_tags()
        response = self._do_delete('servers/%s/tags/%s' % (uuid, TAG))
        self.assertEqual(204, response.status_code)
        self.assertEqual('', response.content)

    def test_server_tags_delete_all(self):
        uuid = self._put_server_tags()
        response = self._do_delete('servers/%s/tags' % uuid)
        self.assertEqual(204, response.status_code)
        self.assertEqual('', response.content)

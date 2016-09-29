# Copyright 2012 Nebula, Inc.
# Copyright 2014 IBM Corp.
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

from nova.tests.functional.api_sample_tests import api_sample_base


class ServerGroupsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = "os-server-groups"

    def _get_create_subs(self):
        return {'name': 'test'}

    def _post_server_group(self):
        """Verify the response status and returns the UUID of the
        newly created server group.
        """
        subs = self._get_create_subs()
        response = self._do_post('os-server-groups',
                                 'server-groups-post-req', subs)
        subs = {}
        subs['name'] = 'test'
        return self._verify_response('server-groups-post-resp',
                                     subs, response, 200)

    def test_server_groups_post(self):
        return self._post_server_group()

    def test_server_groups_list(self):
        subs = self._get_create_subs()
        uuid = self._post_server_group()
        response = self._do_get('os-server-groups')
        subs['id'] = uuid
        self._verify_response('server-groups-list-resp',
                              subs, response, 200)

    def test_server_groups_get(self):
        # Get api sample of server groups get request.
        subs = {'name': 'test'}
        uuid = self._post_server_group()
        subs['id'] = uuid
        response = self._do_get('os-server-groups/%s' % uuid)

        self._verify_response('server-groups-get-resp', subs, response, 200)

    def test_server_groups_delete(self):
        uuid = self._post_server_group()
        response = self._do_delete('os-server-groups/%s' % uuid)
        self.assertEqual(204, response.status_code)


class ServerGroupsV213SampleJsonTest(ServerGroupsSampleJsonTest):
    scenarios = [
        ("v2_13", {'api_major_version': 'v2.1', 'microversion': '2.13'})
    ]

    def setUp(self):
        super(ServerGroupsV213SampleJsonTest, self).setUp()
        self.api.microversion = self.microversion

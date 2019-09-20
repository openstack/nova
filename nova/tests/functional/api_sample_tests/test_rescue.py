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

from nova.tests.functional.api_sample_tests import test_servers


class RescueJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-rescue"

    def _rescue(self, uuid):
        req_subs = {
            'password': 'MySecretPass'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-rescue-req', req_subs)
        self._verify_response('server-rescue', req_subs, response, 200)

    def _unrescue(self, uuid):
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-unrescue-req', {})
        self.assertEqual(202, response.status_code)

    def test_server_rescue(self):
        uuid = self._post_server()

        self._rescue(uuid)

        # Do a server get to make sure that the 'RESCUE' state is set
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'RESCUE'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        subs['instance_name'] = r'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['cdrive'] = '.*'
        self._verify_response('server-get-resp-rescue', subs, response, 200)

    def test_server_rescue_with_image_ref_specified(self):
        uuid = self._post_server()

        req_subs = {
            'password': 'MySecretPass',
            'image_ref': '2341-Abc'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-rescue-req-with-image-ref', req_subs)
        self._verify_response('server-rescue', req_subs, response, 200)

        # Do a server get to make sure that the 'RESCUE' state is set
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'RESCUE'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        subs['instance_name'] = r'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['cdrive'] = '.*'
        self._verify_response('server-get-resp-rescue', subs, response, 200)

    def test_server_unrescue(self):
        uuid = self._post_server()

        self._rescue(uuid)
        self._unrescue(uuid)

        # Do a server get to make sure that the 'ACTIVE' state is back
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'ACTIVE'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        subs['instance_name'] = r'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['cdrive'] = '.*'
        self._verify_response('server-get-resp-unrescue', subs, response, 200)

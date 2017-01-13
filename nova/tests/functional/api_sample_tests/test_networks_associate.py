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


class NetworksAssociateJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-networks-associate"

    _sentinel = object()

    def setUp(self):
        super(NetworksAssociateJsonTests, self).setUp()

        def fake_associate(self, context, network_id,
                           host=NetworksAssociateJsonTests._sentinel,
                           project=NetworksAssociateJsonTests._sentinel):
            return True

        self.stub_out("nova.network.api.API.associate", fake_associate)

    def test_disassociate(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-req',
                                 {})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_disassociate_host(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-host-req',
                                 {})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_disassociate_project(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-project-req',
                                 {})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_associate_host(self):
        response = self._do_post('os-networks/1/action',
                                 'network-associate-host-req',
                                 {"host": "testHost"})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

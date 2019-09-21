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

    def test_disassociate(self):
        self.api.api_post('os-networks/1/action',
                          {'disassociate': None},
                          check_response_status=[410])

    def test_disassociate_host(self):
        self.api.api_post('os-networks/1/action',
                          {'disassociate_host': None},
                          check_response_status=[410])

    def test_disassociate_project(self):
        self.api.api_post('os-networks/1/action',
                          {'disassociate_project': None},
                          check_response_status=[410])

    def test_associate_host(self):
        self.api.api_post('os-networks/1/action',
                          {'associate_host': 'foo'},
                          check_response_status=[410])

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

from nova.tests.functional.api_sample_tests import api_sample_base


class AgentsJsonTest(api_sample_base.ApiSampleTestBaseV21):

    def test_agent_create(self):
        # Creates a new agent build.
        self.api.api_post('/os-agents', {}, check_response_status=[410])

    def test_agent_list(self):
        # Return a list of all agent builds.
        self.api.api_get('/os-agents', check_response_status=[410])

    def test_agent_update(self):
        # Update an existing agent build.
        self.api.api_put('/os-agents/1', {}, check_response_status=[410])

    def test_agent_delete(self):
        # Deletes an existing agent build.
        self.api.api_delete('/os-agents/1', check_response_status=[410])

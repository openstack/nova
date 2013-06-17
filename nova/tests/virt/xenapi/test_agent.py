# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
# All Rights Reserved.
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


from nova import test
from nova.virt.xenapi import agent


class AgentEnabledCase(test.TestCase):
    def test_agent_is_present(self):
        self.flags(xenapi_use_agent_default=False)
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "true"}]}
        self.assertTrue(agent.should_use_agent(instance))

    def test_agent_is_disabled(self):
        self.flags(xenapi_use_agent_default=True)
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "false"}]}
        self.assertFalse(agent.should_use_agent(instance))

    def test_agent_uses_deafault_when_prop_invalid(self):
        self.flags(xenapi_use_agent_default=True)
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "bob"}],
            "uuid": "uuid"}
        self.assertTrue(agent.should_use_agent(instance))

    def test_agent_default_not_present(self):
        self.flags(xenapi_use_agent_default=False)
        instance = {"system_metadata": []}
        self.assertFalse(agent.should_use_agent(instance))

    def test_agent_default_present(self):
        self.flags(xenapi_use_agent_default=True)
        instance = {"system_metadata": []}
        self.assertTrue(agent.should_use_agent(instance))

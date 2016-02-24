# Copyright (c) 2016 OpenStack Foundation
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

from nova.tests.unit.virt.xenapi.plugins import plugin_test


class NovaPluginVersion(plugin_test.PluginTestBase):
    def setUp(self):
        super(NovaPluginVersion, self).setUp()
        self.nova_plugin_version = self.load_plugin("nova_plugin_version")

    def test_nova_plugin_version(self):
        session = 'fake_session'
        expected_value = self.nova_plugin_version.PLUGIN_VERSION
        return_value = self.nova_plugin_version.get_version(session)
        self.assertEqual(expected_value, return_value)

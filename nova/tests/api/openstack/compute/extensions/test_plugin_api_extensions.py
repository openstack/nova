# Copyright 2011 OpenStack Foundation
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

import pkg_resources

from nova.api.openstack.compute import extensions as computeextensions
from nova.api.openstack import extensions
from nova.openstack.common.plugin import plugin
from nova import test


class StubController(object):

    def i_am_the_stub(self):
        pass


class StubControllerExtension(extensions.ExtensionDescriptor):
    """This is a docstring.  We need it."""
    name = 'stubextension'
    alias = 'stubby'

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('testme',
                                           StubController())
        resources.append(res)
        return resources


service_list = []


class TestPluginClass(plugin.Plugin):

    def __init__(self, service_name):
        super(TestPluginClass, self).__init__(service_name)
        self._add_api_extension_descriptor(StubControllerExtension)
        service_list.append(service_name)


class MockEntrypoint(pkg_resources.EntryPoint):
    def load(self):
        return TestPluginClass


class APITestCase(test.TestCase):
    """Test case for the plugin api extension interface."""
    def test_add_extension(self):
        def mock_load(_s):
            return TestPluginClass()

        def mock_iter_entry_points(_t):
            return [MockEntrypoint("fake", "fake", ["fake"])]

        self.stubs.Set(pkg_resources, 'iter_entry_points',
                mock_iter_entry_points)
        global service_list
        service_list = []

        # Marking out the default extension paths makes this test MUCH faster.
        self.flags(osapi_compute_extension=[])

        found = False
        mgr = computeextensions.ExtensionManager()
        for res in mgr.get_resources():
            # We have to use this weird 'dir' check because
            #  the plugin framework muddies up the classname
            #  such that 'isinstance' doesn't work right.
            if 'i_am_the_stub' in dir(res.controller):
                found = True

        self.assertTrue(found)
        self.assertEqual(len(service_list), 1)
        self.assertEqual(service_list[0], 'compute-extensions')

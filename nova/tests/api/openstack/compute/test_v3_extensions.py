# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from nova.api.openstack import compute
from nova.api.openstack.compute import plugins
from nova import test

CONF = cfg.CONF


class fake_bad_extension(object):
    name = "fake_bad_extension"
    alias = "fake-bad"


class ExtensionLoadingTestCase(test.TestCase):

    def test_extensions_loaded(self):
        app = compute.APIRouterV3()
        self.assertIn('servers', app._loaded_extension_info.extensions)

    def test_check_bad_extension(self):
        extension_info = plugins.LoadedExtensionInfo()
        self.assertFalse(extension_info._check_extension(fake_bad_extension))

    def test_extensions_blacklist(self):
        app = compute.APIRouterV3()
        self.assertIn('os-fixed-ips', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_blacklist', 'os-fixed-ips', 'osapi_v3')
        app = compute.APIRouterV3()
        self.assertNotIn('os-fixed-ips', app._loaded_extension_info.extensions)

    def test_extensions_whitelist_accept(self):
        app = compute.APIRouterV3()
        self.assertIn('os-fixed-ips', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_whitelist', 'servers,os-fixed-ips',
                          'osapi_v3')
        app = compute.APIRouterV3()
        self.assertIn('os-fixed-ips', app._loaded_extension_info.extensions)

    def test_extensions_whitelist_block(self):
        app = compute.APIRouterV3()
        self.assertIn('os-fixed-ips', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_whitelist', 'servers', 'osapi_v3')
        app = compute.APIRouterV3()
        self.assertNotIn('os-fixed-ips', app._loaded_extension_info.extensions)

    def test_blacklist_overrides_whitelist(self):
        app = compute.APIRouterV3()
        self.assertIn('os-fixed-ips', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_whitelist', 'servers,os-fixed-ips',
                          'osapi_v3')
        CONF.set_override('extensions_blacklist', 'os-fixed-ips', 'osapi_v3')
        app = compute.APIRouterV3()
        self.assertNotIn('os-fixed-ips', app._loaded_extension_info.extensions)
        self.assertIn('servers', app._loaded_extension_info.extensions)
        self.assertEqual(len(app._loaded_extension_info.extensions), 1)

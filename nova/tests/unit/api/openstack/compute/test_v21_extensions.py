# Copyright 2013 IBM Corp.
# Copyright 2014 NEC Corporation.  All rights reserved.
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

import mock
from oslo_config import cfg
import stevedore
import webob.exc

from nova.api import openstack
from nova.api.openstack import compute
from nova.api.openstack.compute import plugins
from nova.api.openstack import extensions
from nova import exception
from nova import test

CONF = cfg.CONF


class fake_bad_extension(object):
    name = "fake_bad_extension"
    alias = "fake-bad"


class fake_stevedore_enabled_extensions(object):
    def __init__(self, namespace, check_func, invoke_on_load=False,
                 invoke_args=(), invoke_kwds=None):
        self.extensions = []

    def map(self, func, *args, **kwds):
        pass

    def __iter__(self):
        return iter(self.extensions)


class fake_loaded_extension_info(object):
    def __init__(self):
        self.extensions = {}

    def register_extension(self, ext):
        self.extensions[ext] = ext
        return True

    def get_extensions(self):
        return {'core1': None, 'core2': None, 'noncore1': None}


class ExtensionLoadingTestCase(test.NoDBTestCase):

    def _set_v21_core(self, core_extensions):
        openstack.API_V3_CORE_EXTENSIONS = core_extensions

    def test_extensions_loaded(self):
        app = compute.APIRouterV21()
        self.assertIn('servers', app._loaded_extension_info.extensions)

    def test_check_bad_extension(self):
        extension_info = plugins.LoadedExtensionInfo()
        self.assertFalse(extension_info._check_extension(fake_bad_extension))

    def test_extensions_blacklist(self):
        app = compute.APIRouterV21()
        self.assertIn('os-hosts', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_blacklist', ['os-hosts'], 'osapi_v3')
        app = compute.APIRouterV21()
        self.assertNotIn('os-hosts', app._loaded_extension_info.extensions)

    @mock.patch('nova.api.openstack.APIRouterV21._register_resources_list')
    def test_extensions_inherit(self, mock_register):
        app = compute.APIRouterV21()
        self.assertIn('servers', app._loaded_extension_info.extensions)
        self.assertIn('os-volumes', app._loaded_extension_info.extensions)

        mock_register.assert_called_with(mock.ANY, mock.ANY)
        ext_no_inherits = mock_register.call_args_list[0][0][0]
        ext_has_inherits = mock_register.call_args_list[1][0][0]
        # os-volumes inherits from servers
        name_list = [ext.obj.alias for ext in ext_has_inherits]
        self.assertIn('os-volumes', name_list)
        name_list = [ext.obj.alias for ext in ext_no_inherits]
        self.assertIn('servers', name_list)

    def test_extensions_whitelist_accept(self):
        # NOTE(maurosr): just to avoid to get an exception raised for not
        # loading all core api.
        v21_core = openstack.API_V3_CORE_EXTENSIONS
        openstack.API_V3_CORE_EXTENSIONS = set(['servers'])
        self.addCleanup(self._set_v21_core, v21_core)

        app = compute.APIRouterV21()
        self.assertIn('os-hosts', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_whitelist', ['servers', 'os-hosts'],
                          'osapi_v3')
        app = compute.APIRouterV21()
        self.assertIn('os-hosts', app._loaded_extension_info.extensions)

    def test_extensions_whitelist_block(self):
        # NOTE(maurosr): just to avoid to get an exception raised for not
        # loading all core api.
        v21_core = openstack.API_V3_CORE_EXTENSIONS
        openstack.API_V3_CORE_EXTENSIONS = set(['servers'])
        self.addCleanup(self._set_v21_core, v21_core)

        app = compute.APIRouterV21()
        self.assertIn('os-hosts', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_whitelist', ['servers'], 'osapi_v3')
        app = compute.APIRouterV21()
        self.assertNotIn('os-hosts', app._loaded_extension_info.extensions)

    def test_blacklist_overrides_whitelist(self):
        # NOTE(maurosr): just to avoid to get an exception raised for not
        # loading all core api.
        v21_core = openstack.API_V3_CORE_EXTENSIONS
        openstack.API_V3_CORE_EXTENSIONS = set(['servers'])
        self.addCleanup(self._set_v21_core, v21_core)

        app = compute.APIRouterV21()
        self.assertIn('os-hosts', app._loaded_extension_info.extensions)
        CONF.set_override('extensions_whitelist', ['servers', 'os-hosts'],
                          'osapi_v3')
        CONF.set_override('extensions_blacklist', ['os-hosts'], 'osapi_v3')
        app = compute.APIRouterV21()
        self.assertNotIn('os-hosts', app._loaded_extension_info.extensions)
        self.assertIn('servers', app._loaded_extension_info.extensions)
        self.assertEqual(1, len(app._loaded_extension_info.extensions))

    def test_get_missing_core_extensions(self):
        v21_core = openstack.API_V3_CORE_EXTENSIONS
        openstack.API_V3_CORE_EXTENSIONS = set(['core1', 'core2'])
        self.addCleanup(self._set_v21_core, v21_core)
        self.assertEqual(0, len(
            compute.APIRouterV21.get_missing_core_extensions(
            ['core1', 'core2', 'noncore1'])))
        missing_core = compute.APIRouterV21.get_missing_core_extensions(
            ['core1'])
        self.assertEqual(1, len(missing_core))
        self.assertIn('core2', missing_core)
        missing_core = compute.APIRouterV21.get_missing_core_extensions([])
        self.assertEqual(2, len(missing_core))
        self.assertIn('core1', missing_core)
        self.assertIn('core2', missing_core)
        missing_core = compute.APIRouterV21.get_missing_core_extensions(
            ['noncore1'])
        self.assertEqual(2, len(missing_core))
        self.assertIn('core1', missing_core)
        self.assertIn('core2', missing_core)

    def test_core_extensions_present(self):
        self.stubs.Set(stevedore.enabled, 'EnabledExtensionManager',
                       fake_stevedore_enabled_extensions)
        self.stubs.Set(plugins, 'LoadedExtensionInfo',
                       fake_loaded_extension_info)
        v21_core = openstack.API_V3_CORE_EXTENSIONS
        openstack.API_V3_CORE_EXTENSIONS = set(['core1', 'core2'])
        self.addCleanup(self._set_v21_core, v21_core)
        # if no core API extensions are missing then an exception will
        # not be raised when creating an instance of compute.APIRouterV21
        compute.APIRouterV21()

    def test_core_extensions_missing(self):
        self.stubs.Set(stevedore.enabled, 'EnabledExtensionManager',
                       fake_stevedore_enabled_extensions)
        self.stubs.Set(plugins, 'LoadedExtensionInfo',
                       fake_loaded_extension_info)
        self.assertRaises(exception.CoreAPIMissing, compute.APIRouterV21)

    def test_extensions_expected_error(self):
        @extensions.expected_errors(404)
        def fake_func():
            raise webob.exc.HTTPNotFound()

        self.assertRaises(webob.exc.HTTPNotFound, fake_func)

    def test_extensions_expected_error_from_list(self):
        @extensions.expected_errors((404, 403))
        def fake_func():
            raise webob.exc.HTTPNotFound()

        self.assertRaises(webob.exc.HTTPNotFound, fake_func)

    def test_extensions_unexpected_error(self):
        @extensions.expected_errors(404)
        def fake_func():
            raise webob.exc.HTTPConflict()

        self.assertRaises(webob.exc.HTTPInternalServerError, fake_func)

    def test_extensions_unexpected_error_from_list(self):
        @extensions.expected_errors((404, 413))
        def fake_func():
            raise webob.exc.HTTPConflict()

        self.assertRaises(webob.exc.HTTPInternalServerError, fake_func)

    def test_extensions_unexpected_policy_not_authorized_error(self):
        @extensions.expected_errors(404)
        def fake_func():
            raise exception.PolicyNotAuthorized(action="foo")

        self.assertRaises(exception.PolicyNotAuthorized, fake_func)

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

import imp
import mock
import os
import sys

from nova import test
from nova.virt.xenapi.client import session


# both XenAPI and XenAPIPlugin may not exist
# in unit test environment.
sys.modules['XenAPI'] = mock.Mock()
sys.modules['XenAPIPlugin'] = mock.Mock()


class PluginTestBase(test.NoDBTestCase):
    def setUp(self):
        super(PluginTestBase, self).setUp()
        self.session = mock.Mock()
        session.apply_session_helpers(self.session)

    def mock_patch_object(self, target, attribute, return_val=None):
        # utilility function to mock object's attribute
        patcher = mock.patch.object(target, attribute, return_value=return_val)
        mock_one = patcher.start()
        self.addCleanup(patcher.stop)
        return mock_one

    def _get_plugin_path(self):
        current_path = os.path.realpath(__file__)
        rel_path = os.path.join(current_path,
            "../../../../../../../plugins/xenserver/xenapi/etc/xapi.d/plugins")
        plugin_path = os.path.abspath(rel_path)
        return plugin_path

    def load_plugin(self, file_name):
        # XAPI plugins run in a py24 environment and may be not compatible with
        # py34's syntax. In order to prevent unit test scanning the source file
        # under py34 environment, the plugins will be imported with this
        # function at run time.

        plugin_path = self._get_plugin_path()

        # add plugin path into search path.
        if plugin_path not in sys.path:
            sys.path.append(plugin_path)

        # be sure not to create c files next to the plugins
        sys.dont_write_bytecode = True

        name = file_name.split('.')[0]
        path = os.path.join(plugin_path, file_name)
        return imp.load_source(name, path)

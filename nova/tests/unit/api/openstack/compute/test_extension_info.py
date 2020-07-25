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

import webob

from nova.api.openstack.compute import extension_info
from nova import test
from nova.tests.unit.api.openstack import fakes


class ExtensionInfoV21Test(test.NoDBTestCase):

    def setUp(self):
        super(ExtensionInfoV21Test, self).setUp()
        self.controller = extension_info.ExtensionInfoController()

    def test_extension_info_show_servers_not_present(self):
        req = fakes.HTTPRequest.blank('/extensions/servers')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 'servers')

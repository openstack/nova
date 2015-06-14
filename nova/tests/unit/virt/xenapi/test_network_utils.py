
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

import mock

from nova import exception
from nova.tests.unit.virt.xenapi import stubs
from nova.virt.xenapi import network_utils


class NetworkUtilsTestCase(stubs.XenAPITestBaseNoDB):
    def test_find_network_with_name_label_works(self):
        session = mock.Mock()
        session.network.get_by_name_label.return_value = ["net"]

        result = network_utils.find_network_with_name_label(session, "label")

        self.assertEqual("net", result)
        session.network.get_by_name_label.assert_called_once_with("label")

    def test_find_network_with_name_returns_none(self):
        session = mock.Mock()
        session.network.get_by_name_label.return_value = []

        result = network_utils.find_network_with_name_label(session, "label")

        self.assertIsNone(result)

    def test_find_network_with_name_label_raises(self):
        session = mock.Mock()
        session.network.get_by_name_label.return_value = ["net", "net2"]

        self.assertRaises(exception.NovaException,
                          network_utils.find_network_with_name_label,
                          session, "label")

    def test_find_network_with_bridge_works(self):
        session = mock.Mock()
        session.network.get_all_records_where.return_value = {"net": "asdf"}

        result = network_utils.find_network_with_bridge(session, "bridge")

        self.assertEqual(result, "net")
        expr = 'field "name__label" = "bridge" or field "bridge" = "bridge"'
        session.network.get_all_records_where.assert_called_once_with(expr)

    def test_find_network_with_bridge_raises_too_many(self):
        session = mock.Mock()
        session.network.get_all_records_where.return_value = {
            "net": "asdf",
            "net2": "asdf2"
        }

        self.assertRaises(exception.NovaException,
                          network_utils.find_network_with_bridge,
                          session, "bridge")

    def test_find_network_with_bridge_raises_no_networks(self):
        session = mock.Mock()
        session.network.get_all_records_where.return_value = {}

        self.assertRaises(exception.NovaException,
                          network_utils.find_network_with_bridge,
                          session, "bridge")

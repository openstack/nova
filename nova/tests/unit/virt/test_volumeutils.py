# Copyright 2014 Hewlett-Packard Development Company, L.P.
# Copyright 2012 University Of Minho
# Copyright 2010 OpenStack Foundation
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
"""
Tests for virt volumeutils.
"""
import mock
from os_brick.initiator import connector

from nova import test
from nova.virt import volumeutils


class VolumeUtilsTestCase(test.NoDBTestCase):

    @mock.patch.object(connector.ISCSIConnector, 'get_initiator',
                       return_value='fake.initiator.iqn')
    def test_get_iscsi_initiator(self, fake_initiator):
        initiator = 'fake.initiator.iqn'
        # Start test
        result = volumeutils.get_iscsi_initiator()
        self.assertEqual(initiator, result)

    @mock.patch.object(connector.ISCSIConnector, 'get_initiator',
                       return_value=None)
    def test_get_missing_iscsi_initiator(self, fake_initiator):
        result = volumeutils.get_iscsi_initiator()
        self.assertIsNone(result)

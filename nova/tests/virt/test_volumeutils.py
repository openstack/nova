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
Tests fot virt volumeutils.
"""

from nova import exception
from nova import test
from nova import utils
from nova.virt import volumeutils


class VolumeUtilsTestCase(test.TestCase):
    def test_get_iscsi_initiator(self):
        self.mox.StubOutWithMock(utils, 'execute')
        initiator = 'fake.initiator.iqn'
        rval = ("junk\nInitiatorName=%s\njunk\n" % initiator, None)
        utils.execute('cat', '/etc/iscsi/initiatorname.iscsi',
                      run_as_root=True).AndReturn(rval)
        # Start test
        self.mox.ReplayAll()
        result = volumeutils.get_iscsi_initiator()
        self.assertEqual(initiator, result)

    def test_get_missing_iscsi_initiator(self):
        self.mox.StubOutWithMock(utils, 'execute')
        file_path = '/etc/iscsi/initiatorname.iscsi'
        utils.execute('cat', file_path, run_as_root=True).AndRaise(
            exception.FileNotFound(file_path=file_path)
        )
        # Start test
        self.mox.ReplayAll()
        result = volumeutils.get_iscsi_initiator()
        self.assertIsNone(result)

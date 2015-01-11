#    Copyright 2010 OpenStack Foundation
#    (c) Copyright 2012-2013 Hewlett-Packard Development Company, L.P.
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

from oslo_config import cfg

from nova.openstack.common import log as logging
from nova.storage import linuxscsi
from nova import test
from nova import utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class StorageLinuxSCSITestCase(test.NoDBTestCase):
    def setUp(self):
        super(StorageLinuxSCSITestCase, self).setUp()
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)

    def test_find_multipath_device_3par(self):
        def fake_execute(*cmd, **kwargs):
            out = ("mpath6 (350002ac20398383d) dm-3 3PARdata,VV\n"
                   "size=2.0G features='0' hwhandler='0' wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 0:0:0:1 sde 8:64 active undef running\n"
                   "  `- 2:0:0:1 sdf 8:80 active undef running\n"
                   )
            return out, None

        def fake_execute2(*cmd, **kwargs):
            out = ("350002ac20398383d dm-3 3PARdata,VV\n"
                   "size=2.0G features='0' hwhandler='0' wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 0:0:0:1  sde 8:64 active undef running\n"
                   "  `- 2:0:0:1  sdf 8:80 active undef running\n"
                   )
            return out, None

        self.stubs.Set(utils, 'execute', fake_execute)

        info = linuxscsi.find_multipath_device('/dev/sde')
        LOG.error("info = %s" % info)
        self.assertEqual("/dev/mapper/350002ac20398383d", info["device"])
        self.assertEqual("/dev/sde", info['devices'][0]['device'])
        self.assertEqual("0", info['devices'][0]['host'])
        self.assertEqual("0", info['devices'][0]['id'])
        self.assertEqual("0", info['devices'][0]['channel'])
        self.assertEqual("1", info['devices'][0]['lun'])

        self.assertEqual("/dev/sdf", info['devices'][1]['device'])
        self.assertEqual("2", info['devices'][1]['host'])
        self.assertEqual("0", info['devices'][1]['id'])
        self.assertEqual("0", info['devices'][1]['channel'])
        self.assertEqual("1", info['devices'][1]['lun'])

    def test_find_multipath_device_svc(self):
        def fake_execute(*cmd, **kwargs):
            out = ("36005076da00638089c000000000004d5 dm-2 IBM,2145\n"
                   "size=954M features='1 queue_if_no_path' hwhandler='0'"
                   " wp=rw\n"
                   "|-+- policy='round-robin 0' prio=-1 status=active\n"
                   "| |- 6:0:2:0 sde 8:64  active undef  running\n"
                   "| `- 6:0:4:0 sdg 8:96  active undef  running\n"
                   "`-+- policy='round-robin 0' prio=-1 status=enabled\n"
                   "  |- 6:0:3:0 sdf 8:80  active undef  running\n"
                   "  `- 6:0:5:0 sdh 8:112 active undef  running\n"
                   )
            return out, None

        self.stubs.Set(utils, 'execute', fake_execute)

        info = linuxscsi.find_multipath_device('/dev/sde')
        LOG.error("info = %s" % info)
        self.assertEqual("/dev/mapper/36005076da00638089c000000000004d5",
                         info["device"])
        self.assertEqual("/dev/sde", info['devices'][0]['device'])
        self.assertEqual("6", info['devices'][0]['host'])
        self.assertEqual("0", info['devices'][0]['channel'])
        self.assertEqual("2", info['devices'][0]['id'])
        self.assertEqual("0", info['devices'][0]['lun'])

        self.assertEqual("/dev/sdf", info['devices'][2]['device'])
        self.assertEqual("6", info['devices'][2]['host'])
        self.assertEqual("0", info['devices'][2]['channel'])
        self.assertEqual("3", info['devices'][2]['id'])
        self.assertEqual("0", info['devices'][2]['lun'])

    def test_find_multipath_device_ds8000(self):
        def fake_execute(*cmd, **kwargs):
            out = ("36005076303ffc48e0000000000000101 dm-2 IBM,2107900\n"
                   "size=1.0G features='1 queue_if_no_path' hwhandler='0'"
                   " wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 6:0:2:0  sdd 8:64  active undef  running\n"
                   "  `- 6:1:0:3  sdc 8:32  active undef  running\n"
                   )
            return out, None

        self.stubs.Set(utils, 'execute', fake_execute)

        info = linuxscsi.find_multipath_device('/dev/sdd')
        LOG.error("info = %s" % info)
        self.assertEqual("/dev/mapper/36005076303ffc48e0000000000000101",
                         info["device"])
        self.assertEqual("/dev/sdd", info['devices'][0]['device'])
        self.assertEqual("6", info['devices'][0]['host'])
        self.assertEqual("0", info['devices'][0]['channel'])
        self.assertEqual("2", info['devices'][0]['id'])
        self.assertEqual("0", info['devices'][0]['lun'])

        self.assertEqual("/dev/sdc", info['devices'][1]['device'])
        self.assertEqual("6", info['devices'][1]['host'])
        self.assertEqual("1", info['devices'][1]['channel'])
        self.assertEqual("0", info['devices'][1]['id'])
        self.assertEqual("3", info['devices'][1]['lun'])

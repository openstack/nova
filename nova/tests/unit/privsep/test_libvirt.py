# Copyright 2019 OpenStack Foundation
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

import ddt
import mock

import nova.privsep.libvirt
from nova import test


@ddt.ddt
class PrivsepLibvirtMountTestCase(test.NoDBTestCase):

    QB_BINARY = "mount.quobyte"
    QB_FIXED_OPT_1 = "--disable-xattrs"
    FAKE_VOLUME = "fake_volume"
    FAKE_MOUNT_BASE = "/fake/mount/base"

    def setUp(self):
        super(PrivsepLibvirtMountTestCase, self).setUp()
        self.useFixture(test.nova_fixtures.PrivsepFixture())

    @ddt.data(None, "/FAKE/CFG/PATH.cfg")
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_systemd_run_qb_mount(self, cfg_file, mock_execute):
        sysd_bin = "systemd-run"
        sysd_opt_1 = "--scope"

        nova.privsep.libvirt.systemd_run_qb_mount(self.FAKE_VOLUME,
                                                  self.FAKE_MOUNT_BASE,
                                                  cfg_file=cfg_file)

        if cfg_file:
            mock_execute.assert_called_once_with(sysd_bin, sysd_opt_1,
                                                 self.QB_BINARY,
                                                 self.QB_FIXED_OPT_1,
                                                 self.FAKE_VOLUME,
                                                 self.FAKE_MOUNT_BASE,
                                                 "-c",
                                                 cfg_file)
        else:
            mock_execute.assert_called_once_with(sysd_bin, sysd_opt_1,
                                                 self.QB_BINARY,
                                                 self.QB_FIXED_OPT_1,
                                                 self.FAKE_VOLUME,
                                                 self.FAKE_MOUNT_BASE)

    @ddt.data(None, "/FAKE/CFG/PATH.cfg")
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_unprivileged_qb_mount(self, cfg_file, mock_execute):

        nova.privsep.libvirt.unprivileged_qb_mount(self.FAKE_VOLUME,
                                                   self.FAKE_MOUNT_BASE,
                                                   cfg_file=cfg_file)

        if cfg_file:
            mock_execute.assert_called_once_with(self.QB_BINARY,
                                                 self.QB_FIXED_OPT_1,
                                                 self.FAKE_VOLUME,
                                                 self.FAKE_MOUNT_BASE,
                                                 "-c",
                                                 cfg_file)
        else:
            mock_execute.assert_called_once_with(self.QB_BINARY,
                                                 self.QB_FIXED_OPT_1,
                                                 self.FAKE_VOLUME,
                                                 self.FAKE_MOUNT_BASE)

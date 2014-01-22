# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 NTT Data
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

import os

from nova import test
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils


class LibvirtUtilsTestCase(test.NoDBTestCase):
    def test_get_disk_type(self):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
blah BLAH: bb
"""
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((example_output, ''))
        self.mox.ReplayAll()
        disk_type = libvirt_utils.get_disk_type(path)
        self.assertEqual(disk_type, 'raw')

    def test_logical_volume_size(self):
        executes = []

        def fake_execute(*cmd, **kwargs):
            executes.append(cmd)
            return 123456789, None

        expected_commands = [('blockdev', '--getsize64', '/dev/foo')]
        self.stubs.Set(utils, 'execute', fake_execute)
        size = libvirt_utils.logical_volume_size('/dev/foo')
        self.assertEqual(expected_commands, executes)
        self.assertEqual(size, 123456789)

    def test_list_rbd_volumes(self):
        conf = '/etc/ceph/fake_ceph.conf'
        pool = 'fake_pool'
        user = 'user'
        self.flags(images_rbd_ceph_conf=conf, group='libvirt')
        self.flags(rbd_user=user, group='libvirt')
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(libvirt_utils.utils,
                                 'execute')
        libvirt_utils.utils.execute('rbd', '-p', pool, 'ls', '--id',
                                    user,
                                    '--conf', conf).AndReturn(("Out", "Error"))
        self.mox.ReplayAll()

        libvirt_utils.list_rbd_volumes(pool)

        self.mox.VerifyAll()

    def test_remove_rbd_volumes(self):
        conf = '/etc/ceph/fake_ceph.conf'
        pool = 'fake_pool'
        user = 'user'
        names = ['volume1', 'volume2', 'volume3']
        self.flags(images_rbd_ceph_conf=conf, group='libvirt')
        self.flags(rbd_user=user, group='libvirt')
        fn = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(libvirt_utils.utils, 'execute')
        libvirt_utils.utils.execute('rbd', '-p', pool, 'rm', 'volume1',
                                    '--id', user, '--conf', conf, attempts=3,
                                    run_as_root=True)
        libvirt_utils.utils.execute('rbd', '-p', pool, 'rm', 'volume2',
                                    '--id', user, '--conf', conf, attempts=3,
                                    run_as_root=True)
        libvirt_utils.utils.execute('rbd', '-p', pool, 'rm', 'volume3',
                                    '--id', user, '--conf', conf, attempts=3,
                                    run_as_root=True)
        self.mox.ReplayAll()

        libvirt_utils.remove_rbd_volumes(pool, *names)

        self.mox.VerifyAll()

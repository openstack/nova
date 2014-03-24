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
import tempfile

import fixtures
from oslo.config import cfg

from nova.openstack.common import processutils
from nova import test
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF


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

    def test_lvm_clear(self):
        def fake_lvm_size(path):
            return lvm_size

        def fake_execute(*cmd, **kwargs):
            executes.append(cmd)

        self.stubs.Set(libvirt_utils, 'logical_volume_size', fake_lvm_size)
        self.stubs.Set(utils, 'execute', fake_execute)

        # Test the correct dd commands are run for various sizes
        lvm_size = 1
        executes = []
        expected_commands = [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v1',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v1')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1024
        executes = []
        expected_commands = [('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v2',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v2')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1025
        executes = []
        expected_commands = [('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v3',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        expected_commands += [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v3',
                               'seek=1024', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v3')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1048576
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v4',
                              'seek=0', 'count=1', 'oflag=direct')]
        libvirt_utils.clear_logical_volume('/dev/v4')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1048577
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v5',
                              'seek=0', 'count=1', 'oflag=direct')]
        expected_commands += [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v5',
                               'seek=1048576', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v5')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1234567
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v6',
                              'seek=0', 'count=1', 'oflag=direct')]
        expected_commands += [('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v6',
                               'seek=1024', 'count=181', 'conv=fdatasync')]
        expected_commands += [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v6',
                               'seek=1233920', 'count=647', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v6')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear_size limits the size
        lvm_size = 10485761
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v7',
                              'seek=0', 'count=1', 'oflag=direct')]
        libvirt_utils.clear_logical_volume('/dev/v7')
        self.assertEqual(expected_commands, executes)

        CONF.set_override('volume_clear_size', '2', 'libvirt')
        lvm_size = 1048576
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v9',
                              'seek=0', 'count=1', 'oflag=direct')]
        libvirt_utils.clear_logical_volume('/dev/v9')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear=shred
        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '0', 'libvirt')
        lvm_size = 1048576
        executes = []
        expected_commands = [('shred', '-n3', '-s1048576', '/dev/va')]
        libvirt_utils.clear_logical_volume('/dev/va')
        self.assertEqual(expected_commands, executes)

        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        lvm_size = 10485761
        executes = []
        expected_commands = [('shred', '-n3', '-s1048576', '/dev/vb')]
        libvirt_utils.clear_logical_volume('/dev/vb')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear=none does nothing
        CONF.set_override('volume_clear', 'none', 'libvirt')
        executes = []
        expected_commands = []
        libvirt_utils.clear_logical_volume('/dev/vc')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear=invalid falls back to the default 'zero'
        CONF.set_override('volume_clear', 'invalid', 'libvirt')
        lvm_size = 1
        executes = []
        expected_commands = [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/vd',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/vd')
        self.assertEqual(expected_commands, executes)

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

    def _test_copy_image(self, fake_execute, host):
        self.useFixture(fixtures.MonkeyPatch(
            'nova.utils.execute', fake_execute))
        src = tempfile.NamedTemporaryFile()
        dst = tempfile.NamedTemporaryFile()
        libvirt_utils.copy_image(src.name, dst.name, host)

    def test_copy_image_local_cp(self):
        def fake_execute(*args, **kwargs):
            self.assertTrue(args[0] == 'cp')

        self._test_copy_image(fake_execute, host=None)

    def test_copy_image_local_rsync(self):
        def fake_execute(*args, **kwargs):
            self.assertTrue(args[0] == 'rsync')

        self._test_copy_image(fake_execute, host='fake-host')

    def test_copy_image_local_scp(self):
        def fake_execute(*args, **kwargs):
            if args[0] == 'rsync':
                raise processutils.ProcessExecutionError("Bad result")
            self.assertTrue(args[0] == 'scp')

        self._test_copy_image(fake_execute, host='fake-host')

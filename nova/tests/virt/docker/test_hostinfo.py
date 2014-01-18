# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2013 dotCloud, Inc.
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

import posix

import mock

from nova import test
from nova.virt.docker import hostinfo


class HostInfoTestCase(test.NoDBTestCase):

    def setUp(self):
        super(HostInfoTestCase, self).setUp()
        hostinfo.get_meminfo = self.get_meminfo
        hostinfo.statvfs = self.statvfs

    def get_meminfo(self):
        data = ['MemTotal:        1018784 kB\n',
                'MemFree:          220060 kB\n',
                'Buffers:           21640 kB\n',
                'Cached:            63364 kB\n']
        return data

    def statvfs(self):
        seq = (4096, 4096, 10047582, 7332259, 6820195,
               2564096, 2271310, 2271310, 1024, 255)
        return posix.statvfs_result(sequence=seq)

    def test_get_disk_usage(self):
        disk_usage = hostinfo.get_disk_usage()
        self.assertEqual(disk_usage['total'], 41154895872)
        self.assertEqual(disk_usage['available'], 27935518720)
        self.assertEqual(disk_usage['used'], 11121963008)

    def test_parse_meminfo(self):
        meminfo = hostinfo.parse_meminfo()
        self.assertEqual(meminfo['memtotal'], 1043234816)
        self.assertEqual(meminfo['memfree'], 225341440)
        self.assertEqual(meminfo['cached'], 64884736)
        self.assertEqual(meminfo['buffers'], 22159360)

    def test_get_memory_usage(self):
        usage = hostinfo.get_memory_usage()
        self.assertEqual(usage['total'], 1043234816)
        self.assertEqual(usage['used'], 730849280)
        self.assertEqual(usage['free'], 312385536)

    @mock.patch('nova.virt.docker.hostinfo.get_mounts')
    def test_find_cgroup_devices_path_centos(self, mock):
        mock.return_value = [
            'none /sys/fs/cgroup cgroup rw,relatime,perf_event,'
                'blkio,net_cls,freezer,devices,memory,cpuacct,cpu,'
                'cpuset 0 0']
        path = hostinfo.get_cgroup_devices_path()
        self.assertEqual('/sys/fs/cgroup', path)

    @mock.patch('nova.virt.docker.hostinfo.get_mounts')
    def test_find_cgroup_devices_path_ubuntu(self, mock):
        mock.return_value = ['cgroup /cgroup tmpfs rw,relatime,mode=755 0 0',
                'cgroup /cgroup/devices cgroup rw,relatime,devices,' +
                'clone_children 0 0']
        path = hostinfo.get_cgroup_devices_path()
        self.assertEqual('/cgroup/devices', path)

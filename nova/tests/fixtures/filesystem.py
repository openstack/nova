# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os
import shutil
import tempfile
from unittest import mock

import fixtures

from nova import filesystem
from nova.virt.libvirt.cpu import core


SYS = 'sys'


class TempFileSystemFixture(fixtures.Fixture):
    """Creates a fake / filesystem"""

    def _setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='fake_fs')
        # NOTE(sbauza): I/O disk errors may raise an exception here, as we
        # don't ignore them. If that's causing a problem in our CI jobs, the
        # recommended solution is to use shutil.rmtree instead of cleanup()
        # with ignore_errors parameter set to True (or wait for the minimum
        # python version to be 3.10 as TemporaryDirectory will provide
        # ignore_cleanup_errors parameter)
        self.addCleanup(self.temp_dir.cleanup)


class SysFileSystemFixture(TempFileSystemFixture):
    """Creates a fake /sys filesystem"""

    def __init__(self, cpus_supported=None):
        self.cpus_supported = cpus_supported or 10

    def _setUp(self):
        super()._setUp()
        self.sys_path = os.path.join(self.temp_dir.name, SYS)
        self.addCleanup(shutil.rmtree, self.sys_path, ignore_errors=True)

        sys_patcher = mock.patch(
            'nova.filesystem.SYS',
            new_callable=mock.PropertyMock(return_value=self.sys_path))
        self.sys_mock = sys_patcher.start()
        self.addCleanup(sys_patcher.stop)

        avail_path_patcher = mock.patch(
            'nova.virt.libvirt.cpu.core.AVAILABLE_PATH',
            new_callable=mock.PropertyMock(
                return_value=os.path.join(self.sys_path,
                                          'devices/system/cpu/present')))
        self.avail_path_mock = avail_path_patcher.start()
        self.addCleanup(avail_path_patcher.stop)

        cpu_path_patcher = mock.patch(
            'nova.virt.libvirt.cpu.core.CPU_PATH_TEMPLATE',
            new_callable=mock.PropertyMock(
                return_value=os.path.join(self.sys_path,
                                          'devices/system/cpu/cpu%(core)s')))
        self.cpu_path_mock = cpu_path_patcher.start()
        self.addCleanup(cpu_path_patcher.stop)

        for cpu_nr in range(self.cpus_supported):
            cpu_dir = os.path.join(self.cpu_path_mock % {'core': cpu_nr})
            os.makedirs(os.path.join(cpu_dir, 'cpufreq'))
            filesystem.write_sys(
                os.path.join(cpu_dir, 'cpufreq/scaling_governor'),
                data='powersave')
        filesystem.write_sys(core.AVAILABLE_PATH,
                             f'0-{self.cpus_supported - 1}')

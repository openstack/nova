# Copyright 2014 Cloudbase Solutions Srl
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

import datetime

import mock
from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import units

from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import constants
from nova.virt.hyperv import hostops

CONF = cfg.CONF


class HostOpsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V HostOps class."""

    FAKE_ARCHITECTURE = 0
    FAKE_NAME = 'fake_name'
    FAKE_MANUFACTURER = 'FAKE_MANUFACTURER'
    FAKE_NUM_CPUS = 1
    FAKE_WIN_VERSION = '6.3.0'
    FAKE_INSTANCE_DIR = "C:/fake/dir"
    FAKE_LOCAL_IP = '10.11.12.13'
    FAKE_TICK_COUNT = 1000000

    def setUp(self):
        super(HostOpsTestCase, self).setUp()
        self._hostops = hostops.HostOps()
        self._hostops._hostutils = mock.MagicMock()
        self._hostops._pathutils = mock.MagicMock()

    def test_get_cpu_info(self):
        mock_processors = mock.MagicMock()
        info = {'Architecture': self.FAKE_ARCHITECTURE,
                'Name': self.FAKE_NAME,
                'Manufacturer': self.FAKE_MANUFACTURER,
                'NumberOfCores': self.FAKE_NUM_CPUS,
                'NumberOfLogicalProcessors': self.FAKE_NUM_CPUS}

        def getitem(key):
            return info[key]
        mock_processors.__getitem__.side_effect = getitem
        self._hostops._hostutils.get_cpus_info.return_value = [mock_processors]

        response = self._hostops._get_cpu_info()

        self._hostops._hostutils.get_cpus_info.assert_called_once_with()

        expected = [mock.call(fkey)
                    for fkey in constants.PROCESSOR_FEATURE.keys()]
        self._hostops._hostutils.is_cpu_feature_present.has_calls(expected)
        expected_response = self._get_mock_cpu_info()
        self.assertEqual(expected_response, response)

    def _get_mock_cpu_info(self):
        return {'vendor': self.FAKE_MANUFACTURER,
                'model': self.FAKE_NAME,
                'arch': constants.WMI_WIN32_PROCESSOR_ARCHITECTURE[
                    self.FAKE_ARCHITECTURE],
                'features': constants.PROCESSOR_FEATURE.values(),
                'topology': {'cores': self.FAKE_NUM_CPUS,
                             'threads': self.FAKE_NUM_CPUS,
                             'sockets': self.FAKE_NUM_CPUS}}

    def test_get_memory_info(self):
        self._hostops._hostutils.get_memory_info.return_value = (2 * units.Ki,
                                                                 1 * units.Ki)
        response = self._hostops._get_memory_info()
        self._hostops._hostutils.get_memory_info.assert_called_once_with()
        self.assertEqual((2, 1, 1), response)

    def test_get_local_hdd_info_gb(self):
        self._hostops._pathutils.get_instance_dir.return_value = ''
        self._hostops._hostutils.get_volume_info.return_value = (2 * units.Gi,
                                                                 1 * units.Gi)
        response = self._hostops._get_local_hdd_info_gb()
        self._hostops._pathutils.get_instances_dir.assert_called_once_with()
        self._hostops._hostutils.get_volume_info.assert_called_once_with('')
        self.assertEqual((2, 1, 1), response)

    def test_get_hypervisor_version(self):
        self._hostops._hostutils.get_windows_version.return_value = (
            self.FAKE_WIN_VERSION)
        response = self._hostops._get_hypervisor_version()
        self._hostops._hostutils.get_windows_version.assert_called_once_with()
        self.assertEqual(self.FAKE_WIN_VERSION.replace('.', ''), response)

    @mock.patch.object(hostops.HostOps, '_get_cpu_info')
    @mock.patch.object(hostops.HostOps, '_get_memory_info')
    @mock.patch.object(hostops.HostOps, '_get_hypervisor_version')
    @mock.patch.object(hostops.HostOps, '_get_local_hdd_info_gb')
    @mock.patch('platform.node')
    def test_get_available_resource(self, mock_node,
                                    mock_get_local_hdd_info_gb,
                                    mock_get_hypervisor_version,
                                    mock_get_memory_info, mock_get_cpu_info):
        mock_get_local_hdd_info_gb.return_value = (mock.sentinel.LOCAL_GB,
                                                   mock.sentinel.LOCAL_GB_FREE,
                                                   mock.sentinel.LOCAL_GB_USED)
        mock_get_memory_info.return_value = (mock.sentinel.MEMORY_MB,
                                             mock.sentinel.MEMORY_MB_FREE,
                                             mock.sentinel.MEMORY_MB_USED)
        mock_cpu_info = self._get_mock_cpu_info()
        mock_get_cpu_info.return_value = mock_cpu_info
        mock_get_hypervisor_version.return_value = mock.sentinel.VERSION

        response = self._hostops.get_available_resource()

        mock_get_memory_info.assert_called_once_with()
        mock_get_cpu_info.assert_called_once_with()
        mock_get_hypervisor_version.assert_called_once_with()
        expected = {'supported_instances': '[["i686", "hyperv", "hvm"], '
                                           '["x86_64", "hyperv", "hvm"]]',
                    'hypervisor_hostname': mock_node(),
                    'cpu_info': jsonutils.dumps(mock_cpu_info),
                    'hypervisor_version': mock.sentinel.VERSION,
                    'memory_mb': mock.sentinel.MEMORY_MB,
                    'memory_mb_used': mock.sentinel.MEMORY_MB_USED,
                    'local_gb': mock.sentinel.LOCAL_GB,
                    'local_gb_used': mock.sentinel.LOCAL_GB_USED,
                    'vcpus': self.FAKE_NUM_CPUS,
                    'vcpus_used': 0,
                    'hypervisor_type': 'hyperv',
                    'numa_topology': None,
                    }
        self.assertEqual(expected, response)

    def _test_host_power_action(self, action):
        self._hostops._hostutils.host_power_action = mock.Mock()

        self._hostops.host_power_action(action)
        self._hostops._hostutils.host_power_action.assert_called_with(
            action)

    def test_host_power_action_shutdown(self):
        self._test_host_power_action(constants.HOST_POWER_ACTION_SHUTDOWN)

    def test_host_power_action_reboot(self):
        self._test_host_power_action(constants.HOST_POWER_ACTION_REBOOT)

    def test_host_power_action_exception(self):
        self.assertRaises(NotImplementedError,
                          self._hostops.host_power_action,
                          constants.HOST_POWER_ACTION_STARTUP)

    def test_get_host_ip_addr(self):
        CONF.set_override('my_ip', None)
        self._hostops._hostutils.get_local_ips.return_value = [
            self.FAKE_LOCAL_IP]
        response = self._hostops.get_host_ip_addr()
        self._hostops._hostutils.get_local_ips.assert_called_once_with()
        self.assertEqual(self.FAKE_LOCAL_IP, response)

    @mock.patch('time.strftime')
    def test_get_host_uptime(self, mock_time):
        self._hostops._hostutils.get_host_tick_count64.return_value = (
            self.FAKE_TICK_COUNT)

        response = self._hostops.get_host_uptime()
        tdelta = datetime.timedelta(milliseconds=long(self.FAKE_TICK_COUNT))
        expected = "%s up %s,  0 users,  load average: 0, 0, 0" % (
                   str(mock_time()), str(tdelta))

        self.assertEqual(expected, response)

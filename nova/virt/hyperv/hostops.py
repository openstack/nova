# Copyright 2012 Cloudbase Solutions Srl
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

"""
Management class for host operations.
"""
import datetime
import os
import platform
import time

from os_win import constants as os_win_const
from os_win import utilsfactory
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import units

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import vm_mode
from nova.i18n import _
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')
LOG = logging.getLogger(__name__)


class HostOps(object):
    def __init__(self):
        self._hostutils = utilsfactory.get_hostutils()
        self._pathutils = pathutils.PathUtils()

    def _get_cpu_info(self):
        """Get the CPU information.
        :returns: A dictionary containing the main properties
        of the central processor in the hypervisor.
        """
        cpu_info = dict()

        processors = self._hostutils.get_cpus_info()

        w32_arch_dict = constants.WMI_WIN32_PROCESSOR_ARCHITECTURE
        cpu_info['arch'] = w32_arch_dict.get(processors[0]['Architecture'],
                                             'Unknown')
        cpu_info['model'] = processors[0]['Name']
        cpu_info['vendor'] = processors[0]['Manufacturer']

        topology = dict()
        topology['sockets'] = len(processors)
        topology['cores'] = processors[0]['NumberOfCores']
        topology['threads'] = (processors[0]['NumberOfLogicalProcessors'] //
                               processors[0]['NumberOfCores'])
        cpu_info['topology'] = topology

        features = list()
        for fkey, fname in os_win_const.PROCESSOR_FEATURE.items():
            if self._hostutils.is_cpu_feature_present(fkey):
                features.append(fname)
        cpu_info['features'] = features

        return cpu_info

    def _get_memory_info(self):
        (total_mem_kb, free_mem_kb) = self._hostutils.get_memory_info()
        total_mem_mb = total_mem_kb // 1024
        free_mem_mb = free_mem_kb // 1024
        return (total_mem_mb, free_mem_mb, total_mem_mb - free_mem_mb)

    def _get_local_hdd_info_gb(self):
        drive = os.path.splitdrive(self._pathutils.get_instances_dir())[0]
        (size, free_space) = self._hostutils.get_volume_info(drive)

        total_gb = size // units.Gi
        free_gb = free_space // units.Gi
        used_gb = total_gb - free_gb
        return (total_gb, free_gb, used_gb)

    def _get_hypervisor_version(self):
        """Get hypervisor version.
        :returns: hypervisor version (ex. 6003)
        """

        # NOTE(claudiub): The hypervisor_version will be stored in the database
        # as an Integer and it will be used by the scheduler, if required by
        # the image property 'hypervisor_version_requires'.
        # The hypervisor_version will then be converted back to a version
        # by splitting the int in groups of 3 digits.
        # E.g.: hypervisor_version 6003 is converted to '6.3'.
        version = self._hostutils.get_windows_version().split('.')
        version = int(version[0]) * 1000 + int(version[1])
        LOG.debug('Windows version: %s ', version)
        return version

    def get_available_resource(self):
        """Retrieve resource info.

        This method is called when nova-compute launches, and
        as part of a periodic task.

        :returns: dictionary describing resources

        """
        LOG.debug('get_available_resource called')

        (total_mem_mb,
         free_mem_mb,
         used_mem_mb) = self._get_memory_info()

        (total_hdd_gb,
         free_hdd_gb,
         used_hdd_gb) = self._get_local_hdd_info_gb()

        cpu_info = self._get_cpu_info()
        cpu_topology = cpu_info['topology']
        vcpus = (cpu_topology['sockets'] *
                 cpu_topology['cores'] *
                 cpu_topology['threads'])

        dic = {'vcpus': vcpus,
               'memory_mb': total_mem_mb,
               'memory_mb_used': used_mem_mb,
               'local_gb': total_hdd_gb,
               'local_gb_used': used_hdd_gb,
               'hypervisor_type': "hyperv",
               'hypervisor_version': self._get_hypervisor_version(),
               'hypervisor_hostname': platform.node(),
               'vcpus_used': 0,
               'cpu_info': jsonutils.dumps(cpu_info),
               'supported_instances':
                   [(arch.I686, hv_type.HYPERV, vm_mode.HVM),
                    (arch.X86_64, hv_type.HYPERV, vm_mode.HVM)],
               'numa_topology': None,
               }

        return dic

    def host_power_action(self, action):
        """Reboots, shuts down or powers up the host."""
        if action in [constants.HOST_POWER_ACTION_SHUTDOWN,
                      constants.HOST_POWER_ACTION_REBOOT]:
            self._hostutils.host_power_action(action)
        else:
            if action == constants.HOST_POWER_ACTION_STARTUP:
                raise NotImplementedError(
                    _("Host PowerOn is not supported by the Hyper-V driver"))

    def get_host_ip_addr(self):
        host_ip = CONF.my_ip
        if not host_ip:
            # Return the first available address
            host_ip = self._hostutils.get_local_ips()[0]
        LOG.debug("Host IP address is: %s", host_ip)
        return host_ip

    def get_host_uptime(self):
        """Returns the host uptime."""

        tick_count64 = self._hostutils.get_host_tick_count64()

        # format the string to match libvirt driver uptime
        # Libvirt uptime returns a combination of the following
        # - current host time
        # - time since host is up
        # - number of logged in users
        # - cpu load
        # Since the Windows function GetTickCount64 returns only
        # the time since the host is up, returning 0s for cpu load
        # and number of logged in users.
        # This is done to ensure the format of the returned
        # value is same as in libvirt
        return "%s up %s,  0 users,  load average: 0, 0, 0" % (
                   str(time.strftime("%H:%M:%S")),
                   str(datetime.timedelta(milliseconds=int(tick_count64))))

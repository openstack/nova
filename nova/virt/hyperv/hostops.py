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
import platform
import time

from os_win import constants as os_win_const
from os_win import utilsfactory
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import units

import nova.conf
from nova.i18n import _
from nova import objects
from nova.objects import fields as obj_fields
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class HostOps(object):
    def __init__(self):
        self._diskutils = utilsfactory.get_diskutils()
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

    def _get_storage_info_gb(self):
        instances_dir = self._pathutils.get_instances_dir()
        (size, free_space) = self._diskutils.get_disk_capacity(
            instances_dir)

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

    def _get_remotefx_gpu_info(self):
        total_video_ram = 0
        available_video_ram = 0

        if CONF.hyperv.enable_remotefx:
            gpus = self._hostutils.get_remotefx_gpu_info()
            for gpu in gpus:
                total_video_ram += int(gpu['total_video_ram'])
                available_video_ram += int(gpu['available_video_ram'])
        else:
            gpus = []

        return {'total_video_ram': total_video_ram,
                'used_video_ram': total_video_ram - available_video_ram,
                'gpu_info': jsonutils.dumps(gpus)}

    def _get_host_numa_topology(self):
        numa_nodes = self._hostutils.get_numa_nodes()
        cells = []
        for numa_node in numa_nodes:
            # Hyper-V does not support CPU pinning / mempages.
            # initializing the rest of the fields.
            numa_node.update(pinned_cpus=set(), mempages=[], siblings=[])
            cell = objects.NUMACell(**numa_node)
            cells.append(cell)

        return objects.NUMATopology(cells=cells)

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
         used_hdd_gb) = self._get_storage_info_gb()

        cpu_info = self._get_cpu_info()
        cpu_topology = cpu_info['topology']
        vcpus = (cpu_topology['sockets'] *
                 cpu_topology['cores'] *
                 cpu_topology['threads'])

        # NOTE(claudiub): free_hdd_gb only refers to the currently free
        # physical storage, it doesn't take into consideration the virtual
        # sizes of the VMs' dynamic disks. This means that the VMs' disks can
        # expand beyond the free_hdd_gb's value, and instances will still be
        # scheduled to this compute node.
        dic = {'vcpus': vcpus,
               'memory_mb': total_mem_mb,
               'memory_mb_used': used_mem_mb,
               'local_gb': total_hdd_gb,
               'local_gb_used': used_hdd_gb,
               'disk_available_least': free_hdd_gb,
               'hypervisor_type': "hyperv",
               'hypervisor_version': self._get_hypervisor_version(),
               'hypervisor_hostname': platform.node(),
               'vcpus_used': 0,
               'cpu_info': jsonutils.dumps(cpu_info),
               'supported_instances': [
                   (obj_fields.Architecture.I686,
                    obj_fields.HVType.HYPERV,
                    obj_fields.VMMode.HVM),
                   (obj_fields.Architecture.X86_64,
                    obj_fields.HVType.HYPERV,
                    obj_fields.VMMode.HVM)],
               'numa_topology': self._get_host_numa_topology()._to_json(),
               'pci_passthrough_devices': self._get_pci_passthrough_devices(),
               }

        gpu_info = self._get_remotefx_gpu_info()
        dic.update(gpu_info)
        return dic

    def _get_pci_passthrough_devices(self):
        """Get host PCI devices information.

        Obtains PCI devices information and returns it as a JSON string.

        :returns: a JSON string containing a list of the assignable PCI
                  devices information.
        """

        pci_devices = self._hostutils.get_pci_passthrough_devices()

        for pci_dev in pci_devices:
            # NOTE(claudiub): These fields are required by the PCI tracker.
            dev_label = 'label_%(vendor_id)s_%(product_id)s' % {
                'vendor_id': pci_dev['vendor_id'],
                'product_id': pci_dev['product_id']}

            # TODO(claudiub): Find a way to associate the PCI devices with
            # the NUMA nodes they are in.
            pci_dev.update(dev_type=obj_fields.PciDeviceType.STANDARD,
                           label=dev_label,
                           numa_node=None)

        return jsonutils.dumps(pci_devices)

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

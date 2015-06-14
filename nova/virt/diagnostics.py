# Copyright (c) 2014 VMware, Inc.
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

import six

from nova import exception
from nova.i18n import _


class CpuDiagnostics(object):

    def __init__(self, time=0):
        """Create a new CpuDiagnostics object

        :param time: CPU Time in nano seconds (Integer)
        """
        self.time = time


class NicDiagnostics(object):

    def __init__(self, mac_address='00:00:00:00:00:00',
                 rx_octets=0, rx_errors=0, rx_drop=0, rx_packets=0,
                 tx_octets=0, tx_errors=0, tx_drop=0, tx_packets=0):
        """Create a new NicDiagnostics object

        :param mac_address: Mac address of the interface (String)
        :param rx_octets: Received octets (Integer)
        :param rx_errors: Received errors (Integer)
        :param rx_drop: Received packets dropped (Integer)
        :param rx_packets: Received packets (Integer)
        :param tx_octets: Transmitted Octets (Integer)
        :param tx_errors: Transmit errors (Integer)
        :param tx_drop: Transmit dropped packets (Integer)
        :param tx_packets: Transmit packets (Integer)
        """
        self.mac_address = mac_address
        self.rx_octets = rx_octets
        self.rx_errors = rx_errors
        self.rx_drop = rx_drop
        self.rx_packets = rx_packets
        self.tx_octets = tx_octets
        self.tx_errors = tx_errors
        self.tx_drop = tx_drop
        self.tx_packets = tx_packets


class DiskDiagnostics(object):

    def __init__(self, id='', read_bytes=0, read_requests=0,
                 write_bytes=0, write_requests=0, errors_count=0):
        """Create a new DiskDiagnostics object

        :param id: Disk ID (String)
        :param read_bytes: Disk reads in bytes(Integer)
        :param read_requests: Read requests (Integer)
        :param write_bytes: Disk writes in bytes (Integer)
        :param write_requests: Write requests (Integer)
        :param errors_count: Disk errors (Integer)
        """
        self.id = id
        self.read_bytes = read_bytes
        self.read_requests = read_requests
        self.write_bytes = write_bytes
        self.write_requests = write_requests
        self.errors_count = errors_count


class MemoryDiagnostics(object):

    def __init__(self, maximum=0, used=0):
        """Create a new MemoryDiagnostics object

        :param maximum: Amount of memory provisioned for the VM in MB (Integer)
        :param used: Amount of memory used by the VM in MB (Integer)
        """
        self.maximum = maximum
        self.used = used


class Diagnostics(object):

    # Version 1.0: Initial version
    version = '1.0'

    def __init__(self, state=None, driver=None, hypervisor_os=None,
                 uptime=0, cpu_details=None, nic_details=None,
                 disk_details=None, config_drive=False):
        """Create a new diagnostics object

        :param state: The current state of the VM. Example values are:
                      'pending', 'running', 'paused', 'shutdown', 'crashed',
                      'suspended' and 'building' (String)
        :param driver: A string denoting the driver on which the VM is running.
                       Examples may be: 'libvirt', 'xenapi', 'hyperv' and
                       'vmwareapi' (String)
        :param hypervisor_os: A string denoting the hypervisor OS (String)
        :param uptime: The amount of time in seconds that the VM has been
                       running (Integer)
        :param cpu_details: And array of CpuDiagnostics or None.
        :param nic_details: And array of NicDiagnostics or None.
        :param disk_details: And array of DiskDiagnostics or None.
        :param config_drive: Indicates if the config drive is supported on the
                             instance (Boolean)
        """

        self.state = state
        self.driver = driver
        self.hypervisor_os = hypervisor_os
        self.uptime = uptime
        self.config_drive = config_drive
        if cpu_details:
            self._validate_type(cpu_details, CpuDiagnostics, 'cpu_details')
            self.cpu_details = cpu_details
        else:
            self.cpu_details = []
        if nic_details:
            self._validate_type(nic_details, NicDiagnostics, 'nic_details')
            self.nic_details = nic_details
        else:
            self.nic_details = []
        if disk_details:
            self._validate_type(disk_details, DiskDiagnostics, 'disk_details')
            self.disk_details = disk_details
        else:
            self.disk_details = []
        self.memory_details = MemoryDiagnostics()

    def _validate_type(self, input, type, str_input):
        if not isinstance(input, list):
            reason = _("Invalid type for %s") % str_input
            raise exception.InvalidInput(reason=reason)
        for i in input:
            if not isinstance(i, type):
                reason = _("Invalid type for %s entry") % str_input
                raise exception.InvalidInput(reason=reason)

    def add_cpu(self, time=0):
        self.cpu_details.append(CpuDiagnostics(time=time))

    def add_nic(self, mac_address='00:00:00:00:00:00',
                rx_octets=0, rx_errors=0, rx_drop=0, rx_packets=0,
                tx_octets=0, tx_errors=0, tx_drop=0, tx_packets=0):
        self.nic_details.append(NicDiagnostics(mac_address=mac_address,
                                               rx_octets=rx_octets,
                                               rx_errors=rx_errors,
                                               rx_drop=rx_drop,
                                               rx_packets=rx_packets,
                                               tx_octets=tx_octets,
                                               tx_errors=tx_errors,
                                               tx_drop=tx_drop,
                                               tx_packets=tx_packets))

    def add_disk(self, id='', read_bytes=0, read_requests=0,
                 write_bytes=0, write_requests=0, errors_count=0):
        self.disk_details.append(DiskDiagnostics(id=id,
                                                 read_bytes=read_bytes,
                                                 read_requests=read_requests,
                                                 write_bytes=write_bytes,
                                                 write_requests=write_requests,
                                                 errors_count=errors_count))

    def serialize(self):
        s = {}
        for k, v in six.iteritems(self.__dict__):
            # Treat case of CpuDiagnostics, NicDiagnostics and
            # DiskDiagnostics - these are lists
            if isinstance(v, list):
                l = []
                for value in v:
                    l.append(value.__dict__)
                s[k] = l
            # Treat case of MemoryDiagnostics
            elif isinstance(v, MemoryDiagnostics):
                s[k] = v.__dict__
            else:
                s[k] = v
        s['version'] = self.version
        return s

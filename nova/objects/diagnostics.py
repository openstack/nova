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

from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class CpuDiagnostics(base.NovaObject):

    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(nullable=True),
        'time': fields.IntegerField(nullable=True),
        'utilisation': fields.IntegerField(nullable=True),
    }


@base.NovaObjectRegistry.register
class NicDiagnostics(base.NovaObject):

    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'mac_address': fields.MACAddressField(nullable=True),
        'rx_octets': fields.IntegerField(nullable=True),
        'rx_errors': fields.IntegerField(nullable=True),
        'rx_drop': fields.IntegerField(nullable=True),
        'rx_packets': fields.IntegerField(nullable=True),
        'rx_rate': fields.IntegerField(nullable=True),
        'tx_octets': fields.IntegerField(nullable=True),
        'tx_errors': fields.IntegerField(nullable=True),
        'tx_drop': fields.IntegerField(nullable=True),
        'tx_packets': fields.IntegerField(nullable=True),
        'tx_rate': fields.IntegerField(nullable=True)
    }


@base.NovaObjectRegistry.register
class DiskDiagnostics(base.NovaObject):

    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'read_bytes': fields.IntegerField(nullable=True),
        'read_requests': fields.IntegerField(nullable=True),
        'write_bytes': fields.IntegerField(nullable=True),
        'write_requests': fields.IntegerField(nullable=True),
        'errors_count': fields.IntegerField(nullable=True)
    }


@base.NovaObjectRegistry.register
class MemoryDiagnostics(base.NovaObject):

    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'maximum': fields.IntegerField(nullable=True),
        'used': fields.IntegerField(nullable=True)
    }


@base.NovaObjectRegistry.register
class Diagnostics(base.NovaObject):

    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'state': fields.InstancePowerStateField(),
        'driver': fields.HypervisorDriverField(),
        'hypervisor': fields.StringField(nullable=True),
        'hypervisor_os': fields.StringField(nullable=True),
        'uptime': fields.IntegerField(nullable=True),
        'config_drive': fields.BooleanField(),
        'memory_details': fields.ObjectField('MemoryDiagnostics',
                                             default=MemoryDiagnostics()),
        'cpu_details': fields.ListOfObjectsField('CpuDiagnostics', default=[]),
        'nic_details': fields.ListOfObjectsField('NicDiagnostics', default=[]),
        'disk_details': fields.ListOfObjectsField('DiskDiagnostics',
                                                  default=[]),
        'num_cpus': fields.IntegerField(),
        'num_nics': fields.IntegerField(),
        'num_disks': fields.IntegerField()
    }

    def __init__(self, *args, **kwargs):
        super(Diagnostics, self).__init__(*args, **kwargs)
        self.obj_set_defaults()

        self.num_cpus = len(self.cpu_details)
        self.num_nics = len(self.nic_details)
        self.num_disks = len(self.disk_details)

    def add_cpu(self, id=None, time=None, utilisation=None):
        """Add a new CpuDiagnostics object

        :param id: The virtual cpu number (Integer)
        :param time: CPU Time in nano seconds (Integer)
        :param utilisation: CPU utilisation in percentages (Integer)
        """

        self.num_cpus += 1
        self.cpu_details.append(
            CpuDiagnostics(id=id, time=time, utilisation=utilisation))

    def add_nic(self, mac_address=None, rx_octets=None, rx_errors=None,
                rx_drop=None, rx_packets=None, rx_rate=None, tx_octets=None,
                tx_errors=None, tx_drop=None, tx_packets=None, tx_rate=None):
        """Add a new NicDiagnostics object

        :param mac_address: Mac address of the interface (String)
        :param rx_octets: Received octets (Integer)
        :param rx_errors: Received errors (Integer)
        :param rx_drop: Received packets dropped (Integer)
        :param rx_packets: Received packets (Integer)
        :param rx_rate: Receive rate (Integer)
        :param tx_octets: Transmitted Octets (Integer)
        :param tx_errors: Transmit errors (Integer)
        :param tx_drop: Transmit dropped packets (Integer)
        :param tx_packets: Transmit packets (Integer)
        :param tx_rate: Transmit rate (Integer)
        """

        self.num_nics += 1
        self.nic_details.append(NicDiagnostics(mac_address=mac_address,
                                               rx_octets=rx_octets,
                                               rx_errors=rx_errors,
                                               rx_drop=rx_drop,
                                               rx_packets=rx_packets,
                                               rx_rate=rx_rate,
                                               tx_octets=tx_octets,
                                               tx_errors=tx_errors,
                                               tx_drop=tx_drop,
                                               tx_packets=tx_packets,
                                               tx_rate=tx_rate))

    def add_disk(self, read_bytes=None, read_requests=None, write_bytes=None,
                 write_requests=None, errors_count=None):
        """Create a new DiskDiagnostics object

        :param read_bytes: Disk reads in bytes(Integer)
        :param read_requests: Read requests (Integer)
        :param write_bytes: Disk writes in bytes (Integer)
        :param write_requests: Write requests (Integer)
        :param errors_count: Disk errors (Integer)
        """

        self.num_disks += 1
        self.disk_details.append(DiskDiagnostics(read_bytes=read_bytes,
                                                 read_requests=read_requests,
                                                 write_bytes=write_bytes,
                                                 write_requests=write_requests,
                                                 errors_count=errors_count))

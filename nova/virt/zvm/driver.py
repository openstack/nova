# Copyright 2017,2018 IBM Corp.
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

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import conf
from nova import exception
from nova.i18n import _
from nova.objects import fields as obj_fields
from nova.virt import driver
from nova.virt.zvm import hypervisor


LOG = logging.getLogger(__name__)
CONF = conf.CONF


class ZVMDriver(driver.ComputeDriver):
    """z/VM implementation of ComputeDriver."""

    def __init__(self, virtapi):
        super(ZVMDriver, self).__init__(virtapi)

        if not CONF.zvm.cloud_connector_url:
            error = _('Must specify cloud_connector_url in zvm config '
                      'group to use compute_driver=zvm.driver.ZVMDriver')
            raise exception.ZVMDriverException(error=error)

        self._hypervisor = hypervisor.Hypervisor(
            CONF.zvm.cloud_connector_url, ca_file=CONF.zvm.ca_file)

        LOG.info("The zVM compute driver has been initialized.")

    def init_host(self, host):
        pass

    def list_instances(self):
        return self._hypervisor.list_names()

    def get_available_resource(self, nodename=None):
        host_stats = self._hypervisor.get_available_resource()

        hypervisor_hostname = self._hypervisor.get_available_nodes()[0]
        res = {
            'vcpus': host_stats.get('vcpus', 0),
            'memory_mb': host_stats.get('memory_mb', 0),
            'local_gb': host_stats.get('disk_total', 0),
            'vcpus_used': host_stats.get('vcpus_used', 0),
            'memory_mb_used': host_stats.get('memory_mb_used', 0),
            'local_gb_used': host_stats.get('disk_used', 0),
            'hypervisor_type': host_stats.get('hypervisor_type',
                                              obj_fields.HVType.ZVM),
            'hypervisor_version': host_stats.get('hypervisor_version', ''),
            'hypervisor_hostname': host_stats.get('hypervisor_hostname',
                                                  hypervisor_hostname),
            'cpu_info': jsonutils.dumps(host_stats.get('cpu_info', {})),
            'disk_available_least': host_stats.get('disk_available', 0),
            'supported_instances': [(obj_fields.Architecture.S390X,
                                     obj_fields.HVType.ZVM,
                                     obj_fields.VMMode.HVM)],
            'numa_topology': None,
        }

        LOG.debug("Getting available resource for %(host)s:%(nodename)s",
                  {'host': CONF.host, 'nodename': nodename})

        return res

    def get_available_nodes(self, refresh=False):
        return self._hypervisor.get_available_nodes(refresh=refresh)

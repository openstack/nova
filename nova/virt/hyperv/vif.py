# Copyright 2013 Cloudbase Solutions Srl
# Copyright 2013 Pedro Navarro Perez
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

import abc

from oslo_config import cfg

from nova.openstack.common import log as logging
from nova.virt.hyperv import utilsfactory

hyperv_opts = [
    cfg.StrOpt('vswitch_name',
               help='External virtual switch Name, '
                    'if not provided, the first external virtual '
                    'switch is used'),
]

CONF = cfg.CONF
CONF.register_opts(hyperv_opts, 'hyperv')

LOG = logging.getLogger(__name__)


class HyperVBaseVIFDriver(object):
    @abc.abstractmethod
    def plug(self, instance, vif):
        pass

    @abc.abstractmethod
    def unplug(self, instance, vif):
        pass


class HyperVNeutronVIFDriver(HyperVBaseVIFDriver):
    """Neutron VIF driver."""

    def plug(self, instance, vif):
        # Neutron takes care of plugging the port
        pass

    def unplug(self, instance, vif):
        # Neutron takes care of unplugging the port
        pass


class HyperVNovaNetworkVIFDriver(HyperVBaseVIFDriver):
    """Nova network VIF driver."""

    def __init__(self):
        self._vmutils = utilsfactory.get_vmutils()
        self._netutils = utilsfactory.get_networkutils()

    def plug(self, instance, vif):
        vswitch_path = self._netutils.get_external_vswitch(
            CONF.hyperv.vswitch_name)

        vm_name = instance['name']
        LOG.debug('Creating vswitch port for instance: %s', vm_name)
        if self._netutils.vswitch_port_needed():
            vswitch_data = self._netutils.create_vswitch_port(vswitch_path,
                                                              vm_name)
        else:
            vswitch_data = vswitch_path

        self._vmutils.set_nic_connection(vm_name, vif['id'], vswitch_data)

    def unplug(self, instance, vif):
        # TODO(alepilotti) Not implemented
        pass

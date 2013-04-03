# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

from oslo.config import cfg

from nova.openstack.common import log as logging
from nova.virt.hyperv import networkutils
from nova.virt.hyperv import vmutils

hyperv_opts = [
    cfg.StrOpt('vswitch_name',
               default=None,
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


class HyperVQuantumVIFDriver(HyperVBaseVIFDriver):
    """Quantum VIF driver."""

    def plug(self, instance, vif):
        # Quantum takes care of plugging the port
        pass

    def unplug(self, instance, vif):
        # Quantum takes care of unplugging the port
        pass


class HyperVNovaNetworkVIFDriver(HyperVBaseVIFDriver):
    """Nova network VIF driver."""

    def __init__(self):
        self._vmutils = vmutils.VMUtils()
        self._netutils = networkutils.NetworkUtils()

    def plug(self, instance, vif):
        vswitch_path = self._netutils.get_external_vswitch(
            CONF.hyperv.vswitch_name)

        vm_name = instance['name']
        LOG.debug(_('Creating vswitch port for instance: %s') % vm_name)
        vswitch_port = self._netutils.create_vswitch_port(vswitch_path,
                                                          vm_name)
        self._vmutils.set_nic_connection(vm_name, vif['id'], vswitch_port)

    def unplug(self, instance, vif):
        #TODO(alepilotti) Not implemented
        pass

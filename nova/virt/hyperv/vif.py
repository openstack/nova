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
import sys
import uuid

# Check needed for unit testing on Unix
if sys.platform == 'win32':
    import wmi


from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.virt.hyperv import vmutils


hyperv_opts = [
    cfg.StrOpt('vswitch_name',
               default=None,
               help='External virtual switch Name, '
                    'if not provided, the first external virtual '
                    'switch is used'),
]

CONF = cfg.CONF
CONF.register_opts(hyperv_opts)

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
        self._conn = wmi.WMI(moniker='//./root/virtualization')

    def _find_external_network(self):
        """Find the vswitch that is connected to the physical nic.
           Assumes only one physical nic on the host
        """
        #If there are no physical nics connected to networks, return.
        LOG.debug(_("Attempting to bind NIC to %s ")
                  % CONF.vswitch_name)
        if CONF.vswitch_name:
            LOG.debug(_("Attempting to bind NIC to %s ")
                      % CONF.vswitch_name)
            bound = self._conn.Msvm_VirtualSwitch(
                ElementName=CONF.vswitch_name)
        else:
            LOG.debug(_("No vSwitch specified, attaching to default"))
            self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')
        if len(bound) == 0:
            return None
        if CONF.vswitch_name:
            return self._conn.Msvm_VirtualSwitch(
                ElementName=CONF.vswitch_name)[0]\
                .associators(wmi_result_class='Msvm_SwitchPort')[0]\
                .associators(wmi_result_class='Msvm_VirtualSwitch')[0]
        else:
            return self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')\
                .associators(wmi_result_class='Msvm_SwitchPort')[0]\
                .associators(wmi_result_class='Msvm_VirtualSwitch')[0]

    def plug(self, instance, vif):
        extswitch = self._find_external_network()
        if extswitch is None:
            raise vmutils.HyperVException(_('Cannot find vSwitch'))

        vm_name = instance['name']

        nic_data = self._conn.Msvm_SyntheticEthernetPortSettingData(
            ElementName=vif['id'])[0]

        switch_svc = self._conn.Msvm_VirtualSwitchManagementService()[0]
        #Create a port on the vswitch.
        (new_port, ret_val) = switch_svc.CreateSwitchPort(
            Name=str(uuid.uuid4()),
            FriendlyName=vm_name,
            ScopeOfResidence="",
            VirtualSwitch=extswitch.path_())
        if ret_val != 0:
            LOG.error(_('Failed creating a port on the external vswitch'))
            raise vmutils.HyperVException(_('Failed creating port for %s') %
                                          vm_name)
        ext_path = extswitch.path_()
        LOG.debug(_("Created switch port %(vm_name)s on switch %(ext_path)s")
                  % locals())

        vms = self._conn.MSVM_ComputerSystem(ElementName=vm_name)
        vm = vms[0]

        nic_data.Connection = [new_port]
        self._vmutils.modify_virt_resource(self._conn, nic_data, vm)

    def unplug(self, instance, vif):
        #TODO(alepilotti) Not implemented
        pass

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

"""VIF drivers for VMware."""

from oslo_log import log as logging
from oslo_utils import versionutils
from oslo_vmware import vim_util

import nova.conf
from nova import exception
from nova.i18n import _
from nova.network import model
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import network_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF


def _get_associated_vswitch_for_interface(session, interface, cluster=None):
    # Check if the physical network adapter exists on the host.
    if not network_util.check_if_vlan_interface_exists(session,
                                        interface, cluster):
        raise exception.NetworkAdapterNotFound(adapter=interface)
    # Get the vSwitch associated with the Physical Adapter
    vswitch_associated = network_util.get_vswitch_for_vlan_interface(
                                    session, interface, cluster)
    if not vswitch_associated:
        raise exception.SwitchNotFoundForNetworkAdapter(adapter=interface)
    return vswitch_associated


def ensure_vlan_bridge(session, vif, cluster=None, create_vlan=True):
    """Create a vlan and bridge unless they already exist."""
    vlan_num = vif['network'].get_meta('vlan')
    bridge = vif['network']['bridge']
    vlan_interface = CONF.vmware.vlan_interface

    network_ref = network_util.get_network_with_the_name(session, bridge,
                                                         cluster)
    if network_ref and network_ref['type'] == 'DistributedVirtualPortgroup':
        return network_ref

    if not network_ref:
        # Create a port group on the vSwitch associated with the
        # vlan_interface corresponding physical network adapter on the ESX
        # host.
        vswitch_associated = _get_associated_vswitch_for_interface(session,
                                 vlan_interface, cluster)
        network_util.create_port_group(session, bridge,
                                       vswitch_associated,
                                       vlan_num if create_vlan else 0,
                                       cluster)
        network_ref = network_util.get_network_with_the_name(session,
                                                             bridge,
                                                             cluster)
    elif create_vlan:
        # Get the vSwitch associated with the Physical Adapter
        vswitch_associated = _get_associated_vswitch_for_interface(session,
                                 vlan_interface, cluster)
        # Get the vlan id and vswitch corresponding to the port group
        _get_pg_info = network_util.get_vlanid_and_vswitch_for_portgroup
        pg_vlanid, pg_vswitch = _get_pg_info(session, bridge, cluster)

        # Check if the vswitch associated is proper
        if pg_vswitch != vswitch_associated:
            raise exception.InvalidVLANPortGroup(
                bridge=bridge, expected=vswitch_associated,
                actual=pg_vswitch)

        # Check if the vlan id is proper for the port group
        if pg_vlanid != vlan_num:
            raise exception.InvalidVLANTag(bridge=bridge, tag=vlan_num,
                                           pgroup=pg_vlanid)
    return network_ref


def _check_ovs_supported_version(session):
    # The port type 'ovs' is only support by the VC version 5.5 onwards
    min_version = versionutils.convert_version_to_int(
        constants.MIN_VC_OVS_VERSION)
    vc_version = versionutils.convert_version_to_int(
        vim_util.get_vc_version(session))
    if vc_version < min_version:
        LOG.warning('VMware vCenter version less than %(version)s '
                    'does not support the \'ovs\' port type.',
                    {'version': constants.MIN_VC_OVS_VERSION})


def _get_neutron_network(session, cluster, vif):
    if vif['type'] == model.VIF_TYPE_OVS:
        _check_ovs_supported_version(session)
        # Check if this is the NSX-MH plugin is used
        if CONF.vmware.integration_bridge:
            net_id = CONF.vmware.integration_bridge
            use_external_id = False
            network_type = 'opaque'
        else:
            # The NSX|V3 plugin will pass the nsx-logical-switch-id as part
            # of the port details. This will enable the VC to connect to
            # that specific opaque network
            net_id = (vif.get('details') and
                      vif['details'].get('nsx-logical-switch-id'))
            if not net_id:
                # Make use of the original one, in the event that the
                # plugin does not pass the aforementioned id
                LOG.info('NSX Logical switch ID is not present. '
                         'Using network ID to attach to the '
                         'opaque network.')
                net_id = vif['network']['id']
            use_external_id = True
            network_type = 'nsx.LogicalSwitch'
        network_ref = {'type': 'OpaqueNetwork',
                       'network-id': net_id,
                       'network-type': network_type,
                       'use-external-id': use_external_id}
    elif vif['type'] == model.VIF_TYPE_DVS:
        # Port binding for DVS VIF types may pass the name
        # of the port group, so use it if present
        network_id = vif.get('details', {}).get('dvs_port_group_name')
        if network_id is None:
            # Make use of the original one, in the event that the
            # port binding does not provide this key in VIF details
            network_id = vif['network']['bridge']
        network_ref = network_util.get_network_with_the_name(
                session, network_id, cluster)
        if not network_ref:
            # We may have a provider network for a portgroup. The portgroup
            # will have the same name as the network 'label'. This is enforced
            # when the provider network is created
            network_id = vif['network']['label']
            network_ref = network_util.get_network_with_the_name(
                    session, network_id, cluster)
        if not network_ref:
            raise exception.NetworkNotFoundForBridge(bridge=network_id)
        if vif.get('details') and vif['details'].get('dvs_port_key'):
            network_ref['dvs_port_key'] = vif['details']['dvs_port_key']
    else:
        reason = _('vif type %s not supported') % vif['type']
        raise exception.InvalidInput(reason=reason)
    return network_ref


def get_network_ref(session, cluster, vif, is_neutron):
    if is_neutron:
        network_ref = _get_neutron_network(session, cluster, vif)
    else:
        create_vlan = vif['network'].get_meta('should_create_vlan', False)
        network_ref = ensure_vlan_bridge(session, vif, cluster=cluster,
                                         create_vlan=create_vlan)
    return network_ref


def get_vif_dict(session, cluster, vif_model, is_neutron, vif):
    mac = vif['address']
    name = vif['network']['bridge'] or CONF.vmware.integration_bridge
    ref = get_network_ref(session, cluster, vif, is_neutron)
    return {'network_name': name,
            'mac_address': mac,
            'network_ref': ref,
            'iface_id': vif['id'],
            'vif_model': vif_model}


def get_vif_info(session, cluster, is_neutron, vif_model, network_info):
    vif_infos = []
    if network_info is None:
        return vif_infos
    for vif in network_info:
        vif_infos.append(get_vif_dict(session, cluster, vif_model,
                         is_neutron, vif))
    return vif_infos


def get_network_device(hardware_devices, mac_address):
    """Return the network device with MAC 'mac_address'."""
    if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
        hardware_devices = hardware_devices.VirtualDevice
    for device in hardware_devices:
        if device.__class__.__name__ in vm_util.ALL_SUPPORTED_NETWORK_DEVICES:
            if hasattr(device, 'macAddress'):
                if device.macAddress == mac_address:
                    return device

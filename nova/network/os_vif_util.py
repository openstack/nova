# Copyright 2016 Red Hat, Inc.
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

'''
This module contains code for converting from the original
nova.network.model data structure, to the new os-vif based
versioned object model os_vif.objects.*
'''

from os_vif import objects
from oslo_config import cfg
from oslo_log import log as logging

from nova import exception
from nova.i18n import _
from nova.network import model


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

LEGACY_VIFS = {
    model.VIF_TYPE_DVS, model.VIF_TYPE_IOVISOR, model.VIF_TYPE_802_QBG,
    model.VIF_TYPE_802_QBH, model.VIF_TYPE_HW_VEB, model.VIF_TYPE_HOSTDEV,
    model.VIF_TYPE_IB_HOSTDEV, model.VIF_TYPE_MIDONET, model.VIF_TYPE_TAP,
    model.VIF_TYPE_MACVTAP
}


def _get_vif_name(vif):
    """Get a VIF device name

    :param vif: the nova.network.model.VIF instance

    Get a string suitable for use as a host OS network
    device name

    :returns: a device name
    """

    if vif.get('devname', None) is not None:
        return vif['devname']
    return ('nic' + vif['id'])[:model.NIC_NAME_LEN]


def _get_hybrid_bridge_name(vif):
    """Get a bridge device name

    :param vif: the nova.network.model.VIF instance

    Get a string suitable for use as a host OS bridge
    device name

    :returns: a bridge name
    """

    return ('qbr' + vif['id'])[:model.NIC_NAME_LEN]


def _set_vhostuser_settings(vif, obj):
    """Set vhostuser socket mode and path

    :param vif: the nova.network.model.VIF instance
    :param obj: a os_vif.objects.vif.VIFVHostUser instance

    :raises: exception.VifDetailsMissingVhostuserSockPath
    """

    obj.mode = vif['details'].get(
        model.VIF_DETAILS_VHOSTUSER_MODE, 'server')
    path = vif['details'].get(
        model.VIF_DETAILS_VHOSTUSER_SOCKET, None)
    if path:
        obj.path = path
    else:
        raise exception.VifDetailsMissingVhostuserSockPath(
            vif_id=vif['id'])


def nova_to_osvif_instance(instance):
    """Convert a Nova instance object to an os-vif instance object

    :param vif: a nova.objects.Instance instance

    :returns: a os_vif.objects.instance_info.InstanceInfo
    """

    info = objects.instance_info.InstanceInfo(
        uuid=instance.uuid,
        name=instance.name)

    if (instance.obj_attr_is_set("project_id") and
            instance.project_id is not None):
        info.project_id = instance.project_id

    return info


def _nova_to_osvif_ip(ip):
    """Convert Nova IP object into os_vif object

    :param route: nova.network.model.IP instance

    :returns: os_vif.objects.fixed_ip.FixedIP instance
    """
    floating_ips = [fip['address'] for fip in ip.get('floating_ips', [])]
    return objects.fixed_ip.FixedIP(
        address=ip['address'],
        floating_ips=floating_ips)


def _nova_to_osvif_ips(ips):
    """Convert Nova IP list into os_vif object

    :param routes: list of nova.network.model.IP instances

    :returns: os_vif.objects.fixed_ip.FixedIPList instance
    """

    return objects.fixed_ip.FixedIPList(
        objects=[_nova_to_osvif_ip(ip) for ip in ips])


def _nova_to_osvif_route(route):
    """Convert Nova route object into os_vif object

    :param route: nova.network.model.Route instance

    :returns: os_vif.objects.route.Route instance
    """

    obj = objects.route.Route(
        cidr=route['cidr'])

    if route['interface'] is not None:
        obj.interface = route['interface']

    if (route['gateway'] is not None and
        route['gateway']['address'] is not None):
        obj.gateway = route['gateway']['address']

    return obj


def _nova_to_osvif_routes(routes):
    """Convert Nova route list into os_vif object

    :param routes: list of nova.network.model.Route instances

    :returns: os_vif.objects.route.RouteList instance
    """

    return objects.route.RouteList(
        objects=[_nova_to_osvif_route(route) for route in routes])


def _nova_to_osvif_subnet(subnet):
    """Convert Nova subnet object into os_vif object

    :param subnet: nova.network.model.Subnet instance

    :returns: os_vif.objects.subnet.Subnet instance
    """

    dnsaddrs = [ip['address'] for ip in subnet['dns']]

    obj = objects.subnet.Subnet(
        dns=dnsaddrs,
        ips=_nova_to_osvif_ips(subnet['ips']),
        routes=_nova_to_osvif_routes(subnet['routes']))
    if subnet['cidr'] is not None:
        obj.cidr = subnet['cidr']
    if (subnet['gateway'] is not None and
        subnet['gateway']['address'] is not None):
        obj.gateway = subnet['gateway']['address']
    return obj


def _nova_to_osvif_subnets(subnets):
    """Convert Nova subnet list into os_vif object

    :param subnets: list of nova.network.model.Subnet instances

    :returns: os_vif.objects.subnet.SubnetList instance
    """

    return objects.subnet.SubnetList(
        objects=[_nova_to_osvif_subnet(subnet) for subnet in subnets])


def _nova_to_osvif_network(network):
    """Convert Nova network object into os_vif object

    :param network: nova.network.model.Network instance

    :returns: os_vif.objects.network.Network instance
    """

    netobj = objects.network.Network(
        id=network['id'],
        bridge_interface=network.get_meta("bridge_interface"),
        subnets=_nova_to_osvif_subnets(network['subnets']))

    if network["bridge"] is not None:
        netobj.bridge = network['bridge']
    if network['label'] is not None:
        netobj.label = network['label']

    if network.get_meta("mtu") is not None:
        netobj.mtu = network.get_meta("mtu")
    if network.get_meta("multi_host") is not None:
        netobj.multi_host = network.get_meta("multi_host")
    if network.get_meta("should_create_bridge") is not None:
        netobj.should_provide_bridge = network.get_meta("should_create_bridge")
    if network.get_meta("should_create_vlan") is not None:
        netobj.should_provide_vlan = network.get_meta("should_create_vlan")
        if network.get_meta("vlan") is None:
            raise exception.NovaException(_("Missing vlan number in %s") %
                                          network)
        netobj.vlan = network.get_meta("vlan")

    return netobj


def _get_vif_instance(vif, cls, plugin, **kwargs):
    """Instantiate an os-vif VIF instance

    :param vif: the nova.network.model.VIF instance
    :param cls: class for a os_vif.objects.vif.VIFBase subclass

    :returns: a os_vif.objects.vif.VIFBase instance
    """

    return cls(
        id=vif['id'],
        address=vif['address'],
        network=_nova_to_osvif_network(vif['network']),
        has_traffic_filtering=vif.is_neutron_filtering_enabled(),
        preserve_on_delete=vif['preserve_on_delete'],
        active=vif['active'],
        plugin=plugin,
        **kwargs)


def _set_representor_datapath_offload_settings(vif, obj):
    """Populate the representor datapath offload metadata in the port profile.

    This function should only be called if the VIF's ``vnic_type`` is in the
    VNIC_TYPES_SRIOV list, and the ``port_profile`` field of ``obj`` has been
    populated.

    :param vif: the nova.network.model.VIF instance
    :param obj: an os_vif.objects.vif.VIFBase instance
    """

    datapath_offload = objects.vif.DatapathOffloadRepresentor(
        representor_name=_get_vif_name(vif),
        representor_address=vif["profile"]["pci_slot"])
    obj.port_profile.datapath_offload = datapath_offload


def _get_vnic_direct_vif_instance(vif, port_profile, plugin, set_bridge=True):
    """Instantiate an os-vif VIF instance for ``vnic_type`` = VNIC_TYPE_DIRECT

    :param vif: the nova.network.model.VIF instance
    :param port_profile: an os_vif.objects.vif.VIFPortProfileBase instance
    :param plugin: the os-vif plugin name
    :param set_bridge: if True, populate obj.network.bridge

    :returns: an os_vif.objects.vif.VIFHostDevice instance
    """

    obj = _get_vif_instance(
        vif,
        objects.vif.VIFHostDevice,
        port_profile=port_profile,
        plugin=plugin,
        dev_address=vif["profile"]["pci_slot"],
        dev_type=objects.fields.VIFHostDeviceDevType.ETHERNET
    )
    if set_bridge and vif["network"]["bridge"] is not None:
        obj.network.bridge = vif["network"]["bridge"]
    return obj


def _get_ovs_representor_port_profile(vif):
    """Instantiate an os-vif port_profile object.

    :param vif: the nova.network.model.VIF instance

    :returns: an os_vif.objects.vif.VIFPortProfileOVSRepresentor instance
    """

    # TODO(jangutter): in accordance with the generic-os-vif-offloads spec,
    # the datapath offload info is duplicated in both interfaces for Stein.
    # The port profile should be transitioned to VIFPortProfileOpenVSwitch
    # during Train.
    return objects.vif.VIFPortProfileOVSRepresentor(
        interface_id=vif.get('ovs_interfaceid') or vif['id'],
        representor_name=_get_vif_name(vif),
        representor_address=vif["profile"]['pci_slot'])


# VIF_TYPE_BRIDGE = 'bridge'
def _nova_to_osvif_vif_bridge(vif):
    obj = _get_vif_instance(
        vif,
        objects.vif.VIFBridge,
        plugin="linux_bridge",
        vif_name=_get_vif_name(vif))
    if vif["network"]["bridge"] is not None:
        obj.bridge_name = vif["network"]["bridge"]
    return obj


# VIF_TYPE_OVS = 'ovs'
def _nova_to_osvif_vif_ovs(vif):
    vif_name = _get_vif_name(vif)
    vnic_type = vif.get('vnic_type', model.VNIC_TYPE_NORMAL)
    profile = objects.vif.VIFPortProfileOpenVSwitch(
        interface_id=vif.get('ovs_interfaceid') or vif['id'],
        datapath_type=vif['details'].get(
            model.VIF_DETAILS_OVS_DATAPATH_TYPE))
    if vnic_type == model.VNIC_TYPE_DIRECT:
        obj = _get_vnic_direct_vif_instance(
            vif,
            port_profile=_get_ovs_representor_port_profile(vif),
            plugin="ovs")
        _set_representor_datapath_offload_settings(vif, obj)
    elif vif.is_hybrid_plug_enabled():
        obj = _get_vif_instance(
            vif,
            objects.vif.VIFBridge,
            port_profile=profile,
            plugin="ovs",
            vif_name=vif_name,
            bridge_name=_get_hybrid_bridge_name(vif))
    else:
        obj = _get_vif_instance(
            vif,
            objects.vif.VIFOpenVSwitch,
            port_profile=profile,
            plugin="ovs",
            vif_name=vif_name)
        if vif["network"]["bridge"] is not None:
            obj.bridge_name = vif["network"]["bridge"]
    return obj


# VIF_TYPE_AGILIO_OVS = 'agilio_ovs'
def _nova_to_osvif_vif_agilio_ovs(vif):
    vnic_type = vif.get('vnic_type', model.VNIC_TYPE_NORMAL)
    if vnic_type == model.VNIC_TYPE_DIRECT:
        obj = _get_vnic_direct_vif_instance(
            vif,
            plugin="agilio_ovs",
            port_profile=_get_ovs_representor_port_profile(vif))
        _set_representor_datapath_offload_settings(vif, obj)
    elif vnic_type == model.VNIC_TYPE_VIRTIO_FORWARDER:
        obj = _get_vif_instance(
            vif,
            objects.vif.VIFVHostUser,
            port_profile=_get_ovs_representor_port_profile(vif),
            plugin="agilio_ovs",
            vif_name=_get_vif_name(vif))
        _set_representor_datapath_offload_settings(vif, obj)
        _set_vhostuser_settings(vif, obj)
        if vif["network"]["bridge"] is not None:
            obj.network.bridge = vif["network"]["bridge"]
    else:
        LOG.debug("agilio_ovs falling through to ovs %s", vif)
        obj = _nova_to_osvif_vif_ovs(vif)
    return obj


# VIF_TYPE_VHOST_USER = 'vhostuser'
def _nova_to_osvif_vif_vhostuser(vif):
    if vif['details'].get(model.VIF_DETAILS_VHOSTUSER_FP_PLUG, False):
        if vif['details'].get(model.VIF_DETAILS_VHOSTUSER_OVS_PLUG, False):
            profile = objects.vif.VIFPortProfileFPOpenVSwitch(
                interface_id=vif.get('ovs_interfaceid') or vif['id'],
                datapath_type=vif['details'].get(
                    model.VIF_DETAILS_OVS_DATAPATH_TYPE))
            if vif.is_hybrid_plug_enabled():
                profile.bridge_name = _get_hybrid_bridge_name(vif)
                profile.hybrid_plug = True
            else:
                profile.hybrid_plug = False
                if vif["network"]["bridge"] is not None:
                    profile.bridge_name = vif["network"]["bridge"]
        else:
            profile = objects.vif.VIFPortProfileFPBridge()
            if vif["network"]["bridge"] is not None:
                profile.bridge_name = vif["network"]["bridge"]
        obj = _get_vif_instance(vif, objects.vif.VIFVHostUser,
                        plugin="vhostuser_fp",
                        vif_name=_get_vif_name(vif),
                        port_profile=profile)
        _set_vhostuser_settings(vif, obj)
        return obj
    elif vif['details'].get(model.VIF_DETAILS_VHOSTUSER_OVS_PLUG, False):
        profile = objects.vif.VIFPortProfileOpenVSwitch(
            interface_id=vif.get('ovs_interfaceid') or vif['id'],
            datapath_type=vif['details'].get(
                model.VIF_DETAILS_OVS_DATAPATH_TYPE))
        vif_name = ('vhu' + vif['id'])[:model.NIC_NAME_LEN]
        obj = _get_vif_instance(vif, objects.vif.VIFVHostUser,
                                port_profile=profile, plugin="ovs",
                                vif_name=vif_name)
        if vif["network"]["bridge"] is not None:
            obj.bridge_name = vif["network"]["bridge"]
        _set_vhostuser_settings(vif, obj)
        return obj
    elif vif['details'].get(model.VIF_DETAILS_VHOSTUSER_VROUTER_PLUG, False):
        obj = _get_vif_instance(vif, objects.vif.VIFVHostUser,
                                plugin="contrail_vrouter",
                                vif_name=_get_vif_name(vif))
        _set_vhostuser_settings(vif, obj)
        return obj
    else:
        obj = _get_vif_instance(vif, objects.vif.VIFVHostUser,
                                plugin="noop",
                                vif_name=_get_vif_name(vif))
        _set_vhostuser_settings(vif, obj)
        return obj


# VIF_TYPE_IVS = 'ivs'
def _nova_to_osvif_vif_ivs(vif):
    if vif.is_hybrid_plug_enabled():
        obj = _get_vif_instance(
            vif,
            objects.vif.VIFBridge,
            plugin="ivs",
            vif_name=_get_vif_name(vif),
            bridge_name=_get_hybrid_bridge_name(vif))
    else:
        obj = _get_vif_instance(
            vif,
            objects.vif.VIFGeneric,
            plugin="ivs",
            vif_name=_get_vif_name(vif))
    return obj


# VIF_TYPE_VROUTER = 'vrouter'
def _nova_to_osvif_vif_vrouter(vif):
    vif_name = _get_vif_name(vif)
    vnic_type = vif.get('vnic_type', model.VNIC_TYPE_NORMAL)
    if vnic_type == model.VNIC_TYPE_NORMAL:
        obj = _get_vif_instance(
            vif,
            objects.vif.VIFGeneric,
            plugin="vrouter",
            vif_name=vif_name)
    elif vnic_type == model.VNIC_TYPE_DIRECT:
        obj = _get_vnic_direct_vif_instance(
            vif,
            port_profile=objects.vif.VIFPortProfileBase(),
            plugin="vrouter",
            set_bridge=False)
        _set_representor_datapath_offload_settings(vif, obj)
    elif vnic_type == model.VNIC_TYPE_VIRTIO_FORWARDER:
        obj = _get_vif_instance(
            vif,
            objects.vif.VIFVHostUser,
            port_profile=objects.vif.VIFPortProfileBase(),
            plugin="vrouter",
            vif_name=vif_name)
        _set_representor_datapath_offload_settings(vif, obj)
        _set_vhostuser_settings(vif, obj)
    else:
        raise NotImplementedError()
    return obj


def nova_to_osvif_vif(vif):
    """Convert a Nova VIF model to an os-vif object

    :param vif: a nova.network.model.VIF instance

    Attempt to convert a nova VIF instance into an os-vif
    VIF object, pointing to a suitable plugin. This will
    return None if there is no os-vif plugin available yet.

    :returns: a os_vif.objects.vif.VIFBase subclass, or None
      if not supported with os-vif yet
    """

    LOG.debug("Converting VIF %s", vif)

    vif_type = vif['type']

    if vif_type in LEGACY_VIFS:
        # We want to explicitly fall back to the legacy path for these VIF
        # types
        LOG.debug('No conversion for VIF type %s yet', vif_type)
        return None

    if vif_type in {model.VIF_TYPE_BINDING_FAILED, model.VIF_TYPE_UNBOUND}:
        # These aren't real VIF types. VIF_TYPE_BINDING_FAILED indicates port
        # binding to a host failed and we are trying to plug the VIFs again,
        # which will fail because we do not know the actual real VIF type, like
        # VIF_TYPE_OVS, VIF_TYPE_BRIDGE, etc. VIF_TYPE_UNBOUND, by comparison,
        # is the default VIF type of a driver when it is not bound to any host,
        # i.e. we have not set the host ID in the binding driver. This should
        # also only happen in error cases.
        # TODO(stephenfin): We probably want a more meaningful log here
        LOG.debug('No conversion for VIF type %s yet', vif_type)
        return None

    if vif_type == model.VIF_TYPE_OVS:
        vif_obj = _nova_to_osvif_vif_ovs(vif)
    elif vif_type == model.VIF_TYPE_IVS:
        vif_obj = _nova_to_osvif_vif_ivs(vif)
    elif vif_type == model.VIF_TYPE_BRIDGE:
        vif_obj = _nova_to_osvif_vif_bridge(vif)
    elif vif_type == model.VIF_TYPE_AGILIO_OVS:
        vif_obj = _nova_to_osvif_vif_agilio_ovs(vif)
    elif vif_type == model.VIF_TYPE_VHOSTUSER:
        vif_obj = _nova_to_osvif_vif_vhostuser(vif)
    elif vif_type == model.VIF_TYPE_VROUTER:
        vif_obj = _nova_to_osvif_vif_vrouter(vif)
    else:
        raise exception.NovaException('Unsupported VIF type %s' % vif_type)

    LOG.debug('Converted object %s', vif_obj)
    return vif_obj

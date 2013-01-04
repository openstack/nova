# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
# Copyright (C) 2011 Nicira, Inc
# Copyright 2011 OpenStack LLC.
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

"""VIF drivers for libvirt."""

from nova import exception
from nova.network import linux_net
from nova.network import model as network_model
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils

from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import designer

LOG = logging.getLogger(__name__)

libvirt_vif_opts = [
    # quantum_ovs_bridge is used, if Quantum provides Nova
    # the 'vif_type' portbinding field
    cfg.StrOpt('libvirt_ovs_bridge',
               default='br-int',
               help='Name of Integration Bridge used by Open vSwitch'),
    cfg.BoolOpt('libvirt_use_virtio_for_bridges',
                default=True,
                help='Use virtio for bridge interfaces with KVM/QEMU'),
]

CONF = cfg.CONF
CONF.register_opts(libvirt_vif_opts)
CONF.import_opt('libvirt_type', 'nova.virt.libvirt.driver')
CONF.import_opt('use_ipv6', 'nova.netconf')


class LibvirtBaseVIFDriver(object):

    def get_vif_devname(self, mapping):
        if 'vif_devname' in mapping:
            return mapping['vif_devname']
        return ("nic" + mapping['vif_uuid'])[:network_model.NIC_NAME_LEN]

    def get_config(self, instance, network, mapping):
        conf = vconfig.LibvirtConfigGuestInterface()
        model = None
        driver = None
        if (CONF.libvirt_type in ('kvm', 'qemu') and
            CONF.libvirt_use_virtio_for_bridges):
            model = "virtio"
            # Workaround libvirt bug, where it mistakenly
            # enables vhost mode, even for non-KVM guests
            if CONF.libvirt_type == "qemu":
                driver = "qemu"

        designer.set_vif_guest_frontend_config(
            conf, mapping['mac'], model, driver)

        return conf

    def plug(self, instance, vif):
        pass

    def unplug(self, instance, vif):
        pass


class LibvirtGenericVIFDriver(LibvirtBaseVIFDriver):
    """Generic VIF driver for libvirt networking."""

    def get_bridge_name(self, network):
        return network['bridge']

    def get_config_bridge(self, instance, network, mapping):
        """Get VIF configurations for bridge type."""
        conf = super(LibvirtGenericVIFDriver,
                     self).get_config(instance,
                                      network,
                                      mapping)

        designer.set_vif_host_backend_bridge_config(
            conf, self.get_bridge_name(network),
            self.get_vif_devname(mapping))

        mac_id = mapping['mac'].replace(':', '')
        name = "nova-instance-" + instance['name'] + "-" + mac_id
        primary_addr = mapping['ips'][0]['ip']
        dhcp_server = ra_server = ipv4_cidr = ipv6_cidr = None

        if mapping['dhcp_server']:
            dhcp_server = mapping['dhcp_server']
        if CONF.use_ipv6:
            ra_server = mapping.get('gateway_v6') + "/128"
        if CONF.allow_same_net_traffic:
            ipv4_cidr = network['cidr']
            if CONF.use_ipv6:
                ipv6_cidr = network['cidr_v6']

        designer.set_vif_host_backend_filter_config(
            conf, name, primary_addr, dhcp_server,
            ra_server, ipv4_cidr, ipv6_cidr)

        return conf

    def get_config(self, instance, network, mapping):
        vif_type = mapping.get('vif_type')

        LOG.debug(_("vif_type=%(vif_type)s instance=%(instance)s "
                    "network=%(network)s mapping=%(mapping)s")
                  % locals())

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))

        if vif_type == network_model.VIF_TYPE_BRIDGE:
            return self.get_config_bridge(instance, network, mapping)
        else:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)

    def plug_bridge(self, instance, vif):
        """Ensure that the bridge exists, and add VIF to it."""
        super(LibvirtGenericVIFDriver,
              self).plug(instance, vif)

        network, mapping = vif
        if (not network.get('multi_host') and
            mapping.get('should_create_bridge')):
            if mapping.get('should_create_vlan'):
                iface = CONF.vlan_interface or network['bridge_interface']
                LOG.debug(_('Ensuring vlan %(vlan)s and bridge %(bridge)s'),
                          {'vlan': network['vlan'],
                           'bridge': self.get_bridge_name(network)},
                          instance=instance)
                linux_net.LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                                             network['vlan'],
                                             self.get_bridge_name(network),
                                             iface)
            else:
                iface = CONF.flat_interface or network['bridge_interface']
                LOG.debug(_("Ensuring bridge %s"),
                          self.get_bridge_name(network), instance=instance)
                linux_net.LinuxBridgeInterfaceDriver.ensure_bridge(
                                        self.get_bridge_name(network),
                                        iface)

    def plug(self, instance, vif):
        network, mapping = vif
        vif_type = mapping.get('vif_type')

        LOG.debug(_("vif_type=%(vif_type)s instance=%(instance)s "
                    "network=%(network)s mapping=%(mapping)s")
                  % locals())

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))

        if vif_type == network_model.VIF_TYPE_BRIDGE:
            self.plug_bridge(instance, vif)
        else:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)

    def unplug_bridge(self, instance, vif):
        """No manual unplugging required."""
        super(LibvirtGenericVIFDriver,
              self).unplug(instance, vif)

    def unplug(self, instance, vif):
        network, mapping = vif
        vif_type = mapping.get('vif_type')

        LOG.debug(_("vif_type=%(vif_type)s instance=%(instance)s "
                    "network=%(network)s mapping=%(mapping)s")
                  % locals())

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))

        if vif_type == network_model.VIF_TYPE_BRIDGE:
            self.unplug_bridge(instance, vif)
        else:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)


class LibvirtBridgeDriver(LibvirtGenericVIFDriver):
    """Retained in Grizzly for compatibility with Quantum
       drivers which do not yet report 'vif_type' port binding.
       Will be deprecated in Havana, and removed in Ixxxx."""

    def get_config(self, instance, network, mapping):
        return self.get_config_bridge(instance, network, mapping)

    def plug(self, instance, vif):
        self.plug_bridge(instance, vif)

    def unplug(self, instance, vif):
        self.unplug_bridge(instance, vif)


class LibvirtOpenVswitchDriver(LibvirtBaseVIFDriver):
    """VIF driver for Open vSwitch that uses libivrt type='ethernet'

    Used for libvirt versions that do not support
    OVS virtual port XML (0.9.10 or earlier).
    """

    def get_bridge_name(self, network):
        return network.get('bridge') or CONF.libvirt_ovs_bridge

    def get_ovs_interfaceid(self, mapping):
        return mapping.get('ovs_interfaceid') or mapping['vif_uuid']

    def get_config(self, instance, network, mapping):
        dev = self.get_vif_devname(mapping)

        conf = super(LibvirtOpenVswitchDriver,
                     self).get_config(instance,
                                      network,
                                      mapping)

        designer.set_vif_host_backend_ethernet_config(conf, dev)

        return conf

    def plug(self, instance, vif):
        network, mapping = vif
        iface_id = self.get_ovs_interfaceid(mapping)
        dev = self.get_vif_devname(mapping)
        linux_net.create_tap_dev(dev)
        linux_net.create_ovs_vif_port(self.get_bridge_name(network),
                                      dev, iface_id, mapping['mac'],
                                      instance['uuid'])

    def unplug(self, instance, vif):
        """Unplug the VIF by deleting the port from the bridge."""
        try:
            network, mapping = vif
            linux_net.delete_ovs_vif_port(self.get_bridge_name(network),
                                          self.get_vif_devname(mapping))
        except exception.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)


class LibvirtHybridOVSBridgeDriver(LibvirtBridgeDriver):
    """VIF driver that uses OVS + Linux Bridge for iptables compatibility.

    Enables the use of OVS-based Quantum plugins while at the same
    time using iptables-based filtering, which requires that vifs be
    plugged into a linux bridge, not OVS.  IPtables filtering is useful for
    in particular for Nova security groups.
    """

    def get_br_name(self, iface_id):
        return ("qbr" + iface_id)[:network_model.NIC_NAME_LEN]

    def get_veth_pair_names(self, iface_id):
        return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

    def get_bridge_name(self, network):
        return network.get('bridge') or CONF.libvirt_ovs_bridge

    def get_ovs_interfaceid(self, mapping):
        return mapping.get('ovs_interfaceid') or mapping['vif_uuid']

    def get_config(self, instance, network, mapping):
        br_name = self.get_br_name(mapping['vif_uuid'])
        network['bridge'] = br_name
        return super(LibvirtHybridOVSBridgeDriver,
                     self).get_config(instance,
                                      network,
                                      mapping)

    def plug(self, instance, vif):
        """Plug using hybrid strategy

        Create a per-VIF linux bridge, then link that bridge to the OVS
        integration bridge via a veth device, setting up the other end
        of the veth device just like a normal OVS port.  Then boot the
        VIF on the linux bridge using standard libvirt mechanisms
        """

        network, mapping = vif
        iface_id = self.get_ovs_interfaceid(mapping)
        br_name = self.get_br_name(mapping['vif_uuid'])
        v1_name, v2_name = self.get_veth_pair_names(mapping['vif_uuid'])

        if not linux_net.device_exists(br_name):
            utils.execute('brctl', 'addbr', br_name, run_as_root=True)

        if not linux_net.device_exists(v2_name):
            linux_net._create_veth_pair(v1_name, v2_name)
            utils.execute('ip', 'link', 'set', br_name, 'up', run_as_root=True)
            utils.execute('brctl', 'addif', br_name, v1_name, run_as_root=True)
            linux_net.create_ovs_vif_port(self.get_bridge_name(network),
                                          v2_name, iface_id, mapping['mac'],
                                          instance['uuid'])

    def unplug(self, instance, vif):
        """UnPlug using hybrid strategy

        Unhook port from OVS, unhook port from bridge, delete
        bridge, and delete both veth devices.
        """
        try:
            network, mapping = vif
            br_name = self.get_br_name(mapping['vif_uuid'])
            v1_name, v2_name = self.get_veth_pair_names(mapping['vif_uuid'])

            utils.execute('brctl', 'delif', br_name, v1_name, run_as_root=True)
            utils.execute('ip', 'link', 'set', br_name, 'down',
                          run_as_root=True)
            utils.execute('brctl', 'delbr', br_name, run_as_root=True)

            linux_net.delete_ovs_vif_port(self.get_bridge_name(network),
                                          v2_name)
        except exception.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)


class LibvirtOpenVswitchVirtualPortDriver(LibvirtBaseVIFDriver):
    """VIF driver for Open vSwitch that uses integrated libvirt
       OVS virtual port XML (introduced in libvirt 0.9.11)."""

    def get_bridge_name(self, network):
        return network.get('bridge') or CONF.libvirt_ovs_bridge

    def get_ovs_interfaceid(self, mapping):
        return mapping.get('ovs_interfaceid') or mapping['vif_uuid']

    def get_config(self, instance, network, mapping):
        """Pass data required to create OVS virtual port element."""
        conf = super(LibvirtOpenVswitchVirtualPortDriver,
                     self).get_config(instance,
                                      network,
                                      mapping)

        designer.set_vif_host_backend_ovs_config(
            conf, self.get_bridge_name(network),
            self.get_ovs_interfaceid(mapping),
            self.get_vif_devname(mapping))

        return conf

    def plug(self, instance, vif):
        pass

    def unplug(self, instance, vif):
        """No action needed.  Libvirt takes care of cleanup."""
        pass


class QuantumLinuxBridgeVIFDriver(LibvirtGenericVIFDriver):
    """Retained in Grizzly for compatibility with Quantum
       drivers which do not yet report 'vif_type' port binding.
       Will be deprecated in Havana, and removed in Ixxxx."""

    def get_bridge_name(self, network):
        def_bridge = ("brq" + network['id'])[:network_model.NIC_NAME_LEN]
        return network.get('bridge') or def_bridge

    def get_config(self, instance, network, mapping):
        return self.get_config_bridge(instance, network, mapping)

    def plug(self, instance, vif):
        self.plug_bridge(instance, vif)

    def unplug(self, instance, vif):
        self.unplug_bridge(instance, vif)

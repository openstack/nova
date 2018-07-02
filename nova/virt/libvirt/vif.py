# Copyright (C) 2011 Midokura KK
# Copyright (C) 2011 Nicira, Inc
# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
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

"""VIF drivers for libvirt."""

import copy
import os

import os_vif
from os_vif import exception as osv_exception
from os_vif.objects import fields as osv_fields
from oslo_concurrency import processutils
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova.i18n import _
from nova.network import linux_net
from nova.network import model as network_model
from nova.network import os_vif_util
from nova import objects
from nova import profiler
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import designer
from nova.virt import osinfo

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

# vhostuser queues support
MIN_LIBVIRT_VHOSTUSER_MQ = (1, 2, 17)
#  vlan tag for macvtap passthrough mode on SRIOV VFs
MIN_LIBVIRT_MACVTAP_PASSTHROUGH_VLAN = (1, 3, 5)
# setting interface mtu was intoduced in libvirt 3.3, We also need to
# check for QEMU that because libvirt is configuring in same time
# host_mtu for virtio-net, fails if not supported.
MIN_LIBVIRT_INTERFACE_MTU = (3, 3, 0)
MIN_QEMU_INTERFACE_MTU = (2, 9, 0)


def is_vif_model_valid_for_virt(virt_type, vif_model):
    valid_models = {
        'qemu': [network_model.VIF_MODEL_VIRTIO,
                 network_model.VIF_MODEL_NE2K_PCI,
                 network_model.VIF_MODEL_PCNET,
                 network_model.VIF_MODEL_RTL8139,
                 network_model.VIF_MODEL_E1000,
                 network_model.VIF_MODEL_LAN9118,
                 network_model.VIF_MODEL_SPAPR_VLAN],
        'kvm': [network_model.VIF_MODEL_VIRTIO,
                network_model.VIF_MODEL_NE2K_PCI,
                network_model.VIF_MODEL_PCNET,
                network_model.VIF_MODEL_RTL8139,
                network_model.VIF_MODEL_E1000,
                network_model.VIF_MODEL_SPAPR_VLAN],
        'xen': [network_model.VIF_MODEL_NETFRONT,
                network_model.VIF_MODEL_NE2K_PCI,
                network_model.VIF_MODEL_PCNET,
                network_model.VIF_MODEL_RTL8139,
                network_model.VIF_MODEL_E1000],
        'lxc': [],
        'uml': [],
        'parallels': [network_model.VIF_MODEL_VIRTIO,
                      network_model.VIF_MODEL_RTL8139,
                      network_model.VIF_MODEL_E1000],
        }

    if vif_model is None:
        return True

    if virt_type not in valid_models:
        raise exception.UnsupportedVirtType(virt=virt_type)

    return vif_model in valid_models[virt_type]


@profiler.trace_cls("vif_driver")
class LibvirtGenericVIFDriver(object):
    """Generic VIF driver for libvirt networking."""

    def _normalize_vif_type(self, vif_type):
        return vif_type.replace('2.1q', '2q')

    def get_vif_devname(self, vif):
        if 'devname' in vif:
            return vif['devname']
        return ("nic" + vif['id'])[:network_model.NIC_NAME_LEN]

    def get_vif_devname_with_prefix(self, vif, prefix):
        devname = self.get_vif_devname(vif)
        return prefix + devname[3:]

    def get_base_config(self, instance, mac, image_meta,
                        inst_type, virt_type, vnic_type):
        conf = vconfig.LibvirtConfigGuestInterface()
        # Default to letting libvirt / the hypervisor choose the model
        model = None
        driver = None
        vhost_queues = None

        # If the user has specified a 'vif_model' against the
        # image then honour that model
        if image_meta:
            model = osinfo.HardwareProperties(image_meta).network_model

        # Else if the virt type is KVM/QEMU/VZ(Parallels), then use virtio
        # according to the global config parameter
        if (model is None and
            virt_type in ('kvm', 'qemu', 'parallels') and
                    CONF.libvirt.use_virtio_for_bridges):
            model = network_model.VIF_MODEL_VIRTIO

        # Workaround libvirt bug, where it mistakenly
        # enables vhost mode, even for non-KVM guests
        if (model == network_model.VIF_MODEL_VIRTIO and
            virt_type == "qemu"):
            driver = "qemu"

        if not is_vif_model_valid_for_virt(virt_type,
                                           model):
            raise exception.UnsupportedHardware(model=model,
                                                virt=virt_type)
        if (virt_type in ('kvm', 'parallels') and
            model == network_model.VIF_MODEL_VIRTIO and
            vnic_type not in network_model.VNIC_TYPES_SRIOV):
            vhost_drv, vhost_queues = self._get_virtio_mq_settings(image_meta,
                                                                   inst_type)
            driver = vhost_drv or driver

        designer.set_vif_guest_frontend_config(
            conf, mac, model, driver, vhost_queues)

        return conf

    def get_base_hostdev_pci_config(self, vif):
        conf = vconfig.LibvirtConfigGuestHostdevPCI()
        pci_slot = vif['profile']['pci_slot']
        designer.set_vif_host_backend_hostdev_pci_config(conf, pci_slot)
        return conf

    def _is_multiqueue_enabled(self, image_meta, flavor):
        _, vhost_queues = self._get_virtio_mq_settings(image_meta, flavor)
        return vhost_queues > 1 if vhost_queues is not None else False

    def _get_virtio_mq_settings(self, image_meta, flavor):
        """A methods to set the number of virtio queues,
           if it has been requested in extra specs.
        """
        driver = None
        vhost_queues = None
        if not isinstance(image_meta, objects.ImageMeta):
            image_meta = objects.ImageMeta.from_dict(image_meta)
        img_props = image_meta.properties
        if img_props.get('hw_vif_multiqueue_enabled'):
            driver = 'vhost'
            max_tap_queues = self._get_max_tap_queues()
            if max_tap_queues:
                vhost_queues = (max_tap_queues if flavor.vcpus > max_tap_queues
                    else flavor.vcpus)
            else:
                vhost_queues = flavor.vcpus

        return (driver, vhost_queues)

    def _get_max_tap_queues(self):
        # NOTE(kengo.sakai): In kernels prior to 3.0,
        # multiple queues on a tap interface is not supported.
        # In kernels 3.x, the number of queues on a tap interface
        # is limited to 8. From 4.0, the number is 256.
        # See: https://bugs.launchpad.net/nova/+bug/1570631
        kernel_version = int(os.uname()[2].split(".")[0])
        if kernel_version <= 2:
            return 1
        elif kernel_version == 3:
            return 8
        elif kernel_version == 4:
            return 256
        else:
            return None

    def get_bridge_name(self, vif):
        return vif['network']['bridge']

    def get_ovs_interfaceid(self, vif):
        return vif.get('ovs_interfaceid') or vif['id']

    def get_br_name(self, iface_id):
        return ("qbr" + iface_id)[:network_model.NIC_NAME_LEN]

    def get_veth_pair_names(self, iface_id):
        return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

    @staticmethod
    def is_no_op_firewall():
        return CONF.firewall_driver == "nova.virt.firewall.NoopFirewallDriver"

    def get_firewall_required(self, vif):
        if vif.is_neutron_filtering_enabled():
            return False
        if self.is_no_op_firewall():
            return False
        return True

    def get_firewall_required_os_vif(self, vif):
        if vif.has_traffic_filtering:
            return False
        if self.is_no_op_firewall():
            return False
        return True

    def get_config_bridge(self, instance, vif, image_meta,
                          inst_type, virt_type, host):
        """Get VIF configurations for bridge type."""
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        designer.set_vif_host_backend_bridge_config(
            conf, self.get_bridge_name(vif),
            self.get_vif_devname(vif))

        mac_id = vif['address'].replace(':', '')
        name = "nova-instance-" + instance.name + "-" + mac_id
        if self.get_firewall_required(vif):
            conf.filtername = name
        designer.set_vif_bandwidth_config(conf, inst_type)

        self._set_mtu_config(vif, host, conf)

        return conf

    def _set_mtu_config(self, vif, host, conf):
        """:param vif: nova.network.modle.vif
           :param host: nova.virt.libvirt.host.Host
           :param conf: nova.virt.libvirt.config.LibvirtConfigGuestInterface
        """
        network = vif.get('network')
        if (network and network.get_meta("mtu") and
                self._has_min_version_for_mtu(host)):
            designer.set_vif_mtu_config(conf, network.get_meta("mtu"))

    def _has_min_version_for_mtu(self, host):
        return host.has_min_version(MIN_LIBVIRT_INTERFACE_MTU,
                                    MIN_QEMU_INTERFACE_MTU)

    def get_config_ivs_hybrid(self, instance, vif, image_meta,
                              inst_type, virt_type, host):
        newvif = copy.deepcopy(vif)
        newvif['network']['bridge'] = self.get_br_name(vif['id'])
        return self.get_config_bridge(instance,
                                      newvif,
                                      image_meta,
                                      inst_type,
                                      virt_type,
                                      host)

    def get_config_ivs_ethernet(self, instance, vif, image_meta,
                                inst_type, virt_type, host):
        conf = self.get_base_config(instance,
                                    vif['address'],
                                    image_meta,
                                    inst_type,
                                    virt_type,
                                    vif['vnic_type'])

        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        return conf

    def get_config_ivs(self, instance, vif, image_meta,
                       inst_type, virt_type, host):
        if self.get_firewall_required(vif) or vif.is_hybrid_plug_enabled():
            return self.get_config_ivs_hybrid(instance, vif,
                                              image_meta,
                                              inst_type,
                                              virt_type,
                                              host)
        else:
            return self.get_config_ivs_ethernet(instance, vif,
                                                image_meta,
                                                inst_type,
                                                virt_type,
                                                host)

    def get_config_802qbg(self, instance, vif, image_meta,
                          inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        params = vif["qbg_params"]
        designer.set_vif_host_backend_802qbg_config(
            conf, vif['network'].get_meta('interface'),
            params['managerid'],
            params['typeid'],
            params['typeidversion'],
            params['instanceid'])

        designer.set_vif_bandwidth_config(conf, inst_type)

        return conf

    def get_config_802qbh(self, instance, vif, image_meta,
                          inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        profile = vif["profile"]
        vif_details = vif["details"]
        net_type = 'direct'
        if vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
            net_type = 'hostdev'

        designer.set_vif_host_backend_802qbh_config(
            conf, net_type, profile['pci_slot'],
            vif_details[network_model.VIF_DETAILS_PROFILEID])

        designer.set_vif_bandwidth_config(conf, inst_type)

        return conf

    def get_config_hw_veb(self, instance, vif, image_meta,
                            inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        profile = vif["profile"]
        vif_details = vif["details"]
        net_type = 'direct'
        if vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
            net_type = 'hostdev'

        designer.set_vif_host_backend_hw_veb(
            conf, net_type, profile['pci_slot'],
            vif_details[network_model.VIF_DETAILS_VLAN])

        # NOTE(vladikr): Not setting vlan tags for macvtap on SR-IOV VFs
        # as vlan tag is not supported in Libvirt until version 1.3.5
        if (vif['vnic_type'] == network_model.VNIC_TYPE_MACVTAP and not
                host.has_min_version(MIN_LIBVIRT_MACVTAP_PASSTHROUGH_VLAN)):
            conf.vlan = None
        designer.set_vif_bandwidth_config(conf, inst_type)

        return conf

    def get_config_hostdev_physical(self, instance, vif, image_meta,
                                    inst_type, virt_type, host):
        return self.get_base_hostdev_pci_config(vif)

    def get_config_macvtap(self, instance, vif, image_meta,
                           inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        vif_details = vif['details']
        macvtap_src = vif_details.get(network_model.VIF_DETAILS_MACVTAP_SOURCE)
        macvtap_mode = vif_details.get(network_model.VIF_DETAILS_MACVTAP_MODE)
        phys_interface = vif_details.get(
                                    network_model.VIF_DETAILS_PHYS_INTERFACE)

        missing_params = []
        if macvtap_src is None:
            missing_params.append(network_model.VIF_DETAILS_MACVTAP_SOURCE)
        if macvtap_mode is None:
            missing_params.append(network_model.VIF_DETAILS_MACVTAP_MODE)
        if phys_interface is None:
            missing_params.append(network_model.VIF_DETAILS_PHYS_INTERFACE)

        if len(missing_params) > 0:
            raise exception.VifDetailsMissingMacvtapParameters(
                                                vif_id=vif['id'],
                                                missing_params=missing_params)

        designer.set_vif_host_backend_direct_config(
            conf, macvtap_src, macvtap_mode)

        designer.set_vif_bandwidth_config(conf, inst_type)

        return conf

    def get_config_iovisor(self, instance, vif, image_meta,
                           inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        designer.set_vif_bandwidth_config(conf, inst_type)

        return conf

    def get_config_midonet(self, instance, vif, image_meta,
                           inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        return conf

    def get_config_tap(self, instance, vif, image_meta,
                       inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])

        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        self._set_mtu_config(vif, host, conf)

        return conf

    def _get_vhostuser_settings(self, vif):
        vif_details = vif['details']
        mode = vif_details.get(network_model.VIF_DETAILS_VHOSTUSER_MODE,
                               'server')
        sock_path = vif_details.get(network_model.VIF_DETAILS_VHOSTUSER_SOCKET)
        if sock_path is None:
            raise exception.VifDetailsMissingVhostuserSockPath(
                                                        vif_id=vif['id'])
        return mode, sock_path

    def get_config_vhostuser(self, instance, vif, image_meta,
                            inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])
        mode, sock_path = self._get_vhostuser_settings(vif)
        designer.set_vif_host_backend_vhostuser_config(conf, mode, sock_path)
        # (vladikr) Not setting up driver and queues for vhostuser
        # as queues are not supported in Libvirt until version 1.2.17
        if not host.has_min_version(MIN_LIBVIRT_VHOSTUSER_MQ):
            LOG.debug('Queues are not a vhostuser supported feature.')
            conf.driver_name = None
            conf.vhost_queues = None

        return conf

    def get_config_ib_hostdev(self, instance, vif, image_meta,
                              inst_type, virt_type, host):
        return self.get_base_hostdev_pci_config(vif)

    def get_config_vrouter(self, instance, vif, image_meta,
                           inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'])
        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        designer.set_vif_bandwidth_config(conf, inst_type)
        return conf

    def _set_config_VIFBridge(self, instance, vif, conf, host=None):
        conf.net_type = "bridge"
        conf.source_dev = vif.bridge_name
        conf.target_dev = vif.vif_name

        if self.get_firewall_required_os_vif(vif):
            mac_id = vif.address.replace(':', '')
            name = "nova-instance-" + instance.name + "-" + mac_id
            conf.filtername = name

    def _set_config_VIFOpenVSwitch(self, instance, vif, conf, host=None):
        conf.net_type = "bridge"
        conf.source_dev = vif.bridge_name
        conf.target_dev = vif.vif_name
        self._set_config_VIFPortProfile(instance, vif, conf)

    def _set_config_VIFVHostUser(self, instance, vif, conf, host=None):
        designer.set_vif_host_backend_vhostuser_config(
            conf, vif.mode, vif.path)
        if not host.has_min_version(MIN_LIBVIRT_VHOSTUSER_MQ):
            LOG.debug('Queues are not a vhostuser supported feature.')
            conf.driver_name = None
            conf.vhost_queues = None

    def _set_config_VIFHostDevice(self, instance, vif, conf, host=None):
        if vif.dev_type == osv_fields.VIFHostDeviceDevType.ETHERNET:
            # This sets the required fields for an <interface type='hostdev'>
            # section in a libvirt domain (by using a subset of hw_veb's
            # options).
            designer.set_vif_host_backend_hw_veb(
                conf, 'hostdev', vif.dev_address, None)
        else:
            # TODO(jangutter): dev_type == VIFHostDeviceDevType.GENERIC
            # is currently unsupported under os-vif. The corresponding conf
            # class would be: LibvirtConfigGuestHostdevPCI
            # but os-vif only returns a LibvirtConfigGuestInterface object
            raise exception.InternalError(
                _("Unsupported os-vif VIFHostDevice dev_type %(type)s") %
                {'type': vif.dev_type})

    def _set_config_VIFPortProfileOpenVSwitch(self, profile, conf):
        conf.vporttype = "openvswitch"
        conf.add_vport_param("interfaceid",
                             profile.interface_id)

    def _set_config_VIFPortProfile(self, instance, vif, conf):
        # Set any port profile that may be required
        profilefunc = "_set_config_" + vif.port_profile.obj_name()
        func = getattr(self, profilefunc, None)
        if not func:
            raise exception.InternalError(
                _("Unsupported VIF port profile type %(obj)s func %(func)s") %
                {'obj': vif.port_profile.obj_name(), 'func': profilefunc})

        func(vif.port_profile, conf)

    def _get_config_os_vif(self, instance, vif, image_meta, inst_type,
                           virt_type, host, vnic_type):
        """Get the domain config for a VIF

        :param instance: nova.objects.Instance
        :param vif: os_vif.objects.vif.VIFBase subclass
        :param image_meta: nova.objects.ImageMeta
        :param inst_type: nova.objects.Flavor
        :param virt_type: virtualization type
        :param host: nova.virt.libvirt.host.Host
        :param vnic_type: vnic type

        :returns: nova.virt.libvirt.config.LibvirtConfigGuestInterface
        """

        # Do the config that's common to all vif types
        conf = self.get_base_config(instance, vif.address, image_meta,
                                    inst_type, virt_type, vnic_type)

        # Do the VIF type specific config
        viffunc = "_set_config_" + vif.obj_name()
        func = getattr(self, viffunc, None)
        if not func:
            raise exception.InternalError(
                _("Unsupported VIF type %(obj)s func %(func)s") %
                {'obj': vif.obj_name(), 'func': viffunc})
        func(instance, vif, conf, host)

        designer.set_vif_bandwidth_config(conf, inst_type)
        if ('network' in vif and 'mtu' in vif.network and
                self._has_min_version_for_mtu(host)):
            designer.set_vif_mtu_config(conf, vif.network.mtu)

        return conf

    def get_config(self, instance, vif, image_meta,
                   inst_type, virt_type, host):
        vif_type = vif['type']
        vnic_type = vif['vnic_type']

        # instance.display_name could be unicode
        instance_repr = utils.get_obj_repr_unicode(instance)
        LOG.debug('vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s virt_type=%(virt_type)s',
                  {'vif_type': vif_type, 'instance': instance_repr,
                   'vif': vif, 'virt_type': virt_type})

        if vif_type is None:
            raise exception.InternalError(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))

        # Try os-vif codepath first
        vif_obj = os_vif_util.nova_to_osvif_vif(vif)
        if vif_obj is not None:
            return self._get_config_os_vif(instance, vif_obj, image_meta,
                                           inst_type, virt_type, host,
                                           vnic_type)

        # Legacy non-os-vif codepath
        vif_slug = self._normalize_vif_type(vif_type)
        func = getattr(self, 'get_config_%s' % vif_slug, None)
        if not func:
            raise exception.InternalError(
                _("Unexpected vif_type=%s") % vif_type)
        return func(instance, vif, image_meta,
                    inst_type, virt_type, host)

    def plug_ivs_hybrid(self, instance, vif):
        """Plug using hybrid strategy (same as OVS)

        Create a per-VIF linux bridge, then link that bridge to the OVS
        integration bridge via a veth device, setting up the other end
        of the veth device just like a normal IVS port.  Then boot the
        VIF on the linux bridge using standard libvirt mechanisms.
        """
        iface_id = self.get_ovs_interfaceid(vif)
        br_name = self.get_br_name(vif['id'])
        v1_name, v2_name = self.get_veth_pair_names(vif['id'])

        if not linux_net.device_exists(br_name):
            nova.privsep.libvirt.add_bridge(br_name)
            nova.privsep.libvirt.zero_bridge_forward_delay(br_name)
            nova.privsep.libvirt.disable_bridge_stp(br_name)
            nova.privsep.libvirt.disable_multicast_snooping(br_name)
            nova.privsep.libvirt.disable_ipv6(br_name)

        if not linux_net.device_exists(v2_name):
            mtu = vif['network'].get_meta('mtu')
            linux_net._create_veth_pair(v1_name, v2_name, mtu)
            nova.privsep.libvirt.toggle_interface(br_name, 'up')
            nova.privsep.libvirt.bridge_add_interface(br_name, v1_name)
            linux_net.create_ivs_vif_port(v2_name, iface_id,
                                          vif['address'], instance.uuid)

    def plug_ivs_ethernet(self, instance, vif):
        iface_id = self.get_ovs_interfaceid(vif)
        dev = self.get_vif_devname(vif)
        linux_net.create_tap_dev(dev)
        linux_net.create_ivs_vif_port(dev, iface_id, vif['address'],
                                      instance.uuid)

    def plug_ivs(self, instance, vif):
        if self.get_firewall_required(vif) or vif.is_hybrid_plug_enabled():
            self.plug_ivs_hybrid(instance, vif)
        else:
            self.plug_ivs_ethernet(instance, vif)

    def plug_ib_hostdev(self, instance, vif):
        fabric = vif.get_physical_network()
        if not fabric:
            raise exception.NetworkMissingPhysicalNetwork(
                network_uuid=vif['network']['id']
            )
        pci_slot = vif['profile']['pci_slot']
        device_id = instance['uuid']
        vnic_mac = vif['address']
        try:
            nova.privsep.libvirt.plug_infiniband_vif(
                vnic_mac, device_id, fabric,
                network_model.VIF_TYPE_IB_HOSTDEV, pci_slot)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while plugging ib hostdev vif"),
                          instance=instance)

    def plug_802qbg(self, instance, vif):
        pass

    def plug_802qbh(self, instance, vif):
        pass

    def plug_hw_veb(self, instance, vif):
        # TODO(vladikr): This code can be removed once the minimum version of
        # Libvirt is incleased above 1.3.5, as vlan will be set by libvirt
        if vif['vnic_type'] == network_model.VNIC_TYPE_MACVTAP:
            linux_net.set_vf_interface_vlan(
                vif['profile']['pci_slot'],
                mac_addr=vif['address'],
                vlan=vif['details'][network_model.VIF_DETAILS_VLAN])

    def plug_hostdev_physical(self, instance, vif):
        pass

    def plug_macvtap(self, instance, vif):
        vif_details = vif['details']
        vlan = vif_details.get(network_model.VIF_DETAILS_VLAN)
        if vlan:
            vlan_name = vif_details.get(
                                    network_model.VIF_DETAILS_MACVTAP_SOURCE)
            phys_if = vif_details.get(network_model.VIF_DETAILS_PHYS_INTERFACE)
            linux_net.LinuxBridgeInterfaceDriver.ensure_vlan(
                vlan, phys_if, interface=vlan_name)

    def plug_midonet(self, instance, vif):
        """Plug into MidoNet's network port

        Bind the vif to a MidoNet virtual port.
        """
        dev = self.get_vif_devname(vif)
        port_id = vif['id']
        try:
            linux_net.create_tap_dev(dev)
            nova.privsep.libvirt.plug_midonet_vif(port_id, dev)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while plugging vif"), instance=instance)

    def plug_iovisor(self, instance, vif):
        """Plug using PLUMgrid IO Visor Driver

        Connect a network device to their respective
        Virtual Domain in PLUMgrid Platform.
        """
        dev = self.get_vif_devname(vif)
        iface_id = vif['id']
        linux_net.create_tap_dev(dev)
        net_id = vif['network']['id']
        tenant_id = instance.project_id
        try:
            nova.privsep.libvirt.plug_plumgrid_vif(
                dev, iface_id, vif['address'], net_id, tenant_id)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while plugging vif"), instance=instance)

    def plug_tap(self, instance, vif):
        """Plug a VIF_TYPE_TAP virtual interface."""
        dev = self.get_vif_devname(vif)
        mac = vif['details'].get(network_model.VIF_DETAILS_TAP_MAC_ADDRESS)
        linux_net.create_tap_dev(dev, mac)
        network = vif.get('network')
        mtu = network.get_meta('mtu') if network else None
        linux_net._set_device_mtu(dev, mtu)

    def plug_vhostuser(self, instance, vif):
        pass

    def plug_vrouter(self, instance, vif):
        """Plug into Contrail's network port

        Bind the vif to a Contrail virtual port.
        """
        dev = self.get_vif_devname(vif)
        ip_addr = '0.0.0.0'
        ip6_addr = None
        subnets = vif['network']['subnets']
        for subnet in subnets:
            if not subnet['ips']:
                continue
            ips = subnet['ips'][0]
            if not ips['address']:
                continue
            if (ips['version'] == 4):
                if ips['address'] is not None:
                    ip_addr = ips['address']
            if (ips['version'] == 6):
                if ips['address'] is not None:
                    ip6_addr = ips['address']

        ptype = 'NovaVMPort'
        if (CONF.libvirt.virt_type == 'lxc'):
            ptype = 'NameSpacePort'

        try:
            multiqueue = self._is_multiqueue_enabled(instance.image_meta,
                                                     instance.flavor)
            linux_net.create_tap_dev(dev, multiqueue=multiqueue)
            nova.privsep.libvirt.plug_contrail_vif(
                instance.project_id,
                instance.uuid,
                instance.display_name,
                vif['id'],
                vif['network']['id'],
                ptype,
                dev,
                vif['address'],
                ip_addr,
                ip6_addr,
            )
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while plugging vif"), instance=instance)

    def _plug_os_vif(self, instance, vif):
        instance_info = os_vif_util.nova_to_osvif_instance(instance)

        try:
            os_vif.plug(vif, instance_info)
        except osv_exception.ExceptionBase as ex:
            msg = (_("Failure running os_vif plugin plug method: %(ex)s")
                   % {'ex': ex})
            raise exception.InternalError(msg)

    def plug(self, instance, vif):
        vif_type = vif['type']

        # instance.display_name could be unicode
        instance_repr = utils.get_obj_repr_unicode(instance)
        LOG.debug('vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance_repr,
                   'vif': vif})

        if vif_type is None:
            raise exception.VirtualInterfacePlugException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))

        # Try os-vif codepath first
        vif_obj = os_vif_util.nova_to_osvif_vif(vif)
        if vif_obj is not None:
            self._plug_os_vif(instance, vif_obj)
            return

        # Legacy non-os-vif codepath
        vif_slug = self._normalize_vif_type(vif_type)
        func = getattr(self, 'plug_%s' % vif_slug, None)
        if not func:
            raise exception.VirtualInterfacePlugException(
                _("Plug vif failed because of unexpected "
                  "vif_type=%s") % vif_type)
        func(instance, vif)

    def unplug_ivs_hybrid(self, instance, vif):
        """UnPlug using hybrid strategy (same as OVS)

        Unhook port from IVS, unhook port from bridge, delete
        bridge, and delete both veth devices.
        """
        try:
            br_name = self.get_br_name(vif['id'])
            v1_name, v2_name = self.get_veth_pair_names(vif['id'])

            nova.privsep.libvirt.bridge_delete_interface(br_name, v1_name)
            nova.privsep.libvirt.toggle_interface(br_name, 'down')
            nova.privsep.libvirt.delete_bridge(br_name)
            linux_net.delete_ivs_vif_port(v2_name)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_ivs_ethernet(self, instance, vif):
        """Unplug the VIF by deleting the port from the bridge."""
        try:
            linux_net.delete_ivs_vif_port(self.get_vif_devname(vif))
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_ivs(self, instance, vif):
        if self.get_firewall_required(vif) or vif.is_hybrid_plug_enabled():
            self.unplug_ivs_hybrid(instance, vif)
        else:
            self.unplug_ivs_ethernet(instance, vif)

    def unplug_ib_hostdev(self, instance, vif):
        fabric = vif.get_physical_network()
        if not fabric:
            raise exception.NetworkMissingPhysicalNetwork(
                network_uuid=vif['network']['id']
            )
        vnic_mac = vif['address']
        try:
            nova.privsep.libvirt.unplug_infiniband_vif(fabric, vnic_mac)
        except Exception:
            LOG.exception(_("Failed while unplugging ib hostdev vif"))

    def unplug_802qbg(self, instance, vif):
        pass

    def unplug_802qbh(self, instance, vif):
        pass

    def unplug_hw_veb(self, instance, vif):
        # TODO(vladikr): This code can be removed once the minimum version of
        # Libvirt is incleased above 1.3.5, as vlan will be set by libvirt
        if vif['vnic_type'] == network_model.VNIC_TYPE_MACVTAP:
            # The ip utility doesn't accept the MAC 00:00:00:00:00:00.
            # Therefore, keep the MAC unchanged.  Later operations on
            # the same VF will not be affected by the existing MAC.
            linux_net.set_vf_interface_vlan(vif['profile']['pci_slot'],
                                            mac_addr=vif['address'])

    def unplug_hostdev_physical(self, instance, vif):
        pass

    def unplug_macvtap(self, instance, vif):
        pass

    def unplug_midonet(self, instance, vif):
        """Unplug from MidoNet network port

        Unbind the vif from a MidoNet virtual port.
        """
        dev = self.get_vif_devname(vif)
        port_id = vif['id']
        try:
            nova.privsep.libvirt.unplug_midonet_vif(port_id)
            linux_net.delete_net_dev(dev)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_tap(self, instance, vif):
        """Unplug a VIF_TYPE_TAP virtual interface."""
        dev = self.get_vif_devname(vif)
        try:
            linux_net.delete_net_dev(dev)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_iovisor(self, instance, vif):
        """Unplug using PLUMgrid IO Visor Driver

        Delete network device and to their respective
        connection to the Virtual Domain in PLUMgrid Platform.
        """
        dev = self.get_vif_devname(vif)
        try:
            nova.privsep.libvirt.unplug_plumgrid_vif(dev)
            linux_net.delete_net_dev(dev)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_vhostuser(self, instance, vif):
        pass

    def unplug_vrouter(self, instance, vif):
        """Unplug Contrail's network port

        Unbind the vif from a Contrail virtual port.
        """
        dev = self.get_vif_devname(vif)
        port_id = vif['id']
        try:
            nova.privsep.libvirt.unplug_contrail_vif(port_id)
            linux_net.delete_net_dev(dev)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def _unplug_os_vif(self, instance, vif):
        instance_info = os_vif_util.nova_to_osvif_instance(instance)

        try:
            os_vif.unplug(vif, instance_info)
        except osv_exception.ExceptionBase as ex:
            msg = (_("Failure running os_vif plugin unplug method: %(ex)s")
                   % {'ex': ex})
            raise exception.InternalError(msg)

    def unplug(self, instance, vif):
        vif_type = vif['type']

        # instance.display_name could be unicode
        instance_repr = utils.get_obj_repr_unicode(instance)
        LOG.debug('vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance_repr,
                   'vif': vif})

        if vif_type is None:
            msg = _("vif_type parameter must be present for this vif_driver "
                    "implementation")
            raise exception.InternalError(msg)

        # Try os-vif codepath first
        vif_obj = os_vif_util.nova_to_osvif_vif(vif)
        if vif_obj is not None:
            self._unplug_os_vif(instance, vif_obj)
            return

        # Legacy non-os-vif codepath
        vif_slug = self._normalize_vif_type(vif_type)
        func = getattr(self, 'unplug_%s' % vif_slug, None)
        if not func:
            msg = _("Unexpected vif_type=%s") % vif_type
            raise exception.InternalError(msg)
        func(instance, vif)

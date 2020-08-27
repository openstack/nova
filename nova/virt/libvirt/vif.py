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

import os

import os_vif
from os_vif import exception as osv_exception
from os_vif.objects import fields as osv_fields
from os_vif.objects import vif as osv_vifs
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import strutils

import nova.conf
from nova import exception
from nova.i18n import _
from nova.network import model as network_model
from nova.network import os_vif_util
from nova import objects
from nova.pci import utils as pci_utils
import nova.privsep.linux_net
from nova import profiler
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import designer
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt import osinfo


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

# setting interface mtu was intoduced in libvirt 3.3, We also need to
# check for QEMU that because libvirt is configuring in same time
# host_mtu for virtio-net, fails if not supported.
MIN_LIBVIRT_INTERFACE_MTU = (3, 3, 0)
MIN_QEMU_INTERFACE_MTU = (2, 9, 0)

# virtio-net.tx_queue_size support
MIN_LIBVIRT_TX_QUEUE_SIZE = (3, 7, 0)
MIN_QEMU_TX_QUEUE_SIZE = (2, 10, 0)

SUPPORTED_VIF_MODELS = {
    'qemu': [
        network_model.VIF_MODEL_VIRTIO,
        network_model.VIF_MODEL_NE2K_PCI,
        network_model.VIF_MODEL_PCNET,
        network_model.VIF_MODEL_RTL8139,
        network_model.VIF_MODEL_E1000,
        network_model.VIF_MODEL_E1000E,
        network_model.VIF_MODEL_LAN9118,
        network_model.VIF_MODEL_SPAPR_VLAN],
    'kvm': [
        network_model.VIF_MODEL_VIRTIO,
        network_model.VIF_MODEL_NE2K_PCI,
        network_model.VIF_MODEL_PCNET,
        network_model.VIF_MODEL_RTL8139,
        network_model.VIF_MODEL_E1000,
        network_model.VIF_MODEL_E1000E,
        network_model.VIF_MODEL_SPAPR_VLAN],
    'xen': [
        network_model.VIF_MODEL_NETFRONT,
        network_model.VIF_MODEL_NE2K_PCI,
        network_model.VIF_MODEL_PCNET,
        network_model.VIF_MODEL_RTL8139,
        network_model.VIF_MODEL_E1000],
    'lxc': [],
    'uml': [],
    'parallels': [
        network_model.VIF_MODEL_VIRTIO,
        network_model.VIF_MODEL_RTL8139,
        network_model.VIF_MODEL_E1000],
}


def is_vif_model_valid_for_virt(virt_type, vif_model):

    if vif_model is None:
        return True

    if virt_type not in SUPPORTED_VIF_MODELS:
        raise exception.UnsupportedVirtType(virt=virt_type)

    return vif_model in SUPPORTED_VIF_MODELS[virt_type]


def set_vf_interface_vlan(pci_addr, mac_addr, vlan=0):
    vlan_id = int(vlan)
    pf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr,
                                                    pf_interface=True)
    vf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr)
    vf_num = pci_utils.get_vf_num_by_pci_address(pci_addr)

    nova.privsep.linux_net.set_device_macaddr_and_vlan(
        pf_ifname, vf_num, mac_addr, vlan_id)

    # Bring up/down the VF's interface
    # TODO(edand): The mac is assigned as a workaround for the following issue
    #              https://bugzilla.redhat.com/show_bug.cgi?id=1372944
    #              once resolved it will be removed
    port_state = 'up' if vlan_id > 0 else 'down'
    nova.privsep.linux_net.set_device_macaddr(vf_ifname, mac_addr,
                                              port_state=port_state)


def set_vf_trusted(pci_addr, trusted):
    """Configures the VF to be trusted or not

    :param pci_addr: PCI slot of the device
    :param trusted: Boolean value to indicate whether to
                    enable/disable 'trusted' capability
    """
    pf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr,
                                                    pf_interface=True)
    vf_num = pci_utils.get_vf_num_by_pci_address(pci_addr)
    nova.privsep.linux_net.set_device_trust(
        pf_ifname, vf_num, trusted)


@utils.synchronized('lock_vlan', external=True)
def ensure_vlan(vlan_num, bridge_interface, mac_address=None, mtu=None,
                interface=None):
    """Create a vlan unless it already exists."""
    if interface is None:
        interface = 'vlan%s' % vlan_num
    if not nova.privsep.linux_net.device_exists(interface):
        LOG.debug('Starting VLAN interface %s', interface)
        nova.privsep.linux_net.add_vlan(bridge_interface, interface,
                                        vlan_num)
        # (danwent) the bridge will inherit this address, so we want to
        # make sure it is the value set from the NetworkManager
        if mac_address:
            nova.privsep.linux_net.set_device_macaddr(
                interface, mac_address)
        nova.privsep.linux_net.set_device_enabled(interface)
    # NOTE(vish): set mtu every time to ensure that changes to mtu get
    #             propagated
    nova.privsep.linux_net.set_device_mtu(interface, mtu)
    return interface


@profiler.trace_cls("vif_driver")
class LibvirtGenericVIFDriver(object):
    """Generic VIF driver for libvirt networking."""

    def get_vif_devname(self, vif):
        if 'devname' in vif:
            return vif['devname']
        return ("nic" + vif['id'])[:network_model.NIC_NAME_LEN]

    def get_vif_model(self, image_meta=None, vif_model=None):

        model = vif_model

        # If the user has specified a 'vif_model' against the
        # image then honour that model
        if image_meta:
            model = osinfo.HardwareProperties(image_meta).network_model

        # If the virt type is KVM/QEMU/VZ(Parallels), then use virtio according
        # to the global config parameter
        if (model is None and CONF.libvirt.virt_type in
                ('kvm', 'qemu', 'parallels') and
                CONF.libvirt.use_virtio_for_bridges):
            model = network_model.VIF_MODEL_VIRTIO

        return model

    def get_base_config(self, instance, mac, image_meta,
                        inst_type, virt_type, vnic_type, host):
        # TODO(sahid): We should rewrite it. This method handles too
        # many unrelated things. We probably need to have a specific
        # virtio, vhost, vhostuser functions.

        conf = vconfig.LibvirtConfigGuestInterface()
        # Default to letting libvirt / the hypervisor choose the model
        model = None
        driver = None
        vhost_queues = None
        rx_queue_size = None

        # NOTE(stephenfin): Skip most things here as only apply to virtio
        # devices
        if vnic_type in network_model.VNIC_TYPES_DIRECT_PASSTHROUGH:
            designer.set_vif_guest_frontend_config(
                conf, mac, model, driver, vhost_queues, rx_queue_size)
            return conf

        # if model has already been defined,
        # image_meta contents will override it
        model = self.get_vif_model(image_meta=image_meta, vif_model=model)

        if not is_vif_model_valid_for_virt(virt_type, model):
            raise exception.UnsupportedHardware(model=model, virt=virt_type)

        # The rest of this only applies to virtio
        if model != network_model.VIF_MODEL_VIRTIO:
            designer.set_vif_guest_frontend_config(
                conf, mac, model, driver, vhost_queues, rx_queue_size)
            return conf

        # Workaround libvirt bug, where it mistakenly enables vhost mode, even
        # for non-KVM guests
        if virt_type == 'qemu':
            driver = 'qemu'

        if virt_type in ('kvm', 'parallels'):
            vhost_drv, vhost_queues = self._get_virtio_mq_settings(image_meta,
                                                                   inst_type)
            # TODO(sahid): It seems that we return driver 'vhost' even
            # for vhostuser interface where for vhostuser interface
            # the driver should be 'vhost-user'. That currently does
            # not create any issue since QEMU ignores the driver
            # argument for vhostuser interface but we should probably
            # fix that anyway. Also we should enforce that the driver
            # use vhost and not None.
            driver = vhost_drv or driver

        if driver == 'vhost' or driver is None:
            # vhost backend only supports update of RX queue size
            rx_queue_size, _ = self._get_virtio_queue_sizes(host)
            if rx_queue_size:
                # TODO(sahid): Specifically force driver to be vhost
                # that because if None we don't generate the XML
                # driver element needed to set the queue size
                # attribute. This can be removed when get_base_config
                # will be fixed and rewrite to set the correct
                # backend.
                driver = 'vhost'

        designer.set_vif_guest_frontend_config(
            conf, mac, model, driver, vhost_queues, rx_queue_size)

        return conf

    def get_base_hostdev_pci_config(self, vif):
        conf = vconfig.LibvirtConfigGuestHostdevPCI()
        pci_slot = vif['profile']['pci_slot']
        designer.set_vif_host_backend_hostdev_pci_config(conf, pci_slot)
        return conf

    def _get_virtio_mq_settings(self, image_meta, flavor):
        """A methods to set the number of virtio queues,
           if it has been requested in extra specs.
        """
        driver = None
        vhost_queues = None
        if self._requests_multiqueue(image_meta):
            driver = 'vhost'
            max_tap_queues = self._get_max_tap_queues()
            if max_tap_queues:
                vhost_queues = (max_tap_queues if flavor.vcpus > max_tap_queues
                    else flavor.vcpus)
            else:
                vhost_queues = flavor.vcpus

        return (driver, vhost_queues)

    def _requests_multiqueue(self, image_meta):
        """Check if multiqueue property is set in the image metadata."""

        if not isinstance(image_meta, objects.ImageMeta):
            image_meta = objects.ImageMeta.from_dict(image_meta)

        img_props = image_meta.properties

        if img_props.get('hw_vif_multiqueue_enabled'):
            return True

        return False

    def _get_max_tap_queues(self):
        # Note(sean-k-mooney): some linux distros have backported
        # changes for newer kernels which make the kernel version
        # number unreliable to determine the max queues supported
        # To address this without making the code distro dependent
        # we introduce a new config option and prefer it if set.
        if CONF.libvirt.max_queues:
            return CONF.libvirt.max_queues
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

    def get_veth_pair_names(self, iface_id):
        return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

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

    def get_config_802qbg(self, instance, vif, image_meta,
                          inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'],
                                    host)

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
                                    inst_type, virt_type, vif['vnic_type'],
                                    host)

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
                                    inst_type, virt_type, vif['vnic_type'],
                                    host)

        profile = vif["profile"]
        vif_details = vif["details"]
        net_type = 'direct'
        if vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
            net_type = 'hostdev'

        designer.set_vif_host_backend_hw_veb(
            conf, net_type, profile['pci_slot'],
            vif_details[network_model.VIF_DETAILS_VLAN])

        designer.set_vif_bandwidth_config(conf, inst_type)

        return conf

    def get_config_hostdev_physical(self, instance, vif, image_meta,
                                    inst_type, virt_type, host):
        return self.get_base_hostdev_pci_config(vif)

    def get_config_macvtap(self, instance, vif, image_meta,
                           inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'],
                                    host)

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
                                    inst_type, virt_type, vif['vnic_type'],
                                    host)

        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        designer.set_vif_bandwidth_config(conf, inst_type)

        return conf

    def get_config_midonet(self, instance, vif, image_meta,
                           inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'],
                                    host)

        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        return conf

    def get_config_tap(self, instance, vif, image_meta,
                       inst_type, virt_type, host):
        conf = self.get_base_config(instance, vif['address'], image_meta,
                                    inst_type, virt_type, vif['vnic_type'],
                                    host)

        dev = self.get_vif_devname(vif)
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

        self._set_mtu_config(vif, host, conf)

        return conf

    def get_config_ib_hostdev(self, instance, vif, image_meta,
                              inst_type, virt_type, host):
        return self.get_base_hostdev_pci_config(vif)

    def _get_virtio_queue_sizes(self, host):
        """Returns rx/tx queue sizes configured or (None, None)

        Based on tx/rx queue sizes configured on host (nova.conf). The
        methods check whether the versions of libvirt and QEMU are
        corrects.
        """
        # TODO(sahid): For vhostuser interface this function is called
        # from get_base_config and also from the method reponsible to
        # configure vhostuser interface meaning that the logs can be
        # duplicated. In future we want to rewrite get_base_config.
        rx, tx = CONF.libvirt.rx_queue_size, CONF.libvirt.tx_queue_size
        if tx and not host.has_min_version(
                MIN_LIBVIRT_TX_QUEUE_SIZE, MIN_QEMU_TX_QUEUE_SIZE):
            LOG.warning('Setting TX queue size requires libvirt %s and QEMU '
                        '%s version or greater.',
                        libvirt_utils.version_to_string(
                            MIN_LIBVIRT_TX_QUEUE_SIZE),
                        libvirt_utils.version_to_string(
                            MIN_QEMU_TX_QUEUE_SIZE))
            tx = None
        return rx, tx

    def _set_config_VIFGeneric(self, instance, vif, conf, host):
        dev = vif.vif_name
        designer.set_vif_host_backend_ethernet_config(conf, dev, host)

    def _set_config_VIFBridge(self, instance, vif, conf, host=None):
        conf.net_type = "bridge"
        conf.source_dev = vif.bridge_name
        conf.target_dev = vif.vif_name

    def _set_config_VIFOpenVSwitch(self, instance, vif, conf, host=None):
        conf.net_type = "bridge"
        conf.source_dev = vif.bridge_name
        conf.target_dev = vif.vif_name
        self._set_config_VIFPortProfile(instance, vif, conf)

    def _set_config_VIFVHostUser(self, instance, vif, conf, host=None):
        # TODO(sahid): We should never configure a driver backend for
        # vhostuser interface. Specifically override driver to use
        # None. This can be removed when get_base_config will be fixed
        # and rewrite to set the correct backend.
        conf.driver_name = None

        rx_queue_size, tx_queue_size = self._get_virtio_queue_sizes(host)
        designer.set_vif_host_backend_vhostuser_config(
            conf, vif.mode, vif.path, rx_queue_size, tx_queue_size)

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
        profile_name = vif.port_profile.obj_name()
        if profile_name == 'VIFPortProfileOpenVSwitch':
            self._set_config_VIFPortProfileOpenVSwitch(vif.port_profile, conf)
        else:
            raise exception.InternalError(
                _('Unsupported VIF port profile type %s') % profile_name)

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
                                    inst_type, virt_type, vnic_type,
                                    host)

        # Do the VIF type specific config
        if isinstance(vif, osv_vifs.VIFGeneric):
            self._set_config_VIFGeneric(instance, vif, conf, host)
        elif isinstance(vif, osv_vifs.VIFBridge):
            self._set_config_VIFBridge(instance, vif, conf, host)
        elif isinstance(vif, osv_vifs.VIFOpenVSwitch):
            self._set_config_VIFOpenVSwitch(instance, vif, conf, host)
        elif isinstance(vif, osv_vifs.VIFVHostUser):
            self._set_config_VIFVHostUser(instance, vif, conf, host)
        elif isinstance(vif, osv_vifs.VIFHostDevice):
            self._set_config_VIFHostDevice(instance, vif, conf, host)
        else:
            raise exception.InternalError(
                _("Unsupported VIF type %s") % vif.obj_name())

        # not all VIF types support bandwidth configuration
        # https://github.com/libvirt/libvirt/blob/568a41722/src/conf/netdev_bandwidth_conf.h#L38
        if vif.obj_name() not in ('VIFVHostUser', 'VIFHostDevice'):
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
        args = (instance, vif, image_meta, inst_type, virt_type, host)
        if vif_type == network_model.VIF_TYPE_IOVISOR:
            return self.get_config_iovisor(*args)
        elif vif_type == network_model.VIF_TYPE_802_QBG:
            return self.get_config_802qbg(*args)
        elif vif_type == network_model.VIF_TYPE_802_QBH:
            return self.get_config_802qbh(*args)
        elif vif_type == network_model.VIF_TYPE_HW_VEB:
            return self.get_config_hw_veb(*args)
        elif vif_type == network_model.VIF_TYPE_HOSTDEV:
            return self.get_config_hostdev_physical(*args)
        elif vif_type == network_model.VIF_TYPE_MACVTAP:
            return self.get_config_macvtap(*args)
        elif vif_type == network_model.VIF_TYPE_MIDONET:
            return self.get_config_midonet(*args)
        elif vif_type == network_model.VIF_TYPE_TAP:
            return self.get_config_tap(*args)
        elif vif_type == network_model.VIF_TYPE_IB_HOSTDEV:
            return self.get_config_ib_hostdev(*args)

        raise exception.InternalError(_('Unexpected vif_type=%s') % vif_type)

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

    def plug_hw_veb(self, instance, vif):
        # TODO(adrianc): The piece of code for MACVTAP can be removed once:
        #  1. neutron SR-IOV agent does not rely on the administrative mac
        #     as depicted in https://bugs.launchpad.net/neutron/+bug/1841067
        #  2. libvirt driver does not change mac address for macvtap VNICs
        #     or Alternatively does not rely on recreating libvirt's nodev
        #     name from the current mac address set on the netdevice.
        #     See: virt.libvrit.driver.LibvirtDriver._get_pcinet_info
        if vif['vnic_type'] == network_model.VNIC_TYPE_MACVTAP:
            set_vf_interface_vlan(
                vif['profile']['pci_slot'],
                mac_addr=vif['address'],
                vlan=vif['details'][network_model.VIF_DETAILS_VLAN])

        elif vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
            trusted = strutils.bool_from_string(
                vif['profile'].get('trusted', "False"))
            if trusted:
                set_vf_trusted(vif['profile']['pci_slot'], True)

    def plug_macvtap(self, instance, vif):
        vif_details = vif['details']
        vlan = vif_details.get(network_model.VIF_DETAILS_VLAN)
        if vlan:
            vlan_name = vif_details.get(
                                    network_model.VIF_DETAILS_MACVTAP_SOURCE)
            phys_if = vif_details.get(network_model.VIF_DETAILS_PHYS_INTERFACE)
            ensure_vlan(vlan, phys_if, interface=vlan_name)

    def plug_midonet(self, instance, vif):
        """Plug into MidoNet's network port

        Bind the vif to a MidoNet virtual port.
        """
        dev = self.get_vif_devname(vif)
        port_id = vif['id']
        try:
            nova.privsep.linux_net.create_tap_dev(dev)
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
        nova.privsep.linux_net.create_tap_dev(dev)
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
        image_meta = instance.image_meta
        vif_model = self.get_vif_model(image_meta=image_meta)
        # TODO(ganso): explore whether multiqueue works for other vif models
        # that go through this code path.
        multiqueue = (self._requests_multiqueue(image_meta) and
                      vif_model == network_model.VIF_MODEL_VIRTIO)
        nova.privsep.linux_net.create_tap_dev(dev, mac, multiqueue=multiqueue)
        network = vif.get('network')
        mtu = network.get_meta('mtu') if network else None
        nova.privsep.linux_net.set_device_mtu(dev, mtu)

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
        if vif_type == network_model.VIF_TYPE_IB_HOSTDEV:
            self.plug_ib_hostdev(instance, vif)
        elif vif_type == network_model.VIF_TYPE_HW_VEB:
            self.plug_hw_veb(instance, vif)
        elif vif_type == network_model.VIF_TYPE_MACVTAP:
            self.plug_macvtap(instance, vif)
        elif vif_type == network_model.VIF_TYPE_MIDONET:
            self.plug_midonet(instance, vif)
        elif vif_type == network_model.VIF_TYPE_IOVISOR:
            self.plug_iovisor(instance, vif)
        elif vif_type == network_model.VIF_TYPE_TAP:
            self.plug_tap(instance, vif)
        elif vif_type in {network_model.VIF_TYPE_802_QBG,
                          network_model.VIF_TYPE_802_QBH,
                          network_model.VIF_TYPE_HOSTDEV}:
            # These are no-ops
            pass
        else:
            raise exception.VirtualInterfacePlugException(
                _("Plug VIF failed because of unexpected "
                  "vif_type=%s") % vif_type)

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

    def unplug_hw_veb(self, instance, vif):
        # TODO(sean-k-mooney): remove in Train after backporting 0 mac
        # change as this should no longer be needed with libvirt >= 3.2.0.
        if vif['vnic_type'] == network_model.VNIC_TYPE_MACVTAP:
            # NOTE(sean-k-mooney): Retaining the vm mac on the vf
            # after unplugging the vif prevents the PF from transmitting
            # a packet with that destination address. This would create a
            # a network partition in the event a vm is migrated or the neuton
            # port is reused for another vm before the VF is reused.
            # The ip utility accepts the MAC 00:00:00:00:00:00 which can
            # be used to reset the VF mac when no longer in use by a vm.
            # As such we hardcode the 00:00:00:00:00:00 mac.
            set_vf_interface_vlan(vif['profile']['pci_slot'],
                                  mac_addr='00:00:00:00:00:00')
        elif vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
            if "trusted" in vif['profile']:
                set_vf_trusted(vif['profile']['pci_slot'], False)

    def unplug_midonet(self, instance, vif):
        """Unplug from MidoNet network port

        Unbind the vif from a MidoNet virtual port.
        """
        dev = self.get_vif_devname(vif)
        port_id = vif['id']
        try:
            nova.privsep.libvirt.unplug_midonet_vif(port_id)
            nova.privsep.linux_net.delete_net_dev(dev)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_tap(self, instance, vif):
        """Unplug a VIF_TYPE_TAP virtual interface."""
        dev = self.get_vif_devname(vif)
        try:
            nova.privsep.linux_net.delete_net_dev(dev)
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
            nova.privsep.linux_net.delete_net_dev(dev)
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
        if vif_type == network_model.VIF_TYPE_IB_HOSTDEV:
            self.unplug_ib_hostdev(instance, vif)
        elif vif_type == network_model.VIF_TYPE_HW_VEB:
            self.unplug_hw_veb(instance, vif)
        elif vif_type == network_model.VIF_TYPE_MIDONET:
            self.unplug_midonet(instance, vif)
        elif vif_type == network_model.VIF_TYPE_IOVISOR:
            self.unplug_iovisor(instance, vif)
        elif vif_type == network_model.VIF_TYPE_TAP:
            self.unplug_tap(instance, vif)
        elif vif_type in {network_model.VIF_TYPE_802_QBG,
                          network_model.VIF_TYPE_802_QBH,
                          network_model.VIF_TYPE_HOSTDEV,
                          network_model.VIF_TYPE_MACVTAP}:
            # These are no-ops
            pass
        else:
            # TODO(stephenfin): This should probably raise
            # VirtualInterfaceUnplugException
            raise exception.InternalError(
                _("Unplug VIF failed because of unexpected "
                  "vif_type=%s") % vif_type)

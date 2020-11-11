# Copyright (C) 2013 Red Hat, Inc.
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

"""
Policy based configuration of libvirt objects

This module provides helper APIs for populating the config.py
classes based on common operational needs / policies
"""


from nova.pci import utils as pci_utils


def set_vif_guest_frontend_config(conf, mac, model, driver, queues,
                                  rx_queue_size):
    """Populate a LibvirtConfigGuestInterface instance
    with guest frontend details.

    NOTE: @model, @driver, @queues and @rx_queue_size can be None.
    """
    conf.mac_addr = mac
    if model is not None:
        conf.model = model
    if driver is not None:
        conf.driver_name = driver
    if queues is not None:
        conf.vhost_queues = queues
    if rx_queue_size:
        conf.vhost_rx_queue_size = rx_queue_size


def set_vif_host_backend_ethernet_config(conf, tapname):
    """Populate a LibvirtConfigGuestInterface instance
    with host backend details for an externally configured
    host device.

    NB use of this configuration is discouraged by
    libvirt project and will mark domains as 'tainted'.
    """

    conf.net_type = "ethernet"
    conf.target_dev = tapname
    conf.script = None


def set_vif_host_backend_802qbg_config(conf, devname, managerid,
                                       typeid, typeidversion,
                                       instanceid, tapname=None):
    """Populate a LibvirtConfigGuestInterface instance
    with host backend details for an 802.1qbg device.
    """

    conf.net_type = "direct"
    conf.source_dev = devname
    conf.source_mode = "vepa"
    conf.vporttype = "802.1Qbg"
    conf.add_vport_param("managerid", managerid)
    conf.add_vport_param("typeid", typeid)
    conf.add_vport_param("typeidversion", typeidversion)
    conf.add_vport_param("instanceid", instanceid)
    if tapname:
        conf.target_dev = tapname


def set_vif_host_backend_802qbh_config(conf, net_type, devname, profileid,
                                       tapname=None):
    """Populate a LibvirtConfigGuestInterface instance
    with host backend details for an 802.1qbh device.
    """

    conf.net_type = net_type
    if net_type == 'direct':
        conf.source_mode = 'passthrough'
        conf.source_dev = pci_utils.get_ifname_by_pci_address(devname)
        conf.driver_name = 'vhost'
    else:
        conf.source_dev = devname
        conf.model = None
    conf.vporttype = "802.1Qbh"
    conf.add_vport_param("profileid", profileid)
    if tapname:
        conf.target_dev = tapname


def set_vif_host_backend_hw_veb(conf, net_type, devname, vlan,
                                tapname=None):
    """Populate a LibvirtConfigGuestInterface instance
    with host backend details for an device that supports hardware
    virtual ethernet bridge.
    """

    conf.net_type = net_type
    conf.vlan = vlan
    if net_type == 'direct':
        conf.source_mode = 'passthrough'
        conf.source_dev = pci_utils.get_ifname_by_pci_address(devname)
        conf.driver_name = 'vhost'
    else:  # net_type == network_model.VNIC_TYPE_DIRECT
        conf.source_dev = devname
        conf.model = None
    if tapname:
        conf.target_dev = tapname


def set_vif_host_backend_hostdev_pci_config(conf, pci_slot):
    """Populate a LibvirtConfigGuestHostdev instance with pci address data."""

    conf.domain, conf.bus, conf.slot, conf.function = (
        pci_utils.get_pci_address_fields(pci_slot))


def set_vif_host_backend_direct_config(conf, devname, mode="passthrough"):
    """Populate a LibvirtConfigGuestInterface instance
    with direct Interface.
    """

    conf.net_type = "direct"
    conf.source_mode = mode
    conf.source_dev = devname
    conf.model = "virtio"


def set_vif_host_backend_vhostuser_config(conf, mode, path, rx_queue_size,
                                          tx_queue_size, tapname=None):
    """Populate a LibvirtConfigGuestInterface instance
    with host backend details for vhostuser socket.

    NOTE: @rx_queue_size and @tx_queue_size can be None
    """
    conf.net_type = "vhostuser"
    conf.vhostuser_type = "unix"
    conf.vhostuser_mode = mode
    conf.vhostuser_path = path
    if rx_queue_size:
        conf.vhost_rx_queue_size = rx_queue_size
    if tx_queue_size:
        conf.vhost_tx_queue_size = tx_queue_size
    if tapname:
        conf.target_dev = tapname


def set_vif_mtu_config(conf, mtu):
    """Populate a LibvirtConfigGuestInterface instance
    with network mtu.
    """
    conf.mtu = mtu


def set_vif_bandwidth_config(conf, inst_type):
    """Config vif inbound/outbound bandwidth limit. parameters are
    set in instance_type_extra_specs table, key is in  the format
    quota:vif_inbound_average.
    """

    bandwidth_items = ['vif_inbound_average', 'vif_inbound_peak',
        'vif_inbound_burst', 'vif_outbound_average', 'vif_outbound_peak',
        'vif_outbound_burst']
    for key, value in inst_type.get('extra_specs', {}).items():
        scope = key.split(':')
        if len(scope) > 1 and scope[0] == 'quota':
            if scope[1] in bandwidth_items:
                setattr(conf, scope[1], value)


def set_numa_memnode(conf, guest_node_id, host_cell_id):
    """Prepares numa memory node config for the guest.
    """
    conf.cellid = guest_node_id
    conf.nodeset = [host_cell_id]
    conf.mode = "strict"


def set_vcpu_realtime_scheduler(conf, vcpus_rt, priority):
    """Prepares realtime config for the guest."""
    conf.vcpus = vcpus_rt
    conf.scheduler = "fifo"
    conf.priority = priority


def set_driver_iommu_for_sev(conf):
    for dev in conf.devices:
        if dev.uses_virtio:
            dev.driver_iommu = True

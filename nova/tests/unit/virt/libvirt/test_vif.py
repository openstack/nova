#    Copyright 2012 Nicira, Inc
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

import os

import fixtures
from lxml import etree
import mock
import os_vif
from os_vif import exception as osv_exception
from os_vif import objects as osv_objects
from os_vif.objects import fields as osv_fields
from oslo_concurrency import processutils
from oslo_config import cfg
import six

from nova import exception
from nova.network import linux_net
from nova.network import model as network_model
from nova import objects
from nova.pci import utils as pci_utils
from nova import test
from nova.tests.unit import matchers
from nova.tests.unit.virt import fakelibosinfo
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import host
from nova.virt.libvirt import vif

CONF = cfg.CONF

MIN_LIBVIRT_VHOSTUSER_MQ = vif.MIN_LIBVIRT_VHOSTUSER_MQ


class LibvirtVifTestCase(test.NoDBTestCase):

    gateway_bridge_4 = network_model.IP(address='101.168.1.1', type='gateway')
    dns_bridge_4 = network_model.IP(address='8.8.8.8', type=None)
    ips_bridge_4 = [network_model.IP(address='101.168.1.9', type=None)]
    subnet_bridge_4 = network_model.Subnet(
        cidr='101.168.1.0/24',
        dns=[dns_bridge_4],
        gateway=gateway_bridge_4,
        routes=None,
        dhcp_server='191.168.1.1')

    gateway_bridge_6 = network_model.IP(address='101:1db9::1', type='gateway')
    subnet_bridge_6 = network_model.Subnet(cidr='101:1db9::/64',
        dns=None,
        gateway=gateway_bridge_6,
        ips=None,
        routes=None)

    network_bridge = network_model.Network(id=uuids.network,
        bridge='br0',
        label=None,
        subnets=[subnet_bridge_4, subnet_bridge_6],
        bridge_interface='eth0',
        vlan=99, mtu=9000)

    vif_bridge = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_bridge,
        type=network_model.VIF_TYPE_BRIDGE,
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=None)

    network_bridge_neutron = network_model.Network(id=uuids.network,
        bridge=None,
        label=None,
        subnets=[subnet_bridge_4, subnet_bridge_6],
        bridge_interface='eth0',
        vlan=99)

    vif_bridge_neutron = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_bridge_neutron,
        type=None,
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=uuids.ovs)

    network_ovs = network_model.Network(id=uuids.network,
        bridge='br0',
        label=None,
        subnets=[subnet_bridge_4, subnet_bridge_6],
        bridge_interface=None,
        vlan=99, mtu=1000)

    network_ivs = network_model.Network(id=uuids.network,
        bridge='br0',
        label=None,
        subnets=[subnet_bridge_4, subnet_bridge_6],
        bridge_interface=None,
        vlan=99)

    vif_agilio_ovs = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        type=network_model.VIF_TYPE_AGILIO_OVS,
        details={'port_filter': False},
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=uuids.ovs)

    vif_agilio_ovs_direct = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        type=network_model.VIF_TYPE_AGILIO_OVS,
        vnic_type=network_model.VNIC_TYPE_DIRECT,
        ovs_interfaceid=uuids.ovs,
        devname='tap-xxx-yyy-zzz',
        profile={'pci_slot': '0000:0a:00.1'})

    vif_agilio_ovs_forwarder = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        type=network_model.VIF_TYPE_AGILIO_OVS,
        vnic_type=network_model.VNIC_TYPE_VIRTIO_FORWARDER,
        profile={'pci_slot': '0000:0a:00.1'},
        details={
            network_model.VIF_DETAILS_VHOSTUSER_MODE: 'client',
            network_model.VIF_DETAILS_VHOSTUSER_SOCKET: '/tmp/usv-xxx-yyy-zzz',
            network_model.VIF_DETAILS_VHOSTUSER_OVS_PLUG: True},
        ovs_interfaceid=uuids.ovs, mtu=1500)

    vif_ovs = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        type=network_model.VIF_TYPE_OVS,
        details={'port_filter': False},
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=uuids.ovs)

    vif_ovs_direct = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        vnic_type=network_model.VNIC_TYPE_DIRECT,
        profile={'pci_slot': '0000:0a:00.1'},
        type=network_model.VIF_TYPE_OVS,
        details={'port_filter': False},
        ovs_interfaceid=uuids.ovs)

    vif_ovs_filter_cap = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        type=network_model.VIF_TYPE_OVS,
        details={'port_filter': True},
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=uuids.ovs)

    vif_ovs_legacy = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        type=None,
        devname=None,
        ovs_interfaceid=None)

    vif_ivs = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ivs,
        type=network_model.VIF_TYPE_IVS,
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=uuids.ovs)

    vif_ivs_filter_cap = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ivs,
        type=network_model.VIF_TYPE_IVS,
        details={'port_filter': True},
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=uuids.ovs)

    vif_ivs_hybrid = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ivs,
        type=network_model.VIF_TYPE_IVS,
        details={
            'port_filter': True,
            'ovs_hybrid_plug': True},
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=uuids.ovs)

    vif_ivs_legacy = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_ovs,
        type=None,
        devname=None,
        ovs_interfaceid='aaa')

    vif_none = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_bridge,
        type=None,
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=None)

    network_8021 = network_model.Network(id=uuids.network,
        bridge=None,
        label=None,
        subnets=[subnet_bridge_4,
                 subnet_bridge_6],
        interface='eth0',
        vlan=99)

    vif_8021qbh = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_802_QBH,
        vnic_type=network_model.VNIC_TYPE_DIRECT,
        ovs_interfaceid=None,
        details={
            network_model.VIF_DETAILS_PROFILEID:
            'MyPortProfile'},
        profile={'pci_vendor_info': '1137:0043',
                 'pci_slot': '0000:0a:00.1',
                 'physical_network': 'phynet1'})

    vif_hw_veb = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_HW_VEB,
        vnic_type=network_model.VNIC_TYPE_DIRECT,
        ovs_interfaceid=None,
        details={
            network_model.VIF_DETAILS_VLAN: 100},
        profile={'pci_vendor_info': '1137:0043',
                 'pci_slot': '0000:0a:00.1',
                 'physical_network': 'phynet1'})

    vif_hostdev_physical = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_HOSTDEV,
        vnic_type=network_model.VNIC_TYPE_DIRECT_PHYSICAL,
        ovs_interfaceid=None,
        profile={'pci_vendor_info': '1137:0043',
                 'pci_slot': '0000:0a:00.1',
                 'physical_network': 'phynet1'})

    vif_hw_veb_macvtap = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_HW_VEB,
        vnic_type=network_model.VNIC_TYPE_MACVTAP,
        ovs_interfaceid=None,
        details={network_model.VIF_DETAILS_VLAN: 100},
        profile={'pci_vendor_info': '1137:0043',
                 'pci_slot': '0000:0a:00.1',
                 'physical_network': 'phynet1'})

    vif_8021qbg = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_802_QBG,
        ovs_interfaceid=None,
        qbg_params=network_model.VIF8021QbgParams(
        managerid="xxx-yyy-zzz",
        typeid="aaa-bbb-ccc",
        typeidversion="1",
        instanceid="ddd-eee-fff"))

    network_midonet = network_model.Network(id=uuids.network,
        label=None,
        bridge=None,
        subnets=[subnet_bridge_4],
        interface='eth0')

    network_vrouter = network_model.Network(id=uuids.network,
        label=None,
        bridge=None,
        subnets=[subnet_bridge_4, subnet_bridge_6],
        interface='eth0')

    vif_vrouter = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_vrouter,
        type=network_model.VIF_TYPE_VROUTER,
        devname='tap-xxx-yyy-zzz')

    vif_ib_hostdev = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_IB_HOSTDEV,
        vnic_type=network_model.VNIC_TYPE_DIRECT,
        ovs_interfaceid=None,
        details={network_model.VIF_DETAILS_VLAN: 100},
        profile={'pci_vendor_info': '1137:0043',
                 'pci_slot': '0000:0a:00.1',
                 'physical_network': 'phynet1'})

    vif_midonet = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_midonet,
        type=network_model.VIF_TYPE_MIDONET,
        devname='tap-xxx-yyy-zzz')

    vif_tap = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        type=network_model.VIF_TYPE_TAP,
        devname='tap-xxx-yyy-zzz')

    vif_iovisor = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_bridge,
        type=network_model.VIF_TYPE_IOVISOR,
        devname='tap-xxx-yyy-zzz',
        ovs_interfaceid=None)

    vif_vhostuser = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_bridge,
        type=network_model.VIF_TYPE_VHOSTUSER,
        details={
            network_model.VIF_DETAILS_VHOSTUSER_MODE: 'client',
            network_model.VIF_DETAILS_VHOSTUSER_SOCKET: '/tmp/vif-xxx-yyy-zzz'
        })

    vif_vhostuser_ovs = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_bridge,
        type=network_model.VIF_TYPE_VHOSTUSER,
        details={
            network_model.VIF_DETAILS_VHOSTUSER_MODE: 'client',
            network_model.VIF_DETAILS_VHOSTUSER_SOCKET: '/tmp/usv-xxx-yyy-zzz',
            network_model.VIF_DETAILS_VHOSTUSER_OVS_PLUG: True},
        ovs_interfaceid=uuids.ovs, mtu=1500)

    vif_vhostuser_no_path = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_bridge,
        type=network_model.VIF_TYPE_VHOSTUSER,
        details={network_model.VIF_DETAILS_VHOSTUSER_MODE: 'client'})

    vif_macvtap_vlan = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_MACVTAP,
        details={
            network_model.VIF_DETAILS_VLAN: 1,
            network_model.VIF_DETAILS_PHYS_INTERFACE: 'eth0',
            network_model.VIF_DETAILS_MACVTAP_SOURCE: 'eth0.1',
            network_model.VIF_DETAILS_MACVTAP_MODE: 'vepa'})

    vif_macvtap_flat = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_MACVTAP,
        details={
            network_model.VIF_DETAILS_PHYS_INTERFACE: 'eth0',
            network_model.VIF_DETAILS_MACVTAP_SOURCE: 'eth0',
            network_model.VIF_DETAILS_MACVTAP_MODE: 'bridge'})

    vif_macvtap_exception = network_model.VIF(id=uuids.vif,
        address='ca:fe:de:ad:be:ef',
        network=network_8021,
        type=network_model.VIF_TYPE_MACVTAP)

    instance = objects.Instance(id=1,
        uuid='f0000000-0000-0000-0000-000000000001',
        project_id=723)

    bandwidth = {
        'quota:vif_inbound_peak': '200',
        'quota:vif_outbound_peak': '20',
        'quota:vif_inbound_average': '100',
        'quota:vif_outbound_average': '10',
        'quota:vif_inbound_burst': '300',
        'quota:vif_outbound_burst': '30'
    }

    def setup_os_vif_objects(self):
        self.os_vif_network = osv_objects.network.Network(
            id="b82c1929-051e-481d-8110-4669916c7915",
            label="Demo Net",
            subnets=osv_objects.subnet.SubnetList(
                objects=[]))

        self.os_vif_bridge = osv_objects.vif.VIFBridge(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            plugin="linux_bridge",
            vif_name="nicdc065497-3c",
            bridge_name="br100",
            has_traffic_filtering=False,
            network=self.os_vif_network)

        self.os_vif_ovs_prof = osv_objects.vif.VIFPortProfileOpenVSwitch(
            interface_id="07bd6cea-fb37-4594-b769-90fc51854ee9",
            profile_id="fishfood")

        self.os_vif_repr_prof = osv_objects.vif.VIFPortProfileOVSRepresentor(
            interface_id="07bd6cea-fb37-4594-b769-90fc51854ee9",
            profile_id="fishfood",
            representor_name='nicdc065497-3c',
            representor_address='0000:0a:00.1')

        self.os_vif_agilio_ovs = osv_objects.vif.VIFOpenVSwitch(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            plugin="agilio_ovs",
            vif_name="nicdc065497-3c",
            bridge_name="br0",
            port_profile=self.os_vif_ovs_prof,
            network=self.os_vif_network)

        self.os_vif_agilio_forwarder = osv_objects.vif.VIFVHostUser(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            plugin="agilio_ovs",
            vif_name="nicdc065497-3c",
            path='/var/run/openvswitch/vhudc065497-3c',
            mode='client',
            port_profile=self.os_vif_repr_prof,
            network=self.os_vif_network)

        self.os_vif_agilio_direct = osv_objects.vif.VIFHostDevice(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            plugin="agilio_ovs",
            vif_name="nicdc065497-3c",
            dev_type=osv_fields.VIFHostDeviceDevType.ETHERNET,
            dev_address='0000:0a:00.1',
            port_profile=self.os_vif_repr_prof,
            network=self.os_vif_network)

        self.os_vif_ovs = osv_objects.vif.VIFOpenVSwitch(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            unplugin="linux_bridge",
            vif_name="nicdc065497-3c",
            bridge_name="br0",
            port_profile=self.os_vif_ovs_prof,
            network=self.os_vif_network)

        self.os_vif_ovs_hybrid = osv_objects.vif.VIFBridge(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            unplugin="linux_bridge",
            vif_name="nicdc065497-3c",
            bridge_name="br0",
            port_profile=self.os_vif_ovs_prof,
            has_traffic_filtering=False,
            network=self.os_vif_network)

        self.os_vif_vhostuser = osv_objects.vif.VIFVHostUser(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            plugin="openvswitch",
            vif_name="vhudc065497-3c",
            path='/var/run/openvswitch/vhudc065497-3c',
            mode='client',
            port_profile=self.os_vif_ovs_prof,
            network=self.os_vif_network)

        self.os_vif_hostdevice_ethernet = osv_objects.vif.VIFHostDevice(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            plugin="linux_bridge",
            vif_name="nicdc065497-3c",
            dev_type=osv_fields.VIFHostDeviceDevType.ETHERNET,
            dev_address='0000:0a:00.1',
            network=self.os_vif_network)

        self.os_vif_hostdevice_generic = osv_objects.vif.VIFHostDevice(
            id="dc065497-3c8d-4f44-8fb4-e1d33c16a536",
            address="22:52:25:62:e2:aa",
            plugin="linux_bridge",
            vif_name="nicdc065497-3c",
            dev_type=osv_fields.VIFHostDeviceDevType.GENERIC,
            dev_address='0000:0a:00.1',
            network=self.os_vif_network)

        self.os_vif_inst_info = osv_objects.instance_info.InstanceInfo(
            uuid="d5b1090c-9e00-4fa4-9504-4b1494857970",
            name="instance-000004da",
            project_id="2f37d7f6-e51a-4a1f-8b6e-b0917ffc8390")

    def setUp(self):
        super(LibvirtVifTestCase, self).setUp()
        self.useFixture(fakelibvirt.FakeLibvirtFixture(stub_os_vif=False))
        self.flags(firewall_driver=None)
        # os_vif.initialize is typically done in nova-compute startup
        os_vif.initialize()
        self.setup_os_vif_objects()
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stub_out('nova.utils.execute', fake_execute)

    def _get_node(self, xml):
        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        return ret[0]

    def _assertMacEquals(self, node, vif):
        mac = node.find("mac").get("address")
        self.assertEqual(mac, vif['address'])

    def _assertTypeEquals(self, node, type, attr, source, br_want,
                          prefix=None):
        self.assertEqual(node.get("type"), type)
        br_name = node.find(attr).get(source)
        if prefix is None:
            self.assertEqual(br_name, br_want)
        else:
            self.assertTrue(br_name.startswith(prefix))

    def _assertTypeAndMacEquals(self, node, type, attr, source, vif,
                                br_want=None, size=0, prefix=None):
        ret = node.findall("filterref")
        self.assertEqual(len(ret), size)
        self._assertTypeEquals(node, type, attr, source, br_want,
                               prefix)
        self._assertMacEquals(node, vif)

    def _assertModel(self, xml, model_want=None, driver_want=None):
        node = self._get_node(xml)
        if model_want is None:
            ret = node.findall("model")
            self.assertEqual(len(ret), 0)
        else:
            model = node.find("model").get("type")
            self.assertEqual(model, model_want)
        if driver_want is None:
            ret = node.findall("driver")
            self.assertEqual(len(ret), 0)
        else:
            driver = node.find("driver").get("name")
            self.assertEqual(driver, driver_want)

    def _assertTypeAndPciEquals(self, node, type, vif):
        self.assertEqual(node.get("type"), type)
        self._assertPciEqual(node, vif, type="pci")

    def _assertPciEqual(self, node, vif, type=None):
        address = node.find("source").find("address")
        if type:
            addr_type = address.get("type")
            self.assertEqual(type, addr_type)
        pci_slot = "%(domain)s:%(bus)s:%(slot)s.%(func)s" % {
                     'domain': address.get("domain")[2:],
                     'bus': address.get("bus")[2:],
                     'slot': address.get("slot")[2:],
                     'func': address.get("function")[2:]}

        pci_slot_want = vif['profile']['pci_slot']
        self.assertEqual(pci_slot, pci_slot_want)

    def _assertXmlEqual(self, expectedXmlstr, actualXmlstr):
        self.assertThat(actualXmlstr, matchers.XMLMatches(expectedXmlstr))

    def _get_conf(self):
        conf = vconfig.LibvirtConfigGuest()
        conf.virt_type = "qemu"
        conf.name = "fake-name"
        conf.uuid = "fake-uuid"
        conf.memory = 100 * 1024
        conf.vcpus = 4
        return conf

    def _get_instance_xml(self, driver, vif, image_meta=None, flavor=None,
                          has_min_libvirt_version=True):
        if flavor is None:
            flavor = objects.Flavor(name='m1.small',
                                memory_mb=128,
                                vcpus=1,
                                root_gb=0,
                                ephemeral_gb=0,
                                swap=0,
                                extra_specs=dict(self.bandwidth),
                                deleted_at=None,
                                deleted=0,
                                created_at=None, flavorid=1,
                                is_public=True, vcpu_weight=None,
                                id=2, disabled=False, rxtx_factor=1.0)

        conf = self._get_conf()
        hostimpl = host.Host("qemu:///system")
        with mock.patch.object(hostimpl, 'has_min_version',
                               return_value=has_min_libvirt_version):
            nic = driver.get_config(self.instance, vif, image_meta,
                                    flavor, CONF.libvirt.virt_type,
                                    hostimpl)
        conf.add_device(nic)
        return conf.to_xml()

    def _test_virtio_multiqueue(self, vcpus, want_queues):
        self.flags(use_virtio_for_bridges=True,
                   virt_type='kvm',
                   group='libvirt')

        flavor = objects.Flavor(name='m1.small',
                    memory_mb=128,
                    vcpus=vcpus,
                    root_gb=0,
                    ephemeral_gb=0,
                    swap=0,
                    deleted_at=None,
                    deleted=0,
                    created_at=None, flavorid=1,
                    is_public=True, vcpu_weight=None,
                    id=2, disabled=False, rxtx_factor=1.0)

        d = vif.LibvirtGenericVIFDriver()
        image_meta = objects.ImageMeta.from_dict(
            {'properties': {'hw_vif_model': 'virtio',
                            'hw_vif_multiqueue_enabled': 'true'}})
        xml = self._get_instance_xml(d, self.vif_bridge,
                                     image_meta, flavor)

        node = self._get_node(xml)
        driver = node.find("driver").get("name")
        self.assertEqual(driver, 'vhost')
        queues = node.find("driver").get("queues")
        self.assertEqual(queues, want_queues)

    def test_virtio_multiqueue(self):
        self._test_virtio_multiqueue(4, '4')

    @mock.patch('os.uname', return_value=('Linux', '', '2.6.32-21-generic'))
    def test_virtio_multiqueue_in_kernel_2(self, mock_uname):
        self._test_virtio_multiqueue(10, '1')

    @mock.patch('os.uname', return_value=('Linux', '', '3.19.0-47-generic'))
    def test_virtio_multiqueue_in_kernel_3(self, mock_uname):
        self._test_virtio_multiqueue(10, '8')

    @mock.patch('os.uname', return_value=('Linux', '', '4.2.0-35-generic'))
    def test_virtio_multiqueue_in_kernel_4(self, mock_uname):
        self._test_virtio_multiqueue(10, '10')

    @mock.patch.object(host.Host, "has_min_version")
    def test_vhostuser_os_vif_multiqueue(self, has_min_version):
        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        image_meta = objects.ImageMeta.from_dict(
            {'properties': {'hw_vif_model': 'virtio',
                            'hw_vif_multiqueue_enabled': 'true'}})
        flavor = objects.Flavor(name='m1.small',
                    memory_mb=128,
                    vcpus=4,
                    root_gb=0,
                    ephemeral_gb=0,
                    swap=0,
                    deleted_at=None,
                    deleted=0,
                    created_at=None, flavorid=1,
                    is_public=True, vcpu_weight=None,
                    id=2, disabled=False, rxtx_factor=1.0)
        conf = d.get_base_config(None, 'ca:fe:de:ad:be:ef', image_meta,
                                 flavor, 'kvm', 'normal')
        self.assertEqual(4, conf.vhost_queues)
        self.assertEqual('vhost', conf.driver_name)

        has_min_version.return_value = True
        d._set_config_VIFVHostUser(self.instance, self.os_vif_vhostuser,
                                   conf, hostimpl)
        self.assertEqual(4, conf.vhost_queues)
        self.assertEqual('vhost', conf.driver_name)
        has_min_version.assert_called_once_with(MIN_LIBVIRT_VHOSTUSER_MQ)

        has_min_version.return_value = False
        d._set_config_VIFVHostUser(self.instance, self.os_vif_vhostuser,
                                   conf, hostimpl)
        self.assertIsNone(conf.vhost_queues)
        self.assertIsNone(conf.driver_name)

    def test_multiple_nics(self):
        conf = self._get_conf()
        # Tests multiple nic configuration and that target_dev is
        # set for each
        nics = [{'net_type': 'bridge',
                 'mac_addr': '00:00:00:00:00:0b',
                 'source_dev': 'b_source_dev',
                 'target_dev': 'b_target_dev'},
                {'net_type': 'ethernet',
                 'mac_addr': '00:00:00:00:00:0e',
                 'source_dev': 'e_source_dev',
                 'target_dev': 'e_target_dev'},
                {'net_type': 'direct',
                 'mac_addr': '00:00:00:00:00:0d',
                 'source_dev': 'd_source_dev',
                 'target_dev': 'd_target_dev'}]

        for nic in nics:
            nic_conf = vconfig.LibvirtConfigGuestInterface()
            nic_conf.net_type = nic['net_type']
            nic_conf.target_dev = nic['target_dev']
            nic_conf.mac_addr = nic['mac_addr']
            nic_conf.source_dev = nic['source_dev']
            conf.add_device(nic_conf)

        xml = conf.to_xml()
        doc = etree.fromstring(xml)
        for nic in nics:
            path = "./devices/interface/[@type='%s']" % nic['net_type']
            node = doc.find(path)
            self.assertEqual(nic['net_type'], node.get("type"))
            self.assertEqual(nic['mac_addr'],
                             node.find("mac").get("address"))
            self.assertEqual(nic['target_dev'],
                             node.find("target").get("dev"))

    def test_model_novirtio(self):
        self.flags(use_virtio_for_bridges=False,
                   virt_type='kvm',
                   group='libvirt')

        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_bridge)
        self._assertModel(xml)

    def test_model_kvm(self):
        self.flags(use_virtio_for_bridges=True,
                   virt_type='kvm',
                   group='libvirt')

        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_bridge)
        self._assertModel(xml, network_model.VIF_MODEL_VIRTIO)

    def test_model_parallels(self):
        self.flags(use_virtio_for_bridges=True,
                   virt_type='parallels',
                   group='libvirt')

        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_bridge)
        self._assertModel(xml, network_model.VIF_MODEL_VIRTIO)

    def test_model_kvm_qemu_parallels_custom(self):
        for virt in ('kvm', 'qemu', 'parallels'):
            self.flags(use_virtio_for_bridges=True,
                       virt_type=virt,
                       group='libvirt')

            d = vif.LibvirtGenericVIFDriver()
            if virt == 'parallels':
                supported = (network_model.VIF_MODEL_RTL8139,
                             network_model.VIF_MODEL_E1000)
            elif virt == 'qemu':
                supported = (network_model.VIF_MODEL_LAN9118,
                             network_model.VIF_MODEL_NE2K_PCI,
                             network_model.VIF_MODEL_PCNET,
                             network_model.VIF_MODEL_RTL8139,
                             network_model.VIF_MODEL_E1000,
                             network_model.VIF_MODEL_SPAPR_VLAN)
            else:
                supported = (network_model.VIF_MODEL_NE2K_PCI,
                             network_model.VIF_MODEL_PCNET,
                             network_model.VIF_MODEL_RTL8139,
                             network_model.VIF_MODEL_E1000,
                             network_model.VIF_MODEL_SPAPR_VLAN)
            for model in supported:
                image_meta = objects.ImageMeta.from_dict(
                    {'properties': {'hw_vif_model': model}})
                xml = self._get_instance_xml(d, self.vif_bridge,
                                             image_meta)
                self._assertModel(xml, model)

    @mock.patch.object(vif.designer, 'set_vif_guest_frontend_config')
    def test_model_with_osinfo(self, mock_set):
        self.flags(use_virtio_for_bridges=True,
                   virt_type='kvm',
                   group='libvirt')
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.osinfo.libosinfo',
            fakelibosinfo))
        d = vif.LibvirtGenericVIFDriver()
        image_meta = {'properties': {'os_name': 'fedora22'}}
        image_meta = objects.ImageMeta.from_dict(image_meta)
        d.get_base_config(None, 'ca:fe:de:ad:be:ef', image_meta,
                          None, 'kvm', 'normal')
        mock_set.assert_called_once_with(mock.ANY, 'ca:fe:de:ad:be:ef',
                                         'virtio', None, None)

    @mock.patch.object(vif.designer, 'set_vif_guest_frontend_config')
    def test_model_sriov_multi_queue_not_set(self, mock_set):
        self.flags(use_virtio_for_bridges=True,
                   virt_type='kvm',
                   group='libvirt')
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.osinfo.libosinfo',
            fakelibosinfo))
        d = vif.LibvirtGenericVIFDriver()
        image_meta = {'properties': {'os_name': 'fedora22'}}
        image_meta = objects.ImageMeta.from_dict(image_meta)
        conf = d.get_base_config(None, 'ca:fe:de:ad:be:ef', image_meta,
                                 None, 'kvm', 'direct')
        mock_set.assert_called_once_with(mock.ANY, 'ca:fe:de:ad:be:ef',
                                         'virtio', None, None)
        self.assertIsNone(conf.vhost_queues)
        self.assertIsNone(conf.driver_name)

    def _test_model_qemu(self, *vif_objs, **kw):
        libvirt_version = kw.get('libvirt_version')
        self.flags(use_virtio_for_bridges=True,
                   virt_type='qemu',
                   group='libvirt')

        for vif_obj in vif_objs:
            d = vif.LibvirtGenericVIFDriver()
            if libvirt_version is not None:
                d.libvirt_version = libvirt_version

            xml = self._get_instance_xml(d, vif_obj)

            doc = etree.fromstring(xml)

            bandwidth = doc.find('./devices/interface/bandwidth')
            self.assertIsNotNone(bandwidth)

            inbound = bandwidth.find('inbound')
            self.assertEqual(inbound.get("average"),
                             self.bandwidth['quota:vif_inbound_average'])
            self.assertEqual(inbound.get("peak"),
                             self.bandwidth['quota:vif_inbound_peak'])
            self.assertEqual(inbound.get("burst"),
                             self.bandwidth['quota:vif_inbound_burst'])

            outbound = bandwidth.find('outbound')
            self.assertEqual(outbound.get("average"),
                             self.bandwidth['quota:vif_outbound_average'])
            self.assertEqual(outbound.get("peak"),
                             self.bandwidth['quota:vif_outbound_peak'])
            self.assertEqual(outbound.get("burst"),
                             self.bandwidth['quota:vif_outbound_burst'])

            self._assertModel(xml, network_model.VIF_MODEL_VIRTIO, "qemu")

    def test_model_qemu_no_firewall(self):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        self._test_model_qemu(
            self.vif_bridge,
            self.vif_8021qbg,
            self.vif_iovisor,
            self.vif_ovs,
        )

    def test_model_qemu_iptables(self):
        self.flags(firewall_driver="nova.virt.firewall.IptablesFirewallDriver")
        self._test_model_qemu(
            self.vif_bridge,
            self.vif_ovs,
            self.vif_ivs,
            self.vif_8021qbg,
            self.vif_iovisor
        )

    def test_model_xen(self):
        self.flags(use_virtio_for_bridges=True,
                   virt_type='xen',
                   group='libvirt')

        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_bridge)
        self._assertModel(xml)

    def test_generic_driver_none(self):
        d = vif.LibvirtGenericVIFDriver()
        self.assertRaises(exception.NovaException,
                          self._get_instance_xml,
                          d,
                          self.vif_none)

    def _check_bridge_driver(self, d, vif, br_want):
        xml = self._get_instance_xml(d, vif)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     self.vif_bridge, br_want, 1)

    def test_generic_driver_bridge(self):
        d = vif.LibvirtGenericVIFDriver()
        self._check_bridge_driver(d,
                                  self.vif_bridge,
                                  self.vif_bridge['network']['bridge'])

    def _check_ivs_ethernet_driver(self, d, vif, dev_prefix):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, vif)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.vif_ivs, prefix=dev_prefix)
        script = node.find("script")
        self.assertIsNone(script)

    @mock.patch('nova.privsep.libvirt.bridge_delete_interface')
    @mock.patch('nova.privsep.libvirt.toggle_interface')
    @mock.patch('nova.privsep.libvirt.delete_bridge')
    def test_unplug_ivs_ethernet(self, delete_bridge, toggle_interface,
                                 bridge_delete_interface):
        d = vif.LibvirtGenericVIFDriver()
        with mock.patch.object(linux_net, 'delete_ivs_vif_port') as delete:
            delete.side_effect = processutils.ProcessExecutionError
            d.unplug(self.instance, self.vif_ivs)

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(pci_utils, 'get_ifname_by_pci_address')
    @mock.patch.object(pci_utils, 'get_vf_num_by_pci_address', return_value=1)
    def _test_hw_veb_op(self, op, vlan, mock_get_vf_num, mock_get_ifname,
                        mock_execute):
        mock_get_ifname.side_effect = ['eth1', 'eth13']
        exit_code = [0, 2, 254]
        port_state = 'up' if vlan > 0 else 'down'
        calls = {
            'get_ifname':
                [mock.call(self.vif_hw_veb_macvtap['profile']['pci_slot'],
                           pf_interface=True),
                 mock.call(self.vif_hw_veb_macvtap['profile']['pci_slot'])],
            'get_vf_num':
                [mock.call(self.vif_hw_veb_macvtap['profile']['pci_slot'])],
            'execute': [mock.call('ip', 'link', 'set', 'eth1',
                                  'vf', 1, 'mac',
                                  self.vif_hw_veb_macvtap['address'],
                                  'vlan', vlan,
                                  run_as_root=True,
                                  check_exit_code=exit_code),
                        mock.call('ip', 'link', 'set',
                                  'eth13', 'address',
                                  self.vif_hw_veb_macvtap['address'],
                                  port_state,
                                  run_as_root=True,
                                  check_exit_code=exit_code)]
        }
        op(self.instance, self.vif_hw_veb_macvtap)
        mock_get_ifname.assert_has_calls(calls['get_ifname'])
        mock_get_vf_num.assert_has_calls(calls['get_vf_num'])
        mock_execute.assert_has_calls(calls['execute'])

    def test_plug_hw_veb(self):
        d = vif.LibvirtGenericVIFDriver()
        self._test_hw_veb_op(
            d.plug,
            self.vif_hw_veb_macvtap['details'][network_model.VIF_DETAILS_VLAN])

    def test_unplug_hw_veb(self):
        d = vif.LibvirtGenericVIFDriver()
        self._test_hw_veb_op(d.unplug, 0)

    def test_plug_ivs_hybrid(self):
        with test.nested(
                mock.patch.object(linux_net, 'device_exists',
                                  return_value=False),
                mock.patch.object(linux_net, '_create_veth_pair'),
                mock.patch.object(linux_net, 'create_ivs_vif_port'),
                mock.patch.object(os.path, 'exists', return_value=True),
                mock.patch('nova.privsep.libvirt.disable_multicast_snooping'),
                mock.patch('nova.privsep.libvirt.disable_ipv6'),
                mock.patch('nova.privsep.libvirt.add_bridge'),
                mock.patch('nova.privsep.libvirt.zero_bridge_forward_delay'),
                mock.patch('nova.privsep.libvirt.disable_bridge_stp'),
                mock.patch('nova.privsep.libvirt.toggle_interface'),
                mock.patch('nova.privsep.libvirt.bridge_add_interface')
        ) as (device_exists, _create_veth_pair, create_ivs_vif_port,
              path_exists, disable_multicast_snooping, disable_ipv6,
              add_bridge, zero_bridge_forward_delay, disable_bridge_stp,
              toggle_interface, bridge_add_interface):
            d = vif.LibvirtGenericVIFDriver()
            d.plug(self.instance, self.vif_ivs)

            qvo_want = "qvo" + self.vif_ivs['id']
            qvo_want = qvo_want[:network_model.NIC_NAME_LEN]
            qbr_want = "qbr" + self.vif_ivs['id']
            qbr_want = qbr_want[:network_model.NIC_NAME_LEN]
            qvb_want = "qvb" + self.vif_ivs['id']
            qvb_want = qvb_want[:network_model.NIC_NAME_LEN]

            device_exists.assert_has_calls([mock.call(qbr_want),
                                            mock.call(qvo_want)])
            _create_veth_pair.assert_has_calls(
                [mock.call(qvb_want, qvo_want, None)])
            create_ivs_vif_port.assert_has_calls(
                [mock.call(qvo_want, uuids.ovs,
                           'ca:fe:de:ad:be:ef',
                           'f0000000-0000-0000-0000-000000000001')])

            disable_multicast_snooping.assert_has_calls(
                [mock.call(qbr_want)])
            disable_ipv6.assert_has_calls([mock.call(qbr_want)])
            add_bridge.assert_has_calls([mock.call(qbr_want)])
            zero_bridge_forward_delay.assert_has_calls(
                [mock.call(qbr_want)])
            disable_bridge_stp.assert_has_calls([mock.call(qbr_want)])
            toggle_interface.assert_has_calls(
                [mock.call(qbr_want, 'up')])
            bridge_add_interface.assert_has_calls(
                [mock.call(qbr_want, qvb_want)])

    def test_unplug_ivs_hybrid(self):
        with test.nested(
                mock.patch.object(utils, 'execute'),
                mock.patch.object(linux_net, 'delete_ivs_vif_port'),
                mock.patch('nova.privsep.libvirt.bridge_delete_interface'),
                mock.patch('nova.privsep.libvirt.toggle_interface'),
                mock.patch('nova.privsep.libvirt.delete_bridge')
        ) as (execute, delete_ivs_vif_port, bridge_delete_interface,
              toggle_interface, delete_bridge):
            d = vif.LibvirtGenericVIFDriver()
            d.unplug(self.instance, self.vif_ivs)

            qvo_want = "qvo" + self.vif_ivs['id']
            qvo_want = qvo_want[:network_model.NIC_NAME_LEN]
            qbr_want = "qbr" + self.vif_ivs['id']
            qbr_want = qbr_want[:network_model.NIC_NAME_LEN]
            qvb_want = "qvb" + self.vif_ivs['id']
            qvb_want = qvb_want[:network_model.NIC_NAME_LEN]

            delete_ivs_vif_port.assert_has_calls([mock.call(qvo_want)])
            bridge_delete_interface.assert_has_calls(
                [mock.call(qbr_want, qvb_want)])
            toggle_interface.assert_has_calls(
                [mock.call(qbr_want, 'down')])
            delete_bridge.assert_has_calls([mock.call(qbr_want)])

    @mock.patch('nova.privsep.libvirt.bridge_delete_interface',
                side_effect=processutils.ProcessExecutionError)
    def test_unplug_ivs_hybrid_bridge_does_not_exist(self, bdi):
        d = vif.LibvirtGenericVIFDriver()
        d.unplug(self.instance, self.vif_ivs)

    @mock.patch('nova.privsep.libvirt.unplug_plumgrid_vif',
                side_effect=processutils.ProcessExecutionError)
    def test_unplug_iovisor(self, mock_unplug):
        d = vif.LibvirtGenericVIFDriver()
        d.unplug(self.instance, self.vif_iovisor)

    @mock.patch('nova.network.linux_net.device_exists')
    @mock.patch('nova.privsep.libvirt.plug_plumgrid_vif')
    def test_plug_iovisor(self, mock_plug, device_exists):
        device_exists.return_value = True
        d = vif.LibvirtGenericVIFDriver()
        d.plug(self.instance, self.vif_iovisor)
        mock_plug.assert_has_calls(
            [mock.call('tap-xxx-yyy-zzz',
                       self.vif_iovisor['id'],
                       self.vif_iovisor['address'],
                       self.vif_iovisor['network']['id'],
                       self.instance.project_id)])

    @mock.patch('nova.privsep.libvirt.unplug_contrail_vif')
    def test_unplug_vrouter_with_details(self, mock_unplug_contrail):
        d = vif.LibvirtGenericVIFDriver()
        d.unplug(self.instance, self.vif_vrouter)
        mock_unplug_contrail.assert_called_once_with(self.vif_vrouter['id'])

    @mock.patch('nova.privsep.libvirt.plug_contrail_vif')
    def test_plug_vrouter_with_details(self, mock_plug_contrail):
        d = vif.LibvirtGenericVIFDriver()
        instance = mock.Mock()
        instance.name = 'instance-name'
        instance.uuid = '46a4308b-e75a-4f90-a34a-650c86ca18b2'
        instance.project_id = 'b168ea26fa0c49c1a84e1566d9565fa5'
        instance.display_name = 'instance1'
        instance.image_meta = objects.ImageMeta.from_dict({'properties': {}})
        with mock.patch.object(utils, 'execute') as execute:
            d.plug(instance, self.vif_vrouter)
            execute.assert_has_calls([
                mock.call('ip', 'tuntap', 'add', 'tap-xxx-yyy-zzz', 'mode',
                    'tap', run_as_root=True, check_exit_code=[0, 2, 254]),
                mock.call('ip', 'link', 'set', 'tap-xxx-yyy-zzz', 'up',
                    run_as_root=True, check_exit_code=[0, 2, 254])])
            mock_plug_contrail.called_once_with(
                instance.project_id, instance.uuid, instance.display_name,
                self.vif_vrouter['id'], self.vif_vrouter['network']['id'],
                'NovaVMPort', self.vif_vrouter['devname'],
                self.vif_vrouter['address'], '0.0.0.0', None)

    @mock.patch('nova.network.linux_net.create_tap_dev')
    @mock.patch('nova.privsep.libvirt.plug_contrail_vif')
    def test_plug_vrouter_with_details_multiqueue(
            self, mock_plug_contrail, mock_create_tap_dev):
        d = vif.LibvirtGenericVIFDriver()
        instance = mock.Mock()
        instance.name = 'instance-name'
        instance.uuid = '46a4308b-e75a-4f90-a34a-650c86ca18b2'
        instance.project_id = 'b168ea26fa0c49c1a84e1566d9565fa5'
        instance.display_name = 'instance1'
        instance.image_meta = objects.ImageMeta.from_dict({
            'properties': {'hw_vif_multiqueue_enabled': True}})
        instance.flavor.vcpus = 2
        d.plug(instance, self.vif_vrouter)
        mock_create_tap_dev.assert_called_once_with('tap-xxx-yyy-zzz',
                                                    multiqueue=True)

        mock_plug_contrail.called_once_with(
                instance.project_id, instance.uuid, instance.display_name,
                self.vif_vrouter['id'], self.vif_vrouter['network']['id'],
                'NovaVMPort', self.vif_vrouter['devname'],
                self.vif_vrouter['address'], '0.0.0.0', None)

    def test_ivs_ethernet_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        self._check_ivs_ethernet_driver(d,
                                        self.vif_ivs,
                                        "tap")

    def _check_ivs_virtualport_driver(self, d, vif, want_iface_id):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, vif)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     vif, vif['devname'])

    def _check_ovs_virtualport_driver(self, d, vif, want_iface_id):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, vif)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     vif, "br0")
        vp = node.find("virtualport")
        self.assertEqual(vp.get("type"), "openvswitch")
        iface_id_found = False
        for p_elem in vp.findall("parameters"):
            iface_id = p_elem.get("interfaceid", None)
            if iface_id:
                self.assertEqual(iface_id, want_iface_id)
                iface_id_found = True

        self.assertTrue(iface_id_found)

    def test_generic_ovs_virtualport_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        want_iface_id = self.vif_ovs['ovs_interfaceid']
        self._check_ovs_virtualport_driver(d,
                                           self.vif_ovs,
                                           want_iface_id)

    def test_generic_ivs_virtualport_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        want_iface_id = self.vif_ivs['ovs_interfaceid']
        self._check_ivs_virtualport_driver(d,
                                           self.vif_ivs,
                                           want_iface_id)

    def test_ivs_plug_with_nova_firewall(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = "qbr" + self.vif_ivs['id']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        xml = self._get_instance_xml(d, self.vif_ivs)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     self.vif_ivs, br_want, 1)

    def test_ivs_plug_with_port_filter_direct_no_nova_firewall(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = "qbr" + self.vif_ivs_hybrid['id']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, self.vif_ivs_hybrid)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     self.vif_ivs_hybrid, br_want, 0)

    def test_ivs_plug_with_port_hybrid_no_nova_firewall(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = self.vif_ivs_filter_cap['devname']
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, self.vif_ivs_filter_cap)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.vif_ivs_filter_cap, br_want, 0)

    def test_direct_plug_with_port_filter_cap_no_nova_firewall(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = self.vif_midonet['devname']
        xml = self._get_instance_xml(d, self.vif_ovs_filter_cap)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "target", "dev",
                                     self.vif_ovs_filter_cap, br_want)

    def _check_neutron_hybrid_driver(self, d, vif, br_want):
        self.flags(firewall_driver="nova.virt.firewall.IptablesFirewallDriver")
        xml = self._get_instance_xml(d, vif)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     vif, br_want, 1)

    def test_generic_hybrid_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = "qbr" + self.vif_ovs['id']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self._check_neutron_hybrid_driver(d,
                                          self.vif_ovs,
                                          br_want)

    def test_ivs_hybrid_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = "qbr" + self.vif_ivs['id']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self._check_neutron_hybrid_driver(d,
                                          self.vif_ivs,
                                          br_want)

    def test_ib_hostdev_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_ib_hostdev)
        doc = etree.fromstring(xml)
        node = doc.findall('./devices/hostdev')[0]
        self.assertEqual(1, len(node))
        self._assertPciEqual(node, self.vif_ib_hostdev)

    def test_midonet_ethernet_vif_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        br_want = self.vif_midonet['devname']
        xml = self._get_instance_xml(d, self.vif_midonet)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.vif_midonet, br_want)

    def test_tap_ethernet_vif_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = self.vif_tap['devname']
        xml = self._get_instance_xml(d, self.vif_tap)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.vif_tap, br_want)

    @mock.patch('nova.network.linux_net.device_exists')
    def test_plug_tap(self, device_exists):
        device_exists.return_value = True
        d = vif.LibvirtGenericVIFDriver()
        d.plug(self.instance, self.vif_tap)

    def test_unplug_tap(self):
        d = vif.LibvirtGenericVIFDriver()
        d.unplug(self.instance, self.vif_tap)

    def test_generic_8021qbh_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_8021qbh)
        node = self._get_node(xml)
        self._assertTypeAndPciEquals(node, "hostdev", self.vif_8021qbh)
        self._assertMacEquals(node, self.vif_8021qbh)
        vp = node.find("virtualport")
        self.assertEqual(vp.get("type"), "802.1Qbh")
        profile_id_found = False
        for p_elem in vp.findall("parameters"):
            details = self.vif_8021qbh["details"]
            profile_id = p_elem.get("profileid", None)
            if profile_id:
                self.assertEqual(profile_id,
                                 details[network_model.VIF_DETAILS_PROFILEID])
                profile_id_found = True

        self.assertTrue(profile_id_found)

    def test_hw_veb_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_hw_veb)
        node = self._get_node(xml)
        self._assertTypeAndPciEquals(node, "hostdev", self.vif_hw_veb)
        self._assertMacEquals(node, self.vif_hw_veb)

        conf = vconfig.LibvirtConfigGuestInterface()
        conf.parse_dom(node)
        self.assertEqual(conf.vlan, self.vif_hw_veb["details"]["vlan"])

    def test_hostdev_physical_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_hostdev_physical)
        doc = etree.fromstring(xml)
        node = doc.findall('./devices/hostdev')[0]
        self.assertEqual(1, len(node))
        self._assertPciEqual(node, self.vif_hostdev_physical)

    @mock.patch.object(pci_utils, 'get_ifname_by_pci_address',
                       return_value='eth1')
    @mock.patch.object(host.Host, "has_min_version", return_value=True)
    def test_hw_veb_driver_macvtap(self, ver_mock, mock_get_ifname):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_hw_veb_macvtap)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"), "direct")
        self._assertTypeEquals(node, "direct", "source",
                               "dev", "eth1")
        self._assertTypeEquals(node, "direct", "source",
                               "mode", "passthrough")
        self._assertMacEquals(node, self.vif_hw_veb_macvtap)
        vlan = node.find("vlan").find("tag").get("id")
        vlan_want = self.vif_hw_veb["details"]["vlan"]
        self.assertEqual(int(vlan), vlan_want)

    @mock.patch.object(pci_utils, 'get_ifname_by_pci_address',
                       return_value='eth1')
    @mock.patch.object(host.Host, "has_min_version", return_value=False)
    def test_hw_veb_driver_macvtap_pre_vlan_support(self, ver_mock,
                                                    mock_get_ifname):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(
            d, self.vif_hw_veb_macvtap,
            has_min_libvirt_version=ver_mock.return_value)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"), "direct")
        self._assertTypeEquals(node, "direct", "source",
                               "dev", "eth1")
        self._assertTypeEquals(node, "direct", "source",
                               "mode", "passthrough")
        self._assertMacEquals(node, self.vif_hw_veb_macvtap)
        vlan = node.find("vlan")
        self.assertIsNone(vlan)

    def test_driver_macvtap_vlan(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_macvtap_vlan)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"), "direct")
        self._assertTypeEquals(node, "direct", "source",
                               "dev", "eth0.1")
        self._assertTypeEquals(node, "direct", "source",
                               "mode", "vepa")
        self._assertMacEquals(node, self.vif_macvtap_vlan)

    def test_driver_macvtap_flat(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_macvtap_flat)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"), "direct")
        self._assertTypeEquals(node, "direct", "source",
                               "dev", "eth0")
        self._assertTypeEquals(node, "direct", "source",
                               "mode", "bridge")
        self._assertMacEquals(node, self.vif_macvtap_flat)

    def test_driver_macvtap_exception(self):
        d = vif.LibvirtGenericVIFDriver()
        e = self.assertRaises(exception.VifDetailsMissingMacvtapParameters,
                          self._get_instance_xml,
                          d,
                          self.vif_macvtap_exception)
        self.assertIn('macvtap_source', six.text_type(e))
        self.assertIn('macvtap_mode', six.text_type(e))
        self.assertIn('physical_interface', six.text_type(e))

    @mock.patch.object(linux_net.LinuxBridgeInterfaceDriver, 'ensure_vlan')
    def test_macvtap_plug_vlan(self, ensure_vlan_mock):
        d = vif.LibvirtGenericVIFDriver()
        d.plug(self.instance, self.vif_macvtap_vlan)
        ensure_vlan_mock.assert_called_once_with(1, 'eth0', interface='eth0.1')

    @mock.patch.object(linux_net.LinuxBridgeInterfaceDriver, 'ensure_vlan')
    def test_macvtap_plug_flat(self, ensure_vlan_mock):
        d = vif.LibvirtGenericVIFDriver()
        d.plug(self.instance, self.vif_macvtap_flat)
        self.assertFalse(ensure_vlan_mock.called)

    def test_generic_iovisor_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        br_want = self.vif_ivs['devname']
        xml = self._get_instance_xml(d, self.vif_ivs)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.vif_ivs, br_want)

    def test_generic_8021qbg_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_8021qbg)

        node = self._get_node(xml)
        self._assertTypeEquals(node, "direct", "source", "dev", "eth0")
        self._assertMacEquals(node, self.vif_8021qbg)

        vp = node.find("virtualport")
        self.assertEqual(vp.get("type"), "802.1Qbg")
        manager_id_found = False
        type_id_found = False
        typeversion_id_found = False
        instance_id_found = False
        for p_elem in vp.findall("parameters"):
            wantparams = self.vif_8021qbg['qbg_params']
            manager_id = p_elem.get("managerid", None)
            type_id = p_elem.get("typeid", None)
            typeversion_id = p_elem.get("typeidversion", None)
            instance_id = p_elem.get("instanceid", None)
            if manager_id:
                self.assertEqual(manager_id,
                                 wantparams['managerid'])
                manager_id_found = True
            if type_id:
                self.assertEqual(type_id,
                                 wantparams['typeid'])
                type_id_found = True
            if typeversion_id:
                self.assertEqual(typeversion_id,
                                 wantparams['typeidversion'])
                typeversion_id_found = True
            if instance_id:
                self.assertEqual(instance_id,
                                 wantparams['instanceid'])
                instance_id_found = True

        self.assertTrue(manager_id_found)
        self.assertTrue(type_id_found)
        self.assertTrue(typeversion_id_found)
        self.assertTrue(instance_id_found)

    def test_vhostuser_driver(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_vhostuser)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"),
                         network_model.VIF_TYPE_VHOSTUSER)

        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "mode", "client")
        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "path", "/tmp/vif-xxx-yyy-zzz")
        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "type", "unix")
        self._assertMacEquals(node, self.vif_vhostuser)
        self._assertModel(xml, network_model.VIF_MODEL_VIRTIO)

    def test_vhostuser_no_queues(self):
        d = vif.LibvirtGenericVIFDriver()
        image_meta = objects.ImageMeta.from_dict(
            {'properties': {'hw_vif_model': 'virtio',
                            'hw_vif_multiqueue_enabled': 'true'}})
        xml = self._get_instance_xml(d, self.vif_vhostuser, image_meta,
                                     has_min_libvirt_version=False)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"),
                         network_model.VIF_TYPE_VHOSTUSER)
        self._assertMacEquals(node, self.vif_vhostuser)
        driver = node.find("driver")
        self.assertIsNone(driver, None)

    def test_vhostuser_driver_no_path(self):
        d = vif.LibvirtGenericVIFDriver()

        self.assertRaises(exception.VifDetailsMissingVhostuserSockPath,
                          self._get_instance_xml,
                          d,
                          self.vif_vhostuser_no_path)

    def test_vhostuser_driver_ovs(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d,
                                     self.vif_vhostuser_ovs)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"),
                         network_model.VIF_TYPE_VHOSTUSER)

        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "mode", "client")
        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "path", "/tmp/usv-xxx-yyy-zzz")
        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "type", "unix")
        self._assertMacEquals(node, self.vif_vhostuser_ovs)
        self._assertModel(xml, network_model.VIF_MODEL_VIRTIO)

    def test_ovs_direct(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_ovs_direct)
        node = self._get_node(xml)
        self._assertTypeAndPciEquals(node,
                                     "hostdev",
                                     self.vif_ovs_direct)
        self._assertMacEquals(node, self.vif_ovs_direct)

    def test_agilio_ovs_direct(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_agilio_ovs_direct)
        node = self._get_node(xml)
        self._assertTypeAndPciEquals(node,
                                     "hostdev",
                                     self.vif_agilio_ovs_direct)
        self._assertMacEquals(node, self.vif_agilio_ovs_direct)

    def test_agilio_ovs_forwarder(self):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d,
                                     self.vif_agilio_ovs_forwarder)
        node = self._get_node(xml)
        self.assertEqual(node.get("type"),
                         network_model.VIF_TYPE_VHOSTUSER)

        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "mode", "client")
        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "path", "/tmp/usv-xxx-yyy-zzz")
        self._assertTypeEquals(node, network_model.VIF_TYPE_VHOSTUSER,
                               "source", "type", "unix")
        self._assertMacEquals(node, self.vif_agilio_ovs_forwarder)
        self._assertModel(xml, network_model.VIF_MODEL_VIRTIO)

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    @mock.patch.object(os_vif, "plug")
    def _test_osvif_plug(self, fail, mock_plug,
                         mock_convert_vif, mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_bridge
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        if fail:
            mock_plug.side_effect = osv_exception.ExceptionBase("Wibble")
            self.assertRaises(exception.NovaException,
                              d.plug,
                              self.instance, self.vif_bridge)
        else:
            d.plug(self.instance, self.vif_bridge)

        mock_plug.assert_called_once_with(self.os_vif_bridge,
                                          self.os_vif_inst_info)

    def test_osvif_plug_normal(self):
        self._test_osvif_plug(False)

    def test_osvif_plug_fail(self):
        self._test_osvif_plug(True)

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    @mock.patch.object(os_vif, "unplug")
    def _test_osvif_unplug(self, fail, mock_unplug,
                         mock_convert_vif, mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_bridge
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        if fail:
            mock_unplug.side_effect = osv_exception.ExceptionBase("Wibble")
            self.assertRaises(exception.NovaException,
                              d.unplug,
                              self.instance, self.vif_bridge)
        else:
            d.unplug(self.instance, self.vif_bridge)

        mock_unplug.assert_called_once_with(self.os_vif_bridge,
                                            self.os_vif_inst_info)

    def test_osvif_unplug_normal(self):
        self._test_osvif_unplug(False)

    def test_osvif_unplug_fail(self):
        self._test_osvif_unplug(True)

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_bridge(self, mock_convert_vif, mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_bridge
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_bridge,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="bridge">
                <mac address="22:52:25:62:e2:aa"/>
                <model type="virtio"/>
                <source bridge="br100"/>
                <target dev="nicdc065497-3c"/>
                <filterref
                 filter="nova-instance-instance-00000001-22522562e2aa"/>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_bridge_nofw(self, mock_convert_vif,
                                       mock_convert_inst):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")

        mock_convert_vif.return_value = self.os_vif_bridge
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_bridge,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="bridge">
                <mac address="22:52:25:62:e2:aa"/>
                <model type="virtio"/>
                <source bridge="br100"/>
                <target dev="nicdc065497-3c"/>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_agilio_ovs_fallthrough(self, mock_convert_vif,
                                                  mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_agilio_ovs
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_agilio_ovs,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="bridge">
                <mac address="22:52:25:62:e2:aa"/>
                <model type="virtio"/>
                <source bridge="br0"/>
                <target dev="nicdc065497-3c"/>
                <virtualport type="openvswitch">
                    <parameters
                     interfaceid="07bd6cea-fb37-4594-b769-90fc51854ee9"/>
                </virtualport>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_agilio_ovs_forwarder(self, mock_convert_vif,
                                                mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_agilio_forwarder
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_agilio_ovs_forwarder,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="vhostuser">
              <mac address="22:52:25:62:e2:aa"/>
              <model type="virtio"/>
              <source mode="client"
               path="/var/run/openvswitch/vhudc065497-3c" type="unix"/>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_agilio_ovs_direct(self, mock_convert_vif,
                                             mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_agilio_direct
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_agilio_ovs_direct,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="hostdev" managed="yes">
              <mac address="22:52:25:62:e2:aa"/>
              <source>
                <address type="pci" domain="0x0000"
                 bus="0x0a" slot="0x00" function="0x1"/>
              </source>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_ovs(self, mock_convert_vif, mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_ovs
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_ovs,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="bridge">
                <mac address="22:52:25:62:e2:aa"/>
                <model type="virtio"/>
                <source bridge="br0"/>
                <target dev="nicdc065497-3c"/>
                <virtualport type="openvswitch">
                    <parameters
                     interfaceid="07bd6cea-fb37-4594-b769-90fc51854ee9"/>
                </virtualport>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_ovs_hybrid(self, mock_convert_vif,
                                      mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_ovs_hybrid
        mock_convert_inst.return_value = self.os_vif_inst_info

        d = vif.LibvirtGenericVIFDriver()
        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_ovs,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="bridge">
                <mac address="22:52:25:62:e2:aa"/>
                <model type="virtio"/>
                <source bridge="br0"/>
                <target dev="nicdc065497-3c"/>
                <filterref
                 filter="nova-instance-instance-00000001-22522562e2aa"/>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_hostdevice_ethernet(self, mock_convert_vif,
                                               mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_hostdevice_ethernet
        mock_convert_inst.return_value = self.os_vif_inst_info

        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()
        cfg = d.get_config(self.instance, self.vif_bridge,
                           image_meta, flavor,
                           CONF.libvirt.virt_type,
                           hostimpl)

        self._assertXmlEqual("""
            <interface type="hostdev" managed="yes">
              <mac address="22:52:25:62:e2:aa"/>
              <source>
                <address type="pci" domain="0x0000"
                 bus="0x0a" slot="0x00" function="0x1"/>
              </source>
            </interface>""", cfg.to_xml())

    @mock.patch("nova.network.os_vif_util.nova_to_osvif_instance")
    @mock.patch("nova.network.os_vif_util.nova_to_osvif_vif")
    def test_config_os_vif_hostdevice_generic(self, mock_convert_vif,
                                              mock_convert_inst):
        mock_convert_vif.return_value = self.os_vif_hostdevice_generic
        mock_convert_inst.return_value = self.os_vif_inst_info

        hostimpl = host.Host("qemu:///system")
        flavor = objects.Flavor(name='m1.small')
        image_meta = objects.ImageMeta.from_dict({})
        d = vif.LibvirtGenericVIFDriver()

        self.assertRaises(exception.InternalError,
                          d.get_config, self.instance, self.vif_bridge,
                          image_meta, flavor, CONF.libvirt.virt_type,
                          hostimpl)

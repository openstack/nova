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

from lxml import etree
import mock
from oslo_concurrency import processutils
from oslo_config import cfg
import six

from nova import exception
from nova.network import linux_net
from nova.network import model as network_model
from nova import objects
from nova.pci import utils as pci_utils
from nova import test
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import host
from nova.virt.libvirt import vif

CONF = cfg.CONF


class LibvirtVifTestCase(test.NoDBTestCase):

    gateway_bridge_4 = network_model.IP(address='101.168.1.1', type='gateway')
    dns_bridge_4 = network_model.IP(address='8.8.8.8', type=None)
    ips_bridge_4 = [network_model.IP(address='101.168.1.9', type=None)]
    subnet_bridge_4 = network_model.Subnet(cidr='101.168.1.0/24',
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

    network_bridge = network_model.Network(id='network-id-xxx-yyy-zzz',
                                           bridge='br0',
                                           label=None,
                                           subnets=[subnet_bridge_4,
                                                    subnet_bridge_6],
                                           bridge_interface='eth0',
                                           vlan=99)

    vif_bridge = network_model.VIF(id='vif-xxx-yyy-zzz',
                                   address='ca:fe:de:ad:be:ef',
                                   network=network_bridge,
                                   type=network_model.VIF_TYPE_BRIDGE,
                                   devname='tap-xxx-yyy-zzz',
                                   ovs_interfaceid=None)

    network_bridge_neutron = network_model.Network(id='network-id-xxx-yyy-zzz',
                                                   bridge=None,
                                                   label=None,
                                                   subnets=[subnet_bridge_4,
                                                            subnet_bridge_6],
                                                   bridge_interface='eth0',
                                                   vlan=99)

    vif_bridge_neutron = network_model.VIF(id='vif-xxx-yyy-zzz',
                                           address='ca:fe:de:ad:be:ef',
                                           network=network_bridge_neutron,
                                           type=None,
                                           devname='tap-xxx-yyy-zzz',
                                           ovs_interfaceid='aaa-bbb-ccc')

    network_ovs = network_model.Network(id='network-id-xxx-yyy-zzz',
                                        bridge='br0',
                                        label=None,
                                        subnets=[subnet_bridge_4,
                                                 subnet_bridge_6],
                                        bridge_interface=None,
                                        vlan=99)

    network_ivs = network_model.Network(id='network-id-xxx-yyy-zzz',
                                        bridge='br0',
                                        label=None,
                                        subnets=[subnet_bridge_4,
                                                 subnet_bridge_6],
                                        bridge_interface=None,
                                        vlan=99)

    vif_ovs = network_model.VIF(id='vif-xxx-yyy-zzz',
                                address='ca:fe:de:ad:be:ef',
                                network=network_ovs,
                                type=network_model.VIF_TYPE_OVS,
                                devname='tap-xxx-yyy-zzz',
                                ovs_interfaceid='aaa-bbb-ccc')

    vif_ovs_hybrid = network_model.VIF(id='vif-xxx-yyy-zzz',
                                       address='ca:fe:de:ad:be:ef',
                                       network=network_ovs,
                                       type=network_model.VIF_TYPE_OVS,
                                       details={'ovs_hybrid_plug': True,
                                                'port_filter': True},
                                       devname='tap-xxx-yyy-zzz',
                                       ovs_interfaceid='aaa-bbb-ccc')

    vif_ovs_filter_cap = network_model.VIF(id='vif-xxx-yyy-zzz',
                                           address='ca:fe:de:ad:be:ef',
                                           network=network_ovs,
                                           type=network_model.VIF_TYPE_OVS,
                                           details={'port_filter': True},
                                           devname='tap-xxx-yyy-zzz',
                                           ovs_interfaceid='aaa-bbb-ccc')

    vif_ovs_legacy = network_model.VIF(id='vif-xxx-yyy-zzz',
                                       address='ca:fe:de:ad:be:ef',
                                       network=network_ovs,
                                       type=None,
                                       devname=None,
                                       ovs_interfaceid=None)

    vif_ivs = network_model.VIF(id='vif-xxx-yyy-zzz',
                                address='ca:fe:de:ad:be:ef',
                                network=network_ivs,
                                type=network_model.VIF_TYPE_IVS,
                                devname='tap-xxx-yyy-zzz',
                                ovs_interfaceid='aaa-bbb-ccc')

    vif_ivs_legacy = network_model.VIF(id='vif-xxx-yyy-zzz',
                                       address='ca:fe:de:ad:be:ef',
                                       network=network_ovs,
                                       type=None,
                                       devname=None,
                                       ovs_interfaceid='aaa')

    vif_ivs_filter_direct = network_model.VIF(id='vif-xxx-yyy-zzz',
                                              address='ca:fe:de:ad:be:ef',
                                              network=network_ivs,
                                              type=network_model.VIF_TYPE_IVS,
                                              details={'port_filter': True},
                                              devname='tap-xxx-yyy-zzz',
                                              ovs_interfaceid='aaa-bbb-ccc')

    vif_ivs_filter_hybrid = network_model.VIF(id='vif-xxx-yyy-zzz',
                                              address='ca:fe:de:ad:be:ef',
                                              network=network_ivs,
                                              type=network_model.VIF_TYPE_IVS,
                                              details={
                                                  'port_filter': True,
                                                  'ovs_hybrid_plug': True},
                                              devname='tap-xxx-yyy-zzz',
                                              ovs_interfaceid='aaa-bbb-ccc')

    vif_none = network_model.VIF(id='vif-xxx-yyy-zzz',
                                 address='ca:fe:de:ad:be:ef',
                                 network=network_bridge,
                                 type=None,
                                 devname='tap-xxx-yyy-zzz',
                                 ovs_interfaceid=None)

    network_8021 = network_model.Network(id='network-id-xxx-yyy-zzz',
                                         bridge=None,
                                         label=None,
                                         subnets=[subnet_bridge_4,
                                                  subnet_bridge_6],
                                         interface='eth0',
                                         vlan=99)

    vif_8021qbh = network_model.VIF(id='vif-xxx-yyy-zzz',
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

    vif_hw_veb = network_model.VIF(id='vif-xxx-yyy-zzz',
                                   address='ca:fe:de:ad:be:ef',
                                   network=network_8021,
                                   type=network_model.VIF_TYPE_HW_VEB,
                                   vnic_type=network_model.VNIC_TYPE_DIRECT,
                                   ovs_interfaceid=None,
                                   details={
                                       network_model.VIF_DETAILS_VLAN: '100'},
                                   profile={'pci_vendor_info': '1137:0043',
                                            'pci_slot': '0000:0a:00.1',
                                            'physical_network': 'phynet1'})

    vif_hw_veb_macvtap = network_model.VIF(id='vif-xxx-yyy-zzz',
                                    address='ca:fe:de:ad:be:ef',
                                    network=network_8021,
                                    type=network_model.VIF_TYPE_HW_VEB,
                                    vnic_type=network_model.VNIC_TYPE_MACVTAP,
                                    ovs_interfaceid=None,
                                    details={
                                      network_model.VIF_DETAILS_VLAN: '100'},
                                    profile={'pci_vendor_info': '1137:0043',
                                             'pci_slot': '0000:0a:00.1',
                                             'physical_network': 'phynet1'})

    vif_8021qbg = network_model.VIF(id='vif-xxx-yyy-zzz',
                                    address='ca:fe:de:ad:be:ef',
                                    network=network_8021,
                                    type=network_model.VIF_TYPE_802_QBG,
                                    ovs_interfaceid=None,
                                    qbg_params=network_model.VIF8021QbgParams(
                                    managerid="xxx-yyy-zzz",
                                    typeid="aaa-bbb-ccc",
                                    typeidversion="1",
                                    instanceid="ddd-eee-fff"))

    network_midonet = network_model.Network(id='network-id-xxx-yyy-zzz',
                                            label=None,
                                            bridge=None,
                                            subnets=[subnet_bridge_4],
                                            interface='eth0')

    network_vrouter = network_model.Network(id='network-id-xxx-yyy-zzz',
                                            label=None,
                                            bridge=None,
                                            subnets=[subnet_bridge_4,
                                                     subnet_bridge_6],
                                            interface='eth0')

    vif_vrouter = network_model.VIF(id='vif-xxx-yyy-zzz',
                                    address='ca:fe:de:ad:be:ef',
                                    network=network_vrouter,
                                    type=network_model.VIF_TYPE_VROUTER,
                                    devname='tap-xxx-yyy-zzz')

    vif_ib_hostdev = network_model.VIF(id='vif-xxx-yyy-zzz',
                                   address='ca:fe:de:ad:be:ef',
                                   network=network_8021,
                                   type=network_model.VIF_TYPE_IB_HOSTDEV,
                                   vnic_type=network_model.VNIC_TYPE_DIRECT,
                                   ovs_interfaceid=None,
                                   details={
                                       network_model.VIF_DETAILS_VLAN: '100'},
                                   profile={'pci_vendor_info': '1137:0043',
                                            'pci_slot': '0000:0a:00.1',
                                            'physical_network': 'phynet1'})

    vif_midonet = network_model.VIF(id='vif-xxx-yyy-zzz',
                                    address='ca:fe:de:ad:be:ef',
                                    network=network_midonet,
                                    type=network_model.VIF_TYPE_MIDONET,
                                    devname='tap-xxx-yyy-zzz')

    vif_tap = network_model.VIF(id='vif-xxx-yyy-zzz',
                                address='ca:fe:de:ad:be:ef',
                                type=network_model.VIF_TYPE_TAP,
                                devname='tap-xxx-yyy-zzz')

    vif_iovisor = network_model.VIF(id='vif-xxx-yyy-zzz',
                                   address='ca:fe:de:ad:be:ef',
                                   network=network_bridge,
                                   type=network_model.VIF_TYPE_IOVISOR,
                                   devname='tap-xxx-yyy-zzz',
                                   ovs_interfaceid=None)

    vif_vhostuser = network_model.VIF(id='vif-xxx-yyy-zzz',
              address='ca:fe:de:ad:be:ef',
              network=network_bridge,
              type=network_model.VIF_TYPE_VHOSTUSER,
              details = {network_model.VIF_DETAILS_VHOSTUSER_MODE: 'client',
                         network_model.VIF_DETAILS_VHOSTUSER_SOCKET:
                                                    '/tmp/vif-xxx-yyy-zzz'}
              )

    vif_vhostuser_ovs = network_model.VIF(id='vif-xxx-yyy-zzz',
              address='ca:fe:de:ad:be:ef',
              network=network_bridge,
              type=network_model.VIF_TYPE_VHOSTUSER,
              details = {network_model.VIF_DETAILS_VHOSTUSER_MODE: 'client',
                         network_model.VIF_DETAILS_VHOSTUSER_SOCKET:
                                                     '/tmp/usv-xxx-yyy-zzz',
                         network_model.VIF_DETAILS_VHOSTUSER_OVS_PLUG: True},
              ovs_interfaceid='aaa-bbb-ccc'
              )

    vif_vhostuser_no_path = network_model.VIF(id='vif-xxx-yyy-zzz',
          address='ca:fe:de:ad:be:ef',
          network=network_bridge,
          type=network_model.VIF_TYPE_VHOSTUSER,
          details = {network_model.VIF_DETAILS_VHOSTUSER_MODE: 'client'})

    vif_macvtap_vlan = network_model.VIF(id='vif-xxx-yyy-zzz',
          address='ca:fe:de:ad:be:ef',
          network=network_8021,
          type=network_model.VIF_TYPE_MACVTAP,
          details={network_model.VIF_DETAILS_VLAN: '1',
                   network_model.VIF_DETAILS_PHYS_INTERFACE: 'eth0',
                   network_model.VIF_DETAILS_MACVTAP_SOURCE: 'eth0.1',
                   network_model.VIF_DETAILS_MACVTAP_MODE: 'vepa'})

    vif_macvtap_flat = network_model.VIF(id='vif-xxx-yyy-zzz',
          address='ca:fe:de:ad:be:ef',
          network=network_8021,
          type=network_model.VIF_TYPE_MACVTAP,
          details={network_model.VIF_DETAILS_PHYS_INTERFACE: 'eth0',
                   network_model.VIF_DETAILS_MACVTAP_SOURCE: 'eth0',
                   network_model.VIF_DETAILS_MACVTAP_MODE: 'bridge'})

    vif_macvtap_exception = network_model.VIF(id='vif-xxx-yyy-zzz',
          address='ca:fe:de:ad:be:ef',
          network=network_8021,
          type=network_model.VIF_TYPE_MACVTAP)

    instance = objects.Instance(id=1,
                                uuid='f0000000-0000-0000-0000-000000000001')

    bandwidth = {
        'quota:vif_inbound_peak': '200',
        'quota:vif_outbound_peak': '20',
        'quota:vif_inbound_average': '100',
        'quota:vif_outbound_average': '10',
        'quota:vif_inbound_burst': '300',
        'quota:vif_outbound_burst': '30'
    }

    def setUp(self):
        super(LibvirtVifTestCase, self).setUp()
        self.flags(allow_same_net_traffic=True)
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)

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

    def _get_conf(self):
        conf = vconfig.LibvirtConfigGuest()
        conf.virt_type = "qemu"
        conf.name = "fake-name"
        conf.uuid = "fake-uuid"
        conf.memory = 100 * 1024
        conf.vcpus = 4
        return conf

    def _get_instance_xml(self, driver, vif, image_meta=None, flavor=None):
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
        nic = driver.get_config(self.instance, vif, image_meta,
                                flavor, CONF.libvirt.virt_type,
                                hostimpl)
        conf.add_device(nic)
        return conf.to_xml()

    def test_virtio_multiqueue(self):
        self.flags(use_virtio_for_bridges=True,
                   virt_type='kvm',
                   group='libvirt')

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
        self.assertEqual(queues, '4')

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

    def test_model_kvm_qemu_custom(self):
        for virt in ('kvm', 'qemu'):
            self.flags(use_virtio_for_bridges=True,
                       virt_type=virt,
                       group='libvirt')

            d = vif.LibvirtGenericVIFDriver()
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
            self.assertNotEqual(bandwidth, None)

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
        script = node.find("script").get("path")
        self.assertEqual(script, "")

    def test_unplug_ivs_ethernet(self):
        d = vif.LibvirtGenericVIFDriver()
        with mock.patch.object(linux_net, 'delete_ivs_vif_port') as delete:
            delete.side_effect = processutils.ProcessExecutionError
            d.unplug_ivs_ethernet(None, self.vif_ovs)

    def test_plug_ovs_hybrid(self):
        calls = {
            'device_exists': [mock.call('qbrvif-xxx-yyy'),
                              mock.call('qvovif-xxx-yyy')],
            '_create_veth_pair': [mock.call('qvbvif-xxx-yyy',
                                            'qvovif-xxx-yyy')],
            'execute': [mock.call('brctl', 'addbr', 'qbrvif-xxx-yyy',
                                  run_as_root=True),
                        mock.call('brctl', 'setfd', 'qbrvif-xxx-yyy', 0,
                                  run_as_root=True),
                        mock.call('brctl', 'stp', 'qbrvif-xxx-yyy', 'off',
                                  run_as_root=True),
                        mock.call('tee', ('/sys/class/net/qbrvif-xxx-yyy'
                                          '/bridge/multicast_snooping'),
                                  process_input='0', run_as_root=True,
                                  check_exit_code=[0, 1]),
                        mock.call('ip', 'link', 'set', 'qbrvif-xxx-yyy', 'up',
                                  run_as_root=True),
                        mock.call('brctl', 'addif', 'qbrvif-xxx-yyy',
                                  'qvbvif-xxx-yyy', run_as_root=True)],
            'create_ovs_vif_port': [mock.call(
                                    'br0', 'qvovif-xxx-yyy', 'aaa-bbb-ccc',
                                    'ca:fe:de:ad:be:ef',
                                    'f0000000-0000-0000-0000-000000000001')]
        }
        with test.nested(
                mock.patch.object(linux_net, 'device_exists',
                                  return_value=False),
                mock.patch.object(utils, 'execute'),
                mock.patch.object(linux_net, '_create_veth_pair'),
                mock.patch.object(linux_net, 'create_ovs_vif_port')
        ) as (device_exists, execute, _create_veth_pair, create_ovs_vif_port):
            d = vif.LibvirtGenericVIFDriver()
            d.plug_ovs_hybrid(self.instance, self.vif_ovs)
            device_exists.assert_has_calls(calls['device_exists'])
            _create_veth_pair.assert_has_calls(calls['_create_veth_pair'])
            execute.assert_has_calls(calls['execute'])
            create_ovs_vif_port.assert_has_calls(calls['create_ovs_vif_port'])

    def test_unplug_ovs_hybrid(self):
        calls = {
            'device_exists': [mock.call('qbrvif-xxx-yyy')],
            'execute': [mock.call('brctl', 'delif', 'qbrvif-xxx-yyy',
                                  'qvbvif-xxx-yyy', run_as_root=True),
                        mock.call('ip', 'link', 'set',
                                  'qbrvif-xxx-yyy', 'down', run_as_root=True),
                        mock.call('brctl', 'delbr',
                                  'qbrvif-xxx-yyy', run_as_root=True)],
            'delete_ovs_vif_port': [mock.call('br0', 'qvovif-xxx-yyy')]
        }
        with test.nested(
                mock.patch.object(linux_net, 'device_exists',
                                  return_value=True),
                mock.patch.object(utils, 'execute'),
                mock.patch.object(linux_net, 'delete_ovs_vif_port')
        ) as (device_exists, execute, delete_ovs_vif_port):
            d = vif.LibvirtGenericVIFDriver()
            d.unplug_ovs_hybrid(None, self.vif_ovs)
            device_exists.assert_has_calls(calls['device_exists'])
            execute.assert_has_calls(calls['execute'])
            delete_ovs_vif_port.assert_has_calls(calls['delete_ovs_vif_port'])

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
                                  'eth13', port_state,
                                  run_as_root=True,
                                  check_exit_code=exit_code)]
        }
        op(None, self.vif_hw_veb_macvtap)
        mock_get_ifname.assert_has_calls(calls['get_ifname'])
        mock_get_vf_num.assert_has_calls(calls['get_vf_num'])
        mock_execute.assert_has_calls(calls['execute'])

    def test_plug_hw_veb(self):
        d = vif.LibvirtGenericVIFDriver()
        self._test_hw_veb_op(
            d.plug_hw_veb,
            self.vif_hw_veb_macvtap['details'][network_model.VIF_DETAILS_VLAN])

    def test_unplug_hw_veb(self):
        d = vif.LibvirtGenericVIFDriver()
        self._test_hw_veb_op(d.unplug_hw_veb, 0)

    def test_unplug_ovs_hybrid_bridge_does_not_exist(self):
        calls = {
            'device_exists': [mock.call('qbrvif-xxx-yyy')],
            'delete_ovs_vif_port': [mock.call('br0', 'qvovif-xxx-yyy')]
        }
        with test.nested(
                mock.patch.object(linux_net, 'device_exists',
                                  return_value=False),
                mock.patch.object(linux_net, 'delete_ovs_vif_port')
        ) as (device_exists, delete_ovs_vif_port):
            d = vif.LibvirtGenericVIFDriver()
            d.unplug_ovs_hybrid(None, self.vif_ovs)
            device_exists.assert_has_calls(calls['device_exists'])
            delete_ovs_vif_port.assert_has_calls(calls['delete_ovs_vif_port'])

    def test_plug_ivs_hybrid(self):
        calls = {
            'device_exists': [mock.call('qbrvif-xxx-yyy'),
                              mock.call('qvovif-xxx-yyy')],
            '_create_veth_pair': [mock.call('qvbvif-xxx-yyy',
                                            'qvovif-xxx-yyy')],
            'execute': [mock.call('brctl', 'addbr', 'qbrvif-xxx-yyy',
                                  run_as_root=True),
                        mock.call('brctl', 'setfd', 'qbrvif-xxx-yyy', 0,
                                  run_as_root=True),
                        mock.call('brctl', 'stp', 'qbrvif-xxx-yyy', 'off',
                                  run_as_root=True),
                        mock.call('tee', ('/sys/class/net/qbrvif-xxx-yyy'
                                          '/bridge/multicast_snooping'),
                                  process_input='0', run_as_root=True,
                                  check_exit_code=[0, 1]),
                        mock.call('ip', 'link', 'set', 'qbrvif-xxx-yyy', 'up',
                                  run_as_root=True),
                        mock.call('brctl', 'addif', 'qbrvif-xxx-yyy',
                                  'qvbvif-xxx-yyy', run_as_root=True)],
            'create_ivs_vif_port': [mock.call('qvovif-xxx-yyy', 'aaa-bbb-ccc',
                                    'ca:fe:de:ad:be:ef',
                                    'f0000000-0000-0000-0000-000000000001')]
        }
        with test.nested(
                mock.patch.object(linux_net, 'device_exists',
                                  return_value=False),
                mock.patch.object(utils, 'execute'),
                mock.patch.object(linux_net, '_create_veth_pair'),
                mock.patch.object(linux_net, 'create_ivs_vif_port')
        ) as (device_exists, execute, _create_veth_pair, create_ivs_vif_port):
            d = vif.LibvirtGenericVIFDriver()
            d.plug_ivs_hybrid(self.instance, self.vif_ivs)
            device_exists.assert_has_calls(calls['device_exists'])
            _create_veth_pair.assert_has_calls(calls['_create_veth_pair'])
            execute.assert_has_calls(calls['execute'])
            create_ivs_vif_port.assert_has_calls(calls['create_ivs_vif_port'])

    def test_unplug_ivs_hybrid(self):
        calls = {
            'execute': [mock.call('brctl', 'delif', 'qbrvif-xxx-yyy',
                                  'qvbvif-xxx-yyy', run_as_root=True),
                        mock.call('ip', 'link', 'set',
                                  'qbrvif-xxx-yyy', 'down', run_as_root=True),
                        mock.call('brctl', 'delbr',
                                  'qbrvif-xxx-yyy', run_as_root=True)],
            'delete_ivs_vif_port': [mock.call('qvovif-xxx-yyy')]
        }
        with test.nested(
                mock.patch.object(utils, 'execute'),
                mock.patch.object(linux_net, 'delete_ivs_vif_port')
        ) as (execute, delete_ivs_vif_port):
            d = vif.LibvirtGenericVIFDriver()
            d.unplug_ivs_hybrid(None, self.vif_ivs)
            execute.assert_has_calls(calls['execute'])
            delete_ivs_vif_port.assert_has_calls(calls['delete_ivs_vif_port'])

    def test_unplug_ivs_hybrid_bridge_does_not_exist(self):
        d = vif.LibvirtGenericVIFDriver()
        with mock.patch.object(utils, 'execute') as execute:
            execute.side_effect = processutils.ProcessExecutionError
            d.unplug_ivs_hybrid(None, self.vif_ivs)

    def test_unplug_iovisor(self):
        d = vif.LibvirtGenericVIFDriver()
        with mock.patch.object(utils, 'execute') as execute:
            execute.side_effect = processutils.ProcessExecutionError
            mynetwork = network_model.Network(id='network-id-xxx-yyy-zzz',
                                              label='mylabel')
            myvif = network_model.VIF(id='vif-xxx-yyy-zzz',
                                      address='ca:fe:de:ad:be:ef',
                                      network=mynetwork)
            d.unplug_iovisor(None, myvif)

    @mock.patch('nova.network.linux_net.device_exists')
    def test_plug_iovisor(self, device_exists):
        device_exists.return_value = True
        d = vif.LibvirtGenericVIFDriver()
        with mock.patch.object(utils, 'execute') as execute:
            execute.side_effect = processutils.ProcessExecutionError
            instance = objects.Instance(id=1,
                           uuid='f0000000-0000-0000-0000-000000000001',
                           project_id='myproject')
            d.plug_iovisor(instance, self.vif_ivs)

    def test_unplug_vrouter_with_details(self):
        d = vif.LibvirtGenericVIFDriver()
        with mock.patch.object(utils, 'execute') as execute:
            d.unplug_vrouter(None, self.vif_vrouter)
            execute.assert_called_once_with(
                'vrouter-port-control',
                '--oper=delete --uuid=vif-xxx-yyy-zzz',
                run_as_root=True)

    def test_plug_vrouter_with_details(self):
        d = vif.LibvirtGenericVIFDriver()
        instance = mock.Mock()
        instance.name = 'instance-name'
        instance.uuid = '46a4308b-e75a-4f90-a34a-650c86ca18b2'
        instance.project_id = 'b168ea26fa0c49c1a84e1566d9565fa5'
        instance.display_name = 'instance1'
        with mock.patch.object(utils, 'execute') as execute:
            d.plug_vrouter(instance, self.vif_vrouter)
            execute.assert_has_calls([
                mock.call('ip', 'tuntap', 'add', 'tap-xxx-yyy-zzz', 'mode',
                    'tap', run_as_root=True, check_exit_code=[0, 2, 254]),
                mock.call('ip', 'link', 'set', 'tap-xxx-yyy-zzz', 'up',
                    run_as_root=True, check_exit_code=[0, 2, 254]),
                mock.call('vrouter-port-control',
                    '--oper=add --uuid=vif-xxx-yyy-zzz '
                    '--instance_uuid=46a4308b-e75a-4f90-a34a-650c86ca18b2 '
                    '--vn_uuid=network-id-xxx-yyy-zzz '
                    '--vm_project_uuid=b168ea26fa0c49c1a84e1566d9565fa5 '
                    '--ip_address=0.0.0.0 '
                    '--ipv6_address=None '
                    '--vm_name=instance1 '
                    '--mac=ca:fe:de:ad:be:ef '
                    '--tap_name=tap-xxx-yyy-zzz '
                    '--port_type=NovaVMPort '
                    '--tx_vlan_id=-1 '
                    '--rx_vlan_id=-1', run_as_root=True)])

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
        br_want = "qbr" + self.vif_ivs_filter_hybrid['id']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, self.vif_ivs_filter_hybrid)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     self.vif_ivs_filter_hybrid, br_want, 0)

    def test_ivs_plug_with_port_filter_hybrid_no_nova_firewall(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = self.vif_ivs_filter_direct['devname']
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, self.vif_ivs_filter_direct)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.vif_ivs_filter_direct, br_want, 0)

    def test_hybrid_plug_without_nova_firewall(self):
        d = vif.LibvirtGenericVIFDriver()
        br_want = "qbr" + self.vif_ovs_hybrid['id']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, self.vif_ovs_hybrid)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     self.vif_ovs_hybrid, br_want, 0)

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
        d.plug_tap(None, self.vif_tap)

    def test_unplug_tap(self):
        d = vif.LibvirtGenericVIFDriver()
        d.unplug_tap(None, self.vif_tap)

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
        vlan = node.find("vlan").find("tag").get("id")
        vlan_want = self.vif_hw_veb["details"]["vlan"]
        self.assertEqual(vlan, vlan_want)

    @mock.patch.object(pci_utils, 'get_ifname_by_pci_address',
                       return_value='eth1')
    def test_hw_veb_driver_macvtap(self, mock_get_ifname):
        d = vif.LibvirtGenericVIFDriver()
        xml = self._get_instance_xml(d, self.vif_hw_veb_macvtap)
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
        d.plug_macvtap(self.instance, self.vif_macvtap_vlan)
        ensure_vlan_mock.assert_called_once_with('1', 'eth0',
                                                 interface='eth0.1')

    @mock.patch.object(linux_net.LinuxBridgeInterfaceDriver, 'ensure_vlan')
    def test_macvtap_plug_flat(self, ensure_vlan_mock):
        d = vif.LibvirtGenericVIFDriver()
        d.plug_macvtap(self.instance, self.vif_macvtap_flat)
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
        xml = self._get_instance_xml(d, self.vif_vhostuser, image_meta)
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

    def test_vhostuser_ovs_plug(self):

        calls = {
                'create_ovs_vif_port': [mock.call(
                                      'br0', 'usv-xxx-yyy-zzz',
                                      'aaa-bbb-ccc', 'ca:fe:de:ad:be:ef',
                                      'f0000000-0000-0000-0000-000000000001')],
                 'ovs_set_vhostuser_port_type': [mock.call('usv-xxx-yyy-zzz')]
        }
        with test.nested(
                mock.patch.object(linux_net, 'create_ovs_vif_port'),
                mock.patch.object(linux_net, 'ovs_set_vhostuser_port_type')
        ) as (create_ovs_vif_port, ovs_set_vhostuser_port_type):
            d = vif.LibvirtGenericVIFDriver()
            d.plug_vhostuser(self.instance, self.vif_vhostuser_ovs)
            create_ovs_vif_port.assert_has_calls(calls['create_ovs_vif_port'])
            ovs_set_vhostuser_port_type.assert_has_calls(
                                        calls['ovs_set_vhostuser_port_type'])

    def test_vhostuser_ovs_unplug(self):
        calls = {
            'delete_ovs_vif_port': [mock.call('br0', 'usv-xxx-yyy-zzz')]
        }
        with mock.patch.object(linux_net,
                               'delete_ovs_vif_port') as delete_port:
            d = vif.LibvirtGenericVIFDriver()
            d.unplug_vhostuser(None, self.vif_vhostuser_ovs)
            delete_port.assert_has_calls(calls['delete_ovs_vif_port'])

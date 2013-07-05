# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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
from oslo.config import cfg

from nova.compute import flavors
from nova import exception
from nova.network import model as network_model
from nova import test
from nova.tests.virt.libvirt import fakelibvirt
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import vif

CONF = cfg.CONF


def get_default_mapping(exclude=None, **kwargs):
    mapping_body = {
        'mac': 'ca:fe:de:ad:be:ef',
        'ips': [{'ip': '101.168.1.9'}],
        'dhcp_server': '191.168.1.1',
        'vif_uuid': 'vif-xxx-yyy-zzz',
        'vif_devname': 'tap-xxx-yyy-zzz'
    }
    mapping_body.update(kwargs)
    if exclude:
        for key in exclude:
            del mapping_body[key]
    return mapping_body


def get_default_net(**kwargs):
    body = {
        'cidr': '101.168.1.0/24',
        'cidr_v6': '101:1db9::/64',
        'gateway_v6': '101:1db9::1',
        'netmask_v6': '64',
        'netmask': '255.255.255.0',
        'vlan': 99,
        'gateway': '101.168.1.1',
        'broadcast': '101.168.1.255',
        'dns1': '8.8.8.8',
        'id': 'network-id-xxx-yyy-zzz'
    }
    body.update(kwargs)
    return body


class LibvirtVifTestCase(test.TestCase):

    net_bridge = get_default_net(bridge='br0', bridge_interface='eth0')
    net_bridge_neutron = get_default_net(bridge_interface='eth0')
    net_ovs = get_default_net(bridge='br0')
    net_8021 = get_default_net(interface='eth0')

    mapping_bridge = get_default_mapping(gateway_v6=net_bridge['gateway_v6'],
                                         vif_type=
                                         network_model.VIF_TYPE_BRIDGE)
    mapping_bridge_neutron = get_default_mapping(
        gateway_v6=net_bridge['gateway_v6'])
    mapping_ovs = get_default_mapping(gateway_v6=net_ovs['gateway_v6'],
                                      vif_type=network_model.VIF_TYPE_OVS,
                                      ovs_interfaceid='aaa-bbb-ccc')

    mapping_ivs = get_default_mapping(gateway_v6=net_ovs['gateway_v6'],
                                      vif_type=network_model.VIF_TYPE_IVS,
                                      ivs_interfaceid='aaa-bbb-ccc')

    mapping_ovs_legacy = get_default_mapping(['vif_devname'],
                                             gateway_v6=net_ovs['gateway_v6'])

    mapping_8021qbh = get_default_mapping(
        ['ips', 'dhcp_server'], vif_type=network_model.VIF_TYPE_802_QBH,
        qbh_params=network_model.VIF8021QbhParams(profileid="xxx-yyy-zzz"),)

    net_iovisor = get_default_net(interface='eth0')

    mapping_iovisor = get_default_mapping(
        ['ips', 'dhcp_server'], vif_type=network_model.VIF_TYPE_IOVISOR)

    mapping_8021qbg = get_default_mapping(
        ['ips', 'dhcp_server'], vif_type=network_model.VIF_TYPE_802_QBG,
        qbg_params=network_model.VIF8021QbgParams(managerid="xxx-yyy-zzz",
                                                  typeid="aaa-bbb-ccc",
                                                  typeidversion="1",
                                                  instanceid="ddd-eee-fff"))

    mapping_none = get_default_mapping(gateway_v6=net_bridge['gateway_v6'])

    instance = {
        'name': 'instance-name',
        'uuid': 'instance-uuid'
    }

    bandwidth = {
        'quota:vif_inbound_peak': '102400',
        'quota:vif_outbound_peak': '102400',
        'quota:vif_inbound_average': '102400',
        'quota:vif_outbound_average': '102400',
        'quota:vif_inbound_burst': '102400',
        'quota:vif_inbound_burst': '102400'
    }

    def setUp(self):
        super(LibvirtVifTestCase, self).setUp()
        self.flags(allow_same_net_traffic=True)
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)

    def _get_conn(self, uri="qemu:///session", ver=None):
        def __inner():
            if ver is None:
                return fakelibvirt.Connection(uri, False)
            else:
                return fakelibvirt.Connection(uri, False, ver)
        return __inner

    def _get_node(self, xml):
        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        return ret[0]

    def _assertMacEquals(self, node, mapping):
        mac = node.find("mac").get("address")
        self.assertEqual(mac, mapping['mac'])

    def _assertTypeEquals(self, node, type, attr, source, br_want,
                          prefix=None):
        self.assertEqual(node.get("type"), type)
        br_name = node.find(attr).get(source)
        if prefix is None:
            self.assertEqual(br_name, br_want)
        else:
            self.assertTrue(br_name.startswith(prefix))

    def _assertTypeAndMacEquals(self, node, type, attr, source, mapping,
                                br_want=None, size=0, prefix=None):
        ret = node.findall("filterref")
        self.assertEqual(len(ret), size)
        self._assertTypeEquals(node, type, attr, source, br_want,
                               prefix)
        self._assertMacEquals(node, mapping)

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

    def _get_conf(self):
        conf = vconfig.LibvirtConfigGuest()
        conf.virt_type = "qemu"
        conf.name = "fake-name"
        conf.uuid = "fake-uuid"
        conf.memory = 100 * 1024
        conf.vcpus = 4
        return conf

    def _get_instance_xml(self, driver, net, mapping, image_meta=None):
        default_inst_type = flavors.get_default_flavor()
        extra_specs = default_inst_type['extra_specs'].items()
        quota_bandwith = self.bandwidth.items()
        default_inst_type['extra_specs'] = dict(extra_specs + quota_bandwith)
        conf = self._get_conf()
        nic = driver.get_config(self.instance, net, mapping, image_meta,
                                default_inst_type)
        conf.add_device(nic)
        return conf.to_xml()

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
        self.flags(libvirt_use_virtio_for_bridges=False,
                   libvirt_type='kvm')

        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        xml = self._get_instance_xml(d,
                                     self.net_bridge,
                                     self.mapping_bridge)
        self._assertModel(xml)

    def test_model_kvm(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='kvm')

        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        xml = self._get_instance_xml(d,
                                     self.net_bridge,
                                     self.mapping_bridge)

        self._assertModel(xml, "virtio")

    def test_model_kvm_custom(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='kvm')

        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        image_meta = {'properties': {'hw_vif_model': 'e1000'}}
        xml = self._get_instance_xml(d,
                                     self.net_bridge,
                                     self.mapping_bridge,
                                     image_meta)
        self._assertModel(xml, "e1000")

    def test_model_kvm_bogus(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='kvm')

        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        image_meta = {'properties': {'hw_vif_model': 'acme'}}
        self.assertRaises(exception.UnsupportedHardware,
                          self._get_instance_xml,
                          d,
                          self.net_bridge,
                          self.mapping_bridge,
                          image_meta)

    def test_model_qemu(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='qemu')

        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        xml = self._get_instance_xml(d,
                                     self.net_bridge,
                                     self.mapping_bridge)

        doc = etree.fromstring(xml)

        ret = doc.findall('./devices/interface/bandwidth')
        self.assertEqual(len(ret), 1)

        self._assertModel(xml, "virtio", "qemu")

    def test_model_xen(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='xen')

        d = vif.LibvirtGenericVIFDriver(self._get_conn("xen:///system"))
        xml = self._get_instance_xml(d,
                                     self.net_bridge,
                                     self.mapping_bridge)
        self._assertModel(xml)

    def test_generic_driver_none(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        self.assertRaises(exception.NovaException,
                          self._get_instance_xml,
                          d,
                          self.net_bridge,
                          self.mapping_none)

    def _check_bridge_driver(self, d, net, mapping, br_want):
        xml = self._get_instance_xml(d, net, mapping)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     self.mapping_bridge, br_want, 1)

    def test_bridge_driver(self):
        d = vif.LibvirtBridgeDriver(self._get_conn())
        self._check_bridge_driver(d,
                                  self.net_bridge,
                                  self.mapping_bridge,
                                  self.net_bridge['bridge'])

    def test_generic_driver_bridge(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        self._check_bridge_driver(d,
                                  self.net_bridge,
                                  self.mapping_bridge,
                                  self.net_bridge['bridge'])

    def test_neutron_bridge_driver(self):
        d = vif.NeutronLinuxBridgeVIFDriver(self._get_conn())
        br_want = 'brq' + self.net_bridge_neutron['id']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self._check_bridge_driver(d,
                                  self.net_bridge_neutron,
                                  self.mapping_bridge_neutron,
                                  br_want)

    def _check_ivs_ethernet_driver(self, d, net, mapping, dev_prefix):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, net, mapping)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.mapping_ivs, prefix=dev_prefix)
        script = node.find("script").get("path")
        self.assertEquals(script, "")

    def _check_ovs_ethernet_driver(self, d, net, mapping, dev_prefix):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, net, mapping)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     self.mapping_ovs, prefix=dev_prefix)
        script = node.find("script").get("path")
        self.assertEquals(script, "")

    def test_ovs_ethernet_driver_legacy(self):
        d = vif.LibvirtOpenVswitchDriver(self._get_conn(ver=9010))
        self._check_ovs_ethernet_driver(d,
                                        self.net_ovs,
                                        self.mapping_ovs_legacy,
                                        "nic")

    def test_ovs_ethernet_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn(ver=9010))
        self._check_ovs_ethernet_driver(d,
                                        self.net_ovs,
                                        self.mapping_ovs,
                                        "tap")

    def test_ivs_ethernet_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn(ver=9010))
        self._check_ivs_ethernet_driver(d,
                                        self.net_ovs,
                                        self.mapping_ivs,
                                        "tap")

    def _check_ivs_virtualport_driver(self, d, net, mapping, want_iface_id):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, net, mapping)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                     mapping, mapping['vif_devname'])

    def _check_ovs_virtualport_driver(self, d, net, mapping, want_iface_id):
        self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
        xml = self._get_instance_xml(d, net, mapping)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     mapping, "br0")
        vp = node.find("virtualport")
        self.assertEqual(vp.get("type"), "openvswitch")
        iface_id_found = False
        for p_elem in vp.findall("parameters"):
            iface_id = p_elem.get("interfaceid", None)
            if iface_id:
                self.assertEqual(iface_id, want_iface_id)
                iface_id_found = True

        self.assertTrue(iface_id_found)

    def test_ovs_virtualport_driver(self):
        d = vif.LibvirtOpenVswitchVirtualPortDriver(self._get_conn(ver=9011))
        want_iface_id = 'vif-xxx-yyy-zzz'
        self._check_ovs_virtualport_driver(d,
                                           self.net_ovs,
                                           self.mapping_ovs_legacy,
                                           want_iface_id)

    def test_generic_ovs_virtualport_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn(ver=9011))
        want_iface_id = self.mapping_ovs['ovs_interfaceid']
        self._check_ovs_virtualport_driver(d,
                                           self.net_ovs,
                                           self.mapping_ovs,
                                           want_iface_id)

    def test_generic_ivs_virtualport_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn(ver=9011))
        want_iface_id = self.mapping_ivs['ivs_interfaceid']
        self._check_ivs_virtualport_driver(d,
                                           self.net_ovs,
                                           self.mapping_ivs,
                                           want_iface_id)

    def _check_neutron_hybrid_driver(self, d, net, mapping, br_want):
        self.flags(firewall_driver="nova.virt.firewall.IptablesFirewallDriver")
        xml = self._get_instance_xml(d, net, mapping)
        node = self._get_node(xml)
        self._assertTypeAndMacEquals(node, "bridge", "source", "bridge",
                                     mapping, br_want, 1)

    def test_quantum_hybrid_driver(self):
        br_want = "qbr" + self.mapping_ovs['vif_uuid']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        d = vif.LibvirtHybridOVSBridgeDriver(self._get_conn())
        self._check_neutron_hybrid_driver(d,
                                          self.net_ovs,
                                          self.mapping_ovs_legacy,
                                          br_want)

    def test_generic_hybrid_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        br_want = "qbr" + self.mapping_ovs['vif_uuid']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self._check_neutron_hybrid_driver(d,
                                          self.net_ovs,
                                          self.mapping_ovs,
                                          br_want)

    def test_ivs_hybrid_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        br_want = "qbr" + self.mapping_ivs['vif_uuid']
        br_want = br_want[:network_model.NIC_NAME_LEN]
        self._check_neutron_hybrid_driver(d,
                                          self.net_ovs,
                                          self.mapping_ivs,
                                          br_want)

    def test_generic_8021qbh_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        xml = self._get_instance_xml(d,
                                     self.net_8021,
                                     self.mapping_8021qbh)
        node = self._get_node(xml)
        self._assertTypeEquals(node, "direct", "source", "dev", "eth0")
        self._assertMacEquals(node, self.mapping_8021qbh)
        vp = node.find("virtualport")
        self.assertEqual(vp.get("type"), "802.1Qbh")
        profile_id_found = False
        for p_elem in vp.findall("parameters"):
            wantparams = self.mapping_8021qbh['qbh_params']
            profile_id = p_elem.get("profileid", None)
            if profile_id:
                self.assertEqual(profile_id,
                                 wantparams['profileid'])
                profile_id_found = True

        self.assertTrue(profile_id_found)

        def test_generic_iovisor_driver(self):
            d = vif.LibvirtGenericVIFDriver(self._get_conn())
            self.flags(firewall_driver="nova.virt.firewall.NoopFirewallDriver")
            xml = self._get_instance_xml(d,
                                         self.net_iovisor,
                                         self.mapping_iovisor)
            node = self._get_node(xml)
            self._assertTypeAndMacEquals(node, "ethernet", "target", "dev",
                                         self.mapping_iovisor,
                                         self.mapping_iovisor['vif_devname'])

    def test_generic_8021qbg_driver(self):
        d = vif.LibvirtGenericVIFDriver(self._get_conn())
        xml = self._get_instance_xml(d,
                                     self.net_8021,
                                     self.mapping_8021qbg)

        node = self._get_node(xml)
        self._assertTypeEquals(node, "direct", "source", "dev", "eth0")
        self._assertMacEquals(node, self.mapping_8021qbg)

        vp = node.find("virtualport")
        self.assertEqual(vp.get("type"), "802.1Qbg")
        manager_id_found = False
        type_id_found = False
        typeversion_id_found = False
        instance_id_found = False
        for p_elem in vp.findall("parameters"):
            wantparams = self.mapping_8021qbg['qbg_params']
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

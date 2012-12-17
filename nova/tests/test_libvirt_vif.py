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

from nova.openstack.common import cfg
from nova import test
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import vif

CONF = cfg.CONF


class LibvirtVifTestCase(test.TestCase):

    net = {
             'cidr': '101.168.1.0/24',
             'cidr_v6': '101:1db9::/64',
             'gateway_v6': '101:1db9::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'br0',
             'bridge_interface': 'eth0',
             'vlan': 99,
             'gateway': '101.168.1.1',
             'broadcast': '101.168.1.255',
             'dns1': '8.8.8.8',
             'id': 'network-id-xxx-yyy-zzz'
    }

    mapping = {
        'mac': 'ca:fe:de:ad:be:ef',
        'gateway_v6': net['gateway_v6'],
        'ips': [{'ip': '101.168.1.9'}],
        'dhcp_server': '191.168.1.1',
        'vif_uuid': 'vif-xxx-yyy-zzz'
    }

    instance = {
        'name': 'instance-name',
        'uuid': 'instance-uuid'
    }

    def setUp(self):
        super(LibvirtVifTestCase, self).setUp()
        self.flags(allow_same_net_traffic=True)
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)

    def _get_instance_xml(self, driver):
        conf = vconfig.LibvirtConfigGuest()
        conf.virt_type = "qemu"
        conf.name = "fake-name"
        conf.uuid = "fake-uuid"
        conf.memory = 100 * 1024
        conf.vcpus = 4

        nic = driver.get_config(self.instance, self.net, self.mapping)
        conf.add_device(nic)
        return conf.to_xml()

    def test_multiple_nics(self):
        conf = vconfig.LibvirtConfigGuest()
        conf.virt_type = "qemu"
        conf.name = "fake-name"
        conf.uuid = "fake-uuid"
        conf.memory = 100 * 1024
        conf.vcpus = 4

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

        d = vif.LibvirtBridgeDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]

        ret = node.findall("model")
        self.assertEqual(len(ret), 0)
        ret = node.findall("driver")
        self.assertEqual(len(ret), 0)

        d.unplug(None, (self.net, self.mapping))

    def test_model_kvm(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='kvm')

        d = vif.LibvirtBridgeDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]

        model = node.find("model").get("type")
        self.assertEqual(model, "virtio")
        ret = node.findall("driver")
        self.assertEqual(len(ret), 0)

        d.unplug(None, (self.net, self.mapping))

    def test_model_qemu(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='qemu')

        d = vif.LibvirtBridgeDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]

        model = node.find("model").get("type")
        self.assertEqual(model, "virtio")
        driver = node.find("driver").get("name")
        self.assertEqual(driver, "qemu")

        d.unplug(None, (self.net, self.mapping))

    def test_model_xen(self):
        self.flags(libvirt_use_virtio_for_bridges=True,
                   libvirt_type='xen')

        d = vif.LibvirtBridgeDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]

        ret = node.findall("model")
        self.assertEqual(len(ret), 0)
        ret = node.findall("driver")
        self.assertEqual(len(ret), 0)

        d.unplug(None, (self.net, self.mapping))

    def test_bridge_driver(self):
        d = vif.LibvirtBridgeDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]
        self.assertEqual(node.get("type"), "bridge")
        br_name = node.find("source").get("bridge")
        self.assertEqual(br_name, self.net['bridge'])
        mac = node.find("mac").get("address")
        self.assertEqual(mac, self.mapping['mac'])

        d.unplug(None, (self.net, self.mapping))

    def test_ovs_ethernet_driver(self):
        d = vif.LibvirtOpenVswitchDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]
        self.assertEqual(node.get("type"), "ethernet")
        dev_name = node.find("target").get("dev")
        self.assertTrue(dev_name.startswith("tap"))
        mac = node.find("mac").get("address")
        self.assertEqual(mac, self.mapping['mac'])
        script = node.find("script").get("path")
        self.assertEquals(script, "")

        d.unplug(None, (self.net, self.mapping))

    def test_ovs_virtualport_driver(self):
        d = vif.LibvirtOpenVswitchVirtualPortDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]
        self.assertEqual(node.get("type"), "bridge")

        br_name = node.find("source").get("bridge")
        self.assertEqual(br_name, CONF.libvirt_ovs_bridge)
        mac = node.find("mac").get("address")
        self.assertEqual(mac, self.mapping['mac'])
        vp = node.find("virtualport")
        self.assertEqual(vp.get("type"), "openvswitch")
        iface_id_found = False
        for p_elem in vp.findall("parameters"):
            iface_id = p_elem.get("interfaceid", None)
            if iface_id:
                self.assertEqual(iface_id, self.mapping['vif_uuid'])
                iface_id_found = True

        self.assertTrue(iface_id_found)
        d.unplug(None, (self.net, self.mapping))

    def test_quantum_bridge_ethernet_driver(self):
        d = vif.QuantumLinuxBridgeVIFDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]
        self.assertEqual(node.get("type"), "bridge")
        dev_name = node.find("target").get("dev")
        self.assertTrue(dev_name.startswith("tap"))
        mac = node.find("mac").get("address")
        self.assertEqual(mac, self.mapping['mac'])
        br_name = node.find("source").get("bridge")
        self.assertTrue(br_name.startswith("brq"))

        d.unplug(None, (self.net, self.mapping))

    def test_quantum_hybrid_driver(self):
        d = vif.LibvirtHybridOVSBridgeDriver()
        xml = self._get_instance_xml(d)

        doc = etree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]
        self.assertEqual(node.get("type"), "bridge")
        br_name = node.find("source").get("bridge")
        self.assertEqual(br_name, self.net['bridge'])
        mac = node.find("mac").get("address")
        self.assertEqual(mac, self.mapping['mac'])

        d.unplug(None, (self.net, self.mapping))

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

from xml.etree import ElementTree

from nova import flags
from nova import test
from nova import utils
from nova.virt import firewall
from nova.virt.libvirt import vif
from nova.virt.libvirt import connection

FLAGS = flags.FLAGS


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
             'dns1': '8.8.8.8'
    }

    mapping = {
        'mac': 'ca:fe:de:ad:be:ef',
        'gateway_v6': net['gateway_v6'],
        'ips': [{'ip': '101.168.1.9'}],
        'dhcp_server': '191.168.1.1',
        'vif_uuid': 'vif-xxx-yyy-zzz'
    }

    instance = {
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
        t = __import__('Cheetah.Template', globals(), locals(),
                       ['Template'], -1)
        self.Template = t.Template
        xml_file = open(FLAGS.libvirt_xml_template)
        self.xml_template = xml_file.read()

    def _create_xml_info(self, vif_type, nics):
        return     {
                    'type': 'qemu',
                    'name': 'fake-name',
                    'uuid': 'fake-uuid',
                    'memory_kb': 100 * 1024,
                    'basepath': 'foobar',
                    'vcpus': 4,
                    'rescue': False,
                    'disk_prefix': '/dev/sda',
                    'driver_type': 'raw',
                    'root_device_type': 'disk',
                    'vif_type': vif_type,
                    'nics': nics,
                    'ebs_root': True,
                    'ephemeral_device': False,
                    'volumes': [],
                    'use_virtio_for_bridges': False,
                    'ephemerals': []}

    def _get_instance_xml(self, driver, vif_type):
        nic_dict = driver.plug(self.instance, self.net, self.mapping)
        xml_info = self._create_xml_info(vif_type, [nic_dict])
        xml = str(self.Template(self.xml_template, searchList=[xml_info]))
        return xml

    def test_bridge_driver(self):
        d = vif.LibvirtBridgeDriver()
        xml = self._get_instance_xml(d, 'bridge')

        doc = ElementTree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]
        self.assertEqual(node.get("type"), "bridge")
        br_name = node.find("source").get("bridge")
        self.assertEqual(br_name, self.net['bridge'])
        mac = node.find("mac").get("address")
        self.assertEqual(mac, self.mapping['mac'])

        d.unplug(None, self.net, self.mapping)

    def test_ovs_ethernet_driver(self):
        d = vif.LibvirtOpenVswitchDriver()
        xml = self._get_instance_xml(d, 'ethernet')

        doc = ElementTree.fromstring(xml)
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

        d.unplug(None, self.net, self.mapping)

    def test_ovs_virtualport_driver(self):
        d = vif.LibvirtOpenVswitchVirtualPortDriver()
        xml = self._get_instance_xml(d, 'ovs_virtualport')

        doc = ElementTree.fromstring(xml)
        ret = doc.findall('./devices/interface')
        self.assertEqual(len(ret), 1)
        node = ret[0]
        self.assertEqual(node.get("type"), "bridge")

        br_name = node.find("source").get("bridge")
        self.assertEqual(br_name, FLAGS.libvirt_ovs_bridge)
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
        d.unplug(None, self.net, self.mapping)

    def test_quantum_bridge_ethernet_driver(self):
        d = vif.QuantumLinuxBridgeVIFDriver()
        xml = self._get_instance_xml(d, 'ethernet')

        doc = ElementTree.fromstring(xml)
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

        d.unplug(None, self.net, self.mapping)

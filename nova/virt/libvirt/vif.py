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

from nova import flags
from nova import log as logging
from nova.network import linux_net
from nova.virt.libvirt import netutils
from nova import utils
from nova.virt.vif import VIFDriver
from nova import exception

LOG = logging.getLogger('nova.virt.libvirt.vif')

FLAGS = flags.FLAGS

flags.DEFINE_string('libvirt_ovs_bridge', 'br-int',
                    'Name of Integration Bridge used by Open vSwitch')


class LibvirtBridgeDriver(VIFDriver):
    """VIF driver for Linux bridge."""

    def _get_configurations(self, network, mapping):
        """Get a dictionary of VIF configurations for bridge type."""
        # Assume that the gateway also acts as the dhcp server.
        gateway6 = mapping.get('gateway6')
        mac_id = mapping['mac'].replace(':', '')

        if FLAGS.allow_same_net_traffic:
            template = "<parameter name=\"%s\"value=\"%s\" />\n"
            net, mask = netutils.get_net_and_mask(network['cidr'])
            values = [("PROJNET", net), ("PROJMASK", mask)]
            if FLAGS.use_ipv6:
                net_v6, prefixlen_v6 = netutils.get_net_and_prefixlen(
                                           network['cidr_v6'])
                values.extend([("PROJNETV6", net_v6),
                               ("PROJMASKV6", prefixlen_v6)])

            extra_params = "".join([template % value for value in values])
        else:
            extra_params = "\n"

        result = {
            'id': mac_id,
            'bridge_name': network['bridge'],
            'mac_address': mapping['mac'],
            'ip_address': mapping['ips'][0]['ip'],
            'dhcp_server': mapping['dhcp_server'],
            'extra_params': extra_params,
        }

        if gateway6:
            result['gateway6'] = gateway6 + "/128"

        return result

    def plug(self, instance, network, mapping):
        """Ensure that the bridge exists, and add VIF to it."""
        if (not network.get('multi_host') and
            mapping.get('should_create_bridge')):
            if mapping.get('should_create_vlan'):
                LOG.debug(_('Ensuring vlan %(vlan)s and bridge %(bridge)s'),
                          {'vlan': network['vlan'],
                           'bridge': network['bridge']})
                linux_net.LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                                             network['vlan'],
                                             network['bridge'],
                                             network['bridge_interface'])
            else:
                LOG.debug(_("Ensuring bridge %s"), network['bridge'])
                linux_net.LinuxBridgeInterfaceDriver.ensure_bridge(
                                        network['bridge'],
                                        network['bridge_interface'])

        return self._get_configurations(network, mapping)

    def unplug(self, instance, network, mapping):
        """No manual unplugging required."""
        pass


class LibvirtOpenVswitchDriver(VIFDriver):
    """VIF driver for Open vSwitch."""

    def get_dev_name(_self, iface_id):
        return "tap" + iface_id[0:11]

    def plug(self, instance, network, mapping):
        iface_id = mapping['vif_uuid']
        dev = self.get_dev_name(iface_id)
        if not linux_net._device_exists(dev):
            utils.execute('ip', 'tuntap', 'add', dev, 'mode', 'tap',
                          run_as_root=True)
            utils.execute('ip', 'link', 'set', dev, 'up', run_as_root=True)
        utils.execute('ovs-vsctl', '--', '--may-exist', 'add-port',
                FLAGS.libvirt_ovs_bridge, dev,
                '--', 'set', 'Interface', dev,
                "external-ids:iface-id=%s" % iface_id,
                '--', 'set', 'Interface', dev,
                "external-ids:iface-status=active",
                '--', 'set', 'Interface', dev,
                "external-ids:attached-mac=%s" % mapping['mac'],
                run_as_root=True)

        result = {
            'script': '',
            'name': dev,
            'mac_address': mapping['mac']}
        return result

    def unplug(self, instance, network, mapping):
        """Unplug the VIF from the network by deleting the port from
        the bridge."""
        dev = self.get_dev_name(mapping['vif_uuid'])
        try:
            utils.execute('ovs-vsctl', 'del-port',
                          FLAGS.libvirt_ovs_bridge, dev, run_as_root=True)
            utils.execute('ip', 'link', 'delete', dev, run_as_root=True)
        except exception.ProcessExecutionError:
            LOG.warning(_("Failed while unplugging vif of instance '%s'"),
                        instance['name'])
            raise

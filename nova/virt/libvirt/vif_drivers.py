# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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

"""Drivers responsible for VIF creation in libvirt."""

from nova import flags
from nova.virt.libvirt import netutils

FLAGS = flags.FLAGS
flags.DEFINE_bool('allow_project_net_traffic',
                  True,
                  'Whether to allow in project network traffic')


class VIFDriver(object):
    """Base class that defines generic interfaces for VIF drivers."""

    def get_configuration(self, instance, network, mapping):
        """Get a dictionary of VIF configuration for libvirt interfaces."""
        raise NotImplementedError()


class BridgeDriver(VIFDriver):
    """Class that generates VIF configuration of bridge interface type."""

    def get_configuration(self, instance, network, mapping):
        """Get a dictionary of VIF configurations for bridge type."""
        # Assume that the gateway also acts as the dhcp server.
        dhcp_server = mapping['gateway']
        gateway6 = mapping.get('gateway6')
        mac_id = mapping['mac'].replace(':', '')

        if FLAGS.allow_project_net_traffic:
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
            'dhcp_server': dhcp_server,
            'extra_params': extra_params,
        }

        if gateway6:
            result['gateway6'] = gateway6 + "/128"

        return result
        

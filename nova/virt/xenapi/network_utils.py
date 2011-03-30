# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Helper methods for operations related to the management of network
records and their attributes like bridges, PIFs, QoS, as well as
their lookup functions.
"""


from nova.virt.xenapi import HelperBase


class NetworkHelper(HelperBase):
    """
    The class that wraps the helper methods together.
    """
    @classmethod
    def find_network_with_name_label(cls, session, name_label):
        networks = session.call_xenapi('network.get_by_name_label', name_label)
        if len(networks) == 1:
            return networks[0]
        elif len(networks) > 1:
            raise Exception(_('Found non-unique network'
                              ' for name_label %s') % name_label)
        else:
            return None

    @classmethod
    def find_network_with_bridge(cls, session, bridge):
        """
        Return the network on which the bridge is attached, if found.
        The bridge is defined in the nova db and can be found either in the
        'bridge' or 'name_label' fields of the XenAPI network record.
        """
        expr = 'field "name__label" = "%s" or ' \
               'field "bridge" = "%s"' % (bridge, bridge)
        networks = session.call_xenapi('network.get_all_records_where', expr)
        if len(networks) == 1:
            return networks.keys()[0]
        elif len(networks) > 1:
            raise Exception(_('Found non-unique network'
                              ' for bridge %s') % bridge)
        else:
            raise Exception(_('Found no network for bridge %s') % bridge)

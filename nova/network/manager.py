# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Network Hosts are responsible for allocating ips and setting up network
"""

import logging
import math

import IPy

from nova import db
from nova import exception
from nova import flags
from nova import manager
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('flat_network_bridge', 'br100',
                    'Bridge for simple network instances')
flags.DEFINE_list('flat_network_ips',
                  ['192.168.0.2', '192.168.0.3', '192.168.0.4'],
                  'Available ips for simple network')
flags.DEFINE_string('flat_network_network', '192.168.0.0',
                    'Network for simple network')
flags.DEFINE_string('flat_network_netmask', '255.255.255.0',
                    'Netmask for simple network')
flags.DEFINE_string('flat_network_gateway', '192.168.0.1',
                    'Broadcast for simple network')
flags.DEFINE_string('flat_network_broadcast', '192.168.0.255',
                    'Broadcast for simple network')
flags.DEFINE_string('flat_network_dns', '8.8.4.4',
                    'Dns for simple network')
flags.DEFINE_integer('vlan_start', 100, 'First VLAN for private networks')
flags.DEFINE_integer('num_networks', 1000, 'Number of networks to support')
flags.DEFINE_string('vpn_ip', utils.get_my_ip(),
                    'Public IP for the cloudpipe VPN servers')
flags.DEFINE_integer('vpn_start', 1000, 'First Vpn port for private networks')
flags.DEFINE_integer('network_size', 256,
                        'Number of addresses in each private subnet')
flags.DEFINE_string('public_range', '4.4.4.0/24', 'Public IP address block')
flags.DEFINE_string('private_range', '10.0.0.0/8', 'Private IP address block')
flags.DEFINE_integer('cnt_vpn_clients', 5,
                     'Number of addresses reserved for vpn clients')
flags.DEFINE_string('network_driver', 'nova.network.linux_net',
                    'Driver to use for network creation')
flags.DEFINE_bool('update_dhcp_on_disassociate', False,
                  'Whether to update dhcp when fixed_ip is disassocated')


class AddressAlreadyAllocated(exception.Error):
    """Address was already allocated"""
    pass


class NetworkManager(manager.Manager):
    """Implements common network manager functionality

    This class must be subclassed.
    """
    def __init__(self, network_driver=None, *args, **kwargs):
        if not network_driver:
            network_driver = FLAGS.network_driver
        self.driver = utils.import_object(network_driver)
        super(NetworkManager, self).__init__(*args, **kwargs)

    def set_network_host(self, context, project_id):
        """Safely sets the host of the projects network"""
        logging.debug("setting network host")
        network_ref = self.db.project_get_network(context, project_id)
        # TODO(vish): can we minimize db access by just getting the
        #             id here instead of the ref?
        network_id = network_ref['id']
        host = self.db.network_set_host(context,
                                        network_id,
                                        self.host)
        self._on_set_network_host(context, network_id)
        return host

    def allocate_fixed_ip(self, context, instance_id, *args, **kwargs):
        """Gets a fixed ip from the pool"""
        raise NotImplementedError()

    def deallocate_fixed_ip(self, context, instance_id, *args, **kwargs):
        """Returns a fixed ip to the pool"""
        raise NotImplementedError()

    def setup_fixed_ip(self, context, address):
        """Sets up rules for fixed ip"""
        raise NotImplementedError()

    def _on_set_network_host(self, context, network_id):
        """Called when this host becomes the host for a project"""
        raise NotImplementedError()

    def setup_compute_network(self, context, project_id):
        """Sets up matching network for compute hosts"""
        raise NotImplementedError()

    def allocate_floating_ip(self, context, project_id):
        """Gets an floating ip from the pool"""
        # TODO(vish): add floating ips through manage command
        return self.db.floating_ip_allocate_address(context,
                                                    self.host,
                                                    project_id)

    def associate_floating_ip(self, context, floating_address, fixed_address):
        """Associates an floating ip to a fixed ip"""
        self.db.floating_ip_fixed_ip_associate(context,
                                               floating_address,
                                               fixed_address)
        self.driver.bind_floating_ip(floating_address)
        self.driver.ensure_floating_forward(floating_address, fixed_address)

    def disassociate_floating_ip(self, context, floating_address):
        """Disassociates a floating ip"""
        fixed_address = self.db.floating_ip_disassociate(context,
                                                         floating_address)
        self.driver.unbind_floating_ip(floating_address)
        self.driver.remove_floating_forward(floating_address, fixed_address)

    def deallocate_floating_ip(self, context, floating_address):
        """Returns an floating ip to the pool"""
        self.db.floating_ip_deallocate(context, floating_address)

    @property
    def _bottom_reserved_ips(self):  # pylint: disable-msg=R0201
        """Number of reserved ips at the bottom of the range"""
        return 2  # network, gateway

    @property
    def _top_reserved_ips(self):  # pylint: disable-msg=R0201
        """Number of reserved ips at the top of the range"""
        return 1  # broadcast

    def _create_fixed_ips(self, context, network_id):
        """Create all fixed ips for network"""
        network_ref = self.db.network_get(context, network_id)
        # NOTE(vish): should these be properties of the network as opposed
        #             to properties of the manager class?
        bottom_reserved = self._bottom_reserved_ips
        top_reserved = self._top_reserved_ips
        project_net = IPy.IP(network_ref['cidr'])
        num_ips = len(project_net)
        for index in range(num_ips):
            address = str(project_net[index])
            if index < bottom_reserved or num_ips - index < top_reserved:
                reserved = True
            else:
                reserved = False
            self.db.fixed_ip_create(context, {'network_id': network_id,
                                              'address': address,
                                              'reserved': reserved})


class FlatManager(NetworkManager):
    """Basic network where no vlans are used"""

    def allocate_fixed_ip(self, context, instance_id, *args, **kwargs):
        """Gets a fixed ip from the pool"""
        network_ref = self.db.project_get_network(context, context.project.id)
        address = self.db.fixed_ip_associate_pool(context,
                                                  network_ref['id'],
                                                  instance_id)
        self.db.fixed_ip_update(context, address, {'allocated': True})
        return address

    def deallocate_fixed_ip(self, context, address, *args, **kwargs):
        """Returns a fixed ip to the pool"""
        self.db.fixed_ip_update(context, address, {'allocated': False})
        self.db.fixed_ip_disassociate(context, address)

    def setup_compute_network(self, context, project_id):
        """Network is created manually"""
        pass

    def setup_fixed_ip(self, context, address):
        """Currently no setup"""
        pass

    def _on_set_network_host(self, context, network_id):
        """Called when this host becomes the host for a project"""
        # NOTE(vish): should there be two types of network objects
        #             in the datastore?
        net = {}
        net['injected'] = True
        net['network_str'] = FLAGS.flat_network_network
        net['netmask'] = FLAGS.flat_network_netmask
        net['bridge'] = FLAGS.flat_network_bridge
        net['gateway'] = FLAGS.flat_network_gateway
        net['broadcast'] = FLAGS.flat_network_broadcast
        net['dns'] = FLAGS.flat_network_dns
        self.db.network_update(context, network_id, net)
        # NOTE(vish): Rignt now we are putting  all of the fixed ips in
        #             one large pool, but ultimately it may be better to
        #             have each network manager have its own network that
        #             it is responsible for and its own pool of ips.
        for address in FLAGS.flat_network_ips:
            self.db.fixed_ip_create(context, {'address': address})


class VlanManager(NetworkManager):
    """Vlan network with dhcp"""
    def allocate_fixed_ip(self, context, instance_id, *args, **kwargs):
        """Gets a fixed ip from the pool"""
        network_ref = self.db.project_get_network(context, context.project.id)
        if kwargs.get('vpn', None):
            address = network_ref['vpn_private_address']
            self.db.fixed_ip_associate(context, address, instance_id)
        else:
            address = self.db.fixed_ip_associate_pool(context,
                                                      network_ref['id'],
                                                      instance_id)
        self.db.fixed_ip_update(context, address, {'allocated': True})
        return address

    def deallocate_fixed_ip(self, context, address, *args, **kwargs):
        """Returns a fixed ip to the pool"""
        self.db.fixed_ip_update(context, address, {'allocated': False})
        fixed_ip_ref = self.db.fixed_ip_get_by_address(context, address)
        if not fixed_ip_ref['leased']:
            self.db.fixed_ip_disassociate(context, address)
            # NOTE(vish): dhcp server isn't updated until next setup, this
            #             means there will stale entries in the conf file
            #             the code below will update the file if necessary
            if FLAGS.update_dhcp_on_disassociate:
                network_ref = self.db.fixed_ip_get_network(context, address)
                self.driver.update_dhcp(context, network_ref['id'])


    def setup_fixed_ip(self, context, address):
        """Sets forwarding rules and dhcp for fixed ip"""
        fixed_ip_ref = self.db.fixed_ip_get_by_address(context, address)
        network_ref = self.db.fixed_ip_get_network(context, address)
        if self.db.instance_is_vpn(context, fixed_ip_ref['instance_id']):
            self.driver.ensure_vlan_forward(network_ref['vpn_public_address'],
                                            network_ref['vpn_public_port'],
                                            network_ref['vpn_private_address'])
        self.driver.update_dhcp(context, network_ref['id'])

    def lease_fixed_ip(self, context, mac, address):
        """Called by dhcp-bridge when ip is leased"""
        logging.debug("Leasing IP %s", address)
        fixed_ip_ref = self.db.fixed_ip_get_by_address(context, address)
        if not fixed_ip_ref['allocated']:
            logging.warn("IP %s leased that was already deallocated", address)
            return
        instance_ref = fixed_ip_ref['instance']
        if not instance_ref:
            raise exception.Error("IP %s leased that isn't associated" %
                                  address)
        if instance_ref['mac_address'] != mac:
            raise exception.Error("IP %s leased to bad mac %s vs %s" %
                                  (address, instance_ref['mac_address'], mac))
        self.db.fixed_ip_update(context,
                                fixed_ip_ref['address'],
                                {'leased': True})

    def release_fixed_ip(self, context, mac, address):
        """Called by dhcp-bridge when ip is released"""
        logging.debug("Releasing IP %s", address)
        fixed_ip_ref = self.db.fixed_ip_get_by_address(context, address)
        if not fixed_ip_ref['leased']:
            logging.warn("IP %s released that was not leased", address)
            return
        instance_ref = fixed_ip_ref['instance']
        if not instance_ref:
            raise exception.Error("IP %s released that isn't associated" %
                                  address)
        if instance_ref['mac_address'] != mac:
            raise exception.Error("IP %s released from bad mac %s vs %s" %
                                  (address, instance_ref['mac_address'], mac))
        self.db.fixed_ip_update(context, address, {'leased': False})
        if not fixed_ip_ref['allocated']:
            self.db.fixed_ip_disassociate(context, address)
            # NOTE(vish): dhcp server isn't updated until next setup, this
            #             means there will stale entries in the conf file
            #             the code below will update the file if necessary
            if FLAGS.update_dhcp_on_disassociate:
                network_ref = self.db.fixed_ip_get_network(context, address)
                self.driver.update_dhcp(context, network_ref['id'])

    def allocate_network(self, context, project_id):
        """Set up the network"""
        self._ensure_indexes(context)
        network_ref = db.network_create(context, {'project_id': project_id})
        network_id = network_ref['id']
        private_net = IPy.IP(FLAGS.private_range)
        index = db.network_get_index(context, network_id)
        vlan = FLAGS.vlan_start + index
        start = index * FLAGS.network_size
        significant_bits = 32 - int(math.log(FLAGS.network_size, 2))
        cidr = "%s/%s" % (private_net[start], significant_bits)
        project_net = IPy.IP(cidr)

        net = {}
        net['cidr'] = cidr
        # NOTE(vish): we could turn these into properties
        net['netmask'] = str(project_net.netmask())
        net['gateway'] = str(project_net[1])
        net['broadcast'] = str(project_net.broadcast())
        net['vpn_private_address'] = str(project_net[2])
        net['dhcp_start'] = str(project_net[3])
        net['vlan'] = vlan
        net['bridge'] = 'br%s' % vlan
        net['vpn_public_address'] = FLAGS.vpn_ip
        net['vpn_public_port'] = FLAGS.vpn_start + index
        db.network_update(context, network_id, net)
        self._create_fixed_ips(context, network_id)
        return network_id

    def setup_compute_network(self, context, project_id):
        """Sets up matching network for compute hosts"""
        network_ref = self.db.project_get_network(context, project_id)
        self.driver.ensure_vlan_bridge(network_ref['vlan'],
                                       network_ref['bridge'])

    def restart_nets(self):
        """Ensure the network for each user is enabled"""
        # TODO(vish): Implement this
        pass

    def _ensure_indexes(self, context):
        """Ensure the indexes for the network exist

        This could use a manage command instead of keying off of a flag"""
        if not self.db.network_index_count(context):
            for index in range(FLAGS.num_networks):
                self.db.network_index_create_safe(context, {'index': index})

    def _on_set_network_host(self, context, network_id):
        """Called when this host becomes the host for a project"""
        network_ref = self.db.network_get(context, network_id)
        self.driver.ensure_vlan_bridge(network_ref['vlan'],
                                       network_ref['bridge'],
                                       network_ref)

    @property
    def _bottom_reserved_ips(self):
        """Number of reserved ips at the bottom of the range"""
        return super(VlanManager, self)._bottom_reserved_ips + 1  # vpn server

    @property
    def _top_reserved_ips(self):
        """Number of reserved ips at the top of the range"""
        parent_reserved = super(VlanManager, self)._top_reserved_ips
        return parent_reserved + FLAGS.cnt_vpn_clients


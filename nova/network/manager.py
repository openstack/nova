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
Network Hosts are responsible for allocating ips and setting up network.

There are multiple backend drivers that handle specific types of networking
topologies.  All of the network commands are issued to a subclass of
:class:`NetworkManager`.

**Related Flags**

:network_driver:  Driver to use for network creation
:flat_network_bridge:  Bridge device for simple network instances
:flat_interface:  FlatDhcp will bridge into this interface if set
:flat_network_dns:  Dns for simple network
:flat_network_dhcp_start:  Dhcp start for FlatDhcp
:vlan_start:  First VLAN for private networks
:vpn_ip:  Public IP for the cloudpipe VPN servers
:vpn_start:  First Vpn port for private networks
:cnt_vpn_clients:  Number of addresses reserved for vpn clients
:network_size:  Number of addresses in each private subnet
:floating_range:  Floating IP address block
:fixed_range:  Fixed IP address block
:date_dhcp_on_disassociate:  Whether to update dhcp when fixed_ip
                             is disassociated
:fixed_ip_disassociate_timeout:  Seconds after which a deallocated ip
                                 is disassociated

"""

import datetime
import math
import socket

import IPy

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import utils
from nova import rpc


LOG = logging.getLogger("nova.network.manager")
FLAGS = flags.FLAGS
flags.DEFINE_string('flat_network_bridge', 'br100',
                    'Bridge for simple network instances')
flags.DEFINE_string('flat_network_dns', '8.8.4.4',
                    'Dns for simple network')
flags.DEFINE_bool('flat_injected', True,
                  'Whether to attempt to inject network setup into guest')
flags.DEFINE_string('flat_interface', None,
                    'FlatDhcp will bridge into this interface if set')
flags.DEFINE_string('flat_network_dhcp_start', '10.0.0.2',
                    'Dhcp start for FlatDhcp')
flags.DEFINE_integer('vlan_start', 100, 'First VLAN for private networks')
flags.DEFINE_integer('num_networks', 1000, 'Number of networks to support')
flags.DEFINE_string('vpn_ip', '$my_ip',
                    'Public IP for the cloudpipe VPN servers')
flags.DEFINE_integer('vpn_start', 1000, 'First Vpn port for private networks')
flags.DEFINE_integer('network_size', 256,
                        'Number of addresses in each private subnet')
flags.DEFINE_string('floating_range', '4.4.4.0/24',
                    'Floating IP address block')
flags.DEFINE_string('fixed_range', '10.0.0.0/8', 'Fixed IP address block')
flags.DEFINE_string('fixed_range_v6', 'fd00::/48', 'Fixed IPv6 address block')
flags.DEFINE_integer('cnt_vpn_clients', 0,
                     'Number of addresses reserved for vpn clients')
flags.DEFINE_string('network_driver', 'nova.network.linux_net',
                    'Driver to use for network creation')
flags.DEFINE_bool('update_dhcp_on_disassociate', False,
                  'Whether to update dhcp when fixed_ip is disassociated')
flags.DEFINE_integer('fixed_ip_disassociate_timeout', 600,
                     'Seconds after which a deallocated ip is disassociated')

flags.DEFINE_bool('use_ipv6', False,
                  'use the ipv6')
flags.DEFINE_string('network_host', socket.gethostname(),
                    'Network host to use for ip allocation in flat modes')
flags.DEFINE_bool('fake_call', False,
                  'If True, skip using the queue and make local calls')


class AddressAlreadyAllocated(exception.Error):
    """Address was already allocated."""
    pass


class NetworkManager(manager.Manager):
    """Implements common network manager functionality.

    This class must be subclassed to support specific topologies.
    """
    timeout_fixed_ips = True

    def __init__(self, network_driver=None, *args, **kwargs):
        if not network_driver:
            network_driver = FLAGS.network_driver
        self.driver = utils.import_object(network_driver)
        super(NetworkManager, self).__init__(*args, **kwargs)

    def init_host(self):
        """Do any initialization that needs to be run if this is a
        standalone service.
        """
        self.driver.init_host()
        # Set up networking for the projects for which we're already
        # the designated network host.
        ctxt = context.get_admin_context()
        for network in self.db.host_get_networks(ctxt, self.host):
            self._on_set_network_host(ctxt, network['id'])
        floating_ips = self.db.floating_ip_get_all_by_host(ctxt,
                                                           self.host)
        for floating_ip in floating_ips:
            if floating_ip.get('fixed_ip', None):
                fixed_address = floating_ip['fixed_ip']['address']
                # NOTE(vish): The False here is because we ignore the case
                #             that the ip is already bound.
                self.driver.bind_floating_ip(floating_ip['address'], False)
                self.driver.ensure_floating_forward(floating_ip['address'],
                                                    fixed_address)

    def periodic_tasks(self, context=None):
        """Tasks to be run at a periodic interval."""
        super(NetworkManager, self).periodic_tasks(context)
        if self.timeout_fixed_ips:
            now = utils.utcnow()
            timeout = FLAGS.fixed_ip_disassociate_timeout
            time = now - datetime.timedelta(seconds=timeout)
            num = self.db.fixed_ip_disassociate_all_by_timeout(context,
                                                               self.host,
                                                               time)
            if num:
                LOG.debug(_("Dissassociated %s stale fixed ip(s)"), num)

    def set_network_host(self, context, network_id):
        """Safely sets the host of the network."""
        LOG.debug(_("setting network host"), context=context)
        host = self.db.network_set_host(context,
                                        network_id,
                                        self.host)
        self._on_set_network_host(context, network_id)
        return host

    def allocate_fixed_ip(self, context, instance_id, *args, **kwargs):
        """Gets a fixed ip from the pool."""
        # TODO(vish): when this is called by compute, we can associate compute
        #             with a network, or a cluster of computes with a network
        #             and use that network here with a method like
        #             network_get_by_compute_host
        network_ref = self.db.network_get_by_bridge(context,
                                                    FLAGS.flat_network_bridge)
        address = self.db.fixed_ip_associate_pool(context.elevated(),
                                                  network_ref['id'],
                                                  instance_id)
        self.db.fixed_ip_update(context, address, {'allocated': True})
        return address

    def deallocate_fixed_ip(self, context, address, *args, **kwargs):
        """Returns a fixed ip to the pool."""
        self.db.fixed_ip_update(context, address, {'allocated': False})
        self.db.fixed_ip_disassociate(context.elevated(), address)

    def setup_fixed_ip(self, context, address):
        """Sets up rules for fixed ip."""
        raise NotImplementedError()

    def _on_set_network_host(self, context, network_id):
        """Called when this host becomes the host for a network."""
        raise NotImplementedError()

    def setup_compute_network(self, context, instance_id):
        """Sets up matching network for compute hosts."""
        raise NotImplementedError()

    def allocate_floating_ip(self, context, project_id):
        """Gets an floating ip from the pool."""
        # TODO(vish): add floating ips through manage command
        return self.db.floating_ip_allocate_address(context,
                                                    self.host,
                                                    project_id)

    def associate_floating_ip(self, context, floating_address, fixed_address):
        """Associates an floating ip to a fixed ip."""
        self.db.floating_ip_fixed_ip_associate(context,
                                               floating_address,
                                               fixed_address)
        self.driver.bind_floating_ip(floating_address)
        self.driver.ensure_floating_forward(floating_address, fixed_address)

    def disassociate_floating_ip(self, context, floating_address):
        """Disassociates a floating ip."""
        fixed_address = self.db.floating_ip_disassociate(context,
                                                         floating_address)
        self.driver.unbind_floating_ip(floating_address)
        self.driver.remove_floating_forward(floating_address, fixed_address)

    def deallocate_floating_ip(self, context, floating_address):
        """Returns an floating ip to the pool."""
        self.db.floating_ip_deallocate(context, floating_address)

    def lease_fixed_ip(self, context, mac, address):
        """Called by dhcp-bridge when ip is leased."""
        LOG.debug(_("Leasing IP %s"), address, context=context)
        fixed_ip_ref = self.db.fixed_ip_get_by_address(context, address)
        instance_ref = fixed_ip_ref['instance']
        if not instance_ref:
            raise exception.Error(_("IP %s leased that isn't associated") %
                                  address)
        if instance_ref['mac_address'] != mac:
            inst_addr = instance_ref['mac_address']
            raise exception.Error(_("IP %(address)s leased to bad"
                    " mac %(inst_addr)s vs %(mac)s") % locals())
        now = datetime.datetime.utcnow()
        self.db.fixed_ip_update(context,
                                fixed_ip_ref['address'],
                                {'leased': True,
                                 'updated_at': now})
        if not fixed_ip_ref['allocated']:
            LOG.warn(_("IP %s leased that was already deallocated"), address,
                     context=context)

    def release_fixed_ip(self, context, mac, address):
        """Called by dhcp-bridge when ip is released."""
        LOG.debug(_("Releasing IP %s"), address, context=context)
        fixed_ip_ref = self.db.fixed_ip_get_by_address(context, address)
        instance_ref = fixed_ip_ref['instance']
        if not instance_ref:
            raise exception.Error(_("IP %s released that isn't associated") %
                                  address)
        if instance_ref['mac_address'] != mac:
            inst_addr = instance_ref['mac_address']
            raise exception.Error(_("IP %(address)s released from"
                    " bad mac %(inst_addr)s vs %(mac)s") % locals())
        if not fixed_ip_ref['leased']:
            LOG.warn(_("IP %s released that was not leased"), address,
                     context=context)
        self.db.fixed_ip_update(context,
                                fixed_ip_ref['address'],
                                {'leased': False})
        if not fixed_ip_ref['allocated']:
            self.db.fixed_ip_disassociate(context, address)
            # NOTE(vish): dhcp server isn't updated until next setup, this
            #             means there will stale entries in the conf file
            #             the code below will update the file if necessary
            if FLAGS.update_dhcp_on_disassociate:
                network_ref = self.db.fixed_ip_get_network(context, address)
                self.driver.update_dhcp(context, network_ref['id'])

    def get_network_host(self, context):
        """Get the network host for the current context."""
        network_ref = self.db.network_get_by_bridge(context,
                                                    FLAGS.flat_network_bridge)
        # NOTE(vish): If the network has no host, use the network_host flag.
        #             This could eventually be a a db lookup of some sort, but
        #             a flag is easy to handle for now.
        host = network_ref['host']
        if not host:
            topic = self.db.queue_get_for(context,
                                          FLAGS.network_topic,
                                          FLAGS.network_host)
            if FLAGS.fake_call:
                return self.set_network_host(context, network_ref['id'])
            host = rpc.call(context,
                            FLAGS.network_topic,
                            {"method": "set_network_host",
                             "args": {"network_id": network_ref['id']}})
        return host

    def create_networks(self, context, cidr, num_networks, network_size,
                        cidr_v6, label, *args, **kwargs):
        """Create networks based on parameters."""
        fixed_net = IPy.IP(cidr)
        fixed_net_v6 = IPy.IP(cidr_v6)
        significant_bits_v6 = 64
        count = 1
        for index in range(num_networks):
            start = index * network_size
            significant_bits = 32 - int(math.log(network_size, 2))
            cidr = "%s/%s" % (fixed_net[start], significant_bits)
            project_net = IPy.IP(cidr)
            net = {}
            net['bridge'] = FLAGS.flat_network_bridge
            net['dns'] = FLAGS.flat_network_dns
            net['cidr'] = cidr
            net['netmask'] = str(project_net.netmask())
            net['gateway'] = str(project_net[1])
            net['broadcast'] = str(project_net.broadcast())
            net['dhcp_start'] = str(project_net[2])
            if num_networks > 1:
                net['label'] = "%s_%d" % (label, count)
            else:
                net['label'] = label
            count += 1

            if(FLAGS.use_ipv6):
                cidr_v6 = "%s/%s" % (fixed_net_v6[0], significant_bits_v6)
                net['cidr_v6'] = cidr_v6

            network_ref = self.db.network_create_safe(context, net)

            if network_ref:
                self._create_fixed_ips(context, network_ref['id'])

    @property
    def _bottom_reserved_ips(self):  # pylint: disable=R0201
        """Number of reserved ips at the bottom of the range."""
        return 2  # network, gateway

    @property
    def _top_reserved_ips(self):  # pylint: disable=R0201
        """Number of reserved ips at the top of the range."""
        return 1  # broadcast

    def _create_fixed_ips(self, context, network_id):
        """Create all fixed ips for network."""
        network_ref = self.db.network_get(context, network_id)
        # NOTE(vish): Should these be properties of the network as opposed
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
    """Basic network where no vlans are used.

    FlatManager does not do any bridge or vlan creation.  The user is
    responsible for setting up whatever bridge is specified in
    flat_network_bridge (br100 by default).  This bridge needs to be created
    on all compute hosts.

    The idea is to create a single network for the host with a command like:
    nova-manage network create 192.168.0.0/24 1 256. Creating multiple
    networks for for one manager is currently not supported, but could be
    added by modifying allocate_fixed_ip and get_network to get the a network
    with new logic instead of network_get_by_bridge. Arbitrary lists of
    addresses in a single network can be accomplished with manual db editing.

    If flat_injected is True, the compute host will attempt to inject network
    config into the guest.  It attempts to modify /etc/network/interfaces and
    currently only works on debian based systems. To support a wider range of
    OSes, some other method may need to be devised to let the guest know which
    ip it should be using so that it can configure itself. Perhaps an attached
    disk or serial device with configuration info.

    Metadata forwarding must be handled by the gateway, and since nova does
    not do any setup in this mode, it must be done manually.  Requests to
    169.254.169.254 port 80 will need to be forwarded to the api server.
    """
    timeout_fixed_ips = False

    def init_host(self):
        """Do any initialization that needs to be run if this is a
        standalone service.
        """
        #Fix for bug 723298 - do not call init_host on superclass
        #Following code has been copied for NetworkManager.init_host
        ctxt = context.get_admin_context()
        for network in self.db.host_get_networks(ctxt, self.host):
            self._on_set_network_host(ctxt, network['id'])

    def setup_compute_network(self, context, instance_id):
        """Network is created manually."""
        pass

    def _on_set_network_host(self, context, network_id):
        """Called when this host becomes the host for a network."""
        net = {}
        net['injected'] = FLAGS.flat_injected
        net['dns'] = FLAGS.flat_network_dns
        self.db.network_update(context, network_id, net)

    def allocate_floating_ip(self, context, project_id):
        #Fix for bug 723298
        raise NotImplementedError()

    def associate_floating_ip(self, context, floating_address, fixed_address):
        #Fix for bug 723298
        raise NotImplementedError()

    def disassociate_floating_ip(self, context, floating_address):
        #Fix for bug 723298
        raise NotImplementedError()

    def deallocate_floating_ip(self, context, floating_address):
        #Fix for bug 723298
        raise NotImplementedError()


class FlatDHCPManager(NetworkManager):
    """Flat networking with dhcp.

    FlatDHCPManager will start up one dhcp server to give out addresses.
    It never injects network settings into the guest. Otherwise it behaves
    like FlatDHCPManager.
    """

    def init_host(self):
        """Do any initialization that needs to be run if this is a
        standalone service.
        """
        super(FlatDHCPManager, self).init_host()
        self.driver.metadata_forward()

    def setup_compute_network(self, context, instance_id):
        """Sets up matching network for compute hosts."""
        network_ref = db.network_get_by_instance(context, instance_id)
        self.driver.ensure_bridge(network_ref['bridge'],
                                  FLAGS.flat_interface)

    def allocate_fixed_ip(self, context, instance_id, *args, **kwargs):
        """Setup dhcp for this network."""
        address = super(FlatDHCPManager, self).allocate_fixed_ip(context,
                                                                 instance_id,
                                                                 *args,
                                                                 **kwargs)
        network_ref = db.fixed_ip_get_network(context, address)
        if not FLAGS.fake_network:
            self.driver.update_dhcp(context, network_ref['id'])
        return address

    def deallocate_fixed_ip(self, context, address, *args, **kwargs):
        """Returns a fixed ip to the pool."""
        self.db.fixed_ip_update(context, address, {'allocated': False})

    def _on_set_network_host(self, context, network_id):
        """Called when this host becomes the host for a project."""
        net = {}
        net['dhcp_start'] = FLAGS.flat_network_dhcp_start
        self.db.network_update(context, network_id, net)
        network_ref = db.network_get(context, network_id)
        self.driver.ensure_bridge(network_ref['bridge'],
                                  FLAGS.flat_interface,
                                  network_ref)
        if not FLAGS.fake_network:
            self.driver.update_dhcp(context, network_id)
            if(FLAGS.use_ipv6):
                self.driver.update_ra(context, network_id)


class VlanManager(NetworkManager):
    """Vlan network with dhcp.

    VlanManager is the most complicated.  It will create a host-managed
    vlan for each project.  Each project gets its own subnet.  The networks
    and associated subnets are created with nova-manage using a command like:
    nova-manage network create 10.0.0.0/8 3 16.  This will create 3 networks
    of 16 addresses from the beginning of the 10.0.0.0 range.

    A dhcp server is run for each subnet, so each project will have its own.
    For this mode to be useful, each project will need a vpn to access the
    instances in its subnet.
    """

    def init_host(self):
        """Do any initialization that needs to be run if this is a
        standalone service.
        """
        super(VlanManager, self).init_host()
        self.driver.metadata_forward()

    def allocate_fixed_ip(self, context, instance_id, *args, **kwargs):
        """Gets a fixed ip from the pool."""
        # TODO(vish): This should probably be getting project_id from
        #             the instance, but it is another trip to the db.
        #             Perhaps this method should take an instance_ref.
        ctxt = context.elevated()
        network_ref = self.db.project_get_network(ctxt,
                                                  context.project_id)
        if kwargs.get('vpn', None):
            address = network_ref['vpn_private_address']
            self.db.fixed_ip_associate(ctxt,
                                       address,
                                       instance_id)
        else:
            address = self.db.fixed_ip_associate_pool(ctxt,
                                                      network_ref['id'],
                                                      instance_id)
        self.db.fixed_ip_update(context, address, {'allocated': True})
        if not FLAGS.fake_network:
            self.driver.update_dhcp(context, network_ref['id'])
        return address

    def deallocate_fixed_ip(self, context, address, *args, **kwargs):
        """Returns a fixed ip to the pool."""
        self.db.fixed_ip_update(context, address, {'allocated': False})

    def setup_compute_network(self, context, instance_id):
        """Sets up matching network for compute hosts."""
        network_ref = db.network_get_by_instance(context, instance_id)
        self.driver.ensure_vlan_bridge(network_ref['vlan'],
                                       network_ref['bridge'])

    def create_networks(self, context, cidr, num_networks, network_size,
                        cidr_v6, vlan_start, vpn_start, **kwargs):
        """Create networks based on parameters."""
        # Check that num_networks + vlan_start is not > 4094, fixes lp708025
        if num_networks + vlan_start > 4094:
            raise ValueError(_('The sum between the number of networks and'
                               ' the vlan start cannot be greater'
                               ' than 4094'))

        fixed_net = IPy.IP(cidr)
        if fixed_net.len() < num_networks * network_size:
            raise ValueError(_('The network range is not big enough to fit '
                  '%(num_networks)s. Network size is %(network_size)s' %
                  locals()))

        fixed_net_v6 = IPy.IP(cidr_v6)
        network_size_v6 = 1 << 64
        significant_bits_v6 = 64
        for index in range(num_networks):
            vlan = vlan_start + index
            start = index * network_size
            start_v6 = index * network_size_v6
            significant_bits = 32 - int(math.log(network_size, 2))
            cidr = "%s/%s" % (fixed_net[start], significant_bits)
            project_net = IPy.IP(cidr)
            net = {}
            net['cidr'] = cidr
            net['netmask'] = str(project_net.netmask())
            net['gateway'] = str(project_net[1])
            net['broadcast'] = str(project_net.broadcast())
            net['vpn_private_address'] = str(project_net[2])
            net['dhcp_start'] = str(project_net[3])
            net['vlan'] = vlan
            net['bridge'] = 'br%s' % vlan
            if(FLAGS.use_ipv6):
                cidr_v6 = "%s/%s" % (fixed_net_v6[start_v6],
                                     significant_bits_v6)
                net['cidr_v6'] = cidr_v6

            # NOTE(vish): This makes ports unique accross the cloud, a more
            #             robust solution would be to make them unique per ip
            net['vpn_public_port'] = vpn_start + index
            network_ref = None
            try:
                network_ref = db.network_get_by_cidr(context, cidr)
            except exception.NotFound:
                pass

            if network_ref is not None:
                raise ValueError(_('Network with cidr %s already exists' %
                                   cidr))

            network_ref = self.db.network_create_safe(context, net)
            if network_ref:
                self._create_fixed_ips(context, network_ref['id'])

    def get_network_host(self, context):
        """Get the network for the current context."""
        network_ref = self.db.project_get_network(context.elevated(),
                                                  context.project_id)
        # NOTE(vish): If the network has no host, do a call to get an
        #             available host.  This should be changed to go through
        #             the scheduler at some point.
        host = network_ref['host']
        if not host:
            if FLAGS.fake_call:
                return self.set_network_host(context, network_ref['id'])
            host = rpc.call(context,
                            FLAGS.network_topic,
                            {"method": "set_network_host",
                             "args": {"network_id": network_ref['id']}})

        return host

    def _on_set_network_host(self, context, network_id):
        """Called when this host becomes the host for a network."""
        network_ref = self.db.network_get(context, network_id)
        if not network_ref['vpn_public_address']:
            net = {}
            address = FLAGS.vpn_ip
            net['vpn_public_address'] = address
            db.network_update(context, network_id, net)
        else:
            address = network_ref['vpn_public_address']
        self.driver.ensure_vlan_bridge(network_ref['vlan'],
                                       network_ref['bridge'],
                                       network_ref)

        # NOTE(vish): only ensure this forward if the address hasn't been set
        #             manually.
        if address == FLAGS.vpn_ip:
            self.driver.ensure_vlan_forward(FLAGS.vpn_ip,
                                            network_ref['vpn_public_port'],
                                            network_ref['vpn_private_address'])
        if not FLAGS.fake_network:
            self.driver.update_dhcp(context, network_id)
            if(FLAGS.use_ipv6):
                self.driver.update_ra(context, network_id)

    @property
    def _bottom_reserved_ips(self):
        """Number of reserved ips at the bottom of the range."""
        return super(VlanManager, self)._bottom_reserved_ips + 1  # vpn server

    @property
    def _top_reserved_ips(self):
        """Number of reserved ips at the top of the range."""
        parent_reserved = super(VlanManager, self)._top_reserved_ips
        return parent_reserved + FLAGS.cnt_vpn_clients

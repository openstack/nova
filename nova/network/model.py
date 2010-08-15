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
Model Classes for network control, including VLANs, DHCP, and IP allocation.
"""

import IPy
import logging
import os
import time

from nova import datastore
from nova import exception as nova_exception
from nova import flags
from nova import utils
from nova.auth import manager
from nova.network import exception
from nova.network import linux_net


FLAGS = flags.FLAGS
flags.DEFINE_string('networks_path', utils.abspath('../networks'),
                    'Location to keep network config files')
flags.DEFINE_integer('public_vlan', 1, 'VLAN for public IP addresses')
flags.DEFINE_string('public_interface', 'vlan1',
                        'Interface for public IP addresses')
flags.DEFINE_string('bridge_dev', 'eth1',
                        'network device for bridges')
flags.DEFINE_integer('vlan_start', 100, 'First VLAN for private networks')
flags.DEFINE_integer('vlan_end', 4093, 'Last VLAN for private networks')
flags.DEFINE_integer('network_size', 256,
                        'Number of addresses in each private subnet')
flags.DEFINE_string('public_range', '4.4.4.0/24', 'Public IP address block')
flags.DEFINE_string('private_range', '10.0.0.0/8', 'Private IP address block')
flags.DEFINE_integer('cnt_vpn_clients', 5,
                        'Number of addresses reserved for vpn clients')
flags.DEFINE_integer('cloudpipe_start_port', 12000,
                        'Starting port for mapped CloudPipe external ports')

logging.getLogger().setLevel(logging.DEBUG)


class Vlan():
    """Tracks vlans assigned to project it the datastore"""
    def __init__(self, project, vlan):  # pylint: disable=W0231
        """
        Since we don't want to try and find a vlan by its identifier,
        but by a project id, we don't call super-init.
        """
        self.project_id = project
        self.vlan_id = vlan

    @property
    def identifier(self):
        """Datastore identifier"""
        return "%s:%s" % (self.project_id, self.vlan_id)

    @classmethod
    def create(cls, project, vlan):
        """Create a Vlan object"""
        instance = cls(project, vlan)
        instance.save()
        return instance

    @classmethod
    def lookup(cls, project):
        """Returns object by project if it exists in datastore or None"""
        set_name = cls._redis_set_name(cls.__name__)
        vlan = datastore.Redis.instance().hget(set_name, project)
        if vlan:
            return cls(project, vlan)
        else:
            return None

    @classmethod
    def dict_by_project(cls):
        """A hash of project:vlan"""
        set_name = cls._redis_set_name(cls.__name__)
        return datastore.Redis.instance().hgetall(set_name) or {}

    @classmethod
    def dict_by_vlan(cls):
        """A hash of vlan:project"""
        set_name = cls._redis_set_name(cls.__name__)
        retvals = {}
        hashset = datastore.Redis.instance().hgetall(set_name) or {}
        for (key, val) in hashset.iteritems():
            retvals[val] = key
        return retvals

    @classmethod
    def all(cls):
        set_name = cls._redis_set_name(cls.__name__)
        elements = datastore.Redis.instance().hgetall(set_name)
        for project in elements:
            yield cls(project, elements[project])

    def save(self):
        """
        Vlan saves state into a giant hash named "vlans", with keys of
        project_id and value of vlan number.  Therefore, we skip the
        default way of saving into "vlan:ID" and adding to a set of "vlans".
        """
        set_name = self._redis_set_name(self.__class__.__name__)
        datastore.Redis.instance().hset(set_name,
                                        self.project_id,
                                        self.vlan_id)

    def destroy(self):
        """Removes the object from the datastore"""
        set_name = self._redis_set_name(self.__class__.__name__)
        datastore.Redis.instance().hdel(set_name, self.project_id)

    def subnet(self):
        """Returns a string containing the subnet"""
        vlan = int(self.vlan_id)
        network = IPy.IP(FLAGS.private_range)
        start = (vlan - FLAGS.vlan_start) * FLAGS.network_size
        # minus one for the gateway.
        return "%s-%s" % (network[start],
                          network[start + FLAGS.network_size - 1])


class FixedIp():
    """Represents a fixed ip in the datastore"""

    def __init__(self, address):
        self.address = address
        super(FixedIp, self).__init__()

    @property
    def identifier(self):
        return self.address

    # NOTE(vish): address states allocated, leased, deallocated
    def default_state(self):
        return {'address': self.address,
                'state': 'none'}

    @classmethod
    # pylint: disable=R0913
    def create(cls, user_id, project_id, address, mac, hostname, network_id):
        """Creates an FixedIp object"""
        addr = cls(address)
        addr['user_id'] = user_id
        addr['project_id'] = project_id
        addr['mac'] = mac
        if hostname is None:
            hostname = "ip-%s" % address.replace('.', '-')
        addr['hostname'] = hostname
        addr['network_id'] = network_id
        addr['state'] = 'allocated'
        addr.save()
        return addr

    def save(self):
        is_new = self.is_new_record()
        success = super(FixedIp, self).save()
        if success and is_new:
            self.associate_with("network", self['network_id'])

    def destroy(self):
        self.unassociate_with("network", self['network_id'])
        super(FixedIp, self).destroy()


class ElasticIp(FixedIp):
    """Represents an elastic ip in the datastore"""
    override_type = "address"

    def default_state(self):
        return {'address': self.address,
                'instance_id': 'available',
                'private_ip': 'available'}


# CLEANUP:
# TODO(ja): does vlanpool "keeper" need to know the min/max -
#           shouldn't FLAGS always win?
class BaseNetwork():
    """Implements basic logic for allocating ips in a network"""
    override_type = 'network'
    address_class = FixedIp

    @property
    def identifier(self):
        """Datastore identifier"""
        return self.network_id

    def default_state(self):
        """Default values for new objects"""
        return {'network_id': self.network_id, 'network_str': self.network_str}

    @classmethod
    # pylint: disable=R0913
    def create(cls, user_id, project_id, security_group, vlan, network_str):
        """Create a BaseNetwork object"""
        network_id = "%s:%s" % (project_id, security_group)
        net = cls(network_id, network_str)
        net['user_id'] = user_id
        net['project_id'] = project_id
        net["vlan"] = vlan
        net["bridge_name"] = "br%s" % vlan
        net.save()
        return net

    def __init__(self, network_id, network_str=None):
        self.network_id = network_id
        self.network_str = network_str
        super(BaseNetwork, self).__init__()
        self.save()

    @property
    def network(self):
        """Returns a string representing the network"""
        return IPy.IP(self['network_str'])

    @property
    def netmask(self):
        """Returns the netmask of this network"""
        return self.network.netmask()

    @property
    def gateway(self):
        """Returns the network gateway address"""
        return self.network[1]

    @property
    def broadcast(self):
        """Returns the network broadcast address"""
        return self.network.broadcast()

    @property
    def bridge_name(self):
        """Returns the bridge associated with this network"""
        return "br%s" % (self["vlan"])

    @property
    def user(self):
        """Returns the user associated with this network"""
        return manager.AuthManager().get_user(self['user_id'])

    @property
    def project(self):
        """Returns the project associated with this network"""
        return manager.AuthManager().get_project(self['project_id'])

    # pylint: disable=R0913
    def _add_host(self, user_id, project_id, ip_address, mac, hostname):
        """Add a host to the datastore"""
        self.address_class.create(user_id, project_id, ip_address,
                       mac, hostname, self.identifier)

    def _rem_host(self, ip_address):
        """Remove a host from the datastore"""
        self.address_class(ip_address).destroy()

    @property
    def assigned(self):
        """Returns a list of all assigned addresses"""
        return self.address_class.associated_keys('network', self.identifier)

    @property
    def assigned_objs(self):
        """Returns a list of all assigned addresses as objects"""
        return self.address_class.associated_to('network', self.identifier)

    def get_address(self, ip_address):
        """Returns a specific ip as an object"""
        if ip_address in self.assigned:
            return self.address_class(ip_address)
        return None

    @property
    def available(self):
        """Returns a list of all available addresses in the network"""
        for idx in range(self.num_bottom_reserved_ips,
                         len(self.network) - self.num_top_reserved_ips):
            address = str(self.network[idx])
            if not address in self.assigned:
                yield address

    @property
    def num_bottom_reserved_ips(self):
        """Returns number of ips reserved at the bottom of the range"""
        return 2  # Network, Gateway

    @property
    def num_top_reserved_ips(self):
        """Returns number of ips reserved at the top of the range"""
        return 1  # Broadcast

    def allocate_ip(self, user_id, project_id, mac, hostname=None):
        """Allocates an ip to a mac address"""
        for address in self.available:
            logging.debug("Allocating IP %s to %s", address, project_id)
            self._add_host(user_id, project_id, address, mac, hostname)
            self.express(address=address)
            return address
        raise exception.NoMoreAddresses("Project %s with network %s" %
                                        (project_id, str(self.network)))

    def lease_ip(self, ip_str):
        """Called when DHCP lease is activated"""
        if not ip_str in self.assigned:
            raise exception.AddressNotAllocated()
        address = self.get_address(ip_str)
        if address:
            logging.debug("Leasing allocated IP %s", ip_str)
            address['state'] = 'leased'
            address.save()

    def release_ip(self, ip_str):
        """Called when DHCP lease expires

        Removes the ip from the assigned list"""
        if not ip_str in self.assigned:
            raise exception.AddressNotAllocated()
        logging.debug("Releasing IP %s", ip_str)
        self._rem_host(ip_str)
        self.deexpress(address=ip_str)

    def deallocate_ip(self, ip_str):
        """Deallocates an allocated ip"""
        if not ip_str in self.assigned:
            raise exception.AddressNotAllocated()
        address = self.get_address(ip_str)
        if address:
            if address['state'] != 'leased':
                # NOTE(vish): address hasn't been leased, so release it
                self.release_ip(ip_str)
            else:
                logging.debug("Deallocating allocated IP %s", ip_str)
                address['state'] == 'deallocated'
                address.save()

    def express(self, address=None):
        """Set up network.  Implemented in subclasses"""
        pass

    def deexpress(self, address=None):
        """Tear down network.  Implemented in subclasses"""
        pass


class BridgedNetwork(BaseNetwork):
    """
    Virtual Network that can express itself to create a vlan and
    a bridge (with or without an IP address/netmask/gateway)

    properties:
        bridge_name - string (example value: br42)
        vlan - integer (example value: 42)
        bridge_dev - string (example: eth0)
        bridge_gets_ip - boolean used during bridge creation

        if bridge_gets_ip then network address for bridge uses the properties:
            gateway
            broadcast
            netmask
    """

    bridge_gets_ip = False
    override_type = 'network'

    @classmethod
    def get_network_for_project(cls,
                                user_id,
                                project_id,
                                security_group='default'):
        """Returns network for a given project"""
        vlan = get_vlan_for_project(project_id)
        network_str = vlan.subnet()
        return cls.create(user_id, project_id, security_group, vlan.vlan_id,
                          network_str)

    def __init__(self, *args, **kwargs):
        super(BridgedNetwork, self).__init__(*args, **kwargs)
        self['bridge_dev'] = FLAGS.bridge_dev
        self.save()

    def express(self, address=None):
        super(BridgedNetwork, self).express(address=address)
        linux_net.vlan_create(self)
        linux_net.bridge_create(self)


class DHCPNetwork(BridgedNetwork):
    """Network supporting DHCP"""
    bridge_gets_ip = True
    override_type = 'network'

    def __init__(self, *args, **kwargs):
        super(DHCPNetwork, self).__init__(*args, **kwargs)
        if not(os.path.exists(FLAGS.networks_path)):
            os.makedirs(FLAGS.networks_path)

    @property
    def num_bottom_reserved_ips(self):
        # For cloudpipe
        return super(DHCPNetwork, self).num_bottom_reserved_ips + 1

    @property
    def num_top_reserved_ips(self):
        return super(DHCPNetwork, self).num_top_reserved_ips + \
                FLAGS.cnt_vpn_clients

    @property
    def dhcp_listen_address(self):
        """Address where dhcp server should listen"""
        return self.gateway

    @property
    def dhcp_range_start(self):
        """Starting address dhcp server should use"""
        return self.network[self.num_bottom_reserved_ips]

    def express(self, address=None):
        super(DHCPNetwork, self).express(address=address)
        if len(self.assigned) > 0:
            logging.debug("Starting dnsmasq server for network with vlan %s",
                            self['vlan'])
            linux_net.start_dnsmasq(self)
        else:
            logging.debug("Not launching dnsmasq: no hosts.")
        self.express_vpn()

    def allocate_vpn_ip(self, user_id, project_id, mac, hostname=None):
        """Allocates the reserved ip to a vpn instance"""
        address = str(self.network[2])
        self._add_host(user_id, project_id, address, mac, hostname)
        self.express(address=address)
        return address

    def express_vpn(self):
        """Sets up routing rules for vpn"""
        private_ip = str(self.network[2])
        linux_net.confirm_rule("FORWARD -d %s -p udp --dport 1194 -j ACCEPT"
                               % (private_ip, ))
        linux_net.confirm_rule(
            "PREROUTING -t nat -d %s -p udp --dport %s -j DNAT --to %s:1194"
            % (self.project.vpn_ip, self.project.vpn_port, private_ip))

    def deexpress(self, address=None):
        # if this is the last address, stop dns
        super(DHCPNetwork, self).deexpress(address=address)
        if len(self.assigned) == 0:
            linux_net.stop_dnsmasq(self)
        else:
            linux_net.start_dnsmasq(self)

DEFAULT_PORTS = [("tcp", 80), ("tcp", 22), ("udp", 1194), ("tcp", 443)]


class PublicNetworkController(BaseNetwork):
    """Handles elastic ips"""
    override_type = 'network'
    address_class = ElasticIp

    def __init__(self, *args, **kwargs):
        network_id = "public:default"
        super(PublicNetworkController, self).__init__(network_id,
            FLAGS.public_range, *args, **kwargs)
        self['user_id'] = "public"
        self['project_id'] = "public"
        self["create_time"] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                            time.gmtime())
        self["vlan"] = FLAGS.public_vlan
        self.save()
        self.express()

    def deallocate_ip(self, ip_str):
        # NOTE(vish): cleanup is now done on release by the parent class
        self.release_ip(ip_str)

    def associate_address(self, public_ip, private_ip, instance_id):
        """Associates a public ip to a private ip and instance id"""
        if not public_ip in self.assigned:
            raise exception.AddressNotAllocated()
        # TODO(josh): Keep an index going both ways
        for addr in self.assigned_objs:
            if addr.get('private_ip', None) == private_ip:
                raise exception.AddressAlreadyAssociated()
        addr = self.get_address(public_ip)
        if addr.get('private_ip', 'available') != 'available':
            raise exception.AddressAlreadyAssociated()
        addr['private_ip'] = private_ip
        addr['instance_id'] = instance_id
        addr.save()
        self.express(address=public_ip)

    def disassociate_address(self, public_ip):
        """Disassociates a public ip with its private ip"""
        if not public_ip in self.assigned:
            raise exception.AddressNotAllocated()
        addr = self.get_address(public_ip)
        if addr.get('private_ip', 'available') == 'available':
            raise exception.AddressNotAssociated()
        self.deexpress(address=public_ip)
        addr['private_ip'] = 'available'
        addr['instance_id'] = 'available'
        addr.save()

    def express(self, address=None):
        if address:
            if not address in self.assigned:
                raise exception.AddressNotAllocated()
            addresses = [self.get_address(address)]
        else:
            addresses = self.assigned_objs
        for addr in addresses:
            if addr.get('private_ip', 'available') == 'available':
                continue
            public_ip = addr['address']
            private_ip = addr['private_ip']
            linux_net.bind_public_ip(public_ip, FLAGS.public_interface)
            linux_net.confirm_rule("PREROUTING -t nat -d %s -j DNAT --to %s"
                                   % (public_ip, private_ip))
            linux_net.confirm_rule("POSTROUTING -t nat -s %s -j SNAT --to %s"
                                   % (private_ip, public_ip))
            # TODO(joshua): Get these from the secgroup datastore entries
            linux_net.confirm_rule("FORWARD -d %s -p icmp -j ACCEPT"
                                   % (private_ip))
            for (protocol, port) in DEFAULT_PORTS:
                linux_net.confirm_rule(
                    "FORWARD -d %s -p %s --dport %s -j ACCEPT"
                    % (private_ip, protocol, port))

    def deexpress(self, address=None):
        addr = self.get_address(address)
        private_ip = addr['private_ip']
        linux_net.unbind_public_ip(address, FLAGS.public_interface)
        linux_net.remove_rule("PREROUTING -t nat -d %s -j DNAT --to %s"
                              % (address, private_ip))
        linux_net.remove_rule("POSTROUTING -t nat -s %s -j SNAT --to %s"
                              % (private_ip, address))
        linux_net.remove_rule("FORWARD -d %s -p icmp -j ACCEPT"
                              % (private_ip))
        for (protocol, port) in DEFAULT_PORTS:
            linux_net.remove_rule("FORWARD -d %s -p %s --dport %s -j ACCEPT"
                                  % (private_ip, protocol, port))


# FIXME(todd): does this present a race condition, or is there some
#              piece of architecture that mitigates it (only one queue
#              listener per net)?
def get_vlan_for_project(project_id):
    """Allocate vlan IDs to individual users"""
    vlan = Vlan.lookup(project_id)
    if vlan:
        return vlan
    known_vlans = Vlan.dict_by_vlan()
    for vnum in range(FLAGS.vlan_start, FLAGS.vlan_end):
        vstr = str(vnum)
        if not vstr in known_vlans:
            return Vlan.create(project_id, vnum)
        old_project_id = known_vlans[vstr]
        if not manager.AuthManager().get_project(old_project_id):
            vlan = Vlan.lookup(old_project_id)
            if vlan:
                # NOTE(todd): This doesn't check for vlan id match, because
                #             it seems to be assumed that vlan<=>project is
                #             always a 1:1 mapping.  It could be made way
                #             sexier if it didn't fight against the way
                #             BasicModel worked and used associate_with
                #             to build connections to projects.
                # NOTE(josh): This is here because we want to make sure we
                #             don't orphan any VLANs.  It is basically
                #             garbage collection for after projects abandoned
                #             their reference.
                vlan.destroy()
                vlan.project_id = project_id
                vlan.save()
                return vlan
            else:
                return Vlan.create(project_id, vnum)
    raise exception.AddressNotAllocated("Out of VLANs")


def get_project_network(project_id, security_group='default'):
    """Gets a project's private network, allocating one if needed"""
    project = manager.AuthManager().get_project(project_id)
    if not project:
        raise nova_exception.NotFound("Project %s doesn't exist." % project_id)
    manager_id = project.project_manager_id
    return DHCPNetwork.get_network_for_project(manager_id,
                                               project.id,
                                               security_group)


def get_network_by_address(address):
    """Gets the network for a given private ip"""
    address_record = FixedIp.lookup(address)
    if not address_record:
        raise exception.AddressNotAllocated()
    return get_project_network(address_record['project_id'])


def get_network_by_interface(iface, security_group='default'):
    """Gets the network for a given interface"""
    vlan = iface.rpartition("br")[2]
    project_id = Vlan.dict_by_vlan().get(vlan)
    return get_project_network(project_id, security_group)


def get_public_ip_for_instance(instance_id):
    """Gets the public ip for a given instance"""
    # FIXME(josh): this should be a lookup - iteration won't scale
    for address_record in ElasticIp.all():
        if address_record.get('instance_id', 'available') == instance_id:
            return address_record['address']

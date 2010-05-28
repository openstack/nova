# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Classes for network control, including VLANs, DHCP, and IP allocation.
"""

import json
import logging
import os

# TODO(termie): clean up these imports
from nova import vendor
import IPy

from nova import datastore
import nova.exception
from nova.compute import exception
from nova import flags
from nova import utils
from nova.auth import users

import linux_net

FLAGS = flags.FLAGS
flags.DEFINE_string('net_libvirt_xml_template',
                    utils.abspath('compute/net.libvirt.xml.template'),
                    'Template file for libvirt networks')
flags.DEFINE_string('networks_path', utils.abspath('../networks'),
                    'Location to keep network config files')
flags.DEFINE_integer('public_vlan', 1, 'VLAN for public IP addresses')
flags.DEFINE_string('public_interface', 'vlan1', 'Interface for public IP addresses')
flags.DEFINE_string('bridge_dev', 'eth1',
                        'network device for bridges')
flags.DEFINE_integer('vlan_start', 100, 'First VLAN for private networks')
flags.DEFINE_integer('vlan_end', 4093, 'Last VLAN for private networks')
flags.DEFINE_integer('network_size', 256, 'Number of addresses in each private subnet')
flags.DEFINE_string('public_range', '4.4.4.0/24', 'Public IP address block')
flags.DEFINE_string('private_range', '10.0.0.0/8', 'Private IP address block')


# HACK(vish): to delay _get_keeper() loading
def _get_keeper():
    if _get_keeper.keeper == None:
        _get_keeper.keeper = datastore.Keeper(prefix="net")
    return _get_keeper.keeper
_get_keeper.keeper = None

logging.getLogger().setLevel(logging.DEBUG)

# CLEANUP:
# TODO(ja): use singleton for usermanager instead of self.manager in vlanpool et al
# TODO(ja): does vlanpool "keeper" need to know the min/max - shouldn't FLAGS always win?

class Network(object):
    def __init__(self, *args, **kwargs):
        self.bridge_gets_ip = False
        try:
            os.makedirs(FLAGS.networks_path)
        except Exception, err:
            pass
        self.load(**kwargs)

    def to_dict(self):
        return {'vlan': self.vlan,
                'network': self.network_str,
                'hosts': self.hosts}

    def load(self, **kwargs):
        self.network_str = kwargs.get('network', "192.168.100.0/24")
        self.hosts = kwargs.get('hosts', {})
        self.vlan = kwargs.get('vlan', 100)
        self.name = "nova-%s" % (self.vlan)
        self.network = IPy.IP(self.network_str)
        self.gateway = self.network[1]
        self.netmask = self.network.netmask()
        self.broadcast = self.network.broadcast()
        self.bridge_name =  "br%s" % (self.vlan)

    def __str__(self):
        return json.dumps(self.to_dict())

    def __unicode__(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, args):
        for arg in args.keys():
            value = args[arg]
            del args[arg]
            args[str(arg)] = value
        self = cls(**args)
        return self

    @classmethod
    def from_json(cls, json_string):
        parsed = json.loads(json_string)
        return cls.from_dict(parsed)

    def range(self):
        for idx in range(3, len(self.network)-2):
            yield self.network[idx]

    def allocate_ip(self, user_id, mac):
        for ip in self.range():
            address = str(ip)
            if not address in self.hosts.keys():
                logging.debug("Allocating IP %s to %s" % (address, user_id))
                self.hosts[address] = {
                    "address" : address, "user_id" : user_id, 'mac' : mac
                }
                self.express(address=address)
                return address
        raise exception.NoMoreAddresses()

    def deallocate_ip(self, ip_str):
        if not ip_str in self.hosts.keys():
            raise exception.AddressNotAllocated()
        del self.hosts[ip_str]
        # TODO(joshua) SCRUB from the leases file somehow
        self.deexpress(address=ip_str)

    def list_addresses(self):
        for address in self.hosts.values():
            yield address

    def express(self, address=None):
        pass

    def deexpress(self, address=None):
        pass


class Vlan(Network):
    """
    VLAN configuration, that when expressed creates the vlan

    properties:

        vlan - integer (example: 42)
        bridge_dev - string (example: eth0)
    """

    def __init__(self, *args, **kwargs):
        super(Vlan, self).__init__(*args, **kwargs)
        self.bridge_dev = FLAGS.bridge_dev

    def express(self, address=None):
        super(Vlan, self).express(address=address)
        try:
            logging.debug("Starting VLAN inteface for %s network" % (self.vlan))
            linux_net.vlan_create(self)
        except:
            pass


class VirtNetwork(Vlan):
    """
    Virtual Network that can export libvirt configuration or express itself to
    create a bridge (with or without an IP address/netmask/gateway)

    properties:
        bridge_name - string (example value: br42)
        vlan - integer (example value: 42)
        bridge_gets_ip - boolean used during bridge creation

        if bridge_gets_ip then network address for bridge uses the properties:
            gateway
            broadcast
            netmask
    """

    def __init__(self, *args, **kwargs):
        super(VirtNetwork, self).__init__(*args, **kwargs)

    def virtXML(self):
        """ generate XML for libvirt network """

        libvirt_xml = open(FLAGS.net_libvirt_xml_template).read()
        xml_info = {'name' : self.name,
                    'bridge_name' : self.bridge_name,
                    'device' : "vlan%s" % (self.vlan),
                    'gateway' : self.gateway,
                    'netmask' : self.netmask,
                   }
        libvirt_xml = libvirt_xml % xml_info
        return libvirt_xml

    def express(self, address=None):
        """ creates a bridge device on top of the Vlan """
        super(VirtNetwork, self).express(address=address)
        try:
            logging.debug("Starting Bridge inteface for %s network" % (self.vlan))
            linux_net.bridge_create(self)
        except:
            pass

class DHCPNetwork(VirtNetwork):
    """
    properties:
        dhcp_listen_address: the ip of the gateway / dhcp host
        dhcp_range_start: the first ip to give out
        dhcp_range_end: the last ip to give out
    """
    def __init__(self, *args, **kwargs):
        super(DHCPNetwork, self).__init__(*args, **kwargs)
        logging.debug("Initing DHCPNetwork object...")
        self.bridge_gets_ip = True
        self.dhcp_listen_address = self.network[1]
        self.dhcp_range_start = self.network[3]
        self.dhcp_range_end = self.network[-2]

    def express(self, address=None):
        super(DHCPNetwork, self).express(address=address)
        if len(self.hosts.values()) > 0:
            logging.debug("Starting dnsmasq server for network with vlan %s" % self.vlan)
            linux_net.start_dnsmasq(self)
        else:
            logging.debug("Not launching dnsmasq cause I don't think we have any hosts.")

    def deexpress(self, address=None):
        # if this is the last address, stop dns
        super(DHCPNetwork, self).deexpress(address=address)
        if len(self.hosts.values()) == 0:
            linux_net.stop_dnsmasq(self)
        else:
            linux_net.start_dnsmasq(self)


class PrivateNetwork(DHCPNetwork):
    def __init__(self, **kwargs):
        super(PrivateNetwork, self).__init__(**kwargs)
        # self.express()

    def to_dict(self):
        return {'vlan': self.vlan,
                'network': self.network_str,
                'hosts': self.hosts}

    def express(self, *args, **kwargs):
        super(PrivateNetwork, self).express(*args, **kwargs)



class PublicNetwork(Network):
    def __init__(self, network="192.168.216.0/24", **kwargs):
        super(PublicNetwork, self).__init__(network=network, **kwargs)
        self.express()

    def allocate_ip(self, user_id, mac):
        for ip in self.range():
            address = str(ip)
            if not address in self.hosts.keys():
                logging.debug("Allocating IP %s to %s" % (address, user_id))
                self.hosts[address] = {
                    "address" : address, "user_id" : user_id, 'mac' : mac
                }
                self.express(address=address)
                return address
        raise exception.NoMoreAddresses()

    def deallocate_ip(self, ip_str):
        if not ip_str in self.hosts:
            raise exception.AddressNotAllocated()
        del self.hosts[ip_str]
        # TODO(joshua) SCRUB from the leases file somehow
        self.deexpress(address=ip_str)

    def associate_address(self, public_ip, private_ip, instance_id):
        if not public_ip in self.hosts:
            raise exception.AddressNotAllocated()
        for addr in self.hosts.values():
            if addr.has_key('private_ip') and addr['private_ip'] == private_ip:
                raise exception.AddressAlreadyAssociated()
        if self.hosts[public_ip].has_key('private_ip'):
            raise exception.AddressAlreadyAssociated()
        self.hosts[public_ip]['private_ip'] = private_ip
        self.hosts[public_ip]['instance_id'] = instance_id
        self.express(address=public_ip)

    def disassociate_address(self, public_ip):
        if not public_ip in self.hosts:
            raise exception.AddressNotAllocated()
        if not self.hosts[public_ip].has_key('private_ip'):
            raise exception.AddressNotAssociated()
        self.deexpress(public_ip)
        del self.hosts[public_ip]['private_ip']
        del self.hosts[public_ip]['instance_id']
        # TODO Express the removal

    def deexpress(self, address):
        addr = self.hosts[address]
        public_ip = addr['address']
        private_ip = addr['private_ip']
        linux_net.remove_rule("PREROUTING -t nat -d %s -j DNAT --to %s" % (public_ip, private_ip))
        linux_net.remove_rule("POSTROUTING -t nat -s %s -j SNAT --to %s" % (private_ip, public_ip))
        linux_net.remove_rule("FORWARD -d %s -p icmp -j ACCEPT" % (private_ip))
        for (protocol, port) in [("tcp",80), ("tcp",22), ("udp",1194), ("tcp",443)]:
            linux_net.remove_rule("FORWARD -d %s -p %s --dport %s -j ACCEPT" % (private_ip, protocol, port))

    def express(self, address=None):
        logging.debug("Todo - need to create IPTables natting entries for this net.")
        addresses = self.hosts.values()
        if address:
            addresses = [self.hosts[address]]
        for addr in addresses:
            if not addr.has_key('private_ip'):
                continue
            public_ip = addr['address']
            private_ip = addr['private_ip']
            linux_net.bind_public_ip(public_ip, FLAGS.public_interface)
            linux_net.confirm_rule("PREROUTING -t nat -d %s -j DNAT --to %s" % (public_ip, private_ip))
            linux_net.confirm_rule("POSTROUTING -t nat -s %s -j SNAT --to %s" % (private_ip, public_ip))
            # TODO: Get these from the secgroup datastore entries
            linux_net.confirm_rule("FORWARD -d %s -p icmp -j ACCEPT" % (private_ip))
            for (protocol, port) in [("tcp",80), ("tcp",22), ("udp",1194), ("tcp",443)]:
                linux_net.confirm_rule("FORWARD -d %s -p %s --dport %s -j ACCEPT" % (private_ip, protocol, port))


class NetworkPool(object):
    # TODO - Allocations need to be system global

    def __init__(self):
        self.network = IPy.IP(FLAGS.private_range)
        netsize = FLAGS.network_size
        if not netsize in [4,8,16,32,64,128,256,512,1024]:
            raise exception.NotValidNetworkSize()
        self.netsize = netsize
        self.startvlan = FLAGS.vlan_start

    def get_from_vlan(self, vlan):
        start = (vlan-self.startvlan) * self.netsize
        net_str = "%s-%s" % (self.network[start], self.network[start + self.netsize - 1])
        logging.debug("Allocating %s" % net_str)
        return net_str


class VlanPool(object):
    def __init__(self, **kwargs):
        self.start = FLAGS.vlan_start
        self.end = FLAGS.vlan_end
        self.vlans = kwargs.get('vlans', {})
        self.vlanpool = {}
        self.manager = users.UserManager.instance()
        for user_id, vlan in self.vlans.iteritems():
            self.vlanpool[vlan] = user_id

    def to_dict(self):
        return {'vlans': self.vlans}

    def __str__(self):
        return json.dumps(self.to_dict())

    def __unicode__(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, args):
        for arg in args.keys():
            value = args[arg]
            del args[arg]
            args[str(arg)] = value
        self = cls(**args)
        return self

    @classmethod
    def from_json(cls, json_string):
        parsed = json.loads(json_string)
        return cls.from_dict(parsed)

    def assign_vlan(self, user_id, vlan):
        logging.debug("Assigning vlan %s to user %s" % (vlan, user_id))
        self.vlans[user_id] = vlan
        self.vlanpool[vlan] = user_id
        return self.vlans[user_id]

    def next(self, user_id):
        for old_user_id, vlan in self.vlans.iteritems():
            if not self.manager.get_user(old_user_id):
                _get_keeper()["%s-default" % old_user_id] = {}
                del _get_keeper()["%s-default" % old_user_id]
                del self.vlans[old_user_id]
                return self.assign_vlan(user_id, vlan)
        vlans = self.vlanpool.keys()
        vlans.append(self.start)
        nextvlan = max(vlans) + 1
        if nextvlan == self.end:
            raise exception.AddressNotAllocated("Out of VLANs")
        return self.assign_vlan(user_id, nextvlan)


class NetworkController(object):
    """ The network controller is in charge of network connections  """

    def __init__(self, **kwargs):
        logging.debug("Starting up the network controller.")
        self.manager = users.UserManager.instance()
        self._pubnet = None
        if not _get_keeper()['vlans']:
            _get_keeper()['vlans'] = {}
        if not _get_keeper()['public']:
            _get_keeper()['public'] = {'vlan': FLAGS.public_vlan, 'network' : FLAGS.public_range}
        self.express()

    def reset(self):
        _get_keeper()['public'] = {'vlan': FLAGS.public_vlan, 'network': FLAGS.public_range }
        _get_keeper()['vlans'] = {}
        # TODO : Get rid of old interfaces, bridges, and IPTables rules.

    @property
    def public_net(self):
        if not self._pubnet:
            self._pubnet = PublicNetwork.from_dict(_get_keeper()['public'])
        self._pubnet.load(**_get_keeper()['public'])
        return self._pubnet

    @property
    def vlan_pool(self):
        return VlanPool.from_dict(_get_keeper()['vlans'])

    def get_network_from_name(self, network_name):
        net_dict = _get_keeper()[network_name]
        if net_dict:
            return PrivateNetwork.from_dict(net_dict)
        return None

    def get_public_ip_for_instance(self, instance_id):
        # FIXME: this should be a lookup - iteration won't scale
        for address_record in self.describe_addresses(type=PublicNetwork):
            if address_record.get(u'instance_id', 'free') == instance_id:
                return address_record[u'address']

    def get_users_network(self, user_id):
        """ get a user's private network, allocating one if needed """

        user = self.manager.get_user(user_id)
        if not user:
           raise Exception("User %s doesn't exist, uhoh." % user_id)
        usernet = self.get_network_from_name("%s-default" % user_id)
        if not usernet:
            pool = self.vlan_pool
            vlan = pool.next(user_id)
            private_pool = NetworkPool()
            network_str = private_pool.get_from_vlan(vlan)
            logging.debug("Constructing network %s and %s for %s" % (network_str, vlan, user_id))
            usernet = PrivateNetwork(
                network=network_str,
                vlan=vlan)
            _get_keeper()["%s-default" % user_id] = usernet.to_dict()
            _get_keeper()['vlans'] = pool.to_dict()
        return usernet

    def allocate_address(self, user_id, mac=None, type=PrivateNetwork):
        ip = None
        net_name = None
        if type == PrivateNetwork:
            net = self.get_users_network(user_id)
            ip = net.allocate_ip(user_id, mac)
            net_name = net.name
            _get_keeper()["%s-default" % user_id] = net.to_dict()
        else:
            net = self.public_net
            ip = net.allocate_ip(user_id, mac)
            net_name = net.name
            _get_keeper()['public'] = net.to_dict()
        return (ip, net_name)

    def deallocate_address(self, address):
        if address in self.public_net.network:
            net = self.public_net
            rv = net.deallocate_ip(str(address))
            _get_keeper()['public'] = net.to_dict()
            return rv
        for user in self.manager.get_users():
            if address in self.get_users_network(user.id).network:
                net = self.get_users_network(user.id)
                rv = net.deallocate_ip(str(address))
                _get_keeper()["%s-default" % user.id] = net.to_dict()
                return rv
        raise exception.AddressNotAllocated()

    def describe_addresses(self, type=PrivateNetwork):
        if type == PrivateNetwork:
            addresses = []
            for user in self.manager.get_users():
                addresses.extend(self.get_users_network(user.id).list_addresses())
            return addresses
        return self.public_net.list_addresses()

    def associate_address(self, address, private_ip, instance_id):
        net = self.public_net
        rv = net.associate_address(address, private_ip, instance_id)
        _get_keeper()['public'] = net.to_dict()
        return rv

    def disassociate_address(self, address):
        net = self.public_net
        rv = net.disassociate_address(address)
        _get_keeper()['public'] = net.to_dict()
        return rv

    def express(self,address=None):
        for user in self.manager.get_users():
            self.get_users_network(user.id).express()

    def report_state(self):
        pass


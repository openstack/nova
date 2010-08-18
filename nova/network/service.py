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

import IPy
from sqlalchemy.orm import exc

from nova import exception
from nova import flags
from nova import models
from nova import service
from nova import utils
from nova.auth import manager
from nova.network import exception as network_exception
from nova.network import linux_net


FLAGS = flags.FLAGS
flags.DEFINE_string('network_type',
                    'flat',
                    'Service Class for Networking')
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

# TODO(vish): some better type of dependency injection?
_driver = linux_net

def type_to_class(network_type):
    """Convert a network_type string into an actual Python class"""
    if network_type == 'flat':
        return FlatNetworkService
    elif network_type == 'vlan':
        return VlanNetworkService
    raise exception.NotFound("Couldn't find %s network type" % network_type)


def setup_compute_network(project_id):
    """Sets up the network on a compute host"""
    network = get_network_for_project(project_id)
    srv = type_to_class(network.kind)
    srv.setup_compute_network(network)


def get_network_for_project(project_id):
    """Get network allocated to project from datastore"""
    project = manager.AuthManager().get_project(project_id)
    if not project:
        raise exception.NotFound("Couldn't find project %s" % project_id)
    return project.network


def get_host_for_project(project_id):
    """Get host allocated to project from datastore"""
    return get_network_for_project(project_id).node_name


class BaseNetworkService(service.Service):
    """Implements common network service functionality

    This class must be subclassed.
    """

    def set_network_host(self, project_id):
        """Safely sets the host of the projects network"""
        # FIXME abstract this
        session = models.NovaBase.get_session()
        # FIXME will a second request fail or wait for first to finish?
        query = session.query(models.Network).filter_by(project_id=project_id)
        network = query.with_lockmode("update").first()
        if not network:
            raise exception.NotFound("Couldn't find network for %s" %
                                     project_id)
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if network.node_name:
            return network.node_name
        network.node_name = FLAGS.node_name
        network.kind = FLAGS.network_type
        session.add(network)
        session.commit()
        self._on_set_network_host(network)

    def allocate_fixed_ip(self, project_id, instance_id, *args, **kwargs):
        """Gets fixed ip from the pool"""
        # FIXME abstract this
        network = get_network_for_project(project_id)
        session = models.NovaBase.get_session()
        query = session.query(models.FixedIp).filter_by(network_id=network.id)
        query = query.filter_by(reserved=False).filter_by(allocated=False)
        fixed_ip = query.filter_by(leased=False).with_lockmode("update").first
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not fixed_ip:
            raise network_exception.NoMoreAddresses()
        # FIXME will this set backreference?
        fixed_ip.instance_id = instance_id
        fixed_ip.allocated = True
        session.add(fixed_ip)
        session.commit()
        return fixed_ip.ip_str

    def deallocate_fixed_ip(self, fixed_ip_str, *args, **kwargs):
        """Returns a fixed ip to the pool"""
        fixed_ip = models.FixedIp.find_by_ip_str(fixed_ip_str)
        fixed_ip.instance = None
        fixed_ip.allocated = False
        fixed_ip.save()


    def _on_set_network_host(self, network, *args, **kwargs):
        """Called when this host becomes the host for a project"""
        pass

    @classmethod
    def setup_compute_network(cls, network):
        """Sets up matching network for compute hosts"""
        raise NotImplementedError()

    def allocate_elastic_ip(self, project_id):
        """Gets an elastic ip from the pool"""
        # FIXME: add elastic ips through manage command
        # FIXME: abstract this
        session = models.NovaBase.get_session()
        node_name = FLAGS.node_name
        query = session.query(models.ElasticIp).filter_by(node_name=node_name)
        query = query.filter_by(fixed_ip_id=None).with_lockmode("update")
        elastic_ip = query.first()
        if not elastic_ip:
            raise network_exception.NoMoreAddresses()
        elastic_ip.project_id = project_id
        session.add(elastic_ip)
        session.commit()
        return elastic_ip.ip_str

    def associate_elastic_ip(self, elastic_ip_str, fixed_ip_str):
        """Associates an elastic ip to a fixed ip"""
        elastic_ip = models.ElasticIp.find_by_ip_str(elastic_ip_str)
        fixed_ip = models.FixedIp.find_by_ip_str(fixed_ip_str)
        elastic_ip.fixed_ip = fixed_ip
        _driver.bind_elastic_ip(elastic_ip_str)
        _driver.ensure_elastic_forward(elastic_ip_str, fixed_ip_str)
        elastic_ip.save()

    def disassociate_elastic_ip(self, elastic_ip_str):
        """Disassociates a elastic ip"""
        elastic_ip = models.ElasticIp.find_by_ip_str(elastic_ip_str)
        fixed_ip_str = elastic_ip.fixed_ip.ip_str
        elastic_ip.fixed_ip = None
        _driver.unbind_elastic_ip(elastic_ip_str)
        _driver.remove_elastic_forward(elastic_ip_str, fixed_ip_str)
        elastic_ip.save()

    def deallocate_elastic_ip(self, elastic_ip_str):
        """Returns an elastic ip to the pool"""
        elastic_ip = models.ElasticIp.find_by_ip_str(elastic_ip_str)
        elastic_ip.project_id = None
        elastic_ip.save()


class FlatNetworkService(BaseNetworkService):
    """Basic network where no vlans are used"""

    @classmethod
    def setup_compute_network(cls, network):
        """Network is created manually"""
        pass

    def _on_set_network_host(self, network, *args, **kwargs):
        """Called when this host becomes the host for a project"""
        # FIXME should there be two types of network objects in the database?
        network.injected = True
        network.network_str=FLAGS.flat_network_network
        network.netmask=FLAGS.flat_network_netmask
        network.bridge=FLAGS.flat_network_bridge
        network.gateway=FLAGS.flat_network_gateway
        network.broadcast=FLAGS.flat_network_broadcast
        network.dns=FLAGS.flat_network_dns
        network.save()
        # FIXME add public ips from flags to the datastore

class VlanNetworkService(BaseNetworkService):
    """Vlan network with dhcp"""
    def __init__(self, *args, **kwargs):
        super(VlanNetworkService, self).__init__(*args, **kwargs)
        self._ensure_network_indexes()

    def _ensure_network_indexes(self):
        # NOTE(vish): this should probably be removed and added via
        #             admin command or fixtures
        if models.NetworkIndex.count() == 0:
            for i in range(FLAGS.num_networks):
                network_index = models.NetworkIndex()
                network_index.index = i
                network_index.save()

    def allocate_fixed_ip(self, project_id, instance_id,  is_vpn=False,
                          *args, **kwargs):
        """Gets a fixed ip from the pool"""
        network = get_network_for_project(project_id)
        if is_vpn:
            fixed_ip = models.FixedIp.find_by_ip_str(network.vpn_private_ip_str)
            if fixed_ip.allocated:
                raise network_exception.AddressAlreadyAllocated()
            # FIXME will this set backreference?
            fixed_ip.instance_id = instance_id
            fixed_ip.allocated = True
            fixed_ip.save()
            _driver.ensure_vlan_forward(network.vpn_public_ip_str,
                                        network.vpn_public_port,
                                        network.vpn_private_ip_str)
            ip_str = fixed_ip.ip_str
            logging.debug("Allocating vpn IP %s", ip_str)
        else:
            parent = super(VlanNetworkService, self)
            ip_str = parent.allocate_fixed_ip(project_id, instance_id)
        logging.debug("sql %s", FLAGS.sql_connection)
        _driver.ensure_vlan_bridge(network.vlan, network.bridge)
        return ip_str

    def deallocate_fixed_ip(self, fixed_ip_str):
        """Returns an ip to the pool"""
        fixed_ip = models.FixedIp.find_by_ip_str(fixed_ip_str)
        if fixed_ip.leased:
            logging.debug("Deallocating IP %s", fixed_ip_str)
            fixed_ip.allocated = False
            # keep instance id until release occurs
            fixed_ip.save()
        else:
            self.release_ip(fixed_ip_str)

    def lease_ip(self, fixed_ip_str):
        """Called by bridge when ip is leased"""
        logging.debug("sql %s", FLAGS.sql_connection)
        fixed_ip = models.FixedIp.find_by_ip_str(fixed_ip_str)
        if not fixed_ip.allocated:
            raise network_exception.AddressNotAllocated(fixed_ip_str)
        logging.debug("Leasing IP %s", fixed_ip_str)
        fixed_ip.leased = True
        fixed_ip.save()

    def release_ip(self, fixed_ip_str):
        """Called by bridge when ip is released"""
        fixed_ip = models.FixedIp.find_by_ip_str(fixed_ip_str)
        logging.debug("Releasing IP %s", fixed_ip_str)
        fixed_ip.leased = False
        fixed_ip.allocated = False
        fixed_ip.instance = None
        fixed_ip.save()


    def restart_nets(self):
        """Ensure the network for each user is enabled"""
        # FIXME
        pass

    def _on_set_network_host(self, network):
        """Called when this host becomes the host for a project"""
        index = self._get_network_index(network)
        private_net = IPy.IP(FLAGS.private_range)
        start = index * FLAGS.network_size
        # minus one for the gateway.
        network_str = "%s-%s" % (private_net[start],
                                 private_net[start + FLAGS.network_size - 1])
        vlan = FLAGS.vlan_start + index
        project_net = IPy.IP(network_str)
        network.network_str = network_str
        network.netmask = str(project_net.netmask())
        network.vlan = vlan
        network.bridge = 'br%s' % vlan
        network.gateway = str(project_net[1])
        network.broadcast = str(project_net.broadcast())
        network.vpn_private_ip_str = str(project_net[2])
        network.vpn_public_ip_str = FLAGS.vpn_ip
        network.vpn_public_port = FLAGS.vpn_start + index
        # create network fixed ips
        BOTTOM_RESERVED = 3
        TOP_RESERVED = 1 + FLAGS.cnt_vpn_clients
        num_ips = len(project_net)
        for i in range(num_ips):
            fixed_ip = models.FixedIp()
            fixed_ip.ip_str = str(project_net[i])
            if i < BOTTOM_RESERVED or num_ips - i < TOP_RESERVED:
                fixed_ip.reserved = True
            fixed_ip.network = network
            fixed_ip.save()


    def _get_network_index(self, network):
        """Get non-conflicting index for network"""
        session = models.NovaBase.get_session()
        node_name = FLAGS.node_name
        query = session.query(models.NetworkIndex).filter_by(network_id=None)
        network_index = query.with_lockmode("update").first()
        if not network_index:
            raise network_exception.NoMoreNetworks()
        network_index.network = network
        session.add(network_index)
        session.commit()
        return network_index.index


    @classmethod
    def setup_compute_network(cls, network):
        """Sets up matching network for compute hosts"""
        _driver.ensure_vlan_bridge(network.vlan, network.bridge)

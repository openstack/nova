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

from nova import exception
from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('db_backend', 'sqlalchemy',
                    'The backend to use for db')


_impl = utils.LazyPluggable(FLAGS['db_backend'],
                            sqlalchemy='nova.db.sqlalchemy.api')


class AddressNotAllocated(exception.Error):
    pass

class NoMoreAddresses(exception.Error):
    pass


class NoMoreBlades(exception.Error):
    pass


class NoMoreNetworks(exception.Error):
    pass


###################


def daemon_get(context, daemon_id):
    """Get an daemon or raise if it does not exist."""
    return _impl.daemon_get(context, daemon_id)


def daemon_get_by_args(context, node_name, binary):
    """Get the state of an daemon by node name and binary."""
    return _impl.daemon_get_by_args(context, node_name, binary)


def daemon_create(context, values):
    """Create a daemon from the values dictionary."""
    return _impl.daemon_create(context, values)


def daemon_update(context, daemon_id, values):
    """Set the given properties on an daemon and update it.

    Raises NotFound if daemon does not exist.

    """
    return _impl.daemon_update(context, daemon_id, values)


###################


def floating_ip_allocate_address(context, node_name, project_id):
    """Allocate free floating ip and return the address.

    Raises if one is not available.
    """
    return _impl.floating_ip_allocate_address(context, node_name, project_id)


def floating_ip_fixed_ip_associate(context, floating_address, fixed_address):
    """Associate an floating ip to a fixed_ip by address."""
    return _impl.floating_ip_fixed_ip_associate(context,
                                               floating_address,
                                               fixed_address)


def floating_ip_disassociate(context, address):
    """Disassociate an floating ip from a fixed ip by address.

    Returns the address of the existing fixed ip.
    """
    return _impl.floating_ip_disassociate(context, address)


def floating_ip_deallocate(context, address):
    """Deallocate an floating ip by address"""
    return _impl.floating_ip_deallocate(context, address)


####################


def fixed_ip_allocate(context, network_id):
    """Allocate free fixed ip and return the address.

    Raises if one is not available.
    """
    return _impl.fixed_ip_allocate(context, network_id)


def fixed_ip_get_by_address(context, address):
    """Get a fixed ip by address."""
    return _impl.fixed_ip_get_by_address(context, address)


def fixed_ip_lease(context, address):
    """Lease a fixed ip by address."""
    return _impl.fixed_ip_lease(context, address)


def fixed_ip_release(context, address):
    """Un-Lease a fixed ip by address."""
    return _impl.fixed_ip_release(context, address)


def fixed_ip_deallocate(context, address):
    """Deallocate a fixed ip by address."""
    return _impl.fixed_ip_deallocate(context, address)


def fixed_ip_instance_associate(context, address, instance_id):
    """Associate a fixed ip to an instance by address."""
    return _impl.fixed_ip_instance_associate(context, address, instance_id)


def fixed_ip_instance_disassociate(context, address):
    """Disassociate a fixed ip from an instance by address."""
    return _impl.fixed_ip_instance_disassociate(context, address)


####################


def instance_create(context, values):
    """Create an instance from the values dictionary."""
    return _impl.instance_create(context, values)


def instance_destroy(context, instance_id):
    """Destroy the instance or raise if it does not exist."""
    return _impl.instance_destroy(context, instance_id)


def instance_get(context, instance_id):
    """Get an instance or raise if it does not exist."""
    return _impl.instance_get(context, instance_id)


def instance_get_all(context):
    """Get all instances."""
    return _impl.instance_get_all(context)


def instance_get_by_name(context, name):
    """Get an instance by name."""
    return _impl.instance_get_by_project(context, name)


def instance_get_by_project(context, project_id):
    """Get all instance belonging to a project."""
    return _impl.instance_get_by_project(context, project_id)


def instance_get_by_reservation(context, reservation_id):
    """Get all instance belonging to a reservation."""
    return _impl.instance_get_by_reservation(context, reservation_id)


def instance_get_host(context, instance_id):
    """Get the host that the instance is running on."""
    return _impl.instance_get_all(context, instance_id)


def instance_state(context, instance_id, state, description=None):
    """Set the state of an instance."""
    return _impl.instance_state(context, instance_id, state, description)


def instance_update(context, instance_id, values):
    """Set the given properties on an instance and update it.

    Raises NotFound if instance does not exist.

    """
    return _impl.instance_update(context, instance_id, values)


####################


def network_allocate(context, project_id):
    """Allocate a network for a project."""
    return _impl.network_allocate(context, project_id)


def network_create(context, values):
    """Create a network from the values dictionary."""
    return _impl.network_create(context, values)


def network_create_fixed_ips(context, network_id, num_vpn_clients):
    """Create the ips for the network, reserving sepecified ips."""
    return _impl.network_create_fixed_ips(context, network_id, num_vpn_clients)


def network_destroy(context, network_id):
    """Destroy the network or raise if it does not exist."""
    return _impl.network_destroy(context, network_id)


def network_ensure_indexes(context, num_networks):
    """Ensure that network indexes exist, creating them if necessary."""
    return _impl.network_ensure_indexes(context, num_networks)


def network_get(context, network_id):
    """Get an network or raise if it does not exist."""
    return _impl.network_get(context, network_id)


def network_get_host(context, network_id):
    """Get host assigned to network or raise"""
    return _impl.network_get_host(context, network_id)


def network_get_index(context, network_id):
    """Gets non-conflicting index for network"""
    return _impl.network_get_index(context, network_id)


def network_get_vpn_ip(context, network_id):
    """Gets non-conflicting index for network"""
    return _impl.network_get_vpn_ip(context, network_id)


def network_set_cidr(context, network_id, cidr):
    """Set the Classless Inner Domain Routing for the network"""
    return _impl.network_set_cidr(context, network_id, cidr)


def network_set_host(context, network_id, host_id):
    """Safely set the host for network"""
    return _impl.network_set_host(context, network_id, host_id)


def network_update(context, network_id, values):
    """Set the given properties on an network and update it.

    Raises NotFound if network does not exist.

    """
    return _impl.network_update(context, network_id, values)


###################


def project_get_network(context, project_id):
    """Return the network associated with the project."""
    return _impl.project_get_network(context, project_id)


###################


def queue_get_for(context, topic, physical_node_id):
    """Return a channel to send a message to a node with a topic."""
    return _impl.queue_get_for(context, topic, physical_node_id)


###################


def volume_allocate_shelf_and_blade(context, volume_id):
    """Atomically allocate a free shelf and blade from the pool."""
    return _impl.volume_allocate_shelf_and_blade(context, volume_id)


def volume_attached(context, volume_id, instance_id, mountpoint):
    """Ensure that a volume is set as attached."""
    return _impl.volume_attached(context, volume_id, instance_id, mountpoint)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return _impl.volume_create(context, values)


def volume_destroy(context, volume_id):
    """Destroy the volume or raise if it does not exist."""
    return _impl.volume_destroy(context, volume_id)


def volume_detached(context, volume_id):
    """Ensure that a volume is set as detached."""
    return _impl.volume_detached(context, volume_id)


def volume_get(context, volume_id):
    """Get a volume or raise if it does not exist."""
    return _impl.volume_get(context, volume_id)


def volume_get_shelf_and_blade(context, volume_id):
    """Get the shelf and blade allocated to the volume."""
    return _impl.volume_get_shelf_and_blade(context, volume_id)


def volume_update(context, volume_id, values):
    """Set the given properties on an volume and update it.

    Raises NotFound if volume does not exist.

    """
    return _impl.volume_update(context, volume_id, values)

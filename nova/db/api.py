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
Defines interface for DB access
"""

from nova import exception
from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('db_backend', 'sqlalchemy',
                    'The backend to use for db')


IMPL = utils.LazyPluggable(FLAGS['db_backend'],
                           sqlalchemy='nova.db.sqlalchemy.api')


class NoMoreAddresses(exception.Error):
    """No more available addresses"""
    pass


class NoMoreBlades(exception.Error):
    """No more available blades"""
    pass


class NoMoreNetworks(exception.Error):
    """No more available networks"""
    pass


###################


def service_get(context, service_id):
    """Get an service or raise if it does not exist."""
    return IMPL.service_get(context, service_id)


def service_get_by_args(context, host, binary):
    """Get the state of an service by node name and binary."""
    return IMPL.service_get_by_args(context, host, binary)


def service_create(context, values):
    """Create a service from the values dictionary."""
    return IMPL.service_create(context, values)


def service_update(context, service_id, values):
    """Set the given properties on an service and update it.

    Raises NotFound if service does not exist.

    """
    return IMPL.service_update(context, service_id, values)


###################


def floating_ip_allocate_address(context, host, project_id):
    """Allocate free floating ip and return the address.

    Raises if one is not available.
    """
    return IMPL.floating_ip_allocate_address(context, host, project_id)


def floating_ip_create(context, values):
    """Create a floating ip from the values dictionary."""
    return IMPL.floating_ip_create(context, values)


def floating_ip_deallocate(context, address):
    """Deallocate an floating ip by address"""
    return IMPL.floating_ip_deallocate(context, address)


def floating_ip_destroy(context, address):
    """Destroy the floating_ip or raise if it does not exist."""
    return IMPL.floating_ip_destroy(context, address)


def floating_ip_disassociate(context, address):
    """Disassociate an floating ip from a fixed ip by address.

    Returns the address of the existing fixed ip.
    """
    return IMPL.floating_ip_disassociate(context, address)


def floating_ip_fixed_ip_associate(context, floating_address, fixed_address):
    """Associate an floating ip to a fixed_ip by address."""
    return IMPL.floating_ip_fixed_ip_associate(context,
                                               floating_address,
                                               fixed_address)


def floating_ip_get_all(context):
    """Get all floating ips."""
    return IMPL.floating_ip_get_all(context)


def floating_ip_get_all_by_host(context, host):
    """Get all floating ips."""
    return IMPL.floating_ip_get_all_by_host(context, host)


def floating_ip_get_by_address(context, address):
    """Get a floating ip by address or raise if it doesn't exist."""
    return IMPL.floating_ip_get_by_address(context, address)


def floating_ip_get_instance(context, address):
    """Get an instance for a floating ip by address."""
    return IMPL.floating_ip_get_instance(context, address)


####################


def fixed_ip_allocate(context, network_id):
    """Allocate free fixed ip and return the address.

    Raises if one is not available.
    """
    return IMPL.fixed_ip_allocate(context, network_id)


def fixed_ip_create(context, values):
    """Create a fixed ip from the values dictionary."""
    return IMPL.fixed_ip_create(context, values)


def fixed_ip_deallocate(context, address):
    """Deallocate a fixed ip by address."""
    return IMPL.fixed_ip_deallocate(context, address)


def fixed_ip_get_by_address(context, address):
    """Get a fixed ip by address or raise if it does not exist."""
    return IMPL.fixed_ip_get_by_address(context, address)


def fixed_ip_get_instance(context, address):
    """Get an instance for a fixed ip by address."""
    return IMPL.fixed_ip_get_instance(context, address)


def fixed_ip_get_network(context, address):
    """Get a network for a fixed ip by address."""
    return IMPL.fixed_ip_get_network(context, address)


def fixed_ip_instance_associate(context, address, instance_id):
    """Associate a fixed ip to an instance by address."""
    return IMPL.fixed_ip_instance_associate(context, address, instance_id)


def fixed_ip_instance_disassociate(context, address):
    """Disassociate a fixed ip from an instance by address."""
    return IMPL.fixed_ip_instance_disassociate(context, address)


def fixed_ip_update(context, address, values):
    """Create a fixed ip from the values dictionary."""
    return IMPL.fixed_ip_update(context, address, values)


####################


def instance_create(context, values):
    """Create an instance from the values dictionary."""
    return IMPL.instance_create(context, values)


def instance_destroy(context, instance_id):
    """Destroy the instance or raise if it does not exist."""
    return IMPL.instance_destroy(context, instance_id)


def instance_get(context, instance_id):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get(context, instance_id)


def instance_get_all(context):
    """Get all instances."""
    return IMPL.instance_get_all(context)


def instance_get_by_project(context, project_id):
    """Get all instance belonging to a project."""
    return IMPL.instance_get_by_project(context, project_id)


def instance_get_by_reservation(context, reservation_id):
    """Get all instance belonging to a reservation."""
    return IMPL.instance_get_by_reservation(context, reservation_id)


def instance_get_fixed_address(context, instance_id):
    """Get the fixed ip address of an instance."""
    return IMPL.instance_get_fixed_address(context, instance_id)


def instance_get_floating_address(context, instance_id):
    """Get the first floating ip address of an instance."""
    return IMPL.instance_get_floating_address(context, instance_id)


def instance_get_by_str(context, str_id):
    """Get an instance by string id."""
    return IMPL.instance_get_by_str(context, str_id)


def instance_get_host(context, instance_id):
    """Get the host that the instance is running on."""
    return IMPL.instance_get_host(context, instance_id)


def instance_is_vpn(context, instance_id):
    """True if instance is a vpn."""
    return IMPL.instance_is_vpn(context, instance_id)


def instance_set_state(context, instance_id, state, description=None):
    """Set the state of an instance."""
    return IMPL.instance_set_state(context, instance_id, state, description)


def instance_update(context, instance_id, values):
    """Set the given properties on an instance and update it.

    Raises NotFound if instance does not exist.

    """
    return IMPL.instance_update(context, instance_id, values)


####################


def network_count(context):
    """Return the number of networks."""
    return IMPL.network_count(context)


def network_count_allocated_ips(context, network_id):
    """Return the number of allocated non-reserved ips in the network."""
    return IMPL.network_count_allocated_ips(context, network_id)


def network_count_available_ips(context, network_id):
    """Return the number of available ips in the network."""
    return IMPL.network_count_available_ips(context, network_id)


def network_count_reserved_ips(context, network_id):
    """Return the number of reserved ips in the network."""
    return IMPL.network_count_reserved_ips(context, network_id)


def network_create(context, values):
    """Create a network from the values dictionary."""
    return IMPL.network_create(context, values)


def network_create_fixed_ips(context, network_id, num_vpn_clients):
    """Create the ips for the network, reserving sepecified ips."""
    return IMPL.network_create_fixed_ips(context, network_id, num_vpn_clients)


def network_destroy(context, network_id):
    """Destroy the network or raise if it does not exist."""
    return IMPL.network_destroy(context, network_id)


def network_get(context, network_id):
    """Get an network or raise if it does not exist."""
    return IMPL.network_get(context, network_id)


# pylint: disable-msg=C0103
def network_get_associated_fixed_ips(context, network_id):
    """Get all network's ips that have been associated."""
    return IMPL.network_get_associated_fixed_ips(context, network_id)


def network_get_by_bridge(context, bridge):
    """Get an network or raise if it does not exist."""
    return IMPL.network_get_by_bridge(context, bridge)


def network_get_host(context, network_id):
    """Get host assigned to network or raise"""
    return IMPL.network_get_host(context, network_id)


def network_get_index(context, network_id):
    """Get non-conflicting index for network"""
    return IMPL.network_get_index(context, network_id)


def network_get_vpn_ip(context, network_id):
    """Get non-conflicting index for network"""
    return IMPL.network_get_vpn_ip(context, network_id)


def network_index_count(context):
    """Return count of network indexes"""
    return IMPL.network_index_count(context)


def network_index_create(context, values):
    """Create a network index from the values dict"""
    return IMPL.network_index_create(context, values)


def network_set_cidr(context, network_id, cidr):
    """Set the Classless Inner Domain Routing for the network"""
    return IMPL.network_set_cidr(context, network_id, cidr)


def network_set_host(context, network_id, host_id):
    """Safely set the host for network"""
    return IMPL.network_set_host(context, network_id, host_id)


def network_update(context, network_id, values):
    """Set the given properties on an network and update it.

    Raises NotFound if network does not exist.

    """
    return IMPL.network_update(context, network_id, values)


###################


def project_get_network(context, project_id):
    """Return the network associated with the project."""
    return IMPL.project_get_network(context, project_id)


###################


def queue_get_for(context, topic, physical_node_id):
    """Return a channel to send a message to a node with a topic."""
    return IMPL.queue_get_for(context, topic, physical_node_id)


###################


def export_device_count(context):
    """Return count of export devices."""
    return IMPL.export_device_count(context)


def export_device_create(context, values):
    """Create an export_device from the values dictionary."""
    return IMPL.export_device_create(context, values)


###################


def volume_allocate_shelf_and_blade(context, volume_id):
    """Atomically allocate a free shelf and blade from the pool."""
    return IMPL.volume_allocate_shelf_and_blade(context, volume_id)


def volume_attached(context, volume_id, instance_id, mountpoint):
    """Ensure that a volume is set as attached."""
    return IMPL.volume_attached(context, volume_id, instance_id, mountpoint)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return IMPL.volume_create(context, values)


def volume_destroy(context, volume_id):
    """Destroy the volume or raise if it does not exist."""
    return IMPL.volume_destroy(context, volume_id)


def volume_detached(context, volume_id):
    """Ensure that a volume is set as detached."""
    return IMPL.volume_detached(context, volume_id)


def volume_get(context, volume_id):
    """Get a volume or raise if it does not exist."""
    return IMPL.volume_get(context, volume_id)


def volume_get_all(context):
    """Get all volumes."""
    return IMPL.volume_get_all(context)


def volume_get_instance(context, volume_id):
    """Get the instance that a volume is attached to."""
    return IMPL.volume_get_instance(context, volume_id)


def volume_get_by_project(context, project_id):
    """Get all volumes belonging to a project."""
    return IMPL.volume_get_by_project(context, project_id)


def volume_get_by_str(context, str_id):
    """Get a volume by string id."""
    return IMPL.volume_get_by_str(context, str_id)


def volume_get_host(context, volume_id):
    """Get the host that the volume is running on."""
    return IMPL.volume_get_host(context, volume_id)


def volume_get_shelf_and_blade(context, volume_id):
    """Get the shelf and blade allocated to the volume."""
    return IMPL.volume_get_shelf_and_blade(context, volume_id)


def volume_update(context, volume_id, values):
    """Set the given properties on an volume and update it.

    Raises NotFound if volume does not exist.

    """
    return IMPL.volume_update(context, volume_id, values)

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

"""Defines interface for DB access.

The underlying driver is loaded as a :class:`LazyPluggable`.

**Related Flags**

:db_backend:  string to lookup in the list of LazyPluggable backends.
              `sqlalchemy` is the only supported backend right now.

:sql_connection:  string specifying the sqlalchemy connection to use, like:
                  `sqlite:///var/lib/nova/nova.sqlite`.

:enable_new_services:  when adding a new service to the database, is it in the
                       pool of available hardware (Default: True)

"""

from nova import exception
from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('db_backend', 'sqlalchemy',
                    'The backend to use for db')
flags.DEFINE_boolean('enable_new_services', True,
                     'Services to be added to the available pool on create')
flags.DEFINE_string('instance_name_template', 'instance-%08x',
                    'Template string to be used to generate instance names')
flags.DEFINE_string('volume_name_template', 'volume-%08x',
                    'Template string to be used to generate instance names')
flags.DEFINE_string('snapshot_name_template', 'snapshot-%08x',
                    'Template string to be used to generate snapshot names')
flags.DEFINE_string('vsa_name_template', 'vsa-%08x',
                    'Template string to be used to generate VSA names')

IMPL = utils.LazyPluggable(FLAGS['db_backend'],
                           sqlalchemy='nova.db.sqlalchemy.api')


class NoMoreBlades(exception.Error):
    """No more available blades."""
    pass


class NoMoreNetworks(exception.Error):
    """No more available networks."""
    pass


class NoMoreTargets(exception.Error):
    """No more available blades"""
    pass


###################


def service_destroy(context, instance_id):
    """Destroy the service or raise if it does not exist."""
    return IMPL.service_destroy(context, instance_id)


def service_get(context, service_id):
    """Get a service or raise if it does not exist."""
    return IMPL.service_get(context, service_id)


def service_get_by_host_and_topic(context, host, topic):
    """Get a service by host it's on and topic it listens to."""
    return IMPL.service_get_by_host_and_topic(context, host, topic)


def service_get_all(context, disabled=None):
    """Get all services."""
    return IMPL.service_get_all(context, disabled)


def service_get_all_by_topic(context, topic):
    """Get all services for a given topic."""
    return IMPL.service_get_all_by_topic(context, topic)


def service_get_all_by_host(context, host):
    """Get all services for a given host."""
    return IMPL.service_get_all_by_host(context, host)


def service_get_all_compute_by_host(context, host):
    """Get all compute services for a given host."""
    return IMPL.service_get_all_compute_by_host(context, host)


def service_get_all_compute_sorted(context):
    """Get all compute services sorted by instance count.

    :returns: a list of (Service, instance_count) tuples.

    """
    return IMPL.service_get_all_compute_sorted(context)


def service_get_all_network_sorted(context):
    """Get all network services sorted by network count.

    :returns: a list of (Service, network_count) tuples.

    """
    return IMPL.service_get_all_network_sorted(context)


def service_get_all_volume_sorted(context):
    """Get all volume services sorted by volume count.

    :returns: a list of (Service, volume_count) tuples.

    """
    return IMPL.service_get_all_volume_sorted(context)


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


def compute_node_get(context, compute_id, session=None):
    """Get an computeNode or raise if it does not exist."""
    return IMPL.compute_node_get(context, compute_id)


def compute_node_create(context, values):
    """Create a computeNode from the values dictionary."""
    return IMPL.compute_node_create(context, values)


def compute_node_update(context, compute_id, values):
    """Set the given properties on an computeNode and update it.

    Raises NotFound if computeNode does not exist.

    """

    return IMPL.compute_node_update(context, compute_id, values)


###################


def certificate_create(context, values):
    """Create a certificate from the values dictionary."""
    return IMPL.certificate_create(context, values)


def certificate_destroy(context, certificate_id):
    """Destroy the certificate or raise if it does not exist."""
    return IMPL.certificate_destroy(context, certificate_id)


def certificate_get_all_by_project(context, project_id):
    """Get all certificates for a project."""
    return IMPL.certificate_get_all_by_project(context, project_id)


def certificate_get_all_by_user(context, user_id):
    """Get all certificates for a user."""
    return IMPL.certificate_get_all_by_user(context, user_id)


def certificate_get_all_by_user_and_project(context, user_id, project_id):
    """Get all certificates for a user and project."""
    return IMPL.certificate_get_all_by_user_and_project(context,
                                                        user_id,
                                                        project_id)


def certificate_update(context, certificate_id, values):
    """Set the given properties on an certificate and update it.

    Raises NotFound if service does not exist.

    """
    return IMPL.certificate_update(context, certificate_id, values)


###################

def floating_ip_get(context, id):
    return IMPL.floating_ip_get(context, id)


def floating_ip_allocate_address(context, project_id):
    """Allocate free floating ip and return the address.

    Raises if one is not available.

    """
    return IMPL.floating_ip_allocate_address(context, project_id)


def floating_ip_create(context, values):
    """Create a floating ip from the values dictionary."""
    return IMPL.floating_ip_create(context, values)


def floating_ip_count_by_project(context, project_id):
    """Count floating ips used by project."""
    return IMPL.floating_ip_count_by_project(context, project_id)


def floating_ip_deallocate(context, address):
    """Deallocate an floating ip by address."""
    return IMPL.floating_ip_deallocate(context, address)


def floating_ip_destroy(context, address):
    """Destroy the floating_ip or raise if it does not exist."""
    return IMPL.floating_ip_destroy(context, address)


def floating_ip_disassociate(context, address):
    """Disassociate an floating ip from a fixed ip by address.

    :returns: the address of the existing fixed ip.

    """
    return IMPL.floating_ip_disassociate(context, address)


def floating_ip_fixed_ip_associate(context, floating_address,
                                   fixed_address, host):
    """Associate an floating ip to a fixed_ip by address."""
    return IMPL.floating_ip_fixed_ip_associate(context,
                                               floating_address,
                                               fixed_address,
                                               host)


def floating_ip_get_all(context):
    """Get all floating ips."""
    return IMPL.floating_ip_get_all(context)


def floating_ip_get_all_by_host(context, host):
    """Get all floating ips by host."""
    return IMPL.floating_ip_get_all_by_host(context, host)


def floating_ip_get_all_by_project(context, project_id):
    """Get all floating ips by project."""
    return IMPL.floating_ip_get_all_by_project(context, project_id)


def floating_ip_get_by_address(context, address):
    """Get a floating ip by address or raise if it doesn't exist."""
    return IMPL.floating_ip_get_by_address(context, address)


def floating_ip_update(context, address, values):
    """Update a floating ip by address or raise if it doesn't exist."""
    return IMPL.floating_ip_update(context, address, values)


def floating_ip_set_auto_assigned(context, address):
    """Set auto_assigned flag to floating ip"""
    return IMPL.floating_ip_set_auto_assigned(context, address)

####################


def migration_update(context, id, values):
    """Update a migration instance."""
    return IMPL.migration_update(context, id, values)


def migration_create(context, values):
    """Create a migration record."""
    return IMPL.migration_create(context, values)


def migration_get(context, migration_id):
    """Finds a migration by the id."""
    return IMPL.migration_get(context, migration_id)


def migration_get_by_instance_and_status(context, instance_uuid, status):
    """Finds a migration by the instance uuid its migrating."""
    return IMPL.migration_get_by_instance_and_status(context, instance_uuid,
            status)


####################


def fixed_ip_associate(context, address, instance_id, network_id=None,
                       reserved=False):
    """Associate fixed ip to instance.

    Raises if fixed ip is not available.

    """
    return IMPL.fixed_ip_associate(context, address, instance_id, network_id,
                                   reserved)


def fixed_ip_associate_pool(context, network_id, instance_id=None, host=None):
    """Find free ip in network and associate it to instance or host.

    Raises if one is not available.

    """
    return IMPL.fixed_ip_associate_pool(context, network_id,
                                        instance_id, host)


def fixed_ip_create(context, values):
    """Create a fixed ip from the values dictionary."""
    return IMPL.fixed_ip_create(context, values)


def fixed_ip_disassociate(context, address):
    """Disassociate a fixed ip from an instance by address."""
    return IMPL.fixed_ip_disassociate(context, address)


def fixed_ip_disassociate_all_by_timeout(context, host, time):
    """Disassociate old fixed ips from host."""
    return IMPL.fixed_ip_disassociate_all_by_timeout(context, host, time)


def fixed_ip_get_all(context):
    """Get all defined fixed ips."""
    return IMPL.fixed_ip_get_all(context)


def fixed_ip_get_all_by_instance_host(context, host):
    """Get all allocated fixed ips filtered by instance host."""
    return IMPL.fixed_ip_get_all_by_instance_host(context, host)


def fixed_ip_get_by_address(context, address):
    """Get a fixed ip by address or raise if it does not exist."""
    return IMPL.fixed_ip_get_by_address(context, address)


def fixed_ip_get_by_instance(context, instance_id):
    """Get fixed ips by instance or raise if none exist."""
    return IMPL.fixed_ip_get_by_instance(context, instance_id)


def fixed_ip_get_by_network_host(context, network_id, host):
    """Get fixed ip for a host in a network."""
    return IMPL.fixed_ip_get_by_network_host(context, network_id, host)


def fixed_ip_get_by_virtual_interface(context, vif_id):
    """Get fixed ips by virtual interface or raise if none exist."""
    return IMPL.fixed_ip_get_by_virtual_interface(context, vif_id)


def fixed_ip_get_network(context, address):
    """Get a network for a fixed ip by address."""
    return IMPL.fixed_ip_get_network(context, address)


def fixed_ip_update(context, address, values):
    """Create a fixed ip from the values dictionary."""
    return IMPL.fixed_ip_update(context, address, values)

####################


def virtual_interface_create(context, values):
    """Create a virtual interface record in the database."""
    return IMPL.virtual_interface_create(context, values)


def virtual_interface_update(context, vif_id, values):
    """Update a virtual interface record in the database."""
    return IMPL.virtual_interface_update(context, vif_id, values)


def virtual_interface_get(context, vif_id):
    """Gets a virtual interface from the table,"""
    return IMPL.virtual_interface_get(context, vif_id)


def virtual_interface_get_by_address(context, address):
    """Gets a virtual interface from the table filtering on address."""
    return IMPL.virtual_interface_get_by_address(context, address)


def virtual_interface_get_by_uuid(context, vif_uuid):
    """Gets a virtual interface from the table filtering on vif uuid."""
    return IMPL.virtual_interface_get_by_uuid(context, vif_uuid)


def virtual_interface_get_by_fixed_ip(context, fixed_ip_id):
    """Gets the virtual interface fixed_ip is associated with."""
    return IMPL.virtual_interface_get_by_fixed_ip(context, fixed_ip_id)


def virtual_interface_get_by_instance(context, instance_id):
    """Gets all virtual_interfaces for instance."""
    return IMPL.virtual_interface_get_by_instance(context, instance_id)


def virtual_interface_get_by_instance_and_network(context, instance_id,
                                                           network_id):
    """Gets all virtual interfaces for instance."""
    return IMPL.virtual_interface_get_by_instance_and_network(context,
                                                              instance_id,
                                                              network_id)


def virtual_interface_get_by_network(context, network_id):
    """Gets all virtual interfaces on network."""
    return IMPL.virtual_interface_get_by_network(context, network_id)


def virtual_interface_delete(context, vif_id):
    """Delete virtual interface record from the database."""
    return IMPL.virtual_interface_delete(context, vif_id)


def virtual_interface_delete_by_instance(context, instance_id):
    """Delete virtual interface records associated with instance."""
    return IMPL.virtual_interface_delete_by_instance(context, instance_id)


####################


def instance_create(context, values):
    """Create an instance from the values dictionary."""
    return IMPL.instance_create(context, values)


def instance_data_get_for_project(context, project_id):
    """Get (instance_count, total_cores, total_ram) for project."""
    return IMPL.instance_data_get_for_project(context, project_id)


def instance_destroy(context, instance_id):
    """Destroy the instance or raise if it does not exist."""
    return IMPL.instance_destroy(context, instance_id)


def instance_stop(context, instance_id):
    """Stop the instance or raise if it does not exist."""
    return IMPL.instance_stop(context, instance_id)


def instance_get_by_uuid(context, uuid):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get_by_uuid(context, uuid)


def instance_get(context, instance_id):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get(context, instance_id)


def instance_get_all(context):
    """Get all instances."""
    return IMPL.instance_get_all(context)


def instance_get_all_by_filters(context, filters):
    """Get all instances that match all filters."""
    return IMPL.instance_get_all_by_filters(context, filters)


def instance_get_active_by_window(context, begin, end=None, project_id=None):
    """Get instances active during a certain time window.

    Specifying a project_id will filter for a certain project."""
    return IMPL.instance_get_active_by_window(context, begin, end, project_id)


def instance_get_active_by_window_joined(context, begin, end=None,
                                         project_id=None):
    """Get instances and joins active during a certain time window.

    Specifying a project_id will filter for a certain project."""
    return IMPL.instance_get_active_by_window_joined(context, begin, end,
                                              project_id)


def instance_get_all_by_user(context, user_id):
    """Get all instances."""
    return IMPL.instance_get_all_by_user(context, user_id)


def instance_get_all_by_project(context, project_id):
    """Get all instance belonging to a project."""
    return IMPL.instance_get_all_by_project(context, project_id)


def instance_get_all_by_host(context, host):
    """Get all instance belonging to a host."""
    return IMPL.instance_get_all_by_host(context, host)


def instance_get_all_by_reservation(context, reservation_id):
    """Get all instances belonging to a reservation."""
    return IMPL.instance_get_all_by_reservation(context, reservation_id)


def instance_get_by_fixed_ip(context, address):
    """Get an instance for a fixed ip by address."""
    return IMPL.instance_get_by_fixed_ip(context, address)


def instance_get_by_fixed_ipv6(context, address):
    """Get an instance for a fixed ip by IPv6 address."""
    return IMPL.instance_get_by_fixed_ipv6(context, address)


def instance_get_fixed_addresses(context, instance_id):
    """Get the fixed ip address of an instance."""
    return IMPL.instance_get_fixed_addresses(context, instance_id)


def instance_get_fixed_addresses_v6(context, instance_id):
    return IMPL.instance_get_fixed_addresses_v6(context, instance_id)


def instance_get_floating_address(context, instance_id):
    """Get the first floating ip address of an instance."""
    return IMPL.instance_get_floating_address(context, instance_id)


def instance_get_project_vpn(context, project_id):
    """Get a vpn instance by project or return None."""
    return IMPL.instance_get_project_vpn(context, project_id)


def instance_set_state(context, instance_id, state, description=None):
    """Set the state of an instance."""
    return IMPL.instance_set_state(context, instance_id, state, description)


def instance_update(context, instance_id, values):
    """Set the given properties on an instance and update it.

    Raises NotFound if instance does not exist.

    """
    return IMPL.instance_update(context, instance_id, values)


def instance_add_security_group(context, instance_id, security_group_id):
    """Associate the given security group with the given instance."""
    return IMPL.instance_add_security_group(context, instance_id,
                                            security_group_id)


def instance_remove_security_group(context, instance_id, security_group_id):
    """Disassociate the given security group from the given instance."""
    return IMPL.instance_remove_security_group(context, instance_id,
                                            security_group_id)


def instance_action_create(context, values):
    """Create an instance action from the values dictionary."""
    return IMPL.instance_action_create(context, values)


def instance_get_actions(context, instance_id):
    """Get instance actions by instance id."""
    return IMPL.instance_get_actions(context, instance_id)


###################


def key_pair_create(context, values):
    """Create a key_pair from the values dictionary."""
    return IMPL.key_pair_create(context, values)


def key_pair_destroy(context, user_id, name):
    """Destroy the key_pair or raise if it does not exist."""
    return IMPL.key_pair_destroy(context, user_id, name)


def key_pair_destroy_all_by_user(context, user_id):
    """Destroy all key_pairs by user."""
    return IMPL.key_pair_destroy_all_by_user(context, user_id)


def key_pair_get(context, user_id, name):
    """Get a key_pair or raise if it does not exist."""
    return IMPL.key_pair_get(context, user_id, name)


def key_pair_get_all_by_user(context, user_id):
    """Get all key_pairs by user."""
    return IMPL.key_pair_get_all_by_user(context, user_id)


####################


def network_associate(context, project_id, force=False):
    """Associate a free network to a project."""
    return IMPL.network_associate(context, project_id, force)


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


def network_create_safe(context, values):
    """Create a network from the values dict.

    The network is only returned if the create succeeds. If the create violates
    constraints because the network already exists, no exception is raised.

    """
    return IMPL.network_create_safe(context, values)


def network_delete_safe(context, network_id):
    """Delete network with key network_id.

    This method assumes that the network is not associated with any project

    """
    return IMPL.network_delete_safe(context, network_id)


def network_create_fixed_ips(context, network_id, num_vpn_clients):
    """Create the ips for the network, reserving sepecified ips."""
    return IMPL.network_create_fixed_ips(context, network_id, num_vpn_clients)


def network_disassociate(context, network_id):
    """Disassociate the network from project or raise if it does not exist."""
    return IMPL.network_disassociate(context, network_id)


def network_disassociate_all(context):
    """Disassociate all networks from projects."""
    return IMPL.network_disassociate_all(context)


def network_get(context, network_id):
    """Get an network or raise if it does not exist."""
    return IMPL.network_get(context, network_id)


def network_get_all(context):
    """Return all defined networks."""
    return IMPL.network_get_all(context)


def network_get_all_by_uuids(context, network_uuids, project_id=None):
    """Return networks by ids."""
    return IMPL.network_get_all_by_uuids(context, network_uuids, project_id)


# pylint: disable=C0103


def network_get_associated_fixed_ips(context, network_id):
    """Get all network's ips that have been associated."""
    return IMPL.network_get_associated_fixed_ips(context, network_id)


def network_get_by_bridge(context, bridge):
    """Get a network by bridge or raise if it does not exist."""
    return IMPL.network_get_by_bridge(context, bridge)


def network_get_by_uuid(context, uuid):
    """Get a network by uuid or raise if it does not exist."""
    return IMPL.network_get_by_uuid(context, uuid)


def network_get_by_cidr(context, cidr):
    """Get a network by cidr or raise if it does not exist"""
    return IMPL.network_get_by_cidr(context, cidr)


def network_get_by_instance(context, instance_id):
    """Get a network by instance id or raise if it does not exist."""
    return IMPL.network_get_by_instance(context, instance_id)


def network_get_all_by_instance(context, instance_id):
    """Get all networks by instance id or raise if none exist."""
    return IMPL.network_get_all_by_instance(context, instance_id)


def network_get_all_by_host(context, host):
    """All networks for which the given host is the network host."""
    return IMPL.network_get_all_by_host(context, host)


def network_get_index(context, network_id):
    """Get non-conflicting index for network."""
    return IMPL.network_get_index(context, network_id)


def network_get_vpn_ip(context, network_id):
    """Get non-conflicting index for network."""
    return IMPL.network_get_vpn_ip(context, network_id)


def network_set_cidr(context, network_id, cidr):
    """Set the Classless Inner Domain Routing for the network."""
    return IMPL.network_set_cidr(context, network_id, cidr)


def network_set_host(context, network_id, host_id):
    """Safely set the host for network."""
    return IMPL.network_set_host(context, network_id, host_id)


def network_update(context, network_id, values):
    """Set the given properties on an network and update it.

    Raises NotFound if network does not exist.

    """
    return IMPL.network_update(context, network_id, values)


###################


def queue_get_for(context, topic, physical_node_id):
    """Return a channel to send a message to a node with a topic."""
    return IMPL.queue_get_for(context, topic, physical_node_id)


###################


def export_device_count(context):
    """Return count of export devices."""
    return IMPL.export_device_count(context)


def export_device_create_safe(context, values):
    """Create an export_device from the values dictionary.

    The device is not returned. If the create violates the unique
    constraints because the shelf_id and blade_id already exist,
    no exception is raised.

    """
    return IMPL.export_device_create_safe(context, values)


###################


def iscsi_target_count_by_host(context, host):
    """Return count of export devices."""
    return IMPL.iscsi_target_count_by_host(context, host)


def iscsi_target_create_safe(context, values):
    """Create an iscsi_target from the values dictionary.

    The device is not returned. If the create violates the unique
    constraints because the iscsi_target and host already exist,
    no exception is raised.

    """
    return IMPL.iscsi_target_create_safe(context, values)


###############


def auth_token_destroy(context, token_id):
    """Destroy an auth token."""
    return IMPL.auth_token_destroy(context, token_id)


def auth_token_get(context, token_hash):
    """Retrieves a token given the hash representing it."""
    return IMPL.auth_token_get(context, token_hash)


def auth_token_update(context, token_hash, values):
    """Updates a token given the hash representing it."""
    return IMPL.auth_token_update(context, token_hash, values)


def auth_token_create(context, token):
    """Creates a new token."""
    return IMPL.auth_token_create(context, token)


###################


def quota_create(context, project_id, resource, limit):
    """Create a quota for the given project and resource."""
    return IMPL.quota_create(context, project_id, resource, limit)


def quota_get(context, project_id, resource):
    """Retrieve a quota or raise if it does not exist."""
    return IMPL.quota_get(context, project_id, resource)


def quota_get_all_by_project(context, project_id):
    """Retrieve all quotas associated with a given project."""
    return IMPL.quota_get_all_by_project(context, project_id)


def quota_update(context, project_id, resource, limit):
    """Update a quota or raise if it does not exist."""
    return IMPL.quota_update(context, project_id, resource, limit)


def quota_destroy(context, project_id, resource):
    """Destroy the quota or raise if it does not exist."""
    return IMPL.quota_destroy(context, project_id, resource)


def quota_destroy_all_by_project(context, project_id):
    """Destroy all quotas associated with a given project."""
    return IMPL.quota_get_all_by_project(context, project_id)


###################


def volume_allocate_shelf_and_blade(context, volume_id):
    """Atomically allocate a free shelf and blade from the pool."""
    return IMPL.volume_allocate_shelf_and_blade(context, volume_id)


def volume_allocate_iscsi_target(context, volume_id, host):
    """Atomically allocate a free iscsi_target from the pool."""
    return IMPL.volume_allocate_iscsi_target(context, volume_id, host)


def volume_attached(context, volume_id, instance_id, mountpoint):
    """Ensure that a volume is set as attached."""
    return IMPL.volume_attached(context, volume_id, instance_id, mountpoint)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return IMPL.volume_create(context, values)


def volume_data_get_for_project(context, project_id):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_project(context, project_id)


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


def volume_get_all_by_host(context, host):
    """Get all volumes belonging to a host."""
    return IMPL.volume_get_all_by_host(context, host)


def volume_get_all_by_instance(context, instance_id):
    """Get all volumes belonging to a instance."""
    return IMPL.volume_get_all_by_instance(context, instance_id)


def volume_get_all_by_project(context, project_id):
    """Get all volumes belonging to a project."""
    return IMPL.volume_get_all_by_project(context, project_id)


def volume_get_by_ec2_id(context, ec2_id):
    """Get a volume by ec2 id."""
    return IMPL.volume_get_by_ec2_id(context, ec2_id)


def volume_get_instance(context, volume_id):
    """Get the instance that a volume is attached to."""
    return IMPL.volume_get_instance(context, volume_id)


def volume_get_shelf_and_blade(context, volume_id):
    """Get the shelf and blade allocated to the volume."""
    return IMPL.volume_get_shelf_and_blade(context, volume_id)


def volume_get_iscsi_target_num(context, volume_id):
    """Get the target num (tid) allocated to the volume."""
    return IMPL.volume_get_iscsi_target_num(context, volume_id)


def volume_update(context, volume_id, values):
    """Set the given properties on an volume and update it.

    Raises NotFound if volume does not exist.

    """
    return IMPL.volume_update(context, volume_id, values)


####################


def snapshot_create(context, values):
    """Create a snapshot from the values dictionary."""
    return IMPL.snapshot_create(context, values)


def snapshot_destroy(context, snapshot_id):
    """Destroy the snapshot or raise if it does not exist."""
    return IMPL.snapshot_destroy(context, snapshot_id)


def snapshot_get(context, snapshot_id):
    """Get a snapshot or raise if it does not exist."""
    return IMPL.snapshot_get(context, snapshot_id)


def snapshot_get_all(context):
    """Get all snapshots."""
    return IMPL.snapshot_get_all(context)


def snapshot_get_all_by_project(context, project_id):
    """Get all snapshots belonging to a project."""
    return IMPL.snapshot_get_all_by_project(context, project_id)


def snapshot_update(context, snapshot_id, values):
    """Set the given properties on an snapshot and update it.

    Raises NotFound if snapshot does not exist.

    """
    return IMPL.snapshot_update(context, snapshot_id, values)


####################


def block_device_mapping_create(context, values):
    """Create an entry of block device mapping"""
    return IMPL.block_device_mapping_create(context, values)


def block_device_mapping_update(context, bdm_id, values):
    """Update an entry of block device mapping"""
    return IMPL.block_device_mapping_update(context, bdm_id, values)


def block_device_mapping_update_or_create(context, values):
    """Update an entry of block device mapping.
    If not existed, create a new entry"""
    return IMPL.block_device_mapping_update_or_create(context, values)


def block_device_mapping_get_all_by_instance(context, instance_id):
    """Get all block device mapping belonging to a instance"""
    return IMPL.block_device_mapping_get_all_by_instance(context, instance_id)


def block_device_mapping_destroy(context, bdm_id):
    """Destroy the block device mapping."""
    return IMPL.block_device_mapping_destroy(context, bdm_id)


def block_device_mapping_destroy_by_instance_and_volume(context, instance_id,
                                                        volume_id):
    """Destroy the block device mapping or raise if it does not exist."""
    return IMPL.block_device_mapping_destroy_by_instance_and_volume(
        context, instance_id, volume_id)


####################


def security_group_get_all(context):
    """Get all security groups."""
    return IMPL.security_group_get_all(context)


def security_group_get(context, security_group_id):
    """Get security group by its id."""
    return IMPL.security_group_get(context, security_group_id)


def security_group_get_by_name(context, project_id, group_name):
    """Returns a security group with the specified name from a project."""
    return IMPL.security_group_get_by_name(context, project_id, group_name)


def security_group_get_by_project(context, project_id):
    """Get all security groups belonging to a project."""
    return IMPL.security_group_get_by_project(context, project_id)


def security_group_get_by_instance(context, instance_id):
    """Get security groups to which the instance is assigned."""
    return IMPL.security_group_get_by_instance(context, instance_id)


def security_group_exists(context, project_id, group_name):
    """Indicates if a group name exists in a project."""
    return IMPL.security_group_exists(context, project_id, group_name)


def security_group_create(context, values):
    """Create a new security group."""
    return IMPL.security_group_create(context, values)


def security_group_destroy(context, security_group_id):
    """Deletes a security group."""
    return IMPL.security_group_destroy(context, security_group_id)


def security_group_destroy_all(context):
    """Deletes a security group."""
    return IMPL.security_group_destroy_all(context)


####################


def security_group_rule_create(context, values):
    """Create a new security group."""
    return IMPL.security_group_rule_create(context, values)


def security_group_rule_get_by_security_group(context, security_group_id):
    """Get all rules for a a given security group."""
    return IMPL.security_group_rule_get_by_security_group(context,
                                                          security_group_id)


def security_group_rule_get_by_security_group_grantee(context,
                                                      security_group_id):
    """Get all rules that grant access to the given security group."""
    return IMPL.security_group_rule_get_by_security_group_grantee(context,
                                                             security_group_id)


def security_group_rule_destroy(context, security_group_rule_id):
    """Deletes a security group rule."""
    return IMPL.security_group_rule_destroy(context, security_group_rule_id)


def security_group_rule_get(context, security_group_rule_id):
    """Gets a security group rule."""
    return IMPL.security_group_rule_get(context, security_group_rule_id)


###################


def provider_fw_rule_create(context, rule):
    """Add a firewall rule at the provider level (all hosts & instances)."""
    return IMPL.provider_fw_rule_create(context, rule)


def provider_fw_rule_get_all(context):
    """Get all provider-level firewall rules."""
    return IMPL.provider_fw_rule_get_all(context)


def provider_fw_rule_get_all_by_cidr(context, cidr):
    """Get all provider-level firewall rules."""
    return IMPL.provider_fw_rule_get_all_by_cidr(context, cidr)


def provider_fw_rule_destroy(context, rule_id):
    """Delete a provider firewall rule from the database."""
    return IMPL.provider_fw_rule_destroy(context, rule_id)


###################


def user_get(context, id):
    """Get user by id."""
    return IMPL.user_get(context, id)


def user_get_by_uid(context, uid):
    """Get user by uid."""
    return IMPL.user_get_by_uid(context, uid)


def user_get_by_access_key(context, access_key):
    """Get user by access key."""
    return IMPL.user_get_by_access_key(context, access_key)


def user_create(context, values):
    """Create a new user."""
    return IMPL.user_create(context, values)


def user_delete(context, id):
    """Delete a user."""
    return IMPL.user_delete(context, id)


def user_get_all(context):
    """Create a new user."""
    return IMPL.user_get_all(context)


def user_add_role(context, user_id, role):
    """Add another global role for user."""
    return IMPL.user_add_role(context, user_id, role)


def user_remove_role(context, user_id, role):
    """Remove global role from user."""
    return IMPL.user_remove_role(context, user_id, role)


def user_get_roles(context, user_id):
    """Get global roles for user."""
    return IMPL.user_get_roles(context, user_id)


def user_add_project_role(context, user_id, project_id, role):
    """Add project role for user."""
    return IMPL.user_add_project_role(context, user_id, project_id, role)


def user_remove_project_role(context, user_id, project_id, role):
    """Remove project role from user."""
    return IMPL.user_remove_project_role(context, user_id, project_id, role)


def user_get_roles_for_project(context, user_id, project_id):
    """Return list of roles a user holds on project."""
    return IMPL.user_get_roles_for_project(context, user_id, project_id)


def user_update(context, user_id, values):
    """Update user."""
    return IMPL.user_update(context, user_id, values)


###################


def project_get(context, id):
    """Get project by id."""
    return IMPL.project_get(context, id)


def project_create(context, values):
    """Create a new project."""
    return IMPL.project_create(context, values)


def project_add_member(context, project_id, user_id):
    """Add user to project."""
    return IMPL.project_add_member(context, project_id, user_id)


def project_get_all(context):
    """Get all projects."""
    return IMPL.project_get_all(context)


def project_get_by_user(context, user_id):
    """Get all projects of which the given user is a member."""
    return IMPL.project_get_by_user(context, user_id)


def project_remove_member(context, project_id, user_id):
    """Remove the given user from the given project."""
    return IMPL.project_remove_member(context, project_id, user_id)


def project_update(context, project_id, values):
    """Update Remove the given user from the given project."""
    return IMPL.project_update(context, project_id, values)


def project_delete(context, project_id):
    """Delete project."""
    return IMPL.project_delete(context, project_id)


def project_get_networks(context, project_id, associate=True):
    """Return the network associated with the project.

    If associate is true, it will attempt to associate a new
    network if one is not found, otherwise it returns None.

    """
    return IMPL.project_get_networks(context, project_id, associate)


def project_get_networks_v6(context, project_id):
    return IMPL.project_get_networks_v6(context, project_id)


###################


def console_pool_create(context, values):
    """Create console pool."""
    return IMPL.console_pool_create(context, values)


def console_pool_get(context, pool_id):
    """Get a console pool."""
    return IMPL.console_pool_get(context, pool_id)


def console_pool_get_by_host_type(context, compute_host, proxy_host,
                                  console_type):
    """Fetch a console pool for a given proxy host, compute host, and type."""
    return IMPL.console_pool_get_by_host_type(context,
                                              compute_host,
                                              proxy_host,
                                              console_type)


def console_pool_get_all_by_host_type(context, host, console_type):
    """Fetch all pools for given proxy host and type."""
    return IMPL.console_pool_get_all_by_host_type(context,
                                                  host,
                                                  console_type)


def console_create(context, values):
    """Create a console."""
    return IMPL.console_create(context, values)


def console_delete(context, console_id):
    """Delete a console."""
    return IMPL.console_delete(context, console_id)


def console_get_by_pool_instance(context, pool_id, instance_id):
    """Get console entry for a given instance and pool."""
    return IMPL.console_get_by_pool_instance(context, pool_id, instance_id)


def console_get_all_by_instance(context, instance_id):
    """Get consoles for a given instance."""
    return IMPL.console_get_all_by_instance(context, instance_id)


def console_get(context, console_id, instance_id=None):
    """Get a specific console (possibly on a given instance)."""
    return IMPL.console_get(context, console_id, instance_id)


    ##################


def instance_type_create(context, values):
    """Create a new instance type."""
    return IMPL.instance_type_create(context, values)


def instance_type_get_all(context, inactive=False):
    """Get all instance types."""
    return IMPL.instance_type_get_all(context, inactive)


def instance_type_get(context, id):
    """Get instance type by id."""
    return IMPL.instance_type_get(context, id)


def instance_type_get_by_name(context, name):
    """Get instance type by name."""
    return IMPL.instance_type_get_by_name(context, name)


def instance_type_get_by_flavor_id(context, id):
    """Get instance type by name."""
    return IMPL.instance_type_get_by_flavor_id(context, id)


def instance_type_destroy(context, name):
    """Delete a instance type."""
    return IMPL.instance_type_destroy(context, name)


def instance_type_purge(context, name):
    """Purges (removes) an instance type from DB.

    Use instance_type_destroy for most cases

    """
    return IMPL.instance_type_purge(context, name)


####################


def zone_create(context, values):
    """Create a new child Zone entry."""
    return IMPL.zone_create(context, values)


def zone_update(context, zone_id, values):
    """Update a child Zone entry."""
    return IMPL.zone_update(context, zone_id, values)


def zone_delete(context, zone_id):
    """Delete a child Zone."""
    return IMPL.zone_delete(context, zone_id)


def zone_get(context, zone_id):
    """Get a specific child Zone."""
    return IMPL.zone_get(context, zone_id)


def zone_get_all(context):
    """Get all child Zones."""
    return IMPL.zone_get_all(context)


####################


def instance_metadata_get(context, instance_id):
    """Get all metadata for an instance."""
    return IMPL.instance_metadata_get(context, instance_id)


def instance_metadata_delete(context, instance_id, key):
    """Delete the given metadata item."""
    IMPL.instance_metadata_delete(context, instance_id, key)


def instance_metadata_update(context, instance_id, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    IMPL.instance_metadata_update(context, instance_id, metadata, delete)


####################


def agent_build_create(context, values):
    """Create a new agent build entry."""
    return IMPL.agent_build_create(context, values)


def agent_build_get_by_triple(context, hypervisor, os, architecture):
    """Get agent build by hypervisor/OS/architecture triple."""
    return IMPL.agent_build_get_by_triple(context, hypervisor, os,
            architecture)


def agent_build_get_all(context):
    """Get all agent builds."""
    return IMPL.agent_build_get_all(context)


def agent_build_destroy(context, agent_update_id):
    """Destroy agent build entry."""
    IMPL.agent_build_destroy(context, agent_update_id)


def agent_build_update(context, agent_build_id, values):
    """Update agent build entry."""
    IMPL.agent_build_update(context, agent_build_id, values)


####################


def instance_type_extra_specs_get(context, instance_type_id):
    """Get all extra specs for an instance type."""
    return IMPL.instance_type_extra_specs_get(context, instance_type_id)


def instance_type_extra_specs_delete(context, instance_type_id, key):
    """Delete the given extra specs item."""
    IMPL.instance_type_extra_specs_delete(context, instance_type_id, key)


def instance_type_extra_specs_update_or_create(context, instance_type_id,
                                               extra_specs):
    """Create or update instance type extra specs. This adds or modifies the
    key/value pairs specified in the extra specs dict argument"""
    IMPL.instance_type_extra_specs_update_or_create(context, instance_type_id,
                                                    extra_specs)


##################


def volume_metadata_get(context, volume_id):
    """Get all metadata for a volume."""
    return IMPL.volume_metadata_get(context, volume_id)


def volume_metadata_delete(context, volume_id, key):
    """Delete the given metadata item."""
    IMPL.volume_metadata_delete(context, volume_id, key)


def volume_metadata_update(context, volume_id, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    IMPL.volume_metadata_update(context, volume_id, metadata, delete)


##################


def volume_type_create(context, values):
    """Create a new volume type."""
    return IMPL.volume_type_create(context, values)


def volume_type_get_all(context, inactive=False):
    """Get all volume types."""
    return IMPL.volume_type_get_all(context, inactive)


def volume_type_get(context, id):
    """Get volume type by id."""
    return IMPL.volume_type_get(context, id)


def volume_type_get_by_name(context, name):
    """Get volume type by name."""
    return IMPL.volume_type_get_by_name(context, name)


def volume_type_destroy(context, name):
    """Delete a volume type."""
    return IMPL.volume_type_destroy(context, name)


def volume_type_purge(context, name):
    """Purges (removes) a volume type from DB.

    Use volume_type_destroy for most cases

    """
    return IMPL.volume_type_purge(context, name)


####################


def volume_type_extra_specs_get(context, volume_type_id):
    """Get all extra specs for a volume type."""
    return IMPL.volume_type_extra_specs_get(context, volume_type_id)


def volume_type_extra_specs_delete(context, volume_type_id, key):
    """Delete the given extra specs item."""
    IMPL.volume_type_extra_specs_delete(context, volume_type_id, key)


def volume_type_extra_specs_update_or_create(context, volume_type_id,
                                               extra_specs):
    """Create or update volume type extra specs. This adds or modifies the
    key/value pairs specified in the extra specs dict argument"""
    IMPL.volume_type_extra_specs_update_or_create(context, volume_type_id,
                                                    extra_specs)


####################


def vsa_create(context, values):
    """Creates Virtual Storage Array record."""
    return IMPL.vsa_create(context, values)


def vsa_update(context, vsa_id, values):
    """Updates Virtual Storage Array record."""
    return IMPL.vsa_update(context, vsa_id, values)


def vsa_destroy(context, vsa_id):
    """Deletes Virtual Storage Array record."""
    return IMPL.vsa_destroy(context, vsa_id)


def vsa_get(context, vsa_id):
    """Get Virtual Storage Array record by ID."""
    return IMPL.vsa_get(context, vsa_id)


def vsa_get_all(context):
    """Get all Virtual Storage Array records."""
    return IMPL.vsa_get_all(context)


def vsa_get_all_by_project(context, project_id):
    """Get all Virtual Storage Array records by project ID."""
    return IMPL.vsa_get_all_by_project(context, project_id)

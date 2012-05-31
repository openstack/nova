# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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

Functions in this module are imported into the nova.db namespace. Call these
functions from nova.db namespace, not the nova.db.api namespace.

All functions in this module return objects that implement a dictionary-like
interface. Currently, many of these objects are sqlalchemy objects that
implement a dictionary interface. However, a future goal is to have all of
these objects be simple dictionaries.


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
from nova.openstack.common import cfg
from nova import utils


db_opts = [
    cfg.StrOpt('db_backend',
               default='sqlalchemy',
               help='The backend to use for db'),
    cfg.BoolOpt('enable_new_services',
                default=True,
                help='Services to be added to the available pool on create'),
    cfg.StrOpt('instance_name_template',
               default='instance-%08x',
               help='Template string to be used to generate instance names'),
    cfg.StrOpt('volume_name_template',
               default='volume-%s',
               help='Template string to be used to generate instance names'),
    cfg.StrOpt('snapshot_name_template',
               default='snapshot-%s',
               help='Template string to be used to generate snapshot names'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(db_opts)

IMPL = utils.LazyPluggable('db_backend',
                           sqlalchemy='nova.db.sqlalchemy.api')


class NoMoreNetworks(exception.NovaException):
    """No more available networks."""
    pass


class NoMoreTargets(exception.NovaException):
    """No more available targets"""
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


def service_get_all_volume_sorted(context):
    """Get all volume services sorted by volume count.

    :returns: a list of (Service, volume_count) tuples.

    """
    return IMPL.service_get_all_volume_sorted(context)


def service_get_by_args(context, host, binary):
    """Get the state of a service by node name and binary."""
    return IMPL.service_get_by_args(context, host, binary)


def service_create(context, values):
    """Create a service from the values dictionary."""
    return IMPL.service_create(context, values)


def service_update(context, service_id, values):
    """Set the given properties on a service and update it.

    Raises NotFound if service does not exist.

    """
    return IMPL.service_update(context, service_id, values)


###################


def compute_node_get(context, compute_id):
    """Get a computeNode or raise if it does not exist."""
    return IMPL.compute_node_get(context, compute_id)


def compute_node_get_all(context):
    """Get all computeNodes."""
    return IMPL.compute_node_get_all(context)


def compute_node_create(context, values):
    """Create a computeNode from the values dictionary."""
    return IMPL.compute_node_create(context, values)


def compute_node_update(context, compute_id, values, auto_adjust=True):
    """Set the given properties on a computeNode and update it.

    Raises NotFound if computeNode does not exist.
    """
    return IMPL.compute_node_update(context, compute_id, values, auto_adjust)


def compute_node_get_by_host(context, host):
    return IMPL.compute_node_get_by_host(context, host)


def compute_node_utilization_update(context, host, free_ram_mb_delta=0,
                          free_disk_gb_delta=0, work_delta=0, vm_delta=0):
    return IMPL.compute_node_utilization_update(context, host,
                          free_ram_mb_delta, free_disk_gb_delta, work_delta,
                          vm_delta)


def compute_node_utilization_set(context, host, free_ram_mb=None,
                                 free_disk_gb=None, work=None, vms=None):
    return IMPL.compute_node_utilization_set(context, host, free_ram_mb,
                                             free_disk_gb, work, vms)

###################


def certificate_create(context, values):
    """Create a certificate from the values dictionary."""
    return IMPL.certificate_create(context, values)


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


###################

def floating_ip_get(context, id):
    return IMPL.floating_ip_get(context, id)


def floating_ip_get_pools(context):
    """Returns a list of floating ip pools"""
    return IMPL.floating_ip_get_pools(context)


def floating_ip_allocate_address(context, project_id, pool):
    """Allocate free floating ip from specified pool and return the address.

    Raises if one is not available.

    """
    return IMPL.floating_ip_allocate_address(context, project_id, pool)


def floating_ip_create(context, values):
    """Create a floating ip from the values dictionary."""
    return IMPL.floating_ip_create(context, values)


def floating_ip_count_by_project(context, project_id, session=None):
    """Count floating ips used by project."""
    return IMPL.floating_ip_count_by_project(context, project_id,
                                             session=session)


def floating_ip_deallocate(context, address):
    """Deallocate a floating ip by address."""
    return IMPL.floating_ip_deallocate(context, address)


def floating_ip_destroy(context, address):
    """Destroy the floating_ip or raise if it does not exist."""
    return IMPL.floating_ip_destroy(context, address)


def floating_ip_disassociate(context, address):
    """Disassociate a floating ip from a fixed ip by address.

    :returns: the address of the existing fixed ip.

    """
    return IMPL.floating_ip_disassociate(context, address)


def floating_ip_fixed_ip_associate(context, floating_address,
                                   fixed_address, host):
    """Associate a floating ip to a fixed_ip by address."""
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


def floating_ip_get_by_fixed_address(context, fixed_address):
    """Get a floating ips by fixed address"""
    return IMPL.floating_ip_get_by_fixed_address(context, fixed_address)


def floating_ip_get_by_fixed_ip_id(context, fixed_ip_id):
    """Get a floating ips by fixed address"""
    return IMPL.floating_ip_get_by_fixed_ip_id(context, fixed_ip_id)


def floating_ip_update(context, address, values):
    """Update a floating ip by address or raise if it doesn't exist."""
    return IMPL.floating_ip_update(context, address, values)


def floating_ip_set_auto_assigned(context, address):
    """Set auto_assigned flag to floating ip"""
    return IMPL.floating_ip_set_auto_assigned(context, address)


def dnsdomain_list(context):
    """Get a list of all zones in our database, public and private."""
    return IMPL.dnsdomain_list(context)


def dnsdomain_register_for_zone(context, fqdomain, zone):
    """Associated a DNS domain with an availability zone"""
    return IMPL.dnsdomain_register_for_zone(context, fqdomain, zone)


def dnsdomain_register_for_project(context, fqdomain, project):
    """Associated a DNS domain with a project id"""
    return IMPL.dnsdomain_register_for_project(context, fqdomain, project)


def dnsdomain_unregister(context, fqdomain):
    """Purge associations for the specified DNS zone"""
    return IMPL.dnsdomain_unregister(context, fqdomain)


def dnsdomain_get(context, fqdomain):
    """Get the db record for the specified domain."""
    return IMPL.dnsdomain_get(context, fqdomain)


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


def migration_get_all_unconfirmed(context, confirm_window):
    """Finds all unconfirmed migrations within the confirmation window."""
    return IMPL.migration_get_all_unconfirmed(context, confirm_window)


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


def fixed_ip_bulk_create(context, ips):
    """Create a lot of fixed ips from the values dictionary."""
    return IMPL.fixed_ip_bulk_create(context, ips)


def fixed_ip_disassociate(context, address):
    """Disassociate a fixed ip from an instance by address."""
    return IMPL.fixed_ip_disassociate(context, address)


def fixed_ip_disassociate_all_by_timeout(context, host, time):
    """Disassociate old fixed ips from host."""
    return IMPL.fixed_ip_disassociate_all_by_timeout(context, host, time)


def fixed_ip_get(context, id):
    """Get fixed ip by id or raise if it does not exist."""
    return IMPL.fixed_ip_get(context, id)


def fixed_ip_get_all(context):
    """Get all defined fixed ips."""
    return IMPL.fixed_ip_get_all(context)


def fixed_ip_get_by_address(context, address):
    """Get a fixed ip by address or raise if it does not exist."""
    return IMPL.fixed_ip_get_by_address(context, address)


def fixed_ip_get_by_instance(context, instance_id):
    """Get fixed ips by instance or raise if none exist."""
    return IMPL.fixed_ip_get_by_instance(context, instance_id)


def fixed_ip_get_by_network_host(context, network_id, host):
    """Get fixed ip for a host in a network."""
    return IMPL.fixed_ip_get_by_network_host(context, network_id, host)


def fixed_ips_by_virtual_interface(context, vif_id):
    """Get fixed ips by virtual interface or raise if none exist."""
    return IMPL.fixed_ips_by_virtual_interface(context, vif_id)


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


def virtual_interface_get(context, vif_id):
    """Gets a virtual interface from the table,"""
    return IMPL.virtual_interface_get(context, vif_id)


def virtual_interface_get_by_address(context, address):
    """Gets a virtual interface from the table filtering on address."""
    return IMPL.virtual_interface_get_by_address(context, address)


def virtual_interface_get_by_uuid(context, vif_uuid):
    """Gets a virtual interface from the table filtering on vif uuid."""
    return IMPL.virtual_interface_get_by_uuid(context, vif_uuid)


def virtual_interface_get_by_instance(context, instance_id):
    """Gets all virtual_interfaces for instance."""
    return IMPL.virtual_interface_get_by_instance(context, instance_id)


def virtual_interface_get_by_instance_and_network(context, instance_id,
                                                           network_id):
    """Gets all virtual interfaces for instance."""
    return IMPL.virtual_interface_get_by_instance_and_network(context,
                                                              instance_id,
                                                              network_id)


def virtual_interface_delete(context, vif_id):
    """Delete virtual interface record from the database."""
    return IMPL.virtual_interface_delete(context, vif_id)


def virtual_interface_delete_by_instance(context, instance_id):
    """Delete virtual interface records associated with instance."""
    return IMPL.virtual_interface_delete_by_instance(context, instance_id)


def virtual_interface_get_all(context):
    """Gets all virtual interfaces from the table"""
    return IMPL.virtual_interface_get_all(context)


####################


def instance_create(context, values):
    """Create an instance from the values dictionary."""
    return IMPL.instance_create(context, values)


def instance_data_get_for_project(context, project_id, session=None):
    """Get (instance_count, total_cores, total_ram) for project."""
    return IMPL.instance_data_get_for_project(context, project_id,
                                              session=session)


def instance_destroy(context, instance_id):
    """Destroy the instance or raise if it does not exist."""
    return IMPL.instance_destroy(context, instance_id)


def instance_get_by_uuid(context, uuid):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get_by_uuid(context, uuid)


def instance_get(context, instance_id):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get(context, instance_id)


def instance_get_all(context):
    """Get all instances."""
    return IMPL.instance_get_all(context)


def instance_get_all_by_filters(context, filters, sort_key='created_at',
                                sort_dir='desc'):
    """Get all instances that match all filters."""
    return IMPL.instance_get_all_by_filters(context, filters, sort_key,
                                            sort_dir)


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


def instance_get_all_by_project(context, project_id):
    """Get all instances belonging to a project."""
    return IMPL.instance_get_all_by_project(context, project_id)


def instance_get_all_by_host(context, host):
    """Get all instances belonging to a host."""
    return IMPL.instance_get_all_by_host(context, host)


def instance_get_all_by_host_and_not_type(context, host, type_id=None):
    """Get all instances belonging to a host with a different type_id."""
    return IMPL.instance_get_all_by_host_and_not_type(context, host, type_id)


def instance_get_all_by_reservation(context, reservation_id):
    """Get all instances belonging to a reservation."""
    return IMPL.instance_get_all_by_reservation(context, reservation_id)


def instance_get_floating_address(context, instance_id):
    """Get the first floating ip address of an instance."""
    return IMPL.instance_get_floating_address(context, instance_id)


def instance_get_all_hung_in_rebooting(context, reboot_window):
    """Get all instances stuck in a rebooting state."""
    return IMPL.instance_get_all_hung_in_rebooting(context, reboot_window)


def instance_test_and_set(context, instance_id, attr, ok_states,
                          new_state):
    """Atomically check if an instance is in a valid state, and if it is, set
    the instance into a new state.
    """
    return IMPL.instance_test_and_set(
            context, instance_id, attr, ok_states, new_state)


def instance_update(context, instance_id, values):
    """Set the given properties on an instance and update it.

    Raises NotFound if instance does not exist.

    """
    return IMPL.instance_update(context, instance_id, values)


def instance_update_and_get_original(context, instance_id, values):
    """Set the given properties on an instance and update it. Return
    a shallow copy of the original instance reference, as well as the
    updated one.

    :param context: = request context object
    :param instance_id: = instance id or uuid
    :param values: = dict containing column values

    :returns: a tuple of the form (old_instance_ref, new_instance_ref)

    Raises NotFound if instance does not exist.
    """
    return IMPL.instance_update_and_get_original(context, instance_id, values)


def instance_add_security_group(context, instance_id, security_group_id):
    """Associate the given security group with the given instance."""
    return IMPL.instance_add_security_group(context, instance_id,
                                            security_group_id)


def instance_remove_security_group(context, instance_id, security_group_id):
    """Disassociate the given security group from the given instance."""
    return IMPL.instance_remove_security_group(context, instance_id,
                                            security_group_id)


def instance_get_id_to_uuid_mapping(context, ids):
    """Return a dictionary containing 'ID: UUID' given the ids"""
    return IMPL.instance_get_id_to_uuid_mapping(context, ids)


###################


def instance_info_cache_create(context, values):
    """Create a new instance cache record in the table.

    :param context: = request context object
    :param values: = dict containing column values
    """
    return IMPL.instance_info_cache_create(context, values)


def instance_info_cache_get(context, instance_uuid):
    """Gets an instance info cache from the table.

    :param instance_uuid: = uuid of the info cache's instance
    """
    return IMPL.instance_info_cache_get(context, instance_uuid)


def instance_info_cache_update(context, instance_uuid, values):
    """Update an instance info cache record in the table.

    :param instance_uuid: = uuid of info cache's instance
    :param values: = dict containing column values to update
    """
    return IMPL.instance_info_cache_update(context, instance_uuid, values)


def instance_info_cache_delete(context, instance_uuid):
    """Deletes an existing instance_info_cache record

    :param instance_uuid: = uuid of the instance tied to the cache record
    """
    return IMPL.instance_info_cache_delete(context, instance_uuid)


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


def key_pair_count_by_user(context, user_id):
    """Count number of key pairs for the given user ID."""
    return IMPL.key_pair_count_by_user(context, user_id)


####################


def network_associate(context, project_id, force=False):
    """Associate a free network to a project."""
    return IMPL.network_associate(context, project_id, force)


def network_count(context):
    """Return the number of networks."""
    return IMPL.network_count(context)


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


def network_get(context, network_id):
    """Get a network or raise if it does not exist."""
    return IMPL.network_get(context, network_id)


def network_get_all(context):
    """Return all defined networks."""
    return IMPL.network_get_all(context)


def network_get_all_by_uuids(context, network_uuids, project_id=None):
    """Return networks by ids."""
    return IMPL.network_get_all_by_uuids(context, network_uuids, project_id)


# pylint: disable=C0103


def network_get_associated_fixed_ips(context, network_id, host=None):
    """Get all network's ips that have been associated."""
    return IMPL.network_get_associated_fixed_ips(context, network_id, host)


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


def network_set_cidr(context, network_id, cidr):
    """Set the Classless Inner Domain Routing for the network."""
    return IMPL.network_set_cidr(context, network_id, cidr)


def network_set_host(context, network_id, host_id):
    """Safely set the host for network."""
    return IMPL.network_set_host(context, network_id, host_id)


def network_update(context, network_id, values):
    """Set the given properties on a network and update it.

    Raises NotFound if network does not exist.

    """
    return IMPL.network_update(context, network_id, values)


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


###################


def quota_class_create(context, class_name, resource, limit):
    """Create a quota class for the given name and resource."""
    return IMPL.quota_class_create(context, class_name, resource, limit)


def quota_class_get(context, class_name, resource):
    """Retrieve a quota class or raise if it does not exist."""
    return IMPL.quota_class_get(context, class_name, resource)


def quota_class_get_all_by_name(context, class_name):
    """Retrieve all quotas associated with a given quota class."""
    return IMPL.quota_class_get_all_by_name(context, class_name)


def quota_class_update(context, class_name, resource, limit):
    """Update a quota class or raise if it does not exist."""
    return IMPL.quota_class_update(context, class_name, resource, limit)


def quota_class_destroy(context, class_name, resource):
    """Destroy the quota class or raise if it does not exist."""
    return IMPL.quota_class_destroy(context, class_name, resource)


def quota_class_destroy_all_by_name(context, class_name):
    """Destroy all quotas associated with a given quota class."""
    return IMPL.quota_class_destroy_all_by_name(context, class_name)


###################


def quota_usage_create(context, project_id, resource, in_use, reserved,
                       until_refresh):
    """Create a quota usage for the given project and resource."""
    return IMPL.quota_usage_create(context, project_id, resource,
                                   in_use, reserved, until_refresh)


def quota_usage_get(context, project_id, resource):
    """Retrieve a quota usage or raise if it does not exist."""
    return IMPL.quota_usage_get(context, project_id, resource)


def quota_usage_get_all_by_project(context, project_id):
    """Retrieve all usage associated with a given resource."""
    return IMPL.quota_usage_get_all_by_project(context, project_id)


def quota_usage_update(context, class_name, resource, in_use, reserved,
                       until_refresh):
    """Update a quota usage or raise if it does not exist."""
    return IMPL.quota_usage_update(context, project_id, resource,
                                   in_use, reserved, until_refresh)


def quota_usage_destroy(context, project_id, resource):
    """Destroy the quota usage or raise if it does not exist."""
    return IMPL.quota_usage_destroy(context, project_id, resource)


###################


def reservation_create(context, uuid, usage, project_id, resource, delta,
                       expire):
    """Create a reservation for the given project and resource."""
    return IMPL.reservation_create(context, uuid, usage, project_id,
                                   resource, delta, expire)


def reservation_get(context, uuid):
    """Retrieve a reservation or raise if it does not exist."""
    return IMPL.reservation_get(context, uuid)


def reservation_get_all_by_project(context, project_id):
    """Retrieve all reservations associated with a given project."""
    return IMPL.reservation_get_all_by_project(context, project_id)


def reservation_destroy(context, uuid):
    """Destroy the reservation or raise if it does not exist."""
    return IMPL.reservation_destroy(context, uuid)


###################


def quota_reserve(context, resources, quotas, deltas, expire,
                  until_refresh, max_age):
    """Check quotas and create appropriate reservations."""
    return IMPL.quota_reserve(context, resources, quotas, deltas, expire,
                              until_refresh, max_age)


def reservation_commit(context, reservations):
    """Commit quota reservations."""
    return IMPL.reservation_commit(context, reservations)


def reservation_rollback(context, reservations):
    """Roll back quota reservations."""
    return IMPL.reservation_rollback(context, reservations)


def quota_destroy_all_by_project(context, project_id):
    """Destroy all quotas associated with a given project."""
    return IMPL.quota_get_all_by_project(context, project_id)


def reservation_expire(context):
    """Roll back any expired reservations."""
    return IMPL.reservation_expire(context)


###################


def volume_allocate_iscsi_target(context, volume_id, host):
    """Atomically allocate a free iscsi_target from the pool."""
    return IMPL.volume_allocate_iscsi_target(context, volume_id, host)


def volume_attached(context, volume_id, instance_id, mountpoint):
    """Ensure that a volume is set as attached."""
    return IMPL.volume_attached(context, volume_id, instance_id, mountpoint)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return IMPL.volume_create(context, values)


def volume_data_get_for_project(context, project_id, session=None):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_project(context, project_id,
                                            session=session)


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


def volume_get_all_by_instance_uuid(context, instance_uuid):
    """Get all volumes belonging to an instance."""
    return IMPL.volume_get_all_by_instance_uuid(context, instance_uuid)


def volume_get_all_by_project(context, project_id):
    """Get all volumes belonging to a project."""
    return IMPL.volume_get_all_by_project(context, project_id)


def volume_get_by_ec2_id(context, ec2_id):
    """Get a volume by ec2 id."""
    return IMPL.volume_get_by_ec2_id(context, ec2_id)


def volume_get_iscsi_target_num(context, volume_id):
    """Get the target num (tid) allocated to the volume."""
    return IMPL.volume_get_iscsi_target_num(context, volume_id)


def volume_update(context, volume_id, values):
    """Set the given properties on a volume and update it.

    Raises NotFound if volume does not exist.

    """
    return IMPL.volume_update(context, volume_id, values)


def get_ec2_volume_id_by_uuid(context, volume_id):
    return IMPL.get_ec2_volume_id_by_uuid(context, volume_id)


def get_volume_uuid_by_ec2_id(context, ec2_id):
    return IMPL.get_volume_uuid_by_ec2_id(context, ec2_id)


def ec2_volume_create(context, volume_id, forced_id=None):
    return IMPL.ec2_volume_create(context, volume_id, forced_id)


def get_snapshot_uuid_by_ec2_id(context, ec2_id):
    return IMPL.get_snapshot_uuid_by_ec2_id(context, ec2_id)


def get_ec2_snapshot_id_by_uuid(context, snapshot_id):
    return IMPL.get_ec2_snapshot_id_by_uuid(context, snapshot_id)

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


def snapshot_get_all_for_volume(context, volume_id):
    """Get all snapshots for a volume."""
    return IMPL.snapshot_get_all_for_volume(context, volume_id)


def snapshot_update(context, snapshot_id, values):
    """Set the given properties on a snapshot and update it.

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


def block_device_mapping_get_all_by_instance(context, instance_uuid):
    """Get all block device mapping belonging to an instance"""
    return IMPL.block_device_mapping_get_all_by_instance(context,
                                                         instance_uuid)


def block_device_mapping_destroy(context, bdm_id):
    """Destroy the block device mapping."""
    return IMPL.block_device_mapping_destroy(context, bdm_id)


def block_device_mapping_destroy_by_instance_and_volume(context, instance_uuid,
                                                        volume_id):
    """Destroy the block device mapping or raise if it does not exist."""
    return IMPL.block_device_mapping_destroy_by_instance_and_volume(
        context, instance_uuid, volume_id)


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


def security_group_in_use(context, group_id):
    """Indicates if a security group is currently in use."""
    return IMPL.security_group_in_use(context, group_id)


def security_group_create(context, values):
    """Create a new security group."""
    return IMPL.security_group_create(context, values)


def security_group_destroy(context, security_group_id):
    """Deletes a security group."""
    return IMPL.security_group_destroy(context, security_group_id)


def security_group_count_by_project(context, project_id, session=None):
    """Count number of security groups in a project."""
    return IMPL.security_group_count_by_project(context, project_id,
                                                session=session)


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


def security_group_rule_count_by_group(context, security_group_id):
    """Count rules in a given security group."""
    return IMPL.security_group_rule_count_by_group(context, security_group_id)


###################


def provider_fw_rule_create(context, rule):
    """Add a firewall rule at the provider level (all hosts & instances)."""
    return IMPL.provider_fw_rule_create(context, rule)


def provider_fw_rule_get_all(context):
    """Get all provider-level firewall rules."""
    return IMPL.provider_fw_rule_get_all(context)


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


def instance_type_get_all(context, inactive=False, filters=None):
    """Get all instance types."""
    return IMPL.instance_type_get_all(
        context, inactive=inactive, filters=filters)


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
    """Delete an instance type."""
    return IMPL.instance_type_destroy(context, name)


####################


def cell_create(context, values):
    """Create a new child Cell entry."""
    return IMPL.cell_create(context, values)


def cell_update(context, cell_id, values):
    """Update a child Cell entry."""
    return IMPL.cell_update(context, cell_id, values)


def cell_delete(context, cell_id):
    """Delete a child Cell."""
    return IMPL.cell_delete(context, cell_id)


def cell_get(context, cell_id):
    """Get a specific child Cell."""
    return IMPL.cell_get(context, cell_id)


def cell_get_all(context):
    """Get all child Cells."""
    return IMPL.cell_get_all(context)


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


def instance_system_metadata_get(context, instance_uuid):
    """Get all system metadata for an instance."""
    return IMPL.instance_system_metadata_get(context, instance_uuid)


def instance_system_metadata_delete(context, instance_uuid, key):
    """Delete the given system metadata item."""
    IMPL.instance_system_metadata_delete(context, instance_uuid, key)


def instance_system_metadata_update(context, instance_uuid, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    IMPL.instance_system_metadata_update(
            context, instance_uuid, metadata, delete)


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


def bw_usage_get_by_uuids(context, uuids, start_period):
    """Return bw usages for instance(s) in a given audit period."""
    return IMPL.bw_usage_get_by_uuids(context, uuids, start_period)


def bw_usage_update(context,
                    uuid,
                    mac,
                    start_period,
                    bw_in, bw_out):
    """Update cached bw usage for an instance and network
       Creates new record if needed."""
    return IMPL.bw_usage_update(context,
                                uuid,
                                mac,
                                start_period,
                                bw_in, bw_out)


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


def volume_get_active_by_window(context, begin, end=None, project_id=None):
    """Get all the volumes inside the window.

    Specifying a project_id will filter for a certain project."""
    return IMPL.volume_get_active_by_window(context, begin, end, project_id)


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


###################


def s3_image_get(context, image_id):
    """Find local s3 image represented by the provided id"""
    return IMPL.s3_image_get(context, image_id)


def s3_image_get_by_uuid(context, image_uuid):
    """Find local s3 image represented by the provided uuid"""
    return IMPL.s3_image_get_by_uuid(context, image_uuid)


def s3_image_create(context, image_uuid):
    """Create local s3 image represented by provided uuid"""
    return IMPL.s3_image_create(context, image_uuid)


####################


def sm_backend_conf_create(context, values):
    """Create a new SM Backend Config entry."""
    return IMPL.sm_backend_conf_create(context, values)


def sm_backend_conf_update(context, sm_backend_conf_id, values):
    """Update a SM Backend Config entry."""
    return IMPL.sm_backend_conf_update(context, sm_backend_conf_id, values)


def sm_backend_conf_delete(context, sm_backend_conf_id):
    """Delete a SM Backend Config."""
    return IMPL.sm_backend_conf_delete(context, sm_backend_conf_id)


def sm_backend_conf_get(context, sm_backend_conf_id):
    """Get a specific SM Backend Config."""
    return IMPL.sm_backend_conf_get(context, sm_backend_conf_id)


def sm_backend_conf_get_by_sr(context, sr_uuid):
    """Get a specific SM Backend Config."""
    return IMPL.sm_backend_conf_get_by_sr(context, sr_uuid)


def sm_backend_conf_get_all(context):
    """Get all SM Backend Configs."""
    return IMPL.sm_backend_conf_get_all(context)


####################


def sm_flavor_create(context, values):
    """Create a new SM Flavor entry."""
    return IMPL.sm_flavor_create(context, values)


def sm_flavor_update(context, sm_flavor_id, values):
    """Update a SM Flavor entry."""
    return IMPL.sm_flavor_update(context, values)


def sm_flavor_delete(context, sm_flavor_id):
    """Delete a SM Flavor."""
    return IMPL.sm_flavor_delete(context, sm_flavor_id)


def sm_flavor_get(context, sm_flavor):
    """Get a specific SM Flavor."""
    return IMPL.sm_flavor_get(context, sm_flavor)


def sm_flavor_get_all(context):
    """Get all SM Flavors."""
    return IMPL.sm_flavor_get_all(context)


####################


def sm_volume_create(context, values):
    """Create a new child Zone entry."""
    return IMPL.sm_volume_create(context, values)


def sm_volume_update(context, volume_id, values):
    """Update a child Zone entry."""
    return IMPL.sm_volume_update(context, values)


def sm_volume_delete(context, volume_id):
    """Delete a child Zone."""
    return IMPL.sm_volume_delete(context, volume_id)


def sm_volume_get(context, volume_id):
    """Get a specific child Zone."""
    return IMPL.sm_volume_get(context, volume_id)


def sm_volume_get_all(context):
    """Get all child Zones."""
    return IMPL.sm_volume_get_all(context)


####################


def aggregate_create(context, values, metadata=None):
    """Create a new aggregate with metadata."""
    return IMPL.aggregate_create(context, values, metadata)


def aggregate_get(context, aggregate_id):
    """Get a specific aggregate by id."""
    return IMPL.aggregate_get(context, aggregate_id)


def aggregate_get_by_host(context, host):
    """Get a specific aggregate by host"""
    return IMPL.aggregate_get_by_host(context, host)


def aggregate_update(context, aggregate_id, values):
    """Update the attributes of an aggregates. If values contains a metadata
    key, it updates the aggregate metadata too."""
    return IMPL.aggregate_update(context, aggregate_id, values)


def aggregate_delete(context, aggregate_id):
    """Delete an aggregate."""
    return IMPL.aggregate_delete(context, aggregate_id)


def aggregate_get_all(context):
    """Get all aggregates."""
    return IMPL.aggregate_get_all(context)


def aggregate_metadata_add(context, aggregate_id, metadata, set_delete=False):
    """Add/update metadata. If set_delete=True, it adds only."""
    IMPL.aggregate_metadata_add(context, aggregate_id, metadata, set_delete)


def aggregate_metadata_get(context, aggregate_id):
    """Get metadata for the specified aggregate."""
    return IMPL.aggregate_metadata_get(context, aggregate_id)


def aggregate_metadata_delete(context, aggregate_id, key):
    """Delete the given metadata key."""
    IMPL.aggregate_metadata_delete(context, aggregate_id, key)


def aggregate_host_add(context, aggregate_id, host):
    """Add host to the aggregate."""
    IMPL.aggregate_host_add(context, aggregate_id, host)


def aggregate_host_get_all(context, aggregate_id):
    """Get hosts for the specified aggregate."""
    return IMPL.aggregate_host_get_all(context, aggregate_id)


def aggregate_host_delete(context, aggregate_id, host):
    """Delete the given host from the aggregate."""
    IMPL.aggregate_host_delete(context, aggregate_id, host)


####################


def instance_fault_create(context, values):
    """Create a new Instance Fault."""
    return IMPL.instance_fault_create(context, values)


def instance_fault_get_by_instance_uuids(context, instance_uuids):
    """Get all instance faults for the provided instance_uuids."""
    return IMPL.instance_fault_get_by_instance_uuids(context, instance_uuids)

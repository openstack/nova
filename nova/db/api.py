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

Functions in this module are imported into the nova.db namespace. Call these
functions from nova.db namespace, not the nova.db.api namespace.

All functions in this module return objects that implement a dictionary-like
interface. Currently, many of these objects are sqlalchemy objects that
implement a dictionary interface. However, a future goal is to have all of
these objects be simple dictionaries.

"""

from oslo_db import concurrency
from oslo_log import log as logging

import nova.conf
from nova.db import constants


CONF = nova.conf.CONF
# NOTE(cdent): These constants are re-defined in this module to preserve
# existing references to them.
MAX_INT = constants.MAX_INT
SQL_SP_FLOAT_MAX = constants.SQL_SP_FLOAT_MAX

_BACKEND_MAPPING = {'sqlalchemy': 'nova.db.sqlalchemy.api'}


IMPL = concurrency.TpoolDbapiWrapper(CONF, backend_mapping=_BACKEND_MAPPING)

LOG = logging.getLogger(__name__)


###################


def constraint(**conditions):
    """Return a constraint object suitable for use with some updates."""
    return IMPL.constraint(**conditions)


def equal_any(*values):
    """Return an equality condition object suitable for use in a constraint.

    Equal_any conditions require that a model object's attribute equal any
    one of the given values.
    """
    return IMPL.equal_any(*values)


def not_equal(*values):
    """Return an inequality condition object suitable for use in a constraint.

    Not_equal conditions require that a model object's attribute differs from
    all of the given values.
    """
    return IMPL.not_equal(*values)


def create_context_manager(connection):
    """Return a context manager for a cell database connection."""
    return IMPL.create_context_manager(connection=connection)


###################


def select_db_reader_mode(f):
    """Decorator to select synchronous or asynchronous reader mode.

    The kwarg argument 'use_slave' defines reader mode. Asynchronous reader
    will be used if 'use_slave' is True and synchronous reader otherwise.
    """
    return IMPL.select_db_reader_mode(f)


###################


def service_destroy(context, service_id):
    """Destroy the service or raise if it does not exist."""
    return IMPL.service_destroy(context, service_id)


def service_get(context, service_id):
    """Get a service or raise if it does not exist."""
    return IMPL.service_get(context, service_id)


def service_get_by_uuid(context, service_uuid):
    """Get a service by it's uuid or raise ServiceNotFound if it does not
    exist.
    """
    return IMPL.service_get_by_uuid(context, service_uuid)


def service_get_minimum_version(context, binary):
    """Get the minimum service version in the database."""
    return IMPL.service_get_minimum_version(context, binary)


def service_get_by_host_and_topic(context, host, topic):
    """Get a service by hostname and topic it listens to."""
    return IMPL.service_get_by_host_and_topic(context, host, topic)


def service_get_by_host_and_binary(context, host, binary):
    """Get a service by hostname and binary."""
    return IMPL.service_get_by_host_and_binary(context, host, binary)


def service_get_all(context, disabled=None):
    """Get all services."""
    return IMPL.service_get_all(context, disabled)


def service_get_all_by_topic(context, topic):
    """Get all services for a given topic."""
    return IMPL.service_get_all_by_topic(context, topic)


def service_get_all_by_binary(context, binary, include_disabled=False):
    """Get services for a given binary.

    Includes disabled services if 'include_disabled' parameter is True
    """
    return IMPL.service_get_all_by_binary(context, binary,
                                          include_disabled=include_disabled)


def service_get_all_computes_by_hv_type(context, hv_type,
                                        include_disabled=False):
    """Get all compute services for a given hypervisor type.

    Includes disabled services if 'include_disabled' parameter is True.
    """
    return IMPL.service_get_all_computes_by_hv_type(context, hv_type,
        include_disabled=include_disabled)


def service_get_all_by_host(context, host):
    """Get all services for a given host."""
    return IMPL.service_get_all_by_host(context, host)


def service_get_by_compute_host(context, host):
    """Get the service entry for a given compute host.

    Returns the service entry joined with the compute_node entry.
    """
    return IMPL.service_get_by_compute_host(context, host)


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
    """Get a compute node by its id.

    :param context: The security context
    :param compute_id: ID of the compute node

    :returns: Dictionary-like object containing properties of the compute node

    Raises ComputeHostNotFound if compute node with the given ID doesn't exist.
    """
    return IMPL.compute_node_get(context, compute_id)


# TODO(edleafe): remove once the compute node resource provider migration is
# complete, and this distinction is no longer necessary.
def compute_node_get_model(context, compute_id):
    """Get a compute node sqlalchemy model object by its id.

    :param context: The security context
    :param compute_id: ID of the compute node

    :returns: Sqlalchemy model object containing properties of the compute node

    Raises ComputeHostNotFound if compute node with the given ID doesn't exist.
    """
    return IMPL.compute_node_get_model(context, compute_id)


def compute_nodes_get_by_service_id(context, service_id):
    """Get a list of compute nodes by their associated service id.

    :param context: The security context
    :param service_id: ID of the associated service

    :returns: List of dictionary-like objects, each containing properties of
              the compute node, including its corresponding service and
              statistics

    Raises ServiceNotFound if service with the given ID doesn't exist.
    """
    return IMPL.compute_nodes_get_by_service_id(context, service_id)


def compute_node_get_by_host_and_nodename(context, host, nodename):
    """Get a compute node by its associated host and nodename.

    :param context: The security context (admin)
    :param host: Name of the host
    :param nodename: Name of the node

    :returns: Dictionary-like object containing properties of the compute node,
              including its statistics

    Raises ComputeHostNotFound if host with the given name doesn't exist.
    """
    return IMPL.compute_node_get_by_host_and_nodename(context, host, nodename)


def compute_node_get_by_nodename(context, hypervisor_hostname):
    """Get a compute node by hypervisor_hostname.

    :param context: The security context (admin)
    :param hypervisor_hostname: Name of the node

    :returns: Dictionary-like object containing properties of the compute node,
              including its statistics

    Raises ComputeHostNotFound if hypervisor_hostname with the given name
    doesn't exist.
    """
    return IMPL.compute_node_get_by_nodename(context, hypervisor_hostname)


def compute_node_get_all(context):
    """Get all computeNodes.

    :param context: The security context

    :returns: List of dictionaries each containing compute node properties
    """
    return IMPL.compute_node_get_all(context)


def compute_node_get_all_mapped_less_than(context, mapped_less_than):
    """Get all ComputeNode objects with specific mapped values.

    :param context: The security context
    :param mapped_less_than: Get compute nodes with mapped less than this
                             value

    :returns: List of dictionaries each containing compute node properties
    """
    return IMPL.compute_node_get_all_mapped_less_than(context,
                                                      mapped_less_than)


def compute_node_get_all_by_pagination(context, limit=None, marker=None):
    """Get compute nodes by pagination.
    :param context: The security context
    :param limit: Maximum number of items to return
    :param marker: The last item of the previous page, the next results after
                   this value will be returned

    :returns: List of dictionaries each containing compute node properties
    """
    return IMPL.compute_node_get_all_by_pagination(context,
                                                   limit=limit, marker=marker)


def compute_node_get_all_by_host(context, host):
    """Get compute nodes by host name

    :param context: The security context (admin)
    :param host: Name of the host

    :returns: List of dictionaries each containing compute node properties
    """
    return IMPL.compute_node_get_all_by_host(context, host)


def compute_node_search_by_hypervisor(context, hypervisor_match):
    """Get compute nodes by hypervisor hostname.

    :param context: The security context
    :param hypervisor_match: The hypervisor hostname

    :returns: List of dictionary-like objects each containing compute node
              properties
    """
    return IMPL.compute_node_search_by_hypervisor(context, hypervisor_match)


def compute_node_create(context, values):
    """Create a compute node from the values dictionary.

    :param context: The security context
    :param values: Dictionary containing compute node properties

    :returns: Dictionary-like object containing the properties of the created
              node, including its corresponding service and statistics
    """
    return IMPL.compute_node_create(context, values)


def compute_node_update(context, compute_id, values):
    """Set the given properties on a compute node and update it.

    :param context: The security context
    :param compute_id: ID of the compute node
    :param values: Dictionary containing compute node properties to be updated

    :returns: Dictionary-like object containing the properties of the updated
              compute node, including its corresponding service and statistics

    Raises ComputeHostNotFound if compute node with the given ID doesn't exist.
    """
    return IMPL.compute_node_update(context, compute_id, values)


def compute_node_delete(context, compute_id):
    """Delete a compute node from the database.

    :param context: The security context
    :param compute_id: ID of the compute node

    Raises ComputeHostNotFound if compute node with the given ID doesn't exist.
    """
    return IMPL.compute_node_delete(context, compute_id)


def compute_node_statistics(context):
    """Get aggregate statistics over all compute nodes.

    :param context: The security context

    :returns: Dictionary containing compute node characteristics summed up
              over all the compute nodes, e.g. 'vcpus', 'free_ram_mb' etc.
    """
    return IMPL.compute_node_statistics(context)


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


def migration_get_by_uuid(context, migration_uuid):
    """Finds a migration by the migration uuid."""
    return IMPL.migration_get_by_uuid(context, migration_uuid)


def migration_get_by_id_and_instance(context, migration_id, instance_uuid):
    """Finds a migration by the migration id and the instance uuid."""
    return IMPL.migration_get_by_id_and_instance(context,
                                                 migration_id,
                                                 instance_uuid)


def migration_get_by_instance_and_status(context, instance_uuid, status):
    """Finds a migration by the instance uuid its migrating."""
    return IMPL.migration_get_by_instance_and_status(context, instance_uuid,
            status)


def migration_get_unconfirmed_by_dest_compute(context, confirm_window,
        dest_compute):
    """Finds all unconfirmed migrations within the confirmation window for
    a specific destination compute host.
    """
    return IMPL.migration_get_unconfirmed_by_dest_compute(context,
            confirm_window, dest_compute)


def migration_get_in_progress_by_host_and_node(context, host, node):
    """Finds all migrations for the given host + node  that are not yet
    confirmed or reverted.
    """
    return IMPL.migration_get_in_progress_by_host_and_node(context, host, node)


def migration_get_all_by_filters(context, filters, sort_keys=None,
                                 sort_dirs=None, limit=None, marker=None):
    """Finds all migrations using the provided filters."""
    return IMPL.migration_get_all_by_filters(context, filters,
                                             sort_keys=sort_keys,
                                             sort_dirs=sort_dirs,
                                             limit=limit, marker=marker)


def migration_get_in_progress_by_instance(context, instance_uuid,
                                          migration_type=None):
    """Finds all migrations of an instance in progress."""
    return IMPL.migration_get_in_progress_by_instance(context, instance_uuid,
                                                      migration_type)


def migration_get_by_sort_filters(context, sort_keys, sort_dirs, values):
    """Get the uuid of the first migration in a sort order.

    Return the first migration (uuid) of the set where each column value
    is greater than or equal to the matching one in @values, for each key
    in @sort_keys.
    """
    return IMPL.migration_get_by_sort_filters(context, sort_keys, sort_dirs,
                                              values)


####################


def virtual_interface_create(context, values):
    """Create a virtual interface record in the database."""
    return IMPL.virtual_interface_create(context, values)


def virtual_interface_update(context, address, values):
    """Create a virtual interface record in the database."""
    return IMPL.virtual_interface_update(context, address, values)


def virtual_interface_get(context, vif_id):
    """Gets a virtual interface from the table."""
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


def virtual_interface_delete_by_instance(context, instance_id):
    """Delete virtual interface records associated with instance."""
    return IMPL.virtual_interface_delete_by_instance(context, instance_id)


def virtual_interface_delete(context, id):
    """Delete virtual interface by id."""
    return IMPL.virtual_interface_delete(context, id)


def virtual_interface_get_all(context):
    """Gets all virtual interfaces from the table."""
    return IMPL.virtual_interface_get_all(context)


####################


def instance_create(context, values):
    """Create an instance from the values dictionary."""
    return IMPL.instance_create(context, values)


def instance_destroy(context, instance_uuid, constraint=None,
                     hard_delete=False):
    """Destroy the instance or raise if it does not exist.

    :param context: request context object
    :param instance_uuid: uuid of the instance to delete
    :param constraint: a constraint object
    :param hard_delete: when set to True, removes all records related to the
                        instance
    """
    return IMPL.instance_destroy(context, instance_uuid,
                                 constraint=constraint,
                                 hard_delete=hard_delete)


def instance_get_by_uuid(context, uuid, columns_to_join=None):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get_by_uuid(context, uuid, columns_to_join)


def instance_get(context, instance_id, columns_to_join=None):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get(context, instance_id,
                             columns_to_join=columns_to_join)


def instance_get_all(context, columns_to_join=None):
    """Get all instances."""
    return IMPL.instance_get_all(context, columns_to_join=columns_to_join)


def instance_get_all_uuids_by_hosts(context, hosts):
    """Get a dict, keyed by hostname, of a list of instance uuids on one or
    more hosts.
    """
    return IMPL.instance_get_all_uuids_by_hosts(context, hosts)


def instance_get_all_by_filters(context, filters, sort_key='created_at',
                                sort_dir='desc', limit=None, marker=None,
                                columns_to_join=None):
    """Get all instances that match all filters."""
    # Note: This function exists for backwards compatibility since calls to
    # the instance layer coming in over RPC may specify the single sort
    # key/direction values; in this case, this function is invoked instead
    # of the 'instance_get_all_by_filters_sort' function.
    return IMPL.instance_get_all_by_filters(context, filters, sort_key,
                                            sort_dir, limit=limit,
                                            marker=marker,
                                            columns_to_join=columns_to_join)


def instance_get_all_by_filters_sort(context, filters, limit=None,
                                     marker=None, columns_to_join=None,
                                     sort_keys=None, sort_dirs=None):
    """Get all instances that match all filters sorted by multiple keys.

    sort_keys and sort_dirs must be a list of strings.
    """
    return IMPL.instance_get_all_by_filters_sort(
        context, filters, limit=limit, marker=marker,
        columns_to_join=columns_to_join, sort_keys=sort_keys,
        sort_dirs=sort_dirs)


def instance_get_by_sort_filters(context, sort_keys, sort_dirs, values):
    """Get the uuid of the first instance in a sort order.

    Return the first instance (uuid) of the set where each column value
    is greater than or equal to the matching one in @values, for each key
    in @sort_keys.
    """
    return IMPL.instance_get_by_sort_filters(context, sort_keys, sort_dirs,
                                             values)


def instance_get_active_by_window_joined(context, begin, end=None,
                                         project_id=None, host=None,
                                         columns_to_join=None, limit=None,
                                         marker=None):
    """Get instances and joins active during a certain time window.

    Specifying a project_id will filter for a certain project.
    Specifying a host will filter for instances on a given compute host.
    """
    return IMPL.instance_get_active_by_window_joined(context, begin, end,
                                              project_id, host,
                                              columns_to_join=columns_to_join,
                                              limit=limit, marker=marker)


def instance_get_all_by_host(context, host, columns_to_join=None):
    """Get all instances belonging to a host."""
    return IMPL.instance_get_all_by_host(context, host, columns_to_join)


def instance_get_all_by_host_and_node(context, host, node,
                                      columns_to_join=None):
    """Get all instances belonging to a node."""
    return IMPL.instance_get_all_by_host_and_node(
        context, host, node, columns_to_join=columns_to_join)


def instance_get_all_by_host_and_not_type(context, host, type_id=None):
    """Get all instances belonging to a host with a different type_id."""
    return IMPL.instance_get_all_by_host_and_not_type(context, host, type_id)


# NOTE(hanlind): This method can be removed as conductor RPC API moves to v2.0.
def instance_get_all_hung_in_rebooting(context, reboot_window):
    """Get all instances stuck in a rebooting state."""
    return IMPL.instance_get_all_hung_in_rebooting(context, reboot_window)


def instance_update(context, instance_uuid, values, expected=None):
    """Set the given properties on an instance and update it.

    Raises NotFound if instance does not exist.

    """
    return IMPL.instance_update(context, instance_uuid, values,
                                expected=expected)


def instance_update_and_get_original(context, instance_uuid, values,
                                     columns_to_join=None, expected=None):
    """Set the given properties on an instance and update it. Return
    a shallow copy of the original instance reference, as well as the
    updated one.

    :param context: = request context object
    :param instance_uuid: = instance id or uuid
    :param values: = dict containing column values

    :returns: a tuple of the form (old_instance_ref, new_instance_ref)

    Raises NotFound if instance does not exist.
    """
    rv = IMPL.instance_update_and_get_original(context, instance_uuid, values,
                                               columns_to_join=columns_to_join,
                                               expected=expected)
    return rv


def instance_add_security_group(context, instance_id, security_group_id):
    """Associate the given security group with the given instance."""
    return IMPL.instance_add_security_group(context, instance_id,
                                            security_group_id)


def instance_remove_security_group(context, instance_id, security_group_id):
    """Disassociate the given security group from the given instance."""
    return IMPL.instance_remove_security_group(context, instance_id,
                                            security_group_id)


####################


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


def instance_extra_get_by_instance_uuid(context, instance_uuid, columns=None):
    """Get the instance extra record

    :param instance_uuid: = uuid of the instance tied to the topology record
    :param columns: A list of the columns to load, or None for 'all of them'
    """
    return IMPL.instance_extra_get_by_instance_uuid(
        context, instance_uuid, columns=columns)


def instance_extra_update_by_uuid(context, instance_uuid, updates):
    """Update the instance extra record by instance uuid

    :param instance_uuid: = uuid of the instance tied to the record
    :param updates: A dict of updates to apply
    """
    return IMPL.instance_extra_update_by_uuid(context, instance_uuid,
                                              updates)


###################


def key_pair_create(context, values):
    """Create a key_pair from the values dictionary."""
    return IMPL.key_pair_create(context, values)


def key_pair_destroy(context, user_id, name):
    """Destroy the key_pair or raise if it does not exist."""
    return IMPL.key_pair_destroy(context, user_id, name)


def key_pair_get(context, user_id, name):
    """Get a key_pair or raise if it does not exist."""
    return IMPL.key_pair_get(context, user_id, name)


def key_pair_get_all_by_user(context, user_id, limit=None, marker=None):
    """Get all key_pairs by user."""
    return IMPL.key_pair_get_all_by_user(
        context, user_id, limit=limit, marker=marker)


def key_pair_count_by_user(context, user_id):
    """Count number of key pairs for the given user ID."""
    return IMPL.key_pair_count_by_user(context, user_id)


###############


def quota_create(context, project_id, resource, limit, user_id=None):
    """Create a quota for the given project and resource."""
    return IMPL.quota_create(context, project_id, resource, limit,
                             user_id=user_id)


def quota_get(context, project_id, resource, user_id=None):
    """Retrieve a quota or raise if it does not exist."""
    return IMPL.quota_get(context, project_id, resource, user_id=user_id)


def quota_get_all_by_project_and_user(context, project_id, user_id):
    """Retrieve all quotas associated with a given project and user."""
    return IMPL.quota_get_all_by_project_and_user(context, project_id, user_id)


def quota_get_all_by_project(context, project_id):
    """Retrieve all quotas associated with a given project."""
    return IMPL.quota_get_all_by_project(context, project_id)


def quota_get_per_project_resources():
    """Retrieve the names of resources whose quotas are calculated on a
       per-project rather than a per-user basis.
    """
    return IMPL.quota_get_per_project_resources()


def quota_get_all(context, project_id):
    """Retrieve all user quotas associated with a given project."""
    return IMPL.quota_get_all(context, project_id)


def quota_update(context, project_id, resource, limit, user_id=None):
    """Update a quota or raise if it does not exist."""
    return IMPL.quota_update(context, project_id, resource, limit,
                             user_id=user_id)


###################


def quota_class_create(context, class_name, resource, limit):
    """Create a quota class for the given name and resource."""
    return IMPL.quota_class_create(context, class_name, resource, limit)


def quota_class_get(context, class_name, resource):
    """Retrieve a quota class or raise if it does not exist."""
    return IMPL.quota_class_get(context, class_name, resource)


def quota_class_get_default(context):
    """Retrieve all default quotas."""
    return IMPL.quota_class_get_default(context)


def quota_class_get_all_by_name(context, class_name):
    """Retrieve all quotas associated with a given quota class."""
    return IMPL.quota_class_get_all_by_name(context, class_name)


def quota_class_update(context, class_name, resource, limit):
    """Update a quota class or raise if it does not exist."""
    return IMPL.quota_class_update(context, class_name, resource, limit)


###################


def quota_destroy_all_by_project_and_user(context, project_id, user_id):
    """Destroy all quotas associated with a given project and user."""
    return IMPL.quota_destroy_all_by_project_and_user(context,
                                                      project_id, user_id)


def quota_destroy_all_by_project(context, project_id):
    """Destroy all quotas associated with a given project."""
    return IMPL.quota_destroy_all_by_project(context, project_id)


###################


def block_device_mapping_create(context, values, legacy=True):
    """Create an entry of block device mapping."""
    return IMPL.block_device_mapping_create(context, values, legacy)


def block_device_mapping_update(context, bdm_id, values, legacy=True):
    """Update an entry of block device mapping."""
    return IMPL.block_device_mapping_update(context, bdm_id, values, legacy)


def block_device_mapping_update_or_create(context, values, legacy=True):
    """Update an entry of block device mapping.

    If not existed, create a new entry
    """
    return IMPL.block_device_mapping_update_or_create(context, values, legacy)


def block_device_mapping_get_all_by_instance_uuids(context, instance_uuids):
    """Get all block device mapping belonging to a list of instances."""
    return IMPL.block_device_mapping_get_all_by_instance_uuids(context,
                                                               instance_uuids)


def block_device_mapping_get_all_by_instance(context, instance_uuid):
    """Get all block device mapping belonging to an instance."""
    return IMPL.block_device_mapping_get_all_by_instance(context,
                                                         instance_uuid)


def block_device_mapping_get_all_by_volume_id(context, volume_id,
        columns_to_join=None):
    """Get block device mapping for a given volume."""
    return IMPL.block_device_mapping_get_all_by_volume_id(context, volume_id,
            columns_to_join)


def block_device_mapping_get_by_instance_and_volume_id(context, volume_id,
                                                       instance_uuid,
                                                       columns_to_join=None):
    """Get block device mapping for a given volume ID and instance UUID."""
    return IMPL.block_device_mapping_get_by_instance_and_volume_id(
        context, volume_id, instance_uuid, columns_to_join)


def block_device_mapping_destroy(context, bdm_id):
    """Destroy the block device mapping."""
    return IMPL.block_device_mapping_destroy(context, bdm_id)


def block_device_mapping_destroy_by_instance_and_device(context, instance_uuid,
                                                        device_name):
    """Destroy the block device mapping."""
    return IMPL.block_device_mapping_destroy_by_instance_and_device(
        context, instance_uuid, device_name)


def block_device_mapping_destroy_by_instance_and_volume(context, instance_uuid,
                                                        volume_id):
    """Destroy the block device mapping."""
    return IMPL.block_device_mapping_destroy_by_instance_and_volume(
        context, instance_uuid, volume_id)


####################


def security_group_get_all(context):
    """Get all security groups."""
    return IMPL.security_group_get_all(context)


def security_group_get(context, security_group_id, columns_to_join=None):
    """Get security group by its id."""
    return IMPL.security_group_get(context, security_group_id,
                                   columns_to_join)


def security_group_get_by_name(context, project_id, group_name,
                               columns_to_join=None):
    """Returns a security group with the specified name from a project."""
    return IMPL.security_group_get_by_name(context, project_id, group_name,
                                           columns_to_join=None)


def security_group_get_by_project(context, project_id):
    """Get all security groups belonging to a project."""
    return IMPL.security_group_get_by_project(context, project_id)


def security_group_get_by_instance(context, instance_uuid):
    """Get security groups to which the instance is assigned."""
    return IMPL.security_group_get_by_instance(context, instance_uuid)


def security_group_in_use(context, group_id):
    """Indicates if a security group is currently in use."""
    return IMPL.security_group_in_use(context, group_id)


def security_group_create(context, values):
    """Create a new security group."""
    return IMPL.security_group_create(context, values)


def security_group_update(context, security_group_id, values,
                          columns_to_join=None):
    """Update a security group."""
    return IMPL.security_group_update(context, security_group_id, values,
                                      columns_to_join=columns_to_join)


def security_group_ensure_default(context):
    """Ensure default security group exists for a project_id.

    Returns a tuple with the first element being a bool indicating
    if the default security group previously existed. Second
    element is the dict used to create the default security group.
    """
    return IMPL.security_group_ensure_default(context)


def security_group_destroy(context, security_group_id):
    """Deletes a security group."""
    return IMPL.security_group_destroy(context, security_group_id)


####################


def security_group_rule_create(context, values):
    """Create a new security group."""
    return IMPL.security_group_rule_create(context, values)


def security_group_rule_get_by_security_group(context, security_group_id,
                                              columns_to_join=None):
    """Get all rules for a given security group."""
    return IMPL.security_group_rule_get_by_security_group(
        context, security_group_id, columns_to_join=columns_to_join)


def security_group_rule_get_by_instance(context, instance_uuid):
    """Get all rules for a given instance."""
    return IMPL.security_group_rule_get_by_instance(context, instance_uuid)


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


def pci_device_get_by_addr(context, node_id, dev_addr):
    """Get PCI device by address."""
    return IMPL.pci_device_get_by_addr(context, node_id, dev_addr)


def pci_device_get_by_id(context, id):
    """Get PCI device by id."""
    return IMPL.pci_device_get_by_id(context, id)


def pci_device_get_all_by_node(context, node_id):
    """Get all PCI devices for one host."""
    return IMPL.pci_device_get_all_by_node(context, node_id)


def pci_device_get_all_by_instance_uuid(context, instance_uuid):
    """Get PCI devices allocated to instance."""
    return IMPL.pci_device_get_all_by_instance_uuid(context, instance_uuid)


def pci_device_get_all_by_parent_addr(context, node_id, parent_addr):
    """Get all PCI devices by parent address."""
    return IMPL.pci_device_get_all_by_parent_addr(context, node_id,
                                                  parent_addr)


def pci_device_destroy(context, node_id, address):
    """Delete a PCI device record."""
    return IMPL.pci_device_destroy(context, node_id, address)


def pci_device_update(context, node_id, address, value):
    """Update a pci device."""
    return IMPL.pci_device_update(context, node_id, address, value)


####################


def instance_metadata_get(context, instance_uuid):
    """Get all metadata for an instance."""
    return IMPL.instance_metadata_get(context, instance_uuid)


def instance_metadata_delete(context, instance_uuid, key):
    """Delete the given metadata item."""
    IMPL.instance_metadata_delete(context, instance_uuid, key)


def instance_metadata_update(context, instance_uuid, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    return IMPL.instance_metadata_update(context, instance_uuid,
                                         metadata, delete)


####################


def instance_system_metadata_get(context, instance_uuid):
    """Get all system metadata for an instance."""
    return IMPL.instance_system_metadata_get(context, instance_uuid)


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


def agent_build_get_all(context, hypervisor=None):
    """Get all agent builds."""
    return IMPL.agent_build_get_all(context, hypervisor)


def agent_build_destroy(context, agent_update_id):
    """Destroy agent build entry."""
    IMPL.agent_build_destroy(context, agent_update_id)


def agent_build_update(context, agent_build_id, values):
    """Update agent build entry."""
    IMPL.agent_build_update(context, agent_build_id, values)


####################


def bw_usage_get(context, uuid, start_period, mac):
    """Return bw usage for instance and mac in a given audit period."""
    return IMPL.bw_usage_get(context, uuid, start_period, mac)


def bw_usage_get_by_uuids(context, uuids, start_period):
    """Return bw usages for instance(s) in a given audit period."""
    return IMPL.bw_usage_get_by_uuids(context, uuids, start_period)


def bw_usage_update(context, uuid, mac, start_period, bw_in, bw_out,
                    last_ctr_in, last_ctr_out, last_refreshed=None):
    """Update cached bandwidth usage for an instance's network based on mac
    address.  Creates new record if needed.
    """
    rv = IMPL.bw_usage_update(context, uuid, mac, start_period, bw_in,
            bw_out, last_ctr_in, last_ctr_out, last_refreshed=last_refreshed)
    return rv


###################


def vol_get_usage_by_time(context, begin):
    """Return volumes usage that have been updated after a specified time."""
    return IMPL.vol_get_usage_by_time(context, begin)


def vol_usage_update(context, id, rd_req, rd_bytes, wr_req, wr_bytes,
                     instance_id, project_id, user_id, availability_zone,
                     update_totals=False):
    """Update cached volume usage for a volume

       Creates new record if needed.
    """
    return IMPL.vol_usage_update(context, id, rd_req, rd_bytes, wr_req,
                                 wr_bytes, instance_id, project_id, user_id,
                                 availability_zone,
                                 update_totals=update_totals)


###################


def s3_image_get(context, image_id):
    """Find local s3 image represented by the provided id."""
    return IMPL.s3_image_get(context, image_id)


def s3_image_get_by_uuid(context, image_uuid):
    """Find local s3 image represented by the provided uuid."""
    return IMPL.s3_image_get_by_uuid(context, image_uuid)


def s3_image_create(context, image_uuid):
    """Create local s3 image represented by provided uuid."""
    return IMPL.s3_image_create(context, image_uuid)


####################


def instance_fault_create(context, values):
    """Create a new Instance Fault."""
    return IMPL.instance_fault_create(context, values)


def instance_fault_get_by_instance_uuids(context, instance_uuids,
                                         latest=False):
    """Get all instance faults for the provided instance_uuids."""
    return IMPL.instance_fault_get_by_instance_uuids(context, instance_uuids,
                                                     latest=latest)


####################


def action_start(context, values):
    """Start an action for an instance."""
    return IMPL.action_start(context, values)


def action_finish(context, values):
    """Finish an action for an instance."""
    return IMPL.action_finish(context, values)


def actions_get(context, instance_uuid, limit=None, marker=None,
                filters=None):
    """Get all instance actions for the provided instance and filters."""
    return IMPL.actions_get(context, instance_uuid, limit, marker, filters)


def action_get_by_request_id(context, uuid, request_id):
    """Get the action by request_id and given instance."""
    return IMPL.action_get_by_request_id(context, uuid, request_id)


def action_event_start(context, values):
    """Start an event on an instance action."""
    return IMPL.action_event_start(context, values)


def action_event_finish(context, values):
    """Finish an event on an instance action."""
    return IMPL.action_event_finish(context, values)


def action_events_get(context, action_id):
    """Get the events by action id."""
    return IMPL.action_events_get(context, action_id)


def action_event_get_by_id(context, action_id, event_id):
    return IMPL.action_event_get_by_id(context, action_id, event_id)


####################


def get_instance_uuid_by_ec2_id(context, ec2_id):
    """Get uuid through ec2 id from instance_id_mappings table."""
    return IMPL.get_instance_uuid_by_ec2_id(context, ec2_id)


def ec2_instance_create(context, instance_uuid, id=None):
    """Create the ec2 id to instance uuid mapping on demand."""
    return IMPL.ec2_instance_create(context, instance_uuid, id)


def ec2_instance_get_by_uuid(context, instance_uuid):
    return IMPL.ec2_instance_get_by_uuid(context, instance_uuid)


def ec2_instance_get_by_id(context, instance_id):
    return IMPL.ec2_instance_get_by_id(context, instance_id)


####################


def task_log_end_task(context, task_name,
                        period_beginning,
                        period_ending,
                        host,
                        errors,
                        message=None):
    """Mark a task as complete for a given host/time period."""
    return IMPL.task_log_end_task(context, task_name,
                                  period_beginning,
                                  period_ending,
                                  host,
                                  errors,
                                  message)


def task_log_begin_task(context, task_name,
                        period_beginning,
                        period_ending,
                        host,
                        task_items=None,
                        message=None):
    """Mark a task as started for a given host/time period."""
    return IMPL.task_log_begin_task(context, task_name,
                                    period_beginning,
                                    period_ending,
                                    host,
                                    task_items,
                                    message)


def task_log_get_all(context, task_name, period_beginning,
                 period_ending, host=None, state=None):
    return IMPL.task_log_get_all(context, task_name, period_beginning,
                 period_ending, host, state)


def task_log_get(context, task_name, period_beginning,
                 period_ending, host, state=None):
    return IMPL.task_log_get(context, task_name, period_beginning,
                 period_ending, host, state)


####################


def archive_deleted_rows(context=None, max_rows=None, before=None):
    """Move up to max_rows rows from production tables to the corresponding
    shadow tables.

    :param context: nova.context.RequestContext for database access
    :param max_rows: Maximum number of rows to archive (required)
    :param before: optional datetime which when specified filters the records
        to only archive those records deleted before the given date
    :returns: 3-item tuple:

        - dict that maps table name to number of rows archived from that table,
          for example::

            {
                'instances': 5,
                'block_device_mapping': 5,
                'pci_devices': 2,
            }
        - list of UUIDs of instances that were archived
        - total number of rows that were archived
    """
    return IMPL.archive_deleted_rows(context=context, max_rows=max_rows,
                                     before=before)


def pcidevice_online_data_migration(context, max_count):
    return IMPL.pcidevice_online_data_migration(context, max_count)


####################


def instance_tag_add(context, instance_uuid, tag):
    """Add tag to the instance."""
    return IMPL.instance_tag_add(context, instance_uuid, tag)


def instance_tag_set(context, instance_uuid, tags):
    """Replace all of the instance tags with specified list of tags."""
    return IMPL.instance_tag_set(context, instance_uuid, tags)


def instance_tag_get_by_instance_uuid(context, instance_uuid):
    """Get all tags for a given instance."""
    return IMPL.instance_tag_get_by_instance_uuid(context, instance_uuid)


def instance_tag_delete(context, instance_uuid, tag):
    """Delete specified tag from the instance."""
    return IMPL.instance_tag_delete(context, instance_uuid, tag)


def instance_tag_delete_all(context, instance_uuid):
    """Delete all tags from the instance."""
    return IMPL.instance_tag_delete_all(context, instance_uuid)


def instance_tag_exists(context, instance_uuid, tag):
    """Check if specified tag exist on the instance."""
    return IMPL.instance_tag_exists(context, instance_uuid, tag)


####################


def console_auth_token_create(context, values):
    """Create a console authorization."""
    return IMPL.console_auth_token_create(context, values)


def console_auth_token_get_valid(context, token_hash, instance_uuid=None):
    """Get a valid console authorization by token_hash and instance_uuid.

    The console authorizations expire at the time specified by their
    'expires' column. An expired console auth token will not be returned
    to the caller - it is treated as if it does not exist.

    If instance_uuid is specified, the token is validated against both
    expiry and instance_uuid.

    If instance_uuid is not specified, the token is validated against
    expiry only.
    """
    return IMPL.console_auth_token_get_valid(context,
                                             token_hash,
                                             instance_uuid=instance_uuid)


def console_auth_token_destroy_all_by_instance(context, instance_uuid):
    """Delete all console authorizations belonging to the instance."""
    return IMPL.console_auth_token_destroy_all_by_instance(context,
                                                           instance_uuid)


def console_auth_token_destroy_expired(context):
    """Delete expired console authorizations.

    The console authorizations expire at the time specified by their
    'expires' column. This function is used to garbage collect expired tokens.
    """
    return IMPL.console_auth_token_destroy_expired(context)


def console_auth_token_destroy_expired_by_host(context, host):
    """Delete expired console authorizations belonging to the host.

    The console authorizations expire at the time specified by their
    'expires' column. This function is used to garbage collect expired
    tokens associated with the given host.
    """
    return IMPL.console_auth_token_destroy_expired_by_host(context, host)

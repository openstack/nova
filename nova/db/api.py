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
Defines interface for DB access.

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


IMPL = utils.LazyPluggable(FLAGS['db_backend'],
                           sqlalchemy='nova.db.sqlalchemy.api')


class NoMoreAddresses(exception.Error):
    """No more available addresses."""
    pass


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
    """Get an service or raise if it does not exist."""
    return IMPL.service_get(context, service_id)


def service_get_all(context, disabled=False):
    """Get all service."""
    return IMPL.service_get_all(context, None, disabled)


def service_get_all_by_topic(context, topic):
    """Get all services for a given topic."""
    return IMPL.service_get_all_by_topic(context, topic)


def service_get_all_by_host(context, host):
    """Get all services for a given host."""
    return IMPL.service_get_all_by_host(context, host)


def service_get_all_compute_sorted(context):
    """Get all compute services sorted by instance count.

    Returns a list of (Service, instance_count) tuples.

    """
    return IMPL.service_get_all_compute_sorted(context)


def service_get_all_network_sorted(context):
    """Get all network services sorted by network count.

    Returns a list of (Service, network_count) tuples.

    """
    return IMPL.service_get_all_network_sorted(context)


def service_get_all_volume_sorted(context):
    """Get all volume services sorted by volume count.

    Returns a list of (Service, volume_count) tuples.

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
    return IMPL.service_update(context, certificate_id, values)


###################


def floating_ip_allocate_address(context, host, project_id):
    """Allocate free floating ip and return the address.

    Raises if one is not available.

    """
    return IMPL.floating_ip_allocate_address(context, host, project_id)


def floating_ip_create(context, values):
    """Create a floating ip from the values dictionary."""
    return IMPL.floating_ip_create(context, values)


def floating_ip_count_by_project(context, project_id):
    """Count floating ips used by project."""
    return IMPL.floating_ip_count_by_project(context, project_id)


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
    """Get all floating ips by host."""
    return IMPL.floating_ip_get_all_by_host(context, host)


def floating_ip_get_all_by_project(context, project_id):
    """Get all floating ips by project."""
    return IMPL.floating_ip_get_all_by_project(context, project_id)


def floating_ip_get_by_address(context, address):
    """Get a floating ip by address or raise if it doesn't exist."""
    return IMPL.floating_ip_get_by_address(context, address)


####################


def fixed_ip_associate(context, address, instance_id):
    """Associate fixed ip to instance.

    Raises if fixed ip is not available.

    """
    return IMPL.fixed_ip_associate(context, address, instance_id)


def fixed_ip_associate_pool(context, network_id, instance_id):
    """Find free ip in network and associate it to instance.

    Raises if one is not available.

    """
    return IMPL.fixed_ip_associate_pool(context, network_id, instance_id)


def fixed_ip_create(context, values):
    """Create a fixed ip from the values dictionary."""
    return IMPL.fixed_ip_create(context, values)


def fixed_ip_disassociate(context, address):
    """Disassociate a fixed ip from an instance by address."""
    return IMPL.fixed_ip_disassociate(context, address)


def fixed_ip_disassociate_all_by_timeout(context, host, time):
    """Disassociate old fixed ips from host."""
    return IMPL.fixed_ip_disassociate_all_by_timeout(context, host, time)


def fixed_ip_get_by_address(context, address):
    """Get a fixed ip by address or raise if it does not exist."""
    return IMPL.fixed_ip_get_by_address(context, address)


def fixed_ip_get_instance(context, address):
    """Get an instance for a fixed ip by address."""
    return IMPL.fixed_ip_get_instance(context, address)


def fixed_ip_get_instance_v6(context, address):
    return IMPL.fixed_ip_get_instance_v6(context, address)


def fixed_ip_get_network(context, address):
    """Get a network for a fixed ip by address."""
    return IMPL.fixed_ip_get_network(context, address)


def fixed_ip_update(context, address, values):
    """Create a fixed ip from the values dictionary."""
    return IMPL.fixed_ip_update(context, address, values)


####################


def instance_create(context, values):
    """Create an instance from the values dictionary."""
    return IMPL.instance_create(context, values)


def instance_data_get_for_project(context, project_id):
    """Get (instance_count, core_count) for project."""
    return IMPL.instance_data_get_for_project(context, project_id)


def instance_destroy(context, instance_id):
    """Destroy the instance or raise if it does not exist."""
    return IMPL.instance_destroy(context, instance_id)


def instance_get(context, instance_id):
    """Get an instance or raise if it does not exist."""
    return IMPL.instance_get(context, instance_id)


def instance_get_all(context):
    """Get all instances."""
    return IMPL.instance_get_all(context)


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
    """Get all instance belonging to a reservation."""
    return IMPL.instance_get_all_by_reservation(context, reservation_id)


def instance_get_fixed_address(context, instance_id):
    """Get the fixed ip address of an instance."""
    return IMPL.instance_get_fixed_address(context, instance_id)


def instance_get_fixed_address_v6(context, instance_id):
    return IMPL.instance_get_fixed_address_v6(context, instance_id)


def instance_get_floating_address(context, instance_id):
    """Get the first floating ip address of an instance."""
    return IMPL.instance_get_floating_address(context, instance_id)


def instance_get_project_vpn(context, project_id):
    """Get a vpn instance by project or return None."""
    return IMPL.instance_get_project_vpn(context, project_id)


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


def instance_add_security_group(context, instance_id, security_group_id):
    """Associate the given security group with the given instance."""
    return IMPL.instance_add_security_group(context, instance_id,
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


def network_associate(context, project_id):
    """Associate a free network to a project."""
    return IMPL.network_associate(context, project_id)


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


# pylint: disable-msg=C0103
def network_get_associated_fixed_ips(context, network_id):
    """Get all network's ips that have been associated."""
    return IMPL.network_get_associated_fixed_ips(context, network_id)


def network_get_by_bridge(context, bridge):
    """Get a network by bridge or raise if it does not exist."""
    return IMPL.network_get_by_bridge(context, bridge)


def network_get_by_instance(context, instance_id):
    """Get a network by instance id or raise if it does not exist."""
    return IMPL.network_get_by_instance(context, instance_id)


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


def project_get_network(context, project_id, associate=True):
    """Return the network associated with the project.

    If associate is true, it will attempt to associate a new
    network if one is not found, otherwise it returns None.

    """

    return IMPL.project_get_network(context, project_id)


def project_get_network_v6(context, project_id):
    return IMPL.project_get_network_v6(context, project_id)


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
    no exception is raised."""
    return IMPL.iscsi_target_create_safe(context, values)


###############


def auth_destroy_token(context, token):
    """Destroy an auth token."""
    return IMPL.auth_destroy_token(context, token)


def auth_get_token(context, token_hash):
    """Retrieves a token given the hash representing it."""
    return IMPL.auth_get_token(context, token_hash)


def auth_create_token(context, token):
    """Creates a new token."""
    return IMPL.auth_create_token(context, token)


###################


def quota_create(context, values):
    """Create a quota from the values dictionary."""
    return IMPL.quota_create(context, values)


def quota_get(context, project_id):
    """Retrieve a quota or raise if it does not exist."""
    return IMPL.quota_get(context, project_id)


def quota_update(context, project_id, values):
    """Update a quota from the values dictionary."""
    return IMPL.quota_update(context, project_id, values)


def quota_destroy(context, project_id):
    """Destroy the quota or raise if it does not exist."""
    return IMPL.quota_destroy(context, project_id)


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


###################


def host_get_networks(context, host):
    """Return all networks for which the given host is the designated
    network host.

    """
    return IMPL.host_get_networks(context, host)


##################


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
    """Create a new instance type"""
    return IMPL.instance_type_create(context, values)


def instance_type_get_all(context, inactive=0):
    """Get all instance types"""
    return IMPL.instance_type_get_all(context, inactive)


def instance_type_get_by_name(context, name):
    """Get instance type by name"""
    return IMPL.instance_type_get_by_name(context, name)


def instance_type_get_by_flavor_id(context, id):
    """Get instance type by name"""
    return IMPL.instance_type_get_by_flavor_id(context, id)


def instance_type_destroy(context, name):
    """Delete a instance type"""
    return IMPL.instance_type_destroy(context, name)

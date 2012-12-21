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

import functools
import inspect

from nova.db import base
from nova import exception
from nova.network import model as network_model
from nova.network import rpcapi as network_rpcapi
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def refresh_cache(f):
    """
    Decorator to update the instance_info_cache

    Requires context and instance as function args
    """
    argspec = inspect.getargspec(f)

    @functools.wraps(f)
    def wrapper(self, context, *args, **kwargs):
        res = f(self, context, *args, **kwargs)

        try:
            # get the instance from arguments (or raise ValueError)
            instance = kwargs.get('instance')
            if not instance:
                instance = args[argspec.args.index('instance') - 2]
        except ValueError:
            msg = _('instance is a required argument to use @refresh_cache')
            raise Exception(msg)

        # get nw_info from return if possible, otherwise call for it
        nw_info = res if isinstance(res, network_model.NetworkInfo) else None

        update_instance_cache_with_nw_info(self, context, instance, nw_info,
                                           *args, **kwargs)

        # return the original function's return value
        return res
    return wrapper


def update_instance_cache_with_nw_info(api, context, instance,
                                       nw_info=None,
                                       *args,
                                       **kwargs):

    try:
        nw_info = nw_info or api._get_instance_nw_info(context, instance)

        # update cache
        cache = {'network_info': nw_info.json()}
        api.db.instance_info_cache_update(context, instance['uuid'], cache)
    except Exception as e:
        LOG.exception(_('Failed storing info cache'), instance=instance)
        LOG.debug(_('args: %s') % (args or {}))
        LOG.debug(_('kwargs: %s') % (kwargs or {}))


class API(base.Base):
    """API for interacting with the network manager."""

    _sentinel = object()

    def __init__(self, **kwargs):
        self.network_rpcapi = network_rpcapi.NetworkAPI()
        super(API, self).__init__(**kwargs)

    def get_all(self, context):
        return self.network_rpcapi.get_all_networks(context)

    def get(self, context, network_uuid):
        return self.network_rpcapi.get_network(context, network_uuid)

    def create(self, context, **kwargs):
        return self.network_rpcapi.create_networks(context, **kwargs)

    def delete(self, context, network_uuid):
        return self.network_rpcapi.delete_network(context, network_uuid, None)

    def disassociate(self, context, network_uuid):
        return self.network_rpcapi.disassociate_network(context, network_uuid)

    def get_fixed_ip(self, context, id):
        return self.network_rpcapi.get_fixed_ip(context, id)

    def get_fixed_ip_by_address(self, context, address):
        return self.network_rpcapi.get_fixed_ip_by_address(context, address)

    def get_floating_ip(self, context, id):
        return self.network_rpcapi.get_floating_ip(context, id)

    def get_floating_ip_pools(self, context):
        return self.network_rpcapi.get_floating_pools(context)

    def get_floating_ip_by_address(self, context, address):
        return self.network_rpcapi.get_floating_ip_by_address(context, address)

    def get_floating_ips_by_project(self, context):
        return self.network_rpcapi.get_floating_ips_by_project(context)

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        return self.network_rpcapi.get_floating_ips_by_fixed_address(context,
                fixed_address)

    def get_backdoor_port(self, context, host):
        return self.network_rpcapi.get_backdoor_port(context, host)

    def get_instance_id_by_floating_address(self, context, address):
        # NOTE(tr3buchet): i hate this
        return self.network_rpcapi.get_instance_id_by_floating_address(context,
                address)

    def get_vifs_by_instance(self, context, instance):
        return self.network_rpcapi.get_vifs_by_instance(context,
                instance['id'])

    def get_vif_by_mac_address(self, context, mac_address):
        return self.network_rpcapi.get_vif_by_mac_address(context, mac_address)

    def allocate_floating_ip(self, context, pool=None):
        """Adds a floating ip to a project from a pool. (allocates)"""
        # NOTE(vish): We don't know which network host should get the ip
        #             when we allocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        return self.network_rpcapi.allocate_floating_ip(context,
                context.project_id, pool, False)

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Removes floating ip with address from a project. (deallocates)"""
        return self.network_rpcapi.deallocate_floating_ip(context, address,
                affect_auto_assigned)

    @refresh_cache
    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associates a floating ip with a fixed ip.

        ensures floating ip is allocated to the project in context
        """
        orig_instance_uuid = self.network_rpcapi.associate_floating_ip(context,
                floating_address, fixed_address, affect_auto_assigned)

        if orig_instance_uuid:
            msg_dict = dict(address=floating_address,
                            instance_id=orig_instance_uuid)
            LOG.info(_('re-assign floating IP %(address)s from '
                       'instance %(instance_id)s') % msg_dict)
            orig_instance = self.db.instance_get_by_uuid(context,
                                                         orig_instance_uuid)

            # purge cached nw info for the original instance
            update_instance_cache_with_nw_info(self, context, orig_instance)

    @refresh_cache
    def disassociate_floating_ip(self, context, instance, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating ip from fixed ip it is associated with."""
        self.network_rpcapi.disassociate_floating_ip(context, address,
                affect_auto_assigned)

    @refresh_cache
    def allocate_for_instance(self, context, instance, vpn,
                              requested_networks):
        """Allocates all network structures for an instance.

        :returns: network info as from get_instance_nw_info() below
        """
        args = {}
        args['vpn'] = vpn
        args['requested_networks'] = requested_networks
        args['instance_id'] = instance['id']
        args['instance_uuid'] = instance['uuid']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        args['rxtx_factor'] = instance['instance_type']['rxtx_factor']
        nw_info = self.network_rpcapi.allocate_for_instance(context, **args)

        return network_model.NetworkInfo.hydrate(nw_info)

    def deallocate_for_instance(self, context, instance):
        """Deallocates all network structures related to instance."""

        args = {}
        args['instance_id'] = instance['id']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        self.network_rpcapi.deallocate_for_instance(context, **args)

    @refresh_cache
    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Adds a fixed ip to instance from specified network."""
        args = {'instance_id': instance['uuid'],
                'host': instance['host'],
                'network_id': network_id}
        self.network_rpcapi.add_fixed_ip_to_instance(context, **args)

    @refresh_cache
    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Removes a fixed ip from instance from specified network."""

        args = {'instance_id': instance['uuid'],
                'host': instance['host'],
                'address': address}
        self.network_rpcapi.remove_fixed_ip_from_instance(context, **args)

    def add_network_to_project(self, context, project_id, network_uuid=None):
        """Force adds another network to a project."""
        self.network_rpcapi.add_network_to_project(context, project_id,
                network_uuid)

    def associate(self, context, network_uuid, host=_sentinel,
                  project=_sentinel):
        """Associate or disassociate host or project to network"""
        associations = {}
        if host is not API._sentinel:
            associations['host'] = host
        if project is not API._sentinel:
            associations['project'] = project
        self.network_rpcapi.associate(context, network_uuid, associations)

    @refresh_cache
    def get_instance_nw_info(self, context, instance):
        """Returns all network info related to an instance."""
        return self._get_instance_nw_info(context, instance)

    def _get_instance_nw_info(self, context, instance):
        """Returns all network info related to an instance."""
        args = {'instance_id': instance['id'],
                'instance_uuid': instance['uuid'],
                'rxtx_factor': instance['instance_type']['rxtx_factor'],
                'host': instance['host'],
                'project_id': instance['project_id']}
        nw_info = self.network_rpcapi.get_instance_nw_info(context, **args)

        return network_model.NetworkInfo.hydrate(nw_info)

    def validate_networks(self, context, requested_networks):
        """validate the networks passed at the time of creating
        the server
        """
        return self.network_rpcapi.validate_networks(context,
                                                     requested_networks)

    def get_instance_uuids_by_ip_filter(self, context, filters):
        """Returns a list of dicts in the form of
        {'instance_uuid': uuid, 'ip': ip} that matched the ip_filter
        """
        return self.network_rpcapi.get_instance_uuids_by_ip_filter(context,
                                                                   filters)

    def get_dns_domains(self, context):
        """Returns a list of available dns domains.
        These can be used to create DNS entries for floating ips.
        """
        return self.network_rpcapi.get_dns_domains(context)

    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address"""
        args = {'address': address,
                'name': name,
                'dns_type': dns_type,
                'domain': domain}
        return self.network_rpcapi.add_dns_entry(context, **args)

    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address"""
        args = {'address': address,
                'name': name,
                'domain': domain}
        return self.network_rpcapi.modify_dns_entry(context, **args)

    def delete_dns_entry(self, context, name, domain):
        """Delete the specified dns entry."""
        args = {'name': name, 'domain': domain}
        return self.network_rpcapi.delete_dns_entry(context, **args)

    def delete_dns_domain(self, context, domain):
        """Delete the specified dns domain."""
        return self.network_rpcapi.delete_dns_domain(context, domain=domain)

    def get_dns_entries_by_address(self, context, address, domain):
        """Get entries for address and domain"""
        args = {'address': address, 'domain': domain}
        return self.network_rpcapi.get_dns_entries_by_address(context, **args)

    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain"""
        args = {'name': name, 'domain': domain}
        return self.network_rpcapi.get_dns_entries_by_name(context, **args)

    def create_private_dns_domain(self, context, domain, availability_zone):
        """Create a private DNS domain with nova availability zone."""
        args = {'domain': domain, 'av_zone': availability_zone}
        return self.network_rpcapi.create_private_dns_domain(context, **args)

    def create_public_dns_domain(self, context, domain, project=None):
        """Create a public DNS domain with optional nova project."""
        args = {'domain': domain, 'project': project}
        return self.network_rpcapi.create_public_dns_domain(context, **args)

    def setup_networks_on_host(self, context, instance, host=None,
                                                        teardown=False):
        """Setup or teardown the network structures on hosts related to
           instance"""
        host = host or instance['host']
        # NOTE(tr3buchet): host is passed in cases where we need to setup
        # or teardown the networks on a host which has been migrated to/from
        # and instance['host'] is not yet or is no longer equal to
        args = {'instance_id': instance['id'],
                'host': host,
                'teardown': teardown}

        self.network_rpcapi.setup_networks_on_host(context, **args)

    def _is_multi_host(self, context, instance):
        try:
            fixed_ips = self.db.fixed_ip_get_by_instance(context,
                                                         instance['uuid'])
        except exception.FixedIpNotFoundForInstance:
            return False
        network = self.db.network_get(context, fixed_ips[0]['network_id'],
                                      project_only='allow_none')
        return network['multi_host']

    def _get_floating_ip_addresses(self, context, instance):
        floating_ips = self.db.instance_floating_address_get_all(context,
                                                            instance['uuid'])
        return [floating_ip['address'] for floating_ip in floating_ips]

    def migrate_instance_start(self, context, instance, migration):
        """Start to migrate the network of an instance"""
        args = dict(
            instance_uuid=instance['uuid'],
            rxtx_factor=instance['instance_type']['rxtx_factor'],
            project_id=instance['project_id'],
            source_compute=migration['source_compute'],
            dest_compute=migration['dest_compute'],
            floating_addresses=None,
        )

        if self._is_multi_host(context, instance):
            args['floating_addresses'] = \
                self._get_floating_ip_addresses(context, instance)
            args['host'] = migration['source_compute']

        self.network_rpcapi.migrate_instance_start(context, **args)

    def migrate_instance_finish(self, context, instance, migration):
        """Finish migrating the network of an instance"""
        args = dict(
            instance_uuid=instance['uuid'],
            rxtx_factor=instance['instance_type']['rxtx_factor'],
            project_id=instance['project_id'],
            source_compute=migration['source_compute'],
            dest_compute=migration['dest_compute'],
            floating_addresses=None,
        )

        if self._is_multi_host(context, instance):
            args['floating_addresses'] = \
                self._get_floating_ip_addresses(context, instance)
            args['host'] = migration['dest_compute']

        self.network_rpcapi.migrate_instance_finish(context, **args)

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
"""
This version of the api is deprecated in Grizzly and will be removed.

It is provided just in case a third party manager is in use.
"""

from nova.compute import instance_types
from nova.db import base
from nova import exception
from nova.network import api as shiny_api
from nova.network import model as network_model
from nova.network import rpcapi as network_rpcapi
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


refresh_cache = shiny_api.refresh_cache
_update_instance_cache = shiny_api.update_instance_cache_with_nw_info
update_instance_cache_with_nw_info = _update_instance_cache
wrap_check_policy = shiny_api.wrap_check_policy


class API(base.Base):
    """API for doing networking via the nova-network network manager.

    This is a pluggable module - other implementations do networking via
    other services (such as Quantum).
    """

    _sentinel = object()

    def __init__(self, **kwargs):
        self.network_rpcapi = network_rpcapi.NetworkAPI()
        super(API, self).__init__(**kwargs)

    @wrap_check_policy
    def get_all(self, context):
        return self.network_rpcapi.get_all_networks(context)

    @wrap_check_policy
    def get(self, context, network_uuid):
        return self.network_rpcapi.get_network(context, network_uuid)

    @wrap_check_policy
    def create(self, context, **kwargs):
        return self.network_rpcapi.create_networks(context, **kwargs)

    @wrap_check_policy
    def delete(self, context, network_uuid):
        return self.network_rpcapi.delete_network(context, network_uuid, None)

    @wrap_check_policy
    def disassociate(self, context, network_uuid):
        return self.network_rpcapi.disassociate_network(context, network_uuid)

    @wrap_check_policy
    def get_fixed_ip(self, context, id):
        return self.network_rpcapi.get_fixed_ip(context, id)

    @wrap_check_policy
    def get_fixed_ip_by_address(self, context, address):
        return self.network_rpcapi.get_fixed_ip_by_address(context, address)

    @wrap_check_policy
    def get_floating_ip(self, context, id):
        return self.network_rpcapi.get_floating_ip(context, id)

    @wrap_check_policy
    def get_floating_ip_pools(self, context):
        return self.network_rpcapi.get_floating_ip_pools(context)

    @wrap_check_policy
    def get_floating_ip_by_address(self, context, address):
        return self.network_rpcapi.get_floating_ip_by_address(context, address)

    @wrap_check_policy
    def get_floating_ips_by_project(self, context):
        return self.network_rpcapi.get_floating_ips_by_project(context)

    @wrap_check_policy
    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        args = (context, fixed_address)
        return self.network_rpcapi.get_floating_ips_by_fixed_address(*args)

    @wrap_check_policy
    def get_backdoor_port(self, context, host):
        return self.network_rpcapi.get_backdoor_port(context, host)

    @wrap_check_policy
    def get_instance_id_by_floating_address(self, context, address):
        # NOTE(tr3buchet): i hate this
        return self.network_rpcapi.get_instance_id_by_floating_address(context,
                                                                       address)

    @wrap_check_policy
    def get_vifs_by_instance(self, context, instance):
        return self.network_rpcapi.get_vifs_by_instance(context,
                                                        instance['id'])

    @wrap_check_policy
    def get_vif_by_mac_address(self, context, mac_address):
        return self.network_rpcapi.get_vif_by_mac_address(context, mac_address)

    @wrap_check_policy
    def allocate_floating_ip(self, context, pool=None):
        """Adds (allocates) a floating ip to a project from a pool."""
        # NOTE(vish): We don't know which network host should get the ip
        #             when we allocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        return self.network_rpcapi.allocate_floating_ip(context,
                                                        context.project_id,
                                                        pool,
                                                        False)

    @wrap_check_policy
    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Removes (deallocates) a floating ip with address from a project."""
        args = (context, address, affect_auto_assigned)
        return self.network_rpcapi.deallocate_floating_ip(*args)

    @wrap_check_policy
    @refresh_cache
    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associates a floating ip with a fixed ip.

        ensures floating ip is allocated to the project in context
        """
        args = (context, floating_address, fixed_address, affect_auto_assigned)
        orig_instance_uuid = self.network_rpcapi.associate_floating_ip(*args)

        if orig_instance_uuid:
            msg_dict = dict(address=floating_address,
                            instance_id=orig_instance_uuid)
            LOG.info(_('re-assign floating IP %(address)s from '
                       'instance %(instance_id)s') % msg_dict)
            orig_instance = self.db.instance_get_by_uuid(context,
                                                         orig_instance_uuid)

            # purge cached nw info for the original instance
            update_instance_cache_with_nw_info(self, context, orig_instance)

    @wrap_check_policy
    @refresh_cache
    def disassociate_floating_ip(self, context, instance, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating ip from fixed ip it is associated with."""
        self.network_rpcapi.disassociate_floating_ip(context, address,
                                                     affect_auto_assigned)

    @wrap_check_policy
    @refresh_cache
    def allocate_for_instance(self, context, instance, vpn,
                              requested_networks, macs=None,
                              conductor_api=None, security_groups=None,
                              **kwargs):
        """Allocates all network structures for an instance.

        TODO(someone): document the rest of these parameters.

        :param macs: None or a set of MAC addresses that the instance
            should use. macs is supplied by the hypervisor driver (contrast
            with requested_networks which is user supplied).
            NB: macs is ignored by nova-network.
        :returns: network info as from get_instance_nw_info() below
        """
        instance_type = instance_types.extract_instance_type(instance)
        args = {}
        args['vpn'] = vpn
        args['requested_networks'] = requested_networks
        args['instance_id'] = instance['uuid']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        args['rxtx_factor'] = instance_type['rxtx_factor']
        nw_info = self.network_rpcapi.allocate_for_instance(context, **args)

        return network_model.NetworkInfo.hydrate(nw_info)

    @wrap_check_policy
    def deallocate_for_instance(self, context, instance, **kwargs):
        """Deallocates all network structures related to instance."""

        args = {}
        args['instance_id'] = instance['id']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        self.network_rpcapi.deallocate_for_instance(context, **args)

    @wrap_check_policy
    @refresh_cache
    def add_fixed_ip_to_instance(self, context, instance, network_id,
                                 conductor_api=None, **kwargs):
        """Adds a fixed ip to instance from specified network."""
        args = {'instance_id': instance['uuid'],
                'host': instance['host'],
                'network_id': network_id,
                'rxtx_factor': None}
        self.network_rpcapi.add_fixed_ip_to_instance(context, **args)

    @wrap_check_policy
    @refresh_cache
    def remove_fixed_ip_from_instance(self, context, instance, address,
                                      conductor=None, **kwargs):
        """Removes a fixed ip from instance from specified network."""

        args = {'instance_id': instance['uuid'],
                'host': instance['host'],
                'address': address,
                'rxtx_factor': None}
        self.network_rpcapi.remove_fixed_ip_from_instance(context, **args)

    @wrap_check_policy
    def add_network_to_project(self, context, project_id, network_uuid=None):
        """Force adds another network to a project."""
        self.network_rpcapi.add_network_to_project(context, project_id,
                                                   network_uuid)

    @wrap_check_policy
    def associate(self, context, network_uuid, host=_sentinel,
                  project=_sentinel):
        """Associate or disassociate host or project to network."""
        associations = {}
        if host is not API._sentinel:
            associations['host'] = host
        if project is not API._sentinel:
            associations['project'] = project
        self.network_rpcapi.associate(context, network_uuid, associations)

    @wrap_check_policy
    def get_instance_nw_info(self, context, instance, conductor_api=None,
                             **kwargs):
        """Returns all network info related to an instance."""
        result = self._get_instance_nw_info(context, instance)
        update_instance_cache_with_nw_info(self, context, instance,
                                           result, conductor_api)
        return result

    def _get_instance_nw_info(self, context, instance):
        """Returns all network info related to an instance."""
        instance_type = instance_types.extract_instance_type(instance)
        args = {'instance_id': instance['uuid'],
                'rxtx_factor': instance_type['rxtx_factor'],
                'host': instance['host'],
                'project_id': instance['project_id']}
        nw_info = self.network_rpcapi.get_instance_nw_info(context, **args)

        return network_model.NetworkInfo.hydrate(nw_info)

    @wrap_check_policy
    def validate_networks(self, context, requested_networks):
        """validate the networks passed at the time of creating
        the server
        """
        return self.network_rpcapi.validate_networks(context,
                                                     requested_networks)

    @wrap_check_policy
    def get_instance_uuids_by_ip_filter(self, context, filters):
        """Returns a list of dicts in the form of
        {'instance_uuid': uuid, 'ip': ip} that matched the ip_filter
        """
        return self.network_rpcapi.get_instance_uuids_by_ip_filter(context,
                                                                   filters)

    @wrap_check_policy
    def get_dns_domains(self, context):
        """Returns a list of available dns domains.
        These can be used to create DNS entries for floating ips.
        """
        return self.network_rpcapi.get_dns_domains(context)

    @wrap_check_policy
    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address."""
        args = {'address': address,
                'name': name,
                'dns_type': dns_type,
                'domain': domain}
        return self.network_rpcapi.add_dns_entry(context, **args)

    @wrap_check_policy
    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address."""
        args = {'address': address,
                'name': name,
                'domain': domain}
        return self.network_rpcapi.modify_dns_entry(context, **args)

    @wrap_check_policy
    def delete_dns_entry(self, context, name, domain):
        """Delete the specified dns entry."""
        args = {'name': name, 'domain': domain}
        return self.network_rpcapi.delete_dns_entry(context, **args)

    @wrap_check_policy
    def delete_dns_domain(self, context, domain):
        """Delete the specified dns domain."""
        return self.network_rpcapi.delete_dns_domain(context, domain=domain)

    @wrap_check_policy
    def get_dns_entries_by_address(self, context, address, domain):
        """Get entries for address and domain."""
        args = {'address': address, 'domain': domain}
        return self.network_rpcapi.get_dns_entries_by_address(context, **args)

    @wrap_check_policy
    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain."""
        args = {'name': name, 'domain': domain}
        return self.network_rpcapi.get_dns_entries_by_name(context, **args)

    @wrap_check_policy
    def create_private_dns_domain(self, context, domain, availability_zone):
        """Create a private DNS domain with nova availability zone."""
        args = {'domain': domain, 'av_zone': availability_zone}
        return self.network_rpcapi.create_private_dns_domain(context, **args)

    @wrap_check_policy
    def create_public_dns_domain(self, context, domain, project=None):
        """Create a public DNS domain with optional nova project."""
        args = {'domain': domain, 'project': project}
        return self.network_rpcapi.create_public_dns_domain(context, **args)

    @wrap_check_policy
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
        args = (context, instance['uuid'])
        floating_ips = self.db.instance_floating_address_get_all(*args)
        return [floating_ip['address'] for floating_ip in floating_ips]

    @wrap_check_policy
    def migrate_instance_start(self, context, instance, migration):
        """Start to migrate the network of an instance."""
        instance_type = instance_types.extract_instance_type(instance)
        args = dict(
            instance_uuid=instance['uuid'],
            rxtx_factor=instance_type['rxtx_factor'],
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

    @wrap_check_policy
    def migrate_instance_finish(self, context, instance, migration):
        """Finish migrating the network of an instance."""
        instance_type = instance_types.extract_instance_type(instance)
        args = dict(
            instance_uuid=instance['uuid'],
            rxtx_factor=instance_type['rxtx_factor'],
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

    # NOTE(jkoelker) These functions where added to the api after
    #                deprecation. Stubs provided for support documentation
    def allocate_port_for_instance(self, context, instance, port_id,
                                   network_id=None, requested_ip=None,
                                   conductor_api=None):
        raise NotImplementedError()

    def deallocate_port_for_instance(self, context, instance, port_id,
                                     conductor_api=None):
        raise NotImplementedError()

    def list_ports(self, *args, **kwargs):
        raise NotImplementedError()

    def show_port(self, *args, **kwargs):
        raise NotImplementedError()

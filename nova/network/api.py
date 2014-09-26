# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2013 IBM Corp.
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

from oslo.config import cfg

from nova.compute import flavors
from nova.db import base
from nova import exception
from nova.network import floating_ips
from nova.network import model as network_model
from nova.network import rpcapi as network_rpcapi
from nova.objects import fixed_ip as fixed_ip_obj
from nova.objects import instance as instance_obj
from nova.objects import instance_info_cache as info_cache_obj
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import lockutils
from nova.openstack.common import log as logging
from nova import policy
from nova import utils

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


def refresh_cache(f):
    """Decorator to update the instance_info_cache

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

        with lockutils.lock('refresh_cache-%s' % instance['uuid']):
            update_instance_cache_with_nw_info(self, context, instance,
                                               nw_info=res)

        # return the original function's return value
        return res
    return wrapper


def update_instance_cache_with_nw_info(api, context, instance, nw_info=None,
                                       update_cells=True):
    try:
        if not isinstance(nw_info, network_model.NetworkInfo):
            nw_info = None
        if nw_info is None:
            nw_info = api._get_instance_nw_info(context, instance)
        LOG.debug(_('Updating cache with info: %s'), nw_info)
        # NOTE(comstud): The save() method actually handles updating or
        # creating the instance.  We don't need to retrieve the object
        # from the DB first.
        ic = info_cache_obj.InstanceInfoCache.new(context,
                                                  instance['uuid'])
        ic.network_info = nw_info
        ic.save(update_cells=update_cells)
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_('Failed storing info cache'), instance=instance)


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution."""

    @functools.wraps(func)
    def wrapped(self, context, *args, **kwargs):
        action = func.__name__
        check_policy(context, action)
        return func(self, context, *args, **kwargs)

    return wrapped


def check_policy(context, action):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    _action = 'network:%s' % action
    policy.enforce(context, _action, target)


class API(base.Base):
    """API for doing networking via the nova-network network manager.

    This is a pluggable module - other implementations do networking via
    other services (such as Neutron).
    """
    _sentinel = object()

    def __init__(self, **kwargs):
        self.network_rpcapi = network_rpcapi.NetworkAPI()
        helper = utils.ExceptionHelper
        # NOTE(vish): this local version of floating_manager has to convert
        #             ClientExceptions back since they aren't going over rpc.
        self.floating_manager = helper(floating_ips.LocalManager())
        super(API, self).__init__(**kwargs)

    @wrap_check_policy
    def get_all(self, context):
        """Get all the networks.

        If it is an admin user then api will return all the
        networks. If it is a normal user and nova Flat or FlatDHCP
        networking is being used then api will return all
        networks. Otherwise api will only return the networks which
        belong to the user's project.
        """
        if "nova.network.manager.Flat" in CONF.network_manager:
            project_only = "allow_none"
        else:
            project_only = True
        try:
            return self.db.network_get_all(context, project_only=project_only)
        except exception.NoNetworksFound:
            return []

    @wrap_check_policy
    def get(self, context, network_uuid):
        return self.db.network_get_by_uuid(context.elevated(), network_uuid)

    @wrap_check_policy
    def create(self, context, **kwargs):
        return self.network_rpcapi.create_networks(context, **kwargs)

    @wrap_check_policy
    def delete(self, context, network_uuid):
        return self.network_rpcapi.delete_network(context, network_uuid, None)

    @wrap_check_policy
    def disassociate(self, context, network_uuid):
        network = self.get(context, network_uuid)
        self.db.network_disassociate(context, network['id'])

    @wrap_check_policy
    def get_fixed_ip(self, context, id):
        return self.db.fixed_ip_get(context, id)

    @wrap_check_policy
    def get_fixed_ip_by_address(self, context, address):
        return fixed_ip_obj.FixedIP.get_by_address(context, address)

    @wrap_check_policy
    def get_floating_ip(self, context, id):
        if not utils.is_int_like(id):
            raise exception.InvalidID(id=id)
        return self.db.floating_ip_get(context, id)

    @wrap_check_policy
    def get_floating_ip_pools(self, context):
        return self.db.floating_ip_get_pools(context)

    @wrap_check_policy
    def get_floating_ip_by_address(self, context, address):
        return self.db.floating_ip_get_by_address(context, address)

    @wrap_check_policy
    def get_floating_ips_by_project(self, context):
        return self.db.floating_ip_get_all_by_project(context,
                                                      context.project_id)

    @wrap_check_policy
    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        floating_ips = self.db.floating_ip_get_by_fixed_address(context,
                                                                fixed_address)
        return [floating_ip['address'] for floating_ip in floating_ips]

    @wrap_check_policy
    def get_instance_id_by_floating_address(self, context, address):
        fixed_ip = self.db.fixed_ip_get_by_floating_address(context, address)
        if fixed_ip is None:
            return None
        else:
            return fixed_ip['instance_uuid']

    @wrap_check_policy
    def get_vifs_by_instance(self, context, instance):
        vifs = self.db.virtual_interface_get_by_instance(context,
                                                         instance['uuid'])
        for vif in vifs:
            if vif.get('network_id') is not None:
                network = self.db.network_get(context, vif['network_id'],
                                              project_only="allow_none")
                vif['net_uuid'] = network['uuid']
        return vifs

    @wrap_check_policy
    def get_vif_by_mac_address(self, context, mac_address):
        vif = self.db.virtual_interface_get_by_address(context,
                                                       mac_address)
        if vif.get('network_id') is not None:
            network = self.db.network_get(context, vif['network_id'],
                                          project_only="allow_none")
            vif['net_uuid'] = network['uuid']
        return vif

    @wrap_check_policy
    def allocate_floating_ip(self, context, pool=None):
        """Adds (allocates) a floating ip to a project from a pool."""
        return self.floating_manager.allocate_floating_ip(context,
                 context.project_id, False, pool)

    @wrap_check_policy
    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Removes (deallocates) a floating ip with address from a project."""
        return self.floating_manager.deallocate_floating_ip(context, address,
                 affect_auto_assigned)

    def disassociate_and_release_floating_ip(self, context, instance,
                                           floating_ip):
        """Removes (deallocates) and deletes the floating ip.

        This api call was added to allow this to be done in one operation
        if using neutron.
        """

        address = floating_ip['address']
        if floating_ip.get('fixed_ip_id'):
            try:
                self.disassociate_floating_ip(context, instance, address)
            except exception.FloatingIpNotAssociated:
                msg = ("Floating ip %s has already been disassociated, "
                       "perhaps by another concurrent action.") % address
                LOG.debug(msg)

        # release ip from project
        return self.release_floating_ip(context, address)

    @wrap_check_policy
    @refresh_cache
    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associates a floating ip with a fixed ip.

        Ensures floating ip is allocated to the project in context.
        Does not verify ownership of the fixed ip. Caller is assumed to have
        checked that the instance is properly owned.

        """
        orig_instance_uuid = self.floating_manager.associate_floating_ip(
                context, floating_address, fixed_address, affect_auto_assigned)

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
        return self.floating_manager.disassociate_floating_ip(context, address,
                affect_auto_assigned)

    @wrap_check_policy
    @refresh_cache
    def allocate_for_instance(self, context, instance, vpn,
                              requested_networks, macs=None,
                              security_groups=None,
                              dhcp_options=None):
        """Allocates all network structures for an instance.

        :param context: The request context.
        :param instance: An Instance dict.
        :param vpn: A boolean, if True, indicate a vpn to access the instance.
        :param requested_networks: A dictionary of requested_networks,
            Optional value containing network_id, fixed_ip, and port_id.
        :param macs: None or a set of MAC addresses that the instance
            should use. macs is supplied by the hypervisor driver (contrast
            with requested_networks which is user supplied).
        :param security_groups: None or security groups to allocate for
            instance.
        :param dhcp_options: None or a set of key/value pairs that should
            determine the DHCP BOOTP response, eg. for PXE booting an instance
            configured with the baremetal hypervisor. It is expected that these
            are already formatted for the neutron v2 api.
            See nova/virt/driver.py:dhcp_options_for_instance for an example.
        :returns: network info as from get_instance_nw_info() below
        """
        # NOTE(vish): We can't do the floating ip allocation here because
        #             this is called from compute.manager which shouldn't
        #             have db access so we do it on the other side of the
        #             rpc.
        flavor = flavors.extract_flavor(instance)
        args = {}
        args['vpn'] = vpn
        args['requested_networks'] = requested_networks
        args['instance_id'] = instance['uuid']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        args['rxtx_factor'] = flavor['rxtx_factor']
        args['macs'] = macs
        args['dhcp_options'] = dhcp_options
        nw_info = self.network_rpcapi.allocate_for_instance(context, **args)

        return network_model.NetworkInfo.hydrate(nw_info)

    @wrap_check_policy
    def deallocate_for_instance(self, context, instance,
                                requested_networks=None):
        """Deallocates all network structures related to instance."""
        # NOTE(vish): We can't do the floating ip deallocation here because
        #             this is called from compute.manager which shouldn't
        #             have db access so we do it on the other side of the
        #             rpc.
        if not isinstance(instance, instance_obj.Instance):
            instance = instance_obj.Instance._from_db_object(context,
                    instance_obj.Instance(), instance)
        self.network_rpcapi.deallocate_for_instance(context, instance=instance,
                requested_networks=requested_networks)

    # NOTE(danms): Here for neutron compatibility
    def allocate_port_for_instance(self, context, instance, port_id,
                                   network_id=None, requested_ip=None):
        raise NotImplementedError()

    # NOTE(danms): Here for neutron compatibility
    def deallocate_port_for_instance(self, context, instance, port_id):
        raise NotImplementedError()

    # NOTE(danms): Here for neutron compatibility
    def list_ports(self, *args, **kwargs):
        raise NotImplementedError()

    # NOTE(danms): Here for neutron compatibility
    def show_port(self, *args, **kwargs):
        raise NotImplementedError()

    @wrap_check_policy
    @refresh_cache
    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Adds a fixed ip to instance from specified network."""
        flavor = flavors.extract_flavor(instance)
        args = {'instance_id': instance['uuid'],
                'rxtx_factor': flavor['rxtx_factor'],
                'host': instance['host'],
                'network_id': network_id}
        self.network_rpcapi.add_fixed_ip_to_instance(context, **args)

    @wrap_check_policy
    @refresh_cache
    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Removes a fixed ip from instance from specified network."""

        flavor = flavors.extract_flavor(instance)
        args = {'instance_id': instance['uuid'],
                'rxtx_factor': flavor['rxtx_factor'],
                'host': instance['host'],
                'address': address}
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
        network_id = self.get(context, network_uuid)['id']
        if host is not API._sentinel:
            if host is None:
                self.db.network_disassociate(context, network_id,
                                             disassociate_host=True,
                                             disassociate_project=False)
            else:
                self.db.network_set_host(context, network_id, host)
        if project is not API._sentinel:
            if project is None:
                self.db.network_disassociate(context, network_id,
                                             disassociate_host=False,
                                             disassociate_project=True)
            else:
                self.db.network_associate(context, project, network_id, True)

    @wrap_check_policy
    def get_instance_nw_info(self, context, instance):
        """Returns all network info related to an instance."""
        result = self._get_instance_nw_info(context, instance)
        # NOTE(comstud): Don't update API cell with new info_cache every
        # time we pull network info for an instance.  The periodic healing
        # of info_cache causes too many cells messages.  Healing the API
        # will happen separately.
        update_instance_cache_with_nw_info(self, context, instance,
                                           result, update_cells=False)
        return result

    def _get_instance_nw_info(self, context, instance):
        """Returns all network info related to an instance."""
        flavor = flavors.extract_flavor(instance)
        args = {'instance_id': instance['uuid'],
                'rxtx_factor': flavor['rxtx_factor'],
                'host': instance['host'],
                'project_id': instance['project_id']}
        nw_info = self.network_rpcapi.get_instance_nw_info(context, **args)

        return network_model.NetworkInfo.hydrate(nw_info)

    @wrap_check_policy
    def validate_networks(self, context, requested_networks, num_instances):
        """validate the networks passed at the time of creating
        the server.

        Return the number of instances that can be successfully allocated
        with the requested network configuration.
        """
        if requested_networks:
            self.network_rpcapi.validate_networks(context,
                                                  requested_networks)

        # Neutron validation checks and returns how many of num_instances
        # instances can be supported by the quota.  For Nova network
        # this is part of the subsequent quota check, so we just return
        # the requested number in this case.
        return num_instances

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
           instance.
        """
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
        return floating_ips

    @wrap_check_policy
    def migrate_instance_start(self, context, instance, migration):
        """Start to migrate the network of an instance."""
        flavor = flavors.extract_flavor(instance)
        args = dict(
            instance_uuid=instance['uuid'],
            rxtx_factor=flavor['rxtx_factor'],
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
        flavor = flavors.extract_flavor(instance)
        args = dict(
            instance_uuid=instance['uuid'],
            rxtx_factor=flavor['rxtx_factor'],
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

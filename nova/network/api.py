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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils

from nova import exception
from nova.network import base_api
from nova.network import floating_ips
from nova.network import model as network_model
from nova.network import rpcapi as network_rpcapi
from nova import objects
from nova.objects import base as obj_base
from nova import profiler
from nova import utils

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


@profiler.trace_cls("network_api")
class API(base_api.NetworkAPI):
    """API for doing networking via the nova-network network manager.

    This is a pluggable module - other implementations do networking via
    other services (such as Neutron).
    """
    def __init__(self, **kwargs):
        self.network_rpcapi = network_rpcapi.NetworkAPI()
        helper = utils.ExceptionHelper
        # NOTE(vish): this local version of floating_manager has to convert
        #             ClientExceptions back since they aren't going over rpc.
        self.floating_manager = helper(floating_ips.LocalManager())
        super(API, self).__init__(**kwargs)

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
            return objects.NetworkList.get_all(context,
                                               project_only=project_only)
        except exception.NoNetworksFound:
            return []

    def get(self, context, network_uuid):
        return objects.Network.get_by_uuid(context, network_uuid)

    def create(self, context, **kwargs):
        return self.network_rpcapi.create_networks(context, **kwargs)

    def delete(self, context, network_uuid):
        network = self.get(context, network_uuid)
        if network.project_id is not None:
            raise exception.NetworkInUse(network_id=network_uuid)
        return self.network_rpcapi.delete_network(context, network_uuid, None)

    def disassociate(self, context, network_uuid):
        network = self.get(context, network_uuid)
        objects.Network.disassociate(context, network.id,
                                     host=True, project=True)

    def get_fixed_ip(self, context, id):
        return objects.FixedIP.get_by_id(context, id)

    def get_fixed_ip_by_address(self, context, address):
        return objects.FixedIP.get_by_address(context, address)

    def get_floating_ip(self, context, id):
        if not strutils.is_int_like(id):
            raise exception.InvalidID(id=id)
        return objects.FloatingIP.get_by_id(context, id)

    def get_floating_ip_pools(self, context):
        return objects.FloatingIP.get_pool_names(context)

    def get_floating_ip_by_address(self, context, address):
        return objects.FloatingIP.get_by_address(context, address)

    def get_floating_ips_by_project(self, context):
        return objects.FloatingIPList.get_by_project(context,
                                                     context.project_id)

    def get_instance_id_by_floating_address(self, context, address):
        fixed_ip = objects.FixedIP.get_by_floating_address(context, address)
        if fixed_ip is None:
            return None
        else:
            return fixed_ip.instance_uuid

    def get_vifs_by_instance(self, context, instance):
        vifs = objects.VirtualInterfaceList.get_by_instance_uuid(context,
                                                                 instance.uuid)
        for vif in vifs:
            if vif.network_id is not None:
                network = objects.Network.get_by_id(context, vif.network_id,
                                                    project_only='allow_none')
                vif.net_uuid = network.uuid
        return vifs

    def get_vif_by_mac_address(self, context, mac_address):
        vif = objects.VirtualInterface.get_by_address(context,
                                                      mac_address)
        if vif.network_id is not None:
            network = objects.Network.get_by_id(context, vif.network_id,
                                                project_only='allow_none')
            vif.net_uuid = network.uuid
        return vif

    def allocate_floating_ip(self, context, pool=None):
        """Adds (allocates) a floating IP to a project from a pool."""
        return self.floating_manager.allocate_floating_ip(context,
                 context.project_id, False, pool)

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Removes (deallocates) a floating IP with address from a project."""
        return self.floating_manager.deallocate_floating_ip(context, address,
                 affect_auto_assigned)

    def disassociate_and_release_floating_ip(self, context, instance,
                                           floating_ip):
        """Removes (deallocates) and deletes the floating IP.

        This api call was added to allow this to be done in one operation
        if using neutron.
        """

        address = floating_ip['address']
        if floating_ip.get('fixed_ip_id'):
            try:
                self.disassociate_floating_ip(context, instance, address)
            except exception.FloatingIpNotAssociated:
                msg = ("Floating IP %s has already been disassociated, "
                       "perhaps by another concurrent action.") % address
                LOG.debug(msg)

        # release ip from project
        return self.release_floating_ip(context, address)

    @base_api.refresh_cache
    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associates a floating IP with a fixed IP.

        Ensures floating IP is allocated to the project in context.
        Does not verify ownership of the fixed IP. Caller is assumed to have
        checked that the instance is properly owned.

        """
        orig_instance_uuid = self.floating_manager.associate_floating_ip(
                context, floating_address, fixed_address, affect_auto_assigned)

        if orig_instance_uuid:
            msg_dict = dict(address=floating_address,
                            instance_id=orig_instance_uuid)
            LOG.info('re-assign floating IP %(address)s from '
                     'instance %(instance_id)s', msg_dict)
            orig_instance = objects.Instance.get_by_uuid(
                context, orig_instance_uuid, expected_attrs=['flavor'])

            # purge cached nw info for the original instance
            base_api.update_instance_cache_with_nw_info(self, context,
                                                        orig_instance)

    @base_api.refresh_cache
    def disassociate_floating_ip(self, context, instance, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating IP from fixed IP it is associated with."""
        return self.floating_manager.disassociate_floating_ip(context, address,
                affect_auto_assigned)

    @staticmethod
    def _requested_nets_as_obj_list(requested_networks):
        """Helper method to convert a list of requested network tuples into an
        objects.NetworkRequestList.

        :param requested_networks: List of requested networks.
        :return: objects.NetworkRequestList instance
        """
        if requested_networks and not isinstance(requested_networks,
                                                 objects.NetworkRequestList):
            requested_networks = objects.NetworkRequestList.from_tuples(
                requested_networks)
        return requested_networks

    @base_api.refresh_cache
    def allocate_for_instance(self, context, instance, vpn,
                              requested_networks, macs=None,
                              security_groups=None,
                              bind_host_id=None):
        """Allocates all network structures for an instance.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param vpn: A boolean, if True, indicate a vpn to access the instance.
        :param requested_networks: A list of requested_network tuples
            containing network_id and fixed_ip
        :param macs: None or a set of MAC addresses that the instance
            should use. macs is supplied by the hypervisor driver (contrast
            with requested_networks which is user supplied).
        :param security_groups: None or security groups to allocate for
            instance.
        :param bind_host_id: ignored by this driver.
        :returns: network info as from get_instance_nw_info() below
        """
        # NOTE(vish): We can't do the floating ip allocation here because
        #             this is called from compute.manager which shouldn't
        #             have db access so we do it on the other side of the
        #             rpc.
        flavor = instance.get_flavor()
        args = {}
        args['vpn'] = vpn
        args['requested_networks'] = requested_networks
        args['instance_id'] = instance.uuid
        args['project_id'] = instance.project_id
        args['host'] = instance.host
        args['rxtx_factor'] = flavor['rxtx_factor']
        args['macs'] = macs

        # Check to see if we're asked to 'auto' allocate networks because if
        # so we need to just null out the requested_networks value so the
        # network manager doesn't try to get networks with uuid 'auto' which
        # doesn't exist.
        if requested_networks:
            requested_networks = self._requested_nets_as_obj_list(
                requested_networks)

            if requested_networks.auto_allocate:
                args['requested_networks'] = None

        nw_info = self.network_rpcapi.allocate_for_instance(context, **args)

        nw_info = network_model.NetworkInfo.hydrate(nw_info)

        # check to see if nothing was allocated and we were requested to
        # auto-allocate
        if (not nw_info and requested_networks and
                requested_networks.auto_allocate):
            raise exception.UnableToAutoAllocateNetwork(
                project_id=instance.project_id)

        return nw_info

    def deallocate_for_instance(self, context, instance,
                                requested_networks=None):
        """Deallocates all network structures related to instance."""
        # NOTE(vish): We can't do the floating ip deallocation here because
        #             this is called from compute.manager which shouldn't
        #             have db access so we do it on the other side of the
        #             rpc.
        if not isinstance(instance, obj_base.NovaObject):
            instance = objects.Instance._from_db_object(context,
                    objects.Instance(), instance)

        # In the case of 'auto' allocation for networks, just pass None for
        # requested_networks since 'auto' isn't an actual network.
        requested_networks = self._requested_nets_as_obj_list(
            requested_networks)
        if requested_networks and requested_networks.auto_allocate:
            requested_networks = None

        self.network_rpcapi.deallocate_for_instance(context, instance=instance,
                requested_networks=requested_networks)

    # NOTE(danms): Here for neutron compatibility
    def allocate_port_for_instance(self, context, instance, port_id,
                                   network_id=None, requested_ip=None,
                                   bind_host_id=None, tag=None):
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

    @base_api.refresh_cache
    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Adds a fixed IP to instance from specified network."""
        flavor = instance.get_flavor()
        args = {'instance_id': instance.uuid,
                'rxtx_factor': flavor['rxtx_factor'],
                'host': instance.host,
                'network_id': network_id}
        nw_info = self.network_rpcapi.add_fixed_ip_to_instance(
            context, **args)
        return network_model.NetworkInfo.hydrate(nw_info)

    @base_api.refresh_cache
    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Removes a fixed IP from instance from specified network."""

        flavor = instance.get_flavor()
        args = {'instance_id': instance.uuid,
                'rxtx_factor': flavor['rxtx_factor'],
                'host': instance.host,
                'address': address}
        nw_info = self.network_rpcapi.remove_fixed_ip_from_instance(
            context, **args)
        return network_model.NetworkInfo.hydrate(nw_info)

    def add_network_to_project(self, context, project_id, network_uuid=None):
        """Force adds another network to a project."""
        self.network_rpcapi.add_network_to_project(context, project_id,
                network_uuid)

    def associate(self, context, network_uuid, host=base_api.SENTINEL,
                  project=base_api.SENTINEL):
        """Associate or disassociate host or project to network."""
        network = self.get(context, network_uuid)
        if host is not base_api.SENTINEL:
            if host is None:
                objects.Network.disassociate(context, network.id,
                                             host=True, project=False)
            else:
                network.host = host
                network.save()
        if project is not base_api.SENTINEL:
            if project is None:
                objects.Network.disassociate(context, network.id,
                                             host=False, project=True)
            else:
                objects.Network.associate(context, project,
                                          network_id=network.id, force=True)

    def _get_instance_nw_info(self, context, instance, **kwargs):
        """Returns all network info related to an instance."""
        flavor = instance.get_flavor()
        args = {'instance_id': instance.uuid,
                'rxtx_factor': flavor['rxtx_factor'],
                'host': instance.host,
                'project_id': instance.project_id}
        nw_info = self.network_rpcapi.get_instance_nw_info(context, **args)

        return network_model.NetworkInfo.hydrate(nw_info)

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

    def create_pci_requests_for_sriov_ports(self, context,
                                            pci_requests,
                                            requested_networks):
        """Check requested networks for any SR-IOV port request.

        Create a PCI request object for each SR-IOV port, and add it to the
        pci_requests object that contains a list of PCI request object.
        """
        # This is NOOP for Nova network since it doesn't support SR-IOV.
        pass

    def get_dns_domains(self, context):
        """Returns a list of available dns domains.
        These can be used to create DNS entries for floating IPs.
        """
        return self.network_rpcapi.get_dns_domains(context)

    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address."""
        args = {'address': address,
                'name': name,
                'dns_type': dns_type,
                'domain': domain}
        return self.network_rpcapi.add_dns_entry(context, **args)

    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address."""
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
        """Get entries for address and domain."""
        args = {'address': address, 'domain': domain}
        return self.network_rpcapi.get_dns_entries_by_address(context, **args)

    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain."""
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
           instance.
        """
        host = host or instance.host
        # NOTE(tr3buchet): host is passed in cases where we need to setup
        # or teardown the networks on a host which has been migrated to/from
        # and instance.host is not yet or is no longer equal to
        args = {'instance_id': instance.id,
                'host': host,
                'teardown': teardown,
                'instance': instance}

        self.network_rpcapi.setup_networks_on_host(context, **args)

    def _get_multi_addresses(self, context, instance):
        try:
            fixed_ips = objects.FixedIPList.get_by_instance_uuid(
                context, instance.uuid)
        except exception.FixedIpNotFoundForInstance:
            return False, []
        addresses = []
        for fixed in fixed_ips:
            for floating in fixed.floating_ips:
                addresses.append(floating.address)
        return fixed_ips[0].network.multi_host, addresses

    def migrate_instance_start(self, context, instance, migration):
        """Start to migrate the network of an instance."""
        flavor = instance.get_flavor()
        args = dict(
            instance_uuid=instance.uuid,
            rxtx_factor=flavor['rxtx_factor'],
            project_id=instance.project_id,
            source_compute=migration['source_compute'],
            dest_compute=migration['dest_compute'],
            floating_addresses=None,
        )

        multi_host, addresses = self._get_multi_addresses(context, instance)
        if multi_host:
            args['floating_addresses'] = addresses
            args['host'] = migration['source_compute']

        self.network_rpcapi.migrate_instance_start(context, **args)

    def migrate_instance_finish(self, context, instance, migration):
        """Finish migrating the network of an instance."""
        flavor = instance.get_flavor()
        args = dict(
            instance_uuid=instance.uuid,
            rxtx_factor=flavor['rxtx_factor'],
            project_id=instance.project_id,
            source_compute=migration['source_compute'],
            dest_compute=migration['dest_compute'],
            floating_addresses=None,
        )

        multi_host, addresses = self._get_multi_addresses(context, instance)
        if multi_host:
            args['floating_addresses'] = addresses
            args['host'] = migration['dest_compute']

        self.network_rpcapi.migrate_instance_finish(context, **args)

    def setup_instance_network_on_host(self, context, instance, host,
                                       migration=None):
        """Setup network for specified instance on host."""
        self.migrate_instance_finish(context, instance,
                                     {'source_compute': None,
                                      'dest_compute': host})

    def cleanup_instance_network_on_host(self, context, instance, host):
        """Cleanup network for specified instance on host."""
        self.migrate_instance_start(context, instance,
                                    {'source_compute': host,
                                     'dest_compute': None})

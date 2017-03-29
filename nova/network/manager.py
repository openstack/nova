# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2013 IBM Corp.
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

"""Network Hosts are responsible for allocating IPs and setting up network.

There are multiple backend drivers that handle specific types of networking
topologies.  All of the network commands are issued to a subclass of
:class:`NetworkManager`.

"""

import collections
import datetime
import functools
import math
import re

import netaddr
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import periodic_task
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six

import nova.conf
from nova import context
from nova import exception
from nova.i18n import _, _LI, _LE, _LW
from nova import ipv6
from nova import manager
from nova.network import api as network_api
from nova.network import driver
from nova.network import floating_ips
from nova.network import model as network_model
from nova.network import rpcapi as network_rpcapi
from nova.network.security_group import openstack_driver
from nova import objects
from nova.objects import base as obj_base
from nova.objects import quotas as quotas_obj
from nova import servicegroup
from nova import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class RPCAllocateFixedIP(object):
    """Mixin class originally for FlatDCHP and VLAN network managers.

    used since they share code to RPC.call allocate_fixed_ip on the
    correct network host to configure dnsmasq
    """

    servicegroup_api = None

    def _allocate_fixed_ips(self, context, instance_id, host, networks,
                            **kwargs):
        """Calls allocate_fixed_ip once for each network."""
        green_threads = []

        vpn = kwargs.get('vpn')
        requested_networks = kwargs.get('requested_networks')
        addresses_by_network = {}
        if requested_networks is not None:
            for request in requested_networks:
                addresses_by_network[request.network_id] = request.address

        for network in networks:
            if 'uuid' in network and network['uuid'] in addresses_by_network:
                address = addresses_by_network[network['uuid']]
            else:
                address = None
            # NOTE(vish): if we are not multi_host pass to the network host
            # NOTE(tr3buchet): but if we are, host came from instance.host
            if not network['multi_host']:
                host = network['host']
            # NOTE(vish): if there is no network host, set one
            if host is None:
                host = self.network_rpcapi.set_network_host(context,
                                                            network)
            if host != self.host:
                # need to call allocate_fixed_ip to correct network host
                green_threads.append(utils.spawn(
                        self.network_rpcapi._rpc_allocate_fixed_ip,
                        context, instance_id, network['id'], address, vpn,
                        host))
            else:
                # i am the correct host, run here
                self.allocate_fixed_ip(context, instance_id, network,
                                       vpn=vpn, address=address)

        # wait for all of the allocates (if any) to finish
        for gt in green_threads:
            gt.wait()

    def _rpc_allocate_fixed_ip(self, context, instance_id, network_id,
                               **kwargs):
        """Sits in between _allocate_fixed_ips and allocate_fixed_ip to
        perform network lookup on the far side of rpc.
        """
        network = self._get_network_by_id(context, network_id)
        return self.allocate_fixed_ip(context, instance_id, network, **kwargs)

    def deallocate_fixed_ip(self, context, address, host=None, teardown=True,
            instance=None):
        """Call the superclass deallocate_fixed_ip if i'm the correct host
        otherwise call to the correct host
        """
        fixed_ip = objects.FixedIP.get_by_address(
            context, address, expected_attrs=['network'])
        network = fixed_ip.network

        # NOTE(vish): if we are not multi_host pass to the network host
        # NOTE(tr3buchet): but if we are, host came from instance.host
        if not network.multi_host:
            host = network.host
        if host == self.host:
            # NOTE(vish): deallocate the fixed ip locally
            return super(RPCAllocateFixedIP, self).deallocate_fixed_ip(context,
                    address, instance=instance)

        if network.multi_host:
            service = objects.Service.get_by_host_and_binary(
                context, host, 'nova-network')
            if not service or not self.servicegroup_api.service_is_up(service):
                # NOTE(vish): deallocate the fixed ip locally but don't
                #             teardown network devices
                return super(RPCAllocateFixedIP, self).deallocate_fixed_ip(
                        context, address, teardown=False, instance=instance)

        self.network_rpcapi.deallocate_fixed_ip(context, address, host,
                instance)


class NetworkManager(manager.Manager):
    """Implements common network manager functionality.

    This class must be subclassed to support specific topologies.

    host management:
        hosts configure themselves for networks they are assigned to in the
        table upon startup. If there are networks in the table which do not
        have hosts, those will be filled in and have hosts configured
        as the hosts pick them up one at time during their periodic task.
        The one at a time part is to flatten the layout to help scale
    """

    target = messaging.Target(version='1.17')

    # If True, this manager requires VIF to create a bridge.
    SHOULD_CREATE_BRIDGE = False

    # If True, this manager requires VIF to create VLAN tag.
    SHOULD_CREATE_VLAN = False

    # if True, this manager leverages DHCP
    DHCP = False

    timeout_fixed_ips = True

    required_create_args = []

    def __init__(self, network_driver=None, *args, **kwargs):
        self.driver = driver.load_network_driver(network_driver)
        self.instance_dns_manager = importutils.import_object(
                CONF.instance_dns_manager)
        self.instance_dns_domain = CONF.instance_dns_domain
        self.floating_dns_manager = importutils.import_object(
                CONF.floating_ip_dns_manager)
        self.network_api = network_api.API()
        self.network_rpcapi = network_rpcapi.NetworkAPI()
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())

        self.servicegroup_api = servicegroup.API()

        l3_lib = kwargs.get("l3_lib", CONF.l3_lib)
        self.l3driver = importutils.import_object(l3_lib)

        self.quotas_cls = objects.Quotas

        super(NetworkManager, self).__init__(service_name='network',
                                             *args, **kwargs)

    @staticmethod
    def _uses_shared_ip(network):
        shared = network.get('share_address') or CONF.share_dhcp_address
        return not network.get('multi_host') or shared

    @utils.synchronized('get_dhcp')
    def _get_dhcp_ip(self, context, network_ref, host=None):
        """Get the proper dhcp address to listen on."""
        # NOTE(vish): If we are sharing the dhcp_address then we can just
        #             return the dhcp_server from the database.
        if self._uses_shared_ip(network_ref):
            return network_ref.get('dhcp_server') or network_ref['gateway']

        if not host:
            host = self.host
        network_id = network_ref['id']
        try:
            fip = objects.FixedIP.get_by_network_and_host(context,
                                                               network_id,
                                                               host)
            return fip.address
        except exception.FixedIpNotFoundForNetworkHost:
            elevated = context.elevated()
            fip = objects.FixedIP.associate_pool(elevated,
                                                      network_id,
                                                      host=host)
            return fip.address

    def get_dhcp_leases(self, ctxt, network_ref):
        """Broker the request to the driver to fetch the dhcp leases."""
        LOG.debug('Get DHCP leases for network %s', network_ref['uuid'])
        return self.driver.get_dhcp_leases(ctxt, network_ref)

    def init_host(self):
        """Do any initialization that needs to be run if this is a
        standalone service.
        """
        # NOTE(vish): Set up networks for which this host already has
        #             an ip address.
        ctxt = context.get_admin_context()
        for network in objects.NetworkList.get_by_host(ctxt, self.host):
            self._setup_network_on_host(ctxt, network)
            if CONF.update_dns_entries:
                LOG.debug('Update DNS on network %s for host %s',
                          network['uuid'], self.host)
                dev = self.driver.get_dev(network)
                self.driver.update_dns(ctxt, dev, network)
            LOG.info(_LI('Configured network %(network)s on host %(host)s'),
                     {'network': network['uuid'], 'host': self.host})

    @periodic_task.periodic_task
    def _disassociate_stale_fixed_ips(self, context):
        if self.timeout_fixed_ips:
            now = timeutils.utcnow()
            timeout = CONF.fixed_ip_disassociate_timeout
            time = now - datetime.timedelta(seconds=timeout)
            num = objects.FixedIP.disassociate_all_by_timeout(context,
                                                              self.host,
                                                              time)
            if num:
                LOG.debug('Disassociated %s stale fixed IP(s)', num)

    def set_network_host(self, context, network_ref):
        """Safely sets the host of the network."""
        # TODO(mriedem): Remove this compat shim when network RPC API version
        # 1.0 is dropped.
        if not isinstance(network_ref, obj_base.NovaObject):
            network_ref = objects.Network._from_db_object(
                context, objects.Network(), network_ref)
        LOG.debug('Setting host %s for network %s', self.host,
                  network_ref.uuid)
        network_ref.host = self.host
        network_ref.save()
        return self.host

    def _do_trigger_security_group_members_refresh_for_instance(self,
                                                                instance_id):
        # NOTE(francois.charlier): the instance may have been deleted already
        # thus enabling `read_deleted`
        admin_context = context.get_admin_context(read_deleted='yes')
        instance = objects.Instance.get_by_uuid(admin_context, instance_id)

        try:
            # NOTE(vish): We need to make sure the instance info cache has been
            #             updated with new ip info before we trigger the
            #             security group refresh. This is somewhat inefficient
            #             but avoids doing some dangerous refactoring for a
            #             bug fix.
            nw_info = self.get_instance_nw_info(admin_context, instance_id,
                                                None, None)
            ic = objects.InstanceInfoCache.new(admin_context, instance_id)
            ic.network_info = nw_info
            ic.save(update_cells=False)
        except exception.InstanceInfoCacheNotFound:
            pass
        groups = instance.security_groups
        group_ids = [group.id for group in groups]

        self.security_group_api.trigger_members_refresh(admin_context,
                                                        group_ids)

    # NOTE(hanlind): This method can be removed in version 2.0 of the RPC API
    def get_instance_uuids_by_ip_filter(self, context, filters):
        fixed_ip_filter = filters.get('fixed_ip')
        ip_filter = re.compile(str(filters.get('ip')))
        ipv6_filter = re.compile(str(filters.get('ip6')))
        LOG.debug('Get instance uuids by IP filters. Fixed IP filter: %s. '
                  'IP filter: %s. IPv6 filter: %s', fixed_ip_filter,
                  str(filters.get('ip')), str(filters.get('ip6')))

        # NOTE(jkoelker) Should probably figure out a better way to do
        #                this. But for now it "works", this could suck on
        #                large installs.

        vifs = objects.VirtualInterfaceList.get_all(context)
        results = []

        for vif in vifs:
            if vif.instance_uuid is None:
                continue

            network = self._get_network_by_id(context, vif.network_id)
            fixed_ipv6 = None
            if network['cidr_v6'] is not None:
                fixed_ipv6 = ipv6.to_global(network['cidr_v6'],
                                            vif.address,
                                            context.project_id)

            if fixed_ipv6 and ipv6_filter.match(fixed_ipv6):
                results.append({'instance_uuid': vif.instance_uuid,
                                'ip': fixed_ipv6})

            fixed_ips = objects.FixedIPList.get_by_virtual_interface_id(
                context, vif.id)
            for fixed_ip in fixed_ips:
                if not fixed_ip or not fixed_ip.address:
                    continue
                if str(fixed_ip.address) == fixed_ip_filter:
                    results.append({'instance_uuid': vif.instance_uuid,
                                    'ip': fixed_ip.address})
                    continue
                if ip_filter.match(str(fixed_ip.address)):
                    results.append({'instance_uuid': vif.instance_uuid,
                                    'ip': fixed_ip.address})
                    continue
                for floating_ip in fixed_ip.floating_ips:
                    if not floating_ip or not floating_ip.address:
                        continue
                    if ip_filter.match(str(floating_ip.address)):
                        results.append({'instance_uuid': vif.instance_uuid,
                                        'ip': floating_ip.address})
                        continue

        return results

    def _get_networks_for_instance(self, context, instance_id, project_id,
                                   requested_networks=None):
        """Determine & return which networks an instance should connect to."""
        # TODO(tr3buchet) maybe this needs to be updated in the future if
        #                 there is a better way to determine which networks
        #                 a non-vlan instance should connect to
        if requested_networks is not None and len(requested_networks) != 0:
            network_uuids = [request.network_id
                             for request in requested_networks]
            networks = self._get_networks_by_uuids(context, network_uuids)
        else:
            try:
                networks = objects.NetworkList.get_all(context)
            except exception.NoNetworksFound:
                return []
        # return only networks which are not vlan networks
        return [network for network in networks if not network.vlan]

    def allocate_for_instance(self, context, **kwargs):
        """Handles allocating the various network resources for an instance.

        rpc.called by network_api
        """
        instance_uuid = kwargs['instance_id']
        if not uuidutils.is_uuid_like(instance_uuid):
            instance_uuid = kwargs.get('instance_uuid')
        host = kwargs['host']
        project_id = kwargs['project_id']
        rxtx_factor = kwargs['rxtx_factor']
        requested_networks = kwargs.get('requested_networks')
        if (requested_networks and
                not isinstance(requested_networks,
                               objects.NetworkRequestList)):
            requested_networks = objects.NetworkRequestList.from_tuples(
                requested_networks)
        vpn = kwargs['vpn']
        macs = kwargs['macs']
        admin_context = context.elevated()
        networks = self._get_networks_for_instance(context,
                                        instance_uuid, project_id,
                                        requested_networks=requested_networks)
        networks_list = [self._get_network_dict(network)
                                 for network in networks]
        LOG.debug('Networks retrieved for instance: |%s|',
                  networks_list, instance_uuid=instance_uuid)

        try:
            self._allocate_mac_addresses(admin_context, instance_uuid,
                                         networks, macs, requested_networks)
        except Exception:
            with excutils.save_and_reraise_exception():
                # If we fail to allocate any one mac address, clean up all
                # allocated VIFs
                objects.VirtualInterface.delete_by_instance_uuid(
                        context, instance_uuid)

        self._allocate_fixed_ips(admin_context, instance_uuid,
                                 host, networks, vpn=vpn,
                                 requested_networks=requested_networks)

        if CONF.update_dns_entries:
            network_ids = [network['id'] for network in networks]
            self.network_rpcapi.update_dns(context, network_ids)

        net_info = self.get_instance_nw_info(admin_context, instance_uuid,
                                             rxtx_factor, host)
        LOG.info(_LI("Allocated network: '%s' for instance"), net_info,
                 instance_uuid=instance_uuid)
        return net_info

    def deallocate_for_instance(self, context, **kwargs):
        """Handles deallocating various network resources for an instance.

        rpc.called by network_api
        kwargs can contain fixed_ips to circumvent another db lookup
        """
        # NOTE(francois.charlier): in some cases the instance might be
        # deleted before the IPs are released, so we need to get deleted
        # instances too
        read_deleted_context = context.elevated(read_deleted='yes')
        if 'instance' in kwargs:
            instance = kwargs['instance']
            instance_uuid = instance.uuid
            host = instance.host
        else:
            instance_id = kwargs['instance_id']
            if uuidutils.is_uuid_like(instance_id):
                instance = objects.Instance.get_by_uuid(
                        read_deleted_context, instance_id)
            else:
                instance = objects.Instance.get_by_id(
                        read_deleted_context, instance_id)
            # NOTE(russellb) in case instance_id was an ID and not UUID
            instance_uuid = instance.uuid
            host = kwargs.get('host')

        try:
            requested_networks = kwargs.get('requested_networks')
            if requested_networks:
                # NOTE(obondarev): Temporary and transitional
                if isinstance(requested_networks, objects.NetworkRequestList):
                    requested_networks = requested_networks.as_tuples()

                network_ids = set([net_id for (net_id, ip)
                                   in requested_networks])
                fixed_ips = [ip for (net_id, ip) in requested_networks if ip]
            else:
                fixed_ip_list = objects.FixedIPList.get_by_instance_uuid(
                    read_deleted_context, instance_uuid)
                network_ids = set([str(fixed_ip.network_id) for fixed_ip
                               in fixed_ip_list])
                fixed_ips = [str(ip.address) for ip in fixed_ip_list]
        except exception.FixedIpNotFoundForInstance:
            network_ids = set([])
            fixed_ips = []
        LOG.debug("Network deallocation for instance",
                  instance_uuid=instance_uuid)
        # deallocate fixed ips
        for fixed_ip in fixed_ips:
            self.deallocate_fixed_ip(context, fixed_ip, host=host,
                    instance=instance)

        if CONF.update_dns_entries:
            self.network_rpcapi.update_dns(context, list(network_ids))

        # deallocate vifs (mac addresses)
        objects.VirtualInterface.delete_by_instance_uuid(
                read_deleted_context, instance_uuid)
        LOG.info(_LI("Network deallocated for instance (fixed IPs: '%s')"),
                 fixed_ips, instance_uuid=instance_uuid)

    @messaging.expected_exceptions(exception.InstanceNotFound)
    def get_instance_nw_info(self, context, instance_id, rxtx_factor,
                             host, instance_uuid=None, **kwargs):
        """Creates network info list for instance.

        called by allocate_for_instance and network_api
        context needs to be elevated
        :returns: network info list [(network,info),(network,info)...]
        where network = dict containing pertinent data from a network db object
        and info = dict containing pertinent networking data
        """
        if not uuidutils.is_uuid_like(instance_id):
            instance_id = instance_uuid
        instance_uuid = instance_id
        LOG.debug('Get instance network info', instance_uuid=instance_uuid)

        try:
            fixed_ips = objects.FixedIPList.get_by_instance_uuid(
                    context, instance_uuid)
        except exception.FixedIpNotFoundForInstance:
            fixed_ips = []

        LOG.debug('Found %d fixed IPs associated to the instance in the '
                  'database.',
                  len(fixed_ips), instance_uuid=instance_uuid)

        nw_info = network_model.NetworkInfo()

        vifs = collections.OrderedDict()
        for fixed_ip in fixed_ips:
            vif = fixed_ip.virtual_interface
            if not vif:
                LOG.warning(_LW('No VirtualInterface for FixedIP: %s'),
                         str(fixed_ip.address), instance_uuid=instance_uuid)
                continue

            if not fixed_ip.network:
                LOG.warning(_LW('No Network for FixedIP: %s'),
                         str(fixed_ip.address), instance_uuid=instance_uuid)
                continue

            if vif.uuid in vifs:
                current = vifs[vif.uuid]
            else:
                current = {
                    'id': vif.uuid,
                    'type': network_model.VIF_TYPE_BRIDGE,
                    'address': vif.address,
                }
                vifs[vif.uuid] = current

                net_dict = self._get_network_dict(fixed_ip.network)
                network = network_model.Network(**net_dict)
                subnets = self._get_subnets_from_network(context,
                                                         fixed_ip.network,
                                                         host)
                network['subnets'] = subnets
                current['network'] = network
                try:
                    current['rxtx_cap'] = (fixed_ip.network['rxtx_base'] *
                                            rxtx_factor)
                except (TypeError, KeyError):
                    pass
                if fixed_ip.network.cidr_v6 and vif.address:
                    # NOTE(vish): I strongly suspect the v6 subnet is not used
                    #             anywhere, but support it just in case
                    # add the v6 address to the v6 subnet
                    address = ipv6.to_global(fixed_ip.network.cidr_v6,
                                             vif.address,
                                             fixed_ip.network.project_id)
                    model_ip = network_model.FixedIP(address=address)
                    current['network']['subnets'][1]['ips'].append(model_ip)

            # add the v4 address to the v4 subnet
            model_ip = network_model.FixedIP(address=str(fixed_ip.address))
            for ip in fixed_ip.floating_ips:
                floating_ip = network_model.IP(address=str(ip['address']),
                                               type='floating')
                model_ip.add_floating_ip(floating_ip)
            current['network']['subnets'][0]['ips'].append(model_ip)

        for vif in vifs.values():
            nw_info.append(network_model.VIF(**vif))

        LOG.debug('Built network info: |%s|', nw_info,
                  instance_uuid=instance_uuid)
        return nw_info

    @staticmethod
    def _get_network_dict(network):
        """Returns the dict representing necessary and meta network fields."""
        # get generic network fields
        network_dict = {'id': network['uuid'],
                        'bridge': network['bridge'],
                        'label': network['label'],
                        'tenant_id': network['project_id']}

        # get extra information
        if network.get('injected'):
            network_dict['injected'] = network['injected']

        return network_dict

    @staticmethod
    def _extract_subnets(network):
        """Returns information about the IPv4 and IPv6 subnets
           associated with a Neutron Network UUID.
        """
        subnet_v4 = {
            'network_id': network.uuid,
            'cidr': network.cidr,
            'gateway': network.gateway,
            'dhcp_server': getattr(network, 'dhcp_server'),
            'broadcast': network.broadcast,
            'netmask': network.netmask,
            'version': 4,
            'dns1': network.dns1,
            'dns2': network.dns2}
        # TODO(tr3buchet): I'm noticing we've assumed here that all dns is v4.
        #                  this is probably bad as there is no way to add v6
        #                  dns to nova
        subnet_v6 = {
            'network_id': network.uuid,
            'cidr': network.cidr_v6,
            'gateway': network.gateway_v6,
            'dhcp_server': None,
            'broadcast': None,
            'netmask': network.netmask_v6,
            'version': 6,
            'dns1': None,
            'dns2': None}

        def ips_to_strs(net):
            for key, value in net.items():
                if isinstance(value, netaddr.ip.BaseIP):
                    net[key] = str(value)
            return net

        return [ips_to_strs(subnet_v4), ips_to_strs(subnet_v6)]

    def _get_subnets_from_network(self, context, network, instance_host=None):
        """Returns the 1 or 2 possible subnets for a nova network."""
        extracted_subnets = self._extract_subnets(network)
        subnets = []
        for subnet in extracted_subnets:
            subnet_dict = {'cidr': subnet['cidr'],
                           'gateway': network_model.IP(
                                             address=subnet['gateway'],
                                             type='gateway')}
            # deal with dhcp
            if self.DHCP:
                if network.get('multi_host'):
                    dhcp_server = self._get_dhcp_ip(context, network,
                                                    instance_host)
                else:
                    dhcp_server = self._get_dhcp_ip(context, subnet)
                subnet_dict['dhcp_server'] = dhcp_server

            subnet_object = network_model.Subnet(**subnet_dict)

            # add dns info
            for k in ['dns1', 'dns2']:
                if subnet.get(k):
                    subnet_object.add_dns(
                         network_model.IP(address=subnet[k], type='dns'))

            subnet_object['ips'] = []

            subnets.append(subnet_object)

        return subnets

    def _allocate_mac_addresses(self, context, instance_uuid, networks, macs,
                                requested_networks):
        """Generates mac addresses and creates vif rows in db for them."""
        # make a copy we can mutate
        if macs is not None:
            available_macs = set(macs)

        if requested_networks:
            tags_by_network = {
                network.network_id: network.tag if 'tag' in network else None
                for network in requested_networks}
        else:
            tags_by_network = {}

        for network in networks:
            if macs is None:
                self._add_virtual_interface(
                    context, instance_uuid,
                    network['id'],
                    tag=tags_by_network.get(network['uuid']))
            else:
                try:
                    mac = available_macs.pop()
                except KeyError:
                    raise exception.VirtualInterfaceCreateException()
                self._add_virtual_interface(
                    context, instance_uuid,
                    network['id'], mac,
                    tag=tags_by_network.get(network['uuid']))

    def _add_virtual_interface(self, context, instance_uuid, network_id,
                               mac=None, tag=None):
        attempts = 1 if mac else CONF.create_unique_mac_address_attempts
        for i in range(attempts):
            try:
                vif = objects.VirtualInterface(context)
                vif.address = mac or utils.generate_mac_address()
                vif.instance_uuid = instance_uuid
                vif.network_id = network_id
                vif.uuid = uuidutils.generate_uuid()
                vif.tag = tag
                vif.create()
                return vif
            except exception.VirtualInterfaceCreateException:
                # Try again up to max number of attempts
                pass

        raise exception.VirtualInterfaceMacAddressException()

    def add_fixed_ip_to_instance(self, context, instance_id, host, network_id,
                                 rxtx_factor=None):
        """Adds a fixed IP to an instance from specified network."""
        if uuidutils.is_uuid_like(network_id):
            network = self.get_network(context, network_id)
        else:
            network = self._get_network_by_id(context, network_id)
        LOG.debug('Add fixed IP on network %s', network['uuid'],
                  instance_uuid=instance_id)
        self._allocate_fixed_ips(context, instance_id, host, [network])
        return self.get_instance_nw_info(context, instance_id, rxtx_factor,
                                         host)

    # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
    # deprecated in favor of the method in the base API.
    def get_backdoor_port(self, context):
        """Return backdoor port for eventlet_backdoor."""
        return self.backdoor_port

    def remove_fixed_ip_from_instance(self, context, instance_id, host,
                                      address, rxtx_factor=None):
        """Removes a fixed IP from an instance from specified network."""
        LOG.debug('Remove fixed IP %s', address, instance_uuid=instance_id)
        fixed_ips = objects.FixedIPList.get_by_instance_uuid(context,
                                                             instance_id)
        for fixed_ip in fixed_ips:
            if str(fixed_ip.address) == address:
                self.deallocate_fixed_ip(context, address, host)
                # NOTE(vish): this probably isn't a dhcp ip so just
                #             deallocate it now. In the extremely rare
                #             case that this is a race condition, we
                #             will just get a warn in lease or release.
                if not fixed_ip.leased:
                    fixed_ip.disassociate()
                return self.get_instance_nw_info(context, instance_id,
                                                 rxtx_factor, host)
        raise exception.FixedIpNotFoundForSpecificInstance(
                                    instance_uuid=instance_id, ip=address)

    def _validate_instance_zone_for_dns_domain(self, context, instance):
        if not self.instance_dns_domain:
            return True
        instance_domain = self.instance_dns_domain

        domainref = objects.DNSDomain.get_by_domain(context, instance_domain)
        if domainref is None:
            LOG.warning(_LW('instance-dns-zone not found |%s|.'),
                     instance_domain, instance=instance)
            return True
        dns_zone = domainref.availability_zone

        instance_zone = instance.get('availability_zone')
        if dns_zone and (dns_zone != instance_zone):
            LOG.warning(_LW('instance-dns-zone is |%(domain)s|, '
                            'which is in availability zone |%(zone)s|. '
                            'Instance is in zone |%(zone2)s|. '
                            'No DNS record will be created.'),
                        {'domain': instance_domain,
                         'zone': dns_zone,
                         'zone2': instance_zone},
                        instance=instance)
            return False
        else:
            return True

    def allocate_fixed_ip(self, context, instance_id, network, **kwargs):
        """Gets a fixed IP from the pool."""
        # TODO(vish): when this is called by compute, we can associate compute
        #             with a network, or a cluster of computes with a network
        #             and use that network here with a method like
        #             network_get_by_compute_host
        address = None

        # NOTE(vish) This db query could be removed if we pass az and name
        #            (or the whole instance object).
        instance = objects.Instance.get_by_uuid(context, instance_id)
        LOG.debug('Allocate fixed IP on network %s', network['uuid'],
                  instance=instance)

        # A list of cleanup functions to call on error
        cleanup = []

        # Check the quota; can't put this in the API because we get
        # called into from other places
        quotas = self.quotas_cls(context=context)
        quota_project, quota_user = quotas_obj.ids_from_instance(context,
                                                                 instance)
        try:
            quotas.check_deltas(context, {'fixed_ips': 1}, quota_project)
        except exception.OverQuota as exc:
            count = exc.kwargs['usages']['fixed_ips']
            LOG.warning(_LW("Quota exceeded for project %(pid)s, tried to "
                            "allocate fixed IP. %(used)s of %(allowed)s are "
                            "in use or are already reserved."),
                        {'pid': quota_project, 'used': count,
                         'allowed': exc.kwargs['quotas']['fixed_ips']},
                        instance_uuid=instance_id)
            raise exception.FixedIpLimitExceeded()

        try:
            if network['cidr']:

                # NOTE(mriedem): allocate the vif before associating the
                # instance to reduce a race window where a previous instance
                # was associated with the fixed IP and has released it, because
                # release_fixed_ip will disassociate if allocated is False.
                vif = objects.VirtualInterface.get_by_instance_and_network(
                        context, instance_id, network['id'])
                if vif is None:
                    LOG.debug('vif for network %(network)s is used up, '
                              'trying to create new vif',
                              {'network': network['id']}, instance=instance)
                    vif = self._add_virtual_interface(context,
                        instance_id, network['id'])

                address = kwargs.get('address', None)
                if address:
                    LOG.debug('Associating instance with specified fixed IP '
                              '%(address)s in network %(network)s on subnet '
                              '%(cidr)s.',
                              {'address': address, 'network': network['id'],
                               'cidr': network['cidr']},
                              instance=instance)
                    fip = objects.FixedIP.associate(
                            context, str(address), instance_id, network['id'],
                            vif_id=vif.id)
                else:
                    LOG.debug('Associating instance with fixed IP from pool '
                              'in network %(network)s on subnet %(cidr)s.',
                              {'network': network['id'],
                               'cidr': network['cidr']},
                              instance=instance)
                    fip = objects.FixedIP.associate_pool(
                        context.elevated(), network['id'], instance_id,
                        vif_id=vif.id)
                    LOG.debug('Associated instance with fixed IP: %s', fip,
                              instance=instance)
                    address = str(fip.address)

                cleanup.append(functools.partial(fip.disassociate, context))

                # NOTE(melwitt): We recheck the quota after creating the object
                # to prevent users from allocating more resources than their
                # allowed quota in the event of a race. This is configurable
                # because it can be expensive if strict quota limits are not
                # required in a deployment.
                if CONF.quota.recheck_quota:
                    try:
                        quotas.check_deltas(context, {'fixed_ips': 0},
                                            quota_project)
                    except exception.OverQuota as exc:
                        # Cleanup of the fixed IP allocation occurs in the
                        # outermost catch-all except block.
                        count = exc.kwargs['usages']['fixed_ips']
                        allowed = exc.kwargs['quotas']['fixed_ips']
                        LOG.warning(_LW("Quota exceeded for project %(pid)s, "
                                        "tried to allocate fixed IP. %(used)s "
                                        "of %(allowed)s are in use or are "
                                        "already reserved."),
                                    {'pid': quota_project, 'used': count,
                                     'allowed': allowed},
                                    instance_uuid=instance_id)
                        raise exception.FixedIpLimitExceeded()

                LOG.debug('Refreshing security group members for instance.',
                          instance=instance)
                self._do_trigger_security_group_members_refresh_for_instance(
                    instance_id)
                cleanup.append(functools.partial(
                    self._do_trigger_security_group_members_refresh_for_instance,  # noqa
                    instance_id))

            name = instance.display_name

            if self._validate_instance_zone_for_dns_domain(context, instance):
                self.instance_dns_manager.create_entry(
                    name, str(fip.address), "A", self.instance_dns_domain)
                cleanup.append(functools.partial(
                        self.instance_dns_manager.delete_entry,
                        name, self.instance_dns_domain))

                self.instance_dns_manager.create_entry(
                    instance_id, str(fip.address), "A",
                    self.instance_dns_domain)
                cleanup.append(functools.partial(
                        self.instance_dns_manager.delete_entry,
                        instance_id, self.instance_dns_domain))

            LOG.debug('Setting up network %(network)s on host %(host)s.',
                      {'network': network['id'], 'host': self.host},
                      instance=instance)
            self._setup_network_on_host(context, network)
            cleanup.append(functools.partial(
                    self._teardown_network_on_host,
                    context, network))

            if address is None:
                # TODO(mriedem): should _setup_network_on_host return the addr?
                LOG.debug('Fixed IP is setup on network %s but not returning '
                          'the specific IP from the base network manager.',
                          network['uuid'], instance=instance)
            else:
                LOG.debug('Allocated fixed IP %s on network %s', address,
                          network['uuid'], instance=instance)
            return address

        except Exception:
            with excutils.save_and_reraise_exception():
                for f in cleanup:
                    try:
                        f()
                    except Exception:
                        LOG.warning(_LW('Error cleaning up fixed IP '
                                        'allocation. Manual cleanup may '
                                        'be required.'), exc_info=True)

    def deallocate_fixed_ip(self, context, address, host=None, teardown=True,
            instance=None):
        """Returns a fixed IP to the pool."""
        fixed_ip_ref = objects.FixedIP.get_by_address(
            context, address, expected_attrs=['network'])
        instance_uuid = fixed_ip_ref.instance_uuid
        vif_id = fixed_ip_ref.virtual_interface_id
        LOG.debug('Deallocate fixed IP %s', address,
                  instance_uuid=instance_uuid)

        if not instance:
            # NOTE(vish) This db query could be removed if we pass az and name
            #            (or the whole instance object).
            # NOTE(danms) We can't use fixed_ip_ref.instance because
            #             instance may be deleted and the relationship
            #             doesn't extend to deleted instances
            instance = objects.Instance.get_by_uuid(
                context.elevated(read_deleted='yes'), instance_uuid)

        self._do_trigger_security_group_members_refresh_for_instance(
            instance_uuid)

        if self._validate_instance_zone_for_dns_domain(context, instance):
            for n in self.instance_dns_manager.get_entries_by_address(
                address, self.instance_dns_domain):
                self.instance_dns_manager.delete_entry(n,
                    self.instance_dns_domain)

        fixed_ip_ref.allocated = False
        fixed_ip_ref.save()

        if teardown:
            network = fixed_ip_ref.network

            if CONF.force_dhcp_release:
                dev = self.driver.get_dev(network)
                # NOTE(vish): The below errors should never happen, but
                #             there may be a race condition that is causing
                #             them per
                #             https://code.launchpad.net/bugs/968457,
                #             so we log a message to help track down
                #             the possible race.
                if not vif_id:
                    LOG.info(_LI("Unable to release %s because vif "
                                 "doesn't exist"), address)
                    return

                vif = objects.VirtualInterface.get_by_id(context, vif_id)

                if not vif:
                    LOG.info(_LI("Unable to release %s because vif "
                                 "object doesn't exist"), address)
                    return

                # NOTE(cfb): Call teardown before release_dhcp to ensure
                #            that the IP can't be re-leased after a release
                #            packet is sent.
                self._teardown_network_on_host(context, network)
                # NOTE(vish): This forces a packet so that the
                #             release_fixed_ip callback will
                #             get called by nova-dhcpbridge.
                try:
                    self.network_rpcapi.release_dhcp(context,
                                                     instance.launched_on,
                                                     dev, address,
                                                     vif.address)
                except exception.RPCPinnedToOldVersion:
                    # Fall back on previous behaviour of calling
                    # release_dhcp on the local driver
                    self.driver.release_dhcp(dev, address, vif.address)
                except exception.NetworkDhcpReleaseFailed:
                    LOG.error(_LE("Error releasing DHCP for IP %(address)s"
                                  " with MAC %(mac_address)s"),
                              {'address': address,
                               'mac_address': vif.address},
                              instance=instance)

                # NOTE(yufang521247): This is probably a failed dhcp fixed
                # ip. DHCPRELEASE packet sent to dnsmasq would not trigger
                # dhcp-bridge to run. Thus it is better to disassociate
                # such fixed ip here.
                fixed_ip_ref = objects.FixedIP.get_by_address(
                    context, address)
                if (instance_uuid == fixed_ip_ref.instance_uuid and
                        not fixed_ip_ref.leased):
                    LOG.debug('Explicitly disassociating fixed IP %s from '
                              'instance.', address,
                              instance_uuid=instance_uuid)
                    fixed_ip_ref.disassociate()
            else:
                # We can't try to free the IP address so just call teardown
                self._teardown_network_on_host(context, network)

    def release_dhcp(self, context, dev, address, vif_address):
        self.driver.release_dhcp(dev, address, vif_address)

    def lease_fixed_ip(self, context, address):
        """Called by dhcp-bridge when IP is leased."""
        LOG.debug('Leased IP |%s|', address)
        fixed_ip = objects.FixedIP.get_by_address(context, address)

        if fixed_ip.instance_uuid is None:
            LOG.warning(_LW('IP %s leased that is not associated'), fixed_ip)
            return
        fixed_ip.leased = True
        fixed_ip.save()
        if not fixed_ip.allocated:
            LOG.warning(_LW('IP |%s| leased that isn\'t allocated'), fixed_ip,
                        instance_uuid=fixed_ip.instance_uuid)

    def release_fixed_ip(self, context, address, mac=None):
        """Called by dhcp-bridge when IP is released."""
        LOG.debug('Released IP |%s|', address)
        fixed_ip = objects.FixedIP.get_by_address(context, address)

        if fixed_ip.instance_uuid is None:
            LOG.warning(_LW('IP %s released that is not associated'), fixed_ip)
            return
        if not fixed_ip.leased:
            LOG.warning(_LW('IP %s released that was not leased'), fixed_ip,
                        instance_uuid=fixed_ip.instance_uuid)
        else:
            fixed_ip.leased = False
            fixed_ip.save()
        if not fixed_ip.allocated:
            # NOTE(mriedem): Sometimes allocate_fixed_ip will associate the
            # fixed IP to a new instance while an old associated instance is
            # being deallocated. So we check to see if the mac is for the VIF
            # that is associated to the instance that is currently associated
            # with the fixed IP because if it's not, we hit this race and
            # should ignore the request so we don't disassociate the fixed IP
            # from the wrong instance.
            if mac:
                LOG.debug('Checking to see if virtual interface with MAC '
                          '%(mac)s is still associated to instance.',
                          {'mac': mac}, instance_uuid=fixed_ip.instance_uuid)
                vif = objects.VirtualInterface.get_by_address(context, mac)
                if vif:
                    LOG.debug('Found VIF: %s', vif,
                              instance_uuid=fixed_ip.instance_uuid)
                    if vif.instance_uuid != fixed_ip.instance_uuid:
                        LOG.info(_LI("Ignoring request to release fixed IP "
                                     "%(address)s with MAC %(mac)s since it "
                                     "is now associated with a new instance "
                                     "that is in the process of allocating "
                                     "it's network."),
                                 {'address': address, 'mac': mac},
                                 instance_uuid=fixed_ip.instance_uuid)
                        return
                else:
                    LOG.debug('No VIF was found for MAC: %s', mac,
                              instance_uuid=fixed_ip.instance_uuid)

            LOG.debug('Disassociating fixed IP %s from instance.', address,
                      instance_uuid=fixed_ip.instance_uuid)
            fixed_ip.disassociate()

    @staticmethod
    def _convert_int_args(kwargs):
        int_args = ("network_size", "num_networks",
                    "vlan_start", "vpn_start")
        for key in int_args:
            try:
                value = kwargs.get(key)
                if value is None:
                    continue
                kwargs[key] = int(value)
            except ValueError:
                raise exception.InvalidIntValue(key=key)

    def create_networks(self, context,
                        label, cidr=None, multi_host=None, num_networks=None,
                        network_size=None, cidr_v6=None,
                        gateway=None, gateway_v6=None, bridge=None,
                        bridge_interface=None, dns1=None, dns2=None,
                        fixed_cidr=None, allowed_start=None,
                        allowed_end=None, **kwargs):
        if 'dhcp_server' not in kwargs:
            kwargs['dhcp_server'] = gateway
        if 'enable_dhcp' not in kwargs:
            kwargs['enable_dhcp'] = True
        if 'share_address' not in kwargs:
            kwargs['share_address'] = CONF.share_dhcp_address
        kwargs.update({
            'label': label,
            'cidr': cidr,
            'multi_host': multi_host,
            'num_networks': num_networks,
            'network_size': network_size,
            'cidr_v6': cidr_v6,
            'gateway': gateway,
            'gateway_v6': gateway_v6,
            'bridge': bridge,
            'bridge_interface': bridge_interface,
            'dns1': dns1,
            'dns2': dns2,
            'fixed_cidr': fixed_cidr,
            'allowed_start': allowed_start,
            'allowed_end': allowed_end,
        })
        self._convert_int_args(kwargs)

        kwargs["bridge"] = kwargs["bridge"] or CONF.flat_network_bridge
        kwargs["bridge_interface"] = (kwargs["bridge_interface"] or
                                      CONF.flat_interface)

        for fld in self.required_create_args:
            if not kwargs[fld]:
                raise exception.NetworkNotCreated(req=fld)

        if kwargs["cidr_v6"]:
            # NOTE(vish): just for validation
            try:
                netaddr.IPNetwork(kwargs["cidr_v6"])
            except netaddr.AddrFormatError:
                raise exception.InvalidCidr(cidr=kwargs["cidr_v6"])

        if kwargs["cidr"]:
            try:
                fixnet = netaddr.IPNetwork(kwargs["cidr"])
            except netaddr.AddrFormatError:
                raise exception.InvalidCidr(cidr=kwargs["cidr"])

        kwargs["num_networks"] = kwargs["num_networks"] or CONF.num_networks
        if not kwargs["network_size"]:
            if kwargs["cidr"]:
                each_subnet_size = fixnet.size / kwargs["num_networks"]
                if each_subnet_size > CONF.network_size:
                    subnet = 32 - int(math.log(CONF.network_size, 2))
                    oversize_msg = _LW(
                        'Subnet(s) too large, defaulting to /%s.'
                        '  To override, specify network_size flag.') % subnet
                    LOG.warning(oversize_msg)
                    kwargs["network_size"] = CONF.network_size
                else:
                    kwargs["network_size"] = fixnet.size
            else:
                kwargs["network_size"] = CONF.network_size

        kwargs["multi_host"] = (
            CONF.multi_host
            if kwargs["multi_host"] is None
            else strutils.bool_from_string(kwargs["multi_host"]))

        kwargs["vlan_start"] = kwargs.get("vlan_start") or CONF.vlan_start
        kwargs["vpn_start"] = kwargs.get("vpn_start") or CONF.vpn_start
        kwargs["dns1"] = kwargs["dns1"] or CONF.flat_network_dns

        if kwargs["fixed_cidr"]:
            try:
                kwargs["fixed_cidr"] = netaddr.IPNetwork(kwargs["fixed_cidr"])
            except netaddr.AddrFormatError:
                raise exception.InvalidCidr(cidr=kwargs["fixed_cidr"])

            # Subnet of fixed IPs must fall within fixed range
            if kwargs["fixed_cidr"] not in fixnet:
                raise exception.AddressOutOfRange(
                    address=kwargs["fixed_cidr"].network, cidr=fixnet)

        LOG.debug('Create network: |%s|', kwargs)
        return self._do_create_networks(context, **kwargs)

    @staticmethod
    def _index_of(subnet, ip):
        try:
            start = netaddr.IPAddress(ip)
        except netaddr.AddrFormatError:
            raise exception.InvalidAddress(address=ip)
        index = start.value - subnet.value
        if index < 0 or index >= subnet.size:
            raise exception.AddressOutOfRange(address=ip, cidr=str(subnet))
        return index

    def _validate_cidr(self, context, nets, subnets_v4, fixed_net_v4):
        used_subnets = [net.cidr for net in nets]

        def find_next(subnet):
            next_subnet = subnet.next()
            while next_subnet in subnets_v4:
                next_subnet = next_subnet.next()
            if next_subnet in fixed_net_v4:
                return next_subnet

        for subnet in list(subnets_v4):
            if subnet in used_subnets:
                next_subnet = find_next(subnet)
                if next_subnet:
                    subnets_v4.remove(subnet)
                    subnets_v4.append(next_subnet)
                    subnet = next_subnet
                else:
                    raise exception.CidrConflict(cidr=subnet,
                                                 other=subnet)
            for used_subnet in used_subnets:
                if subnet in used_subnet:
                    raise exception.CidrConflict(cidr=subnet,
                                                 other=used_subnet)
                if used_subnet in subnet:
                    next_subnet = find_next(subnet)
                    if next_subnet:
                        subnets_v4.remove(subnet)
                        subnets_v4.append(next_subnet)
                        subnet = next_subnet
                    else:
                        raise exception.CidrConflict(cidr=subnet,
                                                     other=used_subnet)

    def _do_create_networks(self, context,
                            label, cidr, multi_host, num_networks,
                            network_size, cidr_v6, gateway, gateway_v6, bridge,
                            bridge_interface, dns1=None, dns2=None,
                            fixed_cidr=None, mtu=None, dhcp_server=None,
                            enable_dhcp=None, share_address=None,
                            allowed_start=None, allowed_end=None, **kwargs):
        """Create networks based on parameters."""
        # NOTE(jkoelker): these are dummy values to make sure iter works
        # TODO(tr3buchet): disallow carving up networks
        fixed_net_v4 = netaddr.IPNetwork('0/32')
        fixed_net_v6 = netaddr.IPNetwork('::0/128')
        subnets_v4 = []
        subnets_v6 = []

        if kwargs.get('ipam'):
            if cidr_v6:
                subnets_v6 = [netaddr.IPNetwork(cidr_v6)]
            if cidr:
                subnets_v4 = [netaddr.IPNetwork(cidr)]
        else:
            subnet_bits = int(math.ceil(math.log(network_size, 2)))
            if cidr_v6:
                fixed_net_v6 = netaddr.IPNetwork(cidr_v6)
                prefixlen_v6 = 128 - subnet_bits
                # smallest subnet in IPv6 ethernet network is /64
                if prefixlen_v6 > 64:
                    prefixlen_v6 = 64
                subnets_v6 = fixed_net_v6.subnet(prefixlen_v6,
                                                 count=num_networks)
            if cidr:
                fixed_net_v4 = netaddr.IPNetwork(cidr)
                prefixlen_v4 = 32 - subnet_bits
                subnets_v4 = list(fixed_net_v4.subnet(prefixlen_v4,
                                                      count=num_networks))

        if cidr:
            # NOTE(jkoelker): This replaces the _validate_cidrs call and
            #                 prevents looping multiple times
            try:
                nets = objects.NetworkList.get_all(context)
            except exception.NoNetworksFound:
                nets = []
            num_used_nets = len(nets)
            self._validate_cidr(context, nets, subnets_v4, fixed_net_v4)

        networks = objects.NetworkList(context=context, objects=[])
        subnets = six.moves.zip_longest(subnets_v4, subnets_v6)
        for index, (subnet_v4, subnet_v6) in enumerate(subnets):
            net = objects.Network(context=context)
            uuid = kwargs.get('uuid')
            if uuid:
                net.uuid = uuid
            net.bridge = bridge
            net.bridge_interface = bridge_interface
            net.multi_host = multi_host

            net.dns1 = dns1
            net.dns2 = dns2
            net.mtu = mtu
            net.enable_dhcp = enable_dhcp
            net.share_address = share_address

            net.project_id = kwargs.get('project_id')

            if num_networks > 1:
                net.label = '%s_%d' % (label, index)
            else:
                net.label = label

            bottom_reserved = self._bottom_reserved_ips
            top_reserved = self._top_reserved_ips
            extra_reserved = []
            if cidr and subnet_v4:
                current = subnet_v4[1]
                if allowed_start:
                    val = self._index_of(subnet_v4, allowed_start)
                    current = netaddr.IPAddress(allowed_start)
                    bottom_reserved = val
                if allowed_end:
                    val = self._index_of(subnet_v4, allowed_end)
                    top_reserved = subnet_v4.size - 1 - val
                net.cidr = str(subnet_v4)
                net.netmask = str(subnet_v4.netmask)
                net.broadcast = str(subnet_v4.broadcast)
                if gateway:
                    net.gateway = gateway
                else:
                    net.gateway = current
                    current += 1
                net.dhcp_server = dhcp_server or net.gateway
                net.dhcp_start = current
                current += 1
                if net.dhcp_start == net.dhcp_server:
                    net.dhcp_start = current
                extra_reserved.append(str(net.dhcp_server))
                extra_reserved.append(str(net.gateway))

            if cidr_v6 and subnet_v6:
                net.cidr_v6 = str(subnet_v6)
                if gateway_v6:
                    # use a pre-defined gateway if one is provided
                    net.gateway_v6 = str(gateway_v6)
                else:
                    net.gateway_v6 = str(subnet_v6[1])

                net.netmask_v6 = str(subnet_v6.netmask)

            if CONF.network_manager == 'nova.network.manager.VlanManager':
                vlan = kwargs.get('vlan', None)
                if not vlan:
                    index_vlan = index + num_used_nets
                    vlan = kwargs['vlan_start'] + index_vlan
                    used_vlans = [x.vlan for x in nets]
                    if vlan in used_vlans:
                        # That vlan is used, try to get another one
                        used_vlans.sort()
                        vlan = used_vlans[-1] + 1

                net.vpn_private_address = net.dhcp_start
                extra_reserved.append(str(net.vpn_private_address))
                net.dhcp_start = net.dhcp_start + 1
                net.vlan = vlan
                net.bridge = 'br%s' % vlan

                # NOTE(vish): This makes ports unique across the cloud, a more
                #             robust solution would be to make them uniq per ip
                index_vpn = index + num_used_nets
                net.vpn_public_port = kwargs['vpn_start'] + index_vpn

            net.create()
            networks.objects.append(net)

            if cidr and subnet_v4:
                self._create_fixed_ips(context, net.id, fixed_cidr,
                                       extra_reserved, bottom_reserved,
                                       top_reserved)
        # NOTE(danms): Remove this in RPC API v2.0
        return obj_base.obj_to_primitive(networks)

    def delete_network(self, context, fixed_range, uuid,
            require_disassociated=True):

        # Prefer uuid but we'll also take cidr for backwards compatibility
        elevated = context.elevated()
        if uuid:
            network = objects.Network.get_by_uuid(elevated, uuid)
        elif fixed_range:
            network = objects.Network.get_by_cidr(elevated, fixed_range)
        LOG.debug('Delete network %s', network['uuid'])

        if require_disassociated and network.project_id is not None:
            raise exception.NetworkHasProject(project_id=network.project_id)
        network.destroy()

    @property
    def _bottom_reserved_ips(self):
        """Number of reserved IPs at the bottom of the range."""
        return 2  # network, gateway

    @property
    def _top_reserved_ips(self):
        """Number of reserved IPs at the top of the range."""
        return 1  # broadcast

    def _create_fixed_ips(self, context, network_id, fixed_cidr=None,
                          extra_reserved=None, bottom_reserved=0,
                          top_reserved=0):
        """Create all fixed IPs for network."""
        network = self._get_network_by_id(context, network_id)
        if extra_reserved is None:
            extra_reserved = []
        if not fixed_cidr:
            fixed_cidr = netaddr.IPNetwork(network['cidr'])
        num_ips = len(fixed_cidr)
        ips = []
        for index in range(num_ips):
            address = str(fixed_cidr[index])
            if (index < bottom_reserved or num_ips - index <= top_reserved or
                address in extra_reserved):
                reserved = True
            else:
                reserved = False

            ips.append({'network_id': network_id,
                        'address': address,
                        'reserved': reserved})
        objects.FixedIPList.bulk_create(context, ips)

    def _allocate_fixed_ips(self, context, instance_id, host, networks,
                            **kwargs):
        """Calls allocate_fixed_ip once for each network."""
        raise NotImplementedError()

    def setup_networks_on_host(self, context, instance_id, host, instance=None,
                               teardown=False):
        """calls setup/teardown on network hosts for an instance."""
        green_threads = []

        if teardown:
            call_func = self._teardown_network_on_host
        else:
            call_func = self._setup_network_on_host
        if instance is None:
            instance = objects.Instance.get_by_id(context, instance_id)
        vifs = objects.VirtualInterfaceList.get_by_instance_uuid(
                context, instance.uuid)
        LOG.debug('Setup networks on host', instance=instance)
        for vif in vifs:
            network = objects.Network.get_by_id(context, vif.network_id)
            if not network.multi_host:
                # NOTE (tr3buchet): if using multi_host, host is instance.host
                host = network['host']
            if self.host == host or host is None:
                # at this point i am the correct host, or host doesn't
                # matter -> FlatManager
                call_func(context, network)
            else:
                # i'm not the right host, run call on correct host
                green_threads.append(utils.spawn(
                        self.network_rpcapi.rpc_setup_network_on_host, context,
                        network.id, teardown, host))

        # wait for all of the setups (if any) to finish
        for gt in green_threads:
            gt.wait()

    def rpc_setup_network_on_host(self, context, network_id, teardown):
        if teardown:
            call_func = self._teardown_network_on_host
        else:
            call_func = self._setup_network_on_host

        # subcall from original setup_networks_on_host
        network = objects.Network.get_by_id(context, network_id)
        call_func(context, network)

    def _initialize_network(self, network):
        if network.enable_dhcp:
            is_ext = (network.dhcp_server is not None and
                      network.dhcp_server != network.gateway)
            self.l3driver.initialize_network(network.cidr, is_ext)
        self.l3driver.initialize_gateway(network)

    def _setup_network_on_host(self, context, network):
        """Sets up network on this host."""
        raise NotImplementedError()

    def _teardown_network_on_host(self, context, network):
        """Sets up network on this host."""
        raise NotImplementedError()

    def validate_networks(self, context, networks):
        """check if the networks exists and host
        is set to each network.
        """
        LOG.debug('Validate networks')
        if networks is None or len(networks) == 0:
            return

        for network_uuid, address in networks:
            # check if the fixed IP address is valid and
            # it actually belongs to the network
            if address is not None:
                if not netutils.is_valid_ip(address):
                    raise exception.FixedIpInvalid(address=address)

                fixed_ip_ref = objects.FixedIP.get_by_address(
                    context, address, expected_attrs=['network'])
                network = fixed_ip_ref.network
                if network.uuid != network_uuid:
                    raise exception.FixedIpNotFoundForNetwork(
                        address=address, network_uuid=network_uuid)
                if fixed_ip_ref.instance_uuid is not None:
                    raise exception.FixedIpAlreadyInUse(
                        address=address,
                        instance_uuid=fixed_ip_ref.instance_uuid)

    def _get_network_by_id(self, context, network_id):
        return objects.Network.get_by_id(context, network_id,
                                         project_only='allow_none')

    def _get_networks_by_uuids(self, context, network_uuids):
        networks = objects.NetworkList.get_by_uuids(
            context, network_uuids, project_only="allow_none")
        networks.sort(key=lambda x: network_uuids.index(x.uuid))
        return networks

    def get_vifs_by_instance(self, context, instance_id):
        """Returns the vifs associated with an instance."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        instance = objects.Instance.get_by_id(context, instance_id)
        LOG.debug('Get VIFs for instance', instance=instance)

        # NOTE(russellb) No need to object-ify this since
        # get_vifs_by_instance() is unused and set to be removed.
        vifs = objects.VirtualInterfaceList.get_by_instance_uuid(context,
                                                                 instance.uuid)
        for vif in vifs:
            if vif.network_id is not None:
                network = self._get_network_by_id(context, vif.network_id)
                vif.net_uuid = network.uuid
        return [dict(vif) for vif in vifs]

    def get_instance_id_by_floating_address(self, context, address):
        """Returns the instance id a floating IP's fixed IP is allocated to."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        LOG.debug('Get instance for floating address %s', address)
        fixed_ip = objects.FixedIP.get_by_floating_address(context, address)
        if fixed_ip is None:
            return None
        else:
            return fixed_ip.instance_uuid

    def get_network(self, context, network_uuid):
        # NOTE(vish): used locally

        return objects.Network.get_by_uuid(context.elevated(), network_uuid)

    def get_all_networks(self, context):
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        try:
            return obj_base.obj_to_primitive(
                objects.NetworkList.get_all(context))
        except exception.NoNetworksFound:
            return []

    def disassociate_network(self, context, network_uuid):
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        network = self.get_network(context, network_uuid)
        network.disassociate(context, network.id)

    def get_fixed_ip(self, context, id):
        """Return a fixed IP."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        return objects.FixedIP.get_by_id(context, id)

    def get_fixed_ip_by_address(self, context, address):
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        return objects.FixedIP.get_by_address(context, address)

    def get_vif_by_mac_address(self, context, mac_address):
        """Returns the vifs record for the mac_address."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        # NOTE(russellb) No need to object-ify this since
        # get_vifs_by_instance() is unused and set to be removed.
        vif = objects.VirtualInterface.get_by_address(context, mac_address)
        if vif.network_id is not None:
            network = self._get_network_by_id(context, vif.network_id)
            vif.net_uuid = network.uuid
        return vif

    @periodic_task.periodic_task(
        spacing=CONF.dns_update_periodic_interval)
    def _periodic_update_dns(self, context):
        """Update local DNS entries of all networks on this host."""
        networks = objects.NetworkList.get_by_host(context, self.host)
        for network in networks:
            dev = self.driver.get_dev(network)
            self.driver.update_dns(context, dev, network)

    def update_dns(self, context, network_ids):
        """Called when fixed IP is allocated or deallocated."""
        if CONF.fake_network:
            return

        LOG.debug('Update DNS for network ids: %s', network_ids)
        networks = [network for network in
                    objects.NetworkList.get_by_host(context, self.host)
                    if network.multi_host and network.id in network_ids]
        for network in networks:
            dev = self.driver.get_dev(network)
            self.driver.update_dns(context, dev, network)

    def add_network_to_project(self, ctxt, project_id, network_uuid):
        raise NotImplementedError()


class FlatManager(NetworkManager):
    """Basic network where no vlans are used.

    FlatManager does not do any bridge or vlan creation.  The user is
    responsible for setting up whatever bridges are specified when creating
    networks through nova-manage. This bridge needs to be created on all
    compute hosts.

    The idea is to create a single network for the host with a command like:
    nova-manage network create 192.168.0.0/24 1 256. Creating multiple
    networks for one manager is currently not supported, but could be
    added by modifying allocate_fixed_ip and get_network to get the network
    with new logic. Arbitrary lists of addresses in a single network can
    be accomplished with manual db editing.

    If flat_injected is True, the compute host will attempt to inject network
    config into the guest.  It attempts to modify /etc/network/interfaces and
    currently only works on debian based systems. To support a wider range of
    OSes, some other method may need to be devised to let the guest know which
    IP it should be using so that it can configure itself. Perhaps an attached
    disk or serial device with configuration info.

    Metadata forwarding must be handled by the gateway, and since nova does
    not do any setup in this mode, it must be done manually.  Requests to
    169.254.169.254 port 80 will need to be forwarded to the api server.

    """

    timeout_fixed_ips = False

    required_create_args = ['bridge']

    def _allocate_fixed_ips(self, context, instance_id, host, networks,
                            **kwargs):
        """Calls allocate_fixed_ip once for each network."""
        requested_networks = kwargs.get('requested_networks')
        addresses_by_network = {}
        if requested_networks is not None:
            for request in requested_networks:
                addresses_by_network[request.network_id] = request.address
        for network in networks:
            if network['uuid'] in addresses_by_network:
                address = addresses_by_network[network['uuid']]
            else:
                address = None
            self.allocate_fixed_ip(context, instance_id,
                                   network, address=address)

    def deallocate_fixed_ip(self, context, address, host=None, teardown=True,
            instance=None):
        """Returns a fixed IP to the pool."""
        super(FlatManager, self).deallocate_fixed_ip(context, address, host,
                                                     teardown,
                                                     instance=instance)
        objects.FixedIP.disassociate_by_address(context, address)

    def _setup_network_on_host(self, context, network):
        """Setup Network on this host."""
        # NOTE(tr3buchet): this does not need to happen on every ip
        # allocation, this functionality makes more sense in create_network
        # but we'd have to move the flat_injected flag to compute
        network.injected = CONF.flat_injected
        network.save()

    def _teardown_network_on_host(self, context, network):
        """Tear down network on this host."""
        pass

    # NOTE(justinsb): The floating ip functions are stub-implemented.
    # We were throwing an exception, but this was messing up horizon.
    # Timing makes it difficult to implement floating ips here, in Essex.

    def get_floating_ip(self, context, id):
        """Returns a floating IP as a dict."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        return None

    def get_floating_pools(self, context):
        """Returns list of floating pools."""
        # NOTE(maurosr) This method should be removed in future, replaced by
        # get_floating_ip_pools. See bug #1091668
        return {}

    def get_floating_ip_pools(self, context):
        """Returns list of floating IP pools."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        return {}

    def get_floating_ip_by_address(self, context, address):
        """Returns a floating IP as a dict."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        return None

    def get_floating_ips_by_project(self, context):
        """Returns the floating IPs allocated to a project."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        return []

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        """Returns the floating IPs associated with a fixed_address."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        return []

    # NOTE(hanlind): This method can be removed in version 2.0 of the RPC API
    def allocate_floating_ip(self, context, project_id, pool):
        """Gets a floating IP from the pool."""
        return None

    # NOTE(hanlind): This method can be removed in version 2.0 of the RPC API
    def deallocate_floating_ip(self, context, address,
                               affect_auto_assigned):
        """Returns a floating IP to the pool."""
        return None

    # NOTE(hanlind): This method can be removed in version 2.0 of the RPC API
    def associate_floating_ip(self, context, floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associates a floating IP with a fixed IP.

        Makes sure everything makes sense then calls _associate_floating_ip,
        rpc'ing to correct host if i'm not it.
        """
        return None

    # NOTE(hanlind): This method can be removed in version 2.0 of the RPC API
    def disassociate_floating_ip(self, context, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating IP from its fixed IP.

        Makes sure everything makes sense then calls _disassociate_floating_ip,
        rpc'ing to correct host if i'm not it.
        """
        return None

    def migrate_instance_start(self, context, instance_uuid,
                               floating_addresses,
                               rxtx_factor=None, project_id=None,
                               source=None, dest=None):
        pass

    def migrate_instance_finish(self, context, instance_uuid,
                                floating_addresses, host=None,
                                rxtx_factor=None, project_id=None,
                                source=None, dest=None):
        pass

    def update_dns(self, context, network_ids):
        """Called when fixed IP is allocated or deallocated."""
        pass


class FlatDHCPManager(RPCAllocateFixedIP, floating_ips.FloatingIP,
                      NetworkManager):
    """Flat networking with dhcp.

    FlatDHCPManager will start up one dhcp server to give out addresses.
    It never injects network settings into the guest. It also manages bridges.
    Otherwise it behaves like FlatManager.

    """

    SHOULD_CREATE_BRIDGE = True
    DHCP = True
    required_create_args = ['bridge']

    def init_host(self):
        """Do any initialization that needs to be run if this is a
        standalone service.
        """
        ctxt = context.get_admin_context()
        networks = objects.NetworkList.get_by_host(ctxt, self.host)

        self.driver.iptables_manager.defer_apply_on()

        self.l3driver.initialize(fixed_range=False, networks=networks)
        super(FlatDHCPManager, self).init_host()
        self.init_host_floating_ips()

        self.driver.iptables_manager.defer_apply_off()

    def _setup_network_on_host(self, context, network):
        """Sets up network on this host."""
        network.dhcp_server = self._get_dhcp_ip(context, network)

        self._initialize_network(network)

        # NOTE(vish): if dhcp server is not set then don't dhcp
        if not CONF.fake_network and network.enable_dhcp:
            dev = self.driver.get_dev(network)
            # NOTE(dprince): dhcp DB queries require elevated context
            elevated = context.elevated()
            self.driver.update_dhcp(elevated, dev, network)
            if CONF.use_ipv6:
                self.driver.update_ra(context, dev, network)
                gateway = utils.get_my_linklocal(dev)
                network.gateway_v6 = gateway
                network.save()

    def _teardown_network_on_host(self, context, network):
        # NOTE(vish): if dhcp server is not set then don't dhcp
        if not CONF.fake_network and network.enable_dhcp:
            network['dhcp_server'] = self._get_dhcp_ip(context, network)
            dev = self.driver.get_dev(network)
            # NOTE(dprince): dhcp DB queries require elevated context
            elevated = context.elevated()
            self.driver.update_dhcp(elevated, dev, network)

    def _get_network_dict(self, network):
        """Returns the dict representing necessary and meta network fields."""

        # get generic network fields
        network_dict = super(FlatDHCPManager, self)._get_network_dict(network)

        # get flat dhcp specific fields
        if self.SHOULD_CREATE_BRIDGE:
            network_dict['should_create_bridge'] = self.SHOULD_CREATE_BRIDGE
        if network.get('bridge_interface'):
            network_dict['bridge_interface'] = network['bridge_interface']
        if network.get('multi_host'):
            network_dict['multi_host'] = network['multi_host']

        return network_dict


class VlanManager(RPCAllocateFixedIP, floating_ips.FloatingIP, NetworkManager):
    """Vlan network with dhcp.

    VlanManager is the most complicated.  It will create a host-managed
    vlan for each project.  Each project gets its own subnet.  The networks
    and associated subnets are created with nova-manage using a command like:
    nova-manage network create 10.0.0.0/8 3 16.  This will create 3 networks
    of 16 addresses from the beginning of the 10.0.0.0 range.

    A dhcp server is run for each subnet, so each project will have its own.
    For this mode to be useful, each project will need a vpn to access the
    instances in its subnet.

    """

    SHOULD_CREATE_BRIDGE = True
    SHOULD_CREATE_VLAN = True
    DHCP = True
    required_create_args = ['bridge_interface']

    def __init__(self, network_driver=None, *args, **kwargs):
        super(VlanManager, self).__init__(network_driver=network_driver,
                                          *args, **kwargs)
        # NOTE(cfb) VlanManager doesn't enforce quotas on fixed IP addresses
        #           because a project is assigned an entire network.
        self.quotas_cls = objects.QuotasNoOp

    def init_host(self):
        """Do any initialization that needs to be run if this is a
        standalone service.
        """

        LOG.debug('Setup network on host %s', self.host)
        ctxt = context.get_admin_context()
        networks = objects.NetworkList.get_by_host(ctxt, self.host)

        self.driver.iptables_manager.defer_apply_on()

        self.l3driver.initialize(fixed_range=False, networks=networks)
        NetworkManager.init_host(self)
        self.init_host_floating_ips()

        self.driver.iptables_manager.defer_apply_off()

    def allocate_fixed_ip(self, context, instance_id, network, **kwargs):
        """Gets a fixed IP from the pool."""

        LOG.debug('Allocate fixed IP on network %s', network['uuid'],
                  instance_uuid=instance_id)

        # NOTE(mriedem): allocate the vif before associating the
        # instance to reduce a race window where a previous instance
        # was associated with the fixed IP and has released it, because
        # release_fixed_ip will disassociate if allocated is False.
        vif = objects.VirtualInterface.get_by_instance_and_network(
            context, instance_id, network['id'])
        if vif is None:
            LOG.debug('vif for network %(network)s and instance '
                      '%(instance_id)s is used up, '
                      'trying to create new vif',
                      {'network': network['id'],
                       'instance_id': instance_id})
            vif = self._add_virtual_interface(context,
                instance_id, network['id'])

        if kwargs.get('vpn', None):
            address = network['vpn_private_address']
            fip = objects.FixedIP.associate(context, str(address),
                                            instance_id, network['id'],
                                            reserved=True,
                                            vif_id=vif.id)
        else:
            address = kwargs.get('address', None)
            if address:
                fip = objects.FixedIP.associate(context, str(address),
                                                instance_id,
                                                network['id'],
                                                vif_id=vif.id)
            else:
                fip = objects.FixedIP.associate_pool(
                        context, network['id'], instance_id,
                        vif_id=vif.id)
        address = fip.address

        if not kwargs.get('vpn', None):
            self._do_trigger_security_group_members_refresh_for_instance(
                                                                   instance_id)

        # NOTE(vish) This db query could be removed if we pass az and name
        #            (or the whole instance object).
        instance = objects.Instance.get_by_uuid(context, instance_id)

        name = instance.display_name
        if self._validate_instance_zone_for_dns_domain(context, instance):
            self.instance_dns_manager.create_entry(name, address,
                                                   "A",
                                                   self.instance_dns_domain)
            self.instance_dns_manager.create_entry(instance_id, address,
                                                   "A",
                                                   self.instance_dns_domain)

        self._setup_network_on_host(context, network)
        LOG.debug('Allocated fixed IP %s on network %s', address,
                  network['uuid'], instance=instance)
        return address

    def add_network_to_project(self, context, project_id, network_uuid=None):
        """Force adds another network to a project."""
        LOG.debug('Add network %s to project %s', network_uuid, project_id)
        if network_uuid is not None:
            network_id = self.get_network(context, network_uuid).id
        else:
            network_id = None
        objects.Network.associate(context, project_id, network_id, force=True)

    def associate(self, context, network_uuid, associations):
        """Associate or disassociate host or project to network."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi to 2.0.
        LOG.debug('Associate network %s: |%s|', network_uuid, associations)
        network = self.get_network(context, network_uuid)
        network_id = network.id
        if 'host' in associations:
            host = associations['host']
            if host is None:
                network.disassociate(context, network_id,
                                     host=True, project=False)
            else:
                network.host = self.host
                network.save()
        if 'project' in associations:
            project = associations['project']
            if project is None:
                network.disassociate(context, network_id,
                                     host=False, project=True)
            else:
                network.associate(context, project, network_id, force=True)

    def _get_network_by_id(self, context, network_id):
        # NOTE(vish): Don't allow access to networks with project_id=None as
        #             these are networks that haven't been allocated to a
        #             project yet.
        return objects.Network.get_by_id(context, network_id,
                                         project_only=True)

    def _get_networks_by_uuids(self, context, network_uuids):
        # NOTE(vish): Don't allow access to networks with project_id=None as
        #             these are networks that haven't been allocated to a
        #             project yet.
        networks = objects.NetworkList.get_by_uuids(
            context, network_uuids, project_only=True)
        networks.sort(key=lambda x: network_uuids.index(x.uuid))
        return networks

    def _get_networks_for_instance(self, context, instance_id, project_id,
                                   requested_networks=None):
        """Determine which networks an instance should connect to."""
        # get networks associated with project
        if requested_networks is not None and len(requested_networks) != 0:
            network_uuids = [request.network_id
                             for request in requested_networks]
            networks = self._get_networks_by_uuids(context, network_uuids)
        else:
            # NOTE(vish): Allocates network on demand so requires admin.
            networks = objects.NetworkList.get_by_project(
                    context.elevated(), project_id)
        return networks

    def create_networks(self, context, **kwargs):
        """Create networks based on parameters."""
        self._convert_int_args(kwargs)

        kwargs["vlan_start"] = kwargs.get("vlan_start") or CONF.vlan_start
        kwargs["num_networks"] = (kwargs.get("num_networks") or
                                  CONF.num_networks)
        kwargs["network_size"] = (kwargs.get("network_size") or
                                  CONF.network_size)
        # Check that num_networks + vlan_start is not > 4094, fixes lp708025
        if kwargs["num_networks"] + kwargs["vlan_start"] > 4094:
            raise ValueError(_('The sum between the number of networks and'
                               ' the vlan start cannot be greater'
                               ' than 4094'))

        # Check that vlan is not greater than 4094 or less then 1
        vlan_num = kwargs.get("vlan", None)
        if vlan_num is not None:
            try:
                vlan_num = int(vlan_num)
            except ValueError:
                raise ValueError(_("vlan must be an integer"))
            if vlan_num > 4094:
                raise ValueError(_('The vlan number cannot be greater than'
                                   ' 4094'))
            if vlan_num < 1:
                raise ValueError(_('The vlan number cannot be less than 1'))

        # check that num networks and network size fits in fixed_net
        fixed_net = netaddr.IPNetwork(kwargs['cidr'])
        if fixed_net.size < kwargs['num_networks'] * kwargs['network_size']:
            raise ValueError(_('The network range is not '
                  'big enough to fit %(num_networks)s networks. Network '
                  'size is %(network_size)s') % kwargs)

        kwargs['bridge_interface'] = (kwargs.get('bridge_interface') or
                                      CONF.vlan_interface)
        LOG.debug('Create network: |%s|', kwargs)
        return NetworkManager.create_networks(
            self, context, vpn=True, **kwargs)

    @utils.synchronized('setup_network', external=True)
    def _setup_network_on_host(self, context, network):
        """Sets up network on this host."""
        if not network.vpn_public_address:
            address = CONF.vpn_ip
            network.vpn_public_address = address
            network.save()
        else:
            address = network.vpn_public_address
        network.dhcp_server = self._get_dhcp_ip(context, network)

        self._initialize_network(network)

        # NOTE(vish): only ensure this forward if the address hasn't been set
        #             manually.
        if address == CONF.vpn_ip and hasattr(self.driver,
                                               "ensure_vpn_forward"):
            self.l3driver.add_vpn(CONF.vpn_ip,
                    network.vpn_public_port,
                    network.vpn_private_address)
        if not CONF.fake_network:
            dev = self.driver.get_dev(network)
            # NOTE(dprince): dhcp DB queries require elevated context
            if network.enable_dhcp:
                elevated = context.elevated()
                self.driver.update_dhcp(elevated, dev, network)
            if CONF.use_ipv6:
                self.driver.update_ra(context, dev, network)
                gateway = utils.get_my_linklocal(dev)
                network.gateway_v6 = gateway
                network.save()

    @utils.synchronized('setup_network', external=True)
    def _teardown_network_on_host(self, context, network):
        if not CONF.fake_network:
            network['dhcp_server'] = self._get_dhcp_ip(context, network)
            dev = self.driver.get_dev(network)

            # NOTE(ethuleau): For multi hosted networks, if the network is no
            # more used on this host and if VPN forwarding rule aren't handed
            # by the host, we delete the network gateway.
            vpn_address = network['vpn_public_address']
            if (CONF.teardown_unused_network_gateway and
                network['multi_host'] and vpn_address != CONF.vpn_ip and
                not objects.Network.in_use_on_host(context, network['id'],
                                                   self.host)):
                LOG.debug("Remove unused gateway %s", network['bridge'])
                if network.enable_dhcp:
                    self.driver.kill_dhcp(dev)
                self.l3driver.remove_gateway(network)
                if not self._uses_shared_ip(network):
                    fip = objects.FixedIP.get_by_address(context,
                                                         network.dhcp_server)
                    fip.allocated = False
                    fip.host = None
                    fip.save()
            # NOTE(vish): if dhcp server is not set then don't dhcp
            elif network.enable_dhcp:
                # NOTE(dprince): dhcp DB queries require elevated context
                elevated = context.elevated()
                self.driver.update_dhcp(elevated, dev, network)

    def _get_network_dict(self, network):
        """Returns the dict representing necessary and meta network fields."""

        # get generic network fields
        network_dict = super(VlanManager, self)._get_network_dict(network)

        # get vlan specific network fields
        if self.SHOULD_CREATE_BRIDGE:
            network_dict['should_create_bridge'] = self.SHOULD_CREATE_BRIDGE
        if self.SHOULD_CREATE_VLAN:
            network_dict['should_create_vlan'] = self.SHOULD_CREATE_VLAN
        for k in ['vlan', 'bridge_interface', 'multi_host']:
            if network.get(k):
                network_dict[k] = network[k]

        return network_dict

    @property
    def _bottom_reserved_ips(self):
        """Number of reserved IPs at the bottom of the range."""
        return super(VlanManager, self)._bottom_reserved_ips + 1  # vpn server

    @property
    def _top_reserved_ips(self):
        """Number of reserved IPs at the top of the range."""
        parent_reserved = super(VlanManager, self)._top_reserved_ips
        return parent_reserved + CONF.cnt_vpn_clients

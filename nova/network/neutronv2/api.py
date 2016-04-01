# Copyright 2012 OpenStack Foundation
# All Rights Reserved
# Copyright (c) 2012 NEC Corporation
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
#

import copy
import time
import uuid

from keystoneauth1 import loading as ks_loading
from neutronclient.common import exceptions as neutron_client_exc
from neutronclient.v2_0 import client as clientv20
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import uuidutils
import six

from nova.api.openstack import extensions
from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.i18n import _, _LE, _LI, _LW
from nova.network import base_api
from nova.network import model as network_model
from nova.network.neutronv2 import constants
from nova import objects
from nova.objects import fields as obj_fields
from nova.pci import manager as pci_manager
from nova.pci import request as pci_request
from nova.pci import utils as pci_utils
from nova.pci import whitelist as pci_whitelist

neutron_opts = [
    cfg.StrOpt('url',
               default='http://127.0.0.1:9696',
               help='URL for connecting to neutron'),
    cfg.StrOpt('region_name',
               help='Region name for connecting to neutron in admin context'),
    cfg.StrOpt('ovs_bridge',
               default='br-int',
               help='Default OVS bridge name to use if not specified '
                    'by Neutron'),
    cfg.IntOpt('extension_sync_interval',
                default=600,
                help='Number of seconds before querying neutron for'
                     ' extensions'),
   ]

NEUTRON_GROUP = 'neutron'

CONF = nova.conf.CONF
CONF.register_opts(neutron_opts, NEUTRON_GROUP)

deprecations = {'cafile': [cfg.DeprecatedOpt('ca_certificates_file',
                                             group=NEUTRON_GROUP)],
                'insecure': [cfg.DeprecatedOpt('api_insecure',
                                               group=NEUTRON_GROUP)],
                'timeout': [cfg.DeprecatedOpt('url_timeout',
                                              group=NEUTRON_GROUP)]}

_neutron_options = ks_loading.register_session_conf_options(
    CONF, NEUTRON_GROUP, deprecated_opts=deprecations)
ks_loading.register_auth_conf_options(CONF, NEUTRON_GROUP)


CONF.import_opt('default_floating_pool', 'nova.network.floating_ips')
LOG = logging.getLogger(__name__)

soft_external_network_attach_authorize = extensions.soft_core_authorizer(
    'network', 'attach_external_network')

_SESSION = None
_ADMIN_AUTH = None


def list_opts():
    opts = copy.deepcopy(_neutron_options)
    opts.insert(0, ks_loading.get_auth_common_conf_options()[0])
    # NOTE(dims): There are a lot of auth plugins, we just generate
    # the config options for a few common ones
    plugins = ['password', 'v2password', 'v3password']
    for name in plugins:
        plugin = ks_loading.get_plugin_loader(name)
        for plugin_option in ks_loading.get_auth_plugin_conf_options(plugin):
            for option in opts:
                if option.name == plugin_option.name:
                    break
            else:
                opts.append(plugin_option)
    opts.sort(key=lambda x: x.name)
    return [(NEUTRON_GROUP, opts)]


def reset_state():
    global _ADMIN_AUTH
    global _SESSION

    _ADMIN_AUTH = None
    _SESSION = None


def _load_auth_plugin(conf):
    auth_plugin = ks_loading.load_auth_from_conf_options(conf, NEUTRON_GROUP)

    if auth_plugin:
        return auth_plugin

    err_msg = _('Unknown auth plugin: %s') % conf.neutron.auth_plugin
    raise neutron_client_exc.Unauthorized(message=err_msg)


def get_client(context, admin=False):
    # NOTE(dprince): In the case where no auth_token is present we allow use of
    # neutron admin tenant credentials if it is an admin context.  This is to
    # support some services (metadata API) where an admin context is used
    # without an auth token.
    global _ADMIN_AUTH
    global _SESSION

    auth_plugin = None

    if not _SESSION:
        _SESSION = ks_loading.load_session_from_conf_options(
            CONF, NEUTRON_GROUP)

    if admin or (context.is_admin and not context.auth_token):
        if not _ADMIN_AUTH:
            _ADMIN_AUTH = _load_auth_plugin(CONF)
        auth_plugin = _ADMIN_AUTH

    elif context.auth_token:
        auth_plugin = context.get_auth_plugin()

    if not auth_plugin:
        # We did not get a user token and we should not be using
        # an admin token so log an error
        raise neutron_client_exc.Unauthorized()

    return clientv20.Client(session=_SESSION,
                            auth=auth_plugin,
                            endpoint_override=CONF.neutron.url,
                            region_name=CONF.neutron.region_name)


def _is_not_duplicate(item, items, items_list_name, instance):
    present = item in items

    # The expectation from this function's perspective is that the
    # item is not part of the items list so if it is part of it
    # we should at least log it as a warning
    if present:
        LOG.warning(_LW("%(item)s already exists in list: %(list_name)s "
                        "containing: %(items)s. ignoring it"),
                    {'item': item,
                     'list_name': items_list_name,
                     'items': items},
                    instance=instance)

    return not present


class API(base_api.NetworkAPI):
    """API for interacting with the neutron 2.x API."""

    def __init__(self, skip_policy_check=False):
        super(API, self).__init__(skip_policy_check=skip_policy_check)
        self.last_neutron_extension_sync = None
        self.extensions = {}

    def setup_networks_on_host(self, context, instance, host=None,
                               teardown=False):
        """Setup or teardown the network structures."""

    def _get_available_networks(self, context, project_id,
                                net_ids=None, neutron=None):
        """Return a network list available for the tenant.
        The list contains networks owned by the tenant and public networks.
        If net_ids specified, it searches networks with requested IDs only.
        """
        if not neutron:
            neutron = get_client(context)

        if net_ids:
            # If user has specified to attach instance only to specific
            # networks then only add these to **search_opts. This search will
            # also include 'shared' networks.
            search_opts = {'id': net_ids}
            nets = neutron.list_networks(**search_opts).get('networks', [])
        else:
            # (1) Retrieve non-public network list owned by the tenant.
            search_opts = {'tenant_id': project_id, 'shared': False}
            nets = neutron.list_networks(**search_opts).get('networks', [])
            # (2) Retrieve public network list.
            search_opts = {'shared': True}
            nets += neutron.list_networks(**search_opts).get('networks', [])

        _ensure_requested_network_ordering(
            lambda x: x['id'],
            nets,
            net_ids)

        return nets

    def _create_port(self, port_client, instance, network_id, port_req_body,
                     fixed_ip=None, security_group_ids=None,
                     available_macs=None, dhcp_opts=None):
        """Attempts to create a port for the instance on the given network.

        :param port_client: The client to use to create the port.
        :param instance: Create the port for the given instance.
        :param network_id: Create the port on the given network.
        :param port_req_body: Pre-populated port request. Should have the
            device_id, device_owner, and any required neutron extension values.
        :param fixed_ip: Optional fixed IP to use from the given network.
        :param security_group_ids: Optional list of security group IDs to
            apply to the port.
        :param available_macs: Optional set of available MAC addresses,
            from which one will be used at random.
        :param dhcp_opts: Optional DHCP options.
        :returns: ID of the created port.
        :raises PortLimitExceeded: If neutron fails with an OverQuota error.
        :raises NoMoreFixedIps: If neutron fails with
            IpAddressGenerationFailure error.
        :raises: PortBindingFailed: If port binding failed.
        """
        try:
            if fixed_ip:
                port_req_body['port']['fixed_ips'] = [
                    {'ip_address': str(fixed_ip)}]
            port_req_body['port']['network_id'] = network_id
            port_req_body['port']['admin_state_up'] = True
            port_req_body['port']['tenant_id'] = instance.project_id
            if security_group_ids:
                port_req_body['port']['security_groups'] = security_group_ids
            if available_macs is not None:
                if not available_macs:
                    raise exception.PortNotFree(
                        instance=instance.uuid)
                mac_address = available_macs.pop()
                port_req_body['port']['mac_address'] = mac_address
            if dhcp_opts is not None:
                port_req_body['port']['extra_dhcp_opts'] = dhcp_opts
            port = port_client.create_port(port_req_body)
            port_id = port['port']['id']
            if (port['port'].get('binding:vif_type') ==
                network_model.VIF_TYPE_BINDING_FAILED):
                port_client.delete_port(port_id)
                raise exception.PortBindingFailed(port_id=port_id)
            LOG.debug('Successfully created port: %s', port_id,
                      instance=instance)
            return port_id
        except neutron_client_exc.InvalidIpForNetworkClient:
            LOG.warning(_LW('Neutron error: %(ip)s is not a valid IP address '
                            'for network %(network_id)s.'),
                        {'ip': fixed_ip, 'network_id': network_id},
                        instance=instance)
            msg = (_('Fixed IP %(ip)s is not a valid ip address for '
                     'network %(network_id)s.') %
                   {'ip': fixed_ip, 'network_id': network_id})
            raise exception.InvalidInput(reason=msg)
        except neutron_client_exc.IpAddressInUseClient:
            LOG.warning(_LW('Neutron error: Fixed IP %s is '
                            'already in use.'), fixed_ip, instance=instance)
            msg = _("Fixed IP %s is already in use.") % fixed_ip
            raise exception.FixedIpAlreadyInUse(message=msg)
        except neutron_client_exc.OverQuotaClient:
            LOG.warning(_LW(
                'Neutron error: Port quota exceeded in tenant: %s'),
                port_req_body['port']['tenant_id'], instance=instance)
            raise exception.PortLimitExceeded()
        except neutron_client_exc.IpAddressGenerationFailureClient:
            LOG.warning(_LW('Neutron error: No more fixed IPs in network: %s'),
                        network_id, instance=instance)
            raise exception.NoMoreFixedIps(net=network_id)
        except neutron_client_exc.MacAddressInUseClient:
            LOG.warning(_LW('Neutron error: MAC address %(mac)s is already '
                            'in use on network %(network)s.'),
                        {'mac': mac_address, 'network': network_id},
                        instance=instance)
            raise exception.PortInUse(port_id=mac_address)
        except neutron_client_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Neutron error creating port on network %s'),
                              network_id, instance=instance)

    def _check_external_network_attach(self, context, nets):
        """Check if attaching to external network is permitted."""
        if not soft_external_network_attach_authorize(context):
            for net in nets:
                # Perform this check here rather than in validate_networks to
                # ensure the check is performed every time
                # allocate_for_instance is invoked
                if net.get('router:external') and not net.get('shared'):
                    raise exception.ExternalNetworkAttachForbidden(
                        network_uuid=net['id'])

    def _unbind_ports(self, context, ports,
                      neutron, port_client=None):
        """Unbind the given ports by clearing their device_id and
        device_owner.

        :param context: The request context.
        :param ports: list of port IDs.
        :param neutron: neutron client for the current context.
        :param port_client: The client with appropriate karma for
            updating the ports.
        """
        port_binding = self._has_port_binding_extension(context,
                            refresh_cache=True, neutron=neutron)
        if port_client is None:
            # Requires admin creds to set port bindings
            port_client = (neutron if not port_binding else
                           get_client(context, admin=True))
        for port_id in ports:
            # A port_id is optional in the NetworkRequest object so check here
            # in case the caller forgot to filter the list.
            if port_id is None:
                continue
            port_req_body = {'port': {'device_id': '', 'device_owner': ''}}
            if port_binding:
                port_req_body['port']['binding:host_id'] = None
                port_req_body['port']['binding:profile'] = {}
            try:
                port_client.update_port(port_id, port_req_body)
            except Exception:
                LOG.exception(_LE("Unable to clear device ID "
                                  "for port '%s'"), port_id)

    def _process_requested_networks(self, context, instance, neutron,
                                    requested_networks, hypervisor_macs=None):
        """Processes and validates requested networks for allocation.

        Iterates over the list of NetworkRequest objects, validating the
        request and building sets of ports, networks and MAC addresses to
        use for allocating ports for the instance.

        :param instance: allocate networks on this instance
        :type instance: nova.objects.Instance
        :param neutron: neutron client session
        :type neutron: neutronclient.v2_0.client.Client
        :param requested_networks: list of NetworkRequests
        :type requested_networks: nova.objects.NetworkRequestList
        :param hypervisor_macs: None or a set of MAC addresses that the
            instance should use. hypervisor_macs are supplied by the hypervisor
            driver (contrast with requested_networks which is user supplied).
            NB: NeutronV2 currently assigns hypervisor supplied MAC addresses
            to arbitrary networks, which requires openflow switches to
            function correctly if more than one network is being used with
            the bare metal hypervisor (which is the only one known to limit
            MAC addresses).
        :type hypervisor_macs: set
        :returns: tuple of:
            - ports: dict mapping of port id to port dict
            - net_ids: list of requested network ids
            - ordered_networks: list of nova.objects.NetworkRequest objects
                for requested networks (either via explicit network request
                or the network for an explicit port request)
            - available_macs: set of available MAC addresses to use if creating
                a port later; this is the set of hypervisor_macs after removing
                any MAC addresses from explicitly requested ports.
        :raises nova.exception.PortNotFound: If a requested port is not found
            in Neutron.
        :raises nova.exception.PortNotUsable: If a requested port is not owned
            by the same tenant that the instance is created under. This error
            can also be raised if hypervisor_macs is not None and a requested
            port's MAC address is not in that set.
        :raises nova.exception.PortInUse: If a requested port is already
            attached to another instance.
        :raises nova.exception.PortNotUsableDNS: If a requested port has a
            value assigned to its dns_name attribute.
        """

        available_macs = None
        if hypervisor_macs is not None:
            # Make a copy we can mutate: records macs that have not been used
            # to create a port on a network. If we find a mac with a
            # pre-allocated port we also remove it from this set.
            available_macs = set(hypervisor_macs)

        ports = {}
        net_ids = []
        ordered_networks = []
        if requested_networks:
            for request in requested_networks:

                # Process a request to use a pre-existing neutron port.
                if request.port_id:
                    # Make sure the port exists.
                    port = self._show_port(context, request.port_id,
                                           neutron_client=neutron)
                    # Make sure the instance has access to the port.
                    if port['tenant_id'] != instance.project_id:
                        raise exception.PortNotUsable(port_id=request.port_id,
                                                      instance=instance.uuid)

                    # Make sure the port isn't already attached to another
                    # instance.
                    if port.get('device_id'):
                        raise exception.PortInUse(port_id=request.port_id)

                    # Make sure that if the user assigned a value to the port's
                    # dns_name attribute, it is equal to the instance's
                    # hostname
                    if port.get('dns_name'):
                        if port['dns_name'] != instance.hostname:
                            raise exception.PortNotUsableDNS(
                                port_id=request.port_id,
                                instance=instance.uuid, value=port['dns_name'],
                                hostname=instance.hostname)

                    # Make sure the port is usable
                    if (port.get('binding:vif_type') ==
                        network_model.VIF_TYPE_BINDING_FAILED):
                        raise exception.PortBindingFailed(
                            port_id=request.port_id)

                    if hypervisor_macs is not None:
                        if port['mac_address'] not in hypervisor_macs:
                            LOG.debug("Port %(port)s mac address %(mac)s is "
                                      "not in the set of hypervisor macs: "
                                      "%(hyper_macs)s",
                                      {'port': request.port_id,
                                       'mac': port['mac_address'],
                                       'hyper_macs': hypervisor_macs},
                                      instance=instance)
                            raise exception.PortNotUsable(
                                port_id=request.port_id,
                                instance=instance.uuid)
                        # Don't try to use this MAC if we need to create a
                        # port on the fly later. Identical MACs may be
                        # configured by users into multiple ports so we
                        # discard rather than popping.
                        available_macs.discard(port['mac_address'])

                    # If requesting a specific port, automatically process
                    # the network for that port as if it were explicitly
                    # requested.
                    request.network_id = port['network_id']
                    ports[request.port_id] = port

                # Process a request to use a specific neutron network.
                if request.network_id:
                    net_ids.append(request.network_id)
                    ordered_networks.append(request)

        return ports, net_ids, ordered_networks, available_macs

    def _process_security_groups(self, instance, neutron, security_groups):
        """Processes and validates requested security groups for allocation.

        Iterates over the list of requested security groups, validating the
        request and filtering out the list of security group IDs to use for
        port allocation.

        :param instance: allocate networks on this instance
        :type instance: nova.objects.Instance
        :param neutron: neutron client session
        :type neutron: neutronclient.v2_0.client.Client
        :param security_groups: list of requested security group name or IDs
            to use when allocating new ports for the instance
        :return: list of security group IDs to use when allocating new ports
        :raises nova.exception.NoUniqueMatch: If multiple security groups
            are requested with the same name.
        :raises nova.exception.SecurityGroupNotFound: If a requested security
            group is not in the tenant-filtered list of available security
            groups in Neutron.
        """
        security_group_ids = []
        # TODO(arosen) Should optimize more to do direct query for security
        # group if len(security_groups) == 1
        if len(security_groups):
            search_opts = {'tenant_id': instance.project_id}
            user_security_groups = neutron.list_security_groups(
                **search_opts).get('security_groups')

            for security_group in security_groups:
                name_match = None
                uuid_match = None
                for user_security_group in user_security_groups:
                    if user_security_group['name'] == security_group:
                        # If there was a name match in a previous iteration
                        # of the loop, we have a conflict.
                        if name_match:
                            raise exception.NoUniqueMatch(
                                _("Multiple security groups found matching"
                                  " '%s'. Use an ID to be more specific.") %
                                   security_group)

                        name_match = user_security_group['id']

                    if user_security_group['id'] == security_group:
                        uuid_match = user_security_group['id']

                # If a user names the security group the same as
                # another's security groups uuid, the name takes priority.
                if name_match:
                    security_group_ids.append(name_match)
                elif uuid_match:
                    security_group_ids.append(uuid_match)
                else:
                    raise exception.SecurityGroupNotFound(
                        security_group_id=security_group)

        return security_group_ids

    def allocate_for_instance(self, context, instance, **kwargs):
        """Allocate network resources for the instance.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param requested_networks: optional value containing
            network_id, fixed_ip, and port_id
        :param security_groups: security groups to allocate for instance
        :param macs: None or a set of MAC addresses that the instance
            should use. macs is supplied by the hypervisor driver (contrast
            with requested_networks which is user supplied).
            NB: NeutronV2 currently assigns hypervisor supplied MAC addresses
            to arbitrary networks, which requires openflow switches to
            function correctly if more than one network is being used with
            the bare metal hypervisor (which is the only one known to limit
            MAC addresses).
        :param dhcp_options: None or a set of key/value pairs that should
            determine the DHCP BOOTP response, eg. for PXE booting an instance
            configured with the baremetal hypervisor. It is expected that these
            are already formatted for the neutron v2 api.
            See nova/virt/driver.py:dhcp_options_for_instance for an example.
        :param bind_host_id: the host ID to attach to the ports being created.
        """
        hypervisor_macs = kwargs.get('macs', None)

        # The neutron client and port_client (either the admin context or
        # tenant context) are read here. The reason for this is that there are
        # a number of different calls for the instance allocation.
        # We do not want to create a new neutron session for each of these
        # calls.
        neutron = get_client(context)
        # Requires admin creds to set port bindings
        port_client = (neutron if not
                       self._has_port_binding_extension(context,
                           refresh_cache=True, neutron=neutron) else
                       get_client(context, admin=True))
        # Store the admin client - this is used later
        admin_client = port_client if neutron != port_client else None
        LOG.debug('allocate_for_instance()', instance=instance)
        if not instance.project_id:
            msg = _('empty project id for instance %s')
            raise exception.InvalidInput(
                reason=msg % instance.uuid)
        requested_networks = kwargs.get('requested_networks')
        dhcp_opts = kwargs.get('dhcp_options', None)
        bind_host_id = kwargs.get('bind_host_id')
        ports, net_ids, ordered_networks, available_macs = (
            self._process_requested_networks(context,
                instance, neutron, requested_networks, hypervisor_macs))

        nets = self._get_available_networks(context, instance.project_id,
                                            net_ids, neutron=neutron)
        if not nets:
            # NOTE(chaochin): If user specifies a network id and the network
            # can not be found, raise NetworkNotFound error.
            if requested_networks:
                for request in requested_networks:
                    if not request.port_id and request.network_id:
                        raise exception.NetworkNotFound(
                            network_id=request.network_id)
            else:
                LOG.debug("No network configured", instance=instance)
                return network_model.NetworkInfo([])

        # if this function is directly called without a requested_network param
        # or if it is indirectly called through allocate_port_for_instance()
        # with None params=(network_id=None, requested_ip=None, port_id=None,
        # pci_request_id=None):
        if (not requested_networks
            or requested_networks.is_single_unspecified):
            # If no networks were requested and none are available, consider
            # it a bad request.
            if not nets:
                raise exception.InterfaceAttachFailedNoNetwork(
                    project_id=instance.project_id)
            # bug/1267723 - if no network is requested and more
            # than one is available then raise NetworkAmbiguous Exception
            if len(nets) > 1:
                msg = _("Multiple possible networks found, use a Network "
                         "ID to be more specific.")
                raise exception.NetworkAmbiguous(msg)
            ordered_networks.append(
                objects.NetworkRequest(network_id=nets[0]['id']))

        # NOTE(melwitt): check external net attach permission after the
        #                check for ambiguity, there could be another
        #                available net which is permitted bug/1364344
        self._check_external_network_attach(context, nets)

        security_groups = kwargs.get('security_groups', [])
        security_group_ids = self._process_security_groups(
                                    instance, neutron, security_groups)

        preexisting_port_ids = []
        created_port_ids = []
        ports_in_requested_order = []
        nets_in_requested_order = []
        for request in ordered_networks:
            # Network lookup for available network_id
            network = None
            for net in nets:
                if net['id'] == request.network_id:
                    network = net
                    break
            # if network_id did not pass validate_networks() and not available
            # here then skip it safely not continuing with a None Network
            else:
                continue

            nets_in_requested_order.append(network)
            # If security groups are requested on an instance then the
            # network must has a subnet associated with it. Some plugins
            # implement the port-security extension which requires
            # 'port_security_enabled' to be True for security groups.
            # That is why True is returned if 'port_security_enabled'
            # is not found.
            if (security_groups and not (
                    network['subnets']
                    and network.get('port_security_enabled', True))):

                raise exception.SecurityGroupCannotBeApplied()
            zone = 'compute:%s' % instance.availability_zone
            port_req_body = {'port': {'device_id': instance.uuid,
                                      'device_owner': zone}}
            try:
                self._populate_neutron_extension_values(
                    context, instance, request.pci_request_id, port_req_body,
                    network=network, neutron=neutron,
                    bind_host_id=bind_host_id)
                self._populate_mac_address(instance, request.pci_request_id,
                                           port_req_body)
                if request.port_id:
                    port = ports[request.port_id]
                    port_client.update_port(port['id'], port_req_body)
                    preexisting_port_ids.append(port['id'])
                    ports_in_requested_order.append(port['id'])
                else:
                    created_port = self._create_port(
                            port_client, instance, request.network_id,
                            port_req_body, request.address,
                            security_group_ids, available_macs, dhcp_opts)
                    created_port_ids.append(created_port)
                    ports_in_requested_order.append(created_port)
                self._update_port_dns_name(context, instance, network,
                                           ports_in_requested_order[-1],
                                           neutron)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self._unbind_ports(context,
                                       preexisting_port_ids,
                                       neutron, port_client)
                    self._delete_ports(neutron, instance, created_port_ids)
        nw_info = self.get_instance_nw_info(
            context, instance, networks=nets_in_requested_order,
            port_ids=ports_in_requested_order,
            admin_client=admin_client,
            preexisting_port_ids=preexisting_port_ids,
            update_cells=True)
        # NOTE(danms): Only return info about ports we created in this run.
        # In the initial allocation case, this will be everything we created,
        # and in later runs will only be what was created that time. Thus,
        # this only affects the attach case, not the original use for this
        # method.
        return network_model.NetworkInfo([vif for vif in nw_info
                                          if vif['id'] in created_port_ids +
                                          preexisting_port_ids])

    def _refresh_neutron_extensions_cache(self, context, neutron=None):
        """Refresh the neutron extensions cache when necessary."""
        if (not self.last_neutron_extension_sync or
            ((time.time() - self.last_neutron_extension_sync)
             >= CONF.neutron.extension_sync_interval)):
            if neutron is None:
                neutron = get_client(context)
            extensions_list = neutron.list_extensions()['extensions']
            self.last_neutron_extension_sync = time.time()
            self.extensions.clear()
            self.extensions = {ext['name']: ext for ext in extensions_list}

    def _has_port_binding_extension(self, context, refresh_cache=False,
                                    neutron=None):
        if refresh_cache:
            self._refresh_neutron_extensions_cache(context, neutron=neutron)
        return constants.PORTBINDING_EXT in self.extensions

    @staticmethod
    def _populate_neutron_binding_profile(instance, pci_request_id,
                                          port_req_body):
        """Populate neutron binding:profile.

        Populate it with SR-IOV related information
        """
        if pci_request_id:
            pci_dev = pci_manager.get_instance_pci_devs(
                instance, pci_request_id).pop()
            devspec = pci_whitelist.get_pci_device_devspec(pci_dev)
            profile = {'pci_vendor_info': "%s:%s" % (pci_dev.vendor_id,
                                                     pci_dev.product_id),
                       'pci_slot': pci_dev.address,
                       'physical_network':
                           devspec.get_tags().get('physical_network')
                      }
            port_req_body['port']['binding:profile'] = profile

    @staticmethod
    def _populate_mac_address(instance, pci_request_id, port_req_body):
        """Add the updated MAC address value to the update_port request body.

        Currently this is done only for PF passthrough.
        """
        if pci_request_id is not None:
            pci_devs = pci_manager.get_instance_pci_devs(
                instance, pci_request_id)
            if len(pci_devs) != 1:
                # NOTE(ndipanov): We shouldn't ever get here since
                # InstancePCIRequest instances built from network requests
                # only ever index a single device, which needs to be
                # successfully claimed for this to be called as part of
                # allocate_networks method
                LOG.error(_LE("PCI request %s does not have a "
                              "unique device associated with it. Unable to "
                              "determine MAC address"),
                          pci_request, instance=instance)
                return
            pci_dev = pci_devs[0]
            if pci_dev.dev_type == obj_fields.PciDeviceType.SRIOV_PF:
                try:
                    mac = pci_utils.get_mac_by_pci_address(pci_dev.address)
                except exception.PciDeviceNotFoundById as e:
                    LOG.error(
                        _LE("Could not determine MAC address for %(addr)s, "
                            "error: %(e)s"),
                        {"addr": pci_dev.address, "e": e}, instance=instance)
                else:
                    port_req_body['port']['mac_address'] = mac

    def _populate_neutron_extension_values(self, context, instance,
                                           pci_request_id, port_req_body,
                                           network=None, neutron=None,
                                           bind_host_id=None):
        """Populate neutron extension values for the instance.

        If the extensions loaded contain QOS_QUEUE then pass the rxtx_factor.
        """
        self._refresh_neutron_extensions_cache(context, neutron=neutron)
        if constants.QOS_QUEUE in self.extensions:
            flavor = instance.get_flavor()
            rxtx_factor = flavor.get('rxtx_factor')
            port_req_body['port']['rxtx_factor'] = rxtx_factor
        has_port_binding_extension = (
            self._has_port_binding_extension(context, neutron=neutron))
        if has_port_binding_extension:
            port_req_body['port']['binding:host_id'] = bind_host_id
            self._populate_neutron_binding_profile(instance,
                                                   pci_request_id,
                                                   port_req_body)
        if constants.DNS_INTEGRATION in self.extensions:
            # If the DNS integration extension is enabled in Neutron, most
            # ports will get their dns_name attribute set in the port create or
            # update requests in allocate_for_instance. So we just add the
            # dns_name attribute to the payload of those requests. The
            # exception is when the port binding extension is enabled in
            # Neutron and the port is on a network that has a non-blank
            # dns_domain attribute. This case requires to be processed by
            # method _update_port_dns_name
            if (not has_port_binding_extension
                or not network.get('dns_domain')):
                port_req_body['port']['dns_name'] = instance.hostname

    def _update_port_dns_name(self, context, instance, network, port_id,
                              neutron):
        """Update an instance port dns_name attribute with instance.hostname.

        The dns_name attribute of a port on a network with a non-blank
        dns_domain attribute will be sent to the external DNS service
        (Designate) if DNS integration is enabled in Neutron. This requires the
        assignment of the dns_name to the port to be done with a Neutron client
        using the user's context. allocate_for_instance uses a port with admin
        context if the port binding extensions is enabled in Neutron. In this
        case, we assign in this method the dns_name attribute to the port with
        an additional update request. Only a very small fraction of ports will
        require this additional update request.
        """
        if (constants.DNS_INTEGRATION in self.extensions and
            self._has_port_binding_extension(context) and
            network.get('dns_domain')):
            try:
                port_req_body = {'port': {'dns_name': instance.hostname}}
                neutron.update_port(port_id, port_req_body)
            except neutron_client_exc.BadRequest:
                LOG.warning(_LW('Neutron error: Instance hostname '
                                '%(hostname)s is not a valid DNS name'),
                            {'hostname': instance.hostname}, instance=instance)
                msg = (_('Instance hostname %(hostname)s is not a valid DNS '
                         'name') % {'hostname': instance.hostname})
                raise exception.InvalidInput(reason=msg)

    def _delete_ports(self, neutron, instance, ports, raise_if_fail=False):
        exceptions = []
        for port in ports:
            try:
                neutron.delete_port(port)
            except neutron_client_exc.NeutronClientException as e:
                if e.status_code == 404:
                    LOG.warning(_LW("Port %s does not exist"), port,
                                instance=instance)
                else:
                    exceptions.append(e)
                    LOG.warning(
                        _LW("Failed to delete port %s for instance."),
                        port, instance=instance, exc_info=True)
        if len(exceptions) > 0 and raise_if_fail:
            raise exceptions[0]

    def deallocate_for_instance(self, context, instance, **kwargs):
        """Deallocate all network resources related to the instance."""
        LOG.debug('deallocate_for_instance()', instance=instance)
        search_opts = {'device_id': instance.uuid}
        neutron = get_client(context)
        data = neutron.list_ports(**search_opts)
        ports = [port['id'] for port in data.get('ports', [])]

        requested_networks = kwargs.get('requested_networks') or []
        # NOTE(danms): Temporary and transitional
        if isinstance(requested_networks, objects.NetworkRequestList):
            requested_networks = requested_networks.as_tuples()
        ports_to_skip = set([port_id for nets, fips, port_id, pci_request_id
                             in requested_networks])
        # NOTE(boden): requested_networks only passed in when deallocating
        # from a failed build / spawn call. Therefore we need to include
        # preexisting ports when deallocating from a standard delete op
        # in which case requested_networks is not provided.
        ports_to_skip |= set(self._get_preexisting_port_ids(instance))
        ports = set(ports) - ports_to_skip

        # Reset device_id and device_owner for the ports that are skipped
        self._unbind_ports(context, ports_to_skip, neutron)
        # Delete the rest of the ports
        self._delete_ports(neutron, instance, ports, raise_if_fail=True)

        # NOTE(arosen): This clears out the network_cache only if the instance
        # hasn't already been deleted. This is needed when an instance fails to
        # launch and is rescheduled onto another compute node. If the instance
        # has already been deleted this call does nothing.
        base_api.update_instance_cache_with_nw_info(self, context, instance,
                                            network_model.NetworkInfo([]))

    def allocate_port_for_instance(self, context, instance, port_id,
                                   network_id=None, requested_ip=None,
                                   bind_host_id=None):
        """Allocate a port for the instance."""
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=network_id,
                                            address=requested_ip,
                                            port_id=port_id,
                                            pci_request_id=None)])
        return self.allocate_for_instance(context, instance,
                requested_networks=requested_networks,
                bind_host_id=bind_host_id)

    def deallocate_port_for_instance(self, context, instance, port_id):
        """Remove a specified port from the instance.

        Return network information for the instance
        """
        neutron = get_client(context)
        preexisting_ports = self._get_preexisting_port_ids(instance)
        if port_id in preexisting_ports:
            self._unbind_ports(context, [port_id], neutron)
        else:
            self._delete_ports(neutron, instance, [port_id],
                               raise_if_fail=True)
        return self.get_instance_nw_info(context, instance)

    def list_ports(self, context, **search_opts):
        """List ports for the client based on search options."""
        return get_client(context).list_ports(**search_opts)

    def show_port(self, context, port_id):
        """Return the port for the client given the port id.

        :param context: Request context.
        :param port_id: The id of port to be queried.
        :returns: A dict containing port data keyed by 'port', e.g.

        ::

            {'port': {'port_id': 'abcd',
                      'fixed_ip_address': '1.2.3.4'}}
        """
        return dict(port=self._show_port(context, port_id))

    def _show_port(self, context, port_id, neutron_client=None, fields=None):
        """Return the port for the client given the port id.

        :param context: Request context.
        :param port_id: The id of port to be queried.
        :param neutron_client: A neutron client.
        :param fields: The condition fields to query port data.
        :returns: A dict of port data.
                  e.g. {'port_id': 'abcd', 'fixed_ip_address': '1.2.3.4'}
        """
        if not neutron_client:
            neutron_client = get_client(context)
        try:
            if fields:
                result = neutron_client.show_port(port_id, fields=fields)
            else:
                result = neutron_client.show_port(port_id)
            return result.get('port')
        except neutron_client_exc.PortNotFoundClient:
            raise exception.PortNotFound(port_id=port_id)
        except neutron_client_exc.Unauthorized:
            raise exception.Forbidden()
        except neutron_client_exc.NeutronClientException as exc:
            msg = (_("Failed to access port %(port_id)s: %(reason)s") %
                   {'port_id': port_id, 'reason': exc})
            raise exception.NovaException(message=msg)

    def _get_instance_nw_info(self, context, instance, networks=None,
                              port_ids=None, admin_client=None,
                              preexisting_port_ids=None, **kwargs):
        # NOTE(danms): This is an inner method intended to be called
        # by other code that updates instance nwinfo. It *must* be
        # called with the refresh_cache-%(instance_uuid) lock held!
        LOG.debug('_get_instance_nw_info()', instance=instance)
        # Ensure that we have an up to date copy of the instance info cache.
        # Otherwise multiple requests could collide and cause cache
        # corruption.
        compute_utils.refresh_info_cache_for_instance(context, instance)
        nw_info = self._build_network_info_model(context, instance, networks,
                                                 port_ids, admin_client,
                                                 preexisting_port_ids)
        return network_model.NetworkInfo.hydrate(nw_info)

    def _gather_port_ids_and_networks(self, context, instance, networks=None,
                                      port_ids=None):
        """Return an instance's complete list of port_ids and networks."""

        if ((networks is None and port_ids is not None) or
            (port_ids is None and networks is not None)):
            message = _("This method needs to be called with either "
                        "networks=None and port_ids=None or port_ids and "
                        "networks as not none.")
            raise exception.NovaException(message=message)

        ifaces = compute_utils.get_nw_info_for_instance(instance)
        # This code path is only done when refreshing the network_cache
        if port_ids is None:
            port_ids = [iface['id'] for iface in ifaces]
            net_ids = [iface['network']['id'] for iface in ifaces]

        if networks is None:
            networks = self._get_available_networks(context,
                                                    instance.project_id,
                                                    net_ids)
        # an interface was added/removed from instance.
        else:

            # Prepare the network ids list for validation purposes
            networks_ids = [network['id'] for network in networks]

            # Validate that interface networks doesn't exist in networks.
            # Though this issue can and should be solved in methods
            # that prepare the networks list, this method should have this
            # ignore-duplicate-networks/port-ids mechanism to reduce the
            # probability of failing to boot the VM.
            networks = networks + [
                {'id': iface['network']['id'],
                 'name': iface['network']['label'],
                 'tenant_id': iface['network']['meta']['tenant_id']}
                for iface in ifaces
                if _is_not_duplicate(iface['network']['id'],
                                     networks_ids,
                                     "networks",
                                     instance)]

            # Include existing interfaces so they are not removed from the db.
            # Validate that the interface id is not in the port_ids
            port_ids = [iface['id'] for iface in ifaces
                        if _is_not_duplicate(iface['id'],
                                             port_ids,
                                             "port_ids",
                                             instance)] + port_ids

        return networks, port_ids

    @base_api.refresh_cache
    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Add a fixed IP to the instance from specified network."""
        neutron = get_client(context)
        search_opts = {'network_id': network_id}
        data = neutron.list_subnets(**search_opts)
        ipam_subnets = data.get('subnets', [])
        if not ipam_subnets:
            raise exception.NetworkNotFoundForInstance(
                instance_id=instance.uuid)

        zone = 'compute:%s' % instance.availability_zone
        search_opts = {'device_id': instance.uuid,
                       'device_owner': zone,
                       'network_id': network_id}
        data = neutron.list_ports(**search_opts)
        ports = data['ports']
        for p in ports:
            for subnet in ipam_subnets:
                fixed_ips = p['fixed_ips']
                fixed_ips.append({'subnet_id': subnet['id']})
                port_req_body = {'port': {'fixed_ips': fixed_ips}}
                try:
                    neutron.update_port(p['id'], port_req_body)
                    return self._get_instance_nw_info(context, instance)
                except Exception as ex:
                    msg = ("Unable to update port %(portid)s on subnet "
                           "%(subnet_id)s with failure: %(exception)s")
                    LOG.debug(msg, {'portid': p['id'],
                                    'subnet_id': subnet['id'],
                                    'exception': ex}, instance=instance)

        raise exception.NetworkNotFoundForInstance(
                instance_id=instance.uuid)

    @base_api.refresh_cache
    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Remove a fixed IP from the instance."""
        neutron = get_client(context)
        zone = 'compute:%s' % instance.availability_zone
        search_opts = {'device_id': instance.uuid,
                       'device_owner': zone,
                       'fixed_ips': 'ip_address=%s' % address}
        data = neutron.list_ports(**search_opts)
        ports = data['ports']
        for p in ports:
            fixed_ips = p['fixed_ips']
            new_fixed_ips = []
            for fixed_ip in fixed_ips:
                if fixed_ip['ip_address'] != address:
                    new_fixed_ips.append(fixed_ip)
            port_req_body = {'port': {'fixed_ips': new_fixed_ips}}
            try:
                neutron.update_port(p['id'], port_req_body)
            except Exception as ex:
                msg = ("Unable to update port %(portid)s with"
                       " failure: %(exception)s")
                LOG.debug(msg, {'portid': p['id'], 'exception': ex},
                          instance=instance)
            return self._get_instance_nw_info(context, instance)

        raise exception.FixedIpNotFoundForSpecificInstance(
                instance_uuid=instance.uuid, ip=address)

    def _get_port_vnic_info(self, context, neutron, port_id):
        """Retrieve port vnic info

        Invoked with a valid port_id.
        Return vnic type and the attached physical network name.
        """
        phynet_name = None
        port = self._show_port(context, port_id, neutron_client=neutron,
                               fields=['binding:vnic_type', 'network_id'])
        vnic_type = port.get('binding:vnic_type',
                             network_model.VNIC_TYPE_NORMAL)
        if vnic_type in network_model.VNIC_TYPES_SRIOV:
            net_id = port['network_id']
            net = neutron.show_network(net_id,
                fields='provider:physical_network').get('network')
            phynet_name = net.get('provider:physical_network')
        return vnic_type, phynet_name

    def create_pci_requests_for_sriov_ports(self, context, pci_requests,
                                            requested_networks):
        """Check requested networks for any SR-IOV port request.

        Create a PCI request object for each SR-IOV port, and add it to the
        pci_requests object that contains a list of PCI request object.
        """
        if not requested_networks:
            return

        neutron = get_client(context, admin=True)
        for request_net in requested_networks:
            phynet_name = None
            vnic_type = network_model.VNIC_TYPE_NORMAL

            if request_net.port_id:
                vnic_type, phynet_name = self._get_port_vnic_info(
                    context, neutron, request_net.port_id)
            pci_request_id = None
            if vnic_type in network_model.VNIC_TYPES_SRIOV:
                spec = {pci_request.PCI_NET_TAG: phynet_name}
                dev_type = pci_request.DEVICE_TYPE_FOR_VNIC_TYPE.get(vnic_type)
                if dev_type:
                    spec[pci_request.PCI_DEVICE_TYPE_TAG] = dev_type
                request = objects.InstancePCIRequest(
                    count=1,
                    spec=[spec],
                    request_id=str(uuid.uuid4()))
                pci_requests.requests.append(request)
                pci_request_id = request.request_id

            # Add pci_request_id into the requested network
            request_net.pci_request_id = pci_request_id

    def _ports_needed_per_instance(self, context, neutron, requested_networks):
        ports_needed_per_instance = 0
        if requested_networks is None or len(requested_networks) == 0:
            nets = self._get_available_networks(context, context.project_id,
                                                neutron=neutron)
            if len(nets) > 1:
                # Attaching to more than one network by default doesn't
                # make sense, as the order will be arbitrary and the guest OS
                # won't know which to configure
                msg = _("Multiple possible networks found, use a Network "
                         "ID to be more specific.")
                raise exception.NetworkAmbiguous(msg)
            else:
                ports_needed_per_instance = 1
        else:
            net_ids_requested = []

            # TODO(danms): Remove me when all callers pass an object
            if isinstance(requested_networks[0], tuple):
                requested_networks = objects.NetworkRequestList(
                    objects=[objects.NetworkRequest.from_tuple(t)
                             for t in requested_networks])

            for request in requested_networks:
                if request.port_id:
                    port = self._show_port(context, request.port_id,
                                           neutron_client=neutron)
                    if port.get('device_id', None):
                        raise exception.PortInUse(port_id=request.port_id)
                    if not port.get('fixed_ips'):
                        raise exception.PortRequiresFixedIP(
                            port_id=request.port_id)
                    request.network_id = port['network_id']
                else:
                    ports_needed_per_instance += 1
                    net_ids_requested.append(request.network_id)

                    # NOTE(jecarey) There is currently a race condition.
                    # That is, if you have more than one request for a specific
                    # fixed IP at the same time then only one will be allocated
                    # the ip. The fixed IP will be allocated to only one of the
                    # instances that will run. The second instance will fail on
                    # spawn. That instance will go into error state.
                    # TODO(jecarey) Need to address this race condition once we
                    # have the ability to update mac addresses in Neutron.
                    if request.address:
                        # TODO(jecarey) Need to look at consolidating list_port
                        # calls once able to OR filters.
                        search_opts = {'network_id': request.network_id,
                                       'fixed_ips': 'ip_address=%s' % (
                                           request.address),
                                       'fields': 'device_id'}
                        existing_ports = neutron.list_ports(
                                                    **search_opts)['ports']
                        if existing_ports:
                            i_uuid = existing_ports[0]['device_id']
                            raise exception.FixedIpAlreadyInUse(
                                                    address=request.address,
                                                    instance_uuid=i_uuid)

            # Now check to see if all requested networks exist
            if net_ids_requested:
                nets = self._get_available_networks(
                    context, context.project_id, net_ids_requested,
                    neutron=neutron)

                for net in nets:
                    if not net.get('subnets'):
                        raise exception.NetworkRequiresSubnet(
                            network_uuid=net['id'])

                if len(nets) != len(net_ids_requested):
                    requested_netid_set = set(net_ids_requested)
                    returned_netid_set = set([net['id'] for net in nets])
                    lostid_set = requested_netid_set - returned_netid_set
                    if lostid_set:
                        id_str = ''
                        for _id in lostid_set:
                            id_str = id_str and id_str + ', ' + _id or _id
                        raise exception.NetworkNotFound(network_id=id_str)
        return ports_needed_per_instance

    def validate_networks(self, context, requested_networks, num_instances):
        """Validate that the tenant can use the requested networks.

        Return the number of instances than can be successfully allocated
        with the requested network configuration.
        """
        LOG.debug('validate_networks() for %s', requested_networks)

        neutron = get_client(context)
        ports_needed_per_instance = self._ports_needed_per_instance(
            context, neutron, requested_networks)

        # Note(PhilD): Ideally Nova would create all required ports as part of
        # network validation, but port creation requires some details
        # from the hypervisor.  So we just check the quota and return
        # how many of the requested number of instances can be created
        if ports_needed_per_instance:
            quotas = neutron.show_quota(tenant_id=context.project_id)['quota']
            if quotas.get('port', -1) == -1:
                # Unlimited Port Quota
                return num_instances

            # We only need the port count so only ask for ids back.
            params = dict(tenant_id=context.project_id, fields=['id'])
            ports = neutron.list_ports(**params)['ports']
            free_ports = quotas.get('port') - len(ports)
            if free_ports < 0:
                msg = (_("The number of defined ports: %(ports)d "
                         "is over the limit: %(quota)d") %
                       {'ports': len(ports),
                        'quota': quotas.get('port')})
                raise exception.PortLimitExceeded(msg)
            ports_needed = ports_needed_per_instance * num_instances
            if free_ports >= ports_needed:
                return num_instances
            else:
                return free_ports // ports_needed_per_instance
        return num_instances

    def _get_instance_uuids_by_ip(self, context, address):
        """Retrieve instance uuids associated with the given IP address.

        :returns: A list of dicts containing the uuids keyed by 'instance_uuid'
                  e.g. [{'instance_uuid': uuid}, ...]
        """
        search_opts = {"fixed_ips": 'ip_address=%s' % address}
        data = get_client(context).list_ports(**search_opts)
        ports = data.get('ports', [])
        return [{'instance_uuid': port['device_id']} for port in ports
                if port['device_id']]

    def _get_port_id_by_fixed_address(self, client,
                                      instance, address):
        """Return port_id from a fixed address."""
        zone = 'compute:%s' % instance.availability_zone
        search_opts = {'device_id': instance.uuid,
                       'device_owner': zone}
        data = client.list_ports(**search_opts)
        ports = data['ports']
        port_id = None
        for p in ports:
            for ip in p['fixed_ips']:
                if ip['ip_address'] == address:
                    port_id = p['id']
                    break
        if not port_id:
            raise exception.FixedIpNotFoundForAddress(address=address)
        return port_id

    @base_api.refresh_cache
    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associate a floating IP with a fixed IP."""

        # Note(amotoki): 'affect_auto_assigned' is not respected
        # since it is not used anywhere in nova code and I could
        # find why this parameter exists.

        client = get_client(context)
        port_id = self._get_port_id_by_fixed_address(client, instance,
                                                     fixed_address)
        fip = self._get_floating_ip_by_address(client, floating_address)
        param = {'port_id': port_id,
                 'fixed_ip_address': fixed_address}
        client.update_floatingip(fip['id'], {'floatingip': param})

        if fip['port_id']:
            port = self._show_port(context, fip['port_id'],
                                   neutron_client=client)
            orig_instance_uuid = port['device_id']

            msg_dict = dict(address=floating_address,
                            instance_id=orig_instance_uuid)
            LOG.info(_LI('re-assign floating IP %(address)s from '
                         'instance %(instance_id)s'), msg_dict,
                     instance=instance)
            orig_instance = objects.Instance.get_by_uuid(context,
                                                         orig_instance_uuid)

            # purge cached nw info for the original instance
            base_api.update_instance_cache_with_nw_info(self, context,
                                                        orig_instance)

    def get_all(self, context):
        """Get all networks for client."""
        client = get_client(context)
        networks = client.list_networks().get('networks')
        network_objs = []
        for network in networks:
            network_objs.append(objects.Network(context=context,
                                                name=network['name'],
                                                label=network['name'],
                                                uuid=network['id']))
        return objects.NetworkList(context=context,
                                   objects=network_objs)

    def get(self, context, network_uuid):
        """Get specific network for client."""
        client = get_client(context)
        try:
            network = client.show_network(network_uuid).get('network') or {}
        except neutron_client_exc.NetworkNotFoundClient:
            raise exception.NetworkNotFound(network_id=network_uuid)
        net_obj = objects.Network(context=context,
                                  name=network['name'],
                                  label=network['name'],
                                  uuid=network['id'])
        return net_obj

    def delete(self, context, network_uuid):
        """Delete a network for client."""
        raise NotImplementedError()

    def disassociate(self, context, network_uuid):
        """Disassociate a network for client."""
        raise NotImplementedError()

    def associate(self, context, network_uuid, host=base_api.SENTINEL,
                  project=base_api.SENTINEL):
        """Associate a network for client."""
        raise NotImplementedError()

    def get_fixed_ip(self, context, id):
        """Get a fixed IP from the id."""
        raise NotImplementedError()

    def get_fixed_ip_by_address(self, context, address):
        """Return instance uuids given an address."""
        uuid_maps = self._get_instance_uuids_by_ip(context, address)
        if len(uuid_maps) == 1:
            return uuid_maps[0]
        elif not uuid_maps:
            raise exception.FixedIpNotFoundForAddress(address=address)
        else:
            raise exception.FixedIpAssociatedWithMultipleInstances(
                address=address)

    def _setup_net_dict(self, client, network_id):
        if not network_id:
            return {}
        pool = client.show_network(network_id)['network']
        return {pool['id']: pool}

    def _setup_port_dict(self, context, client, port_id):
        if not port_id:
            return {}
        port = self._show_port(context, port_id, neutron_client=client)
        return {port['id']: port}

    def _setup_pools_dict(self, client):
        pools = self._get_floating_ip_pools(client)
        return {i['id']: i for i in pools}

    def _setup_ports_dict(self, client, project_id=None):
        search_opts = {'tenant_id': project_id} if project_id else {}
        ports = client.list_ports(**search_opts)['ports']
        return {p['id']: p for p in ports}

    def get_floating_ip(self, context, id):
        """Return floating IP object given the floating IP id."""
        client = get_client(context)
        try:
            fip = client.show_floatingip(id)['floatingip']
        except neutron_client_exc.NeutronClientException as e:
            if e.status_code == 404:
                raise exception.FloatingIpNotFound(id=id)
            else:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE('Unable to access floating IP %s'), id)
        pool_dict = self._setup_net_dict(client,
                                         fip['floating_network_id'])
        port_dict = self._setup_port_dict(context, client, fip['port_id'])
        return self._format_floating_ip_model(fip, pool_dict, port_dict)

    def _get_floating_ip_pools(self, client, project_id=None):
        search_opts = {constants.NET_EXTERNAL: True}
        if project_id:
            search_opts.update({'tenant_id': project_id})
        data = client.list_networks(**search_opts)
        return data['networks']

    def get_floating_ip_pools(self, context):
        """Return floating IP pool names."""
        client = get_client(context)
        pools = self._get_floating_ip_pools(client)
        # Note(salv-orlando): Return a list of names to be consistent with
        # nova.network.api.get_floating_ip_pools
        return [n['name'] or n['id'] for n in pools]

    def _format_floating_ip_model(self, fip, pool_dict, port_dict):
        pool = pool_dict[fip['floating_network_id']]
        result = {'id': fip['id'],
                  'address': fip['floating_ip_address'],
                  'pool': pool['name'] or pool['id'],
                  'project_id': fip['tenant_id'],
                  # In Neutron v2, an exact fixed_ip_id does not exist.
                  'fixed_ip_id': fip['port_id'],
                  }
        # In Neutron v2 API fixed_ip_address and instance uuid
        # (= device_id) are known here, so pass it as a result.
        result['fixed_ip'] = {'address': fip['fixed_ip_address']}
        if fip['port_id']:
            instance_uuid = port_dict[fip['port_id']]['device_id']
            result['instance'] = {'uuid': instance_uuid}
            # TODO(mriedem): remove this workaround once the get_floating_ip*
            # API methods are converted to use nova objects.
            result['fixed_ip']['instance_uuid'] = instance_uuid
        else:
            result['instance'] = None
        return result

    def get_floating_ip_by_address(self, context, address):
        """Return a floating IP given an address."""
        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        pool_dict = self._setup_net_dict(client,
                                         fip['floating_network_id'])
        port_dict = self._setup_port_dict(context, client, fip['port_id'])
        return self._format_floating_ip_model(fip, pool_dict, port_dict)

    def get_floating_ips_by_project(self, context):
        client = get_client(context)
        project_id = context.project_id
        fips = self._safe_get_floating_ips(client, tenant_id=project_id)
        if not fips:
            return []
        pool_dict = self._setup_pools_dict(client)
        port_dict = self._setup_ports_dict(client, project_id)
        return [self._format_floating_ip_model(fip, pool_dict, port_dict)
                for fip in fips]

    def get_instance_id_by_floating_address(self, context, address):
        """Return the instance id a floating IP's fixed IP is allocated to."""
        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        if not fip['port_id']:
            return None
        port = self._show_port(context, fip['port_id'], neutron_client=client)
        return port['device_id']

    def get_vifs_by_instance(self, context, instance):
        raise NotImplementedError()

    def get_vif_by_mac_address(self, context, mac_address):
        raise NotImplementedError()

    def _get_floating_ip_pool_id_by_name_or_id(self, client, name_or_id):
        search_opts = {constants.NET_EXTERNAL: True, 'fields': 'id'}
        if uuidutils.is_uuid_like(name_or_id):
            search_opts.update({'id': name_or_id})
        else:
            search_opts.update({'name': name_or_id})
        data = client.list_networks(**search_opts)
        nets = data['networks']

        if len(nets) == 1:
            return nets[0]['id']
        elif len(nets) == 0:
            raise exception.FloatingIpPoolNotFound()
        else:
            msg = (_("Multiple floating IP pools matches found for name '%s'")
                   % name_or_id)
            raise exception.NovaException(message=msg)

    def allocate_floating_ip(self, context, pool=None):
        """Add a floating IP to a project from a pool."""
        client = get_client(context)
        pool = pool or CONF.default_floating_pool
        pool_id = self._get_floating_ip_pool_id_by_name_or_id(client, pool)

        param = {'floatingip': {'floating_network_id': pool_id}}
        try:
            fip = client.create_floatingip(param)
        except (neutron_client_exc.IpAddressGenerationFailureClient,
                neutron_client_exc.ExternalIpAddressExhaustedClient) as e:
            raise exception.NoMoreFloatingIps(six.text_type(e))
        except neutron_client_exc.OverQuotaClient as e:
            raise exception.FloatingIpLimitExceeded(six.text_type(e))
        except neutron_client_exc.BadRequest as e:
            raise exception.FloatingIpBadRequest(six.text_type(e))

        return fip['floatingip']['floating_ip_address']

    def _safe_get_floating_ips(self, client, **kwargs):
        """Get floating IP gracefully handling 404 from Neutron."""
        try:
            return client.list_floatingips(**kwargs)['floatingips']
        # If a neutron plugin does not implement the L3 API a 404 from
        # list_floatingips will be raised.
        except neutron_client_exc.NotFound:
            return []
        except neutron_client_exc.NeutronClientException as e:
            # bug/1513879 neutron client is currently using
            # NeutronClientException when there is no L3 API
            if e.status_code == 404:
                return []
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Unable to access floating IP for %s'),
                        ', '.join(['%s %s' % (k, v)
                                   for k, v in six.iteritems(kwargs)]))

    def _get_floating_ip_by_address(self, client, address):
        """Get floating IP from floating IP address."""
        if not address:
            raise exception.FloatingIpNotFoundForAddress(address=address)
        fips = self._safe_get_floating_ips(client, floating_ip_address=address)
        if len(fips) == 0:
            raise exception.FloatingIpNotFoundForAddress(address=address)
        elif len(fips) > 1:
            raise exception.FloatingIpMultipleFoundForAddress(address=address)
        return fips[0]

    def _get_floating_ips_by_fixed_and_port(self, client, fixed_ip, port):
        """Get floating IPs from fixed IP and port."""
        return self._safe_get_floating_ips(client, fixed_ip_address=fixed_ip,
                                           port_id=port)

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Remove a floating IP with the given address from a project."""

        # Note(amotoki): We cannot handle a case where multiple pools
        # have overlapping IP address range. In this case we cannot use
        # 'address' as a unique key.
        # This is a limitation of the current nova.

        # Note(amotoki): 'affect_auto_assigned' is not respected
        # since it is not used anywhere in nova code and I could
        # find why this parameter exists.

        self._release_floating_ip(context, address)

    def disassociate_and_release_floating_ip(self, context, instance,
                                           floating_ip):
        """Removes (deallocates) and deletes the floating IP.

        This api call was added to allow this to be done in one operation
        if using neutron.
        """
        self._release_floating_ip(context, floating_ip['address'],
                                  raise_if_associated=False)

    def _release_floating_ip(self, context, address,
                             raise_if_associated=True):
        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)

        if raise_if_associated and fip['port_id']:
            raise exception.FloatingIpAssociated(address=address)
        client.delete_floatingip(fip['id'])

    @base_api.refresh_cache
    def disassociate_floating_ip(self, context, instance, address,
                                 affect_auto_assigned=False):
        """Disassociate a floating IP from the instance."""

        # Note(amotoki): 'affect_auto_assigned' is not respected
        # since it is not used anywhere in nova code and I could
        # find why this parameter exists.

        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        client.update_floatingip(fip['id'], {'floatingip': {'port_id': None}})

    def migrate_instance_start(self, context, instance, migration):
        """Start to migrate the network of an instance."""
        # NOTE(wenjianhn): just pass to make migrate instance doesn't
        # raise for now.
        pass

    def migrate_instance_finish(self, context, instance, migration):
        """Finish migrating the network of an instance."""
        self._update_port_binding_for_instance(context, instance,
                                               migration['dest_compute'])

    def add_network_to_project(self, context, project_id, network_uuid=None):
        """Force add a network to the project."""
        raise NotImplementedError()

    def _nw_info_get_ips(self, client, port):
        network_IPs = []
        for fixed_ip in port['fixed_ips']:
            fixed = network_model.FixedIP(address=fixed_ip['ip_address'])
            floats = self._get_floating_ips_by_fixed_and_port(
                client, fixed_ip['ip_address'], port['id'])
            for ip in floats:
                fip = network_model.IP(address=ip['floating_ip_address'],
                                       type='floating')
                fixed.add_floating_ip(fip)
            network_IPs.append(fixed)
        return network_IPs

    def _nw_info_get_subnets(self, context, port, network_IPs):
        subnets = self._get_subnets_from_port(context, port)
        for subnet in subnets:
            subnet['ips'] = [fixed_ip for fixed_ip in network_IPs
                             if fixed_ip.is_in_subnet(subnet)]
        return subnets

    def _nw_info_build_network(self, port, networks, subnets):
        network_name = None
        network_mtu = None
        for net in networks:
            if port['network_id'] == net['id']:
                network_name = net['name']
                tenant_id = net['tenant_id']
                network_mtu = net.get('mtu')
                break
        else:
            tenant_id = port['tenant_id']
            LOG.warning(_LW("Network %(id)s not matched with the tenants "
                            "network! The ports tenant %(tenant_id)s will be "
                            "used."),
                        {'id': port['network_id'], 'tenant_id': tenant_id})

        bridge = None
        ovs_interfaceid = None
        # Network model metadata
        should_create_bridge = None
        vif_type = port.get('binding:vif_type')
        port_details = port.get('binding:vif_details', {})
        if vif_type == network_model.VIF_TYPE_OVS:
            bridge = port_details.get(network_model.VIF_DETAILS_BRIDGE_NAME,
                                      CONF.neutron.ovs_bridge)
            ovs_interfaceid = port['id']
        elif vif_type == network_model.VIF_TYPE_BRIDGE:
            bridge = port_details.get(network_model.VIF_DETAILS_BRIDGE_NAME,
                                      "brq" + port['network_id'])
            should_create_bridge = True
        elif vif_type == network_model.VIF_TYPE_DVS:
            # The name of the DVS port group will contain the neutron
            # network id
            bridge = port['network_id']
        elif (vif_type == network_model.VIF_TYPE_VHOSTUSER and
         port_details.get(network_model.VIF_DETAILS_VHOSTUSER_OVS_PLUG,
                          False)):
            bridge = port_details.get(network_model.VIF_DETAILS_BRIDGE_NAME,
                                      CONF.neutron.ovs_bridge)
            ovs_interfaceid = port['id']

        # Prune the bridge name if necessary. For the DVS this is not done
        # as the bridge is a '<network-name>-<network-UUID>'.
        if bridge is not None and vif_type != network_model.VIF_TYPE_DVS:
            bridge = bridge[:network_model.NIC_NAME_LEN]

        network = network_model.Network(
            id=port['network_id'],
            bridge=bridge,
            injected=CONF.flat_injected,
            label=network_name,
            tenant_id=tenant_id,
            mtu=network_mtu
            )
        network['subnets'] = subnets
        port_profile = port.get('binding:profile')
        if port_profile:
            physical_network = port_profile.get('physical_network')
            if physical_network:
                network['physical_network'] = physical_network

        if should_create_bridge is not None:
            network['should_create_bridge'] = should_create_bridge
        return network, ovs_interfaceid

    def _get_preexisting_port_ids(self, instance):
        """Retrieve the preexisting ports associated with the given instance.
        These ports were not created by nova and hence should not be
        deallocated upon instance deletion.
        """
        net_info = compute_utils.get_nw_info_for_instance(instance)
        if not net_info:
            LOG.debug('Instance cache missing network info.',
                      instance=instance)
        return [vif['id'] for vif in net_info
                if vif.get('preserve_on_delete')]

    def _build_network_info_model(self, context, instance, networks=None,
                                  port_ids=None, admin_client=None,
                                  preexisting_port_ids=None):
        """Return list of ordered VIFs attached to instance.

        :param context: Request context.
        :param instance: Instance we are returning network info for.
        :param networks: List of networks being attached to an instance.
                         If value is None this value will be populated
                         from the existing cached value.
        :param port_ids: List of port_ids that are being attached to an
                         instance in order of attachment. If value is None
                         this value will be populated from the existing
                         cached value.
        :param admin_client: A neutron client for the admin context.
        :param preexisting_port_ids: List of port_ids that nova didn't
                        allocate and there shouldn't be deleted when
                        an instance is de-allocated. Supplied list will
                        be added to the cached list of preexisting port
                        IDs for this instance.
        """

        search_opts = {'tenant_id': instance.project_id,
                       'device_id': instance.uuid, }
        if admin_client is None:
            client = get_client(context, admin=True)
        else:
            client = admin_client

        data = client.list_ports(**search_opts)

        current_neutron_ports = data.get('ports', [])
        nw_info_refresh = networks is None and port_ids is None
        networks, port_ids = self._gather_port_ids_and_networks(
                context, instance, networks, port_ids)
        nw_info = network_model.NetworkInfo()

        if preexisting_port_ids is None:
            preexisting_port_ids = []
        preexisting_port_ids = set(
            preexisting_port_ids + self._get_preexisting_port_ids(instance))

        current_neutron_port_map = {}
        for current_neutron_port in current_neutron_ports:
            current_neutron_port_map[current_neutron_port['id']] = (
                current_neutron_port)

        for port_id in port_ids:
            current_neutron_port = current_neutron_port_map.get(port_id)
            if current_neutron_port:
                vif_active = False
                if (current_neutron_port['admin_state_up'] is False
                    or current_neutron_port['status'] == 'ACTIVE'):
                    vif_active = True

                network_IPs = self._nw_info_get_ips(client,
                                                    current_neutron_port)
                subnets = self._nw_info_get_subnets(context,
                                                    current_neutron_port,
                                                    network_IPs)

                devname = "tap" + current_neutron_port['id']
                devname = devname[:network_model.NIC_NAME_LEN]

                network, ovs_interfaceid = (
                    self._nw_info_build_network(current_neutron_port,
                                                networks, subnets))
                preserve_on_delete = (current_neutron_port['id'] in
                                      preexisting_port_ids)

                nw_info.append(network_model.VIF(
                    id=current_neutron_port['id'],
                    address=current_neutron_port['mac_address'],
                    network=network,
                    vnic_type=current_neutron_port.get('binding:vnic_type',
                        network_model.VNIC_TYPE_NORMAL),
                    type=current_neutron_port.get('binding:vif_type'),
                    profile=current_neutron_port.get('binding:profile'),
                    details=current_neutron_port.get('binding:vif_details'),
                    ovs_interfaceid=ovs_interfaceid,
                    devname=devname,
                    active=vif_active,
                    preserve_on_delete=preserve_on_delete))

            elif nw_info_refresh:
                LOG.info(_LI('Port %s from network info_cache is no '
                             'longer associated with instance in Neutron. '
                             'Removing from network info_cache.'), port_id,
                         instance=instance)

        return nw_info

    def _get_subnets_from_port(self, context, port):
        """Return the subnets for a given port."""

        fixed_ips = port['fixed_ips']
        # No fixed_ips for the port means there is no subnet associated
        # with the network the port is created on.
        # Since list_subnets(id=[]) returns all subnets visible for the
        # current tenant, returned subnets may contain subnets which is not
        # related to the port. To avoid this, the method returns here.
        if not fixed_ips:
            return []
        search_opts = {'id': [ip['subnet_id'] for ip in fixed_ips]}
        data = get_client(context).list_subnets(**search_opts)
        ipam_subnets = data.get('subnets', [])
        subnets = []

        for subnet in ipam_subnets:
            subnet_dict = {'cidr': subnet['cidr'],
                           'gateway': network_model.IP(
                                address=subnet['gateway_ip'],
                                type='gateway'),
            }

            # attempt to populate DHCP server field
            search_opts = {'network_id': subnet['network_id'],
                           'device_owner': 'network:dhcp'}
            data = get_client(context).list_ports(**search_opts)
            dhcp_ports = data.get('ports', [])
            for p in dhcp_ports:
                for ip_pair in p['fixed_ips']:
                    if ip_pair['subnet_id'] == subnet['id']:
                        subnet_dict['dhcp_server'] = ip_pair['ip_address']
                        break

            subnet_object = network_model.Subnet(**subnet_dict)
            for dns in subnet.get('dns_nameservers', []):
                subnet_object.add_dns(
                    network_model.IP(address=dns, type='dns'))

            for route in subnet.get('host_routes', []):
                subnet_object.add_route(
                    network_model.Route(cidr=route['destination'],
                                        gateway=network_model.IP(
                                            address=route['nexthop'],
                                            type='gateway')))

            subnets.append(subnet_object)
        return subnets

    def get_dns_domains(self, context):
        """Return a list of available dns domains.

        These can be used to create DNS entries for floating IPs.
        """
        raise NotImplementedError()

    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address."""
        raise NotImplementedError()

    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address."""
        raise NotImplementedError()

    def delete_dns_entry(self, context, name, domain):
        """Delete the specified dns entry."""
        raise NotImplementedError()

    def delete_dns_domain(self, context, domain):
        """Delete the specified dns domain."""
        raise NotImplementedError()

    def get_dns_entries_by_address(self, context, address, domain):
        """Get entries for address and domain."""
        raise NotImplementedError()

    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain."""
        raise NotImplementedError()

    def create_private_dns_domain(self, context, domain, availability_zone):
        """Create a private DNS domain with nova availability zone."""
        raise NotImplementedError()

    def create_public_dns_domain(self, context, domain, project=None):
        """Create a private DNS domain with optional nova project."""
        raise NotImplementedError()

    def setup_instance_network_on_host(self, context, instance, host):
        """Setup network for specified instance on host."""
        self._update_port_binding_for_instance(context, instance, host)

    def cleanup_instance_network_on_host(self, context, instance, host):
        """Cleanup network for specified instance on host."""
        pass

    def _update_port_binding_for_instance(self, context, instance, host):
        if not self._has_port_binding_extension(context, refresh_cache=True):
            return
        neutron = get_client(context, admin=True)
        search_opts = {'device_id': instance.uuid,
                       'tenant_id': instance.project_id}
        data = neutron.list_ports(**search_opts)
        ports = data['ports']
        for p in ports:
            # If the host hasn't changed, like in the case of resizing to the
            # same host, there is nothing to do.
            if p.get('binding:host_id') != host:
                try:
                    neutron.update_port(p['id'],
                                        {'port': {'binding:host_id': host}})
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.exception(_LE("Unable to update host of port %s"),
                                      p['id'], instance=instance)

    def update_instance_vnic_index(self, context, instance, vif, index):
        """Update instance vnic index.

        When the 'VNIC index' extension is supported this method will update
        the vnic index of the instance on the port.
        """
        self._refresh_neutron_extensions_cache(context)
        if constants.VNIC_INDEX_EXT in self.extensions:
            neutron = get_client(context)
            port_req_body = {'port': {'vnic_index': index}}
            try:
                neutron.update_port(vif['id'], port_req_body)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE('Unable to update instance VNIC index '
                                      'for port %s.'),
                                  vif['id'], instance=instance)


def _ensure_requested_network_ordering(accessor, unordered, preferred):
    """Sort a list with respect to the preferred network ordering."""
    if preferred:
        unordered.sort(key=lambda i: preferred.index(accessor(i)))

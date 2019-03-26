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

import time

from keystoneauth1 import loading as ks_loading
from neutronclient.common import exceptions as neutron_client_exc
from neutronclient.v2_0 import client as clientv20
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import uuidutils
import six

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
from nova.policies import servers as servers_policies
from nova import profiler
from nova import service_auth

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

_SESSION = None
_ADMIN_AUTH = None

DEFAULT_SECGROUP = 'default'
BINDING_PROFILE = 'binding:profile'
BINDING_HOST_ID = 'binding:host_id'
MIGRATING_ATTR = 'migrating_to'


def reset_state():
    global _ADMIN_AUTH
    global _SESSION

    _ADMIN_AUTH = None
    _SESSION = None


def _load_auth_plugin(conf):
    auth_plugin = ks_loading.load_auth_from_conf_options(conf,
                                    nova.conf.neutron.NEUTRON_GROUP)

    if auth_plugin:
        return auth_plugin

    err_msg = _('Unknown auth type: %s') % conf.neutron.auth_type
    raise neutron_client_exc.Unauthorized(message=err_msg)


def _get_binding_profile(port):
    """Convenience method to get the binding:profile from the port

    The binding:profile in the port is undefined in the networking service
    API and is dependent on backend configuration. This means it could be
    an empty dict, None, or have some values.

    :param port: dict port response body from the networking service API
    :returns: The port binding:profile dict; empty if not set on the port
    """
    return port.get(BINDING_PROFILE, {}) or {}


@profiler.trace_cls("neutron_api")
class ClientWrapper(clientv20.Client):
    """A Neutron client wrapper class.

    Wraps the callable methods, catches Unauthorized,Forbidden from Neutron and
    convert it to a 401,403 for Nova clients.
    """
    def __init__(self, base_client, admin):
        # Expose all attributes from the base_client instance
        self.__dict__ = base_client.__dict__
        self.base_client = base_client
        self.admin = admin

    def __getattribute__(self, name):
        obj = object.__getattribute__(self, name)
        if callable(obj):
            obj = object.__getattribute__(self, 'proxy')(obj)
        return obj

    def proxy(self, obj):
        def wrapper(*args, **kwargs):
            try:
                ret = obj(*args, **kwargs)
            except neutron_client_exc.Unauthorized:
                if not self.admin:
                    # Token is expired so Neutron is raising a
                    # unauthorized exception, we should convert it to
                    # raise a 401 to make client to handle a retry by
                    # regenerating a valid token and trying a new
                    # attempt.
                    raise exception.Unauthorized()
                # In admin context if token is invalid Neutron client
                # should be able to regenerate a valid by using the
                # Neutron admin credential configuration located in
                # nova.conf.
                LOG.error(_LE("Neutron client was not able to generate a "
                              "valid admin token, please verify Neutron "
                              "admin credential located in nova.conf"))
                raise exception.NeutronAdminCredentialConfigurationInvalid()
            except neutron_client_exc.Forbidden as e:
                raise exception.Forbidden(six.text_type(e))
            return ret
        return wrapper


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
            CONF, nova.conf.neutron.NEUTRON_GROUP)

    if admin or (context.is_admin and not context.auth_token):
        if not _ADMIN_AUTH:
            _ADMIN_AUTH = _load_auth_plugin(CONF)
        auth_plugin = _ADMIN_AUTH

    elif context.auth_token:
        auth_plugin = service_auth.get_auth_plugin(context)

    if not auth_plugin:
        # We did not get a user token and we should not be using
        # an admin token so log an error
        raise exception.Unauthorized()

    return ClientWrapper(
        clientv20.Client(session=_SESSION,
                         auth=auth_plugin,
                         endpoint_override=CONF.neutron.url,
                         region_name=CONF.neutron.region_name,
                         global_request_id=context.global_id),
        admin=admin or context.is_admin)


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


def _ensure_no_port_binding_failure(port):
    binding_vif_type = port.get('binding:vif_type')
    if binding_vif_type == network_model.VIF_TYPE_BINDING_FAILED:
        raise exception.PortBindingFailed(port_id=port['id'])


def _filter_hypervisor_macs(instance, ports, hypervisor_macs):
    """Removes macs from set if used by existing ports

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
    :returns a set of available MAC addresses to use if
            creating a port later; this is the set of hypervisor_macs
            after removing any MAC addresses from explicitly
            requested ports.
    """
    if not hypervisor_macs:
        return None

    # Make a copy we can mutate: records macs that have not been used
    # to create a port on a network. If we find a mac with a
    # pre-allocated port we also remove it from this set.
    available_macs = set(hypervisor_macs)
    if not ports:
        return available_macs

    for port in ports.values():
        mac = port['mac_address']
        if mac not in hypervisor_macs:
            LOG.debug("Port %(port)s mac address %(mac)s is "
                      "not in the set of hypervisor macs: "
                      "%(hyper_macs)s. Nova will overwrite "
                      "this with a new mac address.",
                      {'port': port['id'],
                       'mac': mac,
                       'hyper_macs': hypervisor_macs},
                      instance=instance)
        else:
            # Don't try to use this MAC if we need to create a
            # port on the fly later. Identical MACs may be
            # configured by users into multiple ports so we
            # discard rather than popping.
            available_macs.discard(mac)

    return available_macs


class API(base_api.NetworkAPI):
    """API for interacting with the neutron 2.x API."""

    def __init__(self):
        super(API, self).__init__()
        self.last_neutron_extension_sync = None
        self.extensions = {}
        self.pci_whitelist = pci_whitelist.Whitelist(
            CONF.pci.passthrough_whitelist)

    def _update_port_with_migration_profile(
            self, instance, port_id, port_profile, admin_client):
        try:
            updated_port = admin_client.update_port(
                port_id, {'port': {BINDING_PROFILE: port_profile}})
            return updated_port
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Unable to update binding profile "
                              "for port: %(port)s due to failure: %(error)s"),
                          {'port': port_id, 'error': ex},
                          instance=instance)

    def _clear_migration_port_profile(
            self, context, instance, admin_client, ports):
        for p in ports:
            # If the port already has a migration profile and if
            # it is to be torn down, then we need to clean up
            # the migration profile.
            port_profile = _get_binding_profile(p)
            if not port_profile:
                continue
            if MIGRATING_ATTR in port_profile:
                del port_profile[MIGRATING_ATTR]
                LOG.debug("Removing port %s migration profile", p['id'],
                          instance=instance)
                self._update_port_with_migration_profile(
                    instance, p['id'], port_profile, admin_client)

    def _setup_migration_port_profile(
            self, context, instance, host, admin_client, ports):
        # Migrating to a new host
        for p in ports:
            # If the host hasn't changed, there is nothing to do.
            # But if the destination host is different than the
            # current one, please update the port_profile with
            # the 'migrating_to'(MIGRATING_ATTR) key pointing to
            # the given 'host'.
            host_id = p.get(BINDING_HOST_ID)
            if host_id != host:
                port_profile = _get_binding_profile(p)
                port_profile[MIGRATING_ATTR] = host
                self._update_port_with_migration_profile(
                    instance, p['id'], port_profile, admin_client)
                LOG.debug("Port %(port_id)s updated with migration "
                          "profile %(profile_data)s successfully",
                          {'port_id': p['id'],
                           'profile_data': port_profile},
                          instance=instance)

    def setup_networks_on_host(self, context, instance, host=None,
                               teardown=False):
        """Setup or teardown the network structures."""
        if not self._has_port_binding_extension(context, refresh_cache=True):
            return
        # Check if the instance is migrating to a new host.
        port_migrating = host and (instance.host != host)
        # If the port is migrating to a new host or if it is a
        # teardown on the original host, then proceed.
        if port_migrating or teardown:
            search_opts = {'device_id': instance.uuid,
                           'tenant_id': instance.project_id,
                           BINDING_HOST_ID: instance.host}
            # Now get the port details to process the ports
            # binding profile info.
            data = self.list_ports(context, **search_opts)
            ports = data['ports']
            admin_client = get_client(context, admin=True)
            if teardown:
                # Reset the port profile
                self._clear_migration_port_profile(
                    context, instance, admin_client, ports)
            elif port_migrating:
                # Setup the port profile
                self._setup_migration_port_profile(
                    context, instance, host, admin_client, ports)

    def _get_available_networks(self, context, project_id,
                                net_ids=None, neutron=None,
                                auto_allocate=False):
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
            if auto_allocate:
                # The auto-allocated-topology extension may create complex
                # network topologies and it does so in a non-transactional
                # fashion. Therefore API users may be exposed to resources that
                # are transient or partially built. A client should use
                # resources that are meant to be ready and this can be done by
                # checking their admin_state_up flag.
                search_opts['admin_state_up'] = True
            nets = neutron.list_networks(**search_opts).get('networks', [])
            # (2) Retrieve public network list.
            search_opts = {'shared': True}
            nets += neutron.list_networks(**search_opts).get('networks', [])

        _ensure_requested_network_ordering(
            lambda x: x['id'],
            nets,
            net_ids)

        return nets

    def _create_port_minimal(self, port_client, instance, network_id,
                             fixed_ip=None, security_group_ids=None):
        """Attempts to create a port for the instance on the given network.

        :param port_client: The client to use to create the port.
        :param instance: Create the port for the given instance.
        :param network_id: Create the port on the given network.
        :param fixed_ip: Optional fixed IP to use from the given network.
        :param security_group_ids: Optional list of security group IDs to
            apply to the port.
        :returns: The created port.
        :raises PortLimitExceeded: If neutron fails with an OverQuota error.
        :raises NoMoreFixedIps: If neutron fails with
            IpAddressGenerationFailure error.
        :raises: PortBindingFailed: If port binding failed.
        """
        # Set the device_id so it's clear who this port was created for,
        # and to stop other instances trying to use it
        port_req_body = {'port': {'device_id': instance.uuid}}
        try:
            if fixed_ip:
                port_req_body['port']['fixed_ips'] = [
                    {'ip_address': str(fixed_ip)}]
            port_req_body['port']['network_id'] = network_id
            port_req_body['port']['admin_state_up'] = True
            port_req_body['port']['tenant_id'] = instance.project_id
            if security_group_ids:
                port_req_body['port']['security_groups'] = security_group_ids

            port_response = port_client.create_port(port_req_body)

            port = port_response['port']
            port_id = port['id']
            try:
                _ensure_no_port_binding_failure(port)
            except exception.PortBindingFailed:
                with excutils.save_and_reraise_exception():
                    port_client.delete_port(port_id)

            LOG.debug('Successfully created port: %s', port_id,
                      instance=instance)
            return port
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
        except neutron_client_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Neutron error creating port on network %s'),
                              network_id, instance=instance)

    def _update_port(self, port_client, instance, port_id,
                     port_req_body):
        try:
            port_response = port_client.update_port(port_id, port_req_body)
            port = port_response['port']
            _ensure_no_port_binding_failure(port)
            LOG.debug('Successfully updated port: %s', port_id,
                      instance=instance)
            return port
        except neutron_client_exc.MacAddressInUseClient:
            mac_address = port_req_body['port'].get('mac_address')
            network_id = port_req_body['port'].get('network_id')
            LOG.warning(_LW('Neutron error: MAC address %(mac)s is already '
                            'in use on network %(network)s.'),
                        {'mac': mac_address, 'network': network_id},
                        instance=instance)
            raise exception.PortInUse(port_id=mac_address)
        except neutron_client_exc.HostNotCompatibleWithFixedIpsClient:
            network_id = port_req_body['port'].get('network_id')
            LOG.warning(_LW('Neutron error: Tried to bind a port with '
                            'fixed_ips to a host in the wrong segment on '
                            'network %(network)s.'),
                        {'network': network_id}, instance=instance)
            raise exception.FixedIpInvalidOnHost(port_id=port_id)

    @staticmethod
    def _populate_mac_address(instance, port_req_body, available_macs):
        # NOTE(johngarbutt) On port_update, this will cause us to override
        # any previous mac address the port may have had.
        if available_macs is not None:
            if not available_macs:
                raise exception.PortNotFree(
                    instance=instance.uuid)
            mac_address = available_macs.pop()
            port_req_body['port']['mac_address'] = mac_address
            return mac_address

    def _check_external_network_attach(self, context, nets):
        """Check if attaching to external network is permitted."""
        if not context.can(servers_policies.NETWORK_ATTACH_EXTERNAL,
                           fatal=False):
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
                port_req_body['port'][BINDING_HOST_ID] = None
                port_req_body['port'][BINDING_PROFILE] = {}
            if constants.DNS_INTEGRATION in self.extensions:
                port_req_body['port']['dns_name'] = ''
            try:
                port_client.update_port(port_id, port_req_body)
            except neutron_client_exc.PortNotFoundClient:
                LOG.debug('Unable to unbind port %s as it no longer exists.',
                          port_id)
            except Exception:
                LOG.exception(_LE("Unable to clear device ID "
                                  "for port '%s'"), port_id)

    def _validate_requested_port_ids(self, context, instance, neutron,
                                     requested_networks):
        """Processes and validates requested networks for allocation.

        Iterates over the list of NetworkRequest objects, validating the
        request and building sets of ports, networks and MAC addresses to
        use for allocating ports for the instance.

        :param instance: allocate networks on this instance
        :type instance: nova.objects.Instance
        :param neutron: neutron client session
        :type neutron: neutronclient.v2_0.client.Client
        :returns: tuple of:
            - ports: dict mapping of port id to port dict
            - ordered_networks: list of nova.objects.NetworkRequest objects
                for requested networks (either via explicit network request
                or the network for an explicit port request)
        :raises nova.exception.PortNotFound: If a requested port is not found
            in Neutron.
        :raises nova.exception.PortNotUsable: If a requested port is not owned
            by the same tenant that the instance is created under.
        :raises nova.exception.PortInUse: If a requested port is already
            attached to another instance.
        :raises nova.exception.PortNotUsableDNS: If a requested port has a
            value assigned to its dns_name attribute.
        """
        ports = {}
        ordered_networks = []
        # If we're asked to auto-allocate the network then there won't be any
        # ports or real neutron networks to lookup, so just return empty
        # results.
        if requested_networks and not requested_networks.auto_allocate:
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
                    _ensure_no_port_binding_failure(port)

                    # If requesting a specific port, automatically process
                    # the network for that port as if it were explicitly
                    # requested.
                    request.network_id = port['network_id']
                    ports[request.port_id] = port

                # Process a request to use a specific neutron network.
                if request.network_id:
                    ordered_networks.append(request)

        return ports, ordered_networks

    def _clean_security_groups(self, security_groups):
        """Cleans security groups requested from Nova API

        Neutron already passes a 'default' security group when
        creating ports so it's not necessary to specify it to the
        request.
        """
        if not security_groups:
            security_groups = []
        elif security_groups == [DEFAULT_SECGROUP]:
            security_groups = []
        return security_groups

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

    def _validate_requested_network_ids(self, context, instance, neutron,
            requested_networks, ordered_networks):
        """Check requested networks using the Neutron API.

        Check the user has access to the network they requested, and that
        it is a suitable network to connect to. This includes getting the
        network details for any ports that have been passed in, because the
        request will have been updated with the network_id in
        _validate_requested_port_ids.

        If the user has not requested any ports or any networks, we get back
        a full list of networks the user has access to, and if there is only
        one network, we update ordered_networks so we will connect the
        instance to that network.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param requested_networks: value containing
            network_id, fixed_ip, and port_id
        :param ordered_networks: output from _validate_requested_port_ids
            that will be used to create and update ports
        """

        # Get networks from Neutron
        # If net_ids is empty, this actually returns all available nets
        auto_allocate = requested_networks and requested_networks.auto_allocate
        net_ids = [request.network_id for request in ordered_networks]
        nets = self._get_available_networks(context, instance.project_id,
                                            net_ids, neutron=neutron,
                                            auto_allocate=auto_allocate)
        if not nets:

            if requested_networks:
                # There are no networks available for the project to use and
                # none specifically requested, so check to see if we're asked
                # to auto-allocate the network.
                if auto_allocate:
                    # During validate_networks we checked to see if
                    # auto-allocation is available so we don't need to do that
                    # again here.
                    nets = [self._auto_allocate_network(instance, neutron)]
                else:
                    # NOTE(chaochin): If user specifies a network id and the
                    # network can not be found, raise NetworkNotFound error.
                    for request in requested_networks:
                        if not request.port_id and request.network_id:
                            raise exception.NetworkNotFound(
                                network_id=request.network_id)
            else:
                # no requested nets and user has no available nets
                return {}

        # if this function is directly called without a requested_network param
        # or if it is indirectly called through allocate_port_for_instance()
        # with None params=(network_id=None, requested_ip=None, port_id=None,
        # pci_request_id=None):
        if (not requested_networks
            or requested_networks.is_single_unspecified
            or requested_networks.auto_allocate):
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

        return {net['id']: net for net in nets}

    def _create_ports_for_instance(self, context, instance, ordered_networks,
            nets, neutron, security_group_ids):
        """Create port for network_requests that don't have a port_id

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param ordered_networks: objects.NetworkRequestList in requested order
        :param nets: a dict of network_id to networks returned from neutron
        :param neutron: neutronclient using built from users request context
        :param security_group_ids: a list of security_groups to go to neutron
        :returns a list of pairs (NetworkRequest, created_port_uuid)
        """
        created_port_ids = []
        requests_and_created_ports = []
        for request in ordered_networks:
            network = nets.get(request.network_id)
            # if network_id did not pass validate_networks() and not available
            # here then skip it safely not continuing with a None Network
            if not network:
                continue

            try:
                port_security_enabled = network.get(
                    'port_security_enabled', True)
                if port_security_enabled:
                    if not network.get('subnets'):
                        # Neutron can't apply security groups to a port
                        # for a network without L3 assignments.
                        LOG.debug('Network with port security enabled does '
                                  'not have subnets so security groups '
                                  'cannot be applied: %s',
                                  network, instance=instance)
                        raise exception.SecurityGroupCannotBeApplied()
                else:
                    if security_group_ids:
                        # We don't want to apply security groups on port
                        # for a network defined with
                        # 'port_security_enabled=False'.
                        LOG.debug('Network has port security disabled so '
                                  'security groups cannot be applied: %s',
                                  network, instance=instance)
                        raise exception.SecurityGroupCannotBeApplied()

                created_port_id = None
                if not request.port_id:
                    # create minimal port, if port not already created by user
                    created_port = self._create_port_minimal(
                            neutron, instance, request.network_id,
                            request.address, security_group_ids)
                    created_port_id = created_port['id']
                    created_port_ids.append(created_port_id)

                requests_and_created_ports.append((
                    request, created_port_id))

            except Exception:
                with excutils.save_and_reraise_exception():
                    if created_port_ids:
                        self._delete_ports(
                            neutron, instance, created_port_ids)

        return requests_and_created_ports

    def allocate_for_instance(self, context, instance, vpn,
                              requested_networks, macs=None,
                              security_groups=None,
                              dhcp_options=None, bind_host_id=None):
        """Allocate network resources for the instance.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param vpn: A boolean, ignored by this driver.
        :param requested_networks: objects.NetworkRequestList object.
        :param macs: None or a set of MAC addresses that the instance
            should use. macs is supplied by the hypervisor driver (contrast
            with requested_networks which is user supplied).
            NB: NeutronV2 currently assigns hypervisor supplied MAC addresses
            to arbitrary networks, which requires openflow switches to
            function correctly if more than one network is being used with
            the bare metal hypervisor (which is the only one known to limit
            MAC addresses).
        :param security_groups: None or security groups to allocate for
            instance.
        :param dhcp_options: None or a set of key/value pairs that should
            determine the DHCP BOOTP response, eg. for PXE booting an instance
            configured with the baremetal hypervisor. It is expected that these
            are already formatted for the neutron v2 api.
            See nova/virt/driver.py:dhcp_options_for_instance for an example.
        :param bind_host_id: the host ID to attach to the ports being created.
        :returns: network info as from get_instance_nw_info()
        """
        LOG.debug('allocate_for_instance()', instance=instance)
        if not instance.project_id:
            msg = _('empty project id for instance %s')
            raise exception.InvalidInput(
                reason=msg % instance.uuid)

        # We do not want to create a new neutron session for each call
        neutron = get_client(context)

        #
        # Validate ports and networks with neutron
        #
        ports, ordered_networks = self._validate_requested_port_ids(
            context, instance, neutron, requested_networks)

        nets = self._validate_requested_network_ids(
            context, instance, neutron, requested_networks, ordered_networks)
        if not nets:
            LOG.debug("No network configured", instance=instance)
            return network_model.NetworkInfo([])

        #
        # Create any ports that might be required,
        # after validating requested security groups
        #
        security_groups = self._clean_security_groups(security_groups)
        security_group_ids = self._process_security_groups(
                                    instance, neutron, security_groups)

        requests_and_created_ports = self._create_ports_for_instance(
            context, instance, ordered_networks, nets, neutron,
            security_group_ids)

        #
        # Update existing and newly created ports
        #
        available_macs = _filter_hypervisor_macs(instance, ports, macs)

        # We always need admin_client to build nw_info,
        # we sometimes need it when updating ports
        admin_client = get_client(context, admin=True)

        ordered_nets, ordered_ports, preexisting_port_ids, \
            created_port_ids = self._update_ports_for_instance(
                context, instance,
                neutron, admin_client, requests_and_created_ports, nets,
                bind_host_id, dhcp_options, available_macs)

        #
        # Perform a full update of the network_info_cache,
        # including re-fetching lots of the required data from neutron
        #
        nw_info = self.get_instance_nw_info(
            context, instance, networks=ordered_nets,
            port_ids=ordered_ports,
            admin_client=admin_client,
            preexisting_port_ids=preexisting_port_ids,
            update_cells=True)
        # Only return info about ports we processed in this run, which might
        # have been pre-existing neutron ports or ones that nova created. In
        # the initial allocation case (server create), this will be everything
        # we processed, and in later runs will only be what was processed that
        # time. For example, if the instance was created with port A and
        # then port B was attached in this call, only port B would be returned.
        # Thus, this filtering only affects the attach case.
        return network_model.NetworkInfo([vif for vif in nw_info
                                          if vif['id'] in created_port_ids +
                                          preexisting_port_ids])

    def _update_ports_for_instance(self, context, instance, neutron,
            admin_client, requests_and_created_ports, nets,
            bind_host_id, dhcp_opts, available_macs):
        """Update ports from network_requests.

        Updates the pre-existing ports and the ones created in
        ``_create_ports_for_instance`` with ``device_id``, ``device_owner``,
        optionally ``mac_address`` and ``dhcp_opts``, and, depending on the
        loaded extensions, ``rxtx_factor``, ``binding:host_id``, ``dns_name``.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param neutron: client using user context
        :param admin_client: client using admin context
        :param requests_and_created_ports: [(NetworkRequest, created_port_id)]
        :param nets: a dict of network_id to networks returned from neutron
        :param bind_host_id: a string for port['binding:host_id']
        :param dhcp_opts: a list dicts that contain dhcp option name and value
            e.g. [{'opt_name': 'tftp-server', 'opt_value': '1.2.3.4'}]
        :param available_macs: a list of available mac addresses
        """

        # The neutron client and port_client (either the admin context or
        # tenant context) are read here. The reason for this is that there are
        # a number of different calls for the instance allocation.
        # We require admin creds to set port bindings.
        port_client = (neutron if not
                       self._has_port_binding_extension(context,
                           refresh_cache=True, neutron=neutron) else
                       admin_client)

        preexisting_port_ids = []
        created_port_ids = []
        ports_in_requested_order = []
        nets_in_requested_order = []
        created_vifs = []   # this list is for cleanups if we fail
        for request, created_port_id in requests_and_created_ports:
            vifobj = objects.VirtualInterface(context)
            vifobj.instance_uuid = instance.uuid
            vifobj.tag = request.tag if 'tag' in request else None

            network = nets.get(request.network_id)
            # if network_id did not pass validate_networks() and not available
            # here then skip it safely not continuing with a None Network
            if not network:
                continue

            nets_in_requested_order.append(network)

            zone = 'compute:%s' % instance.availability_zone
            port_req_body = {'port': {'device_id': instance.uuid,
                                      'device_owner': zone}}
            try:
                self._populate_neutron_extension_values(
                    context, instance, request.pci_request_id, port_req_body,
                    network=network, neutron=neutron,
                    bind_host_id=bind_host_id)
                self._populate_pci_mac_address(instance,
                    request.pci_request_id, port_req_body)
                self._populate_mac_address(
                    instance, port_req_body, available_macs)
                if dhcp_opts is not None:
                    port_req_body['port']['extra_dhcp_opts'] = dhcp_opts

                if created_port_id:
                    port_id = created_port_id
                    created_port_ids.append(port_id)
                else:
                    port_id = request.port_id
                ports_in_requested_order.append(port_id)

                # After port is created, update other bits
                updated_port = self._update_port(
                    port_client, instance, port_id, port_req_body)

                # NOTE(danms): The virtual_interfaces table enforces global
                # uniqueness on MAC addresses, which clearly does not match
                # with neutron's view of the world. Since address is a 255-char
                # string we can namespace it with our port id. Using '/' should
                # be safely excluded from MAC address notations as well as
                # UUIDs. We could stop doing this when we remove
                # nova-network, but we'd need to leave the read translation in
                # for longer than that of course.
                vifobj.address = '%s/%s' % (updated_port['mac_address'],
                                            updated_port['id'])
                vifobj.uuid = port_id
                vifobj.create()
                created_vifs.append(vifobj)

                if not created_port_id:
                    # only add if update worked and port create not called
                    preexisting_port_ids.append(port_id)

                self._update_port_dns_name(context, instance, network,
                                           ports_in_requested_order[-1],
                                           neutron)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self._unbind_ports(context,
                                       preexisting_port_ids,
                                       neutron, port_client)
                    self._delete_ports(neutron, instance, created_port_ids)
                    for vif in created_vifs:
                        vif.destroy()

        return (nets_in_requested_order, ports_in_requested_order,
            preexisting_port_ids, created_port_ids)

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

    def _has_auto_allocate_extension(self, context, refresh_cache=False,
                                     neutron=None):
        if refresh_cache or not self.extensions:
            self._refresh_neutron_extensions_cache(context, neutron=neutron)
        return constants.AUTO_ALLOCATE_TOPO_EXT in self.extensions

    def _has_multi_provider_extension(self, context, neutron=None):
        self._refresh_neutron_extensions_cache(context, neutron=neutron)
        return constants.MULTI_NET_EXT in self.extensions

    def _get_pci_device_profile(self, pci_dev):
        dev_spec = self.pci_whitelist.get_devspec(pci_dev)
        if dev_spec:
            return {'pci_vendor_info': "%s:%s" %
                        (pci_dev.vendor_id, pci_dev.product_id),
                    'pci_slot': pci_dev.address,
                    'physical_network':
                        dev_spec.get_tags().get('physical_network')}
        raise exception.PciDeviceNotFound(node_id=pci_dev.compute_node_id,
                                          address=pci_dev.address)

    def _populate_neutron_binding_profile(self, instance, pci_request_id,
                                          port_req_body):
        """Populate neutron binding:profile.

        Populate it with SR-IOV related information

        :raises PciDeviceNotFound: If a claimed PCI device for the given
            pci_request_id cannot be found on the instance.
        """
        if pci_request_id:
            pci_devices = pci_manager.get_instance_pci_devs(
                instance, pci_request_id)
            if not pci_devices:
                # The pci_request_id likely won't mean much except for tracing
                # through the logs since it is generated per request.
                LOG.error(
                    _LE('Unable to find PCI device using PCI request ID in '
                        'list of claimed instance PCI devices: %s. Is the '
                        '[pci]/passthrough_whitelist configuration correct?'),
                    # Convert to a primitive list to stringify it.
                    list(instance.pci_devices), instance=instance)
                raise exception.PciDeviceNotFound(
                    _('PCI device not found for request ID %s.') %
                    pci_request_id)
            pci_dev = pci_devices.pop()
            profile = self._get_pci_device_profile(pci_dev)
            port_req_body['port'][BINDING_PROFILE] = profile

    @staticmethod
    def _populate_pci_mac_address(instance, pci_request_id, port_req_body):
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
            port_req_body['port'][BINDING_HOST_ID] = bind_host_id
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

        # deallocate vifs (mac addresses)
        objects.VirtualInterface.delete_by_instance_uuid(
            context, instance.uuid)

        # NOTE(arosen): This clears out the network_cache only if the instance
        # hasn't already been deleted. This is needed when an instance fails to
        # launch and is rescheduled onto another compute node. If the instance
        # has already been deleted this call does nothing.
        base_api.update_instance_cache_with_nw_info(self, context, instance,
                                            network_model.NetworkInfo([]))

    def allocate_port_for_instance(self, context, instance, port_id,
                                   network_id=None, requested_ip=None,
                                   bind_host_id=None, tag=None):
        """Allocate a port for the instance."""
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id=network_id,
                                            address=requested_ip,
                                            port_id=port_id,
                                            pci_request_id=None,
                                            tag=tag)])
        return self.allocate_for_instance(context, instance, vpn=False,
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

        # Delete the VirtualInterface for the given port_id.
        vif = objects.VirtualInterface.get_by_uuid(context, port_id)
        if vif:
            if 'tag' in vif and vif.tag:
                self._delete_nic_metadata(instance, vif)
            vif.destroy()
        else:
            LOG.debug('VirtualInterface not found for port: %s',
                      port_id, instance=instance)

        return self.get_instance_nw_info(context, instance)

    def _delete_nic_metadata(self, instance, vif):
        for device in instance.device_metadata.devices:
            if (isinstance(device, objects.NetworkInterfaceMetadata)
                    and device.mac == vif.address):
                instance.device_metadata.devices.remove(device)
                instance.save()
                break

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
                                      port_ids=None, neutron=None):
        """Return an instance's complete list of port_ids and networks."""

        if ((networks is None and port_ids is not None) or
            (port_ids is None and networks is not None)):
            message = _("This method needs to be called with either "
                        "networks=None and port_ids=None or port_ids and "
                        "networks as not none.")
            raise exception.NovaException(message=message)

        ifaces = instance.get_network_info()
        # This code path is only done when refreshing the network_cache
        if port_ids is None:
            port_ids = [iface['id'] for iface in ifaces]
            net_ids = [iface['network']['id'] for iface in ifaces]

        if networks is None:
            networks = self._get_available_networks(context,
                                                    instance.project_id,
                                                    net_ids, neutron)
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

    def _get_phynet_info(self, context, neutron, net_id):
        phynet_name = None
        if self._has_multi_provider_extension(context, neutron=neutron):
            network = neutron.show_network(net_id,
                                           fields='segments').get('network')
            segments = network.get('segments', {})
            for net in segments:
                # NOTE(vladikr): In general, "multi-segments" network is a
                # combination of L2 segments. The current implementation
                # contains a vxlan and vlan(s) segments, where only a vlan
                # network will have a physical_network specified, but may
                # change in the future. The purpose of this method
                # is to find a first segment that provides a physical network.
                # TODO(vladikr): Additional work will be required to handle the
                # case of multiple vlan segments associated with different
                # physical networks.
                phynet_name = net.get('provider:physical_network')
                if phynet_name:
                    return phynet_name
            # Raising here as at least one segment should
            # have a physical network provided.
            if segments:
                msg = (_("None of the segments of network %s provides a "
                         "physical_network") % net_id)
                raise exception.NovaException(message=msg)

        net = neutron.show_network(net_id,
                        fields='provider:physical_network').get('network')
        phynet_name = net.get('provider:physical_network')
        return phynet_name

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
            phynet_name = self._get_phynet_info(context, neutron, net_id)
        return vnic_type, phynet_name

    def create_pci_requests_for_sriov_ports(self, context, pci_requests,
                                            requested_networks):
        """Check requested networks for any SR-IOV port request.

        Create a PCI request object for each SR-IOV port, and add it to the
        pci_requests object that contains a list of PCI request object.
        """
        if not requested_networks or requested_networks.no_allocate:
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
                # TODO(moshele): To differentiate between the SR-IOV legacy
                # and SR-IOV ovs hardware offload we will leverage the nic
                # feature based scheduling in nova. This mean we will need
                # libvirt to expose the nic feature. At the moment
                # there is a limitation that deployers cannot use both
                # SR-IOV modes (legacy and ovs) in the same deployment.
                spec = {pci_request.PCI_NET_TAG: phynet_name}
                dev_type = pci_request.DEVICE_TYPE_FOR_VNIC_TYPE.get(vnic_type)
                if dev_type:
                    spec[pci_request.PCI_DEVICE_TYPE_TAG] = dev_type
                request = objects.InstancePCIRequest(
                    count=1,
                    spec=[spec],
                    request_id=uuidutils.generate_uuid())
                pci_requests.requests.append(request)
                pci_request_id = request.request_id

            # Add pci_request_id into the requested network
            request_net.pci_request_id = pci_request_id

    def _can_auto_allocate_network(self, context, neutron):
        """Helper method to determine if we can auto-allocate networks

        :param context: nova request context
        :param neutron: neutron client
        :returns: True if it's possible to auto-allocate networks, False
                  otherwise.
        """
        # check that the auto-allocated-topology extension is available
        if self._has_auto_allocate_extension(context, neutron=neutron):
            # run the dry-run validation, which will raise a 409 if not ready
            try:
                neutron.validate_auto_allocated_topology_requirements(
                    context.project_id)
                LOG.debug('Network auto-allocation is available for project '
                          '%s', context.project_id)
            except neutron_client_exc.Conflict as ex:
                LOG.debug('Unable to auto-allocate networks. %s',
                          six.text_type(ex))
            else:
                return True
        else:
            LOG.debug('Unable to auto-allocate networks. The neutron '
                      'auto-allocated-topology extension is not available.')
        return False

    def _auto_allocate_network(self, instance, neutron):
        """Automatically allocates a network for the given project.

        :param instance: create the network for the project that owns this
            instance
        :param neutron: neutron client
        :returns: Details of the network that was created.
        :raises: nova.exception.UnableToAutoAllocateNetwork
        :raises: nova.exception.NetworkNotFound
        """
        project_id = instance.project_id
        LOG.debug('Automatically allocating a network for project %s.',
                  project_id, instance=instance)
        try:
            topology = neutron.get_auto_allocated_topology(
                project_id)['auto_allocated_topology']
        except neutron_client_exc.Conflict:
            raise exception.UnableToAutoAllocateNetwork(project_id=project_id)

        try:
            network = neutron.show_network(topology['id'])['network']
        except neutron_client_exc.NetworkNotFoundClient:
            # This shouldn't happen since we just created the network, but
            # handle it anyway.
            LOG.error(_LE('Automatically allocated network %(network_id)s '
                          'was not found.'), {'network_id': topology['id']},
                      instance=instance)
            raise exception.UnableToAutoAllocateNetwork(project_id=project_id)

        LOG.debug('Automatically allocated network: %s', network,
                  instance=instance)
        return network

    def _ports_needed_per_instance(self, context, neutron, requested_networks):

        # TODO(danms): Remove me when all callers pass an object
        if requested_networks and isinstance(requested_networks[0], tuple):
            requested_networks = objects.NetworkRequestList.from_tuples(
                requested_networks)

        ports_needed_per_instance = 0
        if (requested_networks is None or len(requested_networks) == 0 or
                requested_networks.auto_allocate):
            nets = self._get_available_networks(context, context.project_id,
                                                neutron=neutron)
            if len(nets) > 1:
                # Attaching to more than one network by default doesn't
                # make sense, as the order will be arbitrary and the guest OS
                # won't know which to configure
                msg = _("Multiple possible networks found, use a Network "
                         "ID to be more specific.")
                raise exception.NetworkAmbiguous(msg)

            if not nets and (
                requested_networks and requested_networks.auto_allocate):
                # If there are no networks available to this project and we
                # were asked to auto-allocate a network, check to see that we
                # can do that first.
                LOG.debug('No networks are available for project %s; checking '
                          'to see if we can automatically allocate a network.',
                          context.project_id)
                if not self._can_auto_allocate_network(context, neutron):
                    raise exception.UnableToAutoAllocateNetwork(
                        project_id=context.project_id)

            ports_needed_per_instance = 1
        else:
            net_ids_requested = []
            for request in requested_networks:
                if request.port_id:
                    port = self._show_port(context, request.port_id,
                                           neutron_client=neutron)
                    if port.get('device_id', None):
                        raise exception.PortInUse(port_id=request.port_id)
                    deferred_ip = port.get('ip_allocation') == 'deferred'
                    # NOTE(carl_baldwin) A deferred IP port doesn't have an
                    # address here. If it fails to get one later when nova
                    # updates it with host info, Neutron will error which
                    # raises an exception.
                    if not deferred_ip and not port.get('fixed_ips'):
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
            quotas = neutron.show_quota(context.project_id)['quota']
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
        try:
            client.update_floatingip(fip['id'], {'floatingip': param})
        except neutron_client_exc.Conflict as e:
            raise exception.FloatingIpAssociateFailed(six.text_type(e))

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
        return self._make_floating_ip_obj(context, fip, pool_dict, port_dict)

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

    def _make_floating_ip_obj(self, context, fip, pool_dict, port_dict):
        pool = pool_dict[fip['floating_network_id']]
        # NOTE(danms): Don't give these objects a context, since they're
        # not lazy-loadable anyway
        floating = objects.floating_ip.NeutronFloatingIP(
            id=fip['id'], address=fip['floating_ip_address'],
            pool=(pool['name'] or pool['id']), project_id=fip['tenant_id'],
            fixed_ip_id=fip['port_id'])
        # In Neutron v2 API fixed_ip_address and instance uuid
        # (= device_id) are known here, so pass it as a result.
        if fip['fixed_ip_address']:
            floating.fixed_ip = objects.FixedIP(
                address=fip['fixed_ip_address'])
        else:
            floating.fixed_ip = None
        if fip['port_id']:
            instance_uuid = port_dict[fip['port_id']]['device_id']
            # NOTE(danms): This could be .refresh()d, so give it context
            floating.instance = objects.Instance(context=context,
                                                 uuid=instance_uuid)
            if floating.fixed_ip:
                floating.fixed_ip.instance_uuid = instance_uuid
        else:
            floating.instance = None
        return floating

    def get_floating_ip_by_address(self, context, address):
        """Return a floating IP given an address."""
        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        pool_dict = self._setup_net_dict(client,
                                         fip['floating_network_id'])
        port_dict = self._setup_port_dict(context, client, fip['port_id'])
        return self._make_floating_ip_obj(context, fip, pool_dict, port_dict)

    def get_floating_ips_by_project(self, context):
        client = get_client(context)
        project_id = context.project_id
        fips = self._safe_get_floating_ips(client, tenant_id=project_id)
        if not fips:
            return []
        pool_dict = self._setup_pools_dict(client)
        port_dict = self._setup_ports_dict(client, project_id)
        return [self._make_floating_ip_obj(context, fip, pool_dict, port_dict)
                for fip in fips]

    def get_instance_id_by_floating_address(self, context, address):
        """Return the instance id a floating IP's fixed IP is allocated to."""
        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        if not fip['port_id']:
            return None

        try:
            port = self._show_port(context, fip['port_id'],
                                   neutron_client=client)
        except exception.PortNotFound:
            # NOTE: Here is a potential race condition between _show_port() and
            # _get_floating_ip_by_address(). fip['port_id'] shows a port which
            # is the server instance's. At _get_floating_ip_by_address(),
            # Neutron returns the list which includes the instance. Just after
            # that, the deletion of the instance happens and Neutron returns
            # 404 on _show_port().
            LOG.debug('The port(%s) is not found', fip['port_id'])
            return None

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

    def _get_default_floating_ip_pool_name(self):
        """Get default pool name from config.

        TODO(stephenfin): Remove this helper function in Queens, opting to
        use the [neutron] option only.
        """
        if CONF.default_floating_pool != 'nova':
            LOG.warning(_LW("Config option 'default_floating_pool' is set to "
                            "a non-default value. Falling back to this value "
                            "for now but this behavior will change in a "
                            "future release. You should unset this value "
                            "and set the '[neutron] default_floating_pool' "
                            "option instead."))
            return CONF.default_floating_pool

        return CONF.neutron.default_floating_pool

    def allocate_floating_ip(self, context, pool=None):
        """Add a floating IP to a project from a pool."""
        client = get_client(context)
        pool = pool or self._get_default_floating_ip_pool_name()
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
                                   for k, v in kwargs.items()]))

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

        @base_api.refresh_cache
        def _release_floating_ip_and_refresh_cache(self, context, instance,
                                                   floating_ip):
            self._release_floating_ip(context, floating_ip['address'],
                                      raise_if_associated=False)
        if instance:
            _release_floating_ip_and_refresh_cache(self, context, instance,
                                                   floating_ip)
        else:
            self._release_floating_ip(context, floating_ip['address'],
                                      raise_if_associated=False)

    def _release_floating_ip(self, context, address,
                             raise_if_associated=True):
        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)

        if raise_if_associated and fip['port_id']:
            raise exception.FloatingIpAssociated(address=address)
        try:
            client.delete_floatingip(fip['id'])
        except neutron_client_exc.NotFound:
            raise exception.FloatingIpNotFoundForAddress(
                address=address
            )

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
                                               migration['dest_compute'],
                                               migration=migration)

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

    def _nw_info_get_subnets(self, context, port, network_IPs, client=None):
        subnets = self._get_subnets_from_port(context, port, client)
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
        if vif_type in [network_model.VIF_TYPE_OVS,
                        network_model.VIF_TYPE_AGILIO_OVS]:
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
        elif (vif_type == network_model.VIF_TYPE_VHOSTUSER and
         port_details.get(network_model.VIF_DETAILS_VHOSTUSER_FP_PLUG,
                          False)):
            bridge = port_details.get(network_model.VIF_DETAILS_BRIDGE_NAME,
                                      "brq" + port['network_id'])

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
        port_profile = _get_binding_profile(port)
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
        net_info = instance.get_network_info()
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
                context, instance, networks, port_ids, client)
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
                                                    network_IPs, client)

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
                    profile=_get_binding_profile(current_neutron_port),
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

    def _get_subnets_from_port(self, context, port, client=None):
        """Return the subnets for a given port."""

        fixed_ips = port['fixed_ips']
        # No fixed_ips for the port means there is no subnet associated
        # with the network the port is created on.
        # Since list_subnets(id=[]) returns all subnets visible for the
        # current tenant, returned subnets may contain subnets which is not
        # related to the port. To avoid this, the method returns here.
        if not fixed_ips:
            return []
        if not client:
            client = get_client(context)
        search_opts = {'id': list(set(ip['subnet_id'] for ip in fixed_ips))}
        data = client.list_subnets(**search_opts)
        ipam_subnets = data.get('subnets', [])
        subnets = []

        for subnet in ipam_subnets:
            subnet_dict = {'cidr': subnet['cidr'],
                           'gateway': network_model.IP(
                                address=subnet['gateway_ip'],
                                type='gateway'),
            }
            if subnet.get('ipv6_address_mode'):
                subnet_dict['ipv6_address_mode'] = subnet['ipv6_address_mode']

            # attempt to populate DHCP server field
            search_opts = {'network_id': subnet['network_id'],
                           'device_owner': 'network:dhcp'}
            data = client.list_ports(**search_opts)
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

    def setup_instance_network_on_host(self, context, instance, host,
                                       migration=None):
        """Setup network for specified instance on host."""
        self._update_port_binding_for_instance(context, instance, host,
                                               migration)

    def cleanup_instance_network_on_host(self, context, instance, host):
        """Cleanup network for specified instance on host."""
        # TODO(mriedem): This should likely be implemented at least for the
        # shelve offload operation because the instance is being removed from
        # a compute host, VIFs are unplugged, etc, so the ports should also
        # be unbound, albeit still logically attached to the instance (for the
        # shelve scenario). If _unbind_ports was going to be leveraged here, it
        # would have to be adjusted a bit since it currently clears the
        # device_id field on the port which is not what we'd want for shelve.
        pass

    def _get_pci_devices_from_migration_context(self, migration_context,
                                                migration):
        if migration and migration.get('status') == 'reverted':
            # In case of revert, swap old and new devices to
            # update the ports back to the original devices.
            return (migration_context.new_pci_devices,
                    migration_context.old_pci_devices)
        return (migration_context.old_pci_devices,
                migration_context.new_pci_devices)

    def _get_pci_mapping_for_migration(self, context, instance, migration):
        """Get the mapping between the old PCI devices and the new PCI
        devices that have been allocated during this migration.  The
        correlation is based on PCI request ID which is unique per PCI
        devices for SR-IOV ports.

        :param context:  The request context.
        :param instance: Get PCI mapping for this instance.
        :param migration: The migration for this instance.
        :Returns: dictionary of mapping {'<old pci address>': <New PciDevice>}
        """
        migration_context = instance.migration_context
        if not migration_context:
            return {}

        old_pci_devices, new_pci_devices = \
            self._get_pci_devices_from_migration_context(migration_context,
                                                         migration)
        if old_pci_devices and new_pci_devices:
            LOG.debug("Determining PCI devices mapping using migration"
                      "context: old_pci_devices: %(old)s, "
                      "new_pci_devices: %(new)s",
                      {'old': [dev for dev in old_pci_devices],
                       'new': [dev for dev in new_pci_devices]})
            return {old.address: new
                    for old in old_pci_devices
                        for new in new_pci_devices
                            if old.request_id == new.request_id}
        return {}

    def _update_port_binding_for_instance(self, context, instance, host,
                                          migration=None):
        if not self._has_port_binding_extension(context, refresh_cache=True):
            return
        neutron = get_client(context, admin=True)
        search_opts = {'device_id': instance.uuid,
                       'tenant_id': instance.project_id}
        data = neutron.list_ports(**search_opts)
        pci_mapping = None
        port_updates = []
        ports = data['ports']
        for p in ports:
            updates = {}
            binding_profile = _get_binding_profile(p)

            # If the host hasn't changed, like in the case of resizing to the
            # same host, there is nothing to do.
            if p.get(BINDING_HOST_ID) != host:
                updates[BINDING_HOST_ID] = host
                # If the host changed, the AZ could have also changed so we
                # need to update the device_owner.
                updates['device_owner'] = (
                        'compute:%s' % instance.availability_zone)
                # NOTE: Before updating the port binding make sure we
                # remove the pre-migration status from the binding profile
                if binding_profile.get(MIGRATING_ATTR):
                    del binding_profile[MIGRATING_ATTR]
                    updates[BINDING_PROFILE] = binding_profile

            # Update port with newly allocated PCI devices.  Even if the
            # resize is happening on the same host, a new PCI device can be
            # allocated. Note that this only needs to happen if a migration
            # is in progress such as in a resize / migrate.  It is possible
            # that this function is called without a migration object, such
            # as in an unshelve operation.
            vnic_type = p.get('binding:vnic_type')
            if (vnic_type in network_model.VNIC_TYPES_SRIOV
                    and migration is not None):
                if not pci_mapping:
                    pci_mapping = self._get_pci_mapping_for_migration(context,
                        instance, migration)

                pci_slot = binding_profile.get('pci_slot')
                new_dev = pci_mapping.get(pci_slot)
                if new_dev:
                    binding_profile.update(
                        self._get_pci_device_profile(new_dev))
                    updates[BINDING_PROFILE] = binding_profile
                else:
                    raise exception.PortUpdateFailed(port_id=p['id'],
                        reason=_("Unable to correlate PCI slot %s") %
                                 pci_slot)

            port_updates.append((p['id'], updates))

        # Avoid rolling back updates if we catch an error above.
        # TODO(lbeliveau): Batch up the port updates in one neutron call.
        for port_id, updates in port_updates:
            if updates:
                LOG.info(_LI("Updating port %(port)s with "
                             "attributes %(attributes)s"),
                         {"port": port_id, "attributes": updates},
                         instance=instance)
                try:
                    neutron.update_port(port_id, {'port': updates})
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.exception(_LE("Unable to update binding details "
                                          "for port %s"),
                                      port_id, instance=instance)

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

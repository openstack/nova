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

"""
API and utilities for nova-network interactions.
"""

import copy
import functools
import time

from keystoneauth1 import loading as ks_loading
from neutronclient.common import exceptions as neutron_client_exc
from neutronclient.v2_0 import client as clientv20
from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import uuidutils
import six

from nova.compute import utils as compute_utils
import nova.conf
from nova import context as nova_context
from nova.db import base
from nova import exception
from nova import hooks
from nova.i18n import _
from nova.network import constants
from nova.network import model as network_model
from nova import objects
from nova.objects import fields as obj_fields
from nova.pci import manager as pci_manager
from nova.pci import request as pci_request
from nova.pci import utils as pci_utils
from nova.pci import whitelist as pci_whitelist
from nova.policies import servers as servers_policies
from nova import profiler
from nova import service_auth
from nova import utils

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

_SESSION = None
_ADMIN_AUTH = None


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

    if conf.neutron.auth_type is None:
        # If we're coming in through a REST API call for something like
        # creating a server, the end user is going to get a 500 response
        # which is accurate since the system is mis-configured, but we should
        # leave a breadcrumb for the operator that is checking the logs.
        LOG.error('The [neutron] section of your nova configuration file '
                  'must be configured for authentication with the networking '
                  'service endpoint. See the networking service install guide '
                  'for details: '
                  'https://docs.openstack.org/neutron/latest/install/')
    err_msg = _('Unknown auth type: %s') % conf.neutron.auth_type
    raise neutron_client_exc.Unauthorized(message=err_msg)


def get_binding_profile(port):
    """Convenience method to get the binding:profile from the port

    The binding:profile in the port is undefined in the networking service
    API and is dependent on backend configuration. This means it could be
    an empty dict, None, or have some values.

    :param port: dict port response body from the networking service API
    :returns: The port binding:profile dict; empty if not set on the port
    """
    return port.get(constants.BINDING_PROFILE, {}) or {}


@hooks.add_hook('instance_network_info')
def update_instance_cache_with_nw_info(impl, context, instance, nw_info=None):
    if instance.deleted:
        LOG.debug('Instance is deleted, no further info cache update',
                  instance=instance)
        return

    try:
        if not isinstance(nw_info, network_model.NetworkInfo):
            nw_info = None
        if nw_info is None:
            nw_info = impl._get_instance_nw_info(context, instance)

        LOG.debug('Updating instance_info_cache with network_info: %s',
                  nw_info, instance=instance)

        # NOTE(comstud): The save() method actually handles updating or
        # creating the instance.  We don't need to retrieve the object
        # from the DB first.
        ic = objects.InstanceInfoCache.new(context, instance.uuid)
        ic.network_info = nw_info
        ic.save()
        instance.info_cache = ic
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception('Failed storing info cache', instance=instance)


def refresh_cache(f):
    """Decorator to update the instance_info_cache

    Requires context and instance as function args
    """
    argspec = utils.getargspec(f)

    @functools.wraps(f)
    def wrapper(self, context, *args, **kwargs):
        try:
            # get the instance from arguments (or raise ValueError)
            instance = kwargs.get('instance')
            if not instance:
                instance = args[argspec.args.index('instance') - 2]
        except ValueError:
            msg = _('instance is a required argument to use @refresh_cache')
            raise Exception(msg)

        with lockutils.lock('refresh_cache-%s' % instance.uuid):
            # We need to call the wrapped function with the lock held to ensure
            # that it can call _get_instance_nw_info safely.
            res = f(self, context, *args, **kwargs)
            update_instance_cache_with_nw_info(self, context, instance,
                                               nw_info=res)
        # return the original function's return value
        return res
    return wrapper


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
                LOG.error("Neutron client was not able to generate a "
                          "valid admin token, please verify Neutron "
                          "admin credential located in nova.conf")
                raise exception.NeutronAdminCredentialConfigurationInvalid()
            except neutron_client_exc.Forbidden as e:
                raise exception.Forbidden(six.text_type(e))
            return ret
        return wrapper


def _get_auth_plugin(context, admin=False):
    # NOTE(dprince): In the case where no auth_token is present we allow use of
    # neutron admin tenant credentials if it is an admin context.  This is to
    # support some services (metadata API) where an admin context is used
    # without an auth token.
    global _ADMIN_AUTH
    if admin or (context.is_admin and not context.auth_token):
        if not _ADMIN_AUTH:
            _ADMIN_AUTH = _load_auth_plugin(CONF)
        return _ADMIN_AUTH

    if context.auth_token:
        return service_auth.get_auth_plugin(context)

    # We did not get a user token and we should not be using
    # an admin token so log an error
    raise exception.Unauthorized()


def _get_session():
    global _SESSION
    if not _SESSION:
        _SESSION = ks_loading.load_session_from_conf_options(
            CONF, nova.conf.neutron.NEUTRON_GROUP)
    return _SESSION


def get_client(context, admin=False):
    auth_plugin = _get_auth_plugin(context, admin=admin)
    session = _get_session()
    client_args = dict(session=session,
                       auth=auth_plugin,
                       global_request_id=context.global_id,
                       connect_retries=CONF.neutron.http_retries)

    # NOTE(efried): We build an adapter
    #               to pull conf options
    #               to pass to neutronclient
    #               which uses them to build an Adapter.
    # This should be unwound at some point.
    adap = utils.get_ksa_adapter(
        'network', ksa_auth=auth_plugin, ksa_session=session)
    client_args = dict(client_args,
                       service_type=adap.service_type,
                       service_name=adap.service_name,
                       interface=adap.interface,
                       region_name=adap.region_name,
                       endpoint_override=adap.endpoint_override)

    return ClientWrapper(clientv20.Client(**client_args),
                         admin=admin or context.is_admin)


def _get_ksa_client(context, admin=False):
    """Returns a keystoneauth Adapter

    This method should only be used if python-neutronclient does not yet
    provide the necessary API bindings.

    :param context: User request context
    :param admin: If True, uses the configured credentials, else uses the
        existing auth_token in the context (the user token).
    :returns: keystoneauth1 Adapter object
    """
    auth_plugin = _get_auth_plugin(context, admin=admin)
    session = _get_session()
    client = utils.get_ksa_adapter(
        'network', ksa_auth=auth_plugin, ksa_session=session)
    client.additional_headers = {'accept': 'application/json'}
    return client


def _is_not_duplicate(item, items, items_list_name, instance):
    present = item in items

    # The expectation from this function's perspective is that the
    # item is not part of the items list so if it is part of it
    # we should at least log it as a warning
    if present:
        LOG.warning("%(item)s already exists in list: %(list_name)s "
                    "containing: %(items)s. ignoring it",
                    {'item': item,
                     'list_name': items_list_name,
                     'items': items},
                    instance=instance)

    return not present


def _ensure_no_port_binding_failure(port):
    binding_vif_type = port.get('binding:vif_type')
    if binding_vif_type == network_model.VIF_TYPE_BINDING_FAILED:
        raise exception.PortBindingFailed(port_id=port['id'])


class API(base.Base):
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
                port_id, {'port': {constants.BINDING_PROFILE: port_profile}})
            return updated_port
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error("Unable to update binding profile "
                          "for port: %(port)s due to failure: %(error)s",
                          {'port': port_id, 'error': ex},
                          instance=instance)

    def _clear_migration_port_profile(
            self, context, instance, admin_client, ports):
        for p in ports:
            # If the port already has a migration profile and if
            # it is to be torn down, then we need to clean up
            # the migration profile.
            port_profile = get_binding_profile(p)
            if not port_profile:
                continue
            if constants.MIGRATING_ATTR in port_profile:
                del port_profile[constants.MIGRATING_ATTR]
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
            # the 'migrating_to'(constants.MIGRATING_ATTR) key pointing to
            # the given 'host'.
            host_id = p.get(constants.BINDING_HOST_ID)
            if host_id != host:
                port_profile = get_binding_profile(p)
                # If the "migrating_to" attribute already points at the given
                # host, then skip the port update call since we're not changing
                # anything.
                if host != port_profile.get(constants.MIGRATING_ATTR):
                    port_profile[constants.MIGRATING_ATTR] = host
                    self._update_port_with_migration_profile(
                        instance, p['id'], port_profile, admin_client)
                    LOG.debug("Port %(port_id)s updated with migration "
                              "profile %(profile_data)s successfully",
                              {'port_id': p['id'],
                               'profile_data': port_profile},
                              instance=instance)

    def setup_networks_on_host(self, context, instance, host=None,
                               teardown=False):
        """Setup or teardown the network structures.

        :param context: The user request context.
        :param instance: The instance with attached ports.
        :param host: Optional host used to control the setup. If provided and
            is not the same as the current instance.host, this method assumes
            the instance is being migrated and sets the "migrating_to"
            attribute in the binding profile for the attached ports.
        :param teardown: Whether or not network information for the ports
            should be cleaned up. If True, at a minimum the "migrating_to"
            attribute is cleared in the binding profile for the ports. If a
            host is also provided, then port bindings for that host are
            deleted when teardown is True as long as the host does not match
            the current instance.host.
        :raises: nova.exception.PortBindingDeletionFailed if host is not None,
            teardown is True, and port binding deletion fails.
        """
        # Check if the instance is migrating to a new host.
        port_migrating = host and (instance.host != host)
        # If the port is migrating to a new host or if it is a
        # teardown on the original host, then proceed.
        if port_migrating or teardown:
            search_opts = {'device_id': instance.uuid,
                           'tenant_id': instance.project_id,
                           constants.BINDING_HOST_ID: instance.host}
            # Now get the port details to process the ports
            # binding profile info.
            data = self.list_ports(context, **search_opts)
            ports = data['ports']
            admin_client = get_client(context, admin=True)
            if teardown:
                # Reset the port profile
                self._clear_migration_port_profile(
                    context, instance, admin_client, ports)
                # If a host was provided, delete any bindings between that
                # host and the ports as long as the host isn't the same as
                # the current instance.host.
                has_binding_ext = self.supports_port_binding_extension(context)
                if port_migrating and has_binding_ext:
                    self._delete_port_bindings(context, ports, host)
            elif port_migrating:
                # Setup the port profile
                self._setup_migration_port_profile(
                    context, instance, host, admin_client, ports)

    def _delete_port_bindings(self, context, ports, host):
        """Attempt to delete all port bindings on the host.

        :param context: The user request context.
        :param ports: list of port dicts to cleanup; the 'id' field is required
            per port dict in the list
        :param host: host from which to delete port bindings
        :raises: PortBindingDeletionFailed if port binding deletion fails.
        """
        failed_port_ids = []
        for port in ports:
            # This call is safe in that 404s for non-existing
            # bindings are ignored.
            try:
                self.delete_port_binding(
                    context, port['id'], host)
            except exception.PortBindingDeletionFailed:
                # delete_port_binding will log an error for each
                # failure but since we're iterating a list we want
                # to keep track of all failures to build a generic
                # exception to raise
                failed_port_ids.append(port['id'])
        if failed_port_ids:
            msg = (_("Failed to delete binding for port(s) "
                     "%(port_ids)s and host %(host)s.") %
                   {'port_ids': ','.join(failed_port_ids),
                    'host': host})
            raise exception.PortBindingDeletionFailed(msg)

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

    def _cleanup_created_port(self, port_client, port_id, instance):
        try:
            port_client.delete_port(port_id)
        except neutron_client_exc.NeutronClientException:
            LOG.exception(
                'Failed to delete port %(port_id)s while cleaning up after an '
                'error.', {'port_id': port_id},
                instance=instance)

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
        :raises NetworksWithQoSPolicyNotSupported: if the created port has
                resource request.
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

            # NOTE(gibi): Checking if the created port has resource request as
            # such ports are currently not supported as they would at least
            # need resource allocation manipulation in placement but might also
            # need a new scheduling if resource on this host is not available.
            if port.get(constants.RESOURCE_REQUEST, None):
                msg = _(
                    "The auto-created port %(port_id)s is being deleted due "
                    "to its network having QoS policy.")
                LOG.info(msg, {'port_id': port_id})
                self._cleanup_created_port(port_client, port_id, instance)
                # NOTE(gibi): This limitation regarding server create can be
                # removed when the port creation is moved to the conductor. But
                # this code also limits attaching a network that has QoS
                # minimum bandwidth rule.
                raise exception.NetworksWithQoSPolicyNotSupported(
                    instance_uuid=instance.uuid, network_id=network_id)
            try:
                _ensure_no_port_binding_failure(port)
            except exception.PortBindingFailed:
                with excutils.save_and_reraise_exception():
                    port_client.delete_port(port_id)

            LOG.debug('Successfully created port: %s', port_id,
                      instance=instance)
            return port
        except neutron_client_exc.InvalidIpForNetworkClient:
            LOG.warning('Neutron error: %(ip)s is not a valid IP address '
                        'for network %(network_id)s.',
                        {'ip': fixed_ip, 'network_id': network_id},
                        instance=instance)
            msg = (_('Fixed IP %(ip)s is not a valid ip address for '
                     'network %(network_id)s.') %
                   {'ip': fixed_ip, 'network_id': network_id})
            raise exception.InvalidInput(reason=msg)
        except (neutron_client_exc.IpAddressInUseClient,
                neutron_client_exc.IpAddressAlreadyAllocatedClient):
            LOG.warning('Neutron error: Fixed IP %s is '
                        'already in use.', fixed_ip, instance=instance)
            msg = _("Fixed IP %s is already in use.") % fixed_ip
            raise exception.FixedIpAlreadyInUse(message=msg)
        except neutron_client_exc.OverQuotaClient:
            LOG.warning(
                'Neutron error: Port quota exceeded in tenant: %s',
                port_req_body['port']['tenant_id'], instance=instance)
            raise exception.PortLimitExceeded()
        except neutron_client_exc.IpAddressGenerationFailureClient:
            LOG.warning('Neutron error: No more fixed IPs in network: %s',
                        network_id, instance=instance)
            raise exception.NoMoreFixedIps(net=network_id)
        except neutron_client_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception('Neutron error creating port on network %s',
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
            LOG.warning('Neutron error: MAC address %(mac)s is already '
                        'in use on network %(network)s.',
                        {'mac': mac_address, 'network': network_id},
                        instance=instance)
            raise exception.PortInUse(port_id=mac_address)
        except neutron_client_exc.HostNotCompatibleWithFixedIpsClient:
            network_id = port_req_body['port'].get('network_id')
            LOG.warning('Neutron error: Tried to bind a port with '
                        'fixed_ips to a host in the wrong segment on '
                        'network %(network)s.',
                        {'network': network_id}, instance=instance)
            raise exception.FixedIpInvalidOnHost(port_id=port_id)

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
        """Unbind the given ports by clearing their device_id,
        device_owner and dns_name.

        :param context: The request context.
        :param ports: list of port IDs.
        :param neutron: neutron client for the current context.
        :param port_client: The client with appropriate karma for
            updating the ports.
        """
        if port_client is None:
            # Requires admin creds to set port bindings
            port_client = get_client(context, admin=True)
        networks = {}
        for port_id in ports:
            # A port_id is optional in the NetworkRequest object so check here
            # in case the caller forgot to filter the list.
            if port_id is None:
                continue
            port_req_body = {'port': {'device_id': '', 'device_owner': ''}}
            port_req_body['port'][constants.BINDING_HOST_ID] = None
            try:
                port = self._show_port(
                    context, port_id, neutron_client=neutron,
                    fields=[constants.BINDING_PROFILE, 'network_id'])
            except exception.PortNotFound:
                LOG.debug('Unable to show port %s as it no longer '
                          'exists.', port_id)
                return
            except Exception:
                # NOTE: In case we can't retrieve the binding:profile or
                # network info assume that they are empty
                LOG.exception("Unable to get binding:profile for port '%s'",
                              port_id)
                port_profile = {}
                network = {}
            else:
                port_profile = get_binding_profile(port)
                net_id = port.get('network_id')
                if net_id in networks:
                    network = networks.get(net_id)
                else:
                    network = neutron.show_network(net_id,
                                                   fields=['dns_domain']
                                                   ).get('network')
                    networks[net_id] = network

            # NOTE: We're doing this to remove the binding information
            # for the physical device but don't want to overwrite the other
            # information in the binding profile.
            for profile_key in ('pci_vendor_info', 'pci_slot',
                                constants.ALLOCATION):
                if profile_key in port_profile:
                    del port_profile[profile_key]
            port_req_body['port'][constants.BINDING_PROFILE] = port_profile

            # NOTE: For internal DNS integration (network does not have a
            # dns_domain), or if we cannot retrieve network info, we use the
            # admin client to reset dns_name.
            if self._has_dns_extension() and not network.get('dns_domain'):
                port_req_body['port']['dns_name'] = ''
            try:
                port_client.update_port(port_id, port_req_body)
            except neutron_client_exc.PortNotFoundClient:
                LOG.debug('Unable to unbind port %s as it no longer '
                          'exists.', port_id)
            except Exception:
                LOG.exception("Unable to clear device ID for port '%s'",
                              port_id)
            # NOTE: For external DNS integration, we use the neutron client
            # with user's context to reset the dns_name since the recordset is
            # under user's zone.
            self._reset_port_dns_name(network, port_id, neutron)

    def _validate_requested_port_ids(self, context, instance, neutron,
                                     requested_networks, attach=False):
        """Processes and validates requested networks for allocation.

        Iterates over the list of NetworkRequest objects, validating the
        request and building sets of ports and networks to
        use for allocating ports for the instance.

        :param context: The user request context.
        :type context: nova.context.RequestContext
        :param instance: allocate networks on this instance
        :type instance: nova.objects.Instance
        :param neutron: neutron client session
        :type neutron: neutronclient.v2_0.client.Client
        :param requested_networks: List of user-requested networks and/or ports
        :type requested_networks: nova.objects.NetworkRequestList
        :param attach: Boolean indicating if a port is being attached to an
            existing running instance. Should be False during server create.
        :type attach: bool
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
        :raises nova.exception.AttachSRIOVPortNotSupported: If a requested port
            is an SR-IOV port and ``attach=True``.
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

                    # Make sure the port can be attached.
                    if attach:
                        # SR-IOV port attach is not supported.
                        vnic_type = port.get('binding:vnic_type',
                                             network_model.VNIC_TYPE_NORMAL)
                        if vnic_type in network_model.VNIC_TYPES_SRIOV:
                            raise exception.AttachSRIOVPortNotSupported(
                                port_id=port['id'],
                                instance_uuid=instance.uuid)

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
        elif security_groups == [constants.DEFAULT_SECGROUP]:
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
        :param neutron: neutron client
        :param requested_networks: nova.objects.NetworkRequestList, list of
            user-requested networks and/or ports; may be empty
        :param ordered_networks: output from _validate_requested_port_ids
            that will be used to create and update ports
        :returns: dict, keyed by network ID, of networks to use
        :raises InterfaceAttachFailedNoNetwork: If no specific networks were
            requested and none are available.
        :raises NetworkAmbiguous: If no specific networks were requested but
            more than one is available.
        :raises ExternalNetworkAttachForbidden: If the policy rules forbid
            the request context from using an external non-shared network but
            one was requested (or available).
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
        if (not requested_networks or
            requested_networks.is_single_unspecified or
            requested_networks.auto_allocate):
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
        :param neutron: neutronclient built from users request context
        :param security_group_ids: a list of security group IDs to be applied
            to any ports created
        :returns a list of pairs (NetworkRequest, created_port_uuid); note that
            created_port_uuid will be None for the pair where a pre-existing
            port was part of the user request
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
                              requested_networks,
                              security_groups=None, bind_host_id=None,
                              attach=False, resource_provider_mapping=None):
        """Allocate network resources for the instance.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param vpn: A boolean, ignored by this driver.
        :param requested_networks: objects.NetworkRequestList object.
        :param security_groups: None or security groups to allocate for
            instance.
        :param bind_host_id: the host ID to attach to the ports being created.
        :param attach: Boolean indicating if a port is being attached to an
            existing running instance. Should be False during server create.
        :param resource_provider_mapping: a dict keyed by ids of the entities
            (for example Neutron port) requesting resources for this instance
            mapped to a list of resource provider UUIDs that are fulfilling
            such a resource request.
        :returns: network info as from get_instance_nw_info()
        """
        LOG.debug('allocate_for_instance()', instance=instance)
        if not instance.project_id:
            msg = _('empty project id for instance %s')
            raise exception.InvalidInput(
                reason=msg % instance.uuid)

        # We do not want to create a new neutron session for each call
        neutron = get_client(context)

        # We always need admin_client to build nw_info,
        # we sometimes need it when updating ports
        admin_client = get_client(context, admin=True)

        #
        # Validate ports and networks with neutron. The requested_ports_dict
        # variable is a dict, keyed by port ID, of ports that were on the user
        # request and may be empty. The ordered_networks variable is a list of
        # NetworkRequest objects for any networks or ports specifically
        # requested by the user, which again may be empty.
        #

        # NOTE(gibi): we use the admin_client here to ensure that the returned
        # ports has the resource_request attribute filled as later we use this
        # information to decide when to add allocation key to the port binding.
        # See bug 1849657.
        requested_ports_dict, ordered_networks = (
            self._validate_requested_port_ids(
                context, instance, admin_client, requested_networks,
                attach=attach))

        nets = self._validate_requested_network_ids(
            context, instance, neutron, requested_networks, ordered_networks)
        if not nets:
            LOG.debug("No network configured", instance=instance)
            return network_model.NetworkInfo([])

        # Validate requested security groups
        security_groups = self._clean_security_groups(security_groups)
        security_group_ids = self._process_security_groups(
                                    instance, neutron, security_groups)

        # Tell Neutron which resource provider fulfills the ports' resource
        # request.
        # We only consider pre-created ports here as ports created
        # below based on requested networks are not scheduled to have their
        # resource request fulfilled.
        for port in requested_ports_dict.values():
            # only communicate the allocations if the port has resource
            # requests
            if port.get(constants.RESOURCE_REQUEST):
                profile = get_binding_profile(port)
                # NOTE(gibi): In the resource provider mapping there can be
                # more than one RP fulfilling a request group. But resource
                # requests of a Neutron port is always mapped to a
                # numbered request group that is always fulfilled by one
                # resource provider. So we only pass that single RP UUID here.
                profile[constants.ALLOCATION] = resource_provider_mapping[
                    port['id']][0]
                port[constants.BINDING_PROFILE] = profile

        # Create ports from the list of ordered_networks. The returned
        # requests_and_created_ports variable is a list of 2-item tuples of
        # the form (NetworkRequest, created_port_id). Note that a tuple pair
        # will have None for the created_port_id if the NetworkRequest already
        # contains a port_id, meaning the user requested a specific
        # pre-existing port so one wasn't created here. The ports will be
        # updated later in _update_ports_for_instance to be bound to the
        # instance and compute host.
        requests_and_created_ports = self._create_ports_for_instance(
            context, instance, ordered_networks, nets, neutron,
            security_group_ids)

        #
        # Update existing and newly created ports
        #

        ordered_nets, ordered_port_ids, preexisting_port_ids, \
            created_port_ids = self._update_ports_for_instance(
                context, instance,
                neutron, admin_client, requests_and_created_ports, nets,
                bind_host_id, requested_ports_dict)

        #
        # Perform a full update of the network_info_cache,
        # including re-fetching lots of the required data from neutron
        #
        nw_info = self.get_instance_nw_info(
            context, instance, networks=ordered_nets,
            port_ids=ordered_port_ids,
            admin_client=admin_client,
            preexisting_port_ids=preexisting_port_ids)
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
            bind_host_id, requested_ports_dict):
        """Update ports from network_requests.

        Updates the pre-existing ports and the ones created in
        ``_create_ports_for_instance`` with ``device_id``, ``device_owner``,
        optionally ``mac_address`` and, depending on the
        loaded extensions, ``rxtx_factor``, ``binding:host_id``, ``dns_name``.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param neutron: client using user context
        :param admin_client: client using admin context
        :param requests_and_created_ports: [(NetworkRequest, created_port_id)];
            Note that created_port_id will be None for any user-requested
            pre-existing port.
        :param nets: a dict of network_id to networks returned from neutron
        :param bind_host_id: a string for port['binding:host_id']
        :param requested_ports_dict: dict, keyed by port ID, of ports requested
            by the user
        :returns: tuple with the following::

            * list of network dicts in their requested order
            * list of port IDs in their requested order - note that does not
              mean the port was requested by the user, it could be a port
              created on a network requested by the user
            * list of pre-existing port IDs requested by the user
            * list of created port IDs
        """

        # We currently require admin creds to set port bindings.
        port_client = admin_client

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
            if (requested_ports_dict and
                request.port_id in requested_ports_dict and
                get_binding_profile(requested_ports_dict[request.port_id])):
                port_req_body['port'][constants.BINDING_PROFILE] = \
                    get_binding_profile(requested_ports_dict[request.port_id])
            try:
                self._populate_neutron_extension_values(
                    context, instance, request.pci_request_id, port_req_body,
                    network=network, neutron=neutron,
                    bind_host_id=bind_host_id)
                self._populate_pci_mac_address(instance,
                    request.pci_request_id, port_req_body)

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
                # UUIDs. We can stop doing this now that we've removed
                # nova-network, but we need to leave the read translation in
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
            ((time.time() - self.last_neutron_extension_sync) >=
             CONF.neutron.extension_sync_interval)):
            if neutron is None:
                neutron = get_client(context)
            extensions_list = neutron.list_extensions()['extensions']
            self.last_neutron_extension_sync = time.time()
            self.extensions.clear()
            self.extensions = {ext['name']: ext for ext in extensions_list}

    def _has_multi_provider_extension(self, context, neutron=None):
        self._refresh_neutron_extensions_cache(context, neutron=neutron)
        return constants.MULTI_NET_EXT in self.extensions

    def _has_dns_extension(self):
        return constants.DNS_INTEGRATION in self.extensions

    def _has_qos_queue_extension(self, context, neutron=None):
        self._refresh_neutron_extensions_cache(context, neutron=neutron)
        return constants.QOS_QUEUE in self.extensions

    def _has_fip_port_details_extension(self, context, neutron=None):
        self._refresh_neutron_extensions_cache(context, neutron=neutron)
        return constants.FIP_PORT_DETAILS in self.extensions

    def has_substr_port_filtering_extension(self, context):
        self._refresh_neutron_extensions_cache(context)
        return constants.SUBSTR_PORT_FILTERING in self.extensions

    def supports_port_binding_extension(self, context):
        """This is a simple check to see if the neutron "binding-extended"
        extension exists and is enabled.

        The "binding-extended" extension allows nova to bind a port to multiple
        hosts at the same time, like during live migration.

        :param context: the user request context
        :returns: True if the binding-extended API extension is available,
                  False otherwise
        """
        self._refresh_neutron_extensions_cache(context)
        return constants.PORT_BINDING_EXTENDED in self.extensions

    def bind_ports_to_host(self, context, instance, host,
                           vnic_types=None, port_profiles=None):
        """Attempts to bind the ports from the instance on the given host

        If the ports are already actively bound to another host, like the
        source host during live migration, then the new port bindings will
        be inactive, assuming $host is the destination host for the live
        migration.

        In the event of an error, any ports which were successfully bound to
        the host should have those host bindings removed from the ports.

        This method should not be used if "supports_port_binding_extension"
        returns False.

        :param context: the user request context
        :type context: nova.context.RequestContext
        :param instance: the instance with a set of ports
        :type instance: nova.objects.Instance
        :param host: the host on which to bind the ports which
                     are attached to the instance
        :type host: str
        :param vnic_types: optional dict for the host port binding
        :type vnic_types: dict of <port_id> : <vnic_type>
        :param port_profiles: optional dict per port ID for the host port
                        binding profile.
                        note that the port binding profile is mutable
                        via the networking "Port Binding" API so callers that
                        pass in a profile should ensure they have the latest
                        version from neutron with their changes merged,
                        which can be determined using the "revision_number"
                        attribute of the port.
        :type port_profiles: dict of <port_id> : <port_profile>
        :raises: PortBindingFailed if any of the ports failed to be bound to
                 the destination host
        :returns: dict, keyed by port ID, of a new host port
                  binding dict per port that was bound
        """
        # Get the current ports off the instance. This assumes the cache is
        # current.
        network_info = instance.get_network_info()

        if not network_info:
            # The instance doesn't have any ports so there is nothing to do.
            LOG.debug('Instance does not have any ports.', instance=instance)
            return {}

        client = _get_ksa_client(context, admin=True)

        bindings_by_port_id = {}
        for vif in network_info:
            # Now bind each port to the destination host and keep track of each
            # port that is bound to the resulting binding so we can rollback in
            # the event of a failure, or return the results if everything is OK
            port_id = vif['id']
            binding = dict(host=host)
            if vnic_types is None or port_id not in vnic_types:
                binding['vnic_type'] = vif['vnic_type']
            else:
                binding['vnic_type'] = vnic_types[port_id]

            if port_profiles is None or port_id not in port_profiles:
                binding['profile'] = vif['profile']
            else:
                binding['profile'] = port_profiles[port_id]

            data = dict(binding=binding)
            resp = self._create_port_binding(context, client, port_id, data)
            if resp:
                bindings_by_port_id[port_id] = resp.json()['binding']
            else:
                # Something failed, so log the error and rollback any
                # successful bindings.
                LOG.error('Binding failed for port %s and host %s. '
                          'Error: (%s %s)',
                          port_id, host, resp.status_code, resp.text,
                          instance=instance)
                for rollback_port_id in bindings_by_port_id:
                    try:
                        self.delete_port_binding(
                            context, rollback_port_id, host)
                    except exception.PortBindingDeletionFailed:
                        LOG.warning('Failed to remove binding for port %s on '
                                    'host %s.', rollback_port_id, host,
                                    instance=instance)
                raise exception.PortBindingFailed(port_id=port_id)

        return bindings_by_port_id

    @staticmethod
    def _create_port_binding(context, client, port_id, data):
        """Creates a port binding with the specified data.

        :param context: The request context for the operation.
        :param client: keystoneauth1.adapter.Adapter
        :param port_id: The ID of the port on which to create the binding.
        :param data: dict of port binding data (requires at least the host),
            for example::

                {'binding': {'host': 'dest.host.com'}}
        :return: requests.Response object
        """
        return client.post(
            '/v2.0/ports/%s/bindings' % port_id, json=data, raise_exc=False,
            global_request_id=context.global_id)

    def delete_port_binding(self, context, port_id, host):
        """Delete the port binding for the given port ID and host

        This method should not be used if "supports_port_binding_extension"
        returns False.

        :param context: The request context for the operation.
        :param port_id: The ID of the port with a binding to the host.
        :param host: The host from which port bindings should be deleted.
        :raises: nova.exception.PortBindingDeletionFailed if a non-404 error
            response is received from neutron.
        """
        client = _get_ksa_client(context, admin=True)
        resp = self._delete_port_binding(context, client, port_id, host)
        if resp:
            LOG.debug('Deleted binding for port %s and host %s.',
                      port_id, host)
        else:
            # We can safely ignore 404s since we're trying to delete
            # the thing that wasn't found anyway.
            if resp.status_code != 404:
                # Log the details, raise an exception.
                LOG.error('Unexpected error trying to delete binding '
                          'for port %s and host %s. Code: %s. '
                          'Error: %s', port_id, host,
                          resp.status_code, resp.text)
                raise exception.PortBindingDeletionFailed(
                    port_id=port_id, host=host)

    @staticmethod
    def _delete_port_binding(context, client, port_id, host):
        """Deletes the binding for the given host on the given port.

        :param context: The request context for the operation.
        :param client: keystoneauth1.adapter.Adapter
        :param port_id: ID of the port from which to delete the binding
        :param host: A string name of the host on which the port is bound
        :return: requests.Response object
        """
        return client.delete(
            '/v2.0/ports/%s/bindings/%s' % (port_id, host), raise_exc=False,
            global_request_id=context.global_id)

    def activate_port_binding(self, context, port_id, host):
        """Activates an inactive port binding.

        If there are two port bindings to different hosts, activating the
        inactive binding atomically changes the other binding to inactive.

        :param context: The request context for the operation.
        :param port_id: The ID of the port with an inactive binding on the
                        host.
        :param host: The host on which the inactive port binding should be
                     activated.
        :raises: nova.exception.PortBindingActivationFailed if a non-409 error
            response is received from neutron.
        """
        client = _get_ksa_client(context, admin=True)
        # This is a bit weird in that we don't PUT and update the status
        # to ACTIVE, it's more like a POST action method in the compute API.
        resp = self._activate_port_binding(context, client, port_id, host)
        if resp:
            LOG.debug('Activated binding for port %s and host %s.',
                      port_id, host)
        # A 409 means the port binding is already active, which shouldn't
        # happen if the caller is doing things in the correct order.
        elif resp.status_code == 409:
            LOG.warning('Binding for port %s and host %s is already '
                        'active.', port_id, host)
        else:
            # Log the details, raise an exception.
            LOG.error('Unexpected error trying to activate binding '
                      'for port %s and host %s. Code: %s. '
                      'Error: %s', port_id, host, resp.status_code,
                      resp.text)
            raise exception.PortBindingActivationFailed(
                port_id=port_id, host=host)

    @staticmethod
    def _activate_port_binding(context, client, port_id, host):
        """Activates an inactive port binding.

        :param context: The request context for the operation.
        :param client: keystoneauth1.adapter.Adapter
        :param port_id: ID of the port to activate the binding on
        :param host: A string name of the host identifying the binding to be
            activated
        :return: requests.Response object
        """
        return client.put(
            '/v2.0/ports/%s/bindings/%s/activate' % (port_id, host),
            raise_exc=False,
            global_request_id=context.global_id)

    @staticmethod
    def _get_port_binding(context, client, port_id, host):
        """Returns a port binding of a given port on a given host

        :param context: The request context for the operation.
        :param client: keystoneauth1.adapter.Adapter
        :param port_id: ID of the port to get the binding
        :param host: A string name of the host identifying the binding to be
            returned
        :return: requests.Response object
        """
        return client.get(
            '/v2.0/ports/%s/bindings/%s' % (port_id, host),
            raise_exc=False,
            global_request_id=context.global_id)

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
                LOG.error('Unable to find PCI device using PCI request ID in '
                          'list of claimed instance PCI devices: %s. Is the '
                          '[pci]/passthrough_whitelist configuration correct?',
                          # Convert to a primitive list to stringify it.
                          list(instance.pci_devices), instance=instance)
                raise exception.PciDeviceNotFound(
                    _('PCI device not found for request ID %s.') %
                    pci_request_id)
            pci_dev = pci_devices.pop()
            profile = copy.deepcopy(get_binding_profile(port_req_body['port']))
            profile.update(self._get_pci_device_profile(pci_dev))
            port_req_body['port'][constants.BINDING_PROFILE] = profile

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
                LOG.error("PCI request %s does not have a "
                          "unique device associated with it. Unable to "
                          "determine MAC address",
                          pci_request_id, instance=instance)
                return
            pci_dev = pci_devs[0]
            if pci_dev.dev_type == obj_fields.PciDeviceType.SRIOV_PF:
                try:
                    mac = pci_utils.get_mac_by_pci_address(pci_dev.address)
                except exception.PciDeviceNotFoundById as e:
                    LOG.error(
                        "Could not determine MAC address for %(addr)s, "
                        "error: %(e)s",
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
        if self._has_qos_queue_extension(context, neutron=neutron):
            flavor = instance.get_flavor()
            rxtx_factor = flavor.get('rxtx_factor')
            port_req_body['port']['rxtx_factor'] = rxtx_factor
        port_req_body['port'][constants.BINDING_HOST_ID] = bind_host_id
        self._populate_neutron_binding_profile(instance,
                                               pci_request_id,
                                               port_req_body)

        if self._has_dns_extension():
            # If the DNS integration extension is enabled in Neutron, most
            # ports will get their dns_name attribute set in the port create or
            # update requests in allocate_for_instance. So we just add the
            # dns_name attribute to the payload of those requests. The
            # exception is when the port binding extension is enabled in
            # Neutron and the port is on a network that has a non-blank
            # dns_domain attribute. This case requires to be processed by
            # method _update_port_dns_name
            if (not network.get('dns_domain')):
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
        if self._has_dns_extension() and network.get('dns_domain'):
            try:
                port_req_body = {'port': {'dns_name': instance.hostname}}
                neutron.update_port(port_id, port_req_body)
            except neutron_client_exc.BadRequest:
                LOG.warning('Neutron error: Instance hostname '
                            '%(hostname)s is not a valid DNS name',
                            {'hostname': instance.hostname}, instance=instance)
                msg = (_('Instance hostname %(hostname)s is not a valid DNS '
                         'name') % {'hostname': instance.hostname})
                raise exception.InvalidInput(reason=msg)

    def _reset_port_dns_name(self, network, port_id, neutron_client):
        """Reset an instance port dns_name attribute to empty when using
        external DNS service.

        _unbind_ports uses a client with admin context to reset the dns_name if
        the DNS extension is enabled and network does not have dns_domain set.
        When external DNS service is enabled, we use this method to make the
        request with a Neutron client using user's context, so that the DNS
        record can be found under user's zone and domain.
        """
        if self._has_dns_extension() and network.get('dns_domain'):
            try:
                port_req_body = {'port': {'dns_name': ''}}
                neutron_client.update_port(port_id, port_req_body)
            except neutron_client_exc.NeutronClientException:
                LOG.exception("Failed to reset dns_name for port %s", port_id)

    def _delete_ports(self, neutron, instance, ports, raise_if_fail=False):
        exceptions = []
        for port in ports:
            try:
                neutron.delete_port(port)
            except neutron_client_exc.NeutronClientException as e:
                if e.status_code == 404:
                    LOG.warning("Port %s does not exist", port,
                                instance=instance)
                else:
                    exceptions.append(e)
                    LOG.warning("Failed to delete port %s for instance.",
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
        update_instance_cache_with_nw_info(self, context, instance,
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
                bind_host_id=bind_host_id, attach=True)

    def deallocate_port_for_instance(self, context, instance, port_id):
        """Remove a specified port from the instance.

        :param context: the request context
        :param instance: the instance object the port is detached from
        :param port_id: the UUID of the port being detached
        :return: A NetworkInfo, port_allocation tuple where the
                 port_allocation is a dict which contains the resource
                 allocation of the port per resource provider uuid. E.g.:
                 {
                     rp_uuid: {
                         NET_BW_EGR_KILOBIT_PER_SEC: 10000,
                         NET_BW_IGR_KILOBIT_PER_SEC: 20000,
                     }
                 }
                 Note that right now this dict only contains a single key as a
                 neutron port only allocates from a single resource provider.
        """
        neutron = get_client(context)
        port_allocation = {}
        try:
            # NOTE(gibi): we need to read the port resource information from
            # neutron here as we might delete the port below
            port = neutron.show_port(port_id)['port']
        except exception.PortNotFound:
            LOG.debug('Unable to determine port %s resource allocation '
                      'information as the port no longer exists.', port_id)
            port = None

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

        if port:
            # if there is resource associated to this port then that needs to
            # be deallocated so lets return info about such allocation
            resource_request = port.get(constants.RESOURCE_REQUEST)
            profile = get_binding_profile(port)
            allocated_rp = profile.get(constants.ALLOCATION)
            if resource_request and allocated_rp:
                port_allocation = {
                    allocated_rp: resource_request.get('resources', {})}
        else:
            # Check the info_cache. If the port is still in the info_cache and
            # in that cache there is allocation in the profile then we suspect
            # that the port is disappeared without deallocating the resources.
            for vif in instance.get_network_info():
                if vif['id'] == port_id:
                    profile = vif.get('profile') or {}
                    rp_uuid = profile.get(constants.ALLOCATION)
                    if rp_uuid:
                        LOG.warning(
                            'Port %s disappeared during deallocate but it had '
                            'resource allocation on resource provider %s. '
                            'Resource allocation for this port may be '
                            'leaked.', port_id, rp_uuid, instance=instance)
                    break

        return self.get_instance_nw_info(context, instance), port_allocation

    def _delete_nic_metadata(self, instance, vif):
        for device in instance.device_metadata.devices:
            if (isinstance(device, objects.NetworkInterfaceMetadata) and
                    device.mac == vif.address):
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

    def get_instance_nw_info(self, context, instance, **kwargs):
        """Returns all network info related to an instance."""
        with lockutils.lock('refresh_cache-%s' % instance.uuid):
            result = self._get_instance_nw_info(context, instance, **kwargs)
            update_instance_cache_with_nw_info(self, context, instance,
                                               nw_info=result)
        return result

    def _get_instance_nw_info(self, context, instance, networks=None,
                              port_ids=None, admin_client=None,
                              preexisting_port_ids=None,
                              refresh_vif_id=None, force_refresh=False,
                              **kwargs):
        # NOTE(danms): This is an inner method intended to be called
        # by other code that updates instance nwinfo. It *must* be
        # called with the refresh_cache-%(instance_uuid) lock held!
        if force_refresh:
            LOG.debug('Forcefully refreshing network info cache for instance',
                      instance=instance)
        elif refresh_vif_id:
            LOG.debug('Refreshing network info cache for port %s',
                      refresh_vif_id, instance=instance)
        else:
            LOG.debug('Building network info cache for instance',
                      instance=instance)
        # Ensure that we have an up to date copy of the instance info cache.
        # Otherwise multiple requests could collide and cause cache
        # corruption.
        compute_utils.refresh_info_cache_for_instance(context, instance)
        nw_info = self._build_network_info_model(context, instance, networks,
                                                 port_ids, admin_client,
                                                 preexisting_port_ids,
                                                 refresh_vif_id,
                                                 force_refresh=force_refresh)
        return network_model.NetworkInfo.hydrate(nw_info)

    def _gather_port_ids_and_networks(self, context, instance, networks=None,
                                      port_ids=None, neutron=None):
        """Return an instance's complete list of port_ids and networks.

        The results are based on the instance info_cache in the nova db, not
        the instance's current list of ports in neutron.
        """

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

    @refresh_cache
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

    @refresh_cache
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

        raise exception.FixedIpNotFoundForInstance(
                instance_uuid=instance.uuid, ip=address)

    def _get_physnet_tunneled_info(self, context, neutron, net_id):
        """Retrieve detailed network info.

        :param context: The request context.
        :param neutron: The neutron client object.
        :param net_id: The ID of the network to retrieve information for.

        :return: A tuple containing the physnet name, if defined, and the
            tunneled status of the network. If the network uses multiple
            segments, the first segment that defines a physnet value will be
            used for the physnet name.
        """
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
                physnet_name = net.get('provider:physical_network')
                if physnet_name:
                    return physnet_name, False

            # Raising here as at least one segment should
            # have a physical network provided.
            if segments:
                msg = (_("None of the segments of network %s provides a "
                         "physical_network") % net_id)
                raise exception.NovaException(message=msg)

        net = neutron.show_network(
            net_id, fields=['provider:physical_network',
                            'provider:network_type']).get('network')
        return (net.get('provider:physical_network'),
                net.get('provider:network_type') in constants.L3_NETWORK_TYPES)

    @staticmethod
    def _get_trusted_mode_from_port(port):
        """Returns whether trusted mode is requested

        If port binding does not provide any information about trusted
        status this function is returning None
        """
        value = get_binding_profile(port).get('trusted')
        if value is not None:
            # This allows the user to specify things like '1' and 'yes' in
            # the port binding profile and we can handle it as a boolean.
            return strutils.bool_from_string(value)

    def _get_port_vnic_info(self, context, neutron, port_id):
        """Retrieve port vNIC info

        :param context: The request context
        :param neutron: The Neutron client
        :param port_id: The id of port to be queried

        :return: A tuple of vNIC type, trusted status, network ID and resource
                 request of the port if any. Trusted status only affects SR-IOV
                 ports and will always be None for other port types.
        """
        port = self._show_port(
            context, port_id, neutron_client=neutron,
            fields=['binding:vnic_type', constants.BINDING_PROFILE,
                    'network_id', constants.RESOURCE_REQUEST])
        network_id = port.get('network_id')
        trusted = None
        vnic_type = port.get('binding:vnic_type',
                             network_model.VNIC_TYPE_NORMAL)
        if vnic_type in network_model.VNIC_TYPES_SRIOV:
            trusted = self._get_trusted_mode_from_port(port)

        # NOTE(gibi): Get the port resource_request which may or may not be
        # set depending on neutron configuration, e.g. if QoS rules are
        # applied to the port/network and the port-resource-request API
        # extension is enabled.
        resource_request = port.get(constants.RESOURCE_REQUEST, None)
        return vnic_type, trusted, network_id, resource_request

    def create_resource_requests(
            self, context, requested_networks, pci_requests=None,
            affinity_policy=None):
        """Retrieve all information for the networks passed at the time of
        creating the server.

        :param context: The request context.
        :param requested_networks: The networks requested for the server.
        :type requested_networks: nova.objects.NetworkRequestList
        :param pci_requests: The list of PCI requests to which additional PCI
            requests created here will be added.
        :type pci_requests: nova.objects.InstancePCIRequests
        :param affinity_policy: requested pci numa affinity policy
        :type affinity_policy: nova.objects.fields.PCINUMAAffinityPolicy

        :returns: A tuple with an instance of ``objects.NetworkMetadata`` for
                  use by the scheduler or None and a list of RequestGroup
                  objects representing the resource needs of each requested
                  port
        """
        if not requested_networks or requested_networks.no_allocate:
            return None, []

        physnets = set()
        tunneled = False

        neutron = get_client(context, admin=True)
        resource_requests = []

        for request_net in requested_networks:
            physnet = None
            trusted = None
            tunneled_ = False
            vnic_type = network_model.VNIC_TYPE_NORMAL
            pci_request_id = None
            requester_id = None

            if request_net.port_id:
                result = self._get_port_vnic_info(
                    context, neutron, request_net.port_id)
                vnic_type, trusted, network_id, resource_request = result
                physnet, tunneled_ = self._get_physnet_tunneled_info(
                    context, neutron, network_id)

                if resource_request:
                    # InstancePCIRequest.requester_id is semantically linked
                    # to a port with a resource_request.
                    requester_id = request_net.port_id
                    # NOTE(gibi): explicitly orphan the RequestGroup by setting
                    # context=None as we never intended to save it to the DB.
                    resource_requests.append(
                        objects.RequestGroup.from_port_request(
                            context=None,
                            port_uuid=request_net.port_id,
                            port_resource_request=resource_request))

            elif request_net.network_id and not request_net.auto_allocate:
                network_id = request_net.network_id
                physnet, tunneled_ = self._get_physnet_tunneled_info(
                    context, neutron, network_id)

            # All tunneled traffic must use the same logical NIC so we just
            # need to know if there is one or more tunneled networks present.
            tunneled = tunneled or tunneled_

            # ...conversely, there can be multiple physnets, which will
            # generally be mapped to different NICs, and some requested
            # networks may use the same physnet. As a result, we need to know
            # the *set* of physnets from every network requested
            if physnet:
                physnets.add(physnet)

            if vnic_type in network_model.VNIC_TYPES_SRIOV:
                # TODO(moshele): To differentiate between the SR-IOV legacy
                # and SR-IOV ovs hardware offload we will leverage the nic
                # feature based scheduling in nova. This mean we will need
                # libvirt to expose the nic feature. At the moment
                # there is a limitation that deployers cannot use both
                # SR-IOV modes (legacy and ovs) in the same deployment.
                spec = {pci_request.PCI_NET_TAG: physnet}
                dev_type = pci_request.DEVICE_TYPE_FOR_VNIC_TYPE.get(vnic_type)
                if dev_type:
                    spec[pci_request.PCI_DEVICE_TYPE_TAG] = dev_type
                if trusted is not None:
                    # We specifically have requested device on a pool
                    # with a tag trusted set to true or false. We
                    # convert the value to string since tags are
                    # compared in that way.
                    spec[pci_request.PCI_TRUSTED_TAG] = str(trusted)
                request = objects.InstancePCIRequest(
                    count=1,
                    spec=[spec],
                    request_id=uuidutils.generate_uuid(),
                    requester_id=requester_id)
                if affinity_policy:
                    request.numa_policy = affinity_policy
                pci_requests.requests.append(request)
                pci_request_id = request.request_id

            # Add pci_request_id into the requested network
            request_net.pci_request_id = pci_request_id

        return (objects.NetworkMetadata(physnets=physnets, tunneled=tunneled),
                resource_requests)

    def _can_auto_allocate_network(self, context, neutron):
        """Helper method to determine if we can auto-allocate networks

        :param context: nova request context
        :param neutron: neutron client
        :returns: True if it's possible to auto-allocate networks, False
                  otherwise.
        """
        # run the dry-run validation, which will raise a 409 if not ready
        try:
            neutron.validate_auto_allocated_topology_requirements(
                context.project_id)
            LOG.debug('Network auto-allocation is available for project '
                      '%s', context.project_id)
            return True
        except neutron_client_exc.Conflict as ex:
            LOG.debug('Unable to auto-allocate networks. %s',
                      six.text_type(ex))
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
            LOG.error('Automatically allocated network %(network_id)s '
                      'was not found.', {'network_id': topology['id']},
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

    def get_requested_resource_for_instance(self, context, instance_uuid):
        """Collect resource requests from the ports associated to the instance

        :param context: nova request context
        :param instance_uuid: The UUID of the instance
        :return: A list of RequestGroup objects
        """

        # NOTE(gibi): We need to use an admin client as otherwise a non admin
        # initiated resize causes that neutron does not fill the
        # resource_request field of the port and this will lead to resource
        # allocation issues. See bug 1849695
        neutron = get_client(context, admin=True)
        # get the ports associated to this instance
        data = neutron.list_ports(
            device_id=instance_uuid, fields=['id', 'resource_request'])
        resource_requests = []

        for port in data.get('ports', []):
            if port.get('resource_request'):
                # NOTE(gibi): explicitly orphan the RequestGroup by setting
                # context=None as we never intended to save it to the DB.
                resource_requests.append(
                    objects.RequestGroup.from_port_request(
                        context=None, port_uuid=port['id'],
                        port_resource_request=port['resource_request']))

        return resource_requests

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

    @refresh_cache
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

        # If the floating IP was associated with another server, try to refresh
        # the cache for that instance to avoid a window of time where multiple
        # servers in the API say they are using the same floating IP.
        if fip['port_id']:
            # Trap and log any errors from
            # _update_inst_info_cache_for_disassociated_fip but not let them
            # raise back up to the caller since this refresh is best effort.
            try:
                self._update_inst_info_cache_for_disassociated_fip(
                    context, instance, client, fip)
            except Exception as e:
                LOG.warning('An error occurred while trying to refresh the '
                            'network info cache for an instance associated '
                            'with port %s. Error: %s', fip['port_id'], e)

    def _update_inst_info_cache_for_disassociated_fip(self, context,
                                                      instance, client, fip):
        """Update the network info cache when a floating IP is re-assigned.

        :param context: nova auth RequestContext
        :param instance: The instance to which the floating IP is now assigned
        :param client: ClientWrapper instance for using the Neutron API
        :param fip: dict for the floating IP that was re-assigned where the
                    the ``port_id`` value represents the port that was
                    associated with another server.
        """
        port = self._show_port(context, fip['port_id'],
                               neutron_client=client)
        orig_instance_uuid = port['device_id']

        msg_dict = dict(address=fip['floating_ip_address'],
                        instance_id=orig_instance_uuid)
        LOG.info('re-assign floating IP %(address)s from '
                 'instance %(instance_id)s', msg_dict,
                 instance=instance)
        orig_instance = self._get_instance_by_uuid_using_api_db(
            context, orig_instance_uuid)
        if orig_instance:
            # purge cached nw info for the original instance; pass the
            # context from the instance in case we found it in another cell
            update_instance_cache_with_nw_info(
                self, orig_instance._context, orig_instance)
        else:
            # Leave a breadcrumb about not being able to refresh the
            # the cache for the original instance.
            LOG.info('Unable to refresh the network info cache for '
                     'instance %s after disassociating floating IP %s. '
                     'If the instance still exists, its info cache may '
                     'be healed automatically.',
                     orig_instance_uuid, fip['id'])

    @staticmethod
    def _get_instance_by_uuid_using_api_db(context, instance_uuid):
        """Look up the instance by UUID

        This method is meant to be used sparingly since it tries to find
        the instance by UUID in the cell-targeted context. If the instance
        is not found, this method will try to determine if it's not found
        because it is deleted or if it is just in another cell. Therefore
        it assumes to have access to the API database and should only be
        called from methods that are used in the control plane services.

        :param context: cell-targeted nova auth RequestContext
        :param instance_uuid: UUID of the instance to find
        :returns: Instance object if the instance was found, else None.
        """
        try:
            return objects.Instance.get_by_uuid(context, instance_uuid)
        except exception.InstanceNotFound:
            # The instance could be deleted or it could be in another cell.
            # To determine if its in another cell, check the instance
            # mapping in the API DB.
            try:
                inst_map = objects.InstanceMapping.get_by_instance_uuid(
                    context, instance_uuid)
            except exception.InstanceMappingNotFound:
                # The instance is gone so just return.
                return

            # We have the instance mapping, look up the instance in the
            # cell the instance is in.
            with nova_context.target_cell(
                    context, inst_map.cell_mapping) as cctxt:
                try:
                    return objects.Instance.get_by_uuid(cctxt, instance_uuid)
                except exception.InstanceNotFound:
                    # Alright it's really gone.
                    return

    def get_all(self, context):
        """Get all networks for client."""
        client = get_client(context)
        return client.list_networks().get('networks')

    def get(self, context, network_uuid):
        """Get specific network for client."""
        client = get_client(context)
        try:
            return client.show_network(network_uuid).get('network') or {}
        except neutron_client_exc.NetworkNotFoundClient:
            raise exception.NetworkNotFound(network_id=network_uuid)

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

    def get_floating_ip(self, context, id):
        """Return floating IP object given the floating IP id."""
        client = get_client(context)
        try:
            fip = client.show_floatingip(id)['floatingip']
        except neutron_client_exc.NeutronClientException as e:
            if e.status_code == 404:
                raise exception.FloatingIpNotFound(id=id)

            with excutils.save_and_reraise_exception():
                LOG.exception('Unable to access floating IP %s', id)

        # retrieve and cache the network details now since many callers need
        # the network name which isn't present in the response from neutron
        network_uuid = fip['floating_network_id']
        try:
            fip['network_details'] = client.show_network(
                network_uuid)['network']
        except neutron_client_exc.NetworkNotFoundClient:
            raise exception.NetworkNotFound(network_id=network_uuid)

        # ...and retrieve the port details for the same reason, but only if
        # they're not already there because the fip-port-details extension is
        # present
        if not self._has_fip_port_details_extension(context, client):
            port_id = fip['port_id']
            try:
                fip['port_details'] = client.show_port(
                    port_id)['port']
            except neutron_client_exc.PortNotFoundClient:
                # it's possible to create floating IPs without a port
                fip['port_details'] = None

        return fip

    def get_floating_ip_by_address(self, context, address):
        """Return a floating IP given an address."""
        client = get_client(context)
        fip = self._get_floating_ip_by_address(client, address)

        # retrieve and cache the network details now since many callers need
        # the network name which isn't present in the response from neutron
        network_uuid = fip['floating_network_id']
        try:
            fip['network_details'] = client.show_network(
                network_uuid)['network']
        except neutron_client_exc.NetworkNotFoundClient:
            raise exception.NetworkNotFound(network_id=network_uuid)

        # ...and retrieve the port details for the same reason, but only if
        # they're not already there because the fip-port-details extension is
        # present
        if not self._has_fip_port_details_extension(context, client):
            port_id = fip['port_id']
            try:
                fip['port_details'] = client.show_port(
                    port_id)['port']
            except neutron_client_exc.PortNotFoundClient:
                # it's possible to create floating IPs without a port
                fip['port_details'] = None

        return fip

    def get_floating_ip_pools(self, context):
        """Return floating IP pools a.k.a. external networks."""
        client = get_client(context)
        data = client.list_networks(**{constants.NET_EXTERNAL: True})
        return data['networks']

    def get_floating_ips_by_project(self, context):
        client = get_client(context)
        project_id = context.project_id
        fips = self._safe_get_floating_ips(client, tenant_id=project_id)
        if not fips:
            return fips

        # retrieve and cache the network details now since many callers need
        # the network name which isn't present in the response from neutron
        networks = {net['id']: net for net in self._get_available_networks(
            context, project_id, [fip['floating_network_id'] for fip in fips],
            client)}
        for fip in fips:
            network_uuid = fip['floating_network_id']
            if network_uuid not in networks:
                raise exception.NetworkNotFound(network_id=network_uuid)

            fip['network_details'] = networks[network_uuid]

        # ...and retrieve the port details for the same reason, but only if
        # they're not already there because the fip-port-details extension is
        # present
        if not self._has_fip_port_details_extension(context, client):
            ports = {port['id']: port for port in client.list_ports(
                **{'tenant_id': project_id})['ports']}
            for fip in fips:
                port_id = fip['port_id']
                if port_id in ports:
                    fip['port_details'] = ports[port_id]
                else:
                    # it's possible to create floating IPs without a port
                    fip['port_details'] = None

        return fips

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
        return objects.VirtualInterfaceList.get_by_instance_uuid(context,
                                                                 instance.uuid)

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
        pool = pool or CONF.neutron.default_floating_pool
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
                LOG.exception('Unable to access floating IP for %s',
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

        @refresh_cache
        def _release_floating_ip_and_refresh_cache(self, context, instance,
                                                   floating_ip):
            self._release_floating_ip(
                context, floating_ip['floating_ip_address'],
                raise_if_associated=False)

        if instance:
            _release_floating_ip_and_refresh_cache(self, context, instance,
                                                   floating_ip)
        else:
            self._release_floating_ip(
                context, floating_ip['floating_ip_address'],
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

    @refresh_cache
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
        """Start to migrate the network of an instance.

        If the instance has port bindings on the destination compute host,
        they are activated in this method which will atomically change the
        source compute host port binding to inactive and also change the port
        "binding:host_id" attribute to the destination host.

        If there are no binding resources for the attached ports on the given
        destination host, this method is a no-op.

        :param context: The user request context.
        :param instance: The instance being migrated.
        :param migration: dict with required keys::

            "source_compute": The name of the source compute host.
            "dest_compute": The name of the destination compute host.

        :raises: nova.exception.PortBindingActivationFailed if any port binding
            activation fails
        """
        if not self.supports_port_binding_extension(context):
            # If neutron isn't new enough yet for the port "binding-extended"
            # API extension, we just no-op. The port binding host will be
            # be updated in migrate_instance_finish, which is functionally OK,
            # it's just not optimal.
            LOG.debug('Neutron is not new enough to perform early destination '
                      'host port binding activation. Port bindings will be '
                      'updated later.', instance=instance)
            return

        client = _get_ksa_client(context, admin=True)
        dest_host = migration['dest_compute']
        for vif in instance.get_network_info():
            # Not all compute migration flows use the port binding-extended
            # API yet, so first check to see if there is a binding for the
            # port and destination host.
            resp = self._get_port_binding(
                context, client, vif['id'], dest_host)
            if resp:
                if resp.json()['binding']['status'] != 'ACTIVE':
                    self.activate_port_binding(context, vif['id'], dest_host)
                    # TODO(mriedem): Do we need to call
                    # _clear_migration_port_profile? migrate_instance_finish
                    # would normally take care of clearing the "migrating_to"
                    # attribute on each port when updating the port's
                    # binding:host_id to point to the destination host.
                else:
                    # We might be racing with another thread that's handling
                    # post-migrate operations and already activated the port
                    # binding for the destination host.
                    LOG.debug('Port %s binding to destination host %s is '
                              'already ACTIVE.', vif['id'], dest_host,
                              instance=instance)
            elif resp.status_code == 404:
                # If there is no port binding record for the destination host,
                # we can safely assume none of the ports attached to the
                # instance are using the binding-extended API in this flow and
                # exit early.
                return
            else:
                # We don't raise an exception here because we assume that
                # port bindings will be updated correctly when
                # migrate_instance_finish runs.
                LOG.error('Unexpected error trying to get binding info '
                          'for port %s and destination host %s. Code: %i. '
                          'Error: %s', vif['id'], dest_host, resp.status_code,
                          resp.text)

    def migrate_instance_finish(
            self, context, instance, migration, provider_mappings):
        """Finish migrating the network of an instance.

        :param context: nova auth request context
        :param instance: Instance object being migrated
        :param migration: Migration object for the operation; used to determine
            the phase of the migration which dictates what to do with claimed
            PCI devices for SR-IOV ports
        :param provider_mappings: a dict of list of resource provider uuids
            keyed by port uuid
        """
        self._update_port_binding_for_instance(
            context, instance, migration.dest_compute, migration=migration,
            provider_mappings=provider_mappings)

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

    def _nw_info_build_network(self, context, port, networks, subnets):
        # TODO(stephenfin): Pass in an existing admin client if available.
        neutron = get_client(context, admin=True)
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
            LOG.warning("Network %(id)s not matched with the tenants "
                        "network! The ports tenant %(tenant_id)s will be "
                        "used.",
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

        physnet, tunneled = self._get_physnet_tunneled_info(
            context, neutron, port['network_id'])
        network = network_model.Network(
            id=port['network_id'],
            bridge=bridge,
            injected=CONF.flat_injected,
            label=network_name,
            tenant_id=tenant_id,
            mtu=network_mtu,
            physical_network=physnet,
            tunneled=tunneled
            )
        network['subnets'] = subnets

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

    def _build_vif_model(self, context, client, current_neutron_port,
                         networks, preexisting_port_ids):
        """Builds a ``nova.network.model.VIF`` object based on the parameters
        and current state of the port in Neutron.

        :param context: Request context.
        :param client: Neutron client.
        :param current_neutron_port: The current state of a Neutron port
            from which to build the VIF object model.
        :param networks: List of dicts which represent Neutron networks
            associated with the ports currently attached to a given server
            instance.
        :param preexisting_port_ids: List of IDs of ports attached to a
            given server instance which Nova did not create and therefore
            should not delete when the port is detached from the server.
        :return: nova.network.model.VIF object which represents a port in the
            instance network info cache.
        """
        vif_active = False
        if (current_neutron_port['admin_state_up'] is False or
            current_neutron_port['status'] == 'ACTIVE'):
            vif_active = True

        network_IPs = self._nw_info_get_ips(client,
                                            current_neutron_port)
        subnets = self._nw_info_get_subnets(context,
                                            current_neutron_port,
                                            network_IPs, client)

        devname = "tap" + current_neutron_port['id']
        devname = devname[:network_model.NIC_NAME_LEN]

        network, ovs_interfaceid = (
            self._nw_info_build_network(context, current_neutron_port,
                                        networks, subnets))
        preserve_on_delete = (current_neutron_port['id'] in
                              preexisting_port_ids)

        return network_model.VIF(
            id=current_neutron_port['id'],
            address=current_neutron_port['mac_address'],
            network=network,
            vnic_type=current_neutron_port.get('binding:vnic_type',
                                               network_model.VNIC_TYPE_NORMAL),
            type=current_neutron_port.get('binding:vif_type'),
            profile=get_binding_profile(current_neutron_port),
            details=current_neutron_port.get('binding:vif_details'),
            ovs_interfaceid=ovs_interfaceid,
            devname=devname,
            active=vif_active,
            preserve_on_delete=preserve_on_delete)

    def _build_network_info_model(self, context, instance, networks=None,
                                  port_ids=None, admin_client=None,
                                  preexisting_port_ids=None,
                                  refresh_vif_id=None, force_refresh=False):
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
        :param refresh_vif_id: Optional port ID to refresh within the existing
                        cache rather than the entire cache. This can be
                        triggered via a "network-changed" server external event
                        from Neutron.
        :param force_refresh: If ``networks`` and ``port_ids`` are both None,
                        by default the instance.info_cache will be used to
                        populate the network info. Pass ``True`` to force
                        collection of ports and networks from neutron directly.
        """

        search_opts = {'tenant_id': instance.project_id,
                       'device_id': instance.uuid, }
        if admin_client is None:
            client = get_client(context, admin=True)
        else:
            client = admin_client

        data = client.list_ports(**search_opts)

        current_neutron_ports = data.get('ports', [])

        if preexisting_port_ids is None:
            preexisting_port_ids = []
        preexisting_port_ids = set(
            preexisting_port_ids + self._get_preexisting_port_ids(instance))

        current_neutron_port_map = {}
        for current_neutron_port in current_neutron_ports:
            current_neutron_port_map[current_neutron_port['id']] = (
                current_neutron_port)

        # Figure out what kind of operation we're processing. If we're given
        # a single port to refresh then we try to optimize and update just the
        # information for that VIF in the existing cache rather than try to
        # rebuild the entire thing.
        if refresh_vif_id is not None:
            # TODO(mriedem): Consider pulling this out into it's own method.
            nw_info = instance.get_network_info()
            if nw_info:
                current_neutron_port = current_neutron_port_map.get(
                    refresh_vif_id)
                if current_neutron_port:
                    # Get the network for the port.
                    networks = self._get_available_networks(
                        context, instance.project_id,
                        [current_neutron_port['network_id']], client)
                    # Build the VIF model given the latest port information.
                    refreshed_vif = self._build_vif_model(
                        context, client, current_neutron_port, networks,
                        preexisting_port_ids)
                    for index, vif in enumerate(nw_info):
                        if vif['id'] == refresh_vif_id:
                            # Update the existing entry.
                            nw_info[index] = refreshed_vif
                            LOG.debug('Updated VIF entry in instance network '
                                      'info cache for port %s.',
                                      refresh_vif_id, instance=instance)
                            break
                    else:
                        # If it wasn't in the existing cache, add it.
                        nw_info.append(refreshed_vif)
                        LOG.debug('Added VIF to instance network info cache '
                                  'for port %s.', refresh_vif_id,
                                  instance=instance)
                else:
                    # This port is no longer associated with the instance, so
                    # simply remove it from the nw_info cache.
                    for index, vif in enumerate(nw_info):
                        if vif['id'] == refresh_vif_id:
                            LOG.info('Port %s from network info_cache is no '
                                     'longer associated with instance in '
                                     'Neutron. Removing from network '
                                     'info_cache.', refresh_vif_id,
                                     instance=instance)
                            del nw_info[index]
                            break
                return nw_info
            # else there is no existing cache and we need to build it

        # Determine if we're doing a full refresh (_heal_instance_info_cache)
        # or if we are refreshing because we have attached/detached a port.
        # TODO(mriedem); we should leverage refresh_vif_id in the latter case
        # since we are unnecessarily rebuilding the entire cache for one port
        nw_info_refresh = networks is None and port_ids is None
        if nw_info_refresh and force_refresh:
            # Use the current set of ports from neutron rather than the cache.
            port_ids = self._get_ordered_port_list(context, instance,
                                                   current_neutron_ports)
            net_ids = [current_neutron_port_map.get(port_id).get('network_id')
                       for port_id in port_ids]

            # This is copied from _gather_port_ids_and_networks.
            networks = self._get_available_networks(
                context, instance.project_id, net_ids, client)
        else:
            # We are refreshing the full cache using the existing cache rather
            # than what is currently in neutron.
            networks, port_ids = self._gather_port_ids_and_networks(
                    context, instance, networks, port_ids, client)

        nw_info = network_model.NetworkInfo()
        for port_id in port_ids:
            current_neutron_port = current_neutron_port_map.get(port_id)
            if current_neutron_port:
                vif = self._build_vif_model(
                    context, client, current_neutron_port, networks,
                    preexisting_port_ids)
                nw_info.append(vif)
            elif nw_info_refresh:
                LOG.info('Port %s from network info_cache is no '
                         'longer associated with instance in Neutron. '
                         'Removing from network info_cache.', port_id,
                         instance=instance)

        return nw_info

    def _get_ordered_port_list(self, context, instance, current_neutron_ports):
        """Returns ordered port list using nova virtual_interface data."""

        # a dict, keyed by port UUID, of the port's "index"
        # so that we can order the returned port UUIDs by the
        # original insertion order followed by any newly-attached
        # ports
        port_uuid_to_index_map = {}
        port_order_list = []
        ports_without_order = []

        # Get set of ports from nova vifs
        vifs = self.get_vifs_by_instance(context, instance)
        for port in current_neutron_ports:
            # NOTE(mjozefcz): For each port check if we have its index from
            # nova virtual_interfaces objects. If not - it seems
            # to be a new port - add it at the end of list.

            # Find port index if it was attached before.
            for vif in vifs:
                if vif.uuid == port['id']:
                    port_uuid_to_index_map[port['id']] = vif.id
                    break

            if port['id'] not in port_uuid_to_index_map:
                # Assume that it's new port and add it to the end of port list.
                ports_without_order.append(port['id'])

        # Lets sort created port order_list by given index.
        port_order_list = sorted(port_uuid_to_index_map,
                                 key=lambda k: port_uuid_to_index_map[k])

        # Add ports without order to the end of list
        port_order_list.extend(ports_without_order)

        return port_order_list

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

            # NOTE(arnaudmorin): If enable_dhcp is set on subnet, but, for
            # some reason neutron did not have any DHCP port yet, we still
            # want the network_info to be populated with a valid dhcp_server
            # value. This is mostly useful for the metadata API (which is
            # relying on this value to give network_data to the instance).
            #
            # This will also help some providers which are using external
            # DHCP servers not handled by neutron.
            # In this case, neutron will never create any DHCP port in the
            # subnet.
            #
            # Also note that we cannot set the value to None because then the
            # value would be discarded by the metadata API.
            # So the subnet gateway will be used as fallback.
            if subnet.get('enable_dhcp') and 'dhcp_server' not in subnet_dict:
                subnet_dict['dhcp_server'] = subnet['gateway_ip']

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

    def setup_instance_network_on_host(
            self, context, instance, host, migration=None,
            provider_mappings=None):
        """Setup network for specified instance on host.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param host: The host which network should be setup for instance.
        :param migration: The migration object if the instance is being
                          tracked with a migration.
        :param provider_mappings: a dict of lists of resource provider uuids
            keyed by port uuid
        """
        self._update_port_binding_for_instance(
            context, instance, host, migration, provider_mappings)

    def cleanup_instance_network_on_host(self, context, instance, host):
        """Cleanup network for specified instance on host.

        Port bindings for the given host are deleted. The ports associated
        with the instance via the port device_id field are left intact.

        :param context: The user request context.
        :param instance: Instance object with the associated ports
        :param host: host from which to delete port bindings
        :raises: PortBindingDeletionFailed if port binding deletion fails.
        """
        # First check to see if the port binding extension is supported.
        if not self.supports_port_binding_extension(context):
            LOG.info("Neutron extension '%s' is not supported; not cleaning "
                     "up port bindings for host %s.",
                     constants.PORT_BINDING_EXTENDED, host, instance=instance)
            return
        # Now get the ports associated with the instance. We go directly to
        # neutron rather than rely on the info cache just like
        # setup_networks_on_host.
        search_opts = {'device_id': instance.uuid,
                       'tenant_id': instance.project_id,
                       'fields': ['id']}  # we only need the port id
        data = self.list_ports(context, **search_opts)
        self._delete_port_bindings(context, data['ports'], host)

    def _get_pci_mapping_for_migration(self, instance, migration):
        if not instance.migration_context:
            return {}
        # In case of revert, swap old and new devices to
        # update the ports back to the original devices.
        revert = (migration and
                  migration.get('status') == 'reverted')
        return instance.migration_context.get_pci_mapping_for_migration(revert)

    def _update_port_binding_for_instance(
            self, context, instance, host, migration=None,
            provider_mappings=None):

        neutron = get_client(context, admin=True)
        search_opts = {'device_id': instance.uuid,
                       'tenant_id': instance.project_id}
        data = neutron.list_ports(**search_opts)
        pci_mapping = None
        port_updates = []
        ports = data['ports']
        FAILED_VIF_TYPES = (network_model.VIF_TYPE_UNBOUND,
                            network_model.VIF_TYPE_BINDING_FAILED)
        for p in ports:
            updates = {}
            binding_profile = get_binding_profile(p)

            # We need to update the port binding if the host has changed or if
            # the binding is clearly wrong due to previous lost messages.
            vif_type = p.get('binding:vif_type')
            if (p.get(constants.BINDING_HOST_ID) != host or
                    vif_type in FAILED_VIF_TYPES):

                updates[constants.BINDING_HOST_ID] = host
                # If the host changed, the AZ could have also changed so we
                # need to update the device_owner.
                updates['device_owner'] = (
                        'compute:%s' % instance.availability_zone)
                # NOTE: Before updating the port binding make sure we
                # remove the pre-migration status from the binding profile
                if binding_profile.get(constants.MIGRATING_ATTR):
                    del binding_profile[constants.MIGRATING_ATTR]
                    updates[constants.BINDING_PROFILE] = binding_profile

            # Update port with newly allocated PCI devices.  Even if the
            # resize is happening on the same host, a new PCI device can be
            # allocated. Note that this only needs to happen if a migration
            # is in progress such as in a resize / migrate.  It is possible
            # that this function is called without a migration object, such
            # as in an unshelve operation.
            vnic_type = p.get('binding:vnic_type')
            if (vnic_type in network_model.VNIC_TYPES_SRIOV and
                    migration is not None and
                    migration['migration_type'] != constants.LIVE_MIGRATION):
                # Note(adrianc): for live migration binding profile was already
                # updated in conductor when calling bind_ports_to_host()
                if not pci_mapping:
                    pci_mapping = self._get_pci_mapping_for_migration(
                        instance, migration)

                pci_slot = binding_profile.get('pci_slot')
                new_dev = pci_mapping.get(pci_slot)
                if new_dev:
                    binding_profile.update(
                        self._get_pci_device_profile(new_dev))
                    updates[constants.BINDING_PROFILE] = binding_profile
                else:
                    raise exception.PortUpdateFailed(port_id=p['id'],
                        reason=_("Unable to correlate PCI slot %s") %
                                 pci_slot)

            # NOTE(gibi): during live migration the conductor already sets the
            # allocation key in the port binding. However during resize, cold
            # migrate, evacuate and unshelve we have to set the binding here.
            # Also note that during unshelve no migration object is created.
            if (p.get('resource_request') and
                    (migration is None or
                     migration['migration_type'] != constants.LIVE_MIGRATION)):
                if not provider_mappings:
                    # TODO(gibi): Remove this check when compute RPC API is
                    # bumped to 6.0
                    # NOTE(gibi): This should not happen as the API level
                    # minimum compute service version check ensures that the
                    # compute services already send the RequestSpec during
                    # the move operations between the source and the
                    # destination and the dest compute calculates the
                    # mapping based on that.
                    LOG.warning(
                        "Provider mappings are not available to the compute "
                        "service but are required for ports with a resource "
                        "request. If compute RPC API versions are pinned for "
                        "a rolling upgrade, you will need to retry this "
                        "operation once the RPC version is unpinned and the "
                        "nova-compute services are all upgraded.",
                        instance=instance)
                    raise exception.PortUpdateFailed(
                        port_id=p['id'],
                        reason=_(
                            "Provider mappings are not available to the "
                            "compute service but are required for ports with "
                            "a resource request."))

                # NOTE(gibi): In the resource provider mapping there can be
                # more than one RP fulfilling a request group. But resource
                # requests of a Neutron port is always mapped to a
                # numbered request group that is always fulfilled by one
                # resource provider. So we only pass that single RP UUID here.
                binding_profile[constants.ALLOCATION] = \
                    provider_mappings[p['id']][0]
                updates[constants.BINDING_PROFILE] = binding_profile

            port_updates.append((p['id'], updates))

        # Avoid rolling back updates if we catch an error above.
        # TODO(lbeliveau): Batch up the port updates in one neutron call.
        for port_id, updates in port_updates:
            if updates:
                LOG.info("Updating port %(port)s with "
                         "attributes %(attributes)s",
                         {"port": port_id, "attributes": updates},
                         instance=instance)
                try:
                    neutron.update_port(port_id, {'port': updates})
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.exception("Unable to update binding details "
                                      "for port %s",
                                      port_id, instance=instance)

    def update_instance_vnic_index(self, context, instance, vif, index):
        """Update instance vnic index.

        When the 'VNIC index' extension is supported this method will update
        the vnic index of the instance on the port. An instance may have more
        than one vnic.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param vif: The VIF in question.
        :param index: The index on the instance for the VIF.
        """
        self._refresh_neutron_extensions_cache(context)
        if constants.VNIC_INDEX_EXT in self.extensions:
            neutron = get_client(context)
            port_req_body = {'port': {'vnic_index': index}}
            try:
                neutron.update_port(vif['id'], port_req_body)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception('Unable to update instance VNIC index '
                                  'for port %s.',
                                  vif['id'], instance=instance)


def _ensure_requested_network_ordering(accessor, unordered, preferred):
    """Sort a list with respect to the preferred network ordering."""
    if preferred:
        unordered.sort(key=lambda i: preferred.index(accessor(i)))

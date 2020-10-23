# Copyright 2010 OpenStack Foundation
# Copyright 2011 Piston Cloud Computing, Inc
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

import copy

from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
import webob
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute import helpers
from nova.api.openstack.compute.schemas import servers as schema_servers
from nova.api.openstack.compute.views import servers as views_servers
from nova.api.openstack import wsgi
from nova.api import validation
from nova import block_device
from nova.compute import api as compute
from nova.compute import flavors
from nova.compute import utils as compute_utils
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.image import api as image_api
from nova import network as network_api
from nova import objects
from nova.policies import servers as server_policies
from nova import utils

TAG_SEARCH_FILTERS = ('tags', 'tags-any', 'not-tags', 'not-tags-any')
PARTIAL_CONSTRUCT_FOR_CELL_DOWN_MIN_VERSION = '2.69'
PAGING_SORTING_PARAMS = ('sort_key', 'sort_dir', 'limit', 'marker')

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

INVALID_FLAVOR_IMAGE_EXCEPTIONS = (
    exception.BadRequirementEmulatorThreadsPolicy,
    exception.CPUThreadPolicyConfigurationInvalid,
    exception.FlavorImageConflict,
    exception.ImageCPUPinningForbidden,
    exception.ImageCPUThreadPolicyForbidden,
    exception.ImageNUMATopologyAsymmetric,
    exception.ImageNUMATopologyCPUDuplicates,
    exception.ImageNUMATopologyCPUOutOfRange,
    exception.ImageNUMATopologyCPUsUnassigned,
    exception.ImageNUMATopologyForbidden,
    exception.ImageNUMATopologyIncomplete,
    exception.ImageNUMATopologyMemoryOutOfRange,
    exception.ImageNUMATopologyRebuildConflict,
    exception.ImagePMUConflict,
    exception.ImageSerialPortNumberExceedFlavorValue,
    exception.ImageSerialPortNumberInvalid,
    exception.ImageVCPULimitsRangeExceeded,
    exception.ImageVCPUTopologyRangeExceeded,
    exception.InvalidCPUAllocationPolicy,
    exception.InvalidCPUThreadAllocationPolicy,
    exception.InvalidEmulatorThreadsPolicy,
    exception.InvalidMachineType,
    exception.InvalidNUMANodesNumber,
    exception.InvalidRequest,
    exception.MemoryPageSizeForbidden,
    exception.MemoryPageSizeInvalid,
    exception.PciInvalidAlias,
    exception.PciRequestAliasNotDefined,
    exception.RealtimeConfigurationInvalid,
    exception.RealtimeMaskNotFoundOrInvalid,
)

MIN_COMPUTE_MOVE_BANDWIDTH = 39


class ServersController(wsgi.Controller):
    """The Server API base controller class for the OpenStack API."""

    _view_builder_class = views_servers.ViewBuilder

    @staticmethod
    def _add_location(robj):
        # Just in case...
        if 'server' not in robj.obj:
            return robj

        link = [l for l in robj.obj['server']['links'] if l['rel'] == 'self']
        if link:
            robj['Location'] = link[0]['href']

        # Convenience return
        return robj

    def __init__(self):
        super(ServersController, self).__init__()
        self.compute_api = compute.API()
        self.network_api = network_api.API()

    @wsgi.expected_errors((400, 403))
    @validation.query_schema(schema_servers.query_params_v275, '2.75')
    @validation.query_schema(schema_servers.query_params_v273, '2.73', '2.74')
    @validation.query_schema(schema_servers.query_params_v266, '2.66', '2.72')
    @validation.query_schema(schema_servers.query_params_v226, '2.26', '2.65')
    @validation.query_schema(schema_servers.query_params_v21, '2.1', '2.25')
    def index(self, req):
        """Returns a list of server names and ids for a given user."""
        context = req.environ['nova.context']
        context.can(server_policies.SERVERS % 'index')
        try:
            servers = self._get_servers(req, is_detail=False)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        return servers

    @wsgi.expected_errors((400, 403))
    @validation.query_schema(schema_servers.query_params_v275, '2.75')
    @validation.query_schema(schema_servers.query_params_v273, '2.73', '2.74')
    @validation.query_schema(schema_servers.query_params_v266, '2.66', '2.72')
    @validation.query_schema(schema_servers.query_params_v226, '2.26', '2.65')
    @validation.query_schema(schema_servers.query_params_v21, '2.1', '2.25')
    def detail(self, req):
        """Returns a list of server details for a given user."""
        context = req.environ['nova.context']
        context.can(server_policies.SERVERS % 'detail')
        try:
            servers = self._get_servers(req, is_detail=True)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        return servers

    @staticmethod
    def _is_cell_down_supported(req, search_opts):
        cell_down_support = api_version_request.is_supported(
            req, min_version=PARTIAL_CONSTRUCT_FOR_CELL_DOWN_MIN_VERSION)

        if cell_down_support:
            # NOTE(tssurya): Minimal constructs would be returned from the down
            # cells if cell_down_support is True, however if filtering, sorting
            # or paging is requested by the user, then cell_down_support should
            # be made False and the down cells should be skipped (depending on
            # CONF.api.list_records_by_skipping_down_cells) as there is no
            # way to return correct results for the down cells in those
            # situations due to missing keys/information.
            # NOTE(tssurya): Since there is a chance that
            # remove_invalid_options function could have removed the paging and
            # sorting parameters, we add the additional check for that from the
            # request.
            pag_sort = any(
                ps in req.GET.keys() for ps in PAGING_SORTING_PARAMS)
            # NOTE(tssurya): ``nova list --all_tenants`` is the only
            # allowed filter exception when handling down cells.
            filters = list(search_opts.keys()) not in ([u'all_tenants'], [])
            if pag_sort or filters:
                cell_down_support = False
        return cell_down_support

    def _get_servers(self, req, is_detail):
        """Returns a list of servers, based on any search options specified."""

        search_opts = {}
        search_opts.update(req.GET)

        context = req.environ['nova.context']
        remove_invalid_options(context, search_opts,
                self._get_server_search_options(req))

        cell_down_support = self._is_cell_down_supported(req, search_opts)

        for search_opt in search_opts:
            if (search_opt in
                schema_servers.JOINED_TABLE_QUERY_PARAMS_SERVERS.keys() or
                    search_opt.startswith('_')):
                msg = _("Invalid filter field: %s.") % search_opt
                raise exc.HTTPBadRequest(explanation=msg)

        # Verify search by 'status' contains a valid status.
        # Convert it to filter by vm_state or task_state for compute_api.
        # For non-admin user, vm_state and task_state are filtered through
        # remove_invalid_options function, based on value of status field.
        # Set value to vm_state and task_state to make search simple.
        search_opts.pop('status', None)
        if 'status' in req.GET.keys():
            statuses = req.GET.getall('status')
            states = common.task_and_vm_state_from_status(statuses)
            vm_state, task_state = states
            if not vm_state and not task_state:
                if api_version_request.is_supported(req, min_version='2.38'):
                    msg = _('Invalid status value')
                    raise exc.HTTPBadRequest(explanation=msg)

                return {'servers': []}
            search_opts['vm_state'] = vm_state
            # When we search by vm state, task state will return 'default'.
            # So we don't need task_state search_opt.
            if 'default' not in task_state:
                search_opts['task_state'] = task_state

        if 'changes-since' in search_opts:
            try:
                search_opts['changes-since'] = timeutils.parse_isotime(
                    search_opts['changes-since'])
            except ValueError:
                # NOTE: This error handling is for V2.0 API to pass the
                # experimental jobs at the gate. V2.1 API covers this case
                # with JSON-Schema and it is a hard burden to apply it to
                # v2.0 API at this time.
                msg = _("Invalid filter field: changes-since.")
                raise exc.HTTPBadRequest(explanation=msg)

        if 'changes-before' in search_opts:
            try:
                search_opts['changes-before'] = timeutils.parse_isotime(
                    search_opts['changes-before'])
                changes_since = search_opts.get('changes-since')
                if changes_since and search_opts['changes-before'] < \
                        search_opts['changes-since']:
                    msg = _('The value of changes-since must be'
                            ' less than or equal to changes-before.')
                    raise exc.HTTPBadRequest(explanation=msg)
            except ValueError:
                msg = _("Invalid filter field: changes-before.")
                raise exc.HTTPBadRequest(explanation=msg)

        # By default, compute's get_all() will return deleted instances.
        # If an admin hasn't specified a 'deleted' search option, we need
        # to filter out deleted instances by setting the filter ourselves.
        # ... Unless 'changes-since' or 'changes-before' is specified,
        # because those will return recently deleted instances according to
        # the API spec.

        if 'deleted' not in search_opts:
            if 'changes-since' not in search_opts and \
                    'changes-before' not in search_opts:
                # No 'changes-since' or 'changes-before', so we only
                # want non-deleted servers
                search_opts['deleted'] = False
        else:
            # Convert deleted filter value to a valid boolean.
            # Return non-deleted servers if an invalid value
            # is passed with deleted filter.
            search_opts['deleted'] = strutils.bool_from_string(
                search_opts['deleted'], default=False)

        if search_opts.get("vm_state") == ['deleted']:
            if context.is_admin:
                search_opts['deleted'] = True
            else:
                msg = _("Only administrators may list deleted instances")
                raise exc.HTTPForbidden(explanation=msg)

        if api_version_request.is_supported(req, min_version='2.26'):
            for tag_filter in TAG_SEARCH_FILTERS:
                if tag_filter in search_opts:
                    search_opts[tag_filter] = search_opts[
                        tag_filter].split(',')

        all_tenants = common.is_all_tenants(search_opts)
        # use the boolean from here on out so remove the entry from search_opts
        # if it's present.
        # NOTE(tssurya): In case we support handling down cells
        # we need to know further down the stack whether the 'all_tenants'
        # filter was passed with the true value or not, so we pass the flag
        # further down the stack.
        search_opts.pop('all_tenants', None)

        if 'locked' in search_opts:
            search_opts['locked'] = common.is_locked(search_opts)

        elevated = None
        if all_tenants:
            if is_detail:
                context.can(server_policies.SERVERS % 'detail:get_all_tenants')
            else:
                context.can(server_policies.SERVERS % 'index:get_all_tenants')
            elevated = context.elevated()
        else:
            # As explained in lp:#1185290, if `all_tenants` is not passed
            # we must ignore the `tenant_id` search option.
            search_opts.pop('tenant_id', None)
            if context.project_id:
                search_opts['project_id'] = context.project_id
            else:
                search_opts['user_id'] = context.user_id

        limit, marker = common.get_limit_and_marker(req)
        sort_keys, sort_dirs = common.get_sort_params(req.params)
        blacklist = schema_servers.SERVER_LIST_IGNORE_SORT_KEY
        if api_version_request.is_supported(req, min_version='2.73'):
            blacklist = schema_servers.SERVER_LIST_IGNORE_SORT_KEY_V273
        sort_keys, sort_dirs = remove_invalid_sort_keys(
            context, sort_keys, sort_dirs, blacklist, ('host', 'node'))

        expected_attrs = []
        if is_detail:
            if api_version_request.is_supported(req, '2.16'):
                expected_attrs.append('services')
            if api_version_request.is_supported(req, '2.26'):
                expected_attrs.append("tags")
            if api_version_request.is_supported(req, '2.63'):
                expected_attrs.append("trusted_certs")
            if api_version_request.is_supported(req, '2.73'):
                expected_attrs.append("system_metadata")

            # merge our expected attrs with what the view builder needs for
            # showing details
            expected_attrs = self._view_builder.get_show_expected_attrs(
                                                                expected_attrs)

        try:
            instance_list = self.compute_api.get_all(elevated or context,
                    search_opts=search_opts, limit=limit, marker=marker,
                    expected_attrs=expected_attrs, sort_keys=sort_keys,
                    sort_dirs=sort_dirs, cell_down_support=cell_down_support,
                    all_tenants=all_tenants)
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.FlavorNotFound:
            LOG.debug("Flavor '%s' could not be found ",
                      search_opts['flavor'])
            instance_list = objects.InstanceList()

        if is_detail:
            instance_list._context = context
            instance_list.fill_faults()
            response = self._view_builder.detail(
                req, instance_list, cell_down_support=cell_down_support)
        else:
            response = self._view_builder.index(
                req, instance_list, cell_down_support=cell_down_support)
        return response

    def _get_server(self, context, req, instance_uuid, is_detail=False,
                    cell_down_support=False, columns_to_join=None):
        """Utility function for looking up an instance by uuid.

        :param context: request context for auth
        :param req: HTTP request.
        :param instance_uuid: UUID of the server instance to get
        :param is_detail: True if you plan on showing the details of the
            instance in the response, False otherwise.
        :param cell_down_support: True if the API (and caller) support
                                  returning a minimal instance
                                  construct if the relevant cell is
                                  down.
        :param columns_to_join: optional list of extra fields to join on the
            Instance object
        """
        expected_attrs = ['flavor', 'numa_topology']
        if is_detail:
            if api_version_request.is_supported(req, '2.26'):
                expected_attrs.append("tags")
            if api_version_request.is_supported(req, '2.63'):
                expected_attrs.append("trusted_certs")
            expected_attrs = self._view_builder.get_show_expected_attrs(
                                                            expected_attrs)
        if columns_to_join:
            expected_attrs.extend(columns_to_join)
        instance = common.get_instance(self.compute_api, context,
                                       instance_uuid,
                                       expected_attrs=expected_attrs,
                                       cell_down_support=cell_down_support)
        return instance

    @staticmethod
    def _validate_network_id(net_id, network_uuids):
        """Validates that a requested network id.

        This method performs two checks:

        1. That the network id is in the proper uuid format.
        2. That the network is not a duplicate when using nova-network.

        :param net_id: The network id to validate.
        :param network_uuids: A running list of requested network IDs that have
            passed validation already.
        :raises: webob.exc.HTTPBadRequest if validation fails
        """
        if not uuidutils.is_uuid_like(net_id):
            # NOTE(mriedem): Neutron would allow a network id with a br- prefix
            # back in Folsom so continue to honor that.
            # TODO(mriedem): Need to figure out if this is still a valid case.
            br_uuid = net_id.split('-', 1)[-1]
            if not uuidutils.is_uuid_like(br_uuid):
                msg = _("Bad networks format: network uuid is "
                        "not in proper format (%s)") % net_id
                raise exc.HTTPBadRequest(explanation=msg)

        # duplicate networks are allowed only for neutron v2.0
        if net_id in network_uuids and not utils.is_neutron():
            expl = _("Duplicate networks (%s) are not allowed") % net_id
            raise exc.HTTPBadRequest(explanation=expl)

    def _get_requested_networks(self, requested_networks):
        """Create a list of requested networks from the networks attribute."""

        # Starting in the 2.37 microversion, requested_networks is either a
        # list or a string enum with value 'auto' or 'none'. The auto/none
        # values are verified via jsonschema so we don't check them again here.
        if isinstance(requested_networks, six.string_types):
            return objects.NetworkRequestList(
                objects=[objects.NetworkRequest(
                    network_id=requested_networks)])

        networks = []
        network_uuids = []
        for network in requested_networks:
            request = objects.NetworkRequest()
            try:
                # fixed IP address is optional
                # if the fixed IP address is not provided then
                # it will use one of the available IP address from the network
                request.address = network.get('fixed_ip', None)
                request.port_id = network.get('port', None)

                request.tag = network.get('tag', None)

                if request.port_id:
                    request.network_id = None
                    if not utils.is_neutron():
                        # port parameter is only for neutron v2.0
                        msg = _("Unknown argument: port")
                        raise exc.HTTPBadRequest(explanation=msg)
                    if request.address is not None:
                        msg = _("Specified Fixed IP '%(addr)s' cannot be used "
                                "with port '%(port)s': the two cannot be "
                                "specified together.") % {
                                    "addr": request.address,
                                    "port": request.port_id}
                        raise exc.HTTPBadRequest(explanation=msg)
                else:
                    request.network_id = network['uuid']
                    self._validate_network_id(
                        request.network_id, network_uuids)
                    network_uuids.append(request.network_id)

                networks.append(request)
            except KeyError as key:
                expl = _('Bad network format: missing %s') % key
                raise exc.HTTPBadRequest(explanation=expl)
            except TypeError:
                expl = _('Bad networks format')
                raise exc.HTTPBadRequest(explanation=expl)

        return objects.NetworkRequestList(objects=networks)

    @wsgi.expected_errors(404)
    def show(self, req, id):
        """Returns server details by server id."""
        context = req.environ['nova.context']
        context.can(server_policies.SERVERS % 'show')
        cell_down_support = api_version_request.is_supported(
            req, min_version=PARTIAL_CONSTRUCT_FOR_CELL_DOWN_MIN_VERSION)
        show_server_groups = api_version_request.is_supported(
            req, min_version='2.71')

        instance = self._get_server(
            context, req, id, is_detail=True,
            cell_down_support=cell_down_support)
        return self._view_builder.show(
            req, instance, cell_down_support=cell_down_support,
            show_server_groups=show_server_groups)

    @staticmethod
    def _process_bdms_for_create(
            context, target, server_dict, create_kwargs):
        """Processes block_device_mapping(_v2) req parameters for server create

        :param context: The nova auth request context
        :param target: The target dict for ``context.can`` policy checks
        :param server_dict: The POST /servers request body "server" entry
        :param create_kwargs: dict that gets populated by this method and
            passed to nova.comptue.api.API.create()
        :raises: webob.exc.HTTPBadRequest if the request parameters are invalid
        :raises: nova.exception.Forbidden if a policy check fails
        """
        block_device_mapping_legacy = server_dict.get('block_device_mapping',
                                                      [])
        block_device_mapping_v2 = server_dict.get('block_device_mapping_v2',
                                                  [])

        if block_device_mapping_legacy and block_device_mapping_v2:
            expl = _('Using different block_device_mapping syntaxes '
                     'is not allowed in the same request.')
            raise exc.HTTPBadRequest(explanation=expl)

        if block_device_mapping_legacy:
            for bdm in block_device_mapping_legacy:
                if 'delete_on_termination' in bdm:
                    bdm['delete_on_termination'] = strutils.bool_from_string(
                        bdm['delete_on_termination'])
            create_kwargs[
                'block_device_mapping'] = block_device_mapping_legacy
            # Sets the legacy_bdm flag if we got a legacy block device mapping.
            create_kwargs['legacy_bdm'] = True
        elif block_device_mapping_v2:
            # Have to check whether --image is given, see bug 1433609
            image_href = server_dict.get('imageRef')
            image_uuid_specified = image_href is not None
            try:
                block_device_mapping = [
                    block_device.BlockDeviceDict.from_api(bdm_dict,
                        image_uuid_specified)
                    for bdm_dict in block_device_mapping_v2]
            except exception.InvalidBDMFormat as e:
                raise exc.HTTPBadRequest(explanation=e.format_message())
            create_kwargs['block_device_mapping'] = block_device_mapping
            # Unset the legacy_bdm flag if we got a block device mapping.
            create_kwargs['legacy_bdm'] = False

        block_device_mapping = create_kwargs.get("block_device_mapping")
        if block_device_mapping:
            context.can(server_policies.SERVERS % 'create:attach_volume',
                        target)

    def _process_networks_for_create(
            self, context, target, server_dict, create_kwargs):
        """Processes networks request parameter for server create

        :param context: The nova auth request context
        :param target: The target dict for ``context.can`` policy checks
        :param server_dict: The POST /servers request body "server" entry
        :param create_kwargs: dict that gets populated by this method and
            passed to nova.comptue.api.API.create()
        :raises: webob.exc.HTTPBadRequest if the request parameters are invalid
        :raises: nova.exception.Forbidden if a policy check fails
        """
        requested_networks = server_dict.get('networks', None)

        if requested_networks is not None:
            requested_networks = self._get_requested_networks(
                requested_networks)

        # Skip policy check for 'create:attach_network' if there is no
        # network allocation request.
        if requested_networks and len(requested_networks) and \
                not requested_networks.no_allocate:
            context.can(server_policies.SERVERS % 'create:attach_network',
                        target)

        create_kwargs['requested_networks'] = requested_networks

    @staticmethod
    def _process_hosts_for_create(
            context, target, server_dict, create_kwargs, host, node):
        """Processes hosts request parameter for server create

        :param context: The nova auth request context
        :param target: The target dict for ``context.can`` policy checks
        :param server_dict: The POST /servers request body "server" entry
        :param create_kwargs: dict that gets populated by this method and
            passed to nova.comptue.api.API.create()
        :param host: Forced host of availability_zone
        :param node: Forced node of availability_zone
        :raise: webob.exc.HTTPBadRequest if the request parameters are invalid
        :raise: nova.exception.Forbidden if a policy check fails
        """
        requested_host = server_dict.get('host')
        requested_hypervisor_hostname = server_dict.get('hypervisor_hostname')
        if requested_host or requested_hypervisor_hostname:
            # If the policy check fails, this will raise Forbidden exception.
            context.can(server_policies.REQUESTED_DESTINATION, target=target)
            if host or node:
                msg = _("One mechanism with host and/or "
                        "hypervisor_hostname and another mechanism "
                        "with zone:host:node are mutually exclusive.")
                raise exc.HTTPBadRequest(explanation=msg)
        create_kwargs['requested_host'] = requested_host
        create_kwargs['requested_hypervisor_hostname'] = (
            requested_hypervisor_hostname)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 409))
    @validation.schema(schema_servers.base_create_v20, '2.0', '2.0')
    @validation.schema(schema_servers.base_create, '2.1', '2.18')
    @validation.schema(schema_servers.base_create_v219, '2.19', '2.31')
    @validation.schema(schema_servers.base_create_v232, '2.32', '2.32')
    @validation.schema(schema_servers.base_create_v233, '2.33', '2.36')
    @validation.schema(schema_servers.base_create_v237, '2.37', '2.41')
    @validation.schema(schema_servers.base_create_v242, '2.42', '2.51')
    @validation.schema(schema_servers.base_create_v252, '2.52', '2.56')
    @validation.schema(schema_servers.base_create_v257, '2.57', '2.62')
    @validation.schema(schema_servers.base_create_v263, '2.63', '2.66')
    @validation.schema(schema_servers.base_create_v267, '2.67', '2.73')
    @validation.schema(schema_servers.base_create_v274, '2.74')
    def create(self, req, body):
        """Creates a new server for a given user."""
        context = req.environ['nova.context']
        server_dict = body['server']
        password = self._get_server_admin_password(server_dict)
        name = common.normalize_name(server_dict['name'])
        description = name
        if api_version_request.is_supported(req, min_version='2.19'):
            description = server_dict.get('description')

        # Arguments to be passed to instance create function
        create_kwargs = {}

        create_kwargs['user_data'] = server_dict.get('user_data')
        # NOTE(alex_xu): The v2.1 API compat mode, we strip the spaces for
        # keypair create. But we didn't strip spaces at here for
        # backward-compatible some users already created keypair and name with
        # leading/trailing spaces by legacy v2 API.
        create_kwargs['key_name'] = server_dict.get('key_name')
        create_kwargs['config_drive'] = server_dict.get('config_drive')
        security_groups = server_dict.get('security_groups')
        if security_groups is not None:
            create_kwargs['security_groups'] = [
                sg['name'] for sg in security_groups if sg.get('name')]
            create_kwargs['security_groups'] = list(
                set(create_kwargs['security_groups']))

        scheduler_hints = {}
        if 'os:scheduler_hints' in body:
            scheduler_hints = body['os:scheduler_hints']
        elif 'OS-SCH-HNT:scheduler_hints' in body:
            scheduler_hints = body['OS-SCH-HNT:scheduler_hints']
        create_kwargs['scheduler_hints'] = scheduler_hints

        # min_count and max_count are optional.  If they exist, they may come
        # in as strings.  Verify that they are valid integers and > 0.
        # Also, we want to default 'min_count' to 1, and default
        # 'max_count' to be 'min_count'.
        min_count = int(server_dict.get('min_count', 1))
        max_count = int(server_dict.get('max_count', min_count))
        if min_count > max_count:
            msg = _('min_count must be <= max_count')
            raise exc.HTTPBadRequest(explanation=msg)
        create_kwargs['min_count'] = min_count
        create_kwargs['max_count'] = max_count

        availability_zone = server_dict.pop("availability_zone", None)

        if api_version_request.is_supported(req, min_version='2.52'):
            create_kwargs['tags'] = server_dict.get('tags')

        helpers.translate_attributes(helpers.CREATE,
                                     server_dict, create_kwargs)

        target = {
            'project_id': context.project_id,
            'user_id': context.user_id,
            'availability_zone': availability_zone}
        context.can(server_policies.SERVERS % 'create', target)

        # Skip policy check for 'create:trusted_certs' if no trusted
        # certificate IDs were provided.
        trusted_certs = server_dict.get('trusted_image_certificates', None)
        if trusted_certs:
            create_kwargs['trusted_certs'] = trusted_certs
            context.can(server_policies.SERVERS % 'create:trusted_certs',
                        target=target)

        parse_az = self.compute_api.parse_availability_zone
        try:
            availability_zone, host, node = parse_az(context,
                                                     availability_zone)
        except exception.InvalidInput as err:
            raise exc.HTTPBadRequest(explanation=six.text_type(err))
        if host or node:
            context.can(server_policies.SERVERS % 'create:forced_host', {})

        if api_version_request.is_supported(req, min_version='2.74'):
            self._process_hosts_for_create(context, target, server_dict,
                                           create_kwargs, host, node)

        self._process_bdms_for_create(
            context, target, server_dict, create_kwargs)

        image_uuid = self._image_from_req_data(server_dict, create_kwargs)

        self._process_networks_for_create(
            context, target, server_dict, create_kwargs)

        flavor_id = self._flavor_id_from_req_data(body)
        try:
            inst_type = flavors.get_flavor_by_flavor_id(
                    flavor_id, ctxt=context, read_deleted="no")

            supports_multiattach = common.supports_multiattach_volume(req)
            supports_port_resource_request = \
                common.supports_port_resource_request(req)
            (instances, resv_id) = self.compute_api.create(context,
                inst_type,
                image_uuid,
                display_name=name,
                display_description=description,
                availability_zone=availability_zone,
                forced_host=host, forced_node=node,
                metadata=server_dict.get('metadata', {}),
                admin_password=password,
                check_server_group_quota=True,
                supports_multiattach=supports_multiattach,
                supports_port_resource_request=supports_port_resource_request,
                **create_kwargs)
        except (exception.QuotaError,
                exception.PortLimitExceeded) as error:
            raise exc.HTTPForbidden(
                explanation=error.format_message())
        except exception.ImageNotFound:
            msg = _("Can not find requested image")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.KeypairNotFound:
            msg = _("Invalid key_name provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.ConfigDriveInvalidValue:
            msg = _("Invalid config_drive provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except (exception.BootFromVolumeRequiredForZeroDiskFlavor,
                exception.ExternalNetworkAttachForbidden) as error:
            raise exc.HTTPForbidden(explanation=error.format_message())
        except messaging.RemoteError as err:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': err.exc_type,
                                                 'err_msg': err.value}
            raise exc.HTTPBadRequest(explanation=msg)
        except UnicodeDecodeError as error:
            msg = "UnicodeError: %s" % error
            raise exc.HTTPBadRequest(explanation=msg)
        except (exception.ImageNotActive,
                exception.ImageBadRequest,
                exception.ImageNotAuthorized,
                exception.ImageUnacceptable,
                exception.FixedIpNotFoundForAddress,
                exception.FlavorNotFound,
                exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.InvalidMetadata,
                exception.InvalidVolume,
                exception.MultiplePortsNotApplicable,
                exception.InvalidFixedIpAndMaxCountRequest,
                exception.InstanceUserDataMalformed,
                exception.PortNotFound,
                exception.FixedIpAlreadyInUse,
                exception.SecurityGroupNotFound,
                exception.PortRequiresFixedIP,
                exception.NetworkRequiresSubnet,
                exception.NetworkNotFound,
                exception.InvalidBDM,
                exception.InvalidBDMSnapshot,
                exception.InvalidBDMVolume,
                exception.InvalidBDMImage,
                exception.InvalidBDMBootSequence,
                exception.InvalidBDMLocalsLimit,
                exception.InvalidBDMVolumeNotBootable,
                exception.InvalidBDMEphemeralSize,
                exception.InvalidBDMFormat,
                exception.InvalidBDMSwapSize,
                exception.InvalidBDMDiskBus,
                exception.VolumeTypeNotFound,
                exception.AutoDiskConfigDisabledByImage,
                exception.InstanceGroupNotFound,
                exception.SnapshotNotFound,
                exception.UnableToAutoAllocateNetwork,
                exception.MultiattachNotSupportedOldMicroversion,
                exception.CertificateValidationFailed,
                exception.CreateWithPortResourceRequestOldVersion,
                exception.ComputeHostNotFound) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except INVALID_FLAVOR_IMAGE_EXCEPTIONS as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except (exception.PortInUse,
                exception.InstanceExists,
                exception.NetworkAmbiguous,
                exception.NoUniqueMatch,
                exception.VolumeTypeSupportNotYetAvailable) as error:
            raise exc.HTTPConflict(explanation=error.format_message())

        # If the caller wanted a reservation_id, return it
        if server_dict.get('return_reservation_id', False):
            return wsgi.ResponseObject({'reservation_id': resv_id})

        server = self._view_builder.create(req, instances[0])

        if CONF.api.enable_instance_password:
            server['server']['adminPass'] = password

        robj = wsgi.ResponseObject(server)

        return self._add_location(robj)

    def _delete(self, context, req, instance_uuid):
        instance = self._get_server(context, req, instance_uuid)
        context.can(server_policies.SERVERS % 'delete',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        if CONF.reclaim_instance_interval:
            try:
                self.compute_api.soft_delete(context, instance)
            except exception.InstanceInvalidState:
                # Note(yufang521247): instance which has never been active
                # is not allowed to be soft_deleted. Thus we have to call
                # delete() to clean up the instance.
                self.compute_api.delete(context, instance)
        else:
            self.compute_api.delete(context, instance)

    @wsgi.expected_errors(404)
    @validation.schema(schema_servers.base_update_v20, '2.0', '2.0')
    @validation.schema(schema_servers.base_update, '2.1', '2.18')
    @validation.schema(schema_servers.base_update_v219, '2.19')
    def update(self, req, id, body):
        """Update server then pass on to version-specific controller."""

        ctxt = req.environ['nova.context']
        update_dict = {}
        instance = self._get_server(ctxt, req, id, is_detail=True)
        ctxt.can(server_policies.SERVERS % 'update',
                 target={'user_id': instance.user_id,
                         'project_id': instance.project_id})
        show_server_groups = api_version_request.is_supported(
                 req, min_version='2.71')

        server = body['server']

        if 'name' in server:
            update_dict['display_name'] = common.normalize_name(
                server['name'])

        if 'description' in server:
            # This is allowed to be None (remove description)
            update_dict['display_description'] = server['description']

        helpers.translate_attributes(helpers.UPDATE, server, update_dict)

        try:
            instance = self.compute_api.update_instance(ctxt, instance,
                                                        update_dict)

            # NOTE(gmann): Starting from microversion 2.75, PUT and Rebuild
            # API response will show all attributes like GET /servers API.
            show_all_attributes = api_version_request.is_supported(
                req, min_version='2.75')
            extend_address = show_all_attributes
            show_AZ = show_all_attributes
            show_config_drive = show_all_attributes
            show_keypair = show_all_attributes
            show_srv_usg = show_all_attributes
            show_sec_grp = show_all_attributes
            show_extended_status = show_all_attributes
            show_extended_volumes = show_all_attributes
            # NOTE(gmann): Below attributes need to be added in response
            # if respective policy allows.So setting these as None
            # to perform the policy check in view builder.
            show_extended_attr = None if show_all_attributes else False
            show_host_status = None if show_all_attributes else False

            return self._view_builder.show(
                req, instance,
                extend_address=extend_address,
                show_AZ=show_AZ,
                show_config_drive=show_config_drive,
                show_extended_attr=show_extended_attr,
                show_host_status=show_host_status,
                show_keypair=show_keypair,
                show_srv_usg=show_srv_usg,
                show_sec_grp=show_sec_grp,
                show_extended_status=show_extended_status,
                show_extended_volumes=show_extended_volumes,
                show_server_groups=show_server_groups)
        except exception.InstanceNotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)

    # NOTE(gmann): Returns 204 for backwards compatibility but should be 202
    # for representing async API as this API just accepts the request and
    # request hypervisor driver to complete the same in async mode.
    @wsgi.response(204)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('confirmResize')
    def _action_confirm_resize(self, req, id, body):
        context = req.environ['nova.context']
        context.can(server_policies.SERVERS % 'confirm_resize')
        instance = self._get_server(context, req, id)
        try:
            self.compute_api.confirm_resize(context, instance)
        except exception.MigrationNotFound:
            msg = _("Instance has not been resized.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'confirmResize', id)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('revertResize')
    def _action_revert_resize(self, req, id, body):
        context = req.environ['nova.context']
        context.can(server_policies.SERVERS % 'revert_resize')
        instance = self._get_server(context, req, id)
        try:
            self.compute_api.revert_resize(context, instance)
        except exception.MigrationNotFound:
            msg = _("Instance has not been resized.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.FlavorNotFound:
            msg = _("Flavor used by the instance could not be found.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'revertResize', id)

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('reboot')
    @validation.schema(schema_servers.reboot)
    def _action_reboot(self, req, id, body):

        reboot_type = body['reboot']['type'].upper()
        context = req.environ['nova.context']
        context.can(server_policies.SERVERS % 'reboot')
        instance = self._get_server(context, req, id)

        try:
            self.compute_api.reboot(context, instance, reboot_type)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'reboot', id)

    def _resize(self, req, instance_id, flavor_id, **kwargs):
        """Begin the resize process with given instance/flavor."""
        context = req.environ["nova.context"]
        instance = self._get_server(context, req, instance_id,
                                    columns_to_join=['services'])
        context.can(server_policies.SERVERS % 'resize',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})

        if common.instance_has_port_with_resource_request(
                instance_id, self.network_api):
            # TODO(gibi): Remove when nova only supports compute newer than
            # Train
            source_service = objects.Service.get_by_host_and_binary(
                context, instance.host, 'nova-compute')
            if source_service.version < MIN_COMPUTE_MOVE_BANDWIDTH:
                msg = _("The resize action on a server with ports having "
                        "resource requests, like a port with a QoS "
                        "minimum bandwidth policy, is not yet supported.")
                raise exc.HTTPConflict(explanation=msg)

        try:
            self.compute_api.resize(context, instance, flavor_id, **kwargs)
        except exception.QuotaError as error:
            raise exc.HTTPForbidden(
                explanation=error.format_message())
        except (exception.InstanceIsLocked,
                exception.AllocationMoveFailed,
                exception.InstanceNotReady,
                exception.ServiceUnavailable) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'resize', instance_id)
        except exception.ImageNotAuthorized:
            msg = _("You are not authorized to access the image "
                    "the instance was started with.")
            raise exc.HTTPUnauthorized(explanation=msg)
        except exception.ImageNotFound:
            msg = _("Image that the instance was started "
                    "with could not be found.")
            raise exc.HTTPBadRequest(explanation=msg)
        except (exception.AutoDiskConfigDisabledByImage,
                exception.CannotResizeDisk,
                exception.CannotResizeToSameFlavor,
                exception.FlavorNotFound,
                exception.NoValidHost) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except INVALID_FLAVOR_IMAGE_EXCEPTIONS as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.Invalid:
            msg = _("Invalid instance image.")
            raise exc.HTTPBadRequest(explanation=msg)

    @wsgi.response(204)
    @wsgi.expected_errors((404, 409))
    def delete(self, req, id):
        """Destroys a server."""
        try:
            self._delete(req.environ['nova.context'], req, id)
        except exception.InstanceNotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except (exception.InstanceIsLocked,
                exception.AllocationDeleteFailed) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete', id)

    def _image_from_req_data(self, server_dict, create_kwargs):
        """Get image data from the request or raise appropriate
        exceptions.

        The field imageRef is mandatory when no block devices have been
        defined and must be a proper uuid when present.
        """
        image_href = server_dict.get('imageRef')

        if not image_href and create_kwargs.get('block_device_mapping'):
            return ''
        elif image_href:
            return image_href
        else:
            msg = _("Missing imageRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)

    def _flavor_id_from_req_data(self, data):
        flavor_ref = data['server']['flavorRef']
        return common.get_id_from_href(flavor_ref)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 401, 403, 404, 409))
    @wsgi.action('resize')
    @validation.schema(schema_servers.resize)
    def _action_resize(self, req, id, body):
        """Resizes a given instance to the flavor size requested."""
        resize_dict = body['resize']
        flavor_ref = str(resize_dict["flavorRef"])

        kwargs = {}
        helpers.translate_attributes(helpers.RESIZE, resize_dict, kwargs)

        self._resize(req, id, flavor_ref, **kwargs)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('rebuild')
    @validation.schema(schema_servers.base_rebuild_v20, '2.0', '2.0')
    @validation.schema(schema_servers.base_rebuild, '2.1', '2.18')
    @validation.schema(schema_servers.base_rebuild_v219, '2.19', '2.53')
    @validation.schema(schema_servers.base_rebuild_v254, '2.54', '2.56')
    @validation.schema(schema_servers.base_rebuild_v257, '2.57', '2.62')
    @validation.schema(schema_servers.base_rebuild_v263, '2.63')
    def _action_rebuild(self, req, id, body):
        """Rebuild an instance with the given attributes."""
        rebuild_dict = body['rebuild']

        image_href = rebuild_dict["imageRef"]

        password = self._get_server_admin_password(rebuild_dict)

        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)
        target = {'user_id': instance.user_id,
                  'project_id': instance.project_id}
        context.can(server_policies.SERVERS % 'rebuild', target=target)
        attr_map = {
            'name': 'display_name',
            'description': 'display_description',
            'metadata': 'metadata',
        }

        kwargs = {}

        helpers.translate_attributes(helpers.REBUILD, rebuild_dict, kwargs)

        if (api_version_request.is_supported(req, min_version='2.54') and
                'key_name' in rebuild_dict):
            kwargs['key_name'] = rebuild_dict.get('key_name')

        # If user_data is not specified, we don't include it in kwargs because
        # we don't want to overwrite the existing user_data.
        include_user_data = api_version_request.is_supported(
            req, min_version='2.57')
        if include_user_data and 'user_data' in rebuild_dict:
            kwargs['user_data'] = rebuild_dict['user_data']

        # Skip policy check for 'rebuild:trusted_certs' if no trusted
        # certificate IDs were provided.
        if ((api_version_request.is_supported(req, min_version='2.63')) and
                # Note that this is different from server create since with
                # rebuild a user can unset/reset the trusted certs by
                # specifying trusted_image_certificates=None, similar to
                # key_name.
                ('trusted_image_certificates' in rebuild_dict)):
            kwargs['trusted_certs'] = rebuild_dict.get(
                'trusted_image_certificates')
            context.can(server_policies.SERVERS % 'rebuild:trusted_certs',
                        target=target)

        for request_attribute, instance_attribute in attr_map.items():
            try:
                if request_attribute == 'name':
                    kwargs[instance_attribute] = common.normalize_name(
                        rebuild_dict[request_attribute])
                else:
                    kwargs[instance_attribute] = rebuild_dict[
                        request_attribute]
            except (KeyError, TypeError):
                pass

        try:
            self.compute_api.rebuild(context,
                                     instance,
                                     image_href,
                                     password,
                                     **kwargs)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'rebuild', id)
        except exception.InstanceNotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.ImageNotFound:
            msg = _("Cannot find image for rebuild")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.KeypairNotFound:
            msg = _("Invalid key_name provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.QuotaError as error:
            raise exc.HTTPForbidden(explanation=error.format_message())
        except (exception.AutoDiskConfigDisabledByImage,
                exception.CertificateValidationFailed,
                exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.ImageNotActive,
                exception.ImageUnacceptable,
                exception.InvalidMetadata,
                exception.InvalidVolume,
                ) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except INVALID_FLAVOR_IMAGE_EXCEPTIONS as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

        instance = self._get_server(context, req, id, is_detail=True)

        # NOTE(liuyulong): set the new key_name for the API response.
        # from microversion 2.54 onwards.
        show_keypair = api_version_request.is_supported(
                           req, min_version='2.54')
        show_server_groups = api_version_request.is_supported(
                           req, min_version='2.71')

        # NOTE(gmann): Starting from microversion 2.75, PUT and Rebuild
        # API response will show all attributes like GET /servers API.
        show_all_attributes = api_version_request.is_supported(
            req, min_version='2.75')
        extend_address = show_all_attributes
        show_AZ = show_all_attributes
        show_config_drive = show_all_attributes
        show_srv_usg = show_all_attributes
        show_sec_grp = show_all_attributes
        show_extended_status = show_all_attributes
        show_extended_volumes = show_all_attributes
        # NOTE(gmann): Below attributes need to be added in response
        # if respective policy allows.So setting these as None
        # to perform the policy check in view builder.
        show_extended_attr = None if show_all_attributes else False
        show_host_status = None if show_all_attributes else False

        view = self._view_builder.show(
            req, instance,
            extend_address=extend_address,
            show_AZ=show_AZ,
            show_config_drive=show_config_drive,
            show_extended_attr=show_extended_attr,
            show_host_status=show_host_status,
            show_keypair=show_keypair,
            show_srv_usg=show_srv_usg,
            show_sec_grp=show_sec_grp,
            show_extended_status=show_extended_status,
            show_extended_volumes=show_extended_volumes,
            show_server_groups=show_server_groups,
            # NOTE(gmann): user_data has been added in response (by code at
            # the end of this API method) since microversion 2.57 so tell
            # view builder not to include it.
            show_user_data=False)

        # Add on the admin_password attribute since the view doesn't do it
        # unless instance passwords are disabled
        if CONF.api.enable_instance_password:
            view['server']['adminPass'] = password

        if include_user_data:
            view['server']['user_data'] = instance.user_data

        robj = wsgi.ResponseObject(view)
        return self._add_location(robj)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('createImage')
    @validation.schema(schema_servers.create_image, '2.0', '2.0')
    @validation.schema(schema_servers.create_image, '2.1')
    def _action_create_image(self, req, id, body):
        """Snapshot a server instance."""
        context = req.environ['nova.context']
        context.can(server_policies.SERVERS % 'create_image')

        entity = body["createImage"]
        image_name = common.normalize_name(entity["name"])
        metadata = entity.get('metadata', {})

        # Starting from microversion 2.39 we don't check quotas on createImage
        if api_version_request.is_supported(
                req, max_version=
                api_version_request.MAX_IMAGE_META_PROXY_API_VERSION):
            common.check_img_metadata_properties_quota(context, metadata)

        instance = self._get_server(context, req, id)

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

        try:
            if compute_utils.is_volume_backed_instance(context, instance,
                                                          bdms):
                context.can(server_policies.SERVERS %
                    'create_image:allow_volume_backed')
                image = self.compute_api.snapshot_volume_backed(
                                                       context,
                                                       instance,
                                                       image_name,
                                                       extra_properties=
                                                       metadata)
            else:
                image = self.compute_api.snapshot(context,
                                                  instance,
                                                  image_name,
                                                  extra_properties=metadata)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                        'createImage', id)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        except exception.OverQuota as e:
            raise exc.HTTPForbidden(explanation=e.format_message())

        # Starting with microversion 2.45 we return a response body containing
        # the snapshot image id without the Location header.
        if api_version_request.is_supported(req, '2.45'):
            return {'image_id': image['id']}

        # build location of newly-created image entity
        image_id = str(image['id'])
        image_ref = image_api.API().generate_image_url(image_id, context)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    def _get_server_admin_password(self, server):
        """Determine the admin password for a server on creation."""
        if 'adminPass' in server:
            password = server['adminPass']
        else:
            password = utils.generate_password()
        return password

    def _get_server_search_options(self, req):
        """Return server search options allowed by non-admin."""
        # NOTE(mriedem): all_tenants is admin-only by default but because of
        # tight-coupling between this method, the remove_invalid_options method
        # and how _get_servers uses them, we include all_tenants here but it
        # will be removed later for non-admins. Fixing this would be nice but
        # probably not trivial.
        opt_list = ('reservation_id', 'name', 'status', 'image', 'flavor',
                    'ip', 'changes-since', 'all_tenants')
        if api_version_request.is_supported(req, min_version='2.5'):
            opt_list += ('ip6',)
        if api_version_request.is_supported(req, min_version='2.26'):
            opt_list += TAG_SEARCH_FILTERS
        if api_version_request.is_supported(req, min_version='2.66'):
            opt_list += ('changes-before',)
        if api_version_request.is_supported(req, min_version='2.73'):
            opt_list += ('locked',)
        return opt_list

    def _get_instance(self, context, instance_uuid):
        try:
            attrs = ['system_metadata', 'metadata']
            mapping = objects.InstanceMapping.get_by_instance_uuid(
                context, instance_uuid)
            nova_context.set_target_cell(context, mapping.cell_mapping)
            return objects.Instance.get_by_uuid(
                context, instance_uuid, expected_attrs=attrs)
        except (exception.InstanceNotFound,
                exception.InstanceMappingNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('os-start')
    def _start_server(self, req, id, body):
        """Start an instance."""
        context = req.environ['nova.context']
        instance = self._get_instance(context, id)
        context.can(server_policies.SERVERS % 'start', instance)
        try:
            self.compute_api.start(context, instance)
        except (exception.InstanceNotReady, exception.InstanceIsLocked) as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                'start', id)

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('os-stop')
    def _stop_server(self, req, id, body):
        """Stop an instance."""
        context = req.environ['nova.context']
        instance = self._get_instance(context, id)
        context.can(server_policies.SERVERS % 'stop',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        try:
            self.compute_api.stop(context, instance)
        except (exception.InstanceNotReady, exception.InstanceIsLocked) as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                'stop', id)

    @wsgi.Controller.api_version("2.17")
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('trigger_crash_dump')
    @validation.schema(schema_servers.trigger_crash_dump)
    def _action_trigger_crash_dump(self, req, id, body):
        """Trigger crash dump in an instance"""
        context = req.environ['nova.context']
        instance = self._get_instance(context, id)
        context.can(server_policies.SERVERS % 'trigger_crash_dump',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        try:
            self.compute_api.trigger_crash_dump(context, instance)
        except (exception.InstanceNotReady, exception.InstanceIsLocked) as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                'trigger_crash_dump', id)


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not permitted unless policy allows."""

    if context.can(server_policies.SERVERS % 'allow_all_filters',
                   fatal=False):
        # Only remove parameters for sorting and pagination
        for key in PAGING_SORTING_PARAMS:
            search_options.pop(key, None)
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
                        if opt not in allowed_search_options]
    if unknown_options:
        LOG.debug("Removing options '%s' from query",
                  ", ".join(unknown_options))
        for opt in unknown_options:
            search_options.pop(opt, None)


def remove_invalid_sort_keys(context, sort_keys, sort_dirs,
                             blacklist, admin_only_fields):
    key_list = copy.deepcopy(sort_keys)
    for key in key_list:
        # NOTE(Kevin Zheng): We are intend to remove the sort_key
        # in the blacklist and its' corresponding sort_dir, since
        # the sort_key and sort_dir are not strict to be provide
        # in pairs in the current implement, sort_dirs could be
        # less than sort_keys, in order to avoid IndexError, we
        # only pop sort_dir when number of sort_dirs is no less
        # than the sort_key index.
        if key in blacklist:
            if len(sort_dirs) > sort_keys.index(key):
                sort_dirs.pop(sort_keys.index(key))
            sort_keys.pop(sort_keys.index(key))
        elif key in admin_only_fields and not context.is_admin:
            msg = _("Only administrators can sort servers "
                    "by %s") % key
            raise exc.HTTPForbidden(explanation=msg)

    return sort_keys, sort_dirs

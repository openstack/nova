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
from nova.api.openstack.compute import block_device_mapping
from nova.api.openstack.compute import block_device_mapping_v1
from nova.api.openstack.compute import config_drive
from nova.api.openstack.compute import helpers
from nova.api.openstack.compute import keypairs
from nova.api.openstack.compute import multiple_create
from nova.api.openstack.compute import scheduler_hints
from nova.api.openstack.compute.schemas import servers as schema_servers
from nova.api.openstack.compute import security_groups
from nova.api.openstack.compute import user_data
from nova.api.openstack.compute.views import servers as views_servers
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova.compute import flavors
from nova.compute import utils as compute_utils
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.image import api as image_api
from nova import objects
from nova.objects import service as service_obj
from nova.policies import servers as server_policies
from nova import utils

TAG_SEARCH_FILTERS = ('tags', 'tags-any', 'not-tags', 'not-tags-any')
DEVICE_TAGGING_MIN_COMPUTE_VERSION = 14

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class ServersController(wsgi.Controller):
    """The Server API base controller class for the OpenStack API."""

    _view_builder_class = views_servers.ViewBuilder

    schema_server_create = schema_servers.base_create
    schema_server_update = schema_servers.base_update
    schema_server_rebuild = schema_servers.base_rebuild

    schema_server_create_v20 = schema_servers.base_create_v20
    schema_server_update_v20 = schema_servers.base_update_v20
    schema_server_rebuild_v20 = schema_servers.base_rebuild_v20

    schema_server_create_v219 = schema_servers.base_create_v219
    schema_server_update_v219 = schema_servers.base_update_v219
    schema_server_rebuild_v219 = schema_servers.base_rebuild_v219
    schema_server_rebuild_v254 = schema_servers.base_rebuild_v254
    schema_server_rebuild_v257 = schema_servers.base_rebuild_v257

    schema_server_create_v232 = schema_servers.base_create_v232
    schema_server_create_v237 = schema_servers.base_create_v237
    schema_server_create_v242 = schema_servers.base_create_v242
    schema_server_create_v252 = schema_servers.base_create_v252
    schema_server_create_v257 = schema_servers.base_create_v257

    # NOTE(alex_xu): Please do not add more items into this list. This list
    # should be removed in the future.
    schema_func_list = [
        block_device_mapping.get_server_create_schema,
        block_device_mapping_v1.get_server_create_schema,
        config_drive.get_server_create_schema,
        keypairs.get_server_create_schema,
        multiple_create.get_server_create_schema,
        scheduler_hints.get_server_create_schema,
        security_groups.get_server_create_schema,
        user_data.get_server_create_schema,
    ]

    # NOTE(alex_xu): Please do not add more items into this list. This list
    # should be removed in the future.
    server_create_func_list = [
        block_device_mapping.server_create,
        block_device_mapping_v1.server_create,
        config_drive.server_create,
        keypairs.server_create,
        multiple_create.server_create,
        scheduler_hints.server_create,
        security_groups.server_create,
        user_data.server_create,
    ]

    @staticmethod
    def _add_location(robj):
        # Just in case...
        if 'server' not in robj.obj:
            return robj

        link = [l for l in robj.obj['server']['links'] if l['rel'] == 'self']
        if link:
            robj['Location'] = utils.utf8(link[0]['href'])

        # Convenience return
        return robj

    def __init__(self, **kwargs):

        super(ServersController, self).__init__(**kwargs)
        self.compute_api = compute.API()

        # TODO(alex_xu): The final goal is that merging all of
        # extended json-schema into server main json-schema.
        self._create_schema(self.schema_server_create_v257, '2.57')
        self._create_schema(self.schema_server_create_v252, '2.52')
        self._create_schema(self.schema_server_create_v242, '2.42')
        self._create_schema(self.schema_server_create_v237, '2.37')
        self._create_schema(self.schema_server_create_v232, '2.32')
        self._create_schema(self.schema_server_create_v219, '2.19')
        self._create_schema(self.schema_server_create, '2.1')
        self._create_schema(self.schema_server_create_v20, '2.0')

    @wsgi.expected_errors((400, 403))
    @validation.query_schema(schema_servers.query_params_v226, '2.26')
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
    @validation.query_schema(schema_servers.query_params_v226, '2.26')
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

    def _get_servers(self, req, is_detail):
        """Returns a list of servers, based on any search options specified."""

        search_opts = {}
        search_opts.update(req.GET)

        context = req.environ['nova.context']
        remove_invalid_options(context, search_opts,
                self._get_server_search_options(req))

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
            search_opts['changes-since'] = timeutils.parse_isotime(
                search_opts['changes-since'])

        # By default, compute's get_all() will return deleted instances.
        # If an admin hasn't specified a 'deleted' search option, we need
        # to filter out deleted instances by setting the filter ourselves.
        # ... Unless 'changes-since' is specified, because 'changes-since'
        # should return recently deleted instances according to the API spec.

        if 'deleted' not in search_opts:
            if 'changes-since' not in search_opts:
                # No 'changes-since', so we only want non-deleted servers
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

        # If tenant_id is passed as a search parameter this should
        # imply that all_tenants is also enabled unless explicitly
        # disabled. Note that the tenant_id parameter is filtered out
        # by remove_invalid_options above unless the requestor is an
        # admin.

        # TODO(gmann): 'all_tenants' flag should not be required while
        # searching with 'tenant_id'. Ref bug# 1185290
        # +microversions to achieve above mentioned behavior by
        # uncommenting below code.

        # if 'tenant_id' in search_opts and 'all_tenants' not in search_opts:
            # We do not need to add the all_tenants flag if the tenant
            # id associated with the token is the tenant id
            # specified. This is done so a request that does not need
            # the all_tenants flag does not fail because of lack of
            # policy permission for compute:get_all_tenants when it
            # doesn't actually need it.
            # if context.project_id != search_opts.get('tenant_id'):
            #    search_opts['all_tenants'] = 1

        all_tenants = common.is_all_tenants(search_opts)
        # use the boolean from here on out so remove the entry from search_opts
        # if it's present
        search_opts.pop('all_tenants', None)

        elevated = None
        if all_tenants:
            if is_detail:
                context.can(server_policies.SERVERS % 'detail:get_all_tenants')
            else:
                context.can(server_policies.SERVERS % 'index:get_all_tenants')
            elevated = context.elevated()
        else:
            # As explained in lp:#1185290, if `all_tenants` is not passed
            # we must ignore the `tenant_id` search option. As explained
            # in a above code comment, any change to this behavior would
            # require a microversion bump.
            search_opts.pop('tenant_id', None)
            if context.project_id:
                search_opts['project_id'] = context.project_id
            else:
                search_opts['user_id'] = context.user_id

        limit, marker = common.get_limit_and_marker(req)
        sort_keys, sort_dirs = common.get_sort_params(req.params)
        sort_keys, sort_dirs = remove_invalid_sort_keys(
            context, sort_keys, sort_dirs,
            schema_servers.SERVER_LIST_IGNORE_SORT_KEY, ('host', 'node'))

        expected_attrs = []
        if is_detail:
            expected_attrs.append('services')
            if api_version_request.is_supported(req, '2.26'):
                expected_attrs.append("tags")

            # merge our expected attrs with what the view builder needs for
            # showing details
            expected_attrs = self._view_builder.get_show_expected_attrs(
                                                                expected_attrs)

        try:
            instance_list = self.compute_api.get_all(elevated or context,
                    search_opts=search_opts, limit=limit, marker=marker,
                    expected_attrs=expected_attrs,
                    sort_keys=sort_keys, sort_dirs=sort_dirs)
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
            response = self._view_builder.detail(req, instance_list)
        else:
            response = self._view_builder.index(req, instance_list)
        req.cache_db_instances(instance_list)
        return response

    def _get_server(self, context, req, instance_uuid, is_detail=False):
        """Utility function for looking up an instance by uuid.

        :param context: request context for auth
        :param req: HTTP request. The instance is cached in this request.
        :param instance_uuid: UUID of the server instance to get
        :param is_detail: True if you plan on showing the details of the
            instance in the response, False otherwise.
        """
        expected_attrs = ['flavor', 'numa_topology']
        if is_detail:
            if api_version_request.is_supported(req, '2.26'):
                expected_attrs.append("tags")
            expected_attrs = self._view_builder.get_show_expected_attrs(
                                                            expected_attrs)
        instance = common.get_instance(self.compute_api, context,
                                       instance_uuid,
                                       expected_attrs=expected_attrs)
        req.cache_db_instance(instance)
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

    def _get_requested_networks(self, requested_networks,
                                supports_device_tagging=False):
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
                if request.tag and not supports_device_tagging:
                    msg = _('Network interface tags are not yet supported.')
                    raise exc.HTTPBadRequest(explanation=msg)

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
        instance = self._get_server(context, req, id, is_detail=True)
        return self._view_builder.show(req, instance)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 409))
    @validation.schema(schema_server_create_v20, '2.0', '2.0')
    @validation.schema(schema_server_create, '2.1', '2.18')
    @validation.schema(schema_server_create_v219, '2.19', '2.31')
    @validation.schema(schema_server_create_v232, '2.32', '2.36')
    @validation.schema(schema_server_create_v237, '2.37', '2.41')
    @validation.schema(schema_server_create_v242, '2.42', '2.51')
    @validation.schema(schema_server_create_v252, '2.52', '2.56')
    @validation.schema(schema_server_create_v257, '2.57')
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

        # TODO(alex_xu): This is for back-compatible with stevedore
        # extension interface. But the final goal is that merging
        # all of extended code into ServersController.
        self._create_by_func_list(server_dict, create_kwargs, body)

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

        # TODO(Shao He, Feng) move this policy check to os-availability-zone
        # extension after refactor it.
        parse_az = self.compute_api.parse_availability_zone
        try:
            availability_zone, host, node = parse_az(context,
                                                     availability_zone)
        except exception.InvalidInput as err:
            raise exc.HTTPBadRequest(explanation=six.text_type(err))
        if host or node:
            context.can(server_policies.SERVERS % 'create:forced_host', {})

        min_compute_version = service_obj.get_minimum_version_all_cells(
            nova_context.get_admin_context(), ['nova-compute'])
        supports_device_tagging = (min_compute_version >=
                                   DEVICE_TAGGING_MIN_COMPUTE_VERSION)

        block_device_mapping = create_kwargs.get("block_device_mapping")
        # TODO(Shao He, Feng) move this policy check to os-block-device-mapping
        # extension after refactor it.
        if block_device_mapping:
            context.can(server_policies.SERVERS % 'create:attach_volume',
                        target)
            for bdm in block_device_mapping:
                if bdm.get('tag', None) and not supports_device_tagging:
                    msg = _('Block device tags are not yet supported.')
                    raise exc.HTTPBadRequest(explanation=msg)

        image_uuid = self._image_from_req_data(server_dict, create_kwargs)

        # NOTE(cyeoh): Although upper layer can set the value of
        # return_reservation_id in order to request that a reservation
        # id be returned to the client instead of the newly created
        # instance information we do not want to pass this parameter
        # to the compute create call which always returns both. We use
        # this flag after the instance create call to determine what
        # to return to the client
        return_reservation_id = create_kwargs.pop('return_reservation_id',
                                                  False)

        requested_networks = server_dict.get('networks', None)

        if requested_networks is not None:
            requested_networks = self._get_requested_networks(
                requested_networks, supports_device_tagging)

        # Skip policy check for 'create:attach_network' if there is no
        # network allocation request.
        if requested_networks and len(requested_networks) and \
                not requested_networks.no_allocate:
            context.can(server_policies.SERVERS % 'create:attach_network',
                        target)

        flavor_id = self._flavor_id_from_req_data(body)
        try:
            inst_type = flavors.get_flavor_by_flavor_id(
                    flavor_id, ctxt=context, read_deleted="no")

            supports_multiattach = common.supports_multiattach_volume(req)
            (instances, resv_id) = self.compute_api.create(context,
                            inst_type,
                            image_uuid,
                            display_name=name,
                            display_description=description,
                            availability_zone=availability_zone,
                            forced_host=host, forced_node=node,
                            metadata=server_dict.get('metadata', {}),
                            admin_password=password,
                            requested_networks=requested_networks,
                            check_server_group_quota=True,
                            supports_multiattach=supports_multiattach,
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
        except exception.ExternalNetworkAttachForbidden as error:
            raise exc.HTTPForbidden(explanation=error.format_message())
        except messaging.RemoteError as err:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': err.exc_type,
                                                 'err_msg': err.value}
            raise exc.HTTPBadRequest(explanation=msg)
        except UnicodeDecodeError as error:
            msg = "UnicodeError: %s" % error
            raise exc.HTTPBadRequest(explanation=msg)
        except (exception.CPUThreadPolicyConfigurationInvalid,
                exception.ImageNotActive,
                exception.ImageBadRequest,
                exception.ImageNotAuthorized,
                exception.FixedIpNotFoundForAddress,
                exception.FlavorNotFound,
                exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.InvalidMetadata,
                exception.InvalidRequest,
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
                exception.AutoDiskConfigDisabledByImage,
                exception.ImageCPUPinningForbidden,
                exception.ImageCPUThreadPolicyForbidden,
                exception.ImageNUMATopologyIncomplete,
                exception.ImageNUMATopologyForbidden,
                exception.ImageNUMATopologyAsymmetric,
                exception.ImageNUMATopologyCPUOutOfRange,
                exception.ImageNUMATopologyCPUDuplicates,
                exception.ImageNUMATopologyCPUsUnassigned,
                exception.ImageNUMATopologyMemoryOutOfRange,
                exception.InvalidNUMANodesNumber,
                exception.InstanceGroupNotFound,
                exception.MemoryPageSizeInvalid,
                exception.MemoryPageSizeForbidden,
                exception.PciRequestAliasNotDefined,
                exception.RealtimeConfigurationInvalid,
                exception.RealtimeMaskNotFoundOrInvalid,
                exception.SnapshotNotFound,
                exception.UnableToAutoAllocateNetwork,
                exception.MultiattachNotSupportedOldMicroversion) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except (exception.PortInUse,
                exception.InstanceExists,
                exception.NetworkAmbiguous,
                exception.NoUniqueMatch,
                exception.MultiattachSupportNotYetAvailable) as error:
            raise exc.HTTPConflict(explanation=error.format_message())

        # If the caller wanted a reservation_id, return it
        if return_reservation_id:
            return wsgi.ResponseObject({'reservation_id': resv_id})

        req.cache_db_instances(instances)
        server = self._view_builder.create(req, instances[0])

        if CONF.api.enable_instance_password:
            server['server']['adminPass'] = password

        robj = wsgi.ResponseObject(server)

        return self._add_location(robj)

    # NOTE(gmann): Parameter 'req_body' is placed to handle scheduler_hint
    # extension for V2.1. No other extension supposed to use this as
    # it will be removed soon.
    def _create_by_func_list(self, server_dict,
                             create_kwargs, req_body):
        for func in self.server_create_func_list:
            func(server_dict, create_kwargs, req_body)

    def _create_schema(self, create_schema, version):
        for schema_func in self.schema_func_list:
            self._create_schema_by_func(create_schema, version, schema_func)

    def _create_schema_by_func(self, create_schema, version, schema_func):
        schema = schema_func(version)

        if (schema_func.__module__ ==
                'nova.api.openstack.compute.scheduler_hints'):
            # NOTE(oomichi): The request parameter position of scheduler-hint
            # extension is different from the other extensions, so here handles
            # the difference.
            create_schema['properties'].update(schema)
        else:
            create_schema['properties']['server']['properties'].update(schema)

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
    @validation.schema(schema_server_update_v20, '2.0', '2.0')
    @validation.schema(schema_server_update, '2.1', '2.18')
    @validation.schema(schema_server_update_v219, '2.19')
    def update(self, req, id, body):
        """Update server then pass on to version-specific controller."""

        ctxt = req.environ['nova.context']
        update_dict = {}
        instance = self._get_server(ctxt, req, id, is_detail=True)
        ctxt.can(server_policies.SERVERS % 'update',
                 target={'user_id': instance.user_id,
                         'project_id': instance.project_id})

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
            return self._view_builder.show(req, instance,
                                           extend_address=False)
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
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
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
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
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
        instance = self._get_server(context, req, instance_id)
        context.can(server_policies.SERVERS % 'resize',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})

        try:
            self.compute_api.resize(context, instance, flavor_id, **kwargs)
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.QuotaError as error:
            raise exc.HTTPForbidden(
                explanation=error.format_message())
        except exception.InstanceIsLocked as e:
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
                exception.NoValidHost,
                exception.PciRequestAliasNotDefined) as e:
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
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
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
    @validation.schema(schema_server_rebuild_v20, '2.0', '2.0')
    @validation.schema(schema_server_rebuild, '2.1', '2.18')
    @validation.schema(schema_server_rebuild_v219, '2.19', '2.53')
    @validation.schema(schema_server_rebuild_v254, '2.54', '2.56')
    @validation.schema(schema_server_rebuild_v257, '2.57')
    def _action_rebuild(self, req, id, body):
        """Rebuild an instance with the given attributes."""
        rebuild_dict = body['rebuild']

        image_href = rebuild_dict["imageRef"]

        password = self._get_server_admin_password(rebuild_dict)

        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)
        context.can(server_policies.SERVERS % 'rebuild',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        attr_map = {
            'name': 'display_name',
            'description': 'display_description',
            'metadata': 'metadata',
        }

        kwargs = {}

        helpers.translate_attributes(helpers.REBUILD, rebuild_dict, kwargs)

        if (api_version_request.is_supported(req, min_version='2.54')
                and 'key_name' in rebuild_dict):
            kwargs['key_name'] = rebuild_dict.get('key_name')

        # If user_data is not specified, we don't include it in kwargs because
        # we don't want to overwrite the existing user_data.
        include_user_data = api_version_request.is_supported(
            req, min_version='2.57')
        if include_user_data and 'user_data' in rebuild_dict:
            kwargs['user_data'] = rebuild_dict['user_data']

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
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.ImageNotFound:
            msg = _("Cannot find image for rebuild")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.KeypairNotFound:
            msg = _("Invalid key_name provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.QuotaError as error:
            raise exc.HTTPForbidden(explanation=error.format_message())
        except (exception.ImageNotActive,
                exception.ImageUnacceptable,
                exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.InvalidMetadata,
                exception.AutoDiskConfigDisabledByImage) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

        instance = self._get_server(context, req, id, is_detail=True)

        view = self._view_builder.show(req, instance, extend_address=False)

        # Add on the admin_password attribute since the view doesn't do it
        # unless instance passwords are disabled
        if CONF.api.enable_instance_password:
            view['server']['adminPass'] = password

        if api_version_request.is_supported(req, min_version='2.54'):
            # NOTE(liuyulong): set the new key_name for the API response.
            view['server']['key_name'] = instance.key_name

        if include_user_data:
            view['server']['user_data'] = instance.user_data

        robj = wsgi.ResponseObject(view)
        return self._add_location(robj)

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('createImage')
    @common.check_snapshots_enabled
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
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
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
        opt_list = ('reservation_id', 'name', 'status', 'image', 'flavor',
                    'ip', 'changes-since', 'all_tenants')
        if api_version_request.is_supported(req, min_version='2.5'):
            opt_list += ('ip6',)
        if api_version_request.is_supported(req, min_version='2.26'):
            opt_list += TAG_SEARCH_FILTERS
        return opt_list

    def _get_instance(self, context, instance_uuid):
        try:
            attrs = ['system_metadata', 'metadata']
            if not CONF.cells.enable:
                # NOTE(danms): We can't target a cell database if we're
                # in cellsv1 otherwise we'll short-circuit the replication.
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
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
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
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
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
        except exception.TriggerCrashDumpNotSupported as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context."""
    if context.is_admin:
        # Only remove parameters for sorting and pagination
        for key in ('sort_key', 'sort_dir', 'limit', 'marker'):
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

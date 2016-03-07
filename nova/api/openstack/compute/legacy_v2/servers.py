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

import base64
import re
import sys

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.views import servers as views_servers
from nova.api.openstack import wsgi
from nova import block_device
from nova import compute
from nova.compute import flavors
from nova import exception
from nova.i18n import _
from nova import objects
from nova import policy
from nova import utils


server_opts = [
    cfg.BoolOpt('enable_instance_password',
                default=True,
                help='Enables returning of the instance password by the'
                     ' relevant server API calls such as create, rebuild'
                     ' or rescue, If the hypervisor does not support'
                     ' password injection then the password returned will'
                     ' not be correct'),
]
CONF = cfg.CONF
CONF.register_opts(server_opts)
CONF.import_opt('reclaim_instance_interval', 'nova.compute.manager')

LOG = logging.getLogger(__name__)

CREATE_EXCEPTIONS = {
    exception.InvalidMetadataSize: exc.HTTPRequestEntityTooLarge,
    exception.ImageNotFound: exc.HTTPBadRequest,
    exception.FlavorNotFound: exc.HTTPBadRequest,
    exception.KeypairNotFound: exc.HTTPBadRequest,
    exception.ConfigDriveInvalidValue: exc.HTTPBadRequest,
    exception.ImageNotActive: exc.HTTPBadRequest,
    exception.FlavorDiskTooSmall: exc.HTTPBadRequest,
    exception.FlavorMemoryTooSmall: exc.HTTPBadRequest,
    exception.NetworkNotFound: exc.HTTPBadRequest,
    exception.PortNotFound: exc.HTTPBadRequest,
    exception.FixedIpAlreadyInUse: exc.HTTPBadRequest,
    exception.SecurityGroupNotFound: exc.HTTPBadRequest,
    exception.InstanceUserDataTooLarge: exc.HTTPBadRequest,
    exception.InstanceUserDataMalformed: exc.HTTPBadRequest,
    exception.ImageNUMATopologyIncomplete: exc.HTTPBadRequest,
    exception.ImageNUMATopologyForbidden: exc.HTTPBadRequest,
    exception.ImageNUMATopologyAsymmetric: exc.HTTPBadRequest,
    exception.ImageNUMATopologyCPUOutOfRange: exc.HTTPBadRequest,
    exception.ImageNUMATopologyCPUDuplicates: exc.HTTPBadRequest,
    exception.ImageNUMATopologyCPUsUnassigned: exc.HTTPBadRequest,
    exception.ImageNUMATopologyMemoryOutOfRange: exc.HTTPBadRequest,
    exception.PortInUse: exc.HTTPConflict,
    exception.InstanceExists: exc.HTTPConflict,
    exception.NoUniqueMatch: exc.HTTPConflict,
    exception.Invalid: exc.HTTPBadRequest,
    exception.InstanceGroupNotFound: exc.HTTPBadRequest,
}

CREATE_EXCEPTIONS_MSGS = {
    exception.ImageNotFound: _("Can not find requested image"),
    exception.FlavorNotFound: _("Invalid flavorRef provided."),
    exception.KeypairNotFound: _("Invalid key_name provided."),
    exception.ConfigDriveInvalidValue: _("Invalid config_drive provided."),
}


class Controller(wsgi.Controller):
    """The Server API base controller class for the OpenStack API."""

    _view_builder_class = views_servers.ViewBuilder

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

    def __init__(self, ext_mgr=None, **kwargs):
        super(Controller, self).__init__(**kwargs)
        self.compute_api = compute.API()
        self.ext_mgr = ext_mgr

    def index(self, req):
        """Returns a list of server names and ids for a given user."""
        try:
            servers = self._get_servers(req, is_detail=False)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        return servers

    def detail(self, req):
        """Returns a list of server details for a given user."""
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
                self._get_server_search_options())

        # Verify search by 'status' contains a valid status.
        # Convert it to filter by vm_state or task_state for compute_api.
        search_opts.pop('status', None)
        if 'status' in req.GET.keys():
            statuses = req.GET.getall('status')
            states = common.task_and_vm_state_from_status(statuses)
            vm_state, task_state = states
            if not vm_state and not task_state:
                return {'servers': []}
            search_opts['vm_state'] = vm_state
            # When we search by vm state, task state will return 'default'.
            # So we don't need task_state search_opt.
            if 'default' not in task_state:
                search_opts['task_state'] = task_state

        if 'changes-since' in search_opts:
            try:
                parsed = timeutils.parse_isotime(search_opts['changes-since'])
            except ValueError:
                msg = _('Invalid changes-since value')
                raise exc.HTTPBadRequest(explanation=msg)
            search_opts['changes-since'] = parsed

        # By default, compute's get_all() will return deleted instances.
        # If an admin hasn't specified a 'deleted' search option, we need
        # to filter out deleted instances by setting the filter ourselves.
        # ... Unless 'changes-since' is specified, because 'changes-since'
        # should return recently deleted images according to the API spec.

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

        all_tenants = common.is_all_tenants(search_opts)
        # use the boolean from here on out so remove the entry from search_opts
        # if it's present
        search_opts.pop('all_tenants', None)

        elevated = None
        if all_tenants:
            policy.enforce(context, 'compute:get_all_tenants',
                           {'project_id': context.project_id,
                            'user_id': context.user_id})
            elevated = context.elevated()
        else:
            if context.project_id:
                search_opts['project_id'] = context.project_id
            else:
                search_opts['user_id'] = context.user_id

        limit, marker = common.get_limit_and_marker(req)
        # Sorting by multiple keys and directions is conditionally enabled
        sort_keys, sort_dirs = None, None
        if self.ext_mgr.is_loaded('os-server-sort-keys'):
            sort_keys, sort_dirs = common.get_sort_params(req.params)

        expected_attrs = None
        if is_detail:
            # merge our expected attrs with what the view builder needs for
            # showing details
            expected_attrs = self._view_builder.get_show_expected_attrs(
                                                                expected_attrs)

        try:
            instance_list = self.compute_api.get_all(elevated or context,
                    search_opts=search_opts, limit=limit, marker=marker,
                    want_objects=True, expected_attrs=expected_attrs,
                    sort_keys=sort_keys, sort_dirs=sort_dirs)
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.FlavorNotFound:
            LOG.debug("Flavor '%s' could not be found", search_opts['flavor'])
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
        expected_attrs = ['flavor']
        if is_detail:
            expected_attrs = self._view_builder.get_show_expected_attrs(
                                                            expected_attrs)
        instance = common.get_instance(self.compute_api, context,
                                       instance_uuid,
                                       expected_attrs=expected_attrs)
        req.cache_db_instance(instance)
        return instance

    def _check_string_length(self, value, name, max_length=None):
        try:
            if isinstance(value, six.string_types):
                value = value.strip()
            utils.check_string_length(value, name, min_length=1,
                                      max_length=max_length)
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    def _validate_server_name(self, value):
        self._check_string_length(value, 'Server name', max_length=255)

    def _get_injected_files(self, personality):
        """Create a list of injected files from the personality attribute.

        At this time, injected_files must be formatted as a list of
        (file_path, file_content) pairs for compatibility with the
        underlying compute service.
        """
        injected_files = []

        for item in personality:
            try:
                path = item['path']
                contents = item['contents']
            except KeyError as key:
                expl = _('Bad personality format: missing %s') % key
                raise exc.HTTPBadRequest(explanation=expl)
            except TypeError:
                expl = _('Bad personality format')
                raise exc.HTTPBadRequest(explanation=expl)
            if self._decode_base64(contents) is None:
                expl = _('Personality content for %s cannot be decoded') % path
                raise exc.HTTPBadRequest(explanation=expl)
            injected_files.append((path, contents))
        return injected_files

    def _get_requested_networks(self, requested_networks):
        """Create a list of requested networks from the networks attribute."""
        networks = []
        network_uuids = []
        for network in requested_networks:
            request = objects.NetworkRequest()
            try:
                try:
                    request.port_id = network.get('port', None)
                except ValueError:
                    msg = _("Bad port format: port uuid is "
                            "not in proper format "
                            "(%s)") % network.get('port')
                    raise exc.HTTPBadRequest(explanation=msg)
                if request.port_id:
                    request.network_id = None
                    if not utils.is_neutron():
                        # port parameter is only for neutron v2.0
                        msg = _("Unknown argument : port")
                        raise exc.HTTPBadRequest(explanation=msg)
                else:
                    request.network_id = network['uuid']

                if (not request.port_id and not
                        uuidutils.is_uuid_like(request.network_id)):
                    br_uuid = request.network_id.split('-', 1)[-1]
                    if not uuidutils.is_uuid_like(br_uuid):
                        msg = _("Bad networks format: network uuid is "
                                "not in proper format "
                                "(%s)") % request.network_id
                        raise exc.HTTPBadRequest(explanation=msg)

                # fixed IP address is optional
                # if the fixed IP address is not provided then
                # it will use one of the available IP address from the network
                try:
                    request.address = network.get('fixed_ip', None)
                except ValueError:
                    msg = (_("Invalid fixed IP address (%s)") %
                           network.get('fixed_ip'))
                    raise exc.HTTPBadRequest(explanation=msg)

                # duplicate networks are allowed only for neutron v2.0
                if (not utils.is_neutron() and request.network_id and
                        request.network_id in network_uuids):
                    expl = (_("Duplicate networks"
                              " (%s) are not allowed") %
                            request.network_id)
                    raise exc.HTTPBadRequest(explanation=expl)
                network_uuids.append(request.network_id)
                networks.append(request)
            except KeyError as key:
                expl = _('Bad network format: missing %s') % key
                raise exc.HTTPBadRequest(explanation=expl)
            except TypeError:
                expl = _('Bad networks format')
                raise exc.HTTPBadRequest(explanation=expl)

        return objects.NetworkRequestList(objects=networks)

    # NOTE(vish): Without this regex, b64decode will happily
    #             ignore illegal bytes in the base64 encoded
    #             data.
    B64_REGEX = re.compile('^(?:[A-Za-z0-9+\/]{4})*'
                           '(?:[A-Za-z0-9+\/]{2}=='
                           '|[A-Za-z0-9+\/]{3}=)?$')

    def _decode_base64(self, data):
        if isinstance(data, six.binary_type) and hasattr(data, "decode"):
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError:
                return None
        data = re.sub(r'\s', '', data)
        if not self.B64_REGEX.match(data):
            return None
        try:
            return base64.b64decode(data)
        except TypeError:
            return None

    def _validate_access_ipv4(self, address):
        if not netutils.is_valid_ipv4(address):
            expl = _('accessIPv4 is not proper IPv4 format')
            raise exc.HTTPBadRequest(explanation=expl)

    def _validate_access_ipv6(self, address):
        if not netutils.is_valid_ipv6(address):
            expl = _('accessIPv6 is not proper IPv6 format')
            raise exc.HTTPBadRequest(explanation=expl)

    def show(self, req, id):
        """Returns server details by server id."""
        context = req.environ['nova.context']
        instance = self._get_server(context, req, id, is_detail=True)
        return self._view_builder.show(req, instance)

    def _extract(self, server_dict, ext_name, key):
        if self.ext_mgr.is_loaded(ext_name):
            return server_dict.get(key)
        return None

    def _validate_user_data(self, user_data):
        if user_data and self._decode_base64(user_data) is None:
            expl = _('Userdata content cannot be decoded')
            raise exc.HTTPBadRequest(explanation=expl)
        return user_data

    def _extract_bdm(self, server_dict, image_uuid_specified):
        legacy_bdm = True
        block_device_mapping_v2 = None
        if not self.ext_mgr.is_loaded('os-volumes'):
            return legacy_bdm, None
        block_device_mapping = server_dict.get('block_device_mapping', [])
        if not isinstance(block_device_mapping, list):
            msg = _('block_device_mapping must be a list')
            raise exc.HTTPBadRequest(explanation=msg)
        for bdm in block_device_mapping:
            try:
                block_device.validate_device_name(bdm.get("device_name"))
                block_device.validate_and_default_volume_size(bdm)
            except exception.InvalidBDMFormat as e:
                raise exc.HTTPBadRequest(explanation=e.format_message())

            if 'delete_on_termination' in bdm:
                bdm['delete_on_termination'] = strutils.bool_from_string(
                    bdm['delete_on_termination'])

        if self.ext_mgr.is_loaded('os-block-device-mapping-v2-boot'):
            # Consider the new data format for block device mapping
            block_device_mapping_v2 = server_dict.get(
                'block_device_mapping_v2', [])
            # NOTE (ndipanov):  Disable usage of both legacy and new
            #                   block device format in the same request
            if block_device_mapping and block_device_mapping_v2:
                expl = _('Using different block_device_mapping syntaxes '
                         'is not allowed in the same request.')
                raise exc.HTTPBadRequest(explanation=expl)

            if not isinstance(block_device_mapping_v2, list):
                msg = _('block_device_mapping_v2 must be a list')
                raise exc.HTTPBadRequest(explanation=msg)

            # Assume legacy format
            legacy_bdm = not bool(block_device_mapping_v2)

            try:
                block_device_mapping_v2 = [
                    block_device.BlockDeviceDict.from_api(bdm_dict,
                        image_uuid_specified)
                    for bdm_dict in block_device_mapping_v2]
            except exception.InvalidBDMFormat as e:
                raise exc.HTTPBadRequest(explanation=e.format_message())

        bdm = (block_device_mapping or block_device_mapping_v2)
        return legacy_bdm, bdm

    @staticmethod
    def _resolve_exception(matches):
        """We want the most specific exception class."""
        while len(matches) > 1:
            first = matches[0]
            second = matches[1]
            if issubclass(first, second):
                del matches[1]
            else:
                del matches[0]
        return matches[0]

    @staticmethod
    def _handle_create_exception(*exc_info):
        """The `CREATE_EXCEPTIONS` dict containing the relationships between
        the nova exceptions and the webob exception classes to be raised is
        defined at the top of this file.
        """
        error = exc_info[1]
        err_cls = error.__class__
        cls_to_raise = CREATE_EXCEPTIONS.get(err_cls)
        if cls_to_raise is None:
            # The error is a subclass of one of the dict keys
            to_raise = [val for key, val in CREATE_EXCEPTIONS.items()
                        if isinstance(error, key)]
            if len(to_raise) > 1:
                cls_to_raise = Controller._resolve_exception(to_raise)
            elif not to_raise:
                # Not any of the expected exceptions, so re-raise
                six.reraise(*exc_info)
            else:
                cls_to_raise = to_raise[0]

        for key, val in CREATE_EXCEPTIONS_MSGS.items():
            if isinstance(error, key):
                raise cls_to_raise(explanation=CREATE_EXCEPTIONS_MSGS[key])
        raise cls_to_raise(explanation=error.format_message())

    def _determine_requested_networks(self, server_dict):
        requested_networks = None
        if (self.ext_mgr.is_loaded('os-networks')
                or utils.is_neutron()):
            requested_networks = server_dict.get('networks')

        if requested_networks is not None:
            if not isinstance(requested_networks, list):
                expl = _('Bad networks format')
                raise exc.HTTPBadRequest(explanation=expl)
            requested_networks = self._get_requested_networks(
                requested_networks)
        return requested_networks

    @wsgi.response(202)
    def create(self, req, body):
        """Creates a new server for a given user."""
        if not self.is_valid_body(body, 'server'):
            raise exc.HTTPUnprocessableEntity()

        context = req.environ['nova.context']
        server_dict = body['server']
        password = self._get_server_admin_password(server_dict)

        if 'name' not in server_dict:
            msg = _("Server name is not defined")
            raise exc.HTTPBadRequest(explanation=msg)

        name = server_dict['name']
        self._validate_server_name(name)
        name = name.strip()

        image_uuid = self._image_from_req_data(body)

        personality = server_dict.get('personality')
        config_drive = None
        if self.ext_mgr.is_loaded('os-config-drive'):
            config_drive = server_dict.get('config_drive')

        injected_files = []
        if personality:
            injected_files = self._get_injected_files(personality)

        sg_names = []
        if self.ext_mgr.is_loaded('os-security-groups'):
            security_groups = server_dict.get('security_groups')
            if security_groups is not None:
                try:
                    sg_names = [sg['name'] for sg in security_groups
                                if sg.get('name')]
                except AttributeError:
                    msg = _("Invalid input for field/attribute %(path)s."
                           " Value: %(value)s. %(message)s") % {
                               'path': 'security_groups',
                               'value': security_groups,
                               'message': ''
                           }
                    raise exc.HTTPBadRequest(explanation=msg)
        if not sg_names:
            sg_names.append('default')

        sg_names = list(set(sg_names))

        requested_networks = self._determine_requested_networks(server_dict)

        (access_ip_v4, ) = server_dict.get('accessIPv4'),
        if access_ip_v4 is not None:
            self._validate_access_ipv4(access_ip_v4)

        (access_ip_v6, ) = server_dict.get('accessIPv6'),
        if access_ip_v6 is not None:
            self._validate_access_ipv6(access_ip_v6)

        flavor_id = self._flavor_id_from_req_data(body)

        # optional openstack extensions:
        key_name = self._extract(server_dict, 'os-keypairs', 'key_name')
        availability_zone = self._extract(server_dict, 'os-availability-zone',
                                          'availability_zone')
        user_data = self._extract(server_dict, 'os-user-data', 'user_data')
        self._validate_user_data(user_data)

        image_uuid_specified = bool(image_uuid)
        legacy_bdm, block_device_mapping = self._extract_bdm(server_dict,
            image_uuid_specified)

        ret_resv_id = False
        # min_count and max_count are optional.  If they exist, they may come
        # in as strings.  Verify that they are valid integers and > 0.
        # Also, we want to default 'min_count' to 1, and default
        # 'max_count' to be 'min_count'.
        min_count = 1
        max_count = 1
        if self.ext_mgr.is_loaded('os-multiple-create'):
            ret_resv_id = server_dict.get('return_reservation_id', False)
            min_count = server_dict.get('min_count', 1)
            max_count = server_dict.get('max_count', min_count)

        try:
            min_count = utils.validate_integer(
                min_count, "min_count", min_value=1)
            max_count = utils.validate_integer(
                max_count, "max_count", min_value=1)
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        if min_count > max_count:
            msg = _('min_count must be <= max_count')
            raise exc.HTTPBadRequest(explanation=msg)

        auto_disk_config = False
        if self.ext_mgr.is_loaded('OS-DCF'):
            auto_disk_config = server_dict.get('auto_disk_config')

        scheduler_hints = {}
        if self.ext_mgr.is_loaded('OS-SCH-HNT'):
            scheduler_hints = server_dict.get('scheduler_hints', {})
        parse_az = self.compute_api.parse_availability_zone
        availability_zone, host, node = parse_az(context, availability_zone)

        check_server_group_quota = self.ext_mgr.is_loaded(
                'os-server-group-quotas')
        try:
            _get_inst_type = flavors.get_flavor_by_flavor_id
            inst_type = _get_inst_type(flavor_id, ctxt=context,
                                       read_deleted="no")

            (instances, resv_id) = self.compute_api.create(context,
                        inst_type,
                        image_uuid,
                        display_name=name,
                        display_description=name,
                        key_name=key_name,
                        metadata=server_dict.get('metadata', {}),
                        access_ip_v4=access_ip_v4,
                        access_ip_v6=access_ip_v6,
                        injected_files=injected_files,
                        admin_password=password,
                        min_count=min_count,
                        max_count=max_count,
                        requested_networks=requested_networks,
                        security_group=sg_names,
                        user_data=user_data,
                        availability_zone=availability_zone,
                        forced_host=host, forced_node=node,
                        config_drive=config_drive,
                        block_device_mapping=block_device_mapping,
                        auto_disk_config=auto_disk_config,
                        scheduler_hints=scheduler_hints,
                        legacy_bdm=legacy_bdm,
                        check_server_group_quota=check_server_group_quota)
        except (exception.QuotaError,
                exception.PortLimitExceeded) as error:
            raise exc.HTTPForbidden(
                explanation=error.format_message())
        except messaging.RemoteError as err:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': err.exc_type,
                                                 'err_msg': err.value}
            raise exc.HTTPBadRequest(explanation=msg)
        except UnicodeDecodeError as error:
            msg = "UnicodeError: %s" % error
            raise exc.HTTPBadRequest(explanation=msg)
        except Exception:
            # The remaining cases can be handled in a standard fashion.
            self._handle_create_exception(*sys.exc_info())

        # If the caller wanted a reservation_id, return it
        if ret_resv_id:
            return wsgi.ResponseObject({'reservation_id': resv_id})

        req.cache_db_instances(instances)
        server = self._view_builder.create(req, instances[0])

        if CONF.enable_instance_password:
            server['server']['adminPass'] = password

        robj = wsgi.ResponseObject(server)

        return self._add_location(robj)

    def _delete(self, context, req, instance_uuid):
        instance = self._get_server(context, req, instance_uuid)
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

    def update(self, req, id, body):
        """Update server then pass on to version-specific controller."""
        if not self.is_valid_body(body, 'server'):
            raise exc.HTTPUnprocessableEntity()

        ctxt = req.environ['nova.context']
        update_dict = {}

        if 'name' in body['server']:
            name = body['server']['name']
            self._validate_server_name(name)
            update_dict['display_name'] = name.strip()

        if 'accessIPv4' in body['server']:
            access_ipv4 = body['server']['accessIPv4']
            if access_ipv4:
                self._validate_access_ipv4(access_ipv4)
            update_dict['access_ip_v4'] = (
                access_ipv4 and access_ipv4.strip() or None)

        if 'accessIPv6' in body['server']:
            access_ipv6 = body['server']['accessIPv6']
            if access_ipv6:
                self._validate_access_ipv6(access_ipv6)
            update_dict['access_ip_v6'] = (
                access_ipv6 and access_ipv6.strip() or None)

        if 'auto_disk_config' in body['server']:
            auto_disk_config = strutils.bool_from_string(
                    body['server']['auto_disk_config'])
            update_dict['auto_disk_config'] = auto_disk_config

        if 'hostId' in body['server']:
            msg = _("HostId cannot be updated.")
            raise exc.HTTPBadRequest(explanation=msg)

        if 'personality' in body['server']:
            msg = _("Personality cannot be updated.")
            raise exc.HTTPBadRequest(explanation=msg)

        instance = self._get_server(ctxt, req, id, is_detail=True)
        try:
            policy.enforce(ctxt, 'compute:update', instance)
            instance.update(update_dict)
            # Note instance.save can throw a NotFound exception
            instance.save()
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.show(req, instance)

    @wsgi.response(204)
    @wsgi.action('confirmResize')
    def _action_confirm_resize(self, req, id, body):
        context = req.environ['nova.context']
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
    @wsgi.action('revertResize')
    def _action_revert_resize(self, req, id, body):
        context = req.environ['nova.context']
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
        return webob.Response(status_int=202)

    @wsgi.response(202)
    @wsgi.action('reboot')
    def _action_reboot(self, req, id, body):
        if 'reboot' in body and 'type' in body['reboot']:
            if not isinstance(body['reboot']['type'], six.string_types):
                msg = _("Argument 'type' for reboot must be a string")
                LOG.error(msg)
                raise exc.HTTPBadRequest(explanation=msg)
            valid_reboot_types = ['HARD', 'SOFT']
            reboot_type = body['reboot']['type'].upper()
            if not valid_reboot_types.count(reboot_type):
                msg = _("Argument 'type' for reboot is not HARD or SOFT")
                LOG.error(msg)
                raise exc.HTTPBadRequest(explanation=msg)
        else:
            msg = _("Missing argument 'type' for reboot")
            LOG.error(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)

        try:
            self.compute_api.reboot(context, instance, reboot_type)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'reboot', id)
        return webob.Response(status_int=202)

    def _resize(self, req, instance_id, flavor_id, **kwargs):
        """Begin the resize process with given instance/flavor."""
        context = req.environ["nova.context"]
        instance = self._get_server(context, req, instance_id)
        try:
            self.compute_api.resize(context, instance, flavor_id, **kwargs)
        except exception.QuotaError as error:
            raise exc.HTTPForbidden(
                explanation=error.format_message())
        except exception.FlavorNotFound:
            msg = _("Unable to locate requested flavor.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeToSameFlavor:
            msg = _("Resize requires a flavor change.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeDisk as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
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
        except (exception.NoValidHost,
                exception.AutoDiskConfigDisabledByImage) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.Invalid:
            msg = _("Invalid instance image.")
            raise exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=202)

    @wsgi.response(204)
    def delete(self, req, id):
        """Destroys a server."""
        try:
            self._delete(req.environ['nova.context'], req, id)
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete', id)

    def _image_ref_from_req_data(self, data):
        try:
            return six.text_type(data['server']['imageRef'])
        except (TypeError, KeyError):
            msg = _("Missing imageRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)

    def _image_uuid_from_href(self, image_href):
        if not image_href:
            msg = _("Invalid imageRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        # If the image href was generated by nova api, strip image_href
        # down to an id and use the default glance connection params
        image_uuid = image_href.split('/').pop()

        if not uuidutils.is_uuid_like(image_uuid):
            msg = _("Invalid imageRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        return image_uuid

    def _image_from_req_data(self, data):
        """Get image data from the request or raise appropriate
        exceptions

        If no image is supplied - checks to see if there is
        block devices set and proper extesions loaded.
        """
        image_ref = data['server'].get('imageRef')
        bdm = data['server'].get('block_device_mapping')
        bdm_v2 = data['server'].get('block_device_mapping_v2')

        if (not image_ref and (
                (bdm and self.ext_mgr.is_loaded('os-volumes')) or
                (bdm_v2 and
                 self.ext_mgr.is_loaded('os-block-device-mapping-v2-boot')))):
            return ''
        else:
            image_href = self._image_ref_from_req_data(data)
            image_uuid = self._image_uuid_from_href(image_href)
            return image_uuid

    def _flavor_id_from_req_data(self, data):
        try:
            flavor_ref = data['server']['flavorRef']
        except (TypeError, KeyError):
            msg = _("Missing flavorRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)
        try:
            return common.get_id_from_href(flavor_ref)
        except ValueError:
            msg = _("Invalid flavorRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

    @wsgi.response(202)
    @wsgi.action('changePassword')
    def _action_change_password(self, req, id, body):
        context = req.environ['nova.context']
        if (not body.get('changePassword')
                or 'adminPass' not in body['changePassword']):
            msg = _("No adminPass was specified")
            raise exc.HTTPBadRequest(explanation=msg)
        password = self._get_server_admin_password(body['changePassword'])

        server = self._get_server(context, req, id)
        try:
            self.compute_api.set_admin_password(context, server, password)
        except exception.InstancePasswordSetFailed as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as e:
            raise common.raise_http_conflict_for_instance_invalid_state(
                e, 'changePassword', id)
        except NotImplementedError:
            msg = _("Unable to set password on instance")
            raise exc.HTTPNotImplemented(explanation=msg)
        return webob.Response(status_int=202)

    def _validate_metadata(self, metadata):
        """Ensure that we can work with the metadata given."""
        try:
            six.iteritems(metadata)
        except AttributeError:
            msg = _("Unable to parse metadata key/value pairs.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

    @wsgi.response(202)
    @wsgi.action('resize')
    def _action_resize(self, req, id, body):
        """Resizes a given instance to the flavor size requested."""
        try:
            flavor_ref = str(body["resize"]["flavorRef"])
            if not flavor_ref:
                msg = _("Resize request has invalid 'flavorRef' attribute.")
                raise exc.HTTPBadRequest(explanation=msg)
        except (KeyError, TypeError):
            msg = _("Resize requests require 'flavorRef' attribute.")
            raise exc.HTTPBadRequest(explanation=msg)

        kwargs = {}
        if 'auto_disk_config' in body['resize']:
            kwargs['auto_disk_config'] = body['resize']['auto_disk_config']

        return self._resize(req, id, flavor_ref, **kwargs)

    @wsgi.response(202)
    @wsgi.action('rebuild')
    def _action_rebuild(self, req, id, body):
        """Rebuild an instance with the given attributes."""
        body = body['rebuild']

        try:
            image_href = body["imageRef"]
        except (KeyError, TypeError):
            msg = _("Could not parse imageRef from request.")
            raise exc.HTTPBadRequest(explanation=msg)

        image_href = self._image_uuid_from_href(image_href)

        password = self._get_server_admin_password(body)

        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)

        attr_map = {
            'personality': 'files_to_inject',
            'name': 'display_name',
            'accessIPv4': 'access_ip_v4',
            'accessIPv6': 'access_ip_v6',
            'metadata': 'metadata',
            'auto_disk_config': 'auto_disk_config',
        }

        kwargs = {}

        # take the preserve_ephemeral value into account only when the
        # corresponding extension is active
        if (self.ext_mgr.is_loaded('os-preserve-ephemeral-rebuild')
                and 'preserve_ephemeral' in body):
            kwargs['preserve_ephemeral'] = strutils.bool_from_string(
                body['preserve_ephemeral'], strict=True)

        if 'accessIPv4' in body:
            self._validate_access_ipv4(body['accessIPv4'])

        if 'accessIPv6' in body:
            self._validate_access_ipv6(body['accessIPv6'])

        if 'name' in body:
            self._validate_server_name(body['name'])

        for request_attribute, instance_attribute in attr_map.items():
            try:
                kwargs[instance_attribute] = body[request_attribute]
            except (KeyError, TypeError):
                pass

        self._validate_metadata(kwargs.get('metadata', {}))

        if 'files_to_inject' in kwargs:
            personality = kwargs.pop('files_to_inject')
            files_to_inject = self._get_injected_files(personality)
        else:
            files_to_inject = None

        try:
            self.compute_api.rebuild(context,
                                     instance,
                                     image_href,
                                     password,
                                     files_to_inject=files_to_inject,
                                     **kwargs)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'rebuild', id)
        except exception.InstanceNotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InvalidMetadataSize as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message())
        except exception.ImageNotFound:
            msg = _("Cannot find image for rebuild")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.QuotaError as error:
            raise exc.HTTPForbidden(explanation=error.format_message())
        except (exception.ImageNotActive,
                exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.InvalidMetadata,
                exception.AutoDiskConfigDisabledByImage) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

        instance = self._get_server(context, req, id, is_detail=True)

        view = self._view_builder.show(req, instance)

        # Add on the adminPass attribute since the view doesn't do it
        # unless instance passwords are disabled
        if CONF.enable_instance_password:
            view['server']['adminPass'] = password

        robj = wsgi.ResponseObject(view)
        return self._add_location(robj)

    @wsgi.response(202)
    @wsgi.action('createImage')
    @common.check_snapshots_enabled
    def _action_create_image(self, req, id, body):
        """Snapshot a server instance."""
        context = req.environ['nova.context']
        entity = body.get("createImage", {})

        image_name = entity.get("name")

        if not image_name:
            msg = _("createImage entity requires name attribute")
            raise exc.HTTPBadRequest(explanation=msg)

        props = {}
        metadata = entity.get('metadata', {})
        common.check_img_metadata_properties_quota(context, metadata)
        try:
            props.update(metadata)
        except ValueError:
            msg = _("Invalid metadata")
            raise exc.HTTPBadRequest(explanation=msg)

        instance = self._get_server(context, req, id)

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

        try:
            if self.compute_api.is_volume_backed_instance(context, instance,
                                                          bdms):
                policy.enforce(context,
                        'compute:snapshot_volume_backed',
                        {'project_id': context.project_id,
                        'user_id': context.user_id})
                image = self.compute_api.snapshot_volume_backed(
                                                       context,
                                                       instance,
                                                       image_name,
                                                       extra_properties=props)
            else:
                image = self.compute_api.snapshot(context,
                                                  instance,
                                                  image_name,
                                                  extra_properties=props)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                        'createImage', id)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())

        # build location of newly-created image entity
        image_id = str(image['id'])
        url_prefix = self._view_builder._update_glance_link_prefix(
                req.application_url)
        image_ref = common.url_join(url_prefix,
                                    context.project_id,
                                    'images',
                                    image_id)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    def _get_server_admin_password(self, server):
        """Determine the admin password for a server on creation."""
        try:
            password = server['adminPass']
            self._validate_admin_password(password)
        except KeyError:
            password = utils.generate_password()
        except ValueError:
            raise exc.HTTPBadRequest(explanation=_("Invalid adminPass"))

        return password

    def _validate_admin_password(self, password):
        if not isinstance(password, six.string_types):
            raise ValueError()

    def _get_server_search_options(self):
        """Return server search options allowed by non-admin."""
        return ('reservation_id', 'name', 'status', 'image', 'flavor',
                'ip', 'changes-since', 'all_tenants')


def create_resource(ext_mgr):
    return wsgi.Resource(Controller(ext_mgr))


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
    LOG.debug("Removing options '%s' from query",
              ", ".join(unknown_options))
    for opt in unknown_options:
        search_options.pop(opt, None)

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
import os
import re
import stevedore

from oslo.config import cfg
import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.plugins.v3 import ips
from nova.api.openstack.compute.views import servers as views_servers
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova.compute import flavors
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import utils


CONF = cfg.CONF
CONF.import_opt('enable_instance_password',
                'nova.api.openstack.compute.servers')
CONF.import_opt('network_api_class', 'nova.network')
CONF.import_opt('reclaim_instance_interval', 'nova.compute.manager')
CONF.import_opt('extensions_blacklist', 'nova.api.openstack', group='osapi_v3')
CONF.import_opt('extensions_whitelist', 'nova.api.openstack', group='osapi_v3')

LOG = logging.getLogger(__name__)


def make_fault(elem):
    fault = xmlutil.SubTemplateElement(elem, 'fault', selector='fault')
    fault.set('code')
    fault.set('created')
    msg = xmlutil.SubTemplateElement(fault, 'message')
    msg.text = 'message'
    det = xmlutil.SubTemplateElement(fault, 'details')
    det.text = 'details'


def make_server(elem, detailed=False):
    elem.set('name')
    elem.set('id')

    if detailed:
        elem.set('user_id')
        elem.set('tenant_id')
        elem.set('updated')
        elem.set('created')
        elem.set('host_id')
        elem.set('access_ip_v4')
        elem.set('access_ip_v6')
        elem.set('status')
        elem.set('progress')
        elem.set('reservation_id')

        # Attach image node
        image = xmlutil.SubTemplateElement(elem, 'image', selector='image')
        image.set('id')
        xmlutil.make_links(image, 'links')

        # Attach flavor node
        flavor = xmlutil.SubTemplateElement(elem, 'flavor', selector='flavor')
        flavor.set('id')
        xmlutil.make_links(flavor, 'links')

        # Attach fault node
        make_fault(elem)

        # Attach metadata node
        elem.append(common.MetadataTemplate())

        # Attach addresses node
        elem.append(ips.AddressesTemplate())

    xmlutil.make_links(elem, 'links')


server_nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}


class ServerTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=server_nsmap)


class MinimalServersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        xmlutil.make_links(root, 'servers_links')
        return xmlutil.MasterTemplate(root, 1, nsmap=server_nsmap)


class ServersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=server_nsmap)


class ServerAdminPassTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('admin_pass')
        return xmlutil.SlaveTemplate(root, 1, nsmap=server_nsmap)


def FullServerTemplate():
    master = ServerTemplate()
    master.attach(ServerAdminPassTemplate())
    return master


class CommonDeserializer(wsgi.MetadataXMLDeserializer):
    """Common deserializer to handle xml-formatted server create requests.

    Handles standard server attributes as well as optional metadata
    and personality attributes
    """

    metadata_deserializer = common.MetadataXMLDeserializer()
    want_controller = True

    def __init__(self, controller):
        self.controller = controller

    def _extract_server(self, node):
        """Marshal the server attribute of a parsed request."""
        server = {}
        server_node = self.find_first_child_named(node, 'server')

        attributes = ["name", "image_ref", "flavor_ref", "admin_pass",
                      "access_ip_v4", "access_ip_v6", "key_name"]
        for attr in attributes:
            if server_node.getAttribute(attr):
                server[attr] = server_node.getAttribute(attr)

        metadata_node = self.find_first_child_named(server_node, "metadata")
        if metadata_node is not None:
            server["metadata"] = self.extract_metadata(metadata_node)

        networks = self._extract_networks(server_node)
        if networks is not None:
            server["networks"] = networks

        if self.controller:
            self.controller.server_create_xml_deserialize(server_node, server)

        return server

    def _extract_networks(self, server_node):
        """Marshal the networks attribute of a parsed request."""
        node = self.find_first_child_named(server_node, "networks")
        if node is not None:
            networks = []
            for network_node in self.find_children_named(node,
                                                         "network"):
                item = {}
                if network_node.hasAttribute("uuid"):
                    item["uuid"] = network_node.getAttribute("uuid")
                if network_node.hasAttribute("fixed_ip"):
                    item["fixed_ip"] = network_node.getAttribute("fixed_ip")
                if network_node.hasAttribute("port"):
                    item["port"] = network_node.getAttribute("port")
                networks.append(item)
            return networks
        else:
            return None


class ActionDeserializer(CommonDeserializer):
    """Deserializer to handle xml-formatted server action requests.

    Handles standard server attributes as well as optional metadata
    and personality attributes
    """

    def default(self, string):
        dom = xmlutil.safe_minidom_parse_string(string)
        action_node = dom.childNodes[0]
        action_name = action_node.tagName

        action_deserializer = {
            'create_image': self._action_create_image,
            'reboot': self._action_reboot,
            'rebuild': self._action_rebuild,
            'resize': self._action_resize,
            'confirm_resize': self._action_confirm_resize,
            'revert_resize': self._action_revert_resize,
        }.get(action_name, super(ActionDeserializer, self).default)

        action_data = action_deserializer(action_node)

        return {'body': {action_name: action_data}}

    def _action_create_image(self, node):
        return self._deserialize_image_action(node, ('name',))

    def _action_reboot(self, node):
        if not node.hasAttribute("type"):
            raise AttributeError("No reboot type was specified in request")
        return {"type": node.getAttribute("type")}

    def _action_rebuild(self, node):
        rebuild = {}
        if node.hasAttribute("name"):
            name = node.getAttribute("name")
            if not name:
                raise AttributeError("Name cannot be blank")
            rebuild['name'] = name

        metadata_node = self.find_first_child_named(node, "metadata")
        if metadata_node is not None:
            rebuild["metadata"] = self.extract_metadata(metadata_node)

        if not node.hasAttribute("image_ref"):
            raise AttributeError("No image_ref was specified in request")
        rebuild["image_ref"] = node.getAttribute("image_ref")

        if node.hasAttribute("admin_pass"):
            rebuild["admin_pass"] = node.getAttribute("admin_pass")

        if node.hasAttribute("access_ipv4"):
            rebuild["access_ip_v4"] = node.getAttribute("access_ip_v4")

        if node.hasAttribute("access_ipv6"):
            rebuild["access_ip_v6"] = node.getAttribute("access_ip_v6")

        if self.controller:
            self.controller.server_rebuild_xml_deserialize(node, rebuild)
        return rebuild

    def _action_resize(self, node):
        resize = {}

        if node.hasAttribute("flavor_ref"):
            resize["flavor_ref"] = node.getAttribute("flavor_ref")
        else:
            raise AttributeError("No flavor_ref was specified in request")

        if self.controller:
            self.controller.server_resize_xml_deserialize(node, resize)
        return resize

    def _action_confirm_resize(self, node):
        return None

    def _action_revert_resize(self, node):
        return None

    def _deserialize_image_action(self, node, allowed_attributes):
        data = {}
        for attribute in allowed_attributes:
            value = node.getAttribute(attribute)
            if value:
                data[attribute] = value
        metadata_node = self.find_first_child_named(node, 'metadata')
        if metadata_node is not None:
            metadata = self.metadata_deserializer.extract_metadata(
                                                        metadata_node)
            data['metadata'] = metadata
        return data


class CreateDeserializer(CommonDeserializer):
    """Deserializer to handle xml-formatted server create requests.

    Handles standard server attributes as well as optional metadata
    and personality attributes
    """

    def default(self, string):
        """Deserialize an xml-formatted server create request."""
        dom = xmlutil.safe_minidom_parse_string(string)
        server = self._extract_server(dom)
        return {'body': {'server': server}}


class ServersController(wsgi.Controller):
    """The Server API base controller class for the OpenStack API."""

    EXTENSION_CREATE_NAMESPACE = 'nova.api.v3.extensions.server.create'
    EXTENSION_DESERIALIZE_EXTRACT_SERVER_NAMESPACE = (
        'nova.api.v3.extensions.server.create.deserialize')

    EXTENSION_REBUILD_NAMESPACE = 'nova.api.v3.extensions.server.rebuild'
    EXTENSION_DESERIALIZE_EXTRACT_REBUILD_NAMESPACE = (
        'nova.api.v3.extensions.server.rebuild.deserialize')

    EXTENSION_RESIZE_NAMESPACE = 'nova.api.v3.extensions.server.resize'
    EXTENSION_DESERIALIZE_EXTRACT_RESIZE_NAMESPACE = (
        'nova.api.v3.extensions.server.resize.deserialize')

    EXTENSION_UPDATE_NAMESPACE = 'nova.api.v3.extensions.server.update'

    _view_builder_class = views_servers.ViewBuilderV3

    @staticmethod
    def _add_location(robj):
        # Just in case...
        if 'server' not in robj.obj:
            return robj

        link = filter(lambda l: l['rel'] == 'self',
                      robj.obj['server']['links'])
        if link:
            robj['Location'] = link[0]['href'].encode('utf-8')

        # Convenience return
        return robj

    def __init__(self, **kwargs):
        def _check_load_extension(required_function):

            def check_whiteblack_lists(ext):
                # Check whitelist is either empty or if not then the extension
                # is in the whitelist
                if (not CONF.osapi_v3.extensions_whitelist or
                        ext.obj.alias in CONF.osapi_v3.extensions_whitelist):

                    # Check the extension is not in the blacklist
                    if ext.obj.alias not in CONF.osapi_v3.extensions_blacklist:
                        return True
                    else:
                        LOG.warning(_("Not loading %s because it is "
                                      "in the blacklist"), ext.obj.alias)
                        return False
                else:
                    LOG.warning(
                        _("Not loading %s because it is not in the whitelist"),
                        ext.obj.alias)
                    return False

            def check_load_extension(ext):
                if isinstance(ext.obj, extensions.V3APIExtensionBase):
                    # Filter out for the existence of the required
                    # function here rather than on every request. We
                    # don't have a new abstract base class to reduce
                    # duplication in the extensions as they may want
                    # to implement multiple server (and other) entry
                    # points if hasattr(ext.obj, 'server_create'):
                    if hasattr(ext.obj, required_function):
                        LOG.debug(_('extension %(ext_alias)s detected by '
                                    'servers extension for function %(func)s'),
                                    {'ext_alias': ext.obj.alias,
                                     'func': required_function})
                        return check_whiteblack_lists(ext)
                    else:
                        LOG.debug(
                            _('extension %(ext_alias)s is missing %(func)s'),
                            {'ext_alias': ext.obj.alias,
                            'func': required_function})
                        return False
                else:
                    return False
            return check_load_extension

        self.extension_info = kwargs.pop('extension_info')
        super(ServersController, self).__init__(**kwargs)
        self.compute_api = compute.API()

        # Look for implmentation of extension point of server creation
        self.create_extension_manager = \
          stevedore.enabled.EnabledExtensionManager(
              namespace=self.EXTENSION_CREATE_NAMESPACE,
              check_func=_check_load_extension('server_create'),
              invoke_on_load=True,
              invoke_kwds={"extension_info": self.extension_info},
              propagate_map_exceptions=True)
        if not list(self.create_extension_manager):
            LOG.debug(_("Did not find any server create extensions"))

        # Look for implmentation of extension point of server create
        # XML deserialization
        self.create_xml_deserialize_manager = \
          stevedore.enabled.EnabledExtensionManager(
              namespace=self.EXTENSION_DESERIALIZE_EXTRACT_SERVER_NAMESPACE,
              check_func=_check_load_extension(
                  'server_xml_extract_server_deserialize'),
              invoke_on_load=True,
              invoke_kwds={"extension_info": self.extension_info},
              propagate_map_exceptions=True)
        if not list(self.create_xml_deserialize_manager):
            LOG.debug(_("Did not find any server create xml deserializer"
                        " extensions"))

        # Look for implmentation of extension point of server rebuild
        self.rebuild_extension_manager = \
            stevedore.enabled.EnabledExtensionManager(
                namespace=self.EXTENSION_REBUILD_NAMESPACE,
                check_func=_check_load_extension('server_rebuild'),
                invoke_on_load=True,
                invoke_kwds={"extension_info": self.extension_info},
                propagate_map_exceptions=True)
        if not list(self.rebuild_extension_manager):
            LOG.debug(_("Did not find any server rebuild extensions"))

        # Look for implmentation of extension point of server rebuild
        # XML deserialization
        self.rebuild_xml_deserialize_manager = \
            stevedore.enabled.EnabledExtensionManager(
                namespace=self.EXTENSION_DESERIALIZE_EXTRACT_REBUILD_NAMESPACE,
                check_func=_check_load_extension(
                    'server_xml_extract_rebuild_deserialize'),
                invoke_on_load=True,
                invoke_kwds={"extension_info": self.extension_info},
                propagate_map_exceptions=True)
        if not list(self.rebuild_xml_deserialize_manager):
            LOG.debug(_("Did not find any server rebuild xml deserializer"
                        " extensions"))

        # Look for implmentation of extension point of server resize
        self.resize_extension_manager = \
            stevedore.enabled.EnabledExtensionManager(
                namespace=self.EXTENSION_RESIZE_NAMESPACE,
                check_func=_check_load_extension('server_resize'),
                invoke_on_load=True,
                invoke_kwds={"extension_info": self.extension_info},
                propagate_map_exceptions=True)
        if not list(self.resize_extension_manager):
            LOG.debug(_("Did not find any server resize extensions"))

        # Look for implmentation of extension point of server resize
        # XML deserialization
        self.resize_xml_deserialize_manager = \
            stevedore.enabled.EnabledExtensionManager(
                namespace=self.EXTENSION_DESERIALIZE_EXTRACT_RESIZE_NAMESPACE,
                check_func=_check_load_extension(
                    'server_xml_extract_resize_deserialize'),
                invoke_on_load=True,
                invoke_kwds={"extension_info": self.extension_info},
                propagate_map_exceptions=True)
        if not list(self.resize_xml_deserialize_manager):
            LOG.debug(_("Did not find any server resize xml deserializer"
                        " extensions"))

        # Look for implmentation of extension point of server update
        self.update_extension_manager = \
            stevedore.enabled.EnabledExtensionManager(
                namespace=self.EXTENSION_UPDATE_NAMESPACE,
                check_func=_check_load_extension('server_resize'),
                invoke_on_load=True,
                invoke_kwds={"extension_info": self.extension_info},
                propagate_map_exceptions=True)
        if not list(self.update_extension_manager):
            LOG.debug(_("Did not find any server update extensions"))

    @wsgi.serializers(xml=MinimalServersTemplate)
    def index(self, req):
        """Returns a list of server names and ids for a given user."""
        try:
            servers = self._get_servers(req, is_detail=False)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        return servers

    @wsgi.serializers(xml=ServersTemplate)
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
        status = search_opts.pop('status', None)
        if status is not None:
            vm_state, task_state = common.task_and_vm_state_from_status(status)
            if not vm_state and not task_state:
                return {'servers': []}
            search_opts['vm_state'] = vm_state
            # When we search by vm state, task state will return 'default'.
            # So we don't need task_state search_opt.
            if 'default' not in task_state:
                search_opts['task_state'] = task_state

        if 'changes_since' in search_opts:
            try:
                parsed = timeutils.parse_isotime(search_opts['changes_since'])
            except ValueError:
                msg = _('Invalid changes_since value')
                raise exc.HTTPBadRequest(explanation=msg)
            search_opts['changes_since'] = parsed

        # By default, compute's get_all() will return deleted instances.
        # If an admin hasn't specified a 'deleted' search option, we need
        # to filter out deleted instances by setting the filter ourselves.
        # ... Unless 'changes_since' is specified, because 'changes_since'
        # should return recently deleted images according to the API spec.

        if 'deleted' not in search_opts:
            if 'changes_since' not in search_opts:
                # No 'changes_since', so we only want non-deleted servers
                search_opts['deleted'] = False

        if 'changes_since' in search_opts:
            search_opts['changes-since'] = search_opts.pop('changes_since')

        if search_opts.get("vm_state") == "deleted":
            if context.is_admin:
                search_opts['deleted'] = True
            else:
                msg = _("Only administrators may list deleted instances")
                raise exc.HTTPBadRequest(explanation=msg)

        if 'all_tenants' not in search_opts:
            if context.project_id:
                search_opts['project_id'] = context.project_id
            else:
                search_opts['user_id'] = context.user_id

        limit, marker = common.get_limit_and_marker(req)
        try:
            instance_list = self.compute_api.get_all(context,
                                                     search_opts=search_opts,
                                                     limit=limit,
                                                     marker=marker,
                                                     want_objects=True)
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.FlavorNotFound:
            log_msg = _("Flavor '%s' could not be found ")
            LOG.debug(log_msg, search_opts['flavor'])
            instance_list = []

        if is_detail:
            instance_list.fill_faults()
            response = self._view_builder.detail(req, instance_list)
        else:
            response = self._view_builder.index(req, instance_list)
        req.cache_db_instances(instance_list)
        return response

    def _get_server(self, context, req, instance_uuid):
        """Utility function for looking up an instance by uuid."""
        try:
            instance = self.compute_api.get(context, instance_uuid,
                                            want_objects=True)
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        req.cache_db_instance(instance)
        return instance

    def _check_string_length(self, value, name, max_length=None):
        try:
            if isinstance(value, basestring):
                value = value.strip()
            utils.check_string_length(value, name, min_length=1,
                                      max_length=max_length)
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    def _validate_server_name(self, value):
        self._check_string_length(value, 'Server name', max_length=255)

    def _validate_device_name(self, value):
        self._check_string_length(value, 'Device name', max_length=255)

        if ' ' in value:
            msg = _("Device name cannot include spaces.")
            raise exc.HTTPBadRequest(explanation=msg)

    def _get_requested_networks(self, requested_networks):
        """Create a list of requested networks from the networks attribute."""
        networks = []
        for network in requested_networks:
            try:
                # fixed IP address is optional
                # if the fixed IP address is not provided then
                # it will use one of the available IP address from the network
                address = network.get('fixed_ip', None)
                if address is not None and not utils.is_valid_ipv4(address):
                    msg = _("Invalid fixed IP address (%s)") % address
                    raise exc.HTTPBadRequest(explanation=msg)

                port_id = network.get('port', None)
                if port_id:
                    network_uuid = None
                    if not utils.is_neutron():
                        # port parameter is only for neutron v2.0
                        msg = _("Unknown argument: port")
                        raise exc.HTTPBadRequest(explanation=msg)
                    if not uuidutils.is_uuid_like(port_id):
                        msg = _("Bad port format: port uuid is "
                                "not in proper format "
                                "(%s)") % port_id
                        raise exc.HTTPBadRequest(explanation=msg)
                    if address is not None:
                        msg = _("Specified Fixed IP '%(addr)s' cannot be used "
                                "with port '%(port)s': port already has "
                                "a Fixed IP allocated.") % {"addr": address,
                                                            "port": port_id}
                        raise exc.HTTPBadRequest(explanation=msg)
                else:
                    network_uuid = network['uuid']

                if not port_id and not uuidutils.is_uuid_like(network_uuid):
                    br_uuid = network_uuid.split('-', 1)[-1]
                    if not uuidutils.is_uuid_like(br_uuid):
                        msg = _("Bad networks format: network uuid is "
                                "not in proper format "
                                "(%s)") % network_uuid
                        raise exc.HTTPBadRequest(explanation=msg)

                # For neutronv2, requested_networks
                # should be tuple of (network_uuid, fixed_ip, port_id)
                if utils.is_neutron():
                    networks.append((network_uuid, address, port_id))
                else:
                    # check if the network id is already present in the list,
                    # we don't want duplicate networks to be passed
                    # at the boot time
                    for id, ip in networks:
                        if id == network_uuid:
                            expl = (_("Duplicate networks"
                                      " (%s) are not allowed") %
                                    network_uuid)
                            raise exc.HTTPBadRequest(explanation=expl)
                    networks.append((network_uuid, address))
            except KeyError as key:
                expl = _('Bad network format: missing %s') % key
                raise exc.HTTPBadRequest(explanation=expl)
            except TypeError:
                expl = _('Bad networks format')
                raise exc.HTTPBadRequest(explanation=expl)

        return networks

    # NOTE(vish): Without this regex, b64decode will happily
    #             ignore illegal bytes in the base64 encoded
    #             data.
    B64_REGEX = re.compile('^(?:[A-Za-z0-9+\/]{4})*'
                           '(?:[A-Za-z0-9+\/]{2}=='
                           '|[A-Za-z0-9+\/]{3}=)?$')

    def _decode_base64(self, data):
        data = re.sub(r'\s', '', data)
        if not self.B64_REGEX.match(data):
            return None
        try:
            return base64.b64decode(data)
        except TypeError:
            return None

    def _validate_access_ipv4(self, address):
        if not utils.is_valid_ipv4(address):
            expl = _('access_ip_v4 is not proper IPv4 format')
            raise exc.HTTPBadRequest(explanation=expl)

    def _validate_access_ipv6(self, address):
        if not utils.is_valid_ipv6(address):
            expl = _('access_ip_v6 is not proper IPv6 format')
            raise exc.HTTPBadRequest(explanation=expl)

    @wsgi.serializers(xml=ServerTemplate)
    def show(self, req, id):
        """Returns server details by server id."""
        try:
            context = req.environ['nova.context']
            instance = self.compute_api.get(context, id, want_objects=True)
            req.cache_db_instance(instance)
            return self._view_builder.show(req, instance)
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
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

        # Arguments to be passed to instance create function
        create_kwargs = {}

        # Query extensions which want to manipulate the keyword
        # arguments.
        # NOTE(cyeoh): This is the hook that extensions use
        # to replace the extension specific code below.
        # When the extensions are ported this will also result
        # in some convenience function from this class being
        # moved to the extension
        if list(self.create_extension_manager):
            self.create_extension_manager.map(self._create_extension_point,
                                              server_dict, create_kwargs)

        image_uuid = self._image_from_req_data(server_dict, create_kwargs)

        # NOTE(cyeoh): Although an extension can set
        # return_reservation_id in order to request that a reservation
        # id be returned to the client instead of the newly created
        # instance information we do not want to pass this parameter
        # to the compute create call which always returns both. We use
        # this flag after the instance create call to determine what
        # to return to the client
        return_reservation_id = create_kwargs.pop('return_reservation_id',
                                                  False)

        requested_networks = None
        # TODO(cyeoh): bp v3-api-core-as-extensions
        # Replace with an extension point when the os-networks
        # extension is ported. Currently reworked
        # to take into account is_neutron
        #if (self.ext_mgr.is_loaded('os-networks')
        #        or utils.is_neutron()):
        #    requested_networks = server_dict.get('networks')

        if utils.is_neutron():
            requested_networks = server_dict.get('networks')
        if requested_networks is not None:
            requested_networks = self._get_requested_networks(
                requested_networks)

        (access_ip_v4, ) = server_dict.get('access_ip_v4'),
        if access_ip_v4 is not None:
            self._validate_access_ipv4(access_ip_v4)

        (access_ip_v6, ) = server_dict.get('access_ip_v6'),
        if access_ip_v6 is not None:
            self._validate_access_ipv6(access_ip_v6)

        try:
            flavor_id = self._flavor_id_from_req_data(body)
        except ValueError as error:
            msg = _("Invalid flavor_ref provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            inst_type = flavors.get_flavor_by_flavor_id(
                    flavor_id, ctxt=context, read_deleted="no")

            (instances, resv_id) = self.compute_api.create(context,
                            inst_type,
                            image_uuid,
                            display_name=name,
                            display_description=name,
                            metadata=server_dict.get('metadata', {}),
                            access_ip_v4=access_ip_v4,
                            access_ip_v6=access_ip_v6,
                            admin_password=password,
                            requested_networks=requested_networks,
                            **create_kwargs)
        except exception.QuotaError as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message(),
                headers={'Retry-After': 0})
        except exception.InvalidMetadataSize as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message())
        except exception.ImageNotFound as error:
            msg = _("Can not find requested image")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.FlavorNotFound as error:
            msg = _("Invalid flavor_ref provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.KeypairNotFound as error:
            msg = _("Invalid key_name provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.ConfigDriveInvalidValue:
            msg = _("Invalid config_drive provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except rpc_common.RemoteError as err:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': err.exc_type,
                                                 'err_msg': err.value}
            raise exc.HTTPBadRequest(explanation=msg)
        except UnicodeDecodeError as error:
            msg = "UnicodeError: %s" % unicode(error)
            raise exc.HTTPBadRequest(explanation=msg)
        except (exception.ImageNotActive,
                exception.InstanceTypeDiskTooSmall,
                exception.InstanceTypeMemoryTooSmall,
                exception.InstanceTypeNotFound,
                exception.InvalidMetadata,
                exception.InvalidRequest,
                exception.MultiplePortsNotApplicable,
                exception.SecurityGroupNotFound,
                exception.InstanceUserDataMalformed) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except exception.PortInUse as error:
            raise exc.HTTPConflict(explanation=error.format_message())

        # If the caller wanted a reservation_id, return it
        if return_reservation_id:
            return wsgi.ResponseObject(
                {'servers_reservation': {'reservation_id': resv_id}},
                xml=wsgi.XMLDictSerializer)

        req.cache_db_instances(instances)
        server = self._view_builder.create(req, instances[0])

        if CONF.enable_instance_password:
            server['server']['admin_pass'] = password

        robj = wsgi.ResponseObject(server)

        return self._add_location(robj)

    def _create_extension_point(self, ext, server_dict, create_kwargs):
        handler = ext.obj
        LOG.debug(_("Running _create_extension_point for %s"), ext.obj)

        handler.server_create(server_dict, create_kwargs)

    def _rebuild_extension_point(self, ext, rebuild_dict, rebuild_kwargs):
        handler = ext.obj
        LOG.debug(_("Running _rebuild_extension_point for %s"), ext.obj)

        handler.server_rebuild(rebuild_dict, rebuild_kwargs)

    def _resize_extension_point(self, ext, resize_dict, resize_kwargs):
        handler = ext.obj
        LOG.debug(_("Running _resize_extension_point for %s"), ext.obj)

        handler.server_resize(resize_dict, resize_kwargs)

    def _update_extension_point(self, ext, update_dict, update_kwargs):
        handler = ext.obj
        LOG.debug(_("Running _update_extension_point for %s"), ext.obj)

        handler.server_update(update_dict, update_kwargs)

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

    @wsgi.serializers(xml=ServerTemplate)
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

        if 'access_ip_v4' in body['server']:
            access_ipv4 = body['server']['access_ip_v4']
            if access_ipv4:
                self._validate_access_ipv4(access_ipv4)
            update_dict['access_ip_v4'] = (
                access_ipv4 and access_ipv4.strip() or None)

        if 'access_ip_v6' in body['server']:
            access_ipv6 = body['server']['access_ip_v6']
            if access_ipv6:
                self._validate_access_ipv6(access_ipv6)
            update_dict['access_ip_v6'] = (
                access_ipv6 and access_ipv6.strip() or None)

        if 'host_id' in body['server']:
            msg = _("host_id cannot be updated.")
            raise exc.HTTPBadRequest(explanation=msg)

        if list(self.update_extension_manager):
            self.update_extension_manager.map(self._update_extension_point,
                                              body['server'], update_dict)

        try:
            instance = self.compute_api.get(ctxt, id, want_objects=True)
            req.cache_db_instance(instance)
            instance.update(update_dict)
            instance.save()
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.show(req, instance)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('confirm_resize')
    def _action_confirm_resize(self, req, id, body):
        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)
        try:
            self.compute_api.confirm_resize(context, instance)
        except exception.MigrationNotFound:
            msg = _("Instance has not been resized.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'confirm_resize')
        return exc.HTTPNoContent()

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('revert_resize')
    def _action_revert_resize(self, req, id, body):
        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)
        try:
            self.compute_api.revert_resize(context, instance)
        except exception.MigrationNotFound:
            msg = _("Instance has not been resized.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.InstanceTypeNotFound:
            msg = _("Flavor used by the instance could not be found.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'revert_resize')
        return webob.Response(status_int=202)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('reboot')
    def _action_reboot(self, req, id, body):
        if 'reboot' in body and 'type' in body['reboot']:
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
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'reboot')
        return webob.Response(status_int=202)

    def _resize(self, req, instance_id, flavor_id, **kwargs):
        """Begin the resize process with given instance/flavor."""
        context = req.environ["nova.context"]
        instance = self._get_server(context, req, instance_id)

        try:
            self.compute_api.resize(context, instance, flavor_id, **kwargs)
        except exception.FlavorNotFound:
            msg = _("Unable to locate requested flavor.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeToSameFlavor:
            msg = _("Resize requires a flavor change.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'resize')
        except exception.ImageNotAuthorized:
            msg = _("You are not authorized to access the image "
                    "the instance was started with.")
            raise exc.HTTPUnauthorized(explanation=msg)
        except exception.ImageNotFound:
            msg = _("Image that the instance was started "
                    "with could not be found.")
            raise exc.HTTPBadRequest(explanation=msg)
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
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete')

    def _image_uuid_from_href(self, image_href):
        # If the image href was generated by nova api, strip image_href
        # down to an id and use the default glance connection params
        image_uuid = image_href.split('/').pop()

        if not uuidutils.is_uuid_like(image_uuid):
            msg = _("Invalid image_ref provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        return image_uuid

    def _image_from_req_data(self, server_dict, create_kwargs):
        """Get image data from the request or raise appropriate
        exceptions.

        The field image_ref is mandatory when no block devices have been
        defined and must be a proper uuid when present.
        """
        image_href = server_dict.get('image_ref')

        if not image_href and create_kwargs.get('block_device_mapping'):
            return ''
        elif image_href:
            return self._image_uuid_from_href(unicode(image_href))
        else:
            msg = _("Missing image_ref attribute")
            raise exc.HTTPBadRequest(explanation=msg)

    def _flavor_id_from_req_data(self, data):
        try:
            flavor_ref = data['server']['flavor_ref']
        except (TypeError, KeyError):
            msg = _("Missing flavor_ref attribute")
            raise exc.HTTPBadRequest(explanation=msg)

        return common.get_id_from_href(flavor_ref)

    def _validate_metadata(self, metadata):
        """Ensure that we can work with the metadata given."""
        try:
            metadata.iteritems()
        except AttributeError:
            msg = _("Unable to parse metadata key/value pairs.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('resize')
    def _action_resize(self, req, id, body):
        """Resizes a given instance to the flavor size requested."""
        resize_dict = body['resize']
        try:
            flavor_ref = str(resize_dict["flavor_ref"])
            if not flavor_ref:
                msg = _("Resize request has invalid 'flavor_ref' attribute.")
                raise exc.HTTPBadRequest(explanation=msg)
        except (KeyError, TypeError):
            msg = _("Resize requests require 'flavor_ref' attribute.")
            raise exc.HTTPBadRequest(explanation=msg)

        resize_kwargs = {}

        if list(self.resize_extension_manager):
            self.resize_extension_manager.map(self._resize_extension_point,
                                              resize_dict, resize_kwargs)

        return self._resize(req, id, flavor_ref, **resize_kwargs)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('rebuild')
    def _action_rebuild(self, req, id, body):
        """Rebuild an instance with the given attributes."""
        try:
            rebuild_dict = body['rebuild']
        except (KeyError, TypeError):
            msg = _('Invalid request body')
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            image_href = rebuild_dict["image_ref"]
        except (KeyError, TypeError):
            msg = _("Could not parse image_ref from request.")
            raise exc.HTTPBadRequest(explanation=msg)

        image_href = self._image_uuid_from_href(image_href)

        try:
            password = rebuild_dict['admin_pass']
        except (KeyError, TypeError):
            password = utils.generate_password()

        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)

        attr_map = {
            'name': 'display_name',
            'access_ip_v4': 'access_ip_v4',
            'access_ip_v6': 'access_ip_v6',
            'metadata': 'metadata',
        }

        if 'name' in rebuild_dict:
            self._validate_server_name(rebuild_dict['name'])

        if 'access_ip_v4' in rebuild_dict:
            self._validate_access_ipv4(rebuild_dict['access_ip_v4'])

        if 'access_ip_v6' in rebuild_dict:
            self._validate_access_ipv6(rebuild_dict['access_ip_v6'])

        rebuild_kwargs = {}
        if list(self.rebuild_extension_manager):
            self.rebuild_extension_manager.map(self._rebuild_extension_point,
                                               rebuild_dict, rebuild_kwargs)

        for request_attribute, instance_attribute in attr_map.items():
            try:
                rebuild_kwargs[instance_attribute] = rebuild_dict[
                    request_attribute]
            except (KeyError, TypeError):
                pass

        self._validate_metadata(rebuild_kwargs.get('metadata', {}))

        try:
            self.compute_api.rebuild(context,
                                     instance,
                                     image_href,
                                     password,
                                     **rebuild_kwargs)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'rebuild')
        except exception.InstanceNotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InvalidMetadataSize as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message())
        except exception.ImageNotFound:
            msg = _("Cannot find image for rebuild")
            raise exc.HTTPBadRequest(explanation=msg)
        except (exception.ImageNotActive,
                exception.InstanceTypeDiskTooSmall,
                exception.InstanceTypeMemoryTooSmall,
                exception.InvalidMetadata) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

        instance = self._get_server(context, req, id)

        view = self._view_builder.show(req, instance)

        # Add on the admin_pass attribute since the view doesn't do it
        # unless instance passwords are disabled
        if CONF.enable_instance_password:
            view['server']['admin_pass'] = password

        robj = wsgi.ResponseObject(view)
        return self._add_location(robj)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('create_image')
    @common.check_snapshots_enabled
    def _action_create_image(self, req, id, body):
        """Snapshot a server instance."""
        context = req.environ['nova.context']
        entity = body.get("create_image", {})

        image_name = entity.get("name")

        if not image_name:
            msg = _("create_image entity requires name attribute")
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

        bdms = self.compute_api.get_instance_bdms(context, instance)

        try:
            if self.compute_api.is_volume_backed_instance(context, instance,
                                                          bdms):
                img = instance['image_ref']
                if not img:
                    # NOTE(Vincent Hou) The private method
                    # _get_bdm_image_metadata only works, when boot
                    # device is set to 'vda'. It needs to be fixed later,
                    # but tentatively we use it here.
                    image_meta = {'properties': self.compute_api.
                                    _get_bdm_image_metadata(context, bdms)}
                else:
                    src_image = self.compute_api.\
                        image_service.show(context, img)
                    image_meta = dict(src_image)

                image = self.compute_api.snapshot_volume_backed(
                                                       context,
                                                       instance,
                                                       image_meta,
                                                       image_name,
                                                       extra_properties=props)
            else:
                image = self.compute_api.snapshot(context,
                                                  instance,
                                                  image_name,
                                                  extra_properties=props)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                        'create_image')
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())

        # build location of newly-created image entity
        image_id = str(image['id'])
        image_ref = os.path.join(req.application_url,
                                 context.project_id,
                                 'images',
                                 image_id)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    def _get_server_admin_password(self, server):
        """Determine the admin password for a server on creation."""
        try:
            password = server['admin_pass']
            self._validate_admin_password(password)
        except KeyError:
            password = utils.generate_password()
        except ValueError:
            raise exc.HTTPBadRequest(explanation=_("Invalid admin_pass"))

        return password

    def _validate_admin_password(self, password):
        if not isinstance(password, basestring):
            raise ValueError()

    def _get_server_search_options(self):
        """Return server search options allowed by non-admin."""
        return ('reservation_id', 'name', 'status', 'image', 'flavor',
                'ip', 'changes_since', 'all_tenants')

    def _server_create_xml_deserialize_extension_point(self, ext, server_node,
                                                       server_dict):
        handler = ext.obj
        LOG.debug(_("Running create xml deserialize ep for %s"),
                  handler.alias)
        handler.server_xml_extract_server_deserialize(server_node,
                                                      server_dict)

    def server_create_xml_deserialize(self, server_node, server):
        if list(self.create_xml_deserialize_manager):
            self.create_xml_deserialize_manager.map(
                self._server_create_xml_deserialize_extension_point,
                server_node, server)

    def _server_rebuild_xml_deserialize_extension_point(self, ext,
                                                        rebuild_node,
                                                        rebuild_dict):
        handler = ext.obj
        LOG.debug(_("Running rebuild xml deserialize ep for %s"),
                  handler.alias)
        handler.server_xml_extract_rebuild_deserialize(rebuild_node,
                                                       rebuild_dict)

    def server_rebuild_xml_deserialize(self, rebuild_node, rebuild_dict):
        if list(self.rebuild_xml_deserialize_manager):
            self.rebuild_xml_deserialize_manager.map(
                self._server_rebuild_xml_deserialize_extension_point,
                rebuild_node, rebuild_dict)

    def _server_resize_xml_deserialize_extension_point(self, ext, resize_node,
                                                       resize_dict):
        handler = ext.obj
        LOG.debug(_("Running rebuild xml deserialize ep for %s"),
                  handler.alias)
        handler.server_xml_extract_resize_deserialize(resize_node, resize_dict)

    def server_resize_xml_deserialize(self, resize_node, resize_dict):
        if list(self.resize_xml_deserialize_manager):
            self.resize_xml_deserialize_manager.map(
                self._server_resize_xml_deserialize_extension_point,
                resize_node, resize_dict)

    def _get_instance(self, context, instance_uuid):
        try:
            attrs = ['system_metadata', 'metadata']
            return instance_obj.Instance.get_by_uuid(context, instance_uuid,
                                                     expected_attrs=attrs)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

    @extensions.expected_errors((404, 409))
    @wsgi.action('start')
    def _start_server(self, req, id, body):
        """Start an instance."""
        context = req.environ['nova.context']
        instance = self._get_instance(context, id)
        LOG.debug(_('start instance'), instance=instance)
        try:
            self.compute_api.start(context, instance)
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        return webob.Response(status_int=202)

    @extensions.expected_errors((404, 409))
    @wsgi.action('stop')
    def _stop_server(self, req, id, body):
        """Stop an instance."""
        context = req.environ['nova.context']
        instance = self._get_instance(context, id)
        LOG.debug(_('stop instance'), instance=instance)
        try:
            self.compute_api.stop(context, instance)
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        return webob.Response(status_int=202)


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context."""
    if context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
                        if opt not in allowed_search_options]
    LOG.debug(_("Removing options '%s' from query"),
              ", ".join(unknown_options))
    for opt in unknown_options:
        search_options.pop(opt, None)


class Servers(extensions.V3APIExtensionBase):
    """Servers."""

    name = "Servers"
    alias = "servers"
    namespace = "http://docs.openstack.org/compute/core/servers/v3"
    version = 1

    def get_resources(self):
        member_actions = {'action': 'POST'}
        collection_actions = {'detail': 'GET'}
        resources = [
            extensions.ResourceExtension(
                'servers',
                ServersController(extension_info=self.extension_info),
                member_name='server', collection_actions=collection_actions,
                member_actions=member_actions)]

        return resources

    def get_controller_extensions(self):
        return []

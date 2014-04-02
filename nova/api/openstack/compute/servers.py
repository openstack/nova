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

from oslo.config import cfg
from oslo import messaging
import six
import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute import ips
from nova.api.openstack.compute.views import servers as views_servers
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import block_device
from nova import compute
from nova.compute import flavors
from nova import exception
from nova.objects import block_device as block_device_obj
from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
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
CONF.import_opt('network_api_class', 'nova.network')
CONF.import_opt('reclaim_instance_interval', 'nova.compute.manager')

LOG = logging.getLogger(__name__)

XML_WARNING = False


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

    global XML_WARNING
    if not XML_WARNING:
        LOG.warning(_('XML support has been deprecated and may be removed '
                      'as early as the Juno release.'))
        XML_WARNING = True

    if detailed:
        elem.set('userId', 'user_id')
        elem.set('tenantId', 'tenant_id')
        elem.set('updated')
        elem.set('created')
        elem.set('hostId')
        elem.set('accessIPv4')
        elem.set('accessIPv6')
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
        root.set('adminPass')
        return xmlutil.SlaveTemplate(root, 1, nsmap=server_nsmap)


class ServerMultipleCreateTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('reservation_id')
        return xmlutil.MasterTemplate(root, 1, nsmap=server_nsmap)


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

    def _extract_personality(self, server_node):
        """Marshal the personality attribute of a parsed request."""
        node = self.find_first_child_named(server_node, "personality")
        if node is not None:
            personality = []
            for file_node in self.find_children_named(node, "file"):
                item = {}
                if file_node.hasAttribute("path"):
                    item["path"] = file_node.getAttribute("path")
                item["contents"] = self.extract_text(file_node)
                personality.append(item)
            return personality
        else:
            return None

    def _extract_server(self, node):
        """Marshal the server attribute of a parsed request."""
        server = {}
        server_node = self.find_first_child_named(node, 'server')

        attributes = ["name", "imageRef", "flavorRef", "adminPass",
                      "accessIPv4", "accessIPv6", "key_name",
                      "availability_zone", "min_count", "max_count"]
        for attr in attributes:
            if server_node.getAttribute(attr):
                server[attr] = server_node.getAttribute(attr)

        res_id = server_node.getAttribute('return_reservation_id')
        if res_id:
            server['return_reservation_id'] = \
                    strutils.bool_from_string(res_id)

        scheduler_hints = self._extract_scheduler_hints(server_node)
        if scheduler_hints:
            server['OS-SCH-HNT:scheduler_hints'] = scheduler_hints

        metadata_node = self.find_first_child_named(server_node, "metadata")
        if metadata_node is not None:
            server["metadata"] = self.extract_metadata(metadata_node)

        user_data_node = self.find_first_child_named(server_node, "user_data")
        if user_data_node is not None:
            server["user_data"] = self.extract_text(user_data_node)

        personality = self._extract_personality(server_node)
        if personality is not None:
            server["personality"] = personality

        networks = self._extract_networks(server_node)
        if networks is not None:
            server["networks"] = networks

        security_groups = self._extract_security_groups(server_node)
        if security_groups is not None:
            server["security_groups"] = security_groups

        # NOTE(vish): this is not namespaced in json, so leave it without a
        #             namespace for now
        block_device_mapping = self._extract_block_device_mapping(server_node)
        if block_device_mapping is not None:
            server["block_device_mapping"] = block_device_mapping

        block_device_mapping_v2 = self._extract_block_device_mapping_v2(
            server_node)
        if block_device_mapping_v2 is not None:
            server["block_device_mapping_v2"] = block_device_mapping_v2

        # NOTE(vish): Support this incorrect version because it was in the code
        #             base for a while and we don't want to accidentally break
        #             anyone that might be using it.
        auto_disk_config = server_node.getAttribute('auto_disk_config')
        if auto_disk_config:
            server['OS-DCF:diskConfig'] = auto_disk_config

        auto_disk_config = server_node.getAttribute('OS-DCF:diskConfig')
        if auto_disk_config:
            server['OS-DCF:diskConfig'] = auto_disk_config

        config_drive = server_node.getAttribute('config_drive')
        if config_drive:
            server['config_drive'] = config_drive

        return server

    def _extract_block_device_mapping(self, server_node):
        """Marshal the block_device_mapping node of a parsed request."""
        node = self.find_first_child_named(server_node, "block_device_mapping")
        if node:
            block_device_mapping = []
            for child in self.extract_elements(node):
                if child.nodeName != "mapping":
                    continue
                mapping = {}
                attributes = ["volume_id", "snapshot_id", "device_name",
                              "virtual_name", "volume_size"]
                for attr in attributes:
                    value = child.getAttribute(attr)
                    if value:
                        mapping[attr] = value
                attributes = ["delete_on_termination", "no_device"]
                for attr in attributes:
                    value = child.getAttribute(attr)
                    if value:
                        mapping[attr] = strutils.bool_from_string(value)
                block_device_mapping.append(mapping)
            return block_device_mapping
        else:
            return None

    def _extract_block_device_mapping_v2(self, server_node):
        """Marshal the new block_device_mappings."""
        node = self.find_first_child_named(server_node,
                                           "block_device_mapping_v2")
        if node:
            block_device_mapping = []
            for child in self.extract_elements(node):
                if child.nodeName != "mapping":
                    continue
                block_device_mapping.append(
                    dict((attr, child.getAttribute(attr))
                        for attr in block_device.bdm_new_api_fields
                        if child.getAttribute(attr)))
            return block_device_mapping

    def _extract_scheduler_hints(self, server_node):
        """Marshal the scheduler hints attribute of a parsed request."""
        node = self.find_first_child_named_in_namespace(server_node,
            "http://docs.openstack.org/compute/ext/scheduler-hints/api/v2",
            "scheduler_hints")
        if node:
            scheduler_hints = {}
            for child in self.extract_elements(node):
                scheduler_hints.setdefault(child.nodeName, [])
                value = self.extract_text(child).strip()
                scheduler_hints[child.nodeName].append(value)
            return scheduler_hints
        else:
            return None

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

    def _extract_security_groups(self, server_node):
        """Marshal the security_groups attribute of a parsed request."""
        node = self.find_first_child_named(server_node, "security_groups")
        if node is not None:
            security_groups = []
            for sg_node in self.find_children_named(node, "security_group"):
                item = {}
                name = self.find_attribute_or_element(sg_node, 'name')
                if name:
                    item["name"] = name
                    security_groups.append(item)
            return security_groups
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
            'createImage': self._action_create_image,
            'changePassword': self._action_change_password,
            'reboot': self._action_reboot,
            'rebuild': self._action_rebuild,
            'resize': self._action_resize,
            'confirmResize': self._action_confirm_resize,
            'revertResize': self._action_revert_resize,
        }.get(action_name, super(ActionDeserializer, self).default)

        action_data = action_deserializer(action_node)

        return {'body': {action_name: action_data}}

    def _action_create_image(self, node):
        return self._deserialize_image_action(node, ('name',))

    def _action_change_password(self, node):
        if not node.hasAttribute("adminPass"):
            raise AttributeError("No adminPass was specified in request")
        return {"adminPass": node.getAttribute("adminPass")}

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

        if node.hasAttribute("auto_disk_config"):
            rebuild['OS-DCF:diskConfig'] = node.getAttribute(
                "auto_disk_config")

        if node.hasAttribute("OS-DCF:diskConfig"):
            rebuild['OS-DCF:diskConfig'] = node.getAttribute(
                "OS-DCF:diskConfig")

        metadata_node = self.find_first_child_named(node, "metadata")
        if metadata_node is not None:
            rebuild["metadata"] = self.extract_metadata(metadata_node)

        personality = self._extract_personality(node)
        if personality is not None:
            rebuild["personality"] = personality

        if not node.hasAttribute("imageRef"):
            raise AttributeError("No imageRef was specified in request")
        rebuild["imageRef"] = node.getAttribute("imageRef")

        if node.hasAttribute("adminPass"):
            rebuild["adminPass"] = node.getAttribute("adminPass")

        if node.hasAttribute("accessIPv4"):
            rebuild["accessIPv4"] = node.getAttribute("accessIPv4")

        if node.hasAttribute("accessIPv6"):
            rebuild["accessIPv6"] = node.getAttribute("accessIPv6")

        if node.hasAttribute("preserve_ephemeral"):
            rebuild["preserve_ephemeral"] = strutils.bool_from_string(
                node.getAttribute("preserve_ephemeral"), strict=True)

        return rebuild

    def _action_resize(self, node):
        resize = {}

        if node.hasAttribute("flavorRef"):
            resize["flavorRef"] = node.getAttribute("flavorRef")
        else:
            raise AttributeError("No flavorRef was specified in request")

        if node.hasAttribute("auto_disk_config"):
            resize['OS-DCF:diskConfig'] = node.getAttribute("auto_disk_config")

        if node.hasAttribute("OS-DCF:diskConfig"):
            resize['OS-DCF:diskConfig'] = node.getAttribute(
                "OS-DCF:diskConfig")

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


class Controller(wsgi.Controller):
    """The Server API base controller class for the OpenStack API."""

    _view_builder_class = views_servers.ViewBuilder

    @staticmethod
    def _add_location(robj):
        # Just in case...
        if 'server' not in robj.obj:
            return robj

        link = filter(lambda l: l['rel'] == 'self',
                      robj.obj['server']['links'])
        if link:
            robj['Location'] = utils.utf8(link[0]['href'])

        # Convenience return
        return robj

    def __init__(self, ext_mgr=None, **kwargs):
        super(Controller, self).__init__(**kwargs)
        self.compute_api = compute.API()
        self.ext_mgr = ext_mgr

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

        if search_opts.get("vm_state") == ['deleted']:
            if context.is_admin:
                search_opts['deleted'] = True
            else:
                msg = _("Only administrators may list deleted instances")
                raise exc.HTTPForbidden(explanation=msg)

        # If all tenants is passed with 0 or false as the value
        # then remove it from the search options. Nothing passed as
        # the value for all_tenants is considered to enable the feature
        all_tenants = search_opts.get('all_tenants')
        if all_tenants:
            try:
                if not strutils.bool_from_string(all_tenants, True):
                    del search_opts['all_tenants']
            except ValueError as err:
                raise exception.InvalidInput(str(err))

        if 'all_tenants' in search_opts:
            policy.enforce(context, 'compute:get_all_tenants',
                           {'project_id': context.project_id,
                            'user_id': context.user_id})
            del search_opts['all_tenants']
        else:
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
            # TODO(mriedem): Move to ObjectListBase.__init__ for empty lists.
            instance_list = instance_obj.InstanceList(objects=[])

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
        for network in requested_networks:
            try:
                port_id = network.get('port', None)
                if port_id:
                    network_uuid = None
                    if not utils.is_neutron():
                        # port parameter is only for neutron v2.0
                        msg = _("Unknown argument : port")
                        raise exc.HTTPBadRequest(explanation=msg)
                    if not uuidutils.is_uuid_like(port_id):
                        msg = _("Bad port format: port uuid is "
                                "not in proper format "
                                "(%s)") % port_id
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

                #fixed IP address is optional
                #if the fixed IP address is not provided then
                #it will use one of the available IP address from the network
                address = network.get('fixed_ip', None)
                if address is not None and not utils.is_valid_ip_address(
                        address):
                    msg = _("Invalid fixed IP address (%s)") % address
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

    def _validate_user_data(self, user_data):
        """Check if the user_data is encoded properly."""
        if not user_data:
            return
        if self._decode_base64(user_data) is None:
            expl = _('Userdata content cannot be decoded')
            raise exc.HTTPBadRequest(explanation=expl)

    def _validate_access_ipv4(self, address):
        if not utils.is_valid_ipv4(address):
            expl = _('accessIPv4 is not proper IPv4 format')
            raise exc.HTTPBadRequest(explanation=expl)

    def _validate_access_ipv6(self, address):
        if not utils.is_valid_ipv6(address):
            expl = _('accessIPv6 is not proper IPv6 format')
            raise exc.HTTPBadRequest(explanation=expl)

    @wsgi.serializers(xml=ServerTemplate)
    def show(self, req, id):
        """Returns server details by server id."""
        try:
            context = req.environ['nova.context']
            instance = self.compute_api.get(context, id,
                                            want_objects=True)
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
                sg_names = [sg['name'] for sg in security_groups
                            if sg.get('name')]
        if not sg_names:
            sg_names.append('default')

        sg_names = list(set(sg_names))

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

        (access_ip_v4, ) = server_dict.get('accessIPv4'),
        if access_ip_v4 is not None:
            self._validate_access_ipv4(access_ip_v4)

        (access_ip_v6, ) = server_dict.get('accessIPv6'),
        if access_ip_v6 is not None:
            self._validate_access_ipv6(access_ip_v6)

        try:
            flavor_id = self._flavor_id_from_req_data(body)
        except ValueError as error:
            msg = _("Invalid flavorRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        # optional openstack extensions:
        key_name = None
        if self.ext_mgr.is_loaded('os-keypairs'):
            key_name = server_dict.get('key_name')

        user_data = None
        if self.ext_mgr.is_loaded('os-user-data'):
            user_data = server_dict.get('user_data')
        self._validate_user_data(user_data)

        availability_zone = None
        if self.ext_mgr.is_loaded('os-availability-zone'):
            availability_zone = server_dict.get('availability_zone')

        block_device_mapping = None
        block_device_mapping_v2 = None
        legacy_bdm = True
        if self.ext_mgr.is_loaded('os-volumes'):
            block_device_mapping = server_dict.get('block_device_mapping', [])
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

                # Assume legacy format
                legacy_bdm = not bool(block_device_mapping_v2)

                try:
                    block_device_mapping_v2 = [
                        block_device.BlockDeviceDict.from_api(bdm_dict)
                        for bdm_dict in block_device_mapping_v2]
                except exception.InvalidBDMFormat as e:
                    raise exc.HTTPBadRequest(explanation=e.format_message())

        block_device_mapping = (block_device_mapping or
                                block_device_mapping_v2)

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
                            config_drive=config_drive,
                            block_device_mapping=block_device_mapping,
                            auto_disk_config=auto_disk_config,
                            scheduler_hints=scheduler_hints,
                            legacy_bdm=legacy_bdm)
        except (exception.QuotaError,
                exception.PortLimitExceeded) as error:
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
            msg = _("Invalid flavorRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.KeypairNotFound as error:
            msg = _("Invalid key_name provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.ConfigDriveInvalidValue:
            msg = _("Invalid config_drive provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except messaging.RemoteError as err:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': err.exc_type,
                                                 'err_msg': err.value}
            raise exc.HTTPBadRequest(explanation=msg)
        except UnicodeDecodeError as error:
            msg = "UnicodeError: %s" % unicode(error)
            raise exc.HTTPBadRequest(explanation=msg)
        except (exception.ImageNotActive,
                exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.InvalidMetadata,
                exception.InvalidRequest,
                exception.MultiplePortsNotApplicable,
                exception.NetworkNotFound,
                exception.PortNotFound,
                exception.SecurityGroupNotFound,
                exception.InvalidBDM,
                exception.PortRequiresFixedIP,
                exception.NetworkRequiresSubnet,
                exception.InstanceUserDataMalformed) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except (exception.PortInUse,
                exception.NoUniqueMatch) as error:
            raise exc.HTTPConflict(explanation=error.format_message())

        # If the caller wanted a reservation_id, return it
        if ret_resv_id:
            return wsgi.ResponseObject({'reservation_id': resv_id},
                                       xml=ServerMultipleCreateTemplate)

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

        try:
            instance = self.compute_api.get(ctxt, id,
                                            want_objects=True)
            req.cache_db_instance(instance)
            policy.enforce(ctxt, 'compute:update', instance)
            instance.update(update_dict)
            instance.save()
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.show(req, instance)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
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
                    'confirmResize')
        return exc.HTTPNoContent()

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
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
                    'revertResize')
        return webob.Response(status_int=202)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
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
                    'reboot')
        return webob.Response(status_int=202)

    def _resize(self, req, instance_id, flavor_id, **kwargs):
        """Begin the resize process with given instance/flavor."""
        context = req.environ["nova.context"]
        instance = self._get_server(context, req, instance_id)
        try:
            self.compute_api.resize(context, instance, flavor_id, **kwargs)
        except exception.QuotaError as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message(),
                headers={'Retry-After': 0})
        except exception.FlavorNotFound:
            msg = _("Unable to locate requested flavor.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeToSameFlavor:
            msg = _("Resize requires a flavor change.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
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
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete')

    def _image_ref_from_req_data(self, data):
        try:
            return unicode(data['server']['imageRef'])
        except (TypeError, KeyError):
            msg = _("Missing imageRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)

    def _image_uuid_from_href(self, image_href):
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

        return common.get_id_from_href(flavor_ref)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('changePassword')
    def _action_change_password(self, req, id, body):
        context = req.environ['nova.context']
        if (not 'changePassword' in body
                or 'adminPass' not in body['changePassword']):
            msg = _("No adminPass was specified")
            raise exc.HTTPBadRequest(explanation=msg)
        password = self._get_server_admin_password(body['changePassword'])

        server = self._get_server(context, req, id)
        try:
            self.compute_api.set_admin_password(context, server, password)
        except NotImplementedError:
            msg = _("Unable to set password on instance")
            raise exc.HTTPNotImplemented(explanation=msg)
        return webob.Response(status_int=202)

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
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
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
                exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.InvalidMetadata) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

        instance = self._get_server(context, req, id)

        view = self._view_builder.show(req, instance)

        # Add on the adminPass attribute since the view doesn't do it
        # unless instance passwords are disabled
        if CONF.enable_instance_password:
            view['server']['adminPass'] = password

        robj = wsgi.ResponseObject(view)
        return self._add_location(robj)

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
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

        bdms = block_device_obj.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

        try:
            if self.compute_api.is_volume_backed_instance(context, instance,
                                                          bdms):
                img = instance['image_ref']
                if not img:
                    props = bdms.root_metadata(
                            context, self.compute_api.image_service,
                            self.compute_api.volume_api)
                    image_meta = {'properties': props}
                else:
                    src_image = self.compute_api.image_service.\
                                                show(context, img)
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
                        'createImage')
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
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
                        if opt not in allowed_search_options]
    LOG.debug(_("Removing options '%s' from query"),
              ", ".join(unknown_options))
    for opt in unknown_options:
        search_options.pop(opt, None)

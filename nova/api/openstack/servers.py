# Copyright 2010 OpenStack LLC.
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
import traceback

from webob import exc
import webob
from xml.dom import minidom

from nova import compute
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.api.openstack import common
from nova.api.openstack import create_instance_helper as helper
import nova.api.openstack.views.addresses
import nova.api.openstack.views.flavors
import nova.api.openstack.views.images
import nova.api.openstack.views.servers
from nova.api.openstack import wsgi
import nova.api.openstack
from nova.scheduler import api as scheduler_api


LOG = logging.getLogger('nova.api.openstack.servers')
FLAGS = flags.FLAGS


class Controller(object):
    """ The Server API controller for the OpenStack API """

    def __init__(self):
        self.compute_api = compute.API()
        self.helper = helper.CreateInstanceHelper(self)

    def index(self, req):
        """ Returns a list of server names and ids for a given user """
        try:
            servers = self._items(req, is_detail=False)
        except exception.Invalid as err:
            return exc.HTTPBadRequest(explanation=str(err))
        return servers

    def detail(self, req):
        """ Returns a list of server details for a given user """
        try:
            servers = self._items(req, is_detail=True)
        except exception.Invalid as err:
            return exc.HTTPBadRequest(explanation=str(err))
        return servers

    def _build_view(self, req, instance, is_detail=False):
        raise NotImplementedError()

    def _limit_items(self, items, req):
        raise NotImplementedError()

    def _action_rebuild(self, info, request, instance_id):
        raise NotImplementedError()

    def _items(self, req, is_detail):
        """Returns a list of servers for a given user.

        builder - the response model builder
        """
        query_str = req.str_GET
        reservation_id = query_str.get('reservation_id')
        project_id = query_str.get('project_id')
        fixed_ip = query_str.get('fixed_ip')
        recurse_zones = utils.bool_from_str(query_str.get('recurse_zones'))
        instance_list = self.compute_api.get_all(
                req.environ['nova.context'],
                reservation_id=reservation_id,
                project_id=project_id,
                fixed_ip=fixed_ip,
                recurse_zones=recurse_zones)
        limited_list = self._limit_items(instance_list, req)
        servers = [self._build_view(req, inst, is_detail)['server']
                for inst in limited_list]
        return dict(servers=servers)

    @scheduler_api.redirect_handler
    def show(self, req, id):
        """ Returns server details by server id """
        try:
            instance = self.compute_api.routing_get(
                req.environ['nova.context'], id)
            return self._build_view(req, instance, is_detail=True)
        except exception.NotFound:
            raise exc.HTTPNotFound()

    def create(self, req, body):
        """ Creates a new server for a given user """
        extra_values = None
        result = None
        extra_values, instances = self.helper.create_instance(
                req, body, self.compute_api.create)

        # We can only return 1 instance via the API, if we happen to
        # build more than one...  instances is a list, so we'll just
        # use the first one..
        inst = instances[0]
        for key in ['instance_type', 'image_ref']:
            inst[key] = extra_values[key]

        server = self._build_view(req, inst, is_detail=True)
        server['server']['adminPass'] = extra_values['password']
        return server

    @scheduler_api.redirect_handler
    def update(self, req, id, body):
        """ Updates the server name or password """
        if len(req.body) == 0:
            raise exc.HTTPUnprocessableEntity()

        if not body:
            raise exc.HTTPUnprocessableEntity()

        ctxt = req.environ['nova.context']
        update_dict = {}

        if 'name' in body['server']:
            name = body['server']['name']
            self.helper._validate_server_name(name)
            update_dict['display_name'] = name.strip()

        self._parse_update(ctxt, id, body, update_dict)

        try:
            self.compute_api.update(ctxt, id, **update_dict)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return exc.HTTPNoContent()

    def _parse_update(self, context, id, inst_dict, update_dict):
        pass

    @scheduler_api.redirect_handler
    def action(self, req, id, body):
        """Multi-purpose method used to reboot, rebuild, or
        resize a server"""

        actions = {
            'changePassword': self._action_change_password,
            'reboot': self._action_reboot,
            'resize': self._action_resize,
            'confirmResize': self._action_confirm_resize,
            'revertResize': self._action_revert_resize,
            'rebuild': self._action_rebuild,
            'migrate': self._action_migrate}

        for key in actions.keys():
            if key in body:
                return actions[key](body, req, id)
        raise exc.HTTPNotImplemented()

    def _action_change_password(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_confirm_resize(self, input_dict, req, id):
        try:
            self.compute_api.confirm_resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in confirm-resize %s"), e)
            raise exc.HTTPBadRequest()
        return exc.HTTPNoContent()

    def _action_revert_resize(self, input_dict, req, id):
        try:
            self.compute_api.revert_resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in revert-resize %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    def _action_resize(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_reboot(self, input_dict, req, id):
        if 'reboot' in input_dict and 'type' in input_dict['reboot']:
            reboot_type = input_dict['reboot']['type']
        else:
            LOG.exception(_("Missing argument 'type' for reboot"))
            raise exc.HTTPUnprocessableEntity()
        try:
            # TODO(gundlach): pass reboot_type, support soft reboot in
            # virt driver
            self.compute_api.reboot(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in reboot %s"), e)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    def _action_migrate(self, input_dict, req, id):
        try:
            self.compute_api.resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in migrate %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def lock(self, req, id):
        """
        lock the instance with id
        admin only operation

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.lock(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::lock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def unlock(self, req, id):
        """
        unlock the instance with id
        admin only operation

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.unlock(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unlock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def get_lock(self, req, id):
        """
        return the boolean state of (instance with id)'s lock

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.get_lock(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::get_lock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def reset_network(self, req, id, body):
        """
        Reset networking on an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.reset_network(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::reset_network %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def inject_network_info(self, req, id, body):
        """
        Inject network info for an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.inject_network_info(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::inject_network_info %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def pause(self, req, id, body):
        """ Permit Admins to Pause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.pause(ctxt, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::pause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def unpause(self, req, id, body):
        """ Permit Admins to Unpause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.unpause(ctxt, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unpause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def suspend(self, req, id, body):
        """permit admins to suspend the server"""
        context = req.environ['nova.context']
        try:
            self.compute_api.suspend(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::suspend %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def resume(self, req, id, body):
        """permit admins to resume the server from suspend"""
        context = req.environ['nova.context']
        try:
            self.compute_api.resume(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::resume %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def rescue(self, req, id):
        """Permit users to rescue the server."""
        context = req.environ["nova.context"]
        try:
            self.compute_api.rescue(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::rescue %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def unrescue(self, req, id):
        """Permit users to unrescue the server."""
        context = req.environ["nova.context"]
        try:
            self.compute_api.unrescue(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::unrescue %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def get_ajax_console(self, req, id):
        """Returns a url to an instance's ajaxterm console."""
        try:
            self.compute_api.get_ajax_console(req.environ['nova.context'],
                int(id))
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def get_vnc_console(self, req, id):
        """Returns a url to an instance's ajaxterm console."""
        try:
            self.compute_api.get_vnc_console(req.environ['nova.context'],
                                             int(id))
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def diagnostics(self, req, id):
        """Permit Admins to retrieve server diagnostics."""
        ctxt = req.environ["nova.context"]
        return self.compute_api.get_diagnostics(ctxt, id)

    def actions(self, req, id):
        """Permit Admins to retrieve server actions."""
        ctxt = req.environ["nova.context"]
        items = self.compute_api.get_actions(ctxt, id)
        actions = []
        # TODO(jk0): Do not do pre-serialization here once the default
        # serializer is updated
        for item in items:
            actions.append(dict(
                created_at=str(item.created_at),
                action=item.action,
                error=item.error))
        return dict(actions=actions)


class ControllerV10(Controller):

    @scheduler_api.redirect_handler
    def delete(self, req, id):
        """ Destroys a server """
        try:
            self.compute_api.delete(req.environ['nova.context'], id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    def _image_ref_from_req_data(self, data):
        return data['server']['imageId']

    def _flavor_id_from_req_data(self, data):
        return data['server']['flavorId']

    def _build_view(self, req, instance, is_detail=False):
        addresses = nova.api.openstack.views.addresses.ViewBuilderV10()
        builder = nova.api.openstack.views.servers.ViewBuilderV10(addresses)
        return builder.build(instance, is_detail=is_detail)

    def _limit_items(self, items, req):
        return common.limited(items, req)

    def _parse_update(self, context, server_id, inst_dict, update_dict):
        if 'adminPass' in inst_dict['server']:
            self.compute_api.set_admin_password(context, server_id,
                    inst_dict['server']['adminPass'])

    def _action_resize(self, input_dict, req, id):
        """ Resizes a given instance to the flavor size requested """
        if 'resize' in input_dict and 'flavorId' in input_dict['resize']:
            flavor_id = input_dict['resize']['flavorId']
            self.compute_api.resize(req.environ['nova.context'], id,
                    flavor_id)
        else:
            LOG.exception(_("Missing 'flavorId' argument for resize"))
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    def _action_rebuild(self, info, request, instance_id):
        context = request.environ['nova.context']
        instance_id = int(instance_id)

        try:
            image_id = info["rebuild"]["imageId"]
        except (KeyError, TypeError):
            msg = _("Could not parse imageId from request.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            self.compute_api.rebuild(context, instance_id, image_id)
        except exception.BuildInProgress:
            msg = _("Instance %d is currently being rebuilt.") % instance_id
            LOG.debug(msg)
            raise exc.HTTPConflict(explanation=msg)

        return webob.Response(status_int=202)

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self.helper._get_server_admin_password_old_style(server)


class ControllerV11(Controller):

    @scheduler_api.redirect_handler
    def delete(self, req, id):
        """ Destroys a server """
        try:
            self.compute_api.delete(req.environ['nova.context'], id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

    def _image_ref_from_req_data(self, data):
        return data['server']['imageRef']

    def _flavor_id_from_req_data(self, data):
        href = data['server']['flavorRef']
        return common.get_id_from_href(href)

    def _build_view(self, req, instance, is_detail=False):
        base_url = req.application_url
        flavor_builder = nova.api.openstack.views.flavors.ViewBuilderV11(
            base_url)
        image_builder = nova.api.openstack.views.images.ViewBuilderV11(
            base_url)
        addresses_builder = nova.api.openstack.views.addresses.ViewBuilderV11()
        builder = nova.api.openstack.views.servers.ViewBuilderV11(
            addresses_builder, flavor_builder, image_builder, base_url)

        return builder.build(instance, is_detail=is_detail)

    def _action_change_password(self, input_dict, req, id):
        context = req.environ['nova.context']
        if (not 'changePassword' in input_dict
            or not 'adminPass' in input_dict['changePassword']):
            msg = _("No adminPass was specified")
            return exc.HTTPBadRequest(explanation=msg)
        password = input_dict['changePassword']['adminPass']
        if not isinstance(password, basestring) or password == '':
            msg = _("Invalid adminPass")
            return exc.HTTPBadRequest(explanation=msg)
        self.compute_api.set_admin_password(context, id, password)
        return webob.Response(status_int=202)

    def _limit_items(self, items, req):
        return common.limited_by_marker(items, req)

    def _validate_metadata(self, metadata):
        """Ensure that we can work with the metadata given."""
        try:
            metadata.iteritems()
        except AttributeError as ex:
            msg = _("Unable to parse metadata key/value pairs.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

    def _decode_personalities(self, personalities):
        """Decode the Base64-encoded personalities."""
        for personality in personalities:
            try:
                path = personality["path"]
                contents = personality["contents"]
            except (KeyError, TypeError):
                msg = _("Unable to parse personality path/contents.")
                LOG.info(msg)
                raise exc.HTTPBadRequest(explanation=msg)

            try:
                personality["contents"] = base64.b64decode(contents)
            except TypeError:
                msg = _("Personality content could not be Base64 decoded.")
                LOG.info(msg)
                raise exc.HTTPBadRequest(explanation=msg)

    def _action_resize(self, input_dict, req, id):
        """ Resizes a given instance to the flavor size requested """
        try:
            if 'resize' in input_dict and 'flavorRef' in input_dict['resize']:
                flavor_ref = input_dict['resize']['flavorRef']
                flavor_id = common.get_id_from_href(flavor_ref)
                self.compute_api.resize(req.environ['nova.context'], id,
                        flavor_id)
            else:
                LOG.exception(_("Missing 'flavorRef' argument for resize"))
                raise exc.HTTPUnprocessableEntity()
        except Exception, e:
            LOG.exception(_("Error in resize %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    def _action_rebuild(self, info, request, instance_id):
        context = request.environ['nova.context']
        instance_id = int(instance_id)

        try:
            image_href = info["rebuild"]["imageRef"]
        except (KeyError, TypeError):
            msg = _("Could not parse imageRef from request.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        personalities = info["rebuild"].get("personality", [])
        metadata = info["rebuild"].get("metadata")
        name = info["rebuild"].get("name")

        if metadata:
            self._validate_metadata(metadata)
        self._decode_personalities(personalities)

        try:
            self.compute_api.rebuild(context, instance_id, image_href, name,
                                     metadata, personalities)
        except exception.BuildInProgress:
            msg = _("Instance %d is currently being rebuilt.") % instance_id
            LOG.debug(msg)
            raise exc.HTTPConflict(explanation=msg)

        return webob.Response(status_int=202)

    def get_default_xmlns(self, req):
        return common.XML_NS_V11

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self.helper._get_server_admin_password_new_style(server)


class HeadersSerializer(wsgi.ResponseHeadersSerializer):

    def delete(self, response, data):
        response.status_int = 204


class ServerXMLSerializer(wsgi.XMLDictSerializer):

    xmlns = wsgi.XMLNS_V11

    def __init__(self):
        self.metadata_serializer = common.MetadataXMLSerializer()

    def _create_basic_entity_node(self, xml_doc, id, links, name):
        basic_node = xml_doc.createElement(name)
        basic_node.setAttribute('id', str(id))
        link_nodes = self._create_link_nodes(xml_doc, links)
        for link_node in link_nodes:
            basic_node.appendChild(link_node)
        return basic_node

    def _create_metadata_node(self, xml_doc, metadata):
        return self.metadata_serializer.meta_list_to_xml(xml_doc, metadata)

    def _create_addresses_node(self, xml_doc, addresses):
        addresses_node = xml_doc.createElement('addresses')
        for name, network_dict in addresses.items():
            network_node = self._create_network_node(xml_doc,
                                                     name,
                                                     network_dict)
            addresses_node.appendChild(network_node)
        return addresses_node

    def _create_network_node(self, xml_doc, network_name, network_dict):
        network_node = xml_doc.createElement('network')
        network_node.setAttribute('id', network_name)
        for ip in network_dict:
            ip_node = xml_doc.createElement('ip')
            ip_node.setAttribute('version', str(ip['version']))
            ip_node.setAttribute('addr', ip['addr'])
            network_node.appendChild(ip_node)
        return network_node

    def _add_server_attributes(self, node, server):
        node.setAttribute('id', str(server['id']))
        node.setAttribute('uuid', str(server['uuid']))
        node.setAttribute('hostId', str(server['hostId']))
        node.setAttribute('name', server['name'])
        node.setAttribute('created', server['created'])
        node.setAttribute('updated', server['updated'])
        node.setAttribute('status', server['status'])
        if 'progress' in server:
            node.setAttribute('progress', str(server['progress']))

    def _server_to_xml(self, xml_doc, server):
        server_node = xml_doc.createElement('server')
        server_node.setAttribute('id', str(server['id']))
        server_node.setAttribute('name', server['name'])
        link_nodes = self._create_link_nodes(xml_doc,
                                             server['links'])
        for link_node in link_nodes:
            server_node.appendChild(link_node)
        return server_node

    def _server_to_xml_detailed(self, xml_doc, server):
        server_node = xml_doc.createElement('server')
        self._add_server_attributes(server_node, server)

        link_nodes = self._create_link_nodes(xml_doc,
                                             server['links'])
        for link_node in link_nodes:
            server_node.appendChild(link_node)

        image_node = self._create_basic_entity_node(xml_doc,
                                                    server['image']['id'],
                                                    server['image']['links'],
                                                    'image')
        server_node.appendChild(image_node)

        flavor_node = self._create_basic_entity_node(xml_doc,
                                                    server['flavor']['id'],
                                                    server['flavor']['links'],
                                                    'flavor')
        server_node.appendChild(flavor_node)

        metadata = server.get('metadata', {}).items()
        if len(metadata) > 0:
            metadata_node = self._create_metadata_node(xml_doc, metadata)
            server_node.appendChild(metadata_node)

        addresses_node = self._create_addresses_node(xml_doc,
                                                     server['addresses'])
        server_node.appendChild(addresses_node)

        return server_node

    def _server_list_to_xml(self, xml_doc, servers, detailed):
        container_node = xml_doc.createElement('servers')
        if detailed:
            server_to_xml = self._server_to_xml_detailed
        else:
            server_to_xml = self._server_to_xml

        for server in servers:
            item_node = server_to_xml(xml_doc, server)
            container_node.appendChild(item_node)
        return container_node

    def index(self, servers_dict):
        xml_doc = minidom.Document()
        node = self._server_list_to_xml(xml_doc,
                                       servers_dict['servers'],
                                       detailed=False)
        return self.to_xml_string(node, True)

    def detail(self, servers_dict):
        xml_doc = minidom.Document()
        node = self._server_list_to_xml(xml_doc,
                                       servers_dict['servers'],
                                       detailed=True)
        return self.to_xml_string(node, True)

    def show(self, server_dict):
        xml_doc = minidom.Document()
        node = self._server_to_xml_detailed(xml_doc,
                                       server_dict['server'])
        return self.to_xml_string(node, True)

    def create(self, server_dict):
        xml_doc = minidom.Document()
        node = self._server_to_xml_detailed(xml_doc,
                                       server_dict['server'])
        node.setAttribute('adminPass', server_dict['server']['adminPass'])
        return self.to_xml_string(node, True)


def create_resource(version='1.0'):
    controller = {
        '1.0': ControllerV10,
        '1.1': ControllerV11,
    }[version]()

    metadata = {
        "attributes": {
            "server": ["id", "imageId", "name", "flavorId", "hostId",
                       "status", "progress", "adminPass", "flavorRef",
                       "imageRef"],
            "link": ["rel", "type", "href"],
        },
        "dict_collections": {
            "metadata": {"item_name": "meta", "item_key": "key"},
        },
        "list_collections": {
            "public": {"item_name": "ip", "item_key": "addr"},
            "private": {"item_name": "ip", "item_key": "addr"},
        },
    }

    xmlns = {
        '1.0': wsgi.XMLNS_V10,
        '1.1': wsgi.XMLNS_V11,
    }[version]

    headers_serializer = HeadersSerializer()

    xml_serializer = {
        '1.0': wsgi.XMLDictSerializer(metadata, wsgi.XMLNS_V10),
        '1.1': ServerXMLSerializer(),
    }[version]

    body_serializers = {
        'application/xml': xml_serializer,
    }

    body_deserializers = {
        'application/xml': helper.ServerXMLDeserializer(),
    }

    serializer = wsgi.ResponseSerializer(body_serializers, headers_serializer)
    deserializer = wsgi.RequestDeserializer(body_deserializers)

    return wsgi.Resource(controller, deserializer, serializer)

# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import re
from urlparse import urlparse
from webob import exc
from xml.dom import minidom

import webob

from nova import exception
from nova import flags
from nova import log as logging
from nova import quota
from nova import utils
from nova import wsgi

from nova.compute import instance_types
from nova.api.openstack import common
from nova.api.openstack import faults
from nova.auth import manager as auth_manager


LOG = logging.getLogger('nova.api.openstack.create_instance_controller')
FLAGS = flags.FLAGS


class OpenstackCreateInstanceController(common.OpenstackController):
    """This is the base class for OS API Controllers that
    are capable of creating instances (currently Servers and Zones).

    Once we stabilize the Zones portion of the API we may be able
    to move this code back into servers.py
    """

    def __init__(self):
        """We need the image service to create an instance."""
        self._image_service = utils.import_object(FLAGS.image_service)
        super(OpenstackCreateInstanceController, self).__init__()

    def _image_id_from_req_data(self, data):
        raise NotImplementedError()

    def _flavor_id_from_req_data(self, data):
        raise NotImplementedError()

    def _get_server_admin_password(self, server):
        raise NotImplementedError()

    def create_instance(self, req, create_method):
        """Creates a new server for the given user. The approach
        used depends on the create_method. For example, the standard
        POST /server call uses compute.api.create(), while
        POST /zones/server uses compute.api.create_all_at_once().

        The problem is, both approaches return different values (i.e.
        [instance dicts] vs. reservation_id). So the handling of the
        return type from this method is left to the caller.
        """
        env = self._deserialize_create(req)
        if not env:
            return (None, faults.Fault(exc.HTTPUnprocessableEntity()))

        context = req.environ['nova.context']

        password = self._get_server_admin_password(env['server'])

        key_name = None
        key_data = None
        key_pairs = auth_manager.AuthManager.get_key_pairs(context)
        if key_pairs:
            key_pair = key_pairs[0]
            key_name = key_pair['name']
            key_data = key_pair['public_key']

        requested_image_id = self._image_id_from_req_data(env)
        try:
            image_id = common.get_image_id_from_image_hash(self._image_service,
                context, requested_image_id)
        except:
            msg = _("Can not find requested image")
            return (None, faults.Fault(exc.HTTPBadRequest(msg)))

        kernel_id, ramdisk_id = self._get_kernel_ramdisk_from_image(
            req, image_id)

        personality = env['server'].get('personality')
        injected_files = []
        if personality:
            injected_files = self._get_injected_files(personality)

        flavor_id = self._flavor_id_from_req_data(env)

        if not 'name' in env['server']:
            msg = _("Server name is not defined")
            return (None, exc.HTTPBadRequest(msg))
        name = env['server']['name']
        self._validate_server_name(name)
        name = name.strip()

        zone_blob = env['server'].get('blob')
        reservation_id = env['server'].get('reservation_id')

        inst_type = instance_types.get_instance_type_by_flavor_id(flavor_id)
        extra_values = {
            'instance_type': inst_type,
            'image_id': requested_image_id,
            'password': password
        }

        try:
            return (extra_values,
                    create_method(context,
                                  inst_type,
                                  image_id,
                                  kernel_id=kernel_id,
                                  ramdisk_id=ramdisk_id,
                                  display_name=name,
                                  display_description=name,
                                  key_name=key_name,
                                  key_data=key_data,
                                  metadata=env['server'].get('metadata', {}),
                                  injected_files=injected_files,
                                  admin_password=password,
                                  zone_blob=zone_blob,
                                  reservation_id=reservation_id
                    )
                )
        except quota.QuotaError as error:
            self._handle_quota_error(error)

        # Let the caller deal with unhandled exceptions.

    def _handle_quota_error(self, error):
        """
        Reraise quota errors as api-specific http exceptions
        """
        if error.code == "OnsetFileLimitExceeded":
            expl = _("Personality file limit exceeded")
            raise exc.HTTPBadRequest(explanation=expl)
        if error.code == "OnsetFilePathLimitExceeded":
            expl = _("Personality file path too long")
            raise exc.HTTPBadRequest(explanation=expl)
        if error.code == "OnsetFileContentLimitExceeded":
            expl = _("Personality file content too long")
            raise exc.HTTPBadRequest(explanation=expl)
        # if the original error is okay, just reraise it
        raise error

    def _deserialize_create(self, request):
        """
        Deserialize a create request

        Overrides normal behavior in the case of xml content
        """
        if request.content_type == "application/xml":
            deserializer = ServerCreateRequestXMLDeserializer()
            return deserializer.deserialize(request.body)
        else:
            return self._deserialize(request.body, request.get_content_type())

    def _validate_server_name(self, value):
        if not isinstance(value, basestring):
            msg = _("Server name is not a string or unicode")
            raise exc.HTTPBadRequest(msg)

        if value.strip() == '':
            msg = _("Server name is an empty string")
            raise exc.HTTPBadRequest(msg)

    def _get_kernel_ramdisk_from_image(self, req, image_id):
        """Fetch an image from the ImageService, then if present, return the
        associated kernel and ramdisk image IDs.
        """
        context = req.environ['nova.context']
        image_meta = self._image_service.show(context, image_id)
        # NOTE(sirp): extracted to a separate method to aid unit-testing, the
        # new method doesn't need a request obj or an ImageService stub
        kernel_id, ramdisk_id = self._do_get_kernel_ramdisk_from_image(
            image_meta)
        return kernel_id, ramdisk_id

    @staticmethod
    def  _do_get_kernel_ramdisk_from_image(image_meta):
        """Given an ImageService image_meta, return kernel and ramdisk image
        ids if present.

        This is only valid for `ami` style images.
        """
        image_id = image_meta['id']
        if image_meta['status'] != 'active':
            raise exception.ImageUnacceptable(image_id=image_id,
                                              reason=_("status is not active"))

        if image_meta.get('container_format') != 'ami':
            return None, None

        try:
            kernel_id = image_meta['properties']['kernel_id']
        except KeyError:
            raise exception.KernelNotFoundForImage(image_id=image_id)

        try:
            ramdisk_id = image_meta['properties']['ramdisk_id']
        except KeyError:
            raise exception.RamdiskNotFoundForImage(image_id=image_id)

        return kernel_id, ramdisk_id


class ServerCreateRequestXMLDeserializer(object):
    """
    Deserializer to handle xml-formatted server create requests.

    Handles standard server attributes as well as optional metadata
    and personality attributes
    """

    def deserialize(self, string):
        """Deserialize an xml-formatted server create request"""
        dom = minidom.parseString(string)
        server = self._extract_server(dom)
        return {'server': server}

    def _extract_server(self, node):
        """Marshal the server attribute of a parsed request"""
        server = {}
        server_node = self._find_first_child_named(node, 'server')
        for attr in ["name", "imageId", "flavorId", "imageRef", "flavorRef"]:
            if server_node.getAttribute(attr):
                server[attr] = server_node.getAttribute(attr)
        metadata = self._extract_metadata(server_node)
        if metadata is not None:
            server["metadata"] = metadata
        personality = self._extract_personality(server_node)
        if personality is not None:
            server["personality"] = personality
        return server

    def _extract_metadata(self, server_node):
        """Marshal the metadata attribute of a parsed request"""
        metadata_node = self._find_first_child_named(server_node, "metadata")
        if metadata_node is None:
            return None
        metadata = {}
        for meta_node in self._find_children_named(metadata_node, "meta"):
            key = meta_node.getAttribute("key")
            metadata[key] = self._extract_text(meta_node)
        return metadata

    def _extract_personality(self, server_node):
        """Marshal the personality attribute of a parsed request"""
        personality_node = \
                self._find_first_child_named(server_node, "personality")
        if personality_node is None:
            return None
        personality = []
        for file_node in self._find_children_named(personality_node, "file"):
            item = {}
            if file_node.hasAttribute("path"):
                item["path"] = file_node.getAttribute("path")
            item["contents"] = self._extract_text(file_node)
            personality.append(item)
        return personality

    def _find_first_child_named(self, parent, name):
        """Search a nodes children for the first child with a given name"""
        for node in parent.childNodes:
            if node.nodeName == name:
                return node
        return None

    def _find_children_named(self, parent, name):
        """Return all of a nodes children who have the given name"""
        for node in parent.childNodes:
            if node.nodeName == name:
                yield node

    def _extract_text(self, node):
        """Get the text field contained by the given node"""
        if len(node.childNodes) == 1:
            child = node.childNodes[0]
            if child.nodeType == child.TEXT_NODE:
                return child.nodeValue
        return ""

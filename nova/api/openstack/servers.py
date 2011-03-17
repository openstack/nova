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
import hashlib
import json
import traceback
from xml.dom import minidom

from webob import exc

from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova import wsgi
from nova import utils
from nova.api.openstack import common
from nova.api.openstack import faults
from nova.auth import manager as auth_manager
from nova.compute import instance_types
from nova.compute import power_state
import nova.api.openstack


LOG = logging.getLogger('server')


FLAGS = flags.FLAGS


def _translate_detail_keys(inst):
    """ Coerces into dictionary format, mapping everything to Rackspace-like
    attributes for return"""
    power_mapping = {
        None: 'build',
        power_state.NOSTATE: 'build',
        power_state.RUNNING: 'active',
        power_state.BLOCKED: 'active',
        power_state.SUSPENDED: 'suspended',
        power_state.PAUSED: 'paused',
        power_state.SHUTDOWN: 'active',
        power_state.SHUTOFF: 'active',
        power_state.CRASHED: 'error',
        power_state.FAILED: 'error'}
    inst_dict = {}

    mapped_keys = dict(status='state', imageId='image_id',
        flavorId='instance_type', name='display_name', id='id')

    for k, v in mapped_keys.iteritems():
        inst_dict[k] = inst[v]

    inst_dict['status'] = power_mapping[inst_dict['status']]
    inst_dict['addresses'] = dict(public=[], private=[])

    # grab single private fixed ip
    private_ips = utils.get_from_path(inst, 'fixed_ip/address')
    inst_dict['addresses']['private'] = private_ips

    # grab all public floating ips
    public_ips = utils.get_from_path(inst, 'fixed_ip/floating_ips/address')
    inst_dict['addresses']['public'] = public_ips

    # Return the metadata as a dictionary
    metadata = {}
    for item in inst['metadata']:
        metadata[item['key']] = item['value']
    inst_dict['metadata'] = metadata

    inst_dict['hostId'] = ''
    if inst['host']:
        inst_dict['hostId'] = hashlib.sha224(inst['host']).hexdigest()

    return dict(server=inst_dict)


def _translate_keys(inst):
    """ Coerces into dictionary format, excluding all model attributes
    save for id and name """
    return dict(server=dict(id=inst['id'], name=inst['display_name']))


class Controller(wsgi.Controller):
    """ The Server API controller for the OpenStack API """

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "server": ["id", "imageId", "name", "flavorId", "hostId",
                           "status", "progress", "adminPass"]}}}

    def __init__(self):
        self.compute_api = compute.API()
        self._image_service = utils.import_object(FLAGS.image_service)
        super(Controller, self).__init__()

    def index(self, req):
        """ Returns a list of server names and ids for a given user """
        return self._items(req, entity_maker=_translate_keys)

    def detail(self, req):
        """ Returns a list of server details for a given user """
        return self._items(req, entity_maker=_translate_detail_keys)

    def _items(self, req, entity_maker):
        """Returns a list of servers for a given user.

        entity_maker - either _translate_detail_keys or _translate_keys
        """
        instance_list = self.compute_api.get_all(req.environ['nova.context'])
        limited_list = common.limited(instance_list, req)
        res = [entity_maker(inst)['server'] for inst in limited_list]
        return dict(servers=res)

    def show(self, req, id):
        """ Returns server details by server id """
        try:
            instance = self.compute_api.get(req.environ['nova.context'], id)
            return _translate_detail_keys(instance)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

    def delete(self, req, id):
        """ Destroys a server """
        try:
            self.compute_api.delete(req.environ['nova.context'], id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return exc.HTTPAccepted()

    def create(self, req):
        """ Creates a new server for a given user """
        env = self._deserialize_create(req)
        if not env:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        context = req.environ['nova.context']

        key_name = None
        key_data = None
        key_pairs = auth_manager.AuthManager.get_key_pairs(context)
        if key_pairs:
            key_pair = key_pairs[0]
            key_name = key_pair['name']
            key_data = key_pair['public_key']

        image_id = common.get_image_id_from_image_hash(self._image_service,
            context, env['server']['imageId'])
        kernel_id, ramdisk_id = self._get_kernel_ramdisk_from_image(
            req, image_id)

        # Metadata is a list, not a Dictionary, because we allow duplicate keys
        # (even though JSON can't encode this)
        # In future, we may not allow duplicate keys.
        # However, the CloudServers API is not definitive on this front,
        #  and we want to be compatible.
        metadata = []
        if env['server'].get('metadata'):
            for k, v in env['server']['metadata'].items():
                metadata.append({'key': k, 'value': v})

        personality = env['server'].get('personality', [])
        injected_files = self._get_injected_files(personality)

        try:
            instances = self.compute_api.create(
                context,
                instance_types.get_by_flavor_id(env['server']['flavorId']),
                image_id,
                kernel_id=kernel_id,
                ramdisk_id=ramdisk_id,
                display_name=env['server']['name'],
                display_description=env['server']['name'],
                key_name=key_name,
                key_data=key_data,
                metadata=metadata,
                injected_files=injected_files)
        except QuotaError as error:
            self._handle_quota_error(error)

        server = _translate_keys(instances[0])
        password = "%s%s" % (server['server']['name'][:4],
                             utils.generate_password(12))
        server['server']['adminPass'] = password
        self.compute_api.set_admin_password(context, server['server']['id'],
                                            password)
        return server

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

    def _get_injected_files(self, personality):
        """
        Create a list of injected files from the personality attribute

        At this time, injected_files must be formatted as a list of
        (file_path, file_content) pairs for compatibility with the
        underlying compute service.
        """
        injected_files = []

        if not personality:
            return injected_files

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
            try:
                contents = base64.b64decode(contents)
            except TypeError:
                expl = _('Personality content for %s cannot be decoded') % path
                raise exc.HTTPBadRequest(explanation=expl)
            injected_files.append((path, contents))
        return injected_files

    def _handle_quota_errors(self, error):
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

    def update(self, req, id):
        """ Updates the server name or password """
        if len(req.body) == 0:
            raise exc.HTTPUnprocessableEntity()

        inst_dict = self._deserialize(req.body, req.get_content_type())
        if not inst_dict:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        ctxt = req.environ['nova.context']
        update_dict = {}
        if 'adminPass' in inst_dict['server']:
            update_dict['admin_pass'] = inst_dict['server']['adminPass']
            try:
                self.compute_api.set_admin_password(ctxt, id)
            except exception.TimeoutException, e:
                return exc.HTTPRequestTimeout()
        if 'name' in inst_dict['server']:
            update_dict['display_name'] = inst_dict['server']['name']
        try:
            self.compute_api.update(ctxt, id, **update_dict)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return exc.HTTPNoContent()

    def action(self, req, id):
        """Multi-purpose method used to reboot, rebuild, or
        resize a server"""

        actions = {
            'reboot':        self._action_reboot,
            'resize':        self._action_resize,
            'confirmResize': self._action_confirm_resize,
            'revertResize':  self._action_revert_resize,
            'rebuild':       self._action_rebuild,
            }

        input_dict = self._deserialize(req.body, req.get_content_type())
        for key in actions.keys():
            if key in input_dict:
                return actions[key](input_dict, req, id)
        return faults.Fault(exc.HTTPNotImplemented())

    def _action_confirm_resize(self, input_dict, req, id):
        try:
            self.compute_api.confirm_resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in confirm-resize %s"), e)
            return faults.Fault(exc.HTTPBadRequest())
        return exc.HTTPNoContent()

    def _action_revert_resize(self, input_dict, req, id):
        try:
            self.compute_api.revert_resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in revert-resize %s"), e)
            return faults.Fault(exc.HTTPBadRequest())
        return exc.HTTPAccepted()

    def _action_rebuild(self, input_dict, req, id):
        return faults.Fault(exc.HTTPNotImplemented())

    def _action_resize(self, input_dict, req, id):
        """ Resizes a given instance to the flavor size requested """
        try:
            if 'resize' in input_dict and 'flavorId' in input_dict['resize']:
                flavor_id = input_dict['resize']['flavorId']
                self.compute_api.resize(req.environ['nova.context'], id,
                        flavor_id)
            else:
                LOG.exception(_("Missing arguments for resize"))
                return faults.Fault(exc.HTTPUnprocessableEntity())
        except Exception, e:
            LOG.exception(_("Error in resize %s"), e)
            return faults.Fault(exc.HTTPBadRequest())
        return faults.Fault(exc.HTTPAccepted())

    def _action_reboot(self, input_dict, req, id):
        try:
            reboot_type = input_dict['reboot']['type']
        except Exception:
            raise faults.Fault(exc.HTTPNotImplemented())
        try:
            # TODO(gundlach): pass reboot_type, support soft reboot in
            # virt driver
            self.compute_api.reboot(req.environ['nova.context'], id)
        except:
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

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
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

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
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

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
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def reset_network(self, req, id):
        """
        Reset networking on an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.reset_network(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::reset_network %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def inject_network_info(self, req, id):
        """
        Inject network info for an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.inject_network_info(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::inject_network_info %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def pause(self, req, id):
        """ Permit Admins to Pause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.pause(ctxt, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::pause %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def unpause(self, req, id):
        """ Permit Admins to Unpause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.unpause(ctxt, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unpause %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def suspend(self, req, id):
        """permit admins to suspend the server"""
        context = req.environ['nova.context']
        try:
            self.compute_api.suspend(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::suspend %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def resume(self, req, id):
        """permit admins to resume the server from suspend"""
        context = req.environ['nova.context']
        try:
            self.compute_api.resume(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::resume %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def rescue(self, req, id):
        """Permit users to rescue the server."""
        context = req.environ["nova.context"]
        try:
            self.compute_api.rescue(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::rescue %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def unrescue(self, req, id):
        """Permit users to unrescue the server."""
        context = req.environ["nova.context"]
        try:
            self.compute_api.unrescue(context, id)
        except:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::unrescue %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def get_ajax_console(self, req, id):
        """ Returns a url to an instance's ajaxterm console. """
        try:
            self.compute_api.get_ajax_console(req.environ['nova.context'],
                int(id))
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return exc.HTTPAccepted()

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

    def _get_kernel_ramdisk_from_image(self, req, image_id):
        """Retrevies kernel and ramdisk IDs from Glance

        Only 'machine' (ami) type use kernel and ramdisk outside of the
        image.
        """
        # FIXME(sirp): Since we're retrieving the kernel_id from an
        # image_property, this means only Glance is supported.
        # The BaseImageService needs to expose a consistent way of accessing
        # kernel_id and ramdisk_id
        image = self._image_service.show(req.environ['nova.context'], image_id)

        if image['status'] != 'active':
            raise exception.Invalid(
                _("Cannot build from image %(image_id)s, status not active") %
                  locals())

        if image['disk_format'] != 'ami':
            return None, None

        try:
            kernel_id = image['properties']['kernel_id']
        except KeyError:
            raise exception.NotFound(
                _("Kernel not found for image %(image_id)s") % locals())

        try:
            ramdisk_id = image['properties']['ramdisk_id']
        except KeyError:
            raise exception.NotFound(
                _("Ramdisk not found for image %(image_id)s") % locals())

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
        for attr in ["name", "imageId", "flavorId"]:
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

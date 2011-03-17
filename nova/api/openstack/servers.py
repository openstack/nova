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

import hashlib
import json
import traceback

from webob import exc

from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova import wsgi
from nova import utils
from nova.api.openstack import common
from nova.api.openstack import faults
import nova.api.openstack.views.addresses
import nova.api.openstack.views.flavors
import nova.api.openstack.views.servers
from nova.auth import manager as auth_manager
from nova.compute import instance_types
from nova.compute import power_state
import nova.api.openstack


LOG = logging.getLogger('server')
FLAGS = flags.FLAGS


class Controller(wsgi.Controller):
    """ The Server API controller for the OpenStack API """

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "server": ["id", "imageId", "name", "flavorId", "hostId",
                           "status", "progress", "adminPass", "flavorRef",
                           "imageRef"]}}}

    def __init__(self):
        self.compute_api = compute.API()
        self._image_service = utils.import_object(FLAGS.image_service)
        super(Controller, self).__init__()

    def ips(self, req, id):
        try:
            instance = self.compute_api.get(req.environ['nova.context'], id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        builder = self._get_addresses_view_builder(req)
        return builder.build(instance)

    def index(self, req):
        """ Returns a list of server names and ids for a given user """
        return self._items(req, is_detail=False)

    def detail(self, req):
        """ Returns a list of server details for a given user """
        return self._items(req, is_detail=True)

    def _items(self, req, is_detail):
        """Returns a list of servers for a given user.

        builder - the response model builder
        """
        instance_list = self.compute_api.get_all(req.environ['nova.context'])
        limited_list = common.limited(instance_list, req)
        builder = self._get_view_builder(req)
        servers = [builder.build(inst, is_detail)['server']
                for inst in limited_list]
        return dict(servers=servers)

    def show(self, req, id):
        """ Returns server details by server id """
        try:
            instance = self.compute_api.get(req.environ['nova.context'], id)
            builder = self._get_view_builder(req)
            return builder.build(instance, is_detail=True)
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
        env = self._deserialize(req.body, req.get_content_type())
        if not env:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        context = req.environ['nova.context']
        key_pairs = auth_manager.AuthManager.get_key_pairs(context)
        if not key_pairs:
            raise exception.NotFound(_("No keypairs defined"))
        key_pair = key_pairs[0]

        requested_image_id = self._image_id_from_req_data(env)
        image_id = common.get_image_id_from_image_hash(self._image_service,
            context, requested_image_id)
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

        flavor_id = self._flavor_id_from_req_data(env)
        (inst,) = self.compute_api.create(
            context,
            instance_types.get_by_flavor_id(flavor_id),
            image_id,
            kernel_id=kernel_id,
            ramdisk_id=ramdisk_id,
            display_name=env['server']['name'],
            display_description=env['server']['name'],
            key_name=key_pair['name'],
            key_data=key_pair['public_key'],
            metadata=metadata,
            onset_files=env.get('onset_files', []))
        inst['instance_type'] = flavor_id
        inst['image_id'] = requested_image_id

        builder = self._get_view_builder(req)
        server = builder.build(inst, is_detail=True)
        password = "%s%s" % (server['server']['name'][:4],
                             utils.generate_password(12))
        server['server']['adminPass'] = password
        self.compute_api.set_admin_password(context, server['server']['id'],
                                            password)
        return server

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


class ControllerV10(Controller):
    def _image_id_from_req_data(self, data):
        return data['server']['imageId']

    def _flavor_id_from_req_data(self, data):
        return data['server']['flavorId']

    def _get_view_builder(self, req):
        addresses_builder = nova.api.openstack.views.addresses.ViewBuilderV10()
        return nova.api.openstack.views.servers.ViewBuilderV10(
            addresses_builder)

    def _get_addresses_view_builder(self, req):
        return nova.api.openstack.views.addresses.ViewBuilderV10(req)


class ControllerV11(Controller):
    def _image_id_from_req_data(self, data):
        href = data['server']['imageRef']
        return href.split('/')[-1]

    def _flavor_id_from_req_data(self, data):
        href = data['server']['flavorRef']
        return href.split('/')[-1]

    def _get_view_builder(self, req):
        base_url = req.application_url
        flavor_builder = nova.api.openstack.views.flavors.ViewBuilderV11(
            base_url)
        image_builder = nova.api.openstack.views.images.ViewBuilderV11(
            base_url)
        addresses_builder = nova.api.openstack.views.addresses.ViewBuilderV11()
        return nova.api.openstack.views.servers.ViewBuilderV11(
            addresses_builder, flavor_builder, image_builder)

    def _get_addresses_view_builder(self, req):
        return nova.api.openstack.views.addresses.ViewBuilderV11(req)

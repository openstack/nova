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
import os
import traceback

from webob import exc
from xml.dom import minidom
import webob

from nova import compute
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.api.openstack import common
from nova.api.openstack import create_instance_helper as helper
from nova.api.openstack import ips
from nova.api.openstack import wsgi
from nova.compute import instance_types
from nova.scheduler import api as scheduler_api
import nova.api.openstack
import nova.api.openstack.views.addresses
import nova.api.openstack.views.flavors
import nova.api.openstack.views.images
import nova.api.openstack.views.servers


LOG = logging.getLogger('nova.api.openstack.servers')
FLAGS = flags.FLAGS


class Controller(object):
    """ The Server API base controller class for the OpenStack API """

    def __init__(self):
        self.compute_api = compute.API()
        self.helper = helper.CreateInstanceHelper(self)

    def index(self, req):
        """ Returns a list of server names and ids for a given user """
        try:
            servers = self._get_servers(req, is_detail=False)
        except exception.Invalid as err:
            return exc.HTTPBadRequest(explanation=str(err))
        except exception.NotFound:
            return exc.HTTPNotFound()
        return servers

    def detail(self, req):
        """ Returns a list of server details for a given user """
        try:
            servers = self._get_servers(req, is_detail=True)
        except exception.Invalid as err:
            return exc.HTTPBadRequest(explanation=str(err))
        except exception.NotFound as err:
            return exc.HTTPNotFound()
        return servers

    def _build_view(self, req, instance, is_detail=False):
        raise NotImplementedError()

    def _limit_items(self, items, req):
        raise NotImplementedError()

    def _action_rebuild(self, info, request, instance_id):
        raise NotImplementedError()

    def _get_servers(self, req, is_detail):
        """Returns a list of servers, taking into account any search
        options specified.
        """

        search_opts = {}
        search_opts.update(req.str_GET)

        context = req.environ['nova.context']
        remove_invalid_options(context, search_opts,
                self._get_server_search_options())

        # Convert recurse_zones into a boolean
        search_opts['recurse_zones'] = utils.bool_from_str(
                search_opts.get('recurse_zones', False))

        # If search by 'status', we need to convert it to 'vm_state'
        # to pass on to child zones.
        if 'status' in search_opts:
            status = search_opts['status']
            state = common.vm_state_from_status(status)
            if state is None:
                reason = _('Invalid server status: %(status)s') % locals()
                raise exception.InvalidInput(reason=reason)
            search_opts['vm_state'] = state

        if 'changes-since' in search_opts:
            try:
                parsed = utils.parse_isotime(search_opts['changes-since'])
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

        instance_list = self.compute_api.get_all(context,
                                                 search_opts=search_opts)

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

    def _get_key_name(self, req, body):
        """ Get default keypair if not set """
        raise NotImplementedError()

    def create(self, req, body):
        """ Creates a new server for a given user """
        if 'server' in body:
            body['server']['key_name'] = self._get_key_name(req, body)

        extra_values = None
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
        """Update server then pass on to version-specific controller"""
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

        if 'accessIPv4' in body['server']:
            access_ipv4 = body['server']['accessIPv4']
            update_dict['access_ip_v4'] = access_ipv4.strip()

        if 'accessIPv6' in body['server']:
            access_ipv6 = body['server']['accessIPv6']
            update_dict['access_ip_v6'] = access_ipv6.strip()

        try:
            self.compute_api.update(ctxt, id, **update_dict)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return self._update(ctxt, req, id, body)

    def _update(self, context, req, id, inst_dict):
        return exc.HTTPNotImplemented()

    @scheduler_api.redirect_handler
    def action(self, req, id, body):
        """Multi-purpose method used to take actions on a server"""

        self.actions = {
            'changePassword': self._action_change_password,
            'reboot': self._action_reboot,
            'resize': self._action_resize,
            'confirmResize': self._action_confirm_resize,
            'revertResize': self._action_revert_resize,
            'rebuild': self._action_rebuild,
            'createImage': self._action_create_image,
        }

        if FLAGS.allow_admin_api:
            admin_actions = {
                'createBackup': self._action_create_backup,
            }
            self.actions.update(admin_actions)

        for key in body:
            if key in self.actions:
                return self.actions[key](body, req, id)
            else:
                msg = _("There is no such server action: %s") % (key,)
                raise exc.HTTPBadRequest(explanation=msg)

        msg = _("Invalid request body")
        raise exc.HTTPBadRequest(explanation=msg)

    def _action_create_backup(self, input_dict, req, instance_id):
        """Backup a server instance.

        Images now have an `image_type` associated with them, which can be
        'snapshot' or the backup type, like 'daily' or 'weekly'.

        If the image_type is backup-like, then the rotation factor can be
        included and that will cause the oldest backups that exceed the
        rotation factor to be deleted.

        """
        entity = input_dict["createBackup"]

        try:
            image_name = entity["name"]
            backup_type = entity["backup_type"]
            rotation = entity["rotation"]

        except KeyError as missing_key:
            msg = _("createBackup entity requires %s attribute") % missing_key
            raise webob.exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed createBackup entity")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            rotation = int(rotation)
        except ValueError:
            msg = _("createBackup attribute 'rotation' must be an integer")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # preserve link to server in image properties
        server_ref = os.path.join(req.application_url,
                                  'servers',
                                  str(instance_id))
        props = {'instance_ref': server_ref}

        metadata = entity.get('metadata', {})
        context = req.environ["nova.context"]
        common.check_img_metadata_quota_limit(context, metadata)
        try:
            props.update(metadata)
        except ValueError:
            msg = _("Invalid metadata")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        image = self.compute_api.backup(context,
                                        instance_id,
                                        image_name,
                                        backup_type,
                                        rotation,
                                        extra_properties=props)

        # build location of newly-created image entity
        image_id = str(image['id'])
        image_ref = os.path.join(req.application_url, 'images', image_id)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    @common.check_snapshots_enabled
    def _action_create_image(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_change_password(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_confirm_resize(self, input_dict, req, id):
        try:
            self.compute_api.confirm_resize(req.environ['nova.context'], id)
        except exception.MigrationNotFound:
            msg = _("Instance has not been resized.")
            raise exc.HTTPBadRequest(explanation=msg)
        except Exception, e:
            LOG.exception(_("Error in confirm-resize %s"), e)
            raise exc.HTTPBadRequest()
        return exc.HTTPNoContent()

    def _action_revert_resize(self, input_dict, req, id):
        try:
            self.compute_api.revert_resize(req.environ['nova.context'], id)
        except exception.MigrationNotFound:
            msg = _("Instance has not been resized.")
            raise exc.HTTPBadRequest(explanation=msg)
        except Exception, e:
            LOG.exception(_("Error in revert-resize %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    def _action_resize(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_reboot(self, input_dict, req, id):
        if 'reboot' in input_dict and 'type' in input_dict['reboot']:
            valid_reboot_types = ['HARD', 'SOFT']
            reboot_type = input_dict['reboot']['type'].upper()
            if not valid_reboot_types.count(reboot_type):
                msg = _("Argument 'type' for reboot is not HARD or SOFT")
                LOG.exception(msg)
                raise exc.HTTPBadRequest(explanation=msg)
        else:
            msg = _("Missing argument 'type' for reboot")
            LOG.exception(msg)
            raise exc.HTTPBadRequest(explanation=msg)
        try:
            # TODO(gundlach): pass reboot_type, support soft reboot in
            # virt driver
            self.compute_api.reboot(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in reboot %s"), e)
            raise exc.HTTPUnprocessableEntity()
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
        except Exception:
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
        except Exception:
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
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::get_lock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def reset_network(self, req, id):
        """
        Reset networking on an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.reset_network(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::reset_network %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def inject_network_info(self, req, id):
        """
        Inject network info for an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.inject_network_info(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::inject_network_info %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def pause(self, req, id):
        """ Permit Admins to Pause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.pause(ctxt, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::pause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def unpause(self, req, id):
        """ Permit Admins to Unpause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.unpause(ctxt, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unpause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def suspend(self, req, id):
        """permit admins to suspend the server"""
        context = req.environ['nova.context']
        try:
            self.compute_api.suspend(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::suspend %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def resume(self, req, id):
        """permit admins to resume the server from suspend"""
        context = req.environ['nova.context']
        try:
            self.compute_api.resume(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::resume %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def migrate(self, req, id):
        try:
            self.compute_api.resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in migrate %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    @scheduler_api.redirect_handler
    def rescue(self, req, id):
        """Permit users to rescue the server."""
        context = req.environ["nova.context"]
        try:
            self.compute_api.rescue(context, id)
        except Exception:
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
        except Exception:
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

    def resize(self, req, instance_id, flavor_id):
        """Begin the resize process with given instance/flavor."""
        context = req.environ["nova.context"]

        try:
            self.compute_api.resize(context, instance_id, flavor_id)
        except exception.FlavorNotFound:
            msg = _("Unable to locate requested flavor.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeToSameSize:
            msg = _("Resize requires a change in size.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeToSmallerSize:
            msg = _("Resizing to a smaller size is not supported.")
            raise exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=202)


class ControllerV10(Controller):
    """v1.0 OpenStack API controller"""

    @scheduler_api.redirect_handler
    def delete(self, req, id):
        """ Destroys a server """
        try:
            self.compute_api.delete(req.environ['nova.context'], id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    def _get_key_name(self, req, body):
        context = req.environ["nova.context"]
        keypairs = db.key_pair_get_all_by_user(context,
                                               context.user_id)
        if keypairs:
            return keypairs[0]['name']

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

    def _update(self, context, req, id, inst_dict):
        if 'adminPass' in inst_dict['server']:
            self.compute_api.set_admin_password(context, id,
                    inst_dict['server']['adminPass'])
        return exc.HTTPNoContent()

    def _action_resize(self, input_dict, req, id):
        """ Resizes a given instance to the flavor size requested """
        try:
            flavor_id = input_dict["resize"]["flavorId"]
        except (KeyError, TypeError):
            msg = _("Resize requests require 'flavorId' attribute.")
            raise exc.HTTPBadRequest(explanation=msg)

        return self.resize(req, id, flavor_id)

    def _action_rebuild(self, info, request, instance_id):
        context = request.environ['nova.context']

        try:
            image_id = info["rebuild"]["imageId"]
        except (KeyError, TypeError):
            msg = _("Could not parse imageId from request.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        password = utils.generate_password(16)

        try:
            self.compute_api.rebuild(context, instance_id, image_id, password)
        except exception.RebuildRequiresActiveInstance:
            msg = _("Instance %s must be active to rebuild.") % instance_id
            raise exc.HTTPConflict(explanation=msg)

        return webob.Response(status_int=202)

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self.helper._get_server_admin_password_old_style(server)

    def _get_server_search_options(self):
        """Return server search options allowed by non-admin"""
        return 'reservation_id', 'fixed_ip', 'name', 'recurse_zones'


class ControllerV11(Controller):
    """v1.1 OpenStack API controller"""

    @scheduler_api.redirect_handler
    def delete(self, req, id):
        """ Destroys a server """
        try:
            self.compute_api.delete(req.environ['nova.context'], id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

    def _get_key_name(self, req, body):
        if 'server' in body:
            return body['server'].get('key_name')

    def _image_ref_from_req_data(self, data):
        try:
            return data['server']['imageRef']
        except (TypeError, KeyError):
            msg = _("Missing imageRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)

    def _flavor_id_from_req_data(self, data):
        try:
            flavor_ref = data['server']['flavorRef']
        except (TypeError, KeyError):
            msg = _("Missing flavorRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)

        return common.get_id_from_href(flavor_ref)

    def _build_view(self, req, instance, is_detail=False):
        project_id = getattr(req.environ['nova.context'], 'project_id', '')
        base_url = req.application_url
        flavor_builder = nova.api.openstack.views.flavors.ViewBuilderV11(
            base_url, project_id)
        image_builder = nova.api.openstack.views.images.ViewBuilderV11(
            base_url, project_id)
        addresses_builder = nova.api.openstack.views.addresses.ViewBuilderV11()
        builder = nova.api.openstack.views.servers.ViewBuilderV11(
            addresses_builder, flavor_builder, image_builder,
            base_url, project_id)

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

    def _update(self, context, req, id, inst_dict):
        instance = self.compute_api.routing_get(context, id)
        return self._build_view(req, instance, is_detail=True)

    def _action_resize(self, input_dict, req, id):
        """ Resizes a given instance to the flavor size requested """
        try:
            flavor_ref = input_dict["resize"]["flavorRef"]
            if not flavor_ref:
                msg = _("Resize request has invalid 'flavorRef' attribute.")
                raise exc.HTTPBadRequest(explanation=msg)
        except (KeyError, TypeError):
            msg = _("Resize requests require 'flavorRef' attribute.")
            raise exc.HTTPBadRequest(explanation=msg)

        return self.resize(req, id, flavor_ref)

    def _action_rebuild(self, info, request, instance_id):
        context = request.environ['nova.context']

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

        password = info["rebuild"].get("adminPass",
                                       utils.generate_password(16))

        try:
            self.compute_api.rebuild(context, instance_id, image_href,
                                     password, name=name, metadata=metadata,
                                     files_to_inject=personalities)
        except exception.RebuildRequiresActiveInstance:
            msg = _("Instance %s must be active to rebuild.") % instance_id
            raise exc.HTTPConflict(explanation=msg)
        except exception.InstanceNotFound:
            msg = _("Instance %s could not be found") % instance_id
            raise exc.HTTPNotFound(explanation=msg)

        instance = self.compute_api.routing_get(context, instance_id)
        view = self._build_view(request, instance, is_detail=True)
        view['server']['adminPass'] = password

        return view

    @common.check_snapshots_enabled
    def _action_create_image(self, input_dict, req, instance_id):
        """Snapshot a server instance."""
        entity = input_dict.get("createImage", {})

        try:
            image_name = entity["name"]

        except KeyError:
            msg = _("createImage entity requires name attribute")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed createImage entity")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # preserve link to server in image properties
        server_ref = os.path.join(req.application_url,
                                  'servers',
                                  str(instance_id))
        props = {'instance_ref': server_ref}

        metadata = entity.get('metadata', {})
        context = req.environ['nova.context']
        common.check_img_metadata_quota_limit(context, metadata)
        try:
            props.update(metadata)
        except ValueError:
            msg = _("Invalid metadata")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            image = self.compute_api.snapshot(context,
                                              instance_id,
                                              image_name,
                                              extra_properties=props)
        except exception.InstanceBusy:
            msg = _("Server is currently creating an image. Please wait.")
            raise webob.exc.HTTPConflict(explanation=msg)

        # build location of newly-created image entity
        image_id = str(image['id'])
        image_ref = os.path.join(req.application_url,
                                 context.project_id,
                                 'images',
                                 image_id)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    def get_default_xmlns(self, req):
        return common.XML_NS_V11

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self.helper._get_server_admin_password_new_style(server)

    def _get_server_search_options(self):
        """Return server search options allowed by non-admin"""
        return ('reservation_id', 'name', 'recurse_zones',
                'status', 'image', 'flavor', 'changes-since')


class HeadersSerializer(wsgi.ResponseHeadersSerializer):

    def create(self, response, data):
        response.status_int = 202

    def delete(self, response, data):
        response.status_int = 204

    def action(self, response, data):
        response.status_int = 202


class ServerXMLSerializer(wsgi.XMLDictSerializer):

    xmlns = wsgi.XMLNS_V11

    def __init__(self):
        self.metadata_serializer = common.MetadataXMLSerializer()
        self.addresses_serializer = ips.IPXMLSerializer()

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
        return self.addresses_serializer.networks_to_xml(xml_doc, addresses)

    def _add_server_attributes(self, node, server):
        node.setAttribute('id', str(server['id']))
        node.setAttribute('userId', str(server['user_id']))
        node.setAttribute('tenantId', str(server['tenant_id']))
        node.setAttribute('uuid', str(server['uuid']))
        node.setAttribute('hostId', str(server['hostId']))
        node.setAttribute('name', server['name'])
        node.setAttribute('created', str(server['created']))
        node.setAttribute('updated', str(server['updated']))
        node.setAttribute('status', server['status'])
        if 'accessIPv4' in server:
            node.setAttribute('accessIPv4', str(server['accessIPv4']))
        if 'accessIPv6' in server:
            node.setAttribute('accessIPv6', str(server['accessIPv6']))
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

        if 'image' in server:
            image_node = self._create_basic_entity_node(xml_doc,
                                                    server['image']['id'],
                                                    server['image']['links'],
                                                    'image')
            server_node.appendChild(image_node)

        if 'flavor' in server:
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

        if 'security_groups' in server:
            security_groups_node = self._create_security_groups_node(xml_doc,
                                                    server['security_groups'])
            server_node.appendChild(security_groups_node)

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

    def action(self, server_dict):
        #NOTE(bcwaldon): We need a way to serialize actions individually. This
        # assumes all actions return a server entity
        return self.create(server_dict)

    def update(self, server_dict):
        xml_doc = minidom.Document()
        node = self._server_to_xml_detailed(xml_doc,
                                       server_dict['server'])
        return self.to_xml_string(node, True)

    def _security_group_to_xml(self, doc, security_group):
        node = doc.createElement('security_group')
        node.setAttribute('name', str(security_group.get('name')))
        return node

    def _create_security_groups_node(self, xml_doc, security_groups):
        security_groups_node = xml_doc.createElement('security_groups')
        if security_groups:
            for security_group in security_groups:
                node = self._security_group_to_xml(xml_doc, security_group)
                security_groups_node.appendChild(node)
        return security_groups_node


def create_resource(version='1.0'):
    controller = {
        '1.0': ControllerV10,
        '1.1': ControllerV11,
    }[version]()

    metadata = {
        "attributes": {
            "server": ["id", "imageId", "name", "flavorId", "hostId",
                       "status", "progress", "adminPass", "flavorRef",
                       "imageRef", "userId", "tenantId"],
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

    xml_deserializer = {
        '1.0': helper.ServerXMLDeserializer(),
        '1.1': helper.ServerXMLDeserializerV11(),
    }[version]

    body_deserializers = {
        'application/xml': xml_deserializer,
    }

    serializer = wsgi.ResponseSerializer(body_serializers, headers_serializer)
    deserializer = wsgi.RequestDeserializer(body_deserializers)

    return wsgi.Resource(controller, deserializer, serializer)


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context"""
    if FLAGS.allow_admin_api and context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
            if opt not in allowed_search_options]
    unk_opt_str = ", ".join(unknown_options)
    log_msg = _("Removing options '%(unk_opt_str)s' from query") % locals()
    LOG.debug(log_msg)
    for opt in unknown_options:
        search_options.pop(opt, None)

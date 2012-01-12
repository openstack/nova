#   Copyright 2011 Openstack, LLC.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import os.path
import traceback

import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.v2 import extensions
from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova.scheduler import api as scheduler_api


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.openstack.v2.contrib.admin_actions")


class Admin_actions(extensions.ExtensionDescriptor):
    """Enable admin-only server actions

    Actions include: pause, unpause, suspend, resume, migrate,
    resetNetwork, injectNetworkInfo, lock, unlock, createBackup
    """

    name = "AdminActions"
    alias = "os-admin-actions"
    namespace = "http://docs.openstack.org/compute/ext/admin-actions/api/v1.1"
    updated = "2011-09-20T00:00:00+00:00"
    admin_only = True

    def __init__(self, ext_mgr):
        super(Admin_actions, self).__init__(ext_mgr)
        self.compute_api = compute.API()

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _pause(self, input_dict, req, id):
        """Permit Admins to pause the server"""
        ctxt = req.environ['nova.context']
        try:
            server = self.compute_api.get(ctxt, id)
            self.compute_api.pause(ctxt, server)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'pause')
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::pause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _unpause(self, input_dict, req, id):
        """Permit Admins to unpause the server"""
        ctxt = req.environ['nova.context']
        try:
            server = self.compute_api.get(ctxt, id)
            self.compute_api.unpause(ctxt, server)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'unpause')
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unpause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _suspend(self, input_dict, req, id):
        """Permit admins to suspend the server"""
        context = req.environ['nova.context']
        try:
            server = self.compute_api.get(context, id)
            self.compute_api.suspend(context, server)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'suspend')
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::suspend %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _resume(self, input_dict, req, id):
        """Permit admins to resume the server from suspend"""
        context = req.environ['nova.context']
        try:
            server = self.compute_api.get(context, id)
            self.compute_api.resume(context, server)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'resume')
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::resume %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _migrate(self, input_dict, req, id):
        """Permit admins to migrate a server to a new host"""
        context = req.environ['nova.context']
        try:
            instance = self.compute_api.get(context, id)
            self.compute_api.resize(req.environ['nova.context'], instance)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'migrate')
        except Exception, e:
            LOG.exception(_("Error in migrate %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _reset_network(self, input_dict, req, id):
        """Permit admins to reset networking on an server"""
        context = req.environ['nova.context']
        try:
            instance = self.compute_api.get(context, id)
            self.compute_api.reset_network(context, instance)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::reset_network %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _inject_network_info(self, input_dict, req, id):
        """Permit admins to inject network info into a server"""
        context = req.environ['nova.context']
        try:
            instance = self.compute_api.get(context, id)
            self.compute_api.inject_network_info(context, instance)
        except exception.InstanceNotFound:
            raise exc.HTTPNotFound(_("Server not found"))
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::inject_network_info %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _lock(self, input_dict, req, id):
        """Permit admins to lock a server"""
        context = req.environ['nova.context']
        try:
            instance = self.compute_api.get(context, id)
            self.compute_api.lock(context, instance)
        except exception.InstanceNotFound:
            raise exc.HTTPNotFound(_("Server not found"))
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::lock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @exception.novaclient_converter
    @scheduler_api.redirect_handler
    def _unlock(self, input_dict, req, id):
        """Permit admins to lock a server"""
        context = req.environ['nova.context']
        try:
            instance = self.compute_api.get(context, id)
            self.compute_api.unlock(context, instance)
        except exception.InstanceNotFound:
            raise exc.HTTPNotFound(_("Server not found"))
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unlock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    def _create_backup(self, input_dict, req, instance_id):
        """Backup a server instance.

        Images now have an `image_type` associated with them, which can be
        'snapshot' or the backup type, like 'daily' or 'weekly'.

        If the image_type is backup-like, then the rotation factor can be
        included and that will cause the oldest backups that exceed the
        rotation factor to be deleted.

        """
        context = req.environ["nova.context"]

        try:
            entity = input_dict["createBackup"]
        except (KeyError, TypeError):
            raise exc.HTTPBadRequest(_("Malformed request body"))

        try:
            image_name = entity["name"]
            backup_type = entity["backup_type"]
            rotation = entity["rotation"]

        except KeyError as missing_key:
            msg = _("createBackup entity requires %s attribute") % missing_key
            raise exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed createBackup entity")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            rotation = int(rotation)
        except ValueError:
            msg = _("createBackup attribute 'rotation' must be an integer")
            raise exc.HTTPBadRequest(explanation=msg)

        # preserve link to server in image properties
        server_ref = os.path.join(req.application_url, 'servers', instance_id)
        props = {'instance_ref': server_ref}

        metadata = entity.get('metadata', {})
        common.check_img_metadata_quota_limit(context, metadata)
        try:
            props.update(metadata)
        except ValueError:
            msg = _("Invalid metadata")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            instance = self.compute_api.get(context, instance_id)
        except exception.NotFound:
            raise exc.HTTPNotFound(_("Instance not found"))

        try:
            image = self.compute_api.backup(context, instance, image_name,
                    backup_type, rotation, extra_properties=props)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'createBackup')

        # build location of newly-created image entity
        image_id = str(image['id'])
        image_ref = os.path.join(req.application_url, 'images', image_id)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    def get_actions(self):
        actions = [
            #TODO(bcwaldon): These actions should be prefixed with 'os-'
            extensions.ActionExtension("servers", "pause", self._pause),
            extensions.ActionExtension("servers", "unpause", self._unpause),
            extensions.ActionExtension("servers", "suspend", self._suspend),
            extensions.ActionExtension("servers", "resume", self._resume),
            extensions.ActionExtension("servers", "migrate", self._migrate),

            extensions.ActionExtension("servers",
                                       "createBackup",
                                       self._create_backup),

            extensions.ActionExtension("servers",
                                       "resetNetwork",
                                       self._reset_network),

            extensions.ActionExtension("servers",
                                       "injectNetworkInfo",
                                       self._inject_network_info),

            extensions.ActionExtension("servers", "lock", self._lock),
            extensions.ActionExtension("servers", "unlock", self._unlock),
        ]

        return actions

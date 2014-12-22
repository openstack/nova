# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _

ALIAS = "os-pause-server"

authorize = extensions.os_compute_authorizer(ALIAS)


class PauseServerController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(PauseServerController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API(skip_policy_check=True)

    @wsgi.response(202)
    @extensions.expected_errors((404, 409, 501))
    @wsgi.action('pause')
    def _pause(self, req, id, body):
        """Permit Admins to pause the server."""
        ctxt = req.environ['nova.context']
        authorize(ctxt, action='pause')
        server = common.get_instance(self.compute_api, ctxt, id,
                                     want_objects=True)
        try:
            self.compute_api.pause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'pause', id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Virt driver does not implement pause function.")
            raise exc.HTTPNotImplemented(explanation=msg)

    @wsgi.response(202)
    @extensions.expected_errors((404, 409, 501))
    @wsgi.action('unpause')
    def _unpause(self, req, id, body):
        """Permit Admins to unpause the server."""
        ctxt = req.environ['nova.context']
        authorize(ctxt, action='unpause')
        server = common.get_instance(self.compute_api, ctxt, id,
                                     want_objects=True)
        try:
            self.compute_api.unpause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'unpause', id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Virt driver does not implement pause function.")
            raise exc.HTTPNotImplemented(explanation=msg)


class PauseServer(extensions.V3APIExtensionBase):
    """Enable pause/unpause server actions."""

    name = "PauseServer"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = PauseServerController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []

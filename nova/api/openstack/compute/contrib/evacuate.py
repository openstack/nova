#   Copyright 2013 OpenStack Foundation
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


from oslo_utils import strutils
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _
from nova import utils

authorize = extensions.extension_authorizer('compute', 'evacuate')


class Controller(wsgi.Controller):
    def __init__(self, ext_mgr, *args, **kwargs):
        super(Controller, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.host_api = compute.HostAPI()
        self.ext_mgr = ext_mgr

    @wsgi.action('evacuate')
    def _evacuate(self, req, id, body):
        """Permit admins to evacuate a server from a failed host
        to a new one.
        If host is empty, the scheduler will select one.
        """
        context = req.environ["nova.context"]
        authorize(context)

        if not self.is_valid_body(body, "evacuate"):
            raise exc.HTTPBadRequest(_("Malformed request body"))
        evacuate_body = body["evacuate"]

        host = evacuate_body.get("host")

        if (not host and
                not self.ext_mgr.is_loaded('os-extended-evacuate-find-host')):
            msg = _("host must be specified.")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            on_shared_storage = strutils.bool_from_string(
                                            evacuate_body["onSharedStorage"])
        except (TypeError, KeyError):
            msg = _("onSharedStorage must be specified.")
            raise exc.HTTPBadRequest(explanation=msg)

        password = None
        if 'adminPass' in evacuate_body:
            # check that if requested to evacuate server on shared storage
            # password not specified
            if on_shared_storage:
                msg = _("admin password can't be changed on existing disk")
                raise exc.HTTPBadRequest(explanation=msg)

            password = evacuate_body['adminPass']
        elif not on_shared_storage:
            password = utils.generate_password()

        if host is not None:
            try:
                self.host_api.service_get_by_compute_host(context, host)
            except exception.NotFound:
                msg = _("Compute host %s not found.") % host
                raise exc.HTTPNotFound(explanation=msg)

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            if instance.host == host:
                msg = _("The target host can't be the same one.")
                raise exc.HTTPBadRequest(explanation=msg)
            self.compute_api.evacuate(context, instance, host,
                                      on_shared_storage, password)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'evacuate', id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.ComputeServiceInUse as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        if password:
            return {'adminPass': password}


class Evacuate(extensions.ExtensionDescriptor):
    """Enables server evacuation."""

    name = "Evacuate"
    alias = "os-evacuate"
    namespace = "http://docs.openstack.org/compute/ext/evacuate/api/v2"
    updated = "2013-01-06T00:00:00Z"

    def get_controller_extensions(self):
        controller = Controller(self.ext_mgr)
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

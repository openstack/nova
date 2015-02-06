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


from oslo_config import cfg
from oslo_utils import strutils
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas.v3 import evacuate
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova.i18n import _
from nova import utils

CONF = cfg.CONF
CONF.import_opt('enable_instance_password',
                'nova.api.openstack.compute.servers')

ALIAS = "os-evacuate"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class EvacuateController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(EvacuateController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.host_api = compute.HostAPI()

    # TODO(eliqiao): Should be responding here with 202 Accept
    # because evacuate is an async call, but keep to 200 for
    # backwards compatibility reasons.
    @extensions.expected_errors((400, 404, 409))
    @wsgi.action('evacuate')
    @validation.schema(evacuate.evacuate)
    def _evacuate(self, req, id, body):
        """Permit admins to evacuate a server from a failed host
        to a new one.
        """
        context = req.environ["nova.context"]
        authorize(context)

        evacuate_body = body["evacuate"]
        host = evacuate_body.get("host")
        on_shared_storage = strutils.bool_from_string(
                                        evacuate_body["onSharedStorage"])

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
        if instance.host == host:
            msg = _("The target host can't be the same one.")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            self.compute_api.evacuate(context, instance, host,
                                      on_shared_storage, password)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'evacuate', id)
        except exception.ComputeServiceInUse as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        if CONF.enable_instance_password:
            return {'adminPass': password}
        else:
            return {}


class Evacuate(extensions.V3APIExtensionBase):
    """Enables server evacuation."""

    name = "Evacuate"
    alias = ALIAS
    version = 1

    def get_resources(self):
        return []

    def get_controller_extensions(self):
        controller = EvacuateController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

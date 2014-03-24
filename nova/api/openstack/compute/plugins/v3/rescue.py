#   Copyright 2011 OpenStack Foundation
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

"""The rescue mode extension."""

from oslo.config import cfg
import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas.v3 import rescue
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova import utils


ALIAS = "os-rescue"
CONF = cfg.CONF
CONF.import_opt('enable_instance_password',
                'nova.api.openstack.compute.servers')

authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class RescueController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(RescueController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.response(202)
    @extensions.expected_errors((400, 404, 409))
    @wsgi.action('rescue')
    @validation.schema(rescue.rescue)
    def _rescue(self, req, id, body):
        """Rescue an instance."""
        context = req.environ["nova.context"]
        authorize(context)

        if body['rescue'] and 'admin_password' in body['rescue']:
            password = body['rescue']['admin_password']
        else:
            password = utils.generate_password()

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.rescue(context, instance,
                                    rescue_password=password)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                                  'rescue')
        except exception.InvalidVolume as volume_error:
            raise exc.HTTPConflict(explanation=volume_error.format_message())
        except exception.InstanceNotRescuable as non_rescuable:
            raise exc.HTTPBadRequest(
                explanation=non_rescuable.format_message())

        if CONF.enable_instance_password:
            return {'admin_password': password}
        else:
            return {}

    @extensions.expected_errors((404, 409))
    @wsgi.action('unrescue')
    def _unrescue(self, req, id, body):
        """Unrescue an instance."""
        context = req.environ["nova.context"]
        authorize(context)
        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.unrescue(context, instance)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                                  'unrescue')
        return webob.Response(status_int=202)


class Rescue(extensions.V3APIExtensionBase):
    """Instance rescue mode."""

    name = "Rescue"
    alias = ALIAS
    version = 1

    def get_resources(self):
        return []

    def get_controller_extensions(self):
        controller = RescueController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

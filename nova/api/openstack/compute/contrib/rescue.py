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
from nova.api.openstack import extensions as exts
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova import utils


CONF = cfg.CONF
authorize = exts.extension_authorizer('compute', 'rescue')


class RescueController(wsgi.Controller):
    def __init__(self, ext_mgr, *args, **kwargs):
        super(RescueController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.ext_mgr = ext_mgr

    @wsgi.action('rescue')
    def _rescue(self, req, id, body):
        """Rescue an instance."""
        context = req.environ["nova.context"]
        authorize(context)

        if body['rescue'] and 'adminPass' in body['rescue']:
            password = body['rescue']['adminPass']
        else:
            password = utils.generate_password()

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            rescue_image_ref = None
            if self.ext_mgr.is_loaded("os-extended-rescue-with-image"):
                if body['rescue'] and 'rescue_image_ref' in body['rescue']:
                    rescue_image_ref = body['rescue']['rescue_image_ref']
            self.compute_api.rescue(context, instance,
                rescue_password=password, rescue_image_ref=rescue_image_ref)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                                  'rescue', id)
        except exception.InvalidVolume as volume_error:
            raise exc.HTTPConflict(explanation=volume_error.format_message())
        except exception.InstanceNotRescuable as non_rescuable:
            raise exc.HTTPBadRequest(
                explanation=non_rescuable.format_message())

        return {'adminPass': password}

    @wsgi.action('unrescue')
    def _unrescue(self, req, id, body):
        """Unrescue an instance."""
        context = req.environ["nova.context"]
        authorize(context)
        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            self.compute_api.unrescue(context, instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                                  'unrescue',
                                                                  id)

        return webob.Response(status_int=202)


class Rescue(exts.ExtensionDescriptor):
    """Instance rescue mode."""

    name = "Rescue"
    alias = "os-rescue"
    namespace = "http://docs.openstack.org/compute/ext/rescue/api/v1.1"
    updated = "2011-08-18T00:00:00Z"

    def get_controller_extensions(self):
        controller = RescueController(self.ext_mgr)
        extension = exts.ControllerExtension(self, 'servers', controller)
        return [extension]

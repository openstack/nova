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

from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import rescue
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
import nova.conf
from nova import exception
from nova.policies import rescue as rescue_policies
from nova import utils

CONF = nova.conf.CONF


class RescueController(wsgi.Controller):
    def __init__(self):
        super(RescueController, self).__init__()
        self.compute_api = compute.API()

    # TODO(cyeoh): Should be responding here with 202 Accept
    # because rescue is an async call, but keep to 200
    # for backwards compatibility reasons.
    @wsgi.expected_errors((400, 404, 409, 501))
    @wsgi.action('rescue')
    @validation.schema(rescue.rescue)
    def _rescue(self, req, id, body):
        """Rescue an instance."""
        context = req.environ["nova.context"]

        if body['rescue'] and 'adminPass' in body['rescue']:
            password = body['rescue']['adminPass']
        else:
            password = utils.generate_password()

        instance = common.get_instance(self.compute_api, context, id)
        context.can(rescue_policies.BASE_POLICY_NAME,
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        rescue_image_ref = None
        if body['rescue']:
            rescue_image_ref = body['rescue'].get('rescue_image_ref')
        allow_bfv_rescue = api_version_request.is_supported(req, '2.87')
        try:
            self.compute_api.rescue(context, instance,
                                    rescue_password=password,
                                    rescue_image_ref=rescue_image_ref,
                                    allow_bfv_rescue=allow_bfv_rescue)
        except (
            exception.InstanceIsLocked,
            exception.OperationNotSupportedForVTPM,
            exception.InvalidVolume,
        ) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as e:
            common.raise_http_conflict_for_instance_invalid_state(
                e, 'rescue', id)
        except (
            exception.InstanceNotRescuable,
            exception.UnsupportedRescueImage,
        ) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        if CONF.api.enable_instance_password:
            return {'adminPass': password}
        else:
            return {}

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409, 501))
    @wsgi.action('unrescue')
    def _unrescue(self, req, id, body):
        """Unrescue an instance."""
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, id)
        context.can(rescue_policies.UNRESCUE_POLICY_NAME,
                    target={'project_id': instance.project_id})
        try:
            self.compute_api.unrescue(context, instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                                  'unrescue',
                                                                  id)

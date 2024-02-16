#   Copyright 2013 Rackspace Hosting
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

"""The shelved mode extension."""

from oslo_log import log as logging
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import shelve as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.policies import shelve as shelve_policies

LOG = logging.getLogger(__name__)


class ShelveController(wsgi.Controller):
    def __init__(self):
        super(ShelveController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.response(202)
    @wsgi.expected_errors((404, 403, 409, 400))
    @wsgi.action('shelve')
    @validation.schema(schema.shelve)
    def _shelve(self, req, id, body):
        """Move an instance into shelved mode."""
        context = req.environ["nova.context"]

        instance = common.get_instance(self.compute_api, context, id)
        context.can(shelve_policies.POLICY_ROOT % 'shelve',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        try:
            self.compute_api.shelve(context, instance)
        except (
            exception.InstanceIsLocked,
            exception.UnexpectedTaskStateError,
        ) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                                  'shelve', id)
        except exception.ForbiddenPortsWithAccelerator as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('shelveOffload')
    @validation.schema(schema.shelve_offload)
    def _shelve_offload(self, req, id, body):
        """Force removal of a shelved instance from the compute node."""
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, id)
        context.can(shelve_policies.POLICY_ROOT % 'shelve_offload',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        try:
            self.compute_api.shelve_offload(context, instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                              'shelveOffload',
                                                              id)

        except exception.ForbiddenPortsWithAccelerator as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('unshelve')
    @validation.schema(schema.unshelve, '2.1', '2.76')
    # In microversion 2.77 we support specifying 'availability_zone' to
    # unshelve a server. But before 2.77 there is no request body
    # schema validation (because of body=null).
    @validation.schema(schema.unshelve_v277, '2.77', '2.90')
    # In microversion 2.91 we support specifying 'host' to
    # unshelve an instance to a specific hostself.
    # 'availability_zone' = None is supported as well to unpin the
    # availability zone of an instance bonded to this availability_zone
    @validation.schema(schema.unshelve_v291, '2.91')
    def _unshelve(self, req, id, body):
        """Restore an instance from shelved mode."""
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, id)
        context.can(
            shelve_policies.POLICY_ROOT % 'unshelve',
            target={'project_id': instance.project_id}
        )

        unshelve_args = {}

        unshelve_dict = body.get('unshelve')
        support_az = api_version_request.is_supported(
            req, '2.77')
        support_host = api_version_request.is_supported(
            req, '2.91')
        if unshelve_dict:
            if support_az and 'availability_zone' in unshelve_dict:
                unshelve_args['new_az'] = (
                    unshelve_dict['availability_zone']
                )
            if support_host:
                unshelve_args['host'] = unshelve_dict.get('host')

        try:
            self.compute_api.unshelve(
                context,
                instance,
                **unshelve_args,
            )
        except (
            exception.InstanceIsLocked,
            exception.UnshelveInstanceInvalidState,
            exception.UnshelveHostNotInAZ,
            exception.MismatchVolumeAZException,
        ) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(
                state_error, 'unshelve', id)
        except (
            exception.InvalidRequest,
            exception.ExtendedResourceRequestOldCompute,
            exception.ComputeHostNotFound,
        ) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.OverQuota as e:
            raise exc.HTTPForbidden(explanation=e.format_message())

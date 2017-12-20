# Copyright 2013 IBM Corp.
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

from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import admin_password
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova.i18n import _
from nova.policies import admin_password as ap_policies


class AdminPasswordController(wsgi.Controller):

    def __init__(self, *args, **kwargs):
        super(AdminPasswordController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    # TODO(eliqiao): Here should be 204(No content) instead of 202 by v2.1+
    # microversions because the password has been changed when returning
    # a response.
    @wsgi.action('changePassword')
    @wsgi.response(202)
    @wsgi.expected_errors((404, 409, 501))
    @validation.schema(admin_password.change_password)
    def change_password(self, req, id, body):
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(ap_policies.BASE_POLICY_NAME,
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})

        password = body['changePassword']['adminPass']
        try:
            self.compute_api.set_admin_password(context, instance, password)
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.InstancePasswordSetFailed,
                exception.SetAdminPasswdNotSupported,
                exception.InstanceAgentNotEnabled) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as e:
            raise common.raise_http_conflict_for_instance_invalid_state(
                e, 'changePassword', id)
        except NotImplementedError:
            msg = _("Unable to set password on instance")
            common.raise_feature_not_supported(msg=msg)

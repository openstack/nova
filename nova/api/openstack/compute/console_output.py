# Copyright 2011 OpenStack Foundation
# Copyright 2011 Grid Dynamics
# Copyright 2011 Eldar Nugaev, Kirill Shileev, Ilya Alekseyev
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

import re

import webob

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import console_output
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.policies import console_output as co_policies


class ConsoleOutputController(wsgi.Controller):
    def __init__(self):
        super(ConsoleOutputController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.expected_errors((404, 409, 501))
    @wsgi.action('os-getConsoleOutput')
    @validation.schema(console_output.get_console_output)
    def get_console_output(self, req, id, body):
        """Get text console output."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(co_policies.BASE_POLICY_NAME,
                    target={'project_id': instance.project_id})

        length = body['os-getConsoleOutput'].get('length')
        # TODO(cyeoh): In a future API update accept a length of -1
        # as meaning unlimited length (convert to None)

        try:
            output = self.compute_api.get_console_output(context,
                                                         instance,
                                                         length)
        # NOTE(cyeoh): This covers race conditions where the instance is
        # deleted between common.get_instance and get_console_output
        # being called
        except (exception.InstanceNotFound,
                exception.ConsoleNotAvailable) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            common.raise_feature_not_supported()

        # XML output is not correctly escaped, so remove invalid characters
        # NOTE(cyeoh): We don't support XML output with V2.1, but for
        # backwards compatibility reasons we continue to filter the output
        # We should remove this in the future
        remove_re = re.compile('[\x00-\x08\x0B-\x1F]')
        output = remove_re.sub('', output)

        return {'output': output}

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
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _


authorize = extensions.extension_authorizer('compute', 'console_output')


class ConsoleOutputController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ConsoleOutputController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.action('os-getConsoleOutput')
    def get_console_output(self, req, id, body):
        """Get text console output."""
        context = req.environ['nova.context']
        authorize(context)

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            length = body['os-getConsoleOutput'].get('length')
        except (TypeError, KeyError):
            raise webob.exc.HTTPBadRequest(_('os-getConsoleOutput malformed '
                                             'or missing from request body'))

        if length is not None:
            try:
                # NOTE(maurosr): cast length into a string before cast into an
                # integer to avoid thing like: int(2.5) which is 2 instead of
                # raise ValueError like it would when we try int("2.5"). This
                # can be removed once we have api validation landed.
                int(str(length))
            except ValueError:
                raise webob.exc.HTTPBadRequest(_('Length in request body must '
                                                 'be an integer value'))

        try:
            output = self.compute_api.get_console_output(context,
                                                         instance,
                                                         length)
        except exception.NotFound:
            msg = _('Unable to get console')
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Unable to get console log, functionality not implemented")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        # XML output is not correctly escaped, so remove invalid characters
        remove_re = re.compile('[\x00-\x08\x0B-\x1F]')
        output = remove_re.sub('', output)

        return {'output': output}


class Console_output(extensions.ExtensionDescriptor):
    """Console log output support, with tailing ability."""

    name = "ConsoleOutput"
    alias = "os-console-output"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "os-console-output/api/v2")
    updated = "2011-12-08T00:00:00Z"

    def get_controller_extensions(self):
        controller = ConsoleOutputController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

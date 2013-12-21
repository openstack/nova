# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.openstack.common.gettextutils import _


authorize = extensions.extension_authorizer('compute', 'consoles')


class ConsolesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        self.compute_api = compute.API()
        super(ConsolesController, self).__init__(*args, **kwargs)

    @wsgi.action('os-getVNCConsole')
    def get_vnc_console(self, req, id, body):
        """Get vnc connection information to access a server."""
        context = req.environ['nova.context']
        authorize(context)

        # If type is not supplied or unknown, get_vnc_console below will cope
        console_type = body['os-getVNCConsole'].get('type')

        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            output = self.compute_api.get_vnc_console(context,
                                                      instance,
                                                      console_type)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(
                    explanation=_('Instance not yet ready'))
        except NotImplementedError:
            msg = _("Unable to get vnc console, functionality not implemented")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        return {'console': {'type': console_type, 'url': output['url']}}

    @wsgi.action('os-getSPICEConsole')
    def get_spice_console(self, req, id, body):
        """Get spice connection information to access a server."""
        context = req.environ['nova.context']
        authorize(context)

        # If type is not supplied or unknown, get_spice_console below will cope
        console_type = body['os-getSPICEConsole'].get('type')

        try:
            instance = self.compute_api.get(context, id, want_objects=True)
            output = self.compute_api.get_spice_console(context,
                                                      instance,
                                                      console_type)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())

        return {'console': {'type': console_type, 'url': output['url']}}

    def get_actions(self):
        """Return the actions the extension adds, as required by contract."""
        actions = [extensions.ActionExtension("servers", "os-getVNCConsole",
                                              self.get_vnc_console),
                   extensions.ActionExtension("servers", "os-getSPICEConsole",
                                              self.get_spice_console)]
        return actions


class Consoles(extensions.ExtensionDescriptor):
    """Interactive Console support."""
    name = "Consoles"
    alias = "os-consoles"
    namespace = "http://docs.openstack.org/compute/ext/os-consoles/api/v2"
    updated = "2011-12-23T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ConsolesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

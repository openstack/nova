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

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.openstack.common.gettextutils import _


ALIAS = "os-remote-consoles"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class RemoteConsolesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        self.compute_api = compute.API()
        super(RemoteConsolesController, self).__init__(*args, **kwargs)

    @extensions.expected_errors((400, 404, 409, 501))
    @wsgi.action('get_vnc_console')
    def get_vnc_console(self, req, id, body):
        """Get text console output."""
        context = req.environ['nova.context']
        authorize(context)

        # If type is not supplied or unknown, get_vnc_console below will cope
        console_type = body['get_vnc_console'].get('type')

        try:
            instance = common.get_instance(self.compute_api, context, id,
                                           want_objects=True)
            output = self.compute_api.get_vnc_console(context,
                                                      instance,
                                                      console_type)
        except exception.ConsoleTypeInvalid as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.ConsoleTypeUnavailable as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Unable to get vnc console, functionality not implemented")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        return {'console': {'type': console_type, 'url': output['url']}}

    @extensions.expected_errors((400, 404, 409, 501))
    @wsgi.action('get_spice_console')
    def get_spice_console(self, req, id, body):
        """Get text console output."""
        context = req.environ['nova.context']
        authorize(context)

        # If type is not supplied or unknown, get_spice_console below will cope
        console_type = body['get_spice_console'].get('type')

        try:
            instance = common.get_instance(self.compute_api, context, id,
                                           want_objects=True)
            output = self.compute_api.get_spice_console(context,
                                                        instance,
                                                        console_type)
        except exception.ConsoleTypeInvalid as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.ConsoleTypeUnavailable as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Unable to get spice console, "
                    "functionality not implemented")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        return {'console': {'type': console_type, 'url': output['url']}}

    @extensions.expected_errors((400, 404, 409, 501))
    @wsgi.action('get_rdp_console')
    def get_rdp_console(self, req, id, body):
        """Get text console output."""
        context = req.environ['nova.context']
        authorize(context)

        # If type is not supplied or unknown, get_rdp_console below will cope
        console_type = body['get_rdp_console'].get('type')

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        try:
            # NOTE(mikal): get_rdp_console() can raise InstanceNotFound, so
            # we still need to catch it here.
            output = self.compute_api.get_rdp_console(context,
                                                      instance,
                                                      console_type)
        except exception.ConsoleTypeInvalid as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.ConsoleTypeUnavailable as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Unable to get rdp console, functionality not implemented")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        return {'console': {'type': console_type, 'url': output['url']}}


class RemoteConsoles(extensions.V3APIExtensionBase):
    """Interactive Console support."""
    name = "RemoteConsoles"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = RemoteConsolesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []

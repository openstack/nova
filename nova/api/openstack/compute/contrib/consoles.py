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
from nova.i18n import _


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
        instance = common.get_instance(self.compute_api, context, id)

        try:
            output = self.compute_api.get_vnc_console(context,
                                                      instance,
                                                      console_type)
        except exception.InstanceNotReady:
            raise webob.exc.HTTPConflict(
                    explanation=_('Instance not yet ready'))
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except (exception.ConsoleTypeUnavailable,
                exception.ConsoleTypeInvalid) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
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
        instance = common.get_instance(self.compute_api, context, id)

        try:
            output = self.compute_api.get_spice_console(context,
                                                      instance,
                                                      console_type)
        except (exception.ConsoleTypeUnavailable,
                exception.ConsoleTypeInvalid) as e:
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

    @wsgi.action('os-getRDPConsole')
    def get_rdp_console(self, req, id, body):
        """Get text console output."""
        context = req.environ['nova.context']
        authorize(context)

        # If type is not supplied or unknown, get_rdp_console below will cope
        console_type = body['os-getRDPConsole'].get('type')
        instance = common.get_instance(self.compute_api, context, id)

        try:
            output = self.compute_api.get_rdp_console(context,
                                                      instance,
                                                      console_type)
        except (exception.ConsoleTypeUnavailable,
                exception.ConsoleTypeInvalid) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Unable to get rdp console, functionality not implemented")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        return {'console': {'type': console_type, 'url': output['url']}}

    @wsgi.action('os-getSerialConsole')
    def get_serial_console(self, req, id, body):
        """Get connection to a serial console."""
        context = req.environ['nova.context']
        authorize(context)

        # If type is not supplied or unknown get_serial_console below will cope
        console_type = body['os-getSerialConsole'].get('type')
        instance = common.get_instance(self.compute_api, context, id)
        try:
            output = self.compute_api.get_serial_console(context,
                                                         instance,
                                                         console_type)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except (exception.ConsoleTypeUnavailable,
                exception.ConsoleTypeInvalid,
                exception.ImageSerialPortNumberInvalid,
                exception.ImageSerialPortNumberExceedFlavorValue,
                exception.SocketPortRangeExhaustedException) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Unable to get serial console, "
                    "functionality not implemented")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        return {'console': {'type': console_type, 'url': output['url']}}


class Consoles(extensions.ExtensionDescriptor):
    """Interactive Console support."""
    name = "Consoles"
    alias = "os-consoles"
    namespace = "http://docs.openstack.org/compute/ext/os-consoles/api/v2"
    updated = "2011-12-23T00:00:00Z"

    def get_controller_extensions(self):
        controller = ConsolesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

# Copyright 2011 OpenStack Foundation
# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
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

import abc
import functools

from oslo_log import log as logging
import six
import webob.dec
import webob.exc

from nova import exception
from nova.i18n import _

LOG = logging.getLogger(__name__)


class ControllerExtension(object):
    """Extend core controllers of nova OpenStack API.

    Provide a way to extend existing nova OpenStack API core
    controllers.
    """

    def __init__(self, extension, collection, controller):
        self.extension = extension
        self.collection = collection
        self.controller = controller


class ResourceExtension(object):
    """Add top level resources to the OpenStack API in nova."""

    def __init__(self, collection, controller=None, parent=None,
                 collection_actions=None, member_actions=None,
                 custom_routes_fn=None, inherits=None, member_name=None):
        if not collection_actions:
            collection_actions = {}
        if not member_actions:
            member_actions = {}
        self.collection = collection
        self.controller = controller
        self.parent = parent
        self.collection_actions = collection_actions
        self.member_actions = member_actions
        self.custom_routes_fn = custom_routes_fn
        self.inherits = inherits
        self.member_name = member_name


@six.add_metaclass(abc.ABCMeta)
class V21APIExtensionBase(object):
    """Abstract base class for all v2.1 API extensions.

    All v2.1 API extensions must derive from this class and implement
    the abstract methods get_resources and get_controller_extensions
    even if they just return an empty list. The extensions must also
    define the abstract properties.
    """

    def __init__(self, extension_info):
        self.extension_info = extension_info

    @abc.abstractmethod
    def get_resources(self):
        """Return a list of resources extensions.

        The extensions should return a list of ResourceExtension
        objects. This list may be empty.
        """
        pass

    @abc.abstractmethod
    def get_controller_extensions(self):
        """Return a list of controller extensions.

        The extensions should return a list of ControllerExtension
        objects. This list may be empty.
        """
        pass

    @abc.abstractproperty
    def name(self):
        """Name of the extension."""
        pass

    @abc.abstractproperty
    def alias(self):
        """Alias for the extension."""
        pass

    @abc.abstractproperty
    def version(self):
        """Version of the extension."""
        pass

    def __repr__(self):
        return "<Extension: name=%s, alias=%s, version=%s>" % (
            self.name, self.alias, self.version)

    def is_valid(self):
        """Validate required fields for extensions.

        Raises an attribute error if the attr is not defined
        """
        for attr in ('name', 'alias', 'version'):
            if getattr(self, attr) is None:
                raise AttributeError("%s is None, needs to be defined" % attr)
        return True


def expected_errors(errors):
    """Decorator for v2.1 API methods which specifies expected exceptions.

    Specify which exceptions may occur when an API method is called. If an
    unexpected exception occurs then return a 500 instead and ask the user
    of the API to file a bug report.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as exc:
                if isinstance(exc, webob.exc.WSGIHTTPException):
                    if isinstance(errors, int):
                        t_errors = (errors,)
                    else:
                        t_errors = errors
                    if exc.code in t_errors:
                        raise
                elif isinstance(exc, exception.Forbidden):
                    # Note(cyeoh): Special case to handle
                    # Forbidden exceptions so every
                    # extension method does not need to wrap authorize
                    # calls. ResourceExceptionHandler silently
                    # converts NotAuthorized to HTTPForbidden
                    raise
                elif isinstance(exc, exception.ValidationError):
                    # Note(oomichi): Handle a validation error, which
                    # happens due to invalid API parameters, as an
                    # expected error.
                    raise
                elif isinstance(exc, exception.Unauthorized):
                    # Handle an authorized exception, will be
                    # automatically converted to a HTTP 401, clients
                    # like python-novaclient handle this error to
                    # generate new token and do another attempt.
                    raise

                LOG.exception("Unexpected exception in API method")
                msg = _('Unexpected API Error. Please report this at '
                    'http://bugs.launchpad.net/nova/ and attach the Nova '
                    'API log if possible.\n%s') % type(exc)
                raise webob.exc.HTTPInternalServerError(explanation=msg)

        return wrapped

    return decorator

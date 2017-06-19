# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Microversion handling."""

# NOTE(cdent): This code is taken from enamel:
# https://github.com/jaypipes/enamel and was the original source of
# the code now used in microversion_parse library.

import collections
import inspect

import microversion_parse
import webob

# NOTE(cdent): avoid cyclical import conflict between util and
# microversion
import nova.api.openstack.placement.util
from nova.i18n import _


SERVICE_TYPE = 'placement'
MICROVERSION_ENVIRON = '%s.microversion' % SERVICE_TYPE
VERSIONED_METHODS = collections.defaultdict(list)

# The Canonical Version List
VERSIONS = [
    '1.0',
    '1.1',  # initial support for aggregate.get_aggregates and set_aggregates
    '1.2',  # Adds /resource_classes resource endpoint
    '1.3',  # Adds 'member_of' query parameter to get resource providers
            # that are members of any of the listed aggregates
    '1.4',  # Adds resources query string parameter in GET /resource_providers
    '1.5',  # Adds DELETE /resource_providers/{uuid}/inventories
    '1.6',  # Adds /traits and /resource_providers{uuid}/traits resource
            # endpoints
    '1.7',  # PUT /resource_classes/{name} is bodiless create or update
    '1.8',  # Adds 'project_id' and 'user_id' required request parameters to
            # PUT /allocations
    '1.9',  # Adds GET /usages
    '1.10',  # Adds GET /allocation_candidates resource endpoint
]


def max_version_string():
    return VERSIONS[-1]


def min_version_string():
    return VERSIONS[0]


def parse_version_string(version_string):
    """Turn a version string into a Version

    :param version_string: A string of two numerals, X.Y, or 'latest'
    :returns: a Version
    :raises: TypeError
    """
    if version_string == 'latest':
        version_string = max_version_string()
    try:
        # The combination of int and a limited split with the
        # named tuple means that this incantation will raise
        # ValueError or TypeError when the incoming data is
        # poorly formed but will, however, naturally adapt to
        # extraneous whitespace.
        return Version(*(int(value) for value
                         in version_string.split('.', 1)))
    except (ValueError, TypeError) as exc:
        raise TypeError('invalid version string: %s; %s' % (
            version_string, exc))


def raise_http_status_code_if_not_version(req, status_code, min_version,
                                          max_version=None):
    """Utility to raise a http status code if the wanted microversion does not
       match.

    :param req: The HTTP request for the placement api
    :param status_code: HTTP status code (integer value) to be raised
    :param min_version: Minimum placement microversion level
    :param max_version: Maximum placement microversion level
    :returns: None
    :raises: HTTP status code if the specified microversion does not match
    :raises: KeyError if status_code is not a valid HTTP status code
    """
    if not isinstance(min_version, tuple):
        min_version = parse_version_string(min_version)
    if max_version and not isinstance(max_version, tuple):
        max_version = parse_version_string(max_version)
    want_version = req.environ[MICROVERSION_ENVIRON]
    if not want_version.matches(min_version, max_version):
        raise webob.exc.status_map[status_code]


class MicroversionMiddleware(object):
    """WSGI middleware for getting microversion info."""

    def __init__(self, application):
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req):
        util = nova.api.openstack.placement.util
        try:
            microversion = extract_version(req.headers)
        except ValueError as exc:
            raise webob.exc.HTTPNotAcceptable(
                _('Invalid microversion: %(error)s') % {'error': exc},
                json_formatter=util.json_error_formatter)
        except TypeError as exc:
            raise webob.exc.HTTPBadRequest(
                _('Invalid microversion: %(error)s') % {'error': exc},
                json_formatter=util.json_error_formatter)

        req.environ[MICROVERSION_ENVIRON] = microversion
        microversion_header = '%s %s' % (SERVICE_TYPE, microversion)

        try:
            response = req.get_response(self.application)
        except webob.exc.HTTPError as exc:
            # If there was an error in the application we still need
            # to send the microversion header, so add the header and
            # re-raise the exception.
            exc.headers.add(Version.HEADER, microversion_header)
            raise exc

        response.headers.add(Version.HEADER, microversion_header)
        response.headers.add('vary', Version.HEADER)
        return response


class Version(collections.namedtuple('Version', 'major minor')):
    """A namedtuple containing major and minor values.

    Since it is a tuple is automatically comparable.
    """

    HEADER = 'OpenStack-API-Version'

    MIN_VERSION = None
    MAX_VERSION = None

    def __str__(self):
        return '%s.%s' % (self.major, self.minor)

    @property
    def max_version(self):
        if not self.MAX_VERSION:
            self.MAX_VERSION = parse_version_string(max_version_string())
        return self.MAX_VERSION

    @property
    def min_version(self):
        if not self.MIN_VERSION:
            self.MIN_VERSION = parse_version_string(min_version_string())
        return self.MIN_VERSION

    def matches(self, min_version=None, max_version=None):
        if min_version is None:
            min_version = self.min_version
        if max_version is None:
            max_version = self.max_version
        return min_version <= self <= max_version


def extract_version(headers):
    """Extract the microversion from Version.HEADER

    There may be multiple headers and some which don't match our
    service.
    """
    found_version = microversion_parse.get_version(headers,
                                                   service_type=SERVICE_TYPE)

    version_string = found_version or min_version_string()
    request_version = parse_version_string(version_string)
    # We need a version that is in VERSION and within MIX and MAX.
    # This gives us the option to administratively disable a
    # version if we really need to.
    if (str(request_version) in VERSIONS and request_version.matches()):
        return request_version
    raise ValueError('Unacceptable version header: %s' % version_string)


# From twisted
# https://github.com/twisted/twisted/blob/trunk/twisted/python/deprecate.py
def _fully_qualified_name(obj):
    """Return the fully qualified name of a module, class, method or function.

    Classes and functions need to be module level ones to be correctly
    qualified.
    """
    try:
        name = obj.__qualname__
    except AttributeError:
        name = obj.__name__

    if inspect.isclass(obj) or inspect.isfunction(obj):
        moduleName = obj.__module__
        return "%s.%s" % (moduleName, name)
    elif inspect.ismethod(obj):
        try:
            cls = obj.im_class
        except AttributeError:
            # Python 3 eliminates im_class, substitutes __module__ and
            # __qualname__ to provide similar information.
            return "%s.%s" % (obj.__module__, obj.__qualname__)
        else:
            className = _fully_qualified_name(cls)
            return "%s.%s" % (className, name)
    return name


def _find_method(f, version):
    """Look in VERSIONED_METHODS for method with right name matching version.

    If no match is found raise a 404.
    """
    qualified_name = _fully_qualified_name(f)
    # A KeyError shouldn't be possible here, but let's be robust
    # just in case.
    method_list = VERSIONED_METHODS.get(qualified_name, [])
    for min_version, max_version, func in method_list:
        if min_version <= version <= max_version:
            return func

    raise webob.exc.HTTPNotFound()


def version_handler(min_ver, max_ver=None):
    """Decorator for versioning API methods.

    Add as a decorator to a placement API handler to constrain
    the microversions at which it will run. Add after the
    ``wsgify`` decorator.

    This does not check for version intersections. That's the
    domain of tests.

    :param min_ver: A string of two numerals, X.Y indicating the
                    minimum version allowed for the decorated method.
    :param min_ver: A string of two numerals, X.Y, indicating the
                    maximum version allowed for the decorated method.
    """
    def decorator(f):
        min_version = parse_version_string(min_ver)
        if max_ver:
            max_version = parse_version_string(max_ver)
        else:
            max_version = parse_version_string(max_version_string())
        qualified_name = _fully_qualified_name(f)
        VERSIONED_METHODS[qualified_name].append(
            (min_version, max_version, f))

        def decorated_func(req, *args, **kwargs):
            version = req.environ[MICROVERSION_ENVIRON]
            return _find_method(f, version)(req, *args, **kwargs)

        # Sort highest min version to beginning of list.
        VERSIONED_METHODS[qualified_name].sort(key=lambda x: x[0],
                                               reverse=True)
        return decorated_func
    return decorator

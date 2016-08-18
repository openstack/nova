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

import microversion_parse
import webob

# NOTE(cdent): avoid cyclical import conflict between util and
# microversion
import nova.api.openstack.placement.util


SERVICE_TYPE = 'placement'
MICROVERSION_ENVIRON = '%s.microversion' % SERVICE_TYPE

# The Canonical Version List
VERSIONS = [
    '1.0',
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
                'Invalid microversion: %s' % exc,
                json_formatter=util.json_error_formatter)
        except TypeError as exc:
            raise webob.exc.HTTPBadRequest(
                'Invalid microversion: %s' % exc,
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

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
"""Utility methods for placement API."""

from oslo_middleware import request_id
import webob

# NOTE(cdent): avoid cyclical import conflict between util and
# microversion
import nova.api.openstack.placement.microversion


def json_error_formatter(body, status, title, environ):
    """A json_formatter for webob exceptions.

    Follows API-WG guidelines at
    http://specs.openstack.org/openstack/api-wg/guidelines/errors.html
    """
    # Clear out the html that webob sneaks in.
    body = webob.exc.strip_tags(body)
    error_dict = {
        'status': status,
        'title': title,
        'detail': body
    }
    # If the request id middleware has had a chance to add an id,
    # put it in the error response.
    if request_id.ENV_REQUEST_ID in environ:
        error_dict['request_id'] = environ[request_id.ENV_REQUEST_ID]

    # When there is a no microversion in the environment and a 406,
    # microversion parsing failed so we need to include microversion
    # min and max information in the error response.
    microversion = nova.api.openstack.placement.microversion
    # Get status code out of status message. webob's error formatter
    # only passes entire status string.
    code = status.split(None, 1)[0]
    if code == '406' and microversion.MICROVERSION_ENVIRON not in environ:
        error_dict['max_version'] = microversion.max_version_string()
        error_dict['min_version'] = microversion.max_version_string()

    return {'errors': [error_dict]}


def wsgi_path_item(environ, name):
    """Extract the value of a named field in a URL.

    Return None if the name is not present or there are no path items.
    """
    # NOTE(cdent): For the time being we don't need to urldecode
    # the value as the entire placement API has paths that accept no
    # encoded values.
    try:
        return environ['wsgiorg.routing_args'][1][name]
    except (KeyError, IndexError):
        return None

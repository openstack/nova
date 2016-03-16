#    Copyright (c) 2011 Justin Santa Barbara
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

import urllib

from oslo_log import log as logging
from oslo_serialization import jsonutils
import requests
import six


LOG = logging.getLogger(__name__)


class APIResponse(object):
    """Decoded API Response

    This provides a decoded version of the Requests response which
    include a json decoded body, far more convenient for testing that
    returned structures are correct, or using parts of returned
    structures in tests.


    This class is a simple wrapper around dictionaries for API
    responses in tests. It includes extra attributes so that they can
    be inspected in addition to the attributes.

    All json responses from Nova APIs are dictionary compatible, or
    blank, so other possible base classes are not needed.

    """
    status = 200
    """The HTTP status code as an int"""
    content = ""
    """The Raw HTTP response body as a string"""
    body = {}
    """The decoded json body as a dictionary"""
    headers = {}
    """Response headers as a dictionary"""

    def __init__(self, response):
        """Construct an API response from a Requests response

        :param response: a ``requests`` library response
        """
        super(APIResponse, self).__init__()
        self.status = response.status_code
        self.content = response.content
        if self.content:
            self.body = jsonutils.loads(self.content)
        self.headers = response.headers

    def __str__(self):
        # because __str__ falls back to __repr__ we can still use repr
        # on self but add in the other attributes.
        return "<Response body:%r, status_code:%s>" % (self.body, self.status)


class OpenStackApiException(Exception):
    def __init__(self, message=None, response=None):
        self.response = response
        if not message:
            message = 'Unspecified error'

        if response:
            _status = response.status_code
            _body = response.content

            message = ('%(message)s\nStatus Code: %(_status)s\n'
                       'Body: %(_body)s' %
                       {'message': message, '_status': _status,
                        '_body': _body})

        super(OpenStackApiException, self).__init__(message)


class OpenStackApiAuthenticationException(OpenStackApiException):
    def __init__(self, response=None, message=None):
        if not message:
            message = "Authentication error"
        super(OpenStackApiAuthenticationException, self).__init__(message,
                                                                  response)


class OpenStackApiAuthorizationException(OpenStackApiException):
    def __init__(self, response=None, message=None):
        if not message:
            message = "Authorization error"
        super(OpenStackApiAuthorizationException, self).__init__(message,
                                                                  response)


class OpenStackApiNotFoundException(OpenStackApiException):
    def __init__(self, response=None, message=None):
        if not message:
            message = "Item not found"
        super(OpenStackApiNotFoundException, self).__init__(message, response)


class TestOpenStackClient(object):
    """Simple OpenStack API Client.

    This is a really basic OpenStack API client that is under our control,
    so we can make changes / insert hooks for testing

    """

    def __init__(self, auth_user, auth_key, auth_uri,
                 project_id=None):
        super(TestOpenStackClient, self).__init__()
        self.auth_result = None
        self.auth_user = auth_user
        self.auth_key = auth_key
        self.auth_uri = auth_uri
        if project_id is None:
            self.project_id = "6f70656e737461636b20342065766572"
        else:
            self.project_id = project_id
        self.microversion = None

    def request(self, url, method='GET', body=None, headers=None):
        _headers = {'Content-Type': 'application/json'}
        _headers.update(headers or {})

        response = requests.request(method, url, data=body, headers=_headers)
        return response

    def _authenticate(self):
        if self.auth_result:
            return self.auth_result

        auth_uri = self.auth_uri
        headers = {'X-Auth-User': self.auth_user,
                   'X-Auth-Key': self.auth_key,
                   'X-Auth-Project-Id': self.project_id}
        response = self.request(auth_uri,
                                headers=headers)

        http_status = response.status_code
        LOG.debug("%(auth_uri)s => code %(http_status)s",
                  {'auth_uri': auth_uri, 'http_status': http_status})

        if http_status == 401:
            raise OpenStackApiAuthenticationException(response=response)

        self.auth_result = response.headers
        return self.auth_result

    def api_request(self, relative_uri, check_response_status=None,
                    strip_version=False, **kwargs):
        auth_result = self._authenticate()

        # NOTE(justinsb): httplib 'helpfully' converts headers to lower case
        base_uri = auth_result['x-server-management-url']
        if strip_version:
            # NOTE(vish): cut out version number and tenant_id
            base_uri = '/'.join(base_uri.split('/', 3)[:-1])

        full_uri = '%s/%s' % (base_uri, relative_uri)

        headers = kwargs.setdefault('headers', {})
        headers['X-Auth-Token'] = auth_result['x-auth-token']
        if self.microversion:
            headers['X-OpenStack-Nova-API-Version'] = self.microversion

        response = self.request(full_uri, **kwargs)

        http_status = response.status_code
        LOG.debug("%(relative_uri)s => code %(http_status)s",
                  {'relative_uri': relative_uri, 'http_status': http_status})

        if check_response_status:
            if http_status not in check_response_status:
                if http_status == 404:
                    raise OpenStackApiNotFoundException(response=response)
                elif http_status == 401:
                    raise OpenStackApiAuthorizationException(response=response)
                else:
                    raise OpenStackApiException(
                        message="Unexpected status code",
                        response=response)

        return response

    def _decode_json(self, response):
        resp = APIResponse(status=response.status_code)
        if response.content:
            resp.body = jsonutils.loads(response.content)
        return resp

    def api_get(self, relative_uri, **kwargs):
        kwargs.setdefault('check_response_status', [200])
        return APIResponse(self.api_request(relative_uri, **kwargs))

    def api_post(self, relative_uri, body, **kwargs):
        kwargs['method'] = 'POST'
        if body:
            headers = kwargs.setdefault('headers', {})
            headers['Content-Type'] = 'application/json'
            kwargs['body'] = jsonutils.dumps(body)

        kwargs.setdefault('check_response_status', [200, 202])
        return APIResponse(self.api_request(relative_uri, **kwargs))

    def api_put(self, relative_uri, body, **kwargs):
        kwargs['method'] = 'PUT'
        if body:
            headers = kwargs.setdefault('headers', {})
            headers['Content-Type'] = 'application/json'
            kwargs['body'] = jsonutils.dumps(body)

        kwargs.setdefault('check_response_status', [200, 202, 204])
        return APIResponse(self.api_request(relative_uri, **kwargs))

    def api_delete(self, relative_uri, **kwargs):
        kwargs['method'] = 'DELETE'
        kwargs.setdefault('check_response_status', [200, 202, 204])
        return APIResponse(self.api_request(relative_uri, **kwargs))

    #####################################
    #
    # Convenience methods
    #
    # The following are a set of convenience methods to get well known
    # resources, they can be helpful in setting up resources in
    # tests. All of these convenience methods throw exceptions if they
    # get a non 20x status code, so will appropriately abort tests if
    # they fail.
    #
    # They all return the most relevant part of their response body as
    # decoded data structure.
    #
    #####################################

    def get_server(self, server_id):
        return self.api_get('/servers/%s' % server_id).body['server']

    def get_servers(self, detail=True, search_opts=None):
        rel_url = '/servers/detail' if detail else '/servers'

        if search_opts is not None:
            qparams = {}
            for opt, val in six.iteritems(search_opts):
                qparams[opt] = val
            if qparams:
                query_string = "?%s" % urllib.urlencode(qparams)
                rel_url += query_string
        return self.api_get(rel_url).body['servers']

    def post_server(self, server):
        response = self.api_post('/servers', server).body
        if 'reservation_id' in response:
            return response
        else:
            return response['server']

    def put_server(self, server_id, server):
        return self.api_put('/servers/%s' % server_id, server).body

    def post_server_action(self, server_id, data):
        return self.api_post('/servers/%s/action' % server_id, data).body

    def delete_server(self, server_id):
        return self.api_delete('/servers/%s' % server_id)

    def get_image(self, image_id):
        return self.api_get('/images/%s' % image_id).body['image']

    def get_images(self, detail=True):
        rel_url = '/images/detail' if detail else '/images'
        return self.api_get(rel_url).body['images']

    def post_image(self, image):
        return self.api_post('/images', image).body['image']

    def delete_image(self, image_id):
        return self.api_delete('/images/%s' % image_id)

    def get_flavor(self, flavor_id):
        return self.api_get('/flavors/%s' % flavor_id).body['flavor']

    def get_flavors(self, detail=True):
        rel_url = '/flavors/detail' if detail else '/flavors'
        return self.api_get(rel_url).body['flavors']

    def post_flavor(self, flavor):
        return self.api_post('/flavors', flavor).body['flavor']

    def delete_flavor(self, flavor_id):
        return self.api_delete('/flavors/%s' % flavor_id)

    def post_extra_spec(self, flavor_id, spec):
        return self.api_post('/flavors/%s/os-extra_specs' %
                             flavor_id, spec)

    def get_volume(self, volume_id):
        return self.api_get('/os-volumes/%s' % volume_id).body['volume']

    def get_volumes(self, detail=True):
        rel_url = '/os-volumes/detail' if detail else '/os-volumes'
        return self.api_get(rel_url).body['volumes']

    def post_volume(self, volume):
        return self.api_post('/os-volumes', volume).body['volume']

    def delete_volume(self, volume_id):
        return self.api_delete('/os-volumes/%s' % volume_id)

    def get_server_volume(self, server_id, attachment_id):
        return self.api_get('/servers/%s/os-volume_attachments/%s' %
                            (server_id, attachment_id)
                        ).body['volumeAttachment']

    def get_server_volumes(self, server_id):
        return self.api_get('/servers/%s/os-volume_attachments' %
                            (server_id)).body['volumeAttachments']

    def post_server_volume(self, server_id, volume_attachment):
        return self.api_post('/servers/%s/os-volume_attachments' %
                             (server_id), volume_attachment
                            ).body['volumeAttachment']

    def delete_server_volume(self, server_id, attachment_id):
        return self.api_delete('/servers/%s/os-volume_attachments/%s' %
                            (server_id, attachment_id))

    def post_server_metadata(self, server_id, metadata):
        post_body = {'metadata': {}}
        post_body['metadata'].update(metadata)
        return self.api_post('/servers/%s/metadata' % server_id,
                             post_body).body['metadata']

    def get_server_groups(self, all_projects=None):
        if all_projects:
            return self.api_get(
                '/os-server-groups?all_projects').body['server_groups']
        else:
            return self.api_get('/os-server-groups').body['server_groups']

    def get_server_group(self, group_id):
        return self.api_get('/os-server-groups/%s' %
                            group_id).body['server_group']

    def post_server_groups(self, group):
        response = self.api_post('/os-server-groups', {"server_group": group})
        return response.body['server_group']

    def delete_server_group(self, group_id):
        self.api_delete('/os-server-groups/%s' % group_id)

    def get_instance_actions(self, server_id):
        return self.api_get('/servers/%s/os-instance-actions' %
                            (server_id)).body['instanceActions']

# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import json
import httplib
import urlparse

from nova import log as logging


LOG = logging.getLogger('nova.tests.api')


class OpenstackApiException(Exception):
    def __init__(self, message=None, response=None):
        self.response = response
        if not message:
            message = 'Unspecified error'

        if response:
            _status = response.status
            _body = response.read()

            message = _('%(message)s\nStatus Code: %(_status)s\n'
                        'Body: %(_body)s') % locals()

        super(OpenstackApiException, self).__init__(message)


class OpenstackApiAuthenticationException(OpenstackApiException):
    def __init__(self, response=None, message=None):
        if not message:
            message = _("Authentication error")
        super(OpenstackApiAuthenticationException, self).__init__(message,
                                                                  response)


class OpenstackApiNotFoundException(OpenstackApiException):
    def __init__(self, response=None, message=None):
        if not message:
            message = _("Item not found")
        super(OpenstackApiNotFoundException, self).__init__(message, response)


class TestOpenStackClient(object):
    """ A really basic OpenStack API client that is under our control,
    so we can make changes / insert hooks for testing"""

    def __init__(self, auth_user, auth_key, auth_uri):
        super(TestOpenStackClient, self).__init__()
        self.auth_result = None
        self.auth_user = auth_user
        self.auth_key = auth_key
        self.auth_uri = auth_uri

    def request(self, url, method='GET', body=None, headers=None):
        if headers is None:
            headers = {}

        parsed_url = urlparse.urlparse(url)
        port = parsed_url.port
        hostname = parsed_url.hostname
        scheme = parsed_url.scheme

        if scheme == 'http':
            conn = httplib.HTTPConnection(hostname,
                                          port=port)
        elif scheme == 'https':
            conn = httplib.HTTPSConnection(hostname,
                                           port=port)
        else:
            raise OpenstackApiException("Unknown scheme: %s" % url)

        relative_url = parsed_url.path
        if parsed_url.query:
            relative_url = relative_url + parsed_url.query
        LOG.info(_("Doing %(method)s on %(relative_url)s") % locals())
        if body:
            LOG.info(_("Body: %s") % body)

        conn.request(method, relative_url, body, headers)
        response = conn.getresponse()
        return response

    def _authenticate(self):
        if self.auth_result:
            return self.auth_result

        headers = {'X-Auth-User': self.auth_user,
                   'X-Auth-Key': self.auth_key}
        response = self.request(self.auth_uri,
                                headers=headers)
        if not response.status in [204]:
            raise OpenstackApiAuthenticationException(response=response)

        auth_headers = {}
        for k, v in response.getheaders():
            auth_headers[k] = v

        self.auth_result = auth_headers
        return self.auth_result

    def api_request(self, relative_uri, check_response_status=None, **kwargs):
        auth_result = self._authenticate()

        base_uri = auth_result['X-Server-Management-Url']
        full_uri = base_uri + relative_uri

        headers = kwargs.setdefault('headers', {})
        headers['X-Auth-Token'] = auth_result['X-Auth-Token']

        LOG.debug(_("HTTP request on %s") % (relative_uri))

        response = self.request(full_uri, **kwargs)

        LOG.debug(_("Response => code %s") % (response.status))

        if check_response_status:
            if not response.status in check_response_status:
                if response.status == 404:
                    raise OpenstackApiNotFoundException(response=response)
                else:
                    raise OpenstackApiException(
                                        message=_("Unexpected status code"),
                                        response=response)

        return response

    def _decode_json(self, response):
        body = response.read()
        LOG.debug(_("Decoding JSON: %s") % (body))
        return json.loads(body)

    def api_get(self, relative_uri, **kwargs):
        kwargs.setdefault('check_response_status', [200])
        response = self.api_request(relative_uri, **kwargs)
        return self._decode_json(response)

    def api_post(self, relative_uri, body, **kwargs):
        kwargs['method'] = 'POST'
        if body:
            headers = kwargs.setdefault('headers', {})
            headers['Content-Type'] = 'application/json'
            kwargs['body'] = json.dumps(body)

        kwargs.setdefault('check_response_status', [200])
        response = self.api_request(relative_uri, **kwargs)
        return self._decode_json(response)

    def api_delete(self, relative_uri, **kwargs):
        kwargs['method'] = 'DELETE'
        kwargs.setdefault('check_response_status', [200, 202])
        return self.api_request(relative_uri, **kwargs)

    def get_keys_detail(self):
        return self.api_get('/keys/detail')['keys']

    def post_key(self, key):
        return self.api_post('/keys', key)['key']

    def delete_key(self, key_id):
        return self.api_delete('/keys/%s' % key_id)

    def get_volume(self, volume_id):
        return self.api_get('/volumes/%s' % volume_id)['volume']

    def get_volumes_detail(self):
        return self.api_get('/volumes/detail')['volumes']

    def post_volume(self, volume):
        return self.api_post('/volumes', volume)['volume']

    def delete_volume(self, volume_id):
        return self.api_delete('/volumes/%s' % volume_id)

    def get_server(self, server_id):
        return self.api_get('/servers/%s' % server_id)['server']

    def get_servers(self, detail=True):
        rel_url = '/servers/detail' if detail else '/servers'
        return self.api_get(rel_url)['servers']

    def post_server(self, server):
        return self.api_post('/servers', server)['server']

    def delete_server(self, server_id):
        return self.api_delete('/servers/%s' % server_id)

    def get_image(self, image_id):
        return self.api_get('/images/%s' % image_id)['image']

    def get_images_detail(self):
        return self.api_get('/images/detail')['images']

    def post_image(self, image):
        return self.api_post('/images', image)['image']

    def delete_image(self, image_id):
        return self.api_delete('/images/%s' % image_id)

    def get_flavor(self, flavor_id):
        return self.api_get('/flavors/%s' % flavor_id)['flavor']

    def get_flavors_detail(self):
        return self.api_get('/flavors/detail')['flavors']

    def post_flavor(self, flavor):
        return self.api_post('/flavors', flavor)['flavor']

    def delete_flavor(self, flavor_id):
        return self.api_delete('/flavors/%s' % flavor_id)

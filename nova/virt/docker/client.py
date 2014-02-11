# Copyright (c) 2013 dotCloud, Inc.
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

import functools
import socket

from eventlet.green import httplib
import six

from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def filter_data(f):
    """Decorator that post-processes data returned by Docker to avoid any
       surprises with different versions of Docker
    """
    @functools.wraps(f)
    def wrapper(*args, **kwds):
        out = f(*args, **kwds)

        def _filter(obj):
            if isinstance(obj, list):
                new_list = []
                for o in obj:
                    new_list.append(_filter(o))
                obj = new_list
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(k, six.string_types):
                        obj[k.lower()] = _filter(v)
            return obj
        return _filter(out)
    return wrapper


class Response(object):
    def __init__(self, http_response, url=None):
        self.url = url
        self._response = http_response
        self.code = int(http_response.status)
        self.data = http_response.read()
        self._json = None

    def read(self, size=None):
        return self._response.read(size)

    def to_json(self, default=None):
        if not self._json:
            self._json = self._decode_json(self.data, default)
        return self._json

    def _validate_content_type(self):
        # Docker does not return always the correct Content-Type.
        # Lets try to parse the response anyway since json is requested.
        if self._response.getheader('Content-Type') != 'application/json':
            LOG.debug(_("Content-Type of response is not application/json"
                       " (Docker bug?). Requested URL %s") % self.url)

    @filter_data
    def _decode_json(self, data, default=None):
        if not data:
            return default
        self._validate_content_type()
        # Do not catch ValueError or SyntaxError since that
        # just hides the root cause of errors.
        return jsonutils.loads(data)


class UnixHTTPConnection(httplib.HTTPConnection):
    def __init__(self):
        httplib.HTTPConnection.__init__(self, 'localhost')
        self.unix_socket = '/var/run/docker.sock'

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.unix_socket)
        self.sock = sock


class DockerHTTPClient(object):
    def __init__(self, connection=None):
        self._connection = connection

    @property
    def connection(self):
        if self._connection:
            return self._connection
        else:
            return UnixHTTPConnection()

    def make_request(self, *args, **kwargs):
        headers = {}
        if 'headers' in kwargs and kwargs['headers']:
            headers = kwargs['headers']
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'
            kwargs['headers'] = headers
        conn = self.connection
        conn.request(*args, **kwargs)
        return Response(conn.getresponse(), url=args[1])

    def list_containers(self, _all=True):
        resp = self.make_request(
            'GET',
            '/v1.7/containers/ps?all={0}'.format(int(_all)))
        return resp.to_json(default=[])

    def create_container(self, args, name):
        data = {
            'Hostname': '',
            'User': '',
            'Memory': 0,
            'MemorySwap': 0,
            'AttachStdin': False,
            'AttachStdout': False,
            'AttachStderr': False,
            'PortSpecs': [],
            'Tty': True,
            'OpenStdin': True,
            'StdinOnce': False,
            'Env': None,
            'Cmd': [],
            'Dns': None,
            'Image': None,
            'Volumes': {},
            'VolumesFrom': '',
        }
        data.update(args)
        resp = self.make_request(
            'POST',
            '/v1.7/containers/create?name={0}'.format(name),
            body=jsonutils.dumps(data))
        if resp.code != 201:
            return
        obj = resp.to_json()
        for k, v in obj.iteritems():
            if k.lower() == 'id':
                return v

    def start_container(self, container_id):
        resp = self.make_request(
            'POST',
            '/v1.7/containers/{0}/start'.format(container_id),
            body='{}')
        return (resp.code == 200)

    def inspect_image(self, image_name):
        resp = self.make_request(
            'GET',
            '/v1.7/images/{0}/json'.format(image_name))
        if resp.code != 200:
            return
        return resp.to_json()

    def inspect_container(self, container_id):
        resp = self.make_request(
            'GET',
            '/v1.7/containers/{0}/json'.format(container_id))
        if resp.code != 200:
            return
        return resp.to_json()

    def stop_container(self, container_id):
        timeout = 5
        resp = self.make_request(
            'POST',
            '/v1.7/containers/{0}/stop?t={1}'.format(container_id, timeout))
        return (resp.code == 204)

    def kill_container(self, container_id):
        resp = self.make_request(
            'POST',
            '/v1.7/containers/{0}/kill'.format(container_id))
        return (resp.code == 204)

    def destroy_container(self, container_id):
        resp = self.make_request(
            'DELETE',
            '/v1.7/containers/{0}'.format(container_id))
        return (resp.code == 204)

    def pull_repository(self, name):
        parts = name.rsplit(':', 1)
        url = '/v1.7/images/create?fromImage={0}'.format(parts[0])
        if len(parts) > 1:
            url += '&tag={0}'.format(parts[1])
        resp = self.make_request('POST', url)
        while True:
            buf = resp.read(1024)
            if not buf:
                # Image pull completed
                break
        return (resp.code == 200)

    def push_repository(self, name, headers=None):
        url = '/v1.7/images/{0}/push'.format(name)
        # NOTE(samalba): docker requires the credentials fields even if
        # they're not needed here.
        body = ('{"username":"foo","password":"bar",'
                '"auth":"","email":"foo@bar.bar"}')
        resp = self.make_request('POST', url, headers=headers, body=body)
        while True:
            buf = resp.read(1024)
            if not buf:
                # Image push completed
                break
        return (resp.code == 200)

    def commit_container(self, container_id, name):
        parts = name.rsplit(':', 1)
        url = '/v1.7/commit?container={0}&repo={1}'.format(container_id,
                                                           parts[0])
        if len(parts) > 1:
            url += '&tag={0}'.format(parts[1])
        resp = self.make_request('POST', url)
        return (resp.code == 201)

    def get_container_logs(self, container_id):
        resp = self.make_request(
            'POST',
            ('/v1.7/containers/{0}/attach'
             '?logs=1&stream=0&stdout=1&stderr=1').format(container_id))
        if resp.code != 200:
            return
        return resp.data

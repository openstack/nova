# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

import mox

from nova.openstack.common import jsonutils
from nova import test
import nova.virt.docker.client


class FakeResponse(object):
    def __init__(self, status, data='', headers=None):
        self.status = status
        self._data = data
        self._headers = headers or {}

    def read(self, _size=None):
        return self._data

    def getheader(self, key):
        return self._headers.get(key)


class DockerHTTPClientTestCase(test.TestCase):

    def test_list_containers(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('GET', '/v1.4/containers/ps?all=1&limit=50',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(200, data='[]',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        containers = client.list_containers()
        self.assertEqual([], containers)

        self.mox.VerifyAll()

    def test_create_container(self):
        mock_conn = self.mox.CreateMockAnything()

        expected_body = jsonutils.dumps({
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
        })
        mock_conn.request('POST', '/v1.4/containers/create',
                          body=expected_body,
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(201, data='{"id": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        container_id = client.create_container({})
        self.assertEqual('XXX', container_id)

        self.mox.VerifyAll()

    def test_create_container_with_args(self):
        mock_conn = self.mox.CreateMockAnything()

        expected_body = jsonutils.dumps({
            'Hostname': 'marco',
            'User': '',
            'Memory': 512,
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
            'Image': 'example',
            'Volumes': {},
            'VolumesFrom': '',
        })
        mock_conn.request('POST', '/v1.4/containers/create',
                          body=expected_body,
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(201, data='{"id": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        args = {
            'Hostname': 'marco',
            'Memory': 512,
            'Image': 'example',
        }
        container_id = client.create_container(args)
        self.assertEqual('XXX', container_id)

        self.mox.VerifyAll()

    def test_create_container_no_id_in_response(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/containers/create',
                          body=mox.IgnoreArg(),
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(201, data='{"ping": "pong"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        container_id = client.create_container({})
        self.assertEqual(None, container_id)

        self.mox.VerifyAll()

    def test_create_container_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/containers/create',
                          body=mox.IgnoreArg(),
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        container_id = client.create_container({})
        self.assertEqual(None, container_id)

        self.mox.VerifyAll()

    def test_start_container(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/containers/XXX/start',
                          body='{}',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(200,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.start_container('XXX'))

        self.mox.VerifyAll()

    def test_start_container_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/containers/XXX/start',
                          body='{}',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.start_container('XXX'))

        self.mox.VerifyAll()

    def test_inspect_image(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('GET', '/v1.4/images/XXX/json',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(200, data='{"name": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        image = client.inspect_image('XXX')
        self.assertEqual({'name': 'XXX'}, image)

        self.mox.VerifyAll()

    def test_inspect_image_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('GET', '/v1.4/images/XXX/json',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(404)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        image = client.inspect_image('XXX')
        self.assertEqual(None, image)

        self.mox.VerifyAll()

    def test_inspect_container(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('GET', '/v1.4/containers/XXX/json',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(200, data='{"id": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        container = client.inspect_container('XXX')
        self.assertEqual({'id': 'XXX'}, container)

        self.mox.VerifyAll()

    def test_inspect_container_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('GET', '/v1.4/containers/XXX/json',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(404)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        container = client.inspect_container('XXX')
        self.assertEqual(None, container)

        self.mox.VerifyAll()

    def test_stop_container(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/containers/XXX/stop?t=5',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(204,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.stop_container('XXX'))

        self.mox.VerifyAll()

    def test_stop_container_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/containers/XXX/stop?t=5',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.stop_container('XXX'))

        self.mox.VerifyAll()

    def test_destroy_container(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('DELETE', '/v1.4/containers/XXX',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(204,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.destroy_container('XXX'))

        self.mox.VerifyAll()

    def test_destroy_container_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('DELETE', '/v1.4/containers/XXX',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.destroy_container('XXX'))

        self.mox.VerifyAll()

    def test_pull_repository(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/images/create?fromImage=ping',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(200,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.pull_repository('ping'))

        self.mox.VerifyAll()

    def test_pull_repository_tag(self):
        mock_conn = self.mox.CreateMockAnything()

        url = '/v1.4/images/create?fromImage=ping&tag=pong'
        mock_conn.request('POST', url,
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(200,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.pull_repository('ping:pong'))

        self.mox.VerifyAll()

    def test_pull_repository_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/images/create?fromImage=ping',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(400,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.pull_repository('ping'))

        self.mox.VerifyAll()

    def test_push_repository(self):
        mock_conn = self.mox.CreateMockAnything()

        body = ('{"username":"foo","password":"bar",'
                '"auth":"","email":"foo@bar.bar"}')
        mock_conn.request('POST', '/v1.4/images/ping/push',
                          headers={'Content-Type': 'application/json'},
                          body=body)
        response = FakeResponse(200,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.push_repository('ping'))

        self.mox.VerifyAll()

    def test_push_repository_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        body = ('{"username":"foo","password":"bar",'
                '"auth":"","email":"foo@bar.bar"}')
        mock_conn.request('POST', '/v1.4/images/ping/push',
                          headers={'Content-Type': 'application/json'},
                          body=body)
        response = FakeResponse(400,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.push_repository('ping'))

        self.mox.VerifyAll()

    def test_commit_container(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/commit?container=XXX&repo=ping',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(201,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.commit_container('XXX', 'ping'))

        self.mox.VerifyAll()

    def test_commit_container_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        mock_conn.request('POST', '/v1.4/commit?container=XXX&repo=ping',
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(400,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.commit_container('XXX', 'ping'))

        self.mox.VerifyAll()

    def test_get_container_logs(self):
        mock_conn = self.mox.CreateMockAnything()

        url = '/v1.4/containers/XXX/attach?logs=1&stream=0&stdout=1&stderr=1'
        mock_conn.request('POST', url,
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(200, data='ping pong',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        logs = client.get_container_logs('XXX')
        self.assertEqual('ping pong', logs)

        self.mox.VerifyAll()

    def test_get_container_logs_bad_return_code(self):
        mock_conn = self.mox.CreateMockAnything()

        url = '/v1.4/containers/XXX/attach?logs=1&stream=0&stdout=1&stderr=1'
        mock_conn.request('POST', url,
                          headers={'Content-Type': 'application/json'})
        response = FakeResponse(404)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = nova.virt.docker.client.DockerHTTPClient(mock_conn)
        logs = client.get_container_logs('XXX')
        self.assertEqual(None, logs)

        self.mox.VerifyAll()

# Copyright 2011 OpenStack Foundation
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

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils

from nova.api.openstack import wsgi as os_wsgi
from nova import compute
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes


NAME_FMT = cfg.CONF.instance_name_template
UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'
UUID4 = '00000000-0000-0000-0000-000000000004'
UUID5 = '00000000-0000-0000-0000-000000000005'


def fake_services(host):
    service_list = [objects.Service(id=0, host=host, forced_down=True,
                                   binary='nova-compute')]
    return objects.ServiceList(objects=service_list)


def fake_compute_get(*args, **kwargs):
    return fakes.stub_instance_obj(
        None, 1, uuid=UUID3, host="host-fake",
        node="node-fake",
        reservation_id="r-1", launch_index=0,
        kernel_id=UUID4, ramdisk_id=UUID5,
        display_name="hostname-1",
        root_device_name="/dev/vda",
        user_data="userdata",
        services=fake_services("host-fake"))


def fake_compute_get_all(*args, **kwargs):
    inst_list = [
        fakes.stub_instance_obj(
            None, 1, uuid=UUID1, host="host-1", node="node-1",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID4, ramdisk_id=UUID5,
            display_name="hostname-1",
            root_device_name="/dev/vda",
            user_data="userdata",
            services=fake_services("host-1")),
        fakes.stub_instance_obj(
            None, 2, uuid=UUID2, host="host-2", node="node-2",
            reservation_id="r-2", launch_index=1,
            kernel_id=UUID4, ramdisk_id=UUID5,
            display_name="hostname-2",
            root_device_name="/dev/vda",
            user_data="userdata",
            services=fake_services("host-2")),
    ]
    return objects.InstanceList(objects=inst_list)


class ExtendedServerAttributesTestV21(test.TestCase):
    content_type = 'application/json'
    prefix = 'OS-EXT-SRV-ATTR:'
    fake_url = '/v2/fake'
    wsgi_api_version = os_wsgi.DEFAULT_API_VERSION

    def setUp(self):
        super(ExtendedServerAttributesTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(self)
        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        self.stub_out('nova.compute.api.API.get_all', fake_compute_get_all)
        self.stub_out('nova.db.api.instance_get_by_uuid', fake_compute_get)

    def _make_request(self, url):
        req = fakes.HTTPRequest.blank(url)
        req.headers['Accept'] = self.content_type
        req.headers = {os_wsgi.API_VERSION_REQUEST_HEADER:
                       'compute %s' % self.wsgi_api_version}
        res = req.get_response(
            fakes.wsgi_app_v21())
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def assertServerAttributes(self, server, host, node, instance_name):
        self.assertEqual(server.get('%shost' % self.prefix), host)
        self.assertEqual(server.get('%sinstance_name' % self.prefix),
                         instance_name)
        self.assertEqual(server.get('%shypervisor_hostname' % self.prefix),
                         node)

    def test_show(self):
        url = self.fake_url + '/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertServerAttributes(self._get_server(res.body),
                                host='host-fake',
                                node='node-fake',
                                instance_name=NAME_FMT % 1)

    def test_detail(self):
        url = self.fake_url + '/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            self.assertServerAttributes(server,
                                    host='host-%s' % (i + 1),
                                    node='node-%s' % (i + 1),
                                    instance_name=NAME_FMT % (i + 1))

    @mock.patch.object(compute.api.API, 'get_all')
    def test_detail_empty_instance_list_invalid_status(self,
                                                       mock_get_all_method):
        mock_get_all_method.return_value = objects.InstanceList(objects=[])

        url = "%s%s" % (self.fake_url, '/servers/detail?status=invalid_status')
        res = self._make_request(url)
        # check status code 200 with empty instance list
        self.assertEqual(200, res.status_int)
        self.assertEqual(0, len(self._get_servers(res.body)))

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        url = self.fake_url + '/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)


class ExtendedServerAttributesTestV23(ExtendedServerAttributesTestV21):
    wsgi_api_version = '2.3'

    def assertServerAttributes(self, server, host, node, instance_name,
                               reservation_id, launch_index, kernel_id,
                               ramdisk_id, hostname, root_device_name,
                               user_data):
        super(ExtendedServerAttributesTestV23, self).assertServerAttributes(
            server, host, node, instance_name)
        self.assertEqual(server.get('%sreservation_id' % self.prefix),
                         reservation_id)
        self.assertEqual(server.get('%slaunch_index' % self.prefix),
                         launch_index)
        self.assertEqual(server.get('%skernel_id' % self.prefix),
                         kernel_id)
        self.assertEqual(server.get('%sramdisk_id' % self.prefix),
                         ramdisk_id)
        self.assertEqual(server.get('%shostname' % self.prefix),
                         hostname)
        self.assertEqual(server.get('%sroot_device_name' % self.prefix),
                         root_device_name)
        self.assertEqual(server.get('%suser_data' % self.prefix),
                         user_data)

    def test_show(self):
        url = self.fake_url + '/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertServerAttributes(self._get_server(res.body),
                                host='host-fake',
                                node='node-fake',
                                instance_name=NAME_FMT % 1,
                                reservation_id="r-1",
                                launch_index=0,
                                kernel_id=UUID4,
                                ramdisk_id=UUID5,
                                hostname="hostname-1",
                                root_device_name="/dev/vda",
                                user_data="userdata")

    def test_detail(self):
        url = self.fake_url + '/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            self.assertServerAttributes(server,
                                    host='host-%s' % (i + 1),
                                    node='node-%s' % (i + 1),
                                    instance_name=NAME_FMT % (i + 1),
                                    reservation_id="r-%s" % (i + 1),
                                    launch_index=i,
                                    kernel_id=UUID4,
                                    ramdisk_id=UUID5,
                                    hostname="hostname-%s" % (i + 1),
                                    root_device_name="/dev/vda",
                                    user_data="userdata")


class ExtendedServerAttributesTestV216(ExtendedServerAttributesTestV21):
    wsgi_api_version = '2.16'

    def assertServerAttributes(self, server, host, node, instance_name,
                               host_status):
        super(ExtendedServerAttributesTestV216, self).assertServerAttributes(
            server, host, node, instance_name)
        self.assertEqual(server.get('host_status'), host_status)

    def test_show(self):
        url = self.fake_url + '/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertServerAttributes(self._get_server(res.body),
                                host='host-fake',
                                node='node-fake',
                                instance_name=NAME_FMT % 1,
                                host_status="DOWN")

    def test_detail(self):
        url = self.fake_url + '/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            self.assertServerAttributes(server,
                                    host='host-%s' % (i + 1),
                                    node='node-%s' % (i + 1),
                                    instance_name=NAME_FMT % (i + 1),
                                    host_status="DOWN")

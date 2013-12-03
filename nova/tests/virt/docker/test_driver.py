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

import contextlib
import socket

import mock

from nova import context
from nova import exception
from nova import test
from nova.tests import utils
import nova.tests.virt.docker.mock_client
from nova.tests.virt.test_virt_drivers import _VirtDriverTestCase
from nova import unit
from nova.virt.docker import hostinfo


class DockerDriverTestCase(_VirtDriverTestCase, test.TestCase):

    driver_module = 'nova.virt.docker.DockerDriver'

    def setUp(self):
        super(DockerDriverTestCase, self).setUp()

        self.stubs.Set(nova.virt.docker.driver.DockerDriver,
                       'docker',
                       nova.tests.virt.docker.mock_client.MockClient())

        def fake_setup_network(self, instance, network_info):
            return

        self.stubs.Set(nova.virt.docker.driver.DockerDriver,
                       '_setup_network',
                       fake_setup_network)

        def fake_get_registry_port(self):
            return 5042

        self.stubs.Set(nova.virt.docker.driver.DockerDriver,
                       '_get_registry_port',
                       fake_get_registry_port)

        self.context = context.RequestContext('fake_user', 'fake_project')

    #NOTE(bcwaldon): This exists only because _get_running_instance on the
    # base class will not let us set a custom disk/container_format.
    def _get_running_instance(self):
        instance_ref = utils.get_test_instance()
        network_info = utils.get_test_network_info()
        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = \
            '1.1.1.1'
        image_info = utils.get_test_image_info(None, instance_ref)
        image_info['disk_format'] = 'raw'
        image_info['container_format'] = 'docker'
        self.connection.spawn(self.ctxt, instance_ref, image_info,
                              [], 'herp', network_info=network_info)
        return instance_ref, network_info

    def test_get_host_stats(self):
        self.mox.StubOutWithMock(socket, 'gethostname')
        socket.gethostname().AndReturn('foo')
        socket.gethostname().AndReturn('bar')
        self.mox.ReplayAll()
        self.assertEqual('foo',
                         self.connection.get_host_stats()['host_hostname'])
        self.assertEqual('foo',
                         self.connection.get_host_stats()['host_hostname'])

    def test_get_available_resource(self):
        memory = {
            'total': 4 * unit.Mi,
            'free': 3 * unit.Mi,
            'used': 1 * unit.Mi
        }
        disk = {
            'total': 50 * unit.Gi,
            'available': 25 * unit.Gi,
            'used': 25 * unit.Gi
        }
        # create the mocks
        with contextlib.nested(
            mock.patch.object(hostinfo, 'get_memory_usage',
                              return_value=memory),
            mock.patch.object(hostinfo, 'get_disk_usage',
                              return_value=disk)
        ) as (
            get_memory_usage,
            get_disk_usage
        ):
            # run the code
            stats = self.connection.get_available_resource(nodename='test')
            # make our assertions
            get_memory_usage.assert_called_once_with()
            get_disk_usage.assert_called_once_with()
            expected_stats = {
                'vcpus': 1,
                'vcpus_used': 0,
                'memory_mb': 4,
                'memory_mb_used': 1,
                'local_gb': 50L,
                'local_gb_used': 25L,
                'disk_available_least': 25L,
                'hypervisor_type': 'docker',
                'hypervisor_version': 1000,
                'hypervisor_hostname': 'test',
                'cpu_info': '?',
                'supported_instances': ('[["i686", "docker", "lxc"],'
                                        ' ["x86_64", "docker", "lxc"]]')
            }
            self.assertEqual(expected_stats, stats)

    def test_plug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self.assertRaises(NotImplementedError,
                          self.connection.plug_vifs,
                          instance=utils.get_test_instance(),
                          network_info=None)

    def test_unplug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self.assertRaises(NotImplementedError,
                          self.connection.unplug_vifs,
                          instance=utils.get_test_instance(),
                          network_info=None)

    def test_create_container(self, image_info=None):
        instance_href = utils.get_test_instance()
        if image_info is None:
            image_info = utils.get_test_image_info(None, instance_href)
            image_info['disk_format'] = 'raw'
            image_info['container_format'] = 'docker'
        self.connection.spawn(self.context, instance_href, image_info,
                              'fake_files', 'fake_password')

    def test_create_container_wrong_image(self):
        instance_href = utils.get_test_instance()
        image_info = utils.get_test_image_info(None, instance_href)
        image_info['disk_format'] = 'raw'
        image_info['container_format'] = 'invalid_format'
        self.assertRaises(exception.InstanceDeployFailure,
                          self.test_create_container,
                          image_info)

    def test_destroy_container(self):
        def fake_find_container_by_name(container_name):
            return {'id': 'fake_id'}

        self.stubs.Set(self.connection, 'find_container_by_name',
            fake_find_container_by_name)
        instance_href = utils.get_test_instance()
        self.connection.destroy(self.context, instance_href,
                'fake_networkinfo')

    def test_get_memory_limit_from_sys_meta_in_object(self):
        instance = utils.get_test_instance(obj=True)
        limit = self.connection._get_memory_limit_bytes(instance)
        self.assertEqual(2048 * unit.Mi, limit)

    def test_get_memory_limit_from_sys_meta_in_db_instance(self):
        instance = utils.get_test_instance(obj=False)
        limit = self.connection._get_memory_limit_bytes(instance)
        self.assertEqual(2048 * unit.Mi, limit)

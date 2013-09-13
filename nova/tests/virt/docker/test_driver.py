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

import socket

from nova import test
from nova.tests import utils
import nova.tests.virt.docker.mock_client
from nova.tests.virt.test_virt_drivers import _VirtDriverTestCase


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

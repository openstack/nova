# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""
Base class of Unit Tests for all network models
"""
import IPy
import os

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import utils
from nova import ipv6
from nova.auth import manager

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


class NetworkTestCase(test.TestCase):
    """Test cases for network code"""
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        # NOTE(vish): if you change these flags, make sure to change the
        #             flags in the corresponding section in nova-dhcpbridge
        self.flags(connection_type='fake',
                   fake_call=True,
                   fake_network=True)
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('netuser', 'netuser', 'netuser')
        self.projects = []
        self.network = utils.import_object(FLAGS.network_manager)
        self.context = context.RequestContext(project=None, user=self.user)
        for i in range(FLAGS.num_networks):
            name = 'project%s' % i
            project = self.manager.create_project(name, 'netuser', name)
            self.projects.append(project)
            # create the necessary network data for the project
            user_context = context.RequestContext(project=self.projects[i],
                                                     user=self.user)
            host = self.network.get_network_host(user_context.elevated())
        instance_ref = self._create_instance(0)
        self.instance_id = instance_ref['id']
        instance_ref = self._create_instance(1)
        self.instance2_id = instance_ref['id']

    def tearDown(self):
        # TODO(termie): this should really be instantiating clean datastores
        #               in between runs, one failure kills all the tests
        db.instance_destroy(context.get_admin_context(), self.instance_id)
        db.instance_destroy(context.get_admin_context(), self.instance2_id)
        for project in self.projects:
            self.manager.delete_project(project)
        self.manager.delete_user(self.user)
        super(NetworkTestCase, self).tearDown()

    def _create_instance(self, project_num, mac=None):
        if not mac:
            mac = utils.generate_mac()
        project = self.projects[project_num]
        self.context._project = project
        self.context.project_id = project.id
        return db.instance_create(self.context,
                                  {'project_id': project.id,
                                   'mac_address': mac})

    def _create_address(self, project_num, instance_id=None):
        """Create an address in given project num"""
        if instance_id is None:
            instance_id = self.instance_id
        self.context._project = self.projects[project_num]
        self.context.project_id = self.projects[project_num].id
        return self.network.allocate_fixed_ip(self.context, instance_id)

    def _deallocate_address(self, project_num, address):
        self.context._project = self.projects[project_num]
        self.context.project_id = self.projects[project_num].id
        self.network.deallocate_fixed_ip(self.context, address)

    def _is_allocated_in_project(self, address, project_id):
        """Returns true if address is in specified project"""
        project_net = db.network_get_by_bridge(context.get_admin_context(),
                                           FLAGS.flat_network_bridge)
        network = db.fixed_ip_get_network(context.get_admin_context(),
                                          address)
        instance = db.fixed_ip_get_instance(context.get_admin_context(),
                                            address)
        # instance exists until release
        return instance is not None and network['id'] == project_net['id']

    def test_private_ipv6(self):
        """Make sure ipv6 is OK"""
        if FLAGS.use_ipv6:
            instance_ref = self._create_instance(0)
            address = self._create_address(0, instance_ref['id'])
            network_ref = db.project_get_network(
                                                 context.get_admin_context(),
                                                 self.context.project_id)
            address_v6 = db.instance_get_fixed_address_v6(
                                                 context.get_admin_context(),
                                                 instance_ref['id'])
            self.assertEqual(instance_ref['mac_address'],
                             ipv6.to_mac(address_v6))
            instance_ref2 = db.fixed_ip_get_instance_v6(
                                                 context.get_admin_context(),
                                                 address_v6)
            self.assertEqual(instance_ref['id'], instance_ref2['id'])
            self.assertEqual(address_v6,
                             ipv6.to_global(network_ref['cidr_v6'],
                                            instance_ref['mac_address']))
            self._deallocate_address(0, address)
            db.instance_destroy(context.get_admin_context(),
                                instance_ref['id'])

    def test_available_ips(self):
        """Make sure the number of available ips for the network is correct

        The number of available IP addresses depends on the test
        environment's setup.

        Network size is set in test fixture's setUp method.

        There are ips reserved at the bottom and top of the range.
        services (network, gateway, CloudPipe, broadcast)
        """
        network = db.project_get_network(context.get_admin_context(),
                                         self.projects[0].id)
        net_size = flags.FLAGS.network_size
        admin_context = context.get_admin_context()
        total_ips = (db.network_count_available_ips(admin_context,
                                                    network['id']) +
                     db.network_count_reserved_ips(admin_context,
                                                   network['id']) +
                     db.network_count_allocated_ips(admin_context,
                                                    network['id']))
        self.assertEqual(total_ips, net_size)

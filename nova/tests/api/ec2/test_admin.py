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

"""Tests for api.ec2.admin"""

import datetime

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.api.ec2 import admin
from nova.api.ec2 import ec2utils
from nova.cloudpipe import pipelib
from nova.compute import vm_states


class AdminTestCase(test.TestCase):
    def setUp(self):
        super(AdminTestCase, self).setUp()
        self.stubs.Set(utils, 'vpn_ping',
                       lambda address, port: address == '127.0.0.1')

    def test_user_dict(self):
        user = type('User', (object,),
                    {'id': 'bob', 'access': 'foo', 'secret': 'bar'})

        expected_user_dict = {'username': 'bob',
                              'accesskey': 'foo',
                              'secretkey': 'bar',
                              'file': 'filename'}

        self.assertEqual(expected_user_dict, admin.user_dict(user, 'filename'))

    def test_user_dict_no_file(self):
        user = type('User', (object,),
                    {'id': 'bob', 'access': 'foo', 'secret': 'bar'})

        expected_user_dict = {'username': 'bob',
                              'accesskey': 'foo',
                              'secretkey': 'bar',
                              'file': None}

        self.assertEqual(expected_user_dict, admin.user_dict(user))

    def test_user_dict_no_user(self):
        self.assertEqual({}, admin.user_dict(None))

    def test_project_dict(self):
        project = type('Project', (object,), {'id': 'project',
                                              'project_manager_id': 'foo',
                                              'description': 'bar'})

        expected_project_dict = {'projectname': 'project',
                                 'project_manager_id': 'foo',
                                 'description': 'bar'}

        self.assertEqual(expected_project_dict, admin.project_dict(project))

    def test_project_dict_no_project(self):
        self.assertEqual({}, admin.project_dict(None))

    def test_host_dict_using_updated_at(self):
        # instances and volumes only used for count
        instances = range(2)
        volumes = range(3)

        now = datetime.datetime.now()
        updated_at = now - datetime.timedelta(seconds=10)
        compute_service = {'updated_at': updated_at}
        volume_service = {'updated_at': updated_at}

        expected_host_dict = {'hostname': 'server',
                              'instance_count': 2,
                              'volume_count': 3,
                              'compute': 'up',
                              'volume': 'up'}

        self.assertEqual(expected_host_dict,
                         admin.host_dict('server', compute_service, instances,
                                         volume_service, volumes, now))

    def test_host_dict_service_down_using_created_at(self):
        # instances and volumes only used for count
        instances = range(2)
        volumes = range(3)

        # service_down_time is 60 by defualt so we set to 70 to simulate
        # services been down
        now = datetime.datetime.now()
        created_at = now - datetime.timedelta(seconds=70)
        compute_service = {'created_at': created_at, 'updated_at': None}
        volume_service = {'created_at': created_at, 'updated_at': None}

        expected_host_dict = {'hostname': 'server',
                              'instance_count': 2,
                              'volume_count': 3,
                              'compute': 'down',
                              'volume': 'down'}

        self.assertEqual(expected_host_dict,
                         admin.host_dict('server', compute_service, instances,
                                         volume_service, volumes, now))

    def test_instance_dict(self):
        inst = {'name': 'this_inst',
                'memory_mb': 1024,
                'vcpus': 2,
                'local_gb': 500,
                'flavorid': 1}

        expected_inst_dict = {'name': 'this_inst',
                              'memory_mb': 1024,
                              'vcpus': 2,
                              'disk_gb': 500,
                              'flavor_id': 1}

        self.assertEqual(expected_inst_dict, admin.instance_dict(inst))

    def test_vpn_dict_state_running(self):
        isonow = datetime.datetime.utcnow()
        vpn_instance = {'id': 1,
                        'created_at': isonow,
                        'fixed_ip': {'address': '127.0.0.1'}}

        project = type('Project', (object,), {'id': 'project',
                                              'vpn_ip': '127.0.0.1',
                                              'vpn_port': 1234})

        # Returns state running for 127.0.0.1 - look at class setup
        expected_vpn_dict = {'project_id': 'project',
                             'public_ip': '127.0.0.1',
                             'public_port': 1234,
                             'internal_ip': '127.0.0.1',
                             'instance_id':
                                ec2utils.id_to_ec2_id(1),
                             'created_at': utils.isotime(isonow),
                             'state': 'running'}

        self.assertEqual(expected_vpn_dict,
                         admin.vpn_dict(project, vpn_instance))

    def test_vpn_dict_state_down(self):
        isonow = datetime.datetime.utcnow()
        vpn_instance = {'id': 1,
                        'created_at': isonow,
                        'fixed_ip': {'address': '127.0.0.1'}}

        project = type('Project', (object,), {'id': 'project',
                                              'vpn_ip': '127.0.0.2',
                                              'vpn_port': 1234})

        # Returns state down for 127.0.0.2 - look at class setup
        vpn_dict = admin.vpn_dict(project, vpn_instance)
        self.assertEqual('down', vpn_dict['state'])

    def test_vpn_dict_invalid_project_vpn_config(self):
        isonow = datetime.datetime.utcnow()
        vpn_instance = {'id': 1,
                        'created_at': isonow,
                        'fixed_ip': {'address': '127.0.0.1'}}

        # Inline project object - vpn_port of None to make it invalid
        project = type('Project', (object,), {'id': 'project',
                                              'vpn_ip': '127.0.0.2',
                                              'vpn_port': None})

        # Returns state down for 127.0.0.2 - look at class setup
        vpn_dict = admin.vpn_dict(project, vpn_instance)
        self.assertEqual('down - invalid project vpn config',
                         vpn_dict['state'])

    def test_vpn_dict_non_vpn_instance(self):
        project = type('Project', (object,), {'id': 'project',
                                              'vpn_ip': '127.0.0.1',
                                              'vpn_port': '1234'})

        expected_vpn_dict = {'project_id': 'project',
                             'public_ip': '127.0.0.1',
                             'public_port': '1234',
                             'state': 'pending'}

        self.assertEqual(expected_vpn_dict, admin.vpn_dict(project, None))


class AdminControllerTestCase(test.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._c = context.get_admin_context()
        cls._ac = admin.AdminController()

    def test_admin_controller_to_str(self):
        self.assertEqual('AdminController', str(admin.AdminController()))

    def test_describe_instance_types(self):
        insts = self._ac.describe_instance_types(self._c)['instanceTypeSet']
        for inst_name in ('m1.medium', 'm1.large', 'm1.tiny', 'm1.xlarge',
                              'm1.small',):
            self.assertIn(inst_name, [i['name'] for i in insts])

    def test_register_user(self):
        registered_user = self._ac.register_user(self._c, 'bob')
        self.assertEqual('bob', registered_user['username'])

    def test_describe_user(self):
        self._ac.register_user(self._c, 'bob')
        self.assertEqual('bob',
            self._ac.describe_user(self._c, 'bob')['username'])

    def test_describe_users(self):
        self._ac.register_user(self._c, 'bob')
        users = self._ac.describe_users(self._c)
        self.assertIn('userSet', users)
        self.assertEqual('bob', users['userSet'][0]['username'])

    def test_deregister_user(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.deregister_user(self._c, 'bob')
        self.assertRaises(exception.UserNotFound,
                          self._ac.describe_user,
                          self._c, 'bob')

    def test_register_project(self):
        self._ac.register_user(self._c, 'bob')
        self.assertEqual('bobs_project',
            self._ac.register_project(self._c,
                                      'bobs_project',
                                      'bob')['projectname'])

    def test_describe_projects(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        projects = self._ac.describe_projects(self._c)
        self.assertIn('projectSet', projects)
        self.assertEqual('bobs_project',
                         projects['projectSet'][0]['projectname'])

    def test_deregister_project(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.deregister_project(self._c, 'bobs_project')
        self.assertRaises(exception.ProjectNotFound,
                          self._ac.describe_project,
                          self._c, 'bobs_project')

    def test_describe_project_members(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        members = self._ac.describe_project_members(self._c, 'bobs_project')
        self.assertIn('members', members)
        self.assertEqual('bob', members['members'][0]['member'])

    def test_modify_project(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.modify_project(self._c, 'bobs_project', 'bob',
                          description='I like cake')
        project = self._ac.describe_project(self._c, 'bobs_project')
        self.assertEqual('I like cake', project['description'])

    def test_modify_project_member_add(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_user(self._c, 'mary')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.modify_project_member(self._c, 'mary', 'bobs_project', 'add')
        members = self._ac.describe_project_members(self._c, 'bobs_project')
        self.assertIn('mary', [m['member'] for m in members['members']])

    def test_modify_project_member_remove(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.modify_project_member(self._c, 'bob', 'bobs_project',
                                       'remove')
        members = self._ac.describe_project_members(self._c, 'bobs_project')
        self.assertNotIn('bob', [m['member'] for m in members['members']])

    def test_modify_project_member_invalid_operation(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self.assertRaises(exception.ApiError,
                          self._ac.modify_project_member,
                          self._c, 'bob', 'bobs_project', 'invalid_operation')

    def test_describe_roles(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        roles = self._ac.describe_roles(self._c, 'bobs_project')

        # Default roles ('sysadmin', 'netadmin', 'developer') should be in here
        roles = [r['role'] for r in roles['roles']]
        for role in ('sysadmin', 'netadmin', 'developer'):
            self.assertIn('sysadmin', roles)

    def test_modify_user_role_add(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.modify_user_role(self._c, 'bob', 'itsec')
        user_roles = self._ac.describe_user_roles(self._c, 'bob')
        self.assertIn('itsec', [r['role'] for r in user_roles['roles']])

    def test_modify_user_role_project_add(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.modify_user_role(self._c, 'bob', 'developer', 'bobs_project')
        user_roles = self._ac.describe_user_roles(self._c, 'bob',
                                                  'bobs_project')
        self.assertIn('developer', [r['role'] for r in user_roles['roles']])

    def test_modify_user_role_remove(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.modify_user_role(self._c, 'bob', 'itsec')
        self._ac.modify_user_role(self._c, 'bob', 'itsec', operation='remove')
        user_roles = self._ac.describe_user_roles(self._c, 'bob')
        self.assertNotIn('itsec', [r['role'] for r in user_roles['roles']])

    def test_modify_user_role_project_remove(self):
        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        self._ac.modify_user_role(self._c, 'bob', 'developer', 'bobs_project')
        self._ac.modify_user_role(self._c, 'bob', 'developer', 'bobs_project',
                                  'remove')
        user_roles = self._ac.describe_user_roles(self._c, 'bob',
                                                  'bobs_project')
        self.assertNotIn('developer', [r['role'] for r in user_roles['roles']])

    def test_modify_user_role_invalid(self):
        self.assertRaises(exception.ApiError,
                          self._ac.modify_user_role,
                          self._c, 'bob', 'itsec',
                          operation='invalid_operation')

    def test_describe_hosts_compute(self):
        db.service_create(self._c, {'host': 'host1',
            'binary': "nova-compute",
            'topic': 'compute',
            'report_count': 0,
            'availability_zone': "zone1"})
        hosts = self._ac.describe_hosts(self._c)['hosts']
        self.assertEqual('host1', hosts[0]['hostname'])

    def test_describe_hosts_volume(self):
        db.service_create(self._c, {'host': 'volume1',
            'binary': "nova-volume",
            'topic': 'volume',
            'report_count': 0,
            'availability_zone': "zone1"})
        hosts = self._ac.describe_hosts(self._c)['hosts']
        self.assertEqual('volume1', hosts[0]['hostname'])

    def test_block_external_addresses(self):
        result = self._ac.block_external_addresses(self._c, '192.168.100.1/24')
        self.assertEqual('OK', result['status'])
        self.assertEqual('Added 3 rules', result['message'])

    def test_block_external_addresses_already_existent_rule(self):
        self._ac.block_external_addresses(self._c, '192.168.100.1/24')
        self.assertRaises(exception.ApiError,
                          self._ac.block_external_addresses,
                          self._c, '192.168.100.1/24')

    def test_describe_external_address_blocks(self):
        self._ac.block_external_addresses(self._c, '192.168.100.1/24')
        self.assertEqual(
                {'externalIpBlockInfo': [{'cidr': u'192.168.100.1/24'}]},
                self._ac.describe_external_address_blocks(self._c))

    def test_remove_external_address_block(self):
        self._ac.block_external_addresses(self._c, '192.168.100.1/24')

        result = self._ac.remove_external_address_block(self._c,
                                                        '192.168.100.1/24')
        self.assertEqual('OK', result['status'])
        self.assertEqual('Deleted 3 rules', result['message'])

        result = self._ac.describe_external_address_blocks(self._c)
        self.assertEqual([], result['externalIpBlockInfo'])

    def test_start_vpn(self):

        def fake_launch_vpn_instance(self, *args):
            pass

        def get_fake_instance_func():
            first_call = [True]

            def fake_instance_get_all_by_project(self, *args):
                if first_call[0]:
                    first_call[0] = False
                    return []
                else:
                    return [{'id': 1,
                            'user_id': 'bob',
                            'image_id': str(flags.FLAGS.vpn_image_id),
                            'project_id': 'bobs_project',
                            'instance_type_id': '1',
                            'os_type': 'linux',
                            'architecture': 'x86-64',
                            'state_description': 'running',
                            'vm_state': vm_states.ACTIVE,
                            'image_ref': '3'}]

            return fake_instance_get_all_by_project

        self.stubs.Set(pipelib.CloudPipe, 'launch_vpn_instance',
                       fake_launch_vpn_instance)
        self.stubs.Set(db, 'instance_get_all_by_project',
                       get_fake_instance_func())

        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')

        self.assertEqual('i-00000001',
                 self._ac.start_vpn(self._c, 'bobs_project')['instance_id'])

    def test_describe_vpns(self):
        def fake_instance_get_all_by_project(self, *args):
            now = datetime.datetime.now()
            created_at = now - datetime.timedelta(seconds=70)

            return [{'id': 1,
                    'user_id': 'bob',
                    'image_id': str(flags.FLAGS.vpn_image_id),
                    'project_id': 'bobs_project',
                    'instance_type_id': '1',
                    'os_type': 'linux',
                    'architecture': 'x86-64',
                    'state_description': 'running',
                    'created_at': created_at,
                    'vm_state': vm_states.ACTIVE,
                    'image_ref': '3'}]

        self.stubs.Set(db, 'instance_get_all_by_project',
                       fake_instance_get_all_by_project)

        self._ac.register_user(self._c, 'bob')
        self._ac.register_project(self._c, 'bobs_project', 'bob')
        vpns = self._ac.describe_vpns(self._c)

        self.assertIn('items', vpns)

        item = vpns['items'][0]
        self.assertEqual('i-00000001', item['instance_id'])
        self.assertEqual(None, item['public_port'])
        self.assertEqual(None, item['public_ip'])
        self.assertEqual('down - invalid project vpn config', item['state'])
        self.assertEqual(u'bobs_project', item['project_id'])

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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

import base64
import copy
import datetime
import functools
import os
import string
import tempfile

import fixtures
from oslo.config import cfg

from nova.api.ec2 import cloud
from nova.api.ec2 import ec2utils
from nova.api.ec2 import inst_state
from nova.api.metadata import password
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.image import s3
from nova.network import api as network_api
from nova.network import quantumv2
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova import test
from nova.tests.api.openstack.compute.contrib import (
    test_quantum_security_groups as test_quantum)
from nova.tests import fake_network
from nova.tests import fake_utils
from nova.tests.image import fake
from nova.tests import matchers
from nova import utils
from nova.virt import fake as fake_virt
from nova import volume

CONF = cfg.CONF
CONF.import_opt('compute_driver', 'nova.virt.driver')
CONF.import_opt('default_instance_type', 'nova.compute.flavors')
CONF.import_opt('use_ipv6', 'nova.netconf')
LOG = logging.getLogger(__name__)

HOST = "testhost"


def get_fake_cache():
    def _ip(ip, fixed=True, floats=None):
        ip_dict = {'address': ip, 'type': 'fixed'}
        if not fixed:
            ip_dict['type'] = 'floating'
        if fixed and floats:
            ip_dict['floating_ips'] = [_ip(f, fixed=False) for f in floats]
        return ip_dict

    info = [{'address': 'aa:bb:cc:dd:ee:ff',
             'id': 1,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'private',
                         'subnets': [{'cidr': '192.168.0.0/24',
                                      'ips': [_ip('192.168.0.3',
                                                  floats=['1.2.3.4',
                                                          '5.6.7.8']),
                                              _ip('192.168.0.4')]}]}}]
    if CONF.use_ipv6:
        ipv6_addr = 'fe80:b33f::a8bb:ccff:fedd:eeff'
        info[0]['network']['subnets'].append({'cidr': 'fe80:b33f::/64',
                                              'ips': [_ip(ipv6_addr)]})
    return info


def get_instances_with_cached_ips(orig_func, *args, **kwargs):
    """Kludge the cache into instance(s) without having to create DB
    entries
    """
    instances = orig_func(*args, **kwargs)
    if isinstance(instances, list):
        for instance in instances:
            instance['info_cache'] = {'network_info': get_fake_cache()}
    else:
        instances['info_cache'] = {'network_info': get_fake_cache()}
    return instances


class CloudTestCase(test.TestCase):
    def setUp(self):
        super(CloudTestCase, self).setUp()
        self.useFixture(test.SampleNetworks())
        ec2utils.reset_cache()
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   volume_api_class='nova.tests.fake_volume.API')
        self.useFixture(fixtures.FakeLogger('boto'))
        fake_utils.stub_out_utils_spawn_n(self.stubs)

        def fake_show(meh, context, id):
            return {'id': id,
                    'name': 'fake_name',
                    'container_format': 'ami',
                    'status': 'active',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'type': 'machine',
                        'image_state': 'available'}}

        def fake_detail(_self, context, **kwargs):
            image = fake_show(None, context, None)
            image['name'] = kwargs.get('filters', {}).get('name')
            return [image]

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail)
        fake.stub_out_image_service(self.stubs)

        def dumb(*args, **kwargs):
            pass

        self.stubs.Set(compute_utils, 'notify_about_instance_usage', dumb)
        fake_network.set_stub_network_methods(self.stubs)

        # set up our cloud
        self.cloud = cloud.CloudController()
        self.flags(scheduler_driver='nova.scheduler.chance.ChanceScheduler')

        # Short-circuit the conductor service
        self.flags(use_local=True, group='conductor')

        # set up services
        self.conductor = self.start_service('conductor',
                manager=CONF.conductor.manager)
        self.compute = self.start_service('compute')
        self.scheduler = self.start_service('scheduler')
        self.network = self.start_service('network')

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)
        self.volume_api = volume.API()

        # NOTE(comstud): Make 'cast' behave like a 'call' which will
        # ensure that operations complete
        self.stubs.Set(rpc, 'cast', rpc.call)

        # make sure we can map ami-00000001/2 to a uuid in FakeImageService
        db.api.s3_image_create(self.context,
                               'cedef40a-ed67-4d10-800e-17455edce175')
        db.api.s3_image_create(self.context,
                               '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6')

    def tearDown(self):
        self.volume_api.reset_fake_api(self.context)
        super(CloudTestCase, self).tearDown()
        fake.FakeImageService_reset()

    def fake_get_target(obj, iqn):
        return 1

    def fake_remove_iscsi_target(obj, tid, lun, vol_id, **kwargs):
        pass

    def _stub_instance_get_with_fixed_ips(self, func_name):
        orig_func = getattr(self.cloud.compute_api, func_name)

        def fake_get(*args, **kwargs):
            return get_instances_with_cached_ips(orig_func, *args, **kwargs)
        self.stubs.Set(self.cloud.compute_api, func_name, fake_get)

    def _create_key(self, name):
        # NOTE(vish): create depends on pool, so just call helper directly
        keypair_api = compute_api.KeypairAPI()
        return keypair_api.create_key_pair(self.context, self.context.user_id,
                                           name)

    def test_describe_regions(self):
        # Makes sure describe regions runs without raising an exception.
        result = self.cloud.describe_regions(self.context)
        self.assertEqual(len(result['regionInfo']), 1)
        self.flags(region_list=["one=test_host1", "two=test_host2"])
        result = self.cloud.describe_regions(self.context)
        self.assertEqual(len(result['regionInfo']), 2)

    def test_describe_addresses(self):
        # Makes sure describe addresses runs without raising an exception.
        address = "10.10.10.10"
        db.floating_ip_create(self.context,
                              {'address': address,
                               'pool': 'nova'})
        self.cloud.allocate_address(self.context)
        self.cloud.describe_addresses(self.context)
        self.cloud.release_address(self.context,
                                  public_ip=address)
        db.floating_ip_destroy(self.context, address)

    def test_describe_specific_address(self):
        # Makes sure describe specific address works.
        addresses = ["10.10.10.10", "10.10.10.11"]
        for address in addresses:
            db.floating_ip_create(self.context,
                                  {'address': address,
                                   'pool': 'nova'})
            self.cloud.allocate_address(self.context)
        result = self.cloud.describe_addresses(self.context)
        self.assertEqual(len(result['addressesSet']), 2)
        result = self.cloud.describe_addresses(self.context,
                                               public_ip=['10.10.10.10'])
        self.assertEqual(len(result['addressesSet']), 1)
        for address in addresses:
            self.cloud.release_address(self.context,
                                       public_ip=address)
            db.floating_ip_destroy(self.context, address)

    def test_allocate_address(self):
        address = "10.10.10.10"
        allocate = self.cloud.allocate_address
        db.floating_ip_create(self.context,
                              {'address': address,
                               'pool': 'nova'})
        self.assertEqual(allocate(self.context)['publicIp'], address)
        db.floating_ip_destroy(self.context, address)
        self.assertRaises(exception.NoMoreFloatingIps,
                          allocate,
                          self.context)

    def test_release_address(self):
        address = "10.10.10.10"
        db.floating_ip_create(self.context,
                              {'address': address,
                               'pool': 'nova',
                               'project_id': self.project_id})
        result = self.cloud.release_address(self.context, address)
        self.assertEqual(result.get('return', None), 'true')

    def test_associate_disassociate_address(self):
        # Verifies associate runs cleanly without raising an exception.
        address = "10.10.10.10"
        db.floating_ip_create(self.context,
                              {'address': address,
                               'pool': 'nova'})
        self.cloud.allocate_address(self.context)
        # TODO(jkoelker) Probably need to query for instance_type_id and
        #                make sure we get a valid one
        inst = db.instance_create(self.context, {'host': self.compute.host,
                                                 'display_name': HOST,
                                                 'instance_type_id': 1})
        networks = db.network_get_all(self.context)
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': self.network.host})
        project_id = self.context.project_id
        nw_info = self.network.allocate_for_instance(self.context,
                                                 instance_id=inst['id'],
                                                 instance_uuid=inst['uuid'],
                                                 host=inst['host'],
                                                 vpn=None,
                                                 rxtx_factor=3,
                                                 project_id=project_id,
                                                 macs=None)

        fixed_ips = nw_info.fixed_ips()
        ec2_id = ec2utils.id_to_ec2_inst_id(inst['uuid'])

        self.stubs.Set(ec2utils, 'get_ip_info_for_instance',
                       lambda *args: {'fixed_ips': ['10.0.0.1'],
                                      'fixed_ip6s': [],
                                      'floating_ips': []})
        self.stubs.Set(network_api.API, 'get_instance_id_by_floating_address',
                       lambda *args: 1)
        self.cloud.associate_address(self.context,
                                     instance_id=ec2_id,
                                     public_ip=address)
        self.cloud.disassociate_address(self.context,
                                        public_ip=address)
        self.cloud.release_address(self.context,
                                  public_ip=address)
        self.network.deallocate_fixed_ip(self.context, fixed_ips[0]['address'],
                                         inst['host'])
        db.instance_destroy(self.context, inst['uuid'])
        db.floating_ip_destroy(self.context, address)

    def test_disassociate_auto_assigned_address(self):
        """Verifies disassociating auto assigned floating IP
        raises an exception
        """
        address = "10.10.10.10"

        def fake_get(*args, **kwargs):
            pass

        def fake_disassociate_floating_ip(*args, **kwargs):
            raise exception.CannotDisassociateAutoAssignedFloatingIP()

        self.stubs.Set(network_api.API, 'get_instance_id_by_floating_address',
                       lambda *args: 1)
        self.stubs.Set(self.cloud.compute_api, 'get', fake_get)
        self.stubs.Set(network_api.API, 'disassociate_floating_ip',
                                    fake_disassociate_floating_ip)

        self.assertRaises(exception.EC2APIError,
                          self.cloud.disassociate_address,
                          self.context, public_ip=address)

    def test_disassociate_unassociated_address(self):
        address = "10.10.10.10"
        db.floating_ip_create(self.context,
                              {'address': address,
                               'pool': 'nova'})
        self.cloud.allocate_address(self.context)
        self.cloud.describe_addresses(self.context)
        self.assertRaises(exception.InstanceNotFound,
                          self.cloud.disassociate_address,
                          self.context, public_ip=address)
        db.floating_ip_destroy(self.context, address)

    def test_describe_security_groups(self):
        # Makes sure describe_security_groups works and filters results.
        sec = db.security_group_create(self.context,
                                       {'project_id': self.context.project_id,
                                        'name': 'test'})
        result = self.cloud.describe_security_groups(self.context)
        # NOTE(vish): should have the default group as well
        self.assertEqual(len(result['securityGroupInfo']), 2)
        result = self.cloud.describe_security_groups(self.context,
                      group_name=[sec['name']])
        self.assertEqual(len(result['securityGroupInfo']), 1)
        self.assertEqual(
                result['securityGroupInfo'][0]['groupName'],
                sec['name'])
        db.security_group_destroy(self.context, sec['id'])

    def test_describe_security_groups_all_tenants(self):
        # Makes sure describe_security_groups works and filters results.
        sec = db.security_group_create(self.context,
                                       {'project_id': 'foobar',
                                        'name': 'test'})

        def _check_name(result, i, expected):
            self.assertEqual(result['securityGroupInfo'][i]['groupName'],
                             expected)

        # include all tenants
        filter = [{'name': 'all-tenants', 'value': {'1': 1}}]
        result = self.cloud.describe_security_groups(self.context,
                                                     filter=filter)
        self.assertEqual(len(result['securityGroupInfo']), 2)
        _check_name(result, 0, 'default')
        _check_name(result, 1, sec['name'])

        # exclude all tenants
        filter = [{'name': 'all-tenants', 'value': {'1': 0}}]
        result = self.cloud.describe_security_groups(self.context,
                                                     filter=filter)
        self.assertEqual(len(result['securityGroupInfo']), 1)
        _check_name(result, 0, 'default')

        # default all tenants
        result = self.cloud.describe_security_groups(self.context)
        self.assertEqual(len(result['securityGroupInfo']), 1)
        _check_name(result, 0, 'default')

        db.security_group_destroy(self.context, sec['id'])

    def test_describe_security_groups_by_id(self):
        sec = db.security_group_create(self.context,
                                       {'project_id': self.context.project_id,
                                        'name': 'test'})
        result = self.cloud.describe_security_groups(self.context,
                      group_id=[sec['id']])
        self.assertEqual(len(result['securityGroupInfo']), 1)
        self.assertEqual(
                result['securityGroupInfo'][0]['groupName'],
                sec['name'])
        default = db.security_group_get_by_name(self.context,
                                                self.context.project_id,
                                                'default')
        result = self.cloud.describe_security_groups(self.context,
                      group_id=[default['id']])
        self.assertEqual(len(result['securityGroupInfo']), 1)
        self.assertEqual(
                result['securityGroupInfo'][0]['groupName'],
                'default')
        db.security_group_destroy(self.context, sec['id'])

    def test_create_delete_security_group(self):
        descript = 'test description'
        create = self.cloud.create_security_group
        result = create(self.context, 'testgrp', descript)
        group_descript = result['securityGroupSet'][0]['groupDescription']
        self.assertEqual(descript, group_descript)
        delete = self.cloud.delete_security_group
        self.assertTrue(delete(self.context, 'testgrp'))

    def test_security_group_quota_limit(self):
        self.flags(quota_security_groups=10)
        for i in range(1, CONF.quota_security_groups + 1):
            name = 'test name %i' % i
            descript = 'test description %i' % i
            create = self.cloud.create_security_group
            result = create(self.context, name, descript)

        # 11'th group should fail
        self.assertRaises(exception.EC2APIError,
                          create, self.context, 'foo', 'bar')

    def test_delete_security_group_by_id(self):
        sec = db.security_group_create(self.context,
                                       {'project_id': self.context.project_id,
                                        'name': 'test'})
        delete = self.cloud.delete_security_group
        self.assertTrue(delete(self.context, group_id=sec['id']))

    def test_delete_security_group_with_bad_name(self):
        delete = self.cloud.delete_security_group
        notfound = exception.SecurityGroupNotFound
        self.assertRaises(notfound, delete, self.context, 'badname')

    def test_delete_security_group_with_bad_group_id(self):
        delete = self.cloud.delete_security_group
        notfound = exception.SecurityGroupNotFound
        self.assertRaises(notfound, delete, self.context, group_id=999)

    def test_delete_security_group_no_params(self):
        delete = self.cloud.delete_security_group
        self.assertRaises(exception.EC2APIError, delete, self.context)

    def test_authorize_security_group_ingress(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'to_port': '999', 'from_port': '999', 'ip_protocol': 'tcp'}
        self.assertTrue(authz(self.context, group_name=sec['name'], **kwargs))

    def test_authorize_security_group_ingress_ip_permissions_ip_ranges(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'ip_permissions': [{'to_port': 81, 'from_port': 81,
                                      'ip_ranges':
                                         {'1': {'cidr_ip': u'0.0.0.0/0'},
                                          '2': {'cidr_ip': u'10.10.10.10/32'}},
                                      'ip_protocol': u'tcp'}]}
        self.assertTrue(authz(self.context, group_name=sec['name'], **kwargs))

    def test_authorize_security_group_fail_missing_source_group(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'ip_permissions': [{'to_port': 81, 'from_port': 81,
                  'ip_ranges': {'1': {'cidr_ip': u'0.0.0.0/0'},
                                '2': {'cidr_ip': u'10.10.10.10/32'}},
                  'groups': {'1': {'user_id': u'someuser',
                                   'group_name': u'somegroup1'}},
                  'ip_protocol': u'tcp'}]}
        self.assertRaises(exception.SecurityGroupNotFound, authz,
                          self.context, group_name=sec['name'], **kwargs)

    def test_authorize_security_group_ingress_ip_permissions_groups(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context,
                                       {'project_id': 'someuser',
                                        'name': 'somegroup1'})
        sec = db.security_group_create(self.context,
                                       {'project_id': 'someuser',
                                        'name': 'othergroup2'})
        sec = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'ip_permissions': [{'to_port': 81, 'from_port': 81,
                  'groups': {'1': {'user_id': u'someuser',
                                   'group_name': u'somegroup1'},
                             '2': {'user_id': u'someuser',
                                   'group_name': u'othergroup2'}},
                  'ip_protocol': u'tcp'}]}
        self.assertTrue(authz(self.context, group_name=sec['name'], **kwargs))

    def test_describe_security_group_ingress_groups(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec1 = db.security_group_create(self.context, kwargs)
        sec2 = db.security_group_create(self.context,
                                       {'project_id': 'someuser',
                                        'name': 'somegroup1'})
        sec3 = db.security_group_create(self.context,
                                       {'project_id': 'someuser',
                                        'name': 'othergroup2'})
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'ip_permissions': [
                  {'groups': {'1': {'user_id': u'someuser',
                                    'group_name': u'somegroup1'}}},
                  {'ip_protocol': 'tcp',
                   'from_port': 80,
                   'to_port': 80,
                   'groups': {'1': {'user_id': u'someuser',
                                    'group_name': u'othergroup2'}}}]}
        self.assertTrue(authz(self.context, group_name=sec1['name'], **kwargs))
        describe = self.cloud.describe_security_groups
        groups = describe(self.context, group_name=['test'])
        self.assertEquals(len(groups['securityGroupInfo']), 1)
        actual_rules = groups['securityGroupInfo'][0]['ipPermissions']
        self.assertEquals(len(actual_rules), 4)
        expected_rules = [{'fromPort': -1,
                           'groups': [{'groupName': 'somegroup1',
                                       'userId': 'someuser'}],
                           'ipProtocol': 'icmp',
                           'ipRanges': [],
                           'toPort': -1},
                          {'fromPort': 1,
                           'groups': [{'groupName': u'somegroup1',
                                       'userId': u'someuser'}],
                           'ipProtocol': 'tcp',
                           'ipRanges': [],
                           'toPort': 65535},
                          {'fromPort': 1,
                           'groups': [{'groupName': u'somegroup1',
                                       'userId': u'someuser'}],
                           'ipProtocol': 'udp',
                           'ipRanges': [],
                           'toPort': 65535},
                          {'fromPort': 80,
                           'groups': [{'groupName': u'othergroup2',
                                       'userId': u'someuser'}],
                           'ipProtocol': u'tcp',
                           'ipRanges': [],
                           'toPort': 80}]
        for rule in expected_rules:
            self.assertTrue(rule in actual_rules)

        db.security_group_destroy(self.context, sec3['id'])
        db.security_group_destroy(self.context, sec2['id'])
        db.security_group_destroy(self.context, sec1['id'])

    def test_revoke_security_group_ingress(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'to_port': '999', 'from_port': '999', 'ip_protocol': 'tcp'}
        authz(self.context, group_id=sec['id'], **kwargs)
        revoke = self.cloud.revoke_security_group_ingress
        self.assertTrue(revoke(self.context, group_name=sec['name'], **kwargs))

    def test_authorize_revoke_security_group_ingress_by_id(self):
        sec = db.security_group_create(self.context,
                                       {'project_id': self.context.project_id,
                                        'name': 'test'})
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'to_port': '999', 'from_port': '999', 'ip_protocol': 'tcp'}
        authz(self.context, group_id=sec['id'], **kwargs)
        revoke = self.cloud.revoke_security_group_ingress
        self.assertTrue(revoke(self.context, group_id=sec['id'], **kwargs))

    def test_authorize_security_group_ingress_missing_protocol_params(self):
        sec = db.security_group_create(self.context,
                                       {'project_id': self.context.project_id,
                                        'name': 'test'})
        authz = self.cloud.authorize_security_group_ingress
        self.assertRaises(exception.EC2APIError, authz, self.context, 'test')

    def test_authorize_security_group_ingress_missing_group_name_or_id(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        authz = self.cloud.authorize_security_group_ingress
        self.assertRaises(exception.EC2APIError, authz, self.context, **kwargs)

    def test_authorize_security_group_ingress_already_exists(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'to_port': '999', 'from_port': '999', 'ip_protocol': 'tcp'}
        authz(self.context, group_name=sec['name'], **kwargs)
        self.assertRaises(exception.EC2APIError, authz, self.context,
                          group_name=sec['name'], **kwargs)

    def test_security_group_ingress_quota_limit(self):
        self.flags(quota_security_group_rules=20)
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec_group = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        for i in range(100, 120):
            kwargs = {'to_port': i, 'from_port': i, 'ip_protocol': 'tcp'}
            authz(self.context, group_id=sec_group['id'], **kwargs)

        kwargs = {'to_port': 121, 'from_port': 121, 'ip_protocol': 'tcp'}
        self.assertRaises(exception.EC2APIError, authz, self.context,
                              group_id=sec_group['id'], **kwargs)

    def _test_authorize_security_group_no_ports_with_source_group(self, proto):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)

        authz = self.cloud.authorize_security_group_ingress
        auth_kwargs = {'ip_protocol': proto,
                       'groups': {'1': {'user_id': self.context.user_id,
                                        'group_name': u'test'}}}
        self.assertTrue(authz(self.context, group_name=sec['name'],
                        **auth_kwargs))

        describe = self.cloud.describe_security_groups
        groups = describe(self.context, group_name=['test'])
        self.assertEquals(len(groups['securityGroupInfo']), 1)
        actual_rules = groups['securityGroupInfo'][0]['ipPermissions']
        expected_rules = [{'groups': [{'groupName': 'test',
                                       'userId': self.context.user_id}],
                           'ipProtocol': proto,
                           'ipRanges': []}]
        if proto == 'icmp':
            expected_rules[0]['fromPort'] = -1
            expected_rules[0]['toPort'] = -1
        else:
            expected_rules[0]['fromPort'] = 1
            expected_rules[0]['toPort'] = 65535
        self.assertTrue(expected_rules == actual_rules)
        describe = self.cloud.describe_security_groups
        groups = describe(self.context, group_name=['test'])

        db.security_group_destroy(self.context, sec['id'])

    def _test_authorize_security_group_no_ports_no_source_group(self, proto):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)

        authz = self.cloud.authorize_security_group_ingress
        auth_kwargs = {'ip_protocol': proto}
        self.assertRaises(exception.EC2APIError, authz, self.context,
                          group_name=sec['name'], **auth_kwargs)

        db.security_group_destroy(self.context, sec['id'])

    def test_authorize_security_group_no_ports_icmp(self):
        self._test_authorize_security_group_no_ports_with_source_group('icmp')
        self._test_authorize_security_group_no_ports_no_source_group('icmp')

    def test_authorize_security_group_no_ports_tcp(self):
        self._test_authorize_security_group_no_ports_with_source_group('tcp')
        self._test_authorize_security_group_no_ports_no_source_group('tcp')

    def test_authorize_security_group_no_ports_udp(self):
        self._test_authorize_security_group_no_ports_with_source_group('udp')
        self._test_authorize_security_group_no_ports_no_source_group('udp')

    def test_revoke_security_group_ingress_missing_group_name_or_id(self):
        kwargs = {'to_port': '999', 'from_port': '999', 'ip_protocol': 'tcp'}
        revoke = self.cloud.revoke_security_group_ingress
        self.assertRaises(exception.EC2APIError, revoke,
                self.context, **kwargs)

    def test_delete_security_group_in_use_by_group(self):
        group1 = self.cloud.create_security_group(self.context, 'testgrp1',
                                                  "test group 1")
        group2 = self.cloud.create_security_group(self.context, 'testgrp2',
                                                  "test group 2")
        kwargs = {'groups': {'1': {'user_id': u'%s' % self.context.user_id,
                                   'group_name': u'testgrp2'}},
                 }
        self.cloud.authorize_security_group_ingress(self.context,
                group_name='testgrp1', **kwargs)

        group1 = db.security_group_get_by_name(self.context,
                                               self.project_id, 'testgrp1')
        get_rules = db.security_group_rule_get_by_security_group

        self.assertTrue(get_rules(self.context, group1['id']))
        self.cloud.delete_security_group(self.context, 'testgrp2')
        self.assertFalse(get_rules(self.context, group1['id']))

    def test_delete_security_group_in_use_by_instance(self):
        # Ensure that a group can not be deleted if in use by an instance.
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        args = {'reservation_id': 'a',
                 'image_ref': image_uuid,
                 'instance_type_id': 1,
                 'host': 'host1',
                 'vm_state': 'active'}
        inst = db.instance_create(self.context, args)

        args = {'user_id': self.context.user_id,
                'project_id': self.context.project_id,
                'name': 'testgrp',
                'description': 'Test group'}
        group = db.security_group_create(self.context, args)

        db.instance_add_security_group(self.context, inst['uuid'], group['id'])

        self.assertRaises(exception.InvalidGroup,
                          self.cloud.delete_security_group,
                          self.context, 'testgrp')

        db.instance_destroy(self.context, inst['uuid'])

        self.cloud.delete_security_group(self.context, 'testgrp')

    def test_describe_availability_zones(self):
        # Makes sure describe_availability_zones works and filters results.
        service1 = db.service_create(self.context, {'host': 'host1_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0})
        service2 = db.service_create(self.context, {'host': 'host2_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0})
        # Aggregate based zones
        agg = db.aggregate_create(self.context,
                {'name': 'agg1'}, {'availability_zone': 'zone1'})
        db.aggregate_host_add(self.context, agg['id'], 'host1_zones')
        agg = db.aggregate_create(self.context,
                {'name': 'agg2'}, {'availability_zone': 'zone2'})
        db.aggregate_host_add(self.context, agg['id'], 'host2_zones')
        result = self.cloud.describe_availability_zones(self.context)
        self.assertEqual(len(result['availabilityZoneInfo']), 3)
        admin_ctxt = context.get_admin_context(read_deleted="no")
        result = self.cloud.describe_availability_zones(admin_ctxt,
                zone_name='verbose')
        self.assertEqual(len(result['availabilityZoneInfo']), 16)
        db.service_destroy(self.context, service1['id'])
        db.service_destroy(self.context, service2['id'])

    def test_describe_availability_zones_verbose(self):
        # Makes sure describe_availability_zones works and filters results.
        service1 = db.service_create(self.context, {'host': 'host1_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0})
        service2 = db.service_create(self.context, {'host': 'host2_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0})
        agg = db.aggregate_create(self.context,
                {'name': 'agg1'}, {'availability_zone': 'second_zone'})
        db.aggregate_host_add(self.context, agg['id'], 'host2_zones')

        admin_ctxt = context.get_admin_context(read_deleted="no")
        result = self.cloud.describe_availability_zones(admin_ctxt,
                                                        zone_name='verbose')

        self.assertEqual(len(result['availabilityZoneInfo']), 15)
        db.service_destroy(self.context, service1['id'])
        db.service_destroy(self.context, service2['id'])

    def test_describe_instances(self):
        # Makes sure describe_instances works and filters results.
        self.flags(use_ipv6=True)

        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        sys_meta = flavors.save_instance_type_info(
            {}, flavors.get_instance_type(1))
        inst1 = db.instance_create(self.context, {'reservation_id': 'a',
                                                  'image_ref': image_uuid,
                                                  'instance_type_id': 1,
                                                  'host': 'host1',
                                                  'hostname': 'server-1234',
                                                  'vm_state': 'active',
                                                  'system_metadata': sys_meta})
        inst2 = db.instance_create(self.context, {'reservation_id': 'a',
                                                  'image_ref': image_uuid,
                                                  'instance_type_id': 1,
                                                  'host': 'host2',
                                                  'hostname': 'server-4321',
                                                  'vm_state': 'active',
                                                  'system_metadata': sys_meta})
        comp1 = db.service_create(self.context, {'host': 'host1',
                                                 'topic': "compute"})
        agg = db.aggregate_create(self.context,
                {'name': 'agg1'}, {'availability_zone': 'zone1'})
        db.aggregate_host_add(self.context, agg['id'], 'host1')

        comp2 = db.service_create(self.context, {'host': 'host2',
                                                 'topic': "compute"})
        agg2 = db.aggregate_create(self.context,
                {'name': 'agg2'}, {'availability_zone': 'zone2'})
        db.aggregate_host_add(self.context, agg2['id'], 'host2')

        result = self.cloud.describe_instances(self.context)
        result = result['reservationSet'][0]
        self.assertEqual(len(result['instancesSet']), 2)

        # Now try filtering.
        instance_id = ec2utils.id_to_ec2_inst_id(inst2['uuid'])
        result = self.cloud.describe_instances(self.context,
                                             instance_id=[instance_id])
        result = result['reservationSet'][0]
        self.assertEqual(len(result['instancesSet']), 1)
        instance = result['instancesSet'][0]
        self.assertEqual(instance['instanceId'], instance_id)
        self.assertEqual(instance['placement']['availabilityZone'],
                'zone2')
        self.assertEqual(instance['publicDnsName'], '1.2.3.4')
        self.assertEqual(instance['ipAddress'], '1.2.3.4')
        self.assertEqual(instance['dnsName'], '1.2.3.4')
        self.assertEqual(instance['tagSet'], [])
        self.assertEqual(instance['privateDnsName'], 'server-4321')
        self.assertEqual(instance['privateIpAddress'], '192.168.0.3')
        self.assertEqual(instance['dnsNameV6'],
                'fe80:b33f::a8bb:ccff:fedd:eeff')

        # A filter with even one invalid id should cause an exception to be
        # raised
        self.assertRaises(exception.InstanceNotFound,
                          self.cloud.describe_instances, self.context,
                          instance_id=[instance_id, '435679'])

        db.instance_destroy(self.context, inst1['uuid'])
        db.instance_destroy(self.context, inst2['uuid'])
        db.service_destroy(self.context, comp1['id'])
        db.service_destroy(self.context, comp2['id'])

    def test_describe_instances_all_invalid(self):
        # Makes sure describe_instances works and filters results.
        self.flags(use_ipv6=True)

        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        instance_id = ec2utils.id_to_ec2_inst_id('435679')
        self.assertRaises(exception.InstanceNotFound,
                          self.cloud.describe_instances, self.context,
                          instance_id=[instance_id])

    def test_describe_instances_with_filters(self):
        # Makes sure describe_instances works and filters results.
        filters = {'filter': [{'name': 'test',
                               'value': ['a', 'b']},
                              {'name': 'another_test',
                               'value': 'a string'}]}

        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        result = self.cloud.describe_instances(self.context, **filters)
        self.assertEqual(result, {'reservationSet': []})

    def test_describe_instances_with_tag_filters(self):
        # Makes sure describe_instances works and filters tag results.

        # We need to stub network calls
        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        # We need to stub out the MQ call - it won't succeed.  We do want
        # to check that the method is called, though
        meta_changes = [None]

        def fake_change_instance_metadata(inst, ctxt, diff, instance=None,
                                          instance_uuid=None):
            meta_changes[0] = diff

        self.stubs.Set(compute_rpcapi.ComputeAPI, 'change_instance_metadata',
                       fake_change_instance_metadata)

        # Create some test images
        sys_meta = flavors.save_instance_type_info(
            {}, flavors.get_instance_type(1))
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        inst1_kwargs = {
                'reservation_id': 'a',
                'image_ref': image_uuid,
                'instance_type_id': 1,
                'host': 'host1',
                'vm_state': 'active',
                'hostname': 'server-1111',
                'created_at': datetime.datetime(2012, 5, 1, 1, 1, 1),
                'system_metadata': sys_meta
        }

        inst2_kwargs = {
                'reservation_id': 'b',
                'image_ref': image_uuid,
                'instance_type_id': 1,
                'host': 'host2',
                'vm_state': 'active',
                'hostname': 'server-1112',
                'created_at': datetime.datetime(2012, 5, 1, 1, 1, 2),
                'system_metadata': sys_meta
        }

        inst1 = db.instance_create(self.context, inst1_kwargs)
        ec2_id1 = ec2utils.id_to_ec2_inst_id(inst1['uuid'])

        inst2 = db.instance_create(self.context, inst2_kwargs)
        ec2_id2 = ec2utils.id_to_ec2_inst_id(inst2['uuid'])

        # Create some tags
        # We get one overlapping pair, one overlapping key, and a
        # disparate pair
        # inst1 : {'foo': 'bar', 'baz': 'wibble', 'bax': 'wobble'}
        # inst2 : {'foo': 'bar', 'baz': 'quux', 'zog': 'bobble'}

        md = {'key': 'foo', 'value': 'bar'}
        self.cloud.create_tags(self.context, resource_id=[ec2_id1, ec2_id2],
                tag=[md])

        md2 = {'key': 'baz', 'value': 'wibble'}
        md3 = {'key': 'bax', 'value': 'wobble'}
        self.cloud.create_tags(self.context, resource_id=[ec2_id1],
                tag=[md2, md3])

        md4 = {'key': 'baz', 'value': 'quux'}
        md5 = {'key': 'zog', 'value': 'bobble'}
        self.cloud.create_tags(self.context, resource_id=[ec2_id2],
                tag=[md4, md5])
        # We should be able to search by:

        inst1_ret = {
            'groupSet': None,
            'instancesSet': [{'amiLaunchIndex': None,
                              'dnsName': '1.2.3.4',
                              'dnsNameV6': 'fe80:b33f::a8bb:ccff:fedd:eeff',
                              'imageId': 'ami-00000001',
                              'instanceId': 'i-00000001',
                              'instanceState': {'code': 16,
                                                'name': 'running'},
                              'instanceType': u'm1.medium',
                              'ipAddress': '1.2.3.4',
                              'keyName': 'None (None, host1)',
                              'launchTime':
                                  datetime.datetime(2012, 5, 1, 1, 1, 1),
                              'placement': {
                                  'availabilityZone': 'nova'},
                              'privateDnsName': u'server-1111',
                              'privateIpAddress': '192.168.0.3',
                              'productCodesSet': None,
                              'publicDnsName': '1.2.3.4',
                              'rootDeviceName': '/dev/sda1',
                              'rootDeviceType': 'instance-store',
                              'tagSet': [{'key': u'foo',
                                          'value': u'bar'},
                                         {'key': u'baz',
                                          'value': u'wibble'},
                                         {'key': u'bax',
                                          'value': u'wobble'}]}],
            'ownerId': None,
            'reservationId': u'a'}

        inst2_ret = {
             'groupSet': None,
             'instancesSet': [{'amiLaunchIndex': None,
                               'dnsName': '1.2.3.4',
                               'dnsNameV6': 'fe80:b33f::a8bb:ccff:fedd:eeff',
                               'imageId': 'ami-00000001',
                               'instanceId': 'i-00000002',
                               'instanceState': {'code': 16,
                                                 'name': 'running'},
                               'instanceType': u'm1.medium',
                               'ipAddress': '1.2.3.4',
                               'keyName': u'None (None, host2)',
                               'launchTime':
                                   datetime.datetime(2012, 5, 1, 1, 1, 2),
                               'placement': {
                                   'availabilityZone': 'nova'},
                               'privateDnsName': u'server-1112',
                               'privateIpAddress': '192.168.0.3',
                               'productCodesSet': None,
                               'publicDnsName': '1.2.3.4',
                               'rootDeviceName': '/dev/sda1',
                               'rootDeviceType': 'instance-store',
                               'tagSet': [{'key': u'foo',
                                           'value': u'bar'},
                                          {'key': u'baz',
                                           'value': u'quux'},
                                          {'key': u'zog',
                                           'value': u'bobble'}]}],
             'ownerId': None,
             'reservationId': u'b'}

        # No filter
        result = self.cloud.describe_instances(self.context)
        self.assertEqual(result, {'reservationSet': [inst1_ret, inst2_ret]})

        # Key search
        # Both should have tags with key 'foo' and value 'bar'
        filters = {'filter': [{'name': 'tag:foo',
                               'value': ['bar']}]}
        result = self.cloud.describe_instances(self.context, **filters)
        self.assertEqual(result, {'reservationSet': [inst1_ret, inst2_ret]})

        # Both should have tags with key 'foo'
        filters = {'filter': [{'name': 'tag-key',
                               'value': ['foo']}]}
        result = self.cloud.describe_instances(self.context, **filters)
        self.assertEqual(result, {'reservationSet': [inst1_ret, inst2_ret]})

        # Value search
        # Only inst2 should have tags with key 'baz' and value 'quux'
        filters = {'filter': [{'name': 'tag:baz',
                               'value': ['quux']}]}
        result = self.cloud.describe_instances(self.context, **filters)
        self.assertEqual(result, {'reservationSet': [inst2_ret]})

        # Only inst2 should have tags with value 'quux'
        filters = {'filter': [{'name': 'tag-value',
                               'value': ['quux']}]}
        result = self.cloud.describe_instances(self.context, **filters)
        self.assertEqual(result, {'reservationSet': [inst2_ret]})

        # Multiple values
        # Both should have tags with key 'baz' and values in the set
        # ['quux', 'wibble']
        filters = {'filter': [{'name': 'tag:baz',
                               'value': ['quux', 'wibble']}]}
        result = self.cloud.describe_instances(self.context, **filters)
        self.assertEqual(result, {'reservationSet': [inst1_ret, inst2_ret]})

        # Both should have tags with key 'baz' or tags with value 'bar'
        filters = {'filter': [{'name': 'tag-key',
                               'value': ['baz']},
                              {'name': 'tag-value',
                               'value': ['bar']}]}
        result = self.cloud.describe_instances(self.context, **filters)
        self.assertEqual(result, {'reservationSet': [inst1_ret, inst2_ret]})

        # destroy the test instances
        db.instance_destroy(self.context, inst1['uuid'])
        db.instance_destroy(self.context, inst2['uuid'])

    def test_describe_instances_sorting(self):
        # Makes sure describe_instances works and is sorted as expected.
        self.flags(use_ipv6=True)

        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        sys_meta = flavors.save_instance_type_info(
            {}, flavors.get_instance_type(1))
        inst_base = {
                'reservation_id': 'a',
                'image_ref': image_uuid,
                'instance_type_id': 1,
                'vm_state': 'active',
                'system_metadata': sys_meta,
        }

        inst1_kwargs = {}
        inst1_kwargs.update(inst_base)
        inst1_kwargs['host'] = 'host1'
        inst1_kwargs['hostname'] = 'server-1111'
        inst1_kwargs['created_at'] = datetime.datetime(2012, 5, 1, 1, 1, 1)
        inst1 = db.instance_create(self.context, inst1_kwargs)

        inst2_kwargs = {}
        inst2_kwargs.update(inst_base)
        inst2_kwargs['host'] = 'host2'
        inst2_kwargs['hostname'] = 'server-2222'
        inst2_kwargs['created_at'] = datetime.datetime(2012, 2, 1, 1, 1, 1)
        inst2 = db.instance_create(self.context, inst2_kwargs)

        inst3_kwargs = {}
        inst3_kwargs.update(inst_base)
        inst3_kwargs['host'] = 'host3'
        inst3_kwargs['hostname'] = 'server-3333'
        inst3_kwargs['created_at'] = datetime.datetime(2012, 2, 5, 1, 1, 1)
        inst3 = db.instance_create(self.context, inst3_kwargs)

        comp1 = db.service_create(self.context, {'host': 'host1',
                                                 'topic': "compute"})

        comp2 = db.service_create(self.context, {'host': 'host2',
                                                 'topic': "compute"})

        result = self.cloud.describe_instances(self.context)
        result = result['reservationSet'][0]['instancesSet']
        self.assertEqual(result[0]['launchTime'], inst2_kwargs['created_at'])
        self.assertEqual(result[1]['launchTime'], inst3_kwargs['created_at'])
        self.assertEqual(result[2]['launchTime'], inst1_kwargs['created_at'])

        db.instance_destroy(self.context, inst1['uuid'])
        db.instance_destroy(self.context, inst2['uuid'])
        db.instance_destroy(self.context, inst3['uuid'])
        db.service_destroy(self.context, comp1['id'])
        db.service_destroy(self.context, comp2['id'])

    def test_describe_instance_state(self):
        # Makes sure describe_instances for instanceState works.

        def test_instance_state(expected_code, expected_name,
                                power_state_, vm_state_, values=None):
            image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
            sys_meta = flavors.save_instance_type_info(
                {}, flavors.get_instance_type(1))
            values = values or {}
            values.update({'image_ref': image_uuid, 'instance_type_id': 1,
                           'power_state': power_state_, 'vm_state': vm_state_,
                           'system_metadata': sys_meta})
            inst = db.instance_create(self.context, values)

            instance_id = ec2utils.id_to_ec2_inst_id(inst['uuid'])
            result = self.cloud.describe_instances(self.context,
                                                 instance_id=[instance_id])
            result = result['reservationSet'][0]
            result = result['instancesSet'][0]['instanceState']

            name = result['name']
            code = result['code']
            self.assertEqual(code, expected_code)
            self.assertEqual(name, expected_name)

            db.instance_destroy(self.context, inst['uuid'])

        test_instance_state(inst_state.RUNNING_CODE, inst_state.RUNNING,
                            power_state.RUNNING, vm_states.ACTIVE)
        test_instance_state(inst_state.STOPPED_CODE, inst_state.STOPPED,
                            power_state.NOSTATE, vm_states.STOPPED,
                            {'shutdown_terminate': False})

    def test_describe_instances_no_ipv6(self):
        # Makes sure describe_instances w/ no ipv6 works.
        self.flags(use_ipv6=False)

        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        sys_meta = flavors.save_instance_type_info(
            {}, flavors.get_instance_type(1))
        inst1 = db.instance_create(self.context, {'reservation_id': 'a',
                                                  'image_ref': image_uuid,
                                                  'instance_type_id': 1,
                                                  'hostname': 'server-1234',
                                                  'vm_state': 'active',
                                                  'system_metadata': sys_meta})
        comp1 = db.service_create(self.context, {'host': 'host1',
                                                 'topic': "compute"})
        result = self.cloud.describe_instances(self.context)
        result = result['reservationSet'][0]
        self.assertEqual(len(result['instancesSet']), 1)
        instance = result['instancesSet'][0]
        instance_id = ec2utils.id_to_ec2_inst_id(inst1['uuid'])
        self.assertEqual(instance['instanceId'], instance_id)
        self.assertEqual(instance['publicDnsName'], '1.2.3.4')
        self.assertEqual(instance['ipAddress'], '1.2.3.4')
        self.assertEqual(instance['dnsName'], '1.2.3.4')
        self.assertEqual(instance['privateDnsName'], 'server-1234')
        self.assertEqual(instance['privateIpAddress'], '192.168.0.3')
        self.assertNotIn('dnsNameV6', instance)
        db.instance_destroy(self.context, inst1['uuid'])
        db.service_destroy(self.context, comp1['id'])

    def test_describe_instances_deleted(self):
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        sys_meta = flavors.save_instance_type_info(
            {}, flavors.get_instance_type(1))
        args1 = {'reservation_id': 'a',
                 'image_ref': image_uuid,
                 'instance_type_id': 1,
                 'host': 'host1',
                 'vm_state': 'active',
                 'system_metadata': sys_meta}
        inst1 = db.instance_create(self.context, args1)
        args2 = {'reservation_id': 'b',
                 'image_ref': image_uuid,
                 'instance_type_id': 1,
                 'host': 'host1',
                 'vm_state': 'active',
                 'system_metadata': sys_meta}
        inst2 = db.instance_create(self.context, args2)
        db.instance_destroy(self.context, inst1['uuid'])
        result = self.cloud.describe_instances(self.context)
        self.assertEqual(len(result['reservationSet']), 1)
        result1 = result['reservationSet'][0]['instancesSet']
        self.assertEqual(result1[0]['instanceId'],
                         ec2utils.id_to_ec2_inst_id(inst2['uuid']))

    def test_describe_instances_with_image_deleted(self):
        image_uuid = 'aebef54a-ed67-4d10-912f-14455edce176'
        sys_meta = flavors.save_instance_type_info(
            {}, flavors.get_instance_type(1))
        args1 = {'reservation_id': 'a',
                 'image_ref': image_uuid,
                 'instance_type_id': 1,
                 'host': 'host1',
                 'vm_state': 'active',
                 'system_metadata': sys_meta}
        inst1 = db.instance_create(self.context, args1)
        args2 = {'reservation_id': 'b',
                 'image_ref': image_uuid,
                 'instance_type_id': 1,
                 'host': 'host1',
                 'vm_state': 'active',
                 'system_metadata': sys_meta}
        inst2 = db.instance_create(self.context, args2)
        result = self.cloud.describe_instances(self.context)
        self.assertEqual(len(result['reservationSet']), 2)

    def test_describe_images(self):
        describe_images = self.cloud.describe_images

        def fake_detail(meh, context, **kwargs):
            return [{'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                     'name': 'fake_name',
                     'container_format': 'ami',
                     'status': 'active',
                     'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'type': 'machine'}}]

        def fake_show_none(meh, context, id):
            raise exception.ImageNotFound(image_id='bad_image_id')

        def fake_detail_none(self, context, **kwargs):
            return []

        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail)
        # list all
        result1 = describe_images(self.context)
        result1 = result1['imagesSet'][0]
        self.assertEqual(result1['imageId'], 'ami-00000001')
        # provided a valid image_id
        result2 = describe_images(self.context, ['ami-00000001'])
        self.assertEqual(1, len(result2['imagesSet']))
        # provide more than 1 valid image_id
        result3 = describe_images(self.context, ['ami-00000001',
                                                 'ami-00000002'])
        self.assertEqual(2, len(result3['imagesSet']))
        # provide a non-existing image_id
        self.stubs.UnsetAll()
        self.stubs.Set(fake._FakeImageService, 'show', fake_show_none)
        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail_none)
        self.assertRaises(exception.ImageNotFound, describe_images,
                          self.context, ['ami-fake'])

    def assertDictListUnorderedMatch(self, L1, L2, key):
        self.assertEqual(len(L1), len(L2))
        for d1 in L1:
            self.assertTrue(key in d1)
            for d2 in L2:
                self.assertTrue(key in d2)
                if d1[key] == d2[key]:
                    self.assertThat(d1, matchers.DictMatches(d2))

    def _setUpImageSet(self, create_volumes_and_snapshots=False):
        mappings1 = [
            {'device': '/dev/sda1', 'virtual': 'root'},

            {'device': 'sdb0', 'virtual': 'ephemeral0'},
            {'device': 'sdb1', 'virtual': 'ephemeral1'},
            {'device': 'sdb2', 'virtual': 'ephemeral2'},
            {'device': 'sdb3', 'virtual': 'ephemeral3'},
            {'device': 'sdb4', 'virtual': 'ephemeral4'},

            {'device': 'sdc0', 'virtual': 'swap'},
            {'device': 'sdc1', 'virtual': 'swap'},
            {'device': 'sdc2', 'virtual': 'swap'},
            {'device': 'sdc3', 'virtual': 'swap'},
            {'device': 'sdc4', 'virtual': 'swap'}]
        block_device_mapping1 = [
            {'device_name': '/dev/sdb1',
             'snapshot_id': 'ccec42a2-c220-4806-b762-6b12fbb592e3'},
            {'device_name': '/dev/sdb2',
             'volume_id': 'ccec42a2-c220-4806-b762-6b12fbb592e4'},
            {'device_name': '/dev/sdb3', 'virtual_name': 'ephemeral5'},
            {'device_name': '/dev/sdb4', 'no_device': True},

            {'device_name': '/dev/sdc1',
             'snapshot_id': 'ccec42a2-c220-4806-b762-6b12fbb592e5'},
            {'device_name': '/dev/sdc2',
             'volume_id': 'ccec42a2-c220-4806-b762-6b12fbb592e6'},
            {'device_name': '/dev/sdc3', 'virtual_name': 'ephemeral6'},
            {'device_name': '/dev/sdc4', 'no_device': True}]
        image1 = {
            'id': 'cedef40a-ed67-4d10-800e-17455edce175',
            'name': 'fake_name',
            'status': 'active',
            'properties': {
                'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                'type': 'machine',
                'image_state': 'available',
                'mappings': mappings1,
                'block_device_mapping': block_device_mapping1,
                }
            }

        mappings2 = [{'device': '/dev/sda1', 'virtual': 'root'}]
        block_device_mapping2 = [{'device_name': '/dev/sdb1',
                'snapshot_id': 'ccec42a2-c220-4806-b762-6b12fbb592e7'}]
        image2 = {
            'id': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
            'name': 'fake_name',
            'status': 'active',
            'properties': {
                'kernel_id': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                'type': 'machine',
                'root_device_name': '/dev/sdb1',
                'mappings': mappings2,
                'block_device_mapping': block_device_mapping2}}

        def fake_show(meh, context, image_id):
            _images = [copy.deepcopy(image1), copy.deepcopy(image2)]
            for i in _images:
                if str(i['id']) == str(image_id):
                    return i
            raise exception.ImageNotFound(image_id=image_id)

        def fake_detail(meh, context, **kwargs):
            return [copy.deepcopy(image1), copy.deepcopy(image2)]

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail)

        volumes = []
        snapshots = []
        if create_volumes_and_snapshots:
            for bdm in block_device_mapping1:
                if 'volume_id' in bdm:
                    vol = self._volume_create(bdm['volume_id'])
                    volumes.append(vol['id'])
                if 'snapshot_id' in bdm:
                    snap = self._snapshot_create(bdm['snapshot_id'])
                    snapshots.append(snap['id'])
        return (volumes, snapshots)

    def _assertImageSet(self, result, root_device_type, root_device_name):
        self.assertEqual(1, len(result['imagesSet']))
        result = result['imagesSet'][0]
        self.assertTrue('rootDeviceType' in result)
        self.assertEqual(result['rootDeviceType'], root_device_type)
        self.assertTrue('rootDeviceName' in result)
        self.assertEqual(result['rootDeviceName'], root_device_name)
        self.assertTrue('blockDeviceMapping' in result)

        return result

    _expected_root_device_name1 = '/dev/sda1'
    # NOTE(yamahata): noDevice doesn't make sense when returning mapping
    #                 It makes sense only when user overriding existing
    #                 mapping.
    _expected_bdms1 = [
        {'deviceName': '/dev/sdb0', 'virtualName': 'ephemeral0'},
        {'deviceName': '/dev/sdb1', 'ebs': {'snapshotId':
                                            'snap-00000001'}},
        {'deviceName': '/dev/sdb2', 'ebs': {'snapshotId':
                                            'vol-00000001'}},
        {'deviceName': '/dev/sdb3', 'virtualName': 'ephemeral5'},
        # {'deviceName': '/dev/sdb4', 'noDevice': True},

        {'deviceName': '/dev/sdc0', 'virtualName': 'swap'},
        {'deviceName': '/dev/sdc1', 'ebs': {'snapshotId':
                                            'snap-00000002'}},
        {'deviceName': '/dev/sdc2', 'ebs': {'snapshotId':
                                            'vol-00000002'}},
        {'deviceName': '/dev/sdc3', 'virtualName': 'ephemeral6'},
        # {'deviceName': '/dev/sdc4', 'noDevice': True}
        ]

    _expected_root_device_name2 = '/dev/sdb1'
    _expected_bdms2 = [{'deviceName': '/dev/sdb1',
                       'ebs': {'snapshotId': 'snap-00000003'}}]

    # NOTE(yamahata):
    # InstanceBlockDeviceMappingItemType
    # rootDeviceType
    # rootDeviceName
    # blockDeviceMapping
    #  deviceName
    #  virtualName
    #  ebs
    #    snapshotId
    #    volumeSize
    #    deleteOnTermination
    #  noDevice
    def test_describe_image_mapping(self):
        # test for rootDeviceName and blockDeviceMapping.
        describe_images = self.cloud.describe_images
        self._setUpImageSet()

        result = describe_images(self.context, ['ami-00000001'])
        result = self._assertImageSet(result, 'instance-store',
                                      self._expected_root_device_name1)

        self.assertDictListUnorderedMatch(result['blockDeviceMapping'],
                                          self._expected_bdms1, 'deviceName')

        result = describe_images(self.context, ['ami-00000002'])
        result = self._assertImageSet(result, 'ebs',
                                      self._expected_root_device_name2)

        self.assertDictListUnorderedMatch(result['blockDeviceMapping'],
                                          self._expected_bdms2, 'deviceName')

    def test_describe_image_attribute(self):
        describe_image_attribute = self.cloud.describe_image_attribute

        def fake_show(meh, context, id):
            return {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'name': 'fake_name',
                    'status': 'active',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'type': 'machine'},
                    'container_format': 'ami',
                    'is_public': True}

        def fake_detail(self, context, **kwargs):
            image = fake_show(None, context, None)
            image['name'] = kwargs.get('filters', {}).get('name')
            return [image]

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail)
        result = describe_image_attribute(self.context, 'ami-00000001',
                                          'launchPermission')
        self.assertEqual([{'group': 'all'}], result['launchPermission'])
        result = describe_image_attribute(self.context, 'ami-00000001',
                                          'kernel')
        self.assertEqual('aki-00000001', result['kernel']['value'])
        result = describe_image_attribute(self.context, 'ami-00000001',
                                          'ramdisk')
        self.assertEqual('ari-00000001', result['ramdisk']['value'])

    def test_describe_image_attribute_root_device_name(self):
        describe_image_attribute = self.cloud.describe_image_attribute
        self._setUpImageSet()

        result = describe_image_attribute(self.context, 'ami-00000001',
                                          'rootDeviceName')
        self.assertEqual(result['rootDeviceName'],
                         self._expected_root_device_name1)
        result = describe_image_attribute(self.context, 'ami-00000002',
                                          'rootDeviceName')
        self.assertEqual(result['rootDeviceName'],
                         self._expected_root_device_name2)

    def test_describe_image_attribute_block_device_mapping(self):
        describe_image_attribute = self.cloud.describe_image_attribute
        self._setUpImageSet()

        result = describe_image_attribute(self.context, 'ami-00000001',
                                          'blockDeviceMapping')
        self.assertDictListUnorderedMatch(result['blockDeviceMapping'],
                                          self._expected_bdms1, 'deviceName')
        result = describe_image_attribute(self.context, 'ami-00000002',
                                          'blockDeviceMapping')
        self.assertDictListUnorderedMatch(result['blockDeviceMapping'],
                                          self._expected_bdms2, 'deviceName')

    def test_modify_image_attribute(self):
        modify_image_attribute = self.cloud.modify_image_attribute

        fake_metadata = {
            'id': 'cedef40a-ed67-4d10-800e-17455edce175',
            'name': 'fake_name',
            'container_format': 'ami',
            'status': 'active',
            'properties': {
                'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                'type': 'machine'},
            'is_public': False}

        def fake_show(meh, context, id):
            return copy.deepcopy(fake_metadata)

        def fake_detail(self, context, **kwargs):
            image = fake_show(None, context, None)
            image['name'] = kwargs.get('filters', {}).get('name')
            return [image]

        def fake_update(meh, context, image_id, metadata, data=None):
            self.assertEqual(metadata['properties']['kernel_id'],
                             fake_metadata['properties']['kernel_id'])
            self.assertEqual(metadata['properties']['ramdisk_id'],
                             fake_metadata['properties']['ramdisk_id'])
            self.assertTrue(metadata['is_public'])
            image = copy.deepcopy(fake_metadata)
            image.update(metadata)
            return image

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail)
        self.stubs.Set(fake._FakeImageService, 'update', fake_update)
        result = modify_image_attribute(self.context, 'ami-00000001',
                                          'launchPermission', 'add',
                                           user_group=['all'])
        self.assertTrue(result['is_public'])

    def test_register_image(self):
        register_image = self.cloud.register_image

        def fake_create(*args, **kwargs):
            # NOTE(vish): We are mocking s3 so make sure we have converted
            #             to ids instead of uuids.
            return {'id': 1,
                    'name': 'fake_name',
                    'container_format': 'ami',
                    'properties': {'kernel_id': 1,
                                   'ramdisk_id': 1,
                                   'type': 'machine'
                                   },
                    'is_public': False
                    }

        self.stubs.Set(s3.S3ImageService, 'create', fake_create)
        image_location = 'fake_bucket/fake.img.manifest.xml'
        result = register_image(self.context, image_location)
        self.assertEqual(result['imageId'], 'ami-00000001')

    def test_register_image_empty(self):
        register_image = self.cloud.register_image
        self.assertRaises(exception.EC2APIError, register_image, self.context,
                          image_location=None)

    def test_register_image_name(self):
        register_image = self.cloud.register_image

        def fake_create(_self, context, metadata, data=None):
            self.assertEqual(metadata['name'], self.expected_name)
            metadata['id'] = 1
            metadata['container_format'] = 'ami'
            metadata['is_public'] = False
            return metadata

        self.stubs.Set(s3.S3ImageService, 'create', fake_create)
        self.expected_name = 'fake_bucket/fake.img.manifest.xml'
        result = register_image(self.context,
                                image_location=self.expected_name,
                                name=None)
        self.expected_name = 'an image name'
        result = register_image(self.context,
                                image_location='some_location',
                                name=self.expected_name)

    def test_format_image(self):
        image = {
            'id': 1,
            'container_format': 'ami',
            'name': 'name',
            'owner': 'someone',
            'properties': {
                'image_location': 'location',
                'kernel_id': 1,
                'ramdisk_id': 1,
                'type': 'machine'},
            'is_public': False}
        expected = {'name': 'name',
                    'imageOwnerId': 'someone',
                    'isPublic': False,
                    'imageId': 'ami-00000001',
                    'imageState': None,
                    'rootDeviceType': 'instance-store',
                    'architecture': None,
                    'imageLocation': 'location',
                    'kernelId': 'aki-00000001',
                    'ramdiskId': 'ari-00000001',
                    'rootDeviceName': '/dev/sda1',
                    'imageType': 'machine',
                    'description': None}
        result = self.cloud._format_image(image)
        self.assertThat(result, matchers.DictMatches(expected))
        image['properties']['image_location'] = None
        expected['imageLocation'] = 'None (name)'
        result = self.cloud._format_image(image)
        self.assertThat(result, matchers.DictMatches(expected))
        image['name'] = None
        image['properties']['image_location'] = 'location'
        expected['imageLocation'] = 'location'
        expected['name'] = 'location'
        result = self.cloud._format_image(image)
        self.assertThat(result, matchers.DictMatches(expected))

    def test_deregister_image(self):
        deregister_image = self.cloud.deregister_image

        def fake_delete(self, context, id):
            return None

        self.stubs.Set(fake._FakeImageService, 'delete', fake_delete)
        # valid image
        result = deregister_image(self.context, 'ami-00000001')
        self.assertTrue(result)
        # invalid image
        self.stubs.UnsetAll()

        def fake_detail_empty(self, context, **kwargs):
            return []

        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail_empty)
        self.assertRaises(exception.ImageNotFound, deregister_image,
                          self.context, 'ami-bad001')

    def test_deregister_image_wrong_container_type(self):
        deregister_image = self.cloud.deregister_image

        def fake_delete(self, context, id):
            return None

        self.stubs.Set(fake._FakeImageService, 'delete', fake_delete)
        self.assertRaises(exception.NotFound, deregister_image, self.context,
                          'aki-00000001')

    def _run_instance(self, **kwargs):
        rv = self.cloud.run_instances(self.context, **kwargs)
        instance_id = rv['instancesSet'][0]['instanceId']
        return instance_id

    def test_get_password_data(self):
        instance_id = self._run_instance(
            image_id='ami-1',
            instance_type=CONF.default_instance_type,
            max_count=1)
        self.stubs.Set(password, 'extract_password', lambda i: 'fakepass')
        output = self.cloud.get_password_data(context=self.context,
                                              instance_id=[instance_id])
        self.assertEquals(output['passwordData'], 'fakepass')
        rv = self.cloud.terminate_instances(self.context, [instance_id])

    def test_console_output(self):
        instance_id = self._run_instance(
            image_id='ami-1',
            instance_type=CONF.default_instance_type,
            max_count=1)
        output = self.cloud.get_console_output(context=self.context,
                                               instance_id=[instance_id])
        self.assertEquals(base64.b64decode(output['output']),
                'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE')
        # TODO(soren): We need this until we can stop polling in the rpc code
        #              for unit tests.
        rv = self.cloud.terminate_instances(self.context, [instance_id])

    def test_key_generation(self):
        result = self._create_key('test')
        private_key = result['private_key']

        expected = db.key_pair_get(self.context,
                                    self.context.user_id,
                                    'test')['public_key']

        (fd, fname) = tempfile.mkstemp()
        os.write(fd, private_key)

        public_key, err = utils.execute('ssh-keygen', '-e', '-f', fname)

        os.unlink(fname)

        # assert key fields are equal
        self.assertEqual(''.join(public_key.split("\n")[2:-2]),
                         expected.split(" ")[1].strip())

    def test_describe_key_pairs(self):
        self._create_key('test1')
        self._create_key('test2')
        result = self.cloud.describe_key_pairs(self.context)
        keys = result["keySet"]
        self.assertTrue(filter(lambda k: k['keyName'] == 'test1', keys))
        self.assertTrue(filter(lambda k: k['keyName'] == 'test2', keys))

    def test_describe_bad_key_pairs(self):
        self.assertRaises(exception.KeypairNotFound,
            self.cloud.describe_key_pairs, self.context,
            key_name=['DoesNotExist'])

    def test_import_key_pair(self):
        pubkey_path = os.path.join(os.path.dirname(__file__), 'public_key')
        f = open(pubkey_path + '/dummy.pub', 'r')
        dummypub = f.readline().rstrip()
        f.close
        f = open(pubkey_path + '/dummy.fingerprint', 'r')
        dummyfprint = f.readline().rstrip()
        f.close
        key_name = 'testimportkey'
        public_key_material = base64.b64encode(dummypub)
        result = self.cloud.import_key_pair(self.context,
                                            key_name,
                                            public_key_material)
        self.assertEqual(result['keyName'], key_name)
        self.assertEqual(result['keyFingerprint'], dummyfprint)
        keydata = db.key_pair_get(self.context,
                                  self.context.user_id,
                                  key_name)
        self.assertEqual(dummypub, keydata['public_key'])
        self.assertEqual(dummyfprint, keydata['fingerprint'])

    def test_import_key_pair_quota_limit(self):
        self.flags(quota_key_pairs=0)
        pubkey_path = os.path.join(os.path.dirname(__file__), 'public_key')
        f = open(pubkey_path + '/dummy.pub', 'r')
        dummypub = f.readline().rstrip()
        f.close
        f = open(pubkey_path + '/dummy.fingerprint', 'r')
        dummyfprint = f.readline().rstrip()
        f.close
        key_name = 'testimportkey'
        public_key_material = base64.b64encode(dummypub)
        self.assertRaises(exception.EC2APIError,
            self.cloud.import_key_pair, self.context, key_name,
            public_key_material)

    def test_create_key_pair(self):
        good_names = ('a', 'a' * 255, string.ascii_letters + ' -_')
        bad_names = ('', 'a' * 256, '*', '/')

        for key_name in good_names:
            result = self.cloud.create_key_pair(self.context,
                                                key_name)
            self.assertEqual(result['keyName'], key_name)

        for key_name in bad_names:
            self.assertRaises(exception.InvalidKeypair,
                              self.cloud.create_key_pair,
                              self.context,
                              key_name)

    def test_create_key_pair_quota_limit(self):
        self.flags(quota_key_pairs=10)
        for i in range(0, 10):
            key_name = 'key_%i' % i
            result = self.cloud.create_key_pair(self.context,
                                                key_name)
            self.assertEqual(result['keyName'], key_name)

        # 11'th group should fail
        self.assertRaises(exception.EC2APIError,
                          self.cloud.create_key_pair,
                          self.context,
                          'foo')

    def test_delete_key_pair(self):
        self._create_key('test')
        self.cloud.delete_key_pair(self.context, 'test')

    def test_run_instances(self):
        kwargs = {'image_id': 'ami-00000001',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show(self, context, id):
            return {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'name': 'fake_name',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'type': 'machine'},
                    'container_format': 'ami',
                    'status': 'active'}

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)

        def dumb(*args, **kwargs):
            pass

        self.stubs.Set(compute_utils, 'notify_about_instance_usage', dumb)
        # NOTE(comstud): Make 'cast' behave like a 'call' which will
        # ensure that operations complete
        self.stubs.Set(rpc, 'cast', rpc.call)

        result = run_instances(self.context, **kwargs)
        instance = result['instancesSet'][0]
        self.assertEqual(instance['imageId'], 'ami-00000001')
        self.assertEqual(instance['instanceId'], 'i-00000001')
        self.assertEqual(instance['instanceState']['name'], 'running')
        self.assertEqual(instance['instanceType'], 'm1.small')

    def test_run_instances_availability_zone(self):
        kwargs = {'image_id': 'ami-00000001',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1,
                  'placement': {'availability_zone': 'fake'},
                 }
        run_instances = self.cloud.run_instances

        def fake_show(self, context, id):
            return {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'name': 'fake_name',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'type': 'machine'},
                    'container_format': 'ami',
                    'status': 'active'}

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        # NOTE(comstud): Make 'cast' behave like a 'call' which will
        # ensure that operations complete
        self.stubs.Set(rpc, 'cast', rpc.call)

        def fake_format(*args, **kwargs):
            pass

        self.stubs.Set(self.cloud, '_format_run_instances', fake_format)

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['availability_zone'], 'fake')
            return ({'id': 'fake-instance'}, 'fake-res-id')

        self.stubs.Set(self.cloud.compute_api, 'create', fake_create)

        # NOTE(vish) the assert for this call is in the fake_create method.
        run_instances(self.context, **kwargs)

    def test_run_instances_image_state_none(self):
        kwargs = {'image_id': 'ami-00000001',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_no_state(self, context, id):
            return {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'name': 'fake_name',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'type': 'machine'}, 'container_format': 'ami'}

        self.stubs.UnsetAll()
        self.stubs.Set(fake._FakeImageService, 'show', fake_show_no_state)
        self.assertRaises(exception.EC2APIError, run_instances,
                          self.context, **kwargs)

    def test_run_instances_image_state_invalid(self):
        kwargs = {'image_id': 'ami-00000001',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_decrypt(self, context, id):
            return {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'name': 'fake_name',
                    'container_format': 'ami',
                    'status': 'active',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'type': 'machine', 'image_state': 'decrypting'}}

        self.stubs.UnsetAll()
        self.stubs.Set(fake._FakeImageService, 'show', fake_show_decrypt)
        self.assertRaises(exception.EC2APIError, run_instances,
                          self.context, **kwargs)

    def test_run_instances_image_status_active(self):
        kwargs = {'image_id': 'ami-00000001',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_stat_active(self, context, id):
            return {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                    'name': 'fake_name',
                    'container_format': 'ami',
                    'status': 'active',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'type': 'machine'},
                    'status': 'active'}

        def fake_id_to_glance_id(context, id):
            return 'cedef40a-ed67-4d10-800e-17455edce175'

        self.stubs.Set(fake._FakeImageService, 'show', fake_show_stat_active)
        self.stubs.Set(ec2utils, 'id_to_glance_id', fake_id_to_glance_id)

        result = run_instances(self.context, **kwargs)
        self.assertEqual(len(result['instancesSet']), 1)

    def _restart_compute_service(self, periodic_interval_max=None):
        """restart compute service. NOTE: fake driver forgets all instances."""
        self.compute.kill()
        if periodic_interval_max:
            self.compute = self.start_service(
                'compute', periodic_interval_max=periodic_interval_max)
        else:
            self.compute = self.start_service('compute')

    def test_stop_start_instance(self):
        # Makes sure stop/start instance works.
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval_max=0.3)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance(**kwargs)

        # a running instance can't be started.
        self.assertRaises(exception.InstanceInvalidState,
                          self.cloud.start_instances,
                          self.context, [instance_id])

        result = self.cloud.stop_instances(self.context, [instance_id])
        self.assertTrue(result)

        result = self.cloud.start_instances(self.context, [instance_id])
        self.assertTrue(result)

        result = self.cloud.stop_instances(self.context, [instance_id])
        self.assertTrue(result)

        expected = {'instancesSet': [
                        {'instanceId': 'i-00000001',
                         'previousState': {'code': 80,
                                           'name': 'stopped'},
                         'currentState': {'code': 48,
                                           'name': 'terminated'}}]}
        result = self.cloud.terminate_instances(self.context, [instance_id])
        self.assertEqual(result, expected)

    def test_start_instances(self):
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance(**kwargs)

        result = self.cloud.stop_instances(self.context, [instance_id])
        self.assertTrue(result)

        result = self.cloud.start_instances(self.context, [instance_id])
        self.assertTrue(result)

        expected = {'instancesSet': [
                        {'instanceId': 'i-00000001',
                         'previousState': {'code': 16,
                                           'name': 'running'},
                         'currentState': {'code': 48,
                                           'name': 'terminated'}}]}
        result = self.cloud.terminate_instances(self.context, [instance_id])
        self.assertEqual(result, expected)
        self._restart_compute_service()

    def test_stop_instances(self):
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance(**kwargs)

        result = self.cloud.stop_instances(self.context, [instance_id])
        self.assertTrue(result)

        expected = {'instancesSet': [
                        {'instanceId': 'i-00000001',
                         'previousState': {'code': 80,
                                           'name': 'stopped'},
                         'currentState': {'code': 48,
                                           'name': 'terminated'}}]}
        result = self.cloud.terminate_instances(self.context, [instance_id])
        self.assertEqual(result, expected)
        self._restart_compute_service()

    def test_terminate_instances(self):
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance(**kwargs)

        # a running instance can't be started.
        self.assertRaises(exception.InstanceInvalidState,
                          self.cloud.start_instances,
                          self.context, [instance_id])

        expected = {'instancesSet': [
                        {'instanceId': 'i-00000001',
                         'previousState': {'code': 16,
                                           'name': 'running'},
                         'currentState': {'code': 48,
                                           'name': 'terminated'}}]}
        result = self.cloud.terminate_instances(self.context, [instance_id])
        self.assertEqual(result, expected)
        self._restart_compute_service()

    def test_terminate_instances_invalid_instance_id(self):
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance(**kwargs)

        self.assertRaises(exception.InstanceNotFound,
                          self.cloud.terminate_instances,
                          self.context, ['i-2'])
        self._restart_compute_service()

    def test_terminate_instances_disable_terminate(self):
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance(**kwargs)

        internal_uuid = db.get_instance_uuid_by_ec2_id(self.context,
                    ec2utils.ec2_id_to_id(instance_id))
        instance = db.instance_update(self.context, internal_uuid,
                                      {'disable_terminate': True})

        expected = {'instancesSet': [
                        {'instanceId': 'i-00000001',
                         'previousState': {'code': 16,
                                           'name': 'running'},
                         'currentState': {'code': 16,
                                           'name': 'running'}}]}
        result = self.cloud.terminate_instances(self.context, [instance_id])
        self.assertEqual(result, expected)

        instance = db.instance_update(self.context, internal_uuid,
                                      {'disable_terminate': False})

        expected = {'instancesSet': [
                        {'instanceId': 'i-00000001',
                         'previousState': {'code': 16,
                                           'name': 'running'},
                         'currentState': {'code': 48,
                                           'name': 'terminated'}}]}
        result = self.cloud.terminate_instances(self.context, [instance_id])
        self.assertEqual(result, expected)
        self._restart_compute_service()

    def test_terminate_instances_two_instances(self):
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        inst1 = self._run_instance(**kwargs)
        inst2 = self._run_instance(**kwargs)

        result = self.cloud.stop_instances(self.context, [inst1])
        self.assertTrue(result)

        expected = {'instancesSet': [
                        {'instanceId': 'i-00000001',
                         'previousState': {'code': 80,
                                           'name': 'stopped'},
                         'currentState': {'code': 48,
                                           'name': 'terminated'}},
                        {'instanceId': 'i-00000002',
                         'previousState': {'code': 16,
                                           'name': 'running'},
                         'currentState': {'code': 48,
                                           'name': 'terminated'}}]}
        result = self.cloud.terminate_instances(self.context, [inst1, inst2])
        self.assertEqual(result, expected)
        self._restart_compute_service()

    def test_reboot_instances(self):
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance(**kwargs)

        # a running instance can't be started.
        self.assertRaises(exception.InstanceInvalidState,
                          self.cloud.start_instances,
                          self.context, [instance_id])

        result = self.cloud.reboot_instances(self.context, [instance_id])
        self.assertTrue(result)

    def _volume_create(self, volume_id=None):
        kwargs = {'name': 'test-volume',
                  'description': 'test volume description',
                  'status': 'available',
                  'host': 'fake',
                  'size': 1,
                  'attach_status': 'detached'}
        if volume_id:
            kwargs['volume_id'] = volume_id
        return self.volume_api.create_with_kwargs(self.context, **kwargs)

    def _snapshot_create(self, snapshot_id=None):
        kwargs = {'volume_id': 'ccec42a2-c220-4806-b762-6b12fbb592e4',
                  'status': "available",
                  'volume_size': 1}
        if snapshot_id:
            kwargs['snap_id'] = snapshot_id
        return self.volume_api.create_snapshot_with_kwargs(self.context,
                                                           **kwargs)

    def _create_snapshot(self, ec2_volume_id):
        result = self.cloud.create_snapshot(self.context,
                                            volume_id=ec2_volume_id)
        return result['snapshotId']

    def _do_test_create_image(self, no_reboot):
        """Make sure that CreateImage works."""
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval_max=0.3)

        (volumes, snapshots) = self._setUpImageSet(
            create_volumes_and_snapshots=True)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1}
        ec2_instance_id = self._run_instance(**kwargs)

        def fake_show(meh, context, id):
            bdm = [dict(snapshot_id=snapshots[0],
                        volume_size=1,
                        device_name='sda1',
                        delete_on_termination=False)]
            props = dict(kernel_id='cedef40a-ed67-4d10-800e-17455edce175',
                         ramdisk_id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                         root_device_name='/dev/sda1',
                         block_device_mapping=bdm)
            return dict(id=id,
                        properties=props,
                        container_format='ami',
                        status='active',
                        is_public=True)

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)

        def fake_block_device_mapping_get_all_by_instance(context, inst_id):
            return [dict(id=1,
                         source_type='snapshot',
                         destination_type='volume',
                         snapshot_id=snapshots[0],
                         volume_id=volumes[0],
                         volume_size=1,
                         device_name='sda1',
                         delete_on_termination=False,
                         no_device=None,
                         connection_info='{"foo":"bar"}')]

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_block_device_mapping_get_all_by_instance)

        virt_driver = {}

        def fake_power_on(self, instance):
            virt_driver['powered_on'] = True

        self.stubs.Set(fake_virt.FakeDriver, 'power_on', fake_power_on)

        def fake_power_off(self, instance):
            virt_driver['powered_off'] = True

        self.stubs.Set(fake_virt.FakeDriver, 'power_off', fake_power_off)

        result = self.cloud.create_image(self.context, ec2_instance_id,
                                         no_reboot=no_reboot)
        ec2_ids = [result['imageId']]
        created_image = self.cloud.describe_images(self.context,
                                                   ec2_ids)['imagesSet'][0]

        self.assertTrue('blockDeviceMapping' in created_image)
        bdm = created_image['blockDeviceMapping'][0]
        self.assertEquals(bdm.get('deviceName'), 'sda1')
        self.assertTrue('ebs' in bdm)
        self.assertEquals(bdm['ebs'].get('snapshotId'),
                          ec2utils.id_to_ec2_snap_id(snapshots[0]))
        self.assertEquals(created_image.get('kernelId'), 'aki-00000001')
        self.assertEquals(created_image.get('ramdiskId'), 'ari-00000002')
        self.assertEquals(created_image.get('rootDeviceType'), 'ebs')
        self.assertNotEqual(virt_driver.get('powered_on'), no_reboot)
        self.assertNotEqual(virt_driver.get('powered_off'), no_reboot)

        self.cloud.terminate_instances(self.context, [ec2_instance_id])

        self._restart_compute_service()

    def test_create_image_no_reboot(self):
        # Make sure that CreateImage works.
        self._do_test_create_image(True)

    def test_create_image_with_reboot(self):
        # Make sure that CreateImage works.
        self._do_test_create_image(False)

    def test_create_image_instance_store(self):
        """
        Ensure CreateImage fails as expected for an instance-store-backed
        instance
        """
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval_max=0.3)

        (volumes, snapshots) = self._setUpImageSet(
            create_volumes_and_snapshots=True)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_instance_type,
                  'max_count': 1}
        ec2_instance_id = self._run_instance(**kwargs)

        def fake_block_device_mapping_get_all_by_instance(context, inst_id):
            return [dict(snapshot_id=snapshots[0],
                         volume_id=volumes[0],
                         virtual_name=None,
                         volume_size=1,
                         device_name='vda',
                         delete_on_termination=False,
                         no_device=None)]

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_block_device_mapping_get_all_by_instance)

        self.assertRaises(exception.InvalidParameterValue,
                          self.cloud.create_image,
                          self.context,
                          ec2_instance_id,
                          no_reboot=True)

    @staticmethod
    def _fake_bdm_get(ctxt, id):
            return [{'volume_id': 87654321,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'snapshot_id': None,
                     'no_device': None,
                     'delete_on_termination': True,
                     'device_name': '/dev/sdh'},
                    {'volume_id': None,
                     'snapshot_id': 98765432,
                     'source_type': 'snapshot',
                     'destination_type': 'volume',
                     'no_device': None,
                     'delete_on_termination': True,
                     'device_name': '/dev/sdi'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': True,
                     'delete_on_termination': None,
                     'device_name': None},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': None,
                     'delete_on_termination': None,
                     'device_name': '/dev/sdb'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': 'swap',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdc'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': None,
                     'delete_on_termination': None,
                     'device_name': '/dev/sdd'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': None,
                     'delete_on_termination': None,
                     'device_name': '/dev/sd3'},
                    ]

    def test_describe_instance_attribute(self):
        # Make sure that describe_instance_attribute works.
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       self._fake_bdm_get)

        def fake_get(ctxt, instance_id):
            inst_type = flavors.get_default_instance_type()
            inst_type['name'] = 'fake_type'
            sys_meta = flavors.save_instance_type_info({}, inst_type)
            sys_meta = utils.dict_to_metadata(sys_meta)
            return {
                'id': 0,
                'uuid': 'e5fe5518-0288-4fa3-b0c4-c79764101b85',
                'root_device_name': '/dev/sdh',
                'security_groups': [{'name': 'fake0'}, {'name': 'fake1'}],
                'vm_state': vm_states.STOPPED,
                'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                'ramdisk_id': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                'user_data': 'fake-user data',
                'shutdown_terminate': False,
                'disable_terminate': False,
                'system_metadata': sys_meta,
                }
        self.stubs.Set(self.cloud.compute_api, 'get', fake_get)

        def fake_get_instance_uuid_by_ec2_id(ctxt, int_id):
            if int_id == 305419896:
                return 'e5fe5518-0288-4fa3-b0c4-c79764101b85'
            raise exception.InstanceNotFound(instance_id=int_id)
        self.stubs.Set(db, 'get_instance_uuid_by_ec2_id',
                        fake_get_instance_uuid_by_ec2_id)

        get_attribute = functools.partial(
            self.cloud.describe_instance_attribute,
            self.context, 'i-12345678')

        bdm = get_attribute('blockDeviceMapping')
        bdm['blockDeviceMapping'].sort()

        expected_bdm = {'instance_id': 'i-12345678',
                        'rootDeviceType': 'ebs',
                        'blockDeviceMapping': [
                            {'deviceName': '/dev/sdh',
                             'ebs': {'status': 'attached',
                                     'deleteOnTermination': True,
                                     'volumeId': 'vol-05397fb1',
                                     'attachTime': '13:56:24'}}]}
        expected_bdm['blockDeviceMapping'].sort()
        self.assertEqual(bdm, expected_bdm)
        groupSet = get_attribute('groupSet')
        groupSet['groupSet'].sort()
        expected_groupSet = {'instance_id': 'i-12345678',
                             'groupSet': [{'groupId': 'fake0'},
                                          {'groupId': 'fake1'}]}
        expected_groupSet['groupSet'].sort()
        self.assertEqual(groupSet, expected_groupSet)
        self.assertEqual(get_attribute('instanceInitiatedShutdownBehavior'),
                         {'instance_id': 'i-12345678',
                          'instanceInitiatedShutdownBehavior': 'stop'})
        self.assertEqual(get_attribute('disableApiTermination'),
                         {'instance_id': 'i-12345678',
                          'disableApiTermination': False})
        self.assertEqual(get_attribute('instanceType'),
                         {'instance_id': 'i-12345678',
                          'instanceType': 'fake_type'})
        self.assertEqual(get_attribute('kernel'),
                         {'instance_id': 'i-12345678',
                          'kernel': 'aki-00000001'})
        self.assertEqual(get_attribute('ramdisk'),
                         {'instance_id': 'i-12345678',
                          'ramdisk': 'ari-00000002'})
        self.assertEqual(get_attribute('rootDeviceName'),
                         {'instance_id': 'i-12345678',
                          'rootDeviceName': '/dev/sdh'})
        # NOTE(yamahata): this isn't supported
        # get_attribute('sourceDestCheck')
        self.assertEqual(get_attribute('userData'),
                         {'instance_id': 'i-12345678',
                          'userData': '}\xa9\x1e\xba\xc7\xabu\xabZ'})

    def test_instance_initiated_shutdown_behavior(self):
        def test_dia_iisb(expected_result, **kwargs):
            """test describe_instance_attribute
            attribute instance_initiated_shutdown_behavior"""
            kwargs.update({'instance_type': CONF.default_instance_type,
                           'max_count': 1})
            instance_id = self._run_instance(**kwargs)

            result = self.cloud.describe_instance_attribute(self.context,
                            instance_id, 'instanceInitiatedShutdownBehavior')
            self.assertEqual(result['instanceInitiatedShutdownBehavior'],
                             expected_result)

            expected = {'instancesSet': [
                            {'instanceId': instance_id,
                             'previousState': {'code': 16,
                                               'name': 'running'},
                             'currentState': {'code': 48,
                                               'name': 'terminated'}}]}
            result = self.cloud.terminate_instances(self.context,
                                                    [instance_id])
            self.assertEqual(result, expected)
            self._restart_compute_service()

        test_dia_iisb('stop', image_id='ami-1')

        block_device_mapping = [{'device_name': '/dev/vdb',
                                 'virtual_name': 'ephemeral0'}]
        test_dia_iisb('stop', image_id='ami-2',
                     block_device_mapping=block_device_mapping)

        def fake_show(self, context, id_):
            LOG.debug("id_ %s", id_)

            prop = {}
            if id_ == 'ami-3':
                pass
            elif id_ == 'ami-4':
                prop = {'mappings': [{'device': 'sdb0',
                                          'virtual': 'ephemeral0'}]}
            elif id_ == 'ami-5':
                prop = {'block_device_mapping':
                        [{'device_name': '/dev/sdb0',
                          'virtual_name': 'ephemeral0'}]}
            elif id_ == 'ami-6':
                prop = {'mappings': [{'device': 'sdb0',
                                          'virtual': 'ephemeral0'}],
                        'block_device_mapping':
                        [{'device_name': '/dev/sdb0',
                          'virtual_name': 'ephemeral0'}]}

            prop_base = {'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                         'type': 'machine'}
            prop_base.update(prop)

            return {
                'id': id_,
                'name': 'fake_name',
                'properties': prop_base,
                'container_format': 'ami',
                'status': 'active'}

        # NOTE(yamahata): create ami-3 ... ami-6
        # ami-1 and ami-2 is already created by setUp()
        for i in range(3, 7):
            db.api.s3_image_create(self.context, 'ami-%d' % i)

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)

        test_dia_iisb('stop', image_id='ami-3')
        test_dia_iisb('stop', image_id='ami-4')
        test_dia_iisb('stop', image_id='ami-5')
        test_dia_iisb('stop', image_id='ami-6')

    def test_create_delete_tags(self):

        # We need to stub network calls
        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        # We need to stub out the MQ call - it won't succeed.  We do want
        # to check that the method is called, though
        meta_changes = [None]

        def fake_change_instance_metadata(inst, ctxt, diff, instance=None,
                                          instance_uuid=None):
            meta_changes[0] = diff

        self.stubs.Set(compute_rpcapi.ComputeAPI, 'change_instance_metadata',
                       fake_change_instance_metadata)

        # Create a test image
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        inst1_kwargs = {
                'reservation_id': 'a',
                'image_ref': image_uuid,
                'instance_type_id': 1,
                'vm_state': 'active',
                'hostname': 'server-1111',
                'created_at': datetime.datetime(2012, 5, 1, 1, 1, 1)
        }

        inst1 = db.instance_create(self.context, inst1_kwargs)
        ec2_id = ec2utils.id_to_ec2_inst_id(inst1['uuid'])

        # Create some tags
        md = {'key': 'foo', 'value': 'bar'}
        md_result = {'foo': 'bar'}
        self.cloud.create_tags(self.context, resource_id=[ec2_id],
                tag=[md])

        metadata = self.cloud.compute_api.get_instance_metadata(self.context,
                inst1)
        self.assertEqual(metadata, md_result)
        self.assertEqual(meta_changes, [{'foo': ['+', 'bar']}])

        # Delete them
        self.cloud.delete_tags(self.context, resource_id=[ec2_id],
                tag=[{'key': 'foo', 'value': 'bar'}])

        metadata = self.cloud.compute_api.get_instance_metadata(self.context,
                inst1)
        self.assertEqual(metadata, {})
        self.assertEqual(meta_changes, [{'foo': ['-']}])

    def test_describe_tags(self):
        # We need to stub network calls
        self._stub_instance_get_with_fixed_ips('get_all')
        self._stub_instance_get_with_fixed_ips('get')

        # We need to stub out the MQ call - it won't succeed.  We do want
        # to check that the method is called, though
        meta_changes = [None]

        def fake_change_instance_metadata(inst, ctxt, diff, instance=None,
                                          instance_uuid=None):
            meta_changes[0] = diff

        self.stubs.Set(compute_rpcapi.ComputeAPI, 'change_instance_metadata',
                       fake_change_instance_metadata)

        # Create some test images
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        inst1_kwargs = {
                'reservation_id': 'a',
                'image_ref': image_uuid,
                'instance_type_id': 1,
                'vm_state': 'active',
                'hostname': 'server-1111',
                'created_at': datetime.datetime(2012, 5, 1, 1, 1, 1)
        }

        inst2_kwargs = {
                'reservation_id': 'b',
                'image_ref': image_uuid,
                'instance_type_id': 1,
                'vm_state': 'active',
                'hostname': 'server-1112',
                'created_at': datetime.datetime(2012, 5, 1, 1, 1, 2)
        }

        inst1 = db.instance_create(self.context, inst1_kwargs)
        ec2_id1 = ec2utils.id_to_ec2_inst_id(inst1['uuid'])

        inst2 = db.instance_create(self.context, inst2_kwargs)
        ec2_id2 = ec2utils.id_to_ec2_inst_id(inst2['uuid'])

        # Create some tags
        # We get one overlapping pair, and each has a different key value pair
        # inst1 : {'foo': 'bar', 'bax': 'wibble'}
        # inst1 : {'foo': 'bar', 'baz': 'quux'}

        md = {'key': 'foo', 'value': 'bar'}
        md_result = {'foo': 'bar'}
        self.cloud.create_tags(self.context, resource_id=[ec2_id1, ec2_id2],
                tag=[md])

        self.assertEqual(meta_changes, [{'foo': ['+', 'bar']}])

        metadata = self.cloud.compute_api.get_instance_metadata(self.context,
                inst1)
        self.assertEqual(metadata, md_result)

        metadata = self.cloud.compute_api.get_instance_metadata(self.context,
                inst2)
        self.assertEqual(metadata, md_result)

        md2 = {'key': 'baz', 'value': 'quux'}
        md2_result = {'baz': 'quux'}
        md2_result.update(md_result)
        self.cloud.create_tags(self.context, resource_id=[ec2_id2],
                tag=[md2])

        self.assertEqual(meta_changes, [{'baz': ['+', 'quux']}])

        metadata = self.cloud.compute_api.get_instance_metadata(self.context,
                inst2)
        self.assertEqual(metadata, md2_result)

        md3 = {'key': 'bax', 'value': 'wibble'}
        md3_result = {'bax': 'wibble'}
        md3_result.update(md_result)
        self.cloud.create_tags(self.context, resource_id=[ec2_id1],
                tag=[md3])

        self.assertEqual(meta_changes, [{'bax': ['+', 'wibble']}])

        metadata = self.cloud.compute_api.get_instance_metadata(self.context,
                inst1)
        self.assertEqual(metadata, md3_result)

        inst1_key_foo = {'key': u'foo', 'resource_id': 'i-00000001',
                         'resource_type': 'instance', 'value': u'bar'}
        inst1_key_bax = {'key': u'bax', 'resource_id': 'i-00000001',
                         'resource_type': 'instance', 'value': u'wibble'}
        inst2_key_foo = {'key': u'foo', 'resource_id': 'i-00000002',
                         'resource_type': 'instance', 'value': u'bar'}
        inst2_key_baz = {'key': u'baz', 'resource_id': 'i-00000002',
                         'resource_type': 'instance', 'value': u'quux'}

        # We should be able to search by:
        # No filter
        tags = self.cloud.describe_tags(self.context)['tagSet']
        self.assertEqual(tags, [inst1_key_foo, inst2_key_foo,
                                inst2_key_baz, inst1_key_bax])

        # Resource ID
        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'resource_id',
                         'value': [ec2_id1]}])['tagSet']
        self.assertEqual(tags, [inst1_key_foo, inst1_key_bax])

        # Resource Type
        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'resource_type',
                         'value': ['instance']}])['tagSet']
        self.assertEqual(tags, [inst1_key_foo, inst2_key_foo,
                                inst2_key_baz, inst1_key_bax])

        # Key, either bare or with wildcards
        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'key',
                         'value': ['foo']}])['tagSet']
        self.assertEqual(tags, [inst1_key_foo, inst2_key_foo])

        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'key',
                         'value': ['baz']}])['tagSet']
        self.assertEqual(tags, [inst2_key_baz])

        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'key',
                         'value': ['ba?']}])['tagSet']
        self.assertEqual(tags, [])

        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'key',
                         'value': ['b*']}])['tagSet']
        self.assertEqual(tags, [])

        # Value, either bare or with wildcards
        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'value',
                         'value': ['bar']}])['tagSet']
        self.assertEqual(tags, [inst1_key_foo, inst2_key_foo])

        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'value',
                         'value': ['wi*']}])['tagSet']
        self.assertEqual(tags, [])

        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'value',
                         'value': ['quu?']}])['tagSet']
        self.assertEqual(tags, [])

        # Multiple values
        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'key',
                         'value': ['baz', 'bax']}])['tagSet']
        self.assertEqual(tags, [inst2_key_baz, inst1_key_bax])

        # Multiple filters
        tags = self.cloud.describe_tags(self.context,
                filter=[{'name': 'key',
                         'value': ['baz']},
                        {'name': 'value',
                         'value': ['wibble']}])['tagSet']
        self.assertEqual(tags, [inst2_key_baz, inst1_key_bax])

        # And we should fail on supported resource types
        self.assertRaises(exception.EC2APIError,
                          self.cloud.describe_tags,
                          self.context,
                          filter=[{'name': 'resource_type',
                                   'value': ['instance', 'volume']}])

    def test_resource_type_from_id(self):
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'i-12345'),
                'instance')
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'r-12345'),
                'reservation')
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'vol-12345'),
                'volume')
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'snap-12345'),
                'snapshot')
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'ami-12345'),
                'image')
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'ari-12345'),
                'image')
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'aki-12345'),
                'image')
        self.assertEqual(
                ec2utils.resource_type_from_id(self.context, 'x-12345'),
                None)


class CloudTestCaseQuantumProxy(test.TestCase):
    def setUp(self):
        cfg.CONF.set_override('security_group_api', 'quantum')
        self.cloud = cloud.CloudController()
        self.original_client = quantumv2.get_client
        quantumv2.get_client = test_quantum.get_client
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)
        super(CloudTestCaseQuantumProxy, self).setUp()

    def tearDown(self):
        quantumv2.get_client = self.original_client
        test_quantum.get_client()._reset()
        super(CloudTestCaseQuantumProxy, self).tearDown()

    def test_describe_security_groups(self):
        # Makes sure describe_security_groups works and filters results.
        group_name = 'test'
        description = 'test'
        self.cloud.create_security_group(self.context, group_name,
                                         description)
        result = self.cloud.describe_security_groups(self.context)
        # NOTE(vish): should have the default group as well
        self.assertEqual(len(result['securityGroupInfo']), 2)
        result = self.cloud.describe_security_groups(self.context,
                      group_name=[group_name])
        self.assertEqual(len(result['securityGroupInfo']), 1)
        self.assertEqual(result['securityGroupInfo'][0]['groupName'],
                         group_name)
        self.cloud.delete_security_group(self.context, group_name)

    def test_describe_security_groups_by_id(self):
        group_name = 'test'
        description = 'test'
        self.cloud.create_security_group(self.context, group_name,
                                         description)
        quantum = test_quantum.get_client()
        # Get id from quantum since cloud.create_security_group
        # does not expose it.
        search_opts = {'name': group_name}
        groups = quantum.list_security_groups(
            **search_opts)['security_groups']
        result = self.cloud.describe_security_groups(self.context,
                      group_id=[groups[0]['id']])
        self.assertEqual(len(result['securityGroupInfo']), 1)
        self.assertEqual(
                result['securityGroupInfo'][0]['groupName'],
                group_name)
        self.cloud.delete_security_group(self.context, group_name)

    def test_create_delete_security_group(self):
        descript = 'test description'
        create = self.cloud.create_security_group
        result = create(self.context, 'testgrp', descript)
        group_descript = result['securityGroupSet'][0]['groupDescription']
        self.assertEqual(descript, group_descript)
        delete = self.cloud.delete_security_group
        self.assertTrue(delete(self.context, 'testgrp'))

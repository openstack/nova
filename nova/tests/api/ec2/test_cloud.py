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
import mox

import functools

from base64 import b64decode
from M2Crypto import BIO
from M2Crypto import RSA
import os

from eventlet import greenthread

from nova import context
from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import network
from nova import rpc
from nova import test
from nova import utils
from nova.api.ec2 import cloud
from nova.api.ec2 import ec2utils
from nova.compute import vm_states
from nova.image import fake


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.cloud')


class CloudTestCase(test.TestCase):
    def setUp(self):
        super(CloudTestCase, self).setUp()
        self.flags(connection_type='fake',
                   stub_network=True)

        # set up our cloud
        self.cloud = cloud.CloudController()

        # set up services
        self.compute = self.start_service('compute')
        self.scheduter = self.start_service('scheduler')
        self.network = self.start_service('network')
        self.volume = self.start_service('volume')
        self.image_service = utils.import_object(FLAGS.image_service)

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              True)

        def fake_show(meh, context, id):
            return {'id': 1, 'container_format': 'ami',
                    'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine', 'image_state': 'available'}}

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'show_by_name', fake_show)

        # NOTE(vish): set up a manual wait so rpc.cast has a chance to finish
        rpc_cast = rpc.cast

        def finish_cast(*args, **kwargs):
            rpc_cast(*args, **kwargs)
            greenthread.sleep(0.2)

        self.stubs.Set(rpc, 'cast', finish_cast)

    def _create_key(self, name):
        # NOTE(vish): create depends on pool, so just call helper directly
        return cloud._gen_key(self.context, self.context.user_id, name)

    def test_describe_regions(self):
        """Makes sure describe regions runs without raising an exception"""
        result = self.cloud.describe_regions(self.context)
        self.assertEqual(len(result['regionInfo']), 1)
        self.flags(region_list=["one=test_host1", "two=test_host2"])
        result = self.cloud.describe_regions(self.context)
        self.assertEqual(len(result['regionInfo']), 2)

    def test_describe_addresses(self):
        """Makes sure describe addresses runs without raising an exception"""
        address = "10.10.10.10"
        db.floating_ip_create(self.context,
                              {'address': address,
                               'host': self.network.host})
        self.cloud.allocate_address(self.context)
        self.cloud.describe_addresses(self.context)
        self.cloud.release_address(self.context,
                                  public_ip=address)
        db.floating_ip_destroy(self.context, address)

    def test_allocate_address(self):
        address = "10.10.10.10"
        allocate = self.cloud.allocate_address
        db.floating_ip_create(self.context,
                              {'address': address,
                               'host': self.network.host})
        self.assertEqual(allocate(self.context)['publicIp'], address)
        db.floating_ip_destroy(self.context, address)
        self.assertRaises(exception.NoMoreFloatingIps,
                          allocate,
                          self.context)

    def test_release_address(self):
        address = "10.10.10.10"
        allocate = self.cloud.allocate_address
        db.floating_ip_create(self.context,
                              {'address': address,
                               'host': self.network.host})
        result = self.cloud.release_address(self.context, address)
        self.assertEqual(result['releaseResponse'], ['Address released.'])

    def test_release_address_still_associated(self):
        address = "10.10.10.10"
        fixed_ip = {'instance': {'id': 1}}
        floating_ip = {'id': 0,
                       'address': address,
                       'fixed_ip_id': 0,
                       'fixed_ip': fixed_ip,
                       'project_id': None,
                       'auto_assigned': False}
        network_api = network.api.API()
        self.mox.StubOutWithMock(network_api.db, 'floating_ip_get_by_address')
        network_api.db.floating_ip_get_by_address(mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(floating_ip)
        self.mox.ReplayAll()
        release = self.cloud.release_address
        # ApiError: Floating ip is in use.  Disassociate it before releasing.
        self.assertRaises(exception.ApiError, release, self.context, address)

    def test_associate_disassociate_address(self):
        """Verifies associate runs cleanly without raising an exception"""
        address = "10.10.10.10"
        db.floating_ip_create(self.context, {'address': address})
        self.cloud.allocate_address(self.context)
        # TODO(jkoelker) Probably need to query for instance_type_id and
        #                make sure we get a valid one
        inst = db.instance_create(self.context, {'host': self.compute.host,
                                                 'instance_type_id': 1})
        networks = db.network_get_all(self.context)
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': self.network.host})
        project_id = self.context.project_id
        type_id = inst['instance_type_id']
        ips = self.network.allocate_for_instance(self.context,
                                                 instance_id=inst['id'],
                                                 host=inst['host'],
                                                 vpn=None,
                                                 instance_type_id=type_id,
                                                 project_id=project_id)
        # TODO(jkoelker) Make this mas bueno
        self.assertTrue(ips)
        self.assertTrue('ips' in ips[0][1])
        self.assertTrue(ips[0][1]['ips'])
        self.assertTrue('ip' in ips[0][1]['ips'][0])

        fixed = ips[0][1]['ips'][0]['ip']

        ec2_id = ec2utils.id_to_ec2_id(inst['id'])
        self.cloud.associate_address(self.context,
                                     instance_id=ec2_id,
                                     public_ip=address)
        self.cloud.disassociate_address(self.context,
                                        public_ip=address)
        self.cloud.release_address(self.context,
                                  public_ip=address)
        self.network.deallocate_fixed_ip(self.context, fixed)
        db.instance_destroy(self.context, inst['id'])
        db.floating_ip_destroy(self.context, address)

    def test_describe_security_groups(self):
        """Makes sure describe_security_groups works and filters results."""
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
        self.assertRaises(exception.ApiError, delete, self.context)

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
                  'ip_ranges':{'1': {'cidr_ip': u'0.0.0.0/0'},
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
                           'toPort': 65536},
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
        self.assertRaises(exception.ApiError, authz, self.context, 'test')

    def test_authorize_security_group_ingress_missing_group_name_or_id(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        authz = self.cloud.authorize_security_group_ingress
        self.assertRaises(exception.ApiError, authz, self.context, **kwargs)

    def test_authorize_security_group_ingress_already_exists(self):
        kwargs = {'project_id': self.context.project_id, 'name': 'test'}
        sec = db.security_group_create(self.context, kwargs)
        authz = self.cloud.authorize_security_group_ingress
        kwargs = {'to_port': '999', 'from_port': '999', 'ip_protocol': 'tcp'}
        authz(self.context, group_name=sec['name'], **kwargs)
        self.assertRaises(exception.ApiError, authz, self.context,
                          group_name=sec['name'], **kwargs)

    def test_revoke_security_group_ingress_missing_group_name_or_id(self):
        kwargs = {'to_port': '999', 'from_port': '999', 'ip_protocol': 'tcp'}
        revoke = self.cloud.revoke_security_group_ingress
        self.assertRaises(exception.ApiError, revoke, self.context, **kwargs)

    def test_describe_volumes(self):
        """Makes sure describe_volumes works and filters results."""
        vol1 = db.volume_create(self.context, {})
        vol2 = db.volume_create(self.context, {})
        result = self.cloud.describe_volumes(self.context)
        self.assertEqual(len(result['volumeSet']), 2)
        volume_id = ec2utils.id_to_ec2_vol_id(vol2['id'])
        result = self.cloud.describe_volumes(self.context,
                                             volume_id=[volume_id])
        self.assertEqual(len(result['volumeSet']), 1)
        self.assertEqual(
                ec2utils.ec2_id_to_id(result['volumeSet'][0]['volumeId']),
                vol2['id'])
        db.volume_destroy(self.context, vol1['id'])
        db.volume_destroy(self.context, vol2['id'])

    def test_create_volume_from_snapshot(self):
        """Makes sure create_volume works when we specify a snapshot."""
        vol = db.volume_create(self.context, {'size': 1})
        snap = db.snapshot_create(self.context, {'volume_id': vol['id'],
                                                 'volume_size': vol['size'],
                                                 'status': "available"})
        snapshot_id = ec2utils.id_to_ec2_snap_id(snap['id'])

        result = self.cloud.create_volume(self.context,
                                          snapshot_id=snapshot_id)
        volume_id = result['volumeId']
        result = self.cloud.describe_volumes(self.context)
        self.assertEqual(len(result['volumeSet']), 2)
        self.assertEqual(result['volumeSet'][1]['volumeId'], volume_id)

        db.volume_destroy(self.context, ec2utils.ec2_id_to_id(volume_id))
        db.snapshot_destroy(self.context, snap['id'])
        db.volume_destroy(self.context, vol['id'])

    def test_describe_availability_zones(self):
        """Makes sure describe_availability_zones works and filters results."""
        service1 = db.service_create(self.context, {'host': 'host1_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0,
                                         'availability_zone': "zone1"})
        service2 = db.service_create(self.context, {'host': 'host2_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0,
                                         'availability_zone': "zone2"})
        result = self.cloud.describe_availability_zones(self.context)
        self.assertEqual(len(result['availabilityZoneInfo']), 3)
        db.service_destroy(self.context, service1['id'])
        db.service_destroy(self.context, service2['id'])

    def test_describe_snapshots(self):
        """Makes sure describe_snapshots works and filters results."""
        vol = db.volume_create(self.context, {})
        snap1 = db.snapshot_create(self.context, {'volume_id': vol['id']})
        snap2 = db.snapshot_create(self.context, {'volume_id': vol['id']})
        result = self.cloud.describe_snapshots(self.context)
        self.assertEqual(len(result['snapshotSet']), 2)
        snapshot_id = ec2utils.id_to_ec2_snap_id(snap2['id'])
        result = self.cloud.describe_snapshots(self.context,
                                               snapshot_id=[snapshot_id])
        self.assertEqual(len(result['snapshotSet']), 1)
        self.assertEqual(
            ec2utils.ec2_id_to_id(result['snapshotSet'][0]['snapshotId']),
            snap2['id'])
        db.snapshot_destroy(self.context, snap1['id'])
        db.snapshot_destroy(self.context, snap2['id'])
        db.volume_destroy(self.context, vol['id'])

    def test_create_snapshot(self):
        """Makes sure create_snapshot works."""
        vol = db.volume_create(self.context, {'status': "available"})
        volume_id = ec2utils.id_to_ec2_vol_id(vol['id'])

        result = self.cloud.create_snapshot(self.context,
                                            volume_id=volume_id)
        snapshot_id = result['snapshotId']
        result = self.cloud.describe_snapshots(self.context)
        self.assertEqual(len(result['snapshotSet']), 1)
        self.assertEqual(result['snapshotSet'][0]['snapshotId'], snapshot_id)

        db.snapshot_destroy(self.context, ec2utils.ec2_id_to_id(snapshot_id))
        db.volume_destroy(self.context, vol['id'])

    def test_delete_snapshot(self):
        """Makes sure delete_snapshot works."""
        vol = db.volume_create(self.context, {'status': "available"})
        snap = db.snapshot_create(self.context, {'volume_id': vol['id'],
                                                  'status': "available"})
        snapshot_id = ec2utils.id_to_ec2_snap_id(snap['id'])

        result = self.cloud.delete_snapshot(self.context,
                                            snapshot_id=snapshot_id)
        self.assertTrue(result)

        db.volume_destroy(self.context, vol['id'])

    def test_describe_instances(self):
        """Makes sure describe_instances works and filters results."""
        inst1 = db.instance_create(self.context, {'reservation_id': 'a',
                                                  'image_ref': 1,
                                                  'host': 'host1'})
        inst2 = db.instance_create(self.context, {'reservation_id': 'a',
                                                  'image_ref': 1,
                                                  'host': 'host2'})
        comp1 = db.service_create(self.context, {'host': 'host1',
                                                 'availability_zone': 'zone1',
                                                 'topic': "compute"})
        comp2 = db.service_create(self.context, {'host': 'host2',
                                                 'availability_zone': 'zone2',
                                                 'topic': "compute"})
        result = self.cloud.describe_instances(self.context)
        result = result['reservationSet'][0]
        self.assertEqual(len(result['instancesSet']), 2)
        instance_id = ec2utils.id_to_ec2_id(inst2['id'])
        result = self.cloud.describe_instances(self.context,
                                             instance_id=[instance_id])
        result = result['reservationSet'][0]
        self.assertEqual(len(result['instancesSet']), 1)
        self.assertEqual(result['instancesSet'][0]['instanceId'],
                         instance_id)
        self.assertEqual(result['instancesSet'][0]
                         ['placement']['availabilityZone'], 'zone2')
        db.instance_destroy(self.context, inst1['id'])
        db.instance_destroy(self.context, inst2['id'])
        db.service_destroy(self.context, comp1['id'])
        db.service_destroy(self.context, comp2['id'])

    def test_describe_instances_deleted(self):
        args1 = {'reservation_id': 'a', 'image_ref': 1, 'host': 'host1'}
        inst1 = db.instance_create(self.context, args1)
        args2 = {'reservation_id': 'b', 'image_ref': 1, 'host': 'host1'}
        inst2 = db.instance_create(self.context, args2)
        db.instance_destroy(self.context, inst1.id)
        result = self.cloud.describe_instances(self.context)
        self.assertEqual(len(result['reservationSet']), 1)
        result1 = result['reservationSet'][0]['instancesSet']
        self.assertEqual(result1[0]['instanceId'],
                         ec2utils.id_to_ec2_id(inst2.id))

    def _block_device_mapping_create(self, instance_id, mappings):
        volumes = []
        for bdm in mappings:
            db.block_device_mapping_create(self.context, bdm)
            if 'volume_id' in bdm:
                values = {'id': bdm['volume_id']}
                for bdm_key, vol_key in [('snapshot_id', 'snapshot_id'),
                                         ('snapshot_size', 'volume_size'),
                                         ('delete_on_termination',
                                          'delete_on_termination')]:
                    if bdm_key in bdm:
                        values[vol_key] = bdm[bdm_key]
                vol = db.volume_create(self.context, values)
                db.volume_attached(self.context, vol['id'],
                                   instance_id, bdm['device_name'])
                volumes.append(vol)
        return volumes

    def _setUpBlockDeviceMapping(self):
        inst1 = db.instance_create(self.context,
                                  {'image_ref': 1,
                                   'root_device_name': '/dev/sdb1'})
        inst2 = db.instance_create(self.context,
                                  {'image_ref': 2,
                                   'root_device_name': '/dev/sdc1'})

        instance_id = inst1['id']
        mappings0 = [
            {'instance_id': instance_id,
             'device_name': '/dev/sdb1',
             'snapshot_id': '1',
             'volume_id': '2'},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb2',
             'volume_id': '3',
             'volume_size': 1},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb3',
             'delete_on_termination': True,
             'snapshot_id': '4',
             'volume_id': '5'},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb4',
             'delete_on_termination': False,
             'snapshot_id': '6',
             'volume_id': '7'},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb5',
             'snapshot_id': '8',
             'volume_id': '9',
             'volume_size': 0},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb6',
             'snapshot_id': '10',
             'volume_id': '11',
             'volume_size': 1},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb7',
             'no_device': True},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb8',
             'virtual_name': 'swap'},
            {'instance_id': instance_id,
             'device_name': '/dev/sdb9',
             'virtual_name': 'ephemeral3'}]

        volumes = self._block_device_mapping_create(instance_id, mappings0)
        return (inst1, inst2, volumes)

    def _tearDownBlockDeviceMapping(self, inst1, inst2, volumes):
        for vol in volumes:
            db.volume_destroy(self.context, vol['id'])
        for id in (inst1['id'], inst2['id']):
            for bdm in db.block_device_mapping_get_all_by_instance(
                self.context, id):
                db.block_device_mapping_destroy(self.context, bdm['id'])
        db.instance_destroy(self.context, inst2['id'])
        db.instance_destroy(self.context, inst1['id'])

    _expected_instance_bdm1 = {
        'instanceId': 'i-00000001',
        'rootDeviceName': '/dev/sdb1',
        'rootDeviceType': 'ebs'}

    _expected_block_device_mapping0 = [
        {'deviceName': '/dev/sdb1',
         'ebs': {'status': 'in-use',
                 'deleteOnTermination': False,
                 'volumeId': 2,
                 }},
        {'deviceName': '/dev/sdb2',
         'ebs': {'status': 'in-use',
                 'deleteOnTermination': False,
                 'volumeId': 3,
                 }},
        {'deviceName': '/dev/sdb3',
         'ebs': {'status': 'in-use',
                 'deleteOnTermination': True,
                 'volumeId': 5,
                 }},
        {'deviceName': '/dev/sdb4',
         'ebs': {'status': 'in-use',
                 'deleteOnTermination': False,
                 'volumeId': 7,
                 }},
        {'deviceName': '/dev/sdb5',
         'ebs': {'status': 'in-use',
                 'deleteOnTermination': False,
                 'volumeId': 9,
                 }},
        {'deviceName': '/dev/sdb6',
         'ebs': {'status': 'in-use',
                 'deleteOnTermination': False,
                 'volumeId': 11, }}]
        # NOTE(yamahata): swap/ephemeral device case isn't supported yet.

    _expected_instance_bdm2 = {
        'instanceId': 'i-00000002',
        'rootDeviceName': '/dev/sdc1',
        'rootDeviceType': 'instance-store'}

    def test_format_instance_bdm(self):
        (inst1, inst2, volumes) = self._setUpBlockDeviceMapping()

        result = {}
        self.cloud._format_instance_bdm(self.context, inst1['id'], '/dev/sdb1',
                                        result)
        self.assertSubDictMatch(
            {'rootDeviceType': self._expected_instance_bdm1['rootDeviceType']},
            result)
        self._assertEqualBlockDeviceMapping(
            self._expected_block_device_mapping0, result['blockDeviceMapping'])

        result = {}
        self.cloud._format_instance_bdm(self.context, inst2['id'], '/dev/sdc1',
                                        result)
        self.assertSubDictMatch(
            {'rootDeviceType': self._expected_instance_bdm2['rootDeviceType']},
            result)

        self._tearDownBlockDeviceMapping(inst1, inst2, volumes)

    def _assertInstance(self, instance_id):
        ec2_instance_id = ec2utils.id_to_ec2_id(instance_id)
        result = self.cloud.describe_instances(self.context,
                                               instance_id=[ec2_instance_id])
        result = result['reservationSet'][0]
        self.assertEqual(len(result['instancesSet']), 1)
        result = result['instancesSet'][0]
        self.assertEqual(result['instanceId'], ec2_instance_id)
        return result

    def _assertEqualBlockDeviceMapping(self, expected, result):
        self.assertEqual(len(expected), len(result))
        for x in expected:
            found = False
            for y in result:
                if x['deviceName'] == y['deviceName']:
                    self.assertSubDictMatch(x, y)
                    found = True
                    break
            self.assertTrue(found)

    def test_describe_instances_bdm(self):
        """Make sure describe_instances works with root_device_name and
        block device mappings
        """
        (inst1, inst2, volumes) = self._setUpBlockDeviceMapping()

        result = self._assertInstance(inst1['id'])
        self.assertSubDictMatch(self._expected_instance_bdm1, result)
        self._assertEqualBlockDeviceMapping(
            self._expected_block_device_mapping0, result['blockDeviceMapping'])

        result = self._assertInstance(inst2['id'])
        self.assertSubDictMatch(self._expected_instance_bdm2, result)

        self._tearDownBlockDeviceMapping(inst1, inst2, volumes)

    def test_describe_images(self):
        describe_images = self.cloud.describe_images

        def fake_detail(meh, context):
            return [{'id': 1, 'container_format': 'ami',
                     'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}}]

        def fake_show_none(meh, context, id):
            raise exception.ImageNotFound(image_id='bad_image_id')

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
        # provide an non-existing image_id
        self.stubs.UnsetAll()
        self.stubs.Set(fake._FakeImageService, 'show', fake_show_none)
        self.stubs.Set(fake._FakeImageService, 'show_by_name', fake_show_none)
        self.assertRaises(exception.ImageNotFound, describe_images,
                          self.context, ['ami-fake'])

    def assertDictListUnorderedMatch(self, L1, L2, key):
        self.assertEqual(len(L1), len(L2))
        for d1 in L1:
            self.assertTrue(key in d1)
            for d2 in L2:
                self.assertTrue(key in d2)
                if d1[key] == d2[key]:
                    self.assertDictMatch(d1, d2)

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
            {'device_name': '/dev/sdb1', 'snapshot_id': 01234567},
            {'device_name': '/dev/sdb2', 'volume_id': 01234567},
            {'device_name': '/dev/sdb3', 'virtual_name': 'ephemeral5'},
            {'device_name': '/dev/sdb4', 'no_device': True},

            {'device_name': '/dev/sdc1', 'snapshot_id': 12345678},
            {'device_name': '/dev/sdc2', 'volume_id': 12345678},
            {'device_name': '/dev/sdc3', 'virtual_name': 'ephemeral6'},
            {'device_name': '/dev/sdc4', 'no_device': True}]
        image1 = {
            'id': 1,
            'properties': {
                'kernel_id': 1,
                'type': 'machine',
                'image_state': 'available',
                'mappings': mappings1,
                'block_device_mapping': block_device_mapping1,
                }
            }

        mappings2 = [{'device': '/dev/sda1', 'virtual': 'root'}]
        block_device_mapping2 = [{'device_name': '/dev/sdb1',
                                  'snapshot_id': 01234567}]
        image2 = {
            'id': 2,
            'properties': {
                'kernel_id': 2,
                'type': 'machine',
                'root_device_name': '/dev/sdb1',
                'mappings': mappings2,
                'block_device_mapping': block_device_mapping2}}

        def fake_show(meh, context, image_id):
            for i in [image1, image2]:
                if i['id'] == image_id:
                    return i
            raise exception.ImageNotFound(image_id=image_id)

        def fake_detail(meh, context):
            return [image1, image2]

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
                    snap = db.snapshot_create(self.context,
                                              {'id': bdm['snapshot_id'],
                                               'volume_id': 76543210,
                                               'status': "available",
                                               'volume_size': 1})
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
                                            'snap-00053977'}},
        {'deviceName': '/dev/sdb2', 'ebs': {'snapshotId':
                                            'vol-00053977'}},
        {'deviceName': '/dev/sdb3', 'virtualName': 'ephemeral5'},
        # {'deviceName': '/dev/sdb4', 'noDevice': True},

        {'deviceName': '/dev/sdc0', 'virtualName': 'swap'},
        {'deviceName': '/dev/sdc1', 'ebs': {'snapshotId':
                                            'snap-00bc614e'}},
        {'deviceName': '/dev/sdc2', 'ebs': {'snapshotId':
                                            'vol-00bc614e'}},
        {'deviceName': '/dev/sdc3', 'virtualName': 'ephemeral6'},
        # {'deviceName': '/dev/sdc4', 'noDevice': True}
        ]

    _expected_root_device_name2 = '/dev/sdb1'
    _expected_bdms2 = [{'deviceName': '/dev/sdb1',
                       'ebs': {'snapshotId': 'snap-00053977'}}]

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
        """test for rootDeviceName and blockDeiceMapping"""
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

        self.stubs.UnsetAll()

    def test_describe_image_attribute(self):
        describe_image_attribute = self.cloud.describe_image_attribute

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}, 'container_format': 'ami',
                    'is_public': True}

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'show_by_name', fake_show)
        result = describe_image_attribute(self.context, 'ami-00000001',
                                          'launchPermission')
        self.assertEqual([{'group': 'all'}], result['launchPermission'])

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

        fake_metadata = {'id': 1, 'container_format': 'ami',
                         'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                                        'type': 'machine'}, 'is_public': False}

        def fake_show(meh, context, id):
            return fake_metadata

        def fake_update(meh, context, image_id, metadata, data=None):
            fake_metadata.update(metadata)
            return fake_metadata

        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'show_by_name', fake_show)
        self.stubs.Set(fake._FakeImageService, 'update', fake_update)
        result = modify_image_attribute(self.context, 'ami-00000001',
                                          'launchPermission', 'add',
                                           user_group=['all'])
        self.assertEqual(True, result['is_public'])

    def test_deregister_image(self):
        deregister_image = self.cloud.deregister_image

        def fake_delete(self, context, id):
            return None

        self.stubs.Set(fake._FakeImageService, 'delete', fake_delete)
        # valid image
        result = deregister_image(self.context, 'ami-00000001')
        self.assertEqual(result['imageId'], 'ami-00000001')
        # invalid image
        self.stubs.UnsetAll()

        def fake_detail_empty(self, context):
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

    def _run_instance_wait(self, **kwargs):
        ec2_instance_id = self._run_instance(**kwargs)
        self._wait_for_running(ec2_instance_id)
        return ec2_instance_id

    def test_console_output(self):
        instance_id = self._run_instance(
            image_id='ami-1',
            instance_type=FLAGS.default_instance_type,
            max_count=1)
        output = self.cloud.get_console_output(context=self.context,
                                               instance_id=[instance_id])
        self.assertEquals(b64decode(output['output']), 'FAKE CONSOLE?OUTPUT')
        # TODO(soren): We need this until we can stop polling in the rpc code
        #              for unit tests.
        rv = self.cloud.terminate_instances(self.context, [instance_id])

    def test_ajax_console(self):
        instance_id = self._run_instance(image_id='ami-1')
        output = self.cloud.get_ajax_console(context=self.context,
                                             instance_id=[instance_id])
        self.assertEquals(output['url'],
                          '%s/?token=FAKETOKEN' % FLAGS.ajax_console_proxy_url)
        # TODO(soren): We need this until we can stop polling in the rpc code
        #              for unit tests.
        rv = self.cloud.terminate_instances(self.context, [instance_id])

    def test_key_generation(self):
        result = self._create_key('test')
        private_key = result['private_key']
        key = RSA.load_key_string(private_key, callback=lambda: None)
        bio = BIO.MemoryBuffer()
        public_key = db.key_pair_get(self.context,
                                    self.context.user_id,
                                    'test')['public_key']
        key.save_pub_key_bio(bio)
        converted = crypto.ssl_pub_to_ssh_pub(bio.read())
        # assert key fields are equal
        self.assertEqual(public_key.split(" ")[1].strip(),
                         converted.split(" ")[1].strip())

    def test_describe_key_pairs(self):
        self._create_key('test1')
        self._create_key('test2')
        result = self.cloud.describe_key_pairs(self.context)
        keys = result["keySet"]
        self.assertTrue(filter(lambda k: k['keyName'] == 'test1', keys))
        self.assertTrue(filter(lambda k: k['keyName'] == 'test2', keys))

    def test_import_public_key(self):
        # test when user provides all values
        result1 = self.cloud.import_public_key(self.context,
                                               'testimportkey1',
                                               'mytestpubkey',
                                               'mytestfprint')
        self.assertTrue(result1)
        keydata = db.key_pair_get(self.context,
                                  self.context.user_id,
                                  'testimportkey1')
        self.assertEqual('mytestpubkey', keydata['public_key'])
        self.assertEqual('mytestfprint', keydata['fingerprint'])
        # test when user omits fingerprint
        pubkey_path = os.path.join(os.path.dirname(__file__), 'public_key')
        f = open(pubkey_path + '/dummy.pub', 'r')
        dummypub = f.readline().rstrip()
        f.close
        f = open(pubkey_path + '/dummy.fingerprint', 'r')
        dummyfprint = f.readline().rstrip()
        f.close
        result2 = self.cloud.import_public_key(self.context,
                                               'testimportkey2',
                                               dummypub)
        self.assertTrue(result2)
        keydata = db.key_pair_get(self.context,
                                  self.context.user_id,
                                  'testimportkey2')
        self.assertEqual(dummypub, keydata['public_key'])
        self.assertEqual(dummyfprint, keydata['fingerprint'])

    def test_delete_key_pair(self):
        self._create_key('test')
        self.cloud.delete_key_pair(self.context, 'test')

    def test_run_instances(self):
        kwargs = {'image_id': FLAGS.default_image,
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances
        result = run_instances(self.context, **kwargs)
        instance = result['instancesSet'][0]
        self.assertEqual(instance['imageId'], 'ami-00000001')
        self.assertEqual(instance['displayName'], 'Server 1')
        self.assertEqual(instance['instanceId'], 'i-00000001')
        self.assertEqual(instance['instanceState']['name'], 'running')
        self.assertEqual(instance['instanceType'], 'm1.small')

    def test_run_instances_image_state_none(self):
        kwargs = {'image_id': FLAGS.default_image,
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_no_state(self, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}, 'container_format': 'ami'}

        self.stubs.UnsetAll()
        self.stubs.Set(fake._FakeImageService, 'show', fake_show_no_state)
        self.assertRaises(exception.ApiError, run_instances,
                          self.context, **kwargs)

    def test_run_instances_image_state_invalid(self):
        kwargs = {'image_id': FLAGS.default_image,
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_decrypt(self, context, id):
            return {'id': 1, 'container_format': 'ami',
                    'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine', 'image_state': 'decrypting'}}

        self.stubs.UnsetAll()
        self.stubs.Set(fake._FakeImageService, 'show', fake_show_decrypt)
        self.assertRaises(exception.ApiError, run_instances,
                          self.context, **kwargs)

    def test_run_instances_image_status_active(self):
        kwargs = {'image_id': FLAGS.default_image,
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_stat_active(self, context, id):
            return {'id': 1, 'container_format': 'ami',
                    'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}, 'status': 'active'}

        self.stubs.Set(fake._FakeImageService, 'show', fake_show_stat_active)

        result = run_instances(self.context, **kwargs)
        self.assertEqual(len(result['instancesSet']), 1)

    def test_terminate_instances(self):
        inst1 = db.instance_create(self.context, {'reservation_id': 'a',
                                                  'image_ref': 1,
                                                  'host': 'host1'})
        terminate_instances = self.cloud.terminate_instances
        # valid instance_id
        result = terminate_instances(self.context, ['i-00000001'])
        self.assertTrue(result)
        # non-existing instance_id
        self.assertRaises(exception.InstanceNotFound, terminate_instances,
                          self.context, ['i-2'])
        db.instance_destroy(self.context, inst1['id'])

    def test_update_of_instance_display_fields(self):
        inst = db.instance_create(self.context, {})
        ec2_id = ec2utils.id_to_ec2_id(inst['id'])
        self.cloud.update_instance(self.context, ec2_id,
                                   display_name='c00l 1m4g3')
        inst = db.instance_get(self.context, inst['id'])
        self.assertEqual('c00l 1m4g3', inst['display_name'])
        db.instance_destroy(self.context, inst['id'])

    def test_update_of_instance_wont_update_private_fields(self):
        inst = db.instance_create(self.context, {})
        host = inst['host']
        ec2_id = ec2utils.id_to_ec2_id(inst['id'])
        self.cloud.update_instance(self.context, ec2_id,
                                   display_name='c00l 1m4g3',
                                   host='otherhost')
        inst = db.instance_get(self.context, inst['id'])
        self.assertEqual(host, inst['host'])
        db.instance_destroy(self.context, inst['id'])

    def test_update_of_volume_display_fields(self):
        vol = db.volume_create(self.context, {})
        self.cloud.update_volume(self.context,
                                 ec2utils.id_to_ec2_vol_id(vol['id']),
                                 display_name='c00l v0lum3')
        vol = db.volume_get(self.context, vol['id'])
        self.assertEqual('c00l v0lum3', vol['display_name'])
        db.volume_destroy(self.context, vol['id'])

    def test_update_of_volume_wont_update_private_fields(self):
        vol = db.volume_create(self.context, {})
        self.cloud.update_volume(self.context,
                                 ec2utils.id_to_ec2_vol_id(vol['id']),
                                 mountpoint='/not/here')
        vol = db.volume_get(self.context, vol['id'])
        self.assertEqual(None, vol['mountpoint'])
        db.volume_destroy(self.context, vol['id'])

    def _restart_compute_service(self, periodic_interval=None):
        """restart compute service. NOTE: fake driver forgets all instances."""
        self.compute.kill()
        if periodic_interval:
            self.compute = self.start_service(
                'compute', periodic_interval=periodic_interval)
        else:
            self.compute = self.start_service('compute')

    def _wait_for_state(self, ctxt, instance_id, predicate):
        """Wait for a stopped instance to be a given state"""
        id = ec2utils.ec2_id_to_id(instance_id)
        while True:
            info = self.cloud.compute_api.get(context=ctxt, instance_id=id)
            LOG.debug(info)
            if predicate(info):
                break
            greenthread.sleep(1)

    def _wait_for_running(self, instance_id):
        def is_running(info):
            vm_state = info["vm_state"]
            task_state = info["task_state"]
            return vm_state == vm_states.ACTIVE and task_state == None
        self._wait_for_state(self.context, instance_id, is_running)

    def _wait_for_stopped(self, instance_id):
        def is_stopped(info):
            vm_state = info["vm_state"]
            task_state = info["task_state"]
            return vm_state == vm_states.STOPPED and task_state == None
        self._wait_for_state(self.context, instance_id, is_stopped)

    def _wait_for_terminate(self, instance_id):
        def is_deleted(info):
            return info['deleted']
        elevated = self.context.elevated(read_deleted=True)
        self._wait_for_state(elevated, instance_id, is_deleted)

    def test_stop_start_instance(self):
        """Makes sure stop/start instance works"""
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval=0.3)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1, }
        instance_id = self._run_instance_wait(**kwargs)

        # a running instance can't be started. It is just ignored.
        result = self.cloud.start_instances(self.context, [instance_id])
        greenthread.sleep(0.3)
        self.assertTrue(result)

        result = self.cloud.stop_instances(self.context, [instance_id])
        greenthread.sleep(0.3)
        self.assertTrue(result)
        self._wait_for_stopped(instance_id)

        result = self.cloud.start_instances(self.context, [instance_id])
        greenthread.sleep(0.3)
        self.assertTrue(result)
        self._wait_for_running(instance_id)

        result = self.cloud.stop_instances(self.context, [instance_id])
        greenthread.sleep(0.3)
        self.assertTrue(result)
        self._wait_for_stopped(instance_id)

        result = self.cloud.terminate_instances(self.context, [instance_id])
        greenthread.sleep(0.3)
        self.assertTrue(result)

        self._restart_compute_service()

    def _volume_create(self, volume_id=None):
        kwargs = {'status': 'available',
                  'host': self.volume.host,
                  'size': 1,
                  'attach_status': 'detached', }
        if volume_id:
            kwargs['id'] = volume_id
        return db.volume_create(self.context, kwargs)

    def _assert_volume_attached(self, vol, instance_id, mountpoint):
        self.assertEqual(vol['instance_id'], instance_id)
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")

    def _assert_volume_detached(self, vol):
        self.assertEqual(vol['instance_id'], None)
        self.assertEqual(vol['mountpoint'], None)
        self.assertEqual(vol['status'], "available")
        self.assertEqual(vol['attach_status'], "detached")

    def test_stop_start_with_volume(self):
        """Make sure run instance with block device mapping works"""

        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval=0.3)

        vol1 = self._volume_create()
        vol2 = self._volume_create()
        kwargs = {'image_id': 'ami-1',
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1,
                  'block_device_mapping': [{'device_name': '/dev/vdb',
                                            'volume_id': vol1['id'],
                                            'delete_on_termination': False},
                                           {'device_name': '/dev/vdc',
                                            'volume_id': vol2['id'],
                                            'delete_on_termination': True},
                                           ]}
        ec2_instance_id = self._run_instance_wait(**kwargs)
        instance_id = ec2utils.ec2_id_to_id(ec2_instance_id)

        vols = db.volume_get_all_by_instance(self.context, instance_id)
        self.assertEqual(len(vols), 2)
        for vol in vols:
            self.assertTrue(vol['id'] == vol1['id'] or vol['id'] == vol2['id'])

        vol = db.volume_get(self.context, vol1['id'])
        self._assert_volume_attached(vol, instance_id, '/dev/vdb')

        vol = db.volume_get(self.context, vol2['id'])
        self._assert_volume_attached(vol, instance_id, '/dev/vdc')

        result = self.cloud.stop_instances(self.context, [ec2_instance_id])
        self.assertTrue(result)
        self._wait_for_stopped(ec2_instance_id)

        vol = db.volume_get(self.context, vol1['id'])
        self._assert_volume_detached(vol)
        vol = db.volume_get(self.context, vol2['id'])
        self._assert_volume_detached(vol)

        self.cloud.start_instances(self.context, [ec2_instance_id])
        self._wait_for_running(ec2_instance_id)
        vols = db.volume_get_all_by_instance(self.context, instance_id)
        self.assertEqual(len(vols), 2)
        for vol in vols:
            self.assertTrue(vol['id'] == vol1['id'] or vol['id'] == vol2['id'])
            self.assertTrue(vol['mountpoint'] == '/dev/vdb' or
                            vol['mountpoint'] == '/dev/vdc')
            self.assertEqual(vol['instance_id'], instance_id)
            self.assertEqual(vol['status'], "in-use")
            self.assertEqual(vol['attach_status'], "attached")

        self.cloud.terminate_instances(self.context, [ec2_instance_id])
        greenthread.sleep(0.3)

        admin_ctxt = context.get_admin_context(read_deleted=False)
        vol = db.volume_get(admin_ctxt, vol1['id'])
        self.assertFalse(vol['deleted'])
        db.volume_destroy(self.context, vol1['id'])

        greenthread.sleep(0.3)
        admin_ctxt = context.get_admin_context(read_deleted=True)
        vol = db.volume_get(admin_ctxt, vol2['id'])
        self.assertTrue(vol['deleted'])

        self._restart_compute_service()

    def test_stop_with_attached_volume(self):
        """Make sure attach info is reflected to block device mapping"""
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval=0.3)

        vol1 = self._volume_create()
        vol2 = self._volume_create()
        kwargs = {'image_id': 'ami-1',
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1,
                  'block_device_mapping': [{'device_name': '/dev/vdb',
                                            'volume_id': vol1['id'],
                                            'delete_on_termination': True}]}
        ec2_instance_id = self._run_instance_wait(**kwargs)
        instance_id = ec2utils.ec2_id_to_id(ec2_instance_id)

        vols = db.volume_get_all_by_instance(self.context, instance_id)
        self.assertEqual(len(vols), 1)
        for vol in vols:
            self.assertEqual(vol['id'], vol1['id'])
            self._assert_volume_attached(vol, instance_id, '/dev/vdb')

        vol = db.volume_get(self.context, vol2['id'])
        self._assert_volume_detached(vol)

        self.cloud.compute_api.attach_volume(self.context,
                                             instance_id=instance_id,
                                             volume_id=vol2['id'],
                                             device='/dev/vdc')
        greenthread.sleep(0.3)
        vol = db.volume_get(self.context, vol2['id'])
        self._assert_volume_attached(vol, instance_id, '/dev/vdc')

        self.cloud.compute_api.detach_volume(self.context,
                                             volume_id=vol1['id'])
        greenthread.sleep(0.3)
        vol = db.volume_get(self.context, vol1['id'])
        self._assert_volume_detached(vol)

        result = self.cloud.stop_instances(self.context, [ec2_instance_id])
        self.assertTrue(result)
        self._wait_for_stopped(ec2_instance_id)

        for vol_id in (vol1['id'], vol2['id']):
            vol = db.volume_get(self.context, vol_id)
            self._assert_volume_detached(vol)

        self.cloud.start_instances(self.context, [ec2_instance_id])
        self._wait_for_running(ec2_instance_id)
        vols = db.volume_get_all_by_instance(self.context, instance_id)
        self.assertEqual(len(vols), 1)
        for vol in vols:
            self.assertEqual(vol['id'], vol2['id'])
            self._assert_volume_attached(vol, instance_id, '/dev/vdc')

        vol = db.volume_get(self.context, vol1['id'])
        self._assert_volume_detached(vol)

        self.cloud.terminate_instances(self.context, [ec2_instance_id])
        greenthread.sleep(0.3)

        for vol_id in (vol1['id'], vol2['id']):
            vol = db.volume_get(self.context, vol_id)
            self.assertEqual(vol['id'], vol_id)
            self._assert_volume_detached(vol)
            db.volume_destroy(self.context, vol_id)

        self._restart_compute_service()

    def _create_snapshot(self, ec2_volume_id):
        result = self.cloud.create_snapshot(self.context,
                                            volume_id=ec2_volume_id)
        greenthread.sleep(0.3)
        return result['snapshotId']

    def test_run_with_snapshot(self):
        """Makes sure run/stop/start instance with snapshot works."""
        vol = self._volume_create()
        ec2_volume_id = ec2utils.id_to_ec2_vol_id(vol['id'])

        ec2_snapshot1_id = self._create_snapshot(ec2_volume_id)
        snapshot1_id = ec2utils.ec2_id_to_id(ec2_snapshot1_id)
        ec2_snapshot2_id = self._create_snapshot(ec2_volume_id)
        snapshot2_id = ec2utils.ec2_id_to_id(ec2_snapshot2_id)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1,
                  'block_device_mapping': [{'device_name': '/dev/vdb',
                                            'snapshot_id': snapshot1_id,
                                            'delete_on_termination': False, },
                                           {'device_name': '/dev/vdc',
                                            'snapshot_id': snapshot2_id,
                                            'delete_on_termination': True}]}
        ec2_instance_id = self._run_instance_wait(**kwargs)
        instance_id = ec2utils.ec2_id_to_id(ec2_instance_id)

        vols = db.volume_get_all_by_instance(self.context, instance_id)
        self.assertEqual(len(vols), 2)
        vol1_id = None
        vol2_id = None
        for vol in vols:
            snapshot_id = vol['snapshot_id']
            if snapshot_id == snapshot1_id:
                vol1_id = vol['id']
                mountpoint = '/dev/vdb'
            elif snapshot_id == snapshot2_id:
                vol2_id = vol['id']
                mountpoint = '/dev/vdc'
            else:
                self.fail()

            self._assert_volume_attached(vol, instance_id, mountpoint)

        self.assertTrue(vol1_id)
        self.assertTrue(vol2_id)

        self.cloud.terminate_instances(self.context, [ec2_instance_id])
        greenthread.sleep(0.3)
        self._wait_for_terminate(ec2_instance_id)

        greenthread.sleep(0.3)
        admin_ctxt = context.get_admin_context(read_deleted=False)
        vol = db.volume_get(admin_ctxt, vol1_id)
        self._assert_volume_detached(vol)
        self.assertFalse(vol['deleted'])
        db.volume_destroy(self.context, vol1_id)

        greenthread.sleep(0.3)
        admin_ctxt = context.get_admin_context(read_deleted=True)
        vol = db.volume_get(admin_ctxt, vol2_id)
        self.assertTrue(vol['deleted'])

        for snapshot_id in (ec2_snapshot1_id, ec2_snapshot2_id):
            self.cloud.delete_snapshot(self.context, snapshot_id)
            greenthread.sleep(0.3)
        db.volume_destroy(self.context, vol['id'])

    def test_create_image(self):
        """Make sure that CreateImage works"""
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval=0.3)

        (volumes, snapshots) = self._setUpImageSet(
            create_volumes_and_snapshots=True)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        ec2_instance_id = self._run_instance_wait(**kwargs)

        # TODO(yamahata): s3._s3_create() can't be tested easily by unit test
        #                 as there is no unit test for s3.create()
        ## result = self.cloud.create_image(self.context, ec2_instance_id,
        ##                                  no_reboot=True)
        ## ec2_image_id = result['imageId']
        ## created_image = self.cloud.describe_images(self.context,
        ##                                            [ec2_image_id])

        self.cloud.terminate_instances(self.context, [ec2_instance_id])
        for vol in volumes:
            db.volume_destroy(self.context, vol)
        for snap in snapshots:
            db.snapshot_destroy(self.context, snap)
        # TODO(yamahata): clean up snapshot created by CreateImage.

        self._restart_compute_service()

    @staticmethod
    def _fake_bdm_get(ctxt, id):
            return [{'volume_id': 87654321,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': None,
                     'delete_on_termination': True,
                     'device_name': '/dev/sdh'},
                    {'volume_id': None,
                     'snapshot_id': 98765432,
                     'no_device': None,
                     'virtual_name': None,
                     'delete_on_termination': True,
                     'device_name': '/dev/sdi'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': True,
                     'virtual_name': None,
                     'delete_on_termination': None,
                     'device_name': None},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'ephemeral0',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdb'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'swap',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdc'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'ephemeral1',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdd'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'ephemeral2',
                     'delete_on_termination': None,
                     'device_name': '/dev/sd3'},
                    ]

    def test_get_instance_mapping(self):
        """Make sure that _get_instance_mapping works"""
        ctxt = None
        instance_ref0 = {'id': 0,
                         'root_device_name': None}
        instance_ref1 = {'id': 0,
                         'root_device_name': '/dev/sda1'}

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       self._fake_bdm_get)

        expected = {'ami': 'sda1',
                    'root': '/dev/sda1',
                    'ephemeral0': '/dev/sdb',
                    'swap': '/dev/sdc',
                    'ephemeral1': '/dev/sdd',
                    'ephemeral2': '/dev/sd3',
                    'ebs0': '/dev/sdh',
                    'ebs1': '/dev/sdi'}

        self.assertEqual(self.cloud._format_instance_mapping(ctxt,
                                                             instance_ref0),
                         cloud._DEFAULT_MAPPINGS)
        self.assertEqual(self.cloud._format_instance_mapping(ctxt,
                                                             instance_ref1),
                         expected)

    def test_describe_instance_attribute(self):
        """Make sure that describe_instance_attribute works"""
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       self._fake_bdm_get)

        def fake_get(ctxt, instance_id):
            return {
                'id': 0,
                'root_device_name': '/dev/sdh',
                'security_groups': [{'name': 'fake0'}, {'name': 'fake1'}],
                'vm_state': vm_states.STOPPED,
                'instance_type': {'name': 'fake_type'},
                'kernel_id': 1,
                'ramdisk_id': 2,
                'user_data': 'fake-user data',
                }
        self.stubs.Set(self.cloud.compute_api, 'get', fake_get)

        def fake_volume_get(ctxt, volume_id, session=None):
            if volume_id == 87654321:
                return {'id': volume_id,
                        'attach_time': '13:56:24',
                        'status': 'in-use'}
            raise exception.VolumeNotFound(volume_id=volume_id)
        self.stubs.Set(db.api, 'volume_get', fake_volume_get)

        get_attribute = functools.partial(
            self.cloud.describe_instance_attribute,
            self.context, 'i-12345678')

        bdm = get_attribute('blockDeviceMapping')
        bdm['blockDeviceMapping'].sort()

        expected_bdm = {'instance_id': 'i-12345678',
                        'rootDeviceType': 'ebs',
                        'blockDeviceMapping': [
                            {'deviceName': '/dev/sdh',
                             'ebs': {'status': 'in-use',
                                     'deleteOnTermination': True,
                                     'volumeId': 87654321,
                                     'attachTime': '13:56:24'}}]}
        expected_bdm['blockDeviceMapping'].sort()
        self.assertEqual(bdm, expected_bdm)
        # NOTE(yamahata): this isn't supported
        # get_attribute('disableApiTermination')
        groupSet = get_attribute('groupSet')
        groupSet['groupSet'].sort()
        expected_groupSet = {'instance_id': 'i-12345678',
                             'groupSet': [{'groupId': 'fake0'},
                                          {'groupId': 'fake1'}]}
        expected_groupSet['groupSet'].sort()
        self.assertEqual(groupSet, expected_groupSet)
        self.assertEqual(get_attribute('instanceInitiatedShutdownBehavior'),
                         {'instance_id': 'i-12345678',
                          'instanceInitiatedShutdownBehavior': 'stopped'})
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

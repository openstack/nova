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

import copy
import uuid

import fixtures
from oslo.config import cfg

from nova.api.ec2 import cloud
from nova.api.ec2 import ec2utils
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import rpc
from nova import test
from nova.tests import fake_network
from nova.tests import fake_utils
from nova.tests.image import fake
from nova.tests import matchers
from nova import volume

CONF = cfg.CONF
CONF.import_opt('compute_driver', 'nova.virt.driver')
CONF.import_opt('default_flavor', 'nova.compute.flavors')
CONF.import_opt('use_ipv6', 'nova.netconf')


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


class CinderCloudTestCase(test.TestCase):
    def setUp(self):
        super(CinderCloudTestCase, self).setUp()
        ec2utils.reset_cache()
        vol_tmpdir = self.useFixture(fixtures.TempDir()).path
        fake_utils.stub_out_utils_spawn_n(self.stubs)
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   volume_api_class='nova.tests.fake_volume.API')

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
        self.volume_api.reset_fake_api(self.context)

        # NOTE(comstud): Make 'cast' behave like a 'call' which will
        # ensure that operations complete
        self.stubs.Set(rpc, 'cast', rpc.call)

        # make sure we can map ami-00000001/2 to a uuid in FakeImageService
        db.s3_image_create(self.context,
                               'cedef40a-ed67-4d10-800e-17455edce175')
        db.s3_image_create(self.context,
                               '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6')

    def tearDown(self):
        self.volume_api.reset_fake_api(self.context)
        super(CinderCloudTestCase, self).tearDown()
        fake.FakeImageService_reset()

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

    def test_describe_volumes(self):
        # Makes sure describe_volumes works and filters results.

        vol1 = self.cloud.create_volume(self.context,
                                        size=1,
                                        name='test-1',
                                        description='test volume 1')
        self.assertEqual(vol1['status'], 'available')
        vol2 = self.cloud.create_volume(self.context,
                                        size=1,
                                        name='test-2',
                                        description='test volume 2')
        result = self.cloud.describe_volumes(self.context)
        self.assertEqual(len(result['volumeSet']), 2)
        result = self.cloud.describe_volumes(self.context,
                                             [vol1['volumeId']])
        self.assertEqual(len(result['volumeSet']), 1)
        self.assertEqual(vol1['volumeId'], result['volumeSet'][0]['volumeId'])

        self.cloud.delete_volume(self.context, vol1['volumeId'])
        self.cloud.delete_volume(self.context, vol2['volumeId'])

    def test_format_volume_maps_status(self):
        fake_volume = {'id': 1,
                       'status': 'creating',
                       'availability_zone': 'nova',
                       'volumeId': 'vol-0000000a',
                       'attachmentSet': [{}],
                       'snapshotId': None,
                       'created_at': '2013-04-18T06:03:35.025626',
                       'size': 1,
                       'mountpoint': None,
                       'attach_status': None}

        self.assertEqual(self.cloud._format_volume(self.context,
                                                   fake_volume)['status'],
                                                   'creating')

        fake_volume['status'] = 'attaching'
        self.assertEqual(self.cloud._format_volume(self.context,
                                                   fake_volume)['status'],
                                                   'in-use')
        fake_volume['status'] = 'detaching'
        self.assertEqual(self.cloud._format_volume(self.context,
                                                   fake_volume)['status'],
                                                   'in-use')
        fake_volume['status'] = 'banana'
        self.assertEqual(self.cloud._format_volume(self.context,
                                                   fake_volume)['status'],
                                                   'banana')

    def test_create_volume_in_availability_zone(self):
        """Makes sure create_volume works when we specify an availability
        zone
        """
        availability_zone = 'zone1:host1'

        result = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        volume_id = result['volumeId']
        availabilityZone = result['availabilityZone']
        self.assertEqual(availabilityZone, availability_zone)
        result = self.cloud.describe_volumes(self.context)
        self.assertEqual(len(result['volumeSet']), 1)
        self.assertEqual(result['volumeSet'][0]['volumeId'], volume_id)
        self.assertEqual(result['volumeSet'][0]['availabilityZone'],
                         availabilityZone)

        self.cloud.delete_volume(self.context, volume_id)

    def test_create_volume_from_snapshot(self):
        # Makes sure create_volume works when we specify a snapshot.
        availability_zone = 'zone1:host1'
        vol1 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        snap = self.cloud.create_snapshot(self.context,
                                          vol1['volumeId'],
                                          name='snap-1',
                                          description='test snap of vol %s'
                                              % vol1['volumeId'])

        vol2 = self.cloud.create_volume(self.context,
                                        snapshot_id=snap['snapshotId'])
        volume1_id = vol1['volumeId']
        volume2_id = vol2['volumeId']

        result = self.cloud.describe_volumes(self.context)
        self.assertEqual(len(result['volumeSet']), 2)
        self.assertEqual(result['volumeSet'][1]['volumeId'], volume2_id)

        self.cloud.delete_volume(self.context, volume2_id)
        self.cloud.delete_snapshot(self.context, snap['snapshotId'])
        self.cloud.delete_volume(self.context, volume1_id)

    def test_describe_snapshots(self):
        # Makes sure describe_snapshots works and filters results.
        availability_zone = 'zone1:host1'
        vol1 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        snap1 = self.cloud.create_snapshot(self.context,
                                           vol1['volumeId'],
                                           name='snap-1',
                                           description='test snap1 of vol %s' %
                                              vol1['volumeId'])
        snap2 = self.cloud.create_snapshot(self.context,
                                           vol1['volumeId'],
                                           name='snap-1',
                                           description='test snap2 of vol %s' %
                                               vol1['volumeId'])

        result = self.cloud.describe_snapshots(self.context)
        self.assertEqual(len(result['snapshotSet']), 2)
        result = self.cloud.describe_snapshots(
           self.context,
           snapshot_id=[snap2['snapshotId']])
        self.assertEqual(len(result['snapshotSet']), 1)

        self.cloud.delete_snapshot(self.context, snap1['snapshotId'])
        self.cloud.delete_snapshot(self.context, snap2['snapshotId'])
        self.cloud.delete_volume(self.context, vol1['volumeId'])

    def test_format_snapshot_maps_status(self):
        fake_snapshot = {'status': 'new',
                         'id': 1,
                         'volume_id': 1,
                         'created_at': 1353560191.08117,
                         'progress': 90,
                         'project_id': str(uuid.uuid4()),
                         'volume_size': 10000,
                         'display_description': 'desc'}

        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot)['status'],
                         'pending')

        fake_snapshot['status'] = 'creating'
        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot)['status'],
                         'pending')

        fake_snapshot['status'] = 'available'
        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot)['status'],
                         'completed')

        fake_snapshot['status'] = 'active'
        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot)['status'],
                         'completed')

        fake_snapshot['status'] = 'deleting'
        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot)['status'],
                         'pending')

        fake_snapshot['status'] = 'deleted'
        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot), None)

        fake_snapshot['status'] = 'error'
        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot)['status'],
                         'error')

        fake_snapshot['status'] = 'banana'
        self.assertEqual(self.cloud._format_snapshot(self.context,
                                                     fake_snapshot)['status'],
                         'banana')

    def test_create_snapshot(self):
        # Makes sure create_snapshot works.
        availability_zone = 'zone1:host1'
        result = self.cloud.describe_snapshots(self.context)
        vol1 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        snap1 = self.cloud.create_snapshot(self.context,
                                           vol1['volumeId'],
                                           name='snap-1',
                                           description='test snap1 of vol %s' %
                                               vol1['volumeId'])

        snapshot_id = snap1['snapshotId']
        result = self.cloud.describe_snapshots(self.context)
        self.assertEqual(len(result['snapshotSet']), 1)
        self.assertEqual(result['snapshotSet'][0]['snapshotId'], snapshot_id)

        self.cloud.delete_snapshot(self.context, snap1['snapshotId'])
        self.cloud.delete_volume(self.context, vol1['volumeId'])

    def test_delete_snapshot(self):
        # Makes sure delete_snapshot works.
        availability_zone = 'zone1:host1'
        vol1 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        snap1 = self.cloud.create_snapshot(self.context,
                                           vol1['volumeId'],
                                           name='snap-1',
                                           description='test snap1 of vol %s' %
                                               vol1['volumeId'])

        snapshot_id = snap1['snapshotId']
        result = self.cloud.delete_snapshot(self.context,
                                            snapshot_id=snapshot_id)
        self.assertTrue(result)
        self.cloud.delete_volume(self.context, vol1['volumeId'])

    def _block_device_mapping_create(self, instance_uuid, mappings):
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
                    kwargs = {'name': 'bdmtest-volume',
                              'description': 'bdm test volume description',
                              'status': 'available',
                              'host': 'fake',
                              'size': 1,
                              'attach_status': 'detached',
                              'volume_id': values['id']}
                vol = self.volume_api.create_with_kwargs(self.context,
                                                        **kwargs)
                if 'snapshot_id' in values:
                    self.volume_api.create_snapshot(self.context,
                                                    vol['id'],
                                                    'snapshot-bdm',
                                                    'fake snap for bdm tests',
                                                    values['snapshot_id'])

                self.volume_api.attach(self.context, vol['id'],
                                       instance_uuid, bdm['device_name'])
                volumes.append(vol)
        return volumes

    def _setUpBlockDeviceMapping(self):
        image_uuid = 'cedef40a-ed67-4d10-800e-17455edce175'
        sys_meta = flavors.save_flavor_info(
            {}, flavors.get_flavor(1))
        inst1 = db.instance_create(self.context,
                                  {'image_ref': image_uuid,
                                   'instance_type_id': 1,
                                   'root_device_name': '/dev/sdb1',
                                   'system_metadata': sys_meta})
        inst2 = db.instance_create(self.context,
                                  {'image_ref': image_uuid,
                                   'instance_type_id': 1,
                                   'root_device_name': '/dev/sdc1',
                                   'system_metadata': sys_meta})

        instance_uuid = inst1['uuid']
        mappings0 = [
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb1',
             'snapshot_id': '1',
             'volume_id': '2'},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb2',
             'volume_id': '3',
             'volume_size': 1},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb3',
             'delete_on_termination': True,
             'snapshot_id': '4',
             'volume_id': '5'},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb4',
             'delete_on_termination': False,
             'snapshot_id': '6',
             'volume_id': '7'},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb5',
             'snapshot_id': '8',
             'volume_id': '9',
             'volume_size': 0},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb6',
             'snapshot_id': '10',
             'volume_id': '11',
             'volume_size': 1},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb7',
             'no_device': True},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb8',
             'virtual_name': 'swap'},
            {'instance_uuid': instance_uuid,
             'device_name': '/dev/sdb9',
             'virtual_name': 'ephemeral3'}]

        volumes = self._block_device_mapping_create(instance_uuid, mappings0)
        return (inst1, inst2, volumes)

    def _tearDownBlockDeviceMapping(self, inst1, inst2, volumes):
        for vol in volumes:
            self.volume_api.delete(self.context, vol['id'])
        for uuid in (inst1['uuid'], inst2['uuid']):
            for bdm in db.block_device_mapping_get_all_by_instance(
                    self.context, uuid):
                db.block_device_mapping_destroy(self.context, bdm['id'])
        db.instance_destroy(self.context, inst2['uuid'])
        db.instance_destroy(self.context, inst1['uuid'])

    _expected_instance_bdm1 = {
        'instanceId': 'i-00000001',
        'rootDeviceName': '/dev/sdb1',
        'rootDeviceType': 'ebs'}

    _expected_block_device_mapping0 = [
        {'deviceName': '/dev/sdb1',
         'ebs': {'status': 'attached',
                 'deleteOnTermination': False,
                 'volumeId': 'vol-00000002',
                 }},
        {'deviceName': '/dev/sdb2',
         'ebs': {'status': 'attached',
                 'deleteOnTermination': False,
                 'volumeId': 'vol-00000003',
                 }},
        {'deviceName': '/dev/sdb3',
         'ebs': {'status': 'attached',
                 'deleteOnTermination': True,
                 'volumeId': 'vol-00000005',
                 }},
        {'deviceName': '/dev/sdb4',
         'ebs': {'status': 'attached',
                 'deleteOnTermination': False,
                 'volumeId': 'vol-00000007',
                 }},
        {'deviceName': '/dev/sdb5',
         'ebs': {'status': 'attached',
                 'deleteOnTermination': False,
                 'volumeId': 'vol-00000009',
                 }},
        {'deviceName': '/dev/sdb6',
         'ebs': {'status': 'attached',
                 'deleteOnTermination': False,
                 'volumeId': 'vol-0000000b', }}]
        # NOTE(yamahata): swap/ephemeral device case isn't supported yet.

    _expected_instance_bdm2 = {
        'instanceId': 'i-00000002',
        'rootDeviceName': '/dev/sdc1',
        'rootDeviceType': 'instance-store'}

    def test_format_instance_bdm(self):
        (inst1, inst2, volumes) = self._setUpBlockDeviceMapping()

        result = {}
        self.cloud._format_instance_bdm(self.context, inst1['uuid'],
                                        '/dev/sdb1', result)
        self.assertThat(
            {'rootDeviceType': self._expected_instance_bdm1['rootDeviceType']},
            matchers.IsSubDictOf(result))
        self._assertEqualBlockDeviceMapping(
            self._expected_block_device_mapping0, result['blockDeviceMapping'])

        result = {}
        self.cloud._format_instance_bdm(self.context, inst2['uuid'],
                                        '/dev/sdc1', result)
        self.assertThat(
            {'rootDeviceType': self._expected_instance_bdm2['rootDeviceType']},
            matchers.IsSubDictOf(result))

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
                    self.assertThat(x, matchers.IsSubDictOf(y))
                    found = True
                    break
            self.assertTrue(found)

    def test_describe_instances_bdm(self):
        """Make sure describe_instances works with root_device_name and
        block device mappings
        """
        (inst1, inst2, volumes) = self._setUpBlockDeviceMapping()

        result = self._assertInstance(inst1['id'])
        self.assertThat(
            self._expected_instance_bdm1,
            matchers.IsSubDictOf(result))
        self._assertEqualBlockDeviceMapping(
            self._expected_block_device_mapping0, result['blockDeviceMapping'])

        result = self._assertInstance(inst2['id'])
        self.assertThat(
            self._expected_instance_bdm2,
            matchers.IsSubDictOf(result))

        self._tearDownBlockDeviceMapping(inst1, inst2, volumes)

    def _setUpImageSet(self, create_volumes_and_snapshots=False):
        self.flags(max_local_block_devices=-1)
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
            {'device_name': '/dev/sdb1', 'snapshot_id': 1234567},
            {'device_name': '/dev/sdb2', 'volume_id': 1234567},
            {'device_name': '/dev/sdb3', 'virtual_name': 'ephemeral5'},
            {'device_name': '/dev/sdb4', 'no_device': True},

            {'device_name': '/dev/sdc1', 'snapshot_id': 12345678},
            {'device_name': '/dev/sdc2', 'volume_id': 12345678},
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
                                  'snapshot_id': 1234567}]
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

        def fake_detail(meh, context):
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
                    kwargs = {'volume_id': 76543210,
                              'volume_size': 1,
                              'name': 'test-snap',
                              'description': 'test snap desc',
                              'snap_id': bdm['snapshot_id'],
                              'status': 'available'}
                    snap = self.volume_api.create_snapshot_with_kwargs(
                        self.context, **kwargs)
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

    def _run_instance(self, **kwargs):
        rv = self.cloud.run_instances(self.context, **kwargs)
        instance_id = rv['instancesSet'][0]['instanceId']
        return instance_id

    def _restart_compute_service(self, periodic_interval_max=None):
        """restart compute service. NOTE: fake driver forgets all instances."""
        self.compute.kill()
        if periodic_interval_max:
            self.compute = self.start_service(
                'compute', periodic_interval_max=periodic_interval_max)
        else:
            self.compute = self.start_service('compute')

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

    def _assert_volume_attached(self, vol, instance_uuid, mountpoint):
        self.assertEqual(vol['instance_uuid'], instance_uuid)
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")

    def _assert_volume_detached(self, vol):
        self.assertEqual(vol['instance_uuid'], None)
        self.assertEqual(vol['mountpoint'], None)
        self.assertEqual(vol['status'], "available")
        self.assertEqual(vol['attach_status'], "detached")

    def test_stop_start_with_volume(self):
        # Make sure run instance with block device mapping works.
        availability_zone = 'zone1:host1'
        vol1 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        vol2 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        vol1_uuid = ec2utils.ec2_vol_id_to_uuid(vol1['volumeId'])
        vol2_uuid = ec2utils.ec2_vol_id_to_uuid(vol2['volumeId'])
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval_max=0.3)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_flavor,
                  'max_count': 1,
                  'block_device_mapping': [{'device_name': '/dev/sdb',
                                            'volume_id': vol1_uuid,
                                            'delete_on_termination': False},
                                           {'device_name': '/dev/sdc',
                                            'volume_id': vol2_uuid,
                                            'delete_on_termination': True},
                                           ]}
        ec2_instance_id = self._run_instance(**kwargs)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(self.context,
                                                     ec2_instance_id)
        vols = self.volume_api.get_all(self.context)
        vols = [v for v in vols if v['instance_uuid'] == instance_uuid]

        self.assertEqual(len(vols), 2)
        for vol in vols:
            self.assertTrue(str(vol['id']) == str(vol1_uuid) or
                str(vol['id']) == str(vol2_uuid))
            if str(vol['id']) == str(vol1_uuid):
                self.volume_api.attach(self.context, vol['id'],
                                       instance_uuid, '/dev/sdb')
            elif str(vol['id']) == str(vol2_uuid):
                self.volume_api.attach(self.context, vol['id'],
                                       instance_uuid, '/dev/sdc')

        vol = self.volume_api.get(self.context, vol1_uuid)
        self._assert_volume_attached(vol, instance_uuid, '/dev/sdb')

        vol = self.volume_api.get(self.context, vol2_uuid)
        self._assert_volume_attached(vol, instance_uuid, '/dev/sdc')

        result = self.cloud.stop_instances(self.context, [ec2_instance_id])
        self.assertTrue(result)

        vol = self.volume_api.get(self.context, vol1_uuid)
        self._assert_volume_attached(vol, instance_uuid, '/dev/sdb')

        vol = self.volume_api.get(self.context, vol1_uuid)
        self._assert_volume_attached(vol, instance_uuid, '/dev/sdb')

        vol = self.volume_api.get(self.context, vol2_uuid)
        self._assert_volume_attached(vol, instance_uuid, '/dev/sdc')

        self.cloud.start_instances(self.context, [ec2_instance_id])
        vols = self.volume_api.get_all(self.context)
        vols = [v for v in vols if v['instance_uuid'] == instance_uuid]
        self.assertEqual(len(vols), 2)
        for vol in vols:
            self.assertTrue(str(vol['id']) == str(vol1_uuid) or
                            str(vol['id']) == str(vol2_uuid))
            self.assertTrue(vol['mountpoint'] == '/dev/sdb' or
                            vol['mountpoint'] == '/dev/sdc')
            self.assertEqual(vol['instance_uuid'], instance_uuid)
            self.assertEqual(vol['status'], "in-use")
            self.assertEqual(vol['attach_status'], "attached")

        #Here we puke...
        self.cloud.terminate_instances(self.context, [ec2_instance_id])

        admin_ctxt = context.get_admin_context(read_deleted="no")
        vol = self.volume_api.get(admin_ctxt, vol2_uuid)
        self.assertFalse(vol['deleted'])
        self.cloud.delete_volume(self.context, vol1['volumeId'])
        self._restart_compute_service()

    def test_stop_with_attached_volume(self):
        # Make sure attach info is reflected to block device mapping.

        availability_zone = 'zone1:host1'
        vol1 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        vol2 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)
        vol1_uuid = ec2utils.ec2_vol_id_to_uuid(vol1['volumeId'])
        vol2_uuid = ec2utils.ec2_vol_id_to_uuid(vol2['volumeId'])

        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval_max=0.3)
        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_flavor,
                  'max_count': 1,
                  'block_device_mapping': [{'device_name': '/dev/sdb',
                                            'volume_id': vol1_uuid,
                                            'delete_on_termination': True}]}
        ec2_instance_id = self._run_instance(**kwargs)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(self.context,
                                                     ec2_instance_id)

        vols = self.volume_api.get_all(self.context)
        vols = [v for v in vols if v['instance_uuid'] == instance_uuid]
        self.assertEqual(len(vols), 1)
        for vol in vols:
            self.assertEqual(vol['id'], vol1_uuid)
            self._assert_volume_attached(vol, instance_uuid, '/dev/sdb')
        vol = self.volume_api.get(self.context, vol2_uuid)
        self._assert_volume_detached(vol)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.cloud.compute_api.attach_volume(self.context,
                                             instance,
                                             volume_id=vol2_uuid,
                                             device='/dev/sdc')

        vol1 = self.volume_api.get(self.context, vol1_uuid)
        self._assert_volume_attached(vol1, instance_uuid, '/dev/sdb')

        vol2 = self.volume_api.get(self.context, vol2_uuid)
        self._assert_volume_attached(vol2, instance_uuid, '/dev/sdc')

        self.cloud.compute_api.detach_volume(self.context,
                                             instance, vol1)

        vol1 = self.volume_api.get(self.context, vol1_uuid)
        self._assert_volume_detached(vol1)

        result = self.cloud.stop_instances(self.context, [ec2_instance_id])
        self.assertTrue(result)

        vol2 = self.volume_api.get(self.context, vol2_uuid)
        self._assert_volume_attached(vol2, instance_uuid, '/dev/sdc')

        self.cloud.start_instances(self.context, [ec2_instance_id])
        vols = self.volume_api.get_all(self.context)
        vols = [v for v in vols if v['instance_uuid'] == instance_uuid]
        self.assertEqual(len(vols), 1)

        self._assert_volume_detached(vol1)

        vol1 = self.volume_api.get(self.context, vol1_uuid)
        self._assert_volume_detached(vol1)

        self.cloud.terminate_instances(self.context, [ec2_instance_id])

    def _create_snapshot(self, ec2_volume_id):
        result = self.cloud.create_snapshot(self.context,
                                            volume_id=ec2_volume_id)
        return result['snapshotId']

    def test_run_with_snapshot(self):
        # Makes sure run/stop/start instance with snapshot works.
        availability_zone = 'zone1:host1'
        vol1 = self.cloud.create_volume(self.context,
                                          size=1,
                                          availability_zone=availability_zone)

        snap1 = self.cloud.create_snapshot(self.context,
                                           vol1['volumeId'],
                                           name='snap-1',
                                           description='test snap of vol %s' %
                                               vol1['volumeId'])
        snap1_uuid = ec2utils.ec2_snap_id_to_uuid(snap1['snapshotId'])

        snap2 = self.cloud.create_snapshot(self.context,
                                           vol1['volumeId'],
                                           name='snap-2',
                                           description='test snap of vol %s' %
                                               vol1['volumeId'])
        snap2_uuid = ec2utils.ec2_snap_id_to_uuid(snap2['snapshotId'])

        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_flavor,
                  'max_count': 1,
                  'block_device_mapping': [{'device_name': '/dev/vdb',
                                            'snapshot_id': snap1_uuid,
                                            'delete_on_termination': False, },
                                           {'device_name': '/dev/vdc',
                                            'snapshot_id': snap2_uuid,
                                            'delete_on_termination': True}]}
        ec2_instance_id = self._run_instance(**kwargs)
        instance_uuid = ec2utils.ec2_inst_id_to_uuid(self.context,
                                                     ec2_instance_id)

        vols = self.volume_api.get_all(self.context)
        vols = [v for v in vols if v['instance_uuid'] == instance_uuid]

        self.assertEqual(len(vols), 2)

        vol1_id = None
        vol2_id = None
        for vol in vols:
            snapshot_uuid = vol['snapshot_id']
            if snapshot_uuid == snap1_uuid:
                vol1_id = vol['id']
                mountpoint = '/dev/vdb'
            elif snapshot_uuid == snap2_uuid:
                vol2_id = vol['id']
                mountpoint = '/dev/vdc'
            else:
                self.fail()

            self._assert_volume_attached(vol, instance_uuid, mountpoint)

        #Just make sure we found them
        self.assertTrue(vol1_id)
        self.assertTrue(vol2_id)

        self.cloud.terminate_instances(self.context, [ec2_instance_id])

        admin_ctxt = context.get_admin_context(read_deleted="no")
        vol = self.volume_api.get(admin_ctxt, vol1_id)
        self._assert_volume_detached(vol)
        self.assertFalse(vol['deleted'])
        #db.volume_destroy(self.context, vol1_id)

        ##admin_ctxt = context.get_admin_context(read_deleted="only")
        ##vol = db.volume_get(admin_ctxt, vol2_id)
        ##self.assertTrue(vol['deleted'])

        #for snapshot_id in (ec2_snapshot1_id, ec2_snapshot2_id):
        #    self.cloud.delete_snapshot(self.context, snapshot_id)

    def test_create_image(self):
        # Make sure that CreateImage works.
        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval_max=0.3)

        (volumes, snapshots) = self._setUpImageSet(
            create_volumes_and_snapshots=True)

        kwargs = {'image_id': 'ami-1',
                  'instance_type': CONF.default_flavor,
                  'max_count': 1}
        ec2_instance_id = self._run_instance(**kwargs)

        self.cloud.terminate_instances(self.context, [ec2_instance_id])
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

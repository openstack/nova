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
from nova import rpc
from nova import test
from nova import utils
from nova.auth import manager
from nova.api.ec2 import cloud
from nova.api.ec2 import ec2utils
from nova.image import local


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.cloud')


class CloudTestCase(test.TestCase):
    def setUp(self):
        super(CloudTestCase, self).setUp()
        self.flags(connection_type='fake')

        self.conn = rpc.Connection.instance()

        # set up our cloud
        self.cloud = cloud.CloudController()

        # set up services
        self.compute = self.start_service('compute')
        self.scheduter = self.start_service('scheduler')
        self.network = self.start_service('network')
        self.image_service = utils.import_object(FLAGS.image_service)

        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('admin', 'admin', 'admin', True)
        self.project = self.manager.create_project('proj', 'admin', 'proj')
        self.context = context.RequestContext(user=self.user,
                                              project=self.project)
        host = self.network.get_network_host(self.context.elevated())

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine', 'image_state': 'available'}}

        self.stubs.Set(local.LocalImageService, 'show', fake_show)
        self.stubs.Set(local.LocalImageService, 'show_by_name', fake_show)

        # NOTE(vish): set up a manual wait so rpc.cast has a chance to finish
        rpc_cast = rpc.cast

        def finish_cast(*args, **kwargs):
            rpc_cast(*args, **kwargs)
            greenthread.sleep(0.2)

        self.stubs.Set(rpc, 'cast', finish_cast)

    def tearDown(self):
        network_ref = db.project_get_network(self.context,
                                             self.project.id)
        db.network_disassociate(self.context, network_ref['id'])
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        super(CloudTestCase, self).tearDown()

    def _create_key(self, name):
        # NOTE(vish): create depends on pool, so just call helper directly
        return cloud._gen_key(self.context, self.context.user.id, name)

    def test_describe_regions(self):
        """Makes sure describe regions runs without raising an exception"""
        result = self.cloud.describe_regions(self.context)
        self.assertEqual(len(result['regionInfo']), 1)
        regions = FLAGS.region_list
        FLAGS.region_list = ["one=test_host1", "two=test_host2"]
        result = self.cloud.describe_regions(self.context)
        self.assertEqual(len(result['regionInfo']), 2)
        FLAGS.region_list = regions

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
        self.assertRaises(rpc.RemoteError, allocate, self.context)

    def test_associate_disassociate_address(self):
        """Verifies associate runs cleanly without raising an exception"""
        address = "10.10.10.10"
        db.floating_ip_create(self.context,
                              {'address': address,
                               'host': self.network.host})
        self.cloud.allocate_address(self.context)
        inst = db.instance_create(self.context, {'host': self.compute.host})
        fixed = self.network.allocate_fixed_ip(self.context, inst['id'])
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

    def test_describe_volumes(self):
        """Makes sure describe_volumes works and filters results."""
        vol1 = db.volume_create(self.context, {})
        vol2 = db.volume_create(self.context, {})
        result = self.cloud.describe_volumes(self.context)
        self.assertEqual(len(result['volumeSet']), 2)
        volume_id = ec2utils.id_to_ec2_id(vol2['id'], 'vol-%08x')
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
        snapshot_id = ec2utils.id_to_ec2_id(snap['id'], 'snap-%08x')

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
        snapshot_id = ec2utils.id_to_ec2_id(snap2['id'], 'snap-%08x')
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
        volume_id = ec2utils.id_to_ec2_id(vol['id'], 'vol-%08x')

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
        snapshot_id = ec2utils.id_to_ec2_id(snap['id'], 'snap-%08x')

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

    def test_describe_images(self):
        describe_images = self.cloud.describe_images

        def fake_detail(meh, context):
            return [{'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}}]

        def fake_show_none(meh, context, id):
            raise exception.ImageNotFound(image_id='bad_image_id')

        self.stubs.Set(local.LocalImageService, 'detail', fake_detail)
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
        self.stubs.Set(local.LocalImageService, 'show', fake_show_none)
        self.stubs.Set(local.LocalImageService, 'show_by_name', fake_show_none)
        self.assertRaises(exception.ImageNotFound, describe_images,
                          self.context, ['ami-fake'])

    def test_describe_image_attribute(self):
        describe_image_attribute = self.cloud.describe_image_attribute

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}, 'is_public': True}

        self.stubs.Set(local.LocalImageService, 'show', fake_show)
        self.stubs.Set(local.LocalImageService, 'show_by_name', fake_show)
        result = describe_image_attribute(self.context, 'ami-00000001',
                                          'launchPermission')
        self.assertEqual([{'group': 'all'}], result['launchPermission'])

    def test_modify_image_attribute(self):
        modify_image_attribute = self.cloud.modify_image_attribute

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}, 'is_public': False}

        def fake_update(meh, context, image_id, metadata, data=None):
            return metadata

        self.stubs.Set(local.LocalImageService, 'show', fake_show)
        self.stubs.Set(local.LocalImageService, 'show_by_name', fake_show)
        self.stubs.Set(local.LocalImageService, 'update', fake_update)
        result = modify_image_attribute(self.context, 'ami-00000001',
                                          'launchPermission', 'add',
                                           user_group=['all'])
        self.assertEqual(True, result['is_public'])

    def test_deregister_image(self):
        deregister_image = self.cloud.deregister_image

        def fake_delete(self, context, id):
            return None

        self.stubs.Set(local.LocalImageService, 'delete', fake_delete)
        # valid image
        result = deregister_image(self.context, 'ami-00000001')
        self.assertEqual(result['imageId'], 'ami-00000001')
        # invalid image
        self.stubs.UnsetAll()

        def fake_detail_empty(self, context):
            return []

        self.stubs.Set(local.LocalImageService, 'detail', fake_detail_empty)
        self.assertRaises(exception.ImageNotFound, deregister_image,
                          self.context, 'ami-bad001')

    def test_console_output(self):
        instance_type = FLAGS.default_instance_type
        max_count = 1
        kwargs = {'image_id': 'ami-1',
                  'instance_type': instance_type,
                  'max_count': max_count}
        rv = self.cloud.run_instances(self.context, **kwargs)
        instance_id = rv['instancesSet'][0]['instanceId']
        output = self.cloud.get_console_output(context=self.context,
                                               instance_id=[instance_id])
        self.assertEquals(b64decode(output['output']), 'FAKE CONSOLE?OUTPUT')
        # TODO(soren): We need this until we can stop polling in the rpc code
        #              for unit tests.
        rv = self.cloud.terminate_instances(self.context, [instance_id])

    def test_ajax_console(self):
        kwargs = {'image_id': 'ami-1'}
        rv = self.cloud.run_instances(self.context, **kwargs)
        instance_id = rv['instancesSet'][0]['instanceId']
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
                                    self.context.user.id,
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
                                  self.context.user.id,
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
                                  self.context.user.id,
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
        self.assertEqual(instance['instanceState']['name'], 'networking')
        self.assertEqual(instance['instanceType'], 'm1.small')

    def test_run_instances_image_state_none(self):
        kwargs = {'image_id': FLAGS.default_image,
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_no_state(self, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}}

        self.stubs.UnsetAll()
        self.stubs.Set(local.LocalImageService, 'show', fake_show_no_state)
        self.assertRaises(exception.ApiError, run_instances,
                          self.context, **kwargs)

    def test_run_instances_image_state_invalid(self):
        kwargs = {'image_id': FLAGS.default_image,
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_decrypt(self, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine', 'image_state': 'decrypting'}}

        self.stubs.UnsetAll()
        self.stubs.Set(local.LocalImageService, 'show', fake_show_decrypt)
        self.assertRaises(exception.ApiError, run_instances,
                          self.context, **kwargs)

    def test_run_instances_image_status_active(self):
        kwargs = {'image_id': FLAGS.default_image,
                  'instance_type': FLAGS.default_instance_type,
                  'max_count': 1}
        run_instances = self.cloud.run_instances

        def fake_show_stat_active(self, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1,
                    'type': 'machine'}, 'status': 'active'}

        self.stubs.Set(local.LocalImageService, 'show', fake_show_stat_active)

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
        self.cloud.update_instance(self.context, inst['id'],
                                   mac_address='DE:AD:BE:EF')
        inst = db.instance_get(self.context, inst['id'])
        self.assertEqual(None, inst['mac_address'])
        db.instance_destroy(self.context, inst['id'])

    def test_update_of_volume_display_fields(self):
        vol = db.volume_create(self.context, {})
        self.cloud.update_volume(self.context,
                                 ec2utils.id_to_ec2_id(vol['id'], 'vol-%08x'),
                                 display_name='c00l v0lum3')
        vol = db.volume_get(self.context, vol['id'])
        self.assertEqual('c00l v0lum3', vol['display_name'])
        db.volume_destroy(self.context, vol['id'])

    def test_update_of_volume_wont_update_private_fields(self):
        vol = db.volume_create(self.context, {})
        self.cloud.update_volume(self.context,
                                 ec2utils.id_to_ec2_id(vol['id'], 'vol-%08x'),
                                 mountpoint='/not/here')
        vol = db.volume_get(self.context, vol['id'])
        self.assertEqual(None, vol['mountpoint'])
        db.volume_destroy(self.context, vol['id'])

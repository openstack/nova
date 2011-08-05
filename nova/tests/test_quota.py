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

from nova import compute
from nova import context
from nova import db
from nova import flags
from nova import quota
from nova import test
from nova import volume
from nova.compute import instance_types


FLAGS = flags.FLAGS


class QuotaTestCase(test.TestCase):

    class StubImageService(object):

        def show(self, *args, **kwargs):
            return {"properties": {}}

    def setUp(self):
        super(QuotaTestCase, self).setUp()
        self.flags(connection_type='fake',
                   quota_instances=2,
                   quota_cores=4,
                   quota_volumes=2,
                   quota_gigabytes=20,
                   quota_floating_ips=1)

        self.network = self.network = self.start_service('network')
        self.user_id = 'admin'
        self.project_id = 'admin'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              True)

    def _create_instance(self, cores=2):
        """Create a test instance"""
        inst = {}
        inst['image_id'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['instance_type_id'] = '3'  # m1.large
        inst['vcpus'] = cores
        return db.instance_create(self.context, inst)['id']

    def _create_volume(self, size=10):
        """Create a test volume"""
        vol = {}
        vol['user_id'] = self.user_id
        vol['project_id'] = self.project_id
        vol['size'] = size
        return db.volume_create(self.context, vol)['id']

    def _get_instance_type(self, name):
        instance_types = {
            'm1.tiny': dict(memory_mb=512, vcpus=1, local_gb=0, flavorid=1),
            'm1.small': dict(memory_mb=2048, vcpus=1, local_gb=20, flavorid=2),
            'm1.medium':
                dict(memory_mb=4096, vcpus=2, local_gb=40, flavorid=3),
            'm1.large': dict(memory_mb=8192, vcpus=4, local_gb=80, flavorid=4),
            'm1.xlarge':
                dict(memory_mb=16384, vcpus=8, local_gb=160, flavorid=5)}
        return instance_types[name]

    def test_quota_overrides(self):
        """Make sure overriding a projects quotas works"""
        num_instances = quota.allowed_instances(self.context, 100,
            self._get_instance_type('m1.small'))
        self.assertEqual(num_instances, 2)
        db.quota_create(self.context, self.project_id, 'instances', 10)
        num_instances = quota.allowed_instances(self.context, 100,
            self._get_instance_type('m1.small'))
        self.assertEqual(num_instances, 4)
        db.quota_create(self.context, self.project_id, 'cores', 100)
        num_instances = quota.allowed_instances(self.context, 100,
            self._get_instance_type('m1.small'))
        self.assertEqual(num_instances, 10)
        db.quota_create(self.context, self.project_id, 'ram', 3 * 2048)
        num_instances = quota.allowed_instances(self.context, 100,
            self._get_instance_type('m1.small'))
        self.assertEqual(num_instances, 3)

        # metadata_items
        too_many_items = FLAGS.quota_metadata_items + 1000
        num_metadata_items = quota.allowed_metadata_items(self.context,
                                                          too_many_items)
        self.assertEqual(num_metadata_items, FLAGS.quota_metadata_items)
        db.quota_create(self.context, self.project_id, 'metadata_items', 5)
        num_metadata_items = quota.allowed_metadata_items(self.context,
                                                          too_many_items)
        self.assertEqual(num_metadata_items, 5)

        # Cleanup
        db.quota_destroy_all_by_project(self.context, self.project_id)

    def test_unlimited_instances(self):
        self.flags(quota_instances=2, quota_ram=-1, quota_cores=-1)
        instance_type = self._get_instance_type('m1.small')
        num_instances = quota.allowed_instances(self.context, 100,
                                                instance_type)
        self.assertEqual(num_instances, 2)
        db.quota_create(self.context, self.project_id, 'instances', None)
        num_instances = quota.allowed_instances(self.context, 100,
                                                instance_type)
        self.assertEqual(num_instances, 100)
        num_instances = quota.allowed_instances(self.context, 101,
                                                instance_type)
        self.assertEqual(num_instances, 101)

    def test_unlimited_ram(self):
        self.flags(quota_instances=-1, quota_ram=2 * 2048, quota_cores=-1)
        instance_type = self._get_instance_type('m1.small')
        num_instances = quota.allowed_instances(self.context, 100,
                                                instance_type)
        self.assertEqual(num_instances, 2)
        db.quota_create(self.context, self.project_id, 'ram', None)
        num_instances = quota.allowed_instances(self.context, 100,
                                                instance_type)
        self.assertEqual(num_instances, 100)
        num_instances = quota.allowed_instances(self.context, 101,
                                                instance_type)
        self.assertEqual(num_instances, 101)

    def test_unlimited_cores(self):
        self.flags(quota_instances=-1, quota_ram=-1, quota_cores=2)
        instance_type = self._get_instance_type('m1.small')
        num_instances = quota.allowed_instances(self.context, 100,
                                                instance_type)
        self.assertEqual(num_instances, 2)
        db.quota_create(self.context, self.project_id, 'cores', None)
        num_instances = quota.allowed_instances(self.context, 100,
                                                instance_type)
        self.assertEqual(num_instances, 100)
        num_instances = quota.allowed_instances(self.context, 101,
                                                instance_type)
        self.assertEqual(num_instances, 101)

    def test_unlimited_volumes(self):
        self.flags(quota_volumes=10, quota_gigabytes=-1)
        volumes = quota.allowed_volumes(self.context, 100, 1)
        self.assertEqual(volumes, 10)
        db.quota_create(self.context, self.project_id, 'volumes', None)
        volumes = quota.allowed_volumes(self.context, 100, 1)
        self.assertEqual(volumes, 100)
        volumes = quota.allowed_volumes(self.context, 101, 1)
        self.assertEqual(volumes, 101)

    def test_unlimited_gigabytes(self):
        self.flags(quota_volumes=-1, quota_gigabytes=10)
        volumes = quota.allowed_volumes(self.context, 100, 1)
        self.assertEqual(volumes, 10)
        db.quota_create(self.context, self.project_id, 'gigabytes', None)
        volumes = quota.allowed_volumes(self.context, 100, 1)
        self.assertEqual(volumes, 100)
        volumes = quota.allowed_volumes(self.context, 101, 1)
        self.assertEqual(volumes, 101)

    def test_unlimited_floating_ips(self):
        self.flags(quota_floating_ips=10)
        floating_ips = quota.allowed_floating_ips(self.context, 100)
        self.assertEqual(floating_ips, 10)
        db.quota_create(self.context, self.project_id, 'floating_ips', None)
        floating_ips = quota.allowed_floating_ips(self.context, 100)
        self.assertEqual(floating_ips, 100)
        floating_ips = quota.allowed_floating_ips(self.context, 101)
        self.assertEqual(floating_ips, 101)

    def test_unlimited_metadata_items(self):
        self.flags(quota_metadata_items=10)
        items = quota.allowed_metadata_items(self.context, 100)
        self.assertEqual(items, 10)
        db.quota_create(self.context, self.project_id, 'metadata_items', None)
        items = quota.allowed_metadata_items(self.context, 100)
        self.assertEqual(items, 100)
        items = quota.allowed_metadata_items(self.context, 101)
        self.assertEqual(items, 101)

    def test_too_many_instances(self):
        instance_ids = []
        for i in range(FLAGS.quota_instances):
            instance_id = self._create_instance()
            instance_ids.append(instance_id)
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        self.assertRaises(quota.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type=inst_type,
                                            image_href=1)
        for instance_id in instance_ids:
            db.instance_destroy(self.context, instance_id)

    def test_too_many_cores(self):
        instance_ids = []
        instance_id = self._create_instance(cores=4)
        instance_ids.append(instance_id)
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        self.assertRaises(quota.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type=inst_type,
                                            image_href=1)
        for instance_id in instance_ids:
            db.instance_destroy(self.context, instance_id)

    def test_too_many_volumes(self):
        volume_ids = []
        for i in range(FLAGS.quota_volumes):
            volume_id = self._create_volume()
            volume_ids.append(volume_id)
        self.assertRaises(quota.QuotaError,
                          volume.API().create,
                          self.context,
                          size=10,
                          snapshot_id=None,
                          name='',
                          description='')
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)

    def test_too_many_gigabytes(self):
        volume_ids = []
        volume_id = self._create_volume(size=20)
        volume_ids.append(volume_id)
        self.assertRaises(quota.QuotaError,
                          volume.API().create,
                          self.context,
                          size=10,
                          snapshot_id=None,
                          name='',
                          description='')
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)

    def test_too_many_addresses(self):
        address = '192.168.0.100'
        db.floating_ip_create(context.get_admin_context(),
                              {'address': address,
                               'project_id': self.project_id})
        self.assertRaises(quota.QuotaError,
                          self.network.allocate_floating_ip,
                          self.context,
                          self.project_id)
        db.floating_ip_destroy(context.get_admin_context(), address)

    def test_too_many_metadata_items(self):
        metadata = {}
        for i in range(FLAGS.quota_metadata_items + 1):
            metadata['key%s' % i] = 'value%s' % i
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        self.assertRaises(quota.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type=inst_type,
                                            image_href='fake',
                                            metadata=metadata)

    def test_default_allowed_injected_files(self):
        self.flags(quota_max_injected_files=55)
        self.assertEqual(quota.allowed_injected_files(self.context, 100), 55)

    def test_overridden_allowed_injected_files(self):
        self.flags(quota_max_injected_files=5)
        db.quota_create(self.context, self.project_id, 'injected_files', 77)
        self.assertEqual(quota.allowed_injected_files(self.context, 100), 77)

    def test_unlimited_default_allowed_injected_files(self):
        self.flags(quota_max_injected_files=-1)
        self.assertEqual(quota.allowed_injected_files(self.context, 100), 100)

    def test_unlimited_db_allowed_injected_files(self):
        self.flags(quota_max_injected_files=5)
        db.quota_create(self.context, self.project_id, 'injected_files', None)
        self.assertEqual(quota.allowed_injected_files(self.context, 100), 100)

    def test_default_allowed_injected_file_content_bytes(self):
        self.flags(quota_max_injected_file_content_bytes=12345)
        limit = quota.allowed_injected_file_content_bytes(self.context, 23456)
        self.assertEqual(limit, 12345)

    def test_overridden_allowed_injected_file_content_bytes(self):
        self.flags(quota_max_injected_file_content_bytes=12345)
        db.quota_create(self.context, self.project_id,
                        'injected_file_content_bytes', 5678)
        limit = quota.allowed_injected_file_content_bytes(self.context, 23456)
        self.assertEqual(limit, 5678)

    def test_unlimited_default_allowed_injected_file_content_bytes(self):
        self.flags(quota_max_injected_file_content_bytes=-1)
        limit = quota.allowed_injected_file_content_bytes(self.context, 23456)
        self.assertEqual(limit, 23456)

    def test_unlimited_db_allowed_injected_file_content_bytes(self):
        self.flags(quota_max_injected_file_content_bytes=12345)
        db.quota_create(self.context, self.project_id,
                        'injected_file_content_bytes', None)
        limit = quota.allowed_injected_file_content_bytes(self.context, 23456)
        self.assertEqual(limit, 23456)

    def _create_with_injected_files(self, files):
        self.flags(image_service='nova.image.fake.FakeImageService')
        api = compute.API(image_service=self.StubImageService())
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        api.create(self.context, min_count=1, max_count=1,
                instance_type=inst_type, image_href='3',
                injected_files=files)

    def test_no_injected_files(self):
        self.flags(image_service='nova.image.fake.FakeImageService')
        api = compute.API(image_service=self.StubImageService())
        inst_type = instance_types.get_instance_type_by_name('m1.small')
        api.create(self.context, instance_type=inst_type, image_href='3')

    def test_max_injected_files(self):
        files = []
        for i in xrange(FLAGS.quota_max_injected_files):
            files.append(('/my/path%d' % i, 'config = test\n'))
        self._create_with_injected_files(files)  # no QuotaError

    def test_too_many_injected_files(self):
        files = []
        for i in xrange(FLAGS.quota_max_injected_files + 1):
            files.append(('/my/path%d' % i, 'my\ncontent%d\n' % i))
        self.assertRaises(quota.QuotaError,
                          self._create_with_injected_files, files)

    def test_max_injected_file_content_bytes(self):
        max = FLAGS.quota_max_injected_file_content_bytes
        content = ''.join(['a' for i in xrange(max)])
        files = [('/test/path', content)]
        self._create_with_injected_files(files)  # no QuotaError

    def test_too_many_injected_file_content_bytes(self):
        max = FLAGS.quota_max_injected_file_content_bytes
        content = ''.join(['a' for i in xrange(max + 1)])
        files = [('/test/path', content)]
        self.assertRaises(quota.QuotaError,
                          self._create_with_injected_files, files)

    def test_allowed_injected_file_path_bytes(self):
        self.assertEqual(
                quota.allowed_injected_file_path_bytes(self.context),
                FLAGS.quota_max_injected_file_path_bytes)

    def test_max_injected_file_path_bytes(self):
        max = FLAGS.quota_max_injected_file_path_bytes
        path = ''.join(['a' for i in xrange(max)])
        files = [(path, 'config = quotatest')]
        self._create_with_injected_files(files)  # no QuotaError

    def test_too_many_injected_file_path_bytes(self):
        max = FLAGS.quota_max_injected_file_path_bytes
        path = ''.join(['a' for i in xrange(max + 1)])
        files = [(path, 'config = quotatest')]
        self.assertRaises(quota.QuotaError,
                          self._create_with_injected_files, files)

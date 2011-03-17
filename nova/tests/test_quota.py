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
from nova import network
from nova import quota
from nova import test
from nova import utils
from nova import volume
from nova.auth import manager
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

        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('admin', 'admin', 'admin', True)
        self.project = self.manager.create_project('admin', 'admin', 'admin')
        self.network = utils.import_object(FLAGS.network_manager)
        self.context = context.RequestContext(project=self.project,
                                              user=self.user)

    def tearDown(self):
        manager.AuthManager().delete_project(self.project)
        manager.AuthManager().delete_user(self.user)
        super(QuotaTestCase, self).tearDown()

    def _create_instance(self, cores=2):
        """Create a test instance"""
        inst = {}
        inst['image_id'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user.id
        inst['project_id'] = self.project.id
        inst['instance_type'] = 'm1.large'
        inst['vcpus'] = cores
        inst['mac_address'] = utils.generate_mac()
        return db.instance_create(self.context, inst)['id']

    def _create_volume(self, size=10):
        """Create a test volume"""
        vol = {}
        vol['user_id'] = self.user.id
        vol['project_id'] = self.project.id
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
        db.quota_create(self.context, {'project_id': self.project.id,
                                       'instances': 10})
        num_instances = quota.allowed_instances(self.context, 100,
            self._get_instance_type('m1.small'))
        self.assertEqual(num_instances, 4)
        db.quota_update(self.context, self.project.id, {'cores': 100})
        num_instances = quota.allowed_instances(self.context, 100,
            self._get_instance_type('m1.small'))
        self.assertEqual(num_instances, 10)

        # metadata_items
        too_many_items = FLAGS.quota_metadata_items + 1000
        num_metadata_items = quota.allowed_metadata_items(self.context,
                                                          too_many_items)
        self.assertEqual(num_metadata_items, FLAGS.quota_metadata_items)
        db.quota_update(self.context, self.project.id, {'metadata_items': 5})
        num_metadata_items = quota.allowed_metadata_items(self.context,
                                                          too_many_items)
        self.assertEqual(num_metadata_items, 5)

        # Cleanup
        db.quota_destroy(self.context, self.project.id)

    def test_too_many_instances(self):
        instance_ids = []
        for i in range(FLAGS.quota_instances):
            instance_id = self._create_instance()
            instance_ids.append(instance_id)
        self.assertRaises(quota.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type='m1.small',
                                            image_id=1)
        for instance_id in instance_ids:
            db.instance_destroy(self.context, instance_id)

    def test_too_many_cores(self):
        instance_ids = []
        instance_id = self._create_instance(cores=4)
        instance_ids.append(instance_id)
        self.assertRaises(quota.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type='m1.small',
                                            image_id=1)
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
                          name='',
                          description='')
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)

    def test_too_many_addresses(self):
        address = '192.168.0.100'
        db.floating_ip_create(context.get_admin_context(),
                              {'address': address, 'host': FLAGS.host})
        float_addr = self.network.allocate_floating_ip(self.context,
                                                       self.project.id)
        # NOTE(vish): This assert never fails. When cloud attempts to
        #             make an rpc.call, the test just finishes with OK. It
        #             appears to be something in the magic inline callbacks
        #             that is breaking.
        self.assertRaises(quota.QuotaError,
                          network.API().allocate_floating_ip,
                          self.context)
        db.floating_ip_destroy(context.get_admin_context(), address)

    def test_too_many_metadata_items(self):
        metadata = {}
        for i in range(FLAGS.quota_metadata_items + 1):
            metadata['key%s' % i] = 'value%s' % i
        self.assertRaises(quota.QuotaError, compute.API().create,
                                            self.context,
                                            min_count=1,
                                            max_count=1,
                                            instance_type='m1.small',
                                            image_id='fake',
                                            metadata=metadata)

    def test_allowed_injected_files(self):
        self.assertEqual(
                quota.allowed_injected_files(self.context),
                FLAGS.quota_max_injected_files)

    def _create_with_injected_files(self, files):
        api = compute.API(image_service=self.StubImageService())
        api.create(self.context, min_count=1, max_count=1,
                instance_type='m1.small', image_id='fake',
                injected_files=files)

    def test_no_injected_files(self):
        api = compute.API(image_service=self.StubImageService())
        api.create(self.context, instance_type='m1.small', image_id='fake')

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

    def test_allowed_injected_file_content_bytes(self):
        self.assertEqual(
                quota.allowed_injected_file_content_bytes(self.context),
                FLAGS.quota_max_injected_file_content_bytes)

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

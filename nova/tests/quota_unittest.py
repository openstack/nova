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

import logging

from nova import db
from nova import flags
from nova import quota
from nova import test
from nova import utils
from nova.auth import manager
from nova.endpoint import cloud
from nova.endpoint import api


FLAGS = flags.FLAGS


class QuotaTestCase(test.TrialTestCase):
    def setUp(self):  # pylint: disable-msg=C0103
        logging.getLogger().setLevel(logging.DEBUG)
        super(QuotaTestCase, self).setUp()
        self.flags(connection_type='fake',
                   quota_instances=2,
                   quota_cores=4,
                   quota_volumes=2,
                   quota_gigabytes=20,
                   quota_floating_ips=2)

        self.cloud = cloud.CloudController()
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('admin', 'admin', 'admin', True)
        self.project = self.manager.create_project('admin', 'admin', 'admin')
        self.context = api.APIRequestContext(handler=None,
                                             project=self.project,
                                             user=self.user)

    def tearDown(self):  # pylint: disable-msg=C0103
        manager.AuthManager().delete_project(self.project)
        manager.AuthManager().delete_user(self.user)
        super(QuotaTestCase, self).tearDown()

    def _create_instance(self, cores=2):
        """Create a test instance"""
        inst = {}
        inst['image_id'] = 'ami-test'
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user.id
        inst['project_id'] = self.project.id
        inst['instance_type'] = 'm1.large'
        inst['vcpus'] = cores
        inst['mac_address'] = utils.generate_mac()
        return db.instance_create(self.context, inst)

    def _create_volume(self, size=10):
        """Create a test volume"""
        vol = {}
        vol['user_id'] = self.user.id
        vol['project_id'] = self.project.id
        vol['size'] = size
        return db.volume_create(self.context, vol)['id']

    def test_quota_overrides(self):
        """Make sure overriding a projects quotas works"""
        num_instances = quota.allowed_instances(self.context, 100, 'm1.small')
        self.assertEqual(num_instances, 2)
        db.quota_create(self.context, {'project_id': self.project.id,
                                       'instances': 10})
        num_instances = quota.allowed_instances(self.context, 100, 'm1.small')
        self.assertEqual(num_instances, 4)
        db.quota_update(self.context, self.project.id, {'cores': 100})
        num_instances = quota.allowed_instances(self.context, 100, 'm1.small')
        self.assertEqual(num_instances, 10)
        db.quota_destroy(self.context, self.project.id)

    def test_too_many_instances(self):
        instance_ids = []
        for i in range(FLAGS.quota_instances):
            instance_id = self._create_instance()
            instance_ids.append(instance_id)
        self.assertFailure(self.cloud.run_instances(self.context,
                                                    min_count=1,
                                                    max_count=1,
                                                    instance_type='m1.small'),
                           cloud.QuotaError)
        for instance_id in instance_ids:
            db.instance_destroy(self.context, instance_id)

    def test_too_many_cores(self):
        instance_ids = []
        instance_id = self._create_instance(cores=4)
        instance_ids.append(instance_id)
        self.assertFailure(self.cloud.run_instances(self.context,
                                                    min_count=1,
                                                    max_count=1,
                                                    instance_type='m1.small'),
                           cloud.QuotaError)
        for instance_id in instance_ids:
            db.instance_destroy(self.context, instance_id)

    def test_too_many_volumes(self):
        volume_ids = []
        for i in range(FLAGS.quota_volumes):
            volume_id = self._create_volume()
            volume_ids.append(volume_id)
        self.assertRaises(cloud.QuotaError,
                          self.cloud.create_volume,
                          self.context,
                          size=10)
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)


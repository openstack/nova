# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

"""Tests For miscellaneous util methods used with volume."""

from nova import context
from nova import db
from nova import flags
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier_api
from nova.openstack.common.notifier import test_notifier
from nova import test
from nova.tests import fake_network
from nova.volume import utils as volume_utils


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class UsageInfoTestCase(test.TestCase):

    def setUp(self):
        super(UsageInfoTestCase, self).setUp()
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   host='fake',
                   notification_driver=[test_notifier.__name__])
        fake_network.set_stub_network_methods(self.stubs)

        self.volume = importutils.import_object(FLAGS.volume_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.snapshot_id = 'fake'
        self.volume_size = 0
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []

    def tearDown(self):
        notifier_api._reset_drivers()
        super(UsageInfoTestCase, self).tearDown()

    def _create_volume(self, params={}):
        """Create a test volume"""
        vol = {}
        vol['snapshot_id'] = self.snapshot_id
        vol['user_id'] = self.user_id
        vol['project_id'] = self.project_id
        vol['host'] = FLAGS.host
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        vol['size'] = self.volume_size
        vol.update(params)
        return db.volume_create(self.context, vol)['id']

    def test_notify_usage_exists(self):
        """Ensure 'exists' notification generates appropriate usage data."""
        volume_id = self._create_volume()
        volume = db.volume_get(self.context, volume_id)
        volume_utils.notify_usage_exists(self.context, volume)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'volume.exists')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['snapshot_id'], self.snapshot_id)
        self.assertEquals(payload['volume_id'], volume.id)
        self.assertEquals(payload['size'], self.volume_size)
        for attr in ('display_name', 'created_at', 'launched_at',
                     'status', 'audit_period_beginning',
                     'audit_period_ending'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        db.volume_destroy(context.get_admin_context(), volume['id'])

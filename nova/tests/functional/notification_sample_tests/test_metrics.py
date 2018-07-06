#    Copyright 2018 NTT Corporation
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

import nova.conf
from nova import context
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit import fake_notifier


CONF = nova.conf.CONF


class TestMetricsNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(compute_monitors=['cpu.virt_driver'])
        super(TestMetricsNotificationSample, self).setUp()
        # Reset the cpu stats of the 'cpu.virt_driver' monitor
        self.compute.manager._resource_tracker.monitors[0]._cpu_stats = {}

    def test_metrics_update(self):
        self.compute.manager.update_available_resource(
            context.get_admin_context())

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'metrics-update',
            replacements={'host_ip': CONF.my_ip},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])

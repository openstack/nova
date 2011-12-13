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

import nova.db.api
from nova.notifier import capacity_notifier as cn
from nova import test
from nova import utils


class CapacityNotifierTestCase(test.TestCase):
    """Test case for the Capacity updating notifier."""

    def _make_msg(self, host, event):
        usage_info = dict(memory_mb=123, disk_gb=456)
        payload = utils.to_primitive(usage_info, convert_instances=True)
        return dict(
            publisher_id="compute.%s" % host,
            event_type="compute.instance.%s" % event,
            payload=payload
        )

    def test_event_type(self):
        msg = self._make_msg("myhost", "mymethod")
        msg['event_type'] = 'random'
        self.assertFalse(cn.notify(msg))

    def test_bad_event_suffix(self):
        msg = self._make_msg("myhost", "mymethod.badsuffix")
        self.assertFalse(cn.notify(msg))

    def test_bad_publisher_id(self):
        msg = self._make_msg("myhost", "mymethod.start")
        msg['publisher_id'] = 'badpublisher'
        self.assertFalse(cn.notify(msg))

    def test_update_called(self):
        def _verify_called(host, context, free_ram_mb_delta,
                           free_disk_gb_delta, work_delta, vm_delta):
            self.assertEquals(free_ram_mb_delta, 123)
            self.assertEquals(free_disk_gb_delta, 456)
            self.assertEquals(vm_delta, -1)
            self.assertEquals(work_delta, -1)

        self.stubs.Set(nova.db.api, "compute_node_utilization_update",
                       _verify_called)
        msg = self._make_msg("myhost", "delete.end")
        self.assertTrue(cn.notify(msg))

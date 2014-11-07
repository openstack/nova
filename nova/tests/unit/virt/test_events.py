# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import time

from nova import test
from nova.virt import event


class TestEvents(test.NoDBTestCase):

    def test_event_repr(self):
        t = time.time()
        uuid = '1234'
        lifecycle = event.EVENT_LIFECYCLE_RESUMED

        e = event.Event(t)
        self.assertEqual(str(e), "<Event: %s>" % t)

        e = event.InstanceEvent(uuid, timestamp=t)
        self.assertEqual(str(e), "<InstanceEvent: %s, %s>" % (t, uuid))

        e = event.LifecycleEvent(uuid, lifecycle, timestamp=t)
        self.assertEqual(str(e), "<LifecycleEvent: %s, %s => Resumed>" %
                         (t, uuid))

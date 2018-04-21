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

from nova import context as nova_context
from nova.network import model as network_model
from nova.notifications.objects import instance as instance_notification
from nova import objects
from nova import test
from nova.tests.unit import fake_instance


class TestInstanceNotification(test.NoDBTestCase):

    def test_instance_payload_request_id_periodic_task(self):
        """Tests that creating an InstancePayload from the type of request
        context used during a periodic task will not populate the
        payload request_id field since it is not an end user request.
        """
        ctxt = nova_context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctxt)
        # Set some other fields otherwise populate_schema tries to hit the DB.
        instance.metadata = {}
        instance.info_cache = objects.InstanceInfoCache(
            network_info=network_model.NetworkInfo([]))
        payload = instance_notification.InstancePayload(ctxt, instance)
        self.assertIsNone(payload.request_id)

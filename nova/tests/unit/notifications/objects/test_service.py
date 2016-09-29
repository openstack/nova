# Copyright (c) 2016 OpenStack Foundation
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

import mock
from oslo_utils import timeutils

from nova import context
from nova.notifications.objects import service as service_notification
from nova import objects
from nova.objects import fields
from nova import test
from nova.tests.unit.objects.test_service import fake_service


class TestServiceStatusNotification(test.TestCase):
    def setUp(self):
        self.ctxt = context.get_admin_context()
        super(TestServiceStatusNotification, self).setUp()

    @mock.patch('nova.notifications.objects.service.ServiceStatusNotification')
    def _verify_notification(self, service_obj, mock_notification):
        service_obj.save()

        self.assertTrue(mock_notification.called)

        event_type = mock_notification.call_args[1]['event_type']
        priority = mock_notification.call_args[1]['priority']
        publisher = mock_notification.call_args[1]['publisher']
        payload = mock_notification.call_args[1]['payload']

        self.assertEqual(service_obj.host, publisher.host)
        self.assertEqual(service_obj.binary, publisher.binary)
        self.assertEqual(fields.NotificationPriority.INFO, priority)
        self.assertEqual('service', event_type.object)
        self.assertEqual(fields.NotificationAction.UPDATE,
                         event_type.action)
        for field in service_notification.ServiceStatusPayload.SCHEMA:
            if field in fake_service:
                self.assertEqual(fake_service[field], getattr(payload, field))

        mock_notification.return_value.emit.assert_called_once_with(self.ctxt)

    @mock.patch('nova.db.service_update')
    def test_service_update_with_notification(self, mock_db_service_update):
        service_obj = objects.Service(context=self.ctxt, id=fake_service['id'])
        mock_db_service_update.return_value = fake_service
        for key, value in {'disabled': True,
                           'disabled_reason': 'my reason',
                           'forced_down': True}.items():
            setattr(service_obj, key, value)
            self._verify_notification(service_obj)

    @mock.patch('nova.notifications.objects.service.ServiceStatusNotification')
    @mock.patch('nova.db.service_update')
    def test_service_update_without_notification(self,
                                                 mock_db_service_update,
                                                 mock_notification):
        service_obj = objects.Service(context=self.ctxt, id=fake_service['id'])
        mock_db_service_update.return_value = fake_service

        for key, value in {'report_count': 13,
                           'last_seen_up': timeutils.utcnow()}.items():
            setattr(service_obj, key, value)
            service_obj.save()
            self.assertFalse(mock_notification.called)

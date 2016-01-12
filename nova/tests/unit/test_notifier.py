# Copyright 2015 OpenStack Foundation
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

from nova import rpc
from nova import test


class TestNotifier(test.NoDBTestCase):

    @mock.patch('oslo_messaging.get_transport')
    @mock.patch('oslo_messaging.get_notification_transport')
    @mock.patch('oslo_messaging.Notifier')
    def test_notification_format_affects_notification_driver(self,
                                                             mock_notifier,
                                                             mock_noti_trans,
                                                             mock_transport):
        conf = mock.Mock()

        cases = {
            'unversioned': [
                mock.call(mock.ANY, serializer=mock.ANY),
                mock.call(mock.ANY, serializer=mock.ANY, driver='noop')],
            'both': [
                mock.call(mock.ANY, serializer=mock.ANY),
                mock.call(mock.ANY, serializer=mock.ANY,
                          topic='versioned_notifications')],
            'versioned': [
                mock.call(mock.ANY, serializer=mock.ANY, driver='noop'),
                mock.call(mock.ANY, serializer=mock.ANY,
                          topic='versioned_notifications')]}

        for config in cases:
            mock_notifier.reset_mock()
            mock_notifier.side_effect = ['first', 'second']
            conf.notification_format = config
            rpc.init(conf)
            self.assertEqual(cases[config], mock_notifier.call_args_list)
            self.assertEqual('first', rpc.LEGACY_NOTIFIER)
            self.assertEqual('second', rpc.NOTIFIER)

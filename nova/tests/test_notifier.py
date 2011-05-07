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

import json

import stubout

import nova
from nova import log
from nova import flags
from nova import notifier
from nova.notifier import no_op_notifier
from nova import test

class NotifierTestCase(test.TestCase):
    """Test case for notifications"""
    def setUp(self):
        super(NotifierTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(NotifierTestCase, self).tearDown()

    def test_send_notification(self):
        self.notify_called = False
        def mock_notify(cls, *args):
            self.notify_called = True

        self.stubs.Set(nova.notifier.no_op_notifier.NoopNotifier, 'notify',
                mock_notify)

        class Mock(object):
            pass
        notifier.notify('derp', Mock())
        self.assertEqual(self.notify_called, True)

    def test_send_rabbit_notification(self):
        self.stubs.Set(nova.flags.FLAGS, 'notification_driver',
                'nova.notifier.rabbit_notifier.RabbitNotifier')
        self.mock_cast = False
        def mock_cast(cls, *args):
            self.mock_cast = True
    
        class Mock(object):
            pass
        self.stubs.Set(nova.rpc, 'cast', mock_cast) 
        notifier.notify('derp', Mock())

        self.assertEqual(self.mock_cast, True)

    def test_error_notification(self):
        self.stubs.Set(nova.flags.FLAGS, 'notification_driver',
            'nova.notifier.rabbit_notifier.RabbitNotifier')
        self.stubs.Set(nova.flags.FLAGS, 'publish_errors', True)
        LOG = log.getLogger('nova')
        LOG.setup_from_flags()

        msgs = []
        def mock_cast(context, topic, msg):
            data = json.loads(msg)
            msgs.append(data)
        self.stubs.Set(nova.rpc, 'cast', mock_cast) 
        LOG.error('foo');
        self.assertEqual(1, len(msgs))
        msg = msgs[0]
        self.assertEqual(msg['event_name'], 'error')
        self.assertEqual(msg['model']['msg'], 'foo')

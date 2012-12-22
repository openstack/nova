# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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
"""
Tests for Consoleauth Code.

"""

from nova.consoleauth import manager
from nova import context
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import test

LOG = logging.getLogger(__name__)


class ConsoleauthTestCase(test.TestCase):
    """Test Case for consoleauth."""

    def setUp(self):
        super(ConsoleauthTestCase, self).setUp()
        self.manager = manager.ConsoleAuthManager()
        self.context = context.get_admin_context()

    def test_tokens_expire(self):
        """Test that tokens expire correctly."""
        self.useFixture(test.TimeOverride())
        token = 'mytok'
        self.flags(console_token_ttl=1)
        self.manager.authorize_console(self.context, token, 'novnc',
                                       '127.0.0.1', 'host', '')
        self.assertTrue(self.manager.check_token(self.context, token))
        timeutils.advance_time_seconds(1)
        self.assertFalse(self.manager.check_token(self.context, token))

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Rackspace
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


from nova import db
from nova import flags
from nova import log as logging
from nova import test


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


class NetworkTestCase(test.TestCase):
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        self.flags(connection_type='fake',
                   fake_call=True,
                   fake_network=True)
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('netuser',
                                             'netuser',
                                             'netuser')
        self.projects = []

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

from oslo_context import context as common_context
from oslo_context import fixture as context_fixture

from nova import context
from nova import test


class TestThreadLocalContext(test.TestCase):
    def setUp(self):
        super(TestThreadLocalContext, self).setUp()
        self.useFixture(context_fixture.ClearRequestContext())
        # This will set the thread local copy of the context
        self.context = context.RequestContext('user', 'project')
        # Start the compute service to initialize compute RPC
        self.start_service('compute')

    def test_context_not_overwritten_by_periodic_tasks(self):
        # None of the periodic tasks should have overwritten the
        # thread local copy of the context
        self.assertEqual(self.context, common_context.get_current())

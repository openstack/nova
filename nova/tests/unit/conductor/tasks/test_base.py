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

from nova.conductor.tasks import base
from nova import test


class FakeTask(base.TaskBase):

    def __init__(self, context, instance, fail=False):
        super(FakeTask, self).__init__(context, instance)
        self.fail = fail

    def _execute(self):
        if self.fail:
            raise Exception
        else:
            pass


class TaskBaseTestCase(test.NoDBTestCase):

    def setUp(self):
        super(TaskBaseTestCase, self).setUp()
        self.task = FakeTask(mock.MagicMock(), mock.MagicMock())

    @mock.patch.object(FakeTask, 'rollback')
    def test_wrapper_exception(self, fake_rollback):
        self.task.fail = True
        try:
            self.task.execute()
        except Exception:
            pass
        fake_rollback.assert_called_once_with()

    @mock.patch.object(FakeTask, 'rollback')
    def test_wrapper_no_exception(self, fake_rollback):
        try:
            self.task.execute()
        except Exception:
            pass
        self.assertFalse(fake_rollback.called)

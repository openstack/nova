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

import datetime

import iso8601
import mock
from oslo_utils import timeutils

from nova import objects
from nova.tests.unit.objects import test_objects
from nova import utils

NOW = timeutils.utcnow().replace(microsecond=0)

fake_task_log = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'task_name': 'fake-name',
    'state': 'fake-state',
    'host': 'fake-host',
    'period_beginning': NOW - datetime.timedelta(seconds=10),
    'period_ending': NOW,
    'message': 'fake-message',
    'task_items': 1,
    'errors': 0,
    }


class _TestTaskLog(object):
    @mock.patch('nova.db.task_log_get', return_value=fake_task_log)
    def test_get(self, mock_get):
        task_log = objects.TaskLog.get(self.context,
                                       fake_task_log['task_name'],
                                       fake_task_log['period_beginning'],
                                       fake_task_log['period_ending'],
                                       fake_task_log['host'],
                                       state=fake_task_log['state'])
        mock_get.assert_called_once_with(
            self.context,
            fake_task_log['task_name'],
            utils.strtime(fake_task_log['period_beginning']),
            utils.strtime(fake_task_log['period_ending']),
            fake_task_log['host'],
            state=fake_task_log['state'])
        self.compare_obj(task_log, fake_task_log)

    @mock.patch('nova.db.task_log_begin_task')
    def test_begin_task(self, mock_begin_task):
        task_log = objects.TaskLog(self.context)
        task_log.task_name = fake_task_log['task_name']
        task_log.period_beginning = fake_task_log['period_beginning']
        task_log.period_ending = fake_task_log['period_ending']
        task_log.host = fake_task_log['host']
        task_log.task_items = fake_task_log['task_items']
        task_log.message = fake_task_log['message']
        task_log.begin_task()
        mock_begin_task.assert_called_once_with(
            self.context,
            fake_task_log['task_name'],
            fake_task_log['period_beginning'].replace(
                tzinfo=iso8601.UTC),
            fake_task_log['period_ending'].replace(
                tzinfo=iso8601.UTC),
            fake_task_log['host'],
            task_items=fake_task_log['task_items'],
            message=fake_task_log['message'])

    @mock.patch('nova.db.task_log_end_task')
    def test_end_task(self, mock_end_task):
        task_log = objects.TaskLog(self.context)
        task_log.task_name = fake_task_log['task_name']
        task_log.period_beginning = fake_task_log['period_beginning']
        task_log.period_ending = fake_task_log['period_ending']
        task_log.host = fake_task_log['host']
        task_log.errors = fake_task_log['errors']
        task_log.message = fake_task_log['message']
        task_log.end_task()
        mock_end_task.assert_called_once_with(
            self.context,
            fake_task_log['task_name'],
            fake_task_log['period_beginning'].replace(
                tzinfo=iso8601.UTC),
            fake_task_log['period_ending'].replace(
                tzinfo=iso8601.UTC),
            fake_task_log['host'],
            errors=fake_task_log['errors'],
            message=fake_task_log['message'])


class TestTaskLog(test_objects._LocalTest, _TestTaskLog):
    pass


class TestRemoteTaskLog(test_objects._RemoteTest, _TestTaskLog):
    pass


class _TestTaskLogList(object):
    @mock.patch('nova.db.task_log_get_all')
    def test_get_all(self, mock_get_all):
        fake_task_logs = [dict(fake_task_log, id=1), dict(fake_task_log, id=2)]
        mock_get_all.return_value = fake_task_logs
        task_logs = objects.TaskLogList.get_all(
            self.context,
            fake_task_log['task_name'],
            fake_task_log['period_beginning'],
            fake_task_log['period_ending'],
            host=fake_task_log['host'],
            state=fake_task_log['state'])
        mock_get_all.assert_called_once_with(
            self.context,
            fake_task_log['task_name'],
            utils.strtime(fake_task_log['period_beginning']),
            utils.strtime(fake_task_log['period_ending']),
            host=fake_task_log['host'],
            state=fake_task_log['state'])
        for index, task_log in enumerate(task_logs):
            self.compare_obj(task_log, fake_task_logs[index])


class TestTaskLogList(test_objects._LocalTest, _TestTaskLogList):
    pass


class TestRemoteTaskLogList(test_objects._RemoteTest, _TestTaskLogList):
    pass

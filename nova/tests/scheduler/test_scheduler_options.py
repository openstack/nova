# Copyright 2011 OpenStack Foundation
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
Tests For PickledScheduler.
"""

import datetime
import StringIO

from oslo.serialization import jsonutils

from nova.scheduler import scheduler_options
from nova import test


class FakeSchedulerOptions(scheduler_options.SchedulerOptions):
    def __init__(self, last_checked, now, file_old, file_now, data, filedata):
        super(FakeSchedulerOptions, self).__init__()
        # Change internals ...
        self.last_modified = file_old
        self.last_checked = last_checked
        self.data = data

        # For overrides ...
        self._time_now = now
        self._file_now = file_now
        self._file_data = filedata

        self.file_was_loaded = False

    def _get_file_timestamp(self, filename):
        return self._file_now

    def _get_file_handle(self, filename):
        self.file_was_loaded = True
        return StringIO.StringIO(self._file_data)

    def _get_time_now(self):
        return self._time_now


class SchedulerOptionsTestCase(test.NoDBTestCase):
    def test_get_configuration_first_time_no_flag(self):
        last_checked = None
        now = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_old = None
        file_now = datetime.datetime(2012, 1, 1, 1, 1, 1)

        data = dict(a=1, b=2, c=3)
        jdata = jsonutils.dumps(data)

        fake = FakeSchedulerOptions(last_checked, now, file_old, file_now,
                                                                  {}, jdata)
        self.assertEqual({}, fake.get_configuration())
        self.assertFalse(fake.file_was_loaded)

    def test_get_configuration_first_time_empty_file(self):
        last_checked = None
        now = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_old = None
        file_now = datetime.datetime(2012, 1, 1, 1, 1, 1)

        jdata = ""

        fake = FakeSchedulerOptions(last_checked, now, file_old, file_now,
                                                                  {}, jdata)
        self.assertEqual({}, fake.get_configuration('foo.json'))
        self.assertTrue(fake.file_was_loaded)

    def test_get_configuration_first_time_happy_day(self):
        last_checked = None
        now = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_old = None
        file_now = datetime.datetime(2012, 1, 1, 1, 1, 1)

        data = dict(a=1, b=2, c=3)
        jdata = jsonutils.dumps(data)

        fake = FakeSchedulerOptions(last_checked, now, file_old, file_now,
                                                                  {}, jdata)
        self.assertEqual(data, fake.get_configuration('foo.json'))
        self.assertTrue(fake.file_was_loaded)

    def test_get_configuration_second_time_no_change(self):
        last_checked = datetime.datetime(2011, 1, 1, 1, 1, 1)
        now = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_old = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_now = datetime.datetime(2012, 1, 1, 1, 1, 1)

        data = dict(a=1, b=2, c=3)
        jdata = jsonutils.dumps(data)

        fake = FakeSchedulerOptions(last_checked, now, file_old, file_now,
                                                                 data, jdata)
        self.assertEqual(data, fake.get_configuration('foo.json'))
        self.assertFalse(fake.file_was_loaded)

    def test_get_configuration_second_time_too_fast(self):
        last_checked = datetime.datetime(2011, 1, 1, 1, 1, 1)
        now = datetime.datetime(2011, 1, 1, 1, 1, 2)
        file_old = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_now = datetime.datetime(2013, 1, 1, 1, 1, 1)

        old_data = dict(a=1, b=2, c=3)
        data = dict(a=11, b=12, c=13)
        jdata = jsonutils.dumps(data)

        fake = FakeSchedulerOptions(last_checked, now, file_old, file_now,
                                                            old_data, jdata)
        self.assertEqual(old_data, fake.get_configuration('foo.json'))
        self.assertFalse(fake.file_was_loaded)

    def test_get_configuration_second_time_change(self):
        last_checked = datetime.datetime(2011, 1, 1, 1, 1, 1)
        now = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_old = datetime.datetime(2012, 1, 1, 1, 1, 1)
        file_now = datetime.datetime(2013, 1, 1, 1, 1, 1)

        old_data = dict(a=1, b=2, c=3)
        data = dict(a=11, b=12, c=13)
        jdata = jsonutils.dumps(data)

        fake = FakeSchedulerOptions(last_checked, now, file_old, file_now,
                                                            old_data, jdata)
        self.assertEqual(data, fake.get_configuration('foo.json'))
        self.assertTrue(fake.file_was_loaded)

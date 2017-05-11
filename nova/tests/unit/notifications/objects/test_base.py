# Copyright (c) 2017 OpenStack Foundation
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
import datetime

from nova.notifications import base
from nova import test
from nova import utils


class TestNullSafeUtils(test.NoDBTestCase):
    def test_null_safe_isotime(self):
        dt = None
        self.assertEqual('', base.null_safe_isotime(dt))
        dt = datetime.datetime(second=1,
                              minute=1,
                              hour=1,
                              day=1,
                              month=1,
                              year=2017)
        self.assertEqual(utils.strtime(dt), base.null_safe_isotime(dt))

    def test_null_safe_str(self):
        line = None
        self.assertEqual('', base.null_safe_str(line))
        line = 'test'
        self.assertEqual(line, base.null_safe_str(line))

    def test_null_safe_int(self):
        number = None
        # TODO(gibi): Fix null_safe_int to return 0 as default instead of empty
        # string
        self.assertEqual('', base.null_safe_int(number))
        number = 10
        self.assertEqual(number, base.null_safe_int(number))

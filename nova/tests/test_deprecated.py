# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2010 OpenStack LLC
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

from nova.common import deprecated
from nova import exception
from nova import test


class DeprecatedConfigTestCase(test.TestCase):
    def setUp(self):
        super(DeprecatedConfigTestCase, self).setUp()
        self.logbuffer = ""

        def local_log(msg):
            self.logbuffer = msg

        self.stubs.Set(deprecated.LOG, 'warn', local_log)

    def test_deprecated(self):
        deprecated.warn('test')
        self.assertEqual(self.logbuffer, 'Deprecated Config: test')

    def test_deprecated_fatal(self):
        self.flags(fatal_deprecations=True)
        self.assertRaises(exception.DeprecatedConfig,
                          deprecated.warn, "test2")
        self.assertEqual(self.logbuffer, 'Deprecated Config: test2')

    def test_deprecated_logs_only_once(self):
        deprecated.warn('only once!')
        deprecated.warn('only once!')
        deprecated.warn('only once!')
        self.assertEqual(self.logbuffer, 'Deprecated Config: only once!')

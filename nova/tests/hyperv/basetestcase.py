# vim: tabstop=4 shiftwidth=4 softtabstop=4

#  Copyright 2012 Cloudbase Solutions Srl
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
TestCase for MockProxy based tests and related classes.
"""

import gzip
import os
import pickle
import sys

from nova import test
from nova.tests.hyperv import mockproxy

gen_test_mocks_key = 'NOVA_GENERATE_TEST_MOCKS'


class BaseTestCase(test.TestCase):
    """TestCase for MockProxy based tests."""

    def run(self, result=None):
        self._currentResult = result
        super(BaseTestCase, self).run(result)

    def setUp(self):
        super(BaseTestCase, self).setUp()
        self._mps = {}

    def tearDown(self):
        super(BaseTestCase, self).tearDown()

        # python-subunit will wrap test results with a decorator.
        # Need to access the decorated member of results to get the
        # actual test result when using python-subunit.
        if hasattr(self._currentResult, 'decorated'):
            result = self._currentResult.decorated
        else:
            result = self._currentResult
        has_errors = len([test for (test, msgs) in result.errors
            if test.id() == self.id()]) > 0
        failed = len([test for (test, msgs) in result.failures
            if test.id() == self.id()]) > 0

        if not has_errors and not failed:
            self._save_mock_proxies()

    def _save_mock(self, name, mock):
        path = self._get_stub_file_path(self.id(), name)
        pickle.dump(mock, gzip.open(path, 'wb'))

    def _get_stub_file_path(self, test_name, mock_name):
        # test naming differs between platforms
        prefix = 'nova.tests.'
        if test_name.startswith(prefix):
            test_name = test_name[len(prefix):]
        file_name = '{0}_{1}.p.gz'.format(test_name, mock_name)
        return os.path.join(os.path.dirname(mockproxy.__file__),
                "stubs", file_name)

    def _load_mock(self, name):
        path = self._get_stub_file_path(self.id(), name)
        if os.path.exists(path):
            return pickle.load(gzip.open(path, 'rb'))
        else:
            return None

    def _load_mock_or_create_proxy(self, module_name):
        m = None
        if not gen_test_mocks_key in os.environ or \
                os.environ[gen_test_mocks_key].lower() \
                    not in ['true', 'yes', '1']:
            m = self._load_mock(module_name)
        else:
            __import__(module_name)
            module = sys.modules[module_name]
            m = mockproxy.MockProxy(module)
            self._mps[module_name] = m
        return m

    def _inject_mocks_in_modules(self, objects_to_mock, modules_to_test):
        for module_name in objects_to_mock:
            mp = self._load_mock_or_create_proxy(module_name)
            for mt in modules_to_test:
                module_local_name = module_name.split('.')[-1]
                setattr(mt, module_local_name, mp)

    def _save_mock_proxies(self):
        for name, mp in self._mps.items():
            m = mp.get_mock()
            if m.has_values():
                self._save_mock(name, m)

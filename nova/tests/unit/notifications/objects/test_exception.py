# Copyright 2020 Red Hat, Inc.
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

import sys
import traceback
import unittest

from nova.notifications.objects import exception
from nova import test


class TestExceptionPayload(test.NoDBTestCase):

    # Failing due to bug #1881455
    @unittest.expectedFailure
    def test_from_exc_and_traceback(self):
        try:
            raise Exception('foo')
        except Exception:
            exc_info = sys.exc_info()
            tb = traceback.format_exc()

        payload = exception.ExceptionPayload.from_exc_and_traceback(
            exc_info[1], tb)

        self.assertEqual(
            'nova.tests.unit.notifications.objects.test_exception',
            payload.module_name,
        )
        self.assertEqual(
            'test_from_exc_and_traceback', payload.function_name)
        self.assertEqual('foo', payload.exception_message)

    def test_from_exc_and_traceback_nested(self):
        try:
            raise Exception('foo')
        except Exception:
            exc_info = sys.exc_info()
            tb = traceback.format_exc()

            payload = exception.ExceptionPayload.from_exc_and_traceback(
                exc_info[1], tb)

        self.assertEqual(
            'nova.tests.unit.notifications.objects.test_exception',
            payload.module_name,
        )
        self.assertEqual(
            'test_from_exc_and_traceback_nested', payload.function_name)
        self.assertEqual('foo', payload.exception_message)

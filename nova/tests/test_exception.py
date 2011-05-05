# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
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

from nova import test
from nova import exception


class ApiErrorTestCase(test.TestCase):
    def test_return_valid_error(self):
        # without 'code' arg
        err = exception.ApiError('fake error')
        self.assertEqual(err.__str__(), 'fake error')
        self.assertEqual(err.code, None)
        self.assertEqual(err.msg, 'fake error')
        # with 'code' arg
        err = exception.ApiError('fake error', 'blah code')
        self.assertEqual(err.__str__(), 'blah code: fake error')
        self.assertEqual(err.code, 'blah code')
        self.assertEqual(err.msg, 'fake error')

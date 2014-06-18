#    Copyright 2011 Justin Santa Barbara
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

from nova import safe_utils
from nova import test


class GetCallArgsTestCase(test.NoDBTestCase):
    def _test_func(self, instance, red=None, blue=None):
        pass

    def test_all_kwargs(self):
        args = ()
        kwargs = {'instance': {'uuid': 1}, 'red': 3, 'blue': 4}
        callargs = safe_utils.getcallargs(self._test_func, *args, **kwargs)
        # implicit self counts as an arg
        self.assertEqual(4, len(callargs))
        self.assertIn('instance', callargs)
        self.assertEqual({'uuid': 1}, callargs['instance'])
        self.assertIn('red', callargs)
        self.assertEqual(3, callargs['red'])
        self.assertIn('blue', callargs)
        self.assertEqual(4, callargs['blue'])

    def test_all_args(self):
        args = ({'uuid': 1}, 3, 4)
        kwargs = {}
        callargs = safe_utils.getcallargs(self._test_func, *args, **kwargs)
        # implicit self counts as an arg
        self.assertEqual(4, len(callargs))
        self.assertIn('instance', callargs)
        self.assertEqual({'uuid': 1}, callargs['instance'])
        self.assertIn('red', callargs)
        self.assertEqual(3, callargs['red'])
        self.assertIn('blue', callargs)
        self.assertEqual(4, callargs['blue'])

    def test_mixed_args(self):
        args = ({'uuid': 1}, 3)
        kwargs = {'blue': 4}
        callargs = safe_utils.getcallargs(self._test_func, *args, **kwargs)
        # implicit self counts as an arg
        self.assertEqual(4, len(callargs))
        self.assertIn('instance', callargs)
        self.assertEqual({'uuid': 1}, callargs['instance'])
        self.assertIn('red', callargs)
        self.assertEqual(3, callargs['red'])
        self.assertIn('blue', callargs)
        self.assertEqual(4, callargs['blue'])

    def test_partial_kwargs(self):
        args = ()
        kwargs = {'instance': {'uuid': 1}, 'red': 3}
        callargs = safe_utils.getcallargs(self._test_func, *args, **kwargs)
        # implicit self counts as an arg
        self.assertEqual(4, len(callargs))
        self.assertIn('instance', callargs)
        self.assertEqual({'uuid': 1}, callargs['instance'])
        self.assertIn('red', callargs)
        self.assertEqual(3, callargs['red'])
        self.assertIn('blue', callargs)
        self.assertIsNone(callargs['blue'])

    def test_partial_args(self):
        args = ({'uuid': 1}, 3)
        kwargs = {}
        callargs = safe_utils.getcallargs(self._test_func, *args, **kwargs)
        # implicit self counts as an arg
        self.assertEqual(4, len(callargs))
        self.assertIn('instance', callargs)
        self.assertEqual({'uuid': 1}, callargs['instance'])
        self.assertIn('red', callargs)
        self.assertEqual(3, callargs['red'])
        self.assertIn('blue', callargs)
        self.assertIsNone(callargs['blue'])

    def test_partial_mixed_args(self):
        args = (3,)
        kwargs = {'instance': {'uuid': 1}}
        callargs = safe_utils.getcallargs(self._test_func, *args, **kwargs)
        self.assertEqual(4, len(callargs))
        self.assertIn('instance', callargs)
        self.assertEqual({'uuid': 1}, callargs['instance'])
        self.assertIn('red', callargs)
        self.assertEqual(3, callargs['red'])
        self.assertIn('blue', callargs)
        self.assertIsNone(callargs['blue'])

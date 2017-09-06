# Copyright 2016 Cloudbase Solutions Srl
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
    Unit tests for the common functions used by different CLI interfaces.
"""

import fixtures
import mock
from six.moves import StringIO

from nova.cmd import common as cmd_common
from nova.db import api
from nova import exception
from nova import test


class TestCmdCommon(test.NoDBTestCase):

    @mock.patch.object(cmd_common, 'LOG')
    @mock.patch.object(api, 'IMPL')
    def test_block_db_access(self, mock_db_IMPL, mock_LOG):
        cmd_common.block_db_access('unit-tests')

        self.assertEqual(api.IMPL, api.IMPL.foo)
        self.assertRaises(exception.DBNotAllowed, api.IMPL)
        self.assertEqual('unit-tests',
                         mock_LOG.error.call_args[0][1]['service_name'])

    def test_args_decorator(self):
        @cmd_common.args(bar='<bar>')
        @cmd_common.args('foo')
        def f():
            pass

        f_args = f.__dict__['args']
        bar_args = ((), {'bar': '<bar>'})
        foo_args = (('foo', ), {})
        self.assertEqual(bar_args, f_args[0])
        self.assertEqual(foo_args, f_args[1])

    def test_methods_of(self):
        class foo(object):
            foo = 'bar'

            def public(self):
                pass

            def _private(self):
                pass

        methods = cmd_common.methods_of(foo())

        method_names = [method_name for method_name, method in methods]
        self.assertIn('public', method_names)
        self.assertNotIn('_private', method_names)
        self.assertNotIn('foo', method_names)

    @mock.patch.object(cmd_common, 'print')
    @mock.patch.object(cmd_common, 'CONF')
    def test_print_bash_completion_no_query_category(self, mock_CONF,
                                                     mock_print):
        mock_CONF.category.query_category = None
        categories = {'foo': mock.sentinel.foo, 'bar': mock.sentinel.bar}

        cmd_common.print_bash_completion(categories)

        mock_print.assert_called_once_with(' '.join(categories.keys()))

    @mock.patch.object(cmd_common, 'print')
    @mock.patch.object(cmd_common, 'CONF')
    def test_print_bash_completion_mismatch(self, mock_CONF, mock_print):
        mock_CONF.category.query_category = 'bar'
        categories = {'foo': mock.sentinel.foo}

        cmd_common.print_bash_completion(categories)
        self.assertFalse(mock_print.called)

    @mock.patch.object(cmd_common, 'methods_of')
    @mock.patch.object(cmd_common, 'print')
    @mock.patch.object(cmd_common, 'CONF')
    def test_print_bash_completion(self, mock_CONF, mock_print,
                                   mock_method_of):
        mock_CONF.category.query_category = 'foo'
        actions = [('f1', mock.sentinel.f1), ('f2', mock.sentinel.f2)]
        mock_method_of.return_value = actions
        mock_fn = mock.Mock()
        categories = {'foo': mock_fn}

        cmd_common.print_bash_completion(categories)

        mock_fn.assert_called_once_with()
        mock_method_of.assert_called_once_with(mock_fn.return_value)
        mock_print.assert_called_once_with(' '.join([k for k, v in actions]))

    @mock.patch.object(cmd_common, 'validate_args')
    @mock.patch.object(cmd_common, 'CONF')
    def test_get_action_fn(self, mock_CONF, mock_validate_args):
        mock_validate_args.return_value = None
        action_args = [u'arg']
        action_kwargs = ['missing', 'foo', 'bar']

        mock_CONF.category.action_fn = mock.sentinel.action_fn
        mock_CONF.category.action_args = action_args
        mock_CONF.category.action_kwargs = action_kwargs
        mock_CONF.category.action_kwarg_foo = u'foo_val'
        mock_CONF.category.action_kwarg_bar = True
        mock_CONF.category.action_kwarg_missing = None

        actual_fn, actual_args, actual_kwargs = cmd_common.get_action_fn()

        self.assertEqual(mock.sentinel.action_fn, actual_fn)
        self.assertEqual(action_args, actual_args)
        self.assertEqual(u'foo_val', actual_kwargs['foo'])
        self.assertTrue(actual_kwargs['bar'])
        self.assertNotIn('missing', actual_kwargs)

    @mock.patch.object(cmd_common, 'validate_args')
    @mock.patch.object(cmd_common, 'CONF')
    def test_get_action_fn_missing_args(self, mock_CONF, mock_validate_args):
        # Don't leak the actual print call
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', StringIO()))
        mock_validate_args.return_value = ['foo']
        mock_CONF.category.action_fn = mock.sentinel.action_fn
        mock_CONF.category.action_args = []
        mock_CONF.category.action_kwargs = []

        self.assertRaises(exception.Invalid, cmd_common.get_action_fn)
        mock_CONF.print_help.assert_called_once_with()

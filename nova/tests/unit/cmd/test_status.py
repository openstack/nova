# Copyright 2016 IBM Corp.
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
Unit tests for the nova-status CLI interfaces.
"""

import fixtures
import mock
from six.moves import StringIO

from nova.cmd import status
import nova.conf
from nova import test

CONF = nova.conf.CONF


class TestNovaStatusMain(test.NoDBTestCase):
    """Tests for the basic nova-status command infrastructure."""

    def setUp(self):
        super(TestNovaStatusMain, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))

    @mock.patch.object(status.config, 'parse_args')
    @mock.patch.object(status, 'CONF')
    def _check_main(self, mock_CONF, mock_parse_args,
                    category_name='check', expected_return_value=0):
        mock_CONF.category.name = category_name
        return_value = status.main()

        self.assertEqual(expected_return_value, return_value)
        mock_CONF.register_cli_opt.assert_called_once_with(
            status.category_opt)

    @mock.patch.object(status.version, 'version_string_with_package',
                       return_value="x.x.x")
    def test_main_version(self, mock_version_string):
        self._check_main(category_name='version')
        self.assertEqual("x.x.x\n", self.output.getvalue())

    @mock.patch.object(status.cmd_common, 'print_bash_completion')
    def test_main_bash_completion(self, mock_print_bash):
        self._check_main(category_name='bash-completion')
        mock_print_bash.assert_called_once_with(status.CATEGORIES)

    @mock.patch.object(status.cmd_common, 'get_action_fn')
    def test_main(self, mock_get_action_fn):
        mock_fn = mock.Mock()
        mock_fn_args = [mock.sentinel.arg]
        mock_fn_kwargs = {'key': mock.sentinel.value}
        mock_get_action_fn.return_value = (mock_fn, mock_fn_args,
                                           mock_fn_kwargs)

        self._check_main(expected_return_value=mock_fn.return_value)
        mock_fn.assert_called_once_with(mock.sentinel.arg,
                                        key=mock.sentinel.value)

    @mock.patch.object(status.cmd_common, 'get_action_fn')
    def test_main_error(self, mock_get_action_fn):
        mock_fn = mock.Mock(side_effect=Exception('wut'))
        mock_get_action_fn.return_value = (mock_fn, [], {})

        self._check_main(expected_return_value=255)
        output = self.output.getvalue()
        self.assertIn('Error:', output)
        # assert the traceback is in the output
        self.assertIn('wut', output)


class TestUpgradeCheckBasic(test.NoDBTestCase):
    """Tests for the nova-status upgrade check command.

    The tests in this class should just test basic logic and use mock. Real
    checks which require more elaborate fixtures or the database should be done
    in separate test classes as they are more or less specific to a particular
    release and may be removed in a later release after they are no longer
    needed.
    """

    def setUp(self):
        super(TestUpgradeCheckBasic, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.cmd = status.UpgradeCommands()

    def test_check_success(self):
        fake_checks = {
            'good': mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.SUCCESS
            )),
        }
        with mock.patch.object(self.cmd, '_upgrade_checks', fake_checks):
            self.assertEqual(status.UpgradeCheckCode.SUCCESS, self.cmd.check())
        expected = """\
+-----------------------+
| Upgrade Check Results |
+-----------------------+
| Check: good           |
| Result: Success       |
| Details: None         |
+-----------------------+
"""
        self.assertEqual(expected, self.output.getvalue())

    def test_check_warning(self):
        fake_checks = {
            'good': mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.SUCCESS
            )),
            'warn': mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.WARNING, 'there might be a problem'
            )),
        }
        with mock.patch.object(self.cmd, '_upgrade_checks', fake_checks):
            self.assertEqual(status.UpgradeCheckCode.WARNING, self.cmd.check())
        expected = """\
+-----------------------------------+
| Upgrade Check Results             |
+-----------------------------------+
| Check: good                       |
| Result: Success                   |
| Details: None                     |
+-----------------------------------+
| Check: warn                       |
| Result: Warning                   |
| Details: there might be a problem |
+-----------------------------------+
"""
        self.assertEqual(expected, self.output.getvalue())

    def test_check_failure(self):
        # make the error details over 60 characters so we test the wrapping
        error_details = 'go back to bed' + '!' * 60
        fake_checks = {
            'good': mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.SUCCESS
            )),
            'warn': mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.WARNING, 'there might be a problem'
            )),
            'fail': mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.FAILURE, error_details
            )),
        }
        with mock.patch.object(self.cmd, '_upgrade_checks', fake_checks):
            self.assertEqual(status.UpgradeCheckCode.FAILURE, self.cmd.check())
        expected = """\
+-----------------------------------------------------------------------+
| Upgrade Check Results                                                 |
+-----------------------------------------------------------------------+
| Check: fail                                                           |
| Result: Failure                                                       |
| Details: go back to bed!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! |
|   !!!!!!!!!!!!!!                                                      |
+-----------------------------------------------------------------------+
| Check: good                                                           |
| Result: Success                                                       |
| Details: None                                                         |
+-----------------------------------------------------------------------+
| Check: warn                                                           |
| Result: Warning                                                       |
| Details: there might be a problem                                     |
+-----------------------------------------------------------------------+
"""
        self.assertEqual(expected, self.output.getvalue())

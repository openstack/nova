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
from nova import context
# NOTE(mriedem): We only use objects as a convenience to populate the database
# in the tests, we don't use them in the actual CLI.
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests import uuidsentinel as uuids

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

        self._check_main(expected_return_value=10)
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


class TestUpgradeCheckCellsV2(test.NoDBTestCase):
    """Tests for the nova-status upgrade cells v2 specific check."""

    # We'll setup the API DB fixture ourselves and slowly build up the
    # contents until the check passes.
    USES_DB_SELF = True

    def setUp(self):
        super(TestUpgradeCheckCellsV2, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.useFixture(nova_fixtures.Database(database='api'))
        self.cmd = status.UpgradeCommands()

    def test_check_no_cell_mappings(self):
        """The cells v2 check should fail because there are no cell mappings.
        """
        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, result.code)
        self.assertIn('There needs to be at least two cell mappings',
                      result.details)

    def _create_cell_mapping(self, uuid):
        cm = objects.CellMapping(
            context=context.get_admin_context(),
            uuid=uuid,
            name=uuid,
            transport_url='fake://%s/' % uuid,
            database_connection=uuid)
        cm.create()
        return cm

    def test_check_no_cell0_mapping(self):
        """We'll create two cell mappings but not have cell0 mapped yet."""
        for i in range(2):
            uuid = getattr(uuids, str(i))
            self._create_cell_mapping(uuid)

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, result.code)
        self.assertIn('No cell0 mapping found', result.details)

    def test_check_no_host_mappings_with_computes(self):
        """Creates a cell0 and cell1 mapping but no host mappings and there are
        compute nodes in the cell database.
        """
        self._setup_cells()
        cn = objects.ComputeNode(
            context=context.get_admin_context(),
            host='fake-host',
            vcpus=4,
            memory_mb=8 * 1024,
            local_gb=40,
            vcpus_used=2,
            memory_mb_used=2 * 1024,
            local_gb_used=10,
            hypervisor_type='fake',
            hypervisor_version=1,
            cpu_info='{"arch": "x86_64"}')
        cn.create()

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, result.code)
        self.assertIn('No host mappings found but there are compute nodes',
                      result.details)

    def test_check_no_host_mappings_no_computes(self):
        """Creates the cell0 and cell1 mappings but no host mappings and no
        compute nodes so it's assumed to be an initial install.
        """
        self._setup_cells()

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)
        self.assertIn('No host mappings or compute nodes were found',
                      result.details)

    def test_check_success(self):
        """Tests a successful cells v2 upgrade check."""
        # create the cell0 and first cell mappings
        self._setup_cells()
        # create the host mapping indirectly - host mappings existing implies
        # there is a compute node so that's not checked.
        self.start_service('compute')

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)
        self.assertIsNone(result.details)

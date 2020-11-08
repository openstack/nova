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

# NOTE(cdent): Additional tests of nova-status may be found in
# nova/tests/functional/test_nova_status.py. Those tests use the external
# PlacementFixture, which is only available in functioanl tests.

import fixtures
import mock
import os
from six.moves import StringIO
import tempfile
import yaml

from keystoneauth1 import exceptions as ks_exc
from keystoneauth1 import loading as keystone
from keystoneauth1 import session
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_upgradecheck import upgradecheck
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
from requests import models

from nova.cmd import status
import nova.conf
from nova import context
from nova import exception
# NOTE(mriedem): We only use objects as a convenience to populate the database
# in the tests, we don't use them in the actual CLI.
from nova import objects
from nova.objects import service
from nova import policy
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import policy_fixture


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


class TestPlacementCheck(test.NoDBTestCase):
    """Tests the nova-status placement checks.

    These are done with mock as the ability to replicate all failure
    domains otherwise is quite complicated. Using a devstack
    environment you can validate each of these tests are matching
    reality.
    """

    def setUp(self):
        super(TestPlacementCheck, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.cmd = status.UpgradeCommands()

    @mock.patch.object(keystone, "load_auth_from_conf_options")
    def test_no_auth(self, auth):
        """Test failure when no credentials are specified.

        Replicate in devstack: start devstack with or without
        placement engine, remove the auth section from the [placement]
        block in nova.conf.
        """
        auth.side_effect = ks_exc.MissingAuthPlugin()
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.FAILURE, res.code)
        self.assertIn('No credentials specified', res.details)

    @mock.patch.object(keystone, "load_auth_from_conf_options")
    @mock.patch.object(session.Session, 'request')
    def _test_placement_get_interface(
            self, expected_interface, mock_get, mock_auth):

        def fake_request(path, method, *a, **kw):
            self.assertEqual(mock.sentinel.path, path)
            self.assertEqual('GET', method)
            self.assertIn('endpoint_filter', kw)
            self.assertEqual(expected_interface,
                             kw['endpoint_filter']['interface'])
            return mock.Mock(autospec=models.Response)

        mock_get.side_effect = fake_request
        self.cmd._placement_get(mock.sentinel.path)
        mock_auth.assert_called_once_with(status.CONF, 'placement')
        self.assertTrue(mock_get.called)

    def test_placement_get_interface_default(self):
        """Tests that we try internal, then public interface by default."""
        self._test_placement_get_interface(['internal', 'public'])

    def test_placement_get_interface_internal(self):
        """Tests that "internal" is specified for interface when configured."""
        self.flags(valid_interfaces='internal', group='placement')
        self._test_placement_get_interface(['internal'])

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_invalid_auth(self, get):
        """Test failure when wrong credentials are specified or service user
        doesn't exist.

        Replicate in devstack: start devstack with or without
        placement engine, specify random credentials in auth section
        from the [placement] block in nova.conf.

        """
        get.side_effect = ks_exc.Unauthorized()
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.FAILURE, res.code)
        self.assertIn('Placement service credentials do not work', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_invalid_endpoint(self, get):
        """Test failure when no endpoint exists.

        Replicate in devstack: start devstack without placement
        engine, but create valid placement service user and specify it
        in auth section of [placement] in nova.conf.
        """
        get.side_effect = ks_exc.EndpointNotFound()
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.FAILURE, res.code)
        self.assertIn('Placement API endpoint not found', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_discovery_failure(self, get):
        """Test failure when discovery for placement URL failed.

        Replicate in devstack: start devstack with placement
        engine, create valid placement service user and specify it
        in auth section of [placement] in nova.conf. Stop keystone service.
        """
        get.side_effect = ks_exc.DiscoveryFailure()
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.FAILURE, res.code)
        self.assertIn('Discovery for placement API URI failed.', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_down_endpoint(self, get):
        """Test failure when endpoint is down.

        Replicate in devstack: start devstack with placement
        engine, disable placement engine apache config.
        """
        get.side_effect = ks_exc.NotFound()
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.FAILURE, res.code)
        self.assertIn('Placement API does not seem to be running', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_valid_version(self, get):
        get.return_value = {
            "versions": [
                {
                    "min_version": "1.0",
                    "max_version": status.MIN_PLACEMENT_MICROVERSION,
                    "id": "v1.0"
                }
            ]
        }
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.SUCCESS, res.code)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_version_comparison_does_not_use_floats(self, get):
        # NOTE(rpodolyaka): previously _check_placement() coerced the version
        # numbers to floats prior to comparison, that would lead to failures
        # in cases like float('1.10') < float('1.4'). As we require 1.4+ now,
        # the _check_placement() call below will assert that version comparison
        # continues to work correctly when Placement API versions 1.10
        # (or newer) is released
        get.return_value = {
             "versions": [
                {
                    "min_version": "1.0",
                    "max_version": status.MIN_PLACEMENT_MICROVERSION,
                    "id": "v1.0"
                }
            ]
        }
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.SUCCESS, res.code)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_invalid_version(self, get):
        get.return_value = {
            "versions": [
                {
                    "min_version": "0.9",
                    "max_version": "0.9",
                    "id": "v1.0"
                }
            ]
        }
        res = self.cmd._check_placement()
        self.assertEqual(upgradecheck.Code.FAILURE, res.code)
        self.assertIn('Placement API version %s needed, you have 0.9' %
                      status.MIN_PLACEMENT_MICROVERSION, res.details)


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
        self.assertEqual(upgradecheck.Code.FAILURE, result.code)
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
        self.assertEqual(upgradecheck.Code.FAILURE, result.code)
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
        self.assertEqual(upgradecheck.Code.FAILURE, result.code)
        self.assertIn('No host mappings found but there are compute nodes',
                      result.details)

    def test_check_no_host_mappings_no_computes(self):
        """Creates the cell0 and cell1 mappings but no host mappings and no
        compute nodes so it's assumed to be an initial install.
        """
        self._setup_cells()

        result = self.cmd._check_cellsv2()
        self.assertEqual(upgradecheck.Code.SUCCESS, result.code)
        self.assertIn('No host mappings or compute nodes were found',
                      result.details)

    def test_check_success(self):
        """Tests a successful cells v2 upgrade check."""
        # create the cell0 and first cell mappings
        self._setup_cells()
        # Start a compute service and create a hostmapping for it
        svc = self.start_service('compute')
        cell = self.cell_mappings[test.CELL1_NAME]
        hm = objects.HostMapping(context=context.get_admin_context(),
                                 host=svc.host,
                                 cell_mapping=cell)
        hm.create()

        result = self.cmd._check_cellsv2()
        self.assertEqual(upgradecheck.Code.SUCCESS, result.code)
        self.assertIsNone(result.details)


class TestUpgradeCheckIronicFlavorMigration(test.NoDBTestCase):
    """Tests for the nova-status upgrade check on ironic flavor migration."""

    # We'll setup the database ourselves because we need to use cells fixtures
    # for multiple cell mappings.
    USES_DB_SELF = True

    # This will create three cell mappings: cell0, cell1 (default) and cell2
    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(TestUpgradeCheckIronicFlavorMigration, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        # We always need the API DB to be setup.
        self.useFixture(nova_fixtures.Database(database='api'))
        self.cmd = status.UpgradeCommands()

    @staticmethod
    def _create_node_in_cell(ctxt, cell, hypervisor_type, nodename):
        with context.target_cell(ctxt, cell) as cctxt:
            cn = objects.ComputeNode(
                context=cctxt,
                hypervisor_type=hypervisor_type,
                hypervisor_hostname=nodename,
                # The rest of these values are fakes.
                host=uuids.host,
                vcpus=4,
                memory_mb=8 * 1024,
                local_gb=40,
                vcpus_used=2,
                memory_mb_used=2 * 1024,
                local_gb_used=10,
                hypervisor_version=1,
                cpu_info='{"arch": "x86_64"}')
            cn.create()
            return cn

    @staticmethod
    def _create_instance_in_cell(ctxt, cell, node, is_deleted=False,
                                 flavor_migrated=False):
        with context.target_cell(ctxt, cell) as cctxt:
            inst = objects.Instance(
                context=cctxt,
                host=node.host,
                node=node.hypervisor_hostname,
                uuid=uuidutils.generate_uuid())
            inst.create()

            if is_deleted:
                inst.destroy()
            else:
                # Create an embedded flavor for the instance. We don't create
                # this because we're in a cell context and flavors are global,
                # but we don't actually care about global flavors in this
                # check.
                extra_specs = {}
                if flavor_migrated:
                    extra_specs['resources:CUSTOM_BAREMETAL_GOLD'] = '1'
                inst.flavor = objects.Flavor(cctxt, extra_specs=extra_specs)
                inst.old_flavor = None
                inst.new_flavor = None
                inst.save()

            return inst

    def test_fresh_install_no_cell_mappings(self):
        """Tests the scenario where we don't have any cell mappings (no cells
        v2 setup yet) so we don't know what state we're in and we return a
        warning.
        """
        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(upgradecheck.Code.WARNING, result.code)
        self.assertIn('Unable to determine ironic flavor migration without '
                      'cell mappings', result.details)

    def test_fresh_install_no_computes(self):
        """Tests a fresh install scenario where we have two non-cell0 cells
        but no compute nodes in either cell yet, so there is nothing to do
        and we return success.
        """
        self._setup_cells()
        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(upgradecheck.Code.SUCCESS, result.code)

    def test_mixed_computes_deleted_ironic_instance(self):
        """Tests the scenario where we have a kvm compute node in one cell
        and an ironic compute node in another cell. The kvm compute node does
        not have any instances. The ironic compute node has an instance with
        the same hypervisor_hostname match but the instance is (soft) deleted
        so it's ignored.
        """
        self._setup_cells()
        ctxt = context.get_admin_context()
        # Create the ironic compute node in cell1
        ironic_node = self._create_node_in_cell(
            ctxt, self.cell_mappings['cell1'], 'ironic', uuids.node_uuid)
        # Create the kvm compute node in cell2
        self._create_node_in_cell(
            ctxt, self.cell_mappings['cell2'], 'kvm', 'fake-kvm-host')

        # Now create an instance in cell1 which is on the ironic node but is
        # soft deleted (instance.deleted == instance.id).
        self._create_instance_in_cell(
            ctxt, self.cell_mappings['cell1'], ironic_node, is_deleted=True)

        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(upgradecheck.Code.SUCCESS, result.code)

    def test_unmigrated_ironic_instances(self):
        """Tests a scenario where we have two cells with only ironic compute
        nodes. The first cell has one migrated and one unmigrated instance.
        The second cell has two unmigrated instances. The result is the check
        returns failure.
        """
        self._setup_cells()
        ctxt = context.get_admin_context()

        # Create the ironic compute nodes in cell1
        for x in range(2):
            cell = self.cell_mappings['cell1']
            ironic_node = self._create_node_in_cell(
                ctxt, cell, 'ironic', getattr(uuids, 'cell1-node-%d' % x))
            # Create an instance for this node. In cell1, we have one
            # migrated and one unmigrated instance.
            flavor_migrated = True if x % 2 else False
            self._create_instance_in_cell(
                ctxt, cell, ironic_node, flavor_migrated=flavor_migrated)

        # Create the ironic compute nodes in cell2
        for x in range(2):
            cell = self.cell_mappings['cell2']
            ironic_node = self._create_node_in_cell(
                ctxt, cell, 'ironic', getattr(uuids, 'cell2-node-%d' % x))
            # Create an instance for this node. In cell2, all instances are
            # unmigrated.
            self._create_instance_in_cell(
                ctxt, cell, ironic_node, flavor_migrated=False)

        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(upgradecheck.Code.FAILURE, result.code)
        # Check the message - it should point out cell1 has one unmigrated
        # instance and cell2 has two unmigrated instances.
        unmigrated_instance_count_by_cell = {
            self.cell_mappings['cell1'].uuid: 1,
            self.cell_mappings['cell2'].uuid: 2
        }
        self.assertIn(
            'There are (cell=x) number of unmigrated instances in each '
            'cell: %s.' % ' '.join('(%s=%s)' % (
                cell_id, unmigrated_instance_count_by_cell[cell_id])
                    for cell_id in
                    sorted(unmigrated_instance_count_by_cell.keys())),
            result.details)


class TestUpgradeCheckCinderAPI(test.NoDBTestCase):

    def setUp(self):
        super(TestUpgradeCheckCinderAPI, self).setUp()
        self.cmd = status.UpgradeCommands()

    def test_cinder_not_configured(self):
        self.flags(auth_type=None, group='cinder')
        self.assertEqual(upgradecheck.Code.SUCCESS,
                         self.cmd._check_cinder().code)

    @mock.patch('nova.volume.cinder.is_microversion_supported',
                side_effect=exception.CinderAPIVersionNotAvailable(
                    version='3.44'))
    def test_microversion_not_available(self, mock_version_check):
        self.flags(auth_type='password', group='cinder')
        result = self.cmd._check_cinder()
        mock_version_check.assert_called_once()
        self.assertEqual(upgradecheck.Code.FAILURE, result.code)
        self.assertIn('Cinder API 3.44 or greater is required.',
                      result.details)

    @mock.patch('nova.volume.cinder.is_microversion_supported',
                side_effect=test.TestingException('oops'))
    def test_unknown_error(self, mock_version_check):
        self.flags(auth_type='password', group='cinder')
        result = self.cmd._check_cinder()
        mock_version_check.assert_called_once()
        self.assertEqual(upgradecheck.Code.WARNING, result.code)
        self.assertIn('oops', result.details)

    @mock.patch('nova.volume.cinder.is_microversion_supported')
    def test_microversion_available(self, mock_version_check):
        self.flags(auth_type='password', group='cinder')
        result = self.cmd._check_cinder()
        mock_version_check.assert_called_once()
        self.assertEqual(upgradecheck.Code.SUCCESS, result.code)


class TestUpgradeCheckPolicy(test.NoDBTestCase):

    new_default_status = upgradecheck.Code.WARNING

    def setUp(self):
        super(TestUpgradeCheckPolicy, self).setUp()
        self.cmd = status.UpgradeCommands()
        self.rule_name = "system_admin_api"

    def tearDown(self):
        super(TestUpgradeCheckPolicy, self).tearDown()
        # Check if policy is reset back after the upgrade check
        self.assertIsNone(policy._ENFORCER)

    def test_policy_rule_with_new_defaults(self):
        new_default = "role:admin and system_scope:all"
        rule = {self.rule_name: new_default}
        self.policy.set_rules(rule, overwrite=False)
        self.assertEqual(self.new_default_status,
                         self.cmd._check_policy().code)

    def test_policy_rule_with_old_defaults(self):
        new_default = "is_admin:True"
        rule = {self.rule_name: new_default}
        self.policy.set_rules(rule, overwrite=False)

        self.assertEqual(upgradecheck.Code.SUCCESS,
                         self.cmd._check_policy().code)

    def test_policy_rule_with_both_defaults(self):
        new_default = "(role:admin and system_scope:all) or is_admin:True"
        rule = {self.rule_name: new_default}
        self.policy.set_rules(rule, overwrite=False)

        self.assertEqual(upgradecheck.Code.SUCCESS,
                         self.cmd._check_policy().code)

    def test_policy_checks_with_fresh_init_and_no_policy_override(self):
        self.policy = self.useFixture(policy_fixture.OverridePolicyFixture(
                                      rules_in_file={}))
        policy.reset()
        self.assertEqual(upgradecheck.Code.SUCCESS,
                         self.cmd._check_policy().code)


class TestUpgradeCheckPolicyEnableScope(TestUpgradeCheckPolicy):

    new_default_status = upgradecheck.Code.SUCCESS

    def setUp(self):
        super(TestUpgradeCheckPolicyEnableScope, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class TestUpgradeCheckPolicyJSON(test.NoDBTestCase):

    def setUp(self):
        super(TestUpgradeCheckPolicyJSON, self).setUp()
        self.cmd = status.UpgradeCommands()
        policy.CONF.clear_override('policy_file', group='oslo_policy')
        self.data = {
            'rule_admin': 'True',
            'rule_admin2': 'is_admin:True'
        }
        self.temp_dir = self.useFixture(fixtures.TempDir())
        fd, self.json_file = tempfile.mkstemp(dir=self.temp_dir.path)
        fd, self.yaml_file = tempfile.mkstemp(dir=self.temp_dir.path)

        with open(self.json_file, 'w') as fh:
            jsonutils.dump(self.data, fh)
        with open(self.yaml_file, 'w') as fh:
            yaml.dump(self.data, fh)

        original_search_dirs = cfg._search_dirs

        def fake_search_dirs(dirs, name):
            dirs.append(self.temp_dir.path)
            return original_search_dirs(dirs, name)

        self.stub_out('oslo_config.cfg._search_dirs', fake_search_dirs)

    def test_policy_json_file_fail_upgrade(self):
        # Test with policy json file full path set in config.
        self.flags(policy_file=self.json_file, group="oslo_policy")
        self.assertEqual(upgradecheck.Code.FAILURE,
                         self.cmd._check_policy_json().code)

    def test_policy_yaml_file_pass_upgrade(self):
        # Test with full policy yaml file path set in config.
        self.flags(policy_file=self.yaml_file, group="oslo_policy")
        self.assertEqual(upgradecheck.Code.SUCCESS,
                         self.cmd._check_policy_json().code)

    def test_no_policy_file_pass_upgrade(self):
        # Test with no policy file exist.
        self.assertEqual(upgradecheck.Code.SUCCESS,
                         self.cmd._check_policy_json().code)

    def test_default_policy_yaml_file_pass_upgrade(self):
        tmpfilename = os.path.join(self.temp_dir.path, 'policy.yaml')
        with open(tmpfilename, 'w') as fh:
            yaml.dump(self.data, fh)
        self.assertEqual(upgradecheck.Code.SUCCESS,
                         self.cmd._check_policy_json().code)

    def test_old_default_policy_json_file_fail_upgrade(self):
        self.flags(policy_file='policy.json', group="oslo_policy")
        tmpfilename = os.path.join(self.temp_dir.path, 'policy.json')
        with open(tmpfilename, 'w') as fh:
            jsonutils.dump(self.data, fh)
        self.assertEqual(upgradecheck.Code.FAILURE,
                         self.cmd._check_policy_json().code)


class TestUpgradeCheckOldCompute(test.NoDBTestCase):

    def setUp(self):
        super(TestUpgradeCheckOldCompute, self).setUp()
        self.cmd = status.UpgradeCommands()

    def test_no_compute(self):
        self.assertEqual(
            upgradecheck.Code.SUCCESS, self.cmd._check_old_computes().code)

    def test_only_new_compute(self):
        last_supported_version = service.SERVICE_VERSION_ALIASES[
            service.OLDEST_SUPPORTED_SERVICE_VERSION]
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=last_supported_version):
            self.assertEqual(
                upgradecheck.Code.SUCCESS, self.cmd._check_old_computes().code)

    def test_old_compute(self):
        too_old = service.SERVICE_VERSION_ALIASES[
            service.OLDEST_SUPPORTED_SERVICE_VERSION] - 1
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=too_old):
            result = self.cmd._check_old_computes()
            self.assertEqual(upgradecheck.Code.WARNING, result.code)

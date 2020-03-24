#    Copyright 2022 StackHPC
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

from unittest import mock

from oslo_config import cfg
from oslo_limit import exception as limit_exceptions
from oslo_limit import fixture as limit_fixture
from oslo_limit import limit
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context
from nova import exception
from nova.limit import placement as placement_limits
from nova.limit import utils as limit_utils
from nova import objects
from nova import quota
from nova.scheduler.client import report
from nova import test

CONF = cfg.CONF


class TestGetUsage(test.NoDBTestCase):
    def setUp(self):
        super(TestGetUsage, self).setUp()
        self.flags(driver=limit_utils.UNIFIED_LIMITS_DRIVER, group="quota")
        self.context = context.RequestContext()

    @mock.patch.object(quota, "is_qfd_populated")
    @mock.patch.object(objects.InstanceMappingList, "get_counts")
    @mock.patch.object(report.SchedulerReportClient,
                       "get_usages_counts_for_limits")
    def test_get_usage(self, mock_placement, mock_inst, mock_qfd):
        resources = ["servers", "class:VCPU", "class:MEMORY_MB",
                     "class:CUSTOM_BAREMETAL"]
        mock_qfd.return_value = True
        mock_placement.return_value = {"VCPU": 1, "CUSTOM_BAREMETAL": 2}
        mock_inst.return_value = {"project": {"instances": 42}}

        usage = placement_limits._get_usage(self.context, uuids.project,
                                            resources)

        expected = {'class:MEMORY_MB': 0, 'class:VCPU': 1, 'servers': 42,
                    'class:CUSTOM_BAREMETAL': 2}
        self.assertDictEqual(expected, usage)

    def test_get_usage_bad_resources(self):
        bad_resource = ["unknown_resource"]
        self.assertRaises(ValueError, placement_limits._get_usage,
                          self.context, uuids.project, bad_resource)
        bad_class = ["class:UNKNOWN_CLASS"]
        self.assertRaises(ValueError, placement_limits._get_usage,
                          self.context, uuids.project, bad_class)
        no_resources = []
        self.assertRaises(ValueError, placement_limits._get_usage,
                          self.context, uuids.project, no_resources)

    @mock.patch.object(quota, "is_qfd_populated")
    def test_get_usage_bad_qfd(self, mock_qfd):
        mock_qfd.return_value = False
        resources = ["servers"]
        e = self.assertRaises(ValueError, placement_limits._get_usage,
                              self.context, uuids.project, resources)
        self.assertEqual("must first migrate instance mappings", str(e))

    def test_get_usage_unified_limits_disabled(self):
        self.flags(driver="nova.quota.NoopQuotaDriver", group="quota")
        e = self.assertRaises(NotImplementedError, placement_limits._get_usage,
                              self.context, uuids.project, [])
        self.assertEqual("Unified limits support is disabled", str(e))

    @mock.patch.object(quota, "is_qfd_populated")
    @mock.patch.object(objects.InstanceMappingList, "get_counts")
    @mock.patch.object(report.SchedulerReportClient,
                       'get_usages_counts_for_limits')
    def test_get_usage_placement_fail(self, mock_placement, mock_inst,
                                      mock_qfd):
        resources = ["servers", "class:VCPU", "class:MEMORY_MB",
                     "class:CUSTOM_BAREMETAL"]
        mock_qfd.return_value = True
        mock_placement.side_effect = exception.UsagesRetrievalFailed(
            project_id=uuids.project, user_id=uuids.user)
        mock_inst.return_value = {"project": {"instances": 42}}

        e = self.assertRaises(
            exception.UsagesRetrievalFailed, placement_limits._get_usage,
            self.context, uuids.project, resources)

        expected = ("Failed to retrieve usages from placement while enforcing "
                    "%s quota limits." % ", ".join(resources))
        self.assertEqual(expected, str(e))

    @mock.patch.object(quota, "is_qfd_populated")
    @mock.patch.object(objects.InstanceMappingList, "get_counts")
    @mock.patch.object(report.SchedulerReportClient,
                       "get_usages_counts_for_limits")
    def test_get_usage_pcpu_as_vcpu(self, mock_placement, mock_inst, mock_qfd):
        # Test that when configured, PCPU count is merged into VCPU count when
        # appropriate.
        self.flags(unified_limits_count_pcpu_as_vcpu=True, group="workarounds")
        mock_qfd.return_value = True
        mock_inst.return_value = {"project": {"instances": 42}}

        # PCPU was not specified in the flavor but usage was found in
        # placement. PCPU count should be merged into VCPU count.
        resources = ["servers", "class:VCPU", "class:MEMORY_MB"]
        mock_placement.return_value = {"VCPU": 1, "PCPU": 2}

        usage = placement_limits._get_usage(self.context, uuids.project,
                                            resources)

        expected = {'class:MEMORY_MB': 0, 'class:VCPU': 3, 'servers': 42}
        self.assertDictEqual(expected, usage)

        # PCPU was not specified in the flavor and usage was found in placement
        # and there was no VCPU usage in placement. The PCPU count should be
        # returned as VCPU count.
        resources = ["servers", "class:VCPU", "class:MEMORY_MB"]
        mock_placement.return_value = {"PCPU": 1}

        usage = placement_limits._get_usage(self.context, uuids.project,
                                            resources)

        expected = {'class:MEMORY_MB': 0, 'class:VCPU': 1, 'servers': 42}
        self.assertDictEqual(expected, usage)

        # PCPU was not specified in the flavor but only VCPU usage was found in
        # placement.
        resources = ["servers", "class:VCPU", "class:MEMORY_MB"]
        mock_placement.return_value = {"VCPU": 1}

        usage = placement_limits._get_usage(self.context, uuids.project,
                                            resources)

        expected = {'class:MEMORY_MB': 0, 'class:VCPU': 1, 'servers': 42}
        self.assertDictEqual(expected, usage)

        # PCPU was specified in the flavor, so the counts should be separate.
        resources = ["servers", "class:VCPU", "class:MEMORY_MB", "class:PCPU"]
        mock_placement.return_value = {"VCPU": 1, "PCPU": 2}

        usage = placement_limits._get_usage(self.context, uuids.project,
                                            resources)

        expected = {'class:MEMORY_MB': 0, 'class:VCPU': 1, 'servers': 42,
                    'class:PCPU': 2}
        self.assertDictEqual(expected, usage)


class TestGetDeltas(test.NoDBTestCase):
    def test_get_deltas(self):
        flavor = objects.Flavor(memory_mb=100, vcpus=10, swap=0,
                                ephemeral_gb=2, root_gb=5)

        deltas = placement_limits._get_deltas_by_flavor(flavor, False, 2)

        expected = {'servers': 2,
                    'class:VCPU': 20, 'class:MEMORY_MB': 200,
                    'class:DISK_GB': 14}
        self.assertDictEqual(expected, deltas)

    def test_get_deltas_recheck(self):
        flavor = objects.Flavor(memory_mb=100, vcpus=10, swap=0,
                                ephemeral_gb=2, root_gb=5)

        deltas = placement_limits._get_deltas_by_flavor(flavor, False, 0)

        expected = {'servers': 0,
                    'class:VCPU': 0, 'class:MEMORY_MB': 0,
                    'class:DISK_GB': 0}
        self.assertDictEqual(expected, deltas)

    def test_get_deltas_check_baremetal(self):
        extra_specs = {"resources:VCPU": 0, "resources:MEMORY_MB": 0,
                       "resources:DISK_GB": 0, "resources:CUSTOM_BAREMETAL": 1}
        flavor = objects.Flavor(memory_mb=100, vcpus=10, swap=0,
                                ephemeral_gb=2, root_gb=5,
                                extra_specs=extra_specs)

        deltas = placement_limits._get_deltas_by_flavor(flavor, True, 1)

        expected = {'servers': 1, 'class:CUSTOM_BAREMETAL': 1}
        self.assertDictEqual(expected, deltas)

    def test_get_deltas_check_bfv(self):
        flavor = objects.Flavor(memory_mb=100, vcpus=10, swap=0,
                                ephemeral_gb=2, root_gb=5)

        deltas = placement_limits._get_deltas_by_flavor(flavor, True, 2)

        expected = {'servers': 2,
                    'class:VCPU': 20, 'class:MEMORY_MB': 200,
                    'class:DISK_GB': 4}
        self.assertDictEqual(expected, deltas)


class TestEnforce(test.NoDBTestCase):
    def setUp(self):
        super(TestEnforce, self).setUp()
        self.context = context.RequestContext()
        self.flags(driver=limit_utils.UNIFIED_LIMITS_DRIVER, group="quota")

        placement_limits._ENFORCER = mock.Mock(limit.Enforcer)
        self.flavor = objects.Flavor(memory_mb=100, vcpus=10, swap=0,
                                     ephemeral_gb=2, root_gb=5)

    def test_enforce_num_instances_and_flavor_disabled(self):
        self.flags(driver="nova.quota.NoopQuotaDriver", group="quota")
        count = placement_limits.enforce_num_instances_and_flavor(
            self.context, uuids.project_id, "flavor", False, 0, 42)
        self.assertEqual(42, count)

    @mock.patch('oslo_limit.limit.Enforcer')
    def test_enforce_num_instances_and_flavor(self, mock_limit):
        mock_enforcer = mock.MagicMock()
        mock_limit.return_value = mock_enforcer

        count = placement_limits.enforce_num_instances_and_flavor(
            self.context, uuids.project_id, self.flavor, False, 0, 2)

        self.assertEqual(2, count)
        mock_limit.assert_called_once_with(mock.ANY)
        mock_enforcer.enforce.assert_called_once_with(
            uuids.project_id,
            {'servers': 2, 'class:VCPU': 20, 'class:MEMORY_MB': 200,
             'class:DISK_GB': 14})

    @mock.patch('oslo_limit.limit.Enforcer')
    def test_enforce_num_instances_and_flavor_recheck(self, mock_limit):
        mock_enforcer = mock.MagicMock()
        mock_limit.return_value = mock_enforcer

        count = placement_limits.enforce_num_instances_and_flavor(
            self.context, uuids.project_id, self.flavor, False, 0, 0)

        self.assertEqual(0, count)
        mock_limit.assert_called_once_with(mock.ANY)
        mock_enforcer.enforce.assert_called_once_with(
            uuids.project_id,
            {'servers': 0, 'class:VCPU': 0, 'class:MEMORY_MB': 0,
             'class:DISK_GB': 0})

    @mock.patch('oslo_limit.limit.Enforcer')
    def test_enforce_num_instances_and_flavor_retry(self, mock_limit):
        mock_enforcer = mock.MagicMock()
        mock_limit.return_value = mock_enforcer
        over_limit_info_list = [
            limit_exceptions.OverLimitInfo("class:VCPU", 12, 0, 30)
        ]
        mock_enforcer.enforce.side_effect = [
            limit_exceptions.ProjectOverLimit(
                uuids.project_id, over_limit_info_list),
            None]

        count = placement_limits.enforce_num_instances_and_flavor(
            self.context, uuids.project_id, self.flavor, True, 0, 3)

        self.assertEqual(2, count)
        self.assertEqual(2, mock_enforcer.enforce.call_count)
        mock_enforcer.enforce.assert_called_with(
            uuids.project_id,
            {'servers': 2, 'class:VCPU': 20, 'class:MEMORY_MB': 200,
             'class:DISK_GB': 4})

    @mock.patch('oslo_limit.limit.Enforcer')
    def test_enforce_num_instances_and_flavor_fails(self, mock_limit):
        mock_enforcer = mock.MagicMock()
        mock_limit.return_value = mock_enforcer
        over_limit_info_list = [
            limit_exceptions.OverLimitInfo("class:VCPU", 12, 0, 20),
            limit_exceptions.OverLimitInfo("servers", 2, 1, 2)
        ]
        expected = limit_exceptions.ProjectOverLimit(uuids.project_id,
                                                     over_limit_info_list)
        mock_enforcer.enforce.side_effect = expected

        # Verify that the oslo.limit ProjectOverLimit gets translated to a
        # TooManyInstances that the API knows how to handle
        e = self.assertRaises(
            exception.TooManyInstances,
            placement_limits.enforce_num_instances_and_flavor, self.context,
            uuids.project_id, self.flavor, True, 2, 4)

        self.assertEqual(str(expected), str(e))
        self.assertEqual(3, mock_enforcer.enforce.call_count)

    @mock.patch('oslo_limit.limit.Enforcer')
    def test_enforce_num_instances_and_flavor_placement_fail(self, mock_limit):
        mock_enforcer = mock.MagicMock()
        mock_limit.return_value = mock_enforcer
        mock_enforcer.enforce.side_effect = exception.UsagesRetrievalFailed(
            'Failed to retrieve usages')

        e = self.assertRaises(
            exception.UsagesRetrievalFailed,
            placement_limits.enforce_num_instances_and_flavor, self.context,
            uuids.project, self.flavor, True, 0, 5)

        expected = str(mock_enforcer.enforce.side_effect)
        self.assertEqual(expected, str(e))


class GetLegacyLimitsTest(test.NoDBTestCase):
    def setUp(self):
        super(GetLegacyLimitsTest, self).setUp()
        self.new = {"servers": 1, "class:VCPU": 2, "class:MEMORY_MB": 3}
        self.legacy = {"instances": 1, "cores": 2, "ram": 3}
        self.resources = ["servers", "class:VCPU", "class:MEMORY_MB"]
        self.resources.sort()
        self.flags(driver=limit_utils.UNIFIED_LIMITS_DRIVER, group="quota")

    def test_convert_keys_to_legacy_name(self):
        limits = placement_limits._convert_keys_to_legacy_name(self.new)
        self.assertEqual(self.legacy, limits)

    def test_get_legacy_default_limits(self):
        reglimits = {'servers': 1, 'class:VCPU': 2}
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))
        limits = placement_limits.get_legacy_default_limits()
        self.assertEqual({'cores': 2, 'instances': 1, 'ram': 0}, limits)

    def test_get_legacy_project_limits(self):
        reglimits = {'servers': 5, 'class:MEMORY_MB': 7}
        projlimits = {uuids.project_id: {'servers': 1}}
        self.useFixture(limit_fixture.LimitFixture(reglimits, projlimits))
        limits = placement_limits.get_legacy_project_limits(uuids.project_id)
        self.assertEqual({'instances': 1, 'cores': 0, 'ram': 7}, limits)

    @mock.patch.object(report.SchedulerReportClient,
                       "get_usages_counts_for_limits")
    @mock.patch.object(objects.InstanceMappingList, "get_counts")
    @mock.patch.object(quota, "is_qfd_populated")
    def test_get_legacy_counts(self, mock_qfd, mock_counts, mock_placement):
        mock_qfd.return_value = True
        mock_counts.return_value = {"project": {"instances": 1}}
        mock_placement.return_value = {
            "VCPU": 2, "CUSTOM_BAREMETAL": 2, "MEMORY_MB": 3,
        }
        counts = placement_limits.get_legacy_counts(
            "context", uuids.project_id)
        self.assertEqual(self.legacy, counts)

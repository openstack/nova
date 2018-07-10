# Copyright (c) 2012 OpenStack Foundation
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

import datetime

from oslo_utils import fixture as utils_fixture

from nova.api.openstack.compute import instance_usage_audit_log as v21_ial
from nova import context
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_service


service_base = test_service.fake_service
TEST_COMPUTE_SERVICES = [dict(service_base, host='foo', topic='compute'),
                         dict(service_base, host='bar', topic='compute'),
                         dict(service_base, host='baz', topic='compute'),
                         dict(service_base, host='plonk', topic='compute'),
                         dict(service_base, host='wibble', topic='bogus'),
                         ]


begin1 = datetime.datetime(2012, 7, 4, 6, 0, 0)
begin2 = end1 = datetime.datetime(2012, 7, 5, 6, 0, 0)
begin3 = end2 = datetime.datetime(2012, 7, 6, 6, 0, 0)
end3 = datetime.datetime(2012, 7, 7, 6, 0, 0)


# test data


TEST_LOGS1 = [
    # all services done, no errors.
    dict(host="plonk", period_beginning=begin1, period_ending=end1,
         state="DONE", errors=0, task_items=23, message="test1"),
    dict(host="baz", period_beginning=begin1, period_ending=end1,
         state="DONE", errors=0, task_items=17, message="test2"),
    dict(host="bar", period_beginning=begin1, period_ending=end1,
         state="DONE", errors=0, task_items=10, message="test3"),
    dict(host="foo", period_beginning=begin1, period_ending=end1,
         state="DONE", errors=0, task_items=7, message="test4"),
    ]


TEST_LOGS2 = [
    # some still running...
    dict(host="plonk", period_beginning=begin2, period_ending=end2,
         state="DONE", errors=0, task_items=23, message="test5"),
    dict(host="baz", period_beginning=begin2, period_ending=end2,
         state="DONE", errors=0, task_items=17, message="test6"),
    dict(host="bar", period_beginning=begin2, period_ending=end2,
         state="RUNNING", errors=0, task_items=10, message="test7"),
    dict(host="foo", period_beginning=begin2, period_ending=end2,
         state="DONE", errors=0, task_items=7, message="test8"),
    ]


TEST_LOGS3 = [
    # some errors..
    dict(host="plonk", period_beginning=begin3, period_ending=end3,
         state="DONE", errors=0, task_items=23, message="test9"),
    dict(host="baz", period_beginning=begin3, period_ending=end3,
         state="DONE", errors=2, task_items=17, message="test10"),
    dict(host="bar", period_beginning=begin3, period_ending=end3,
         state="DONE", errors=0, task_items=10, message="test11"),
    dict(host="foo", period_beginning=begin3, period_ending=end3,
         state="DONE", errors=1, task_items=7, message="test12"),
    ]


def fake_task_log_get_all(context, task_name, begin, end,
                          host=None, state=None):
    assert task_name == "instance_usage_audit"

    if begin == begin1 and end == end1:
        return TEST_LOGS1
    if begin == begin2 and end == end2:
        return TEST_LOGS2
    if begin == begin3 and end == end3:
        return TEST_LOGS3
    raise AssertionError("Invalid date %s to %s" % (begin, end))


def fake_last_completed_audit_period(unit=None, before=None):
    audit_periods = [(begin3, end3),
                     (begin2, end2),
                     (begin1, end1)]
    if before is not None:
        for begin, end in audit_periods:
            if before > end:
                return begin, end
        raise AssertionError("Invalid before date %s" % (before))
    return begin1, end1


class InstanceUsageAuditLogTestV21(test.NoDBTestCase):
    def setUp(self):
        super(InstanceUsageAuditLogTestV21, self).setUp()
        self.context = context.get_admin_context()
        self.useFixture(
            utils_fixture.TimeFixture(datetime.datetime(2012, 7, 5, 10, 0, 0)))
        self._set_up_controller()
        self.host_api = self.controller.host_api

        def fake_service_get_all(context, disabled):
            self.assertIsNone(disabled)
            return TEST_COMPUTE_SERVICES

        self.stub_out('nova.utils.last_completed_audit_period',
                      fake_last_completed_audit_period)
        self.stub_out('nova.db.api.service_get_all', fake_service_get_all)
        self.stub_out('nova.db.api.task_log_get_all', fake_task_log_get_all)

        self.req = fakes.HTTPRequest.blank('')

    def _set_up_controller(self):
        self.controller = v21_ial.InstanceUsageAuditLogController()

    def test_index(self):
        result = self.controller.index(self.req)
        self.assertIn('instance_usage_audit_logs', result)
        logs = result['instance_usage_audit_logs']
        self.assertEqual(57, logs['total_instances'])
        self.assertEqual(0, logs['total_errors'])
        self.assertEqual(4, len(logs['log']))
        self.assertEqual(4, logs['num_hosts'])
        self.assertEqual(4, logs['num_hosts_done'])
        self.assertEqual(0, logs['num_hosts_running'])
        self.assertEqual(0, logs['num_hosts_not_run'])
        self.assertEqual("ALL hosts done. 0 errors.", logs['overall_status'])

    def test_show(self):
        result = self.controller.show(self.req, '2012-07-05 10:00:00')
        self.assertIn('instance_usage_audit_log', result)
        logs = result['instance_usage_audit_log']
        self.assertEqual(57, logs['total_instances'])
        self.assertEqual(0, logs['total_errors'])
        self.assertEqual(4, len(logs['log']))
        self.assertEqual(4, logs['num_hosts'])
        self.assertEqual(4, logs['num_hosts_done'])
        self.assertEqual(0, logs['num_hosts_running'])
        self.assertEqual(0, logs['num_hosts_not_run'])
        self.assertEqual("ALL hosts done. 0 errors.", logs['overall_status'])

    def test_show_with_running(self):
        result = self.controller.show(self.req, '2012-07-06 10:00:00')
        self.assertIn('instance_usage_audit_log', result)
        logs = result['instance_usage_audit_log']
        self.assertEqual(57, logs['total_instances'])
        self.assertEqual(0, logs['total_errors'])
        self.assertEqual(4, len(logs['log']))
        self.assertEqual(4, logs['num_hosts'])
        self.assertEqual(3, logs['num_hosts_done'])
        self.assertEqual(1, logs['num_hosts_running'])
        self.assertEqual(0, logs['num_hosts_not_run'])
        self.assertEqual("3 of 4 hosts done. 0 errors.",
                         logs['overall_status'])

    def test_show_with_errors(self):
        result = self.controller.show(self.req, '2012-07-07 10:00:00')
        self.assertIn('instance_usage_audit_log', result)
        logs = result['instance_usage_audit_log']
        self.assertEqual(57, logs['total_instances'])
        self.assertEqual(3, logs['total_errors'])
        self.assertEqual(4, len(logs['log']))
        self.assertEqual(4, logs['num_hosts'])
        self.assertEqual(4, logs['num_hosts_done'])
        self.assertEqual(0, logs['num_hosts_running'])
        self.assertEqual(0, logs['num_hosts_not_run'])
        self.assertEqual("ALL hosts done. 3 errors.",
                         logs['overall_status'])


class InstanceUsageAuditPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(InstanceUsageAuditPolicyEnforcementV21, self).setUp()
        self.controller = v21_ial.InstanceUsageAuditLogController()
        self.req = fakes.HTTPRequest.blank('')

    def test_index_policy_failed(self):
        rule_name = "os_compute_api:os-instance-usage-audit-log"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_show_policy_failed(self):
        rule_name = "os_compute_api:os-instance-usage-audit-log"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.show, self.req, '2012-07-05 10:00:00')
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

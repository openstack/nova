# Copyright 2011 OpenStack Foundation
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

import mock
from oslo.utils import timeutils
import webob

from nova.api.openstack.compute.contrib import simple_tenant_usage as \
    simple_tenant_usage_v2
from nova.api.openstack.compute.plugins.v3 import simple_tenant_usage as \
    simple_tenant_usage_v21
from nova.compute import flavors
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.openstack.common import policy as common_policy
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova import utils

SERVERS = 5
TENANTS = 2
HOURS = 24
ROOT_GB = 10
EPHEMERAL_GB = 20
MEMORY_MB = 1024
VCPUS = 2
NOW = timeutils.utcnow()
START = NOW - datetime.timedelta(hours=HOURS)
STOP = NOW


FAKE_INST_TYPE = {'id': 1,
                  'vcpus': VCPUS,
                  'root_gb': ROOT_GB,
                  'ephemeral_gb': EPHEMERAL_GB,
                  'memory_mb': MEMORY_MB,
                  'name': 'fakeflavor',
                  'flavorid': 'foo',
                  'rxtx_factor': 1.0,
                  'vcpu_weight': 1,
                  'swap': 0,
                  'created_at': None,
                  'updated_at': None,
                  'deleted_at': None,
                  'deleted': 0,
                  'disabled': False,
                  'is_public': True,
                  'extra_specs': {'foo': 'bar'}}


def get_fake_db_instance(start, end, instance_id, tenant_id,
                         vm_state=vm_states.ACTIVE):
    sys_meta = utils.dict_to_metadata(
        flavors.save_flavor_info({}, FAKE_INST_TYPE))
    # NOTE(mriedem): We use fakes.stub_instance since it sets the fields
    # needed on the db instance for converting it to an object, but we still
    # need to override system_metadata to use our fake flavor.
    inst = fakes.stub_instance(
            id=instance_id,
            uuid='00000000-0000-0000-0000-00000000000000%02d' % instance_id,
            image_ref='1',
            project_id=tenant_id,
            user_id='fakeuser',
            display_name='name',
            flavor_id=FAKE_INST_TYPE['id'],
            launched_at=start,
            terminated_at=end,
            vm_state=vm_state,
            memory_mb=MEMORY_MB,
            vcpus=VCPUS,
            root_gb=ROOT_GB,
            ephemeral_gb=EPHEMERAL_GB,)
    inst['system_metadata'] = sys_meta
    return inst


def fake_instance_get_active_by_window_joined(context, begin, end,
        project_id, host, columns_to_join):
            return [get_fake_db_instance(START,
                                         STOP,
                                         x,
                                         "faketenant_%s" % (x / SERVERS))
                                         for x in xrange(TENANTS * SERVERS)]


@mock.patch.object(db, 'instance_get_active_by_window_joined',
                   fake_instance_get_active_by_window_joined)
class SimpleTenantUsageTestV21(test.TestCase):
    policy_rule_prefix = "compute_extension:v3:os-simple-tenant-usage"
    controller = simple_tenant_usage_v21.SimpleTenantUsageController()

    def setUp(self):
        super(SimpleTenantUsageTestV21, self).setUp()
        self.admin_context = context.RequestContext('fakeadmin_0',
                                                    'faketenant_0',
                                                    is_admin=True)
        self.user_context = context.RequestContext('fakeadmin_0',
                                                   'faketenant_0',
                                                    is_admin=False)
        self.alt_user_context = context.RequestContext('fakeadmin_0',
                                                      'faketenant_1',
                                                       is_admin=False)

    def _test_verify_index(self, start, stop):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    (start.isoformat(), stop.isoformat()))
        req.environ['nova.context'] = self.admin_context
        res_dict = self.controller.index(req)
        usages = res_dict['tenant_usages']
        for i in xrange(TENANTS):
            self.assertEqual(int(usages[i]['total_hours']),
                             SERVERS * HOURS)
            self.assertEqual(int(usages[i]['total_local_gb_usage']),
                             SERVERS * (ROOT_GB + EPHEMERAL_GB) * HOURS)
            self.assertEqual(int(usages[i]['total_memory_mb_usage']),
                             SERVERS * MEMORY_MB * HOURS)
            self.assertEqual(int(usages[i]['total_vcpus_usage']),
                             SERVERS * VCPUS * HOURS)
            self.assertFalse(usages[i].get('server_usages'))

    def test_verify_index(self):
        self._test_verify_index(START, STOP)

    def test_verify_index_future_end_time(self):
        future = NOW + datetime.timedelta(hours=HOURS)
        self._test_verify_index(START, future)

    def test_verify_show(self):
        self._test_verify_show(START, STOP)

    def test_verify_show_future_end_time(self):
        future = NOW + datetime.timedelta(hours=HOURS)
        self._test_verify_show(START, future)

    def _get_tenant_usages(self, detailed=''):
        req = fakes.HTTPRequest.blank('?detailed=%s&start=%s&end=%s' %
                    (detailed, START.isoformat(), STOP.isoformat()))
        req.environ['nova.context'] = self.admin_context

        # Make sure that get_active_by_window_joined is only called with
        # expected_attrs=['system_metadata'].
        orig_get_active_by_window_joined = (
            objects.InstanceList.get_active_by_window_joined)

        def fake_get_active_by_window_joined(context, begin, end=None,
                                    project_id=None, host=None,
                                    expected_attrs=None,
                                    use_slave=False):
            self.assertEqual(['system_metadata'], expected_attrs)
            return orig_get_active_by_window_joined(context, begin, end,
                                                    project_id, host,
                                                    expected_attrs, use_slave)

        with mock.patch.object(objects.InstanceList,
                               'get_active_by_window_joined',
                               side_effect=fake_get_active_by_window_joined):
            res_dict = self.controller.index(req)
            return res_dict['tenant_usages']

    def test_verify_detailed_index(self):
        usages = self._get_tenant_usages('1')
        for i in xrange(TENANTS):
            servers = usages[i]['server_usages']
            for j in xrange(SERVERS):
                self.assertEqual(int(servers[j]['hours']), HOURS)

    def test_verify_simple_index(self):
        usages = self._get_tenant_usages(detailed='0')
        for i in xrange(TENANTS):
            self.assertIsNone(usages[i].get('server_usages'))

    def test_verify_simple_index_empty_param(self):
        # NOTE(lzyeval): 'detailed=&start=..&end=..'
        usages = self._get_tenant_usages()
        for i in xrange(TENANTS):
            self.assertIsNone(usages[i].get('server_usages'))

    def _test_verify_show(self, start, stop):
        tenant_id = 0
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    (start.isoformat(), stop.isoformat()))
        req.environ['nova.context'] = self.user_context

        res_dict = self.controller.show(req, tenant_id)

        usage = res_dict['tenant_usage']
        servers = usage['server_usages']
        self.assertEqual(len(usage['server_usages']), SERVERS)
        uuids = ['00000000-0000-0000-0000-00000000000000%02d' %
                    (x + (tenant_id * SERVERS)) for x in xrange(SERVERS)]
        for j in xrange(SERVERS):
            delta = STOP - START
            uptime = delta.days * 24 * 3600 + delta.seconds
            self.assertEqual(int(servers[j]['uptime']), uptime)
            self.assertEqual(int(servers[j]['hours']), HOURS)
            self.assertIn(servers[j]['instance_id'], uuids)

    def test_verify_show_cannot_view_other_tenant(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    (START.isoformat(), STOP.isoformat()))
        req.environ['nova.context'] = self.alt_user_context

        rules = {
            self.policy_rule_prefix + ":show":
                common_policy.parse_rule([
                    ["role:admin"], ["project_id:%(project_id)s"]
                    ])
        }
        policy.set_rules(rules)

        try:
            self.assertRaises(exception.PolicyNotAuthorized,
                              self.controller.show, req, 'faketenant_0')
        finally:
            policy.reset()

    def test_get_tenants_usage_with_bad_start_date(self):
        future = NOW + datetime.timedelta(hours=HOURS)
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    (future.isoformat(), NOW.isoformat()))
        req.environ['nova.context'] = self.user_context
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.show, req, 'faketenant_0')

    def test_get_tenants_usage_with_invalid_start_date(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    ("xxxx", NOW.isoformat()))
        req.environ['nova.context'] = self.user_context
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.show, req, 'faketenant_0')

    def _test_get_tenants_usage_with_one_date(self, date_url_param):
        req = fakes.HTTPRequest.blank('?%s' % date_url_param)
        req.environ['nova.context'] = self.user_context
        res = self.controller.show(req, 'faketenant_0')
        self.assertIn('tenant_usage', res)

    def test_get_tenants_usage_with_no_start_date(self):
        self._test_get_tenants_usage_with_one_date(
            'end=%s' % (NOW + datetime.timedelta(5)).isoformat())

    def test_get_tenants_usage_with_no_end_date(self):
        self._test_get_tenants_usage_with_one_date(
            'start=%s' % (NOW - datetime.timedelta(5)).isoformat())


class SimpleTenantUsageTestV2(SimpleTenantUsageTestV21):
    policy_rule_prefix = "compute_extension:simple_tenant_usage"
    controller = simple_tenant_usage_v2.SimpleTenantUsageController()


class SimpleTenantUsageControllerTestV21(test.TestCase):
    controller = simple_tenant_usage_v21.SimpleTenantUsageController()

    def setUp(self):
        super(SimpleTenantUsageControllerTestV21, self).setUp()

        self.context = context.RequestContext('fakeuser', 'fake-project')

        self.baseinst = get_fake_db_instance(START, STOP, instance_id=1,
                                             tenant_id=self.context.project_id,
                                             vm_state=vm_states.DELETED)
        # convert the fake instance dict to an object
        self.inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), self.baseinst)

    def test_get_flavor_from_sys_meta(self):
        # Non-deleted instances get their type information from their
        # system_metadata
        with mock.patch.object(db, 'instance_get_by_uuid',
                               return_value=self.baseinst):
            flavor = self.controller._get_flavor(self.context,
                                                 self.inst_obj, {})
        self.assertEqual(objects.Flavor, type(flavor))
        self.assertEqual(FAKE_INST_TYPE['id'], flavor.id)

    def test_get_flavor_from_non_deleted_with_id_fails(self):
        # If an instance is not deleted and missing type information from
        # system_metadata, then that's a bug
        self.inst_obj.system_metadata = {}
        self.assertRaises(KeyError,
                          self.controller._get_flavor, self.context,
                          self.inst_obj, {})

    def test_get_flavor_from_deleted_with_id(self):
        # Deleted instances may not have type info in system_metadata,
        # so verify that they get their type from a lookup of their
        # instance_type_id
        self.inst_obj.system_metadata = {}
        self.inst_obj.deleted = 1
        flavor = self.controller._get_flavor(self.context, self.inst_obj, {})
        self.assertEqual(objects.Flavor, type(flavor))
        self.assertEqual(FAKE_INST_TYPE['id'], flavor.id)

    def test_get_flavor_from_deleted_with_id_of_deleted(self):
        # Verify the legacy behavior of instance_type_id pointing to a
        # missing type being non-fatal
        self.inst_obj.system_metadata = {}
        self.inst_obj.deleted = 1
        self.inst_obj.instance_type_id = 99
        flavor = self.controller._get_flavor(self.context, self.inst_obj, {})
        self.assertIsNone(flavor)


class SimpleTenantUsageControllerTestV2(SimpleTenantUsageControllerTestV21):
    controller = simple_tenant_usage_v2.SimpleTenantUsageController()


class SimpleTenantUsageUtilsV21(test.NoDBTestCase):
    simple_tenant_usage = simple_tenant_usage_v21

    def test_valid_string(self):
        dt = self.simple_tenant_usage.parse_strtime(
            "2014-02-21T13:47:20.824060", "%Y-%m-%dT%H:%M:%S.%f")
        self.assertEqual(datetime.datetime(
                microsecond=824060, second=20, minute=47, hour=13,
                day=21, month=2, year=2014), dt)

    def test_invalid_string(self):
        self.assertRaises(exception.InvalidStrTime,
                          self.simple_tenant_usage.parse_strtime,
                          "2014-02-21 13:47:20.824060",
                          "%Y-%m-%dT%H:%M:%S.%f")


class SimpleTenantUsageUtilsV2(SimpleTenantUsageUtilsV21):
    simple_tenant_usage = simple_tenant_usage_v2

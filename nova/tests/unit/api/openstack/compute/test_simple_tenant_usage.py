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
from oslo_policy import policy as oslo_policy
from oslo_utils import timeutils
from six.moves import range
import webob

from nova.api.openstack.compute.legacy_v2.contrib import simple_tenant_usage as \
    simple_tenant_usage_v2
from nova.api.openstack.compute import simple_tenant_usage as \
    simple_tenant_usage_v21
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_flavor

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
    return inst


def fake_instance_get_active_by_window_joined(context, begin, end,
        project_id, host, columns_to_join):
            return [get_fake_db_instance(START,
                                         STOP,
                                         x,
                                         project_id if project_id else
                                         "faketenant_%s" % (x / SERVERS))
                                         for x in range(TENANTS * SERVERS)]


@mock.patch.object(db, 'instance_get_active_by_window_joined',
                   fake_instance_get_active_by_window_joined)
class SimpleTenantUsageTestV21(test.TestCase):
    policy_rule_prefix = "os_compute_api:os-simple-tenant-usage"
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
        for i in range(TENANTS):
            self.assertEqual(SERVERS * HOURS, int(usages[i]['total_hours']))
            self.assertEqual(SERVERS * (ROOT_GB + EPHEMERAL_GB) * HOURS,
                             int(usages[i]['total_local_gb_usage']))
            self.assertEqual(SERVERS * MEMORY_MB * HOURS,
                             int(usages[i]['total_memory_mb_usage']))
            self.assertEqual(SERVERS * VCPUS * HOURS,
                             int(usages[i]['total_vcpus_usage']))
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
        # expected_attrs=['flavor'].
        orig_get_active_by_window_joined = (
            objects.InstanceList.get_active_by_window_joined)

        def fake_get_active_by_window_joined(context, begin, end=None,
                                    project_id=None, host=None,
                                    expected_attrs=None,
                                    use_slave=False):
            self.assertEqual(['flavor'], expected_attrs)
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
        for i in range(TENANTS):
            servers = usages[i]['server_usages']
            for j in range(SERVERS):
                self.assertEqual(HOURS, int(servers[j]['hours']))

    def test_verify_simple_index(self):
        usages = self._get_tenant_usages(detailed='0')
        for i in range(TENANTS):
            self.assertIsNone(usages[i].get('server_usages'))

    def test_verify_simple_index_empty_param(self):
        # NOTE(lzyeval): 'detailed=&start=..&end=..'
        usages = self._get_tenant_usages()
        for i in range(TENANTS):
            self.assertIsNone(usages[i].get('server_usages'))

    def _test_verify_show(self, start, stop):
        tenant_id = 1
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    (start.isoformat(), stop.isoformat()))
        req.environ['nova.context'] = self.user_context

        res_dict = self.controller.show(req, tenant_id)

        usage = res_dict['tenant_usage']
        servers = usage['server_usages']
        self.assertEqual(TENANTS * SERVERS, len(usage['server_usages']))
        uuids = ['00000000-0000-0000-0000-00000000000000%02d' %
                    x for x in range(SERVERS)]
        for j in range(SERVERS):
            delta = STOP - START
            # NOTE(javeme): cast seconds from float to int for clarity
            uptime = int(delta.total_seconds())
            self.assertEqual(uptime, int(servers[j]['uptime']))
            self.assertEqual(HOURS, int(servers[j]['hours']))
            self.assertIn(servers[j]['instance_id'], uuids)

    def test_verify_show_cannot_view_other_tenant(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    (START.isoformat(), STOP.isoformat()))
        req.environ['nova.context'] = self.alt_user_context

        rules = {
            self.policy_rule_prefix + ":show": [
                ["role:admin"], ["project_id:%(project_id)s"]]
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

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
        flavor = fake_flavor.fake_flavor_obj(self.context, **FAKE_INST_TYPE)
        self.inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), self.baseinst)
        self.inst_obj.flavor = flavor

    @mock.patch('nova.objects.Instance.get_flavor',
                side_effect=exception.NotFound())
    def test_get_flavor_from_non_deleted_with_id_fails(self, fake_get_flavor):
        # If an instance is not deleted and missing type information from
        # instance.flavor, then that's a bug
        self.assertRaises(exception.NotFound,
                          self.controller._get_flavor, self.context,
                          self.inst_obj, {})

    @mock.patch('nova.objects.Instance.get_flavor',
                side_effect=exception.NotFound())
    def test_get_flavor_from_deleted_with_notfound(self, fake_get_flavor):
        # If the flavor is not found from the instance and the instance is
        # deleted, attempt to look it up from the DB and if found we're OK.
        self.inst_obj.deleted = 1
        flavor = self.controller._get_flavor(self.context, self.inst_obj, {})
        self.assertEqual(objects.Flavor, type(flavor))
        self.assertEqual(FAKE_INST_TYPE['id'], flavor.id)

    @mock.patch('nova.objects.Instance.get_flavor',
                side_effect=exception.NotFound())
    def test_get_flavor_from_deleted_with_id_of_deleted(self, fake_get_flavor):
        # Verify the legacy behavior of instance_type_id pointing to a
        # missing type being non-fatal
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

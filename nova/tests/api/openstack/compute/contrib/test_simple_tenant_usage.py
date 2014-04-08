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

from lxml import etree
import mock
import webob

from nova.api.openstack.compute.contrib import simple_tenant_usage
from nova.compute import flavors
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.objects import flavor as flavor_obj
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import policy as common_policy
from nova.openstack.common import timeutils
from nova import policy
from nova import test
from nova.tests.api.openstack import fakes
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
            vm_state=vm_state)
    inst['system_metadata'] = sys_meta
    return inst


def fake_instance_get_active_by_window_joined(context, begin, end,
        project_id, host):
            return [get_fake_db_instance(START,
                                         STOP,
                                         x,
                                         "faketenant_%s" % (x / SERVERS))
                                         for x in xrange(TENANTS * SERVERS)]


@mock.patch.object(db, 'instance_get_active_by_window_joined',
                   fake_instance_get_active_by_window_joined)
class SimpleTenantUsageTest(test.TestCase):
    def setUp(self):
        super(SimpleTenantUsageTest, self).setUp()
        self.admin_context = context.RequestContext('fakeadmin_0',
                                                    'faketenant_0',
                                                    is_admin=True)
        self.user_context = context.RequestContext('fakeadmin_0',
                                                   'faketenant_0',
                                                    is_admin=False)
        self.alt_user_context = context.RequestContext('fakeadmin_0',
                                                      'faketenant_1',
                                                       is_admin=False)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Simple_tenant_usage'])

    def _test_verify_index(self, start, stop):
        req = webob.Request.blank(
                    '/v2/faketenant_0/os-simple-tenant-usage?start=%s&end=%s' %
                    (start.isoformat(), stop.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context,
                               init_only=('os-simple-tenant-usage',)))

        self.assertEqual(res.status_int, 200)
        res_dict = jsonutils.loads(res.body)
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
        req = webob.Request.blank(
                    '/v2/faketenant_0/os-simple-tenant-usage?'
                    'detailed=%s&start=%s&end=%s' %
                    (detailed, START.isoformat(), STOP.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context,
                               init_only=('os-simple-tenant-usage',)))
        self.assertEqual(res.status_int, 200)
        res_dict = jsonutils.loads(res.body)
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
        req = webob.Request.blank(
                  '/v2/faketenant_0/os-simple-tenant-usage/'
                  'faketenant_%s?start=%s&end=%s' %
                  (tenant_id, start.isoformat(), stop.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context,
                               init_only=('os-simple-tenant-usage',)))
        self.assertEqual(res.status_int, 200)
        res_dict = jsonutils.loads(res.body)

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

    def test_verify_show_cant_view_other_tenant(self):
        req = webob.Request.blank(
                  '/v2/faketenant_1/os-simple-tenant-usage/'
                  'faketenant_0?start=%s&end=%s' %
                  (START.isoformat(), STOP.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        rules = {
            "compute_extension:simple_tenant_usage:show":
                common_policy.parse_rule([
                    ["role:admin"], ["project_id:%(project_id)s"]
                    ])
        }
        common_policy.set_rules(common_policy.Rules(rules))

        try:
            res = req.get_response(fakes.wsgi_app(
                                   fake_auth_context=self.alt_user_context,
                                   init_only=('os-simple-tenant-usage',)))
            self.assertEqual(res.status_int, 403)
        finally:
            policy.reset()

    def test_get_tenants_usage_with_bad_start_date(self):
        future = NOW + datetime.timedelta(hours=HOURS)
        tenant_id = 0
        req = webob.Request.blank(
                  '/v2/faketenant_0/os-simple-tenant-usage/'
                  'faketenant_%s?start=%s&end=%s' %
                  (tenant_id, future.isoformat(), NOW.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context,
                               init_only=('os-simple-tenant-usage',)))
        self.assertEqual(res.status_int, 400)

    def test_get_tenants_usage_with_invalid_start_date(self):
        tenant_id = 0
        req = webob.Request.blank(
                  '/v2/faketenant_0/os-simple-tenant-usage/'
                  'faketenant_%s?start=%s&end=%s' %
                  (tenant_id, "xxxx", NOW.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context,
                               init_only=('os-simple-tenant-usage',)))
        self.assertEqual(res.status_int, 400)

    def _test_get_tenants_usage_with_one_date(self, date_url_param):
        req = webob.Request.blank(
                  '/v2/faketenant_0/os-simple-tenant-usage/'
                  'faketenant_0?%s' % date_url_param)
        req.method = "GET"
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context,
                               init_only=('os-simple-tenant-usage',)))
        self.assertEqual(200, res.status_int)

    def test_get_tenants_usage_with_no_start_date(self):
        self._test_get_tenants_usage_with_one_date(
            'end=%s' % (NOW + datetime.timedelta(5)).isoformat())

    def test_get_tenants_usage_with_no_end_date(self):
        self._test_get_tenants_usage_with_one_date(
            'start=%s' % (NOW - datetime.timedelta(5)).isoformat())


class SimpleTenantUsageSerializerTest(test.TestCase):
    def _verify_server_usage(self, raw_usage, tree):
        self.assertEqual('server_usage', tree.tag)

        # Figure out what fields we expect
        not_seen = set(raw_usage.keys())

        for child in tree:
            self.assertIn(child.tag, not_seen)
            not_seen.remove(child.tag)
            self.assertEqual(str(raw_usage[child.tag]), child.text)

        self.assertEqual(len(not_seen), 0)

    def _verify_tenant_usage(self, raw_usage, tree):
        self.assertEqual('tenant_usage', tree.tag)

        # Figure out what fields we expect
        not_seen = set(raw_usage.keys())

        for child in tree:
            self.assertIn(child.tag, not_seen)
            not_seen.remove(child.tag)
            if child.tag == 'server_usages':
                for idx, gr_child in enumerate(child):
                    self._verify_server_usage(raw_usage['server_usages'][idx],
                                              gr_child)
            else:
                self.assertEqual(str(raw_usage[child.tag]), child.text)

        self.assertEqual(len(not_seen), 0)

    def test_serializer_show(self):
        serializer = simple_tenant_usage.SimpleTenantUsageTemplate()
        today = timeutils.utcnow()
        yesterday = today - datetime.timedelta(days=1)
        raw_usage = dict(
            tenant_id='tenant',
            total_local_gb_usage=789,
            total_vcpus_usage=456,
            total_memory_mb_usage=123,
            total_hours=24,
            start=yesterday,
            stop=today,
            server_usages=[dict(
                    instance_id='00000000-0000-0000-0000-0000000000000000',
                    name='test',
                    hours=24,
                    memory_mb=1024,
                    local_gb=50,
                    vcpus=1,
                    tenant_id='tenant',
                    flavor='m1.small',
                    started_at=yesterday,
                    ended_at=today,
                    state='terminated',
                    uptime=86400),
                           dict(
                    instance_id='00000000-0000-0000-0000-0000000000000002',
                    name='test2',
                    hours=12,
                    memory_mb=512,
                    local_gb=25,
                    vcpus=2,
                    tenant_id='tenant',
                    flavor='m1.tiny',
                    started_at=yesterday,
                    ended_at=today,
                    state='terminated',
                    uptime=43200),
                           ],
            )
        tenant_usage = dict(tenant_usage=raw_usage)
        text = serializer.serialize(tenant_usage)

        tree = etree.fromstring(text)

        self._verify_tenant_usage(raw_usage, tree)

    def test_serializer_index(self):
        serializer = simple_tenant_usage.SimpleTenantUsagesTemplate()
        today = timeutils.utcnow()
        yesterday = today - datetime.timedelta(days=1)
        raw_usages = [dict(
                tenant_id='tenant1',
                total_local_gb_usage=1024,
                total_vcpus_usage=23,
                total_memory_mb_usage=512,
                total_hours=24,
                start=yesterday,
                stop=today,
                server_usages=[dict(
                        instance_id='00000000-0000-0000-0000-0000000000000001',
                        name='test1',
                        hours=24,
                        memory_mb=1024,
                        local_gb=50,
                        vcpus=2,
                        tenant_id='tenant1',
                        flavor='m1.small',
                        started_at=yesterday,
                        ended_at=today,
                        state='terminated',
                        uptime=86400),
                               dict(
                        instance_id='00000000-0000-0000-0000-0000000000000002',
                        name='test2',
                        hours=42,
                        memory_mb=4201,
                        local_gb=25,
                        vcpus=1,
                        tenant_id='tenant1',
                        flavor='m1.tiny',
                        started_at=today,
                        ended_at=yesterday,
                        state='terminated',
                        uptime=43200),
                               ],
                ),
                      dict(
                tenant_id='tenant2',
                total_local_gb_usage=512,
                total_vcpus_usage=32,
                total_memory_mb_usage=1024,
                total_hours=42,
                start=today,
                stop=yesterday,
                server_usages=[dict(
                        instance_id='00000000-0000-0000-0000-0000000000000003',
                        name='test3',
                        hours=24,
                        memory_mb=1024,
                        local_gb=50,
                        vcpus=2,
                        tenant_id='tenant2',
                        flavor='m1.small',
                        started_at=yesterday,
                        ended_at=today,
                        state='terminated',
                        uptime=86400),
                               dict(
                        instance_id='00000000-0000-0000-0000-0000000000000002',
                        name='test2',
                        hours=42,
                        memory_mb=4201,
                        local_gb=25,
                        vcpus=1,
                        tenant_id='tenant4',
                        flavor='m1.tiny',
                        started_at=today,
                        ended_at=yesterday,
                        state='terminated',
                        uptime=43200),
                               ],
                ),
            ]
        tenant_usages = dict(tenant_usages=raw_usages)
        text = serializer.serialize(tenant_usages)

        tree = etree.fromstring(text)

        self.assertEqual('tenant_usages', tree.tag)
        self.assertEqual(len(raw_usages), len(tree))
        for idx, child in enumerate(tree):
            self._verify_tenant_usage(raw_usages[idx], child)


class SimpleTenantUsageControllerTest(test.TestCase):
    def setUp(self):
        super(SimpleTenantUsageControllerTest, self).setUp()
        self.controller = simple_tenant_usage.SimpleTenantUsageController()

        self.context = context.RequestContext('fakeuser', 'fake-project')

        self.baseinst = get_fake_db_instance(START, STOP, instance_id=1,
                                             tenant_id=self.context.project_id,
                                             vm_state=vm_states.DELETED)
        # convert the fake instance dict to an object
        self.inst_obj = instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), self.baseinst)

    def test_get_flavor_from_sys_meta(self):
        # Non-deleted instances get their type information from their
        # system_metadata
        with mock.patch.object(db, 'instance_get_by_uuid',
                               return_value=self.baseinst):
            flavor = self.controller._get_flavor(self.context,
                                                 self.inst_obj, {})
        self.assertEqual(flavor_obj.Flavor, type(flavor))
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
        self.assertEqual(flavor_obj.Flavor, type(flavor))
        self.assertEqual(FAKE_INST_TYPE['id'], flavor.id)

    def test_get_flavor_from_deleted_with_id_of_deleted(self):
        # Verify the legacy behavior of instance_type_id pointing to a
        # missing type being non-fatal
        self.inst_obj.system_metadata = {}
        self.inst_obj.deleted = 1
        self.inst_obj.instance_type_id = 99
        flavor = self.controller._get_flavor(self.context, self.inst_obj, {})
        self.assertIsNone(flavor)


class SimpleTenantUsageUtils(test.NoDBTestCase):
    def test_valid_string(self):
        dt = simple_tenant_usage.parse_strtime("2014-02-21T13:47:20.824060",
                                               "%Y-%m-%dT%H:%M:%S.%f")
        self.assertEqual(datetime.datetime(
                microsecond=824060, second=20, minute=47, hour=13,
                day=21, month=2, year=2014), dt)

    def test_invalid_string(self):
        self.assertRaises(exception.InvalidStrTime,
                          simple_tenant_usage.parse_strtime,
                          "2014-02-21 13:47:20.824060",
                          "%Y-%m-%dT%H:%M:%S.%f")

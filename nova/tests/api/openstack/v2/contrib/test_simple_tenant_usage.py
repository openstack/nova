# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
import json

from lxml import etree
import webob

from nova.api.openstack.v2.contrib import simple_tenant_usage
from nova.compute import api
from nova import context
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS

SERVERS = 5
TENANTS = 2
HOURS = 24
LOCAL_GB = 10
MEMORY_MB = 1024
VCPUS = 2
STOP = datetime.datetime.utcnow()
START = STOP - datetime.timedelta(hours=HOURS)


def fake_instance_type_get(self, context, instance_type_id):
    return {'id': 1,
            'vcpus': VCPUS,
            'local_gb': LOCAL_GB,
            'memory_mb': MEMORY_MB,
            'name':
            'fakeflavor'}


def get_fake_db_instance(start, end, instance_id, tenant_id):
    return  {'id': instance_id,
             'image_ref': '1',
             'project_id': tenant_id,
             'user_id': 'fakeuser',
             'display_name': 'name',
             'state_description': 'state',
             'instance_type_id': 1,
             'launched_at': start,
             'terminated_at': end}


def fake_instance_get_active_by_window(self, context, begin, end, project_id):
            return [get_fake_db_instance(START,
                                         STOP,
                                         x,
                                         "faketenant_%s" % (x / SERVERS))
                                         for x in xrange(TENANTS * SERVERS)]


class SimpleTenantUsageTest(test.TestCase):
    def setUp(self):
        super(SimpleTenantUsageTest, self).setUp()
        self.stubs.Set(api.API, "get_instance_type",
                       fake_instance_type_get)
        self.stubs.Set(api.API, "get_active_by_window",
                       fake_instance_get_active_by_window)
        self.admin_context = context.RequestContext('fakeadmin_0',
                                                    'faketenant_0',
                                                    is_admin=True)
        self.user_context = context.RequestContext('fakeadmin_0',
                                                   'faketenant_0',
                                                    is_admin=False)
        self.alt_user_context = context.RequestContext('fakeadmin_0',
                                                      'faketenant_1',
                                                       is_admin=False)
        FLAGS.allow_admin_api = True

    def test_verify_index(self):
        req = webob.Request.blank(
                    '/v2/123/os-simple-tenant-usage?start=%s&end=%s' %
                    (START.isoformat(), STOP.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))

        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        usages = res_dict['tenant_usages']
        from nova import log as logging
        logging.warn(usages)
        for i in xrange(TENANTS):
            self.assertEqual(int(usages[i]['total_hours']),
                             SERVERS * HOURS)
            self.assertEqual(int(usages[i]['total_local_gb_usage']),
                             SERVERS * LOCAL_GB * HOURS)
            self.assertEqual(int(usages[i]['total_memory_mb_usage']),
                             SERVERS * MEMORY_MB * HOURS)
            self.assertEqual(int(usages[i]['total_vcpus_usage']),
                             SERVERS * VCPUS * HOURS)
            self.assertFalse(usages[i].get('server_usages'))

    def test_verify_detailed_index(self):
        req = webob.Request.blank(
                    '/v2/123/os-simple-tenant-usage?'
                    'detailed=1&start=%s&end=%s' %
                    (START.isoformat(), STOP.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        usages = res_dict['tenant_usages']
        for i in xrange(TENANTS):
            servers = usages[i]['server_usages']
            for j in xrange(SERVERS):
                self.assertEqual(int(servers[j]['hours']), HOURS)

    def test_verify_index_fails_for_nonadmin(self):
        req = webob.Request.blank(
                    '/v2/123/os-simple-tenant-usage?'
                    'detailed=1&start=%s&end=%s' %
                    (START.isoformat(), STOP.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 403)

    def test_verify_show(self):
        req = webob.Request.blank(
                  '/v2/faketenant_0/os-simple-tenant-usage/'
                  'faketenant_0?start=%s&end=%s' %
                  (START.isoformat(), STOP.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context))
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)

        usage = res_dict['tenant_usage']
        servers = usage['server_usages']
        self.assertEqual(len(usage['server_usages']), SERVERS)
        for j in xrange(SERVERS):
            self.assertEqual(int(servers[j]['hours']), HOURS)

    def test_verify_show_cant_view_other_tenant(self):
        req = webob.Request.blank(
                  '/v2/faketenant_1/os-simple-tenant-usage/'
                  'faketenant_0?start=%s&end=%s' %
                  (START.isoformat(), STOP.isoformat()))
        req.method = "GET"
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.alt_user_context))
        self.assertEqual(res.status_int, 403)


class SimpleTenantUsageSerializerTest(test.TestCase):
    def _verify_server_usage(self, raw_usage, tree):
        self.assertEqual('server_usage', tree.tag)

        # Figure out what fields we expect
        not_seen = set(raw_usage.keys())

        for child in tree:
            self.assertTrue(child.tag in not_seen)
            not_seen.remove(child.tag)
            self.assertEqual(str(raw_usage[child.tag]), child.text)

        self.assertEqual(len(not_seen), 0)

    def _verify_tenant_usage(self, raw_usage, tree):
        self.assertEqual('tenant_usage', tree.tag)

        # Figure out what fields we expect
        not_seen = set(raw_usage.keys())

        for child in tree:
            self.assertTrue(child.tag in not_seen)
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
        today = datetime.datetime.now()
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

        print text
        tree = etree.fromstring(text)

        self._verify_tenant_usage(raw_usage, tree)

    def test_serializer_index(self):
        serializer = simple_tenant_usage.SimpleTenantUsagesTemplate()
        today = datetime.datetime.now()
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

        print text
        tree = etree.fromstring(text)

        self.assertEqual('tenant_usages', tree.tag)
        self.assertEqual(len(raw_usages), len(tree))
        for idx, child in enumerate(tree):
            self._verify_tenant_usage(raw_usages[idx], child)

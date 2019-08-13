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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from six.moves import range
import webob

from nova.api.openstack.compute import simple_tenant_usage as \
    simple_tenant_usage_v21
from nova.compute import vm_states
import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes


CONF = nova.conf.CONF


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


def _fake_instance(start, end, instance_id, tenant_id,
                   vm_state=vm_states.ACTIVE):
    flavor = objects.Flavor(**FAKE_INST_TYPE)
    return objects.Instance(
        deleted=False,
        id=instance_id,
        uuid=getattr(uuids, 'instance_%d' % instance_id),
        image_ref='1',
        project_id=tenant_id,
        user_id='fakeuser',
        display_name='name',
        instance_type_id=FAKE_INST_TYPE['id'],
        launched_at=start,
        terminated_at=end,
        vm_state=vm_state,
        memory_mb=MEMORY_MB,
        vcpus=VCPUS,
        root_gb=ROOT_GB,
        ephemeral_gb=EPHEMERAL_GB,
        flavor=flavor)


def _fake_instance_deleted_flavorless(context, start, end, instance_id,
                                      tenant_id, vm_state=vm_states.ACTIVE):
    return objects.Instance(
        context=context,
        deleted=instance_id,
        id=instance_id,
        uuid=getattr(uuids, 'instance_%d' % instance_id),
        image_ref='1',
        project_id=tenant_id,
        user_id='fakeuser',
        display_name='name',
        instance_type_id=FAKE_INST_TYPE['id'],
        launched_at=start,
        terminated_at=end,
        deleted_at=start,
        vm_state=vm_state,
        memory_mb=MEMORY_MB,
        vcpus=VCPUS,
        root_gb=ROOT_GB,
        ephemeral_gb=EPHEMERAL_GB)


@classmethod
def fake_get_active_deleted_flavorless(cls, context, begin, end=None,
                                       project_id=None, host=None,
                                       expected_attrs=None, use_slave=False,
                                       limit=None, marker=None):
    # First get some normal instances to have actual usage
    instances = [
        _fake_instance(START, STOP, x,
                       project_id or 'faketenant_%s' % (x // SERVERS))
        for x in range(TENANTS * SERVERS)]
    # Then get some deleted instances with no flavor to test bugs 1643444 and
    # 1692893 (duplicates)
    instances.extend([
        _fake_instance_deleted_flavorless(
            context, START, STOP, x,
            project_id or 'faketenant_%s' % (x // SERVERS))
        for x in range(TENANTS * SERVERS)])
    return objects.InstanceList(objects=instances)


@classmethod
def fake_get_active_by_window_joined(cls, context, begin, end=None,
                                     project_id=None, host=None,
                                     expected_attrs=None, use_slave=False,
                                     limit=None, marker=None):
    return objects.InstanceList(objects=[
        _fake_instance(START, STOP, x,
                       project_id or 'faketenant_%s' % (x // SERVERS))
        for x in range(TENANTS * SERVERS)])


class SimpleTenantUsageTestV21(test.TestCase):
    version = '2.1'
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
        self.num_cells = len(objects.CellMappingList.get_all(
            self.admin_context))

    def _test_verify_index(self, start, stop, limit=None):
        url = '?start=%s&end=%s'
        if limit:
            url += '&limit=%s' % (limit)
        req = fakes.HTTPRequest.blank(url %
                    (start.isoformat(), stop.isoformat()),
                    version=self.version)
        req.environ['nova.context'] = self.admin_context
        res_dict = self.controller.index(req)

        usages = res_dict['tenant_usages']

        if limit:
            num = 1
        else:
            # NOTE(danms): We call our fake data mock once per cell,
            # and the default fixture has two cells (cell0 and cell1),
            # so all our math will be doubled.
            num = self.num_cells

        for i in range(TENANTS):
            self.assertEqual(SERVERS * HOURS * num,
                             int(usages[i]['total_hours']))
            self.assertEqual(SERVERS * (ROOT_GB + EPHEMERAL_GB) * HOURS * num,
                             int(usages[i]['total_local_gb_usage']))
            self.assertEqual(SERVERS * MEMORY_MB * HOURS * num,
                             int(usages[i]['total_memory_mb_usage']))
            self.assertEqual(SERVERS * VCPUS * HOURS * num,
                             int(usages[i]['total_vcpus_usage']))
            self.assertFalse(usages[i].get('server_usages'))

        if limit:
            self.assertIn('tenant_usages_links', res_dict)
            self.assertEqual('next', res_dict['tenant_usages_links'][0]['rel'])
        else:
            self.assertNotIn('tenant_usages_links', res_dict)

    # NOTE(artom) Test for bugs 1643444 and 1692893 (duplicates). We simulate a
    # situation where an instance has been deleted (moved to shadow table) and
    # its corresponding instance_extra row has been archived (deleted from
    # shadow table).
    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_deleted_flavorless)
    @mock.patch.object(
        objects.Instance, '_load_flavor',
        side_effect=exception.InstanceNotFound(instance_id='fake-id'))
    def test_verify_index_deleted_flavorless(self, mock_load):
        with mock.patch.object(self.controller, '_get_flavor',
                               return_value=None):
            self._test_verify_index(START, STOP)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def test_verify_index(self):
        self._test_verify_index(START, STOP)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def test_verify_index_future_end_time(self):
        future = NOW + datetime.timedelta(hours=HOURS)
        self._test_verify_index(START, future)

    def test_verify_show(self):
        self._test_verify_show(START, STOP)

    def test_verify_show_future_end_time(self):
        future = NOW + datetime.timedelta(hours=HOURS)
        self._test_verify_show(START, future)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def _get_tenant_usages(self, detailed=''):
        req = fakes.HTTPRequest.blank('?detailed=%s&start=%s&end=%s' %
                    (detailed, START.isoformat(), STOP.isoformat()),
                    version=self.version)
        req.environ['nova.context'] = self.admin_context

        # Make sure that get_active_by_window_joined is only called with
        # expected_attrs=['flavor'].
        orig_get_active_by_window_joined = (
            objects.InstanceList.get_active_by_window_joined)

        def fake_get_active_by_window_joined(context, begin, end=None,
                                    project_id=None, host=None,
                                    expected_attrs=None, use_slave=False,
                                    limit=None, marker=None):
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

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def _test_verify_show(self, start, stop, limit=None):
        tenant_id = 1
        url = '?start=%s&end=%s'
        if limit:
            url += '&limit=%s' % (limit)
        req = fakes.HTTPRequest.blank(url %
                    (start.isoformat(), stop.isoformat()),
                    version=self.version)
        req.environ['nova.context'] = self.user_context
        res_dict = self.controller.show(req, tenant_id)

        if limit:
            num = 1
        else:
            # NOTE(danms): We call our fake data mock once per cell,
            # and the default fixture has two cells (cell0 and cell1),
            # so all our math will be doubled.
            num = self.num_cells

        usage = res_dict['tenant_usage']
        servers = usage['server_usages']
        self.assertEqual(TENANTS * SERVERS * num, len(usage['server_usages']))
        server_uuids = [getattr(uuids, 'instance_%d' % x)
                        for x in range(SERVERS)]
        for j in range(SERVERS):
            delta = STOP - START
            # NOTE(javeme): cast seconds from float to int for clarity
            uptime = int(delta.total_seconds())
            self.assertEqual(uptime, int(servers[j]['uptime']))
            self.assertEqual(HOURS, int(servers[j]['hours']))
            self.assertIn(servers[j]['instance_id'], server_uuids)

        if limit:
            self.assertIn('tenant_usage_links', res_dict)
            self.assertEqual('next', res_dict['tenant_usage_links'][0]['rel'])
        else:
            self.assertNotIn('tenant_usage_links', res_dict)

    def test_verify_show_cannot_view_other_tenant(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    (START.isoformat(), STOP.isoformat()),
                    version=self.version)
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
                    (future.isoformat(), NOW.isoformat()),
                    version=self.version)
        req.environ['nova.context'] = self.user_context
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.show, req, 'faketenant_0')

    def test_get_tenants_usage_with_invalid_start_date(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s' %
                    ("xxxx", NOW.isoformat()),
                    version=self.version)
        req.environ['nova.context'] = self.user_context
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.show, req, 'faketenant_0')

    def _test_get_tenants_usage_with_one_date(self, date_url_param):
        req = fakes.HTTPRequest.blank('?%s' % date_url_param,
                                      version=self.version)
        req.environ['nova.context'] = self.user_context
        res = self.controller.show(req, 'faketenant_0')
        self.assertIn('tenant_usage', res)

    def test_get_tenants_usage_with_no_start_date(self):
        self._test_get_tenants_usage_with_one_date(
            'end=%s' % (NOW + datetime.timedelta(5)).isoformat())

    def test_get_tenants_usage_with_no_end_date(self):
        self._test_get_tenants_usage_with_one_date(
            'start=%s' % (NOW - datetime.timedelta(5)).isoformat())

    def test_index_additional_query_parameters(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s&additional=1' %
                (START.isoformat(), STOP.isoformat()),
                version=self.version)
        res = self.controller.index(req)
        self.assertIn('tenant_usages', res)

    def _test_index_duplicate_query_parameters_validation(self, params):
        for param, value in params.items():
            req = fakes.HTTPRequest.blank('?start=%s&%s=%s&%s=%s' %
                    (START.isoformat(), param, value, param, value),
                    version=self.version)

            res = self.controller.index(req)
            self.assertIn('tenant_usages', res)

    def test_index_duplicate_query_parameters_validation(self):
        params = {
            'start': START.isoformat(),
            'end': STOP.isoformat(),
            'detailed': 1
        }
        self._test_index_duplicate_query_parameters_validation(params)

    def test_show_additional_query_parameters(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s&additional=1' %
                (START.isoformat(), STOP.isoformat()),
                version=self.version)
        res = self.controller.show(req, 1)
        self.assertIn('tenant_usage', res)

    def _test_show_duplicate_query_parameters_validation(self, params):
        for param, value in params.items():
            req = fakes.HTTPRequest.blank('?start=%s&%s=%s&%s=%s' %
                    (START.isoformat(), param, value, param, value),
                    version=self.version)

            res = self.controller.show(req, 1)
            self.assertIn('tenant_usage', res)

    def test_show_duplicate_query_parameters_validation(self):
        params = {
            'start': START.isoformat(),
            'end': STOP.isoformat()
        }
        self._test_show_duplicate_query_parameters_validation(params)


class SimpleTenantUsageTestV40(SimpleTenantUsageTestV21):
    version = '2.40'

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def test_next_links_show(self):
        self._test_verify_show(START, STOP,
                               limit=SERVERS * TENANTS)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def test_next_links_index(self):
        self._test_verify_index(START, STOP,
                                limit=SERVERS * TENANTS)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def test_index_duplicate_query_parameters_validation(self):
        params = {
            'start': START.isoformat(),
            'end': STOP.isoformat(),
            'detailed': 1,
            'limit': 1,
            'marker': 1
        }
        self._test_index_duplicate_query_parameters_validation(params)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined',
                fake_get_active_by_window_joined)
    def test_show_duplicate_query_parameters_validation(self):
        params = {
            'start': START.isoformat(),
            'end': STOP.isoformat(),
            'limit': 1,
            'marker': 1
        }
        self._test_show_duplicate_query_parameters_validation(params)


class SimpleTenantUsageTestV2_75(SimpleTenantUsageTestV40):
    version = '2.75'

    def test_index_additional_query_param_old_version(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s&additional=1' %
                (START.isoformat(), STOP.isoformat()),
                version='2.74')
        res = self.controller.index(req)
        self.assertIn('tenant_usages', res)

    def test_index_additional_query_parameters(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s&additional=1' %
                (START.isoformat(), STOP.isoformat()),
                version=self.version)
        self.assertRaises(exception.ValidationError, self.controller.index,
                          req)

    def test_show_additional_query_param_old_version(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s&additional=1' %
                (START.isoformat(), STOP.isoformat()),
                version='2.74')
        res = self.controller.show(req, 1)
        self.assertIn('tenant_usage', res)

    def test_show_additional_query_parameters(self):
        req = fakes.HTTPRequest.blank('?start=%s&end=%s&additional=1' %
                (START.isoformat(), STOP.isoformat()),
                version=self.version)
        self.assertRaises(exception.ValidationError, self.controller.show,
                          req, 1)


class SimpleTenantUsageLimitsTestV21(test.TestCase):
    version = '2.1'

    def setUp(self):
        super(SimpleTenantUsageLimitsTestV21, self).setUp()
        self.controller = simple_tenant_usage_v21.SimpleTenantUsageController()
        self.tenant_id = 1

    def _get_request(self, url):
        url = url % (START.isoformat(), STOP.isoformat())
        return fakes.HTTPRequest.blank(url, version=self.version)

    def assert_limit(self, mock_get, limit):
        mock_get.assert_called_with(
            mock.ANY, mock.ANY, mock.ANY, mock.ANY, expected_attrs=['flavor'],
            limit=1000, marker=None)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined')
    def test_limit_defaults_to_conf_max_limit_show(self, mock_get):
        req = self._get_request('?start=%s&end=%s')
        self.controller.show(req, self.tenant_id)
        self.assert_limit(mock_get, CONF.api.max_limit)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined')
    def test_limit_defaults_to_conf_max_limit_index(self, mock_get):
        req = self._get_request('?start=%s&end=%s')
        self.controller.index(req)
        self.assert_limit(mock_get, CONF.api.max_limit)


class SimpleTenantUsageLimitsTestV240(SimpleTenantUsageLimitsTestV21):
    version = '2.40'

    def assert_limit_and_marker(self, mock_get, limit, marker):
        # NOTE(danms): Make sure we called at least once with the marker
        mock_get.assert_any_call(
            mock.ANY, mock.ANY, mock.ANY, mock.ANY, expected_attrs=['flavor'],
            limit=3, marker=marker)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined')
    def test_limit_and_marker_show(self, mock_get):
        req = self._get_request('?start=%s&end=%s&limit=3&marker=some-marker')
        self.controller.show(req, self.tenant_id)
        self.assert_limit_and_marker(mock_get, 3, 'some-marker')

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined')
    def test_limit_and_marker_index(self, mock_get):
        req = self._get_request('?start=%s&end=%s&limit=3&marker=some-marker')
        self.controller.index(req)
        self.assert_limit_and_marker(mock_get, 3, 'some-marker')

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined')
    def test_marker_not_found_show(self, mock_get):
        mock_get.side_effect = exception.MarkerNotFound(marker='some-marker')
        req = self._get_request('?start=%s&end=%s&limit=3&marker=some-marker')
        self.assertRaises(
            webob.exc.HTTPBadRequest, self.controller.show, req, 1)

    @mock.patch('nova.objects.InstanceList.get_active_by_window_joined')
    def test_marker_not_found_index(self, mock_get):
        mock_get.side_effect = exception.MarkerNotFound(marker='some-marker')
        req = self._get_request('?start=%s&end=%s&limit=3&marker=some-marker')
        self.assertRaises(
            webob.exc.HTTPBadRequest, self.controller.index, req)

    def test_index_with_invalid_non_int_limit(self):
        req = self._get_request('?start=%s&end=%s&limit=-3')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_with_invalid_string_limit(self):
        req = self._get_request('?start=%s&end=%s&limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_index_duplicate_query_with_invalid_string_limit(self):
        req = self._get_request('?start=%s&end=%s&limit=3&limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_show_with_invalid_non_int_limit(self):
        req = self._get_request('?start=%s&end=%s&limit=-3')
        self.assertRaises(exception.ValidationError,
                          self.controller.show, req)

    def test_show_with_invalid_string_limit(self):
        req = self._get_request('?start=%s&end=%s&limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.show, req)

    def test_show_duplicate_query_with_invalid_string_limit(self):
        req = self._get_request('?start=%s&end=%s&limit=3&limit=abc')
        self.assertRaises(exception.ValidationError,
                          self.controller.show, req)


class SimpleTenantUsageControllerTestV21(test.TestCase):
    controller = simple_tenant_usage_v21.SimpleTenantUsageController()

    def setUp(self):
        super(SimpleTenantUsageControllerTestV21, self).setUp()

        self.context = context.RequestContext('fakeuser', 'fake-project')

        self.inst_obj = _fake_instance(START, STOP, instance_id=1,
                                       tenant_id=self.context.project_id,
                                       vm_state=vm_states.DELETED)

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

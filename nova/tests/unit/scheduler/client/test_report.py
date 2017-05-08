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

from keystoneauth1 import exceptions as ks_exc
import mock
import six
from six.moves.urllib import parse

import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova.scheduler.client import report
from nova import test
from nova.tests import uuidsentinel as uuids

CONF = nova.conf.CONF


class SafeConnectedTestCase(test.NoDBTestCase):
    """Test the safe_connect decorator for the scheduler client."""

    def setUp(self):
        super(SafeConnectedTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.ks_sess_mock = mock.Mock()

        with test.nested(
                mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
        ) as _auth_mock:  # noqa
            self.client = report.SchedulerReportClient()

    @mock.patch('keystoneauth1.session.Session.request')
    def test_missing_endpoint(self, req):
        """Test EndpointNotFound behavior.

        A missing endpoint entry should not explode.
        """
        req.side_effect = ks_exc.EndpointNotFound()
        self.client._get_resource_provider("fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        self.assertTrue(req.called)

    @mock.patch('keystoneauth1.session.Session.request')
    def test_missing_auth(self, req):
        """Test Missing Auth handled correctly.

        A missing auth configuration should not explode.

        """
        req.side_effect = ks_exc.MissingAuthPlugin()
        self.client._get_resource_provider("fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        self.assertTrue(req.called)

    @mock.patch('keystoneauth1.session.Session.request')
    def test_unauthorized(self, req):
        """Test Unauthorized handled correctly.

        An unauthorized configuration should not explode.

        """
        req.side_effect = ks_exc.Unauthorized()
        self.client._get_resource_provider("fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        self.assertTrue(req.called)

    @mock.patch('keystoneauth1.session.Session.request')
    def test_connect_fail(self, req):
        """Test Connect Failure handled correctly.

        If we get a connect failure, this is transient, and we expect
        that this will end up working correctly later.

        """
        req.side_effect = ks_exc.ConnectFailure()
        self.client._get_resource_provider("fake")

        # reset the call count to demonstrate that future calls do
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        self.assertTrue(req.called)

    @mock.patch.object(report, 'LOG')
    def test_warning_limit(self, mock_log):
        # Assert that __init__ initializes _warn_count as we expect
        self.assertEqual(0, self.client._warn_count)
        mock_self = mock.MagicMock()
        mock_self._warn_count = 0
        for i in range(0, report.WARN_EVERY + 3):
            report.warn_limit(mock_self, 'warning')
        mock_log.warning.assert_has_calls([mock.call('warning'),
                                           mock.call('warning')])

    @mock.patch('keystoneauth1.session.Session.request')
    def test_failed_discovery(self, req):
        """Test DiscoveryFailure behavior.

        Failed discovery should not blow up.
        """
        req.side_effect = ks_exc.DiscoveryFailure()
        self.client._get_resource_provider("fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        self.assertTrue(req.called)


class TestConstructor(test.NoDBTestCase):
    @mock.patch('keystoneauth1.loading.load_session_from_conf_options')
    @mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
    def test_constructor(self, load_auth_mock, load_sess_mock):
        client = report.SchedulerReportClient()

        load_auth_mock.assert_called_once_with(CONF, 'placement')
        load_sess_mock.assert_called_once_with(CONF, 'placement',
                                              auth=load_auth_mock.return_value)
        self.assertIsNone(client.ks_filter['interface'])

    @mock.patch('keystoneauth1.loading.load_session_from_conf_options')
    @mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
    def test_constructor_admin_interface(self, load_auth_mock, load_sess_mock):
        self.flags(os_interface='admin', group='placement')
        client = report.SchedulerReportClient()

        load_auth_mock.assert_called_once_with(CONF, 'placement')
        load_sess_mock.assert_called_once_with(CONF, 'placement',
                                              auth=load_auth_mock.return_value)
        self.assertEqual('admin', client.ks_filter['interface'])


class SchedulerReportClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerReportClientTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.ks_sess_mock = mock.Mock()
        self.compute_node = objects.ComputeNode(
            uuid=uuids.compute_node,
            hypervisor_hostname='foo',
            vcpus=8,
            cpu_allocation_ratio=16.0,
            memory_mb=1024,
            ram_allocation_ratio=1.5,
            local_gb=10,
            disk_allocation_ratio=1.0,
        )

        with test.nested(
                mock.patch('keystoneauth1.session.Session',
                           return_value=self.ks_sess_mock),
                mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
        ) as (_auth_mock, _sess_mock):
            self.client = report.SchedulerReportClient()


class TestPutAllocations(SchedulerReportClientTestCase):
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations(self, mock_put):
        mock_put.return_value.status_code = 204
        mock_put.return_value.text = "cool"
        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        resp = self.client.put_allocations(rp_uuid, consumer_uuid, data)
        self.assertTrue(resp)
        mock_put.assert_called_once_with(expected_url, mock.ANY)

    @mock.patch.object(report.LOG, 'warning')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations_fail(self, mock_put, mock_warn):
        mock_put.return_value.status_code = 400
        mock_put.return_value.text = "not cool"
        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        resp = self.client.put_allocations(rp_uuid, consumer_uuid, data)
        self.assertFalse(resp)
        mock_put.assert_called_once_with(expected_url, mock.ANY)
        log_msg = mock_warn.call_args[0][0]
        self.assertIn("Unable to submit allocation for instance", log_msg)


class TestProviderOperations(SchedulerReportClientTestCase):
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_exists_in_cache(self, get_rp_mock,
            get_agg_mock, create_rp_mock):
        # Override the client object's cache to contain a resource provider
        # object for the compute host and check that
        # _ensure_resource_provider() doesn't call _get_resource_provider() or
        # _create_resource_provider()
        self.client._resource_providers = {
            uuids.compute_node: mock.sentinel.rp
        }

        self.client._ensure_resource_provider(uuids.compute_node)
        get_agg_mock.assert_called_once_with(uuids.compute_node)
        self.assertIn(uuids.compute_node, self.client._provider_aggregate_map)
        self.assertEqual(
            get_agg_mock.return_value,
            self.client._provider_aggregate_map[uuids.compute_node]
        )
        self.assertFalse(get_rp_mock.called)
        self.assertFalse(create_rp_mock.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_get(self, get_rp_mock, get_agg_mock,
            create_rp_mock):
        # No resource provider exists in the client's cache, so validate that
        # if we get the resource provider from the placement API that we don't
        # try to create the resource provider.
        get_rp_mock.return_value = mock.sentinel.rp

        self.client._ensure_resource_provider(uuids.compute_node)

        get_rp_mock.assert_called_once_with(uuids.compute_node)
        get_agg_mock.assert_called_once_with(uuids.compute_node)
        self.assertIn(uuids.compute_node, self.client._provider_aggregate_map)
        self.assertEqual(
            get_agg_mock.return_value,
            self.client._provider_aggregate_map[uuids.compute_node]
        )
        self.assertEqual({uuids.compute_node: mock.sentinel.rp},
                          self.client._resource_providers)
        self.assertFalse(create_rp_mock.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_create_none(self, get_rp_mock,
            get_agg_mock, create_rp_mock):
        # No resource provider exists in the client's cache, and
        # _create_provider returns None, indicating there was an error with the
        # create call. Ensure we don't populate the resource provider cache
        # with a None value.
        get_rp_mock.return_value = None
        create_rp_mock.return_value = None

        self.client._ensure_resource_provider(uuids.compute_node)

        get_rp_mock.assert_called_once_with(uuids.compute_node)
        create_rp_mock.assert_called_once_with(uuids.compute_node,
                                               uuids.compute_node)
        self.assertFalse(get_agg_mock.called)
        self.assertEqual({}, self.client._resource_providers)
        self.assertEqual({}, self.client._provider_aggregate_map)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_create(self, get_rp_mock, get_agg_mock,
            create_rp_mock):
        # No resource provider exists in the client's cache and no resource
        # provider was returned from the placement API, so verify that in this
        # case we try to create the resource provider via the placement API.
        get_rp_mock.return_value = None
        create_rp_mock.return_value = mock.sentinel.rp

        self.client._ensure_resource_provider(uuids.compute_node)

        get_agg_mock.assert_called_once_with(uuids.compute_node)
        self.assertIn(uuids.compute_node, self.client._provider_aggregate_map)
        self.assertEqual(
            get_agg_mock.return_value,
            self.client._provider_aggregate_map[uuids.compute_node]
        )
        get_rp_mock.assert_called_once_with(uuids.compute_node)
        create_rp_mock.assert_called_once_with(
                uuids.compute_node,
                uuids.compute_node,  # name param defaults to UUID if None
        )
        self.assertEqual({uuids.compute_node: mock.sentinel.rp},
                          self.client._resource_providers)

        create_rp_mock.reset_mock()
        self.client._resource_providers = {}

        self.client._ensure_resource_provider(uuids.compute_node,
                                              mock.sentinel.name)

        create_rp_mock.assert_called_once_with(
                uuids.compute_node,
                mock.sentinel.name,
        )

    def test_get_filtered_resource_providers(self):
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'resource_providers': [
                {'uuid': uuid,
                 'name': uuid,
                 'generation': 42}
            ],
        }
        filters = {'resources': {'VCPU': 1, 'MEMORY_MB': 1024}}
        resp_mock.json.return_value = json_data
        self.ks_sess_mock.get.return_value = resp_mock

        result = self.client.get_filtered_resource_providers(filters)

        expected_provider_dict = dict(
                uuid=uuid,
                name=uuid,
                generation=42,
        )
        expected_url = '/resource_providers?%s' % parse.urlencode(
            {'resources': 'MEMORY_MB:1024,VCPU:1'})
        self.ks_sess_mock.get.assert_called_once_with(
            expected_url, endpoint_filter=mock.ANY, raise_exc=False,
            headers={'OpenStack-API-Version': 'placement 1.4'})
        self.assertEqual(expected_provider_dict, result[0])

    def test_get_filtered_resource_providers_not_found(self):
        # Ensure _get_resource_provider() just returns None when the placement
        # API doesn't find a resource provider matching a UUID
        resp_mock = mock.Mock(status_code=404)
        self.ks_sess_mock.get.return_value = resp_mock

        result = self.client.get_filtered_resource_providers({'foo': 'bar'})

        expected_url = '/resource_providers?foo=bar'
        self.ks_sess_mock.get.assert_called_once_with(
            expected_url, endpoint_filter=mock.ANY, raise_exc=False,
            headers={'OpenStack-API-Version': 'placement 1.4'})
        self.assertIsNone(result)

    def test_get_resource_provider_found(self):
        # Ensure _get_resource_provider() returns a dict of resource provider
        # if it finds a resource provider record from the placement API
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'uuid': uuid,
            'name': uuid,
            'generation': 42,
        }
        resp_mock.json.return_value = json_data
        self.ks_sess_mock.get.return_value = resp_mock

        result = self.client._get_resource_provider(uuid)

        expected_provider_dict = dict(
                uuid=uuid,
                name=uuid,
                generation=42,
        )
        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        self.assertEqual(expected_provider_dict, result)

    def test_get_resource_provider_not_found(self):
        # Ensure _get_resource_provider() just returns None when the placement
        # API doesn't find a resource provider matching a UUID
        resp_mock = mock.Mock(status_code=404)
        self.ks_sess_mock.get.return_value = resp_mock

        uuid = uuids.compute_node
        result = self.client._get_resource_provider(uuid)

        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        self.assertIsNone(result)

    @mock.patch.object(report.LOG, 'error')
    def test_get_resource_provider_error(self, logging_mock):
        # Ensure _get_resource_provider() sets the error flag when trying to
        # communicate with the placement API and not getting an error we can
        # deal with
        resp_mock = mock.Mock(status_code=503)
        self.ks_sess_mock.get.return_value = resp_mock
        self.ks_sess_mock.get.return_value.headers = {
            'openstack-request-id': uuids.request_id}

        uuid = uuids.compute_node
        result = self.client._get_resource_provider(uuid)

        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        # A 503 Service Unavailable should trigger an error log
        # that includes the placement request id and return None
        # from _get_resource_provider()
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                        logging_mock.call_args[0][1]['placement_req_id'])
        self.assertIsNone(result)

    def test_create_resource_provider(self):
        # Ensure _create_resource_provider() returns a dict of resource
        # provider constructed after creating a resource provider record in the
        # placement API
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=201)
        self.ks_sess_mock.post.return_value = resp_mock

        result = self.client._create_resource_provider(uuid, name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_provider_dict = dict(
            uuid=uuid,
            name=name,
            generation=0,
        )
        expected_url = '/resource_providers'
        self.ks_sess_mock.post.assert_called_once_with(
                expected_url,
                endpoint_filter=mock.ANY,
                json=expected_payload,
                raise_exc=False)
        self.assertEqual(expected_provider_dict, result)

    @mock.patch.object(report.LOG, 'info')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_create_resource_provider_concurrent_create(self, get_rp_mock,
                                                        logging_mock):
        # Ensure _create_resource_provider() returns a dict of resource
        # provider gotten from _get_resource_provider() if the call to create
        # the resource provider in the placement API returned a 409 Conflict,
        # indicating another thread concurrently created the resource provider
        # record.
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=409)
        self.ks_sess_mock.post.return_value = resp_mock
        self.ks_sess_mock.post.return_value.headers = {
            'openstack-request-id': uuids.request_id}

        get_rp_mock.return_value = mock.sentinel.get_rp

        result = self.client._create_resource_provider(uuid, name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_url = '/resource_providers'
        self.ks_sess_mock.post.assert_called_once_with(
                expected_url,
                endpoint_filter=mock.ANY,
                json=expected_payload,
                raise_exc=False)
        self.assertEqual(mock.sentinel.get_rp, result)
        # The 409 response will produce a message to the info log.
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                        logging_mock.call_args[0][1]['placement_req_id'])

    @mock.patch.object(report.LOG, 'error')
    def test_create_resource_provider_error(self, logging_mock):
        # Ensure _create_resource_provider() sets the error flag when trying to
        # communicate with the placement API and not getting an error we can
        # deal with
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=503)
        self.ks_sess_mock.post.return_value = resp_mock
        self.ks_sess_mock.post.return_value.headers = {
            'x-openstack-request-id': uuids.request_id}

        result = self.client._create_resource_provider(uuid, name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_url = '/resource_providers'
        self.ks_sess_mock.post.assert_called_once_with(
                expected_url,
                endpoint_filter=mock.ANY,
                json=expected_payload,
                raise_exc=False)
        # A 503 Service Unavailable should log an error that
        # includes the placement request id and
        # _create_resource_provider() should return None
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                        logging_mock.call_args[0][1]['placement_req_id'])
        self.assertFalse(result)


class TestAggregates(SchedulerReportClientTestCase):
    def test_get_provider_aggregates_found(self):
        """Test that when the placement API returns a list of aggregate UUIDs,
        that we cache that aggregate information in the appropriate map.
        """
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'aggregates': [
                uuids.agg1,
                uuids.agg2,
            ],
        }
        resp_mock.json.return_value = json_data
        self.ks_sess_mock.get.return_value = resp_mock

        result = self.client._get_provider_aggregates(uuid)

        expected = set([
            uuids.agg1,
            uuids.agg2,
        ])
        expected_url = '/resource_providers/' + uuid + '/aggregates'
        self.ks_sess_mock.get.assert_called_once_with(
            expected_url, endpoint_filter=mock.ANY, raise_exc=False,
            headers={'OpenStack-API-Version': 'placement 1.1'})
        self.assertEqual(expected, result)

    @mock.patch.object(report.LOG, 'warning')
    def test_get_provider_aggregates_not_found(self, log_mock):
        """Test that when the placement API returns a 404 when looking up a
        provider's aggregates, that we simply return None and log a warning
        (since _get_provider_aggregates() should be called after
        _ensure_resource_provider()).
        """
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=404)
        self.ks_sess_mock.get.return_value = resp_mock
        self.ks_sess_mock.get.return_value.headers = {
            'x-openstack-request-id': uuids.request_id}

        result = self.client._get_provider_aggregates(uuid)

        expected_url = '/resource_providers/' + uuid + '/aggregates'
        self.ks_sess_mock.get.assert_called_once_with(
            expected_url, endpoint_filter=mock.ANY, raise_exc=False,
            headers={'OpenStack-API-Version': 'placement 1.1'})
        self.assertTrue(log_mock.called)
        self.assertEqual(uuids.request_id,
                        log_mock.call_args[0][1]['placement_req_id'])
        self.assertIsNone(result)

    @mock.patch.object(report.LOG, 'error')
    def test_get_provider_aggregates_bad_request(self, log_mock):
        """Test that when the placement API returns a 400 when looking up a
        provider's aggregates, that we simply return None and log an error.
        """
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=400)
        self.ks_sess_mock.get.return_value = resp_mock
        self.ks_sess_mock.get.return_value.headers = {
            'x-openstack-request-id': uuids.request_id}

        result = self.client._get_provider_aggregates(uuid)

        expected_url = '/resource_providers/' + uuid + '/aggregates'
        self.ks_sess_mock.get.assert_called_once_with(
            expected_url, endpoint_filter=mock.ANY, raise_exc=False,
            headers={'OpenStack-API-Version': 'placement 1.1'})
        self.assertTrue(log_mock.called)
        self.assertEqual(uuids.request_id,
                        log_mock.call_args[0][1]['placement_req_id'])
        self.assertIsNone(result)


class TestComputeNodeToInventoryDict(test.NoDBTestCase):
    def test_compute_node_inventory(self):
        uuid = uuids.compute_node
        name = 'computehost'
        compute_node = objects.ComputeNode(uuid=uuid,
                                           hypervisor_hostname=name,
                                           vcpus=2,
                                           cpu_allocation_ratio=16.0,
                                           memory_mb=1024,
                                           ram_allocation_ratio=1.5,
                                           local_gb=10,
                                           disk_allocation_ratio=1.0)

        self.flags(reserved_host_memory_mb=1000)
        self.flags(reserved_host_disk_mb=200)
        self.flags(reserved_host_cpus=1)

        result = report._compute_node_to_inventory_dict(compute_node)

        expected = {
            'VCPU': {
                'total': compute_node.vcpus,
                'reserved': CONF.reserved_host_cpus,
                'min_unit': 1,
                'max_unit': compute_node.vcpus,
                'step_size': 1,
                'allocation_ratio': compute_node.cpu_allocation_ratio,
            },
            'MEMORY_MB': {
                'total': compute_node.memory_mb,
                'reserved': CONF.reserved_host_memory_mb,
                'min_unit': 1,
                'max_unit': compute_node.memory_mb,
                'step_size': 1,
                'allocation_ratio': compute_node.ram_allocation_ratio,
            },
            'DISK_GB': {
                'total': compute_node.local_gb,
                'reserved': 1,  # this is ceil(1000/1024)
                'min_unit': 1,
                'max_unit': compute_node.local_gb,
                'step_size': 1,
                'allocation_ratio': compute_node.disk_allocation_ratio,
            },
        }
        self.assertEqual(expected, result)

    def test_compute_node_inventory_empty(self):
        uuid = uuids.compute_node
        name = 'computehost'
        compute_node = objects.ComputeNode(uuid=uuid,
                                           hypervisor_hostname=name,
                                           vcpus=0,
                                           cpu_allocation_ratio=16.0,
                                           memory_mb=0,
                                           ram_allocation_ratio=1.5,
                                           local_gb=0,
                                           disk_allocation_ratio=1.0)
        result = report._compute_node_to_inventory_dict(compute_node)
        self.assertEqual({}, result)


class TestInventory(SchedulerReportClientTestCase):
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_delete_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    def test_update_compute_node(self, mock_ui, mock_delete, mock_erp):
        cn = self.compute_node
        self.client.update_compute_node(cn)
        mock_erp.assert_called_once_with(cn.uuid, cn.hypervisor_hostname)
        expected_inv_data = {
            'VCPU': {
                'total': 8,
                'reserved': CONF.reserved_host_cpus,
                'min_unit': 1,
                'max_unit': 8,
                'step_size': 1,
                'allocation_ratio': 16.0,
            },
            'MEMORY_MB': {
                'total': 1024,
                'reserved': 512,
                'min_unit': 1,
                'max_unit': 1024,
                'step_size': 1,
                'allocation_ratio': 1.5,
            },
            'DISK_GB': {
                'total': 10,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 10,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        mock_ui.assert_called_once_with(
            cn.uuid,
            expected_inv_data,
        )
        self.assertFalse(mock_delete.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_delete_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    def test_update_compute_node_no_inv(self, mock_ui, mock_delete,
            mock_erp):
        """Ensure that if there are no inventory records, that we call
        _delete_inventory() instead of _update_inventory().
        """
        cn = self.compute_node
        cn.vcpus = 0
        cn.memory_mb = 0
        cn.local_gb = 0
        self.client.update_compute_node(cn)
        mock_erp.assert_called_once_with(cn.uuid, cn.hypervisor_hostname)
        mock_delete.assert_called_once_with(cn.uuid)
        self.assertFalse(mock_ui.called)

    @mock.patch('nova.scheduler.client.report._extract_inventory_in_use')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    def test_delete_inventory_already_no_inventory(self, mock_get, mock_put,
            mock_extract):
        cn = self.compute_node
        rp = dict(uuid=cn.uuid, generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[cn.uuid] = rp

        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 1,
            'inventories': {
            }
        }
        result = self.client._delete_inventory(cn.uuid)
        self.assertIsNone(result)
        self.assertFalse(mock_put.called)
        self.assertFalse(mock_extract.called)
        new_gen = self.client._resource_providers[cn.uuid]['generation']
        self.assertEqual(1, new_gen)

    @mock.patch.object(report.LOG, 'info')
    @mock.patch('nova.scheduler.client.report._extract_inventory_in_use')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    def test_delete_inventory(self, mock_get, mock_put, mock_extract,
                              mock_info):
        cn = self.compute_node
        rp = dict(uuid=cn.uuid, generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[cn.uuid] = rp

        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 1,
            'inventories': {
                'VCPU': {'total': 16},
                'MEMORY_MB': {'total': 1024},
                'DISK_GB': {'total': 10},
            }
        }
        mock_put.return_value.status_code = 200
        mock_put.return_value.json.return_value = {
            'resource_provider_generation': 44,
            'inventories': {
            }
        }
        mock_put.return_value.headers = {'openstack-request-id':
                                         uuids.request_id}
        result = self.client._delete_inventory(cn.uuid)
        self.assertIsNone(result)
        self.assertFalse(mock_extract.called)
        new_gen = self.client._resource_providers[cn.uuid]['generation']
        self.assertEqual(44, new_gen)
        self.assertTrue(mock_info.called)
        self.assertEqual(uuids.request_id,
                         mock_info.call_args[0][1]['placement_req_id'])

    @mock.patch.object(report.LOG, 'warning')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    def test_delete_inventory_inventory_in_use(self, mock_get, mock_put,
            mock_warn):
        cn = self.compute_node
        rp = dict(uuid=cn.uuid, generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[cn.uuid] = rp

        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 1,
            'inventories': {
                'VCPU': {'total': 16},
                'MEMORY_MB': {'total': 1024},
                'DISK_GB': {'total': 10},
            }
        }
        mock_put.return_value.status_code = 409
        mock_put.return_value.headers = {'openstack-request-id':
                                         uuids.request_id}
        rc_str = "VCPU, MEMORY_MB"
        in_use_exc = exception.InventoryInUse(
            resource_classes=rc_str,
            resource_provider=cn.uuid,
        )
        fault_text = """
409 Conflict

There was a conflict when trying to complete your request.

 update conflict: %s
 """ % six.text_type(in_use_exc)
        mock_put.return_value.text = fault_text
        mock_put.return_value.json.return_value = {
            'resource_provider_generation': 44,
            'inventories': {
            }
        }
        result = self.client._delete_inventory(cn.uuid)
        self.assertIsNone(result)
        self.assertTrue(mock_warn.called)
        self.assertEqual(uuids.request_id,
                         mock_warn.call_args[0][1]['placement_req_id'])

    @mock.patch.object(report.LOG, 'error')
    @mock.patch.object(report.LOG, 'warning')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    def test_delete_inventory_inventory_error(self, mock_get, mock_put,
            mock_warn, mock_error):
        cn = self.compute_node
        rp = dict(uuid=cn.uuid, generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[cn.uuid] = rp

        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 1,
            'inventories': {
                'VCPU': {'total': 16},
                'MEMORY_MB': {'total': 1024},
                'DISK_GB': {'total': 10},
            }
        }
        mock_put.return_value.status_code = 409
        mock_put.return_value.text = (
            'There was a failure'
        )
        mock_put.return_value.json.return_value = {
            'resource_provider_generation': 44,
            'inventories': {
            }
        }
        mock_put.return_value.headers = {'openstack-request-id':
                                         uuids.request_id}
        result = self.client._delete_inventory(cn.uuid)
        self.assertIsNone(result)
        self.assertFalse(mock_warn.called)
        self.assertTrue(mock_error.called)
        self.assertEqual(uuids.request_id,
                         mock_error.call_args[0][1]['placement_req_id'])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory(self, mock_put, mock_get):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = self.compute_node
        rp = dict(uuid=uuid, name='foo', generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 43,
            'inventories': {
                'VCPU': {'total': 16},
                'MEMORY_MB': {'total': 1024},
                'DISK_GB': {'total': 10},
            }
        }
        mock_put.return_value.status_code = 200
        mock_put.return_value.json.return_value = {
            'resource_provider_generation': 44,
            'inventories': {
                'VCPU': {'total': 16},
                'MEMORY_MB': {'total': 1024},
                'DISK_GB': {'total': 10},
            }
        }

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            compute_node.uuid, inv_data
        )
        self.assertTrue(result)

        exp_url = '/resource_providers/%s/inventories' % uuid
        mock_get.assert_called_once_with(exp_url)
        # Updated with the new inventory from the PUT call
        self.assertEqual(44, rp['generation'])
        expected = {
            # Called with the newly-found generation from the existing
            # inventory
            'resource_provider_generation': 43,
            'inventories': {
                'VCPU': {
                    'total': 8,
                    'reserved': CONF.reserved_host_cpus,
                    'min_unit': 1,
                    'max_unit': compute_node.vcpus,
                    'step_size': 1,
                    'allocation_ratio': compute_node.cpu_allocation_ratio,
                },
                'MEMORY_MB': {
                    'total': 1024,
                    'reserved': CONF.reserved_host_memory_mb,
                    'min_unit': 1,
                    'max_unit': compute_node.memory_mb,
                    'step_size': 1,
                    'allocation_ratio': compute_node.ram_allocation_ratio,
                },
                'DISK_GB': {
                    'total': 10,
                    'reserved': CONF.reserved_host_disk_mb * 1024,
                    'min_unit': 1,
                    'max_unit': compute_node.local_gb,
                    'step_size': 1,
                    'allocation_ratio': compute_node.disk_allocation_ratio,
                },
            }
        }
        mock_put.assert_called_once_with(exp_url, expected)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory_no_update(self, mock_put, mock_get):
        uuid = uuids.compute_node
        compute_node = self.compute_node
        rp = dict(uuid=uuid, name='foo', generation=42)
        self.client._resource_providers[uuid] = rp
        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 43,
            'inventories': {
                'VCPU': {
                    'total': 8,
                    'reserved': CONF.reserved_host_cpus,
                    'min_unit': 1,
                    'max_unit': compute_node.vcpus,
                    'step_size': 1,
                    'allocation_ratio': compute_node.cpu_allocation_ratio,
                },
                'MEMORY_MB': {
                    'total': 1024,
                    'reserved': CONF.reserved_host_memory_mb,
                    'min_unit': 1,
                    'max_unit': compute_node.memory_mb,
                    'step_size': 1,
                    'allocation_ratio': compute_node.ram_allocation_ratio,
                },
                'DISK_GB': {
                    'total': 10,
                    'reserved': CONF.reserved_host_disk_mb * 1024,
                    'min_unit': 1,
                    'max_unit': compute_node.local_gb,
                    'step_size': 1,
                    'allocation_ratio': compute_node.disk_allocation_ratio,
                },
            }
        }
        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            compute_node.uuid, inv_data
        )
        self.assertTrue(result)
        exp_url = '/resource_providers/%s/inventories' % uuid
        mock_get.assert_called_once_with(exp_url)
        # No update so put should not be called
        self.assertFalse(mock_put.called)
        # Make sure we updated the generation from the inventory records
        self.assertEqual(43, rp['generation'])

    @mock.patch.object(report.LOG, 'info')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_update_inventory_concurrent_update(self, mock_ensure,
                                                mock_put, mock_get, mock_info):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = self.compute_node
        rp = dict(uuid=uuid, name='foo', generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_get.return_value = {}
        mock_put.return_value.status_code = 409
        mock_put.return_value.text = 'Does not match inventory in use'
        mock_put.return_value.headers = {'x-openstack-request-id':
                                         uuids.request_id}

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            compute_node.uuid, inv_data
        )
        self.assertFalse(result)

        # Invalidated the cache
        self.assertNotIn(uuid, self.client._resource_providers)
        # Refreshed our resource provider
        mock_ensure.assert_called_once_with(uuid)
        # Logged the request id in the log message
        self.assertEqual(uuids.request_id,
                         mock_info.call_args[0][1]['placement_req_id'])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory_inventory_in_use(self, mock_put, mock_get):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = self.compute_node
        rp = dict(uuid=uuid, name='foo', generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_get.return_value = {}
        mock_put.return_value.status_code = 409
        mock_put.return_value.text = (
            "update conflict: Inventory for VCPU on "
            "resource provider 123 in use"
        )

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        self.assertRaises(
            exception.InventoryInUse,
            self.client._update_inventory_attempt,
            compute_node.uuid,
            inv_data,
        )

        # Did NOT invalidate the cache
        self.assertIn(uuid, self.client._resource_providers)

    @mock.patch.object(report.LOG, 'info')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory_unknown_response(self, mock_put, mock_get,
                                               mock_info):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = self.compute_node
        rp = dict(uuid=uuid, name='foo', generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_get.return_value = {}
        mock_put.return_value.status_code = 234
        mock_put.return_value.headers = {'openstack-request-id':
                                         uuids.request_id}

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            compute_node.uuid, inv_data
        )
        self.assertFalse(result)

        # No cache invalidation
        self.assertIn(uuid, self.client._resource_providers)
        # Logged the request id in the log messages
        self.assertEqual(uuids.request_id,
                         mock_info.call_args[0][1]['placement_req_id'])

    @mock.patch.object(report.LOG, 'warning')
    @mock.patch.object(report.LOG, 'debug')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory_failed(self, mock_put, mock_get,
                                     mock_debug, mock_warn):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = self.compute_node
        rp = dict(uuid=uuid, name='foo', generation=42)
        # Make sure the resource provider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_get.return_value = {}
        try:
            mock_put.return_value.__nonzero__.return_value = False
        except AttributeError:
            # Thanks py3
            mock_put.return_value.__bool__.return_value = False
        mock_put.return_value.headers = {'openstack-request-id':
                                         uuids.request_id}

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            compute_node.uuid, inv_data
        )
        self.assertFalse(result)

        # No cache invalidation
        self.assertIn(uuid, self.client._resource_providers)
        # Logged the request id in the log messages
        self.assertEqual(uuids.request_id,
                         mock_debug.call_args[0][1]['placement_req_id'])
        self.assertEqual(uuids.request_id,
                         mock_warn.call_args[0][1]['placement_req_id'])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory_attempt')
    @mock.patch('time.sleep')
    def test_update_inventory_fails_and_then_succeeds(self, mock_sleep,
                                                      mock_update,
                                                      mock_ensure):
        # Ensure _update_inventory() fails if we have a conflict when updating
        # but retries correctly.
        cn = mock.MagicMock()
        mock_update.side_effect = (False, True)

        self.client._resource_providers[cn.uuid] = True
        result = self.client._update_inventory(
            cn.uuid, mock.sentinel.inv_data
        )
        self.assertTrue(result)

        # Only slept once
        mock_sleep.assert_called_once_with(1)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory_attempt')
    @mock.patch('time.sleep')
    def test_update_inventory_never_succeeds(self, mock_sleep,
                                             mock_update,
                                             mock_ensure):
        # but retries correctly.
        cn = mock.MagicMock()
        mock_update.side_effect = (False, False, False)

        self.client._resource_providers[cn.uuid] = True
        result = self.client._update_inventory(
            cn.uuid, mock.sentinel.inv_data
        )
        self.assertFalse(result)

        # Slept three times
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1), mock.call(1)])

        # Three attempts to update
        mock_update.assert_has_calls([
            mock.call(cn.uuid, mock.sentinel.inv_data),
            mock.call(cn.uuid, mock.sentinel.inv_data),
            mock.call(cn.uuid, mock.sentinel.inv_data),
        ])

        # Slept three times
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1), mock.call(1)])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_delete_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_or_create_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_set_inventory_for_provider_no_custom(self, mock_erp, mock_gocr,
            mock_erc, mock_del, mock_upd):
        """Tests that inventory records of all standard resource classes are
        passed to the report client's _update_inventory() method.
        """
        inv_data = {
            'VCPU': {
                'total': 24,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 24,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            'MEMORY_MB': {
                'total': 1024,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1024,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            'DISK_GB': {
                'total': 100,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 100,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        self.client.set_inventory_for_provider(
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            inv_data,
        )
        mock_erp.assert_called_once_with(
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
        )
        # No custom resource classes to ensure...
        self.assertFalse(mock_erc.called)
        self.assertFalse(mock_gocr.called)
        mock_upd.assert_called_once_with(
            mock.sentinel.rp_uuid,
            inv_data,
        )
        self.assertFalse(mock_del.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_delete_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_or_create_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_set_inventory_for_provider_no_inv(self, mock_erp, mock_gocr,
            mock_erc, mock_del, mock_upd):
        """Tests that passing empty set of inventory records triggers a delete
        of inventory for the provider.
        """
        inv_data = {}
        self.client.set_inventory_for_provider(
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            inv_data,
        )
        mock_erp.assert_called_once_with(
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
        )
        self.assertFalse(mock_gocr.called)
        self.assertFalse(mock_erc.called)
        self.assertFalse(mock_upd.called)
        mock_del.assert_called_once_with(mock.sentinel.rp_uuid)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_delete_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_or_create_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_set_inventory_for_provider_with_custom(self, mock_erp,
            mock_gocr, mock_erc, mock_del, mock_upd):
        """Tests that inventory records that include a custom resource class
        are passed to the report client's _update_inventory() method and that
        the custom resource class is auto-created.
        """
        inv_data = {
            'VCPU': {
                'total': 24,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 24,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            'MEMORY_MB': {
                'total': 1024,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1024,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            'DISK_GB': {
                'total': 100,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 100,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            'CUSTOM_IRON_SILVER': {
                'total': 1,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
            }

        }
        self.client.set_inventory_for_provider(
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            inv_data,
        )
        mock_erp.assert_called_once_with(
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
        )
        mock_erc.assert_called_once_with('CUSTOM_IRON_SILVER')
        mock_upd.assert_called_once_with(
            mock.sentinel.rp_uuid,
            inv_data,
        )
        self.assertFalse(mock_gocr.called)
        self.assertFalse(mock_del.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_or_create_resource_class')
    def test_ensure_resource_class_microversion_failover(self, mock_gocr,
                                                         mock_put):
        mock_put.return_value.status_code = 406
        self.client._ensure_resource_class('CUSTOM_IRON_SILVER')
        mock_gocr.assert_called_once_with('CUSTOM_IRON_SILVER')


class TestAllocations(SchedulerReportClientTestCase):

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_instance_to_allocations_dict(self, mock_vbi):
        mock_vbi.return_value = False
        inst = objects.Instance(
            uuid=uuids.inst,
            flavor=objects.Flavor(root_gb=10,
                                  swap=1023,
                                  ephemeral_gb=100,
                                  memory_mb=1024,
                                  vcpus=2))
        result = report._instance_to_allocations_dict(inst)
        expected = {
            'MEMORY_MB': 1024,
            'VCPU': 2,
            'DISK_GB': 111,
        }
        self.assertEqual(expected, result)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_instance_to_allocations_dict_boot_from_volume(self, mock_vbi):
        mock_vbi.return_value = True
        inst = objects.Instance(
            uuid=uuids.inst,
            flavor=objects.Flavor(root_gb=10,
                                  swap=1,
                                  ephemeral_gb=100,
                                  memory_mb=1024,
                                  vcpus=2))
        result = report._instance_to_allocations_dict(inst)
        expected = {
            'MEMORY_MB': 1024,
            'VCPU': 2,
            'DISK_GB': 101,
        }
        self.assertEqual(expected, result)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_instance_to_allocations_dict_zero_disk(self, mock_vbi):
        mock_vbi.return_value = True
        inst = objects.Instance(
            uuid=uuids.inst,
            flavor=objects.Flavor(root_gb=10,
                                  swap=0,
                                  ephemeral_gb=0,
                                  memory_mb=1024,
                                  vcpus=2))
        result = report._instance_to_allocations_dict(inst)
        expected = {
            'MEMORY_MB': 1024,
            'VCPU': 2,
        }
        self.assertEqual(expected, result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.'
                '_instance_to_allocations_dict')
    def test_update_instance_allocation_new(self, mock_a, mock_get,
                                            mock_put):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        mock_get.return_value.json.return_value = {'allocations': {}}
        expected = {
            'allocations': [
                {'resource_provider': {'uuid': cn.uuid},
                 'resources': mock_a.return_value}]
        }
        self.client.update_instance_allocation(cn, inst, 1)
        mock_put.assert_called_once_with(
            '/allocations/%s' % inst.uuid,
            expected)
        self.assertTrue(mock_get.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.'
                '_instance_to_allocations_dict')
    def test_update_instance_allocation_existing(self, mock_a, mock_get,
                                                 mock_put):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        mock_get.return_value.json.return_value = {'allocations': {
            cn.uuid: {
                'generation': 2,
                'resources': {
                    'DISK_GB': 123,
                    'MEMORY_MB': 456,
                }
            }}
        }
        mock_a.return_value = {
            'DISK_GB': 123,
            'MEMORY_MB': 456,
        }
        self.client.update_instance_allocation(cn, inst, 1)
        self.assertFalse(mock_put.called)
        mock_get.assert_called_once_with(
            '/allocations/%s' % inst.uuid)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.'
                '_instance_to_allocations_dict')
    @mock.patch.object(report.LOG, 'warning')
    def test_update_instance_allocation_new_failed(self, mock_warn, mock_a,
                                                   mock_put, mock_get):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        try:
            mock_put.return_value.__nonzero__.return_value = False
        except AttributeError:
            # NOTE(danms): LOL @ py3
            mock_put.return_value.__bool__.return_value = False
        self.client.update_instance_allocation(cn, inst, 1)
        self.assertTrue(mock_warn.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete')
    def test_update_instance_allocation_delete(self, mock_delete):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        self.client.update_instance_allocation(cn, inst, -1)
        mock_delete.assert_called_once_with(
            '/allocations/%s' % inst.uuid)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete')
    @mock.patch.object(report.LOG, 'warning')
    def test_update_instance_allocation_delete_failed(self, mock_warn,
                                                      mock_delete):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        try:
            mock_delete.return_value.__nonzero__.return_value = False
        except AttributeError:
            # NOTE(danms): LOL @ py3
            mock_delete.return_value.__bool__.return_value = False
        self.client.update_instance_allocation(cn, inst, -1)
        self.assertTrue(mock_warn.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete')
    @mock.patch('nova.scheduler.client.report.LOG')
    def test_delete_allocation_for_instance_ignore_404(self, mock_log,
                                                       mock_delete):
        """Tests that we don't log a warning on a 404 response when trying to
        delete an allocation record.
        """
        mock_response = mock.MagicMock(status_code=404)
        try:
            mock_response.__nonzero__.return_value = False
        except AttributeError:
            # py3 uses __bool__
            mock_response.__bool__.return_value = False
        mock_delete.return_value = mock_response
        self.client.delete_allocation_for_instance(uuids.rp_uuid)
        # make sure we didn't screw up the logic or the mock
        mock_log.info.assert_not_called()
        # make sure warning wasn't called for the 404
        mock_log.warning.assert_not_called()

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete_allocation_for_instance")
    @mock.patch("nova.objects.InstanceList.get_by_host_and_node")
    def test_delete_resource_provider_cascade(self, mock_by_host,
            mock_del_alloc, mock_delete):
        self.client._resource_providers[uuids.cn] = mock.Mock()
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake_host",
                hypervisor_hostname="fake_hostname", )
        inst1 = objects.Instance(uuid=uuids.inst1)
        inst2 = objects.Instance(uuid=uuids.inst2)
        mock_by_host.return_value = objects.InstanceList(
                objects=[inst1, inst2])
        resp_mock = mock.Mock(status_code=204)
        mock_delete.return_value = resp_mock
        self.client.delete_resource_provider(self.context, cn, cascade=True)
        self.assertEqual(2, mock_del_alloc.call_count)
        exp_url = "/resource_providers/%s" % uuids.cn
        mock_delete.assert_called_once_with(exp_url)
        self.assertNotIn(uuids.cn, self.client._resource_providers)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete_allocation_for_instance")
    @mock.patch("nova.objects.InstanceList.get_by_host_and_node")
    def test_delete_resource_provider_no_cascade(self, mock_by_host,
            mock_del_alloc, mock_delete):
        self.client._provider_aggregate_map[uuids.cn] = mock.Mock()
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake_host",
                hypervisor_hostname="fake_hostname", )
        inst1 = objects.Instance(uuid=uuids.inst1)
        inst2 = objects.Instance(uuid=uuids.inst2)
        mock_by_host.return_value = objects.InstanceList(
                objects=[inst1, inst2])
        resp_mock = mock.Mock(status_code=204)
        mock_delete.return_value = resp_mock
        self.client.delete_resource_provider(self.context, cn)
        mock_del_alloc.assert_not_called()
        exp_url = "/resource_providers/%s" % uuids.cn
        mock_delete.assert_called_once_with(exp_url)
        self.assertNotIn(uuids.cn, self.client._provider_aggregate_map)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete")
    @mock.patch('nova.scheduler.client.report.LOG')
    def test_delete_resource_provider_log_calls(self, mock_log, mock_delete):
        # First, check a successful call
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake_host",
                hypervisor_hostname="fake_hostname", )
        resp_mock = mock.MagicMock(status_code=204)
        try:
            resp_mock.__nonzero__.return_value = True
        except AttributeError:
            # py3 uses __bool__
            resp_mock.__bool__.return_value = True
        mock_delete.return_value = resp_mock
        self.client.delete_resource_provider(self.context, cn)
        # With a 204, only the info should be called
        self.assertEqual(1, mock_log.info.call_count)
        self.assertEqual(0, mock_log.warning.call_count)

        # Now check a 404 response
        mock_log.reset_mock()
        resp_mock.status_code = 404
        try:
            resp_mock.__nonzero__.return_value = False
        except AttributeError:
            # py3 uses __bool__
            resp_mock.__bool__.return_value = False
        self.client.delete_resource_provider(self.context, cn)
        # With a 404, neither log message should be called
        self.assertEqual(0, mock_log.info.call_count)
        self.assertEqual(0, mock_log.warning.call_count)

        # Finally, check a 409 response
        mock_log.reset_mock()
        resp_mock.status_code = 409
        self.client.delete_resource_provider(self.context, cn)
        # With a 409, only the warning should be called
        self.assertEqual(0, mock_log.info.call_count)
        self.assertEqual(1, mock_log.warning.call_count)


class TestResourceClass(SchedulerReportClientTestCase):

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def test_get_or_create_existing(self, mock_get, mock_crc):
        resp_mock = mock.Mock(status_code=200)
        mock_get.return_value = resp_mock
        rc_name = 'CUSTOM_FOO'
        result = self.client._get_or_create_resource_class(rc_name)
        mock_get.assert_called_once_with(
            '/resource_classes/' + rc_name,
            version="1.2",
        )
        self.assertFalse(mock_crc.called)
        self.assertEqual(rc_name, result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def test_get_or_create_not_existing(self, mock_get, mock_crc):
        resp_mock = mock.Mock(status_code=404)
        mock_get.return_value = resp_mock
        rc_name = 'CUSTOM_FOO'
        result = self.client._get_or_create_resource_class(rc_name)
        mock_get.assert_called_once_with(
            '/resource_classes/' + rc_name,
            version="1.2",
        )
        mock_crc.assert_called_once_with(rc_name)
        self.assertEqual(rc_name, result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_class')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def test_get_or_create_bad_get(self, mock_get, mock_crc):
        resp_mock = mock.Mock(status_code=500, text='server error')
        mock_get.return_value = resp_mock
        rc_name = 'CUSTOM_FOO'
        result = self.client._get_or_create_resource_class(rc_name)
        mock_get.assert_called_once_with(
            '/resource_classes/' + rc_name,
            version="1.2",
        )
        self.assertFalse(mock_crc.called)
        self.assertIsNone(result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.post')
    def test_create_resource_class(self, mock_post):
        resp_mock = mock.Mock(status_code=201)
        mock_post.return_value = resp_mock
        rc_name = 'CUSTOM_FOO'
        result = self.client._create_resource_class(rc_name)
        mock_post.assert_called_once_with(
            '/resource_classes',
            {'name': rc_name},
            version="1.2",
        )
        self.assertIsNone(result)

    @mock.patch('nova.scheduler.client.report.LOG.info')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.post')
    def test_create_resource_class_concurrent_write(self, mock_post, mock_log):
        resp_mock = mock.Mock(status_code=409)
        mock_post.return_value = resp_mock
        rc_name = 'CUSTOM_FOO'
        result = self.client._create_resource_class(rc_name)
        mock_post.assert_called_once_with(
            '/resource_classes',
            {'name': rc_name},
            version="1.2",
        )
        self.assertIsNone(result)
        self.assertIn('Another thread already', mock_log.call_args[0][0])

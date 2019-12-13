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
import copy
import time

import fixtures
from keystoneauth1 import exceptions as ks_exc
import mock
import os_resource_classes as orc
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
import six
from six.moves.urllib import parse

import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova.scheduler.client import report
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_requests


CONF = nova.conf.CONF


class SafeConnectedTestCase(test.NoDBTestCase):
    """Test the safe_connect decorator for the scheduler client."""

    def setUp(self):
        super(SafeConnectedTestCase, self).setUp()
        self.context = context.get_admin_context()

        with mock.patch('keystoneauth1.loading.load_auth_from_conf_options'):
            self.client = report.SchedulerReportClient()

    @mock.patch('keystoneauth1.session.Session.request')
    def test_missing_endpoint(self, req):
        """Test EndpointNotFound behavior.

        A missing endpoint entry should not explode.
        """
        req.side_effect = ks_exc.EndpointNotFound()
        self.client._get_resource_provider(self.context, "fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider(self.context, "fake")
        self.assertTrue(req.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_client')
    @mock.patch('keystoneauth1.session.Session.request')
    def test_missing_endpoint_create_client(self, req, create_client):
        """Test EndpointNotFound retry behavior.

        A missing endpoint should cause _create_client to be called.
        """
        req.side_effect = ks_exc.EndpointNotFound()
        self.client._get_resource_provider(self.context, "fake")

        # This is the second time _create_client is called, but the first since
        # the mock was created.
        self.assertTrue(create_client.called)

    @mock.patch('keystoneauth1.session.Session.request')
    def test_missing_auth(self, req):
        """Test Missing Auth handled correctly.

        A missing auth configuration should not explode.

        """
        req.side_effect = ks_exc.MissingAuthPlugin()
        self.client._get_resource_provider(self.context, "fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider(self.context, "fake")
        self.assertTrue(req.called)

    @mock.patch('keystoneauth1.session.Session.request')
    def test_unauthorized(self, req):
        """Test Unauthorized handled correctly.

        An unauthorized configuration should not explode.

        """
        req.side_effect = ks_exc.Unauthorized()
        self.client._get_resource_provider(self.context, "fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider(self.context, "fake")
        self.assertTrue(req.called)

    @mock.patch('keystoneauth1.session.Session.request')
    def test_connect_fail(self, req):
        """Test Connect Failure handled correctly.

        If we get a connect failure, this is transient, and we expect
        that this will end up working correctly later.

        """
        req.side_effect = ks_exc.ConnectFailure()
        self.client._get_resource_provider(self.context, "fake")

        # reset the call count to demonstrate that future calls do
        # work
        req.reset_mock()
        self.client._get_resource_provider(self.context, "fake")
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
        self.client._get_resource_provider(self.context, "fake")

        # reset the call count to demonstrate that future calls still
        # work
        req.reset_mock()
        self.client._get_resource_provider(self.context, "fake")
        self.assertTrue(req.called)


class TestConstructor(test.NoDBTestCase):
    def setUp(self):
        super(TestConstructor, self).setUp()
        ksafx = self.useFixture(nova_fixtures.KSAFixture())
        self.load_auth_mock = ksafx.mock_load_auth
        self.load_sess_mock = ksafx.mock_load_sess

    def test_constructor(self):
        client = report.SchedulerReportClient()

        self.load_auth_mock.assert_called_once_with(CONF, 'placement')
        self.load_sess_mock.assert_called_once_with(
            CONF, 'placement', auth=self.load_auth_mock.return_value)
        self.assertEqual(['internal', 'public'], client._client.interface)
        self.assertEqual({'accept': 'application/json'},
                         client._client.additional_headers)

    def test_constructor_admin_interface(self):
        self.flags(valid_interfaces='admin', group='placement')
        client = report.SchedulerReportClient()

        self.load_auth_mock.assert_called_once_with(CONF, 'placement')
        self.load_sess_mock.assert_called_once_with(
            CONF, 'placement', auth=self.load_auth_mock.return_value)
        self.assertEqual(['admin'], client._client.interface)
        self.assertEqual({'accept': 'application/json'},
                         client._client.additional_headers)


class SchedulerReportClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerReportClientTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.useFixture(nova_fixtures.KSAFixture())
        self.ks_adap_mock = mock.Mock()
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

        self.client = report.SchedulerReportClient(self.ks_adap_mock)

    def _init_provider_tree(self, generation_override=None,
                            resources_override=None):
        cn = self.compute_node
        resources = resources_override
        if resources_override is None:
            resources = {
                'VCPU': {
                    'total': cn.vcpus,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': cn.vcpus,
                    'step_size': 1,
                    'allocation_ratio': cn.cpu_allocation_ratio,
                },
                'MEMORY_MB': {
                    'total': cn.memory_mb,
                    'reserved': 512,
                    'min_unit': 1,
                    'max_unit': cn.memory_mb,
                    'step_size': 1,
                    'allocation_ratio': cn.ram_allocation_ratio,
                },
                'DISK_GB': {
                    'total': cn.local_gb,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': cn.local_gb,
                    'step_size': 1,
                    'allocation_ratio': cn.disk_allocation_ratio,
                },
            }
        generation = generation_override or 1
        rp_uuid = self.client._provider_tree.new_root(
            cn.hypervisor_hostname,
            cn.uuid,
            generation=generation,
        )
        self.client._provider_tree.update_inventory(rp_uuid, resources)

    def _validate_provider(self, name_or_uuid, **kwargs):
        """Validates existence and values of a provider in this client's
        _provider_tree.

        :param name_or_uuid: The name or UUID of the provider to validate.
        :param kwargs: Optional keyword arguments of ProviderData attributes
                       whose values are to be validated.
        """
        found = self.client._provider_tree.data(name_or_uuid)
        # If kwargs provided, their names indicate ProviderData attributes
        for attr, expected in kwargs.items():
            try:
                self.assertEqual(getattr(found, attr), expected)
            except AttributeError:
                self.fail("Provider with name or UUID %s doesn't have "
                          "attribute %s (expected value: %s)" %
                          (name_or_uuid, attr, expected))


class TestPutAllocations(SchedulerReportClientTestCase):
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations(self, mock_put):
        mock_put.return_value.status_code = 204
        mock_put.return_value.text = "cool"
        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        payload = {
            "allocations": {
                rp_uuid: {"resources": data}
            },
            "project_id": mock.sentinel.project_id,
            "user_id": mock.sentinel.user_id,
            "consumer_generation": mock.sentinel.consumer_generation
        }
        resp = self.client.put_allocations(
            self.context, consumer_uuid, payload)
        self.assertTrue(resp)
        mock_put.assert_called_once_with(
            expected_url, payload, version='1.28',
            global_request_id=self.context.global_id)

    @mock.patch.object(report.LOG, 'warning')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations_fail(self, mock_put, mock_warn):
        mock_put.return_value.status_code = 400
        mock_put.return_value.text = "not cool"
        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        payload = {
            "allocations": {
                rp_uuid: {"resources": data}
            },
            "project_id": mock.sentinel.project_id,
            "user_id": mock.sentinel.user_id,
            "consumer_generation": mock.sentinel.consumer_generation
        }
        resp = self.client.put_allocations(
            self.context, consumer_uuid, payload)

        self.assertFalse(resp)
        mock_put.assert_called_once_with(
            expected_url, payload, version='1.28',
            global_request_id=self.context.global_id)
        log_msg = mock_warn.call_args[0][0]
        self.assertIn("Failed to save allocation for", log_msg)

    def test_put_allocations_fail_connection_error(self):
        self.ks_adap_mock.put.side_effect = ks_exc.EndpointNotFound()
        self.assertRaises(
            exception.PlacementAPIConnectFailure, self.client.put_allocations,
            self.context, mock.sentinel.consumer, mock.sentinel.payload)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations_fail_due_to_consumer_generation_conflict(
            self, mock_put):
        mock_put.return_value = fake_requests.FakeResponse(
            status_code=409,
            content=jsonutils.dumps(
                {'errors': [{'code': 'placement.concurrent_update',
                             'detail': 'consumer generation conflict'}]}))

        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        payload = {
            "allocations": {
                rp_uuid: {"resources": data}
            },
            "project_id": mock.sentinel.project_id,
            "user_id": mock.sentinel.user_id,
            "consumer_generation": mock.sentinel.consumer_generation
        }
        self.assertRaises(exception.AllocationUpdateFailed,
                          self.client.put_allocations,
                          self.context, consumer_uuid, payload)

        mock_put.assert_called_once_with(
            expected_url, mock.ANY, version='1.28',
            global_request_id=self.context.global_id)

    @mock.patch('time.sleep', new=mock.Mock())
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations_retries_conflict(self, mock_put):
        failed = fake_requests.FakeResponse(
            status_code=409,
            content=jsonutils.dumps(
                {'errors': [{'code': 'placement.concurrent_update',
                             'detail': ''}]}))

        succeeded = mock.MagicMock()
        succeeded.status_code = 204

        mock_put.side_effect = (failed, succeeded)

        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        payload = {
            "allocations": {
                rp_uuid: {"resources": data}
            },
            "project_id": mock.sentinel.project_id,
            "user_id": mock.sentinel.user_id,
            "consumer_generation": mock.sentinel.consumer_generation
        }
        resp = self.client.put_allocations(
            self.context, consumer_uuid, payload)
        self.assertTrue(resp)
        mock_put.assert_has_calls([
            mock.call(expected_url, payload, version='1.28',
                      global_request_id=self.context.global_id)] * 2)

    @mock.patch('time.sleep', new=mock.Mock())
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations_retry_gives_up(self, mock_put):

        failed = fake_requests.FakeResponse(
            status_code=409,
            content=jsonutils.dumps(
                {'errors': [{'code': 'placement.concurrent_update',
                             'detail': ''}]}))

        mock_put.return_value = failed

        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        payload = {
            "allocations": {
                rp_uuid: {"resources": data}
            },
            "project_id": mock.sentinel.project_id,
            "user_id": mock.sentinel.user_id,
            "consumer_generation": mock.sentinel.consumer_generation
        }
        resp = self.client.put_allocations(
            self.context, consumer_uuid, payload)
        self.assertFalse(resp)
        mock_put.assert_has_calls([
            mock.call(expected_url, payload, version='1.28',
            global_request_id=self.context.global_id)] * 3)

    def test_claim_resources_success(self):
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {},  # build instance, not move
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': {
                uuids.cn1: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
            },
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.12')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {'allocations': {
            rp_uuid: alloc
                for rp_uuid, alloc in alloc_req['allocations'].items()}}
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=expected_payload,
            global_request_id=self.context.global_id)

        self.assertTrue(res)

    def test_claim_resources_older_alloc_req(self):
        """Test the case when a stale allocation request is sent to the report
        client to claim
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {},  # build instance, not move
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': {
                uuids.cn1: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
            },
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.12')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations': {
                rp_uuid: res
                for rp_uuid, res in alloc_req['allocations'].items()},
            # no consumer generation in the payload as the caller requested
            # older microversion to be used
            'project_id': project_id,
            'user_id': user_id}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=expected_payload,
            global_request_id=self.context.global_id)
        self.assertTrue(res)

    def test_claim_resources_success_resize_to_same_host_no_shared(self):
        """Tests resize to the same host operation. In this case allocation
        exists against the same host RP but with the migration_uuid.
        """
        get_current_allocations_resp_mock = mock.Mock(status_code=200)
        # source host allocation held by the migration_uuid so it is not
        # not returned to the claim code as that asks for the instance_uuid
        # consumer
        get_current_allocations_resp_mock.json.return_value = {
            'allocations': {},
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        self.ks_adap_mock.get.return_value = get_current_allocations_resp_mock
        put_allocations_resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = put_allocations_resp_mock
        consumer_uuid = uuids.consumer_uuid
        # This is the resize-up allocation where VCPU, MEMORY_MB and DISK_GB
        # are all being increased but on the same host. We also throw a custom
        # resource class in the new allocation to make sure it's not lost
        alloc_req = {
            'allocations': {
                uuids.same_host: {
                    'resources': {
                        'VCPU': 2,
                        'MEMORY_MB': 2048,
                        'DISK_GB': 40,
                        'CUSTOM_FOO': 1
                    }
                },
            },
            # this allocation request comes from the scheduler therefore it
            # does not have consumer_generation in it.
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations': {
                uuids.same_host: {
                    'resources': {
                        'VCPU': 2,
                        'MEMORY_MB': 2048,
                        'DISK_GB': 40,
                        'CUSTOM_FOO': 1
                    }
                },
            },
            # report client assumes a new consumer in this case
            'consumer_generation': None,
            'project_id': project_id,
            'user_id': user_id}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_resize_to_same_host_with_shared(self):
        """Tests resize to the same host operation. In this case allocation
        exists against the same host RP and the shared RP but with the
        migration_uuid.
        """
        get_current_allocations_resp_mock = mock.Mock(status_code=200)
        # source host allocation held by the migration_uuid so it is not
        # not returned to the claim code as that asks for the instance_uuid
        # consumer
        get_current_allocations_resp_mock.json.return_value = {
            'allocations': {},
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        self.ks_adap_mock.get.return_value = get_current_allocations_resp_mock
        put_allocations_resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = put_allocations_resp_mock
        consumer_uuid = uuids.consumer_uuid
        # This is the resize-up allocation where VCPU, MEMORY_MB and DISK_GB
        # are all being increased but on the same host. We also throw a custom
        # resource class in the new allocation to make sure it's not lost
        alloc_req = {
            'allocations': {
                uuids.same_host: {
                    'resources': {
                        'VCPU': 2,
                        'MEMORY_MB': 2048,
                        'CUSTOM_FOO': 1
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 40,
                    }
                },
            },
            # this allocation request comes from the scheduler therefore it
            # does not have consumer_generation in it.
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations': {
                uuids.same_host: {
                    'resources': {
                        'VCPU': 2,
                        'MEMORY_MB': 2048,
                        'CUSTOM_FOO': 1
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 40,
                    }
                },
            },
            # report client assumes a new consumer in this case
            'consumer_generation': None,
            'project_id': project_id,
            'user_id': user_id}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_evacuate_no_shared(self):
        """Tests non-forced evacuate. In this case both the source and the
        dest allocation are held by the instance_uuid in placement. So the
        claim code needs to merge allocations. The second claim comes from the
        scheduler and therefore it does not have consumer_generation in it.
        """
        # the source allocation is also held by the instance_uuid so report
        # client will see it.
        current_allocs = {
            'allocations': {
                uuids.source_host: {
                    'generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20
                    },
                },
            },
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }
        self.ks_adap_mock.get.return_value = fake_requests.FakeResponse(
            status_code=200,
            content=jsonutils.dumps(current_allocs))
        put_allocations_resp_mock = fake_requests.FakeResponse(status_code=204)
        self.ks_adap_mock.put.return_value = put_allocations_resp_mock
        consumer_uuid = uuids.consumer_uuid
        # this is an evacuate so we have the same resources request towards the
        # dest host
        alloc_req = {
            'allocations': {
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20,
                    }
                },
            },
            # this allocation request comes from the scheduler therefore it
            # does not have consumer_generation in it.
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        # we expect that both the source and dest allocations are here
        expected_payload = {
            'allocations': {
                uuids.source_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20
                    },
                },
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20,
                    }
                },
            },
            # report client uses the consumer_generation that it got from
            # placement when asked for the existing allocations
            'consumer_generation': 1,
            'project_id': project_id,
            'user_id': user_id}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_evacuate_with_shared(self):
        """Similar test that test_claim_resources_success_evacuate_no_shared
        but adds shared disk into the mix.
        """
        # the source allocation is also held by the instance_uuid so report
        # client will see it.
        current_allocs = {
            'allocations': {
                uuids.source_host: {
                    'generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.shared_storage: {
                    'generation': 42,
                    'resources': {
                        'DISK_GB': 20,
                    },
                },
            },
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }
        self.ks_adap_mock.get.return_value = fake_requests.FakeResponse(
            status_code=200,
            content = jsonutils.dumps(current_allocs))
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(
            status_code=204)
        consumer_uuid = uuids.consumer_uuid
        # this is an evacuate so we have the same resources request towards the
        # dest host
        alloc_req = {
            'allocations': {
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.shared_storage: {
                    'generation': 42,
                    'resources': {
                        'DISK_GB': 20,
                    },
                },
            },
            # this allocation request comes from the scheduler therefore it
            # does not have consumer_generation in it.
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        # we expect that both the source and dest allocations are here plus the
        # shared storage allocation
        expected_payload = {
            'allocations': {
                uuids.source_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 20,
                    },
                },
            },
            # report client uses the consumer_generation that got from
            # placement when asked for the existing allocations
            'consumer_generation': 1,
            'project_id': project_id,
            'user_id': user_id}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_force_evacuate_no_shared(self):
        """Tests forced evacuate. In this case both the source and the
        dest allocation are held by the instance_uuid in placement. So the
        claim code needs to merge allocations. The second claim comes from the
        conductor and therefore it does have consumer_generation in it.
        """
        # the source allocation is also held by the instance_uuid so report
        # client will see it.
        current_allocs = {
            'allocations': {
                uuids.source_host: {
                    'generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20
                    },
                },
            },
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        self.ks_adap_mock.get.return_value = fake_requests.FakeResponse(
            status_code=200,
            content=jsonutils.dumps(current_allocs))
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(
            status_code=204)
        consumer_uuid = uuids.consumer_uuid
        # this is an evacuate so we have the same resources request towards the
        # dest host
        alloc_req = {
            'allocations': {
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20,
                    }
                },
            },
            # this allocation request comes from the conductor that read the
            # allocation from placement therefore it has consumer_generation in
            # it.
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        # we expect that both the source and dest allocations are here
        expected_payload = {
            'allocations': {
                uuids.source_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20
                    },
                },
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20,
                    }
                },
            },
            # report client uses the consumer_generation that it got in the
            # allocation request
            'consumer_generation': 1,
            'project_id': project_id,
            'user_id': user_id}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_force_evacuate_with_shared(self):
        """Similar test that
        test_claim_resources_success_force_evacuate_no_shared but adds shared
        disk into the mix.
        """
        # the source allocation is also held by the instance_uuid so report
        # client will see it.
        current_allocs = {
            'allocations': {
                uuids.source_host: {
                    'generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.shared_storage: {
                    'generation': 42,
                    'resources': {
                        'DISK_GB': 20,
                    },
                },
            },
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        self.ks_adap_mock.get.return_value = fake_requests.FakeResponse(
            status_code=200,
            content=jsonutils.dumps(current_allocs))
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(
            status_code=204)
        consumer_uuid = uuids.consumer_uuid
        # this is an evacuate so we have the same resources request towards the
        # dest host
        alloc_req = {
            'allocations': {
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.shared_storage: {
                    'generation': 42,
                    'resources': {
                        'DISK_GB': 20,
                    },
                },
            },
            # this allocation request comes from the conductor that read the
            # allocation from placement therefore it has consumer_generation in
            # it.
            "consumer_generation": 1,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        # we expect that both the source and dest allocations are here plus the
        # shared storage allocation
        expected_payload = {
            'allocations': {
                uuids.source_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.dest_host: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 20,
                    },
                },
            },
            # report client uses the consumer_generation that it got in the
            # allocation request
            'consumer_generation': 1,
            'project_id': project_id,
            'user_id': user_id}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    @mock.patch('time.sleep', new=mock.Mock())
    def test_claim_resources_fail_due_to_rp_generation_retry_success(self):
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {},  # build instance, not move
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mocks = [
            fake_requests.FakeResponse(
                409,
                jsonutils.dumps(
                    {'errors': [
                        {'code': 'placement.concurrent_update',
                         'detail': ''}]})),
            fake_requests.FakeResponse(204)
        ]
        self.ks_adap_mock.put.side_effect = resp_mocks
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': {
                uuids.cn1: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
            },
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations':
                {rp_uuid: res
                    for rp_uuid, res in alloc_req['allocations'].items()}
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        expected_payload['consumer_generation'] = None
        # We should have exactly two calls to the placement API that look
        # identical since we're retrying the same HTTP request
        expected_calls = [
            mock.call(expected_url, microversion='1.28', json=expected_payload,
                      global_request_id=self.context.global_id)] * 2
        self.assertEqual(len(expected_calls),
                         self.ks_adap_mock.put.call_count)
        self.ks_adap_mock.put.assert_has_calls(expected_calls)

        self.assertTrue(res)

    @mock.patch.object(report.LOG, 'warning')
    def test_claim_resources_failure(self, mock_log):
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {},  # build instance, not move
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'something else',
                     'detail': 'not cool'}]}))

        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': {
                uuids.cn1: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
            },
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations':
                {rp_uuid: res
                    for rp_uuid, res in alloc_req['allocations'].items()}
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        expected_payload['consumer_generation'] = None
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=expected_payload,
            global_request_id=self.context.global_id)

        self.assertFalse(res)
        self.assertTrue(mock_log.called)

    def test_claim_resources_consumer_generation_failure(self):
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {},  # build instance, not move
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))

        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': {
                uuids.cn1: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
            },
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        self.assertRaises(exception.AllocationUpdateFailed,
                          self.client.claim_resources, self.context,
                          consumer_uuid, alloc_req, project_id, user_id,
                          allocation_request_version='1.28')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations': {
                rp_uuid: res
                for rp_uuid, res in alloc_req['allocations'].items()},
            'project_id': project_id,
            'user_id': user_id,
            'consumer_generation': None}
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=expected_payload,
            global_request_id=self.context.global_id)

    def test_remove_provider_from_inst_alloc_no_shared(self):
        """Tests that the method which manipulates an existing doubled-up
        allocation for a move operation to remove the source host results in
        sending placement the proper payload to PUT
        /allocations/{consumer_uuid} call.
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.side_effect = [
            {
            'allocations': {
                uuids.source: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.destination: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
            'consumer_generation': 1,
            'project_id': uuids.project_id,
            'user_id': uuids.user_id,
            },
            # the second get is for resource providers in the compute tree,
            # return just the compute
            {
                "resource_providers": [
                    {
                        "uuid": uuids.source,
                    },
                ]
            },
        ]
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.remove_provider_tree_from_instance_allocation(
            self.context, consumer_uuid, uuids.source)

        expected_url = "/allocations/%s" % consumer_uuid
        # New allocations should only include the destination...
        expected_payload = {
            'allocations': {
                uuids.destination: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
            'consumer_generation': 1,
            'project_id': project_id,
            'user_id': user_id
        }
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)

        self.assertTrue(res)

    def test_remove_provider_from_inst_alloc_with_shared(self):
        """Tests that the method which manipulates an existing doubled-up
        allocation with DISK_GB being consumed from a shared storage provider
        for a move operation to remove the source host results in sending
        placement the proper payload to PUT /allocations/{consumer_uuid}
        call.
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.side_effect = [
            {
            'allocations': {
                uuids.source: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.shared_storage: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'DISK_GB': 100,
                    },
                },
                uuids.destination: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
            'consumer_generation': 1,
            'project_id': uuids.project_id,
            'user_id': uuids.user_id,
            },
            # the second get is for resource providers in the compute tree,
            # return just the compute
            {
                "resource_providers": [
                    {
                        "uuid": uuids.source,
                    },
                ]
            },
        ]
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.remove_provider_tree_from_instance_allocation(
            self.context, consumer_uuid, uuids.source)

        expected_url = "/allocations/%s" % consumer_uuid
        # New allocations should only include the destination...
        expected_payload = {
            'allocations': {
                uuids.shared_storage: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'DISK_GB': 100,
                    },
                },
                uuids.destination: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
            'consumer_generation': 1,
            'project_id': project_id,
            'user_id': user_id
        }
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)

        self.assertTrue(res)

    def test_remove_provider_from_inst_alloc_no_source(self):
        """Tests that if remove_provider_tree_from_instance_allocation() fails
        to find any allocations for the source host, it just returns True and
        does not attempt to rewrite the allocation for the consumer.
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.side_effect = [
            # Act like the allocations already did not include the source host
            # for some reason
            {
            'allocations': {
                uuids.shared_storage: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'DISK_GB': 100,
                    },
                },
                uuids.destination: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
            'consumer_generation': 1,
            'project_id': uuids.project_id,
            'user_id': uuids.user_id,
            },
            # the second get is for resource providers in the compute tree,
            # return just the compute
            {
                "resource_providers": [
                    {
                        "uuid": uuids.source,
                    },
                ]
            },
        ]
        self.ks_adap_mock.get.return_value = get_resp_mock
        consumer_uuid = uuids.consumer_uuid
        res = self.client.remove_provider_tree_from_instance_allocation(
            self.context, consumer_uuid, uuids.source)

        self.ks_adap_mock.get.assert_called()
        self.ks_adap_mock.put.assert_not_called()

        self.assertTrue(res)

    def test_remove_provider_from_inst_alloc_fail_get_allocs(self):
        self.ks_adap_mock.get.return_value = fake_requests.FakeResponse(
            status_code=500)
        consumer_uuid = uuids.consumer_uuid
        self.assertRaises(
            exception.ConsumerAllocationRetrievalFailed,
            self.client.remove_provider_tree_from_instance_allocation,
            self.context, consumer_uuid, uuids.source)

        self.ks_adap_mock.get.assert_called()
        self.ks_adap_mock.put.assert_not_called()

    def test_remove_provider_from_inst_alloc_consumer_gen_conflict(self):
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.side_effect = [
            {
            'allocations': {
                uuids.source: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
                uuids.destination: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
            'consumer_generation': 1,
            'project_id': uuids.project_id,
            'user_id': uuids.user_id,
            },
            # the second get is for resource providers in the compute tree,
            # return just the compute
            {
                "resource_providers": [
                    {
                        "uuid": uuids.source,
                    },
                ]
            },
        ]
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=409)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        res = self.client.remove_provider_tree_from_instance_allocation(
            self.context, consumer_uuid, uuids.source)

        self.assertFalse(res)

    def test_remove_provider_tree_from_inst_alloc_nested(self):
        self.ks_adap_mock.get.side_effect = [
            fake_requests.FakeResponse(
                status_code=200,
                content=jsonutils.dumps(
                    {
                        'allocations': {
                            uuids.source_compute: {
                                'resource_provider_generation': 42,
                                'resources': {
                                    'VCPU': 1,
                                    'MEMORY_MB': 1024,
                                },
                            },
                            uuids.source_nested: {
                                'resource_provider_generation': 42,
                                'resources': {
                                    'CUSTOM_MAGIC': 1
                                },
                            },
                            uuids.destination: {
                                'resource_provider_generation': 42,
                                'resources': {
                                    'VCPU': 1,
                                    'MEMORY_MB': 1024,
                                },
                            },
                        },
                        'consumer_generation': 1,
                        'project_id': uuids.project_id,
                        'user_id': uuids.user_id,
                    })),
            # the second get is for resource providers in the compute tree,
            # return both RPs in the source compute tree
            fake_requests.FakeResponse(
                status_code=200,
                content=jsonutils.dumps(
                    {
                        "resource_providers": [
                            {
                                "uuid": uuids.source_compute,
                            },
                            {
                                "uuid": uuids.source_nested,
                            },
                        ]
                    }))
        ]
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(
            status_code=204)
        consumer_uuid = uuids.consumer_uuid
        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.remove_provider_tree_from_instance_allocation(
            self.context, consumer_uuid, uuids.source_compute)

        expected_url = "/allocations/%s" % consumer_uuid
        # New allocations should only include the destination...
        expected_payload = {
            'allocations': {
                uuids.destination: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
            'consumer_generation': 1,
            'project_id': project_id,
            'user_id': user_id
        }

        self.assertEqual(
            [
                mock.call(
                    '/allocations/%s' % consumer_uuid,
                    global_request_id=self.context.global_id,
                    microversion='1.28'
                ),
                mock.call(
                    '/resource_providers?in_tree=%s' % uuids.source_compute,
                    global_request_id=self.context.global_id,
                    microversion='1.14'
                )
            ],
            self.ks_adap_mock.get.mock_calls)

        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.28', json=mock.ANY,
            global_request_id=self.context.global_id)

        self.assertTrue(res)


class TestMoveAllocations(SchedulerReportClientTestCase):

    def setUp(self):
        super(TestMoveAllocations, self).setUp()
        # We want to reuse the mock throughout the class, but with
        # different return values.
        patcher = mock.patch(
            'nova.scheduler.client.report.SchedulerReportClient.post')
        self.mock_post = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_post.return_value.status_code = 204
        self.rp_uuid = mock.sentinel.rp
        self.consumer_uuid = mock.sentinel.consumer
        self.data = {"MEMORY_MB": 1024}
        patcher = mock.patch(
            'nova.scheduler.client.report.SchedulerReportClient.get')
        self.mock_get = patcher.start()
        self.addCleanup(patcher.stop)

        self.project_id = mock.sentinel.project_id
        self.user_id = mock.sentinel.user_id

        self.mock_post.return_value.status_code = 204
        self.rp_uuid = mock.sentinel.rp
        self.source_consumer_uuid = mock.sentinel.source_consumer
        self.target_consumer_uuid = mock.sentinel.target_consumer
        self.source_consumer_data = {
            "allocations": {
                self.rp_uuid: {
                    "generation": 1,
                    "resources": {
                        "MEMORY_MB": 1024
                    }
                }
            },
            "consumer_generation": 2,
            "project_id": self.project_id,
            "user_id": self.user_id
        }
        self.source_rsp = mock.Mock()
        self.source_rsp.json.return_value = self.source_consumer_data
        self.target_consumer_data = {
            "allocations": {
                self.rp_uuid: {
                    "generation": 1,
                    "resources": {
                        "MEMORY_MB": 2048
                    }
                }
            },
            "consumer_generation": 1,
            "project_id": self.project_id,
            "user_id": self.user_id
        }
        self.target_rsp = mock.Mock()
        self.target_rsp.json.return_value = self.target_consumer_data
        self.mock_get.side_effect = [self.source_rsp, self.target_rsp]
        self.expected_url = '/allocations'
        self.expected_microversion = '1.28'

    def test_url_microversion(self):
        resp = self.client.move_allocations(
            self.context, self.source_consumer_uuid, self.target_consumer_uuid)

        self.assertTrue(resp)
        self.mock_post.assert_called_once_with(
            self.expected_url, mock.ANY,
            version=self.expected_microversion,
            global_request_id=self.context.global_id)

    def test_move_to_empty_target(self):
        self.target_consumer_data = {"allocations": {}}
        target_rsp = mock.Mock()
        target_rsp.json.return_value = self.target_consumer_data
        self.mock_get.side_effect = [self.source_rsp, target_rsp]

        expected_payload = {
            self.target_consumer_uuid: {
                "allocations": {
                    self.rp_uuid: {
                        "resources": {
                            "MEMORY_MB": 1024
                        },
                        "generation": 1
                    }
                },
                "consumer_generation": None,
                "project_id": self.project_id,
                "user_id": self.user_id,
            },
            self.source_consumer_uuid: {
                "allocations": {},
                "consumer_generation": 2,
                "project_id": self.project_id,
                "user_id": self.user_id,
            }
        }

        resp = self.client.move_allocations(
            self.context, self.source_consumer_uuid, self.target_consumer_uuid)

        self.assertTrue(resp)
        self.mock_post.assert_called_once_with(
            self.expected_url, expected_payload,
            version=self.expected_microversion,
            global_request_id=self.context.global_id)

    @mock.patch('nova.scheduler.client.report.LOG.info')
    def test_move_from_empty_source(self, mock_info):
        """Tests the case that the target has allocations but the source does
        not so the move_allocations method assumes the allocations were already
        moved and returns True without trying to POST /allocations.
        """
        source_consumer_data = {"allocations": {}}
        source_rsp = mock.Mock()
        source_rsp.json.return_value = source_consumer_data
        self.mock_get.side_effect = [source_rsp, self.target_rsp]

        resp = self.client.move_allocations(
            self.context, self.source_consumer_uuid, self.target_consumer_uuid)

        self.assertTrue(resp)
        self.mock_post.assert_not_called()
        mock_info.assert_called_once()
        self.assertIn('Allocations not found for consumer',
                      mock_info.call_args[0][0])

    def test_move_to_non_empty_target(self):
        self.mock_get.side_effect = [self.source_rsp, self.target_rsp]

        expected_payload = {
            self.target_consumer_uuid: {
                "allocations": {
                    self.rp_uuid: {
                        "resources": {
                            "MEMORY_MB": 1024
                        },
                        "generation": 1
                    }
                },
                "consumer_generation": 1,
                "project_id": self.project_id,
                "user_id": self.user_id,
            },
            self.source_consumer_uuid: {
                "allocations": {},
                "consumer_generation": 2,
                "project_id": self.project_id,
                "user_id": self.user_id,
            }
        }

        with fixtures.EnvironmentVariable('OS_DEBUG', '1'):
            with nova_fixtures.StandardLogging() as stdlog:
                resp = self.client.move_allocations(
                    self.context, self.source_consumer_uuid,
                    self.target_consumer_uuid)

        self.assertTrue(resp)
        self.mock_post.assert_called_once_with(
            self.expected_url, expected_payload,
            version=self.expected_microversion,
            global_request_id=self.context.global_id)
        self.assertIn('Overwriting current allocation',
                      stdlog.logger.output)

    @mock.patch('time.sleep')
    def test_409_concurrent_provider_update(self, mock_sleep):
        # there will be 1 normal call and 3 retries
        self.mock_get.side_effect = [self.source_rsp, self.target_rsp,
                                     self.source_rsp, self.target_rsp,
                                     self.source_rsp, self.target_rsp,
                                     self.source_rsp, self.target_rsp]
        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': ''}]}))

        self.mock_post.return_value = rsp

        resp = self.client.move_allocations(
            self.context, self.source_consumer_uuid, self.target_consumer_uuid)

        self.assertFalse(resp)
        # Post was attempted four times.
        self.assertEqual(4, self.mock_post.call_count)

    @mock.patch('nova.scheduler.client.report.LOG.warning')
    def test_not_409_failure(self, mock_log):
        error_message = 'placement not there'
        self.mock_post.return_value.status_code = 503
        self.mock_post.return_value.text = error_message

        resp = self.client.move_allocations(
            self.context, self.source_consumer_uuid, self.target_consumer_uuid)

        self.assertFalse(resp)
        args, kwargs = mock_log.call_args
        log_message = args[0]
        log_args = args[1]
        self.assertIn('Unable to post allocations', log_message)
        self.assertEqual(error_message, log_args['text'])

    def test_409_concurrent_consumer_update(self):
        self.mock_post.return_value = fake_requests.FakeResponse(
            status_code=409,
            content=jsonutils.dumps(
                {'errors': [{'code': 'placement.concurrent_update',
                             'detail': 'consumer generation conflict'}]}))

        self.assertRaises(exception.AllocationMoveFailed,
            self.client.move_allocations, self.context,
            self.source_consumer_uuid, self.target_consumer_uuid)


class TestProviderOperations(SchedulerReportClientTestCase):
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_traits')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_sharing_providers')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_providers_in_tree')
    def test_ensure_resource_provider_get(self, get_rpt_mock, get_shr_mock,
            get_trait_mock, get_agg_mock, get_inv_mock, create_rp_mock):
        # No resource provider exists in the client's cache, so validate that
        # if we get the resource provider from the placement API that we don't
        # try to create the resource provider.
        get_rpt_mock.return_value = [{
            'uuid': uuids.compute_node,
            'name': mock.sentinel.name,
            'generation': 1,
        }]

        get_inv_mock.return_value = None
        get_agg_mock.return_value = report.AggInfo(
            aggregates=set([uuids.agg1]), generation=42)
        get_trait_mock.return_value = report.TraitInfo(
            traits=set(['CUSTOM_GOLD']), generation=43)
        get_shr_mock.return_value = []

        def assert_cache_contents():
            self.assertTrue(
                self.client._provider_tree.exists(uuids.compute_node))
            self.assertTrue(
                self.client._provider_tree.in_aggregates(uuids.compute_node,
                                                         [uuids.agg1]))
            self.assertFalse(
                self.client._provider_tree.in_aggregates(uuids.compute_node,
                                                         [uuids.agg2]))
            self.assertTrue(
                self.client._provider_tree.has_traits(uuids.compute_node,
                                                      ['CUSTOM_GOLD']))
            self.assertFalse(
                self.client._provider_tree.has_traits(uuids.compute_node,
                                                      ['CUSTOM_SILVER']))
            data = self.client._provider_tree.data(uuids.compute_node)
            self.assertEqual(43, data.generation)

        self.client._ensure_resource_provider(self.context, uuids.compute_node)

        assert_cache_contents()
        get_rpt_mock.assert_called_once_with(self.context, uuids.compute_node)
        get_agg_mock.assert_called_once_with(self.context, uuids.compute_node)
        get_trait_mock.assert_called_once_with(self.context,
                                               uuids.compute_node)
        get_shr_mock.assert_called_once_with(self.context, set([uuids.agg1]))
        self.assertFalse(create_rp_mock.called)

        # Now that the cache is populated, a subsequent call should be a no-op.
        get_rpt_mock.reset_mock()
        get_agg_mock.reset_mock()
        get_trait_mock.reset_mock()
        get_shr_mock.reset_mock()

        self.client._ensure_resource_provider(self.context, uuids.compute_node)

        assert_cache_contents()
        get_rpt_mock.assert_not_called()
        get_agg_mock.assert_not_called()
        get_trait_mock.assert_not_called()
        get_shr_mock.assert_not_called()
        create_rp_mock.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_providers_in_tree')
    def test_ensure_resource_provider_create_fail(self, get_rpt_mock,
            refresh_mock, create_rp_mock):
        # No resource provider exists in the client's cache, and
        # _create_provider raises, indicating there was an error with the
        # create call. Ensure we don't populate the resource provider cache
        get_rpt_mock.return_value = []
        create_rp_mock.side_effect = exception.ResourceProviderCreationFailed(
            name=uuids.compute_node)

        self.assertRaises(
            exception.ResourceProviderCreationFailed,
            self.client._ensure_resource_provider, self.context,
            uuids.compute_node)

        get_rpt_mock.assert_called_once_with(self.context, uuids.compute_node)
        create_rp_mock.assert_called_once_with(
            self.context, uuids.compute_node, uuids.compute_node,
            parent_provider_uuid=None)
        self.assertFalse(self.client._provider_tree.exists(uuids.compute_node))
        self.assertFalse(refresh_mock.called)
        self.assertRaises(
            ValueError,
            self.client._provider_tree.in_aggregates, uuids.compute_node, [])
        self.assertRaises(
            ValueError,
            self.client._provider_tree.has_traits, uuids.compute_node, [])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider', return_value=None)
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_providers_in_tree')
    def test_ensure_resource_provider_create_no_placement(self, get_rpt_mock,
            refresh_mock, create_rp_mock):
        # No resource provider exists in the client's cache, and
        # @safe_connect on _create_resource_provider returns None because
        # Placement isn't running yet. Ensure we don't populate the resource
        # provider cache.
        get_rpt_mock.return_value = []

        self.assertRaises(
            exception.ResourceProviderCreationFailed,
            self.client._ensure_resource_provider, self.context,
            uuids.compute_node)

        get_rpt_mock.assert_called_once_with(self.context, uuids.compute_node)
        create_rp_mock.assert_called_once_with(
            self.context, uuids.compute_node, uuids.compute_node,
            parent_provider_uuid=None)
        self.assertFalse(self.client._provider_tree.exists(uuids.compute_node))
        refresh_mock.assert_not_called()
        self.assertRaises(
            ValueError,
            self.client._provider_tree.in_aggregates, uuids.compute_node, [])
        self.assertRaises(
            ValueError,
            self.client._provider_tree.has_traits, uuids.compute_node, [])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_and_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_providers_in_tree')
    def test_ensure_resource_provider_create(self, get_rpt_mock,
                                             refresh_inv_mock,
                                             refresh_assoc_mock,
                                             create_rp_mock):
        # No resource provider exists in the client's cache and no resource
        # provider was returned from the placement API, so verify that in this
        # case we try to create the resource provider via the placement API.
        get_rpt_mock.return_value = []
        create_rp_mock.return_value = {
            'uuid': uuids.compute_node,
            'name': 'compute-name',
            'generation': 1,
        }
        self.assertEqual(
            uuids.compute_node,
            self.client._ensure_resource_provider(self.context,
                                                  uuids.compute_node))
        self._validate_provider(uuids.compute_node, name='compute-name',
                                generation=1, parent_uuid=None,
                                aggregates=set(), traits=set())

        # We don't refresh for a just-created provider
        refresh_inv_mock.assert_not_called()
        refresh_assoc_mock.assert_not_called()
        get_rpt_mock.assert_called_once_with(self.context, uuids.compute_node)
        create_rp_mock.assert_called_once_with(
                self.context,
                uuids.compute_node,
                uuids.compute_node,  # name param defaults to UUID if None
                parent_provider_uuid=None,
        )
        self.assertTrue(self.client._provider_tree.exists(uuids.compute_node))

        create_rp_mock.reset_mock()

        # Validate the path where we specify a name (don't default to the UUID)
        self.client._ensure_resource_provider(
            self.context, uuids.cn2, 'a-name')
        create_rp_mock.assert_called_once_with(
                self.context, uuids.cn2, 'a-name', parent_provider_uuid=None)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_providers_in_tree')
    def test_ensure_resource_provider_tree(self, get_rpt_mock, create_rp_mock,
                                           refresh_mock):
        """Test _ensure_resource_provider with a tree of providers."""
        def _create_resource_provider(context, uuid, name,
                                      parent_provider_uuid=None):
            """Mock side effect for creating the RP with the specified args."""
            return {
                'uuid': uuid,
                'name': name,
                'generation': 0,
                'parent_provider_uuid': parent_provider_uuid
            }
        create_rp_mock.side_effect = _create_resource_provider

        # We at least have to simulate the part of _refresh_associations that
        # marks a provider as 'seen'
        def mocked_refresh(context, rp_uuid, **kwargs):
            self.client._association_refresh_time[rp_uuid] = time.time()
        refresh_mock.side_effect = mocked_refresh

        # Not initially in the placement database, so we have to create it.
        get_rpt_mock.return_value = []

        # Create the root
        root = self.client._ensure_resource_provider(self.context, uuids.root)
        self.assertEqual(uuids.root, root)

        # Now create a child
        child1 = self.client._ensure_resource_provider(
            self.context, uuids.child1, name='junior',
            parent_provider_uuid=uuids.root)
        self.assertEqual(uuids.child1, child1)

        # If we re-ensure the child, we get the object from the tree, not a
        # newly-created one - i.e. the early .find() works like it should.
        self.assertIs(child1,
                      self.client._ensure_resource_provider(self.context,
                                                            uuids.child1))

        # Make sure we can create a grandchild
        grandchild = self.client._ensure_resource_provider(
            self.context, uuids.grandchild,
            parent_provider_uuid=uuids.child1)
        self.assertEqual(uuids.grandchild, grandchild)

        # Now create a second child of the root and make sure it doesn't wind
        # up in some crazy wrong place like under child1 or grandchild
        child2 = self.client._ensure_resource_provider(
            self.context, uuids.child2, parent_provider_uuid=uuids.root)
        self.assertEqual(uuids.child2, child2)

        all_rp_uuids = [uuids.root, uuids.child1, uuids.child2,
                        uuids.grandchild]

        # At this point we should get all the providers.
        self.assertEqual(
            set(all_rp_uuids),
            set(self.client._provider_tree.get_provider_uuids()))

        # And now _ensure is a no-op because everything is cached
        get_rpt_mock.reset_mock()
        create_rp_mock.reset_mock()
        refresh_mock.reset_mock()

        for rp_uuid in all_rp_uuids:
            self.client._ensure_resource_provider(self.context, rp_uuid)
        get_rpt_mock.assert_not_called()
        create_rp_mock.assert_not_called()
        refresh_mock.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_providers_in_tree')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    def test_ensure_resource_provider_refresh_fetch(self, mock_ref_assoc,
                                                    mock_gpit):
        """Make sure refreshes are called with the appropriate UUIDs and flags
        when we fetch the provider tree from placement.
        """
        tree_uuids = set([uuids.root, uuids.one, uuids.two])
        mock_gpit.return_value = [{'uuid': u, 'name': u, 'generation': 42}
                                  for u in tree_uuids]
        self.assertEqual(uuids.root,
                         self.client._ensure_resource_provider(self.context,
                                                               uuids.root))
        mock_gpit.assert_called_once_with(self.context, uuids.root)
        mock_ref_assoc.assert_has_calls(
            [mock.call(self.context, uuid, force=True)
             for uuid in tree_uuids])
        self.assertEqual(tree_uuids,
                         set(self.client._provider_tree.get_provider_uuids()))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_providers_in_tree')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    def test_ensure_resource_provider_refresh_create(self, mock_refresh,
            mock_create, mock_gpit):
        """Make sure refresh is not called when we create the RP."""
        mock_gpit.return_value = []
        mock_create.return_value = {'name': 'cn', 'uuid': uuids.cn,
                                    'generation': 42}
        self.assertEqual(uuids.root,
                         self.client._ensure_resource_provider(self.context,
                                                               uuids.root))
        mock_gpit.assert_called_once_with(self.context, uuids.root)
        mock_create.assert_called_once_with(self.context, uuids.root,
                                            uuids.root,
                                            parent_provider_uuid=None)
        mock_refresh.assert_not_called()
        self.assertEqual([uuids.cn],
                         self.client._provider_tree.get_provider_uuids())

    def test_get_allocation_candidates(self):
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'allocation_requests': mock.sentinel.alloc_reqs,
            'provider_summaries': mock.sentinel.p_sums,
        }
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'resources:VCPU': '1',
                'resources:MEMORY_MB': '1024',
                'trait:HW_CPU_X86_AVX': 'required',
                'trait:CUSTOM_TRAIT1': 'required',
                'trait:CUSTOM_TRAIT2': 'preferred',
                'trait:CUSTOM_TRAIT3': 'forbidden',
                'trait:CUSTOM_TRAIT4': 'forbidden',
                'resources_DISK:DISK_GB': '30',
                'trait_DISK:STORAGE_DISK_SSD': 'required',
                'resources2:VGPU': '2',
                'trait2:HW_GPU_RESOLUTION_W2560H1600': 'required',
                'trait2:HW_GPU_API_VULKAN': 'required',
                'resources_NET:SRIOV_NET_VF': '1',
                'resources_NET:CUSTOM_NET_EGRESS_BYTES_SEC': '125000',
                'group_policy': 'isolate',
                # These are ignored because misspelled, bad value, etc.
                'resources*2:CUSTOM_WIDGET': '123',
                'trait:HW_NIC_OFFLOAD_LRO': 'preferred',
                'group_policy3': 'none',
            })
        req_spec = objects.RequestSpec(flavor=flavor, is_bfv=False)
        resources = scheduler_utils.ResourceRequest(req_spec)
        resources.get_request_group(None).aggregates = [
            ['agg1', 'agg2', 'agg3'], ['agg1', 'agg2']]
        forbidden_aggs = set(['agg1', 'agg5', 'agg6'])
        resources.get_request_group(None).forbidden_aggregates = forbidden_aggs
        expected_path = '/allocation_candidates'
        expected_query = [
            ('group_policy', 'isolate'),
            ('limit', '1000'),
            ('member_of', '!in:agg1,agg5,agg6'),
            ('member_of', 'in:agg1,agg2'),
            ('member_of', 'in:agg1,agg2,agg3'),
            ('required', 'CUSTOM_TRAIT1,HW_CPU_X86_AVX,!CUSTOM_TRAIT3,'
                         '!CUSTOM_TRAIT4'),
            ('required2', 'HW_GPU_API_VULKAN,HW_GPU_RESOLUTION_W2560H1600'),
            ('required_DISK', 'STORAGE_DISK_SSD'),
            ('resources', 'MEMORY_MB:1024,VCPU:1'),
            ('resources2', 'VGPU:2'),
            ('resources_DISK', 'DISK_GB:30'),
            ('resources_NET',
             'CUSTOM_NET_EGRESS_BYTES_SEC:125000,SRIOV_NET_VF:1')
        ]

        resp_mock.json.return_value = json_data
        self.ks_adap_mock.get.return_value = resp_mock

        alloc_reqs, p_sums, allocation_request_version = (
            self.client.get_allocation_candidates(self.context, resources))

        url = self.ks_adap_mock.get.call_args[0][0]
        split_url = parse.urlsplit(url)
        query = parse.parse_qsl(split_url.query)
        self.assertEqual(expected_path, split_url.path)
        self.assertEqual(expected_query, query)
        expected_url = '/allocation_candidates?%s' % parse.urlencode(
            expected_query)
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.35',
            global_request_id=self.context.global_id)
        self.assertEqual(mock.sentinel.alloc_reqs, alloc_reqs)
        self.assertEqual(mock.sentinel.p_sums, p_sums)

    def test_get_ac_no_trait_bogus_group_policy_custom_limit(self):
        self.flags(max_placement_results=42, group='scheduler')
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'allocation_requests': mock.sentinel.alloc_reqs,
            'provider_summaries': mock.sentinel.p_sums,
        }
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'resources:VCPU': '1',
                'resources:MEMORY_MB': '1024',
                'resources1:DISK_GB': '30',
                'group_policy': 'bogus',
            })
        req_spec = objects.RequestSpec(flavor=flavor, is_bfv=False)
        resources = scheduler_utils.ResourceRequest(req_spec)
        expected_path = '/allocation_candidates'
        expected_query = [
            ('limit', '42'),
            ('resources', 'MEMORY_MB:1024,VCPU:1'),
            ('resources1', 'DISK_GB:30'),
        ]

        resp_mock.json.return_value = json_data
        self.ks_adap_mock.get.return_value = resp_mock

        alloc_reqs, p_sums, allocation_request_version = (
            self.client.get_allocation_candidates(self.context, resources))

        url = self.ks_adap_mock.get.call_args[0][0]
        split_url = parse.urlsplit(url)
        query = parse.parse_qsl(split_url.query)
        self.assertEqual(expected_path, split_url.path)
        self.assertEqual(expected_query, query)
        expected_url = '/allocation_candidates?%s' % parse.urlencode(
            expected_query)
        self.assertEqual(mock.sentinel.alloc_reqs, alloc_reqs)
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.35',
            global_request_id=self.context.global_id)
        self.assertEqual(mock.sentinel.p_sums, p_sums)

    def test_get_allocation_candidates_not_found(self):
        # Ensure _get_resource_provider() just returns None when the placement
        # API doesn't find a resource provider matching a UUID
        resp_mock = mock.Mock(status_code=404)
        self.ks_adap_mock.get.return_value = resp_mock
        expected_path = '/allocation_candidates'
        expected_query = {
            'resources': ['DISK_GB:15,MEMORY_MB:1024,VCPU:1'],
            'limit': ['100']
        }

        # Make sure we're also honoring the configured limit
        self.flags(max_placement_results=100, group='scheduler')

        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)
        req_spec = objects.RequestSpec(flavor=flavor, is_bfv=False)
        resources = scheduler_utils.ResourceRequest(req_spec)

        res = self.client.get_allocation_candidates(self.context, resources)

        self.ks_adap_mock.get.assert_called_once_with(
            mock.ANY, microversion='1.35',
            global_request_id=self.context.global_id)
        url = self.ks_adap_mock.get.call_args[0][0]
        split_url = parse.urlsplit(url)
        query = parse.parse_qs(split_url.query)
        self.assertEqual(expected_path, split_url.path)
        self.assertEqual(expected_query, query)
        self.assertIsNone(res[0])

    def test_get_resource_provider_found(self):
        # Ensure _get_resource_provider() returns a dict of resource provider
        # if it finds a resource provider record from the placement API
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'uuid': uuid,
            'name': uuid,
            'generation': 42,
            'parent_provider_uuid': None,
        }
        resp_mock.json.return_value = json_data
        self.ks_adap_mock.get.return_value = resp_mock

        result = self.client._get_resource_provider(self.context, uuid)

        expected_provider_dict = dict(
                uuid=uuid,
                name=uuid,
                generation=42,
                parent_provider_uuid=None,
        )
        expected_url = '/resource_providers/' + uuid
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.14',
            global_request_id=self.context.global_id)
        self.assertEqual(expected_provider_dict, result)

    def test_get_resource_provider_not_found(self):
        # Ensure _get_resource_provider() just returns None when the placement
        # API doesn't find a resource provider matching a UUID
        resp_mock = mock.Mock(status_code=404)
        self.ks_adap_mock.get.return_value = resp_mock

        uuid = uuids.compute_node
        result = self.client._get_resource_provider(self.context, uuid)

        expected_url = '/resource_providers/' + uuid
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.14',
            global_request_id=self.context.global_id)
        self.assertIsNone(result)

    @mock.patch.object(report.LOG, 'error')
    def test_get_resource_provider_error(self, logging_mock):
        # Ensure _get_resource_provider() sets the error flag when trying to
        # communicate with the placement API and not getting an error we can
        # deal with
        resp_mock = mock.Mock(status_code=503)
        self.ks_adap_mock.get.return_value = resp_mock
        self.ks_adap_mock.get.return_value.headers = {
            'x-openstack-request-id': uuids.request_id}

        uuid = uuids.compute_node
        self.assertRaises(
            exception.ResourceProviderRetrievalFailed,
            self.client._get_resource_provider, self.context, uuid)

        expected_url = '/resource_providers/' + uuid
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.14',
            global_request_id=self.context.global_id)
        # A 503 Service Unavailable should trigger an error log that
        # includes the placement request id and return None
        # from _get_resource_provider()
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                         logging_mock.call_args[0][1]['placement_req_id'])

    def test_get_sharing_providers(self):
        resp_mock = mock.Mock(status_code=200)
        rpjson = [
            {
                'uuid': uuids.sharing1,
                'name': 'bandwidth_provider',
                'generation': 42,
                'parent_provider_uuid': None,
                'root_provider_uuid': None,
                'links': [],
            },
            {
                'uuid': uuids.sharing2,
                'name': 'storage_provider',
                'generation': 42,
                'parent_provider_uuid': None,
                'root_provider_uuid': None,
                'links': [],
            },
        ]
        resp_mock.json.return_value = {'resource_providers': rpjson}
        self.ks_adap_mock.get.return_value = resp_mock

        result = self.client._get_sharing_providers(
            self.context, [uuids.agg1, uuids.agg2])

        expected_url = ('/resource_providers?member_of=in:' +
                        ','.join((uuids.agg1, uuids.agg2)) +
                        '&required=MISC_SHARES_VIA_AGGREGATE')
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.18',
            global_request_id=self.context.global_id)
        self.assertEqual(rpjson, result)

    def test_get_sharing_providers_emptylist(self):
        self.assertEqual(
            [], self.client._get_sharing_providers(self.context, []))
        self.ks_adap_mock.get.assert_not_called()

    @mock.patch.object(report.LOG, 'error')
    def test_get_sharing_providers_error(self, logging_mock):
        # Ensure _get_sharing_providers() logs an error and raises if the
        # placement API call doesn't respond 200
        resp_mock = mock.Mock(status_code=503)
        self.ks_adap_mock.get.return_value = resp_mock
        self.ks_adap_mock.get.return_value.headers = {
            'x-openstack-request-id': uuids.request_id}

        uuid = uuids.agg
        self.assertRaises(exception.ResourceProviderRetrievalFailed,
                          self.client._get_sharing_providers,
                          self.context, [uuid])

        expected_url = ('/resource_providers?member_of=in:' + uuid +
                        '&required=MISC_SHARES_VIA_AGGREGATE')
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.18',
            global_request_id=self.context.global_id)
        # A 503 Service Unavailable should trigger an error log that
        # includes the placement request id
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                         logging_mock.call_args[0][1]['placement_req_id'])

    def test_get_providers_in_tree(self):
        # Ensure get_providers_in_tree() returns a list of resource
        # provider dicts if it finds a resource provider record from the
        # placement API
        root = uuids.compute_node
        child = uuids.child
        resp_mock = mock.Mock(status_code=200)
        rpjson = [
            {
                'uuid': root,
                'name': 'daddy', 'generation': 42,
                'parent_provider_uuid': None,
            },
            {
                'uuid': child,
                'name': 'junior',
                'generation': 42,
                'parent_provider_uuid': root,
            },
        ]
        resp_mock.json.return_value = {'resource_providers': rpjson}
        self.ks_adap_mock.get.return_value = resp_mock

        result = self.client.get_providers_in_tree(self.context, root)

        expected_url = '/resource_providers?in_tree=' + root
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.14',
            global_request_id=self.context.global_id)
        self.assertEqual(rpjson, result)

    @mock.patch.object(report.LOG, 'error')
    def test_get_providers_in_tree_error(self, logging_mock):
        # Ensure get_providers_in_tree() logs an error and raises if the
        # placement API call doesn't respond 200
        resp_mock = mock.Mock(status_code=503)
        self.ks_adap_mock.get.return_value = resp_mock
        self.ks_adap_mock.get.return_value.headers = {
            'x-openstack-request-id': 'req-' + uuids.request_id}

        uuid = uuids.compute_node
        self.assertRaises(exception.ResourceProviderRetrievalFailed,
                          self.client.get_providers_in_tree, self.context,
                          uuid)

        expected_url = '/resource_providers?in_tree=' + uuid
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.14',
            global_request_id=self.context.global_id)
        # A 503 Service Unavailable should trigger an error log that includes
        # the placement request id
        self.assertTrue(logging_mock.called)
        self.assertEqual('req-' + uuids.request_id,
                         logging_mock.call_args[0][1]['placement_req_id'])

    def test_get_providers_in_tree_ksa_exc(self):
        self.ks_adap_mock.get.side_effect = ks_exc.EndpointNotFound()
        self.assertRaises(
            ks_exc.ClientException,
            self.client.get_providers_in_tree, self.context, uuids.whatever)

    def test_create_resource_provider(self):
        """Test that _create_resource_provider() sends a dict of resource
        provider information without a parent provider UUID.
        """
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=200)
        self.ks_adap_mock.post.return_value = resp_mock

        self.assertEqual(
            resp_mock.json.return_value,
            self.client._create_resource_provider(self.context, uuid, name))

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }

        expected_url = '/resource_providers'
        self.ks_adap_mock.post.assert_called_once_with(
            expected_url, json=expected_payload, microversion='1.20',
            global_request_id=self.context.global_id)

    def test_create_resource_provider_with_parent(self):
        """Test that when specifying a parent provider UUID, that the
        parent_provider_uuid part of the payload is properly specified.
        """
        parent_uuid = uuids.parent
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=200)
        self.ks_adap_mock.post.return_value = resp_mock

        self.assertEqual(
            resp_mock.json.return_value,
            self.client._create_resource_provider(
                self.context,
                uuid,
                name,
                parent_provider_uuid=parent_uuid,
            )
        )

        expected_payload = {
            'uuid': uuid,
            'name': name,
            'parent_provider_uuid': parent_uuid,
        }
        expected_url = '/resource_providers'
        self.ks_adap_mock.post.assert_called_once_with(
            expected_url, json=expected_payload, microversion='1.20',
            global_request_id=self.context.global_id)

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
        self.ks_adap_mock.post.return_value = fake_requests.FakeResponse(
            409, content='not a name conflict',
            headers={'x-openstack-request-id': uuids.request_id})

        get_rp_mock.return_value = mock.sentinel.get_rp

        result = self.client._create_resource_provider(self.context, uuid,
                                                       name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_url = '/resource_providers'
        self.ks_adap_mock.post.assert_called_once_with(
            expected_url, json=expected_payload, microversion='1.20',
            global_request_id=self.context.global_id)
        self.assertEqual(mock.sentinel.get_rp, result)
        # The 409 response will produce a message to the info log.
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                        logging_mock.call_args[0][1]['placement_req_id'])

    def test_create_resource_provider_name_conflict(self):
        # When the API call to create the resource provider fails 409 with a
        # name conflict, we raise an exception.
        self.ks_adap_mock.post.return_value = fake_requests.FakeResponse(
            409, content='<stuff>Conflicting resource provider name: foo '
                         'already exists.</stuff>')

        self.assertRaises(
            exception.ResourceProviderCreationFailed,
            self.client._create_resource_provider, self.context,
            uuids.compute_node, 'foo')

    @mock.patch.object(report.LOG, 'error')
    def test_create_resource_provider_error(self, logging_mock):
        # Ensure _create_resource_provider() sets the error flag when trying to
        # communicate with the placement API and not getting an error we can
        # deal with
        uuid = uuids.compute_node
        name = 'computehost'
        self.ks_adap_mock.post.return_value = fake_requests.FakeResponse(
            503, headers={'x-openstack-request-id': uuids.request_id})

        self.assertRaises(
            exception.ResourceProviderCreationFailed,
            self.client._create_resource_provider, self.context, uuid, name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_url = '/resource_providers'
        self.ks_adap_mock.post.assert_called_once_with(
            expected_url, json=expected_payload, microversion='1.20',
            global_request_id=self.context.global_id)
        # A 503 Service Unavailable should log an error that
        # includes the placement request id and
        # _create_resource_provider() should return None
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                        logging_mock.call_args[0][1]['placement_req_id'])

    def test_put_empty(self):
        # A simple put with an empty (not None) payload should send the empty
        # payload through.
        # Bug #1744786
        url = '/resource_providers/%s/aggregates' % uuids.foo
        self.client.put(url, [])
        self.ks_adap_mock.put.assert_called_once_with(
            url, json=[], microversion=None, global_request_id=None)

    def test_delete_provider(self):
        delete_mock = fake_requests.FakeResponse(None)
        self.ks_adap_mock.delete.return_value = delete_mock

        for status_code in (204, 404):
            delete_mock.status_code = status_code
            # Seed the caches
            self.client._provider_tree.new_root('compute', uuids.root,
                                                generation=0)
            self.client._association_refresh_time[uuids.root] = 1234

            self.client._delete_provider(uuids.root, global_request_id='gri')

            self.ks_adap_mock.delete.assert_called_once_with(
                '/resource_providers/' + uuids.root,
                global_request_id='gri', microversion=None)
            self.assertFalse(self.client._provider_tree.exists(uuids.root))
            self.assertNotIn(uuids.root, self.client._association_refresh_time)

            self.ks_adap_mock.delete.reset_mock()

    def test_delete_provider_fail(self):
        delete_mock = fake_requests.FakeResponse(None)
        self.ks_adap_mock.delete.return_value = delete_mock
        resp_exc_map = {409: exception.ResourceProviderInUse,
                        503: exception.ResourceProviderDeletionFailed}

        for status_code, exc in resp_exc_map.items():
            delete_mock.status_code = status_code
            self.assertRaises(exc, self.client._delete_provider, uuids.root)
            self.ks_adap_mock.delete.assert_called_once_with(
                '/resource_providers/' + uuids.root, microversion=None,
                global_request_id=None)

            self.ks_adap_mock.delete.reset_mock()

    def test_set_aggregates_for_provider(self):
        aggs = [uuids.agg1, uuids.agg2]
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(
            200, content=jsonutils.dumps({
                'aggregates': aggs,
                'resource_provider_generation': 1}))

        # Prime the provider tree cache
        self.client._provider_tree.new_root('rp', uuids.rp, generation=0)
        self.assertEqual(set(),
                         self.client._provider_tree.data(uuids.rp).aggregates)

        self.client.set_aggregates_for_provider(self.context, uuids.rp, aggs)

        exp_payload = {'aggregates': aggs,
                       'resource_provider_generation': 0}
        self.ks_adap_mock.put.assert_called_once_with(
            '/resource_providers/%s/aggregates' % uuids.rp, json=exp_payload,
            microversion='1.19',
            global_request_id=self.context.global_id)
        # Cache was updated
        ptree_data = self.client._provider_tree.data(uuids.rp)
        self.assertEqual(set(aggs), ptree_data.aggregates)
        self.assertEqual(1, ptree_data.generation)

    def test_set_aggregates_for_provider_bad_args(self):
        self.assertRaises(ValueError, self.client.set_aggregates_for_provider,
                          self.context, uuids.rp, {}, use_cache=False)
        self.assertRaises(ValueError, self.client.set_aggregates_for_provider,
                          self.context, uuids.rp, {}, use_cache=False,
                          generation=None)

    def test_set_aggregates_for_provider_fail(self):
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(503)
        # Prime the provider tree cache
        self.client._provider_tree.new_root('rp', uuids.rp, generation=0)
        self.assertRaises(
            exception.ResourceProviderUpdateFailed,
            self.client.set_aggregates_for_provider,
            self.context, uuids.rp, [uuids.agg])
        # The cache wasn't updated
        self.assertEqual(set(),
                         self.client._provider_tree.data(uuids.rp).aggregates)

    def test_set_aggregates_for_provider_conflict(self):
        # Prime the provider tree cache
        self.client._provider_tree.new_root('rp', uuids.rp, generation=0)
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(409)
        self.assertRaises(
            exception.ResourceProviderUpdateConflict,
            self.client.set_aggregates_for_provider,
            self.context, uuids.rp, [uuids.agg])
        # The cache was invalidated
        self.assertNotIn(uuids.rp,
                         self.client._provider_tree.get_provider_uuids())
        self.assertNotIn(uuids.rp, self.client._association_refresh_time)

    def test_set_aggregates_for_provider_short_circuit(self):
        """No-op when aggregates have not changed."""
        # Prime the provider tree cache
        self.client._provider_tree.new_root('rp', uuids.rp, generation=7)
        self.client.set_aggregates_for_provider(self.context, uuids.rp, [])
        self.ks_adap_mock.put.assert_not_called()

    def test_set_aggregates_for_provider_no_short_circuit(self):
        """Don't short-circuit if generation doesn't match, even if aggs have
        not changed.
        """
        # Prime the provider tree cache
        self.client._provider_tree.new_root('rp', uuids.rp, generation=2)
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(
            200, content=jsonutils.dumps({
                'aggregates': [],
                'resource_provider_generation': 5}))
        self.client.set_aggregates_for_provider(self.context, uuids.rp, [],
                                                generation=4)
        exp_payload = {'aggregates': [],
                       'resource_provider_generation': 4}
        self.ks_adap_mock.put.assert_called_once_with(
            '/resource_providers/%s/aggregates' % uuids.rp, json=exp_payload,
            microversion='1.19',
            global_request_id=self.context.global_id)
        # Cache was updated
        ptree_data = self.client._provider_tree.data(uuids.rp)
        self.assertEqual(set(), ptree_data.aggregates)
        self.assertEqual(5, ptree_data.generation)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider', return_value=mock.NonCallableMock)
    def test_get_resource_provider_name_from_cache(self, mock_placement_get):
        expected_name = 'rp'
        self.client._provider_tree.new_root(
            expected_name, uuids.rp, generation=0)

        actual_name = self.client.get_resource_provider_name(
            self.context, uuids.rp)

        self.assertEqual(expected_name, actual_name)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_get_resource_provider_name_from_placement(
            self, mock_placement_get):
        expected_name = 'rp'
        mock_placement_get.return_value = {
            'uuid': uuids.rp,
            'name': expected_name
        }

        actual_name = self.client.get_resource_provider_name(
            self.context, uuids.rp)

        self.assertEqual(expected_name, actual_name)
        mock_placement_get.assert_called_once_with(self.context, uuids.rp)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_get_resource_provider_name_rp_not_found_in_placement(
            self, mock_placement_get):
        mock_placement_get.side_effect = \
            exception.ResourceProviderNotFound(uuids.rp)

        self.assertRaises(
            exception.ResourceProviderNotFound,
            self.client.get_resource_provider_name,
            self.context, uuids.rp)

        mock_placement_get.assert_called_once_with(self.context, uuids.rp)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_get_resource_provider_name_placement_unavailable(
            self, mock_placement_get):
        mock_placement_get.side_effect = \
            exception.ResourceProviderRetrievalFailed(uuid=uuids.rp)

        self.assertRaises(
            exception.ResourceProviderRetrievalFailed,
            self.client.get_resource_provider_name,
            self.context, uuids.rp)


class TestAggregates(SchedulerReportClientTestCase):
    def test_get_provider_aggregates_found(self):
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=200)
        aggs = [
            uuids.agg1,
            uuids.agg2,
        ]
        resp_mock.json.return_value = {'aggregates': aggs,
                                       'resource_provider_generation': 42}
        self.ks_adap_mock.get.return_value = resp_mock

        result, gen = self.client._get_provider_aggregates(self.context, uuid)

        expected_url = '/resource_providers/' + uuid + '/aggregates'
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.19',
            global_request_id=self.context.global_id)
        self.assertEqual(set(aggs), result)
        self.assertEqual(42, gen)

    @mock.patch.object(report.LOG, 'error')
    def test_get_provider_aggregates_error(self, log_mock):
        """Test that when the placement API returns any error when looking up a
        provider's aggregates, we raise an exception.
        """
        uuid = uuids.compute_node
        resp_mock = mock.Mock(headers={
            'x-openstack-request-id': uuids.request_id})
        self.ks_adap_mock.get.return_value = resp_mock

        for status_code in (400, 404, 503):
            resp_mock.status_code = status_code
            self.assertRaises(
                exception.ResourceProviderAggregateRetrievalFailed,
                self.client._get_provider_aggregates, self.context, uuid)

            expected_url = '/resource_providers/' + uuid + '/aggregates'
            self.ks_adap_mock.get.assert_called_once_with(
                expected_url, microversion='1.19',
                global_request_id=self.context.global_id)
            self.assertTrue(log_mock.called)
            self.assertEqual(uuids.request_id,
                             log_mock.call_args[0][1]['placement_req_id'])
            self.ks_adap_mock.get.reset_mock()
            log_mock.reset_mock()


class TestTraits(SchedulerReportClientTestCase):
    trait_api_kwargs = {'microversion': '1.6'}

    def test_get_provider_traits_found(self):
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=200)
        traits = [
            'CUSTOM_GOLD',
            'CUSTOM_SILVER',
        ]
        resp_mock.json.return_value = {'traits': traits,
                                       'resource_provider_generation': 42}
        self.ks_adap_mock.get.return_value = resp_mock

        result, gen = self.client.get_provider_traits(self.context, uuid)

        expected_url = '/resource_providers/' + uuid + '/traits'
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url,
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)
        self.assertEqual(set(traits), result)
        self.assertEqual(42, gen)

    @mock.patch.object(report.LOG, 'error')
    def test_get_provider_traits_error(self, log_mock):
        """Test that when the placement API returns any error when looking up a
        provider's traits, we raise an exception.
        """
        uuid = uuids.compute_node
        resp_mock = mock.Mock(headers={
            'x-openstack-request-id': uuids.request_id})
        self.ks_adap_mock.get.return_value = resp_mock

        for status_code in (400, 404, 503):
            resp_mock.status_code = status_code
            self.assertRaises(
                exception.ResourceProviderTraitRetrievalFailed,
                self.client.get_provider_traits, self.context, uuid)

            expected_url = '/resource_providers/' + uuid + '/traits'
            self.ks_adap_mock.get.assert_called_once_with(
                expected_url,
                global_request_id=self.context.global_id,
                **self.trait_api_kwargs)
            self.assertTrue(log_mock.called)
            self.assertEqual(uuids.request_id,
                             log_mock.call_args[0][1]['placement_req_id'])
            self.ks_adap_mock.get.reset_mock()
            log_mock.reset_mock()

    def test_get_provider_traits_placement_comm_error(self):
        """ksa ClientException raises through."""
        uuid = uuids.compute_node
        self.ks_adap_mock.get.side_effect = ks_exc.EndpointNotFound()
        self.assertRaises(ks_exc.ClientException,
                          self.client.get_provider_traits, self.context, uuid)
        expected_url = '/resource_providers/' + uuid + '/traits'
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url,
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)

    def test_ensure_traits(self):
        """Successful paths, various permutations of traits existing or needing
        to be created.
        """
        standard_traits = ['HW_NIC_OFFLOAD_UCS', 'HW_NIC_OFFLOAD_RDMA']
        custom_traits = ['CUSTOM_GOLD', 'CUSTOM_SILVER']
        all_traits = standard_traits + custom_traits

        get_mock = mock.Mock(status_code=200)
        self.ks_adap_mock.get.return_value = get_mock

        # Request all traits; custom traits need to be created
        get_mock.json.return_value = {'traits': standard_traits}
        self.client._ensure_traits(self.context, all_traits)
        self.ks_adap_mock.get.assert_called_once_with(
            '/traits?name=in:' + ','.join(all_traits),
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_has_calls(
            [mock.call('/traits/' + trait,
             global_request_id=self.context.global_id, json=None,
             **self.trait_api_kwargs)
             for trait in custom_traits], any_order=True)

        self.ks_adap_mock.reset_mock()

        # Request standard traits; no traits need to be created
        get_mock.json.return_value = {'traits': standard_traits}
        self.client._ensure_traits(self.context, standard_traits)
        self.ks_adap_mock.get.assert_called_once_with(
            '/traits?name=in:' + ','.join(standard_traits),
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_not_called()

        self.ks_adap_mock.reset_mock()

        # Request no traits - short circuit
        self.client._ensure_traits(self.context, None)
        self.client._ensure_traits(self.context, [])
        self.ks_adap_mock.get.assert_not_called()
        self.ks_adap_mock.put.assert_not_called()

    def test_ensure_traits_fail_retrieval(self):
        self.ks_adap_mock.get.return_value = mock.Mock(status_code=400)

        self.assertRaises(exception.TraitRetrievalFailed,
                          self.client._ensure_traits,
                          self.context, ['FOO'])

        self.ks_adap_mock.get.assert_called_once_with(
            '/traits?name=in:FOO',
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_not_called()

    def test_ensure_traits_fail_creation(self):
        get_mock = mock.Mock(status_code=200)
        get_mock.json.return_value = {'traits': []}
        self.ks_adap_mock.get.return_value = get_mock
        self.ks_adap_mock.put.return_value = fake_requests.FakeResponse(400)

        self.assertRaises(exception.TraitCreationFailed,
                          self.client._ensure_traits,
                          self.context, ['FOO'])

        self.ks_adap_mock.get.assert_called_once_with(
            '/traits?name=in:FOO',
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_called_once_with(
            '/traits/FOO',
            global_request_id=self.context.global_id, json=None,
            **self.trait_api_kwargs)

    def test_set_traits_for_provider(self):
        traits = ['HW_NIC_OFFLOAD_UCS', 'HW_NIC_OFFLOAD_RDMA']

        # Make _ensure_traits succeed without PUTting
        get_mock = mock.Mock(status_code=200)
        get_mock.json.return_value = {'traits': traits}
        self.ks_adap_mock.get.return_value = get_mock

        # Prime the provider tree cache
        self.client._provider_tree.new_root('rp', uuids.rp, generation=0)

        # Mock the /rp/{u}/traits PUT to succeed
        put_mock = mock.Mock(status_code=200)
        put_mock.json.return_value = {'traits': traits,
                                      'resource_provider_generation': 1}
        self.ks_adap_mock.put.return_value = put_mock

        # Invoke
        self.client.set_traits_for_provider(self.context, uuids.rp, traits)

        # Verify API calls
        self.ks_adap_mock.get.assert_called_once_with(
            '/traits?name=in:' + ','.join(traits),
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_called_once_with(
            '/resource_providers/%s/traits' % uuids.rp,
            json={'traits': traits, 'resource_provider_generation': 0},
            global_request_id=self.context.global_id,
            **self.trait_api_kwargs)

        # And ensure the provider tree cache was updated appropriately
        self.assertFalse(
            self.client._provider_tree.have_traits_changed(uuids.rp, traits))
        # Validate the generation
        self.assertEqual(
            1, self.client._provider_tree.data(uuids.rp).generation)

    def test_set_traits_for_provider_fail(self):
        traits = ['HW_NIC_OFFLOAD_UCS', 'HW_NIC_OFFLOAD_RDMA']
        get_mock = mock.Mock()
        self.ks_adap_mock.get.return_value = get_mock

        # Prime the provider tree cache
        self.client._provider_tree.new_root('rp', uuids.rp, generation=0)

        # _ensure_traits exception bubbles up
        get_mock.status_code = 400
        self.assertRaises(
            exception.TraitRetrievalFailed,
            self.client.set_traits_for_provider,
            self.context, uuids.rp, traits)
        self.ks_adap_mock.put.assert_not_called()

        get_mock.status_code = 200
        get_mock.json.return_value = {'traits': traits}

        # Conflict
        self.ks_adap_mock.put.return_value = mock.Mock(status_code=409)
        self.assertRaises(
            exception.ResourceProviderUpdateConflict,
            self.client.set_traits_for_provider,
            self.context, uuids.rp, traits)

        # Other error
        self.ks_adap_mock.put.return_value = mock.Mock(status_code=503)
        self.assertRaises(
            exception.ResourceProviderUpdateFailed,
            self.client.set_traits_for_provider,
            self.context, uuids.rp, traits)


class TestAssociations(SchedulerReportClientTestCase):
    def setUp(self):
        super(TestAssociations, self).setUp()

        self.mock_get_inv = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.client.report.SchedulerReportClient.'
            '_get_inventory')).mock
        self.inv = {
            'VCPU': {'total': 16},
            'MEMORY_MB': {'total': 1024},
            'DISK_GB': {'total': 10},
        }
        self.mock_get_inv.return_value = {
            'resource_provider_generation': 41,
            'inventories': self.inv,
        }

        self.mock_get_aggs = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.client.report.SchedulerReportClient.'
            '_get_provider_aggregates')).mock
        self.mock_get_aggs.return_value = report.AggInfo(
            aggregates=set([uuids.agg1]), generation=42)

        self.mock_get_traits = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.client.report.SchedulerReportClient.'
            'get_provider_traits')).mock
        self.mock_get_traits.return_value = report.TraitInfo(
            traits=set(['CUSTOM_GOLD']), generation=43)

        self.mock_get_sharing = self.useFixture(fixtures.MockPatch(
            'nova.scheduler.client.report.SchedulerReportClient.'
            '_get_sharing_providers')).mock

    def assert_getters_were_called(self, uuid, sharing=True):
        self.mock_get_inv.assert_called_once_with(self.context, uuid)
        self.mock_get_aggs.assert_called_once_with(self.context, uuid)
        self.mock_get_traits.assert_called_once_with(self.context, uuid)
        if sharing:
            self.mock_get_sharing.assert_called_once_with(
                self.context, self.mock_get_aggs.return_value[0])
        self.assertIn(uuid, self.client._association_refresh_time)
        self.assertFalse(
            self.client._provider_tree.has_inventory_changed(uuid, self.inv))
        self.assertTrue(
            self.client._provider_tree.in_aggregates(uuid, [uuids.agg1]))
        self.assertFalse(
            self.client._provider_tree.in_aggregates(uuid, [uuids.agg2]))
        self.assertTrue(
            self.client._provider_tree.has_traits(uuid, ['CUSTOM_GOLD']))
        self.assertFalse(
            self.client._provider_tree.has_traits(uuid, ['CUSTOM_SILVER']))
        self.assertEqual(43, self.client._provider_tree.data(uuid).generation)

    def assert_getters_not_called(self, timer_entry=None):
        self.mock_get_inv.assert_not_called()
        self.mock_get_aggs.assert_not_called()
        self.mock_get_traits.assert_not_called()
        self.mock_get_sharing.assert_not_called()
        if timer_entry is None:
            self.assertFalse(self.client._association_refresh_time)
        else:
            self.assertIn(timer_entry, self.client._association_refresh_time)

    def reset_getter_mocks(self):
        self.mock_get_inv.reset_mock()
        self.mock_get_aggs.reset_mock()
        self.mock_get_traits.reset_mock()
        self.mock_get_sharing.reset_mock()

    def test_refresh_associations_no_last(self):
        """Test that associations are refreshed when stale."""
        uuid = uuids.compute_node
        # Seed the provider tree so _refresh_associations finds the provider
        self.client._provider_tree.new_root('compute', uuid, generation=1)
        self.client._refresh_associations(self.context, uuid)
        self.assert_getters_were_called(uuid)

    def test_refresh_associations_no_refresh_sharing(self):
        """Test refresh_sharing=False."""
        uuid = uuids.compute_node
        # Seed the provider tree so _refresh_associations finds the provider
        self.client._provider_tree.new_root('compute', uuid, generation=1)
        self.client._refresh_associations(self.context, uuid,
                                          refresh_sharing=False)
        self.assert_getters_were_called(uuid, sharing=False)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_associations_stale')
    def test_refresh_associations_not_stale(self, mock_stale):
        """Test that refresh associations is not called when the map is
        not stale.
        """
        mock_stale.return_value = False
        uuid = uuids.compute_node
        self.client._refresh_associations(self.context, uuid)
        self.assert_getters_not_called()

    @mock.patch.object(report.LOG, 'debug')
    def test_refresh_associations_time(self, log_mock):
        """Test that refresh associations is called when the map is stale."""
        uuid = uuids.compute_node
        # Seed the provider tree so _refresh_associations finds the provider
        self.client._provider_tree.new_root('compute', uuid, generation=1)

        # Called a first time because association_refresh_time is empty.
        now = time.time()
        self.client._refresh_associations(self.context, uuid)
        self.assert_getters_were_called(uuid)
        log_mock.assert_has_calls([
            mock.call('Refreshing inventories for resource provider %s', uuid),
            mock.call('Updating ProviderTree inventory for provider %s from '
                      '_refresh_and_get_inventory using data: %s',
                      uuid, self.inv),
            mock.call('Refreshing aggregate associations for resource '
                      'provider %s, aggregates: %s', uuid, uuids.agg1),
            mock.call('Refreshing trait associations for resource '
                      'provider %s, traits: %s', uuid, 'CUSTOM_GOLD')
        ])

        # Clear call count.
        self.reset_getter_mocks()

        with mock.patch('time.time') as mock_future:
            # Not called a second time because not enough time has passed.
            mock_future.return_value = (now +
                CONF.compute.resource_provider_association_refresh / 2)
            self.client._refresh_associations(self.context, uuid)
            self.assert_getters_not_called(timer_entry=uuid)

            # Called because time has passed.
            mock_future.return_value = (now +
                CONF.compute.resource_provider_association_refresh + 1)
            self.client._refresh_associations(self.context, uuid)
            self.assert_getters_were_called(uuid)

    def test_refresh_associations_disabled(self):
        """Test that refresh associations can be disabled."""
        self.flags(resource_provider_association_refresh=0, group='compute')
        uuid = uuids.compute_node
        # Seed the provider tree so _refresh_associations finds the provider
        self.client._provider_tree.new_root('compute', uuid, generation=1)

        # Called a first time because association_refresh_time is empty.
        now = time.time()
        self.client._refresh_associations(self.context, uuid)
        self.assert_getters_were_called(uuid)

        # Clear call count.
        self.reset_getter_mocks()

        with mock.patch('time.time') as mock_future:
            # A lot of time passes
            mock_future.return_value = now + 10000000000000
            self.client._refresh_associations(self.context, uuid)
            self.assert_getters_not_called(timer_entry=uuid)

            self.reset_getter_mocks()

            # Forever passes
            mock_future.return_value = float('inf')
            self.client._refresh_associations(self.context, uuid)
            self.assert_getters_not_called(timer_entry=uuid)

            self.reset_getter_mocks()

            # Even if no time passes, clearing the counter triggers refresh
            mock_future.return_value = now
            del self.client._association_refresh_time[uuid]
            self.client._refresh_associations(self.context, uuid)
            self.assert_getters_were_called(uuid)


class TestAllocations(SchedulerReportClientTestCase):

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete_allocation_for_instance")
    @mock.patch("nova.objects.InstanceList.get_uuids_by_host_and_node")
    def test_delete_resource_provider_cascade(self, mock_by_host,
            mock_del_alloc, mock_delete):
        self.client._provider_tree.new_root(uuids.cn, uuids.cn, generation=1)
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake_host",
                hypervisor_hostname="fake_hostname", )
        mock_by_host.return_value = [uuids.inst1, uuids.inst2]
        resp_mock = mock.Mock(status_code=204)
        mock_delete.return_value = resp_mock
        self.client.delete_resource_provider(self.context, cn, cascade=True)
        mock_by_host.assert_called_once_with(
            self.context, cn.host, cn.hypervisor_hostname)
        self.assertEqual(2, mock_del_alloc.call_count)
        exp_url = "/resource_providers/%s" % uuids.cn
        mock_delete.assert_called_once_with(
            exp_url, global_request_id=self.context.global_id)
        self.assertFalse(self.client._provider_tree.exists(uuids.cn))

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete_allocation_for_instance")
    @mock.patch("nova.objects.InstanceList.get_uuids_by_host_and_node")
    def test_delete_resource_provider_no_cascade(self, mock_by_host,
            mock_del_alloc, mock_delete):
        self.client._provider_tree.new_root(uuids.cn, uuids.cn, generation=1)
        self.client._association_refresh_time[uuids.cn] = mock.Mock()
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake_host",
                hypervisor_hostname="fake_hostname", )
        mock_by_host.return_value = [uuids.inst1, uuids.inst2]
        resp_mock = mock.Mock(status_code=204)
        mock_delete.return_value = resp_mock
        self.client.delete_resource_provider(self.context, cn)
        mock_del_alloc.assert_not_called()
        exp_url = "/resource_providers/%s" % uuids.cn
        mock_delete.assert_called_once_with(
            exp_url, global_request_id=self.context.global_id)
        self.assertNotIn(uuids.cn, self.client._association_refresh_time)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete")
    @mock.patch('nova.scheduler.client.report.LOG')
    def test_delete_resource_provider_log_calls(self, mock_log, mock_delete):
        # First, check a successful call
        self.client._provider_tree.new_root(uuids.cn, uuids.cn, generation=1)
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake_host",
                hypervisor_hostname="fake_hostname", )
        resp_mock = fake_requests.FakeResponse(204)
        mock_delete.return_value = resp_mock
        self.client.delete_resource_provider(self.context, cn)
        # With a 204, only the info should be called
        self.assertEqual(1, mock_log.info.call_count)
        self.assertEqual(0, mock_log.warning.call_count)

        # Now check a 404 response
        mock_log.reset_mock()
        resp_mock.status_code = 404
        self.client.delete_resource_provider(self.context, cn)
        # With a 404, neither log message should be called
        self.assertEqual(0, mock_log.info.call_count)
        self.assertEqual(0, mock_log.warning.call_count)

        # Finally, check a 409 response
        mock_log.reset_mock()
        resp_mock.status_code = 409
        self.client.delete_resource_provider(self.context, cn)
        # With a 409, only the error should be called
        self.assertEqual(0, mock_log.info.call_count)
        self.assertEqual(1, mock_log.error.call_count)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.delete',
                new=mock.Mock(side_effect=ks_exc.EndpointNotFound()))
    def test_delete_resource_provider_placement_exception(self):
        """Ensure that a ksa exception in delete_resource_provider raises
        through.
        """
        self.client._provider_tree.new_root(uuids.cn, uuids.cn, generation=1)
        cn = objects.ComputeNode(uuid=uuids.cn, host="fake_host",
                hypervisor_hostname="fake_hostname", )
        self.assertRaises(
            ks_exc.ClientException,
            self.client.delete_resource_provider, self.context, cn)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_get_allocations_for_resource_provider(self, mock_get):
        mock_get.return_value = fake_requests.FakeResponse(
            200, content=jsonutils.dumps(
                {'allocations': 'fake', 'resource_provider_generation': 42}))
        ret = self.client.get_allocations_for_resource_provider(
            self.context, 'rpuuid')
        self.assertEqual('fake', ret.allocations)
        mock_get.assert_called_once_with(
            '/resource_providers/rpuuid/allocations',
            global_request_id=self.context.global_id)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_get_allocations_for_resource_provider_fail(self, mock_get):
        mock_get.return_value = fake_requests.FakeResponse(400, content="ouch")
        self.assertRaises(exception.ResourceProviderAllocationRetrievalFailed,
                          self.client.get_allocations_for_resource_provider,
                          self.context, 'rpuuid')
        mock_get.assert_called_once_with(
            '/resource_providers/rpuuid/allocations',
            global_request_id=self.context.global_id)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_get_allocs_for_consumer(self, mock_get):
        mock_get.return_value = fake_requests.FakeResponse(
            200, content=jsonutils.dumps({'foo': 'bar'}))
        ret = self.client.get_allocs_for_consumer(self.context, 'consumer')
        self.assertEqual({'foo': 'bar'}, ret)
        mock_get.assert_called_once_with(
            '/allocations/consumer', version='1.28',
            global_request_id=self.context.global_id)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_get_allocs_for_consumer_fail(self, mock_get):
        mock_get.return_value = fake_requests.FakeResponse(400, content='err')
        self.assertRaises(exception.ConsumerAllocationRetrievalFailed,
                          self.client.get_allocs_for_consumer,
                          self.context, 'consumer')
        mock_get.assert_called_once_with(
            '/allocations/consumer', version='1.28',
            global_request_id=self.context.global_id)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_get_allocs_for_consumer_safe_connect_fail(self, mock_get):
        mock_get.side_effect = ks_exc.EndpointNotFound()
        self.assertRaises(ks_exc.ClientException,
                          self.client.get_allocs_for_consumer,
                          self.context, 'consumer')
        mock_get.assert_called_once_with(
            '/allocations/consumer', version='1.28',
            global_request_id=self.context.global_id)

    def _test_remove_res_from_alloc(
            self, current_allocations, resources_to_remove,
            updated_allocations):

        with test.nested(
                mock.patch(
                    "nova.scheduler.client.report.SchedulerReportClient.get"),
                mock.patch(
                    "nova.scheduler.client.report.SchedulerReportClient.put")
        ) as (mock_get, mock_put):
            mock_get.return_value = fake_requests.FakeResponse(
                200, content=jsonutils.dumps(current_allocations))

            self.client.remove_resources_from_instance_allocation(
                self.context, uuids.consumer_uuid, resources_to_remove)

            mock_get.assert_called_once_with(
                '/allocations/%s' % uuids.consumer_uuid, version='1.28',
                global_request_id=self.context.global_id)
            mock_put.assert_called_once_with(
                '/allocations/%s' % uuids.consumer_uuid, updated_allocations,
                version='1.28', global_request_id=self.context.global_id)

    def test_remove_res_from_alloc(self):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 13,
                    "resources": {
                        'VCPU': 10,
                        'MEMORY_MB': 4096,
                    },
                },
                uuids.rp2: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                        'NET_BW_IGR_KILOBIT_PER_SEC': 300,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        resources_to_remove = {
            uuids.rp1: {
                'VCPU': 1
            },
            uuids.rp2: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 100,
                'NET_BW_IGR_KILOBIT_PER_SEC': 200,
            }
        }
        updated_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 13,
                    "resources": {
                        'VCPU': 9,
                        'MEMORY_MB': 4096,
                    },
                },
                uuids.rp2: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 100,
                        'NET_BW_IGR_KILOBIT_PER_SEC': 100,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }

        self._test_remove_res_from_alloc(
            current_allocations, resources_to_remove, updated_allocations)

    def test_remove_res_from_alloc_remove_rc_when_value_dropped_to_zero(self):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                        'NET_BW_IGR_KILOBIT_PER_SEC': 300,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        # this will remove all of NET_BW_EGR_KILOBIT_PER_SEC resources from
        # the allocation so the whole resource class will be removed
        resources_to_remove = {
            uuids.rp1: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                'NET_BW_IGR_KILOBIT_PER_SEC': 200,
            }
        }
        updated_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_IGR_KILOBIT_PER_SEC': 100,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }

        self._test_remove_res_from_alloc(
            current_allocations, resources_to_remove, updated_allocations)

    def test_remove_res_from_alloc_remove_rp_when_all_rc_removed(self):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                        'NET_BW_IGR_KILOBIT_PER_SEC': 300,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        resources_to_remove = {
            uuids.rp1: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                'NET_BW_IGR_KILOBIT_PER_SEC': 300,
            }
        }
        updated_allocations = {
            "allocations": {},
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }

        self._test_remove_res_from_alloc(
            current_allocations, resources_to_remove, updated_allocations)

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_remove_res_from_alloc_failed_to_get_alloc(
            self, mock_get):
        mock_get.side_effect = ks_exc.EndpointNotFound()
        resources_to_remove = {
            uuids.rp1: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                'NET_BW_IGR_KILOBIT_PER_SEC': 200,
            }
        }

        self.assertRaises(
            ks_exc.ClientException,
            self.client.remove_resources_from_instance_allocation,
            self.context, uuids.consumer_uuid, resources_to_remove)

    def test_remove_res_from_alloc_empty_alloc(self):
        resources_to_remove = {
            uuids.rp1: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                'NET_BW_IGR_KILOBIT_PER_SEC': 200,
            }
        }
        current_allocations = {
            "allocations": {},
            "consumer_generation": 0,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        ex = self.assertRaises(
            exception.AllocationUpdateFailed,
            self._test_remove_res_from_alloc, current_allocations,
            resources_to_remove, None)
        self.assertIn('The allocation is empty', six.text_type(ex))

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.put")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_remove_res_from_alloc_no_resource_to_remove(
            self, mock_get, mock_put):
        self.client.remove_resources_from_instance_allocation(
            self.context, uuids.consumer_uuid, {})

        mock_get.assert_not_called()
        mock_put.assert_not_called()

    def test_remove_res_from_alloc_missing_rc(self):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        resources_to_remove = {
            uuids.rp1: {
                'VCPU': 1,
            }
        }

        ex = self.assertRaises(
            exception.AllocationUpdateFailed, self._test_remove_res_from_alloc,
            current_allocations, resources_to_remove, None)
        self.assertIn(
            "Key 'VCPU' is missing from the allocation",
            six.text_type(ex))

    def test_remove_res_from_alloc_missing_rp(self):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        resources_to_remove = {
            uuids.other_rp: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 200,
            }
        }

        ex = self.assertRaises(
            exception.AllocationUpdateFailed, self._test_remove_res_from_alloc,
            current_allocations, resources_to_remove, None)
        self.assertIn(
            "Key '%s' is missing from the allocation" % uuids.other_rp,
            six.text_type(ex))

    def test_remove_res_from_alloc_not_enough_resource_to_remove(self):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        resources_to_remove = {
            uuids.rp1: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 400,
            }
        }

        ex = self.assertRaises(
            exception.AllocationUpdateFailed, self._test_remove_res_from_alloc,
            current_allocations, resources_to_remove, None)
        self.assertIn(
            'There are not enough allocated resources left on %s resource '
            'provider to remove 400 amount of NET_BW_EGR_KILOBIT_PER_SEC '
            'resources' %
            uuids.rp1,
            six.text_type(ex))

    @mock.patch('time.sleep', new=mock.Mock())
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.put")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_remove_res_from_alloc_retry_succeed(
            self, mock_get, mock_put):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        current_allocations_2 = copy.deepcopy(current_allocations)
        current_allocations_2['consumer_generation'] = 3
        resources_to_remove = {
            uuids.rp1: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 200,
            }
        }
        updated_allocations = {
            "allocations": {},
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        updated_allocations_2 = copy.deepcopy(updated_allocations)
        updated_allocations_2['consumer_generation'] = 3
        mock_get.side_effect = [
            fake_requests.FakeResponse(
                200, content=jsonutils.dumps(current_allocations)),
            fake_requests.FakeResponse(
                200, content=jsonutils.dumps(current_allocations_2))
        ]

        mock_put.side_effect = [
            fake_requests.FakeResponse(
                status_code=409,
                content=jsonutils.dumps(
                    {'errors': [{'code': 'placement.concurrent_update',
                                 'detail': ''}]})),
            fake_requests.FakeResponse(
                status_code=204)
        ]

        self.client.remove_resources_from_instance_allocation(
            self.context, uuids.consumer_uuid, resources_to_remove)

        self.assertEqual(
            [
                mock.call(
                    '/allocations/%s' % uuids.consumer_uuid, version='1.28',
                    global_request_id=self.context.global_id),
                mock.call(
                    '/allocations/%s' % uuids.consumer_uuid, version='1.28',
                    global_request_id=self.context.global_id)
            ],
            mock_get.mock_calls)

        self.assertEqual(
            [
                mock.call(
                    '/allocations/%s' % uuids.consumer_uuid,
                    updated_allocations, version='1.28',
                    global_request_id=self.context.global_id),
                mock.call(
                    '/allocations/%s' % uuids.consumer_uuid,
                    updated_allocations_2, version='1.28',
                    global_request_id=self.context.global_id),
            ],
            mock_put.mock_calls)

    @mock.patch('time.sleep', new=mock.Mock())
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.put")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient.get")
    def test_remove_res_from_alloc_run_out_of_retries(
            self, mock_get, mock_put):
        current_allocations = {
            "allocations": {
                uuids.rp1: {
                    "generation": 42,
                    "resources": {
                        'NET_BW_EGR_KILOBIT_PER_SEC': 200,
                    },
                },
            },
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }
        resources_to_remove = {
            uuids.rp1: {
                'NET_BW_EGR_KILOBIT_PER_SEC': 200,
            }
        }
        updated_allocations = {
            "allocations": {},
            "consumer_generation": 2,
            "project_id": uuids.project_id,
            "user_id": uuids.user_id,
        }

        get_rsp = fake_requests.FakeResponse(
            200, content=jsonutils.dumps(current_allocations))

        mock_get.side_effect = [get_rsp] * 4

        put_rsp = fake_requests.FakeResponse(
            status_code=409,
            content=jsonutils.dumps(
                    {'errors': [{'code': 'placement.concurrent_update',
                                 'detail': ''}]}))

        mock_put.side_effect = [put_rsp] * 4

        ex = self.assertRaises(
            exception.AllocationUpdateFailed,
            self.client.remove_resources_from_instance_allocation,
            self.context, uuids.consumer_uuid, resources_to_remove)
        self.assertIn(
            'due to multiple successive generation conflicts',
            six.text_type(ex))

        get_call = mock.call(
            '/allocations/%s' % uuids.consumer_uuid, version='1.28',
            global_request_id=self.context.global_id)

        mock_get.assert_has_calls([get_call] * 4)

        put_call = mock.call(
            '/allocations/%s' % uuids.consumer_uuid, updated_allocations,
            version='1.28', global_request_id=self.context.global_id)

        mock_put.assert_has_calls([put_call] * 4)


class TestResourceClass(SchedulerReportClientTestCase):
    def setUp(self):
        super(TestResourceClass, self).setUp()
        _put_patch = mock.patch(
            "nova.scheduler.client.report.SchedulerReportClient.put")
        self.addCleanup(_put_patch.stop)
        self.mock_put = _put_patch.start()

    def test_ensure_resource_classes(self):
        rcs = ['VCPU', 'CUSTOM_FOO', 'MEMORY_MB', 'CUSTOM_BAR']
        self.client._ensure_resource_classes(self.context, rcs)
        self.mock_put.assert_has_calls([
            mock.call('/resource_classes/%s' % rc, None, version='1.7',
                      global_request_id=self.context.global_id)
            for rc in ('CUSTOM_FOO', 'CUSTOM_BAR')
        ], any_order=True)

    def test_ensure_resource_classes_none(self):
        for empty in ([], (), set(), {}):
            self.client._ensure_resource_classes(self.context, empty)
            self.mock_put.assert_not_called()

    def test_ensure_resource_classes_put_fail(self):
        self.mock_put.return_value = fake_requests.FakeResponse(503)
        rcs = ['VCPU', 'MEMORY_MB', 'CUSTOM_BAD']
        self.assertRaises(
            exception.InvalidResourceClass,
            self.client._ensure_resource_classes, self.context, rcs)
        # Only called with the "bad" one
        self.mock_put.assert_called_once_with(
            '/resource_classes/CUSTOM_BAD', None, version='1.7',
            global_request_id=self.context.global_id)


class TestAggregateAddRemoveHost(SchedulerReportClientTestCase):
    """Unit tests for the methods of the report client which look up providers
    by name and add/remove host aggregates to providers. These methods do not
    access the SchedulerReportClient provider_tree attribute and are called
    from the nova API, not the nova compute manager/resource tracker.
    """
    def setUp(self):
        super(TestAggregateAddRemoveHost, self).setUp()
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.scheduler.client.report.'
                               'SchedulerReportClient.get')).mock
        self.mock_put = self.useFixture(
            fixtures.MockPatch('nova.scheduler.client.report.'
                               'SchedulerReportClient.put')).mock

    def test_get_provider_by_name_success(self):
        get_resp = mock.Mock()
        get_resp.status_code = 200
        get_resp.json.return_value = {
            "resource_providers": [
                mock.sentinel.expected,
            ]
        }
        self.mock_get.return_value = get_resp
        name = 'cn1'
        res = self.client.get_provider_by_name(self.context, name)

        exp_url = "/resource_providers?name=%s" % name
        self.mock_get.assert_called_once_with(
            exp_url, global_request_id=self.context.global_id)
        self.assertEqual(mock.sentinel.expected, res)

    @mock.patch.object(report.LOG, 'warning')
    def test_get_provider_by_name_multiple_results(self, mock_log):
        """Test that if we find multiple resource providers with the same name,
        that a ResourceProviderNotFound is raised (the reason being that >1
        resource provider with a name should never happen...)
        """
        get_resp = mock.Mock()
        get_resp.status_code = 200
        get_resp.json.return_value = {
            "resource_providers": [
                {'uuid': uuids.cn1a},
                {'uuid': uuids.cn1b},
            ]
        }
        self.mock_get.return_value = get_resp
        name = 'cn1'
        self.assertRaises(
            exception.ResourceProviderNotFound,
            self.client.get_provider_by_name, self.context, name)
        mock_log.assert_called_once()

    @mock.patch.object(report.LOG, 'warning')
    def test_get_provider_by_name_500(self, mock_log):
        get_resp = mock.Mock()
        get_resp.status_code = 500
        self.mock_get.return_value = get_resp
        name = 'cn1'
        self.assertRaises(
            exception.ResourceProviderNotFound,
            self.client.get_provider_by_name, self.context, name)
        mock_log.assert_called_once()

    @mock.patch.object(report.LOG, 'warning')
    def test_get_provider_by_name_404(self, mock_log):
        get_resp = mock.Mock()
        get_resp.status_code = 404
        self.mock_get.return_value = get_resp
        name = 'cn1'
        self.assertRaises(
            exception.ResourceProviderNotFound,
            self.client.get_provider_by_name, self.context, name)
        mock_log.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_add_host_success_no_existing(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        agg_uuid = uuids.agg1
        mock_get_aggs.return_value = report.AggInfo(aggregates=set([]),
                                                    generation=42)
        name = 'cn1'
        self.client.aggregate_add_host(self.context, agg_uuid, host_name=name)
        mock_set_aggs.assert_called_once_with(
            self.context, uuids.cn1, set([agg_uuid]), use_cache=False,
            generation=42)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name', new=mock.NonCallableMock())
    def test_aggregate_add_host_rp_uuid(self, mock_get_aggs, mock_set_aggs):
        mock_get_aggs.return_value = report.AggInfo(
            aggregates=set([]), generation=42)
        self.client.aggregate_add_host(
            self.context, uuids.agg1, rp_uuid=uuids.cn1)
        mock_set_aggs.assert_called_once_with(
            self.context, uuids.cn1, set([uuids.agg1]), use_cache=False,
            generation=42)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_add_host_success_already_existing(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        agg1_uuid = uuids.agg1
        agg2_uuid = uuids.agg2
        agg3_uuid = uuids.agg3
        mock_get_aggs.return_value = report.AggInfo(
            aggregates=set([agg1_uuid]), generation=42)
        name = 'cn1'
        self.client.aggregate_add_host(self.context, agg1_uuid, host_name=name)
        mock_set_aggs.assert_not_called()
        mock_get_aggs.reset_mock()
        mock_set_aggs.reset_mock()
        mock_get_aggs.return_value = report.AggInfo(
            aggregates=set([agg1_uuid, agg3_uuid]), generation=43)
        self.client.aggregate_add_host(self.context, agg2_uuid, host_name=name)
        mock_set_aggs.assert_called_once_with(
            self.context, uuids.cn1, set([agg1_uuid, agg2_uuid, agg3_uuid]),
            use_cache=False, generation=43)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name',
                side_effect=exception.PlacementAPIConnectFailure)
    def test_aggregate_add_host_no_placement(self, mock_get_by_name):
        """Tests that PlacementAPIConnectFailure will be raised up from
        aggregate_add_host if get_provider_by_name raises that error.
        """
        name = 'cn1'
        agg_uuid = uuids.agg1
        self.assertRaises(
            exception.PlacementAPIConnectFailure,
            self.client.aggregate_add_host, self.context, agg_uuid,
            host_name=name)
        self.mock_get.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_add_host_retry_success(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        gens = (42, 43, 44)
        mock_get_aggs.side_effect = (
            report.AggInfo(aggregates=set([]), generation=gen) for gen in gens)
        mock_set_aggs.side_effect = (
            exception.ResourceProviderUpdateConflict(
                uuid='uuid', generation=42, error='error'),
            exception.ResourceProviderUpdateConflict(
                uuid='uuid', generation=43, error='error'),
            None,
        )
        self.client.aggregate_add_host(self.context, uuids.agg1,
                                       host_name='cn1')
        mock_set_aggs.assert_has_calls([mock.call(
            self.context, uuids.cn1, set([uuids.agg1]), use_cache=False,
            generation=gen) for gen in gens])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_add_host_retry_raises(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        gens = (42, 43, 44, 45)
        mock_get_aggs.side_effect = (
            report.AggInfo(aggregates=set([]), generation=gen) for gen in gens)
        mock_set_aggs.side_effect = (
            exception.ResourceProviderUpdateConflict(
                uuid='uuid', generation=gen, error='error') for gen in gens)
        self.assertRaises(
            exception.ResourceProviderUpdateConflict,
            self.client.aggregate_add_host, self.context, uuids.agg1,
            host_name='cn1')
        mock_set_aggs.assert_has_calls([mock.call(
            self.context, uuids.cn1, set([uuids.agg1]), use_cache=False,
            generation=gen) for gen in gens])

    def test_aggregate_add_host_no_host_name_or_rp_uuid(self):
        self.assertRaises(
            ValueError,
            self.client.aggregate_add_host, self.context, uuids.agg1)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name',
                side_effect=exception.PlacementAPIConnectFailure)
    def test_aggregate_remove_host_no_placement(self, mock_get_by_name):
        """Tests that PlacementAPIConnectFailure will be raised up from
        aggregate_remove_host if get_provider_by_name raises that error.
        """
        name = 'cn1'
        agg_uuid = uuids.agg1
        self.assertRaises(
            exception.PlacementAPIConnectFailure,
            self.client.aggregate_remove_host, self.context, agg_uuid, name)
        self.mock_get.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_remove_host_success_already_existing(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        agg_uuid = uuids.agg1
        mock_get_aggs.return_value = report.AggInfo(aggregates=set([agg_uuid]),
                                                    generation=42)
        name = 'cn1'
        self.client.aggregate_remove_host(self.context, agg_uuid, name)
        mock_set_aggs.assert_called_once_with(
            self.context, uuids.cn1, set([]), use_cache=False, generation=42)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_remove_host_success_no_existing(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        agg1_uuid = uuids.agg1
        agg2_uuid = uuids.agg2
        agg3_uuid = uuids.agg3
        mock_get_aggs.return_value = report.AggInfo(aggregates=set([]),
                                                    generation=42)
        name = 'cn1'
        self.client.aggregate_remove_host(self.context, agg2_uuid, name)
        mock_set_aggs.assert_not_called()
        mock_get_aggs.reset_mock()
        mock_set_aggs.reset_mock()
        mock_get_aggs.return_value = report.AggInfo(
            aggregates=set([agg1_uuid, agg2_uuid, agg3_uuid]), generation=43)
        self.client.aggregate_remove_host(self.context, agg2_uuid, name)
        mock_set_aggs.assert_called_once_with(
            self.context, uuids.cn1, set([agg1_uuid, agg3_uuid]),
            use_cache=False, generation=43)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_remove_host_retry_success(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        gens = (42, 43, 44)
        mock_get_aggs.side_effect = (
            report.AggInfo(aggregates=set([uuids.agg1]), generation=gen)
            for gen in gens)
        mock_set_aggs.side_effect = (
            exception.ResourceProviderUpdateConflict(
                uuid='uuid', generation=42, error='error'),
            exception.ResourceProviderUpdateConflict(
                uuid='uuid', generation=43, error='error'),
            None,
        )
        self.client.aggregate_remove_host(self.context, uuids.agg1, 'cn1')
        mock_set_aggs.assert_has_calls([mock.call(
            self.context, uuids.cn1, set([]), use_cache=False,
            generation=gen) for gen in gens])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_by_name')
    def test_aggregate_remove_host_retry_raises(
            self, mock_get_by_name, mock_get_aggs, mock_set_aggs):
        mock_get_by_name.return_value = {
            'uuid': uuids.cn1,
            'generation': 1,
        }
        gens = (42, 43, 44, 45)
        mock_get_aggs.side_effect = (
            report.AggInfo(aggregates=set([uuids.agg1]), generation=gen)
            for gen in gens)
        mock_set_aggs.side_effect = (
            exception.ResourceProviderUpdateConflict(
                uuid='uuid', generation=gen, error='error') for gen in gens)
        self.assertRaises(
            exception.ResourceProviderUpdateConflict,
            self.client.aggregate_remove_host, self.context, uuids.agg1, 'cn1')
        mock_set_aggs.assert_has_calls([mock.call(
            self.context, uuids.cn1, set([]), use_cache=False,
            generation=gen) for gen in gens])


class TestUsages(SchedulerReportClientTestCase):
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def test_get_usages_counts_for_quota_fail(self, mock_get):
        # First call with project fails
        mock_get.return_value = fake_requests.FakeResponse(500, content='err')
        self.assertRaises(exception.UsagesRetrievalFailed,
                          self.client.get_usages_counts_for_quota,
                          self.context, 'fake-project')
        mock_get.assert_called_once_with(
            '/usages?project_id=fake-project', version='1.9',
            global_request_id=self.context.global_id)
        # Second call with project + user fails
        mock_get.reset_mock()
        fake_good_response = fake_requests.FakeResponse(
            200, content=jsonutils.dumps(
                {'usages': {orc.VCPU: 2,
                            orc.MEMORY_MB: 512}}))
        mock_get.side_effect = [fake_good_response,
                                fake_requests.FakeResponse(500, content='err')]
        self.assertRaises(exception.UsagesRetrievalFailed,
                          self.client.get_usages_counts_for_quota,
                          self.context, 'fake-project', user_id='fake-user')
        self.assertEqual(2, mock_get.call_count)
        call1 = mock.call(
            '/usages?project_id=fake-project', version='1.9',
            global_request_id=self.context.global_id)
        call2 = mock.call(
            '/usages?project_id=fake-project&user_id=fake-user', version='1.9',
            global_request_id=self.context.global_id)
        mock_get.assert_has_calls([call1, call2])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def test_get_usages_counts_for_quota_retries(self, mock_get):
        # Two attempts have a ConnectFailure and the third succeeds
        fake_project_response = fake_requests.FakeResponse(
            200, content=jsonutils.dumps(
                {'usages': {orc.VCPU: 2,
                            orc.MEMORY_MB: 512}}))
        mock_get.side_effect = [ks_exc.ConnectFailure,
                                ks_exc.ConnectFailure,
                                fake_project_response]
        counts = self.client.get_usages_counts_for_quota(self.context,
                                                         'fake-project')
        self.assertEqual(3, mock_get.call_count)
        expected = {'project': {'cores': 2, 'ram': 512}}
        self.assertDictEqual(expected, counts)

        # Project query succeeds, first project + user query has a
        # ConnectFailure, second project + user query succeeds
        mock_get.reset_mock()
        fake_user_response = fake_requests.FakeResponse(
            200, content=jsonutils.dumps(
                {'usages': {orc.VCPU: 1,
                            orc.MEMORY_MB: 256}}))
        mock_get.side_effect = [fake_project_response,
                                ks_exc.ConnectFailure,
                                fake_user_response]
        counts = self.client.get_usages_counts_for_quota(
            self.context, 'fake-project', user_id='fake-user')
        self.assertEqual(3, mock_get.call_count)
        expected['user'] = {'cores': 1, 'ram': 256}
        self.assertDictEqual(expected, counts)

        # Three attempts in a row have a ConnectFailure
        mock_get.reset_mock()
        mock_get.side_effect = [ks_exc.ConnectFailure] * 4
        self.assertRaises(ks_exc.ConnectFailure,
                          self.client.get_usages_counts_for_quota,
                          self.context, 'fake-project')

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def test_get_usages_counts_default_zero(self, mock_get):
        # A project and user are not yet consuming any resources.
        fake_response = fake_requests.FakeResponse(
            200, content=jsonutils.dumps({'usages': {}}))
        mock_get.side_effect = [fake_response, fake_response]

        counts = self.client.get_usages_counts_for_quota(
            self.context, 'fake-project', user_id='fake-user')

        self.assertEqual(2, mock_get.call_count)
        expected = {'project': {'cores': 0, 'ram': 0},
                    'user': {'cores': 0, 'ram': 0}}
        self.assertDictEqual(expected, counts)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def test_get_usages_count_with_pcpu(self, mock_get):
        fake_responses = fake_requests.FakeResponse(
            200,
            content=jsonutils.dumps({'usages': {orc.VCPU: 2, orc.PCPU: 2}}))
        mock_get.return_value = fake_responses
        counts = self.client.get_usages_counts_for_quota(
            self.context, 'fake-project', user_id='fake-user')
        self.assertEqual(2, mock_get.call_count)
        expected = {'project': {'cores': 4, 'ram': 0},
                    'user': {'cores': 4, 'ram': 0}}
        self.assertDictEqual(expected, counts)

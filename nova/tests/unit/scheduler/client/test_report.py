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

import time

import fixtures
from keystoneauth1 import exceptions as ks_exc
import mock
from oslo_serialization import jsonutils
from six.moves.urllib import parse

import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova import rc_fields as fields
from nova.scheduler.client import report
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests.unit import fake_requests
from nova.tests import uuidsentinel as uuids

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
    @mock.patch('keystoneauth1.loading.load_session_from_conf_options')
    @mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
    def test_constructor(self, load_auth_mock, load_sess_mock):
        client = report.SchedulerReportClient()

        load_auth_mock.assert_called_once_with(CONF, 'placement')
        load_sess_mock.assert_called_once_with(CONF, 'placement',
                                              auth=load_auth_mock.return_value)
        self.assertEqual(['internal', 'public'], client._client.interface)
        self.assertEqual({'accept': 'application/json'},
                         client._client.additional_headers)

    @mock.patch('keystoneauth1.loading.load_session_from_conf_options')
    @mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
    def test_constructor_admin_interface(self, load_auth_mock, load_sess_mock):
        self.flags(valid_interfaces='admin', group='placement')
        client = report.SchedulerReportClient()

        load_auth_mock.assert_called_once_with(CONF, 'placement')
        load_sess_mock.assert_called_once_with(CONF, 'placement',
                                              auth=load_auth_mock.return_value)
        self.assertEqual(['admin'], client._client.interface)
        self.assertEqual({'accept': 'application/json'},
                         client._client.additional_headers)


class SchedulerReportClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerReportClientTestCase, self).setUp()
        self.context = context.get_admin_context()
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

        with test.nested(
                mock.patch('keystoneauth1.adapter.Adapter',
                           return_value=self.ks_adap_mock),
                mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
        ):
            self.client = report.SchedulerReportClient()

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
        resp = self.client.put_allocations(self.context, rp_uuid,
                                           consumer_uuid, data,
                                           mock.sentinel.project_id,
                                           mock.sentinel.user_id)
        self.assertTrue(resp)
        mock_put.assert_called_once_with(
            expected_url, mock.ANY, version='1.8',
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
        resp = self.client.put_allocations(self.context, rp_uuid,
                                           consumer_uuid, data,
                                           mock.sentinel.project_id,
                                           mock.sentinel.user_id)
        self.assertFalse(resp)
        mock_put.assert_called_once_with(
            expected_url, mock.ANY, version='1.8',
            global_request_id=self.context.global_id)
        log_msg = mock_warn.call_args[0][0]
        self.assertIn("Unable to submit allocation for instance", log_msg)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations_retries_conflict(self, mock_put):

        failed = mock.MagicMock()
        failed.status_code = 409
        failed.text = "concurrently updated"

        succeeded = mock.MagicMock()
        succeeded.status_code = 204

        mock_put.side_effect = (failed, succeeded)

        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        resp = self.client.put_allocations(self.context, rp_uuid,
                                           consumer_uuid, data,
                                           mock.sentinel.project_id,
                                           mock.sentinel.user_id)
        self.assertTrue(resp)
        mock_put.assert_has_calls([
            mock.call(expected_url, mock.ANY, version='1.8',
                      global_request_id=self.context.global_id)] * 2)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put')
    def test_put_allocations_retry_gives_up(self, mock_put):

        failed = mock.MagicMock()
        failed.status_code = 409
        failed.text = "concurrently updated"

        mock_put.return_value = failed

        rp_uuid = mock.sentinel.rp
        consumer_uuid = mock.sentinel.consumer
        data = {"MEMORY_MB": 1024}
        expected_url = "/allocations/%s" % consumer_uuid
        resp = self.client.put_allocations(self.context, rp_uuid,
                                           consumer_uuid, data,
                                           mock.sentinel.project_id,
                                           mock.sentinel.user_id)
        self.assertFalse(resp)
        mock_put.assert_has_calls([
            mock.call(expected_url, mock.ANY, version='1.8',
            global_request_id=self.context.global_id)] * 3)

    def test_claim_resources_success_with_old_version(self):
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {},  # build instance, not move
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': [
                {
                    'resource_provider': {
                        'uuid': uuids.cn1
                    },
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
            ],
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(
            self.context, consumer_uuid, alloc_req, project_id, user_id)

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations': {
                alloc['resource_provider']['uuid']: {
                    'resources': alloc['resources']
                }
                for alloc in alloc_req['allocations']
            }
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=expected_payload,
            headers={'X-Openstack-Request-Id': self.context.global_id})

        self.assertTrue(res)

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
            headers={'X-Openstack-Request-Id': self.context.global_id})

        self.assertTrue(res)

    def test_claim_resources_success_move_operation_no_shared(self):
        """Tests that when a move operation is detected (existing allocations
        for the same instance UUID) that we end up constructing an appropriate
        allocation that contains the original resources on the source host
        as well as the resources on the destination host.
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {
                uuids.source: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            },
        }

        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': {
                uuids.destination: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024
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
        # New allocation should include resources claimed on both the source
        # and destination hosts
        expected_payload = {
            'allocations': {
                uuids.source: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024
                    }
                },
                uuids.destination: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024
                    }
                },
            },
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=mock.ANY,
            headers={'X-Openstack-Request-Id': self.context.global_id})
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_move_operation_with_shared(self):
        """Tests that when a move operation is detected (existing allocations
        for the same instance UUID) that we end up constructing an appropriate
        allocation that contains the original resources on the source host
        as well as the resources on the destination host but that when a shared
        storage provider is claimed against in both the original allocation as
        well as the new allocation request, we don't double that allocation
        resource request up.
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
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
            },
        }

        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        alloc_req = {
            'allocations': {
                uuids.destination: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 100,
                    }
                },
            }
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.12')

        expected_url = "/allocations/%s" % consumer_uuid
        # New allocation should include resources claimed on both the source
        # and destination hosts but not have a doubled-up request for the disk
        # resources on the shared provider
        expected_payload = {
            'allocations': {
                uuids.source: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 100
                    }
                },
                uuids.destination: {
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024
                    }
                },
            },
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=mock.ANY,
            headers={'X-Openstack-Request-Id': self.context.global_id})
        # We have to pull the allocations from the json body from the
        # mock call_args to validate it separately otherwise hash seed
        # issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_resize_to_same_host_no_shared(self):
        """Tests that when a resize to the same host operation is detected
        (existing allocations for the same instance UUID and same resource
        provider) that we end up constructing an appropriate allocation that
        contains the original resources on the source host as well as the
        resources on the destination host, which in this case are the same.
        """
        get_current_allocations_resp_mock = mock.Mock(status_code=200)
        get_current_allocations_resp_mock.json.return_value = {
            'allocations': {
                uuids.same_host: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                        'DISK_GB': 20
                    },
                },
            },
        }

        self.ks_adap_mock.get.return_value = get_current_allocations_resp_mock
        put_allocations_resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = put_allocations_resp_mock
        consumer_uuid = uuids.consumer_uuid
        # This is the resize-up allocation where VCPU, MEMORY_MB and DISK_GB
        # are all being increased but on the same host. We also throw a custom
        # resource class in the new allocation to make sure it's not lost and
        # that we don't have a KeyError when merging the allocations.
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
        }

        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.claim_resources(self.context, consumer_uuid,
                                          alloc_req, project_id, user_id,
                                          allocation_request_version='1.12')

        expected_url = "/allocations/%s" % consumer_uuid
        # New allocation should include doubled resources claimed on the same
        # host.
        expected_payload = {
            'allocations': {
                uuids.same_host: {
                    'resources': {
                        'VCPU': 3,
                        'MEMORY_MB': 3072,
                        'DISK_GB': 60,
                        'CUSTOM_FOO': 1
                    }
                },
            },
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=mock.ANY,
            headers={'X-Openstack-Request-Id': self.context.global_id})
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_success_resize_to_same_host_with_shared(self):
        """Tests that when a resize to the same host operation is detected
        (existing allocations for the same instance UUID and same resource
        provider) that we end up constructing an appropriate allocation that
        contains the original resources on the source host as well as the
        resources on the destination host, which in this case are the same.
        This test adds the fun wrinkle of throwing a shared storage provider
        in the mix when doing resize to the same host.
        """
        get_current_allocations_resp_mock = mock.Mock(status_code=200)
        get_current_allocations_resp_mock.json.return_value = {
            'allocations': {
                uuids.same_host: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024
                    },
                },
                uuids.shared_storage: {
                    'resource_provider_generation': 42,
                    'resources': {
                        'DISK_GB': 20,
                    },
                },
            },
        }

        self.ks_adap_mock.get.return_value = get_current_allocations_resp_mock
        put_allocations_resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = put_allocations_resp_mock
        consumer_uuid = uuids.consumer_uuid
        # This is the resize-up allocation where VCPU, MEMORY_MB and DISK_GB
        # are all being increased but DISK_GB is on a shared storage provider.
        alloc_req = {
            'allocations': {
                uuids.same_host: {
                    'resources': {
                        'VCPU': 2,
                        'MEMORY_MB': 2048
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 40,
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
        # New allocation should include doubled resources claimed on the same
        # host.
        expected_payload = {
            'allocations': {
                uuids.same_host: {
                    'resources': {
                        'VCPU': 3,
                        'MEMORY_MB': 3072
                    }
                },
                uuids.shared_storage: {
                    'resources': {
                        'DISK_GB': 60
                    }
                },
            },
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=mock.ANY,
            headers={'X-Openstack-Request-Id': self.context.global_id})
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        self.assertEqual(expected_payload, actual_payload)

        self.assertTrue(res)

    def test_claim_resources_fail_retry_success(self):
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
            'allocations': {},  # build instance, not move
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mocks = [
            mock.Mock(
                status_code=409,
                text='Inventory changed while attempting to allocate: '
                     'Another thread concurrently updated the data. '
                     'Please retry your update'),
            mock.Mock(status_code=204),
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
                                          allocation_request_version='1.12')

        expected_url = "/allocations/%s" % consumer_uuid
        expected_payload = {
            'allocations':
                {rp_uuid: res
                    for rp_uuid, res in alloc_req['allocations'].items()}
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        # We should have exactly two calls to the placement API that look
        # identical since we're retrying the same HTTP request
        expected_calls = [
            mock.call(expected_url, microversion='1.12', json=expected_payload,
                      headers={'X-Openstack-Request-Id':
                               self.context.global_id})] * 2
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
        resp_mock = mock.Mock(status_code=409, text='not cool')
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
            'allocations':
                {rp_uuid: res
                    for rp_uuid, res in alloc_req['allocations'].items()}
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.12', json=expected_payload,
            headers={'X-Openstack-Request-Id': self.context.global_id})

        self.assertFalse(res)
        self.assertTrue(mock_log.called)

    def test_remove_provider_from_inst_alloc_no_shared(self):
        """Tests that the method which manipulates an existing doubled-up
        allocation for a move operation to remove the source host results in
        sending placement the proper payload to PUT
        /allocations/{consumer_uuid} call.
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
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
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.remove_provider_from_instance_allocation(
            self.context, consumer_uuid, uuids.source, user_id, project_id,
            mock.Mock())

        expected_url = "/allocations/%s" % consumer_uuid
        # New allocations should only include the destination...
        expected_payload = {
            'allocations': [
                {
                    'resource_provider': {
                        'uuid': uuids.destination,
                    },
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            ],
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        sort_by_uuid = lambda x: x['resource_provider']['uuid']
        expected_allocations = sorted(expected_payload['allocations'],
                                      key=sort_by_uuid)
        actual_allocations = sorted(actual_payload['allocations'],
                                    key=sort_by_uuid)
        self.assertEqual(expected_allocations, actual_allocations)
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.10', json=mock.ANY,
            headers={'X-Openstack-Request-Id': self.context.global_id})

        self.assertTrue(res)

    def test_remove_provider_from_inst_alloc_with_shared(self):
        """Tests that the method which manipulates an existing doubled-up
        allocation with DISK_GB being consumed from a shared storage provider
        for a move operation to remove the source host results in sending
        placement the proper payload to PUT /allocations/{consumer_uuid}
        call.
        """
        get_resp_mock = mock.Mock(status_code=200)
        get_resp_mock.json.return_value = {
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
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        resp_mock = mock.Mock(status_code=204)
        self.ks_adap_mock.put.return_value = resp_mock
        consumer_uuid = uuids.consumer_uuid
        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.remove_provider_from_instance_allocation(
            self.context, consumer_uuid, uuids.source, user_id, project_id,
            mock.Mock())

        expected_url = "/allocations/%s" % consumer_uuid
        # New allocations should only include the destination...
        expected_payload = {
            'allocations': [
                {
                    'resource_provider': {
                        'uuid': uuids.shared_storage,
                    },
                    'resources': {
                        'DISK_GB': 100,
                    },
                },
                {
                    'resource_provider': {
                        'uuid': uuids.destination,
                    },
                    'resources': {
                        'VCPU': 1,
                        'MEMORY_MB': 1024,
                    },
                },
            ],
        }
        expected_payload['project_id'] = project_id
        expected_payload['user_id'] = user_id
        # We have to pull the json body from the mock call_args to validate
        # it separately otherwise hash seed issues get in the way.
        actual_payload = self.ks_adap_mock.put.call_args[1]['json']
        sort_by_uuid = lambda x: x['resource_provider']['uuid']
        expected_allocations = sorted(expected_payload['allocations'],
                                      key=sort_by_uuid)
        actual_allocations = sorted(actual_payload['allocations'],
                                    key=sort_by_uuid)
        self.assertEqual(expected_allocations, actual_allocations)
        self.ks_adap_mock.put.assert_called_once_with(
            expected_url, microversion='1.10', json=mock.ANY,
            headers={'X-Openstack-Request-Id': self.context.global_id})

        self.assertTrue(res)

    def test_remove_provider_from_inst_alloc_no_source(self):
        """Tests that if remove_provider_from_instance_allocation() fails to
        find any allocations for the source host, it just returns True and
        does not attempt to rewrite the allocation for the consumer.
        """
        get_resp_mock = mock.Mock(status_code=200)
        # Act like the allocations already did not include the source host for
        # some reason
        get_resp_mock.json.return_value = {
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
        }
        self.ks_adap_mock.get.return_value = get_resp_mock
        consumer_uuid = uuids.consumer_uuid
        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.remove_provider_from_instance_allocation(
            self.context, consumer_uuid, uuids.source, user_id, project_id,
            mock.Mock())

        self.ks_adap_mock.get.assert_called()
        self.ks_adap_mock.put.assert_not_called()

        self.assertTrue(res)

    def test_remove_provider_from_inst_alloc_fail_get_allocs(self):
        """Tests that we gracefully exit with False from
        remove_provider_from_instance_allocation() if the call to get the
        existing allocations fails for some reason
        """
        get_resp_mock = mock.Mock(status_code=500)
        self.ks_adap_mock.get.return_value = get_resp_mock
        consumer_uuid = uuids.consumer_uuid
        project_id = uuids.project_id
        user_id = uuids.user_id
        res = self.client.remove_provider_from_instance_allocation(
            self.context, consumer_uuid, uuids.source, user_id, project_id,
            mock.Mock())

        self.ks_adap_mock.get.assert_called()
        self.ks_adap_mock.put.assert_not_called()

        self.assertFalse(res)


class TestSetAndClearAllocations(SchedulerReportClientTestCase):

    def setUp(self):
        super(TestSetAndClearAllocations, self).setUp()
        # We want to reuse the mock throughout the class, but with
        # different return values.
        self.mock_post = mock.patch(
            'nova.scheduler.client.report.SchedulerReportClient.post').start()
        self.addCleanup(self.mock_post.stop)
        self.mock_post.return_value.status_code = 204
        self.rp_uuid = mock.sentinel.rp
        self.consumer_uuid = mock.sentinel.consumer
        self.data = {"MEMORY_MB": 1024}
        self.project_id = mock.sentinel.project_id
        self.user_id = mock.sentinel.user_id
        self.expected_url = '/allocations'

    def test_url_microversion(self):
        expected_microversion = '1.13'

        resp = self.client.set_and_clear_allocations(
            self.context, self.rp_uuid, self.consumer_uuid, self.data,
            self.project_id, self.user_id)

        self.assertTrue(resp)
        self.mock_post.assert_called_once_with(
            self.expected_url, mock.ANY,
            version=expected_microversion,
            global_request_id=self.context.global_id)

    def test_payload_no_clear(self):
        expected_payload = {
            self.consumer_uuid: {
                'user_id': self.user_id,
                'project_id': self.project_id,
                'allocations': {
                    self.rp_uuid: {
                        'resources': {
                            'MEMORY_MB': 1024
                        }
                    }
                }
            }
        }

        resp = self.client.set_and_clear_allocations(
            self.context, self.rp_uuid, self.consumer_uuid, self.data,
            self.project_id, self.user_id)

        self.assertTrue(resp)
        args, kwargs = self.mock_post.call_args
        payload = args[1]
        self.assertEqual(expected_payload, payload)

    def test_payload_with_clear(self):
        expected_payload = {
            self.consumer_uuid: {
                'user_id': self.user_id,
                'project_id': self.project_id,
                'allocations': {
                    self.rp_uuid: {
                        'resources': {
                            'MEMORY_MB': 1024
                        }
                    }
                }
            },
            mock.sentinel.migration_uuid: {
                'user_id': self.user_id,
                'project_id': self.project_id,
                'allocations': {}
            }
        }

        resp = self.client.set_and_clear_allocations(
            self.context, self.rp_uuid, self.consumer_uuid, self.data,
            self.project_id, self.user_id,
            consumer_to_clear=mock.sentinel.migration_uuid)

        self.assertTrue(resp)
        args, kwargs = self.mock_post.call_args
        payload = args[1]
        self.assertEqual(expected_payload, payload)

    @mock.patch('time.sleep')
    def test_409_concurrent_update(self, mock_sleep):
        self.mock_post.return_value.status_code = 409
        self.mock_post.return_value.text = 'concurrently updated'

        resp = self.client.set_and_clear_allocations(
            self.context, self.rp_uuid, self.consumer_uuid, self.data,
            self.project_id, self.user_id,
            consumer_to_clear=mock.sentinel.migration_uuid)

        self.assertFalse(resp)
        # Post was attempted four times.
        self.assertEqual(4, self.mock_post.call_count)

    @mock.patch('nova.scheduler.client.report.LOG.warning')
    def test_not_409_failure(self, mock_log):
        error_message = 'placement not there'
        self.mock_post.return_value.status_code = 503
        self.mock_post.return_value.text = error_message

        resp = self.client.set_and_clear_allocations(
            self.context, self.rp_uuid, self.consumer_uuid, self.data,
            self.project_id, self.user_id,
            consumer_to_clear=mock.sentinel.migration_uuid)

        self.assertFalse(resp)
        args, kwargs = mock_log.call_args
        log_message = args[0]
        log_args = args[1]
        self.assertIn('Unable to post allocations', log_message)
        self.assertEqual(error_message, log_args['text'])


class TestProviderOperations(SchedulerReportClientTestCase):
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_traits')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_sharing_providers')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_providers_in_tree')
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

        self.client._ensure_resource_provider(self.context, uuids.compute_node)

        get_rpt_mock.assert_called_once_with(self.context, uuids.compute_node)
        self.assertTrue(self.client._provider_tree.exists(uuids.compute_node))
        get_agg_mock.assert_called_once_with(self.context, uuids.compute_node)
        self.assertTrue(
            self.client._provider_tree.in_aggregates(uuids.compute_node,
                                                     [uuids.agg1]))
        self.assertFalse(
            self.client._provider_tree.in_aggregates(uuids.compute_node,
                                                     [uuids.agg2]))
        get_trait_mock.assert_called_once_with(self.context,
                                               uuids.compute_node)
        self.assertTrue(
            self.client._provider_tree.has_traits(uuids.compute_node,
                                                  ['CUSTOM_GOLD']))
        self.assertFalse(
            self.client._provider_tree.has_traits(uuids.compute_node,
                                                  ['CUSTOM_SILVER']))
        get_shr_mock.assert_called_once_with(self.context, set([uuids.agg1]))
        self.assertEqual(
            43,
            self.client._provider_tree.data(uuids.compute_node).generation)
        self.assertFalse(create_rp_mock.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_providers_in_tree')
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
                '_get_providers_in_tree')
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
                '_get_providers_in_tree')
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
                '_refresh_associations', new=mock.Mock())
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_providers_in_tree')
    def test_ensure_resource_provider_tree(self, get_rpt_mock, create_rp_mock):
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

        # At this point we should get all the providers.
        self.assertEqual(
            set([uuids.root, uuids.child1, uuids.child2, uuids.grandchild]),
            set(self.client._provider_tree.get_provider_uuids()))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_providers_in_tree')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_and_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_refresh_associations')
    def test_ensure_resource_provider_refresh_fetch(self, mock_ref_assoc,
                                                    mock_ref_inv, mock_gpit):
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
        mock_ref_inv.assert_has_calls([mock.call(self.context, uuid)
                                       for uuid in tree_uuids])
        mock_ref_assoc.assert_has_calls(
            [mock.call(self.context, uuid, force=True)
             for uuid in tree_uuids])
        self.assertEqual(tree_uuids,
                         set(self.client._provider_tree.get_provider_uuids()))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_providers_in_tree')
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
        resources = scheduler_utils.ResourceRequest.from_extra_specs({
            'resources:VCPU': '1',
            'resources:MEMORY_MB': '1024',
            'trait:HW_CPU_X86_AVX': 'required',
            'trait:CUSTOM_TRAIT1': 'required',
            'trait:CUSTOM_TRAIT2': 'preferred',
            'trait:CUSTOM_TRAIT3': 'forbidden',
            'trait:CUSTOM_TRAIT4': 'forbidden',
            'resources1:DISK_GB': '30',
            'trait1:STORAGE_DISK_SSD': 'required',
            'resources2:VGPU': '2',
            'trait2:HW_GPU_RESOLUTION_W2560H1600': 'required',
            'trait2:HW_GPU_API_VULKAN': 'required',
            'resources3:SRIOV_NET_VF': '1',
            'resources3:CUSTOM_NET_EGRESS_BYTES_SEC': '125000',
            'group_policy': 'isolate',
            # These are ignored because misspelled, bad value, etc.
            'resources02:CUSTOM_WIDGET': '123',
            'trait:HW_NIC_OFFLOAD_LRO': 'preferred',
            'group_policy3': 'none',
        })
        resources.get_request_group(None).member_of = [
            ('agg1', 'agg2', 'agg3'), ('agg1', 'agg2')]
        expected_path = '/allocation_candidates'
        expected_query = [
            ('group_policy', 'isolate'),
            ('limit', '1000'),
            ('member_of', 'in:agg1,agg2'),
            ('member_of', 'in:agg1,agg2,agg3'),
            ('required', 'CUSTOM_TRAIT1,HW_CPU_X86_AVX,!CUSTOM_TRAIT3,'
                         '!CUSTOM_TRAIT4'),
            ('required1', 'STORAGE_DISK_SSD'),
            ('required2', 'HW_GPU_API_VULKAN,HW_GPU_RESOLUTION_W2560H1600'),
            ('resources', 'MEMORY_MB:1024,VCPU:1'),
            ('resources1', 'DISK_GB:30'),
            ('resources2', 'VGPU:2'),
            ('resources3', 'CUSTOM_NET_EGRESS_BYTES_SEC:125000,SRIOV_NET_VF:1')
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
            expected_url, microversion='1.25',
            headers={'X-Openstack-Request-Id': self.context.global_id})
        self.assertEqual(mock.sentinel.alloc_reqs, alloc_reqs)
        self.assertEqual(mock.sentinel.p_sums, p_sums)

    def test_get_ac_no_trait_bogus_group_policy_custom_limit(self):
        self.flags(max_placement_results=42, group='scheduler')
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'allocation_requests': mock.sentinel.alloc_reqs,
            'provider_summaries': mock.sentinel.p_sums,
        }
        resources = scheduler_utils.ResourceRequest.from_extra_specs({
            'resources:VCPU': '1',
            'resources:MEMORY_MB': '1024',
            'resources1:DISK_GB': '30',
            'group_policy': 'bogus',
        })
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
            expected_url, microversion='1.25',
            headers={'X-Openstack-Request-Id': self.context.global_id})
        self.assertEqual(mock.sentinel.p_sums, p_sums)

    def test_get_allocation_candidates_not_found(self):
        # Ensure _get_resource_provider() just returns None when the placement
        # API doesn't find a resource provider matching a UUID
        resp_mock = mock.Mock(status_code=404)
        self.ks_adap_mock.get.return_value = resp_mock
        expected_path = '/allocation_candidates'
        expected_query = {'resources': ['MEMORY_MB:1024'],
                          'limit': ['100']}

        # Make sure we're also honoring the configured limit
        self.flags(max_placement_results=100, group='scheduler')

        resources = scheduler_utils.ResourceRequest.from_extra_specs(
            {'resources:MEMORY_MB': '1024'})

        res = self.client.get_allocation_candidates(self.context, resources)

        self.ks_adap_mock.get.assert_called_once_with(
            mock.ANY, microversion='1.25',
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            headers={'X-Openstack-Request-Id': self.context.global_id})
        # A 503 Service Unavailable should trigger an error log that
        # includes the placement request id
        self.assertTrue(logging_mock.called)
        self.assertEqual(uuids.request_id,
                         logging_mock.call_args[0][1]['placement_req_id'])

    def test_get_providers_in_tree(self):
        # Ensure _get_providers_in_tree() returns a list of resource
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

        result = self.client._get_providers_in_tree(self.context, root)

        expected_url = '/resource_providers?in_tree=' + root
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.14',
            headers={'X-Openstack-Request-Id': self.context.global_id})
        self.assertEqual(rpjson, result)

    @mock.patch.object(report.LOG, 'error')
    def test_get_providers_in_tree_error(self, logging_mock):
        # Ensure _get_providers_in_tree() logs an error and raises if the
        # placement API call doesn't respond 200
        resp_mock = mock.Mock(status_code=503)
        self.ks_adap_mock.get.return_value = resp_mock
        self.ks_adap_mock.get.return_value.headers = {
            'x-openstack-request-id': 'req-' + uuids.request_id}

        uuid = uuids.compute_node
        self.assertRaises(exception.ResourceProviderRetrievalFailed,
                          self.client._get_providers_in_tree, self.context,
                          uuid)

        expected_url = '/resource_providers?in_tree=' + uuid
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url, microversion='1.14',
            headers={'X-Openstack-Request-Id': self.context.global_id})
        # A 503 Service Unavailable should trigger an error log that includes
        # the placement request id
        self.assertTrue(logging_mock.called)
        self.assertEqual('req-' + uuids.request_id,
                         logging_mock.call_args[0][1]['placement_req_id'])

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
            headers={'X-Openstack-Request-Id': self.context.global_id})

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
            headers={'X-Openstack-Request-Id': self.context.global_id})

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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            url, json=[], microversion=None, headers={})

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
                headers={'X-Openstack-Request-Id': 'gri'}, microversion=None)
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
                headers={})

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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
            headers={'X-Openstack-Request-Id': self.context.global_id})
        # Cache was updated
        ptree_data = self.client._provider_tree.data(uuids.rp)
        self.assertEqual(set(), ptree_data.aggregates)
        self.assertEqual(5, ptree_data.generation)


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
            headers={'X-Openstack-Request-Id': self.context.global_id})
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
                headers={'X-Openstack-Request-Id': self.context.global_id})
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

        result, gen = self.client._get_provider_traits(self.context, uuid)

        expected_url = '/resource_providers/' + uuid + '/traits'
        self.ks_adap_mock.get.assert_called_once_with(
            expected_url,
            headers={'X-Openstack-Request-Id': self.context.global_id},
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
                self.client._get_provider_traits, self.context, uuid)

            expected_url = '/resource_providers/' + uuid + '/traits'
            self.ks_adap_mock.get.assert_called_once_with(
                expected_url,
                headers={'X-Openstack-Request-Id': self.context.global_id},
                **self.trait_api_kwargs)
            self.assertTrue(log_mock.called)
            self.assertEqual(uuids.request_id,
                             log_mock.call_args[0][1]['placement_req_id'])
            self.ks_adap_mock.get.reset_mock()
            log_mock.reset_mock()

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
            headers={'X-Openstack-Request-Id': self.context.global_id},
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_has_calls(
            [mock.call('/traits/' + trait,
            headers={'X-Openstack-Request-Id': self.context.global_id},
            **self.trait_api_kwargs)
             for trait in custom_traits], any_order=True)

        self.ks_adap_mock.reset_mock()

        # Request standard traits; no traits need to be created
        get_mock.json.return_value = {'traits': standard_traits}
        self.client._ensure_traits(self.context, standard_traits)
        self.ks_adap_mock.get.assert_called_once_with(
            '/traits?name=in:' + ','.join(standard_traits),
            headers={'X-Openstack-Request-Id': self.context.global_id},
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
            headers={'X-Openstack-Request-Id': self.context.global_id},
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
            headers={'X-Openstack-Request-Id': self.context.global_id},
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_called_once_with(
            '/traits/FOO',
            headers={'X-Openstack-Request-Id': self.context.global_id},
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
            headers={'X-Openstack-Request-Id': self.context.global_id},
            **self.trait_api_kwargs)
        self.ks_adap_mock.put.assert_called_once_with(
            '/resource_providers/%s/traits' % uuids.rp,
            json={'traits': traits, 'resource_provider_generation': 0},
            headers={'X-Openstack-Request-Id': self.context.global_id},
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
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_traits')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_sharing_providers')
    def test_refresh_associations_no_last(self, mock_shr_get, mock_trait_get,
                                          mock_agg_get):
        """Test that associations are refreshed when stale."""
        uuid = uuids.compute_node
        # Seed the provider tree so _refresh_associations finds the provider
        self.client._provider_tree.new_root('compute', uuid, generation=1)
        mock_agg_get.return_value = report.AggInfo(
            aggregates=set([uuids.agg1]), generation=42)
        mock_trait_get.return_value = report.TraitInfo(
            traits=set(['CUSTOM_GOLD']), generation=43)
        self.client._refresh_associations(self.context, uuid)
        mock_agg_get.assert_called_once_with(self.context, uuid)
        mock_trait_get.assert_called_once_with(self.context, uuid)
        mock_shr_get.assert_called_once_with(
            self.context, mock_agg_get.return_value[0])
        self.assertIn(uuid, self.client._association_refresh_time)
        self.assertTrue(
            self.client._provider_tree.in_aggregates(uuid, [uuids.agg1]))
        self.assertFalse(
            self.client._provider_tree.in_aggregates(uuid, [uuids.agg2]))
        self.assertTrue(
            self.client._provider_tree.has_traits(uuid, ['CUSTOM_GOLD']))
        self.assertFalse(
            self.client._provider_tree.has_traits(uuid, ['CUSTOM_SILVER']))
        self.assertEqual(43, self.client._provider_tree.data(uuid).generation)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_traits')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_sharing_providers')
    def test_refresh_associations_no_refresh_sharing(self, mock_shr_get,
                                                     mock_trait_get,
                                                     mock_agg_get):
        """Test refresh_sharing=False."""
        uuid = uuids.compute_node
        # Seed the provider tree so _refresh_associations finds the provider
        self.client._provider_tree.new_root('compute', uuid, generation=1)
        mock_agg_get.return_value = report.AggInfo(
            aggregates=set([uuids.agg1]), generation=42)
        mock_trait_get.return_value = report.TraitInfo(
            traits=set(['CUSTOM_GOLD']), generation=43)
        self.client._refresh_associations(self.context, uuid,
                                          refresh_sharing=False)
        mock_agg_get.assert_called_once_with(self.context, uuid)
        mock_trait_get.assert_called_once_with(self.context, uuid)
        mock_shr_get.assert_not_called()
        self.assertIn(uuid, self.client._association_refresh_time)
        self.assertTrue(
            self.client._provider_tree.in_aggregates(uuid, [uuids.agg1]))
        self.assertFalse(
            self.client._provider_tree.in_aggregates(uuid, [uuids.agg2]))
        self.assertTrue(
            self.client._provider_tree.has_traits(uuid, ['CUSTOM_GOLD']))
        self.assertFalse(
            self.client._provider_tree.has_traits(uuid, ['CUSTOM_SILVER']))
        self.assertEqual(43, self.client._provider_tree.data(uuid).generation)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_traits')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_sharing_providers')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_associations_stale')
    def test_refresh_associations_not_stale(self, mock_stale, mock_shr_get,
                                            mock_trait_get, mock_agg_get):
        """Test that refresh associations is not called when the map is
        not stale.
        """
        mock_stale.return_value = False
        uuid = uuids.compute_node
        self.client._refresh_associations(self.context, uuid)
        mock_agg_get.assert_not_called()
        mock_trait_get.assert_not_called()
        mock_shr_get.assert_not_called()
        self.assertFalse(self.client._association_refresh_time)

    @mock.patch.object(report.LOG, 'debug')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_traits')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_sharing_providers')
    def test_refresh_associations_time(self, mock_shr_get, mock_trait_get,
                                       mock_agg_get, log_mock):
        """Test that refresh associations is called when the map is stale."""
        uuid = uuids.compute_node
        # Seed the provider tree so _refresh_associations finds the provider
        self.client._provider_tree.new_root('compute', uuid, generation=1)
        mock_agg_get.return_value = report.AggInfo(aggregates=set([]),
                                                   generation=42)
        mock_trait_get.return_value = report.TraitInfo(traits=set([]),
                                                       generation=43)
        mock_shr_get.return_value = []

        # Called a first time because association_refresh_time is empty.
        now = time.time()
        self.client._refresh_associations(self.context, uuid)
        mock_agg_get.assert_called_once_with(self.context, uuid)
        mock_trait_get.assert_called_once_with(self.context, uuid)
        mock_shr_get.assert_called_once_with(self.context, set())
        log_mock.assert_has_calls([
            mock.call('Refreshing aggregate associations for resource '
                      'provider %s, aggregates: %s', uuid, 'None'),
            mock.call('Refreshing trait associations for resource '
                      'provider %s, traits: %s', uuid, 'None')
        ])
        self.assertIn(uuid, self.client._association_refresh_time)

        # Clear call count.
        mock_agg_get.reset_mock()
        mock_trait_get.reset_mock()
        mock_shr_get.reset_mock()

        with mock.patch('time.time') as mock_future:
            # Not called a second time because not enough time has passed.
            mock_future.return_value = (now +
                CONF.compute.resource_provider_association_refresh / 2)
            self.client._refresh_associations(self.context, uuid)
            mock_agg_get.assert_not_called()
            mock_trait_get.assert_not_called()
            mock_shr_get.assert_not_called()

            # Called because time has passed.
            mock_future.return_value = (now +
                CONF.compute.resource_provider_association_refresh + 1)
            self.client._refresh_associations(self.context, uuid)
            mock_agg_get.assert_called_once_with(self.context, uuid)
            mock_trait_get.assert_called_once_with(self.context, uuid)
            mock_shr_get.assert_called_once_with(self.context, set())


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
                '_update_inventory')
    def test_update_compute_node(self, mock_ui, mock_erp):
        cn = self.compute_node
        self.client.update_compute_node(self.context, cn)
        mock_erp.assert_called_once_with(self.context, cn.uuid,
                                         cn.hypervisor_hostname)
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
            self.context,
            cn.uuid,
            expected_inv_data,
        )

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    def test_update_compute_node_no_inv(self, mock_ui, mock_erp):
        """Ensure that if there are no inventory records, we still call
        _update_inventory().
        """
        cn = self.compute_node
        cn.vcpus = 0
        cn.memory_mb = 0
        cn.local_gb = 0
        self.client.update_compute_node(self.context, cn)
        mock_erp.assert_called_once_with(self.context, cn.uuid,
                                         cn.hypervisor_hostname)
        mock_ui.assert_called_once_with(self.context, cn.uuid, {})

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory_initial_empty(self, mock_put, mock_get):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = self.compute_node
        # Make sure the resource provider exists for preventing to call the API
        self._init_provider_tree(resources_override={})

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
            self.context, compute_node.uuid, inv_data
        )
        self.assertTrue(result)

        exp_url = '/resource_providers/%s/inventories' % uuid
        mock_get.assert_called_once_with(
            exp_url, global_request_id=self.context.global_id)
        # Updated with the new inventory from the PUT call
        self._validate_provider(uuid, generation=44)
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
                    'reserved': 0,  # reserved_host_disk_mb is 0 by default
                    'min_unit': 1,
                    'max_unit': compute_node.local_gb,
                    'step_size': 1,
                    'allocation_ratio': compute_node.disk_allocation_ratio,
                },
            }
        }
        mock_put.assert_called_once_with(
            exp_url, expected, version='1.26',
            global_request_id=self.context.global_id)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory(self, mock_put, mock_get):
        self.flags(reserved_host_disk_mb=1000)

        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = self.compute_node
        # Make sure the resource provider exists for preventing to call the API
        self._init_provider_tree()
        new_vcpus_total = 240

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
                'VCPU': {'total': new_vcpus_total},
                'MEMORY_MB': {'total': 1024},
                'DISK_GB': {'total': 10},
            }
        }

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        # Make a change to trigger the update...
        inv_data['VCPU']['total'] = new_vcpus_total
        result = self.client._update_inventory_attempt(
            self.context, compute_node.uuid, inv_data
        )
        self.assertTrue(result)

        exp_url = '/resource_providers/%s/inventories' % uuid
        mock_get.assert_called_once_with(
            exp_url, global_request_id=self.context.global_id)
        # Updated with the new inventory from the PUT call
        self._validate_provider(uuid, generation=44)
        expected = {
            # Called with the newly-found generation from the existing
            # inventory
            'resource_provider_generation': 43,
            'inventories': {
                'VCPU': {
                    'total': new_vcpus_total,
                    'reserved': 0,
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
                    'reserved': 1,  # this is ceil for 1000MB
                    'min_unit': 1,
                    'max_unit': compute_node.local_gb,
                    'step_size': 1,
                    'allocation_ratio': compute_node.disk_allocation_ratio,
                },
            }
        }
        mock_put.assert_called_once_with(
            exp_url, expected, version='1.26',
            global_request_id=self.context.global_id)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_inventory_no_update(self, mock_put, mock_get):
        """Simulate situation where scheduler client is first starting up and
        ends up loading information from the placement API via a GET against
        the resource provider's inventory but has no local cached inventory
        information for a resource provider.
        """
        uuid = uuids.compute_node
        compute_node = self.compute_node
        # Make sure the resource provider exists for preventing to call the API
        self._init_provider_tree(generation_override=42, resources_override={})
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
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': compute_node.local_gb,
                    'step_size': 1,
                    'allocation_ratio': compute_node.disk_allocation_ratio,
                },
            }
        }
        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            self.context, compute_node.uuid, inv_data
        )
        self.assertTrue(result)
        exp_url = '/resource_providers/%s/inventories' % uuid
        mock_get.assert_called_once_with(
            exp_url, global_request_id=self.context.global_id)
        # No update so put should not be called
        self.assertFalse(mock_put.called)
        # Make sure we updated the generation from the inventory records
        self._validate_provider(uuid, generation=43)

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
        # Make sure the resource provider exists for preventing to call the API
        self.client._provider_tree.new_root(
            compute_node.hypervisor_hostname,
            compute_node.uuid,
            generation=42,
        )

        mock_get.return_value = {
            'resource_provider_generation': 42,
            'inventories': {},
        }
        mock_put.return_value.status_code = 409
        mock_put.return_value.text = 'Does not match inventory in use'
        mock_put.return_value.headers = {'x-openstack-request-id':
                                         uuids.request_id}

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            self.context, compute_node.uuid, inv_data
        )
        self.assertFalse(result)

        # Invalidated the cache
        self.assertFalse(self.client._provider_tree.exists(uuid))
        # Refreshed our resource provider
        mock_ensure.assert_called_once_with(self.context, uuid)
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
        # Make sure the resource provider exists for preventing to call the API
        self.client._provider_tree.new_root(
            compute_node.hypervisor_hostname,
            compute_node.uuid,
            generation=42,
        )

        mock_get.return_value = {
            'resource_provider_generation': 42,
            'inventories': {},
        }
        mock_put.return_value.status_code = 409
        mock_put.return_value.text = (
            "update conflict: Inventory for VCPU on "
            "resource provider 123 in use"
        )

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        self.assertRaises(
            exception.InventoryInUse,
            self.client._update_inventory_attempt,
            self.context,
            compute_node.uuid,
            inv_data,
        )

        # Did NOT invalidate the cache
        self.assertTrue(self.client._provider_tree.exists(uuid))

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
        # Make sure the resource provider exists for preventing to call the API
        self.client._provider_tree.new_root(
            compute_node.hypervisor_hostname,
            compute_node.uuid,
            generation=42,
        )

        mock_get.return_value = {
            'resource_provider_generation': 42,
            'inventories': {},
        }
        mock_put.return_value.status_code = 234
        mock_put.return_value.headers = {'x-openstack-request-id':
                                         uuids.request_id}

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            self.context, compute_node.uuid, inv_data
        )
        self.assertFalse(result)

        # No cache invalidation
        self.assertTrue(self.client._provider_tree.exists(uuid))

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
        # Make sure the resource provider exists for preventing to call the API
        self.client._provider_tree.new_root(
            compute_node.hypervisor_hostname,
            compute_node.uuid,
            generation=42,
        )

        mock_get.return_value = {
            'resource_provider_generation': 42,
            'inventories': {},
        }
        mock_put.return_value = fake_requests.FakeResponse(
            400, headers={'x-openstack-request-id': uuids.request_id})

        inv_data = report._compute_node_to_inventory_dict(compute_node)
        result = self.client._update_inventory_attempt(
            self.context, compute_node.uuid, inv_data
        )
        self.assertFalse(result)

        # No cache invalidation
        self.assertTrue(self.client._provider_tree.exists(uuid))
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
        cn = self.compute_node
        mock_update.side_effect = (False, True)

        self.client._provider_tree.new_root(
            cn.hypervisor_hostname,
            cn.uuid,
            generation=42,
        )
        result = self.client._update_inventory(
            self.context, cn.uuid, mock.sentinel.inv_data
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
        cn = self.compute_node
        mock_update.side_effect = (False, False, False)

        self.client._provider_tree.new_root(
            cn.hypervisor_hostname,
            cn.uuid,
            generation=42,
        )
        result = self.client._update_inventory(
            self.context, cn.uuid, mock.sentinel.inv_data
        )
        self.assertFalse(result)

        # Slept three times
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1), mock.call(1)])

        # Three attempts to update
        mock_update.assert_has_calls([
            mock.call(self.context, cn.uuid, mock.sentinel.inv_data),
            mock.call(self.context, cn.uuid, mock.sentinel.inv_data),
            mock.call(self.context, cn.uuid, mock.sentinel.inv_data),
        ])

        # Slept three times
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1), mock.call(1)])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_classes')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_set_inventory_for_provider_no_custom(self, mock_erp, mock_erc,
                                                  mock_upd):
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
            self.context,
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            inv_data,
        )
        mock_erp.assert_called_once_with(
            self.context,
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            parent_provider_uuid=None,
        )
        # No custom resource classes to ensure...
        mock_erc.assert_called_once_with(self.context,
                                         set(['VCPU', 'MEMORY_MB', 'DISK_GB']))
        mock_upd.assert_called_once_with(
            self.context,
            mock.sentinel.rp_uuid,
            inv_data,
        )

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_classes')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_set_inventory_for_provider_no_inv(self, mock_erp, mock_erc,
                                               mock_upd):
        """Tests that passing empty set of inventory records triggers a delete
        of inventory for the provider.
        """
        inv_data = {}
        self.client.set_inventory_for_provider(
            self.context,
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            inv_data,
        )
        mock_erp.assert_called_once_with(
            self.context,
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            parent_provider_uuid=None,
        )
        mock_erc.assert_called_once_with(self.context, set())
        mock_upd.assert_called_once_with(
            self.context, mock.sentinel.rp_uuid, {})

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_classes')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_set_inventory_for_provider_with_custom(self, mock_erp, mock_erc,
                                                    mock_upd):
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
            self.context,
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            inv_data,
        )
        mock_erp.assert_called_once_with(
            self.context,
            mock.sentinel.rp_uuid,
            mock.sentinel.rp_name,
            parent_provider_uuid=None,
        )
        mock_erc.assert_called_once_with(
            self.context,
            set(['VCPU', 'MEMORY_MB', 'DISK_GB', 'CUSTOM_IRON_SILVER']))
        mock_upd.assert_called_once_with(
            self.context,
            mock.sentinel.rp_uuid,
            inv_data,
        )

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_classes', new=mock.Mock())
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_set_inventory_for_provider_with_parent(self, mock_erp):
        """Ensure parent UUID is sent through."""
        self.client.set_inventory_for_provider(
            self.context, uuids.child, 'junior', {},
            parent_provider_uuid=uuids.parent)
        mock_erp.assert_called_once_with(
            self.context, uuids.child, 'junior',
            parent_provider_uuid=uuids.parent)


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
                                  vcpus=2,
                                  extra_specs={}))
        result = report._instance_to_allocations_dict(inst)
        expected = {
            'MEMORY_MB': 1024,
            'VCPU': 2,
            'DISK_GB': 111,
        }
        self.assertEqual(expected, result)

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_instance_to_allocations_dict_overrides(self, mock_vbi):
        """Test that resource overrides in an instance's flavor extra_specs
        are reported to placement.
        """

        mock_vbi.return_value = False
        specs = {
            'resources:CUSTOM_DAN': '123',
            'resources:%s' % fields.ResourceClass.VCPU: '4',
            'resources:NOTATHING': '456',
            'resources:NOTEVENANUMBER': 'catfood',
            'resources:': '7',
            'resources:ferret:weasel': 'smelly',
            'foo': 'bar',
        }
        inst = objects.Instance(
            uuid=uuids.inst,
            flavor=objects.Flavor(root_gb=10,
                                  swap=1023,
                                  ephemeral_gb=100,
                                  memory_mb=1024,
                                  vcpus=2,
                                  extra_specs=specs))
        result = report._instance_to_allocations_dict(inst)
        expected = {
            'MEMORY_MB': 1024,
            'VCPU': 4,
            'DISK_GB': 111,
            'CUSTOM_DAN': 123,
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
                                  vcpus=2,
                                  extra_specs={}))
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
                                  vcpus=2,
                                  extra_specs={}))
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
        inst = objects.Instance(uuid=uuids.inst, project_id=uuids.project,
                                user_id=uuids.user)
        mock_get.return_value.json.return_value = {'allocations': {}}
        expected = {
            'allocations': [
                {'resource_provider': {'uuid': cn.uuid},
                 'resources': mock_a.return_value}],
            'project_id': inst.project_id,
            'user_id': inst.user_id,
        }
        self.client.update_instance_allocation(self.context, cn, inst, 1)
        mock_put.assert_called_once_with(
            '/allocations/%s' % inst.uuid,
            expected, version='1.8',
            global_request_id=self.context.global_id)
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
        self.client.update_instance_allocation(self.context, cn, inst, 1)
        self.assertFalse(mock_put.called)
        mock_get.assert_called_once_with(
            '/allocations/%s' % inst.uuid, version='1.28',
            global_request_id=self.context.global_id)

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
        inst = objects.Instance(uuid=uuids.inst, project_id=uuids.project,
                                user_id=uuids.user)
        mock_put.return_value = fake_requests.FakeResponse(400)
        self.client.update_instance_allocation(self.context, cn, inst, 1)
        self.assertTrue(mock_warn.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete')
    def test_update_instance_allocation_delete(self, mock_delete):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        self.client.update_instance_allocation(self.context, cn, inst, -1)
        mock_delete.assert_called_once_with(
            '/allocations/%s' % inst.uuid,
            global_request_id=self.context.global_id)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete')
    @mock.patch.object(report.LOG, 'warning')
    def test_update_instance_allocation_delete_failed(self, mock_warn,
                                                      mock_delete):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        mock_delete.return_value = fake_requests.FakeResponse(400)
        self.client.update_instance_allocation(self.context, cn, inst, -1)
        self.assertTrue(mock_warn.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'delete')
    @mock.patch('nova.scheduler.client.report.LOG')
    def test_delete_allocation_for_instance_ignore_404(self, mock_log,
                                                       mock_delete):
        """Tests that we don't log a warning on a 404 response when trying to
        delete an allocation record.
        """
        mock_delete.return_value = fake_requests.FakeResponse(404)
        self.client.delete_allocation_for_instance(self.context, uuids.rp_uuid)
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
        self.client._provider_tree.new_root(uuids.cn, uuids.cn, generation=1)
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
        mock_delete.assert_called_once_with(
            exp_url, global_request_id=self.context.global_id)
        self.assertFalse(self.client._provider_tree.exists(uuids.cn))

    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete")
    @mock.patch("nova.scheduler.client.report.SchedulerReportClient."
                "delete_allocation_for_instance")
    @mock.patch("nova.objects.InstanceList.get_by_host_and_node")
    def test_delete_resource_provider_no_cascade(self, mock_by_host,
            mock_del_alloc, mock_delete):
        self.client._provider_tree.new_root(uuids.cn, uuids.cn, generation=1)
        self.client._association_refresh_time[uuids.cn] = mock.Mock()
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
        res = self.client._get_provider_by_name(self.context, name)

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
            self.client._get_provider_by_name, self.context, name)
        mock_log.assert_called_once()

    @mock.patch.object(report.LOG, 'warning')
    def test_get_provider_by_name_500(self, mock_log):
        get_resp = mock.Mock()
        get_resp.status_code = 500
        self.mock_get.return_value = get_resp
        name = 'cn1'
        self.assertRaises(
            exception.ResourceProviderNotFound,
            self.client._get_provider_by_name, self.context, name)
        mock_log.assert_called_once()

    @mock.patch.object(report.LOG, 'warning')
    def test_get_provider_by_name_404(self, mock_log):
        get_resp = mock.Mock()
        get_resp.status_code = 404
        self.mock_get.return_value = get_resp
        name = 'cn1'
        self.assertRaises(
            exception.ResourceProviderNotFound,
            self.client._get_provider_by_name, self.context, name)
        mock_log.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_by_name')
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
        self.client.aggregate_add_host(self.context, agg_uuid, name)
        mock_set_aggs.assert_called_once_with(
            self.context, uuids.cn1, set([agg_uuid]), use_cache=False,
            generation=42)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_by_name')
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
        self.client.aggregate_add_host(self.context, agg1_uuid, name)
        mock_set_aggs.assert_not_called()
        mock_get_aggs.reset_mock()
        mock_set_aggs.reset_mock()
        mock_get_aggs.return_value = report.AggInfo(
            aggregates=set([agg1_uuid, agg3_uuid]), generation=43)
        self.client.aggregate_add_host(self.context, agg2_uuid, name)
        mock_set_aggs.assert_called_once_with(
            self.context, uuids.cn1, set([agg1_uuid, agg2_uuid, agg3_uuid]),
            use_cache=False, generation=43)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_by_name')
    def test_aggregate_add_host_no_placement(self, mock_get_by_name):
        """In Rocky, we allow nova-api to not be able to communicate with
        placement, so the @safe_connect decorator will return None. Check that
        an appropriate exception is raised back to the nova-api code in this
        case.
        """
        mock_get_by_name.return_value = None  # emulate @safe_connect...
        name = 'cn1'
        agg_uuid = uuids.agg1
        self.assertRaises(
            exception.PlacementAPIConnectFailure,
            self.client.aggregate_add_host, self.context, agg_uuid, name)
        self.mock_get.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_by_name')
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
        self.client.aggregate_add_host(self.context, uuids.agg1, 'cn1')
        mock_set_aggs.assert_has_calls([mock.call(
            self.context, uuids.cn1, set([uuids.agg1]), use_cache=False,
            generation=gen) for gen in gens])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'set_aggregates_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_aggregates')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_by_name')
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
            self.client.aggregate_add_host, self.context, uuids.agg1, 'cn1')
        mock_set_aggs.assert_has_calls([mock.call(
            self.context, uuids.cn1, set([uuids.agg1]), use_cache=False,
            generation=gen) for gen in gens])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_provider_by_name')
    def test_aggregate_remove_host_no_placement(self, mock_get_by_name):
        """In Rocky, we allow nova-api to not be able to communicate with
        placement, so the @safe_connect decorator will return None. Check that
        an appropriate exception is raised back to the nova-api code in this
        case.
        """
        mock_get_by_name.return_value = None  # emulate @safe_connect...
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
                '_get_provider_by_name')
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
                '_get_provider_by_name')
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
                '_get_provider_by_name')
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
                '_get_provider_by_name')
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

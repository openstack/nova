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

import mock

from keystoneauth1 import exceptions as ks_exc

import nova.conf
from nova import context
from nova import objects
from nova.objects import base as obj_base
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

        A missing endpoint entry should permanently disable the
        client. And make future calls to it not happen.
        """
        req.side_effect = ks_exc.EndpointNotFound()
        self.client._get_resource_provider("fake")
        self.assertTrue(self.client._disabled)

        # reset the call count to demonstrate that future calls don't
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        req.assert_not_called()

    @mock.patch('keystoneauth1.session.Session.request')
    def test_missing_auth(self, req):
        """Test Missing Auth handled correctly.

        A missing auth configuration should permanently disable the
        client. And make future calls to it not happen.

        """
        req.side_effect = ks_exc.MissingAuthPlugin()
        self.client._get_resource_provider("fake")
        self.assertTrue(self.client._disabled)

        # reset the call count to demonstrate that future calls don't
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        req.assert_not_called()

    @mock.patch('keystoneauth1.session.Session.request')
    def test_connect_fail(self, req):
        """Test Connect Failure handled correctly.

        If we get a connect failure, this is transient, and we expect
        that this will end up working correctly later. We don't want
        to disable the client.

        """
        req.side_effect = ks_exc.ConnectFailure()
        self.client._get_resource_provider("fake")
        self.assertFalse(self.client._disabled)

        # reset the call count to demonstrate that future calls do
        # work
        req.reset_mock()
        self.client._get_resource_provider("fake")
        self.assertTrue(req.called)


class SchedulerReportClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerReportClientTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.ks_sess_mock = mock.Mock()

        with test.nested(
                mock.patch('keystoneauth1.session.Session',
                           return_value=self.ks_sess_mock),
                mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
        ) as (_auth_mock, _sess_mock):
            self.client = report.SchedulerReportClient()

    @mock.patch('keystoneauth1.session.Session')
    @mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
    def test_constructor(self, load_auth_mock, ks_sess_mock):
        report.SchedulerReportClient()

        load_auth_mock.assert_called_once_with(CONF, 'placement')
        ks_sess_mock.assert_called_once_with(auth=load_auth_mock.return_value)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_exists_in_cache(self, get_rp_mock,
            create_rp_mock):
        # Override the client object's cache to contain a resource provider
        # object for the compute host and check that
        # _ensure_resource_provider() doesn't call _get_resource_provider() or
        # _create_resource_provider()
        self.client._resource_providers = {
            uuids.compute_node: mock.sentinel.rp
        }

        self.client._ensure_resource_provider(uuids.compute_node)
        self.assertFalse(get_rp_mock.called)
        self.assertFalse(create_rp_mock.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_get(self, get_rp_mock, create_rp_mock):
        # No resource provider exists in the client's cache, so validate that
        # if we get the resource provider from the placement API that we don't
        # try to create the resource provider.
        get_rp_mock.return_value = mock.sentinel.rp

        self.client._ensure_resource_provider(uuids.compute_node)

        get_rp_mock.assert_called_once_with(uuids.compute_node)
        self.assertEqual({uuids.compute_node: mock.sentinel.rp},
                          self.client._resource_providers)
        self.assertFalse(create_rp_mock.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_create_none(self, get_rp_mock,
            create_rp_mock):
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
        self.assertEqual({}, self.client._resource_providers)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_create(self, get_rp_mock,
            create_rp_mock):
        # No resource provider exists in the client's cache and no resource
        # provider was returned from the placement API, so verify that in this
        # case we try to create the resource provider via the placement API.
        get_rp_mock.return_value = None
        create_rp_mock.return_value = mock.sentinel.rp

        self.client._ensure_resource_provider(uuids.compute_node)

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

    def test_get_resource_provider_found(self):
        # Ensure _get_resource_provider() returns a ResourceProvider object if
        # it finds a resource provider record from the placement API
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

        expected_provider = objects.ResourceProvider(
                uuid=uuid,
                name=uuid,
                generation=42,
        )
        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        self.assertTrue(obj_base.obj_equal_prims(expected_provider,
                                                 result))

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

        uuid = uuids.compute_node
        result = self.client._get_resource_provider(uuid)

        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        # A 503 Service Unavailable should trigger an error logged and
        # return None from _get_resource_provider()
        self.assertTrue(logging_mock.called)
        self.assertIsNone(result)

    def test_create_resource_provider(self):
        # Ensure _create_resource_provider() returns a ResourceProvider object
        # constructed after creating a resource provider record in the
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
        expected_provider = objects.ResourceProvider(
            uuid=uuid,
            name=name,
            generation=1,
        )
        expected_url = '/resource_providers'
        self.ks_sess_mock.post.assert_called_once_with(
                expected_url,
                endpoint_filter=mock.ANY,
                json=expected_payload,
                raise_exc=False)
        self.assertTrue(obj_base.obj_equal_prims(expected_provider,
                                                 result))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_create_resource_provider_concurrent_create(self, get_rp_mock):
        # Ensure _create_resource_provider() returns a ResourceProvider object
        # gotten from _get_resource_provider() if the call to create the
        # resource provider in the placement API returned a 409 Conflict,
        # indicating another thread concurrently created the resource provider
        # record.
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=409)
        self.ks_sess_mock.post.return_value = resp_mock

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

    @mock.patch.object(report.LOG, 'error')
    def test_create_resource_provider_error(self, logging_mock):
        # Ensure _create_resource_provider() sets the error flag when trying to
        # communicate with the placement API and not getting an error we can
        # deal with
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=503)
        self.ks_sess_mock.post.return_value = resp_mock

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
        # A 503 Service Unavailable should log an error and
        # _create_resource_provider() should return None
        self.assertTrue(logging_mock.called)
        self.assertFalse(result)

    def test_compute_node_inventory(self):
        # This is for making sure we only check once the I/O so we can directly
        # call this helper method for the next tests.
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
        rp = objects.ResourceProvider(uuid=uuid, name=name, generation=42)
        self.client._resource_providers[uuid] = rp

        self.flags(reserved_host_memory_mb=1000)
        self.flags(reserved_host_disk_mb=2000)

        result = self.client._compute_node_inventory(compute_node)

        expected_inventories = {
            'VCPU': {
                'total': compute_node.vcpus,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': compute_node.cpu_allocation_ratio,
            },
            'MEMORY_MB': {
                'total': compute_node.memory_mb,
                'reserved': CONF.reserved_host_memory_mb,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': compute_node.ram_allocation_ratio,
            },
            'DISK_GB': {
                'total': compute_node.local_gb,
                'reserved': CONF.reserved_host_disk_mb * 1024,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': compute_node.disk_allocation_ratio,
            },
        }
        expected = {
            'inventories': expected_inventories,
        }
        self.assertEqual(expected, result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_compute_node_inventory')
    def test_update_inventory(self, mock_inv, mock_put, mock_get):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = objects.ComputeNode(uuid=uuid,
                                           hypervisor_hostname='foo')
        rp = objects.ResourceProvider(uuid=uuid, name='foo', generation=42)
        # Make sure the ResourceProvider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_inv.return_value = {'inventories': []}
        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 43,
            'inventories': {'VCPU': {'total': 16}},
        }
        mock_put.return_value.status_code = 200
        mock_put.return_value.json.return_value = {
            'resource_provider_generation': 44,
            'inventories': {'VCPU': {'total': 16}},
        }

        result = self.client._update_inventory_attempt(compute_node)
        self.assertTrue(result)

        exp_url = '/resource_providers/%s/inventories' % uuid
        mock_get.assert_called_once_with(exp_url)
        # Called with the newly-found generation from the existing inventory
        self.assertEqual(43,
                         mock_inv.return_value['resource_provider_generation'])
        # Updated with the new inventory from the PUT call
        self.assertEqual(44, rp.generation)
        mock_put.assert_called_once_with(exp_url, mock_inv.return_value)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_compute_node_inventory')
    def test_update_inventory_no_update(self, mock_inv, mock_put, mock_get):
        uuid = uuids.compute_node
        compute_node = objects.ComputeNode(uuid=uuid,
                                           hypervisor_hostname='foo')
        rp = objects.ResourceProvider(uuid=uuid, name='foo', generation=42)
        self.client._resource_providers[uuid] = rp
        mock_inv.return_value = {'inventories': {
            'VCPU': {'total': 8},
        }}
        mock_get.return_value.json.return_value = {
            'resource_provider_generation': 43,
            'inventories': {
                'VCPU': {'total': 8}
            }
        }
        result = self.client._update_inventory_attempt(compute_node)
        self.assertTrue(result)
        exp_url = '/resource_providers/%s/inventories' % uuid
        mock_get.assert_called_once_with(exp_url)
        # No update so put should not be called
        self.assertFalse(mock_put.called)
        # Make sure we updated the generation from the inventory records
        self.assertEqual(43, rp.generation)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_compute_node_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    def test_update_inventory_conflicts(self, mock_ensure, mock_inv,
                                        mock_put, mock_get):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = objects.ComputeNode(uuid=uuid,
                                           hypervisor_hostname='foo')
        rp = objects.ResourceProvider(uuid=uuid, name='foo', generation=42)
        # Make sure the ResourceProvider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_inv.return_value = {'inventories': [{'resource_class': 'VCPU'}]}
        mock_get.return_value = {}
        mock_put.return_value.status_code = 409

        result = self.client._update_inventory_attempt(compute_node)
        self.assertFalse(result)

        # Invalidated the cache
        self.assertNotIn(uuid, self.client._resource_providers)
        # Refreshed our resource provider
        mock_ensure.assert_called_once_with(uuid, 'foo')

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_compute_node_inventory')
    def test_update_inventory_unknown_response(self, mock_inv,
                                               mock_put, mock_get):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = objects.ComputeNode(uuid=uuid,
                                           hypervisor_hostname='foo')
        rp = objects.ResourceProvider(uuid=uuid, name='foo', generation=42)
        # Make sure the ResourceProvider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_inv.return_value = {'inventories': [{'resource_class': 'VCPU'}]}
        mock_get.return_value = {}
        mock_put.return_value.status_code = 234

        result = self.client._update_inventory_attempt(compute_node)
        self.assertFalse(result)

        # No cache invalidation
        self.assertIn(uuid, self.client._resource_providers)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_inventory')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_compute_node_inventory')
    def test_update_inventory_failed(self, mock_inv,
                                     mock_put, mock_get):
        # Ensure _update_inventory() returns a list of Inventories objects
        # after creating or updating the existing values
        uuid = uuids.compute_node
        compute_node = objects.ComputeNode(uuid=uuid,
                                           hypervisor_hostname='foo')
        rp = objects.ResourceProvider(uuid=uuid, name='foo', generation=42)
        # Make sure the ResourceProvider exists for preventing to call the API
        self.client._resource_providers[uuid] = rp

        mock_inv.return_value = {'inventories': [{'resource_class': 'VCPU'}]}
        mock_get.return_value = {}
        try:
            mock_put.return_value.__nonzero__.return_value = False
        except AttributeError:
            # Thanks py3
            mock_put.return_value.__bool__.return_value = False

        result = self.client._update_inventory_attempt(compute_node)
        self.assertFalse(result)

        # No cache invalidation
        self.assertIn(uuid, self.client._resource_providers)

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

        result = self.client._update_inventory(cn)
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

        result = self.client._update_inventory(cn)
        self.assertFalse(result)

        # Slept three times
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1), mock.call(1)])

        # Three attempts to update
        mock_update.assert_has_calls([mock.call(cn), mock.call(cn),
                                      mock.call(cn)])

        # Slept three times
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1), mock.call(1)])

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_update_inventory')
    def test_update_resource_stats_rp_fail(self, mock_ui, mock_erp):
        cn = mock.MagicMock()
        self.client.update_resource_stats(cn)
        cn.save.assert_called_once_with()
        mock_erp.assert_called_once_with(cn.uuid, cn.hypervisor_hostname)
        self.assertFalse(mock_ui.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch.object(objects.ComputeNode, 'save')
    def test_update_resource_stats_saves(self, mock_save, mock_ensure):
        cn = objects.ComputeNode(context=self.context,
                                 uuid=uuids.compute_node,
                                 hypervisor_hostname='host1')
        self.client.update_resource_stats(cn)
        mock_save.assert_called_once_with()
        mock_ensure.assert_called_once_with(uuids.compute_node, 'host1')

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_allocations(self, mock_vbi):
        mock_vbi.return_value = False
        inst = objects.Instance(
            uuid=uuids.inst,
            flavor=objects.Flavor(root_gb=10,
                                  swap=1,
                                  ephemeral_gb=100,
                                  memory_mb=1024,
                                  vcpus=2))
        expected = {
            'MEMORY_MB': 1024,
            'VCPU': 2,
            'DISK_GB': 111,
        }
        self.assertEqual(expected, self.client._allocations(inst))

    @mock.patch('nova.compute.utils.is_volume_backed_instance')
    def test_allocations_boot_from_volume(self, mock_vbi):
        mock_vbi.return_value = True
        inst = objects.Instance(
            uuid=uuids.inst,
            flavor=objects.Flavor(root_gb=10,
                                  swap=1,
                                  ephemeral_gb=100,
                                  memory_mb=1024,
                                  vcpus=2))
        expected = {
            'MEMORY_MB': 1024,
            'VCPU': 2,
            'DISK_GB': 101,
        }
        self.assertEqual(expected, self.client._allocations(inst))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    def test_update_instance_allocation_new(self, mock_put):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        with mock.patch.object(self.client, '_allocations') as mock_a:
            expected = {
                'allocations': [
                    {'resource_provider': {'uuid': cn.uuid},
                     'resources': mock_a.return_value}]
            }
            self.client.update_instance_allocation(cn, inst, 1)
            mock_put.assert_called_once_with(
                '/allocations/%s' % inst.uuid,
                expected)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'put')
    @mock.patch.object(report.LOG, 'warning')
    def test_update_instance_allocation_new_failed(self, mock_warn, mock_put):
        cn = objects.ComputeNode(uuid=uuids.cn)
        inst = objects.Instance(uuid=uuids.inst)
        with mock.patch.object(self.client, '_allocations'):
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

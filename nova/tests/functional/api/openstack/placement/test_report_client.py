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

from keystoneauth1 import adapter
from keystoneauth1 import session
import mock
import requests
from wsgi_intercept import interceptor

from nova.api.openstack.placement import deploy
from nova import conf
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields
from nova.scheduler.client import report
from nova import test
from nova.tests import uuidsentinel as uuids

CONF = conf.CONF


class NoAuthReportClient(report.SchedulerReportClient):
    """A SchedulerReportClient that avoids keystone."""

    def __init__(self):
        super(NoAuthReportClient, self).__init__()
        # Supply our own session so the wsgi-intercept can intercept
        # the right thing. Another option would be to use the direct
        # urllib3 interceptor.
        request_session = requests.Session()
        headers = {
            'x-auth-token': 'admin',
            'OpenStack-API-Version': 'placement latest',
        }
        self._client = adapter.Adapter(
            session.Session(auth=None, session=request_session,
                            additional_headers=headers),
            service_type='placement')


@mock.patch('nova.compute.utils.is_volume_backed_instance',
            new=mock.Mock(return_value=False))
@mock.patch('nova.objects.compute_node.ComputeNode.save', new=mock.Mock())
@mock.patch('keystoneauth1.session.Session.get_auth_headers',
            new=mock.Mock(return_value={'x-auth-token': 'admin'}))
@mock.patch('keystoneauth1.session.Session.get_endpoint',
            new=mock.Mock(return_value='http://localhost:80/placement'))
class SchedulerReportClientTests(test.TestCase):
    """Set up an intercepted placement API to test against."""

    def setUp(self):
        super(SchedulerReportClientTests, self).setUp()
        self.flags(auth_strategy='noauth2', group='api')

        self.app = lambda: deploy.loadapp(CONF)
        self.client = NoAuthReportClient()
        # TODO(cdent): Port required here to deal with a bug
        # in wsgi-intercept:
        # https://github.com/cdent/wsgi-intercept/issues/41
        self.url = 'http://localhost:80/placement'
        self.compute_uuid = uuids.compute_node
        self.compute_name = 'computehost'
        self.compute_node = objects.ComputeNode(
            uuid=self.compute_uuid,
            hypervisor_hostname=self.compute_name,
            vcpus=2,
            cpu_allocation_ratio=16.0,
            memory_mb=2048,
            ram_allocation_ratio=1.5,
            local_gb=1024,
            disk_allocation_ratio=1.0)

        self.instance_uuid = uuids.inst
        self.instance = objects.Instance(
            uuid=self.instance_uuid,
            project_id = uuids.project,
            user_id = uuids.user,
            flavor=objects.Flavor(root_gb=10,
                                  swap=1,
                                  ephemeral_gb=100,
                                  memory_mb=1024,
                                  vcpus=2,
                                  extra_specs={}))
        self.context = context.get_admin_context()

    def _interceptor(self):
        # Isolate this initialization for maintainability.
        return interceptor.RequestsInterceptor(app=self.app, url=self.url)

    def test_client_report_smoke(self):
        """Check things go as expected when doing the right things."""
        # TODO(cdent): We should probably also have a test that
        # tests that when allocation or inventory errors happen, we
        # are resilient.
        res_class = fields.ResourceClass.VCPU
        with self._interceptor():
            # When we start out there are no resource providers.
            rp = self.client._get_resource_provider(self.compute_uuid)
            self.assertIsNone(rp)
            rps = self.client._get_providers_in_tree(self.compute_uuid)
            self.assertEqual([], rps)
            # But get_provider_tree_and_ensure_root creates one (via
            # _ensure_resource_provider)
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            self.assertEqual([self.compute_uuid], ptree.get_provider_uuids())

            # Now let's update status for our compute node.
            self.client.update_compute_node(self.context, self.compute_node)

            # So now we have a resource provider
            rp = self.client._get_resource_provider(self.compute_uuid)
            self.assertIsNotNone(rp)
            rps = self.client._get_providers_in_tree(self.compute_uuid)
            self.assertEqual(1, len(rps))

            # We should also have empty sets of aggregate and trait
            # associations
            self.assertEqual(
                [], self.client._get_sharing_providers([uuids.agg]))
            self.assertFalse(
                self.client._provider_tree.have_aggregates_changed(
                    self.compute_uuid, []))
            self.assertFalse(
                self.client._provider_tree.have_traits_changed(
                    self.compute_uuid, []))

            # TODO(cdent): change this to use the methods built in
            # to the report client to retrieve inventory?
            inventory_url = ('/resource_providers/%s/inventories' %
                             self.compute_uuid)
            resp = self.client.get(inventory_url)
            inventory_data = resp.json()['inventories']
            self.assertEqual(self.compute_node.vcpus,
                             inventory_data[res_class]['total'])

            # Providers and inventory show up nicely in the provider tree
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            self.assertEqual([self.compute_uuid], ptree.get_provider_uuids())
            self.assertTrue(ptree.has_inventory(self.compute_uuid))

            # Update allocations with our instance
            self.client.update_instance_allocation(
                self.context, self.compute_node, self.instance, 1)

            # Check that allocations were made
            resp = self.client.get('/allocations/%s' % self.instance_uuid)
            alloc_data = resp.json()['allocations']
            vcpu_data = alloc_data[self.compute_uuid]['resources'][res_class]
            self.assertEqual(2, vcpu_data)

            # Check that usages are up to date
            resp = self.client.get('/resource_providers/%s/usages' %
                                   self.compute_uuid)
            usage_data = resp.json()['usages']
            vcpu_data = usage_data[res_class]
            self.assertEqual(2, vcpu_data)

            # Delete allocations with our instance
            self.client.update_instance_allocation(
                self.context, self.compute_node, self.instance, -1)

            # No usage
            resp = self.client.get('/resource_providers/%s/usages' %
                                   self.compute_uuid)
            usage_data = resp.json()['usages']
            vcpu_data = usage_data[res_class]
            self.assertEqual(0, vcpu_data)

            # Trigger the reporting client deleting all inventory by setting
            # the compute node's CPU, RAM and disk amounts to 0.
            self.compute_node.vcpus = 0
            self.compute_node.memory_mb = 0
            self.compute_node.local_gb = 0
            self.client.update_compute_node(self.context, self.compute_node)

            # Check there's no more inventory records
            resp = self.client.get(inventory_url)
            inventory_data = resp.json()['inventories']
            self.assertEqual({}, inventory_data)

            # Build the provider tree afresh.
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            # The compute node is still there
            self.assertEqual([self.compute_uuid], ptree.get_provider_uuids())
            # But the inventory is gone
            self.assertFalse(ptree.has_inventory(self.compute_uuid))

            # Try setting some invalid inventory and make sure the report
            # client raises the expected error.
            inv_data = {
                'BAD_FOO': {
                    'total': 100,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 100,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            self.assertRaises(exception.InvalidResourceClass,
                              self.client.set_inventory_for_provider,
                              self.context, self.compute_uuid,
                              self.compute_name, inv_data)

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                new=mock.Mock(return_value=False))
    @mock.patch('nova.objects.compute_node.ComputeNode.save', new=mock.Mock())
    @mock.patch('keystoneauth1.session.Session.get_auth_headers',
                new=mock.Mock(return_value={'x-auth-token': 'admin'}))
    @mock.patch('keystoneauth1.session.Session.get_endpoint',
                new=mock.Mock(return_value='http://localhost:80/placement'))
    def test_ensure_standard_resource_class(self):
        """Test case for bug #1746615: If placement is running a newer version
        of code than compute, it may have new standard resource classes we
        don't know about.  Make sure this scenario doesn't cause errors in
        set_inventory_for_provider.
        """
        inv = {
            'VCPU': {
                'total': 10,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 2,
                'step_size': 1,
                'allocation_ratio': 10.0,
            },
            'MEMORY_MB': {
                'total': 1048576,
                'reserved': 2048,
                'min_unit': 1024,
                'max_unit': 131072,
                'step_size': 1024,
                'allocation_ratio': 1.0,
            },
            'DISK_GB': {
                'total': 100,
                'reserved': 1,
                'min_unit': 1,
                'max_unit': 10,
                'step_size': 2,
                'allocation_ratio': 10.0,
            },
            # A standard resource class known by placement, but not locally
            'PCI_DEVICE': {
                'total': 4,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 4,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
            'CUSTOM_BANDWIDTH': {
                'total': 1250000,
                'reserved': 10000,
                'min_unit': 5000,
                'max_unit': 250000,
                'step_size': 5000,
                'allocation_ratio': 8.0,
            },
        }
        with interceptor.RequestsInterceptor(app=self.app, url=self.url):
            self.client.update_compute_node(self.context, self.compute_node)
            # Simulate that our locally-running code has an outdated notion of
            # standard resource classes.
            with mock.patch.object(fields.ResourceClass, 'STANDARD',
                                   ('VCPU', 'MEMORY_MB', 'DISK_GB')):
                # TODO(efried): Once bug #1746615 is fixed, this will no longer
                # raise, and can be replaced with:
                # self.client.set_inventory_for_provider(
                #     self.context, self.compute_uuid, self.compute_name, inv)
                self.assertRaises(
                    exception.InvalidResourceClass,
                    self.client.set_inventory_for_provider,
                    self.context, self.compute_uuid, self.compute_name, inv)

    @mock.patch('keystoneauth1.session.Session.get_endpoint',
                return_value='http://localhost:80/placement')
    def test_global_request_id(self, mock_endpoint):
        global_request_id = 'req-%s' % uuids.global_request_id

        def assert_app(environ, start_response):
            # Assert the 'X-Openstack-Request-Id' header in the request.
            self.assertIn('HTTP_X_OPENSTACK_REQUEST_ID', environ)
            self.assertEqual(global_request_id,
                             environ['HTTP_X_OPENSTACK_REQUEST_ID'])
            start_response('204 OK', [])
            return []

        with interceptor.RequestsInterceptor(
                app=lambda: assert_app, url=self.url):
            self.client._delete_provider(self.compute_uuid,
                                         global_request_id=global_request_id)
            payload = {
                'name': 'test-resource-provider'
            }
            self.client.post('/resource_providers', payload,
                             global_request_id=global_request_id)
            self.client.put('/resource_providers/%s' % self.compute_uuid,
                            payload,
                            global_request_id=global_request_id)

    def test_get_provider_tree_with_nested_and_aggregates(self):
        """A more in-depth test of get_provider_tree_and_ensure_root with
        nested and sharing resource providers.

               ss1(DISK)    ss2(DISK)           ss3(DISK)
         agg_disk_1 \         / agg_disk_2        | agg_disk_3
               cn(VCPU,MEM,DISK)                  x
               /              \
        pf1(VF,BW)        pf2(VF,BW)           sbw(BW)
          agg_ip \       / agg_ip                 | agg_bw
                  sip(IP)                         x

        """
        with self._interceptor():
            # Register the compute node and its inventory
            self.client.update_compute_node(self.context, self.compute_node)
            # The compute node is associated with two of the shared storages
            self.client.set_aggregates_for_provider(
                self.compute_uuid, set([uuids.agg_disk_1, uuids.agg_disk_2]))

            # Register two SR-IOV PFs with VF and bandwidth inventory
            for x in (1, 2):
                name = 'pf%d' % x
                uuid = getattr(uuids, name)
                self.client.set_inventory_for_provider(
                    self.context, uuid, name, {
                        fields.ResourceClass.SRIOV_NET_VF: {
                            'total': 24 * x,
                            'reserved': x,
                            'min_unit': 1,
                            'max_unit': 24 * x,
                            'step_size': 1,
                            'allocation_ratio': 1.0,
                        },
                        'CUSTOM_BANDWIDTH': {
                            'total': 125000 * x,
                            'reserved': 1000 * x,
                            'min_unit': 5000,
                            'max_unit': 25000 * x,
                            'step_size': 5000,
                            'allocation_ratio': 1.0,
                        },
                    }, parent_provider_uuid=self.compute_uuid)
                # They're associated with an IP address aggregate
                self.client.set_aggregates_for_provider(uuid, [uuids.agg_ip])
                # Set some traits on 'em
                self.client.set_traits_for_provider(
                    uuid, ['CUSTOM_PHYSNET_%d' % x])

            # Register three shared storage pools with disk inventory
            for x in (1, 2, 3):
                name = 'ss%d' % x
                uuid = getattr(uuids, name)
                self.client.set_inventory_for_provider(
                    self.context, uuid, name, {
                        fields.ResourceClass.DISK_GB: {
                            'total': 100 * x,
                            'reserved': x,
                            'min_unit': 1,
                            'max_unit': 10 * x,
                            'step_size': 2,
                            'allocation_ratio': 10.0,
                        },
                    })
                # Mark as a sharing provider
                self.client.set_traits_for_provider(
                    uuid, ['MISC_SHARES_VIA_AGGREGATE'])
                # Associate each with its own aggregate.  The compute node is
                # associated with the first two (agg_disk_1 and agg_disk_2).
                agg = getattr(uuids, 'agg_disk_%d' % x)
                self.client.set_aggregates_for_provider(uuid, [agg])

            # Register a shared IP address provider with IP address inventory
            self.client.set_inventory_for_provider(
                self.context, uuids.sip, 'sip', {
                    fields.ResourceClass.IPV4_ADDRESS: {
                        'total': 128,
                        'reserved': 0,
                        'min_unit': 1,
                        'max_unit': 8,
                        'step_size': 1,
                        'allocation_ratio': 1.0,
                    },
                })
            # Mark as a sharing provider, and add another trait
            self.client.set_traits_for_provider(
                uuids.sip, set(['MISC_SHARES_VIA_AGGREGATE', 'CUSTOM_FOO']))
            # It's associated with the same aggregate as both PFs
            self.client.set_aggregates_for_provider(uuids.sip, [uuids.agg_ip])

            # Register a shared network bandwidth provider
            self.client.set_inventory_for_provider(
                self.context, uuids.sbw, 'sbw', {
                    'CUSTOM_BANDWIDTH': {
                        'total': 1250000,
                        'reserved': 10000,
                        'min_unit': 5000,
                        'max_unit': 250000,
                        'step_size': 5000,
                        'allocation_ratio': 8.0,
                    },
                })
            # Mark as a sharing provider
            self.client.set_traits_for_provider(
                uuids.sbw, ['MISC_SHARES_VIA_AGGREGATE'])
            # It's associated with some other aggregate.
            self.client.set_aggregates_for_provider(uuids.sbw, [uuids.agg_bw])

            # Setup is done.  Grab the ProviderTree
            prov_tree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)

            # All providers show up because we used set_inventory_for_provider
            self.assertEqual(set([self.compute_uuid, uuids.ss1, uuids.ss2,
                                  uuids.pf1, uuids.pf2, uuids.sip, uuids.ss3,
                                  uuids.sbw]),
                             set(prov_tree.get_provider_uuids()))
            # Narrow the field to just our compute subtree.
            self.assertEqual(
                set([self.compute_uuid, uuids.pf1, uuids.pf2]),
                set(prov_tree.get_provider_uuids(self.compute_uuid)))

            # Validate traits for a couple of providers
            self.assertFalse(prov_tree.have_traits_changed(
                uuids.pf2, ['CUSTOM_PHYSNET_2']))
            self.assertFalse(prov_tree.have_traits_changed(
                uuids.sip, ['MISC_SHARES_VIA_AGGREGATE', 'CUSTOM_FOO']))

            # Validate aggregates for a couple of providers
            self.assertFalse(prov_tree.have_aggregates_changed(
                uuids.sbw, [uuids.agg_bw]))
            self.assertFalse(prov_tree.have_aggregates_changed(
                self.compute_uuid, [uuids.agg_disk_1, uuids.agg_disk_2]))

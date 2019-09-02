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

import copy
from keystoneauth1 import exceptions as kse
import mock
import os_resource_classes as orc
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_utils.fixture import uuidsentinel as uuids
import pkg_resources
from placement import direct
from placement.tests.functional.fixtures import placement

from nova.cmd import status
from nova.compute import provider_tree
from nova.compute import utils as compute_utils
from nova import conf
from nova import context
# TODO(cdent): This points to the nova, not placement, exception for
# InvalidResourceClass. This test should probably move out of the
# placement hierarchy since it expects a "standard" placement server
# and is not testing the placement service itself.
from nova import exception
from nova import objects
from nova.scheduler.client import report
from nova.scheduler import utils
from nova import test


CONF = conf.CONF

CMD_STATUS_MIN_MICROVERSION = pkg_resources.parse_version(
    status.MIN_PLACEMENT_MICROVERSION)


class VersionCheckingReportClient(report.SchedulerReportClient):
    """This wrapper around SchedulerReportClient checks microversions for
    get/put/post/delete calls to validate that the minimum requirement enforced
    in nova.cmd.status has been bumped appropriately when the report client
    uses a new version. This of course relies on there being a test in this
    module that hits the code path using that microversion. (This mechanism can
    be copied into other func test suites where we hit the report client.)
    """
    @staticmethod
    def _check_microversion(kwargs):
        microversion = kwargs.get('version')
        if not microversion:
            return

        seen_microversion = pkg_resources.parse_version(microversion)
        if seen_microversion > CMD_STATUS_MIN_MICROVERSION:
            raise ValueError(
                "Report client is using microversion %s, but nova.cmd.status "
                "is only requiring %s. See "
                "I4369f7fb1453e896864222fa407437982be8f6b5 for an example of "
                "how to bump the minimum requirement." %
                (microversion, status.MIN_PLACEMENT_MICROVERSION))

    def get(self, *args, **kwargs):
        self._check_microversion(kwargs)
        return super(VersionCheckingReportClient, self).get(*args, **kwargs)

    def put(self, *args, **kwargs):
        self._check_microversion(kwargs)
        return super(VersionCheckingReportClient, self).put(*args, **kwargs)

    def post(self, *args, **kwargs):
        self._check_microversion(kwargs)
        return super(VersionCheckingReportClient, self).post(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._check_microversion(kwargs)
        return super(VersionCheckingReportClient, self).delete(*args, **kwargs)


class SchedulerReportClientTestBase(test.TestCase):

    def setUp(self):
        super(SchedulerReportClientTestBase, self).setUp()
        # Because these tests use PlacementDirect we need to manage
        # the database and other config ourselves.
        config = cfg.ConfigOpts()
        placement_conf = self.useFixture(config_fixture.Config(config))
        self.useFixture(
            placement.PlacementFixture(conf_fixture=placement_conf, db=True,
                                       use_intercept=False))
        self.placement_conf = placement_conf.conf

    def _interceptor(self, app=None, latest_microversion=True):
        """Set up an intercepted placement API to test against.

        Use as e.g.

        with interceptor() as client:
            ret = client.get_provider_tree_and_ensure_root(...)

        :param app: An optional wsgi app loader.
        :param latest_microversion: If True (the default), API requests will
                                    use the latest microversion if not
                                    otherwise specified. If False, the base
                                    microversion is the default.
        :return: Context manager, which in turn returns a direct
                SchedulerReportClient.
        """
        class ReportClientInterceptor(direct.PlacementDirect):
            """A shim around PlacementDirect that wraps the Adapter in a
            SchedulerReportClient.
            """
            def __enter__(inner_self):
                adap = super(ReportClientInterceptor, inner_self).__enter__()
                client = VersionCheckingReportClient(adapter=adap)
                # NOTE(efried): This `self` is the TestCase!
                self._set_client(client)
                return client

        interceptor = ReportClientInterceptor(
            self.placement_conf, latest_microversion=latest_microversion)
        if app:
            interceptor.app = app
        return interceptor

    def _set_client(self, client):
        """Set report client attributes on the TestCase instance.

        Override this to do things like:
        self.mocked_thingy.report_client = client

        :param client: A direct SchedulerReportClient.
        """
        pass


@mock.patch('nova.compute.utils.is_volume_backed_instance',
            new=mock.Mock(return_value=False))
@mock.patch('nova.objects.compute_node.ComputeNode.save', new=mock.Mock())
class SchedulerReportClientTests(SchedulerReportClientTestBase):

    def setUp(self):
        super(SchedulerReportClientTests, self).setUp()
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

    def _set_client(self, client):
        # TODO(efried): Rip this out and just use `as client` throughout.
        self.client = client

    def test_client_report_smoke(self):
        """Check things go as expected when doing the right things."""
        # TODO(cdent): We should probably also have a test that
        # tests that when allocation or inventory errors happen, we
        # are resilient.
        res_class = orc.VCPU
        with self._interceptor():
            # When we start out there are no resource providers.
            rp = self.client._get_resource_provider(self.context,
                                                    self.compute_uuid)
            self.assertIsNone(rp)
            rps = self.client.get_providers_in_tree(self.context,
                                                    self.compute_uuid)
            self.assertEqual([], rps)
            # But get_provider_tree_and_ensure_root creates one (via
            # _ensure_resource_provider)
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            self.assertEqual([self.compute_uuid], ptree.get_provider_uuids())

            # Now let's update status for our compute node.
            self.client._ensure_resource_provider(
                self.context, self.compute_uuid, name=self.compute_name)
            self.client.set_inventory_for_provider(
                self.context, self.compute_uuid,
                compute_utils.compute_node_to_inventory_dict(
                    self.compute_node))

            # So now we have a resource provider
            rp = self.client._get_resource_provider(self.context,
                                                    self.compute_uuid)
            self.assertIsNotNone(rp)
            rps = self.client.get_providers_in_tree(self.context,
                                                    self.compute_uuid)
            self.assertEqual(1, len(rps))

            # We should also have empty sets of aggregate and trait
            # associations
            self.assertEqual(
                [], self.client._get_sharing_providers(self.context,
                                                       [uuids.agg]))
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
            alloc_dict = utils.resources_from_flavor(self.instance,
                                                     self.instance.flavor)
            payload = {
                "allocations": {
                    self.compute_uuid: {"resources": alloc_dict}
                },
                "project_id": self.instance.project_id,
                "user_id": self.instance.user_id,
                "consumer_generation": None
            }
            self.client.put_allocations(
                self.context, self.instance_uuid, payload)

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
            self.client.delete_allocation_for_instance(self.context,
                                                       self.instance.uuid)

            # No usage
            resp = self.client.get('/resource_providers/%s/usages' %
                                   self.compute_uuid)
            usage_data = resp.json()['usages']
            vcpu_data = usage_data[res_class]
            self.assertEqual(0, vcpu_data)

            # Allocation bumped the generation, so refresh to get the latest
            self.client._refresh_and_get_inventory(self.context,
                                                   self.compute_uuid)

            # Trigger the reporting client deleting all inventory by setting
            # the compute node's CPU, RAM and disk amounts to 0.
            self.compute_node.vcpus = 0
            self.compute_node.memory_mb = 0
            self.compute_node.local_gb = 0
            self.client.set_inventory_for_provider(
                self.context, self.compute_uuid,
                compute_utils.compute_node_to_inventory_dict(
                    self.compute_node))

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

    def test_global_request_id(self):
        global_request_id = 'req-%s' % uuids.global_request_id

        def assert_app(environ, start_response):
            # Assert the 'X-Openstack-Request-Id' header in the request.
            self.assertIn('HTTP_X_OPENSTACK_REQUEST_ID', environ)
            self.assertEqual(global_request_id,
                             environ['HTTP_X_OPENSTACK_REQUEST_ID'])
            start_response('204 OK', [])
            return []

        with self._interceptor(app=lambda: assert_app):
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
            self.client.get('/resource_providers/%s' % self.compute_uuid,
                            global_request_id=global_request_id)

    def test_get_provider_tree_with_nested_and_aggregates(self):
        r"""A more in-depth test of get_provider_tree_and_ensure_root with
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
            self.client._ensure_resource_provider(
                self.context, self.compute_uuid, name=self.compute_name)
            self.client.set_inventory_for_provider(
                self.context, self.compute_uuid,
                compute_utils.compute_node_to_inventory_dict(
                    self.compute_node))
            # The compute node is associated with two of the shared storages
            self.client.set_aggregates_for_provider(
                self.context, self.compute_uuid,
                set([uuids.agg_disk_1, uuids.agg_disk_2]))

            # Register two SR-IOV PFs with VF and bandwidth inventory
            for x in (1, 2):
                name = 'pf%d' % x
                uuid = getattr(uuids, name)
                self.client._ensure_resource_provider(
                    self.context, uuid, name=name,
                    parent_provider_uuid=self.compute_uuid)
                self.client.set_inventory_for_provider(
                    self.context, uuid, {
                        orc.SRIOV_NET_VF: {
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
                    })
                # They're associated with an IP address aggregate
                self.client.set_aggregates_for_provider(self.context, uuid,
                                                        [uuids.agg_ip])
                # Set some traits on 'em
                self.client.set_traits_for_provider(
                    self.context, uuid, ['CUSTOM_PHYSNET_%d' % x])

            # Register three shared storage pools with disk inventory
            for x in (1, 2, 3):
                name = 'ss%d' % x
                uuid = getattr(uuids, name)
                self.client._ensure_resource_provider(self.context, uuid,
                                                      name=name)
                self.client.set_inventory_for_provider(
                    self.context, uuid, {
                        orc.DISK_GB: {
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
                    self.context, uuid, ['MISC_SHARES_VIA_AGGREGATE'])
                # Associate each with its own aggregate.  The compute node is
                # associated with the first two (agg_disk_1 and agg_disk_2).
                agg = getattr(uuids, 'agg_disk_%d' % x)
                self.client.set_aggregates_for_provider(self.context, uuid,
                                                        [agg])

            # Register a shared IP address provider with IP address inventory
            self.client._ensure_resource_provider(self.context, uuids.sip,
                                                  name='sip')
            self.client.set_inventory_for_provider(
                self.context, uuids.sip, {
                    orc.IPV4_ADDRESS: {
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
                self.context, uuids.sip,
                set(['MISC_SHARES_VIA_AGGREGATE', 'CUSTOM_FOO']))
            # It's associated with the same aggregate as both PFs
            self.client.set_aggregates_for_provider(self.context, uuids.sip,
                                                    [uuids.agg_ip])

            # Register a shared network bandwidth provider
            self.client._ensure_resource_provider(self.context, uuids.sbw,
                                                  name='sbw')
            self.client.set_inventory_for_provider(
                self.context, uuids.sbw, {
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
                self.context, uuids.sbw, ['MISC_SHARES_VIA_AGGREGATE'])
            # It's associated with some other aggregate.
            self.client.set_aggregates_for_provider(self.context, uuids.sbw,
                                                    [uuids.agg_bw])

            # Setup is done.  Grab the ProviderTree
            prov_tree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)

            # All providers show up because we used _ensure_resource_provider
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

    def test__set_inventory_reserved_eq_total(self):
        with self._interceptor(latest_microversion=False):
            # Create the provider
            self.client._ensure_resource_provider(self.context, uuids.cn)

            # Make sure we can set reserved value equal to total
            inv = {
                orc.SRIOV_NET_VF: {
                    'total': 24,
                    'reserved': 24,
                    'min_unit': 1,
                    'max_unit': 24,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            self.client.set_inventory_for_provider(
                self.context, uuids.cn, inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

    def test_set_inventory_for_provider(self):
        """Tests for SchedulerReportClient.set_inventory_for_provider.
        """
        with self._interceptor():
            inv = {
                orc.SRIOV_NET_VF: {
                    'total': 24,
                    'reserved': 1,
                    'min_unit': 1,
                    'max_unit': 24,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            # Provider doesn't exist in our cache
            self.assertRaises(
                ValueError,
                self.client.set_inventory_for_provider,
                self.context, uuids.cn, inv)
            self.assertIsNone(self.client._get_inventory(
                self.context, uuids.cn))

            # Create the provider
            self.client._ensure_resource_provider(self.context, uuids.cn)
            # Still no inventory, but now we don't get a 404
            self.assertEqual(
                {},
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

            # Now set the inventory
            self.client.set_inventory_for_provider(
                self.context, uuids.cn, inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

            # Make sure we can change it
            inv = {
                orc.SRIOV_NET_VF: {
                    'total': 24,
                    'reserved': 1,
                    'min_unit': 1,
                    'max_unit': 24,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
                orc.IPV4_ADDRESS: {
                    'total': 128,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 8,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            self.client.set_inventory_for_provider(
                self.context, uuids.cn, inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

            # Create custom resource classes on the fly
            self.assertFalse(
                self.client.get('/resource_classes/CUSTOM_BANDWIDTH'))
            inv = {
                orc.SRIOV_NET_VF: {
                    'total': 24,
                    'reserved': 1,
                    'min_unit': 1,
                    'max_unit': 24,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
                orc.IPV4_ADDRESS: {
                    'total': 128,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 8,
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
            self.client.set_inventory_for_provider(
                self.context, uuids.cn, inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])
            # The custom resource class got created.
            self.assertTrue(
                self.client.get('/resource_classes/CUSTOM_BANDWIDTH'))

            # Creating a bogus resource class raises the appropriate exception.
            bogus_inv = dict(inv)
            bogus_inv['CUSTOM_BOGU$$'] = {
                'total': 1,
                'reserved': 1,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
            }
            self.assertRaises(
                exception.InvalidResourceClass,
                self.client.set_inventory_for_provider,
                self.context, uuids.cn, bogus_inv)
            self.assertFalse(
                self.client.get('/resource_classes/BOGUS'))
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

            # Create a generation conflict by doing an "out of band" update
            oob_inv = {
                orc.IPV4_ADDRESS: {
                    'total': 128,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 8,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            gen = self.client._provider_tree.data(uuids.cn).generation
            self.assertTrue(
                self.client.put(
                    '/resource_providers/%s/inventories' % uuids.cn,
                    {'resource_provider_generation': gen,
                     'inventories': oob_inv}))
            self.assertEqual(
                oob_inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

            # Now try to update again.
            inv = {
                orc.SRIOV_NET_VF: {
                    'total': 24,
                    'reserved': 1,
                    'min_unit': 1,
                    'max_unit': 24,
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
            # Cached generation is off, so this will bounce with a conflict.
            self.assertRaises(
                exception.ResourceProviderUpdateConflict,
                self.client.set_inventory_for_provider,
                self.context, uuids.cn, inv)
            # Inventory still corresponds to the out-of-band update
            self.assertEqual(
                oob_inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])
            # Force refresh to get the latest generation
            self.client._refresh_and_get_inventory(self.context, uuids.cn)
            # Now the update should work
            self.client.set_inventory_for_provider(
                self.context, uuids.cn, inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])
            payload = {
                "allocations": {
                    uuids.cn: {"resources": {orc.SRIOV_NET_VF: 1}}
                },
                "project_id": uuids.proj,
                "user_id": uuids.user,
                "consumer_generation": None
            }
            # Now set up an InventoryInUse case by creating a VF allocation...
            self.assertTrue(
                self.client.put_allocations(
                    self.context, uuids.consumer, payload))
            # ...and trying to delete the provider's VF inventory
            bad_inv = {
                'CUSTOM_BANDWIDTH': {
                    'total': 1250000,
                    'reserved': 10000,
                    'min_unit': 5000,
                    'max_unit': 250000,
                    'step_size': 5000,
                    'allocation_ratio': 8.0,
                },
            }
            # Allocation bumped the generation, so refresh to get the latest
            self.client._refresh_and_get_inventory(self.context, uuids.cn)
            msgre = (".*update conflict: Inventory for 'SRIOV_NET_VF' on "
                     "resource provider '%s' in use..*" % uuids.cn)
            with self.assertRaisesRegex(exception.InventoryInUse, msgre):
                self.client.set_inventory_for_provider(self.context, uuids.cn,
                                                       bad_inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

            # Same result if we try to clear all the inventory
            bad_inv = {}
            with self.assertRaisesRegex(exception.InventoryInUse, msgre):
                self.client.set_inventory_for_provider(self.context, uuids.cn,
                                                       bad_inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

            # Remove the allocation to make it work
            self.client.delete('/allocations/' + uuids.consumer)
            # Force refresh to get the latest generation
            self.client._refresh_and_get_inventory(self.context, uuids.cn)
            inv = {}
            self.client.set_inventory_for_provider(
                self.context, uuids.cn, inv)
            self.assertEqual(
                inv,
                self.client._get_inventory(
                    self.context, uuids.cn)['inventories'])

    def test_update_from_provider_tree(self):
        """A "realistic" walk through the lifecycle of a compute node provider
        tree.
        """
        # NOTE(efried): We can use the same ProviderTree throughout, since
        # update_from_provider_tree doesn't change it.
        new_tree = provider_tree.ProviderTree()

        def assert_ptrees_equal():
            uuids = set(self.client._provider_tree.get_provider_uuids())
            self.assertEqual(uuids, set(new_tree.get_provider_uuids()))
            for uuid in uuids:
                cdata = self.client._provider_tree.data(uuid)
                ndata = new_tree.data(uuid)
                self.assertEqual(ndata.name, cdata.name)
                self.assertEqual(ndata.parent_uuid, cdata.parent_uuid)
                self.assertFalse(
                    new_tree.has_inventory_changed(uuid, cdata.inventory))
                self.assertFalse(
                    new_tree.have_traits_changed(uuid, cdata.traits))
                self.assertFalse(
                    new_tree.have_aggregates_changed(uuid, cdata.aggregates))

        # Do these with a failing interceptor to prove no API calls are made.
        with self._interceptor(app=lambda: 'nuke') as client:
            # To begin with, the cache should be empty
            self.assertEqual([], client._provider_tree.get_provider_uuids())
            # When new_tree is empty, it's a no-op.
            client.update_from_provider_tree(self.context, new_tree)
            assert_ptrees_equal()

        with self._interceptor():
            # Populate with a provider with no inventories, aggregates, traits
            new_tree.new_root('root', uuids.root)
            self.client.update_from_provider_tree(self.context, new_tree)
            assert_ptrees_equal()

            # Throw in some more providers, in various spots in the tree, with
            # some sub-properties
            new_tree.new_child('child1', uuids.root, uuid=uuids.child1)
            new_tree.update_aggregates('child1', [uuids.agg1, uuids.agg2])
            new_tree.new_child('grandchild1_1', uuids.child1, uuid=uuids.gc1_1)
            new_tree.update_traits(uuids.gc1_1, ['CUSTOM_PHYSNET_2'])
            new_tree.new_root('ssp', uuids.ssp)
            new_tree.update_inventory('ssp', {
                orc.DISK_GB: {
                    'total': 100,
                    'reserved': 1,
                    'min_unit': 1,
                    'max_unit': 10,
                    'step_size': 2,
                    'allocation_ratio': 10.0,
                },
            })
            self.client.update_from_provider_tree(self.context, new_tree)
            assert_ptrees_equal()

            # Swizzle properties
            # Give the root some everything
            new_tree.update_inventory(uuids.root, {
                orc.VCPU: {
                    'total': 10,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 2,
                    'step_size': 1,
                    'allocation_ratio': 10.0,
                },
                orc.MEMORY_MB: {
                    'total': 1048576,
                    'reserved': 2048,
                    'min_unit': 1024,
                    'max_unit': 131072,
                    'step_size': 1024,
                    'allocation_ratio': 1.0,
                },
            })
            new_tree.update_aggregates(uuids.root, [uuids.agg1])
            new_tree.update_traits(uuids.root, ['HW_CPU_X86_AVX',
                                                'HW_CPU_X86_AVX2'])
            # Take away the child's aggregates
            new_tree.update_aggregates(uuids.child1, [])
            # Grandchild gets some inventory
            ipv4_inv = {
                orc.IPV4_ADDRESS: {
                    'total': 128,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 8,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            new_tree.update_inventory('grandchild1_1', ipv4_inv)
            # Shared storage provider gets traits
            new_tree.update_traits('ssp', set(['MISC_SHARES_VIA_AGGREGATE',
                                               'STORAGE_DISK_SSD']))
            self.client.update_from_provider_tree(self.context, new_tree)
            assert_ptrees_equal()

            # Let's go for some error scenarios.
            # Add inventory in an invalid resource class
            new_tree.update_inventory(
                'grandchild1_1',
                dict(ipv4_inv,
                     MOTSUC_BANDWIDTH={
                         'total': 1250000,
                         'reserved': 10000,
                         'min_unit': 5000,
                         'max_unit': 250000,
                         'step_size': 5000,
                         'allocation_ratio': 8.0,
                     }))
            self.assertRaises(
                exception.ResourceProviderSyncFailed,
                self.client.update_from_provider_tree, self.context, new_tree)
            # The inventory update didn't get synced.
            self.assertIsNone(self.client._get_inventory(
                self.context, uuids.grandchild1_1))
            # We invalidated the cache for the entire tree around grandchild1_1
            # but did not invalidate the other root (the SSP)
            self.assertEqual([uuids.ssp],
                             self.client._provider_tree.get_provider_uuids())
            # This is a little under-the-hood-looking, but make sure we cleared
            # the association refresh timers for everything in the grandchild's
            # tree
            self.assertEqual(set([uuids.ssp]),
                             set(self.client._association_refresh_time))

            # Fix that problem so we can try the next one
            new_tree.update_inventory(
                'grandchild1_1',
                dict(ipv4_inv,
                     CUSTOM_BANDWIDTH={
                         'total': 1250000,
                         'reserved': 10000,
                         'min_unit': 5000,
                         'max_unit': 250000,
                         'step_size': 5000,
                         'allocation_ratio': 8.0,
                     }))

            # Add a bogus trait
            new_tree.update_traits(uuids.root, ['HW_CPU_X86_AVX',
                                                'HW_CPU_X86_AVX2',
                                                'MOTSUC_FOO'])
            self.assertRaises(
                exception.ResourceProviderSyncFailed,
                self.client.update_from_provider_tree, self.context, new_tree)
            # Placement didn't get updated
            self.assertEqual(set(['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2']),
                             self.client.get_provider_traits(
                                 self.context, uuids.root).traits)
            # ...and the root was removed from the cache
            self.assertFalse(self.client._provider_tree.exists(uuids.root))

            # Fix that problem
            new_tree.update_traits(uuids.root, ['HW_CPU_X86_AVX',
                                                'HW_CPU_X86_AVX2',
                                                'CUSTOM_FOO'])

            # Now the sync should work
            self.client.update_from_provider_tree(self.context, new_tree)
            assert_ptrees_equal()

            # Let's cause a conflict error by doing an "out-of-band" update
            gen = self.client._provider_tree.data(uuids.ssp).generation
            self.assertTrue(self.client.put(
                '/resource_providers/%s/traits' % uuids.ssp,
                {'resource_provider_generation': gen,
                 'traits': ['MISC_SHARES_VIA_AGGREGATE', 'STORAGE_DISK_HDD']},
                version='1.6'))

            # Now if we try to modify the traits, we should fail and invalidate
            # the cache...
            new_tree.update_traits(uuids.ssp, ['MISC_SHARES_VIA_AGGREGATE',
                                               'STORAGE_DISK_SSD',
                                               'CUSTOM_FAST'])
            self.assertRaises(
                exception.ResourceProviderUpdateConflict,
                self.client.update_from_provider_tree, self.context, new_tree)
            # ...but the next iteration will refresh the cache with the latest
            # generation and so the next attempt should succeed.
            self.client.update_from_provider_tree(self.context, new_tree)
            # The out-of-band change is blown away, as it should be.
            assert_ptrees_equal()

            # Let's delete some stuff
            new_tree.remove(uuids.ssp)
            self.assertFalse(new_tree.exists('ssp'))
            new_tree.remove('child1')
            self.assertFalse(new_tree.exists('child1'))
            # Removing a node removes its descendants too
            self.assertFalse(new_tree.exists('grandchild1_1'))
            self.client.update_from_provider_tree(self.context, new_tree)
            assert_ptrees_equal()

            # Remove the last provider
            new_tree.remove(uuids.root)
            self.assertEqual([], new_tree.get_provider_uuids())
            self.client.update_from_provider_tree(self.context, new_tree)
            assert_ptrees_equal()

            # Having removed the providers this way, they ought to be gone
            # from placement
            for uuid in (uuids.root, uuids.child1, uuids.grandchild1_1,
                         uuids.ssp):
                resp = self.client.get('/resource_providers/%s' % uuid)
                self.assertEqual(404, resp.status_code)

    def test_non_tree_aggregate_membership(self):
        """There are some methods of the reportclient that interact with the
        reportclient's provider_tree cache of information on a best-effort
        basis. These methods are called to add and remove members from a nova
        host aggregate and ensure that the placement API has a mirrored record
        of the resource provider's aggregate associations. We want to simulate
        this use case by invoking these methods with an empty cache and making
        sure it never gets populated (and we don't raise ValueError).
        """
        agg_uuid = uuids.agg
        with self._interceptor():
            # get_provider_tree_and_ensure_root creates a resource provider
            # record for us
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid, name=self.compute_name)
            self.assertEqual([self.compute_uuid], ptree.get_provider_uuids())
            # Now blow away the cache so we can ensure the use_cache=False
            # behavior of aggregate_{add|remove}_host correctly ignores and/or
            # doesn't attempt to populate/update it.
            self.client._provider_tree.remove(self.compute_uuid)
            self.assertEqual(
                [], self.client._provider_tree.get_provider_uuids())

            # Use the reportclient's _get_provider_aggregates() private method
            # to verify no aggregates are yet associated with this provider
            aggs = self.client._get_provider_aggregates(
                self.context, self.compute_uuid).aggregates
            self.assertEqual(set(), aggs)

            # Now associate the compute **host name** with an aggregate and
            # ensure the aggregate association is saved properly
            self.client.aggregate_add_host(
                self.context, agg_uuid, host_name=self.compute_name)

            # Check that the ProviderTree cache hasn't been modified (since
            # the aggregate_add_host() method is only called from nova-api and
            # we don't want to have a ProviderTree cache at that layer.
            self.assertEqual(
                [], self.client._provider_tree.get_provider_uuids())
            aggs = self.client._get_provider_aggregates(
                self.context, self.compute_uuid).aggregates
            self.assertEqual(set([agg_uuid]), aggs)

            # Finally, remove the association and verify it's removed in
            # placement
            self.client.aggregate_remove_host(
                self.context, agg_uuid, self.compute_name)
            self.assertEqual(
                [], self.client._provider_tree.get_provider_uuids())
            aggs = self.client._get_provider_aggregates(
                self.context, self.compute_uuid).aggregates
            self.assertEqual(set(), aggs)

            #  Try removing the same host and verify no error
            self.client.aggregate_remove_host(
                self.context, agg_uuid, self.compute_name)
            self.assertEqual(
                [], self.client._provider_tree.get_provider_uuids())

    def test_alloc_cands_smoke(self):
        """Simple call to get_allocation_candidates for version checking."""
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)
        req_spec = objects.RequestSpec(flavor=flavor, is_bfv=False)
        with self._interceptor():
            self.client.get_allocation_candidates(
                self.context, utils.ResourceRequest(req_spec))

    def _set_up_provider_tree(self):
        r"""Create two compute nodes in placement ("this" one, and another one)
        and a storage provider sharing with both.

             +-----------------------+      +------------------------+
             |uuid: self.compute_uuid|      |uuid: uuids.ssp         |
             |name: self.compute_name|      |name: 'ssp'             |
             |inv: MEMORY_MB=2048    |......|inv: DISK_GB=500        |...
             |     SRIOV_NET_VF=2    | agg1 |traits: [MISC_SHARES...]|  .
             |aggs: [uuids.agg1]     |      |aggs: [uuids.agg1]      |  . agg1
             +-----------------------+      +------------------------+  .
                    /             \                                     .
        +-------------------+  +-------------------+     +-------------------+
        |uuid: uuids.numa1  |  |uuid: uuids.numa2  |     |uuid: uuids.othercn|
        |name: 'numa1'      |  |name: 'numa2'      |     |name: 'othercn'    |
        |inv: VCPU=8        |  |inv: VCPU=8        |     |inv: VCPU=8        |
        |     CUSTOM_PCPU=8 |  |     CUSTOM_PCPU=8 |     |     MEMORY_MB=1024|
        |     SRIOV_NET_VF=4|  |     SRIOV_NET_VF=4|     |aggs: [uuids.agg1] |
        +-------------------+  +-------------------+     +-------------------+

        Must be invoked from within an _interceptor() context.

        Returns a dict, keyed by provider UUID, of the expected shape of the
        provider tree, as expected by the expected_dict param of
        assertProviderTree.
        """
        ret = {}
        # get_provider_tree_and_ensure_root creates a resource provider
        # record for us
        ptree = self.client.get_provider_tree_and_ensure_root(
            self.context, self.compute_uuid, name=self.compute_name)
        inv = dict(MEMORY_MB={'total': 2048},
                   SRIOV_NET_VF={'total': 2})
        ptree.update_inventory(self.compute_uuid, inv)
        ptree.update_aggregates(self.compute_uuid, [uuids.agg1])
        ret[self.compute_uuid] = dict(
            name=self.compute_name,
            parent_uuid=None,
            inventory=inv,
            aggregates=set([uuids.agg1]),
            traits=set()
        )

        # These are part of the compute node's tree
        ptree.new_child('numa1', self.compute_uuid, uuid=uuids.numa1)
        inv = dict(VCPU={'total': 8},
                   CUSTOM_PCPU={'total': 8},
                   SRIOV_NET_VF={'total': 4})
        ptree.update_inventory('numa1', inv)
        ret[uuids.numa1] = dict(
            name='numa1',
            parent_uuid=self.compute_uuid,
            inventory=inv,
            aggregates=set(),
            traits=set(),
        )
        ptree.new_child('numa2', self.compute_uuid, uuid=uuids.numa2)
        ptree.update_inventory('numa2', inv)
        ret[uuids.numa2] = dict(
            name='numa2',
            parent_uuid=self.compute_uuid,
            inventory=inv,
            aggregates=set(),
            traits=set(),
        )

        # A sharing provider that's not part of the compute node's tree.
        ptree.new_root('ssp', uuids.ssp)
        inv = dict(DISK_GB={'total': 500})
        ptree.update_inventory(uuids.ssp, inv)
        # Part of the shared storage aggregate
        ptree.update_aggregates(uuids.ssp, [uuids.agg1])
        ptree.update_traits(uuids.ssp, ['MISC_SHARES_VIA_AGGREGATE'])
        ret[uuids.ssp] = dict(
            name='ssp',
            parent_uuid=None,
            inventory=inv,
            aggregates=set([uuids.agg1]),
            traits=set(['MISC_SHARES_VIA_AGGREGATE'])
        )

        self.client.update_from_provider_tree(self.context, ptree)

        # Another unrelated compute node. We don't use the report client's
        # convenience methods because we don't want this guy in the cache.
        resp = self.client.post(
            '/resource_providers',
            {'uuid': uuids.othercn, 'name': 'othercn'}, version='1.20')
        resp = self.client.put(
            '/resource_providers/%s/inventories' % uuids.othercn,
            {'inventories': {'VCPU': {'total': 8},
                             'MEMORY_MB': {'total': 1024}},
             'resource_provider_generation': resp.json()['generation']})
        # Part of the shared storage aggregate
        self.client.put(
            '/resource_providers/%s/aggregates' % uuids.othercn,
            {'aggregates': [uuids.agg1],
             'resource_provider_generation':
                 resp.json()['resource_provider_generation']},
            version='1.19')

        return ret

    def assertProviderTree(self, expected_dict, actual_tree):
        # expected_dict is of the form:
        # { rp_uuid: {
        #       'parent_uuid': ...,
        #       'inventory': {...},
        #       'aggregates': set(...),
        #       'traits': set(...),
        #   }
        # }
        # actual_tree is a ProviderTree
        # Same UUIDs
        self.assertEqual(set(expected_dict),
                         set(actual_tree.get_provider_uuids()))
        for uuid, pdict in expected_dict.items():
            actual_data = actual_tree.data(uuid)
            # Fields existing on the `expected` object are the only ones we
            # care to check.
            for k, expected in pdict.items():
                # For inventories, we're only validating totals
                if k == 'inventory':
                    self.assertEqual(
                        set(expected), set(actual_data.inventory),
                        "Mismatched inventory keys for provider %s" % uuid)
                    for rc, totaldict in expected.items():
                        self.assertEqual(
                            totaldict['total'],
                            actual_data.inventory[rc]['total'],
                            "Mismatched inventory totals for provider %s" %
                            uuid)
                else:
                    self.assertEqual(expected, getattr(actual_data, k),
                                     "Mismatched %s for provider %s" %
                                     (k, uuid))

    def _set_up_provider_tree_allocs(self):
        """Create some allocations on our compute (with sharing).

        Must be invoked from within an _interceptor() context.
        """
        ret = {
            uuids.cn_inst1: {
                'allocations': {
                    self.compute_uuid: {'resources': {'MEMORY_MB': 512,
                                                      'SRIOV_NET_VF': 1}},
                    uuids.numa1: {'resources': {'VCPU': 2, 'CUSTOM_PCPU': 2}},
                    uuids.ssp: {'resources': {'DISK_GB': 100}}
                },
                'consumer_generation': None,
                'project_id': uuids.proj,
                'user_id': uuids.user,
            },
            uuids.cn_inst2: {
                'allocations': {
                    self.compute_uuid: {'resources': {'MEMORY_MB': 256}},
                    uuids.numa2: {'resources': {'CUSTOM_PCPU': 1,
                                                'SRIOV_NET_VF': 1}},
                    uuids.ssp: {'resources': {'DISK_GB': 50}}
                },
                'consumer_generation': None,
                'project_id': uuids.proj,
                'user_id': uuids.user,
            },
        }
        self.client.put('/allocations/' + uuids.cn_inst1, ret[uuids.cn_inst1],
                        version='1.28')
        self.client.put('/allocations/' + uuids.cn_inst2, ret[uuids.cn_inst2],
                        version='1.28')
        # And on the other compute (with sharing)
        self.client.put(
            '/allocations/' + uuids.othercn_inst,
            {'allocations': {
                uuids.othercn: {'resources': {'VCPU': 2, 'MEMORY_MB': 64}},
                uuids.ssp: {'resources': {'DISK_GB': 30}}
            },
                'consumer_generation': None,
                'project_id': uuids.proj,
                'user_id': uuids.user,
            },
            version='1.28')

        return ret

    def assertAllocations(self, expected, actual):
        """Compare the parts we care about in two dicts, keyed by consumer
        UUID, of allocation information.

        We don't care about comparing generations
        """
        # Same consumers
        self.assertEqual(set(expected), set(actual))
        # We're going to mess with these, to make life easier, so copy them
        expected = copy.deepcopy(expected)
        actual = copy.deepcopy(actual)
        for allocs in list(expected.values()) + list(actual.values()):
            del allocs['consumer_generation']
            for alloc in allocs['allocations'].values():
                if 'generation' in alloc:
                    del alloc['generation']
        self.assertEqual(expected, actual)

    def test_get_allocations_for_provider_tree(self):
        with self._interceptor():
            # When the provider tree cache is empty (or we otherwise supply a
            # bogus node name), we get ValueError.
            self.assertRaises(ValueError,
                              self.client.get_allocations_for_provider_tree,
                              self.context, 'bogus')

            self._set_up_provider_tree()

            # At this point, there are no allocations
            self.assertEqual({}, self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name))

            expected = self._set_up_provider_tree_allocs()

            # And now we should get all the right allocations. Note that we see
            # nothing from othercn_inst.
            actual = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            self.assertAllocations(expected, actual)

    def test_reshape(self):
        """Smoke test the report client shim for the reshaper API."""
        with self._interceptor():
            # Simulate placement API communication failure
            with mock.patch.object(
                    self.client, 'post', side_effect=kse.MissingAuthPlugin):
                self.assertRaises(kse.ClientException,
                                  self.client._reshape, self.context, {}, {})

            # Invalid payload (empty inventories) results in a 409, which the
            # report client converts to ReshapeFailed
            try:
                self.client._reshape(self.context, {}, {})
            except exception.ReshapeFailed as e:
                self.assertIn('JSON does not validate: {} does not have '
                              'enough properties', e.kwargs['error'])

            # Okay, do some real stuffs. We're just smoke-testing that we can
            # hit a good path to the API here; real testing of the API happens
            # in gabbits and via update_from_provider_tree.
            self._set_up_provider_tree()
            self._set_up_provider_tree_allocs()
            # Updating allocations bumps generations for affected providers.
            # In real life, the subsequent update_from_provider_tree will
            # bounce 409, the cache will be cleared, and the operation will be
            # retried. We don't care about any of that retry logic in the scope
            # of this test case, so just clear the cache so
            # get_provider_tree_and_ensure_root repopulates it and we avoid the
            # conflict exception.
            self.client.clear_provider_cache()

            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            inventories = {}
            for rp_uuid in ptree.get_provider_uuids():
                data = ptree.data(rp_uuid)
                # Add a new resource class to the inventories
                inventories[rp_uuid] = {
                    "inventories": dict(data.inventory,
                                        CUSTOM_FOO={'total': 10}),
                    "resource_provider_generation": data.generation
                }

            allocs = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            for alloc in allocs.values():
                for res in alloc['allocations'].values():
                    res['resources']['CUSTOM_FOO'] = 1

            resp = self.client._reshape(self.context, inventories, allocs)
            self.assertEqual(204, resp.status_code)

    def test_update_from_provider_tree_reshape(self):
        """Run update_from_provider_tree with reshaping."""
        with self._interceptor():
            exp_ptree = self._set_up_provider_tree()
            # Save a copy of this for later
            orig_exp_ptree = copy.deepcopy(exp_ptree)

            # A null reshape: no inv changes, empty allocs
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            allocs = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            self.assertProviderTree(exp_ptree, ptree)
            self.assertAllocations({}, allocs)
            self.client.update_from_provider_tree(self.context, ptree,
                                                  allocations=allocs)

            exp_allocs = self._set_up_provider_tree_allocs()
            # Save a copy of this for later
            orig_exp_allocs = copy.deepcopy(exp_allocs)
            # Updating allocations bumps generations for affected providers.
            # In real life, the subsequent update_from_provider_tree will
            # bounce 409, the cache will be cleared, and the operation will be
            # retried. We don't care about any of that retry logic in the scope
            # of this test case, so just clear the cache so
            # get_provider_tree_and_ensure_root repopulates it and we avoid the
            # conflict exception.
            self.client.clear_provider_cache()
            # Another null reshape: no inv changes, no alloc changes
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            allocs = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            self.assertProviderTree(exp_ptree, ptree)
            self.assertAllocations(exp_allocs, allocs)
            self.client.update_from_provider_tree(self.context, ptree,
                                                  allocations=allocs)

            # Now a reshape that adds an inventory item to all the providers in
            # the provider tree (i.e. the "local" ones and the shared one, but
            # not the othercn); and an allocation of that resource only for the
            # local instances, and only on providers that already have
            # allocations (i.e. the compute node and sharing provider for both
            # cn_inst*, and numa1 for cn_inst1 and numa2 for cn_inst2).
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            allocs = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            self.assertProviderTree(exp_ptree, ptree)
            self.assertAllocations(exp_allocs, allocs)
            for rp_uuid in ptree.get_provider_uuids():
                # Add a new resource class to the inventories
                ptree.update_inventory(
                    rp_uuid, dict(ptree.data(rp_uuid).inventory,
                                  CUSTOM_FOO={'total': 10}))
                exp_ptree[rp_uuid]['inventory']['CUSTOM_FOO'] = {
                    'total': 10}
            for c_uuid, alloc in allocs.items():
                for rp_uuid, res in alloc['allocations'].items():
                    res['resources']['CUSTOM_FOO'] = 1
                    exp_allocs[c_uuid]['allocations'][rp_uuid][
                        'resources']['CUSTOM_FOO'] = 1
            self.client.update_from_provider_tree(self.context, ptree,
                                                  allocations=allocs)

            # Let's do a big transform that stuffs everything back onto the
            # compute node
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            allocs = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            self.assertProviderTree(exp_ptree, ptree)
            self.assertAllocations(exp_allocs, allocs)
            cum_inv = {}
            for rp_uuid in ptree.get_provider_uuids():
                # Accumulate all the inventory amounts for each RC
                for rc, inv in ptree.data(rp_uuid).inventory.items():
                    if rc not in cum_inv:
                        cum_inv[rc] = {'total': 0}
                    cum_inv[rc]['total'] += inv['total']
                # Remove all the providers except the compute node and the
                # shared storage provider, which still has (and shall
                # retain) allocations from the "other" compute node.
                # TODO(efried): But is that right? I should be able to
                # remove the SSP from *this* tree and have it continue to
                # exist in the world. But how would ufpt distinguish?
                if rp_uuid not in (self.compute_uuid, uuids.ssp):
                    ptree.remove(rp_uuid)
            # Put the accumulated inventory onto the compute RP
            ptree.update_inventory(self.compute_uuid, cum_inv)
            # Cause trait and aggregate transformations too.
            ptree.update_aggregates(self.compute_uuid, set())
            ptree.update_traits(self.compute_uuid, ['CUSTOM_ALL_IN_ONE'])
            exp_ptree = {
                self.compute_uuid: dict(
                    parent_uuid = None,
                    inventory = cum_inv,
                    aggregates=set(),
                    traits = set(['CUSTOM_ALL_IN_ONE']),
                ),
                uuids.ssp: dict(
                    # Don't really care about the details
                    parent_uuid=None,
                ),
            }

            # Let's inject an error path test here: attempting to reshape
            # inventories without having moved their allocations should fail.
            ex = self.assertRaises(
                exception.ReshapeFailed,
                self.client.update_from_provider_tree, self.context, ptree,
                allocations=allocs)
            self.assertIn('placement.inventory.inuse', ex.format_message())

            # Move all the allocations off their existing providers and
            # onto the compute node
            for c_uuid, alloc in allocs.items():
                cum_allocs = {}
                for rp_uuid, resources in alloc['allocations'].items():
                    # Accumulate all the allocations for each RC
                    for rc, amount in resources['resources'].items():
                        if rc not in cum_allocs:
                            cum_allocs[rc] = 0
                        cum_allocs[rc] += amount
                alloc['allocations'] = {
                    # Put the accumulated allocations on the compute RP
                    self.compute_uuid: {'resources': cum_allocs}}
            exp_allocs = copy.deepcopy(allocs)
            self.client.update_from_provider_tree(self.context, ptree,
                                                  allocations=allocs)

            # Okay, let's transform back now
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            allocs = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            self.assertProviderTree(exp_ptree, ptree)
            self.assertAllocations(exp_allocs, allocs)
            for rp_uuid, data in orig_exp_ptree.items():
                if not ptree.exists(rp_uuid):
                    # This should only happen for children, because the CN
                    # and SSP are already there.
                    ptree.new_child(data['name'], data['parent_uuid'],
                                    uuid=rp_uuid)
                ptree.update_inventory(rp_uuid, data['inventory'])
                ptree.update_traits(rp_uuid, data['traits'])
                ptree.update_aggregates(rp_uuid, data['aggregates'])
            for c_uuid, orig_allocs in orig_exp_allocs.items():
                allocs[c_uuid]['allocations'] = orig_allocs['allocations']
            self.client.update_from_provider_tree(self.context, ptree,
                                                  allocations=allocs)
            ptree = self.client.get_provider_tree_and_ensure_root(
                self.context, self.compute_uuid)
            allocs = self.client.get_allocations_for_provider_tree(
                self.context, self.compute_name)
            self.assertProviderTree(orig_exp_ptree, ptree)
            self.assertAllocations(orig_exp_allocs, allocs)

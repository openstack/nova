# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

from nova import context
from nova import objects
from nova.tests.functional import integrated_helpers
from nova.virt import fake as fake_driver


class NodeRebalanceDeletedComputeNodeRaceTestCase(
    integrated_helpers.ProviderUsageBaseTestCase,
):
    """Regression test for bug 1853009 observed in Rocky & later.

    When an ironic node re-balances from one host to another, there can be a
    race where the old host deletes the orphan compute node after the new host
    has taken ownership of it which results in the new host failing to create
    the compute node and resource provider because the ResourceTracker does not
    detect a change.
    """
    # Make sure we're using the fake driver that has predictable uuids
    # for each node.
    compute_driver = 'fake.PredictableNodeUUIDDriver'

    def _assert_hypervisor_api(self, nodename, expected_host):
        # We should have one compute node shown by the API.
        hypervisors = self.api.api_get(
            '/os-hypervisors/detail'
        ).body['hypervisors']
        self.assertEqual(1, len(hypervisors), hypervisors)
        hypervisor = hypervisors[0]
        self.assertEqual(nodename, hypervisor['hypervisor_hostname'])
        self.assertEqual(expected_host, hypervisor['service']['host'])

    def _start_compute(self, host):
        host = self.start_service('compute', host)
        # Ironic compute driver has rebalances_nodes = True.
        host.manager.driver.rebalances_nodes = True
        return host

    def setUp(self):
        super(NodeRebalanceDeletedComputeNodeRaceTestCase, self).setUp()

        self.nodename = 'fake-node'
        self.ctxt = context.get_admin_context()

    @mock.patch.object(fake_driver.FakeDriver, 'is_node_deleted')
    def test_node_rebalance_deleted_compute_node_race(self, mock_delete):
        # make the fake driver allow nodes to be delete, like ironic driver
        mock_delete.return_value = True
        # Simulate a service running and then stopping. host_a runs, creates
        # fake-node, then is stopped. The fake-node compute node is destroyed.
        # This leaves a soft-deleted node in the DB.
        host_a = self._start_compute('host_a')
        host_a.manager.driver._set_nodes([self.nodename])
        host_a.manager.update_available_resource(self.ctxt)
        host_a.stop()
        cn = objects.ComputeNode.get_by_host_and_nodename(
            self.ctxt, 'host_a', self.nodename,
        )
        cn.destroy()

        self.assertEqual(0, len(objects.ComputeNodeList.get_all(self.ctxt)))

        # Now we create a new compute service to manage our node.
        host_b = self._start_compute('host_b')
        host_b.manager.driver._set_nodes([self.nodename])

        # When start_service runs, it will create a host_b ComputeNode. We want
        # to delete that and inject our fake node into the driver which will
        # be re-balanced to another host later. First assert this actually
        # exists.
        self._assert_hypervisor_api('host_b', expected_host='host_b')

        # Now run the update_available_resource periodic to register fake-node
        # and have it managed by host_b. This will also detect the "host_b"
        # node as orphaned and delete it along with its resource provider.

        # host_b[1]: Finds no compute record in RT. Tries to create one
        # (_init_compute_node).
        host_b.manager.update_available_resource(self.ctxt)
        self._assert_hypervisor_api(self.nodename, expected_host='host_b')
        # There should only be one resource provider (fake-node).
        original_rps = self._get_all_providers()
        self.assertEqual(1, len(original_rps), original_rps)
        self.assertEqual(self.nodename, original_rps[0]['name'])

        # Simulate a re-balance by restarting host_a and make it manage
        # fake-node. At this point both host_b and host_a think they own
        # fake-node.
        host_a = self._start_compute('host_a')
        host_a.manager.driver._set_nodes([self.nodename])

        # host_a[1]: Finds no compute record in RT, 'moves' existing node from
        # host_b
        host_a.manager.update_available_resource(self.ctxt)
        # Assert that fake-node was re-balanced from host_b to host_a.
        self.assertIn(
            'ComputeNode fake-node moving from host_b to host_a',
            self.stdlog.logger.output)
        self._assert_hypervisor_api(self.nodename, expected_host='host_a')

        # host_a[2]: Begins periodic update, queries compute nodes for this
        # host, finds the fake-node.
        cn = objects.ComputeNode.get_by_host_and_nodename(
            self.ctxt, 'host_a', self.nodename,
        )

        # host_b[2]: Finds no compute record in RT, 'moves' existing node from
        # host_a
        host_b.manager.update_available_resource(self.ctxt)
        # Assert that fake-node was re-balanced from host_a to host_b.
        self.assertIn(
            'ComputeNode fake-node moving from host_a to host_b',
            self.stdlog.logger.output)
        self._assert_hypervisor_api(self.nodename, expected_host='host_b')

        # Complete rebalance, as host_a realises it does not own fake-node.
        host_a.manager.driver._set_nodes([])

        # host_a[2]: Deletes orphan compute node.
        # Mock out the compute node query to simulate a race condition where
        # the list includes an orphan compute node that is newly owned by
        # host_b by the time host_a attempts to delete it.
        with mock.patch(
            'nova.compute.manager.ComputeManager._get_compute_nodes_in_db'
        ) as mock_get:
            mock_get.return_value = [cn]
            host_a.manager.update_available_resource(self.ctxt)

        # Verify that the node was almost deleted, but was saved by the host
        # check
        self.assertIn(
            'Deleting orphan compute node %s hypervisor host '
            'is fake-node, nodes are' % cn.id,
            self.stdlog.logger.output)
        self.assertIn(
            'Ignoring failure to delete orphan compute node %s on '
            'hypervisor host fake-node' % cn.id,
            self.stdlog.logger.output)
        self._assert_hypervisor_api(self.nodename, 'host_b')
        rps = self._get_all_providers()
        self.assertEqual(1, len(rps), rps)
        self.assertEqual(self.nodename, rps[0]['name'])

        # Simulate deletion of an orphan by host_a. It shouldn't happen
        # anymore, but let's assume it already did.
        cn = objects.ComputeNode.get_by_host_and_nodename(
            self.ctxt, 'host_b', self.nodename)
        cn.destroy()
        host_a.manager.rt.remove_node(cn.hypervisor_hostname)
        host_a.manager.reportclient.delete_resource_provider(
            self.ctxt, cn, cascade=True)

        # host_b[3]: Should recreate compute node and resource provider.
        host_b.manager.update_available_resource(self.ctxt)

        # Verify that the node was recreated.
        self._assert_hypervisor_api(self.nodename, 'host_b')

        # The resource provider has now been created.
        rps = self._get_all_providers()
        self.assertEqual(1, len(rps), rps)
        self.assertEqual(self.nodename, rps[0]['name'])

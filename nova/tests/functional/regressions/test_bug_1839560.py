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

from oslo_log import log as logging

from nova import context
from nova.db import api as db_api
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova import utils
from nova.virt import fake as fake_virt

LOG = logging.getLogger(__name__)


class PeriodicNodeRecreateTestCase(test.TestCase,
                                   integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1839560 introduced in Rocky.

    When an ironic node is undergoing maintenance the driver will not report
    it as an available node to the ComputeManager.update_available_resource
    periodic task. The ComputeManager will then (soft) delete a ComputeNode
    record for that no-longer-available node. If/when the ironic node is
    available again and the driver reports it, the ResourceTracker will attempt
    to create a ComputeNode record for the ironic node.

    The regression with change Ia69fabce8e7fd7de101e291fe133c6f5f5f7056a is
    that the ironic node uuid is used as the ComputeNode.uuid and there is
    a unique constraint on the ComputeNode.uuid value in the database. So
    trying to create a ComputeNode with the same uuid (after the ironic node
    comes back from being unavailable) fails with a DuplicateEntry error since
    there is a (soft) deleted version of the ComputeNode with the same uuid
    in the database.
    """
    def setUp(self):
        super(PeriodicNodeRecreateTestCase, self).setUp()
        # We need the PlacementFixture for the compute nodes to report in but
        # otherwise don't care about placement for this test.
        self.useFixture(nova_fixtures.PlacementFixture())
        # Start up the API so we can query the os-hypervisors API.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        # Make sure we're using the fake driver that has predictable uuids
        # for each node.
        self.flags(compute_driver='fake.PredictableNodeUUIDDriver')

    def test_update_available_resource_node_recreate(self):
        # First we create a compute service to manage a couple of fake nodes.
        # When start_service runs, it will create the node1 and node2
        # ComputeNodes.
        fake_virt.set_nodes(['node1', 'node2'])
        self.addCleanup(fake_virt.restore_nodes)
        compute = self.start_service('compute', 'node1')
        # Now we should have two compute nodes, make sure the hypervisors API
        # shows them.
        hypervisors = self.api.api_get('/os-hypervisors').body['hypervisors']
        self.assertEqual(2, len(hypervisors), hypervisors)
        self.assertEqual({'node1', 'node2'},
                         set([hyp['hypervisor_hostname']
                              for hyp in hypervisors]))
        # Now stub the driver to only report node1. This is making it look like
        # node2 is no longer available when update_available_resource runs.
        compute.manager.driver._nodes = ['node1']
        ctxt = context.get_admin_context()
        compute.manager.update_available_resource(ctxt)
        # node2 should have been deleted, check the logs and API.
        log = self.stdlog.logger.output
        self.assertIn('Deleting orphan compute node', log)
        self.assertIn('hypervisor host is node2', log)
        hypervisors = self.api.api_get('/os-hypervisors').body['hypervisors']
        self.assertEqual(1, len(hypervisors), hypervisors)
        self.assertEqual('node1', hypervisors[0]['hypervisor_hostname'])
        # But the node2 ComputeNode is still in the database with deleted!=0.
        with utils.temporary_mutation(ctxt, read_deleted='yes'):
            cn = objects.ComputeNode.get_by_host_and_nodename(
                ctxt, 'node1', 'node2')
            self.assertTrue(cn.deleted)
        # Now stub the driver again to report node2 as being back and run
        # the periodic task.
        compute.manager.driver._nodes = ['node1', 'node2']
        compute.manager.update_available_resource(ctxt)
        # FIXME(mriedem): This is bug 1839560 where the ResourceTracker fails
        # to create a ComputeNode for node2 because of conflicting UUIDs.
        log = self.stdlog.logger.output
        self.assertIn('Error updating resources for node node2', log)
        self.assertIn('DBDuplicateEntry', log)
        # Should still only have one reported hypervisor (node1).
        hypervisors = self.api.api_get('/os-hypervisors').body['hypervisors']
        self.assertEqual(1, len(hypervisors), hypervisors)
        # Test the workaround for bug 1839560 by archiving the deleted node2
        # compute_nodes table record which will allow the periodic to create a
        # new entry for node2. We can remove this when the bug is fixed.
        LOG.info('Archiving the database.')
        archived = db_api.archive_deleted_rows(1000)[0]
        self.assertIn('compute_nodes', archived)
        self.assertEqual(1, archived['compute_nodes'])
        with utils.temporary_mutation(ctxt, read_deleted='yes'):
            self.assertRaises(exception.ComputeHostNotFound,
                              objects.ComputeNode.get_by_host_and_nodename,
                              ctxt, 'node1', 'node2')
        # Now run the periodic again and we should have a new ComputeNode for
        # node2.
        LOG.info('Running update_available_resource which should create a new '
                 'ComputeNode record for node2.')
        compute.manager.update_available_resource(ctxt)
        hypervisors = self.api.api_get('/os-hypervisors').body['hypervisors']
        self.assertEqual(2, len(hypervisors), hypervisors)

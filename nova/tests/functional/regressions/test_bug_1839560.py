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
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova import utils

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
        self.useFixture(func_fixtures.PlacementFixture())
        # Start up the API so we can query the os-hypervisors API.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        # Make sure we're using the fake driver that has predictable uuids
        # for each node.
        self.flags(compute_driver='fake.PredictableNodeUUIDDriver')

    def test_update_available_resource_node_recreate(self):
        # First we create a compute service to manage a couple of fake nodes.
        compute = self.start_service('compute', 'node1')
        # When start_service runs, it will create the node1 ComputeNode.
        compute.manager.driver._set_nodes(['node1', 'node2'])
        # Run the update_available_resource periodic to register node2.
        ctxt = context.get_admin_context()
        compute.manager.update_available_resource(ctxt)
        # Make sure no compute nodes were orphaned or deleted.
        self.assertNotIn('Deleting orphan compute node',
                         self.stdlog.logger.output)
        # Now we should have two compute nodes, make sure the hypervisors API
        # shows them.
        hypervisors = self.api.api_get('/os-hypervisors').body['hypervisors']
        self.assertEqual(2, len(hypervisors), hypervisors)
        self.assertEqual({'node1', 'node2'},
                         set([hyp['hypervisor_hostname']
                              for hyp in hypervisors]))
        # Now stub the driver to only report node1. This is making it look like
        # node2 is no longer available when update_available_resource runs.
        compute.manager.driver._set_nodes(['node1'])
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
        compute.manager.driver._set_nodes(['node1', 'node2'])
        LOG.info('Running update_available_resource which should bring back '
                 'node2.')
        compute.manager.update_available_resource(ctxt)
        # The DBDuplicateEntry error should have been handled and resulted in
        # updating the (soft) deleted record to no longer be deleted.
        log = self.stdlog.logger.output
        self.assertNotIn('DBDuplicateEntry', log)
        # Should have two reported hypervisors again.
        hypervisors = self.api.api_get('/os-hypervisors').body['hypervisors']
        self.assertEqual(2, len(hypervisors), hypervisors)
        # Now that the node2 record was un-soft-deleted, archiving should not
        # remove any compute_nodes.
        LOG.info('Archiving the database.')
        archived = db_api.archive_deleted_rows(max_rows=1000)[0]
        self.assertNotIn('compute_nodes', archived)
        cn2 = objects.ComputeNode.get_by_host_and_nodename(
            ctxt, 'node1', 'node2')
        self.assertFalse(cn2.deleted)
        self.assertIsNone(cn2.deleted_at)
        # The node2 id and uuid should not have changed in the DB.
        self.assertEqual(cn.id, cn2.id)
        self.assertEqual(cn.uuid, cn2.uuid)

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

from nova import context
from nova.db.main import api as db
from nova import exception
from nova import objects
from nova.objects import host_mapping
from nova import test
from nova.tests import fixtures
from nova import utils


class HostMappingDiscoveryTestFail(test.TestCase):
    """Regression test for bug 2085135
    """

    def setUp(self):
        super().setUp()
        self.ctxt = context.get_admin_context()

        api_fixture = self.useFixture(fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.admin_api = api_fixture.admin_api
        self.admin_api.microversion = 'latest'

    def test_discover_host_fail_after_service_deletion(self):
        # Create compute
        host_name = "compute-1"
        service = self._start_compute(host_name)

        # Store its node uuid
        node_uuid = service.service_ref.compute_node.uuid

        # Now delete its service
        # It will delete the related compute node and host mapping
        self.admin_api.api_delete(
            '/os-services/%s' % service.service_ref.uuid)
        # Check its deletion
        self.assertRaises(exception.HostBinaryNotFound,
            db.service_get_by_host_and_binary,
            self.ctxt, host_name, 'nova-compute')

        # Check that compute node and its mappings have correctly been deleted
        with utils.temporary_mutation(self.ctxt, read_deleted='yes'):
            node = db.compute_node_get_by_nodename(self.ctxt, host_name)
            self.assertEqual(node['deleted'], node['id'])
        self.assertRaises(exception.HostMappingNotFound,
            objects.HostMapping.get_by_host,
            self.ctxt, host_name)

        # Now recreate the service and compute node by updating its resources
        # like if the services restarts
        service.manager.update_available_resource(self.ctxt)

        # At this point, service and compute come back to life
        # with the same compute uuid
        node = db.compute_node_get_by_nodename(self.ctxt, host_name)
        self.assertEqual(node['deleted'], 0)
        self.assertEqual(node['uuid'], node_uuid)

        # Bug #2085135: node should be unmapped and be discoverable
        self.assertEqual(node['mapped'], 1)
        mappings = host_mapping.discover_hosts(
            self.ctxt, status_fn=lambda m: None)
        self.assertEqual(0, len(mappings))

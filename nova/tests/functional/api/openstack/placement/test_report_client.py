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

from keystoneauth1 import session
import mock
import requests
from wsgi_intercept import interceptor

from nova.api.openstack.placement import deploy
from nova import conf
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
        self._client = session.Session(
            auth=None,
            session=request_session,
            additional_headers=headers,
        )


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

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.compute_node.ComputeNode.save')
    @mock.patch('keystoneauth1.session.Session.get_auth_headers',
                return_value={'x-auth-token': 'admin'})
    @mock.patch('keystoneauth1.session.Session.get_endpoint',
                return_value='http://localhost:80/placement')
    def test_client_report_smoke(self, mock_vbi, mock_endpoint, mock_auth,
                                 mock_cn):
        """Check things go as expected when doing the right things."""
        # TODO(cdent): We should probably also have a test that
        # tests that when allocation or inventory errors happen, we
        # are resilient.
        res_class = fields.ResourceClass.VCPU
        with interceptor.RequestsInterceptor(
                app=self.app, url=self.url):
            # When we start out there are no resource providers.
            rp = self.client._get_resource_provider(self.compute_uuid)
            self.assertIsNone(rp)

            # Now let's update status for our compute node.
            self.client.update_compute_node(self.compute_node)

            # So now we have a resource provider
            rp = self.client._get_resource_provider(self.compute_uuid)
            self.assertIsNotNone(rp)

            # We should also have an empty list set of aggregate UUID
            # associations
            pam = self.client._provider_aggregate_map
            self.assertIn(self.compute_uuid, pam)
            self.assertEqual(set(), pam[self.compute_uuid])

            # TODO(cdent): change this to use the methods built in
            # to the report client to retrieve inventory?
            inventory_url = ('/resource_providers/%s/inventories' %
                             self.compute_uuid)
            resp = self.client.get(inventory_url)
            inventory_data = resp.json()['inventories']
            self.assertEqual(self.compute_node.vcpus,
                             inventory_data[res_class]['total'])

            # Update allocations with our instance
            self.client.update_instance_allocation(
                self.compute_node, self.instance, 1)

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
                self.compute_node, self.instance, -1)

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
            self.client.update_compute_node(self.compute_node)

            # Check there's no more inventory records
            resp = self.client.get(inventory_url)
            inventory_data = resp.json()['inventories']
            self.assertEqual({}, inventory_data)

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
                              self.compute_uuid, self.compute_name, inv_data)

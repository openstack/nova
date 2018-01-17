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
from wsgi_intercept import interceptor

from nova.api.openstack.placement import deploy
from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import vm_states
from nova import conf
from nova import context
from nova import objects
from nova.objects import fields
from nova import test
from nova.tests.functional.api.openstack.placement import test_report_client
from nova.tests import uuidsentinel as uuids

CONF = conf.CONF
VCPU = fields.ResourceClass.VCPU
MEMORY_MB = fields.ResourceClass.MEMORY_MB
DISK_GB = fields.ResourceClass.DISK_GB
COMPUTE_HOST = 'compute-host'


class IronicResourceTrackerTest(test.TestCase):
    """Tests the behaviour of the resource tracker with regards to the
    transitional period between adding support for custom resource classes in
    the placement API and integrating inventory and allocation records for
    Ironic baremetal nodes with those custom resource classes.
    """

    FLAVOR_FIXTURES = {
        'CUSTOM_SMALL_IRON': objects.Flavor(
            name='CUSTOM_SMALL_IRON',
            flavorid=42,
            vcpus=4,
            memory_mb=4096,
            root_gb=1024,
            swap=0,
            ephemeral_gb=0,
            extra_specs={},
    ),
        'CUSTOM_BIG_IRON': objects.Flavor(
            name='CUSTOM_BIG_IRON',
            flavorid=43,
            vcpus=16,
            memory_mb=65536,
            root_gb=1024,
            swap=0,
            ephemeral_gb=0,
            extra_specs={},
        ),
    }

    COMPUTE_NODE_FIXTURES = {
        uuids.cn1: objects.ComputeNode(
            uuid=uuids.cn1,
            hypervisor_hostname='cn1',
            hypervisor_type='ironic',
            hypervisor_version=0,
            cpu_info="",
            host=COMPUTE_HOST,
            vcpus=4,
            vcpus_used=0,
            cpu_allocation_ratio=1.0,
            memory_mb=4096,
            memory_mb_used=0,
            ram_allocation_ratio=1.0,
            local_gb=1024,
            local_gb_used=0,
            disk_allocation_ratio=1.0,
        ),
        uuids.cn2: objects.ComputeNode(
            uuid=uuids.cn2,
            hypervisor_hostname='cn2',
            hypervisor_type='ironic',
            hypervisor_version=0,
            cpu_info="",
            host=COMPUTE_HOST,
            vcpus=4,
            vcpus_used=0,
            cpu_allocation_ratio=1.0,
            memory_mb=4096,
            memory_mb_used=0,
            ram_allocation_ratio=1.0,
            local_gb=1024,
            local_gb_used=0,
            disk_allocation_ratio=1.0,
        ),
        uuids.cn3: objects.ComputeNode(
            uuid=uuids.cn3,
            hypervisor_hostname='cn3',
            hypervisor_type='ironic',
            hypervisor_version=0,
            cpu_info="",
            host=COMPUTE_HOST,
            vcpus=16,
            vcpus_used=0,
            cpu_allocation_ratio=1.0,
            memory_mb=65536,
            memory_mb_used=0,
            ram_allocation_ratio=1.0,
            local_gb=2048,
            local_gb_used=0,
            disk_allocation_ratio=1.0,
        ),
    }

    INSTANCE_FIXTURES = {
        uuids.instance1: objects.Instance(
            uuid=uuids.instance1,
            flavor=FLAVOR_FIXTURES['CUSTOM_SMALL_IRON'],
            vm_state=vm_states.BUILDING,
            task_state=task_states.SPAWNING,
            power_state=power_state.RUNNING,
            project_id='project',
            user_id=uuids.user,
        ),
    }

    def setUp(self):
        super(IronicResourceTrackerTest, self).setUp()
        self.flags(auth_strategy='noauth2', group='api')
        self.flags(
            reserved_host_memory_mb=0,
            cpu_allocation_ratio=1.0,
            ram_allocation_ratio=1.0,
            disk_allocation_ratio=1.0,
        )

        self.ctx = context.RequestContext('user', 'project')
        self.app = lambda: deploy.loadapp(CONF)
        self.report_client = test_report_client.NoAuthReportClient()

        driver = mock.MagicMock(autospec='nova.virt.driver.ComputeDriver')
        driver.node_is_available.return_value = True
        self.driver_mock = driver
        self.rt = resource_tracker.ResourceTracker(COMPUTE_HOST, driver)
        self.rt.scheduler_client.reportclient = self.report_client
        self.rt.reportclient = self.report_client
        self.url = 'http://localhost/placement'
        self.create_fixtures()

    def create_fixtures(self):
        for flavor in self.FLAVOR_FIXTURES.values():
            flavor._context = self.ctx
            flavor.obj_set_defaults()
            flavor.create()

        # We create some compute node records in the Nova cell DB to simulate
        # data before adding integration for Ironic baremetal nodes with the
        # placement API...
        for cn in self.COMPUTE_NODE_FIXTURES.values():
            cn._context = self.ctx
            cn.obj_set_defaults()
            cn.create()

        for instance in self.INSTANCE_FIXTURES.values():
            instance._context = self.ctx
            instance.obj_set_defaults()
            instance.create()

    def placement_get_inventory(self, rp_uuid):
        url = '/resource_providers/%s/inventories' % rp_uuid
        resp = self.report_client.get(url)
        if 200 <= resp.status_code < 300:
            return resp.json()['inventories']
        else:
            return resp.status_code

    def placement_get_allocations(self, consumer_uuid):
        url = '/allocations/%s' % consumer_uuid
        resp = self.report_client.get(url)
        if 200 <= resp.status_code < 300:
            return resp.json()['allocations']
        else:
            return resp.status_code

    def placement_get_custom_rcs(self):
        url = '/resource_classes'
        resp = self.report_client.get(url)
        if 200 <= resp.status_code < 300:
            all_rcs = resp.json()['resource_classes']
            return [rc['name'] for rc in all_rcs
                    if rc['name'] not in fields.ResourceClass.STANDARD]

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    @mock.patch('nova.objects.compute_node.ComputeNode.save')
    @mock.patch('keystoneauth1.session.Session.get_auth_headers',
                return_value={'x-auth-token': 'admin'})
    @mock.patch('keystoneauth1.session.Session.get_endpoint',
                return_value='http://localhost/placement')
    def test_ironic_ocata_to_pike(self, mock_vbi, mock_endpoint, mock_auth,
            mock_cn):
        """Check that when going from an Ocata installation with Ironic having
        node's resource class attributes set, that we properly "auto-heal" the
        inventory and allocation records in the placement API to account for
        both the old-style VCPU/MEMORY_MB/DISK_GB resources as well as the new
        custom resource class from Ironic's node.resource_class attribute.
        """
        with interceptor.RequestsInterceptor(
                app=self.app, url=self.url):
            # Before the resource tracker is "initialized", we shouldn't have
            # any compute nodes in the RT's cache...
            self.assertEqual(0, len(self.rt.compute_nodes))

            # There should not be any records in the placement API since we
            # haven't yet run update_available_resource() in the RT.
            for cn in self.COMPUTE_NODE_FIXTURES.values():
                self.assertEqual(404, self.placement_get_inventory(cn.uuid))

            for inst in self.INSTANCE_FIXTURES.keys():
                self.assertEqual({}, self.placement_get_allocations(inst))

            # Nor should there be any custom resource classes in the placement
            # API, since we haven't had an Ironic node's resource class set yet
            self.assertEqual(0, len(self.placement_get_custom_rcs()))

            # Now "initialize" the resource tracker as if the compute host is a
            # Ocata host, with Ironic virt driver, but the admin has not yet
            # added a resource_class attribute to the Ironic baremetal nodes in
            # her system.
            # NOTE(jaypipes): This is what nova.compute.manager.ComputeManager
            # does when "initializing" the service...
            for cn in self.COMPUTE_NODE_FIXTURES.values():
                nodename = cn.hypervisor_hostname
                self.driver_mock.get_available_resource.return_value = {
                    'hypervisor_hostname': nodename,
                    'hypervisor_type': 'ironic',
                    'hypervisor_version': 0,
                    'vcpus': cn.vcpus,
                    'vcpus_used': cn.vcpus_used,
                    'memory_mb': cn.memory_mb,
                    'memory_mb_used': cn.memory_mb_used,
                    'local_gb': cn.local_gb,
                    'local_gb_used': cn.local_gb_used,
                    'numa_topology': None,
                    'resource_class': None,  # Act like admin hasn't set yet...
                }
                self.driver_mock.get_inventory.return_value = {
                    VCPU: {
                        'total': cn.vcpus,
                        'reserved': 0,
                        'min_unit': 1,
                        'max_unit': cn.vcpus,
                        'step_size': 1,
                        'allocation_ratio': 1.0,
                    },
                    MEMORY_MB: {
                        'total': cn.memory_mb,
                        'reserved': 0,
                        'min_unit': 1,
                        'max_unit': cn.memory_mb,
                        'step_size': 1,
                        'allocation_ratio': 1.0,
                    },
                    DISK_GB: {
                        'total': cn.local_gb,
                        'reserved': 0,
                        'min_unit': 1,
                        'max_unit': cn.local_gb,
                        'step_size': 1,
                        'allocation_ratio': 1.0,
                    },
                }
                self.rt.update_available_resource(self.ctx, nodename)

            self.assertEqual(3, len(self.rt.compute_nodes))
            # A canary just to make sure the assertion below about the custom
            # resource class being added wasn't already added somehow...
            crcs = self.placement_get_custom_rcs()
            self.assertNotIn('CUSTOM_SMALL_IRON', crcs)

            # Verify that the placement API has the "old-style" resources in
            # inventory and allocations
            for cn in self.COMPUTE_NODE_FIXTURES.values():
                inv = self.placement_get_inventory(cn.uuid)
                self.assertEqual(3, len(inv))

            # Now "spawn" an instance to the first compute node by calling the
            # RT's instance_claim().
            cn1_obj = self.COMPUTE_NODE_FIXTURES[uuids.cn1]
            cn1_nodename = cn1_obj.hypervisor_hostname
            inst = self.INSTANCE_FIXTURES[uuids.instance1]
            # Since we're pike, the scheduler would have created our
            # allocation for us. So, we can use our old update routine
            # here to mimic that before we go do the compute RT claim,
            # and then the checks below.
            self.rt.reportclient.update_instance_allocation(self.ctx,
                                                            cn1_obj,
                                                            inst,
                                                            1)
            with self.rt.instance_claim(self.ctx, inst, cn1_nodename):
                pass

            allocs = self.placement_get_allocations(inst.uuid)
            self.assertEqual(1, len(allocs))
            self.assertIn(uuids.cn1, allocs)

            resources = allocs[uuids.cn1]['resources']
            self.assertEqual(3, len(resources))
            for rc in (VCPU, MEMORY_MB, DISK_GB):
                self.assertIn(rc, resources)

            # Now we emulate the operator setting ONE of the Ironic node's
            # resource class attribute to the value of a custom resource class
            # and re-run update_available_resource(). We will expect to see the
            # inventory and allocations reset for the first compute node that
            # had an instance on it. The new inventory and allocation records
            # will be for VCPU, MEMORY_MB, DISK_GB, and also a new record for
            # the custom resource class of the Ironic node.
            self.driver_mock.get_available_resource.return_value = {
                'hypervisor_hostname': cn1_obj.hypervisor_hostname,
                'hypervisor_type': 'ironic',
                'hypervisor_version': 0,
                'vcpus': cn1_obj.vcpus,
                'vcpus_used': cn1_obj.vcpus_used,
                'memory_mb': cn1_obj.memory_mb,
                'memory_mb_used': cn1_obj.memory_mb_used,
                'local_gb': cn1_obj.local_gb,
                'local_gb_used': cn1_obj.local_gb_used,
                'numa_topology': None,
                'resource_class': 'small-iron',
            }
            self.driver_mock.get_inventory.return_value = {
                VCPU: {
                    'total': cn1_obj.vcpus,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': cn1_obj.vcpus,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
                MEMORY_MB: {
                    'total': cn1_obj.memory_mb,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': cn1_obj.memory_mb,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
                DISK_GB: {
                    'total': cn1_obj.local_gb,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': cn1_obj.local_gb,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
                'CUSTOM_SMALL_IRON': {
                    'total': 1,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 1,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            self.rt.update_available_resource(self.ctx, cn1_nodename)

            # Verify the auto-creation of the custom resource class, normalized
            # to what the placement API expects
            self.assertIn('CUSTOM_SMALL_IRON', self.placement_get_custom_rcs())

            allocs = self.placement_get_allocations(inst.uuid)
            self.assertEqual(1, len(allocs))
            self.assertIn(uuids.cn1, allocs)

            resources = allocs[uuids.cn1]['resources']
            self.assertEqual(3, len(resources))
            for rc in (VCPU, MEMORY_MB, DISK_GB):
                self.assertIn(rc, resources)

            # TODO(jaypipes): Check allocations include the CUSTOM_SMALL_IRON
            # resource class. At the moment, we do not add an allocation record
            # for the Ironic custom resource class. Once the flavor is updated
            # to store a resources:$CUSTOM_RESOURCE_CLASS=1 extra_spec key and
            # the scheduler is constructing the request_spec to actually
            # request a single amount of that custom resource class, we will
            # modify the allocation/claim to consume only the custom resource
            # class and not the VCPU, MEMORY_MB and DISK_GB.

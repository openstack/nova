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

from nova.compute import rpcapi as compute_rpcapi
from nova.conductor.tasks import migrate
from nova import objects
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests.unit.conductor.test_conductor import FakeContext
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance


class MigrationTaskTestCase(test.NoDBTestCase):
    def setUp(self):
        super(MigrationTaskTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = FakeContext(self.user_id, self.project_id)
        self.flavor = fake_flavor.fake_flavor_obj(self.context)
        self.flavor.extra_specs = {'extra_specs': 'fake'}
        inst = fake_instance.fake_db_instance(image_ref='image_ref',
                                              instance_type=self.flavor)
        inst_object = objects.Instance(
            flavor=self.flavor,
            numa_topology=None,
            pci_requests=None,
            system_metadata={'image_hw_disk_bus': 'scsi'})
        self.instance = objects.Instance._from_db_object(
            self.context, inst_object, inst, [])
        self.request_spec = objects.RequestSpec(image=objects.ImageMeta())
        self.hosts = [dict(host='host1', nodename=None, limits={})]
        self.filter_properties = {'limits': {}, 'retry': {'num_attempts': 1,
                                  'hosts': [['host1', None]]}}
        self.reservations = []
        self.clean_shutdown = True

    def _generate_task(self):
        return migrate.MigrationTask(self.context, self.instance, self.flavor,
                                     self.request_spec, self.reservations,
                                     self.clean_shutdown,
                                     compute_rpcapi.ComputeAPI(),
                                     scheduler_client.SchedulerClient())

    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def test_execute(self, prep_resize_mock, sel_dest_mock, sig_mock, az_mock):
        sel_dest_mock.return_value = self.hosts
        az_mock.return_value = 'myaz'
        task = self._generate_task()
        legacy_request_spec = self.request_spec.to_legacy_request_spec_dict()
        task.execute()

        sig_mock.assert_called_once_with(self.context, self.request_spec)
        task.scheduler_client.select_destinations.assert_called_once_with(
            self.context, self.request_spec, [self.instance.uuid])
        prep_resize_mock.assert_called_once_with(
            self.context, self.instance, legacy_request_spec['image'],
            self.flavor, self.hosts[0]['host'], self.reservations,
            request_spec=legacy_request_spec,
            filter_properties=self.filter_properties,
            node=self.hosts[0]['nodename'], clean_shutdown=self.clean_shutdown)
        az_mock.assert_called_once_with(self.context, 'host1')

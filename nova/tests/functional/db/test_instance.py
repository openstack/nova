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

from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from nova.compute import vm_states
from nova import context
from nova.db import api as db
from nova import objects
from nova import test


class InstanceObjectTestCase(test.TestCase):
    def setUp(self):
        super(InstanceObjectTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def _create_instance(self, **values):
        inst = objects.Instance(context=self.context,
                                project_id=self.context.project_id,
                                user_id=self.context.user_id)
        inst.update(values)
        inst.create()
        return inst

    def test_get_count_by_vm_state(self):
        # _create_instance() creates an instance with project_id and user_id
        # from self.context by default
        self._create_instance()
        self._create_instance(vm_state=vm_states.ACTIVE)
        self._create_instance(vm_state=vm_states.ACTIVE, project_id='foo')
        self._create_instance(vm_state=vm_states.ACTIVE, user_id='bar')
        count = objects.InstanceList.get_count_by_vm_state(
            self.context, self.context.project_id, self.context.user_id,
            vm_states.ACTIVE)
        self.assertEqual(1, count)

    def test_embedded_instance_flavor_description_is_not_persisted(self):
        """The instance.flavor.description field will not be exposed out
        of the REST API when showing server details, so we want to make
        sure the embedded instance.flavor.description is not persisted with
        the instance_extra.flavor information.
        """
        # Create a flavor with a description.
        flavorid = uuidutils.generate_uuid()
        flavor = objects.Flavor(context.get_admin_context(),
                                name=flavorid, flavorid=flavorid,
                                memory_mb=2048, vcpus=2,
                                description='do not persist me in an instance')
        flavor.create()

        # Now create the instance with that flavor.
        instance = self._create_instance(flavor=flavor)

        # Make sure the embedded flavor.description is nulled out.
        self.assertIsNone(instance.flavor.description)

        # Now set the flavor on the instance again to make sure save() does
        # not persist the flavor.description value.
        instance.flavor = flavor
        self.assertIn('flavor', list(instance.obj_what_changed()))
        instance.save()

        # Get the instance from the database since our old version is dirty.
        instance = objects.Instance.get_by_uuid(
            self.context, instance.uuid, expected_attrs=['flavor'])
        self.assertIsNone(instance.flavor.description)

    def test_populate_missing_availability_zones(self):
        # create two instances once with avz set and other not set.
        inst1 = self._create_instance(host="fake-host1")
        uuid1 = inst1.uuid
        inst2 = self._create_instance(availability_zone="fake",
                                      host="fake-host2")
        # ... and one without a host (simulating failed spawn)
        self._create_instance(host=None)

        self.assertIsNone(inst1.availability_zone)
        self.assertEqual("fake", inst2.availability_zone)
        count_all, count_hit = (objects.instance.
            populate_missing_availability_zones(self.context, 10))
        # we get only the instance whose avz was None and where host is set
        self.assertEqual(1, count_all)
        self.assertEqual(1, count_hit)
        # since instance has no avz, avz is set by get_host_availability_zone
        # to CONF.default_availability_zone i.e 'nova' which is the default
        # zone for compute services.
        inst1 = objects.Instance.get_by_uuid(self.context, uuid1)
        self.assertEqual('nova', inst1.availability_zone)

        # create an instance with avz as None on a host that has avz.
        host = 'fake-host'
        agg_meta = {'name': 'az_agg', 'uuid': uuidutils.generate_uuid(),
                    'metadata': {'availability_zone': 'nova-test'}}
        agg = objects.Aggregate(self.context, **agg_meta)
        agg.create()
        agg = objects.Aggregate.get_by_id(self.context, agg.id)
        values = {
            'binary': 'nova-compute',
            'host': host,
            'topic': 'compute',
            'disabled': False,
        }
        service = db.service_create(self.context, values)
        agg.add_host(service['host'])
        inst3 = self._create_instance(host=host)
        uuid3 = inst3.uuid
        self.assertIsNone(inst3.availability_zone)
        count_all, count_hit = (objects.instance.
            populate_missing_availability_zones(self.context, 10))
        # we get only the instance whose avz was None i.e inst3.
        self.assertEqual(1, count_all)
        self.assertEqual(1, count_hit)
        inst3 = objects.Instance.get_by_uuid(self.context, uuid3)
        self.assertEqual('nova-test', inst3.availability_zone)

    def test_get_count_by_hosts(self):
        self._create_instance(host='fake_host1')
        self._create_instance(host='fake_host1')
        self._create_instance(host='fake_host2')
        count = objects.InstanceList.get_count_by_hosts(
            self.context, hosts=['fake_host1'])
        self.assertEqual(2, count)
        count = objects.InstanceList.get_count_by_hosts(
            self.context, hosts=['fake_host2'])
        self.assertEqual(1, count)
        count = objects.InstanceList.get_count_by_hosts(
            self.context, hosts=['fake_host1', 'fake_host2'])
        self.assertEqual(3, count)

    def test_hidden_instance_not_counted(self):
        """Tests that a hidden instance is not counted against quota usage."""
        # Create an instance that is not hidden and count usage.
        instance = self._create_instance(vcpus=1, memory_mb=2048)
        counts = objects.InstanceList.get_counts(
            self.context, instance.project_id)['project']
        self.assertEqual(1, counts['instances'])
        self.assertEqual(instance.vcpus, counts['cores'])
        self.assertEqual(instance.memory_mb, counts['ram'])
        # Now hide the instance and count usage again, everything should be 0.
        instance.hidden = True
        instance.save()
        counts = objects.InstanceList.get_counts(
            self.context, instance.project_id)['project']
        self.assertEqual(0, counts['instances'])
        self.assertEqual(0, counts['cores'])
        self.assertEqual(0, counts['ram'])

    def test_numa_topology_online_migration(self):
        """Ensure legacy NUMA topology objects are reserialized to o.vo's."""
        instance = self._create_instance(host='fake-host', node='fake-node')

        legacy_topology = jsonutils.dumps({
            "cells": [
                {
                    "id": 0,
                    "cpus": "0-3",
                    "mem": {"total": 512},
                    "pagesize": 4
                },
                {
                    "id": 1,
                    "cpus": "4,5,6,7",
                    "mem": {"total": 512},
                    "pagesize": 4
                }
            ]
        })
        db.instance_extra_update_by_uuid(
            self.context, instance.uuid, {'numa_topology': legacy_topology})

        instance_db = db.instance_extra_get_by_instance_uuid(
            self.context, instance.uuid, ['numa_topology'])
        self.assertEqual(legacy_topology, instance_db['numa_topology'])
        self.assertNotIn('nova_object.name', instance_db['numa_topology'])

        # trigger online migration
        objects.InstanceList.get_by_host_and_node(
            self.context, 'fake-host', 'fake-node',
            expected_attrs=['numa_topology'])

        instance_db = db.instance_extra_get_by_instance_uuid(
            self.context, instance.uuid, ['numa_topology'])
        self.assertNotEqual(legacy_topology, instance_db['numa_topology'])
        self.assertIn('nova_object.name', instance_db['numa_topology'])

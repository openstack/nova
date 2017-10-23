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

from oslo_utils import uuidutils

from nova.compute import vm_states
from nova import context
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

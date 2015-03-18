# Copyright 2015 IBM Corp.
# All Rights Reserved.
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

from nova import objects
from nova.scheduler.filters import utils
from nova import test
from nova.tests.unit.scheduler import fakes


class TestUtils(test.NoDBTestCase):
    def setUp(self):
        super(TestUtils, self).setUp()

    def test_instance_uuids_overlap(self):
        inst1 = objects.Instance(uuid='aa')
        inst2 = objects.Instance(uuid='bb')
        instances = [inst1, inst2]
        host_state = fakes.FakeHostState('host1', 'node1', {})
        host_state.instances = {instance.uuid: instance
                                for instance in instances}
        self.assertTrue(utils.instance_uuids_overlap(host_state, ['aa']))
        self.assertFalse(utils.instance_uuids_overlap(host_state, ['zz']))

    def test_other_types_on_host(self):
        inst1 = objects.Instance(uuid='aa', instance_type_id=1)
        host_state = fakes.FakeHostState('host1', 'node1', {})
        host_state.instances = {inst1.uuid: inst1}
        self.assertFalse(utils.other_types_on_host(host_state, 1))
        self.assertTrue(utils.other_types_on_host(host_state, 2))

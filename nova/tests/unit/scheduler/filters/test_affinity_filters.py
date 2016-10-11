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

from nova import objects
from nova.scheduler.filters import affinity_filter
from nova import test
from nova.tests.unit.scheduler import fakes
from nova.tests import uuidsentinel as uuids


class TestDifferentHostFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestDifferentHostFilter, self).setUp()
        self.filt_cls = affinity_filter.DifferentHostFilter()

    def test_affinity_different_filter_passes(self):
        host = fakes.FakeHostState('host1', 'node1', {})
        inst1 = objects.Instance(uuid=uuids.instance)
        host.instances = {inst1.uuid: inst1}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=dict(different_host=['same']))
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_affinity_different_filter_fails(self):
        inst1 = objects.Instance(uuid=uuids.instance)
        host = fakes.FakeHostState('host1', 'node1', {})
        host.instances = {inst1.uuid: inst1}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=dict(different_host=[uuids.instance]))
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_affinity_different_filter_handles_none(self):
        inst1 = objects.Instance(uuid=uuids.instance)
        host = fakes.FakeHostState('host1', 'node1', {})
        host.instances = {inst1.uuid: inst1}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=None)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))


class TestSameHostFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestSameHostFilter, self).setUp()
        self.filt_cls = affinity_filter.SameHostFilter()

    def test_affinity_same_filter_passes(self):
        inst1 = objects.Instance(uuid=uuids.instance)
        host = fakes.FakeHostState('host1', 'node1', {})
        host.instances = {inst1.uuid: inst1}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=dict(same_host=[uuids.instance]))
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_affinity_same_filter_no_list_passes(self):
        host = fakes.FakeHostState('host1', 'node1', {})
        host.instances = {}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=dict(same_host=['same']))
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_affinity_same_filter_fails(self):
        inst1 = objects.Instance(uuid=uuids.instance)
        host = fakes.FakeHostState('host1', 'node1', {})
        host.instances = {inst1.uuid: inst1}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=dict(same_host=['same']))
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_affinity_same_filter_handles_none(self):
        inst1 = objects.Instance(uuid=uuids.instance)
        host = fakes.FakeHostState('host1', 'node1', {})
        host.instances = {inst1.uuid: inst1}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=None)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))


class TestSimpleCIDRAffinityFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestSimpleCIDRAffinityFilter, self).setUp()
        self.filt_cls = affinity_filter.SimpleCIDRAffinityFilter()

    def test_affinity_simple_cidr_filter_passes(self):
        host = fakes.FakeHostState('host1', 'node1', {})
        host.host_ip = '10.8.1.1'

        affinity_ip = "10.8.1.100"

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=dict(
                cidr=['/24'],
                build_near_host_ip=[affinity_ip]))

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_affinity_simple_cidr_filter_fails(self):
        host = fakes.FakeHostState('host1', 'node1', {})
        host.host_ip = '10.8.1.1'

        affinity_ip = "10.8.1.100"

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=dict(
                cidr=['/32'],
                build_near_host_ip=[affinity_ip]))

        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_affinity_simple_cidr_filter_handles_none(self):
        host = fakes.FakeHostState('host1', 'node1', {})

        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            scheduler_hints=None)

        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))


class TestGroupAffinityFilter(test.NoDBTestCase):

    def _test_group_anti_affinity_filter_passes(self, filt_cls, policy):
        host = fakes.FakeHostState('host1', 'node1', {})
        spec_obj = objects.RequestSpec(instance_group=None)
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        spec_obj = objects.RequestSpec(instance_group=objects.InstanceGroup(
            policies=['affinity']))
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        spec_obj = objects.RequestSpec(instance_group=objects.InstanceGroup(
            policies=[policy]), instance_uuid=uuids.fake)
        spec_obj.instance_group.hosts = []
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        spec_obj.instance_group.hosts = ['host2']
        self.assertTrue(filt_cls.host_passes(host, spec_obj))

    def test_group_anti_affinity_filter_passes(self):
        self._test_group_anti_affinity_filter_passes(
                affinity_filter.ServerGroupAntiAffinityFilter(),
                'anti-affinity')

    def _test_group_anti_affinity_filter_fails(self, filt_cls, policy):
        host = fakes.FakeHostState('host1', 'node1', {})
        spec_obj = objects.RequestSpec(
            instance_group=objects.InstanceGroup(policies=[policy],
                                                 hosts=['host1']),
            instance_uuid=uuids.fake)
        self.assertFalse(filt_cls.host_passes(host, spec_obj))

    def test_group_anti_affinity_filter_fails(self):
        self._test_group_anti_affinity_filter_fails(
                affinity_filter.ServerGroupAntiAffinityFilter(),
                'anti-affinity')

    def test_group_anti_affinity_filter_allows_instance_to_same_host(self):
        fake_uuid = uuids.fake
        mock_instance = objects.Instance(uuid=fake_uuid)
        host_state = fakes.FakeHostState('host1', 'node1',
                                         {}, instances=[mock_instance])
        spec_obj = objects.RequestSpec(instance_group=objects.InstanceGroup(
            policies=['anti-affinity'], hosts=['host1', 'host2']),
            instance_uuid=mock_instance.uuid)
        self.assertTrue(affinity_filter.ServerGroupAntiAffinityFilter().
                        host_passes(host_state, spec_obj))

    def _test_group_affinity_filter_passes(self, filt_cls, policy):
        host = fakes.FakeHostState('host1', 'node1', {})
        spec_obj = objects.RequestSpec(instance_group=None)
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        spec_obj = objects.RequestSpec(instance_group=objects.InstanceGroup(
            policies=['anti-affinity']))
        self.assertTrue(filt_cls.host_passes(host, spec_obj))
        spec_obj = objects.RequestSpec(instance_group=objects.InstanceGroup(
            policies=['affinity'],
            hosts=['host1']))
        self.assertTrue(filt_cls.host_passes(host, spec_obj))

    def test_group_affinity_filter_passes(self):
        self._test_group_affinity_filter_passes(
                affinity_filter.ServerGroupAffinityFilter(), 'affinity')

    def _test_group_affinity_filter_fails(self, filt_cls, policy):
        host = fakes.FakeHostState('host1', 'node1', {})
        spec_obj = objects.RequestSpec(instance_group=objects.InstanceGroup(
            policies=[policy],
            hosts=['host2']))
        self.assertFalse(filt_cls.host_passes(host, spec_obj))

    def test_group_affinity_filter_fails(self):
        self._test_group_affinity_filter_fails(
                affinity_filter.ServerGroupAffinityFilter(), 'affinity')

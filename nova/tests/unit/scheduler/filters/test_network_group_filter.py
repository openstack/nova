# Copyright 2025 Rackspace Technology, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

from nova import objects
from nova.scheduler.filters import network_group_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestNetworkGroupAffinityFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestNetworkGroupAffinityFilter, self).setUp()
        self.filt_cls = network_group_filter.NetworkGroupAffinityFilter()

    def _make_host_state(self, host, traits=None):
        host_state = fakes.FakeHostState(host, 'node', {})
        host_state.traits = traits or set()
        return host_state

    def _make_spec_obj(self, policy=None, rules=None):
        spec_obj = mock.Mock()
        if policy:
            instance_group = objects.InstanceGroup(
                policy=policy,
                _rules=rules or {},
            )
            spec_obj.instance_group = instance_group
        else:
            spec_obj.instance_group = None
        return spec_obj

    def test_passes_no_instance_group(self):
        host_state = self._make_host_state('host1')
        spec_obj = self._make_spec_obj()
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_different_policy(self):
        host_state = self._make_host_state('host1')
        spec_obj = self._make_spec_obj(policy='anti-affinity')
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_no_network_group_rule(self):
        host_state = self._make_host_state('host1')
        spec_obj = self._make_spec_obj(
            policy='network-group-affinity', rules={})
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_host_has_matching_trait(self):
        host_state = self._make_host_state(
            'host1',
            traits={'CUSTOM_NETGROUP_A1_1_NETWORK', 'CUSTOM_OTHER'})
        spec_obj = self._make_spec_obj(
            policy='network-group-affinity',
            rules={'network_group': 'a1-1-network'})
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_fails_host_missing_trait(self):
        host_state = self._make_host_state(
            'host1',
            traits={'CUSTOM_NETGROUP_B2_3_NETWORK', 'CUSTOM_OTHER'})
        spec_obj = self._make_spec_obj(
            policy='network-group-affinity',
            rules={'network_group': 'a1-1-network'})
        self.assertFalse(self.filt_cls.host_passes(host_state, spec_obj))

    def test_fails_host_no_traits(self):
        host_state = self._make_host_state('host1', traits=set())
        spec_obj = self._make_spec_obj(
            policy='network-group-affinity',
            rules={'network_group': 'a1-1-network'})
        self.assertFalse(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_cross_rack_network_group(self):
        """Test VLAN groups that span paired racks (slash in name)."""
        host_state = self._make_host_state(
            'host1',
            traits={'CUSTOM_NETGROUP_A11_12_A11_13_NETWORK'})
        spec_obj = self._make_spec_obj(
            policy='network-group-affinity',
            rules={'network_group': 'a11-12/a11-13-network'})
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_trait_conversion(self):
        """Verify the name-to-trait conversion logic."""
        self.assertEqual(
            'CUSTOM_NETGROUP_A1_1_NETWORK',
            network_group_filter._network_group_to_trait('a1-1-network'))
        self.assertEqual(
            'CUSTOM_NETGROUP_A11_12_A11_13_NETWORK',
            network_group_filter._network_group_to_trait(
                'a11-12/a11-13-network'))
        self.assertEqual(
            'CUSTOM_NETGROUP_F20_1_NETWORK',
            network_group_filter._network_group_to_trait('f20-1-network'))


class TestNetworkGroupAntiAffinityFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestNetworkGroupAntiAffinityFilter, self).setUp()
        self.filt_cls = network_group_filter.NetworkGroupAntiAffinityFilter()

    def _make_host_state(self, host, traits=None):
        host_state = fakes.FakeHostState(host, 'node', {})
        host_state.traits = traits or set()
        return host_state

    def _make_spec_obj(self, policy=None, rules=None):
        spec_obj = mock.Mock()
        if policy:
            instance_group = objects.InstanceGroup(
                policy=policy,
                _rules=rules or {},
            )
            spec_obj.instance_group = instance_group
        else:
            spec_obj.instance_group = None
        return spec_obj

    def test_passes_no_instance_group(self):
        host_state = self._make_host_state('host1')
        spec_obj = self._make_spec_obj()
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_different_policy(self):
        host_state = self._make_host_state('host1')
        spec_obj = self._make_spec_obj(policy='affinity')
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_no_network_group_rule(self):
        host_state = self._make_host_state('host1')
        spec_obj = self._make_spec_obj(
            policy='network-group-anti-affinity', rules={})
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_host_does_not_have_excluded_trait(self):
        host_state = self._make_host_state(
            'host1',
            traits={'CUSTOM_NETGROUP_B2_3_NETWORK', 'CUSTOM_OTHER'})
        spec_obj = self._make_spec_obj(
            policy='network-group-anti-affinity',
            rules={'network_group': 'a1-1-network'})
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_fails_host_has_excluded_trait(self):
        host_state = self._make_host_state(
            'host1',
            traits={'CUSTOM_NETGROUP_A1_1_NETWORK', 'CUSTOM_OTHER'})
        spec_obj = self._make_spec_obj(
            policy='network-group-anti-affinity',
            rules={'network_group': 'a1-1-network'})
        self.assertFalse(self.filt_cls.host_passes(host_state, spec_obj))

    def test_passes_host_no_traits(self):
        """Hosts with no traits pass anti-affinity (they're not in any
        network group).
        """
        host_state = self._make_host_state('host1', traits=set())
        spec_obj = self._make_spec_obj(
            policy='network-group-anti-affinity',
            rules={'network_group': 'a1-1-network'})
        self.assertTrue(self.filt_cls.host_passes(host_state, spec_obj))

    def test_fails_cross_rack_network_group(self):
        """Test anti-affinity with cross-rack VLAN group name."""
        host_state = self._make_host_state(
            'host1',
            traits={'CUSTOM_NETGROUP_A11_12_A11_13_NETWORK'})
        spec_obj = self._make_spec_obj(
            policy='network-group-anti-affinity',
            rules={'network_group': 'a11-12/a11-13-network'})
        self.assertFalse(self.filt_cls.host_passes(host_state, spec_obj))

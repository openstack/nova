# Copyright (c) 2013 Rackspace Hosting
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
"""
Tests For Scheduler Utils
"""

import mock
import six

from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova import context as nova_context
from nova import exception
from nova import objects
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_flavor
from nova.tests import uuidsentinel as uuids


class SchedulerUtilsTestCase(test.NoDBTestCase):
    """Test case for scheduler utils methods."""
    def setUp(self):
        super(SchedulerUtilsTestCase, self).setUp()
        self.context = nova_context.get_context()

    def test_build_request_spec_without_image(self):
        instance = {'uuid': uuids.instance}
        instance_type = objects.Flavor(**test_flavor.fake_flavor)

        with mock.patch.object(flavors, 'extract_flavor') as mock_extract:
            mock_extract.return_value = instance_type
            request_spec = scheduler_utils.build_request_spec(None,
                                                              [instance])
            mock_extract.assert_called_once_with({'uuid': uuids.instance})
        self.assertEqual({}, request_spec['image'])

    def test_build_request_spec_with_object(self):
        instance_type = objects.Flavor()
        instance = fake_instance.fake_instance_obj(self.context)

        with mock.patch.object(instance, 'get_flavor') as mock_get:
            mock_get.return_value = instance_type
            request_spec = scheduler_utils.build_request_spec(None,
                                                              [instance])
            mock_get.assert_called_once_with()
        self.assertIsInstance(request_spec['instance_properties'], dict)

    @mock.patch('nova.rpc.LegacyValidatingNotifier')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(objects.Instance, 'save')
    def _test_set_vm_state_and_notify(self, mock_save, mock_add, mock_notifier,
                                      request_spec, payload_request_spec):
        expected_uuid = uuids.instance
        updates = dict(vm_state='fake-vm-state')
        service = 'fake-service'
        method = 'fake-method'
        exc_info = 'exc_info'

        payload = dict(request_spec=payload_request_spec,
                       instance_properties=payload_request_spec.get(
                           'instance_properties', {}),
                       instance_id=expected_uuid,
                       state='fake-vm-state',
                       method=method,
                       reason=exc_info)
        event_type = '%s.%s' % (service, method)

        scheduler_utils.set_vm_state_and_notify(self.context,
                                                expected_uuid,
                                                service,
                                                method,
                                                updates,
                                                exc_info,
                                                request_spec)
        mock_save.assert_called_once_with()
        mock_add.assert_called_once_with(self.context, mock.ANY,
                                         exc_info, mock.ANY)
        self.assertIsInstance(mock_add.call_args[0][1], objects.Instance)
        self.assertIsInstance(mock_add.call_args[0][3], tuple)
        mock_notifier.return_value.error.assert_called_once_with(self.context,
                                                                 event_type,
                                                                 payload)

    def test_set_vm_state_and_notify_request_spec_dict(self):
        """Tests passing a legacy dict format request spec to
        set_vm_state_and_notify.
        """
        request_spec = dict(instance_properties=dict(uuid=uuids.instance))
        # The request_spec in the notification payload should be unchanged.
        self._test_set_vm_state_and_notify(
            request_spec=request_spec, payload_request_spec=request_spec)

    def test_set_vm_state_and_notify_request_spec_object(self):
        """Tests passing a RequestSpec object to set_vm_state_and_notify."""
        request_spec = objects.RequestSpec.from_primitives(
            self.context, dict(instance_properties=dict(uuid=uuids.instance)),
            filter_properties=dict())
        # The request_spec in the notification payload should be converted
        # to the legacy format.
        self._test_set_vm_state_and_notify(
            request_spec=request_spec,
            payload_request_spec=request_spec.to_legacy_request_spec_dict())

    def test_set_vm_state_and_notify_request_spec_none(self):
        """Tests passing None for the request_spec to set_vm_state_and_notify.
        """
        # The request_spec in the notification payload should be changed to
        # just an empty dict.
        self._test_set_vm_state_and_notify(
            request_spec=None, payload_request_spec={})

    def test_build_filter_properties(self):
        sched_hints = {'hint': ['over-there']}
        forced_host = 'forced-host1'
        forced_node = 'forced-node1'
        instance_type = objects.Flavor()
        filt_props = scheduler_utils.build_filter_properties(sched_hints,
                forced_host, forced_node, instance_type)
        self.assertEqual(sched_hints, filt_props['scheduler_hints'])
        self.assertEqual([forced_host], filt_props['force_hosts'])
        self.assertEqual([forced_node], filt_props['force_nodes'])
        self.assertEqual(instance_type, filt_props['instance_type'])

    def test_build_filter_properties_no_forced_host_no_force_node(self):
        sched_hints = {'hint': ['over-there']}
        forced_host = None
        forced_node = None
        instance_type = objects.Flavor()
        filt_props = scheduler_utils.build_filter_properties(sched_hints,
                forced_host, forced_node, instance_type)
        self.assertEqual(sched_hints, filt_props['scheduler_hints'])
        self.assertEqual(instance_type, filt_props['instance_type'])
        self.assertNotIn('forced_host', filt_props)
        self.assertNotIn('forced_node', filt_props)

    def _test_populate_filter_props(self, selection_obj=True,
                                    with_retry=True,
                                    force_hosts=None,
                                    force_nodes=None,
                                    no_limits=None):
        if force_hosts is None:
            force_hosts = []
        if force_nodes is None:
            force_nodes = []
        if with_retry:
            if ((len(force_hosts) == 1 and len(force_nodes) <= 1)
                 or (len(force_nodes) == 1 and len(force_hosts) <= 1)):
                filter_properties = dict(force_hosts=force_hosts,
                                         force_nodes=force_nodes)
            elif len(force_hosts) > 1 or len(force_nodes) > 1:
                filter_properties = dict(retry=dict(hosts=[]),
                                         force_hosts=force_hosts,
                                         force_nodes=force_nodes)
            else:
                filter_properties = dict(retry=dict(hosts=[]))
        else:
            filter_properties = dict()

        if no_limits:
            fake_limits = None
        else:
            fake_limits = objects.SchedulerLimits(vcpu=1, disk_gb=2,
                    memory_mb=3, numa_topology=None)
        selection = objects.Selection(service_host="fake-host",
                nodename="fake-node", limits=fake_limits)
        if not selection_obj:
            selection = selection.to_dict()
            fake_limits = fake_limits.to_dict()

        scheduler_utils.populate_filter_properties(filter_properties,
                                                   selection)

        enable_retry_force_hosts = not force_hosts or len(force_hosts) > 1
        enable_retry_force_nodes = not force_nodes or len(force_nodes) > 1
        if with_retry or enable_retry_force_hosts or enable_retry_force_nodes:
            # So we can check for 2 hosts
            scheduler_utils.populate_filter_properties(filter_properties,
                                                       selection)

        if force_hosts:
            expected_limits = None
        elif no_limits:
            expected_limits = {}
        elif isinstance(fake_limits, objects.SchedulerLimits):
            expected_limits = fake_limits.to_dict()
        else:
            expected_limits = fake_limits
        self.assertEqual(expected_limits,
                         filter_properties.get('limits'))

        if (with_retry and enable_retry_force_hosts
                       and enable_retry_force_nodes):
            self.assertEqual([['fake-host', 'fake-node'],
                              ['fake-host', 'fake-node']],
                             filter_properties['retry']['hosts'])
        else:
            self.assertNotIn('retry', filter_properties)

    def test_populate_filter_props(self):
        self._test_populate_filter_props()

    def test_populate_filter_props_host_dict(self):
        self._test_populate_filter_props(selection_obj=False)

    def test_populate_filter_props_no_retry(self):
        self._test_populate_filter_props(with_retry=False)

    def test_populate_filter_props_force_hosts_no_retry(self):
        self._test_populate_filter_props(force_hosts=['force-host'])

    def test_populate_filter_props_force_nodes_no_retry(self):
        self._test_populate_filter_props(force_nodes=['force-node'])

    def test_populate_filter_props_multi_force_hosts_with_retry(self):
        self._test_populate_filter_props(force_hosts=['force-host1',
                                                      'force-host2'])

    def test_populate_filter_props_multi_force_nodes_with_retry(self):
        self._test_populate_filter_props(force_nodes=['force-node1',
                                                      'force-node2'])

    def test_populate_filter_props_no_limits(self):
        self._test_populate_filter_props(no_limits=True)

    def test_populate_retry_exception_at_max_attempts(self):
        self.flags(max_attempts=2, group='scheduler')
        msg = 'The exception text was preserved!'
        filter_properties = dict(retry=dict(num_attempts=2, hosts=[],
                                            exc_reason=[msg]))
        nvh = self.assertRaises(exception.MaxRetriesExceeded,
                                scheduler_utils.populate_retry,
                                filter_properties, uuids.instance)
        # make sure 'msg' is a substring of the complete exception text
        self.assertIn(msg, six.text_type(nvh))

    def _check_parse_options(self, opts, sep, converter, expected):
        good = scheduler_utils.parse_options(opts,
                                             sep=sep,
                                             converter=converter)
        for item in expected:
            self.assertIn(item, good)

    def test_parse_options(self):
        # check normal
        self._check_parse_options(['foo=1', 'bar=-2.1'],
                                  '=',
                                  float,
                                  [('foo', 1.0), ('bar', -2.1)])
        # check convert error
        self._check_parse_options(['foo=a1', 'bar=-2.1'],
                                  '=',
                                  float,
                                  [('bar', -2.1)])
        # check separator missing
        self._check_parse_options(['foo', 'bar=-2.1'],
                                  '=',
                                  float,
                                  [('bar', -2.1)])
        # check key missing
        self._check_parse_options(['=5', 'bar=-2.1'],
                                  '=',
                                  float,
                                  [('bar', -2.1)])

    def test_validate_filters_configured(self):
        self.flags(enabled_filters='FakeFilter1,FakeFilter2',
                   group='filter_scheduler')
        self.assertTrue(scheduler_utils.validate_filter('FakeFilter1'))
        self.assertTrue(scheduler_utils.validate_filter('FakeFilter2'))
        self.assertFalse(scheduler_utils.validate_filter('FakeFilter3'))

    def test_validate_weighers_configured(self):
        self.flags(weight_classes=[
            'ServerGroupSoftAntiAffinityWeigher', 'FakeFilter1'],
            group='filter_scheduler')

        self.assertTrue(scheduler_utils.validate_weigher(
            'ServerGroupSoftAntiAffinityWeigher'))
        self.assertTrue(scheduler_utils.validate_weigher('FakeFilter1'))
        self.assertFalse(scheduler_utils.validate_weigher(
            'ServerGroupSoftAffinityWeigher'))

    def test_validate_weighers_configured_all_weighers(self):
        self.assertTrue(scheduler_utils.validate_weigher(
            'ServerGroupSoftAffinityWeigher'))
        self.assertTrue(scheduler_utils.validate_weigher(
            'ServerGroupSoftAntiAffinityWeigher'))

    def _create_server_group(self, policy='anti-affinity'):
        instance = fake_instance.fake_instance_obj(self.context,
                params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.name = 'pele'
        group.uuid = uuids.fake
        group.members = [instance.uuid]
        group.policy = policy
        return group

    def _get_group_details(self, group, policy=None):
        group_hosts = ['hostB']

        with test.nested(
            mock.patch.object(objects.InstanceGroup, 'get_by_instance_uuid',
                              return_value=group),
            mock.patch.object(objects.InstanceGroup, 'get_hosts',
                              return_value=['hostA']),
        ) as (get_group, get_hosts):
            scheduler_utils._SUPPORTS_ANTI_AFFINITY = None
            scheduler_utils._SUPPORTS_AFFINITY = None
            group_info = scheduler_utils._get_group_details(
                self.context, 'fake_uuid', group_hosts)
            self.assertEqual(
                (set(['hostA', 'hostB']), policy, group.members),
                group_info)

    def test_get_group_details(self):
        for policy in ['affinity', 'anti-affinity',
                       'soft-affinity', 'soft-anti-affinity']:
            group = self._create_server_group(policy)
            self._get_group_details(group, policy=policy)

    def test_get_group_details_with_no_instance_uuid(self):
        group_info = scheduler_utils._get_group_details(self.context, None)
        self.assertIsNone(group_info)

    def _get_group_details_with_filter_not_configured(self, policy):
        self.flags(enabled_filters=['fake'], group='filter_scheduler')
        self.flags(weight_classes=['fake'], group='filter_scheduler')

        instance = fake_instance.fake_instance_obj(self.context,
                params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.uuid = uuids.fake
        group.members = [instance.uuid]
        group.policy = policy

        with test.nested(
            mock.patch.object(objects.InstanceGroup, 'get_by_instance_uuid',
                              return_value=group),
        ) as (get_group,):
            scheduler_utils._SUPPORTS_ANTI_AFFINITY = None
            scheduler_utils._SUPPORTS_AFFINITY = None
            scheduler_utils._SUPPORTS_SOFT_AFFINITY = None
            scheduler_utils._SUPPORTS_SOFT_ANTI_AFFINITY = None
            self.assertRaises(exception.UnsupportedPolicyException,
                              scheduler_utils._get_group_details,
                              self.context, uuids.instance)

    def test_get_group_details_with_filter_not_configured(self):
        policies = ['anti-affinity', 'affinity',
                    'soft-affinity', 'soft-anti-affinity']
        for policy in policies:
            self._get_group_details_with_filter_not_configured(policy)

    @mock.patch.object(scheduler_utils, '_get_group_details')
    def test_setup_instance_group_in_request_spec(self, mock_ggd):
        mock_ggd.return_value = scheduler_utils.GroupDetails(
            hosts=set(['hostA', 'hostB']), policy='policy',
            members=['instance1'])
        spec = objects.RequestSpec(instance_uuid=uuids.instance)
        spec.instance_group = objects.InstanceGroup(hosts=['hostC'])

        scheduler_utils.setup_instance_group(self.context, spec)

        mock_ggd.assert_called_once_with(self.context, uuids.instance,
                                         ['hostC'])
        # Given it returns a list from a set, make sure it's sorted.
        self.assertEqual(['hostA', 'hostB'], sorted(spec.instance_group.hosts))
        self.assertEqual('policy', spec.instance_group.policy)
        self.assertEqual(['instance1'], spec.instance_group.members)

    @mock.patch.object(scheduler_utils, '_get_group_details')
    def test_setup_instance_group_with_no_group(self, mock_ggd):
        mock_ggd.return_value = None
        spec = objects.RequestSpec(instance_uuid=uuids.instance)
        spec.instance_group = objects.InstanceGroup(hosts=['hostC'])

        scheduler_utils.setup_instance_group(self.context, spec)

        mock_ggd.assert_called_once_with(self.context, uuids.instance,
                                         ['hostC'])
        # Make sure the field isn't touched by the caller.
        self.assertFalse(spec.instance_group.obj_attr_is_set('policies'))
        self.assertEqual(['hostC'], spec.instance_group.hosts)

    @mock.patch.object(scheduler_utils, '_get_group_details')
    def test_setup_instance_group_with_filter_not_configured(self, mock_ggd):
        mock_ggd.side_effect = exception.NoValidHost(reason='whatever')
        spec = {'instance_properties': {'uuid': uuids.instance}}
        spec = objects.RequestSpec(instance_uuid=uuids.instance)
        spec.instance_group = objects.InstanceGroup(hosts=['hostC'])
        self.assertRaises(exception.NoValidHost,
                          scheduler_utils.setup_instance_group,
                          self.context, spec)

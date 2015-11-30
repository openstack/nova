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
import uuid

import mock
from mox3 import mox
from oslo_config import cfg
import six

from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova import db
from nova import exception
from nova import objects
from nova import rpc
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_flavor

CONF = cfg.CONF


class SchedulerUtilsTestCase(test.NoDBTestCase):
    """Test case for scheduler utils methods."""
    def setUp(self):
        super(SchedulerUtilsTestCase, self).setUp()
        self.context = 'fake-context'

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    def test_build_request_spec_without_image(self, mock_get):
        image = None
        instance = {'uuid': 'fake-uuid'}
        instance_type = objects.Flavor(**test_flavor.fake_flavor)

        mock_get.return_value = objects.Flavor(extra_specs={})

        self.mox.StubOutWithMock(flavors, 'extract_flavor')
        flavors.extract_flavor(mox.IgnoreArg()).AndReturn(instance_type)
        self.mox.ReplayAll()

        request_spec = scheduler_utils.build_request_spec(self.context, image,
                                                          [instance])
        self.assertEqual({}, request_spec['image'])

    def test_build_request_spec_with_object(self):
        instance_type = objects.Flavor()
        instance = fake_instance.fake_instance_obj(self.context)

        with mock.patch.object(instance, 'get_flavor') as mock_get:
            mock_get.return_value = instance_type
            request_spec = scheduler_utils.build_request_spec(self.context,
                                                              None,
                                                              [instance])
            mock_get.assert_called_once_with()
        self.assertIsInstance(request_spec['instance_properties'], dict)

    @mock.patch.object(rpc, 'get_notifier', return_value=mock.Mock())
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    @mock.patch.object(objects.Instance, 'save')
    def test_set_vm_state_and_notify(self, mock_save, mock_add, mock_get):
        expected_uuid = 'fake-uuid'
        request_spec = dict(instance_properties=dict(uuid='other-uuid'))
        updates = dict(vm_state='fake-vm-state')
        service = 'fake-service'
        method = 'fake-method'
        exc_info = 'exc_info'

        payload = dict(request_spec=request_spec,
                       instance_properties=request_spec.get(
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
                                                request_spec,
                                                db)
        mock_save.assert_called_once_with()
        mock_add.assert_called_once_with(self.context, mock.ANY,
                                         exc_info, mock.ANY)
        self.assertIsInstance(mock_add.call_args[0][1], objects.Instance)
        self.assertIsInstance(mock_add.call_args[0][3], tuple)
        mock_get.return_value.error.assert_called_once_with(self.context,
                                                            event_type,
                                                            payload)

    def _test_populate_filter_props(self, host_state_obj=True,
                                    with_retry=True,
                                    force_hosts=None,
                                    force_nodes=None):
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

        if host_state_obj:
            class host_state(object):
                host = 'fake-host'
                nodename = 'fake-node'
                limits = 'fake-limits'
        else:
            host_state = dict(host='fake-host',
                              nodename='fake-node',
                              limits='fake-limits')

        scheduler_utils.populate_filter_properties(filter_properties,
                                                   host_state)

        enable_retry_force_hosts = not force_hosts or len(force_hosts) > 1
        enable_retry_force_nodes = not force_nodes or len(force_nodes) > 1
        if with_retry or enable_retry_force_hosts or enable_retry_force_nodes:
            # So we can check for 2 hosts
            scheduler_utils.populate_filter_properties(filter_properties,
                                                       host_state)

        if force_hosts:
            expected_limits = None
        else:
            expected_limits = 'fake-limits'
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
        self._test_populate_filter_props(host_state_obj=False)

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

    @mock.patch.object(scheduler_utils, '_max_attempts')
    def test_populate_retry_exception_at_max_attempts(self, _max_attempts):
        _max_attempts.return_value = 2
        msg = 'The exception text was preserved!'
        filter_properties = dict(retry=dict(num_attempts=2, hosts=[],
                                            exc_reason=[msg]))
        nvh = self.assertRaises(exception.MaxRetriesExceeded,
                                scheduler_utils.populate_retry,
                                filter_properties, 'fake-uuid')
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
        self.flags(scheduler_default_filters='FakeFilter1,FakeFilter2')
        self.assertTrue(scheduler_utils.validate_filter('FakeFilter1'))
        self.assertTrue(scheduler_utils.validate_filter('FakeFilter2'))
        self.assertFalse(scheduler_utils.validate_filter('FakeFilter3'))

    def test_validate_weighers_configured(self):
        self.flags(scheduler_weight_classes=
                   ['ServerGroupSoftAntiAffinityWeigher',
                    'FakeFilter1'])

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
        group.uuid = str(uuid.uuid4())
        group.members = [instance.uuid]
        group.policies = [policy]
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
                (set(['hostA', 'hostB']), [policy], group.members),
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
        self.flags(scheduler_default_filters=['fake'])
        self.flags(scheduler_weight_classes=['fake'])

        instance = fake_instance.fake_instance_obj(self.context,
                params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.uuid = str(uuid.uuid4())
        group.members = [instance.uuid]
        group.policies = [policy]

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
                              self.context, 'fake-uuid')

    def test_get_group_details_with_filter_not_configured(self):
        policies = ['anti-affinity', 'affinity',
                    'soft-affinity', 'soft-anti-affinity']
        for policy in policies:
            self._get_group_details_with_filter_not_configured(policy)

    @mock.patch.object(scheduler_utils, '_get_group_details')
    def test_setup_instance_group_in_filter_properties(self, mock_ggd):
        mock_ggd.return_value = scheduler_utils.GroupDetails(
            hosts=set(['hostA', 'hostB']), policies=['policy'],
            members=['instance1'])
        spec = {'instance_properties': {'uuid': 'fake-uuid'}}
        filter_props = {'group_hosts': ['hostC']}

        scheduler_utils.setup_instance_group(self.context, spec, filter_props)

        mock_ggd.assert_called_once_with(self.context, 'fake-uuid',
                                         ['hostC'])
        expected_filter_props = {'group_updated': True,
                                 'group_hosts': set(['hostA', 'hostB']),
                                 'group_policies': ['policy'],
                                 'group_members': ['instance1']}
        self.assertEqual(expected_filter_props, filter_props)

    @mock.patch.object(scheduler_utils, '_get_group_details')
    def test_setup_instance_group_with_no_group(self, mock_ggd):
        mock_ggd.return_value = None
        spec = {'instance_properties': {'uuid': 'fake-uuid'}}
        filter_props = {'group_hosts': ['hostC']}

        scheduler_utils.setup_instance_group(self.context, spec, filter_props)

        mock_ggd.assert_called_once_with(self.context, 'fake-uuid',
                                         ['hostC'])
        self.assertNotIn('group_updated', filter_props)
        self.assertNotIn('group_policies', filter_props)
        self.assertEqual(['hostC'], filter_props['group_hosts'])

    @mock.patch.object(scheduler_utils, '_get_group_details')
    def test_setup_instance_group_with_filter_not_configured(self, mock_ggd):
        mock_ggd.side_effect = exception.NoValidHost(reason='whatever')
        spec = {'instance_properties': {'uuid': 'fake-uuid'}}
        filter_props = {'group_hosts': ['hostC']}

        self.assertRaises(exception.NoValidHost,
                          scheduler_utils.setup_instance_group,
                          self.context, spec, filter_props)

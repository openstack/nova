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
import contextlib
import uuid

import mock
from mox3 import mox
from oslo_config import cfg

from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova import db
from nova import exception
from nova import notifications
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

    def test_set_vm_state_and_notify(self):
        expected_uuid = 'fake-uuid'
        request_spec = dict(instance_properties=dict(uuid='other-uuid'))
        updates = dict(vm_state='fake-vm-state')
        service = 'fake-service'
        method = 'fake-method'
        exc_info = 'exc_info'

        self.mox.StubOutWithMock(compute_utils,
                                 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(notifications, 'send_update')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.mox.StubOutWithMock(rpc, 'get_notifier')
        notifier = self.mox.CreateMockAnything()
        rpc.get_notifier(service).AndReturn(notifier)

        old_ref = 'old_ref'
        new_ref = 'new_ref'
        inst_obj = 'inst_obj'

        db.instance_update_and_get_original(
            self.context, expected_uuid, updates,
            columns_to_join=['system_metadata']).AndReturn((old_ref, new_ref))
        notifications.send_update(self.context, old_ref, inst_obj,
                                  service=service)
        compute_utils.add_instance_fault_from_exc(
                self.context,
                new_ref, exc_info, mox.IsA(tuple))

        payload = dict(request_spec=request_spec,
                       instance_properties=request_spec.get(
                           'instance_properties', {}),
                       instance_id=expected_uuid,
                       state='fake-vm-state',
                       method=method,
                       reason=exc_info)
        event_type = '%s.%s' % (service, method)
        notifier.error(self.context, event_type, payload)

        self.mox.ReplayAll()

        with mock.patch.object(objects.Instance, '_from_db_object',
                               return_value=inst_obj):
            scheduler_utils.set_vm_state_and_notify(self.context,
                                                    expected_uuid,
                                                    service,
                                                    method,
                                                    updates,
                                                    exc_info,
                                                    request_spec,
                                                    db)

    def _test_populate_filter_props(self, host_state_obj=True,
                                    with_retry=True,
                                    force_hosts=None,
                                    force_nodes=None):
        if force_hosts is None:
            force_hosts = []
        if force_nodes is None:
            force_nodes = []
        if with_retry:
            if not force_hosts and not force_nodes:
                filter_properties = dict(retry=dict(hosts=[]))
            else:
                filter_properties = dict(force_hosts=force_hosts,
                                         force_nodes=force_nodes)
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
        if with_retry and not force_hosts and not force_nodes:
            # So we can check for 2 hosts
            scheduler_utils.populate_filter_properties(filter_properties,
                                                       host_state)

        if force_hosts:
            expected_limits = None
        else:
            expected_limits = 'fake-limits'
        self.assertEqual(expected_limits,
                         filter_properties.get('limits'))

        if with_retry and not force_hosts and not force_nodes:
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

    @mock.patch.object(scheduler_utils, '_max_attempts')
    def test_populate_retry_exception_at_max_attempts(self, _max_attempts):
        _max_attempts.return_value = 2
        msg = 'The exception text was preserved!'
        filter_properties = dict(retry=dict(num_attempts=2, hosts=[],
                                            exc=[msg]))
        nvh = self.assertRaises(exception.NoValidHost,
                                scheduler_utils.populate_retry,
                                filter_properties, 'fake-uuid')
        # make sure 'msg' is a substring of the complete exception text
        self.assertIn(msg, nvh.message)

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

        with contextlib.nested(
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
                (set(['hostA', 'hostB']), [policy]),
                group_info)

    def test_get_group_details(self):
        for policy in ['affinity', 'anti-affinity']:
            group = self._create_server_group(policy)
            self._get_group_details(group, policy=policy)

    def test_get_group_details_with_no_affinity_filters(self):
        self.flags(scheduler_default_filters=['fake'])
        scheduler_utils._SUPPORTS_ANTI_AFFINITY = None
        scheduler_utils._SUPPORTS_AFFINITY = None
        group_info = scheduler_utils._get_group_details(self.context,
                                                        'fake-uuid')
        self.assertIsNone(group_info)

    def test_get_group_details_with_no_instance_uuid(self):
        self.flags(scheduler_default_filters=['fake'])
        scheduler_utils._SUPPORTS_ANTI_AFFINITY = None
        scheduler_utils._SUPPORTS_AFFINITY = None
        group_info = scheduler_utils._get_group_details(self.context, None)
        self.assertIsNone(group_info)

    def _get_group_details_with_filter_not_configured(self, policy):
        wrong_filter = {
            'affinity': 'ServerGroupAntiAffinityFilter',
            'anti-affinity': 'ServerGroupAffinityFilter',
        }
        self.flags(scheduler_default_filters=[wrong_filter[policy]])

        instance = fake_instance.fake_instance_obj(self.context,
                params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.uuid = str(uuid.uuid4())
        group.members = [instance.uuid]
        group.policies = [policy]

        with contextlib.nested(
            mock.patch.object(objects.InstanceGroup, 'get_by_instance_uuid',
                              return_value=group),
            mock.patch.object(objects.InstanceGroup, 'get_hosts',
                              return_value=['hostA']),
        ) as (get_group, get_hosts):
            scheduler_utils._SUPPORTS_ANTI_AFFINITY = None
            scheduler_utils._SUPPORTS_AFFINITY = None
            self.assertRaises(exception.UnsupportedPolicyException,
                              scheduler_utils._get_group_details,
                              self.context, 'fake-uuid')

    def test_get_group_details_with_filter_not_configured(self):
        policies = ['anti-affinity', 'affinity']
        for policy in policies:
            self._get_group_details_with_filter_not_configured(policy)

    @mock.patch.object(scheduler_utils, '_get_group_details')
    def test_setup_instance_group_in_filter_properties(self, mock_ggd):
        mock_ggd.return_value = scheduler_utils.GroupDetails(
            hosts=set(['hostA', 'hostB']), policies=['policy'])
        spec = {'instance_properties': {'uuid': 'fake-uuid'}}
        filter_props = {'group_hosts': ['hostC']}

        scheduler_utils.setup_instance_group(self.context, spec, filter_props)

        mock_ggd.assert_called_once_with(self.context, 'fake-uuid',
                                         ['hostC'])
        expected_filter_props = {'group_updated': True,
                                 'group_hosts': set(['hostA', 'hostB']),
                                 'group_policies': ['policy']}
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

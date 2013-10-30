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
import mox
from oslo.config import cfg

from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova.conductor import api as conductor_api
from nova import db
from nova import notifications
from nova import notifier as notify
from nova.scheduler import utils as scheduler_utils
from nova import test

CONF = cfg.CONF


class SchedulerUtilsTestCase(test.NoDBTestCase):
    """Test case for scheduler utils methods."""
    def setUp(self):
        super(SchedulerUtilsTestCase, self).setUp()
        self.context = 'fake-context'

    def test_build_request_spec_without_image(self):
        image = None
        instance = {'uuid': 'fake-uuid'}
        instance_type = {'flavorid': 'fake-id'}

        self.mox.StubOutWithMock(flavors, 'extract_flavor')
        self.mox.StubOutWithMock(db, 'flavor_extra_specs_get')
        flavors.extract_flavor(mox.IgnoreArg()).AndReturn(instance_type)
        db.flavor_extra_specs_get(self.context, mox.IgnoreArg()).AndReturn([])
        self.mox.ReplayAll()

        request_spec = scheduler_utils.build_request_spec(self.context, image,
                                                          [instance])
        self.assertEqual({}, request_spec['image'])

    def _test_set_vm_state_and_notify(self, request_spec,
                                      expected_uuids):
        updates = dict(vm_state='fake-vm-state')
        service = 'fake-service'
        method = 'fake-method'
        exc_info = 'exc_info'

        self.mox.StubOutWithMock(compute_utils,
                                 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(notifications, 'send_update')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.mox.StubOutWithMock(notify, 'get_notifier')
        notifier = self.mox.CreateMockAnything()
        notify.get_notifier('conductor', CONF.host).AndReturn(notifier)
        notify.get_notifier(service).AndReturn(notifier)

        old_ref = 'old_ref'
        new_ref = 'new_ref'

        for uuid in expected_uuids:
            db.instance_update_and_get_original(
                    self.context, uuid, updates).AndReturn((old_ref, new_ref))
            notifications.send_update(self.context, old_ref, new_ref,
                                      service=service)
            compute_utils.add_instance_fault_from_exc(
                    self.context,
                    mox.IsA(conductor_api.LocalAPI),
                    new_ref, exc_info, mox.IsA(tuple))

            payload = dict(request_spec=request_spec,
                           instance_properties=request_spec.get(
                               'instance_properties', {}),
                           instance_id=uuid,
                           state='fake-vm-state',
                           method=method,
                           reason=exc_info)
            event_type = '%s.%s' % (service, method)
            notifier.error(self.context, event_type, payload)

        self.mox.ReplayAll()

        scheduler_utils.set_vm_state_and_notify(self.context,
                                                service,
                                                method,
                                                updates,
                                                exc_info,
                                                request_spec,
                                                db)

    def test_set_vm_state_and_notify_rs_uuids(self):
        expected_uuids = ['1', '2', '3']
        request_spec = dict(instance_uuids=expected_uuids)
        self._test_set_vm_state_and_notify(request_spec, expected_uuids)

    def test_set_vm_state_and_notify_uuid_from_instance_props(self):
        expected_uuids = ['fake-uuid']
        request_spec = dict(instance_properties=dict(uuid='fake-uuid'))
        self._test_set_vm_state_and_notify(request_spec, expected_uuids)

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

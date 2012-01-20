# Copyright (c) 2011 Openstack, LLC
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
Tests For HostManager
"""

import datetime

from nova import db
from nova import exception
from nova import log as logging
from nova.scheduler import host_manager
from nova import test
from nova.tests.scheduler import fakes
from nova import utils


class ComputeFilterClass1(object):
    def host_passes(self, *args, **kwargs):
        pass


class ComputeFilterClass2(object):
    def host_passes(self, *args, **kwargs):
        pass


class HostManagerTestCase(test.TestCase):
    """Test case for HostManager class"""

    def setUp(self):
        super(HostManagerTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()

    def test_choose_host_filters_not_found(self):
        self.flags(default_host_filters='ComputeFilterClass3')
        self.host_manager.filter_classes = [ComputeFilterClass1,
                ComputeFilterClass2]
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                self.host_manager._choose_host_filters, None)

    def test_choose_host_filters(self):
        self.flags(default_host_filters=['ComputeFilterClass2'])
        self.host_manager.filter_classes = [ComputeFilterClass1,
                ComputeFilterClass2]

        # Test 'compute' returns 1 correct function
        filter_fns = self.host_manager._choose_host_filters(None)
        self.assertEqual(len(filter_fns), 1)
        self.assertEqual(filter_fns[0].__func__,
                ComputeFilterClass2.host_passes.__func__)

    def test_filter_hosts(self):
        topic = 'fake_topic'

        filters = ['fake-filter1', 'fake-filter2']
        fake_host1 = host_manager.HostState('host1', topic)
        fake_host2 = host_manager.HostState('host2', topic)
        hosts = [fake_host1, fake_host2]
        filter_properties = 'fake_properties'

        self.mox.StubOutWithMock(self.host_manager,
                '_choose_host_filters')
        self.mox.StubOutWithMock(fake_host1, 'passes_filters')
        self.mox.StubOutWithMock(fake_host2, 'passes_filters')

        self.host_manager._choose_host_filters(None).AndReturn(filters)
        fake_host1.passes_filters(filters, filter_properties).AndReturn(
                False)
        fake_host2.passes_filters(filters, filter_properties).AndReturn(
                True)

        self.mox.ReplayAll()
        filtered_hosts = self.host_manager.filter_hosts(hosts,
                filter_properties, filters=None)
        self.mox.VerifyAll()
        self.assertEqual(len(filtered_hosts), 1)
        self.assertEqual(filtered_hosts[0], fake_host2)

    def test_update_service_capabilities(self):
        service_states = self.host_manager.service_states
        self.assertDictMatch(service_states, {})
        self.mox.StubOutWithMock(utils, 'utcnow')
        utils.utcnow().AndReturn(31337)
        utils.utcnow().AndReturn(31338)
        utils.utcnow().AndReturn(31339)

        host1_compute_capabs = dict(free_memory=1234, host_memory=5678,
                timestamp=1)
        host1_volume_capabs = dict(free_disk=4321, timestamp=1)
        host2_compute_capabs = dict(free_memory=8756, timestamp=1)

        self.mox.ReplayAll()
        self.host_manager.update_service_capabilities('compute', 'host1',
                host1_compute_capabs)
        self.host_manager.update_service_capabilities('volume', 'host1',
                host1_volume_capabs)
        self.host_manager.update_service_capabilities('compute', 'host2',
                host2_compute_capabs)
        self.mox.VerifyAll()

        # Make sure dictionary isn't re-assigned
        self.assertEqual(self.host_manager.service_states, service_states)
        # Make sure original dictionary wasn't copied
        self.assertEqual(host1_compute_capabs['timestamp'], 1)

        host1_compute_capabs['timestamp'] = 31337
        host1_volume_capabs['timestamp'] = 31338
        host2_compute_capabs['timestamp'] = 31339

        expected = {'host1': {'compute': host1_compute_capabs,
                              'volume': host1_volume_capabs},
                    'host2': {'compute': host2_compute_capabs}}
        self.assertDictMatch(service_states, expected)

    def test_host_service_caps_stale(self):
        self.flags(periodic_interval=5)

        host1_compute_capabs = dict(free_memory=1234, host_memory=5678,
                timestamp=datetime.datetime.fromtimestamp(3000))
        host1_volume_capabs = dict(free_disk=4321,
                timestamp=datetime.datetime.fromtimestamp(3005))
        host2_compute_capabs = dict(free_memory=8756,
                timestamp=datetime.datetime.fromtimestamp(3010))

        service_states = {'host1': {'compute': host1_compute_capabs,
                                    'volume': host1_volume_capabs},
                          'host2': {'compute': host2_compute_capabs}}

        self.host_manager.service_states = service_states

        self.mox.StubOutWithMock(utils, 'utcnow')
        utils.utcnow().AndReturn(datetime.datetime.fromtimestamp(3020))
        utils.utcnow().AndReturn(datetime.datetime.fromtimestamp(3020))
        utils.utcnow().AndReturn(datetime.datetime.fromtimestamp(3020))

        self.mox.ReplayAll()
        res1 = self.host_manager.host_service_caps_stale('host1', 'compute')
        res2 = self.host_manager.host_service_caps_stale('host1', 'volume')
        res3 = self.host_manager.host_service_caps_stale('host2', 'compute')
        self.mox.VerifyAll()

        self.assertEqual(res1, True)
        self.assertEqual(res2, False)
        self.assertEqual(res3, False)

    def test_delete_expired_host_services(self):
        host1_compute_capabs = dict(free_memory=1234, host_memory=5678,
                timestamp=datetime.datetime.fromtimestamp(3000))
        host1_volume_capabs = dict(free_disk=4321,
                timestamp=datetime.datetime.fromtimestamp(3005))
        host2_compute_capabs = dict(free_memory=8756,
                timestamp=datetime.datetime.fromtimestamp(3010))

        service_states = {'host1': {'compute': host1_compute_capabs,
                                    'volume': host1_volume_capabs},
                          'host2': {'compute': host2_compute_capabs}}
        self.host_manager.service_states = service_states

        to_delete = {'host1': {'volume': host1_volume_capabs},
                     'host2': {'compute': host2_compute_capabs}}

        self.host_manager.delete_expired_host_services(to_delete)
        # Make sure dictionary isn't re-assigned
        self.assertEqual(self.host_manager.service_states, service_states)

        expected = {'host1': {'compute': host1_compute_capabs}}
        self.assertEqual(service_states, expected)

    def test_get_service_capabilities(self):
        host1_compute_capabs = dict(free_memory=1000, host_memory=5678,
                timestamp=datetime.datetime.fromtimestamp(3000))
        host1_volume_capabs = dict(free_disk=4321,
                timestamp=datetime.datetime.fromtimestamp(3005))
        host2_compute_capabs = dict(free_memory=8756,
                timestamp=datetime.datetime.fromtimestamp(3010))
        host2_volume_capabs = dict(free_disk=8756,
                enabled=False,
                timestamp=datetime.datetime.fromtimestamp(3010))
        host3_compute_capabs = dict(free_memory=1234, host_memory=4000,
                timestamp=datetime.datetime.fromtimestamp(3010))
        host3_volume_capabs = dict(free_disk=2000,
                timestamp=datetime.datetime.fromtimestamp(3010))

        service_states = {'host1': {'compute': host1_compute_capabs,
                                    'volume': host1_volume_capabs},
                          'host2': {'compute': host2_compute_capabs,
                                    'volume': host2_volume_capabs},
                          'host3': {'compute': host3_compute_capabs,
                                    'volume': host3_volume_capabs}}
        self.host_manager.service_states = service_states

        info = {'called': 0}

        # This tests with 1 volume disabled (host2), and 1 volume node
        # as stale (host1)
        def _fake_host_service_caps_stale(host, service):
            info['called'] += 1
            if host == 'host1':
                if service == 'compute':
                    return False
                elif service == 'volume':
                    return True
            elif host == 'host2':
                # Shouldn't get here for 'volume' because the service
                # is disabled
                self.assertEqual(service, 'compute')
                return False
            self.assertEqual(host, 'host3')
            return False

        self.stubs.Set(self.host_manager, 'host_service_caps_stale',
                _fake_host_service_caps_stale)

        self.mox.StubOutWithMock(self.host_manager,
                'delete_expired_host_services')
        self.host_manager.delete_expired_host_services({'host1': ['volume']})

        self.mox.ReplayAll()
        result = self.host_manager.get_service_capabilities()
        self.mox.VerifyAll()

        self.assertEqual(info['called'], 5)

        # only 1 volume node active == 'host3', so min/max is 2000
        expected = {'volume_free_disk': (2000, 2000),
                    'compute_host_memory': (4000, 5678),
                    'compute_free_memory': (1000, 8756)}

        self.assertDictMatch(result, expected)

    def test_get_all_host_states(self):
        self.flags(reserved_host_memory_mb=512,
                reserved_host_disk_mb=1024)

        context = 'fake_context'
        topic = 'compute'

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        self.mox.StubOutWithMock(logging, 'warn')
        self.mox.StubOutWithMock(db, 'instance_get_all')

        db.compute_node_get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # Invalid service
        logging.warn("No service for compute ID 5")
        db.instance_get_all(context).AndReturn(fakes.INSTANCES)

        self.mox.ReplayAll()
        host_states = self.host_manager.get_all_host_states(context, topic)
        self.mox.VerifyAll()

        self.assertEqual(len(host_states), 4)
        # Check that .service is set properly
        for i in xrange(4):
            compute_node = fakes.COMPUTE_NODES[i]
            host = compute_node['service']['host']
            self.assertEqual(host_states[host].service,
                    compute_node['service'])
        self.assertEqual(host_states['host1'].free_ram_mb, 0)
        # 511GB
        self.assertEqual(host_states['host1'].free_disk_mb, 523264)
        self.assertEqual(host_states['host2'].free_ram_mb, 512)
        # 1023GB
        self.assertEqual(host_states['host2'].free_disk_mb, 1047552)
        self.assertEqual(host_states['host3'].free_ram_mb, 2560)
        # 3071GB
        self.assertEqual(host_states['host3'].free_disk_mb, 3144704)
        self.assertEqual(host_states['host4'].free_ram_mb, 7680)
        # 8191GB
        self.assertEqual(host_states['host4'].free_disk_mb, 8387584)


class HostStateTestCase(test.TestCase):
    """Test case for HostState class"""

    def setUp(self):
        super(HostStateTestCase, self).setUp()

    # update_from_compute_node() and consume_from_instance() are tested
    # in HostManagerTestCase.test_get_all_host_states()

    def test_host_state_passes_filters_passes(self):
        fake_host = host_manager.HostState('host1', 'compute')
        filter_properties = {}

        cls1 = ComputeFilterClass1()
        cls2 = ComputeFilterClass2()
        self.mox.StubOutWithMock(cls1, 'host_passes')
        self.mox.StubOutWithMock(cls2, 'host_passes')
        filter_fns = [cls1.host_passes, cls2.host_passes]

        cls1.host_passes(fake_host, filter_properties).AndReturn(True)
        cls2.host_passes(fake_host, filter_properties).AndReturn(True)

        self.mox.ReplayAll()
        result = fake_host.passes_filters(filter_fns, filter_properties)
        self.mox.VerifyAll()
        self.assertTrue(result)

    def test_host_state_passes_filters_passes_with_ignore(self):
        fake_host = host_manager.HostState('host1', 'compute')
        filter_properties = {'ignore_hosts': ['host2']}

        cls1 = ComputeFilterClass1()
        cls2 = ComputeFilterClass2()
        self.mox.StubOutWithMock(cls1, 'host_passes')
        self.mox.StubOutWithMock(cls2, 'host_passes')
        filter_fns = [cls1.host_passes, cls2.host_passes]

        cls1.host_passes(fake_host, filter_properties).AndReturn(True)
        cls2.host_passes(fake_host, filter_properties).AndReturn(True)

        self.mox.ReplayAll()
        result = fake_host.passes_filters(filter_fns, filter_properties)
        self.mox.VerifyAll()
        self.assertTrue(result)

    def test_host_state_passes_filters_fails(self):
        fake_host = host_manager.HostState('host1', 'compute')
        filter_properties = {}

        cls1 = ComputeFilterClass1()
        cls2 = ComputeFilterClass2()
        self.mox.StubOutWithMock(cls1, 'host_passes')
        self.mox.StubOutWithMock(cls2, 'host_passes')
        filter_fns = [cls1.host_passes, cls2.host_passes]

        cls1.host_passes(fake_host, filter_properties).AndReturn(False)
        # cls2.host_passes() not called because of short circuit

        self.mox.ReplayAll()
        result = fake_host.passes_filters(filter_fns, filter_properties)
        self.mox.VerifyAll()
        self.assertFalse(result)

    def test_host_state_passes_filters_fails_from_ignore(self):
        fake_host = host_manager.HostState('host1', 'compute')
        filter_properties = {'ignore_hosts': ['host1']}

        cls1 = ComputeFilterClass1()
        cls2 = ComputeFilterClass2()
        self.mox.StubOutWithMock(cls1, 'host_passes')
        self.mox.StubOutWithMock(cls2, 'host_passes')
        filter_fns = [cls1.host_passes, cls2.host_passes]

        # cls[12].host_passes() not called because of short circuit
        # with matching host to ignore

        self.mox.ReplayAll()
        result = fake_host.passes_filters(filter_fns, filter_properties)
        self.mox.VerifyAll()
        self.assertFalse(result)

    def test_host_state_passes_filters_skipped_from_force(self):
        fake_host = host_manager.HostState('host1', 'compute')
        filter_properties = {'force_hosts': ['host1']}

        cls1 = ComputeFilterClass1()
        cls2 = ComputeFilterClass2()
        self.mox.StubOutWithMock(cls1, 'host_passes')
        self.mox.StubOutWithMock(cls2, 'host_passes')
        filter_fns = [cls1.host_passes, cls2.host_passes]

        # cls[12].host_passes() not called because of short circuit
        # with matching host to force

        self.mox.ReplayAll()
        result = fake_host.passes_filters(filter_fns, filter_properties)
        self.mox.VerifyAll()
        self.assertTrue(result)

# Copyright 2010 United States Government as represented by the
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
Tests For ZoneManager
"""

import datetime
import mox

from nova import context
from nova import db
from nova import flags
from nova import service
from nova import test
from nova import rpc
from nova import utils
from nova.auth import manager as auth_manager
from nova.scheduler import zone_manager

FLAGS = flags.FLAGS


class FakeZone:
    """Represents a fake zone from the db"""
    def __init__(self, *args, **kwargs):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)


def exploding_novaclient(zone):
    """Used when we want to simulate a novaclient call failing."""
    raise Exception("kaboom")


class ZoneManagerTestCase(test.TestCase):
    """Test case for zone manager"""
    def test_ping(self):
        zm = zone_manager.ZoneManager()
        self.mox.StubOutWithMock(zm, '_refresh_from_db')
        self.mox.StubOutWithMock(zm, '_poll_zones')
        zm._refresh_from_db(mox.IgnoreArg())
        zm._poll_zones(mox.IgnoreArg())

        self.mox.ReplayAll()
        zm.ping(None)
        self.mox.VerifyAll()

    def test_refresh_from_db_new(self):
        zm = zone_manager.ZoneManager()

        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([
               FakeZone(id=1, api_url='http://foo.com', username='user1',
                    password='pass1'),
            ])

        self.assertEquals(len(zm.zone_states), 0)

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 1)
        self.assertEquals(zm.zone_states[1].username, 'user1')

    def test_service_capabilities(self):
        zm = zone_manager.ZoneManager()
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, {})

        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(1, 1), svc1_b=(2, 2)))

        zm.update_service_capabilities("svc1", "host1", dict(a=2, b=3))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(2, 2), svc1_b=(3, 3)))

        zm.update_service_capabilities("svc1", "host2", dict(a=20, b=30))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(2, 20), svc1_b=(3, 30)))

        zm.update_service_capabilities("svc10", "host1", dict(a=99, b=99))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(2, 20), svc1_b=(3, 30),
                                     svc10_a=(99, 99), svc10_b=(99, 99)))

        zm.update_service_capabilities("svc1", "host3", dict(c=5))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(2, 20), svc1_b=(3, 30),
                                     svc1_c=(5, 5), svc10_a=(99, 99),
                                     svc10_b=(99, 99)))

    def test_refresh_from_db_replace_existing(self):
        zm = zone_manager.ZoneManager()
        zone_state = zone_manager.ZoneState()
        zone_state.update_credentials(FakeZone(id=1, api_url='http://foo.com',
                        username='user1', password='pass1'))
        zm.zone_states[1] = zone_state

        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([
               FakeZone(id=1, api_url='http://foo.com', username='user2',
                    password='pass2'),
            ])

        self.assertEquals(len(zm.zone_states), 1)

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 1)
        self.assertEquals(zm.zone_states[1].username, 'user2')

    def test_refresh_from_db_missing(self):
        zm = zone_manager.ZoneManager()
        zone_state = zone_manager.ZoneState()
        zone_state.update_credentials(FakeZone(id=1, api_url='http://foo.com',
                        username='user1', password='pass1'))
        zm.zone_states[1] = zone_state

        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([])

        self.assertEquals(len(zm.zone_states), 1)

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 0)

    def test_refresh_from_db_add_and_delete(self):
        zm = zone_manager.ZoneManager()
        zone_state = zone_manager.ZoneState()
        zone_state.update_credentials(FakeZone(id=1, api_url='http://foo.com',
                        username='user1', password='pass1'))
        zm.zone_states[1] = zone_state

        self.mox.StubOutWithMock(db, 'zone_get_all')

        db.zone_get_all(mox.IgnoreArg()).AndReturn([
               FakeZone(id=2, api_url='http://foo.com', username='user2',
                    password='pass2'),
            ])
        self.assertEquals(len(zm.zone_states), 1)

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 1)
        self.assertEquals(zm.zone_states[2].username, 'user2')

    def test_poll_zone(self):
        self.mox.StubOutWithMock(zone_manager, '_call_novaclient')
        zone_manager._call_novaclient(mox.IgnoreArg()).AndReturn(
                        dict(name='zohan', capabilities='hairdresser'))

        zone_state = zone_manager.ZoneState()
        zone_state.update_credentials(FakeZone(id=2,
                       api_url='http://foo.com', username='user2',
                       password='pass2'))
        zone_state.attempt = 1

        self.mox.ReplayAll()
        zone_manager._poll_zone(zone_state)
        self.mox.VerifyAll()
        self.assertEquals(zone_state.attempt, 0)
        self.assertEquals(zone_state.name, 'zohan')

    def test_poll_zone_fails(self):
        self.stubs.Set(zone_manager, "_call_novaclient", exploding_novaclient)

        zone_state = zone_manager.ZoneState()
        zone_state.update_credentials(FakeZone(id=2,
                       api_url='http://foo.com', username='user2',
                       password='pass2'))
        zone_state.attempt = FLAGS.zone_failures_to_offline - 1

        self.mox.ReplayAll()
        zone_manager._poll_zone(zone_state)
        self.mox.VerifyAll()
        self.assertEquals(zone_state.attempt, 3)
        self.assertFalse(zone_state.is_active)
        self.assertEquals(zone_state.name, None)

    def test_host_service_caps_stale_no_stale_service(self):
        zm = zone_manager.ZoneManager()

        # services just updated capabilities
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc2", "host1", dict(a=3, b=4))
        self.assertFalse(zm.host_service_caps_stale("host1", "svc1"))
        self.assertFalse(zm.host_service_caps_stale("host1", "svc2"))

    def test_host_service_caps_stale_all_stale_services(self):
        zm = zone_manager.ZoneManager()
        expiry_time = (FLAGS.periodic_interval * 3) + 1

        # Both services became stale
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc2", "host1", dict(a=3, b=4))
        time_future = utils.utcnow() + datetime.timedelta(seconds=expiry_time)
        utils.set_time_override(time_future)
        self.assertTrue(zm.host_service_caps_stale("host1", "svc1"))
        self.assertTrue(zm.host_service_caps_stale("host1", "svc2"))
        utils.clear_time_override()

    def test_host_service_caps_stale_one_stale_service(self):
        zm = zone_manager.ZoneManager()
        expiry_time = (FLAGS.periodic_interval * 3) + 1

        # One service became stale
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc2", "host1", dict(a=3, b=4))
        caps = zm.service_states["host1"]["svc1"]
        caps["timestamp"] = utils.utcnow() - \
                               datetime.timedelta(seconds=expiry_time)
        self.assertTrue(zm.host_service_caps_stale("host1", "svc1"))
        self.assertFalse(zm.host_service_caps_stale("host1", "svc2"))

    def test_delete_expired_host_services_del_one_service(self):
        zm = zone_manager.ZoneManager()

        # Delete one service in a host
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc2", "host1", dict(a=3, b=4))
        stale_host_services = {"host1": ["svc1"]}
        zm.delete_expired_host_services(stale_host_services)
        self.assertFalse("svc1" in zm.service_states["host1"])
        self.assertTrue("svc2" in zm.service_states["host1"])

    def test_delete_expired_host_services_del_all_hosts(self):
        zm = zone_manager.ZoneManager()

        # Delete all services in a host
        zm.update_service_capabilities("svc2", "host1", dict(a=3, b=4))
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        stale_host_services = {"host1": ["svc1", "svc2"]}
        zm.delete_expired_host_services(stale_host_services)
        self.assertFalse("host1" in zm.service_states)

    def test_delete_expired_host_services_del_one_service_per_host(self):
        zm = zone_manager.ZoneManager()

        # Delete one service per host
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc1", "host2", dict(a=3, b=4))
        stale_host_services = {"host1": ["svc1"], "host2": ["svc1"]}
        zm.delete_expired_host_services(stale_host_services)
        self.assertFalse("host1" in zm.service_states)
        self.assertFalse("host2" in zm.service_states)

    def test_get_zone_capabilities_one_host(self):
        zm = zone_manager.ZoneManager()

        # Service capabilities recent
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(1, 1), svc1_b=(2, 2)))

    def test_get_zone_capabilities_expired_host(self):
        zm = zone_manager.ZoneManager()
        expiry_time = (FLAGS.periodic_interval * 3) + 1

        # Service capabilities stale
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        time_future = utils.utcnow() + datetime.timedelta(seconds=expiry_time)
        utils.set_time_override(time_future)
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, {})
        utils.clear_time_override()

    def test_get_zone_capabilities_multiple_hosts(self):
        zm = zone_manager.ZoneManager()

        # Both host service capabilities recent
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc1", "host2", dict(a=3, b=4))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(1, 3), svc1_b=(2, 4)))

    def test_get_zone_capabilities_one_stale_host(self):
        zm = zone_manager.ZoneManager()
        expiry_time = (FLAGS.periodic_interval * 3) + 1

        # One host service capabilities become stale
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc1", "host2", dict(a=3, b=4))
        serv_caps = zm.service_states["host1"]["svc1"]
        serv_caps["timestamp"] = utils.utcnow() - \
                               datetime.timedelta(seconds=expiry_time)
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(3, 3), svc1_b=(4, 4)))

    def test_get_zone_capabilities_multiple_service_per_host(self):
        zm = zone_manager.ZoneManager()

        # Multiple services per host
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc1", "host2", dict(a=3, b=4))
        zm.update_service_capabilities("svc2", "host1", dict(a=5, b=6))
        zm.update_service_capabilities("svc2", "host2", dict(a=7, b=8))
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(1, 3), svc1_b=(2, 4),
                                     svc2_a=(5, 7), svc2_b=(6, 8)))

    def test_get_zone_capabilities_one_stale_service_per_host(self):
        zm = zone_manager.ZoneManager()
        expiry_time = (FLAGS.periodic_interval * 3) + 1

        # Two host services among four become stale
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc1", "host2", dict(a=3, b=4))
        zm.update_service_capabilities("svc2", "host1", dict(a=5, b=6))
        zm.update_service_capabilities("svc2", "host2", dict(a=7, b=8))
        serv_caps_1 = zm.service_states["host1"]["svc2"]
        serv_caps_1["timestamp"] = utils.utcnow() - \
                               datetime.timedelta(seconds=expiry_time)
        serv_caps_2 = zm.service_states["host2"]["svc1"]
        serv_caps_2["timestamp"] = utils.utcnow() - \
                               datetime.timedelta(seconds=expiry_time)
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(1, 1), svc1_b=(2, 2),
                                     svc2_a=(7, 7), svc2_b=(8, 8)))

    def test_get_zone_capabilities_three_stale_host_services(self):
        zm = zone_manager.ZoneManager()
        expiry_time = (FLAGS.periodic_interval * 3) + 1

        # Three host services among four become stale
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc1", "host2", dict(a=3, b=4))
        zm.update_service_capabilities("svc2", "host1", dict(a=5, b=6))
        zm.update_service_capabilities("svc2", "host2", dict(a=7, b=8))
        serv_caps_1 = zm.service_states["host1"]["svc2"]
        serv_caps_1["timestamp"] = utils.utcnow() - \
                               datetime.timedelta(seconds=expiry_time)
        serv_caps_2 = zm.service_states["host2"]["svc1"]
        serv_caps_2["timestamp"] = utils.utcnow() - \
                               datetime.timedelta(seconds=expiry_time)
        serv_caps_3 = zm.service_states["host2"]["svc2"]
        serv_caps_3["timestamp"] = utils.utcnow() - \
                               datetime.timedelta(seconds=expiry_time)
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, dict(svc1_a=(1, 1), svc1_b=(2, 2)))

    def test_get_zone_capabilities_all_stale_host_services(self):
        zm = zone_manager.ZoneManager()
        expiry_time = (FLAGS.periodic_interval * 3) + 1

        # All the host services  become stale
        zm.update_service_capabilities("svc1", "host1", dict(a=1, b=2))
        zm.update_service_capabilities("svc1", "host2", dict(a=3, b=4))
        zm.update_service_capabilities("svc2", "host1", dict(a=5, b=6))
        zm.update_service_capabilities("svc2", "host2", dict(a=7, b=8))
        time_future = utils.utcnow() + datetime.timedelta(seconds=expiry_time)
        utils.set_time_override(time_future)
        caps = zm.get_zone_capabilities(None)
        self.assertEquals(caps, {})

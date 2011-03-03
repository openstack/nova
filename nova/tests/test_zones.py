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
import novaclient

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

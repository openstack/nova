# Copyright 2010 United States Government as represented by the
# All Rights Reserved.
# Copyright 2011 OpenStack LLC
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

import mox

from nova import db
from nova import flags
from nova.scheduler import zone_manager
from nova import test

FLAGS = flags.FLAGS


def _create_zone(zone_id=1, name=None, api_url=None, username=None):
    if api_url is None:
        api_url = "http://foo.com"
    if username is None:
        username = "user1"
    if name is None:
        name = "child1"
    return dict(id=zone_id, name=name, api_url=api_url,
            username=username, password="pass1", weight_offset=0.0,
            weight_scale=1.0)


def exploding_novaclient(zone):
    """Used when we want to simulate a novaclient call failing."""
    raise Exception("kaboom")


class ZoneManagerTestCase(test.TestCase):
    """Test case for zone manager"""

    zone_manager_cls = zone_manager.ZoneManager
    zone_state_cls = zone_manager.ZoneState

    def setUp(self):
        super(ZoneManagerTestCase, self).setUp()
        self.zone_manager = self.zone_manager_cls()

    def _create_zone_state(self, zone_id=1, name=None, api_url=None,
            username=None):
        zone = self.zone_state_cls()
        zone.zone_info = _create_zone(zone_id, name, api_url, username)
        return zone

    def test_update(self):
        zm = self.zone_manager
        self.mox.StubOutWithMock(zm, '_refresh_from_db')
        self.mox.StubOutWithMock(zm, '_poll_zones')
        zm._refresh_from_db(mox.IgnoreArg())
        zm._poll_zones()

        self.mox.ReplayAll()
        zm.update(None)
        self.mox.VerifyAll()

    def test_refresh_from_db_new(self):
        zone = _create_zone(zone_id=1, username='user1')
        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([zone])

        zm = self.zone_manager
        self.assertEquals(len(zm.zone_states), 0)

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 1)
        self.assertIn(1, zm.zone_states)
        self.assertEquals(zm.zone_states[1].zone_info['username'], 'user1')

    def test_refresh_from_db_replace_existing(self):
        zone_state = self._create_zone_state(zone_id=1, username='user1')
        zm = self.zone_manager
        zm.zone_states[1] = zone_state

        zone = _create_zone(zone_id=1, username='user2')
        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([zone])
        self.assertEquals(len(zm.zone_states), 1)

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 1)
        self.assertEquals(zm.zone_states[1].zone_info['username'], 'user2')

    def test_refresh_from_db_missing(self):
        zone_state = self._create_zone_state(zone_id=1, username='user1')
        zm = self.zone_manager
        zm.zone_states[1] = zone_state

        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([])

        self.assertEquals(len(zm.zone_states), 1)

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 0)

    def test_refresh_from_db_add(self):
        zone_state = self._create_zone_state(zone_id=1, username='user1')
        zm = self.zone_manager
        zm.zone_states[1] = zone_state

        zone1 = _create_zone(zone_id=1, username='user1')
        zone2 = _create_zone(zone_id=2, username='user2')
        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([zone1, zone2])

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 2)
        self.assertIn(1, zm.zone_states)
        self.assertIn(2, zm.zone_states)
        self.assertEquals(zm.zone_states[1].zone_info['username'], 'user1')
        self.assertEquals(zm.zone_states[2].zone_info['username'], 'user2')

    def test_refresh_from_db_add_and_delete(self):
        zone_state = self._create_zone_state(zone_id=1, username='user1')
        zm = self.zone_manager
        zm.zone_states[1] = zone_state

        zone2 = _create_zone(zone_id=2, username='user2')
        self.mox.StubOutWithMock(db, 'zone_get_all')
        db.zone_get_all(mox.IgnoreArg()).AndReturn([zone2])

        self.mox.ReplayAll()
        zm._refresh_from_db(None)
        self.mox.VerifyAll()

        self.assertEquals(len(zm.zone_states), 1)
        self.assertIn(2, zm.zone_states)
        self.assertEquals(zm.zone_states[2].zone_info['username'], 'user2')

    def test_poll_zone(self):
        zone_state = self._create_zone_state(zone_id=1, name='child1')
        zone_state.attempt = 1

        self.mox.StubOutWithMock(zone_state, 'call_novaclient')
        zone_state.call_novaclient().AndReturn(
                dict(name=zone_state.zone_info['name'],
                        hairdresser='dietz'))
        self.assertDictMatch(zone_state.capabilities, {})

        self.mox.ReplayAll()
        zone_state.poll()
        self.mox.VerifyAll()
        self.assertEquals(zone_state.attempt, 0)
        self.assertDictMatch(zone_state.capabilities,
                dict(hairdresser='dietz'))
        self.assertTrue(zone_state.is_active)

    def test_poll_zones_with_failure(self):
        zone_state = self._create_zone_state(zone_id=1)
        zone_state.attempt = FLAGS.zone_failures_to_offline - 1

        self.mox.StubOutWithMock(zone_state, 'call_novaclient')
        zone_state.call_novaclient().AndRaise(Exception('foo'))

        self.mox.ReplayAll()
        zone_state.poll()
        self.mox.VerifyAll()
        self.assertEquals(zone_state.attempt, 3)
        self.assertFalse(zone_state.is_active)

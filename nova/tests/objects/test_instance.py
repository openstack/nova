#    Copyright 2013 IBM Corp.
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

import datetime
import iso8601
import netaddr

from nova import context
from nova import db
from nova.objects import instance
from nova.openstack.common import timeutils
from nova.tests.api.openstack import fakes
from nova.tests.objects import test_objects


class _TestInstanceObject(object):
    @property
    def fake_instance(self):
        fake_instance = fakes.stub_instance(id=2,
                                            access_ipv4='1.2.3.4',
                                            access_ipv6='::1')
        fake_instance['scheduled_at'] = None
        fake_instance['terminated_at'] = None
        fake_instance['deleted_at'] = None
        fake_instance['created_at'] = None
        fake_instance['updated_at'] = None
        fake_instance['launched_at'] = (
            fake_instance['launched_at'].replace(
                tzinfo=iso8601.iso8601.Utc(), microsecond=0))
        return fake_instance

    def test_datetime_deserialization(self):
        red_letter_date = timeutils.parse_isotime(
            timeutils.isotime(datetime.datetime(1955, 11, 5)))
        inst = instance.Instance()
        inst.uuid = 'fake-uuid'
        inst.launched_at = red_letter_date
        primitive = inst.obj_to_primitive()
        expected = {'nova_object.name': 'Instance',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.0',
                    'nova_object.data':
                        {'uuid': 'fake-uuid',
                         'launched_at': '1955-11-05T00:00:00Z'},
                    'nova_object.changes': ['uuid', 'launched_at']}
        self.assertEqual(primitive, expected)
        inst2 = instance.Instance.obj_from_primitive(primitive)
        self.assertTrue(isinstance(inst2.launched_at,
                        datetime.datetime))
        self.assertEqual(inst2.launched_at, red_letter_date)

    def test_ip_deserialization(self):
        inst = instance.Instance()
        inst.uuid = 'fake-uuid'
        inst.access_ip_v4 = '1.2.3.4'
        inst.access_ip_v6 = '::1'
        primitive = inst.obj_to_primitive()
        expected = {'nova_object.name': 'Instance',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.0',
                    'nova_object.data':
                        {'uuid': 'fake-uuid',
                         'access_ip_v4': '1.2.3.4',
                         'access_ip_v6': '::1'},
                    'nova_object.changes': ['uuid', 'access_ip_v6',
                                            'access_ip_v4']}
        self.assertEqual(primitive, expected)
        inst2 = instance.Instance.obj_from_primitive(primitive)
        self.assertTrue(isinstance(inst2.access_ip_v4, netaddr.IPAddress))
        self.assertTrue(isinstance(inst2.access_ip_v6, netaddr.IPAddress))
        self.assertEqual(inst2.access_ip_v4, netaddr.IPAddress('1.2.3.4'))
        self.assertEqual(inst2.access_ip_v6, netaddr.IPAddress('::1'))

    def test_get_without_expected(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(ctxt, 'uuid', []).AndReturn(self.fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(ctxt, uuid='uuid')
        # Make sure these weren't loaded
        self.assertFalse(hasattr(inst, '_metadata'))
        self.assertFalse(hasattr(inst, '_system_metadata'))
        self.assertRemotes()

    def test_get_with_expected(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(
            ctxt, 'uuid',
            ['metadata', 'system_metadata']).AndReturn(self.fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(
            ctxt, uuid='uuid', expected_attrs=['metadata', 'system_metadata'])
        self.assertTrue(hasattr(inst, '_metadata'))
        self.assertTrue(hasattr(inst, '_system_metadata'))
        self.assertRemotes()

    def test_load(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_uuid = self.fake_instance['uuid']
        db.instance_get_by_uuid(ctxt, fake_uuid, []).AndReturn(
            self.fake_instance)
        fake_inst2 = dict(self.fake_instance,
                          system_metadata=[{'key': 'foo', 'value': 'bar'}])
        db.instance_get_by_uuid(ctxt, fake_uuid, ['system_metadata']
                                ).AndReturn(fake_inst2)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(ctxt, uuid=fake_uuid)
        self.assertFalse(hasattr(inst, '_system_metadata'))
        sys_meta = inst.system_metadata
        self.assertEqual(sys_meta, {'foo': 'bar'})
        self.assertTrue(hasattr(inst, '_system_metadata'))
        # Make sure we don't run load again
        sys_meta2 = inst.system_metadata
        self.assertEqual(sys_meta2, {'foo': 'bar'})
        self.assertRemotes()

    def test_get_remote(self):
        # isotime doesn't have microseconds and is always UTC
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_instance = self.fake_instance
        db.instance_get_by_uuid(ctxt, 'fake-uuid', []).AndReturn(
            fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(ctxt, uuid='fake-uuid')
        self.assertEqual(inst.id, fake_instance['id'])
        self.assertEqual(inst.launched_at, fake_instance['launched_at'])
        self.assertEqual(str(inst.access_ip_v4),
                         fake_instance['access_ip_v4'])
        self.assertEqual(str(inst.access_ip_v6),
                         fake_instance['access_ip_v6'])
        self.assertRemotes()

    def test_refresh(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_uuid = self.fake_instance['uuid']
        db.instance_get_by_uuid(ctxt, fake_uuid, []).AndReturn(
            dict(self.fake_instance, host='orig-host'))
        db.instance_get_by_uuid(ctxt, fake_uuid, []).AndReturn(
            dict(self.fake_instance, host='new-host'))
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(ctxt, uuid=fake_uuid)
        self.assertEqual(inst.host, 'orig-host')
        inst.refresh()
        self.assertEqual(inst.host, 'new-host')
        self.assertRemotes()

    def test_save(self):
        ctxt = context.get_admin_context()
        fake_inst = dict(self.fake_instance, host='oldhost')
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        db.instance_get_by_uuid(ctxt, fake_uuid, []).AndReturn(fake_inst)
        db.instance_update_and_get_original(
            ctxt, fake_uuid, {'user_data': 'foo'}).AndReturn(
                (fake_inst, dict(fake_inst, host='newhost')))
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(ctxt, uuid=fake_uuid)
        inst.user_data = 'foo'
        inst.save()
        self.assertEqual(inst.host, 'newhost')


class TestInstanceObject(test_objects._LocalTest,
                         _TestInstanceObject):
    pass


class TestRemoteInstanceObject(test_objects._RemoteTest,
                               _TestInstanceObject):
    pass

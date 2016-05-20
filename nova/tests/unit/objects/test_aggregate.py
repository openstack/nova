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

import mock
from oslo_utils import timeutils

from nova import db
from nova import exception
from nova.objects import aggregate
from nova.tests.unit import fake_notifier
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel


NOW = timeutils.utcnow().replace(microsecond=0)
fake_aggregate = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'uuid': uuidsentinel.fake_aggregate,
    'name': 'fake-aggregate',
    'hosts': ['foo', 'bar'],
    'metadetails': {'this': 'that'},
    }

SUBS = {'metadata': 'metadetails'}


class _TestAggregateObject(object):
    def test_get_by_id(self):
        self.mox.StubOutWithMock(db, 'aggregate_get')
        db.aggregate_get(self.context, 123).AndReturn(fake_aggregate)
        self.mox.ReplayAll()
        agg = aggregate.Aggregate.get_by_id(self.context, 123)
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

    @mock.patch('nova.objects.Aggregate.save')
    @mock.patch('nova.db.aggregate_get')
    def test_load_allocates_uuid(self, mock_get, mock_save):
        fake_agg = dict(fake_aggregate)
        del fake_agg['uuid']
        mock_get.return_value = fake_agg
        uuid = uuidsentinel.aggregate
        with mock.patch('oslo_utils.uuidutils.generate_uuid') as mock_g:
            mock_g.return_value = uuid
            obj = aggregate.Aggregate.get_by_id(self.context, 123)
            mock_g.assert_called_once_with()
            self.assertEqual(uuid, obj.uuid)
            mock_save.assert_called_once_with()

    def test_create(self):
        self.mox.StubOutWithMock(db, 'aggregate_create')
        db.aggregate_create(self.context, {'name': 'foo',
                                           'uuid': uuidsentinel.fake_agg},
                            metadata={'one': 'two'}).AndReturn(fake_aggregate)
        self.mox.ReplayAll()
        agg = aggregate.Aggregate(context=self.context)
        agg.name = 'foo'
        agg.metadata = {'one': 'two'}
        agg.uuid = uuidsentinel.fake_agg
        agg.create()
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

    def test_recreate_fails(self):
        self.mox.StubOutWithMock(db, 'aggregate_create')
        db.aggregate_create(self.context, {'name': 'foo',
                                           'uuid': uuidsentinel.fake_agg},
                            metadata={'one': 'two'}).AndReturn(fake_aggregate)
        self.mox.ReplayAll()
        agg = aggregate.Aggregate(context=self.context)
        agg.name = 'foo'
        agg.metadata = {'one': 'two'}
        agg.uuid = uuidsentinel.fake_agg
        agg.create()
        self.assertRaises(exception.ObjectActionError, agg.create)

    def test_save(self):
        self.mox.StubOutWithMock(db, 'aggregate_update')
        db.aggregate_update(self.context, 123, {'name': 'baz'}).AndReturn(
            fake_aggregate)
        self.mox.ReplayAll()
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.name = 'baz'
        agg.save()
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

    def test_save_and_create_no_hosts(self):
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.hosts = ['foo', 'bar']
        self.assertRaises(exception.ObjectActionError,
                          agg.create)
        self.assertRaises(exception.ObjectActionError,
                          agg.save)

    def test_update_metadata(self):
        self.mox.StubOutWithMock(db, 'aggregate_metadata_delete')
        self.mox.StubOutWithMock(db, 'aggregate_metadata_add')
        db.aggregate_metadata_delete(self.context, 123, 'todelete')
        db.aggregate_metadata_add(self.context, 123, {'toadd': 'myval'})
        self.mox.ReplayAll()
        fake_notifier.NOTIFICATIONS = []
        agg = aggregate.Aggregate()
        agg._context = self.context
        agg.id = 123
        agg.metadata = {'foo': 'bar'}
        agg.obj_reset_changes()
        agg.update_metadata({'todelete': None, 'toadd': 'myval'})
        self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('aggregate.updatemetadata.start', msg.event_type)
        self.assertEqual({'todelete': None, 'toadd': 'myval'},
                         msg.payload['meta_data'])
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual('aggregate.updatemetadata.end', msg.event_type)
        self.assertEqual({'todelete': None, 'toadd': 'myval'},
                         msg.payload['meta_data'])
        self.assertEqual({'foo': 'bar', 'toadd': 'myval'}, agg.metadata)

    def test_destroy(self):
        self.mox.StubOutWithMock(db, 'aggregate_delete')
        db.aggregate_delete(self.context, 123)
        self.mox.ReplayAll()
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.destroy()

    def test_add_host(self):
        self.mox.StubOutWithMock(db, 'aggregate_host_add')
        db.aggregate_host_add(self.context, 123, 'bar'
                              ).AndReturn({'host': 'bar'})
        self.mox.ReplayAll()
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo']
        agg._context = self.context
        agg.add_host('bar')
        self.assertEqual(agg.hosts, ['foo', 'bar'])

    def test_delete_host(self):
        self.mox.StubOutWithMock(db, 'aggregate_host_delete')
        db.aggregate_host_delete(self.context, 123, 'foo')
        self.mox.ReplayAll()
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo', 'bar']
        agg._context = self.context
        agg.delete_host('foo')
        self.assertEqual(agg.hosts, ['bar'])

    def test_availability_zone(self):
        agg = aggregate.Aggregate()
        agg.metadata = {'availability_zone': 'foo'}
        self.assertEqual('foo', agg.availability_zone)

    def test_get_all(self):
        self.mox.StubOutWithMock(db, 'aggregate_get_all')
        db.aggregate_get_all(self.context).AndReturn([fake_aggregate])
        self.mox.ReplayAll()
        aggs = aggregate.AggregateList.get_all(self.context)
        self.assertEqual(1, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)

    def test_by_host(self):
        self.mox.StubOutWithMock(db, 'aggregate_get_by_host')
        db.aggregate_get_by_host(self.context, 'fake-host', key=None,
                                 ).AndReturn([fake_aggregate])
        self.mox.ReplayAll()
        aggs = aggregate.AggregateList.get_by_host(self.context, 'fake-host')
        self.assertEqual(1, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)

    @mock.patch('nova.db.aggregate_get_by_metadata_key')
    def test_get_by_metadata_key(self, get_by_metadata_key):
        get_by_metadata_key.return_value = [fake_aggregate]
        aggs = aggregate.AggregateList.get_by_metadata_key(
            self.context, 'this')
        self.assertEqual(1, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)

    @mock.patch('nova.db.aggregate_get_by_metadata_key')
    def test_get_by_metadata_key_and_hosts_no_match(self, get_by_metadata_key):
        get_by_metadata_key.return_value = [fake_aggregate]
        aggs = aggregate.AggregateList.get_by_metadata_key(
            self.context, 'this', hosts=['baz'])
        self.assertEqual(0, len(aggs))

    @mock.patch('nova.db.aggregate_get_by_metadata_key')
    def test_get_by_metadata_key_and_hosts_match(self, get_by_metadata_key):
        get_by_metadata_key.return_value = [fake_aggregate]
        aggs = aggregate.AggregateList.get_by_metadata_key(
            self.context, 'this', hosts=['foo', 'bar'])
        self.assertEqual(1, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)


class TestAggregateObject(test_objects._LocalTest,
                          _TestAggregateObject):
    pass


class TestRemoteAggregateObject(test_objects._RemoteTest,
                                _TestAggregateObject):
    pass

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
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
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

fake_api_aggregate = {
    'created_at': NOW,
    'updated_at': None,
    'id': 123,
    'uuid': uuidsentinel.fake_aggregate,
    'name': 'fake-aggregate',
    'hosts': ['foo', 'bar'],
    'metadetails': {'this': 'that'},
    }

SUBS = {'metadata': 'metadetails'}

fake_db_aggregate_values = {'name': 'fake_aggregate'}

fake_db_aggregate_metadata = {'fake_key1': 'fake_value1',
                              'fake_key2': 'fake_value2',
                              'availability_zone': 'fake_avail_zone'}

fake_db_aggregate_hosts = ['foo.openstack.org']


@db_api.api_context_manager.writer
def _create_aggregate(context, values=fake_db_aggregate_values,
                               metadata=fake_db_aggregate_metadata):
    aggregate = api_models.Aggregate()
    aggregate.update(values)
    aggregate.save(context.session)

    if metadata:
        for key, value in metadata.items():
            aggregate_metadata = api_models.AggregateMetadata()
            aggregate_metadata.update({'key': key,
                                       'value': value,
                                       'aggregate_id': aggregate['id']})
            aggregate_metadata.save(context.session)

    return aggregate


@db_api.api_context_manager.writer
def _create_aggregate_with_hosts(context, values=fake_db_aggregate_values,
                                          metadata=fake_db_aggregate_metadata,
                                          hosts=fake_db_aggregate_hosts):
    aggregate = _create_aggregate(context, values, metadata)
    for host in hosts:
        host_model = api_models.AggregateHost()
        host_model.update({'host': host,
                           'aggregate_id': aggregate.id})
        host_model.save(context.session)

    return aggregate


class _TestAggregateObject(object):
    def test_aggregate_get_from_db(self):
        result = _create_aggregate_with_hosts(self.context)
        expected = aggregate._aggregate_get_from_db(self.context, result['id'])
        self.assertEqual(fake_db_aggregate_hosts, expected.hosts)
        self.assertEqual(fake_db_aggregate_metadata, expected['metadetails'])

    def test_aggregate_get_from_db_raise_not_found(self):
        aggregate_id = 5
        self.assertRaises(exception.AggregateNotFound,
                          aggregate._aggregate_get_from_db,
                          self.context, aggregate_id)

    def test_aggregate_get_all_from_db(self):
        for c in range(3):
            _create_aggregate(self.context,
                              values={'name': 'fake_aggregate_%d' % c})
        results = aggregate._get_all_from_db(self.context)
        self.assertEqual(len(results), 3)

    def test_aggregate_get_by_host_from_db(self):
        _create_aggregate_with_hosts(self.context,
                                     values={'name': 'fake_aggregate_1'},
                                     hosts=['host.1.openstack.org'])
        _create_aggregate_with_hosts(self.context,
                                     values={'name': 'fake_aggregate_2'},
                                     hosts=['host.1.openstack.org'])
        _create_aggregate(self.context,
                          values={'name': 'no_host_aggregate'})
        rh1 = aggregate._get_all_from_db(self.context)
        rh2 = aggregate._get_by_host_from_db(self.context,
                                             'host.1.openstack.org')
        self.assertEqual(3, len(rh1))
        self.assertEqual(2, len(rh2))

    def test_aggregate_get_by_host_with_key_from_db(self):
        ah1 = _create_aggregate_with_hosts(self.context,
                                           values={'name': 'fake_aggregate_1'},
                                           metadata={'goodkey': 'good'},
                                           hosts=['host.1.openstack.org'])
        _create_aggregate_with_hosts(self.context,
                                     values={'name': 'fake_aggregate_2'},
                                     hosts=['host.1.openstack.org'])
        rh1 = aggregate._get_by_host_from_db(self.context,
                                             'host.1.openstack.org',
                                             key='goodkey')
        self.assertEqual(1, len(rh1))
        self.assertEqual(ah1['id'], rh1[0]['id'])

    def test_aggregate_get_by_metadata_key_from_db(self):
        _create_aggregate(self.context,
                          values={'name': 'aggregate_1'},
                          metadata={'goodkey': 'good'})
        _create_aggregate(self.context,
                          values={'name': 'aggregate_2'},
                          metadata={'goodkey': 'bad'})
        _create_aggregate(self.context,
                          values={'name': 'aggregate_3'},
                          metadata={'badkey': 'good'})
        rl1 = aggregate._get_by_metadata_key_from_db(self.context,
                                                     key='goodkey')
        self.assertEqual(2, len(rl1))

    @mock.patch('nova.objects.aggregate._aggregate_get_from_db')
    @mock.patch('nova.db.aggregate_get')
    def test_get_by_id_from_api(self, mock_get, mock_get_api):
        mock_get_api.return_value = fake_api_aggregate

        agg = aggregate.Aggregate.get_by_id(self.context, 123)
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

        mock_get_api.assert_called_once_with(self.context, 123)
        mock_get.assert_not_called()

    @mock.patch('nova.objects.aggregate._aggregate_get_from_db')
    @mock.patch('nova.db.aggregate_get')
    def test_get_by_id(self, mock_get, mock_get_api):
        mock_get_api.side_effect = exception.AggregateNotFound(
                aggregate_id=123)
        mock_get.return_value = fake_aggregate

        agg = aggregate.Aggregate.get_by_id(self.context, 123)
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

        mock_get_api.assert_called_once_with(self.context, 123)
        mock_get.assert_called_once_with(self.context, 123)

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

    @mock.patch('nova.objects.aggregate._get_all_from_db')
    @mock.patch('nova.db.aggregate_get_all')
    def test_get_all(self, mock_get_all, mock_api_get_all):
        mock_get_all.return_value = [fake_aggregate]
        mock_api_get_all.return_value = [fake_api_aggregate]
        aggs = aggregate.AggregateList.get_all(self.context)
        self.assertEqual(2, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)
        self.compare_obj(aggs[1], fake_api_aggregate, subs=SUBS)

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.db.aggregate_get_by_host')
    def test_by_host(self, mock_get_by_host, mock_api_get_by_host):
        mock_get_by_host.return_value = [fake_aggregate]
        mock_api_get_by_host.return_value = [fake_api_aggregate]
        aggs = aggregate.AggregateList.get_by_host(self.context, 'fake-host')
        self.assertEqual(2, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)
        self.compare_obj(aggs[1], fake_api_aggregate, subs=SUBS)

    @mock.patch('nova.objects.aggregate._get_by_metadata_key_from_db')
    @mock.patch('nova.db.aggregate_get_by_metadata_key')
    def test_get_by_metadata_key(self,
                                 mock_get_by_metadata_key,
                                 mock_api_get_by_metadata_key):
        mock_get_by_metadata_key.return_value = [fake_aggregate]
        mock_api_get_by_metadata_key.return_value = [fake_api_aggregate]
        aggs = aggregate.AggregateList.get_by_metadata_key(
            self.context, 'this')
        self.assertEqual(2, len(aggs))
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

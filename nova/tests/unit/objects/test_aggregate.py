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


class _TestAggregateObject(object):

    @mock.patch('nova.objects.aggregate._aggregate_get_from_db')
    @mock.patch('nova.db.aggregate_get')
    def test_get_by_id_from_api(self, mock_get, mock_get_api):
        mock_get_api.return_value = fake_api_aggregate

        agg = aggregate.Aggregate.get_by_id(self.context, 123)
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

        mock_get_api.assert_called_once_with(self.context, 123)
        self.assertFalse(mock_get.called)

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

    @mock.patch('nova.objects.aggregate._aggregate_get_from_db_by_uuid')
    @mock.patch('nova.db.aggregate_get_by_uuid')
    def test_get_by_uuid(self, get_by_uuid, get_by_uuid_api):
        get_by_uuid_api.side_effect = exception.AggregateNotFound(
                                                            aggregate_id=123)
        get_by_uuid.return_value = fake_aggregate
        agg = aggregate.Aggregate.get_by_uuid(self.context,
                                              uuidsentinel.fake_aggregate)
        self.assertEqual(uuidsentinel.fake_aggregate, agg.uuid)
        self.assertEqual(fake_aggregate['id'], agg.id)

    @mock.patch('nova.objects.aggregate._aggregate_get_from_db_by_uuid')
    @mock.patch('nova.db.aggregate_get_by_uuid')
    def test_get_by_uuid_from_api(self, get_by_uuid, get_by_uuid_api):
        get_by_uuid_api.return_value = fake_aggregate
        agg = aggregate.Aggregate.get_by_uuid(self.context,
                                              uuidsentinel.fake_aggregate)
        self.assertEqual(uuidsentinel.fake_aggregate, agg.uuid)
        self.assertEqual(fake_aggregate['id'], agg.id)
        self.assertFalse(get_by_uuid.called)

    @mock.patch('nova.objects.aggregate._aggregate_create_in_db')
    @mock.patch('nova.db.aggregate_create')
    def test_create(self, create_mock, api_create_mock):
        api_create_mock.return_value = fake_aggregate
        agg = aggregate.Aggregate(context=self.context)
        agg.name = 'foo'
        agg.metadata = {'one': 'two'}
        agg.uuid = uuidsentinel.fake_agg
        agg.create()
        api_create_mock.assert_called_once_with(
                self.context,
                {'name': 'foo', 'uuid': uuidsentinel.fake_agg},
                metadata={'one': 'two'})
        self.assertFalse(create_mock.called)
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

        api_create_mock.assert_called_once_with(self.context,
            {'name': 'foo', 'uuid': uuidsentinel.fake_agg},
            metadata={'one': 'two'})

    @mock.patch('nova.objects.aggregate._aggregate_create_in_db')
    @mock.patch.object(db, 'aggregate_create')
    def test_recreate_fails(self, create_mock, api_create_mock):
        api_create_mock.return_value = fake_aggregate
        agg = aggregate.Aggregate(context=self.context)
        agg.name = 'foo'
        agg.metadata = {'one': 'two'}
        agg.uuid = uuidsentinel.fake_agg
        agg.create()
        self.assertRaises(exception.ObjectActionError, agg.create)

        api_create_mock.assert_called_once_with(self.context,
            {'name': 'foo', 'uuid': uuidsentinel.fake_agg},
            metadata={'one': 'two'})

    @mock.patch('nova.objects.aggregate._aggregate_delete_from_db')
    @mock.patch('nova.db.aggregate_delete')
    def test_destroy(self, delete_mock, api_delete_mock):
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.destroy()
        self.assertFalse(delete_mock.called)
        api_delete_mock.assert_called_with(self.context, 123)

    @mock.patch('nova.objects.aggregate._aggregate_delete_from_db')
    @mock.patch('nova.db.aggregate_delete')
    def test_destroy_cell(self, delete_mock, api_delete_mock):
        api_delete_mock.side_effect = exception.AggregateNotFound(
                                                            aggregate_id=123)
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.destroy()
        delete_mock.assert_called_with(self.context, 123)
        api_delete_mock.assert_called_with(self.context, 123)

    @mock.patch('nova.objects.aggregate._aggregate_update_to_db')
    @mock.patch('nova.db.aggregate_update')
    def test_save_to_cell(self, update_mock, api_update_mock):
        api_update_mock.side_effect = exception.AggregateNotFound(
            aggregate_id='foo')
        update_mock.return_value = fake_aggregate
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.name = 'fake-aggregate'
        agg.save()
        self.compare_obj(agg, fake_aggregate, subs=SUBS)
        update_mock.assert_called_once_with(self.context,
                                            123,
                                            {'name': 'fake-aggregate'})
        self.assertTrue(api_update_mock.called)

    @mock.patch('nova.objects.aggregate._aggregate_update_to_db')
    @mock.patch('nova.db.aggregate_update')
    def test_save_to_api(self, update_mock, api_update_mock):
        api_update_mock.return_value = fake_aggregate
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.name = 'fake-api-aggregate'
        agg.save()
        self.compare_obj(agg, fake_aggregate, subs=SUBS)
        api_update_mock.assert_called_once_with(self.context,
                                                123,
                                                {'name': 'fake-api-aggregate'})
        self.assertFalse(update_mock.called)

        api_update_mock.assert_called_once_with(self.context,
            123, {'name': 'fake-api-aggregate'})

    def test_save_and_create_no_hosts(self):
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.hosts = ['foo', 'bar']
        self.assertRaises(exception.ObjectActionError,
                          agg.create)
        self.assertRaises(exception.ObjectActionError,
                          agg.save)

    @mock.patch('nova.objects.aggregate._metadata_delete_from_db')
    @mock.patch('nova.objects.aggregate._metadata_add_to_db')
    @mock.patch('nova.db.aggregate_metadata_delete')
    @mock.patch('nova.db.aggregate_metadata_add')
    def test_update_metadata(self,
                             mock_metadata_add,
                             mock_metadata_delete,
                             mock_api_metadata_add,
                             mock_api_metadata_delete):
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
        mock_metadata_add.assert_called_once_with(self.context, 123,
                                                  {'toadd': 'myval'})
        mock_metadata_delete.assert_called_once_with(self.context, 123,
                                                     'todelete')
        self.assertFalse(mock_api_metadata_add.called)
        self.assertFalse(mock_api_metadata_delete.called)

    @mock.patch('nova.objects.Aggregate.in_api')
    @mock.patch('nova.objects.aggregate._metadata_delete_from_db')
    @mock.patch('nova.objects.aggregate._metadata_add_to_db')
    @mock.patch('nova.db.aggregate_metadata_delete')
    @mock.patch('nova.db.aggregate_metadata_add')
    def test_update_metadata_api(self,
                                 mock_metadata_add,
                                 mock_metadata_delete,
                                 mock_api_metadata_add,
                                 mock_api_metadata_delete,
                                 mock_in_api):
        mock_in_api.return_value = True
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
        mock_api_metadata_delete.assert_called_once_with(self.context, 123,
                                                         'todelete')
        mock_api_metadata_add.assert_called_once_with(self.context, 123,
                                                      {'toadd': 'myval'})
        self.assertFalse(mock_metadata_add.called)
        self.assertFalse(mock_metadata_delete.called)

        mock_api_metadata_delete.assert_called_once_with(self.context,
                                                         123,
                                                         'todelete')
        mock_api_metadata_add.assert_called_once_with(self.context,
                                                      123,
                                                      {'toadd': 'myval'})

    @mock.patch.object(db, 'aggregate_host_add')
    def test_add_host(self, mock_host_add):
        mock_host_add.return_value = {'host': 'bar'}
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo']
        agg._context = self.context
        agg.add_host('bar')
        self.assertEqual(agg.hosts, ['foo', 'bar'])
        mock_host_add.assert_called_once_with(self.context, 123, 'bar')

    @mock.patch('nova.db.aggregate_host_add')
    @mock.patch('nova.objects.aggregate._host_add_to_db')
    @mock.patch('nova.objects.Aggregate.in_api')
    def test_add_host_api(self, mock_in_api, mock_host_add_api, mock_host_add):
        mock_host_add_api.return_value = {'host': 'bar'}
        mock_in_api.return_value = True
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo']
        agg._context = self.context
        agg.add_host('bar')
        self.assertEqual(agg.hosts, ['foo', 'bar'])
        mock_host_add_api.assert_called_once_with(self.context, 123, 'bar')
        self.assertFalse(mock_host_add.called)

    @mock.patch.object(db, 'aggregate_host_delete')
    def test_delete_host(self, mock_host_delete):
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo', 'bar']
        agg._context = self.context
        agg.delete_host('foo')
        self.assertEqual(agg.hosts, ['bar'])
        mock_host_delete.assert_called_once_with(self.context, 123, 'foo')

    @mock.patch('nova.db.aggregate_host_delete')
    @mock.patch('nova.objects.aggregate._host_delete_from_db')
    @mock.patch('nova.objects.Aggregate.in_api')
    def test_delete_host_api(self, mock_in_api,
                                   mock_host_delete_api,
                                   mock_host_delete):
        mock_in_api.return_value = True
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo', 'bar']
        agg._context = self.context
        agg.delete_host('foo')
        self.assertEqual(agg.hosts, ['bar'])
        mock_host_delete_api.assert_called_once_with(self.context, 123, 'foo')
        self.assertFalse(mock_host_delete.called)

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

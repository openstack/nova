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

from nova import exception
from nova.objects import aggregate
from nova import test
from nova.tests.unit import fake_notifier
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel


NOW = timeutils.utcnow().replace(microsecond=0)
fake_aggregate = {
    'deleted': 0,
    'deleted_at': None,
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
    def test_get_by_id_from_api(self, mock_get_api):
        mock_get_api.return_value = fake_aggregate

        agg = aggregate.Aggregate.get_by_id(self.context, 123)
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

        mock_get_api.assert_called_once_with(self.context, 123)

    @mock.patch('nova.objects.aggregate._aggregate_get_from_db_by_uuid')
    def test_get_by_uuid_from_api(self, get_by_uuid_api):
        get_by_uuid_api.return_value = fake_aggregate
        agg = aggregate.Aggregate.get_by_uuid(self.context,
                                              uuidsentinel.fake_aggregate)
        self.assertEqual(uuidsentinel.fake_aggregate, agg.uuid)
        self.assertEqual(fake_aggregate['id'], agg.id)

    @mock.patch('nova.objects.aggregate._aggregate_create_in_db')
    def test_create(self, api_create_mock):
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
        self.compare_obj(agg, fake_aggregate, subs=SUBS)

        api_create_mock.assert_called_once_with(self.context,
            {'name': 'foo', 'uuid': uuidsentinel.fake_agg},
            metadata={'one': 'two'})

    @mock.patch('nova.objects.aggregate._aggregate_create_in_db')
    def test_recreate_fails(self, api_create_mock):
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
    def test_destroy(self, api_delete_mock):
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.destroy()
        api_delete_mock.assert_called_with(self.context, 123)

    @mock.patch('nova.compute.utils.notify_about_aggregate_action')
    @mock.patch('nova.objects.aggregate._aggregate_update_to_db')
    def test_save_to_api(self, api_update_mock, mock_notify):
        api_update_mock.return_value = fake_aggregate
        agg = aggregate.Aggregate(context=self.context)
        agg.id = 123
        agg.name = 'fake-api-aggregate'
        agg.save()
        self.compare_obj(agg, fake_aggregate, subs=SUBS)
        api_update_mock.assert_called_once_with(self.context,
                                                123,
                                                {'name': 'fake-api-aggregate'})

        api_update_mock.assert_called_once_with(self.context,
            123, {'name': 'fake-api-aggregate'})

        mock_notify.assert_has_calls([
            mock.call(context=self.context,
                      aggregate=test.MatchType(aggregate.Aggregate),
                      action='update_prop', phase='start'),
            mock.call(context=self.context,
                      aggregate=test.MatchType(aggregate.Aggregate),
                      action='update_prop', phase='end')])
        self.assertEqual(2, mock_notify.call_count)

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
    @mock.patch('nova.compute.utils.notify_about_aggregate_action')
    @mock.patch('oslo_versionedobjects.base.VersionedObject.'
                'obj_from_primitive')
    def test_update_metadata_api(self,
                                 mock_obj_from_primitive,
                                 mock_notify,
                                 mock_api_metadata_add,
                                 mock_api_metadata_delete):
        fake_notifier.NOTIFICATIONS = []
        agg = aggregate.Aggregate()
        agg._context = self.context
        agg.id = 123
        agg.metadata = {'foo': 'bar'}
        agg.obj_reset_changes()
        mock_obj_from_primitive.return_value = agg

        agg.update_metadata({'todelete': None, 'toadd': 'myval'})
        self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('aggregate.updatemetadata.start', msg.event_type)
        self.assertEqual({'todelete': None, 'toadd': 'myval'},
                         msg.payload['meta_data'])
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual('aggregate.updatemetadata.end', msg.event_type)
        mock_notify.assert_has_calls([
            mock.call(context=self.context, aggregate=agg,
                      action='update_metadata', phase='start'),
            mock.call(context=self.context, aggregate=agg,
                      action='update_metadata', phase='end')])
        self.assertEqual({'todelete': None, 'toadd': 'myval'},
                         msg.payload['meta_data'])
        self.assertEqual({'foo': 'bar', 'toadd': 'myval'}, agg.metadata)
        mock_api_metadata_delete.assert_called_once_with(self.context, 123,
                                                         'todelete')
        mock_api_metadata_add.assert_called_once_with(self.context, 123,
                                                      {'toadd': 'myval'})
        mock_api_metadata_delete.assert_called_once_with(self.context,
                                                         123,
                                                         'todelete')
        mock_api_metadata_add.assert_called_once_with(self.context,
                                                      123,
                                                      {'toadd': 'myval'})

    @mock.patch('nova.objects.aggregate._host_add_to_db')
    def test_add_host_api(self, mock_host_add_api):
        mock_host_add_api.return_value = {'host': 'bar'}
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo']
        agg._context = self.context
        agg.add_host('bar')
        self.assertEqual(agg.hosts, ['foo', 'bar'])
        mock_host_add_api.assert_called_once_with(self.context, 123, 'bar')

    @mock.patch('nova.objects.aggregate._host_delete_from_db')
    def test_delete_host_api(self, mock_host_delete_api):
        agg = aggregate.Aggregate()
        agg.id = 123
        agg.hosts = ['foo', 'bar']
        agg._context = self.context
        agg.delete_host('foo')
        self.assertEqual(agg.hosts, ['bar'])
        mock_host_delete_api.assert_called_once_with(self.context, 123, 'foo')

    def test_availability_zone(self):
        agg = aggregate.Aggregate()
        agg.metadata = {'availability_zone': 'foo'}
        self.assertEqual('foo', agg.availability_zone)

    @mock.patch('nova.objects.aggregate._get_all_from_db')
    def test_get_all(self, mock_api_get_all):
        mock_api_get_all.return_value = [fake_aggregate]
        aggs = aggregate.AggregateList.get_all(self.context)
        self.assertEqual(1, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    def test_by_host(self, mock_api_get_by_host):
        mock_api_get_by_host.return_value = [fake_aggregate]
        aggs = aggregate.AggregateList.get_by_host(self.context, 'fake-host')
        self.assertEqual(1, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)

    @mock.patch('nova.objects.aggregate._get_by_metadata_from_db')
    def test_get_by_metadata_key(self, mock_api_get_by_metadata_key):
        mock_api_get_by_metadata_key.return_value = [fake_aggregate]
        aggs = aggregate.AggregateList.get_by_metadata_key(
            self.context, 'this')
        self.assertEqual(1, len(aggs))
        self.compare_obj(aggs[0], fake_aggregate, subs=SUBS)

    @mock.patch('nova.objects.aggregate._get_by_metadata_from_db')
    def test_get_by_metadata_key_and_hosts_no_match(self, get_by_metadata_key):
        get_by_metadata_key.return_value = [fake_aggregate]
        aggs = aggregate.AggregateList.get_by_metadata_key(
            self.context, 'this', hosts=['baz'])
        self.assertEqual(0, len(aggs))

    @mock.patch('nova.objects.aggregate._get_by_metadata_from_db')
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

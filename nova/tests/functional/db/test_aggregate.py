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

from copy import deepcopy

import mock
from oslo_db import exception as db_exc
from oslo_utils import timeutils

from nova import context
from nova import db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
import nova.objects.aggregate as aggregate_obj
from nova import test
from nova.tests.unit import matchers
from nova.tests.unit.objects.test_objects import compare_obj as base_compare
from nova.tests import uuidsentinel


SUBS = {'metadata': 'metadetails'}


NOW = timeutils.utcnow().replace(microsecond=0)


def _get_fake_aggregate(db_id, in_api=True, result=True):
    agg_map = {
        'created_at': NOW,
        'updated_at': None,
        'deleted_at': None,
        'id': db_id,
        'uuid': getattr(uuidsentinel, str(db_id)),
        'name': 'name_' + str(db_id),
    }
    if not in_api:
        agg_map['deleted'] = False
    if result:
        agg_map['hosts'] = _get_fake_hosts(db_id)
        agg_map['metadetails'] = _get_fake_metadata(db_id)
    return agg_map


def _get_fake_hosts(db_id):
    return ['constant_host', 'unique_host_' + str(db_id)]


def _get_fake_metadata(db_id):
    return {'constant_key': 'constant_value',
            'unique_key': 'unique_value_' + str(db_id)}


@db_api.api_context_manager.writer
def _create_aggregate(context, values=_get_fake_aggregate(1, result=False),
                               metadata=_get_fake_metadata(1)):
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
def _create_aggregate_with_hosts(context,
                                 values=_get_fake_aggregate(1, result=False),
                                 metadata=_get_fake_metadata(1),
                                 hosts=_get_fake_hosts(1)):
    aggregate = _create_aggregate(context, values, metadata)
    for host in hosts:
        host_model = api_models.AggregateHost()
        host_model.update({'host': host,
                           'aggregate_id': aggregate.id})
        host_model.save(context.session)

    return aggregate


@db_api.api_context_manager.reader
def _aggregate_host_get_all(context, aggregate_id):
    return context.session.query(api_models.AggregateHost).\
                       filter_by(aggregate_id=aggregate_id).all()


@db_api.api_context_manager.reader
def _aggregate_metadata_get_all(context, aggregate_id):
    results = context.session.query(api_models.AggregateMetadata).\
                                filter_by(aggregate_id=aggregate_id).all()
    metadata = {}
    for r in results:
        metadata[r['key']] = r['value']
    return metadata


class AggregateObjectDbTestCase(test.TestCase):

    def setUp(self):
        super(AggregateObjectDbTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def test_in_api(self):
        ca1 = _create_aggregate(self.context, values={'name': 'fake_agg_1',
                                                      'id': 1,
                                                      'uuid': 'nonce'})
        ca2 = db.aggregate_create(self.context, {'name': 'fake_agg_2',
                                                 'id': 2,
                                                 'uuid': 'nonce'})

        api_db_agg = aggregate_obj.Aggregate.get_by_id(self.context, ca1['id'])
        cell_db_agg = aggregate_obj.Aggregate.get_by_id(
                                                    self.context, ca2['id'])

        self.assertTrue(api_db_agg.in_api)
        self.assertFalse(cell_db_agg.in_api)

    def test_aggregate_get_from_db(self):
        result = _create_aggregate_with_hosts(self.context)
        expected = aggregate_obj._aggregate_get_from_db(self.context,
                                                        result['id'])
        self.assertEqual(_get_fake_hosts(1), expected.hosts)
        self.assertEqual(_get_fake_metadata(1), expected['metadetails'])

    def test_aggregate_get_from_db_by_uuid(self):
        result = _create_aggregate_with_hosts(self.context)
        expected = aggregate_obj._aggregate_get_from_db_by_uuid(
                self.context, result['uuid'])
        self.assertEqual(result.uuid, expected.uuid)
        self.assertEqual(_get_fake_hosts(1), expected.hosts)
        self.assertEqual(_get_fake_metadata(1), expected['metadetails'])

    def test_aggregate_get_from_db_raise_not_found(self):
        aggregate_id = 5
        self.assertRaises(exception.AggregateNotFound,
                          aggregate_obj._aggregate_get_from_db,
                          self.context, aggregate_id)

    def test_aggregate_get_all_from_db(self):
        for c in range(3):
            _create_aggregate(self.context,
                              values={'name': 'fake_aggregate_%d' % c})
        results = aggregate_obj._get_all_from_db(self.context)
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
        rh1 = aggregate_obj._get_all_from_db(self.context)
        rh2 = aggregate_obj._get_by_host_from_db(self.context,
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
        rh1 = aggregate_obj._get_by_host_from_db(self.context,
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
        rl1 = aggregate_obj._get_by_metadata_key_from_db(self.context,
                                                     key='goodkey')
        self.assertEqual(2, len(rl1))

    def test_aggregate_create_in_db(self):
        fake_create_aggregate = {
            'name': 'fake-aggregate',
        }
        agg = aggregate_obj._aggregate_create_in_db(self.context,
                                                    fake_create_aggregate)
        result = aggregate_obj._aggregate_get_from_db(self.context,
                                                      agg.id)
        self.assertEqual(result.name, fake_create_aggregate['name'])

    def test_aggregate_create_in_db_with_metadata(self):
        fake_create_aggregate = {
            'name': 'fake-aggregate',
        }
        agg = aggregate_obj._aggregate_create_in_db(self.context,
                                                fake_create_aggregate,
                                                metadata={'goodkey': 'good'})
        result = aggregate_obj._aggregate_get_from_db(self.context,
                                                      agg.id)
        md = aggregate_obj._get_by_metadata_key_from_db(self.context,
                                                        key='goodkey')
        self.assertEqual(len(md), 1)
        self.assertEqual(md[0]['id'], agg.id)
        self.assertEqual(result.name, fake_create_aggregate['name'])

    def test_aggregate_create_raise_exist_exc(self):
        fake_create_aggregate = {
            'name': 'fake-aggregate',
        }
        aggregate_obj._aggregate_create_in_db(self.context,
                                              fake_create_aggregate)
        self.assertRaises(exception.AggregateNameExists,
                          aggregate_obj._aggregate_create_in_db,
                          self.context,
                          fake_create_aggregate,
                          metadata=None)

    def test_aggregate_delete(self):
        result = _create_aggregate(self.context, metadata=None)
        aggregate_obj._aggregate_delete_from_db(self.context, result['id'])
        self.assertRaises(exception.AggregateNotFound,
                          aggregate_obj._aggregate_get_from_db,
                          self.context, result['id'])

    def test_aggregate_delete_raise_not_found(self):
        # this does not exist!
        aggregate_id = 45
        self.assertRaises(exception.AggregateNotFound,
                          aggregate_obj._aggregate_delete_from_db,
                          self.context, aggregate_id)

    def test_aggregate_delete_with_metadata(self):
        result = _create_aggregate(self.context,
                            metadata={'availability_zone': 'fake_avail_zone'})
        aggregate_obj._aggregate_delete_from_db(self.context, result['id'])
        self.assertRaises(exception.AggregateNotFound,
                          aggregate_obj._aggregate_get_from_db,
                          self.context, result['id'])

    def test_aggregate_update(self):
        created = _create_aggregate(self.context,
                            metadata={'availability_zone': 'fake_avail_zone'})
        result = aggregate_obj._aggregate_get_from_db(self.context,
                                                      created['id'])
        self.assertEqual('fake_avail_zone', result['availability_zone'])
        new_values = deepcopy(_get_fake_aggregate(1, result=False))
        new_values['availability_zone'] = 'different_avail_zone'
        updated = aggregate_obj._aggregate_update_to_db(self.context,
                                                    result['id'], new_values)
        self.assertEqual('different_avail_zone', updated['availability_zone'])

    def test_aggregate_update_with_metadata(self):
        result = _create_aggregate(self.context, metadata=None)
        values = deepcopy(_get_fake_aggregate(1, result=False))
        values['metadata'] = deepcopy(_get_fake_metadata(1))
        values['availability_zone'] = 'different_avail_zone'
        expected_metadata = deepcopy(values['metadata'])
        expected_metadata['availability_zone'] = values['availability_zone']
        aggregate_obj._aggregate_update_to_db(self.context, result['id'],
                                              values)
        metadata = _aggregate_metadata_get_all(self.context, result['id'])
        updated = aggregate_obj._aggregate_get_from_db(self.context,
                                                       result['id'])
        self.assertThat(metadata,
                        matchers.DictMatches(expected_metadata))
        self.assertEqual('different_avail_zone', updated['availability_zone'])

    def test_aggregate_update_with_existing_metadata(self):
        result = _create_aggregate(self.context)
        values = deepcopy(_get_fake_aggregate(1, result=False))
        values['metadata'] = deepcopy(_get_fake_metadata(1))
        values['metadata']['fake_key1'] = 'foo'
        expected_metadata = deepcopy(values['metadata'])
        aggregate_obj._aggregate_update_to_db(self.context, result['id'],
                                              values)
        metadata = _aggregate_metadata_get_all(self.context, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected_metadata))

    def test_aggregate_update_zone_with_existing_metadata(self):
        result = _create_aggregate(self.context)
        new_zone = {'availability_zone': 'fake_avail_zone_2'}
        metadata = deepcopy(_get_fake_metadata(1))
        metadata.update(new_zone)
        aggregate_obj._aggregate_update_to_db(self.context, result['id'],
                                              new_zone)
        expected = _aggregate_metadata_get_all(self.context, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_update_raise_not_found(self):
        # this does not exist!
        aggregate_id = 2
        new_values = deepcopy(_get_fake_aggregate(1, result=False))
        self.assertRaises(exception.AggregateNotFound,
                          aggregate_obj._aggregate_update_to_db,
                          self.context, aggregate_id, new_values)

    def test_aggregate_update_raise_name_exist(self):
        _create_aggregate(self.context, values={'name': 'test1'},
                         metadata={'availability_zone': 'fake_avail_zone'})
        _create_aggregate(self.context, values={'name': 'test2'},
                          metadata={'availability_zone': 'fake_avail_zone'})
        aggregate_id = 1
        new_values = {'name': 'test2'}
        self.assertRaises(exception.AggregateNameExists,
                          aggregate_obj._aggregate_update_to_db,
                          self.context, aggregate_id, new_values)

    def test_aggregate_host_add_to_db(self):
        result = _create_aggregate(self.context, metadata=None)
        host = _get_fake_hosts(1)[0]
        aggregate_obj._host_add_to_db(self.context, result['id'], host)
        expected = aggregate_obj._aggregate_get_from_db(self.context,
                                                        result['id'])
        self.assertEqual([_get_fake_hosts(1)[0]], expected.hosts)

    def test_aggregate_host_re_add_to_db(self):
        result = _create_aggregate_with_hosts(self.context,
                                              metadata=None)
        host = _get_fake_hosts(1)[0]
        aggregate_obj._host_delete_from_db(self.context, result['id'], host)
        aggregate_obj._host_add_to_db(self.context, result['id'], host)
        expected = _aggregate_host_get_all(self.context, result['id'])
        self.assertEqual(len(expected), 2)

    def test_aggregate_host_add_to_db_duplicate_works(self):
        r1 = _create_aggregate_with_hosts(self.context,
                                          metadata=None)
        r2 = _create_aggregate_with_hosts(self.context,
                          values={'name': 'fake_aggregate2'},
                          metadata={'availability_zone': 'fake_avail_zone2'})
        h1 = _aggregate_host_get_all(self.context, r1['id'])
        self.assertEqual(len(h1), 2)
        self.assertEqual(r1['id'], h1[0]['aggregate_id'])
        h2 = _aggregate_host_get_all(self.context, r2['id'])
        self.assertEqual(len(h2), 2)
        self.assertEqual(r2['id'], h2[0]['aggregate_id'])

    def test_aggregate_host_add_to_db_duplicate_raise_exist_exc(self):
        result = _create_aggregate_with_hosts(self.context,
                                              metadata=None)
        self.assertRaises(exception.AggregateHostExists,
                          aggregate_obj._host_add_to_db,
                          self.context, result['id'],
                          _get_fake_hosts(1)[0])

    def test_aggregate_host_add_to_db_raise_not_found(self):
        # this does not exist!
        aggregate_id = 1
        host = _get_fake_hosts(1)[0]
        self.assertRaises(exception.AggregateNotFound,
                          aggregate_obj._host_add_to_db,
                          self.context, aggregate_id, host)

    def test_aggregate_host_delete_from_db(self):
        result = _create_aggregate_with_hosts(self.context,
                                              metadata=None)
        aggregate_obj._host_delete_from_db(self.context, result['id'],
                                 _get_fake_hosts(1)[0])
        expected = _aggregate_host_get_all(self.context, result['id'])
        self.assertEqual(len(expected), 1)

    def test_aggregate_host_delete_from_db_raise_not_found(self):
        result = _create_aggregate(self.context)
        self.assertRaises(exception.AggregateHostNotFound,
                          aggregate_obj._host_delete_from_db,
                          self.context, result['id'],
                          _get_fake_hosts(1)[0])

    def test_aggregate_metadata_add(self):
        result = _create_aggregate(self.context, metadata=None)
        metadata = deepcopy(_get_fake_metadata(1))
        aggregate_obj._metadata_add_to_db(self.context, result['id'], metadata)
        expected = _aggregate_metadata_get_all(self.context, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_add_empty_metadata(self):
        result = _create_aggregate(self.context, metadata=None)
        metadata = {}
        aggregate_obj._metadata_add_to_db(self.context, result['id'], metadata)
        expected = _aggregate_metadata_get_all(self.context, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_add_and_update(self):
        result = _create_aggregate(self.context)
        metadata = deepcopy(_get_fake_metadata(1))
        key = list(metadata.keys())[0]
        new_metadata = {key: 'foo',
                        'fake_new_key': 'fake_new_value'}
        metadata.update(new_metadata)
        aggregate_obj._metadata_add_to_db(self.context,
                                          result['id'], new_metadata)
        expected = _aggregate_metadata_get_all(self.context, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_add_retry(self):
        result = _create_aggregate(self.context, metadata=None)
        with mock.patch('nova.db.sqlalchemy.api_models.'
                        'AggregateMetadata.__table__.insert') as insert_mock:
            insert_mock.side_effect = db_exc.DBDuplicateEntry
            self.assertRaises(db_exc.DBDuplicateEntry,
                              aggregate_obj._metadata_add_to_db,
                              self.context,
                              result['id'],
                              {'fake_key2': 'fake_value2'},
                              max_retries=5)

    def test_aggregate_metadata_update(self):
        result = _create_aggregate(self.context)
        metadata = deepcopy(_get_fake_metadata(1))
        key = list(metadata.keys())[0]
        aggregate_obj._metadata_delete_from_db(self.context, result['id'], key)
        new_metadata = {key: 'foo'}
        aggregate_obj._metadata_add_to_db(self.context,
                                          result['id'], new_metadata)
        expected = _aggregate_metadata_get_all(self.context, result['id'])
        metadata[key] = 'foo'
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_delete(self):
        result = _create_aggregate(self.context, metadata=None)
        metadata = deepcopy(_get_fake_metadata(1))
        aggregate_obj._metadata_add_to_db(self.context, result['id'], metadata)
        aggregate_obj._metadata_delete_from_db(self.context, result['id'],
                                           list(metadata.keys())[0])
        expected = _aggregate_metadata_get_all(self.context, result['id'])
        del metadata[list(metadata.keys())[0]]
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_remove_availability_zone(self):
        result = _create_aggregate(self.context, metadata={'availability_zone':
            'fake_avail_zone'})
        aggregate_obj._metadata_delete_from_db(self.context,
                                           result['id'],
                                           'availability_zone')
        aggr = aggregate_obj._aggregate_get_from_db(self.context, result['id'])
        self.assertIsNone(aggr['availability_zone'])

    def test_aggregate_metadata_delete_raise_not_found(self):
        result = _create_aggregate(self.context)
        self.assertRaises(exception.AggregateMetadataNotFound,
                          aggregate_obj._metadata_delete_from_db,
                          self.context, result['id'], 'foo_key')


def create_aggregate(context, db_id, in_api=True):
    if in_api:
        fake_aggregate = _get_fake_aggregate(db_id, in_api=False, result=False)
        aggregate_obj._aggregate_create_in_db(context, fake_aggregate,
                                       metadata=_get_fake_metadata(db_id))
        for host in _get_fake_hosts(db_id):
            aggregate_obj._host_add_to_db(context, fake_aggregate['id'], host)
    else:
        fake_aggregate = _get_fake_aggregate(db_id, in_api=False, result=False)
        db.aggregate_create(context, fake_aggregate,
                            metadata=_get_fake_metadata(db_id))
        for host in _get_fake_hosts(db_id):
            db.aggregate_host_add(context, fake_aggregate['id'], host)


def compare_obj(test, result, source):
    source['deleted'] = False

    def updated_at_comparator(result, source):
        return True

    return base_compare(test, result, source, subs=SUBS,
                        comparators={'updated_at': updated_at_comparator})


class AggregateObjectCellTestCase(test.TestCase):
    """Tests for the case where all aggregate data is in Cell DB"""

    def setUp(self):
        super(AggregateObjectCellTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        self._seed_data()

    def _seed_data(self):
        for i in range(1, 10):
            create_aggregate(self.context, i, in_api=False)

    def test_get_by_id(self):
        for i in range(1, 10):
            agg = aggregate_obj.Aggregate.get_by_id(self.context, i)
            compare_obj(self, agg, _get_fake_aggregate(i))

    def test_save(self):
        for i in range(1, 10):
            agg = aggregate_obj.Aggregate.get_by_id(self.context, i)
            fake_agg = _get_fake_aggregate(i)
            fake_agg['name'] = 'new-name' + str(i)
            agg.name = 'new-name' + str(i)
            agg.save()
            result = aggregate_obj.Aggregate.get_by_id(self.context, i)
            compare_obj(self, agg, fake_agg)
            compare_obj(self, result, fake_agg)

    def test_update_metadata(self):
        for i in range(1, 10):
            agg = aggregate_obj.Aggregate.get_by_id(self.context, i)
            fake_agg = _get_fake_aggregate(i)
            fake_agg['metadetails'] = {'constant_key': 'constant_value'}
            agg.update_metadata({'unique_key': None})
            agg.save()
            result = aggregate_obj.Aggregate.get_by_id(self.context, i)
            compare_obj(self, agg, fake_agg)
            compare_obj(self, result, fake_agg)

    def test_destroy(self):
        for i in range(1, 10):
            agg = aggregate_obj.Aggregate.get_by_id(self.context, i)
            agg.destroy()
        aggs = aggregate_obj.AggregateList.get_all(self.context)
        self.assertEqual(len(aggs), 0)

    def test_add_host(self):
        for i in range(1, 10):
            agg = aggregate_obj.Aggregate.get_by_id(self.context, i)
            fake_agg = _get_fake_aggregate(i)
            fake_agg['hosts'].append('barbar')
            agg.add_host('barbar')
            agg.save()
            result = aggregate_obj.Aggregate.get_by_id(self.context, i)
            compare_obj(self, agg, fake_agg)
            compare_obj(self, result, fake_agg)

    def test_delete_host(self):
        for i in range(1, 10):
            agg = aggregate_obj.Aggregate.get_by_id(self.context, i)
            fake_agg = _get_fake_aggregate(i)
            fake_agg['hosts'].remove('constant_host')
            agg.delete_host('constant_host')
            result = aggregate_obj.Aggregate.get_by_id(self.context, i)
            compare_obj(self, agg, fake_agg)
            compare_obj(self, result, fake_agg)


class AggregateObjectApiTestCase(AggregateObjectCellTestCase):
    """Tests the aggregate in the case where all data is in the API DB"""
    def _seed_data(self):
        for i in range(1, 10):
            create_aggregate(self.context, i)

    def test_create(self):
        new_agg = aggregate_obj.Aggregate(self.context)
        new_agg.name = 'new-aggregate'
        new_agg.create()
        result = aggregate_obj.Aggregate.get_by_id(self.context, new_agg.id)
        self.assertEqual(new_agg.name, result.name)


class AggregateObjectMixedTestCase(AggregateObjectCellTestCase):
    """Tests the aggregate in the case where data is in both databases"""
    def _seed_data(self):
        for i in range(1, 6):
            create_aggregate(self.context, i)
        for i in range(6, 10):
            create_aggregate(self.context, i, in_api=False)

    def test_create(self):
        new_agg = aggregate_obj.Aggregate(self.context)
        new_agg.name = 'new-aggregate'
        self.assertRaises(exception.ObjectActionError,
                          new_agg.create)


class AggregateObjectMigrationTestCase(AggregateObjectCellTestCase):
    """Tests the aggregate in the case where data is migrated to the API db"""
    def _seed_data(self):
        for i in range(1, 10):
            create_aggregate(self.context, i, in_api=False)
        aggregate_obj.migrate_aggregates(self.context, 50)

    def test_create(self):
        new_agg = aggregate_obj.Aggregate(self.context)
        new_agg.name = 'new-aggregate'
        new_agg.create()
        result = aggregate_obj.Aggregate.get_by_id(self.context, new_agg.id)
        self.assertEqual(new_agg.name, result.name)


class AggregateMigrationTestCase(test.TestCase):

    def setUp(self):
        super(AggregateMigrationTestCase, self).setUp()
        self.context = context.get_admin_context()

    def test_migration(self):
        db.aggregate_create(self.context, {'name': 'foo',
                                           'uuid': uuidsentinel.agg_uuid})
        main_aggregates_len = len(db.aggregate_get_all(self.context))
        match, done = aggregate_obj.migrate_aggregates(self.context, 50)
        self.assertEqual(1, main_aggregates_len)
        self.assertEqual(main_aggregates_len, match)
        self.assertEqual(main_aggregates_len, done)
        self.assertEqual(0, len(db.aggregate_get_all(self.context)))
        self.assertEqual(main_aggregates_len,
                         len(aggregate_obj.AggregateList.get_all(
                                                                self.context)))

    def test_migrate_aggregate_reset_autoincrement(self):
        agg = aggregate_obj.Aggregate(self.context, name='foo')
        agg.create()
        match, done = aggregate_obj.migrate_aggregate_reset_autoincrement(
            self.context, 0)
        self.assertEqual(0, match)
        self.assertEqual(0, done)

    def test_migrate_aggregate_reset_autoincrement_no_aggregates(self):
        # NOTE(danms): This validates the "or 0" default if there are no
        # aggregates (and thus no max id).
        match, done = aggregate_obj.migrate_aggregate_reset_autoincrement(
            self.context, 0)
        self.assertEqual(0, match)
        self.assertEqual(0, done)

    @mock.patch('nova.objects.aggregate.LOG.error')
    def test_migrate_aggregates_duplicate_unicode(self, mock_log_error):
        """Tests that we handle a duplicate aggregate when migrating and that
        we handle when the exception message is in unicode.
        """
        # First create an aggregate that will be migrated from main to API DB.
        create_aggregate(self.context, 1, in_api=False)
        # Now create that same aggregate in the API DB.
        create_aggregate(self.context, 1, in_api=True)
        # Now let's run the online data migration which will fail to create
        # a duplicate aggregate in the API database and will raise
        # AggregateNameExists which we want to modify to have a unicode
        # message.
        with mock.patch.object(exception.AggregateNameExists, 'msg_fmt',
                               u'\xF0\x9F\x92\xA9'):
            match, done = aggregate_obj.migrate_aggregates(self.context, 50)
            # we found one
            self.assertEqual(1, match)
            # but we didn't migrate it
            self.assertEqual(0, done)
            # and we logged an error for the duplicate aggregate
            mock_log_error.assert_called()

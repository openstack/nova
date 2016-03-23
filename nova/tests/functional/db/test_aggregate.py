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

from oslo_utils import timeutils

from nova import context
from nova import db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel

import nova.objects.aggregate as aggregate_obj


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


class AggregateObjectDbTestCase(test.NoDBTestCase):

    USES_DB_SELF = True

    def setUp(self):
        super(AggregateObjectDbTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(database='api'))
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

        self.assertEqual(api_db_agg.in_api, True)
        self.assertEqual(cell_db_agg.in_api, False)

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

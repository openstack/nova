# vim: tabstop=4 shiftwidth=4 softtabstop=4
# encoding=UTF8

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Unit tests for the DB API."""

import copy
import datetime
import types
import uuid as stdlib_uuid

import mox
import netaddr
from oslo.config import cfg
from sqlalchemy.dialects import sqlite
from sqlalchemy import exc
from sqlalchemy.exc import IntegrityError
from sqlalchemy import MetaData
from sqlalchemy.orm import exc as sqlalchemy_orm_exc
from sqlalchemy.orm import query
from sqlalchemy.sql.expression import select

from nova import block_device
from nova.compute import vm_states
from nova import context
from nova import db
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy import utils as db_utils
from nova import exception
from nova.openstack.common.db import exception as db_exc
from nova.openstack.common.db.sqlalchemy import session as db_session
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova.quota import ReservableResource
from nova.quota import resources
from nova import test
from nova.tests import matchers
from nova import utils


CONF = cfg.CONF
CONF.import_opt('reserved_host_memory_mb', 'nova.compute.resource_tracker')
CONF.import_opt('reserved_host_disk_mb', 'nova.compute.resource_tracker')

get_engine = db_session.get_engine
get_session = db_session.get_session


def _quota_reserve(context, project_id, user_id):
    """Create sample Quota, QuotaUsage and Reservation objects.

    There is no method db.quota_usage_create(), so we have to use
    db.quota_reserve() for creating QuotaUsage objects.

    Returns reservations uuids.

    """
    def get_sync(resource, usage):
        def sync(elevated, project_id, user_id, session):
            return {resource: usage}
        return sync
    quotas = {}
    user_quotas = {}
    resources = {}
    deltas = {}
    for i in range(3):
        resource = 'resource%d' % i
        sync_name = '_sync_%s' % resource
        quotas[resource] = db.quota_create(context, project_id, resource, i)
        user_quotas[resource] = db.quota_create(context, project_id,
                                                resource, i, user_id=user_id)
        resources[resource] = ReservableResource(
            resource, sync_name, 'quota_res_%d' % i)
        deltas[resource] = i
        setattr(sqlalchemy_api, sync_name, get_sync(resource, i))
        sqlalchemy_api.QUOTA_SYNC_FUNCTIONS[sync_name] = getattr(
            sqlalchemy_api, sync_name)
    return db.quota_reserve(context, resources, quotas, user_quotas, deltas,
                    timeutils.utcnow(), timeutils.utcnow(),
                    datetime.timedelta(days=1), project_id, user_id)


class DbTestCase(test.TestCase):
    def setUp(self):
        super(DbTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def create_instance_with_args(self, **kwargs):
        args = {'reservation_id': 'a', 'image_ref': 1, 'host': 'host1',
                'node': 'node1', 'project_id': self.project_id,
                'vm_state': 'fake'}
        if 'context' in kwargs:
            ctxt = kwargs.pop('context')
            args['project_id'] = ctxt.project_id
        else:
            ctxt = self.context
        args.update(kwargs)
        return db.instance_create(ctxt, args)

    def fake_metadata(self, content):
        meta = {}
        for i in range(0, 10):
            meta["foo%i" % i] = "this is %s item %i" % (content, i)
        return meta

    def create_metadata_for_instance(self, instance_uuid):
        meta = self.fake_metadata('metadata')
        db.instance_metadata_update(self.context, instance_uuid, meta, False)
        sys_meta = self.fake_metadata('system_metadata')
        db.instance_system_metadata_update(self.context, instance_uuid,
                                           sys_meta, False)
        return meta, sys_meta


class DecoratorTestCase(test.TestCase):
    def _test_decorator_wraps_helper(self, decorator):
        def test_func():
            """Test docstring."""

        decorated_func = decorator(test_func)

        self.assertEquals(test_func.func_name, decorated_func.func_name)
        self.assertEquals(test_func.__doc__, decorated_func.__doc__)
        self.assertEquals(test_func.__module__, decorated_func.__module__)

    def test_require_context_decorator_wraps_functions_properly(self):
        self._test_decorator_wraps_helper(sqlalchemy_api.require_context)

    def test_require_admin_context_decorator_wraps_functions_properly(self):
        self._test_decorator_wraps_helper(sqlalchemy_api.require_admin_context)


def _get_fake_aggr_values():
    return {'name': 'fake_aggregate'}


def _get_fake_aggr_metadata():
    return {'fake_key1': 'fake_value1',
            'fake_key2': 'fake_value2',
            'availability_zone': 'fake_avail_zone'}


def _get_fake_aggr_hosts():
    return ['foo.openstack.org']


def _create_aggregate(context=context.get_admin_context(),
                      values=_get_fake_aggr_values(),
                      metadata=_get_fake_aggr_metadata()):
    return db.aggregate_create(context, values, metadata)


def _create_aggregate_with_hosts(context=context.get_admin_context(),
                      values=_get_fake_aggr_values(),
                      metadata=_get_fake_aggr_metadata(),
                      hosts=_get_fake_aggr_hosts()):
    result = _create_aggregate(context=context,
                               values=values, metadata=metadata)
    for host in hosts:
        db.aggregate_host_add(context, result['id'], host)
    return result


class NotDbApiTestCase(DbTestCase):
    def setUp(self):
        super(NotDbApiTestCase, self).setUp()
        self.flags(connection='notdb://', group='database')

    def test_instance_get_all_by_filters_regex_unsupported_db(self):
        # Ensure that the 'LIKE' operator is used for unsupported dbs.
        self.create_instance_with_args(display_name='test1')
        self.create_instance_with_args(display_name='test.*')
        self.create_instance_with_args(display_name='diff')
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': 'test.*'})
        self.assertEqual(1, len(result))
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': '%test%'})
        self.assertEqual(2, len(result))

    def test_instance_get_all_by_filters_paginate(self):
        test1 = self.create_instance_with_args(display_name='test1')
        test2 = self.create_instance_with_args(display_name='test2')
        test3 = self.create_instance_with_args(display_name='test3')

        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': '%test%'},
                                                marker=None)
        self.assertEqual(3, len(result))
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': '%test%'},
                                                sort_dir="asc",
                                                marker=test1['uuid'])
        self.assertEqual(2, len(result))
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': '%test%'},
                                                sort_dir="asc",
                                                marker=test2['uuid'])
        self.assertEqual(1, len(result))
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': '%test%'},
                                                sort_dir="asc",
                                                marker=test3['uuid'])
        self.assertEqual(0, len(result))

        self.assertRaises(exception.MarkerNotFound,
                          db.instance_get_all_by_filters,
                          self.context, {'display_name': '%test%'},
                          marker=str(stdlib_uuid.uuid4()))


class AggregateDBApiTestCase(test.TestCase):
    def setUp(self):
        super(AggregateDBApiTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def test_aggregate_create_no_metadata(self):
        result = _create_aggregate(metadata=None)
        self.assertEquals(result['name'], 'fake_aggregate')

    def test_aggregate_create_avoid_name_conflict(self):
        r1 = _create_aggregate(metadata=None)
        db.aggregate_delete(context.get_admin_context(), r1['id'])
        values = {'name': r1['name']}
        metadata = {'availability_zone': 'new_zone'}
        r2 = _create_aggregate(values=values, metadata=metadata)
        self.assertEqual(r2['name'], values['name'])
        self.assertEqual(r2['availability_zone'],
                metadata['availability_zone'])

    def test_aggregate_create_raise_exist_exc(self):
        _create_aggregate(metadata=None)
        self.assertRaises(exception.AggregateNameExists,
                          _create_aggregate, metadata=None)

    def test_aggregate_get_raise_not_found(self):
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_get,
                          ctxt, aggregate_id)

    def test_aggregate_metadata_get_raise_not_found(self):
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_metadata_get,
                          ctxt, aggregate_id)

    def test_aggregate_create_with_metadata(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        expected_metadata = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(expected_metadata,
                        matchers.DictMatches(_get_fake_aggr_metadata()))

    def test_aggregate_create_delete_create_with_metadata(self):
        #test for bug 1052479
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        expected_metadata = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(expected_metadata,
                        matchers.DictMatches(_get_fake_aggr_metadata()))
        db.aggregate_delete(ctxt, result['id'])
        result = _create_aggregate(metadata={'availability_zone':
            'fake_avail_zone'})
        expected_metadata = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertEqual(expected_metadata, {'availability_zone':
            'fake_avail_zone'})

    def test_aggregate_create_low_privi_context(self):
        self.assertRaises(exception.AdminRequired,
                          db.aggregate_create,
                          self.context, _get_fake_aggr_values())

    def test_aggregate_get(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt)
        expected = db.aggregate_get(ctxt, result['id'])
        self.assertEqual(_get_fake_aggr_hosts(), expected['hosts'])
        self.assertEqual(_get_fake_aggr_metadata(), expected['metadetails'])

    def test_aggregate_get_by_host(self):
        ctxt = context.get_admin_context()
        values2 = {'name': 'fake_aggregate2'}
        values3 = {'name': 'fake_aggregate3'}
        values4 = {'name': 'fake_aggregate4'}
        values5 = {'name': 'fake_aggregate5'}
        a1 = _create_aggregate_with_hosts(context=ctxt)
        a2 = _create_aggregate_with_hosts(context=ctxt, values=values2)
        # a3 has no hosts and should not be in the results.
        a3 = _create_aggregate(context=ctxt, values=values3)
        # a4 has no matching hosts.
        a4 = _create_aggregate_with_hosts(context=ctxt, values=values4,
                hosts=['foo4.openstack.org'])
        # a5 has no matching hosts after deleting the only matching host.
        a5 = _create_aggregate_with_hosts(context=ctxt, values=values5,
                hosts=['foo5.openstack.org', 'foo.openstack.org'])
        db.aggregate_host_delete(ctxt, a5['id'],
                                 'foo.openstack.org')
        r1 = db.aggregate_get_by_host(ctxt, 'foo.openstack.org')
        self.assertEqual([a1['id'], a2['id']], [x['id'] for x in r1])

    def test_aggregate_get_by_host_with_key(self):
        ctxt = context.get_admin_context()
        values2 = {'name': 'fake_aggregate2'}
        values3 = {'name': 'fake_aggregate3'}
        values4 = {'name': 'fake_aggregate4'}
        a1 = _create_aggregate_with_hosts(context=ctxt,
                                          metadata={'goodkey': 'good'})
        _create_aggregate_with_hosts(context=ctxt, values=values2)
        _create_aggregate(context=ctxt, values=values3)
        _create_aggregate_with_hosts(context=ctxt, values=values4,
                hosts=['foo4.openstack.org'], metadata={'goodkey': 'bad'})
        # filter result by key
        r1 = db.aggregate_get_by_host(ctxt, 'foo.openstack.org', key='goodkey')
        self.assertEqual([a1['id']], [x['id'] for x in r1])

    def test_aggregate_metadata_get_by_host(self):
        ctxt = context.get_admin_context()
        values = {'name': 'fake_aggregate2'}
        values2 = {'name': 'fake_aggregate3'}
        _create_aggregate_with_hosts(context=ctxt)
        _create_aggregate_with_hosts(context=ctxt, values=values)
        _create_aggregate_with_hosts(context=ctxt, values=values2,
                hosts=['bar.openstack.org'], metadata={'badkey': 'bad'})
        r1 = db.aggregate_metadata_get_by_host(ctxt, 'foo.openstack.org')
        self.assertEqual(r1['fake_key1'], set(['fake_value1']))
        self.assertFalse('badkey' in r1)

    def test_aggregate_metadata_get_by_metadata_key(self):
        ctxt = context.get_admin_context()
        values = {'aggregate_id': 'fake_id',
                  'name': 'fake_aggregate'}
        aggr = _create_aggregate_with_hosts(context=ctxt, values=values,
                                            hosts=['bar.openstack.org'],
                                            metadata={'availability_zone':
                                                      'az1'})
        r1 = db.aggregate_metadata_get_by_metadata_key(ctxt, aggr['id'],
                                                        'availability_zone')
        self.assertEqual(r1['availability_zone'], set(['az1']))
        self.assertTrue('availability_zone' in r1)
        self.assertFalse('name' in r1)

    def test_aggregate_metadata_get_by_host_with_key(self):
        ctxt = context.get_admin_context()
        values2 = {'name': 'fake_aggregate12'}
        values3 = {'name': 'fake_aggregate23'}
        a2_hosts = ['foo1.openstack.org', 'foo2.openstack.org']
        a2_metadata = {'good': 'value12', 'bad': 'badvalue12'}
        a3_hosts = ['foo2.openstack.org', 'foo3.openstack.org']
        a3_metadata = {'good': 'value23', 'bad': 'badvalue23'}
        a1 = _create_aggregate_with_hosts(context=ctxt)
        a2 = _create_aggregate_with_hosts(context=ctxt, values=values2,
                hosts=a2_hosts, metadata=a2_metadata)
        a3 = _create_aggregate_with_hosts(context=ctxt, values=values3,
                hosts=a3_hosts, metadata=a3_metadata)
        r1 = db.aggregate_metadata_get_by_host(ctxt, 'foo2.openstack.org',
                                               key='good')
        self.assertEqual(r1['good'], set(['value12', 'value23']))
        self.assertFalse('fake_key1' in r1)
        self.assertFalse('bad' in r1)
        # Delete metadata
        db.aggregate_metadata_delete(ctxt, a3['id'], 'good')
        r2 = db.aggregate_metadata_get_by_host(ctxt, 'foo.openstack.org',
                                               key='good')
        self.assertFalse('good' in r2)

    def test_aggregate_host_get_by_metadata_key(self):
        ctxt = context.get_admin_context()
        values2 = {'name': 'fake_aggregate12'}
        values3 = {'name': 'fake_aggregate23'}
        a2_hosts = ['foo1.openstack.org', 'foo2.openstack.org']
        a2_metadata = {'good': 'value12', 'bad': 'badvalue12'}
        a3_hosts = ['foo2.openstack.org', 'foo3.openstack.org']
        a3_metadata = {'good': 'value23', 'bad': 'badvalue23'}
        a1 = _create_aggregate_with_hosts(context=ctxt)
        a2 = _create_aggregate_with_hosts(context=ctxt, values=values2,
                hosts=a2_hosts, metadata=a2_metadata)
        a3 = _create_aggregate_with_hosts(context=ctxt, values=values3,
                hosts=a3_hosts, metadata=a3_metadata)
        r1 = db.aggregate_host_get_by_metadata_key(ctxt, key='good')
        self.assertEqual({
            'foo1.openstack.org': set(['value12']),
            'foo2.openstack.org': set(['value12', 'value23']),
            'foo3.openstack.org': set(['value23']),
        }, r1)
        self.assertFalse('fake_key1' in r1)

    def test_aggregate_get_by_host_not_found(self):
        ctxt = context.get_admin_context()
        _create_aggregate_with_hosts(context=ctxt)
        self.assertEqual([], db.aggregate_get_by_host(ctxt, 'unknown_host'))

    def test_aggregate_delete_raise_not_found(self):
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_delete,
                          ctxt, aggregate_id)

    def test_aggregate_delete(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        db.aggregate_delete(ctxt, result['id'])
        expected = db.aggregate_get_all(ctxt)
        self.assertEqual(0, len(expected))
        aggregate = db.aggregate_get(ctxt.elevated(read_deleted='yes'),
                                     result['id'])
        self.assertEqual(aggregate['deleted'], True)

    def test_aggregate_update(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata={'availability_zone':
            'fake_avail_zone'})
        self.assertEqual(result['availability_zone'], 'fake_avail_zone')
        new_values = _get_fake_aggr_values()
        new_values['availability_zone'] = 'different_avail_zone'
        updated = db.aggregate_update(ctxt, 1, new_values)
        self.assertNotEqual(result['availability_zone'],
                            updated['availability_zone'])

    def test_aggregate_update_with_metadata(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        values['availability_zone'] = 'different_avail_zone'
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        updated = db.aggregate_get(ctxt, result['id'])
        self.assertThat(values['metadata'],
                        matchers.DictMatches(expected))
        self.assertNotEqual(result['availability_zone'],
                            updated['availability_zone'])

    def test_aggregate_update_with_existing_metadata(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        values['metadata']['fake_key1'] = 'foo'
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(values['metadata'], matchers.DictMatches(expected))

    def test_aggregate_update_zone_with_existing_metadata(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        new_zone = {'availability_zone': 'fake_avail_zone_2'}
        metadata = _get_fake_aggr_metadata()
        metadata.update(new_zone)
        db.aggregate_update(ctxt, result['id'], new_zone)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_update_raise_not_found(self):
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        new_values = _get_fake_aggr_values()
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_update, ctxt, aggregate_id, new_values)

    def test_aggregate_get_all(self):
        ctxt = context.get_admin_context()
        counter = 3
        for c in range(counter):
            _create_aggregate(context=ctxt,
                              values={'name': 'fake_aggregate_%d' % c},
                              metadata=None)
        results = db.aggregate_get_all(ctxt)
        self.assertEqual(len(results), counter)

    def test_aggregate_get_all_non_deleted(self):
        ctxt = context.get_admin_context()
        add_counter = 5
        remove_counter = 2
        aggregates = []
        for c in range(1, add_counter):
            values = {'name': 'fake_aggregate_%d' % c}
            aggregates.append(_create_aggregate(context=ctxt,
                                                values=values, metadata=None))
        for c in range(1, remove_counter):
            db.aggregate_delete(ctxt, aggregates[c - 1]['id'])
        results = db.aggregate_get_all(ctxt)
        self.assertEqual(len(results), add_counter - remove_counter)

    def test_aggregate_metadata_add(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result['id'], metadata)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_update(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        metadata = _get_fake_aggr_metadata()
        key = metadata.keys()[0]
        db.aggregate_metadata_delete(ctxt, result['id'], key)
        new_metadata = {key: 'foo'}
        db.aggregate_metadata_add(ctxt, result['id'], new_metadata)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        metadata[key] = 'foo'
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_delete(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result['id'], metadata)
        db.aggregate_metadata_delete(ctxt, result['id'], metadata.keys()[0])
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        del metadata[metadata.keys()[0]]
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_remove_availability_zone(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata={'availability_zone':
            'fake_avail_zone'})
        db.aggregate_metadata_delete(ctxt, result['id'], 'availability_zone')
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        aggregate = db.aggregate_get(ctxt, result['id'])
        self.assertEquals(aggregate['availability_zone'], None)
        self.assertThat({}, matchers.DictMatches(expected))

    def test_aggregate_metadata_delete_raise_not_found(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateMetadataNotFound,
                          db.aggregate_metadata_delete,
                          ctxt, result['id'], 'foo_key')

    def test_aggregate_host_add(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        expected = db.aggregate_host_get_all(ctxt, result['id'])
        self.assertEqual(_get_fake_aggr_hosts(), expected)

    def test_aggregate_host_re_add(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        host = _get_fake_aggr_hosts()[0]
        db.aggregate_host_delete(ctxt, result['id'], host)
        db.aggregate_host_add(ctxt, result['id'], host)
        expected = db.aggregate_host_get_all(ctxt, result['id'])
        self.assertEqual(len(expected), 1)

    def test_aggregate_host_add_duplicate_works(self):
        ctxt = context.get_admin_context()
        r1 = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        r2 = _create_aggregate_with_hosts(ctxt,
                          values={'name': 'fake_aggregate2'},
                          metadata={'availability_zone': 'fake_avail_zone2'})
        h1 = db.aggregate_host_get_all(ctxt, r1['id'])
        h2 = db.aggregate_host_get_all(ctxt, r2['id'])
        self.assertEqual(h1, h2)

    def test_aggregate_host_add_duplicate_raise_exist_exc(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        self.assertRaises(exception.AggregateHostExists,
                          db.aggregate_host_add,
                          ctxt, result['id'], _get_fake_aggr_hosts()[0])

    def test_aggregate_host_add_raise_not_found(self):
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        host = _get_fake_aggr_hosts()[0]
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_host_add,
                          ctxt, aggregate_id, host)

    def test_aggregate_host_delete(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        db.aggregate_host_delete(ctxt, result['id'],
                                 _get_fake_aggr_hosts()[0])
        expected = db.aggregate_host_get_all(ctxt, result['id'])
        self.assertEqual(0, len(expected))

    def test_aggregate_host_delete_raise_not_found(self):
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateHostNotFound,
                          db.aggregate_host_delete,
                          ctxt, result['id'], _get_fake_aggr_hosts()[0])


class SqlAlchemyDbApiTestCase(DbTestCase):
    def test_instance_get_all_by_host(self):
        ctxt = context.get_admin_context()

        self.create_instance_with_args()
        self.create_instance_with_args()
        self.create_instance_with_args(host='host2')
        result = sqlalchemy_api._instance_get_all_uuids_by_host(ctxt, 'host1')
        self.assertEqual(2, len(result))

    def test_instance_get_all_uuids_by_host(self):
        ctxt = context.get_admin_context()
        self.create_instance_with_args()
        self.create_instance_with_args()
        self.create_instance_with_args(host='host2')
        result = sqlalchemy_api._instance_get_all_uuids_by_host(ctxt, 'host1')
        self.assertEqual(2, len(result))
        self.assertEqual(types.UnicodeType, type(result[0]))


class MigrationTestCase(test.TestCase):

    def setUp(self):
        super(MigrationTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        self._create()
        self._create()
        self._create(status='reverted')
        self._create(status='confirmed')
        self._create(source_compute='host2', source_node='b',
                dest_compute='host1', dest_node='a')
        self._create(source_compute='host2', dest_compute='host3')
        self._create(source_compute='host3', dest_compute='host4')

    def _create(self, status='migrating', source_compute='host1',
                source_node='a', dest_compute='host2', dest_node='b',
                system_metadata=None):

        values = {'host': source_compute}
        instance = db.instance_create(self.ctxt, values)
        if system_metadata:
            db.instance_system_metadata_update(self.ctxt, instance['uuid'],
                                               system_metadata, False)

        values = {'status': status, 'source_compute': source_compute,
                  'source_node': source_node, 'dest_compute': dest_compute,
                  'dest_node': dest_node, 'instance_uuid': instance['uuid']}
        db.migration_create(self.ctxt, values)

    def _assert_in_progress(self, migrations):
        for migration in migrations:
            self.assertNotEqual('confirmed', migration['status'])
            self.assertNotEqual('reverted', migration['status'])

    def test_migration_get_in_progress_joins(self):
        self._create(source_compute='foo', system_metadata={'foo': 'bar'})
        migrations = db.migration_get_in_progress_by_host_and_node(self.ctxt,
                'foo', 'a')
        system_metadata = migrations[0]['instance']['system_metadata'][0]
        self.assertEqual(system_metadata['key'], 'foo')
        self.assertEqual(system_metadata['value'], 'bar')

    def test_in_progress_host1_nodea(self):
        migrations = db.migration_get_in_progress_by_host_and_node(self.ctxt,
                'host1', 'a')
        # 2 as source + 1 as dest
        self.assertEqual(3, len(migrations))
        self._assert_in_progress(migrations)

    def test_in_progress_host1_nodeb(self):
        migrations = db.migration_get_in_progress_by_host_and_node(self.ctxt,
                'host1', 'b')
        # some migrations are to/from host1, but none with a node 'b'
        self.assertEqual(0, len(migrations))

    def test_in_progress_host2_nodeb(self):
        migrations = db.migration_get_in_progress_by_host_and_node(self.ctxt,
                'host2', 'b')
        # 2 as dest, 1 as source
        self.assertEqual(3, len(migrations))
        self._assert_in_progress(migrations)

    def test_instance_join(self):
        migrations = db.migration_get_in_progress_by_host_and_node(self.ctxt,
                'host2', 'b')
        for migration in migrations:
            instance = migration['instance']
            self.assertEqual(migration['instance_uuid'], instance['uuid'])

    def test_get_migrations_by_filters(self):
        filters = {"status": "migrating", "host": "host3"}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        self.assertEqual(2, len(migrations))
        for migration in migrations:
            self.assertEqual(filters["status"], migration['status'])
            hosts = [migration['source_compute'], migration['dest_compute']]
            self.assertIn(filters["host"], hosts)

    def test_only_admin_can_get_all_migrations_by_filters(self):
        user_ctxt = context.RequestContext(user_id=None, project_id=None,
                                   is_admin=False, read_deleted="no",
                                   overwrite=False)

        self.assertRaises(exception.AdminRequired,
                          db.migration_get_all_by_filters, user_ctxt, {})

    def test_migration_get_unconfirmed_by_dest_compute(self):
        # Ensure no migrations are returned.
        results = db.migration_get_unconfirmed_by_dest_compute(self.ctxt, 10,
                'fake_host')
        self.assertEqual(0, len(results))

        # Ensure no migrations are returned.
        results = db.migration_get_unconfirmed_by_dest_compute(self.ctxt, 10,
                'fake_host2')
        self.assertEqual(0, len(results))

        updated_at = datetime.datetime(2000, 1, 1, 12, 0, 0)
        values = {"status": "finished", "updated_at": updated_at,
                "dest_compute": "fake_host2"}
        migration = db.migration_create(self.ctxt, values)

        # Ensure different host is not returned
        results = db.migration_get_unconfirmed_by_dest_compute(self.ctxt, 10,
                'fake_host')
        self.assertEqual(0, len(results))

        # Ensure one migration older than 10 seconds is returned.
        results = db.migration_get_unconfirmed_by_dest_compute(self.ctxt, 10,
                'fake_host2')
        self.assertEqual(1, len(results))
        db.migration_update(self.ctxt, migration['id'],
                            {"status": "CONFIRMED"})

        # Ensure the new migration is not returned.
        updated_at = timeutils.utcnow()
        values = {"status": "finished", "updated_at": updated_at,
                "dest_compute": "fake_host2"}
        migration = db.migration_create(self.ctxt, values)
        results = db.migration_get_unconfirmed_by_dest_compute(self.ctxt, 10,
                "fake_host2")
        self.assertEqual(0, len(results))
        db.migration_update(self.ctxt, migration['id'],
                            {"status": "CONFIRMED"})


class ModelsObjectComparatorMixin(object):
    def _dict_from_object(self, obj, ignored_keys):
        if ignored_keys is None:
            ignored_keys = []
        return dict([(k, v) for k, v in obj.iteritems()
                                if k not in ignored_keys])

    def _assertEqualObjects(self, obj1, obj2, ignored_keys=None):
        obj1 = self._dict_from_object(obj1, ignored_keys)
        obj2 = self._dict_from_object(obj2, ignored_keys)

        self.assertEqual(len(obj1),
                         len(obj2),
                         "Keys mismatch: %s" %
                          str(set(obj1.keys()) ^ set(obj2.keys())))
        for key, value in obj1.iteritems():
            self.assertEqual(value, obj2[key])

    def _assertEqualListsOfObjects(self, objs1, objs2, ignored_keys=None):
        obj_to_dict = lambda o: self._dict_from_object(o, ignored_keys)
        sort_key = lambda d: [d[k] for k in sorted(d)]
        conv_and_sort = lambda obj: sorted(map(obj_to_dict, obj), key=sort_key)

        self.assertEqual(conv_and_sort(objs1), conv_and_sort(objs2))

    def _assertEqualListsOfPrimitivesAsSets(self, primitives1, primitives2):
        self.assertEqual(len(primitives1), len(primitives2))
        for primitive in primitives1:
            self.assertIn(primitive, primitives2)

        for primitive in primitives2:
            self.assertIn(primitive, primitives1)


class InstanceSystemMetadataTestCase(test.TestCase):

    """Tests for db.api.instance_system_metadata_* methods."""

    def setUp(self):
        super(InstanceSystemMetadataTestCase, self).setUp()
        values = {'host': 'h1', 'project_id': 'p1',
                  'system_metadata': {'key': 'value'}}
        self.ctxt = context.get_admin_context()
        self.instance = db.instance_create(self.ctxt, values)

    def test_instance_system_metadata_get(self):
        metadata = db.instance_system_metadata_get(self.ctxt,
                                                   self.instance['uuid'])
        self.assertEqual(metadata, {'key': 'value'})

    def test_instance_system_metadata_update_new_pair(self):
        db.instance_system_metadata_update(
                    self.ctxt, self.instance['uuid'],
                    {'new_key': 'new_value'}, False)
        metadata = db.instance_system_metadata_get(self.ctxt,
                                                   self.instance['uuid'])
        self.assertEqual(metadata, {'key': 'value', 'new_key': 'new_value'})

    def test_instance_system_metadata_update_existent_pair(self):
        db.instance_system_metadata_update(
                    self.ctxt, self.instance['uuid'],
                    {'key': 'new_value'}, True)
        metadata = db.instance_system_metadata_get(self.ctxt,
                                                   self.instance['uuid'])
        self.assertEqual(metadata, {'key': 'new_value'})

    def test_instance_system_metadata_update_delete_true(self):
        db.instance_system_metadata_update(
                    self.ctxt, self.instance['uuid'],
                    {'new_key': 'new_value'}, True)
        metadata = db.instance_system_metadata_get(self.ctxt,
                                                   self.instance['uuid'])
        self.assertEqual(metadata, {'new_key': 'new_value'})

    @test.testtools.skip("bug 1189462")
    def test_instance_system_metadata_update_nonexistent(self):
        self.assertRaises(exception.InstanceNotFound,
                          db.instance_system_metadata_update,
                          self.ctxt, 'nonexistent-uuid',
                          {'key': 'value'}, True)


class ReservationTestCase(test.TestCase, ModelsObjectComparatorMixin):

    """Tests for db.api.reservation_* methods."""

    def setUp(self):
        super(ReservationTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.values = {'uuid': 'sample-uuid',
                'project_id': 'project1',
                'user_id': 'user1',
                'resource': 'resource',
                'delta': 42,
                'expire': timeutils.utcnow() + datetime.timedelta(days=1),
                'usage': {'id': 1}}

    def test_reservation_create(self):
        reservation = db.reservation_create(self.ctxt, **self.values)
        self._assertEqualObjects(self.values, reservation, ignored_keys=(
                        'deleted', 'updated_at',
                        'deleted_at', 'id',
                        'created_at', 'usage',
                        'usage_id'))
        self.assertEqual(reservation['usage_id'], self.values['usage']['id'])

    def test_reservation_get(self):
        reservation = db.reservation_create(self.ctxt, **self.values)
        reservation_db = db.reservation_get(self.ctxt, self.values['uuid'])
        self._assertEqualObjects(reservation, reservation_db)

    def test_reservation_get_nonexistent(self):
        self.assertRaises(exception.ReservationNotFound, db.reservation_get,
                                    self.ctxt, 'non-exitent-resevation-uuid')

    def test_reservation_commit(self):
        reservations = _quota_reserve(self.ctxt, 'project1', 'user1')
        expected = {'project_id': 'project1', 'user_id': 'user1',
                'resource0': {'reserved': 0, 'in_use': 0},
                'resource1': {'reserved': 1, 'in_use': 1},
                'resource2': {'reserved': 2, 'in_use': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project_and_user(
                                            self.ctxt, 'project1', 'user1'))
        db.reservation_get(self.ctxt, reservations[0])
        db.reservation_commit(self.ctxt, reservations, 'project1', 'user1')
        self.assertRaises(exception.ReservationNotFound,
            db.reservation_get, self.ctxt, reservations[0])
        expected = {'project_id': 'project1', 'user_id': 'user1',
                'resource0': {'reserved': 0, 'in_use': 0},
                'resource1': {'reserved': 0, 'in_use': 2},
                'resource2': {'reserved': 0, 'in_use': 4}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project_and_user(
                                            self.ctxt, 'project1', 'user1'))

    def test_reservation_rollback(self):
        reservations = _quota_reserve(self.ctxt, 'project1', 'user1')
        expected = {'project_id': 'project1', 'user_id': 'user1',
                'resource0': {'reserved': 0, 'in_use': 0},
                'resource1': {'reserved': 1, 'in_use': 1},
                'resource2': {'reserved': 2, 'in_use': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project_and_user(
                                            self.ctxt, 'project1', 'user1'))
        db.reservation_get(self.ctxt, reservations[0])
        db.reservation_rollback(self.ctxt, reservations, 'project1', 'user1')
        self.assertRaises(exception.ReservationNotFound,
            db.reservation_get, self.ctxt, reservations[0])
        expected = {'project_id': 'project1', 'user_id': 'user1',
                'resource0': {'reserved': 0, 'in_use': 0},
                'resource1': {'reserved': 0, 'in_use': 1},
                'resource2': {'reserved': 0, 'in_use': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project_and_user(
                                            self.ctxt, 'project1', 'user1'))

    def test_reservation_expire(self):
        self.values['expire'] = timeutils.utcnow() + datetime.timedelta(days=1)
        _quota_reserve(self.ctxt, 'project1', 'user1')
        db.reservation_expire(self.ctxt)

        expected = {'project_id': 'project1', 'user_id': 'user1',
                'resource0': {'reserved': 0, 'in_use': 0},
                'resource1': {'reserved': 0, 'in_use': 1},
                'resource2': {'reserved': 0, 'in_use': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project_and_user(
                                            self.ctxt, 'project1', 'user1'))


class SecurityGroupRuleTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(SecurityGroupRuleTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _get_base_values(self):
        return {
            'name': 'fake_sec_group',
            'description': 'fake_sec_group_descr',
            'user_id': 'fake',
            'project_id': 'fake',
            'instances': []
            }

    def _get_base_rule_values(self):
        return {
            'protocol': "tcp",
            'from_port': 80,
            'to_port': 8080,
            'cidr': None,
            'deleted': 0,
            'deleted_at': None,
            'grantee_group': None,
            'updated_at': None
            }

    def _create_security_group(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.security_group_create(self.ctxt, v)

    def _create_security_group_rule(self, values):
        v = self._get_base_rule_values()
        v.update(values)
        return db.security_group_rule_create(self.ctxt, v)

    def test_security_group_rule_create(self):
        security_group_rule = self._create_security_group_rule({})
        self.assertIsNotNone(security_group_rule['id'])
        for key, value in self._get_base_rule_values().items():
            self.assertEqual(value, security_group_rule[key])

    def test_security_group_rule_get_by_security_group(self):
        security_group = self._create_security_group({})
        security_group_rule = self._create_security_group_rule(
            {'parent_group': security_group})
        security_group_rule1 = self._create_security_group_rule(
            {'parent_group': security_group})
        found_rules = db.security_group_rule_get_by_security_group(self.ctxt,
                                                        security_group['id'])
        self.assertEqual(len(found_rules), 2)
        rules_ids = [security_group_rule['id'], security_group_rule1['id']]
        for rule in found_rules:
            self.assertIn(rule['id'], rules_ids)

    def test_security_group_rule_get_by_security_group_grantee(self):
        security_group = self._create_security_group({})
        security_group_rule = self._create_security_group_rule(
            {'grantee_group': security_group})
        rules = db.security_group_rule_get_by_security_group_grantee(self.ctxt,
                                                          security_group['id'])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['id'], security_group_rule['id'])

    def test_security_group_rule_destroy(self):
        security_group1 = self._create_security_group({'name': 'fake1'})
        security_group2 = self._create_security_group({'name': 'fake2'})
        security_group_rule1 = self._create_security_group_rule({})
        security_group_rule2 = self._create_security_group_rule({})
        db.security_group_rule_destroy(self.ctxt, security_group_rule1['id'])
        self.assertRaises(exception.SecurityGroupNotFound,
                          db.security_group_rule_get,
                          self.ctxt, security_group_rule1['id'])
        self._assertEqualObjects(db.security_group_rule_get(self.ctxt,
                                        security_group_rule2['id']),
                                 security_group_rule2, ['grantee_group'])

    def test_security_group_rule_destroy_not_found_exception(self):
        self.assertRaises(exception.SecurityGroupNotFound,
                          db.security_group_rule_destroy, self.ctxt, 100500)

    def test_security_group_rule_get(self):
        security_group_rule1 = (
                self._create_security_group_rule({}))
        security_group_rule2 = self._create_security_group_rule({})
        real_security_group_rule = db.security_group_rule_get(self.ctxt,
                                              security_group_rule1['id'])
        self._assertEqualObjects(security_group_rule1,
                                 real_security_group_rule, ['grantee_group'])

    def test_security_group_rule_get_not_found_exception(self):
        self.assertRaises(exception.SecurityGroupNotFound,
                          db.security_group_rule_get, self.ctxt, 100500)

    def test_security_group_rule_count_by_group(self):
        sg1 = self._create_security_group({'name': 'fake1'})
        sg2 = self._create_security_group({'name': 'fake2'})
        rules_by_group = {sg1: [], sg2: []}
        for group in rules_by_group:
            rules = rules_by_group[group]
            for i in range(0, 10):
                rules.append(
                    self._create_security_group_rule({'parent_group_id':
                                                    group['id']}))
        db.security_group_rule_destroy(self.ctxt,
                                       rules_by_group[sg1][0]['id'])
        counted_groups = [db.security_group_rule_count_by_group(self.ctxt,
                                                                group['id'])
                          for group in [sg1, sg2]]
        expected = [9, 10]
        self.assertEqual(counted_groups, expected)


class SecurityGroupTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(SecurityGroupTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _get_base_values(self):
        return {
            'name': 'fake_sec_group',
            'description': 'fake_sec_group_descr',
            'user_id': 'fake',
            'project_id': 'fake',
            'instances': []
            }

    def _create_security_group(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.security_group_create(self.ctxt, v)

    def test_security_group_create(self):
        security_group = self._create_security_group({})
        self.assertFalse(security_group['id'] is None)
        for key, value in self._get_base_values().iteritems():
            self.assertEqual(value, security_group[key])

    def test_security_group_destroy(self):
        security_group1 = self._create_security_group({})
        security_group2 = \
            self._create_security_group({'name': 'fake_sec_group2'})

        db.security_group_destroy(self.ctxt, security_group1['id'])
        self.assertRaises(exception.SecurityGroupNotFound,
                          db.security_group_get,
                          self.ctxt, security_group1['id'])
        self._assertEqualObjects(db.security_group_get(
                self.ctxt, security_group2['id'],
                columns_to_join=['instances']), security_group2)

    def test_security_group_get(self):
        security_group1 = self._create_security_group({})
        self._create_security_group({'name': 'fake_sec_group2'})
        real_security_group = db.security_group_get(self.ctxt,
                                              security_group1['id'],
                                              columns_to_join=['instances'])
        self._assertEqualObjects(security_group1,
                                 real_security_group)

    def test_security_group_get_no_instances(self):
        instance = db.instance_create(self.ctxt, {})
        sid = self._create_security_group({'instances': [instance]})['id']

        session = get_session()
        self.mox.StubOutWithMock(sqlalchemy_api, 'get_session')
        sqlalchemy_api.get_session().AndReturn(session)
        sqlalchemy_api.get_session().AndReturn(session)
        self.mox.ReplayAll()

        security_group = db.security_group_get(self.ctxt, sid,
                                               columns_to_join=['instances'])
        session.expunge(security_group)
        self.assertEqual(1, len(security_group['instances']))

        security_group = db.security_group_get(self.ctxt, sid)
        session.expunge(security_group)
        self.assertRaises(sqlalchemy_orm_exc.DetachedInstanceError,
                          getattr, security_group, 'instances')

    def test_security_group_get_not_found_exception(self):
        self.assertRaises(exception.SecurityGroupNotFound,
                          db.security_group_get, self.ctxt, 100500)

    def test_security_group_get_by_name(self):
        security_group1 = self._create_security_group({'name': 'fake1'})
        security_group2 = self._create_security_group({'name': 'fake2'})

        real_security_group1 = db.security_group_get_by_name(
                                self.ctxt,
                                security_group1['project_id'],
                                security_group1['name'])
        real_security_group2 = db.security_group_get_by_name(
                                self.ctxt,
                                security_group2['project_id'],
                                security_group2['name'])
        self._assertEqualObjects(security_group1, real_security_group1)
        self._assertEqualObjects(security_group2, real_security_group2)

    def test_security_group_get_by_project(self):
        security_group1 = self._create_security_group(
                {'name': 'fake1', 'project_id': 'fake_proj1'})
        security_group2 = self._create_security_group(
                {'name': 'fake2', 'project_id': 'fake_proj2'})

        real1 = db.security_group_get_by_project(
                               self.ctxt,
                               security_group1['project_id'])
        real2 = db.security_group_get_by_project(
                               self.ctxt,
                               security_group2['project_id'])

        expected1, expected2 = [security_group1], [security_group2]
        self._assertEqualListsOfObjects(expected1, real1,
                                        ignored_keys=['instances'])
        self._assertEqualListsOfObjects(expected2, real2,
                                        ignored_keys=['instances'])

    def test_security_group_get_by_instance(self):
        instance = db.instance_create(self.ctxt, dict(host='foo'))
        values = [
            {'name': 'fake1', 'instances': [instance]},
            {'name': 'fake2', 'instances': [instance]},
            {'name': 'fake3', 'instances': []},
        ]
        security_groups = [self._create_security_group(vals)
                           for vals in values]

        real = db.security_group_get_by_instance(self.ctxt,
                                                 instance['uuid'])
        expected = security_groups[:2]
        self._assertEqualListsOfObjects(expected, real,
                                        ignored_keys=['instances'])

    def test_security_group_get_all(self):
        values = [
            {'name': 'fake1', 'project_id': 'fake_proj1'},
            {'name': 'fake2', 'project_id': 'fake_proj2'},
        ]
        security_groups = [self._create_security_group(vals)
                           for vals in values]

        real = db.security_group_get_all(self.ctxt)

        self._assertEqualListsOfObjects(security_groups, real,
                                        ignored_keys=['instances'])

    def test_security_group_in_use(self):
        instance = db.instance_create(self.ctxt, dict(host='foo'))
        values = [
            {'instances': [instance],
             'name': 'fake_in_use'},
            {'instances': []},
        ]

        security_groups = [self._create_security_group(vals)
                           for vals in values]

        real = []
        for security_group in security_groups:
            in_use = db.security_group_in_use(self.ctxt,
                                              security_group['id'])
            real.append(in_use)
        expected = [True, False]

        self.assertEquals(expected, real)

    def test_security_group_ensure_default(self):
        self.assertEquals(0, len(db.security_group_get_by_project(
                                    self.ctxt,
                                    self.ctxt.project_id)))

        db.security_group_ensure_default(self.ctxt)

        security_groups = db.security_group_get_by_project(
                            self.ctxt,
                            self.ctxt.project_id)

        self.assertEquals(1, len(security_groups))
        self.assertEquals("default", security_groups[0]["name"])

    def test_security_group_update(self):
        security_group = self._create_security_group({})
        new_values = {
                    'name': 'sec_group1',
                    'description': 'sec_group_descr1',
                    'user_id': 'fake_user1',
                    'project_id': 'fake_proj1',
        }
        updated_group = db.security_group_update(self.ctxt,
                                                 security_group['id'],
                                                 new_values)
        for key, value in new_values.iteritems():
            self.assertEqual(updated_group[key], value)

    def test_security_group_update_to_duplicate(self):
        security_group1 = self._create_security_group(
                {'name': 'fake1', 'project_id': 'fake_proj1'})
        security_group2 = self._create_security_group(
                {'name': 'fake1', 'project_id': 'fake_proj2'})

        self.assertRaises(exception.SecurityGroupExists,
                          db.security_group_update,
                          self.ctxt, security_group2['id'],
                          {'project_id': 'fake_proj1'})


class InstanceTestCase(test.TestCase, ModelsObjectComparatorMixin):

    """Tests for db.api.instance_* methods."""

    sample_data = {
        'project_id': 'project1',
        'hostname': 'example.com',
        'host': 'h1',
        'node': 'n1',
        'metadata': {'mkey1': 'mval1', 'mkey2': 'mval2'},
        'system_metadata': {'smkey1': 'smval1', 'smkey2': 'smval2'},
        'info_cache': {'ckey': 'cvalue'},
    }

    def setUp(self):
        super(InstanceTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _assertEqualInstances(self, instance1, instance2):
        self._assertEqualObjects(instance1, instance2,
                ignored_keys=['metadata', 'system_metadata', 'info_cache'])

    def _assertEqualListsOfInstances(self, list1, list2):
        self._assertEqualListsOfObjects(list1, list2,
                ignored_keys=['metadata', 'system_metadata', 'info_cache'])

    def create_instance_with_args(self, **kwargs):
        if 'context' in kwargs:
            context = kwargs.pop('context')
        else:
            context = self.ctxt
        args = self.sample_data.copy()
        args.update(kwargs)
        return db.instance_create(context, args)

    def test_instance_create(self):
        instance = self.create_instance_with_args()
        self.assertTrue(uuidutils.is_uuid_like(instance['uuid']))

    def test_instance_get_all_with_meta(self):
        inst = self.create_instance_with_args()
        for inst in db.instance_get_all(self.ctxt):
            meta = utils.metadata_to_dict(inst['metadata'])
            self.assertEqual(meta, self.sample_data['metadata'])
            sys_meta = utils.metadata_to_dict(inst['system_metadata'])
            self.assertEqual(sys_meta, self.sample_data['system_metadata'])

    def test_instance_update(self):
        instance = self.create_instance_with_args()
        metadata = {'host': 'bar', 'key2': 'wuff'}
        system_metadata = {'original_image_ref': 'baz'}
        # Update the metadata
        db.instance_update(self.ctxt, instance['uuid'], {'metadata': metadata,
                           'system_metadata': system_metadata})
        # Retrieve the user-provided metadata to ensure it was successfully
        # updated
        self.assertEqual(metadata,
                db.instance_metadata_get(self.ctxt, instance['uuid']))
        self.assertEqual(system_metadata,
                db.instance_system_metadata_get(self.ctxt, instance['uuid']))

    def test_instance_update_bad_str_dates(self):
        instance = self.create_instance_with_args()
        values = {'created_at': '123'}
        self.assertRaises(ValueError,
                          db.instance_update,
                          self.ctxt, instance['uuid'], values)

    def test_instance_update_good_str_dates(self):
        instance = self.create_instance_with_args()
        values = {'created_at': '2011-01-31T00:00:00.0'}
        actual = db.instance_update(self.ctxt, instance['uuid'], values)
        expected = datetime.datetime(2011, 1, 31)
        self.assertEquals(expected, actual["created_at"])

    def test_create_instance_unique_hostname(self):
        context1 = context.RequestContext('user1', 'p1')
        context2 = context.RequestContext('user2', 'p2')
        self.create_instance_with_args(hostname='h1', project_id='p1')

        # With scope 'global' any duplicate should fail, be it this project:
        self.flags(osapi_compute_unique_server_name_scope='global')
        self.assertRaises(exception.InstanceExists,
                          self.create_instance_with_args,
                          context=context1,
                          hostname='h1', project_id='p3')
        # or another:
        self.assertRaises(exception.InstanceExists,
                          self.create_instance_with_args,
                          context=context2,
                          hostname='h1', project_id='p2')
        # With scope 'project' a duplicate in the project should fail:
        self.flags(osapi_compute_unique_server_name_scope='project')
        self.assertRaises(exception.InstanceExists,
                          self.create_instance_with_args,
                          context=context1,
                          hostname='h1', project_id='p1')
        # With scope 'project' a duplicate in a different project should work:
        self.flags(osapi_compute_unique_server_name_scope='project')
        self.create_instance_with_args(context=context2, hostname='h2')
        self.flags(osapi_compute_unique_server_name_scope=None)

    def test_instance_get_all_with_meta(self):
        inst = self.create_instance_with_args()
        for inst in db.instance_get_all(self.ctxt):
            meta = utils.metadata_to_dict(inst['metadata'])
            self.assertEqual(meta, self.sample_data['metadata'])
            sys_meta = utils.metadata_to_dict(inst['system_metadata'])
            self.assertEqual(sys_meta, self.sample_data['system_metadata'])

    def test_instance_get_all_by_filters_with_meta(self):
        inst = self.create_instance_with_args()
        for inst in db.instance_get_all_by_filters(self.ctxt, {}):
            meta = utils.metadata_to_dict(inst['metadata'])
            self.assertEqual(meta, self.sample_data['metadata'])
            sys_meta = utils.metadata_to_dict(inst['system_metadata'])
            self.assertEqual(sys_meta, self.sample_data['system_metadata'])

    def test_instance_get_all_by_filters_without_meta(self):
        inst = self.create_instance_with_args()
        result = db.instance_get_all_by_filters(self.ctxt, {},
                                                columns_to_join=[])
        for inst in result:
            meta = utils.metadata_to_dict(inst['metadata'])
            self.assertEqual(meta, {})
            sys_meta = utils.metadata_to_dict(inst['system_metadata'])
            self.assertEqual(sys_meta, {})

    def test_instance_get_all_by_filters(self):
        instances = [self.create_instance_with_args() for i in range(3)]
        filtered_instances = db.instance_get_all_by_filters(self.ctxt, {})
        self._assertEqualListsOfInstances(instances, filtered_instances)

    def test_instance_metadata_get_multi(self):
        uuids = [self.create_instance_with_args()['uuid'] for i in range(3)]
        meta = sqlalchemy_api._instance_metadata_get_multi(self.ctxt, uuids)
        for row in meta:
            self.assertTrue(row['instance_uuid'] in uuids)

    def test_instance_metadata_get_multi_no_uuids(self):
        self.mox.StubOutWithMock(query.Query, 'filter')
        self.mox.ReplayAll()
        sqlalchemy_api._instance_metadata_get_multi(self.ctxt, [])

    def test_instance_system_system_metadata_get_multi(self):
        uuids = [self.create_instance_with_args()['uuid'] for i in range(3)]
        sys_meta = sqlalchemy_api._instance_system_metadata_get_multi(
                self.ctxt, uuids)
        for row in sys_meta:
            self.assertTrue(row['instance_uuid'] in uuids)

    def test_instance_system_metadata_get_multi_no_uuids(self):
        self.mox.StubOutWithMock(query.Query, 'filter')
        self.mox.ReplayAll()
        sqlalchemy_api._instance_system_metadata_get_multi(self.ctxt, [])

    def test_instance_get_all_by_filters_regex(self):
        i1 = self.create_instance_with_args(display_name='test1')
        i2 = self.create_instance_with_args(display_name='teeeest2')
        self.create_instance_with_args(display_name='diff')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'display_name': 't.*st.'})
        self._assertEqualListsOfInstances(result, [i1, i2])

    def test_instance_get_all_by_filters_exact_match(self):
        instance = self.create_instance_with_args(host='host1')
        self.create_instance_with_args(host='host12')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'host': 'host1'})
        self._assertEqualListsOfInstances([instance], result)

    def test_instance_get_all_by_filters_metadata(self):
        instance = self.create_instance_with_args(metadata={'foo': 'bar'})
        self.create_instance_with_args()
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'metadata': {'foo': 'bar'}})
        self._assertEqualListsOfInstances([instance], result)

    def test_instance_get_all_by_filters_unicode_value(self):
        instance = self.create_instance_with_args(display_name=u'test♥')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'display_name': u'test'})
        self._assertEqualListsOfInstances([instance], result)

    def test_instance_get_all_by_filters_tags(self):
        instance = self.create_instance_with_args(
            metadata={'foo': 'bar'})
        self.create_instance_with_args()
        #For format 'tag-'
        result = db.instance_get_all_by_filters(
            self.ctxt, {'filter': [
                {'name': 'tag-key', 'value': 'foo'},
                {'name': 'tag-value', 'value': 'bar'},
            ]})
        self._assertEqualListsOfInstances([instance], result)
        #For format 'tag:'
        result = db.instance_get_all_by_filters(
            self.ctxt, {'filter': [
                {'name': 'tag:foo', 'value': 'bar'},
            ]})
        self._assertEqualListsOfInstances([instance], result)
        #For non-existent tag
        result = db.instance_get_all_by_filters(
            self.ctxt, {'filter': [
                {'name': 'tag:foo', 'value': 'barred'},
            ]})
        self.assertEqual([], result)

        #Confirm with deleted tags
        db.instance_metadata_delete(self.ctxt, instance['uuid'], 'foo')
        #For format 'tag-'
        result = db.instance_get_all_by_filters(
            self.ctxt, {'filter': [
                {'name': 'tag-key', 'value': 'foo'},
            ]})
        self.assertEqual([], result)
        result = db.instance_get_all_by_filters(
            self.ctxt, {'filter': [
                {'name': 'tag-value', 'value': 'bar'}
            ]})
        self.assertEqual([], result)
        #For format 'tag:'
        result = db.instance_get_all_by_filters(
            self.ctxt, {'filter': [
                {'name': 'tag:foo', 'value': 'bar'},
            ]})
        self.assertEqual([], result)

    def test_instance_get_by_uuid(self):
        inst = self.create_instance_with_args()
        result = db.instance_get_by_uuid(self.ctxt, inst['uuid'])
        self._assertEqualInstances(inst, result)

    def test_instance_get_by_uuid_join_empty(self):
        inst = self.create_instance_with_args()
        result = db.instance_get_by_uuid(self.ctxt, inst['uuid'],
                columns_to_join=[])
        meta = utils.metadata_to_dict(result['metadata'])
        self.assertEqual(meta, {})
        sys_meta = utils.metadata_to_dict(result['system_metadata'])
        self.assertEqual(sys_meta, {})

    def test_instance_get_by_uuid_join_meta(self):
        inst = self.create_instance_with_args()
        result = db.instance_get_by_uuid(self.ctxt, inst['uuid'],
                    columns_to_join=['metadata'])
        meta = utils.metadata_to_dict(result['metadata'])
        self.assertEqual(meta, self.sample_data['metadata'])
        sys_meta = utils.metadata_to_dict(result['system_metadata'])
        self.assertEqual(sys_meta, {})

    def test_instance_get_by_uuid_join_sys_meta(self):
        inst = self.create_instance_with_args()
        result = db.instance_get_by_uuid(self.ctxt, inst['uuid'],
                columns_to_join=['system_metadata'])
        meta = utils.metadata_to_dict(result['metadata'])
        self.assertEqual(meta, {})
        sys_meta = utils.metadata_to_dict(result['system_metadata'])
        self.assertEqual(sys_meta, self.sample_data['system_metadata'])

    def test_instance_get_all_by_filters_deleted(self):
        inst1 = self.create_instance_with_args()
        inst2 = self.create_instance_with_args(reservation_id='b')
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt, {})
        self._assertEqualListsOfObjects([inst1, inst2], result,
            ignored_keys=['metadata', 'system_metadata',
                          'deleted', 'deleted_at', 'info_cache'])

    def test_instance_get_all_by_filters_deleted_and_soft_deleted(self):
        inst1 = self.create_instance_with_args()
        inst2 = self.create_instance_with_args(vm_state=vm_states.SOFT_DELETED)
        inst3 = self.create_instance_with_args()
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'deleted': True})
        self._assertEqualListsOfObjects([inst1, inst2], result,
            ignored_keys=['metadata', 'system_metadata',
                          'deleted', 'deleted_at', 'info_cache'])

    def test_instance_get_all_by_filters_deleted_no_soft_deleted(self):
        inst1 = self.create_instance_with_args()
        inst2 = self.create_instance_with_args(vm_state=vm_states.SOFT_DELETED)
        inst3 = self.create_instance_with_args()
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'deleted': True,
                                                 'soft_deleted': False})
        self._assertEqualListsOfObjects([inst1], result,
                ignored_keys=['deleted', 'deleted_at', 'metadata',
                              'system_metadata', 'info_cache'])

    def test_instance_get_all_by_filters_alive_and_soft_deleted(self):
        inst1 = self.create_instance_with_args()
        inst2 = self.create_instance_with_args(vm_state=vm_states.SOFT_DELETED)
        inst3 = self.create_instance_with_args()
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'deleted': False,
                                                 'soft_deleted': True})
        self._assertEqualListsOfInstances([inst2, inst3], result)

    def test_instance_get_all_by_filters_cleaned(self):
        inst1 = self.create_instance_with_args()
        inst2 = self.create_instance_with_args(reservation_id='b')
        db.instance_update(self.ctxt, inst1['uuid'], {'cleaned': 1})
        result = db.instance_get_all_by_filters(self.ctxt, {})
        self.assertEqual(2, len(result))
        self.assertIn(inst1['uuid'], [result[0]['uuid'], result[1]['uuid']])
        self.assertIn(inst2['uuid'], [result[0]['uuid'], result[1]['uuid']])
        if inst1['uuid'] == result[0]['uuid']:
            self.assertTrue(result[0]['cleaned'])
            self.assertFalse(result[1]['cleaned'])
        else:
            self.assertTrue(result[1]['cleaned'])
            self.assertFalse(result[0]['cleaned'])

    def test_instance_get_all_by_host_and_node_no_join(self):
        instance = self.create_instance_with_args()
        result = db.instance_get_all_by_host_and_node(self.ctxt, 'h1', 'n1')
        self.assertEqual(result[0]['uuid'], instance['uuid'])
        self.assertEqual(result[0]['system_metadata'], [])

    def test_instance_get_all_hung_in_rebooting(self):
        # Ensure no instances are returned.
        results = db.instance_get_all_hung_in_rebooting(self.ctxt, 10)
        self.assertEqual([], results)

        # Ensure one rebooting instance with updated_at older than 10 seconds
        # is returned.
        instance = self.create_instance_with_args(task_state="rebooting",
                updated_at=datetime.datetime(2000, 1, 1, 12, 0, 0))
        results = db.instance_get_all_hung_in_rebooting(self.ctxt, 10)
        self._assertEqualListsOfObjects([instance], results,
            ignored_keys=['task_state', 'info_cache', 'security_groups',
                          'metadata', 'system_metadata'])
        db.instance_update(self.ctxt, instance['uuid'], {"task_state": None})

        # Ensure the newly rebooted instance is not returned.
        instance = self.create_instance_with_args(task_state="rebooting",
                                                updated_at=timeutils.utcnow())
        results = db.instance_get_all_hung_in_rebooting(self.ctxt, 10)
        self.assertEqual([], results)

    def test_instance_update_with_expected_vm_state(self):
        instance = self.create_instance_with_args(vm_state='foo')
        db.instance_update(self.ctxt, instance['uuid'], {'host': 'h1',
                                       'expected_vm_state': ('foo', 'bar')})

    def test_instance_update_with_unexpected_vm_state(self):
        instance = self.create_instance_with_args(vm_state='foo')
        self.assertRaises(exception.UnexpectedVMStateError,
                    db.instance_update, self.ctxt, instance['uuid'],
                    {'host': 'h1', 'expected_vm_state': ('spam', 'bar')})

    def test_instance_update_with_instance_uuid(self):
        # test instance_update() works when an instance UUID is passed.
        ctxt = context.get_admin_context()

        # Create an instance with some metadata
        values = {'metadata': {'host': 'foo', 'key1': 'meow'},
                  'system_metadata': {'original_image_ref': 'blah'}}
        instance = db.instance_create(ctxt, values)

        # Update the metadata
        values = {'metadata': {'host': 'bar', 'key2': 'wuff'},
                  'system_metadata': {'original_image_ref': 'baz'}}
        db.instance_update(ctxt, instance['uuid'], values)

        # Retrieve the user-provided metadata to ensure it was successfully
        # updated
        instance_meta = db.instance_metadata_get(ctxt, instance['uuid'])
        self.assertEqual('bar', instance_meta['host'])
        self.assertEqual('wuff', instance_meta['key2'])
        self.assertNotIn('key1', instance_meta)

        # Retrieve the system metadata to ensure it was successfully updated
        system_meta = db.instance_system_metadata_get(ctxt, instance['uuid'])
        self.assertEqual('baz', system_meta['original_image_ref'])

    def test_delete_instance_metadata_on_instance_destroy(self):
        ctxt = context.get_admin_context()
        # Create an instance with some metadata
        values = {'metadata': {'host': 'foo', 'key1': 'meow'},
                  'system_metadata': {'original_image_ref': 'blah'}}
        instance = db.instance_create(ctxt, values)
        instance_meta = db.instance_metadata_get(ctxt, instance['uuid'])
        self.assertEqual('foo', instance_meta['host'])
        self.assertEqual('meow', instance_meta['key1'])
        db.instance_destroy(ctxt, instance['uuid'])
        instance_meta = db.instance_metadata_get(ctxt, instance['uuid'])
        # Make sure instance metadata is deleted as well
        self.assertEqual({}, instance_meta)

    def test_instance_update_with_and_get_original(self):
        instance = self.create_instance_with_args(vm_state='building')
        (old_ref, new_ref) = db.instance_update_and_get_original(self.ctxt,
                            instance['uuid'], {'vm_state': 'needscoffee'})
        self.assertEqual('building', old_ref['vm_state'])
        self.assertEqual('needscoffee', new_ref['vm_state'])

    def test_instance_update_unique_name(self):
        context1 = context.RequestContext('user1', 'p1')
        context2 = context.RequestContext('user2', 'p2')

        inst1 = self.create_instance_with_args(context=context1,
                                               project_id='p1',
                                               hostname='fake_name1')
        inst2 = self.create_instance_with_args(context=context1,
                                               project_id='p1',
                                               hostname='fake_name2')
        inst3 = self.create_instance_with_args(context=context2,
                                               project_id='p2',
                                               hostname='fake_name3')
        # osapi_compute_unique_server_name_scope is unset so this should work:
        db.instance_update(context1, inst1['uuid'], {'hostname': 'fake_name2'})
        db.instance_update(context1, inst1['uuid'], {'hostname': 'fake_name1'})

        # With scope 'global' any duplicate should fail.
        self.flags(osapi_compute_unique_server_name_scope='global')
        self.assertRaises(exception.InstanceExists,
                          db.instance_update,
                          context1,
                          inst2['uuid'],
                          {'hostname': 'fake_name1'})
        self.assertRaises(exception.InstanceExists,
                          db.instance_update,
                          context2,
                          inst3['uuid'],
                          {'hostname': 'fake_name1'})
        # But we should definitely be able to update our name if we aren't
        #  really changing it.
        db.instance_update(context1, inst1['uuid'], {'hostname': 'fake_NAME'})

        # With scope 'project' a duplicate in the project should fail:
        self.flags(osapi_compute_unique_server_name_scope='project')
        self.assertRaises(exception.InstanceExists, db.instance_update,
                          context1, inst2['uuid'], {'hostname': 'fake_NAME'})

        # With scope 'project' a duplicate in a different project should work:
        self.flags(osapi_compute_unique_server_name_scope='project')
        db.instance_update(context2, inst3['uuid'], {'hostname': 'fake_NAME'})

    def _test_instance_update_updates_metadata(self, metadata_type):
        instance = self.create_instance_with_args()

        def set_and_check(meta):
            inst = db.instance_update(self.ctxt, instance['uuid'],
                               {metadata_type: dict(meta)})
            _meta = utils.metadata_to_dict(inst[metadata_type])
            self.assertEqual(meta, _meta)

        meta = {'speed': '88', 'units': 'MPH'}
        set_and_check(meta)
        meta['gigawatts'] = '1.21'
        set_and_check(meta)
        del meta['gigawatts']
        set_and_check(meta)

    def test_security_group_in_use(self):
        instance = db.instance_create(self.ctxt, dict(host='foo'))
        values = [
            {'instances': [instance]},
            {'instances': []},
        ]

    def test_instance_update_updates_system_metadata(self):
        # Ensure that system_metadata is updated during instance_update
        self._test_instance_update_updates_metadata('system_metadata')

    def test_instance_update_updates_metadata(self):
        # Ensure that metadata is updated during instance_update
        self._test_instance_update_updates_metadata('metadata')

    def test_instance_floating_address_get_all(self):
        ctxt = context.get_admin_context()

        instance1 = db.instance_create(ctxt, {'host': 'h1', 'hostname': 'n1'})
        instance2 = db.instance_create(ctxt, {'host': 'h2', 'hostname': 'n2'})

        fixed_addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        float_addresses = ['2.1.1.1', '2.1.1.2', '2.1.1.3']
        instance_uuids = [instance1['uuid'], instance1['uuid'],
                          instance2['uuid']]

        for fixed_addr, float_addr, instance_uuid in zip(fixed_addresses,
                                                         float_addresses,
                                                         instance_uuids):
            db.fixed_ip_create(ctxt, {'address': fixed_addr,
                                      'instance_uuid': instance_uuid})
            fixed_id = db.fixed_ip_get_by_address(ctxt, fixed_addr)['id']
            db.floating_ip_create(ctxt,
                                  {'address': float_addr,
                                   'fixed_ip_id': fixed_id})

        real_float_addresses = \
                db.instance_floating_address_get_all(ctxt, instance_uuids[0])
        self.assertEqual(set(float_addresses[:2]), set(real_float_addresses))
        real_float_addresses = \
                db.instance_floating_address_get_all(ctxt, instance_uuids[2])
        self.assertEqual(set([float_addresses[2]]), set(real_float_addresses))

    def test_instance_stringified_ips(self):
        instance = self.create_instance_with_args()
        instance = db.instance_update(
            self.ctxt, instance['uuid'],
            {'access_ip_v4': netaddr.IPAddress('1.2.3.4'),
             'access_ip_v6': netaddr.IPAddress('::1')})
        self.assertTrue(isinstance(instance['access_ip_v4'], basestring))
        self.assertTrue(isinstance(instance['access_ip_v6'], basestring))
        instance = db.instance_get_by_uuid(self.ctxt, instance['uuid'])
        self.assertTrue(isinstance(instance['access_ip_v4'], basestring))
        self.assertTrue(isinstance(instance['access_ip_v6'], basestring))


class InstanceMetadataTestCase(test.TestCase):

    """Tests for db.api.instance_metadata_* methods."""

    def setUp(self):
        super(InstanceMetadataTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def test_instance_metadata_get(self):
        instance = db.instance_create(self.ctxt, {'metadata':
                                                    {'key': 'value'}})
        self.assertEqual({'key': 'value'}, db.instance_metadata_get(
                                            self.ctxt, instance['uuid']))

    def test_instance_metadata_delete(self):
        instance = db.instance_create(self.ctxt,
                                      {'metadata': {'key': 'val',
                                                    'key1': 'val1'}})
        db.instance_metadata_delete(self.ctxt, instance['uuid'], 'key1')
        self.assertEqual({'key': 'val'}, db.instance_metadata_get(
                                            self.ctxt, instance['uuid']))

    def test_instance_metadata_update(self):
        instance = db.instance_create(self.ctxt, {'host': 'h1',
                    'project_id': 'p1', 'metadata': {'key': 'value'}})

        # This should add new key/value pair
        metadata = db.instance_metadata_update(
                    self.ctxt, instance['uuid'],
                    {'new_key': 'new_value'}, False)
        metadata = db.instance_metadata_get(self.ctxt, instance['uuid'])
        self.assertEqual(metadata, {'key': 'value', 'new_key': 'new_value'})

        # This should leave only one key/value pair
        metadata = db.instance_metadata_update(
                    self.ctxt, instance['uuid'],
                    {'new_key': 'new_value'}, True)
        metadata = db.instance_metadata_get(self.ctxt, instance['uuid'])
        self.assertEqual(metadata, {'new_key': 'new_value'})


class ServiceTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _get_base_values(self):
        return {
            'host': 'fake_host',
            'binary': 'fake_binary',
            'topic': 'fake_topic',
            'report_count': 3,
            'disabled': False
        }

    def _create_service(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.service_create(self.ctxt, v)

    def test_service_create(self):
        service = self._create_service({})
        self.assertFalse(service['id'] is None)
        for key, value in self._get_base_values().iteritems():
            self.assertEqual(value, service[key])

    def test_service_destroy(self):
        service1 = self._create_service({})
        service2 = self._create_service({'host': 'fake_host2'})

        db.service_destroy(self.ctxt, service1['id'])
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, self.ctxt, service1['id'])
        self._assertEqualObjects(db.service_get(self.ctxt, service2['id']),
                                 service2, ignored_keys=['compute_node'])

    def test_service_update(self):
        service = self._create_service({})
        new_values = {
            'host': 'fake_host1',
            'binary': 'fake_binary1',
            'topic': 'fake_topic1',
            'report_count': 4,
            'disabled': True
        }
        db.service_update(self.ctxt, service['id'], new_values)
        updated_service = db.service_get(self.ctxt, service['id'])
        for key, value in new_values.iteritems():
            self.assertEqual(value, updated_service[key])

    def test_service_update_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_update, self.ctxt, 100500, {})

    def test_service_get(self):
        service1 = self._create_service({})
        self._create_service({'host': 'some_other_fake_host'})
        real_service1 = db.service_get(self.ctxt, service1['id'])
        self._assertEqualObjects(service1, real_service1,
                                 ignored_keys=['compute_node'])

    def test_service_get_with_compute_node(self):
        service = self._create_service({})
        compute_values = dict(vcpus=2, memory_mb=1024, local_gb=2048,
                              vcpus_used=0, memory_mb_used=0,
                              local_gb_used=0, free_ram_mb=1024,
                              free_disk_gb=2048, hypervisor_type="xen",
                              hypervisor_version=1, cpu_info="",
                              running_vms=0, current_workload=0,
                              service_id=service['id'])
        compute = db.compute_node_create(self.ctxt, compute_values)
        real_service = db.service_get(self.ctxt, service['id'])
        real_compute = real_service['compute_node'][0]
        self.assertEqual(compute['id'], real_compute['id'])

    def test_service_get_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, self.ctxt, 100500)

    def test_service_get_by_host_and_topic(self):
        service1 = self._create_service({'host': 'host1', 'topic': 'topic1'})
        self._create_service({'host': 'host2', 'topic': 'topic2'})

        real_service1 = db.service_get_by_host_and_topic(self.ctxt,
                                                         host='host1',
                                                         topic='topic1')
        self._assertEqualObjects(service1, real_service1)

    def test_service_get_all(self):
        values = [
            {'host': 'host1', 'topic': 'topic1'},
            {'host': 'host2', 'topic': 'topic2'},
            {'disabled': True}
        ]
        services = [self._create_service(vals) for vals in values]
        disabled_services = [services[-1]]
        non_disabled_services = services[:-1]

        compares = [
            (services, db.service_get_all(self.ctxt)),
            (disabled_services, db.service_get_all(self.ctxt, True)),
            (non_disabled_services, db.service_get_all(self.ctxt, False))
        ]
        for comp in compares:
            self._assertEqualListsOfObjects(*comp)

    def test_service_get_all_by_topic(self):
        values = [
            {'host': 'host1', 'topic': 't1'},
            {'host': 'host2', 'topic': 't1'},
            {'disabled': True, 'topic': 't1'},
            {'host': 'host3', 'topic': 't2'}
        ]
        services = [self._create_service(vals) for vals in values]
        expected = services[:2]
        real = db.service_get_all_by_topic(self.ctxt, 't1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_all_by_host(self):
        values = [
            {'host': 'host1', 'topic': 't11', 'binary': 'b11'},
            {'host': 'host1', 'topic': 't12', 'binary': 'b12'},
            {'host': 'host2', 'topic': 't1'},
            {'host': 'host3', 'topic': 't1'}
        ]
        services = [self._create_service(vals) for vals in values]

        expected = services[:2]
        real = db.service_get_all_by_host(self.ctxt, 'host1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_by_compute_host(self):
        values = [
            {'host': 'host1', 'topic': CONF.compute_topic},
            {'host': 'host2', 'topic': 't1'},
            {'host': 'host3', 'topic': CONF.compute_topic}
        ]
        services = [self._create_service(vals) for vals in values]

        real_service = db.service_get_by_compute_host(self.ctxt, 'host1')
        self._assertEqualObjects(services[0], real_service,
                                 ignored_keys=['compute_node'])

        self.assertRaises(exception.ComputeHostNotFound,
                          db.service_get_by_compute_host,
                          self.ctxt, 'non-exists-host')

    def test_service_get_by_compute_host_not_found(self):
        self.assertRaises(exception.ComputeHostNotFound,
                          db.service_get_by_compute_host,
                          self.ctxt, 'non-exists-host')

    def test_service_get_by_args(self):
        values = [
            {'host': 'host1', 'binary': 'a'},
            {'host': 'host2', 'binary': 'b'}
        ]
        services = [self._create_service(vals) for vals in values]

        service1 = db.service_get_by_args(self.ctxt, 'host1', 'a')
        self._assertEqualObjects(services[0], service1)

        service2 = db.service_get_by_args(self.ctxt, 'host2', 'b')
        self._assertEqualObjects(services[1], service2)

    def test_service_get_by_args_not_found_exception(self):
        self.assertRaises(exception.HostBinaryNotFound,
                          db.service_get_by_args,
                          self.ctxt, 'non-exists-host', 'a')

    def test_service_binary_exists_exception(self):
        db.service_create(self.ctxt, self._get_base_values())
        values = self._get_base_values()
        values.update({'topic': 'top1'})
        self.assertRaises(exception.ServiceBinaryExists, db.service_create,
                          self.ctxt, values)

    def test_service_topic_exists_exceptions(self):
        db.service_create(self.ctxt, self._get_base_values())
        values = self._get_base_values()
        values.update({'binary': 'bin1'})
        self.assertRaises(exception.ServiceTopicExists, db.service_create,
                          self.ctxt, values)


class BaseInstanceTypeTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(BaseInstanceTypeTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.user_ctxt = context.RequestContext('user', 'user')

    def _get_base_values(self):
        return {
            'name': 'fake_name',
            'memory_mb': 512,
            'vcpus': 1,
            'root_gb': 10,
            'ephemeral_gb': 10,
            'flavorid': 'fake_flavor',
            'swap': 0,
            'rxtx_factor': 0.5,
            'vcpu_weight': 1,
            'disabled': False,
            'is_public': True
        }

    def _create_inst_type(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.flavor_create(self.ctxt, v)


class InstanceActionTestCase(test.TestCase, ModelsObjectComparatorMixin):
    IGNORED_FIELDS = [
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
        'deleted'
    ]

    def setUp(self):
        super(InstanceActionTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _create_action_values(self, uuid, action='run_instance', ctxt=None):
        if ctxt is None:
            ctxt = self.ctxt
        return {
            'action': action,
            'instance_uuid': uuid,
            'request_id': ctxt.request_id,
            'user_id': ctxt.user_id,
            'project_id': ctxt.project_id,
            'start_time': timeutils.utcnow(),
            'message': 'action-message'
        }

    def _create_event_values(self, uuid, event='schedule',
                             ctxt=None, extra=None):
        if ctxt is None:
            ctxt = self.ctxt
        values = {
            'event': event,
            'instance_uuid': uuid,
            'request_id': ctxt.request_id,
            'start_time': timeutils.utcnow()
        }
        if extra is not None:
            values.update(extra)
        return values

    def _assertActionSaved(self, action, uuid):
        """Retrieve the action to ensure it was successfully added."""
        actions = db.actions_get(self.ctxt, uuid)
        self.assertEqual(1, len(actions))
        self._assertEqualObjects(action, actions[0])

    def _assertActionEventSaved(self, event, action_id):
        # Retrieve the event to ensure it was successfully added
        events = db.action_events_get(self.ctxt, action_id)
        self.assertEqual(1, len(events))
        self._assertEqualObjects(event, events[0],
                                 ['instance_uuid', 'request_id'])

    def test_instance_action_start(self):
        """Create an instance action."""
        uuid = str(stdlib_uuid.uuid4())

        action_values = self._create_action_values(uuid)
        action = db.action_start(self.ctxt, action_values)

        ignored_keys = self.IGNORED_FIELDS + ['finish_time']
        self._assertEqualObjects(action_values, action, ignored_keys)

        self._assertActionSaved(action, uuid)

    def test_instance_action_finish(self):
        """Create an instance action."""
        uuid = str(stdlib_uuid.uuid4())

        action_values = self._create_action_values(uuid)
        db.action_start(self.ctxt, action_values)

        action_values['finish_time'] = timeutils.utcnow()
        action = db.action_finish(self.ctxt, action_values)
        self._assertEqualObjects(action_values, action, self.IGNORED_FIELDS)

        self._assertActionSaved(action, uuid)

    def test_instance_action_finish_without_started_event(self):
        """Create an instance finish action."""
        uuid = str(stdlib_uuid.uuid4())

        action_values = self._create_action_values(uuid)
        action_values['finish_time'] = timeutils.utcnow()
        self.assertRaises(exception.InstanceActionNotFound, db.action_finish,
                          self.ctxt, action_values)

    def test_instance_actions_get_by_instance(self):
        """Ensure we can get actions by UUID."""
        uuid1 = str(stdlib_uuid.uuid4())

        expected = []

        action_values = self._create_action_values(uuid1)
        action = db.action_start(self.ctxt, action_values)
        expected.append(action)

        action_values['action'] = 'resize'
        action = db.action_start(self.ctxt, action_values)
        expected.append(action)

        # Create some extra actions
        uuid2 = str(stdlib_uuid.uuid4())
        ctxt2 = context.get_admin_context()
        action_values = self._create_action_values(uuid2, 'reboot', ctxt2)
        db.action_start(ctxt2, action_values)
        db.action_start(ctxt2, action_values)

        # Retrieve the action to ensure it was successfully added
        actions = db.actions_get(self.ctxt, uuid1)
        self._assertEqualListsOfObjects(expected, actions)

    def test_instance_action_get_by_instance_and_action(self):
        """Ensure we can get an action by instance UUID and action id."""
        ctxt2 = context.get_admin_context()
        uuid1 = str(stdlib_uuid.uuid4())
        uuid2 = str(stdlib_uuid.uuid4())

        action_values = self._create_action_values(uuid1)
        db.action_start(self.ctxt, action_values)
        action_values['action'] = 'resize'
        db.action_start(self.ctxt, action_values)

        action_values = self._create_action_values(uuid2, 'reboot', ctxt2)
        db.action_start(ctxt2, action_values)
        db.action_start(ctxt2, action_values)

        actions = db.actions_get(self.ctxt, uuid1)
        request_id = actions[0]['request_id']
        action = db.action_get_by_request_id(self.ctxt, uuid1, request_id)
        self.assertEqual('run_instance', action['action'])
        self.assertEqual(self.ctxt.request_id, action['request_id'])

    def test_instance_action_event_start(self):
        """Create an instance action event."""
        uuid = str(stdlib_uuid.uuid4())

        action_values = self._create_action_values(uuid)
        action = db.action_start(self.ctxt, action_values)

        event_values = self._create_event_values(uuid)
        event = db.action_event_start(self.ctxt, event_values)
        # self.fail(self._dict_from_object(event, None))
        event_values['action_id'] = action['id']
        ignored = self.IGNORED_FIELDS + ['finish_time', 'traceback', 'result']
        self._assertEqualObjects(event_values, event, ignored)

        self._assertActionEventSaved(event, action['id'])

    def test_instance_action_event_start_without_action(self):
        """Create an instance action event."""
        uuid = str(stdlib_uuid.uuid4())

        event_values = self._create_event_values(uuid)
        self.assertRaises(exception.InstanceActionNotFound,
                          db.action_event_start, self.ctxt, event_values)

    def test_instance_action_event_finish_without_started_event(self):
        """Finish an instance action event."""
        uuid = str(stdlib_uuid.uuid4())

        db.action_start(self.ctxt, self._create_action_values(uuid))

        event_values = {
            'finish_time': timeutils.utcnow() + datetime.timedelta(seconds=5),
            'result': 'Success'
        }
        event_values = self._create_event_values(uuid, extra=event_values)
        self.assertRaises(exception.InstanceActionEventNotFound,
                          db.action_event_finish, self.ctxt, event_values)

    def test_instance_action_event_finish_without_action(self):
        """Finish an instance action event."""
        uuid = str(stdlib_uuid.uuid4())

        event_values = {
            'finish_time': timeutils.utcnow() + datetime.timedelta(seconds=5),
            'result': 'Success'
        }
        event_values = self._create_event_values(uuid, extra=event_values)
        self.assertRaises(exception.InstanceActionNotFound,
                          db.action_event_finish, self.ctxt, event_values)

    def test_instance_action_event_finish_success(self):
        """Finish an instance action event."""
        uuid = str(stdlib_uuid.uuid4())

        action = db.action_start(self.ctxt, self._create_action_values(uuid))

        db.action_event_start(self.ctxt, self._create_event_values(uuid))

        event_values = {
            'finish_time': timeutils.utcnow() + datetime.timedelta(seconds=5),
            'result': 'Success'
        }
        event_values = self._create_event_values(uuid, extra=event_values)
        event = db.action_event_finish(self.ctxt, event_values)

        self._assertActionEventSaved(event, action['id'])
        action = db.action_get_by_request_id(self.ctxt, uuid,
                                             self.ctxt.request_id)
        self.assertNotEqual('Error', action['message'])

    def test_instance_action_event_finish_error(self):
        """Finish an instance action event with an error."""
        uuid = str(stdlib_uuid.uuid4())

        action = db.action_start(self.ctxt, self._create_action_values(uuid))

        db.action_event_start(self.ctxt, self._create_event_values(uuid))

        event_values = {
            'finish_time': timeutils.utcnow() + datetime.timedelta(seconds=5),
            'result': 'Error'
        }
        event_values = self._create_event_values(uuid, extra=event_values)
        event = db.action_event_finish(self.ctxt, event_values)

        self._assertActionEventSaved(event, action['id'])
        action = db.action_get_by_request_id(self.ctxt, uuid,
                                             self.ctxt.request_id)
        self.assertEqual('Error', action['message'])

    def test_instance_action_and_event_start_string_time(self):
        """Create an instance action and event with a string start_time."""
        uuid = str(stdlib_uuid.uuid4())

        action = db.action_start(self.ctxt, self._create_action_values(uuid))

        event_values = {'start_time': timeutils.strtime(timeutils.utcnow())}
        event_values = self._create_event_values(uuid, extra=event_values)
        event = db.action_event_start(self.ctxt, event_values)

        self._assertActionEventSaved(event, action['id'])

    def test_instance_action_event_get_by_id(self):
        """Get a specific instance action event."""
        ctxt2 = context.get_admin_context()
        uuid1 = str(stdlib_uuid.uuid4())
        uuid2 = str(stdlib_uuid.uuid4())

        action = db.action_start(self.ctxt,
                                 self._create_action_values(uuid1))

        db.action_start(ctxt2,
                        self._create_action_values(uuid2, 'reboot', ctxt2))

        event = db.action_event_start(self.ctxt,
                                      self._create_event_values(uuid1))

        event_values = self._create_event_values(uuid2, 'reboot', ctxt2)
        db.action_event_start(ctxt2, event_values)

        # Retrieve the event to ensure it was successfully added
        saved_event = db.action_event_get_by_id(self.ctxt,
                                                action['id'],
                                                event['id'])
        self._assertEqualObjects(event, saved_event,
                                 ['instance_uuid', 'request_id'])


class InstanceFaultTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(InstanceFaultTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _create_fault_values(self, uuid, code=404):
        return {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuid,
            'code': code,
            'host': 'localhost'
        }

    def test_instance_fault_create(self):
        """Ensure we can create an instance fault."""
        uuid = str(stdlib_uuid.uuid4())

        # Ensure no faults registered for this instance
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, [uuid])
        self.assertEqual(0, len(faults[uuid]))

        # Create a fault
        fault_values = self._create_fault_values(uuid)
        fault = db.instance_fault_create(self.ctxt, fault_values)

        ignored_keys = ['deleted', 'created_at', 'updated_at',
                        'deleted_at', 'id']
        self._assertEqualObjects(fault_values, fault, ignored_keys)

        # Retrieve the fault to ensure it was successfully added
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, [uuid])
        self.assertEqual(1, len(faults[uuid]))
        self._assertEqualObjects(fault, faults[uuid][0])

    def test_instance_fault_get_by_instance(self):
        """Ensure we can retrieve faults for instance."""
        uuids = [str(stdlib_uuid.uuid4()), str(stdlib_uuid.uuid4())]
        fault_codes = [404, 500]
        expected = {}

        # Create faults
        for uuid in uuids:
            expected[uuid] = []
            for code in fault_codes:
                fault_values = self._create_fault_values(uuid, code)
                fault = db.instance_fault_create(self.ctxt, fault_values)
                expected[uuid].append(fault)

        # Ensure faults are saved
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, uuids)
        self.assertEqual(len(expected), len(faults))
        for uuid in uuids:
            self._assertEqualListsOfObjects(expected[uuid], faults[uuid])

    def test_instance_faults_get_by_instance_uuids_no_faults(self):
        uuid = str(stdlib_uuid.uuid4())
        # None should be returned when no faults exist.
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, [uuid])
        expected = {uuid: []}
        self.assertEqual(expected, faults)

    def test_instance_faults_get_by_instance_uuids_no_uuids(self):
        self.mox.StubOutWithMock(query.Query, 'filter')
        self.mox.ReplayAll()
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, [])
        self.assertEqual({}, faults)


class InstanceTypeTestCase(BaseInstanceTypeTestCase):

    def test_flavor_create(self):
        inst_type = self._create_inst_type({})
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at', 'extra_specs']

        self.assertFalse(inst_type['id'] is None)
        self._assertEqualObjects(inst_type, self._get_base_values(),
                                 ignored_keys)

    def test_instance_type_destroy(self):
        specs1 = {'a': '1', 'b': '2'}
        inst_type1 = self._create_inst_type({'name': 'name1', 'flavorid': 'a1',
                                             'extra_specs': specs1})
        specs2 = {'c': '4', 'd': '3'}
        inst_type2 = self._create_inst_type({'name': 'name2', 'flavorid': 'a2',
                                             'extra_specs': specs2})

        db.flavor_destroy(self.ctxt, 'name1')

        self.assertRaises(exception.InstanceTypeNotFound,
                          db.flavor_get, self.ctxt, inst_type1['id'])
        real_specs1 = db.flavor_extra_specs_get(self.ctxt,
                                                       inst_type1['flavorid'])
        self._assertEqualObjects(real_specs1, {})

        r_inst_type2 = db.flavor_get(self.ctxt, inst_type2['id'])
        self._assertEqualObjects(inst_type2, r_inst_type2, 'extra_specs')

    def test_instance_type_destroy_not_found(self):
        self.assertRaises(exception.InstanceTypeNotFound,
                          db.flavor_destroy, self.ctxt, 'nonexists')

    def test_flavor_create_duplicate_name(self):
        self._create_inst_type({})
        self.assertRaises(exception.InstanceTypeExists,
                          self._create_inst_type,
                          {'flavorid': 'some_random_flavor'})

    def test_flavor_create_duplicate_flavorid(self):
        self._create_inst_type({})
        self.assertRaises(exception.InstanceTypeIdExists,
                          self._create_inst_type,
                          {'name': 'some_random_name'})

    def test_flavor_create_with_extra_specs(self):
        extra_specs = dict(a='abc', b='def', c='ghi')
        inst_type = self._create_inst_type({'extra_specs': extra_specs})
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at', 'extra_specs']

        self._assertEqualObjects(inst_type, self._get_base_values(),
                                 ignored_keys)
        self._assertEqualObjects(extra_specs, inst_type['extra_specs'])

    def test_instance_type_get_all(self):
        # NOTE(boris-42): Remove base instance types
        for it in db.flavor_get_all(self.ctxt):
            db.flavor_destroy(self.ctxt, it['name'])

        instance_types = [
            {'root_gb': 600, 'memory_mb': 100, 'disabled': True,
             'is_public': True, 'name': 'a1', 'flavorid': 'f1'},
            {'root_gb': 500, 'memory_mb': 200, 'disabled': True,
             'is_public': True, 'name': 'a2', 'flavorid': 'f2'},
            {'root_gb': 400, 'memory_mb': 300, 'disabled': False,
             'is_public': True, 'name': 'a3', 'flavorid': 'f3'},
            {'root_gb': 300, 'memory_mb': 400, 'disabled': False,
             'is_public': False, 'name': 'a4', 'flavorid': 'f4'},
            {'root_gb': 200, 'memory_mb': 500, 'disabled': True,
             'is_public': False, 'name': 'a5', 'flavorid': 'f5'},
            {'root_gb': 100, 'memory_mb': 600, 'disabled': True,
             'is_public': False, 'name': 'a6', 'flavorid': 'f6'}
        ]
        instance_types = [self._create_inst_type(it) for it in instance_types]

        lambda_filters = {
            'min_memory_mb': lambda it, v: it['memory_mb'] >= v,
            'min_root_gb': lambda it, v: it['root_gb'] >= v,
            'disabled': lambda it, v: it['disabled'] == v,
            'is_public': lambda it, v: (v is None or it['is_public'] == v)
        }

        mem_filts = [{'min_memory_mb': x} for x in [100, 350, 550, 650]]
        root_filts = [{'min_root_gb': x} for x in [100, 350, 550, 650]]
        disabled_filts = [{'disabled': x} for x in [True, False]]
        is_public_filts = [{'is_public': x} for x in [True, False, None]]

        def assert_multi_filter_instance_type_get(filters=None):
            if filters is None:
                filters = {}

            expected_it = instance_types
            for name, value in filters.iteritems():
                filt = lambda it: lambda_filters[name](it, value)
                expected_it = filter(filt, expected_it)

            real_it = db.flavor_get_all(self.ctxt, filters=filters)
            self._assertEqualListsOfObjects(expected_it, real_it)

        #no filter
        assert_multi_filter_instance_type_get()

        #test only with one filter
        for filt in mem_filts:
            assert_multi_filter_instance_type_get(filt)
        for filt in root_filts:
            assert_multi_filter_instance_type_get(filt)
        for filt in disabled_filts:
            assert_multi_filter_instance_type_get(filt)
        for filt in is_public_filts:
            assert_multi_filter_instance_type_get(filt)

        #test all filters together
        for mem in mem_filts:
            for root in root_filts:
                for disabled in disabled_filts:
                    for is_public in is_public_filts:
                        filts = [f.items() for f in
                                    [mem, root, disabled, is_public]]
                        filts = dict(reduce(lambda x, y: x + y, filts, []))
                        assert_multi_filter_instance_type_get(filts)

    def test_instance_type_get(self):
        inst_types = [{'name': 'abc', 'flavorid': '123'},
                    {'name': 'def', 'flavorid': '456'},
                    {'name': 'ghi', 'flavorid': '789'}]
        inst_types = [self._create_inst_type(t) for t in inst_types]

        for inst_type in inst_types:
            inst_type_by_id = db.flavor_get(self.ctxt, inst_type['id'])
            self._assertEqualObjects(inst_type, inst_type_by_id)

    def test_instance_type_get_non_public(self):
        inst_type = self._create_inst_type({'name': 'abc', 'flavorid': '123',
                                            'is_public': False})

        # Admin can see it
        inst_type_by_id = db.flavor_get(self.ctxt, inst_type['id'])
        self._assertEqualObjects(inst_type, inst_type_by_id)

        # Regular user can not
        self.assertRaises(exception.InstanceTypeNotFound, db.flavor_get,
                self.user_ctxt, inst_type['id'])

        # Regular user can see it after being granted access
        db.flavor_access_add(self.ctxt, inst_type['flavorid'],
                self.user_ctxt.project_id)
        inst_type_by_id = db.flavor_get(self.user_ctxt, inst_type['id'])
        self._assertEqualObjects(inst_type, inst_type_by_id)

    def test_instance_type_get_by_name(self):
        inst_types = [{'name': 'abc', 'flavorid': '123'},
                    {'name': 'def', 'flavorid': '456'},
                    {'name': 'ghi', 'flavorid': '789'}]
        inst_types = [self._create_inst_type(t) for t in inst_types]

        for inst_type in inst_types:
            inst_type_by_name = db.flavor_get_by_name(self.ctxt,
                                                             inst_type['name'])
            self._assertEqualObjects(inst_type, inst_type_by_name)

    def test_instance_type_get_by_name_not_found(self):
        self._create_inst_type({})
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          db.flavor_get_by_name, self.ctxt, 'nonexists')

    def test_instance_type_get_by_name_non_public(self):
        inst_type = self._create_inst_type({'name': 'abc', 'flavorid': '123',
                                            'is_public': False})

        # Admin can see it
        inst_type_by_name = db.flavor_get_by_name(self.ctxt,
                                                         inst_type['name'])
        self._assertEqualObjects(inst_type, inst_type_by_name)

        # Regular user can not
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                db.flavor_get_by_name, self.user_ctxt,
                inst_type['name'])

        # Regular user can see it after being granted access
        db.flavor_access_add(self.ctxt, inst_type['flavorid'],
                self.user_ctxt.project_id)
        inst_type_by_name = db.flavor_get_by_name(self.user_ctxt,
                                                         inst_type['name'])
        self._assertEqualObjects(inst_type, inst_type_by_name)

    def test_instance_type_get_by_flavor_id(self):
        inst_types = [{'name': 'abc', 'flavorid': '123'},
                      {'name': 'def', 'flavorid': '456'},
                      {'name': 'ghi', 'flavorid': '789'}]
        inst_types = [self._create_inst_type(t) for t in inst_types]

        for inst_type in inst_types:
            params = (self.ctxt, inst_type['flavorid'])
            inst_type_by_flavorid = db.flavor_get_by_flavor_id(*params)
            self._assertEqualObjects(inst_type, inst_type_by_flavorid)

    def test_instance_type_get_by_flavor_not_found(self):
        self._create_inst_type({})
        self.assertRaises(exception.FlavorNotFound,
                          db.flavor_get_by_flavor_id,
                          self.ctxt, 'nonexists')

    def test_instance_type_get_by_flavor_id_non_public(self):
        inst_type = self._create_inst_type({'name': 'abc', 'flavorid': '123',
                                            'is_public': False})

        # Admin can see it
        inst_type_by_fid = db.flavor_get_by_flavor_id(self.ctxt,
                inst_type['flavorid'])
        self._assertEqualObjects(inst_type, inst_type_by_fid)

        # Regular user can not
        self.assertRaises(exception.FlavorNotFound,
                db.flavor_get_by_flavor_id, self.user_ctxt,
                inst_type['flavorid'])

        # Regular user can see it after being granted access
        db.flavor_access_add(self.ctxt, inst_type['flavorid'],
                self.user_ctxt.project_id)
        inst_type_by_fid = db.flavor_get_by_flavor_id(self.user_ctxt,
                inst_type['flavorid'])
        self._assertEqualObjects(inst_type, inst_type_by_fid)

    def test_instance_type_get_by_flavor_id_deleted(self):
        inst_type = self._create_inst_type({'name': 'abc', 'flavorid': '123'})

        db.flavor_destroy(self.ctxt, 'abc')

        inst_type_by_fid = db.flavor_get_by_flavor_id(self.ctxt,
                inst_type['flavorid'], read_deleted='yes')
        self.assertEqual(inst_type['id'], inst_type_by_fid['id'])


class InstanceTypeExtraSpecsTestCase(BaseInstanceTypeTestCase):

    def setUp(self):
        super(InstanceTypeExtraSpecsTestCase, self).setUp()
        values = ({'name': 'n1', 'flavorid': 'f1',
                   'extra_specs': dict(a='a', b='b', c='c')},
                  {'name': 'n2', 'flavorid': 'f2',
                   'extra_specs': dict(d='d', e='e', f='f')})

        # NOTE(boris-42): We have already tested flavor_create method
        #                 with extra_specs in InstanceTypeTestCase.
        self.inst_types = [self._create_inst_type(v) for v in values]

    def test_instance_type_extra_specs_get(self):
        for it in self.inst_types:
            real_specs = db.flavor_extra_specs_get(self.ctxt,
                                                          it['flavorid'])
            self._assertEqualObjects(it['extra_specs'], real_specs)

    def test_instance_type_extra_specs_get_item(self):
        expected = dict(f1=dict(a='a', b='b', c='c'),
                        f2=dict(d='d', e='e', f='f'))

        for flavor, specs in expected.iteritems():
            for key, val in specs.iteritems():
                spec = db.flavor_extra_specs_get_item(self.ctxt, flavor,
                                                             key)
                self.assertEqual(spec[key], val)

    def test_instance_type_extra_specs_delete(self):
        for it in self.inst_types:
            specs = it['extra_specs']
            key = specs.keys()[0]
            del specs[key]
            db.flavor_extra_specs_delete(self.ctxt, it['flavorid'], key)
            real_specs = db.flavor_extra_specs_get(self.ctxt,
                                                          it['flavorid'])
            self._assertEqualObjects(it['extra_specs'], real_specs)

    def test_instance_type_extra_specs_update_or_create(self):
        for it in self.inst_types:
            current_specs = it['extra_specs']
            current_specs.update(dict(b='b1', c='c1', d='d1', e='e1'))
            params = (self.ctxt, it['flavorid'], current_specs)
            db.flavor_extra_specs_update_or_create(*params)
            real_specs = db.flavor_extra_specs_get(self.ctxt,
                                                          it['flavorid'])
            self._assertEqualObjects(current_specs, real_specs)

    def test_instance_type_extra_specs_update_or_create_flavor_not_found(self):
        self.assertRaises(exception.FlavorNotFound,
                          db.flavor_extra_specs_update_or_create,
                          self.ctxt, 'nonexists', {})

    def test_instance_type_extra_specs_update_or_create_retry(self):

        def counted():
            def get_id(context, flavorid, session):
                get_id.counter += 1
                raise db_exc.DBDuplicateEntry
            get_id.counter = 0
            return get_id

        get_id = counted()
        self.stubs.Set(sqlalchemy_api,
                       '_instance_type_get_id_from_flavor', get_id)
        self.assertRaises(db_exc.DBDuplicateEntry, sqlalchemy_api.
                          flavor_extra_specs_update_or_create,
                          self.ctxt, 1, {}, 5)
        self.assertEqual(get_id.counter, 5)


class InstanceTypeAccessTestCase(BaseInstanceTypeTestCase):

    def _create_inst_type_access(self, instance_type_id, project_id):
        return db.flavor_access_add(self.ctxt, instance_type_id,
                                           project_id)

    def test_instance_type_access_get_by_flavor_id(self):
        inst_types = ({'name': 'n1', 'flavorid': 'f1'},
                      {'name': 'n2', 'flavorid': 'f2'})
        it1, it2 = tuple((self._create_inst_type(v) for v in inst_types))

        access_it1 = [self._create_inst_type_access(it1['flavorid'], 'pr1'),
                      self._create_inst_type_access(it1['flavorid'], 'pr2')]

        access_it2 = [self._create_inst_type_access(it2['flavorid'], 'pr1')]

        for it, access_it in zip((it1, it2), (access_it1, access_it2)):
            params = (self.ctxt, it['flavorid'])
            real_access_it = db.flavor_access_get_by_flavor_id(*params)
            self._assertEqualListsOfObjects(access_it, real_access_it)

    def test_instance_type_access_get_by_flavor_id_flavor_not_found(self):
        self.assertRaises(exception.FlavorNotFound,
                          db.flavor_get_by_flavor_id,
                          self.ctxt, 'nonexists')

    def test_instance_type_access_add(self):
        inst_type = self._create_inst_type({'flavorid': 'f1'})
        project_id = 'p1'

        access = self._create_inst_type_access(inst_type['flavorid'],
                                               project_id)
        # NOTE(boris-42): Check that instance_type_access_add doesn't fail and
        #                 returns correct value. This is enough because other
        #                 logic is checked by other methods.
        self.assertFalse(access['id'] is None)
        self.assertEqual(access['instance_type_id'], inst_type['id'])
        self.assertEqual(access['project_id'], project_id)

    def test_instance_type_access_add_to_non_existing_flavor(self):
        self.assertRaises(exception.FlavorNotFound,
                          self._create_inst_type_access,
                          'nonexists', 'does_not_matter')

    def test_instance_type_access_add_duplicate_project_id_flavor(self):
        inst_type = self._create_inst_type({'flavorid': 'f1'})
        params = (inst_type['flavorid'], 'p1')

        self._create_inst_type_access(*params)
        self.assertRaises(exception.FlavorAccessExists,
                          self._create_inst_type_access, *params)

    def test_instance_type_access_remove(self):
        inst_types = ({'name': 'n1', 'flavorid': 'f1'},
                      {'name': 'n2', 'flavorid': 'f2'})
        it1, it2 = tuple((self._create_inst_type(v) for v in inst_types))

        access_it1 = [self._create_inst_type_access(it1['flavorid'], 'pr1'),
                      self._create_inst_type_access(it1['flavorid'], 'pr2')]

        access_it2 = [self._create_inst_type_access(it2['flavorid'], 'pr1')]

        db.flavor_access_remove(self.ctxt, it1['flavorid'],
                                       access_it1[1]['project_id'])

        for it, access_it in zip((it1, it2), (access_it1[:1], access_it2)):
            params = (self.ctxt, it['flavorid'])
            real_access_it = db.flavor_access_get_by_flavor_id(*params)
            self._assertEqualListsOfObjects(access_it, real_access_it)

    def test_instance_type_access_remove_flavor_not_found(self):
        self.assertRaises(exception.FlavorNotFound,
                          db.flavor_access_remove,
                          self.ctxt, 'nonexists', 'does_not_matter')

    def test_instance_type_access_remove_access_not_found(self):
        inst_type = self._create_inst_type({'flavorid': 'f1'})
        params = (inst_type['flavorid'], 'p1')
        self._create_inst_type_access(*params)
        self.assertRaises(exception.FlavorAccessNotFound,
                          db.flavor_access_remove,
                          self.ctxt, inst_type['flavorid'], 'p2')

    def test_instance_type_access_removed_after_instance_type_destroy(self):
        inst_type1 = self._create_inst_type({'flavorid': 'f1', 'name': 'n1'})
        inst_type2 = self._create_inst_type({'flavorid': 'f2', 'name': 'n2'})
        values = [
            (inst_type1['flavorid'], 'p1'),
            (inst_type1['flavorid'], 'p2'),
            (inst_type2['flavorid'], 'p3')
        ]
        for v in values:
            self._create_inst_type_access(*v)

        db.flavor_destroy(self.ctxt, inst_type1['name'])

        p = (self.ctxt, inst_type1['flavorid'])
        self.assertEqual(0, len(db.flavor_access_get_by_flavor_id(*p)))
        p = (self.ctxt, inst_type2['flavorid'])
        self.assertEqual(1, len(db.flavor_access_get_by_flavor_id(*p)))
        db.flavor_destroy(self.ctxt, inst_type2['name'])
        self.assertEqual(0, len(db.flavor_access_get_by_flavor_id(*p)))


class FixedIPTestCase(BaseInstanceTypeTestCase):
    def _timeout_test(self, ctxt, timeout, multi_host):
        instance = db.instance_create(ctxt, dict(host='foo'))
        net = db.network_create_safe(ctxt, dict(multi_host=multi_host,
                                                host='bar'))
        old = timeout - datetime.timedelta(seconds=5)
        new = timeout + datetime.timedelta(seconds=5)
        # should deallocate
        db.fixed_ip_create(ctxt, dict(allocated=False,
                                      instance_uuid=instance['uuid'],
                                      network_id=net['id'],
                                      updated_at=old))
        # still allocated
        db.fixed_ip_create(ctxt, dict(allocated=True,
                                      instance_uuid=instance['uuid'],
                                      network_id=net['id'],
                                      updated_at=old))
        # wrong network
        db.fixed_ip_create(ctxt, dict(allocated=False,
                                      instance_uuid=instance['uuid'],
                                      network_id=None,
                                      updated_at=old))
        # too new
        db.fixed_ip_create(ctxt, dict(allocated=False,
                                      instance_uuid=instance['uuid'],
                                      network_id=None,
                                      updated_at=new))

    def mock_db_query_first_to_raise_data_error_exception(self):
        self.mox.StubOutWithMock(query.Query, 'first')
        query.Query.first().AndRaise(exc.DataError(mox.IgnoreArg(),
                                                   mox.IgnoreArg(),
                                                   mox.IgnoreArg()))
        self.mox.ReplayAll()

    def test_fixed_ip_disassociate_all_by_timeout_single_host(self):
        now = timeutils.utcnow()
        self._timeout_test(self.ctxt, now, False)
        result = db.fixed_ip_disassociate_all_by_timeout(self.ctxt, 'foo', now)
        self.assertEqual(result, 0)
        result = db.fixed_ip_disassociate_all_by_timeout(self.ctxt, 'bar', now)
        self.assertEqual(result, 1)

    def test_fixed_ip_disassociate_all_by_timeout_multi_host(self):
        now = timeutils.utcnow()
        self._timeout_test(self.ctxt, now, True)
        result = db.fixed_ip_disassociate_all_by_timeout(self.ctxt, 'foo', now)
        self.assertEqual(result, 1)
        result = db.fixed_ip_disassociate_all_by_timeout(self.ctxt, 'bar', now)
        self.assertEqual(result, 0)

    def test_fixed_ip_get_by_floating_address(self):
        fixed_ip = db.fixed_ip_create(self.ctxt, {'address': '192.168.0.2'})
        values = {'address': '8.7.6.5',
                  'fixed_ip_id': fixed_ip['id']}
        floating = db.floating_ip_create(self.ctxt, values)['address']
        fixed_ip_ref = db.fixed_ip_get_by_floating_address(self.ctxt, floating)
        self._assertEqualObjects(fixed_ip, fixed_ip_ref)

    def test_fixed_ip_get_by_host(self):
        host_ips = {
            'host1': ['1.1.1.1', '1.1.1.2', '1.1.1.3'],
            'host2': ['1.1.1.4', '1.1.1.5'],
            'host3': ['1.1.1.6']
        }

        for host, ips in host_ips.iteritems():
            for ip in ips:
                instance_uuid = self._create_instance(host=host)
                db.fixed_ip_create(self.ctxt, {'address': ip})
                db.fixed_ip_associate(self.ctxt, ip, instance_uuid)

        for host, ips in host_ips.iteritems():
            ips_on_host = map(lambda x: x['address'],
                                db.fixed_ip_get_by_host(self.ctxt, host))
            self._assertEqualListsOfPrimitivesAsSets(ips_on_host, ips)

    def test_fixed_ip_get_by_network_host_not_found_exception(self):
        self.assertRaises(
            exception.FixedIpNotFoundForNetworkHost,
            db.fixed_ip_get_by_network_host,
            self.ctxt, 1, 'ignore')

    def test_fixed_ip_get_by_network_host_fixed_ip_found(self):
        db.fixed_ip_create(self.ctxt, dict(network_id=1, host='host'))

        fip = db.fixed_ip_get_by_network_host(self.ctxt, 1, 'host')

        self.assertEquals(1, fip['network_id'])
        self.assertEquals('host', fip['host'])

    def _create_instance(self, **kwargs):
        instance = db.instance_create(self.ctxt, kwargs)
        return instance['uuid']

    def test_fixed_ip_get_by_instance_fixed_ip_found(self):
        instance_uuid = self._create_instance()

        FIXED_IP_ADDRESS = '192.168.1.5'
        db.fixed_ip_create(self.ctxt, dict(
            instance_uuid=instance_uuid, address=FIXED_IP_ADDRESS))

        ips_list = db.fixed_ip_get_by_instance(self.ctxt, instance_uuid)
        self._assertEqualListsOfPrimitivesAsSets([FIXED_IP_ADDRESS],
                                                 [ips_list[0].address])

    def test_fixed_ip_get_by_instance_multiple_fixed_ips_found(self):
        instance_uuid = self._create_instance()

        FIXED_IP_ADDRESS_1 = '192.168.1.5'
        db.fixed_ip_create(self.ctxt, dict(
            instance_uuid=instance_uuid, address=FIXED_IP_ADDRESS_1))
        FIXED_IP_ADDRESS_2 = '192.168.1.6'
        db.fixed_ip_create(self.ctxt, dict(
            instance_uuid=instance_uuid, address=FIXED_IP_ADDRESS_2))

        ips_list = db.fixed_ip_get_by_instance(self.ctxt, instance_uuid)
        self._assertEqualListsOfPrimitivesAsSets(
            [FIXED_IP_ADDRESS_1, FIXED_IP_ADDRESS_2],
            [ips_list[0].address, ips_list[1].address])

    def test_fixed_ip_get_by_instance_inappropriate_ignored(self):
        instance_uuid = self._create_instance()

        FIXED_IP_ADDRESS_1 = '192.168.1.5'
        db.fixed_ip_create(self.ctxt, dict(
            instance_uuid=instance_uuid, address=FIXED_IP_ADDRESS_1))
        FIXED_IP_ADDRESS_2 = '192.168.1.6'
        db.fixed_ip_create(self.ctxt, dict(
            instance_uuid=instance_uuid, address=FIXED_IP_ADDRESS_2))

        another_instance = db.instance_create(self.ctxt, {})
        db.fixed_ip_create(self.ctxt, dict(
            instance_uuid=another_instance['uuid'], address="192.168.1.7"))

        ips_list = db.fixed_ip_get_by_instance(self.ctxt, instance_uuid)
        self._assertEqualListsOfPrimitivesAsSets(
            [FIXED_IP_ADDRESS_1, FIXED_IP_ADDRESS_2],
            [ips_list[0].address, ips_list[1].address])

    def test_fixed_ip_get_by_instance_not_found_exception(self):
        instance_uuid = self._create_instance()

        self.assertRaises(exception.FixedIpNotFoundForInstance,
                          db.fixed_ip_get_by_instance,
                          self.ctxt, instance_uuid)

    def test_fixed_ips_by_virtual_interface_fixed_ip_found(self):
        instance_uuid = self._create_instance()

        vif = db.virtual_interface_create(
            self.ctxt, dict(instance_uuid=instance_uuid))

        FIXED_IP_ADDRESS = '192.168.1.5'
        db.fixed_ip_create(self.ctxt, dict(
            virtual_interface_id=vif.id, address=FIXED_IP_ADDRESS))

        ips_list = db.fixed_ips_by_virtual_interface(self.ctxt, vif.id)
        self._assertEqualListsOfPrimitivesAsSets([FIXED_IP_ADDRESS],
                                                 [ips_list[0].address])

    def test_fixed_ips_by_virtual_interface_multiple_fixed_ips_found(self):
        instance_uuid = self._create_instance()

        vif = db.virtual_interface_create(
            self.ctxt, dict(instance_uuid=instance_uuid))

        FIXED_IP_ADDRESS_1 = '192.168.1.5'
        db.fixed_ip_create(self.ctxt, dict(
            virtual_interface_id=vif.id, address=FIXED_IP_ADDRESS_1))
        FIXED_IP_ADDRESS_2 = '192.168.1.6'
        db.fixed_ip_create(self.ctxt, dict(
            virtual_interface_id=vif.id, address=FIXED_IP_ADDRESS_2))

        ips_list = db.fixed_ips_by_virtual_interface(self.ctxt, vif.id)
        self._assertEqualListsOfPrimitivesAsSets(
            [FIXED_IP_ADDRESS_1, FIXED_IP_ADDRESS_2],
            [ips_list[0].address, ips_list[1].address])

    def test_fixed_ips_by_virtual_interface_inappropriate_ignored(self):
        instance_uuid = self._create_instance()

        vif = db.virtual_interface_create(
            self.ctxt, dict(instance_uuid=instance_uuid))

        FIXED_IP_ADDRESS_1 = '192.168.1.5'
        db.fixed_ip_create(self.ctxt, dict(
            virtual_interface_id=vif.id, address=FIXED_IP_ADDRESS_1))
        FIXED_IP_ADDRESS_2 = '192.168.1.6'
        db.fixed_ip_create(self.ctxt, dict(
            virtual_interface_id=vif.id, address=FIXED_IP_ADDRESS_2))

        another_vif = db.virtual_interface_create(
            self.ctxt, dict(instance_uuid=instance_uuid))
        db.fixed_ip_create(self.ctxt, dict(
            virtual_interface_id=another_vif.id, address="192.168.1.7"))

        ips_list = db.fixed_ips_by_virtual_interface(self.ctxt, vif.id)
        self._assertEqualListsOfPrimitivesAsSets(
            [FIXED_IP_ADDRESS_1, FIXED_IP_ADDRESS_2],
            [ips_list[0].address, ips_list[1].address])

    def test_fixed_ips_by_virtual_interface_no_ip_found(self):
        instance_uuid = self._create_instance()

        vif = db.virtual_interface_create(
            self.ctxt, dict(instance_uuid=instance_uuid))

        ips_list = db.fixed_ips_by_virtual_interface(self.ctxt, vif.id)
        self.assertEquals(0, len(ips_list))

    def create_fixed_ip(self, **params):
        default_params = {'address': '192.168.0.1'}
        default_params.update(params)
        return db.fixed_ip_create(self.ctxt, default_params)['address']

    def test_fixed_ip_associate_fails_if_ip_not_in_network(self):
        instance_uuid = self._create_instance()
        self.assertRaises(exception.FixedIpNotFoundForNetwork,
                          db.fixed_ip_associate,
                          self.ctxt, None, instance_uuid)

    def test_fixed_ip_associate_fails_if_ip_in_use(self):
        instance_uuid = self._create_instance()

        address = self.create_fixed_ip(instance_uuid=instance_uuid)
        self.assertRaises(exception.FixedIpAlreadyInUse,
                          db.fixed_ip_associate,
                          self.ctxt, address, instance_uuid)

    def test_fixed_ip_associate_succeeds(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip(network_id=network['id'])
        db.fixed_ip_associate(self.ctxt, address, instance_uuid,
                              network_id=network['id'])
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], instance_uuid)

    def test_fixed_ip_associate_succeeds_and_sets_network(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip()
        db.fixed_ip_associate(self.ctxt, address, instance_uuid,
                              network_id=network['id'])
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], instance_uuid)
        self.assertEqual(fixed_ip['network_id'], network['id'])

    def test_fixed_ip_associate_pool_invalid_uuid(self):
        instance_uuid = '123'
        self.assertRaises(exception.InvalidUUID, db.fixed_ip_associate_pool,
                          self.ctxt, None, instance_uuid)

    def test_fixed_ip_associate_pool_no_more_fixed_ips(self):
        instance_uuid = self._create_instance()
        self.assertRaises(exception.NoMoreFixedIps, db.fixed_ip_associate_pool,
                          self.ctxt, None, instance_uuid)

    def test_fixed_ip_associate_pool_succeeds(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip(network_id=network['id'])
        db.fixed_ip_associate_pool(self.ctxt, network['id'], instance_uuid)
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], instance_uuid)

    def test_fixed_ip_create_same_address(self):
        address = '192.168.1.5'
        params = {'address': address}
        db.fixed_ip_create(self.ctxt, params)
        self.assertRaises(exception.FixedIpExists, db.fixed_ip_create,
                          self.ctxt, params)

    def test_fixed_ip_create_success(self):
        instance_uuid = self._create_instance()
        network_id = db.network_create_safe(self.ctxt, {})['id']
        param = {
            'reserved': False,
            'deleted': 0,
            'leased': False,
            'host': '127.0.0.1',
            'address': '192.168.1.5',
            'allocated': False,
            'instance_uuid': instance_uuid,
            'network_id': network_id,
            'virtual_interface_id': None
        }

        ignored_keys = ['created_at', 'id', 'deleted_at', 'updated_at']
        fixed_ip_data = db.fixed_ip_create(self.ctxt, param)
        self._assertEqualObjects(param, fixed_ip_data, ignored_keys)

    def test_fixed_ip_bulk_create_same_address(self):
        address_1 = '192.168.1.5'
        address_2 = '192.168.1.6'
        instance_uuid = self._create_instance()
        network_id_1 = db.network_create_safe(self.ctxt, {})['id']
        network_id_2 = db.network_create_safe(self.ctxt, {})['id']
        params = [
            {'reserved': False, 'deleted': 0, 'leased': False,
             'host': '127.0.0.1', 'address': address_2, 'allocated': False,
             'instance_uuid': instance_uuid, 'network_id': network_id_1,
             'virtual_interface_id': None},
            {'reserved': False, 'deleted': 0, 'leased': False,
             'host': '127.0.0.1', 'address': address_1, 'allocated': False,
             'instance_uuid': instance_uuid, 'network_id': network_id_1,
             'virtual_interface_id': None},
            {'reserved': False, 'deleted': 0, 'leased': False,
             'host': 'localhost', 'address': address_2, 'allocated': True,
             'instance_uuid': instance_uuid, 'network_id': network_id_2,
             'virtual_interface_id': None},
        ]

        self.assertRaises(exception.FixedIpExists, db.fixed_ip_bulk_create,
                          self.ctxt, params)
        # In this case the transaction will be rolled back and none of the ips
        # will make it to the database.
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          db.fixed_ip_get_by_address, self.ctxt, address_1)
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          db.fixed_ip_get_by_address, self.ctxt, address_2)

    def test_fixed_ip_bulk_create_success(self):
        address_1 = '192.168.1.5'
        address_2 = '192.168.1.6'

        instance_uuid = self._create_instance()
        network_id_1 = db.network_create_safe(self.ctxt, {})['id']
        network_id_2 = db.network_create_safe(self.ctxt, {})['id']
        params = [
            {'reserved': False, 'deleted': 0, 'leased': False,
             'host': '127.0.0.1', 'address': address_1, 'allocated': False,
             'instance_uuid': instance_uuid, 'network_id': network_id_1,
             'virtual_interface_id': None},
            {'reserved': False, 'deleted': 0, 'leased': False,
             'host': 'localhost', 'address': address_2, 'allocated': True,
             'instance_uuid': instance_uuid, 'network_id': network_id_2,
             'virtual_interface_id': None}
        ]

        db.fixed_ip_bulk_create(self.ctxt, params)
        ignored_keys = ['created_at', 'id', 'deleted_at', 'updated_at']
        fixed_ip_data = db.fixed_ip_get_by_instance(self.ctxt, instance_uuid)

        # we have no `id` in incoming data so we can not use
        # _assertEqualListsOfObjects to compare incoming data and received
        # objects
        fixed_ip_data = sorted(fixed_ip_data, key=lambda i: i['network_id'])
        params = sorted(params, key=lambda i: i['network_id'])
        for param, ip in zip(params, fixed_ip_data):
            self._assertEqualObjects(param, ip, ignored_keys)

    def test_fixed_ip_disassociate(self):
        address = '192.168.1.5'
        instance_uuid = self._create_instance()
        network_id = db.network_create_safe(self.ctxt, {})['id']
        param = {
            'reserved': False,
            'deleted': 0,
            'leased': False,
            'host': '127.0.0.1',
            'address': address,
            'allocated': False,
            'instance_uuid': instance_uuid,
            'network_id': network_id,
            'virtual_interface_id': None
        }
        db.fixed_ip_create(self.ctxt, param)

        db.fixed_ip_disassociate(self.ctxt, address)
        fixed_ip_data = db.fixed_ip_get_by_address(self.ctxt, address)
        ignored_keys = ['created_at', 'id', 'deleted_at',
                        'updated_at', 'instance_uuid']
        self._assertEqualObjects(param, fixed_ip_data, ignored_keys)
        self.assertIsNone(fixed_ip_data['instance_uuid'])

    def test_fixed_ip_get_not_found_exception(self):
        self.assertRaises(exception.FixedIpNotFound,
                          db.fixed_ip_get, self.ctxt, 0)

    def test_fixed_ip_get_success2(self):
        address = '192.168.1.5'
        instance_uuid = self._create_instance()
        network_id = db.network_create_safe(self.ctxt, {})['id']
        param = {
            'reserved': False,
            'deleted': 0,
            'leased': False,
            'host': '127.0.0.1',
            'address': address,
            'allocated': False,
            'instance_uuid': instance_uuid,
            'network_id': network_id,
            'virtual_interface_id': None
        }
        fixed_ip_id = db.fixed_ip_create(self.ctxt, param)

        self.ctxt.is_admin = False
        self.assertRaises(exception.NotAuthorized, db.fixed_ip_get,
                          self.ctxt, fixed_ip_id)

    def test_fixed_ip_get_success(self):
        address = '192.168.1.5'
        instance_uuid = self._create_instance()
        network_id = db.network_create_safe(self.ctxt, {})['id']
        param = {
            'reserved': False,
            'deleted': 0,
            'leased': False,
            'host': '127.0.0.1',
            'address': address,
            'allocated': False,
            'instance_uuid': instance_uuid,
            'network_id': network_id,
            'virtual_interface_id': None
        }
        db.fixed_ip_create(self.ctxt, param)

        fixed_ip_id = db.fixed_ip_get_by_address(self.ctxt, address)['id']
        fixed_ip_data = db.fixed_ip_get(self.ctxt, fixed_ip_id)
        ignored_keys = ['created_at', 'id', 'deleted_at', 'updated_at']
        self._assertEqualObjects(param, fixed_ip_data, ignored_keys)

    def test_fixed_ip_get_by_address_detailed_not_found_exception(self):
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          db.fixed_ip_get_by_address_detailed, self.ctxt,
                          '192.168.1.5')

    def test_fixed_ip_get_by_address_with_data_error_exception(self):
        self.mock_db_query_first_to_raise_data_error_exception()
        self.assertRaises(exception.FixedIpInvalid,
                          db.fixed_ip_get_by_address_detailed, self.ctxt,
                          '192.168.1.6')

    def test_fixed_ip_get_by_address_detailed_sucsess(self):
        address = '192.168.1.5'
        instance_uuid = self._create_instance()
        network_id = db.network_create_safe(self.ctxt, {})['id']
        param = {
            'reserved': False,
            'deleted': 0,
            'leased': False,
            'host': '127.0.0.1',
            'address': address,
            'allocated': False,
            'instance_uuid': instance_uuid,
            'network_id': network_id,
            'virtual_interface_id': None
        }
        db.fixed_ip_create(self.ctxt, param)

        fixed_ip_data = db.fixed_ip_get_by_address_detailed(self.ctxt, address)
        # fixed ip check here
        ignored_keys = ['created_at', 'id', 'deleted_at', 'updated_at']
        self._assertEqualObjects(param, fixed_ip_data[0], ignored_keys)

        # network model check here
        network_data = db.network_get(self.ctxt, network_id)
        self._assertEqualObjects(network_data, fixed_ip_data[1])

        # Instance check here
        instance_data = db.instance_get_by_uuid(self.ctxt, instance_uuid)
        ignored_keys = ['info_cache', 'system_metadata',
                        'security_groups', 'metadata']  # HOW ????
        self._assertEqualObjects(instance_data, fixed_ip_data[2], ignored_keys)

    def test_fixed_ip_update_not_found_for_address(self):
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          db.fixed_ip_update, self.ctxt,
                          '192.168.1.5', {})

    def test_fixed_ip_update(self):
        instance_uuid_1 = self._create_instance()
        instance_uuid_2 = self._create_instance()
        network_id_1 = db.network_create_safe(self.ctxt, {})['id']
        network_id_2 = db.network_create_safe(self.ctxt, {})['id']
        param_1 = {
            'reserved': True, 'deleted': 0, 'leased': True,
            'host': '192.168.133.1', 'address': '10.0.0.2',
            'allocated': True, 'instance_uuid': instance_uuid_1,
            'network_id': network_id_1, 'virtual_interface_id': '123',
        }

        param_2 = {
            'reserved': False, 'deleted': 0, 'leased': False,
            'host': '127.0.0.1', 'address': '10.0.0.3', 'allocated': False,
            'instance_uuid': instance_uuid_2, 'network_id': network_id_2,
            'virtual_interface_id': None
        }

        ignored_keys = ['created_at', 'id', 'deleted_at', 'updated_at']
        fixed_ip_addr = db.fixed_ip_create(self.ctxt, param_1)['address']
        db.fixed_ip_update(self.ctxt, fixed_ip_addr, param_2)
        fixed_ip_after_update = db.fixed_ip_get_by_address(self.ctxt,
                                                           param_2['address'])
        self._assertEqualObjects(param_2, fixed_ip_after_update, ignored_keys)


class FloatingIpTestCase(test.TestCase, ModelsObjectComparatorMixin):

    def setUp(self):
        super(FloatingIpTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _get_base_values(self):
        return {
            'address': '1.1.1.1',
            'fixed_ip_id': None,
            'project_id': 'fake_project',
            'host': 'fake_host',
            'auto_assigned': False,
            'pool': 'fake_pool',
            'interface': 'fake_interface',
        }

    def mock_db_query_first_to_raise_data_error_exception(self):
        self.mox.StubOutWithMock(query.Query, 'first')
        query.Query.first().AndRaise(exc.DataError(mox.IgnoreArg(),
                                                   mox.IgnoreArg(),
                                                   mox.IgnoreArg()))
        self.mox.ReplayAll()

    def _create_floating_ip(self, values):
        if not values:
            values = {}
        vals = self._get_base_values()
        vals.update(values)
        return db.floating_ip_create(self.ctxt, vals)

    def test_floating_ip_get(self):
        values = [{'address': '0.0.0.0'}, {'address': '1.1.1.1'}]
        floating_ips = [self._create_floating_ip(val) for val in values]

        for floating_ip in floating_ips:
            real_floating_ip = db.floating_ip_get(self.ctxt, floating_ip['id'])
            self._assertEqualObjects(floating_ip, real_floating_ip,
                                     ignored_keys=['fixed_ip'])

    def test_floating_ip_get_not_found(self):
        self.assertRaises(exception.FloatingIpNotFound,
                          db.floating_ip_get, self.ctxt, 100500)

    def test_floating_ip_get_with_long_id_not_found(self):
        self.mock_db_query_first_to_raise_data_error_exception()
        self.assertRaises(exception.InvalidID,
                          db.floating_ip_get, self.ctxt, 123456789101112)

    def test_floating_ip_get_pools(self):
        values = [
            {'address': '0.0.0.0', 'pool': 'abc'},
            {'address': '1.1.1.1', 'pool': 'abc'},
            {'address': '2.2.2.2', 'pool': 'def'},
            {'address': '3.3.3.3', 'pool': 'ghi'},
        ]
        for val in values:
            self._create_floating_ip(val)
        expected_pools = [{'name': x}
                          for x in set(map(lambda x: x['pool'], values))]
        real_pools = db.floating_ip_get_pools(self.ctxt)
        self._assertEqualListsOfPrimitivesAsSets(real_pools, expected_pools)

    def test_floating_ip_allocate_address(self):
        pools = {
            'pool1': ['0.0.0.0', '1.1.1.1'],
            'pool2': ['2.2.2.2'],
            'pool3': ['3.3.3.3', '4.4.4.4', '5.5.5.5']
        }
        for pool, addresses in pools.iteritems():
            for address in addresses:
                vals = {'pool': pool, 'address': address, 'project_id': None}
                self._create_floating_ip(vals)

        project_id = self._get_base_values()['project_id']
        for pool, addresses in pools.iteritems():
            alloc_addrs = []
            for i in addresses:
                float_addr = db.floating_ip_allocate_address(self.ctxt,
                                                             project_id, pool)
                alloc_addrs.append(float_addr)
            self._assertEqualListsOfPrimitivesAsSets(alloc_addrs, addresses)

    def test_floating_ip_allocate_address_no_more_floating_ips(self):
        self.assertRaises(exception.NoMoreFloatingIps,
                          db.floating_ip_allocate_address,
                          self.ctxt, 'any_project_id', 'no_such_pool')

    def test_floating_ip_allocate_not_authorized(self):
        ctxt = context.RequestContext(user_id='a', project_id='abc',
                                      is_admin=False)
        self.assertRaises(exception.NotAuthorized,
                          db.floating_ip_allocate_address,
                          ctxt, 'other_project_id', 'any_pool')

    def _get_existing_ips(self):
        return [ip['address'] for ip in db.floating_ip_get_all(self.ctxt)]

    def test_floating_ip_bulk_create(self):
        expected_ips = ['1.1.1.1', '1.1.1.2', '1.1.1.3', '1.1.1.4']
        db.floating_ip_bulk_create(self.ctxt,
                                   map(lambda x: {'address': x}, expected_ips))
        self._assertEqualListsOfPrimitivesAsSets(self._get_existing_ips(),
                                                 expected_ips)

    def test_floating_ip_bulk_create_duplicate(self):
        ips = ['1.1.1.1', '1.1.1.2', '1.1.1.3', '1.1.1.4']
        prepare_ips = lambda x: {'address': x}

        db.floating_ip_bulk_create(self.ctxt, map(prepare_ips, ips))
        self.assertRaises(exception.FloatingIpExists,
                          db.floating_ip_bulk_create,
                          self.ctxt, map(prepare_ips, ['1.1.1.5', '1.1.1.4']))
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          db.floating_ip_get_by_address,
                          self.ctxt, '1.1.1.5')

    def test_floating_ip_bulk_destroy(self):
        ips_for_delete = []
        ips_for_non_delete = []

        def create_ips(i):
            return [{'address': '1.1.%s.%s' % (i, k)} for k in range(1, 256)]

        # NOTE(boris-42): Create more then 256 ip to check that
        #                 _ip_range_splitter works properly.
        for i in range(1, 3):
            ips_for_delete.extend(create_ips(i))
        ips_for_non_delete.extend(create_ips(3))

        db.floating_ip_bulk_create(self.ctxt,
                                   ips_for_delete + ips_for_non_delete)
        db.floating_ip_bulk_destroy(self.ctxt, ips_for_delete)

        expected_addresses = map(lambda x: x['address'], ips_for_non_delete)
        self._assertEqualListsOfPrimitivesAsSets(self._get_existing_ips(),
                                                 expected_addresses)

    def test_floating_ip_create(self):
        floating_ip = self._create_floating_ip({})
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']

        self.assertFalse(floating_ip['id'] is None)
        self._assertEqualObjects(floating_ip, self._get_base_values(),
                                 ignored_keys)

    def test_floating_ip_create_duplicate(self):
        self._create_floating_ip({})
        self.assertRaises(exception.FloatingIpExists,
                          self._create_floating_ip, {})

    def _create_fixed_ip(self, params):
        default_params = {'address': '192.168.0.1'}
        default_params.update(params)
        return db.fixed_ip_create(self.ctxt, default_params)['address']

    def test_floating_ip_fixed_ip_associate(self):
        float_addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        fixed_addresses = ['2.2.2.1', '2.2.2.2', '2.2.2.3']

        float_ips = [self._create_floating_ip({'address': address})
                        for address in float_addresses]
        fixed_addrs = [self._create_fixed_ip({'address': address})
                        for address in fixed_addresses]

        for float_ip, fixed_addr in zip(float_ips, fixed_addrs):
            fixed_ip = db.floating_ip_fixed_ip_associate(self.ctxt,
                                                         float_ip.address,
                                                         fixed_addr, 'host')
            self.assertEqual(fixed_ip.address, fixed_addr)

            updated_float_ip = db.floating_ip_get(self.ctxt, float_ip.id)
            self.assertEqual(fixed_ip.id, updated_float_ip.fixed_ip_id)
            self.assertEqual('host', updated_float_ip.host)

        # Test that already allocated float_ip returns None
        result = db.floating_ip_fixed_ip_associate(self.ctxt,
                                                   float_addresses[0],
                                                   fixed_addresses[0], 'host')
        self.assertTrue(result is None)

    def test_floating_ip_fixed_ip_associate_float_ip_not_found(self):
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          db.floating_ip_fixed_ip_associate,
                          self.ctxt, '10.10.10.10', 'some', 'some')

    def test_floating_ip_deallocate(self):
        values = {'address': '1.1.1.1', 'project_id': 'fake', 'host': 'fake'}
        float_ip = self._create_floating_ip(values)
        db.floating_ip_deallocate(self.ctxt, float_ip.address)

        updated_float_ip = db.floating_ip_get(self.ctxt, float_ip.id)
        self.assertTrue(updated_float_ip.project_id is None)
        self.assertTrue(updated_float_ip.host is None)
        self.assertFalse(updated_float_ip.auto_assigned)

    def test_floating_ip_destroy(self):
        addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        float_ips = [self._create_floating_ip({'address': addr})
                        for addr in addresses]

        expected_len = len(addresses)
        for float_ip in float_ips:
            db.floating_ip_destroy(self.ctxt, float_ip.address)
            self.assertRaises(exception.FloatingIpNotFound,
                              db.floating_ip_get, self.ctxt, float_ip.id)
            expected_len -= 1
            if expected_len > 0:
                self.assertEqual(expected_len,
                                 len(db.floating_ip_get_all(self.ctxt)))
            else:
                self.assertRaises(exception.NoFloatingIpsDefined,
                                  db.floating_ip_get_all, self.ctxt)

    def test_floating_ip_disassociate(self):
        float_addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        fixed_addresses = ['2.2.2.1', '2.2.2.2', '2.2.2.3']

        float_ips = [self._create_floating_ip({'address': address})
                        for address in float_addresses]
        fixed_addrs = [self._create_fixed_ip({'address': address})
                        for address in fixed_addresses]

        for float_ip, fixed_addr in zip(float_ips, fixed_addrs):
            db.floating_ip_fixed_ip_associate(self.ctxt,
                                              float_ip.address,
                                              fixed_addr, 'host')

        for float_ip, fixed_addr in zip(float_ips, fixed_addrs):
            fixed = db.floating_ip_disassociate(self.ctxt, float_ip.address)
            self.assertEqual(fixed.address, fixed_addr)
            updated_float_ip = db.floating_ip_get(self.ctxt, float_ip.id)
            self.assertTrue(updated_float_ip.fixed_ip_id is None)
            self.assertTrue(updated_float_ip.host is None)

    def test_floating_ip_disassociate_not_found(self):
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          db.floating_ip_disassociate, self.ctxt,
                          '11.11.11.11')

    def test_floating_ip_set_auto_assigned(self):
        addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        float_ips = [self._create_floating_ip({'address': addr,
                                               'auto_assigned': False})
                        for addr in addresses]

        for i in range(2):
            db.floating_ip_set_auto_assigned(self.ctxt, float_ips[i].address)
        for i in range(2):
            float_ip = db.floating_ip_get(self.ctxt, float_ips[i].id)
            self.assertTrue(float_ip.auto_assigned)

        float_ip = db.floating_ip_get(self.ctxt, float_ips[2].id)
        self.assertFalse(float_ip.auto_assigned)

    def test_floating_ip_get_all(self):
        addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        float_ips = [self._create_floating_ip({'address': addr})
                        for addr in addresses]
        self._assertEqualListsOfObjects(float_ips,
                                        db.floating_ip_get_all(self.ctxt))

    def test_floating_ip_get_all_not_found(self):
        self.assertRaises(exception.NoFloatingIpsDefined,
                          db.floating_ip_get_all, self.ctxt)

    def test_floating_ip_get_all_by_host(self):
        hosts = {
            'host1': ['1.1.1.1', '1.1.1.2'],
            'host2': ['2.1.1.1', '2.1.1.2'],
            'host3': ['3.1.1.1', '3.1.1.2', '3.1.1.3']
        }

        hosts_with_float_ips = {}
        for host, addresses in hosts.iteritems():
            hosts_with_float_ips[host] = []
            for address in addresses:
                float_ip = self._create_floating_ip({'host': host,
                                                     'address': address})
                hosts_with_float_ips[host].append(float_ip)

        for host, float_ips in hosts_with_float_ips.iteritems():
            real_float_ips = db.floating_ip_get_all_by_host(self.ctxt, host)
            self._assertEqualListsOfObjects(float_ips, real_float_ips)

    def test_floating_ip_get_all_by_host_not_found(self):
        self.assertRaises(exception.FloatingIpNotFoundForHost,
                          db.floating_ip_get_all_by_host,
                          self.ctxt, 'non_exists_host')

    def test_floating_ip_get_all_by_project(self):
        projects = {
            'pr1': ['1.1.1.1', '1.1.1.2'],
            'pr2': ['2.1.1.1', '2.1.1.2'],
            'pr3': ['3.1.1.1', '3.1.1.2', '3.1.1.3']
        }

        projects_with_float_ips = {}
        for project_id, addresses in projects.iteritems():
            projects_with_float_ips[project_id] = []
            for address in addresses:
                float_ip = self._create_floating_ip({'project_id': project_id,
                                                     'address': address})
                projects_with_float_ips[project_id].append(float_ip)

        for project_id, float_ips in projects_with_float_ips.iteritems():
            real_float_ips = db.floating_ip_get_all_by_project(self.ctxt,
                                                               project_id)
            self._assertEqualListsOfObjects(float_ips, real_float_ips,
                                            ignored_keys='fixed_ip')

    def test_floating_ip_get_all_by_project_not_authorized(self):
        ctxt = context.RequestContext(user_id='a', project_id='abc',
                                      is_admin=False)
        self.assertRaises(exception.NotAuthorized,
                          db.floating_ip_get_all_by_project,
                          ctxt, 'other_project')

    def test_floating_ip_get_by_address(self):
        addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        float_ips = [self._create_floating_ip({'address': addr})
                        for addr in addresses]

        for float_ip in float_ips:
            real_float_ip = db.floating_ip_get_by_address(self.ctxt,
                                                          float_ip.address)
            self._assertEqualObjects(float_ip, real_float_ip,
                                     ignored_keys='fixed_ip')

    def test_floating_ip_get_by_address_not_found(self):
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          db.floating_ip_get_by_address,
                          self.ctxt, '20.20.20.20')

    def test_floating_ip_get_by_invalid_address(self):
        self.mock_db_query_first_to_raise_data_error_exception()
        self.assertRaises(exception.InvalidIpAddressError,
                          db.floating_ip_get_by_address,
                          self.ctxt, 'non_exists_host')

    def test_floating_ip_get_by_fixed_address(self):
        fixed_float = [
            ('1.1.1.1', '2.2.2.1'),
            ('1.1.1.2', '2.2.2.2'),
            ('1.1.1.3', '2.2.2.3')
        ]

        for fixed_addr, float_addr in fixed_float:
            self._create_floating_ip({'address': float_addr})
            self._create_fixed_ip({'address': fixed_addr})
            db.floating_ip_fixed_ip_associate(self.ctxt, float_addr,
                                              fixed_addr, 'some_host')

        for fixed_addr, float_addr in fixed_float:
            float_ip = db.floating_ip_get_by_fixed_address(self.ctxt,
                                                           fixed_addr)
            self.assertEqual(float_addr, float_ip[0]['address'])

    def test_floating_ip_get_by_fixed_ip_id(self):
        fixed_float = [
            ('1.1.1.1', '2.2.2.1'),
            ('1.1.1.2', '2.2.2.2'),
            ('1.1.1.3', '2.2.2.3')
        ]

        for fixed_addr, float_addr in fixed_float:
            self._create_floating_ip({'address': float_addr})
            self._create_fixed_ip({'address': fixed_addr})
            db.floating_ip_fixed_ip_associate(self.ctxt, float_addr,
                                              fixed_addr, 'some_host')

        for fixed_addr, float_addr in fixed_float:
            fixed_ip = db.fixed_ip_get_by_address(self.ctxt, fixed_addr)
            float_ip = db.floating_ip_get_by_fixed_ip_id(self.ctxt,
                                                         fixed_ip['id'])
            self.assertEqual(float_addr, float_ip[0]['address'])

    def test_floating_ip_update(self):
        float_ip = self._create_floating_ip({})

        values = {
            'project_id': 'some_pr',
            'host': 'some_host',
            'auto_assigned': True,
            'interface': 'some_interface',
            'pool': 'some_pool'
        }
        db.floating_ip_update(self.ctxt, float_ip['address'], values)
        updated_float_ip = db.floating_ip_get(self.ctxt, float_ip['id'])
        self._assertEqualObjects(updated_float_ip, values,
                                 ignored_keys=['id', 'address', 'updated_at',
                                               'deleted_at', 'created_at',
                                               'deleted', 'fixed_ip_id',
                                               'fixed_ip'])

    def test_floating_ip_update_to_duplicate(self):
        float_ip1 = self._create_floating_ip({'address': '1.1.1.1'})
        float_ip2 = self._create_floating_ip({'address': '1.1.1.2'})

        self.assertRaises(exception.FloatingIpExists,
                          db.floating_ip_update,
                          self.ctxt, float_ip2['address'],
                          {'address': float_ip1['address']})


class InstanceDestroyConstraints(test.TestCase):

    def test_destroy_with_equal_any_constraint_met(self):
        ctx = context.get_admin_context()
        instance = db.instance_create(ctx, {'task_state': 'deleting'})
        constraint = db.constraint(task_state=db.equal_any('deleting'))
        db.instance_destroy(ctx, instance['uuid'], constraint)
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          ctx, instance['uuid'])

    def test_destroy_with_equal_any_constraint_not_met(self):
        ctx = context.get_admin_context()
        instance = db.instance_create(ctx, {'vm_state': 'resize'})
        constraint = db.constraint(vm_state=db.equal_any('active', 'error'))
        self.assertRaises(exception.ConstraintNotMet, db.instance_destroy,
                          ctx, instance['uuid'], constraint)
        instance = db.instance_get_by_uuid(ctx, instance['uuid'])
        self.assertFalse(instance['deleted'])

    def test_destroy_with_not_equal_constraint_met(self):
        ctx = context.get_admin_context()
        instance = db.instance_create(ctx, {'task_state': 'deleting'})
        constraint = db.constraint(task_state=db.not_equal('error', 'resize'))
        db.instance_destroy(ctx, instance['uuid'], constraint)
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          ctx, instance['uuid'])

    def test_destroy_with_not_equal_constraint_not_met(self):
        ctx = context.get_admin_context()
        instance = db.instance_create(ctx, {'vm_state': 'active'})
        constraint = db.constraint(vm_state=db.not_equal('active', 'error'))
        self.assertRaises(exception.ConstraintNotMet, db.instance_destroy,
                          ctx, instance['uuid'], constraint)
        instance = db.instance_get_by_uuid(ctx, instance['uuid'])
        self.assertFalse(instance['deleted'])


class VolumeUsageDBApiTestCase(test.TestCase):

    def setUp(self):
        super(VolumeUsageDBApiTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

        self.useFixture(test.TimeOverride())

    def test_vol_usage_update_no_totals_update(self):
        ctxt = context.get_admin_context()
        now = timeutils.utcnow()
        start_time = now - datetime.timedelta(seconds=10)

        self.mox.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().AndReturn(now)
        timeutils.utcnow().AndReturn(now)
        timeutils.utcnow().AndReturn(now)
        self.mox.ReplayAll()

        expected_vol_usages = [{'volume_id': u'1',
                                'instance_uuid': 'fake-instance-uuid1',
                                'project_id': 'fake-project-uuid1',
                                'user_id': 'fake-user-uuid1',
                                'curr_reads': 1000,
                                'curr_read_bytes': 2000,
                                'curr_writes': 3000,
                                'curr_write_bytes': 4000,
                                'curr_last_refreshed': now,
                                'tot_reads': 0,
                                'tot_read_bytes': 0,
                                'tot_writes': 0,
                                'tot_write_bytes': 0,
                                'tot_last_refreshed': None},
                               {'volume_id': u'2',
                                'instance_uuid': 'fake-instance-uuid2',
                                'project_id': 'fake-project-uuid2',
                                'user_id': 'fake-user-uuid2',
                                'curr_reads': 100,
                                'curr_read_bytes': 200,
                                'curr_writes': 300,
                                'curr_write_bytes': 400,
                                'tot_reads': 0,
                                'tot_read_bytes': 0,
                                'tot_writes': 0,
                                'tot_write_bytes': 0,
                                'tot_last_refreshed': None}]

        def _compare(vol_usage, expected):
            for key, value in expected.items():
                self.assertEqual(vol_usage[key], value)

        vol_usages = db.vol_get_usage_by_time(ctxt, start_time)
        self.assertEqual(len(vol_usages), 0)

        db.vol_usage_update(ctxt, u'1', rd_req=10, rd_bytes=20,
                            wr_req=30, wr_bytes=40,
                            instance_id='fake-instance-uuid1',
                            project_id='fake-project-uuid1',
                            user_id='fake-user-uuid1',
                            availability_zone='fake-az')
        db.vol_usage_update(ctxt, u'2', rd_req=100, rd_bytes=200,
                            wr_req=300, wr_bytes=400,
                            instance_id='fake-instance-uuid2',
                            project_id='fake-project-uuid2',
                            user_id='fake-user-uuid2',
                            availability_zone='fake-az')
        db.vol_usage_update(ctxt, u'1', rd_req=1000, rd_bytes=2000,
                            wr_req=3000, wr_bytes=4000,
                            instance_id='fake-instance-uuid1',
                            project_id='fake-project-uuid1',
                            user_id='fake-user-uuid1',
                            availability_zone='fake-az')

        vol_usages = db.vol_get_usage_by_time(ctxt, start_time)
        self.assertEqual(len(vol_usages), 2)
        _compare(vol_usages[0], expected_vol_usages[0])
        _compare(vol_usages[1], expected_vol_usages[1])

    def test_vol_usage_update_totals_update(self):
        ctxt = context.get_admin_context()
        now = datetime.datetime(1, 1, 1, 1, 0, 0)
        start_time = now - datetime.timedelta(seconds=10)

        self.mox.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().AndReturn(now)
        now1 = now + datetime.timedelta(minutes=1)
        timeutils.utcnow().AndReturn(now1)
        now2 = now + datetime.timedelta(minutes=2)
        timeutils.utcnow().AndReturn(now2)
        now3 = now + datetime.timedelta(minutes=3)
        timeutils.utcnow().AndReturn(now3)
        self.mox.ReplayAll()

        db.vol_usage_update(ctxt, u'1', rd_req=100, rd_bytes=200,
                            wr_req=300, wr_bytes=400,
                            instance_id='fake-instance-uuid',
                            project_id='fake-project-uuid',
                            user_id='fake-user-uuid',
                            availability_zone='fake-az')
        current_usage = db.vol_get_usage_by_time(ctxt, start_time)[0]
        self.assertEqual(current_usage['tot_reads'], 0)
        self.assertEqual(current_usage['curr_reads'], 100)

        db.vol_usage_update(ctxt, u'1', rd_req=200, rd_bytes=300,
                            wr_req=400, wr_bytes=500,
                            instance_id='fake-instance-uuid',
                            project_id='fake-project-uuid',
                            user_id='fake-user-uuid',
                            availability_zone='fake-az',
                            update_totals=True)
        current_usage = db.vol_get_usage_by_time(ctxt, start_time)[0]
        self.assertEqual(current_usage['tot_reads'], 200)
        self.assertEqual(current_usage['curr_reads'], 0)

        db.vol_usage_update(ctxt, u'1', rd_req=300, rd_bytes=400,
                            wr_req=500, wr_bytes=600,
                            instance_id='fake-instance-uuid',
                            project_id='fake-project-uuid',
                            availability_zone='fake-az',
                            user_id='fake-user-uuid')
        current_usage = db.vol_get_usage_by_time(ctxt, start_time)[0]
        self.assertEqual(current_usage['tot_reads'], 200)
        self.assertEqual(current_usage['curr_reads'], 300)

        db.vol_usage_update(ctxt, u'1', rd_req=400, rd_bytes=500,
                            wr_req=600, wr_bytes=700,
                            instance_id='fake-instance-uuid',
                            project_id='fake-project-uuid',
                            user_id='fake-user-uuid',
                            availability_zone='fake-az',
                            update_totals=True)

        vol_usages = db.vol_get_usage_by_time(ctxt, start_time)

        expected_vol_usages = {'volume_id': u'1',
                               'project_id': 'fake-project-uuid',
                               'user_id': 'fake-user-uuid',
                               'instance_uuid': 'fake-instance-uuid',
                               'availability_zone': 'fake-az',
                               'tot_reads': 600,
                               'tot_read_bytes': 800,
                               'tot_writes': 1000,
                               'tot_write_bytes': 1200,
                               'tot_last_refreshed': now3,
                               'curr_reads': 0,
                               'curr_read_bytes': 0,
                               'curr_writes': 0,
                               'curr_write_bytes': 0,
                               'curr_last_refreshed': now2}

        self.assertEquals(1, len(vol_usages))
        for key, value in expected_vol_usages.items():
            self.assertEqual(vol_usages[0][key], value, key)

    def test_vol_usage_update_when_blockdevicestats_reset(self):
        ctxt = context.get_admin_context()
        now = timeutils.utcnow()
        start_time = now - datetime.timedelta(seconds=10)

        vol_usages = db.vol_get_usage_by_time(ctxt, start_time)
        self.assertEqual(len(vol_usages), 0)

        db.vol_usage_update(ctxt, u'1',
                            rd_req=10000, rd_bytes=20000,
                            wr_req=30000, wr_bytes=40000,
                            instance_id='fake-instance-uuid1',
                            project_id='fake-project-uuid1',
                            availability_zone='fake-az',
                            user_id='fake-user-uuid1')

        # Instance rebooted or crashed. block device stats were reset and are
        # less then the previous values
        db.vol_usage_update(ctxt, u'1',
                            rd_req=100, rd_bytes=200,
                            wr_req=300, wr_bytes=400,
                            instance_id='fake-instance-uuid1',
                            project_id='fake-project-uuid1',
                            availability_zone='fake-az',
                            user_id='fake-user-uuid1')

        db.vol_usage_update(ctxt, u'1',
                            rd_req=200, rd_bytes=300,
                            wr_req=400, wr_bytes=500,
                            instance_id='fake-instance-uuid1',
                            project_id='fake-project-uuid1',
                            availability_zone='fake-az',
                            user_id='fake-user-uuid1')

        vol_usage = db.vol_get_usage_by_time(ctxt, start_time)[0]
        expected_vol_usage = {'volume_id': u'1',
                              'instance_uuid': 'fake-instance-uuid1',
                              'project_id': 'fake-project-uuid1',
                              'availability_zone': 'fake-az',
                              'user_id': 'fake-user-uuid1',
                              'curr_reads': 200,
                              'curr_read_bytes': 300,
                              'curr_writes': 400,
                              'curr_write_bytes': 500,
                              'tot_reads': 10000,
                              'tot_read_bytes': 20000,
                              'tot_writes': 30000,
                              'tot_write_bytes': 40000}
        for key, value in expected_vol_usage.items():
            self.assertEqual(vol_usage[key], value, key)

    def test_vol_usage_update_totals_update_when_blockdevicestats_reset(self):
        # This is unlikely to happen, but could when a volume is detached
        # right after a instance has rebooted / recovered and before
        # the system polled and updated the volume usage cache table.
        ctxt = context.get_admin_context()
        now = timeutils.utcnow()
        start_time = now - datetime.timedelta(seconds=10)

        vol_usages = db.vol_get_usage_by_time(ctxt, start_time)
        self.assertEqual(len(vol_usages), 0)

        db.vol_usage_update(ctxt, u'1',
                            rd_req=10000, rd_bytes=20000,
                            wr_req=30000, wr_bytes=40000,
                            instance_id='fake-instance-uuid1',
                            project_id='fake-project-uuid1',
                            availability_zone='fake-az',
                            user_id='fake-user-uuid1')

        # Instance rebooted or crashed. block device stats were reset and are
        # less then the previous values
        db.vol_usage_update(ctxt, u'1',
                            rd_req=100, rd_bytes=200,
                            wr_req=300, wr_bytes=400,
                            instance_id='fake-instance-uuid1',
                            project_id='fake-project-uuid1',
                            availability_zone='fake-az',
                            user_id='fake-user-uuid1',
                            update_totals=True)

        vol_usage = db.vol_get_usage_by_time(ctxt, start_time)[0]
        expected_vol_usage = {'volume_id': u'1',
                              'instance_uuid': 'fake-instance-uuid1',
                              'project_id': 'fake-project-uuid1',
                              'availability_zone': 'fake-az',
                              'user_id': 'fake-user-uuid1',
                              'curr_reads': 0,
                              'curr_read_bytes': 0,
                              'curr_writes': 0,
                              'curr_write_bytes': 0,
                              'tot_reads': 10100,
                              'tot_read_bytes': 20200,
                              'tot_writes': 30300,
                              'tot_write_bytes': 40400}
        for key, value in expected_vol_usage.items():
            self.assertEqual(vol_usage[key], value, key)


class TaskLogTestCase(test.TestCase):

    def setUp(self):
        super(TaskLogTestCase, self).setUp()
        self.context = context.get_admin_context()
        now = timeutils.utcnow()
        self.begin = now - datetime.timedelta(seconds=10)
        self.end = now - datetime.timedelta(seconds=5)
        self.task_name = 'fake-task-name'
        self.host = 'fake-host'
        self.message = 'Fake task message'
        db.task_log_begin_task(self.context, self.task_name, self.begin,
                               self.end, self.host, message=self.message)

    def test_task_log_get(self):
        result = db.task_log_get(self.context, self.task_name, self.begin,
                                 self.end, self.host)
        self.assertEqual(result['task_name'], self.task_name)
        self.assertEqual(result['period_beginning'], self.begin)
        self.assertEqual(result['period_ending'], self.end)
        self.assertEqual(result['host'], self.host)
        self.assertEqual(result['message'], self.message)

    def test_task_log_get_all(self):
        result = db.task_log_get_all(self.context, self.task_name, self.begin,
                                     self.end, host=self.host)
        self.assertEqual(len(result), 1)

    def test_task_log_begin_task(self):
        db.task_log_begin_task(self.context, 'fake', self.begin,
                               self.end, self.host, message=self.message)
        result = db.task_log_get(self.context, 'fake', self.begin,
                                 self.end, self.host)
        self.assertEqual(result['task_name'], 'fake')

    def test_task_log_begin_task_duplicate(self):
        params = (self.context, 'fake', self.begin, self.end, self.host)
        db.task_log_begin_task(*params, message=self.message)
        self.assertRaises(exception.TaskAlreadyRunning,
                          db.task_log_begin_task,
                          *params, message=self.message)

    def test_task_log_end_task(self):
        errors = 1
        db.task_log_end_task(self.context, self.task_name, self.begin,
                            self.end, self.host, errors, message=self.message)
        result = db.task_log_get(self.context, self.task_name, self.begin,
                                 self.end, self.host)
        self.assertEqual(result['errors'], 1)


class BlockDeviceMappingTestCase(test.TestCase):
    def setUp(self):
        super(BlockDeviceMappingTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.instance = db.instance_create(self.ctxt, {})

    def _create_bdm(self, values):
        values.setdefault('instance_uuid', self.instance['uuid'])
        values.setdefault('device_name', 'fake_device')
        values.setdefault('source_type', 'volume')
        values.setdefault('destination_type', 'volume')
        block_dev = block_device.BlockDeviceDict(values)
        db.block_device_mapping_create(self.ctxt, block_dev, legacy=False)
        uuid = block_dev['instance_uuid']

        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)

        for bdm in bdms:
            if bdm['device_name'] == values['device_name']:
                return bdm

    def test_scrub_empty_str_values_no_effect(self):
        values = {'volume_size': 5}
        expected = copy.copy(values)
        sqlalchemy_api._scrub_empty_str_values(values, ['volume_size'])
        self.assertEqual(values, expected)

    def test_scrub_empty_str_values_empty_string(self):
        values = {'volume_size': ''}
        sqlalchemy_api._scrub_empty_str_values(values, ['volume_size'])
        self.assertEqual(values, {})

    def test_scrub_empty_str_values_empty_unicode(self):
        values = {'volume_size': u''}
        sqlalchemy_api._scrub_empty_str_values(values, ['volume_size'])
        self.assertEqual(values, {})

    def test_block_device_mapping_create(self):
        bdm = self._create_bdm({})
        self.assertFalse(bdm is None)

    def test_block_device_mapping_update(self):
        bdm = self._create_bdm({})
        result = db.block_device_mapping_update(
                self.ctxt, bdm['id'], {'destination_type': 'moon'},
                legacy=False)
        uuid = bdm['instance_uuid']
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(bdm_real[0]['destination_type'], 'moon')
        # Also make sure the update call returned correct data
        self.assertEqual(dict(bdm_real[0].iteritems()),
                         dict(result.iteritems()))

    def test_block_device_mapping_update_or_create(self):
        values = {
            'instance_uuid': self.instance['uuid'],
            'device_name': 'fake_name',
            'source_type': 'volume',
            'destination_type': 'volume'
        }
        # check create
        db.block_device_mapping_update_or_create(self.ctxt, values,
                                                 legacy=False)
        uuid = values['instance_uuid']
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdm_real), 1)
        self.assertEqual(bdm_real[0]['device_name'], 'fake_name')

        # check update
        values['destination_type'] = 'camelot'
        db.block_device_mapping_update_or_create(self.ctxt, values,
                                                 legacy=False)
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdm_real), 1)
        bdm_real = bdm_real[0]
        self.assertEqual(bdm_real['device_name'], 'fake_name')
        self.assertEqual(bdm_real['destination_type'], 'camelot')

    def test_block_device_mapping_update_or_create_check_remove_virt(self):
        uuid = self.instance['uuid']
        values = {
            'instance_uuid': uuid,
            'source_type': 'blank',
            'guest_format': 'swap',
        }

        # check that old swap bdms are deleted on create
        val1 = dict(values)
        val1['device_name'] = 'device1'
        db.block_device_mapping_create(self.ctxt, val1, legacy=False)
        val2 = dict(values)
        val2['device_name'] = 'device2'
        db.block_device_mapping_update_or_create(self.ctxt, val2, legacy=False)
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdm_real), 1)
        bdm_real = bdm_real[0]
        self.assertEqual(bdm_real['device_name'], 'device2')
        self.assertEqual(bdm_real['source_type'], 'blank')
        self.assertEqual(bdm_real['guest_format'], 'swap')
        db.block_device_mapping_destroy(self.ctxt, bdm_real['id'])

        # check that old ephemerals are deleted no matter what
        val3 = dict(values)
        val3['device_name'] = 'device3'
        val3['guest_format'] = None
        val4 = dict(values)
        val4['device_name'] = 'device4'
        val4['guest_format'] = None
        db.block_device_mapping_create(self.ctxt, val3, legacy=False)
        db.block_device_mapping_create(self.ctxt, val4, legacy=False)
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdm_real), 2)

        val5 = dict(values)
        val5['device_name'] = 'device5'
        val5['guest_format'] = None
        db.block_device_mapping_update_or_create(self.ctxt, val5, legacy=False)
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdm_real), 1)
        bdm_real = bdm_real[0]
        self.assertEqual(bdm_real['device_name'], 'device5')

    def test_block_device_mapping_get_all_by_instance(self):
        uuid1 = self.instance['uuid']
        uuid2 = db.instance_create(self.ctxt, {})['uuid']

        bmds_values = [{'instance_uuid': uuid1,
                        'device_name': 'first'},
                       {'instance_uuid': uuid2,
                        'device_name': 'second'},
                       {'instance_uuid': uuid2,
                        'device_name': 'third'}]

        for bdm in bmds_values:
            self._create_bdm(bdm)

        bmd = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid1)
        self.assertEqual(len(bmd), 1)
        self.assertEqual(bmd[0]['device_name'], 'first')

        bmd = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid2)
        self.assertEqual(len(bmd), 2)

    def test_block_device_mapping_destroy(self):
        bdm = self._create_bdm({})
        db.block_device_mapping_destroy(self.ctxt, bdm['id'])
        bdm = db.block_device_mapping_get_all_by_instance(self.ctxt,
                                                          bdm['instance_uuid'])
        self.assertEqual(len(bdm), 0)

    def test_block_device_mapping_destory_by_instance_and_volumne(self):
        vol_id1 = '69f5c254-1a5b-4fff-acf7-cb369904f58f'
        vol_id2 = '69f5c254-1a5b-4fff-acf7-cb369904f59f'

        self._create_bdm({'device_name': 'fake1', 'volume_id': vol_id1})
        self._create_bdm({'device_name': 'fake2', 'volume_id': vol_id2})

        uuid = self.instance['uuid']
        db.block_device_mapping_destroy_by_instance_and_volume(self.ctxt, uuid,
                                                               vol_id1)
        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdms), 1)
        self.assertEqual(bdms[0]['device_name'], 'fake2')

    def test_block_device_mapping_destroy_by_instance_and_device(self):
        self._create_bdm({'device_name': 'fake1'})
        self._create_bdm({'device_name': 'fake2'})

        uuid = self.instance['uuid']
        params = (self.ctxt, uuid, 'fake1')
        db.block_device_mapping_destroy_by_instance_and_device(*params)

        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdms), 1)
        self.assertEqual(bdms[0]['device_name'], 'fake2')


class AgentBuildTestCase(test.TestCase, ModelsObjectComparatorMixin):

    """Tests for db.api.agent_build_* methods."""

    def setUp(self):
        super(AgentBuildTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def test_agent_build_create_and_get_all(self):
        self.assertEqual(0, len(db.agent_build_get_all(self.ctxt)))
        agent_build = db.agent_build_create(self.ctxt, {'os': 'GNU/HURD'})
        all_agent_builds = db.agent_build_get_all(self.ctxt)
        self.assertEqual(1, len(all_agent_builds))
        self._assertEqualObjects(agent_build, all_agent_builds[0])

    def test_agent_build_get_by_triple(self):
        agent_build = db.agent_build_create(self.ctxt, {'hypervisor': 'kvm',
                                'os': 'FreeBSD', 'architecture': 'x86_64'})
        self.assertIsNone(db.agent_build_get_by_triple(self.ctxt, 'kvm',
                                                        'FreeBSD', 'i386'))
        self._assertEqualObjects(agent_build, db.agent_build_get_by_triple(
                                    self.ctxt, 'kvm', 'FreeBSD', 'x86_64'))

    def test_agent_build_destroy(self):
        agent_build = db.agent_build_create(self.ctxt, {})
        self.assertEqual(1, len(db.agent_build_get_all(self.ctxt)))
        db.agent_build_destroy(self.ctxt, agent_build.id)
        self.assertEqual(0, len(db.agent_build_get_all(self.ctxt)))

    def test_agent_build_update(self):
        agent_build = db.agent_build_create(self.ctxt, {'os': 'HaikuOS'})
        db.agent_build_update(self.ctxt, agent_build.id, {'os': 'ReactOS'})
        self.assertEqual('ReactOS', db.agent_build_get_all(self.ctxt)[0].os)

    def test_agent_build_destroy_destroyed(self):
        agent_build = db.agent_build_create(self.ctxt, {})
        db.agent_build_destroy(self.ctxt, agent_build.id)
        self.assertRaises(exception.AgentBuildNotFound,
            db.agent_build_destroy, self.ctxt, agent_build.id)

    def test_agent_build_update_destroyed(self):
        agent_build = db.agent_build_create(self.ctxt, {'os': 'HaikuOS'})
        db.agent_build_destroy(self.ctxt, agent_build.id)
        self.assertRaises(exception.AgentBuildNotFound,
            db.agent_build_update, self.ctxt, agent_build.id, {'os': 'OS/2'})

    def test_agent_build_exists(self):
        values = {'hypervisor': 'kvm', 'os': 'FreeBSD',
                  'architecture': 'x86_64'}
        db.agent_build_create(self.ctxt, values)
        self.assertRaises(exception.AgentBuildExists, db.agent_build_create,
                          self.ctxt, values)


class VirtualInterfaceTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(VirtualInterfaceTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.instance_uuid = db.instance_create(self.ctxt, {})['uuid']
        values = {'host': 'localhost', 'project_id': 'project1'}
        self.network = db.network_create_safe(self.ctxt, values)

    def _get_base_values(self):
        return {
            'instance_uuid': self.instance_uuid,
            'address': 'fake_address',
            'network_id': self.network['id'],
            'uuid': str(stdlib_uuid.uuid4())
        }

    def mock_db_query_first_to_raise_data_error_exception(self):
        self.mox.StubOutWithMock(query.Query, 'first')
        query.Query.first().AndRaise(exc.DataError(mox.IgnoreArg(),
                                                   mox.IgnoreArg(),
                                                   mox.IgnoreArg()))
        self.mox.ReplayAll()

    def _create_virt_interface(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.virtual_interface_create(self.ctxt, v)

    def test_virtual_interface_create(self):
        vif = self._create_virt_interface({})
        self.assertFalse(vif['id'] is None)
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at', 'uuid']
        self._assertEqualObjects(vif, self._get_base_values(), ignored_keys)

    def test_virtual_interface_create_with_duplicate_address(self):
        vif = self._create_virt_interface({})
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          self._create_virt_interface, {"uuid": vif['uuid']})

    def test_virtual_interface_get(self):
        vifs = [self._create_virt_interface({'address': 'a'}),
                self._create_virt_interface({'address': 'b'})]

        for vif in vifs:
            real_vif = db.virtual_interface_get(self.ctxt, vif['id'])
            self._assertEqualObjects(vif, real_vif)

    def test_virtual_interface_get_by_address(self):
        vifs = [self._create_virt_interface({'address': 'first'}),
                self._create_virt_interface({'address': 'second'})]
        for vif in vifs:
            real_vif = db.virtual_interface_get_by_address(self.ctxt,
                                                           vif['address'])
            self._assertEqualObjects(vif, real_vif)

    def test_virtual_interface_get_by_address_not_found(self):
        self.assertIsNone(db.virtual_interface_get_by_address(self.ctxt,
                          "i.nv.ali.ip"))

    def test_virtual_interface_get_by_address_data_error_exception(self):
        self.mock_db_query_first_to_raise_data_error_exception()
        self.assertRaises(exception.InvalidIpAddressError,
                          db.virtual_interface_get_by_address,
                          self.ctxt,
                          "i.nv.ali.ip")

    def test_virtual_interface_get_by_uuid(self):
        vifs = [self._create_virt_interface({"address": "address_1"}),
                self._create_virt_interface({"address": "address_2"})]
        for vif in vifs:
            real_vif = db.virtual_interface_get_by_uuid(self.ctxt, vif['uuid'])
            self._assertEqualObjects(vif, real_vif)

    def test_virtual_interface_get_by_instance(self):
        inst_uuid2 = db.instance_create(self.ctxt, {})['uuid']
        vifs1 = [self._create_virt_interface({'address': 'fake1'}),
                 self._create_virt_interface({'address': 'fake2'})]
        vifs2 = [self._create_virt_interface({'address': 'fake3',
                                              'instance_uuid': inst_uuid2})]
        vifs1_real = db.virtual_interface_get_by_instance(self.ctxt,
                                                          self.instance_uuid)
        vifs2_real = db.virtual_interface_get_by_instance(self.ctxt,
                                                          inst_uuid2)
        self._assertEqualListsOfObjects(vifs1, vifs1_real)
        self._assertEqualListsOfObjects(vifs2, vifs2_real)

    def test_virtual_interface_get_by_instance_and_network(self):
        inst_uuid2 = db.instance_create(self.ctxt, {})['uuid']
        values = {'host': 'localhost', 'project_id': 'project2'}
        network_id = db.network_create_safe(self.ctxt, values)['id']

        vifs = [self._create_virt_interface({'address': 'fake1'}),
                self._create_virt_interface({'address': 'fake2',
                                             'network_id': network_id,
                                             'instance_uuid': inst_uuid2}),
                self._create_virt_interface({'address': 'fake3',
                                             'instance_uuid': inst_uuid2})]
        for vif in vifs:
            params = (self.ctxt, vif['instance_uuid'], vif['network_id'])
            r_vif = db.virtual_interface_get_by_instance_and_network(*params)
            self._assertEqualObjects(r_vif, vif)

    def test_virtual_interface_delete_by_instance(self):
        inst_uuid2 = db.instance_create(self.ctxt, {})['uuid']

        values = [dict(address='fake1'), dict(address='fake2'),
                  dict(address='fake3', instance_uuid=inst_uuid2)]
        for vals in values:
            self._create_virt_interface(vals)

        db.virtual_interface_delete_by_instance(self.ctxt, self.instance_uuid)

        real_vifs1 = db.virtual_interface_get_by_instance(self.ctxt,
                                                          self.instance_uuid)
        real_vifs2 = db.virtual_interface_get_by_instance(self.ctxt,
                                                          inst_uuid2)
        self.assertEqual(len(real_vifs1), 0)
        self.assertEqual(len(real_vifs2), 1)

    def test_virtual_interface_get_all(self):
        inst_uuid2 = db.instance_create(self.ctxt, {})['uuid']
        values = [dict(address='fake1'), dict(address='fake2'),
                  dict(address='fake3', instance_uuid=inst_uuid2)]

        vifs = [self._create_virt_interface(val) for val in values]
        real_vifs = db.virtual_interface_get_all(self.ctxt)
        self._assertEqualListsOfObjects(vifs, real_vifs)


class NetworkTestCase(test.TestCase, ModelsObjectComparatorMixin):

    """Tests for db.api.network_* methods."""

    def setUp(self):
        super(NetworkTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _get_associated_fixed_ip(self, host, cidr, ip):
        network = db.network_create_safe(self.ctxt,
            {'project_id': 'project1', 'cidr': cidr})
        self.assertFalse(db.network_in_use_on_host(self.ctxt, network.id,
            host))
        instance = db.instance_create(self.ctxt,
            {'project_id': 'project1', 'host': host})
        virtual_interface = db.virtual_interface_create(self.ctxt,
            {'instance_uuid': instance.uuid, 'network_id': network.id,
            'address': ip})
        db.fixed_ip_create(self.ctxt, {'address': ip,
            'network_id': network.id, 'allocated': True,
            'virtual_interface_id': virtual_interface.id})
        db.fixed_ip_associate(self.ctxt, ip, instance.uuid,
            network.id)
        return network, instance

    def test_network_in_use_on_host(self):
        network, _ = self._get_associated_fixed_ip('host.net', '192.0.2.0/30',
            '192.0.2.1')
        self.assertTrue(db.network_in_use_on_host(self.ctxt, network.id,
            'host.net'))

    def test_network_get_associated_fixed_ips(self):
        network, instance = self._get_associated_fixed_ip('host.net',
            '192.0.2.0/30', '192.0.2.1')
        data = db.network_get_associated_fixed_ips(self.ctxt, network.id)
        self.assertEqual(1, len(data))
        self.assertEqual('192.0.2.1', data[0]['address'])
        self.assertEqual('192.0.2.1', data[0]['vif_address'])
        self.assertEqual(instance.uuid, data[0]['instance_uuid'])
        self.assertTrue(data[0]['allocated'])

    def test_network_create_safe(self):
        values = {'host': 'localhost', 'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)
        self.assertEqual(36, len(network['uuid']))
        db_network = db.network_get(self.ctxt, network['id'])
        self._assertEqualObjects(network, db_network)

    def test_network_create_with_duplicate_vlan(self):
        values1 = {'host': 'localhost', 'project_id': 'project1', 'vlan': 1}
        values2 = {'host': 'something', 'project_id': 'project1', 'vlan': 1}
        db.network_create_safe(self.ctxt, values1)
        self.assertRaises(exception.DuplicateVlan,
                          db.network_create_safe, self.ctxt, values2)

    def test_network_delete_safe(self):
        values = {'host': 'localhost', 'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)
        db_network = db.network_get(self.ctxt, network['id'])
        values = {'network_id': network['id'], 'address': '192.168.1.5'}
        address1 = db.fixed_ip_create(self.ctxt, values)['address']
        values = {'network_id': network['id'],
                  'address': '192.168.1.6',
                  'allocated': True}
        address2 = db.fixed_ip_create(self.ctxt, values)['address']
        self.assertRaises(exception.NetworkInUse,
                          db.network_delete_safe, self.ctxt, network['id'])
        db.fixed_ip_update(self.ctxt, address2, {'allocated': False})
        network = db.network_delete_safe(self.ctxt, network['id'])
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          db.fixed_ip_get_by_address, self.ctxt, address1)
        ctxt = self.ctxt.elevated(read_deleted='yes')
        fixed_ip = db.fixed_ip_get_by_address(ctxt, address1)
        self.assertTrue(fixed_ip['deleted'])

    def test_network_in_use_on_host(self):
        values = {'host': 'foo', 'hostname': 'myname'}
        instance = db.instance_create(self.ctxt, values)
        values = {'address': '192.168.1.5', 'instance_uuid': instance['uuid']}
        vif = db.virtual_interface_create(self.ctxt, values)
        values = {'address': '192.168.1.6',
                  'network_id': 1,
                  'allocated': True,
                  'instance_uuid': instance['uuid'],
                  'virtual_interface_id': vif['id']}
        db.fixed_ip_create(self.ctxt, values)
        self.assertEqual(db.network_in_use_on_host(self.ctxt, 1, 'foo'), True)
        self.assertEqual(db.network_in_use_on_host(self.ctxt, 1, 'bar'), False)

    def test_network_update_nonexistent(self):
        self.assertRaises(exception.NetworkNotFound,
            db.network_update, self.ctxt, 'nonexistent', {})

    def test_network_update_with_duplicate_vlan(self):
        values1 = {'host': 'localhost', 'project_id': 'project1', 'vlan': 1}
        values2 = {'host': 'something', 'project_id': 'project1', 'vlan': 2}
        network_ref = db.network_create_safe(self.ctxt, values1)
        db.network_create_safe(self.ctxt, values2)
        self.assertRaises(exception.DuplicateVlan,
                          db.network_update, self.ctxt,
                          network_ref["id"], values2)

    def test_network_update(self):
        network = db.network_create_safe(self.ctxt, {'project_id': 'project1',
            'vlan': 1, 'host': 'test.com'})
        db.network_update(self.ctxt, network.id, {'vlan': 2})
        network_new = db.network_get(self.ctxt, network.id)
        self.assertEqual(2, network_new.vlan)

    def test_network_set_host_nonexistent_network(self):
        self.assertRaises(exception.NetworkNotFound,
            db.network_set_host, self.ctxt, 'nonexistent', 'nonexistent')

    def test_network_set_host_with_initially_no_host(self):
        values = {'host': 'example.com', 'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)
        self.assertEqual(
            db.network_set_host(self.ctxt, network.id, 'new.example.com'),
            'example.com')

    def test_network_set_host(self):
        values = {'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)
        self.assertEqual(
            db.network_set_host(self.ctxt, network.id, 'example.com'),
            'example.com')
        self.assertEqual('example.com',
            db.network_get(self.ctxt, network.id).host)

    def test_network_get_all_by_host(self):
        self.assertEqual([],
            db.network_get_all_by_host(self.ctxt, 'example.com'))
        host = 'h1.example.com'
        # network with host set
        net1 = db.network_create_safe(self.ctxt, {'host': host})
        self._assertEqualListsOfObjects([net1],
            db.network_get_all_by_host(self.ctxt, host))
        # network with fixed ip with host set
        net2 = db.network_create_safe(self.ctxt, {})
        db.fixed_ip_create(self.ctxt, {'host': host, 'network_id': net2.id})
        data = db.network_get_all_by_host(self.ctxt, host)
        self._assertEqualListsOfObjects([net1, net2],
            db.network_get_all_by_host(self.ctxt, host))
        # network with instance with host set
        net3 = db.network_create_safe(self.ctxt, {})
        instance = db.instance_create(self.ctxt, {'host': host})
        vif = db.virtual_interface_create(self.ctxt,
            {'instance_uuid': instance.uuid})
        db.fixed_ip_create(self.ctxt, {'network_id': net3.id,
            'virtual_interface_id': vif.id})
        self._assertEqualListsOfObjects([net1, net2, net3],
            db.network_get_all_by_host(self.ctxt, host))

    def test_network_get_by_cidr_nonexistent(self):
        self.assertRaises(exception.NetworkNotFoundForCidr,
            db.network_get_by_cidr(self.ctxt, '192.0.2.0/29'))

    def test_network_get_by_cidr(self):
        cidr = '192.0.2.0/30'
        cidr_v6 = '2001:db8:1::/64'
        network = db.network_create_safe(self.ctxt,
            {'project_id': 'project1', 'cidr': cidr, 'cidr_v6': cidr_v6})
        self._assertEqualObjects(network,
            db.network_get_by_cidr(self.ctxt, cidr))
        self._assertEqualObjects(network,
            db.network_get_by_cidr(self.ctxt, cidr_v6))

    def test_network_get_by_cidr_nonexistent(self):
        self.assertRaises(exception.NetworkNotFoundForCidr,
            db.network_get_by_cidr, self.ctxt, '192.0.2.0/30')

    def test_network_get_by_uuid(self):
        network = db.network_create_safe(self.ctxt,
            {'project_id': 'project_1'})
        self._assertEqualObjects(network,
            db.network_get_by_uuid(self.ctxt, network.uuid))

    def test_network_get_by_uuid_nonexistent(self):
        self.assertRaises(exception.NetworkNotFoundForUUID,
            db.network_get_by_uuid, self.ctxt, 'non-existent-uuid')

    def test_network_get_all_by_uuids_no_networks(self):
        self.assertRaises(exception.NoNetworksFound,
            db.network_get_all_by_uuids, self.ctxt, ['non-existent-uuid'])

    def test_network_get_all_by_uuids(self):
        net1 = db.network_create_safe(self.ctxt, {})
        net2 = db.network_create_safe(self.ctxt, {})
        self._assertEqualListsOfObjects([net1, net2],
            db.network_get_all_by_uuids(self.ctxt, [net1.uuid, net2.uuid]))

    def test_network_get_all_no_networks(self):
        self.assertRaises(exception.NoNetworksFound,
            db.network_get_all, self.ctxt)

    def test_network_get_all(self):
        network = db.network_create_safe(self.ctxt, {})
        network_db = db.network_get_all(self.ctxt)
        self.assertEqual(1, len(network_db))
        self._assertEqualObjects(network, network_db[0])

    def test_network_get(self):
        network = db.network_create_safe(self.ctxt, {})
        self._assertEqualObjects(db.network_get(self.ctxt, network.id),
            network)
        db.network_delete_safe(self.ctxt, network.id)
        self.assertRaises(exception.NetworkNotFound,
            db.network_get, self.ctxt, network.id)

    def test_network_associate(self):
        network = db.network_create_safe(self.ctxt, {})
        self.assertIsNone(network.project_id)
        db.network_associate(self.ctxt, "project1", network.id)
        self.assertEqual("project1", db.network_get(self.ctxt,
            network.id).project_id)

    def test_network_diassociate(self):
        network = db.network_create_safe(self.ctxt,
            {'project_id': 'project1', 'host': 'test.net'})
        # disassociate project
        db.network_disassociate(self.ctxt, network.id, False, True)
        self.assertIsNone(db.network_get(self.ctxt, network.id).project_id)
        # disassociate host
        db.network_disassociate(self.ctxt, network.id, True, False)
        self.assertIsNone(db.network_get(self.ctxt, network.id).host)

    def test_network_count_reserved_ips(self):
        net = db.network_create_safe(self.ctxt, {})
        self.assertEqual(0, db.network_count_reserved_ips(self.ctxt, net.id))
        db.fixed_ip_create(self.ctxt, {'network_id': net.id,
            'reserved': True})
        self.assertEqual(1, db.network_count_reserved_ips(self.ctxt, net.id))


class KeyPairTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(KeyPairTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _create_key_pair(self, values):
        return db.key_pair_create(self.ctxt, values)

    def test_key_pair_create(self):
        param = {
            'name': 'test_1',
            'user_id': 'test_user_id_1',
            'public_key': 'test_public_key_1',
            'fingerprint': 'test_fingerprint_1'
        }
        key_pair = self._create_key_pair(param)

        self.assertTrue(key_pair['id'] is not None)
        ignored_keys = ['deleted', 'created_at', 'updated_at',
                        'deleted_at', 'id']
        self._assertEqualObjects(key_pair, param, ignored_keys)

    def test_key_pair_create_with_duplicate_name(self):
        params = {'name': 'test_name', 'user_id': 'test_user_id'}
        self._create_key_pair(params)
        self.assertRaises(exception.KeyPairExists, self._create_key_pair,
                          params)

    def test_key_pair_get(self):
        params = [
            {'name': 'test_1', 'user_id': 'test_user_id_1'},
            {'name': 'test_2', 'user_id': 'test_user_id_2'},
            {'name': 'test_3', 'user_id': 'test_user_id_3'}
        ]
        key_pairs = [self._create_key_pair(p) for p in params]

        for key in key_pairs:
            real_key = db.key_pair_get(self.ctxt, key['user_id'], key['name'])
            self._assertEqualObjects(key, real_key)

    def test_key_pair_get_no_results(self):
        param = {'name': 'test_1', 'user_id': 'test_user_id_1'}
        self.assertRaises(exception.KeypairNotFound, db.key_pair_get,
                          self.ctxt, param['user_id'], param['name'])

    def test_key_pair_get_deleted(self):
        param = {'name': 'test_1', 'user_id': 'test_user_id_1'}
        key_pair_created = self._create_key_pair(param)

        db.key_pair_destroy(self.ctxt, param['user_id'], param['name'])
        self.assertRaises(exception.KeypairNotFound, db.key_pair_get,
                          self.ctxt, param['user_id'], param['name'])

        ctxt = self.ctxt.elevated(read_deleted='yes')
        key_pair_deleted = db.key_pair_get(ctxt, param['user_id'],
                                           param['name'])
        ignored_keys = ['deleted', 'created_at', 'updated_at', 'deleted_at']
        self._assertEqualObjects(key_pair_deleted, key_pair_created,
                                 ignored_keys)
        self.assertEqual(key_pair_deleted['deleted'], key_pair_deleted['id'])

    def test_key_pair_get_all_by_user(self):
        params = [
            {'name': 'test_1', 'user_id': 'test_user_id_1'},
            {'name': 'test_2', 'user_id': 'test_user_id_1'},
            {'name': 'test_3', 'user_id': 'test_user_id_2'}
        ]
        key_pairs_user_1 = [self._create_key_pair(p) for p in params
                            if p['user_id'] == 'test_user_id_1']
        key_pairs_user_2 = [self._create_key_pair(p) for p in params
                            if p['user_id'] == 'test_user_id_2']

        real_keys_1 = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id_1')
        real_keys_2 = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id_2')

        self._assertEqualListsOfObjects(key_pairs_user_1, real_keys_1)
        self._assertEqualListsOfObjects(key_pairs_user_2, real_keys_2)

    def test_key_pair_count_by_user(self):
        params = [
            {'name': 'test_1', 'user_id': 'test_user_id_1'},
            {'name': 'test_2', 'user_id': 'test_user_id_1'},
            {'name': 'test_3', 'user_id': 'test_user_id_2'}
        ]
        for p in params:
            self._create_key_pair(p)

        count_1 = db.key_pair_count_by_user(self.ctxt, 'test_user_id_1')
        self.assertEqual(count_1, 2)

        count_2 = db.key_pair_count_by_user(self.ctxt, 'test_user_id_2')
        self.assertEqual(count_2, 1)

    def test_key_pair_destroy(self):
        param = {'name': 'test_1', 'user_id': 'test_user_id_1'}
        self._create_key_pair(param)

        db.key_pair_destroy(self.ctxt, param['user_id'], param['name'])
        self.assertRaises(exception.KeypairNotFound, db.key_pair_get,
                          self.ctxt, param['user_id'], param['name'])

    def test_key_pair_destroy_no_such_key(self):
        param = {'name': 'test_1', 'user_id': 'test_user_id_1'}
        self.assertRaises(exception.KeypairNotFound,
                          db.key_pair_destroy, self.ctxt,
                          param['user_id'], param['name'])


class QuotaTestCase(test.TestCase, ModelsObjectComparatorMixin):

    """Tests for db.api.quota_* methods."""

    def setUp(self):
        super(QuotaTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def test_quota_create(self):
        quota = db.quota_create(self.ctxt, 'project1', 'resource', 99)
        self.assertEqual(quota.resource, 'resource')
        self.assertEqual(quota.hard_limit, 99)
        self.assertEqual(quota.project_id, 'project1')

    def test_quota_get(self):
        quota = db.quota_create(self.ctxt, 'project1', 'resource', 99)
        quota_db = db.quota_get(self.ctxt, 'project1', 'resource')
        self._assertEqualObjects(quota, quota_db)

    def test_quota_get_all_by_project(self):
        for i in range(3):
            for j in range(3):
                db.quota_create(self.ctxt, 'proj%d' % i, 'resource%d' % j, j)
        for i in range(3):
            quotas_db = db.quota_get_all_by_project(self.ctxt, 'proj%d' % i)
            self.assertEqual(quotas_db, {'project_id': 'proj%d' % i,
                                                        'resource0': 0,
                                                        'resource1': 1,
                                                        'resource2': 2})

    def test_quota_get_all_by_project_and_user(self):
        for i in range(3):
            for j in range(3):
                db.quota_create(self.ctxt, 'proj%d' % i, 'resource%d' % j, j)
        for i in range(3):
            quotas_db = db.quota_get_all_by_project_and_user(self.ctxt,
                                                             'proj%d' % i,
                                                             'user%d' % i)
            self.assertEqual(quotas_db, {'project_id': 'proj%d' % i,
                                         'user_id': 'user%d' % i,
                                                        'resource0': 0,
                                                        'resource1': 1,
                                                        'resource2': 2})
        for i in range(3):
            for j in range(3):
                db.quota_create(self.ctxt, 'proj%d' % i, 'resource%d' % j,
                                j - 1, user_id='user%d' % i)
        for i in range(3):
            quotas_db = db.quota_get_all_by_project_and_user(self.ctxt,
                                                             'proj%d' % i,
                                                             'user%d' % i)
            self.assertEqual(quotas_db, {'project_id': 'proj%d' % i,
                                         'user_id': 'user%d' % i,
                                                        'resource0': -1,
                                                        'resource1': 0,
                                                        'resource2': 1})

    def test_quota_update(self):
        db.quota_create(self.ctxt, 'project1', 'resource1', 41)
        db.quota_update(self.ctxt, 'project1', 'resource1', 42)
        quota = db.quota_get(self.ctxt, 'project1', 'resource1')
        self.assertEqual(quota.hard_limit, 42)
        self.assertEqual(quota.resource, 'resource1')
        self.assertEqual(quota.project_id, 'project1')

    def test_quota_update_nonexistent(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
            db.quota_update, self.ctxt, 'project1', 'resource1', 42)

    def test_quota_get_nonexistent(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
            db.quota_get, self.ctxt, 'project1', 'resource1')

    def test_quota_reserve_all_resources(self):
        quotas = {}
        deltas = {}
        reservable_resources = {}
        for i, resource in enumerate(resources):
            if isinstance(resource, ReservableResource):
                quotas[resource.name] = db.quota_create(self.ctxt, 'project1',
                                                        resource.name, 100)
                deltas[resource.name] = i
                reservable_resources[resource.name] = resource

        usages = {'instances': 3, 'cores': 6, 'ram': 9}
        instances = []
        for i in range(3):
            instances.append(db.instance_create(self.ctxt,
                             {'vcpus': 2, 'memory_mb': 3,
                             'project_id': 'project1'}))

        usages['fixed_ips'] = 2
        network = db.network_create_safe(self.ctxt, {})
        for i in range(2):
            address = '192.168.0.%d' % i
            ip = db.fixed_ip_create(self.ctxt, {'project_id': 'project1',
                                                'address': address,
                                                'network_id': network['id']})
            db.fixed_ip_associate(self.ctxt, address,
                                  instances[0].uuid, network['id'])

        usages['floating_ips'] = 5
        for i in range(5):
            db.floating_ip_create(self.ctxt, {'project_id': 'project1'})

        usages['security_groups'] = 3
        for i in range(3):
            db.security_group_create(self.ctxt, {'project_id': 'project1'})

        reservations_uuids = db.quota_reserve(self.ctxt, reservable_resources,
                                              quotas, quotas, deltas, None,
                                              None, None, 'project1')
        resources_names = reservable_resources.keys()
        for reservation_uuid in reservations_uuids:
            reservation = db.reservation_get(self.ctxt, reservation_uuid)
            usage = db.quota_usage_get(self.ctxt, 'project1',
                                       reservation.resource)
            self.assertEqual(usage.in_use, usages[reservation.resource],
                             'Resource: %s' % reservation.resource)
            self.assertEqual(usage.reserved, deltas[reservation.resource])
            self.assertIn(reservation.resource, resources_names)
            resources_names.remove(reservation.resource)
        self.assertEqual(len(resources_names), 0)

    def test_quota_destroy_all_by_project(self):
        reservations = _quota_reserve(self.ctxt, 'project1', 'user1')
        db.quota_destroy_all_by_project(self.ctxt, 'project1')
        self.assertEqual(db.quota_get_all_by_project(self.ctxt, 'project1'),
                            {'project_id': 'project1'})
        self.assertEqual(db.quota_usage_get_all_by_project(
                            self.ctxt, 'project1'),
                            {'project_id': 'project1'})
        for r in reservations:
            self.assertRaises(exception.ReservationNotFound,
                            db.reservation_get, self.ctxt, r)

    def test_quota_destroy_all_by_project_and_user(self):
        reservations = _quota_reserve(self.ctxt, 'project1', 'user1')
        db.quota_destroy_all_by_project_and_user(self.ctxt, 'project1',
                                                 'user1')
        self.assertEqual(db.quota_get_all_by_project_and_user(self.ctxt,
                            'project1', 'user1'),
                            {'project_id': 'project1',
                             'user_id': 'user1',
                             'resource0': 0,
                             'resource1': 1,
                             'resource2': 2})
        self.assertEqual(db.quota_usage_get_all_by_project_and_user(
                            self.ctxt, 'project1', 'user1'),
                            {'project_id': 'project1',
                             'user_id': 'user1'})
        for r in reservations:
            self.assertRaises(exception.ReservationNotFound,
                            db.reservation_get, self.ctxt, r)

    def test_quota_usage_get_nonexistent(self):
        self.assertRaises(exception.QuotaUsageNotFound, db.quota_usage_get,
            self.ctxt, 'p1', 'nonexitent_resource')

    def test_quota_usage_get(self):
        _quota_reserve(self.ctxt, 'p1', 'u1')
        quota_usage = db.quota_usage_get(self.ctxt, 'p1', 'resource0')
        expected = {'resource': 'resource0', 'project_id': 'p1',
                    'in_use': 0, 'reserved': 0, 'total': 0}
        for key, value in expected.iteritems():
            self.assertEqual(value, quota_usage[key])

    def test_quota_usage_get_all_by_project(self):
        _quota_reserve(self.ctxt, 'p1', 'u1')
        expected = {'project_id': 'p1',
                    'resource0': {'in_use': 0, 'reserved': 0},
                    'resource1': {'in_use': 1, 'reserved': 1},
                    'resource2': {'in_use': 2, 'reserved': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project(
                         self.ctxt, 'p1'))

    def test_quota_usage_get_all_by_project_and_user(self):
        _quota_reserve(self.ctxt, 'p1', 'u1')
        expected = {'project_id': 'p1',
                    'user_id': 'u1',
                    'resource0': {'in_use': 0, 'reserved': 0},
                    'resource1': {'in_use': 1, 'reserved': 1},
                    'resource2': {'in_use': 2, 'reserved': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project_and_user(
                         self.ctxt, 'p1', 'u1'))

    def test_quota_usage_update_nonexistent(self):
        self.assertRaises(exception.QuotaUsageNotFound, db.quota_usage_update,
            self.ctxt, 'p1', 'u1', 'resource', in_use=42)

    def test_quota_usage_update(self):
        _quota_reserve(self.ctxt, 'p1', 'u1')
        db.quota_usage_update(self.ctxt, 'p1', 'u1', 'resource0', in_use=42,
                              reserved=43)
        quota_usage = db.quota_usage_get(self.ctxt, 'p1', 'resource0', 'u1')
        expected = {'resource': 'resource0', 'project_id': 'p1',
                    'user_id': 'u1', 'in_use': 42, 'reserved': 43, 'total': 85}
        for key, value in expected.iteritems():
            self.assertEqual(value, quota_usage[key])

    def test_quota_create_exists(self):
        db.quota_create(self.ctxt, 'project1', 'resource1', 41)
        self.assertRaises(exception.QuotaExists, db.quota_create, self.ctxt,
                          'project1', 'resource1', 42)


class QuotaClassTestCase(test.TestCase, ModelsObjectComparatorMixin):

    def setUp(self):
        super(QuotaClassTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def test_quota_class_get_default(self):
        params = {
            'test_resource1': '10',
            'test_resource2': '20',
            'test_resource3': '30',
        }
        for res, limit in params.items():
            db.quota_class_create(self.ctxt, 'default', res, limit)

        defaults = db.quota_class_get_default(self.ctxt)
        self.assertEqual(defaults, dict(class_name='default',
                                        test_resource1=10,
                                        test_resource2=20,
                                        test_resource3=30))

    def test_quota_class_create(self):
        qc = db.quota_class_create(self.ctxt, 'class name', 'resource', 42)
        self.assertEqual(qc.class_name, 'class name')
        self.assertEqual(qc.resource, 'resource')
        self.assertEqual(qc.hard_limit, 42)

    def test_quota_class_get(self):
        qc = db.quota_class_create(self.ctxt, 'class name', 'resource', 42)
        qc_db = db.quota_class_get(self.ctxt, 'class name', 'resource')
        self._assertEqualObjects(qc, qc_db)

    def test_quota_class_get_nonexistent(self):
        self.assertRaises(exception.QuotaClassNotFound, db.quota_class_get,
                                self.ctxt, 'nonexistent', 'resource')

    def test_quota_class_get_all_by_name(self):
        for i in range(3):
            for j in range(3):
                db.quota_class_create(self.ctxt, 'class%d' % i,
                                                'resource%d' % j, j)
        for i in range(3):
            classes = db.quota_class_get_all_by_name(self.ctxt, 'class%d' % i)
            self.assertEqual(classes, {'class_name': 'class%d' % i,
                            'resource0': 0, 'resource1': 1, 'resource2': 2})

    def test_quota_class_update(self):
        db.quota_class_create(self.ctxt, 'class name', 'resource', 42)
        db.quota_class_update(self.ctxt, 'class name', 'resource', 43)
        self.assertEqual(db.quota_class_get(self.ctxt, 'class name',
                                    'resource').hard_limit, 43)

    def test_quota_class_update_nonexistent(self):
        self.assertRaises(exception.QuotaClassNotFound, db.quota_class_update,
                                self.ctxt, 'class name', 'resource', 42)


class S3ImageTestCase(test.TestCase):

    def setUp(self):
        super(S3ImageTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.values = [uuidutils.generate_uuid() for i in xrange(3)]
        self.images = [db.s3_image_create(self.ctxt, uuid)
                                          for uuid in self.values]

    def test_s3_image_create(self):
        for ref in self.images:
            self.assertTrue(uuidutils.is_uuid_like(ref.uuid))
        self.assertEqual(sorted(self.values),
                         sorted([ref.uuid for ref in self.images]))

    def test_s3_image_get_by_uuid(self):
        for uuid in self.values:
            ref = db.s3_image_get_by_uuid(self.ctxt, uuid)
            self.assertTrue(uuidutils.is_uuid_like(ref.uuid))
            self.assertEqual(uuid, ref.uuid)

    def test_s3_image_get(self):
        self.assertEqual(sorted(self.values),
                         sorted([db.s3_image_get(self.ctxt, ref.id).uuid
                         for ref in self.images]))

    def test_s3_image_get_not_found(self):
        self.assertRaises(exception.ImageNotFound, db.s3_image_get, self.ctxt,
                          100500)

    def test_s3_image_get_by_uuid_not_found(self):
        self.assertRaises(exception.ImageNotFound, db.s3_image_get_by_uuid,
                          self.ctxt, uuidutils.generate_uuid())


class ComputeNodeTestCase(test.TestCase, ModelsObjectComparatorMixin):

    _ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at', 'updated_at']

    def setUp(self):
        super(ComputeNodeTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.service_dict = dict(host='host1', binary='binary1',
                            topic='compute', report_count=1,
                            disabled=False)
        self.service = db.service_create(self.ctxt, self.service_dict)
        self.compute_node_dict = dict(vcpus=2, memory_mb=1024, local_gb=2048,
                                 vcpus_used=0, memory_mb_used=0,
                                 local_gb_used=0, free_ram_mb=1024,
                                 free_disk_gb=2048, hypervisor_type="xen",
                                 hypervisor_version=1, cpu_info="",
                                 running_vms=0, current_workload=0,
                                 service_id=self.service['id'],
                                 disk_available_least=100,
                                 hypervisor_hostname='abracadabra104')
        # add some random stats
        self.stats = dict(num_instances=3, num_proj_12345=2,
                     num_proj_23456=2, num_vm_building=3)
        self.compute_node_dict['stats'] = self.stats
        self.flags(reserved_host_memory_mb=0)
        self.flags(reserved_host_disk_mb=0)
        self.item = db.compute_node_create(self.ctxt, self.compute_node_dict)

    def _stats_as_dict(self, stats):
        d = {}
        for s in stats:
            key = s['key']
            d[key] = s['value']
        return d

    def _stats_equal(self, stats, new_stats):
        for k, v in stats.iteritems():
            self.assertEqual(v, int(new_stats[k]))

    def test_compute_node_create(self):
        self._assertEqualObjects(self.compute_node_dict, self.item,
                                ignored_keys=self._ignored_keys + ['stats'])
        new_stats = self._stats_as_dict(self.item['stats'])
        self._stats_equal(self.stats, new_stats)

    def test_compute_node_get_all(self):
        nodes = db.compute_node_get_all(self.ctxt)
        self.assertEqual(1, len(nodes))
        node = nodes[0]
        self._assertEqualObjects(self.compute_node_dict, node,
                        ignored_keys=self._ignored_keys + ['stats', 'service'])
        new_stats = self._stats_as_dict(node['stats'])
        self._stats_equal(self.stats, new_stats)

    def test_compute_node_get(self):
        compute_node_id = self.item['id']
        node = db.compute_node_get(self.ctxt, compute_node_id)
        self._assertEqualObjects(self.compute_node_dict, node,
                        ignored_keys=self._ignored_keys + ['stats', 'service'])
        new_stats = self._stats_as_dict(node['stats'])
        self._stats_equal(self.stats, new_stats)

    def test_compute_node_update(self):
        compute_node_id = self.item['id']
        stats = self._stats_as_dict(self.item['stats'])
        # change some values:
        stats['num_instances'] = 8
        stats['num_tribbles'] = 1
        values = {
            'vcpus': 4,
            'stats': stats,
        }
        item_updated = db.compute_node_update(self.ctxt, compute_node_id,
                                              values)
        self.assertEqual(4, item_updated['vcpus'])
        new_stats = self._stats_as_dict(item_updated['stats'])
        self._stats_equal(stats, new_stats)

    def test_compute_node_delete(self):
        compute_node_id = self.item['id']
        db.compute_node_delete(self.ctxt, compute_node_id)
        nodes = db.compute_node_get_all(self.ctxt)
        self.assertEqual(len(nodes), 0)

    def test_compute_node_search_by_hypervisor(self):
        nodes_created = []
        new_service = copy.copy(self.service_dict)
        for i in xrange(3):
            new_service['binary'] += str(i)
            new_service['topic'] += str(i)
            service = db.service_create(self.ctxt, new_service)
            self.compute_node_dict['service_id'] = service['id']
            self.compute_node_dict['hypervisor_hostname'] = 'testhost' + str(i)
            self.compute_node_dict['stats'] = self.stats
            node = db.compute_node_create(self.ctxt, self.compute_node_dict)
            nodes_created.append(node)
        nodes = db.compute_node_search_by_hypervisor(self.ctxt, 'host')
        self.assertEqual(3, len(nodes))
        self._assertEqualListsOfObjects(nodes_created, nodes,
                        ignored_keys=self._ignored_keys + ['stats', 'service'])

    def test_compute_node_statistics(self):
        stats = db.compute_node_statistics(self.ctxt)
        self.assertEqual(stats.pop('count'), 1)
        for k, v in stats.iteritems():
            self.assertEqual(v, self.item[k])

    def test_compute_node_not_found(self):
        self.assertRaises(exception.ComputeHostNotFound, db.compute_node_get,
                          self.ctxt, 100500)

    def test_compute_node_update_always_updates_updated_at(self):
        item_updated = db.compute_node_update(self.ctxt,
                self.item['id'], {})
        self.assertNotEqual(self.item['updated_at'],
                                 item_updated['updated_at'])

    def test_compute_node_update_override_updated_at(self):
        # Update the record once so updated_at is set.
        first = db.compute_node_update(self.ctxt, self.item['id'],
                                       {'free_ram_mb': '12'})
        self.assertIsNotNone(first['updated_at'])

        # Update a second time. Make sure that the updated_at value we send
        # is overridden.
        second = db.compute_node_update(self.ctxt, self.item['id'],
                                        {'updated_at': first.updated_at,
                                         'free_ram_mb': '13'})
        self.assertNotEqual(first['updated_at'], second['updated_at'])

    def test_compute_node_stat_unchanged(self):
        # don't update unchanged stat values:
        stats = self.item['stats']
        stats_updated_at = dict([(stat['key'], stat['updated_at'])
                                  for stat in stats])
        stats_values = self._stats_as_dict(stats)
        new_values = {'stats': stats_values}
        compute_node_id = self.item['id']
        db.compute_node_update(self.ctxt, compute_node_id, new_values)
        updated_node = db.compute_node_get(self.ctxt, compute_node_id)
        updated_stats = updated_node['stats']
        for stat in updated_stats:
            self.assertEqual(stat['updated_at'], stats_updated_at[stat['key']])

    def test_compute_node_stat_prune(self):
        for stat in self.item['stats']:
            if stat['key'] == 'num_instances':
                num_instance_stat = stat
                break

        values = {
            'stats': dict(num_instances=1)
        }
        db.compute_node_update(self.ctxt, self.item['id'], values,
                               prune_stats=True)
        item_updated = db.compute_node_get_all(self.ctxt)[0]
        self.assertEqual(1, len(item_updated['stats']))

        stat = item_updated['stats'][0]
        self.assertEqual(num_instance_stat['id'], stat['id'])
        self.assertEqual(num_instance_stat['key'], stat['key'])
        self.assertEqual(1, int(stat['value']))


class ProviderFwRuleTestCase(test.TestCase, ModelsObjectComparatorMixin):

    def setUp(self):
        super(ProviderFwRuleTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.values = self._get_rule_values()
        self.rules = [db.provider_fw_rule_create(self.ctxt, rule)
                                  for rule in self.values]

    def _get_rule_values(self):
        cidr_samples = ['192.168.0.0/24', '10.1.2.3/32',
                        '2001:4f8:3:ba::/64',
                        '2001:4f8:3:ba:2e0:81ff:fe22:d1f1/128']
        values = []
        for i in xrange(len(cidr_samples)):
            rule = {}
            rule['protocol'] = 'foo' + str(i)
            rule['from_port'] = 9999 + i
            rule['to_port'] = 9898 + i
            rule['cidr'] = cidr_samples[i]
            values.append(rule)
        return values

    def test_provider_fw_rule_create(self):
        ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at',
                        'updated_at']
        for i, rule in enumerate(self.values):
            self._assertEqualObjects(self.rules[i], rule,
                                     ignored_keys=ignored_keys)

    def test_provider_fw_rule_get_all(self):
        self._assertEqualListsOfObjects(self.rules,
                                        db.provider_fw_rule_get_all(self.ctxt))

    def test_provider_fw_rule_destroy(self):
        for rule in self.rules:
            db.provider_fw_rule_destroy(self.ctxt, rule.id)
        self.assertEqual([], db.provider_fw_rule_get_all(self.ctxt))


class CertificateTestCase(test.TestCase, ModelsObjectComparatorMixin):

    def setUp(self):
        super(CertificateTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.created = self._certificates_create()

    def _get_certs_values(self):
        base_values = {
            'user_id': 'user',
            'project_id': 'project',
            'file_name': 'filename'
        }
        return [dict((k, v + str(x)) for k, v in base_values.iteritems())
                      for x in xrange(1, 4)]

    def _certificates_create(self):
        return [db.certificate_create(self.ctxt, cert)
                                      for cert in self._get_certs_values()]

    def test_certificate_create(self):
        ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at',
                        'updated_at']
        for i, cert in enumerate(self._get_certs_values()):
            self._assertEqualObjects(self.created[i], cert,
                                     ignored_keys=ignored_keys)

    def test_certificate_get_all_by_project(self):
        cert = db.certificate_get_all_by_project(self.ctxt,
                                                 self.created[1].project_id)
        self._assertEqualObjects(self.created[1], cert[0])

    def test_certificate_get_all_by_user(self):
        cert = db.certificate_get_all_by_user(self.ctxt,
                                              self.created[1].user_id)
        self._assertEqualObjects(self.created[1], cert[0])

    def test_certificate_get_all_by_user_and_project(self):
        cert = db.certificate_get_all_by_user_and_project(self.ctxt,
                           self.created[1].user_id, self.created[1].project_id)
        self._assertEqualObjects(self.created[1], cert[0])


class ConsoleTestCase(test.TestCase, ModelsObjectComparatorMixin):

    def setUp(self):
        super(ConsoleTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        pools_data = [
            {'address': '192.168.10.10',
             'username': 'user1',
             'password': 'passwd1',
             'console_type': 'type1',
             'public_hostname': 'public_host1',
             'host': 'host1',
             'compute_host': 'compute_host1',
            },
            {'address': '192.168.10.11',
             'username': 'user2',
             'password': 'passwd2',
             'console_type': 'type2',
             'public_hostname': 'public_host2',
             'host': 'host2',
             'compute_host': 'compute_host2',
            },
        ]
        console_pools = [db.console_pool_create(self.ctxt, val)
                         for val in pools_data]
        instance_uuid = uuidutils.generate_uuid()
        self.console_data = [dict([('instance_name', 'name' + str(x)),
                                  ('instance_uuid', instance_uuid),
                                  ('password', 'pass' + str(x)),
                                  ('port', 7878 + x),
                                  ('pool_id', console_pools[x]['id'])])
                             for x in xrange(len(pools_data))]
        self.consoles = [db.console_create(self.ctxt, val)
                         for val in self.console_data]

    def test_console_create(self):
        ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at',
                        'updated_at']
        for console in self.consoles:
            self.assertIsNotNone(console['id'])
        self._assertEqualListsOfObjects(self.console_data, self.consoles,
                                        ignored_keys=ignored_keys)

    def test_console_get_by_id(self):
        console = self.consoles[0]
        console_get = db.console_get(self.ctxt, console['id'])
        self._assertEqualObjects(console, console_get,
                                 ignored_keys=['pool'])

    def test_console_get_by_id_uuid(self):
        console = self.consoles[0]
        console_get = db.console_get(self.ctxt, console['id'],
                                     console['instance_uuid'])
        self._assertEqualObjects(console, console_get,
                                 ignored_keys=['pool'])

    def test_console_get_by_pool_instance(self):
        console = self.consoles[0]
        console_get = db.console_get_by_pool_instance(self.ctxt,
                            console['pool_id'], console['instance_uuid'])
        self._assertEqualObjects(console, console_get,
                                 ignored_keys=['pool'])

    def test_console_get_all_by_instance(self):
        instance_uuid = self.consoles[0]['instance_uuid']
        consoles_get = db.console_get_all_by_instance(self.ctxt, instance_uuid)
        self._assertEqualListsOfObjects(self.consoles, consoles_get)

    def test_console_get_all_by_instance_empty(self):
        consoles_get = db.console_get_all_by_instance(self.ctxt,
                                                uuidutils.generate_uuid())
        self.assertEqual(consoles_get, [])

    def test_console_delete(self):
        console_id = self.consoles[0]['id']
        db.console_delete(self.ctxt, console_id)
        self.assertRaises(exception.ConsoleNotFound, db.console_get,
                          self.ctxt, console_id)

    def test_console_get_by_pool_instance_not_found(self):
        self.assertRaises(exception.ConsoleNotFoundInPoolForInstance,
                          db.console_get_by_pool_instance, self.ctxt,
                          self.consoles[0]['pool_id'],
                          uuidutils.generate_uuid())

    def test_console_get_not_found(self):
        self.assertRaises(exception.ConsoleNotFound, db.console_get,
                          self.ctxt, 100500)

    def test_console_get_not_found_instance(self):
        self.assertRaises(exception.ConsoleNotFoundForInstance, db.console_get,
                          self.ctxt, self.consoles[0]['id'],
                          uuidutils.generate_uuid())


class CellTestCase(test.TestCase, ModelsObjectComparatorMixin):

    _ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at', 'updated_at']

    def setUp(self):
        super(CellTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _get_cell_base_values(self):
        return {
            'name': 'myname',
            'api_url': 'apiurl',
            'transport_url': 'transporturl',
            'weight_offset': 0.5,
            'weight_scale': 1.5,
            'is_parent': True,
        }

    def _cell_value_modify(self, value, step):
        if isinstance(value, str):
            return value + str(step)
        elif isinstance(value, float):
            return value + step + 0.6
        elif isinstance(value, bool):
            return bool(step % 2)
        elif isinstance(value, int):
            return value + step

    def _create_cells(self):
        test_values = []
        for x in xrange(1, 4):
            modified_val = dict([(k, self._cell_value_modify(v, x))
                        for k, v in self._get_cell_base_values().iteritems()])
            db.cell_create(self.ctxt, modified_val)
            test_values.append(modified_val)
        return test_values

    def test_cell_create(self):
        cell = db.cell_create(self.ctxt, self._get_cell_base_values())
        self.assertFalse(cell['id'] is None)
        self._assertEqualObjects(cell, self._get_cell_base_values(),
                                 ignored_keys=self._ignored_keys)

    def test_cell_update(self):
        db.cell_create(self.ctxt, self._get_cell_base_values())
        new_values = {
            'api_url': 'apiurl1',
            'transport_url': 'transporturl1',
            'weight_offset': 0.6,
            'weight_scale': 1.6,
            'is_parent': False,
        }
        test_cellname = self._get_cell_base_values()['name']
        db.cell_update(self.ctxt, test_cellname, new_values)
        updated_cell = db.cell_get(self.ctxt, test_cellname)
        self._assertEqualObjects(updated_cell, new_values,
                                 ignored_keys=self._ignored_keys + ['name'])

    def test_cell_delete(self):
        new_cells = self._create_cells()
        for cell in new_cells:
            test_cellname = cell['name']
            db.cell_delete(self.ctxt, test_cellname)
            self.assertRaises(exception.CellNotFound, db.cell_get, self.ctxt,
                              test_cellname)

    def test_cell_get(self):
        new_cells = self._create_cells()
        for cell in new_cells:
            cell_get = db.cell_get(self.ctxt, cell['name'])
            self._assertEqualObjects(cell_get, cell,
                                     ignored_keys=self._ignored_keys)

    def test_cell_get_all(self):
        new_cells = self._create_cells()
        cells = db.cell_get_all(self.ctxt)
        self.assertEqual(len(new_cells), len(cells))
        cells_byname = dict([(newcell['name'],
                              newcell) for newcell in new_cells])
        for cell in cells:
            self._assertEqualObjects(cell, cells_byname[cell['name']],
                                     self._ignored_keys)

    def test_cell_get_not_found(self):
        self._create_cells()
        self.assertRaises(exception.CellNotFound, db.cell_get, self.ctxt,
                          'cellnotinbase')

    def test_cell_update_not_found(self):
        self._create_cells()
        self.assertRaises(exception.CellNotFound, db.cell_update, self.ctxt,
                          'cellnotinbase', self._get_cell_base_values())

    def test_cell_create_exists(self):
        db.cell_create(self.ctxt, self._get_cell_base_values())
        self.assertRaises(exception.CellExists, db.cell_create,
                          self.ctxt, self._get_cell_base_values())


class ConsolePoolTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(ConsolePoolTestCase, self).setUp()

        self.ctxt = context.get_admin_context()
        self.test_console_pool_1 = {
            'address': '192.168.2.10',
            'username': 'user_1',
            'password': 'secret_123',
            'console_type': 'type_1',
            'public_hostname': 'public_hostname_123',
            'host': 'localhost',
            'compute_host': '127.0.0.1',
        }
        self.test_console_pool_2 = {
            'address': '192.168.2.11',
            'username': 'user_2',
            'password': 'secret_1234',
            'console_type': 'type_2',
            'public_hostname': 'public_hostname_1234',
            'host': '127.0.0.1',
            'compute_host': 'localhost',
        }
        self.test_console_pool_3 = {
            'address': '192.168.2.12',
            'username': 'user_3',
            'password': 'secret_12345',
            'console_type': 'type_2',
            'public_hostname': 'public_hostname_12345',
            'host': '127.0.0.1',
            'compute_host': '192.168.1.1',
        }

    def test_console_pool_create(self):
        console_pool = db.console_pool_create(
            self.ctxt, self.test_console_pool_1)
        self.assertTrue(console_pool.get('id') is not None)
        ignored_keys = ['deleted', 'created_at', 'updated_at',
                        'deleted_at', 'id']
        self._assertEqualObjects(
            console_pool, self.test_console_pool_1, ignored_keys)

    def test_console_pool_create_duplicate(self):
        db.console_pool_create(self.ctxt, self.test_console_pool_1)
        self.assertRaises(exception.ConsolePoolExists, db.console_pool_create,
                          self.ctxt, self.test_console_pool_1)

    def test_console_pool_get_by_host_type(self):
        params = [
            self.test_console_pool_1,
            self.test_console_pool_2,
        ]

        for p in params:
            db.console_pool_create(self.ctxt, p)

        ignored_keys = ['deleted', 'created_at', 'updated_at',
                        'deleted_at', 'id', 'consoles']

        cp = self.test_console_pool_1
        db_cp = db.console_pool_get_by_host_type(
            self.ctxt, cp['compute_host'], cp['host'], cp['console_type']
        )
        self._assertEqualObjects(cp, db_cp, ignored_keys)

    def test_console_pool_get_by_host_type_no_resuls(self):
        self.assertRaises(
            exception.ConsolePoolNotFoundForHostType,
            db.console_pool_get_by_host_type, self.ctxt, 'compute_host',
            'host', 'console_type')

    def test_console_pool_get_all_by_host_type(self):
        params = [
            self.test_console_pool_1,
            self.test_console_pool_2,
            self.test_console_pool_3,
        ]
        for p in params:
            db.console_pool_create(self.ctxt, p)
        ignored_keys = ['deleted', 'created_at', 'updated_at',
                        'deleted_at', 'id', 'consoles']

        cp = self.test_console_pool_2
        db_cp = db.console_pool_get_all_by_host_type(
            self.ctxt, cp['host'], cp['console_type'])

        self._assertEqualListsOfObjects(
            db_cp, [self.test_console_pool_2, self.test_console_pool_3],
            ignored_keys)

    def test_console_pool_get_all_by_host_type_no_results(self):
        res = db.console_pool_get_all_by_host_type(
            self.ctxt, 'cp_host', 'cp_console_type')
        self.assertEqual([], res)


class DnsdomainTestCase(test.TestCase):

    def setUp(self):
        super(DnsdomainTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.domain = 'test.domain'
        self.testzone = 'testzone'
        self.project = 'fake'

    def test_dnsdomain_register_for_zone(self):
        db.dnsdomain_register_for_zone(self.ctxt, self.domain, self.testzone)
        domain = db.dnsdomain_get(self.ctxt, self.domain)
        self.assertEqual(domain['domain'], self.domain)
        self.assertEqual(domain['availability_zone'], self.testzone)
        self.assertEqual(domain['scope'], 'private')

    def test_dnsdomain_register_for_project(self):
        db.dnsdomain_register_for_project(self.ctxt, self.domain, self.project)
        domain = db.dnsdomain_get(self.ctxt, self.domain)
        self.assertEqual(domain['domain'], self.domain)
        self.assertEqual(domain['project_id'], self.project)
        self.assertEqual(domain['scope'], 'public')

    def test_dnsdomain_list(self):
        d_list = ['test.domain.one', 'test.domain.two']
        db.dnsdomain_register_for_zone(self.ctxt, d_list[0], self.testzone)
        db.dnsdomain_register_for_project(self.ctxt, d_list[1], self.project)
        db_list = db.dnsdomain_list(self.ctxt)
        self.assertEqual(sorted(d_list), sorted(db_list))

    def test_dnsdomain_unregister(self):
        db.dnsdomain_register_for_zone(self.ctxt, self.domain, self.testzone)
        db.dnsdomain_unregister(self.ctxt, self.domain)
        domain = db.dnsdomain_get(self.ctxt, self.domain)
        self.assertIsNone(domain)


class BwUsageTestCase(test.TestCase, ModelsObjectComparatorMixin):

    _ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at', 'updated_at']

    def setUp(self):
        super(BwUsageTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.useFixture(test.TimeOverride())

    def test_bw_usage_get_by_uuids(self):
        now = timeutils.utcnow()
        start_period = now - datetime.timedelta(seconds=10)
        uuid3_refreshed = now - datetime.timedelta(seconds=5)

        expected_bw_usages = [{'uuid': 'fake_uuid1',
                               'mac': 'fake_mac1',
                               'start_period': start_period,
                               'bw_in': 100,
                               'bw_out': 200,
                               'last_ctr_in': 12345,
                               'last_ctr_out': 67890,
                               'last_refreshed': now},
                              {'uuid': 'fake_uuid2',
                               'mac': 'fake_mac2',
                               'start_period': start_period,
                               'bw_in': 200,
                               'bw_out': 300,
                               'last_ctr_in': 22345,
                               'last_ctr_out': 77890,
                               'last_refreshed': now},
                              {'uuid': 'fake_uuid3',
                               'mac': 'fake_mac3',
                               'start_period': start_period,
                               'bw_in': 400,
                               'bw_out': 500,
                               'last_ctr_in': 32345,
                               'last_ctr_out': 87890,
                               'last_refreshed': uuid3_refreshed}]

        bw_usages = db.bw_usage_get_by_uuids(self.ctxt,
                ['fake_uuid1', 'fake_uuid2'], start_period)
        # No matches
        self.assertEqual(len(bw_usages), 0)

        # Add 3 entries
        db.bw_usage_update(self.ctxt, 'fake_uuid1',
                'fake_mac1', start_period,
                100, 200, 12345, 67890)
        db.bw_usage_update(self.ctxt, 'fake_uuid2',
                'fake_mac2', start_period,
                100, 200, 42, 42)
        # Test explicit refreshed time
        db.bw_usage_update(self.ctxt, 'fake_uuid3',
                'fake_mac3', start_period,
                400, 500, 32345, 87890,
                last_refreshed=uuid3_refreshed)
        # Update 2nd entry
        db.bw_usage_update(self.ctxt, 'fake_uuid2',
                'fake_mac2', start_period,
                200, 300, 22345, 77890)

        bw_usages = db.bw_usage_get_by_uuids(self.ctxt,
                ['fake_uuid1', 'fake_uuid2', 'fake_uuid3'], start_period)
        self.assertEqual(len(bw_usages), 3)
        for i, expected in enumerate(expected_bw_usages):
            self._assertEqualObjects(bw_usages[i], expected,
                                     ignored_keys=self._ignored_keys)

    def test_bw_usage_get(self):
        now = timeutils.utcnow()
        start_period = now - datetime.timedelta(seconds=10)

        expected_bw_usage = {'uuid': 'fake_uuid1',
                             'mac': 'fake_mac1',
                             'start_period': start_period,
                             'bw_in': 100,
                             'bw_out': 200,
                             'last_ctr_in': 12345,
                             'last_ctr_out': 67890,
                             'last_refreshed': now}

        bw_usage = db.bw_usage_get(self.ctxt, 'fake_uuid1', start_period,
                                   'fake_mac1')
        self.assertIsNone(bw_usage)

        db.bw_usage_update(self.ctxt, 'fake_uuid1',
                'fake_mac1', start_period,
                100, 200, 12345, 67890)

        bw_usage = db.bw_usage_get(self.ctxt, 'fake_uuid1', start_period,
                                   'fake_mac1')
        self._assertEqualObjects(bw_usage, expected_bw_usage,
                                 ignored_keys=self._ignored_keys)


class Ec2TestCase(test.TestCase):

    def setUp(self):
        super(Ec2TestCase, self).setUp()
        self.ctxt = context.RequestContext('fake_user', 'fake_project')

    def test_ec2_ids_not_found_are_printable(self):
        def check_exc_format(method, value):
            try:
                method(self.ctxt, value)
            except exception.NotFound as exc:
                self.assertTrue(unicode(value) in unicode(exc))

        check_exc_format(db.get_ec2_volume_id_by_uuid, 'fake')
        check_exc_format(db.get_volume_uuid_by_ec2_id, 123456)
        check_exc_format(db.get_ec2_snapshot_id_by_uuid, 'fake')
        check_exc_format(db.get_snapshot_uuid_by_ec2_id, 123456)
        check_exc_format(db.get_ec2_instance_id_by_uuid, 'fake')
        check_exc_format(db.get_instance_uuid_by_ec2_id, 123456)

    def test_ec2_volume_create(self):
        vol = db.ec2_volume_create(self.ctxt, 'fake-uuid')
        self.assertIsNotNone(vol['id'])
        self.assertEqual(vol['uuid'], 'fake-uuid')

    def test_get_ec2_volume_id_by_uuid(self):
        vol = db.ec2_volume_create(self.ctxt, 'fake-uuid')
        vol_id = db.get_ec2_volume_id_by_uuid(self.ctxt, 'fake-uuid')
        self.assertEqual(vol['id'], vol_id)

    def test_get_volume_uuid_by_ec2_id(self):
        vol = db.ec2_volume_create(self.ctxt, 'fake-uuid')
        vol_uuid = db.get_volume_uuid_by_ec2_id(self.ctxt, vol['id'])
        self.assertEqual(vol_uuid, 'fake-uuid')

    def test_get_ec2_volume_id_by_uuid_not_found(self):
        self.assertRaises(exception.VolumeNotFound,
                          db.get_ec2_volume_id_by_uuid,
                          self.ctxt, 'uuid-not-present')

    def test_get_volume_uuid_by_ec2_id_not_found(self):
        self.assertRaises(exception.VolumeNotFound,
                          db.get_volume_uuid_by_ec2_id,
                          self.ctxt, 100500)

    def test_ec2_snapshot_create(self):
        snap = db.ec2_snapshot_create(self.ctxt, 'fake-uuid')
        self.assertIsNotNone(snap['id'])
        self.assertEqual(snap['uuid'], 'fake-uuid')

    def test_get_ec2_snapshot_id_by_uuid(self):
        snap = db.ec2_snapshot_create(self.ctxt, 'fake-uuid')
        snap_id = db.get_ec2_snapshot_id_by_uuid(self.ctxt, 'fake-uuid')
        self.assertEqual(snap['id'], snap_id)

    def test_get_snapshot_uuid_by_ec2_id(self):
        snap = db.ec2_snapshot_create(self.ctxt, 'fake-uuid')
        snap_uuid = db.get_snapshot_uuid_by_ec2_id(self.ctxt, snap['id'])
        self.assertEqual(snap_uuid, 'fake-uuid')

    def test_get_ec2_snapshot_id_by_uuid_not_found(self):
        self.assertRaises(exception.SnapshotNotFound,
                          db.get_ec2_snapshot_id_by_uuid,
                          self.ctxt, 'uuid-not-present')

    def test_get_snapshot_uuid_by_ec2_id_not_found(self):
        self.assertRaises(exception.SnapshotNotFound,
                          db.get_snapshot_uuid_by_ec2_id,
                          self.ctxt, 100500)

    def test_ec2_instance_create(self):
        inst = db.ec2_instance_create(self.ctxt, 'fake-uuid')
        self.assertIsNotNone(inst['id'])
        self.assertEqual(inst['uuid'], 'fake-uuid')

    def test_get_ec2_instance_id_by_uuid(self):
        inst = db.ec2_instance_create(self.ctxt, 'fake-uuid')
        inst_id = db.get_ec2_instance_id_by_uuid(self.ctxt, 'fake-uuid')
        self.assertEqual(inst['id'], inst_id)

    def test_get_instance_uuid_by_ec2_id(self):
        inst = db.ec2_instance_create(self.ctxt, 'fake-uuid')
        inst_uuid = db.get_instance_uuid_by_ec2_id(self.ctxt, inst['id'])
        self.assertEqual(inst_uuid, 'fake-uuid')

    def test_get_ec2_instance_id_by_uuid_not_found(self):
        self.assertRaises(exception.InstanceNotFound,
                          db.get_ec2_instance_id_by_uuid,
                          self.ctxt, 'uuid-not-present')

    def test_get_instance_uuid_by_ec2_id_not_found(self):
        self.assertRaises(exception.InstanceNotFound,
                          db.get_instance_uuid_by_ec2_id,
                          self.ctxt, 100500)


class ArchiveTestCase(test.TestCase):

    def setUp(self):
        super(ArchiveTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.engine = get_engine()
        self.conn = self.engine.connect()
        self.instance_id_mappings = db_utils.get_table(self.engine,
                                                       "instance_id_mappings")
        self.shadow_instance_id_mappings = db_utils.get_table(self.engine,
                                                "shadow_instance_id_mappings")
        self.dns_domains = db_utils.get_table(self.engine, "dns_domains")
        self.shadow_dns_domains = db_utils.get_table(self.engine,
                                                     "shadow_dns_domains")
        self.consoles = db_utils.get_table(self.engine, "consoles")
        self.console_pools = db_utils.get_table(self.engine, "console_pools")
        self.shadow_consoles = db_utils.get_table(self.engine,
                                                  "shadow_consoles")
        self.shadow_console_pools = db_utils.get_table(self.engine,
                                                       "shadow_console_pools")
        self.instances = db_utils.get_table(self.engine, "instances")
        self.shadow_instances = db_utils.get_table(self.engine,
                                                   "shadow_instances")
        self.uuidstrs = []
        for unused in range(6):
            self.uuidstrs.append(stdlib_uuid.uuid4().hex)
        self.ids = []
        self.id_tablenames_to_cleanup = set(["console_pools", "consoles"])
        self.uuid_tablenames_to_cleanup = set(["instance_id_mappings",
                                               "instances"])
        self.domain_tablenames_to_cleanup = set(["dns_domains"])

    def tearDown(self):
        super(ArchiveTestCase, self).tearDown()
        for tablename in self.id_tablenames_to_cleanup:
            for name in [tablename, "shadow_" + tablename]:
                table = db_utils.get_table(self.engine, name)
                del_statement = table.delete(table.c.id.in_(self.ids))
                self.conn.execute(del_statement)
        for tablename in self.uuid_tablenames_to_cleanup:
            for name in [tablename, "shadow_" + tablename]:
                table = db_utils.get_table(self.engine, name)
                del_statement = table.delete(table.c.uuid.in_(self.uuidstrs))
                self.conn.execute(del_statement)
        for tablename in self.domain_tablenames_to_cleanup:
            for name in [tablename, "shadow_" + tablename]:
                table = db_utils.get_table(self.engine, name)
                del_statement = table.delete(table.c.domain.in_(self.uuidstrs))
                self.conn.execute(del_statement)

    def test_shadow_tables(self):
        metadata = MetaData(bind=self.engine)
        metadata.reflect()
        for table_name in metadata.tables:
            if table_name.startswith("shadow_"):
                self.assertIn(table_name[7:], metadata.tables)
                continue
            self.assertTrue(db_utils.check_shadow_table(self.engine,
                                                        table_name))

    def test_archive_deleted_rows(self):
        # Add 6 rows to table
        for uuidstr in self.uuidstrs:
            ins_stmt = self.instance_id_mappings.insert().values(uuid=uuidstr)
            self.conn.execute(ins_stmt)
        # Set 4 to deleted
        update_statement = self.instance_id_mappings.update().\
                where(self.instance_id_mappings.c.uuid.in_(self.uuidstrs[:4]))\
                .values(deleted=1)
        self.conn.execute(update_statement)
        qiim = select([self.instance_id_mappings]).where(self.
                                instance_id_mappings.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qiim).fetchall()
        # Verify we have 6 in main
        self.assertEqual(len(rows), 6)
        qsiim = select([self.shadow_instance_id_mappings]).\
                where(self.shadow_instance_id_mappings.c.uuid.in_(
                                                                self.uuidstrs))
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we have 0 in shadow
        self.assertEqual(len(rows), 0)
        # Archive 2 rows
        db.archive_deleted_rows(self.context, max_rows=2)
        rows = self.conn.execute(qiim).fetchall()
        # Verify we have 4 left in main
        self.assertEqual(len(rows), 4)
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we have 2 in shadow
        self.assertEqual(len(rows), 2)
        # Archive 2 more rows
        db.archive_deleted_rows(self.context, max_rows=2)
        rows = self.conn.execute(qiim).fetchall()
        # Verify we have 2 left in main
        self.assertEqual(len(rows), 2)
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we have 4 in shadow
        self.assertEqual(len(rows), 4)
        # Try to archive more, but there are no deleted rows left.
        db.archive_deleted_rows(self.context, max_rows=2)
        rows = self.conn.execute(qiim).fetchall()
        # Verify we still have 2 left in main
        self.assertEqual(len(rows), 2)
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we still have 4 in shadow
        self.assertEqual(len(rows), 4)

    def test_archive_deleted_rows_for_every_uuid_table(self):
        tablenames = []
        for model_class in models.__dict__.itervalues():
            if hasattr(model_class, "__tablename__"):
                tablenames.append(model_class.__tablename__)
        tablenames.sort()
        for tablename in tablenames:
            ret = self._test_archive_deleted_rows_for_one_uuid_table(tablename)
            if ret == 0:
                self.uuid_tablenames_to_cleanup.add(tablename)

    def _test_archive_deleted_rows_for_one_uuid_table(self, tablename):
        """
        :returns: 0 on success, 1 if no uuid column, 2 if insert failed
        """
        main_table = db_utils.get_table(self.engine, tablename)
        if not hasattr(main_table.c, "uuid"):
            # Not a uuid table, so skip it.
            return 1
        shadow_table = db_utils.get_table(self.engine, "shadow_" + tablename)
        # Add 6 rows to table
        for uuidstr in self.uuidstrs:
            ins_stmt = main_table.insert().values(uuid=uuidstr)
            try:
                self.conn.execute(ins_stmt)
            except IntegrityError:
                # This table has constraints that require a table-specific
                # insert, so skip it.
                return 2
        # Set 4 to deleted
        update_statement = main_table.update().\
                where(main_table.c.uuid.in_(self.uuidstrs[:4]))\
                .values(deleted=1)
        self.conn.execute(update_statement)
        qmt = select([main_table]).where(main_table.c.uuid.in_(
                                             self.uuidstrs))
        rows = self.conn.execute(qmt).fetchall()
        # Verify we have 6 in main
        self.assertEqual(len(rows), 6)
        qst = select([shadow_table]).\
                where(shadow_table.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qst).fetchall()
        # Verify we have 0 in shadow
        self.assertEqual(len(rows), 0)
        # Archive 2 rows
        db.archive_deleted_rows_for_table(self.context, tablename, max_rows=2)
        # Verify we have 4 left in main
        rows = self.conn.execute(qmt).fetchall()
        self.assertEqual(len(rows), 4)
        # Verify we have 2 in shadow
        rows = self.conn.execute(qst).fetchall()
        self.assertEqual(len(rows), 2)
        # Archive 2 more rows
        db.archive_deleted_rows_for_table(self.context, tablename, max_rows=2)
        # Verify we have 2 left in main
        rows = self.conn.execute(qmt).fetchall()
        self.assertEqual(len(rows), 2)
        # Verify we have 4 in shadow
        rows = self.conn.execute(qst).fetchall()
        self.assertEqual(len(rows), 4)
        # Try to archive more, but there are no deleted rows left.
        db.archive_deleted_rows_for_table(self.context, tablename, max_rows=2)
        # Verify we still have 2 left in main
        rows = self.conn.execute(qmt).fetchall()
        self.assertEqual(len(rows), 2)
        # Verify we still have 4 in shadow
        rows = self.conn.execute(qst).fetchall()
        self.assertEqual(len(rows), 4)
        return 0

    def test_archive_deleted_rows_no_id_column(self):
        uuidstr0 = self.uuidstrs[0]
        ins_stmt = self.dns_domains.insert().values(domain=uuidstr0)
        self.conn.execute(ins_stmt)
        update_statement = self.dns_domains.update().\
                           where(self.dns_domains.c.domain == uuidstr0).\
                           values(deleted=1)
        self.conn.execute(update_statement)
        qdd = select([self.dns_domains], self.dns_domains.c.domain ==
                                            uuidstr0)
        rows = self.conn.execute(qdd).fetchall()
        self.assertEqual(len(rows), 1)
        qsdd = select([self.shadow_dns_domains],
                        self.shadow_dns_domains.c.domain == uuidstr0)
        rows = self.conn.execute(qsdd).fetchall()
        self.assertEqual(len(rows), 0)
        db.archive_deleted_rows(self.context, max_rows=1)
        rows = self.conn.execute(qdd).fetchall()
        self.assertEqual(len(rows), 0)
        rows = self.conn.execute(qsdd).fetchall()
        self.assertEqual(len(rows), 1)

    def test_archive_deleted_rows_fk_constraint(self):
        # consoles.pool_id depends on console_pools.id
        # SQLite doesn't enforce foreign key constraints without a pragma.
        dialect = self.engine.url.get_dialect()
        if dialect == sqlite.dialect:
            # We're seeing issues with foreign key support in SQLite 3.6.20
            # SQLAlchemy doesn't support it at all with < SQLite 3.6.19
            # It works fine in SQLite 3.7.
            # So return early to skip this test if running SQLite < 3.7
            import sqlite3
            tup = sqlite3.sqlite_version_info
            if tup[0] < 3 or (tup[0] == 3 and tup[1] < 7):
                self.skipTest(
                    'sqlite version too old for reliable SQLA foreign_keys')
            self.conn.execute("PRAGMA foreign_keys = ON")
        ins_stmt = self.console_pools.insert().values(deleted=1)
        result = self.conn.execute(ins_stmt)
        id1 = result.inserted_primary_key[0]
        self.ids.append(id1)
        ins_stmt = self.consoles.insert().values(deleted=1,
                                                         pool_id=id1)
        result = self.conn.execute(ins_stmt)
        id2 = result.inserted_primary_key[0]
        self.ids.append(id2)
        # The first try to archive console_pools should fail, due to FK.
        num = db.archive_deleted_rows_for_table(self.context, "console_pools")
        self.assertEqual(num, 0)
        # Then archiving consoles should work.
        num = db.archive_deleted_rows_for_table(self.context, "consoles")
        self.assertEqual(num, 1)
        # Then archiving console_pools should work.
        num = db.archive_deleted_rows_for_table(self.context, "console_pools")
        self.assertEqual(num, 1)

    def test_archive_deleted_rows_2_tables(self):
        # Add 6 rows to each table
        for uuidstr in self.uuidstrs:
            ins_stmt = self.instance_id_mappings.insert().values(uuid=uuidstr)
            self.conn.execute(ins_stmt)
            ins_stmt2 = self.instances.insert().values(uuid=uuidstr)
            self.conn.execute(ins_stmt2)
        # Set 4 of each to deleted
        update_statement = self.instance_id_mappings.update().\
                where(self.instance_id_mappings.c.uuid.in_(self.uuidstrs[:4]))\
                .values(deleted=1)
        self.conn.execute(update_statement)
        update_statement2 = self.instances.update().\
                where(self.instances.c.uuid.in_(self.uuidstrs[:4]))\
                .values(deleted=1)
        self.conn.execute(update_statement2)
        # Verify we have 6 in each main table
        qiim = select([self.instance_id_mappings]).where(
                         self.instance_id_mappings.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qiim).fetchall()
        self.assertEqual(len(rows), 6)
        qi = select([self.instances]).where(self.instances.c.uuid.in_(
                                             self.uuidstrs))
        rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(rows), 6)
        # Verify we have 0 in each shadow table
        qsiim = select([self.shadow_instance_id_mappings]).\
                where(self.shadow_instance_id_mappings.c.uuid.in_(
                                                            self.uuidstrs))
        rows = self.conn.execute(qsiim).fetchall()
        self.assertEqual(len(rows), 0)
        qsi = select([self.shadow_instances]).\
                where(self.shadow_instances.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(rows), 0)
        # Archive 7 rows, which should be 4 in one table and 3 in the other.
        db.archive_deleted_rows(self.context, max_rows=7)
        # Verify we have 5 left in the two main tables combined
        iim_rows = self.conn.execute(qiim).fetchall()
        i_rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(iim_rows) + len(i_rows), 5)
        # Verify we have 7 in the two shadow tables combined.
        siim_rows = self.conn.execute(qsiim).fetchall()
        si_rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(siim_rows) + len(si_rows), 7)
        # Archive the remaining deleted rows.
        db.archive_deleted_rows(self.context, max_rows=1)
        # Verify we have 4 total left in both main tables.
        iim_rows = self.conn.execute(qiim).fetchall()
        i_rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(iim_rows) + len(i_rows), 4)
        # Verify we have 8 in shadow
        siim_rows = self.conn.execute(qsiim).fetchall()
        si_rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(siim_rows) + len(si_rows), 8)
        # Try to archive more, but there are no deleted rows left.
        db.archive_deleted_rows(self.context, max_rows=500)
        # Verify we have 4 total left in both main tables.
        iim_rows = self.conn.execute(qiim).fetchall()
        i_rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(iim_rows) + len(i_rows), 4)
        # Verify we have 8 in shadow
        siim_rows = self.conn.execute(qsiim).fetchall()
        si_rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(siim_rows) + len(si_rows), 8)


class InstanceGroupDBApiTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(InstanceGroupDBApiTestCase, self).setUp()
        self.user_id = 'fake_user'
        self.project_id = 'fake_project'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def _get_default_values(self):
        return {'name': 'fake_name',
                'user_id': self.user_id,
                'project_id': self.project_id}

    def _create_instance_group(self, context, values, policies=None,
                               metadata=None, members=None):
        return db.instance_group_create(context, values, policies=policies,
                                        metadata=metadata, members=members)

    def test_instance_group_create_no_key(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        ignored_keys = ['id', 'uuid', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']
        self._assertEqualObjects(result, values, ignored_keys)
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))

    def test_instance_group_create_with_key(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']
        self._assertEqualObjects(result, values, ignored_keys)

    def test_instance_group_create_with_same_key(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        self.assertRaises(exception.InstanceGroupIdExists,
                          self._create_instance_group, self.context, values)

    def test_instance_group_get(self):
        values = self._get_default_values()
        result1 = self._create_instance_group(self.context, values)
        result2 = db.instance_group_get(self.context, result1['uuid'])
        self._assertEqualObjects(result1, result2)

    def test_instance_group_update_simple(self):
        values = self._get_default_values()
        result1 = self._create_instance_group(self.context, values)
        values = {'name': 'new_name', 'user_id': 'new_user',
                  'project_id': 'new_project'}
        db.instance_group_update(self.context, result1['uuid'],
                                 values)
        result2 = db.instance_group_get(self.context, result1['uuid'])
        self.assertEquals(result1['uuid'], result2['uuid'])
        ignored_keys = ['id', 'uuid', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']
        self._assertEqualObjects(result2, values, ignored_keys)

    def test_instance_group_delete(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        db.instance_group_delete(self.context, result['uuid'])
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_get, self.context, result['uuid'])

    def test_instance_group_get_all(self):
        groups = db.instance_group_get_all(self.context)
        self.assertEquals(0, len(groups))
        value = self._get_default_values()
        result1 = self._create_instance_group(self.context, value)
        groups = db.instance_group_get_all(self.context)
        self.assertEquals(1, len(groups))
        value = self._get_default_values()
        result2 = self._create_instance_group(self.context, value)
        groups = db.instance_group_get_all(self.context)
        results = [result1, result2]
        self._assertEqualListsOfObjects(results, groups)

    def test_instance_group_get_all_by_project_id(self):
        groups = db.instance_group_get_all_by_project_id(self.context,
                                                         'invalid_project_id')
        self.assertEquals(0, len(groups))
        values = self._get_default_values()
        result1 = self._create_instance_group(self.context, values)
        groups = db.instance_group_get_all_by_project_id(self.context,
                                                         'fake_project')
        self.assertEquals(1, len(groups))
        values = self._get_default_values()
        values['project_id'] = 'new_project_id'
        result2 = self._create_instance_group(self.context, values)
        groups = db.instance_group_get_all(self.context)
        results = [result1, result2]
        self._assertEqualListsOfObjects(results, groups)
        projects = [{'name': 'fake_project', 'value': [result1]},
                    {'name': 'new_project_id', 'value': [result2]}]
        for project in projects:
            groups = db.instance_group_get_all_by_project_id(self.context,
                                                             project['name'])
            self._assertEqualListsOfObjects(project['value'], groups)

    def test_instance_group_update(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        ignored_keys = ['id', 'uuid', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']
        self._assertEqualObjects(result, values, ignored_keys)
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        id = result['uuid']
        values = self._get_default_values()
        values['name'] = 'new_fake_name'
        db.instance_group_update(self.context, id, values)
        result = db.instance_group_get(self.context, id)
        self.assertEquals(result['name'], 'new_fake_name')
        # update metadata
        values = self._get_default_values()
        metadataInput = {'key11': 'value1',
                         'key12': 'value2'}
        values['metadata'] = metadataInput
        db.instance_group_update(self.context, id, values)
        result = db.instance_group_get(self.context, id)
        metadata = result['metadetails']
        self._assertEqualObjects(metadata, metadataInput)
        # update update members
        values = self._get_default_values()
        members = ['instance_id1', 'instance_id2']
        values['members'] = members
        db.instance_group_update(self.context, id, values)
        result = db.instance_group_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(result['members'], members)
        # update update policies
        values = self._get_default_values()
        policies = ['policy1', 'policy2']
        values['policies'] = policies
        db.instance_group_update(self.context, id, values)
        result = db.instance_group_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(result['policies'], policies)
        # test invalid ID
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_update, self.context,
                          'invalid_id', values)


class InstanceGroupMetadataDBApiTestCase(InstanceGroupDBApiTestCase):
    def test_instance_group_metadata_on_create(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        metadata = {'key11': 'value1',
                    'key12': 'value2'}
        result = self._create_instance_group(self.context, values,
                                             metadata=metadata)
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']
        self._assertEqualObjects(result, values, ignored_keys)
        self._assertEqualObjects(metadata, result['metadetails'])

    def test_instance_group_metadata_add(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        metadata = db.instance_group_metadata_get(self.context, id)
        self._assertEqualObjects(metadata, {})
        metadata = {'key1': 'value1',
                    'key2': 'value2'}
        db.instance_group_metadata_add(self.context, id, metadata)
        metadata2 = db.instance_group_metadata_get(self.context, id)
        self._assertEqualObjects(metadata, metadata2)

    def test_instance_group_update(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        metadata = {'key1': 'value1',
                    'key2': 'value2'}
        db.instance_group_metadata_add(self.context, id, metadata)
        metadata2 = db.instance_group_metadata_get(self.context, id)
        self._assertEqualObjects(metadata, metadata2)
        # check add with existing keys
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3'}
        db.instance_group_metadata_add(self.context, id, metadata)
        metadata3 = db.instance_group_metadata_get(self.context, id)
        self._assertEqualObjects(metadata, metadata3)

    def test_instance_group_delete(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'key3': 'value3'}
        db.instance_group_metadata_add(self.context, id, metadata)
        metadata3 = db.instance_group_metadata_get(self.context, id)
        self._assertEqualObjects(metadata, metadata3)
        db.instance_group_metadata_delete(self.context, id, 'key1')
        metadata = db.instance_group_metadata_get(self.context, id)
        self.assertTrue('key1' not in metadata)
        db.instance_group_metadata_delete(self.context, id, 'key2')
        metadata = db.instance_group_metadata_get(self.context, id)
        self.assertTrue('key2' not in metadata)

    def test_instance_group_metadata_invalid_ids(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_metadata_get,
                          self.context, 'invalid')
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_metadata_delete, self.context,
                          'invalidid', 'key1')
        metadata = {'key1': 'value1',
                    'key2': 'value2'}
        db.instance_group_metadata_add(self.context, id, metadata)
        self.assertRaises(exception.InstanceGroupMetadataNotFound,
                          db.instance_group_metadata_delete,
                          self.context, id, 'invalidkey')


class InstanceGroupMembersDBApiTestCase(InstanceGroupDBApiTestCase):
    def test_instance_group_members_on_create(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        members = ['instance_id1', 'instance_id2']
        result = self._create_instance_group(self.context, values,
                                             members=members)
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']
        self._assertEqualObjects(result, values, ignored_keys)
        self._assertEqualListsOfPrimitivesAsSets(result['members'], members)

    def test_instance_group_members_add(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        members = db.instance_group_members_get(self.context, id)
        self.assertEquals(members, [])
        members2 = ['instance_id1', 'instance_id2']
        db.instance_group_members_add(self.context, id, members2)
        members = db.instance_group_members_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(members, members2)

    def test_instance_group_members_update(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        members2 = ['instance_id1', 'instance_id2']
        db.instance_group_members_add(self.context, id, members2)
        members = db.instance_group_members_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(members, members2)
        # check add with existing keys
        members3 = ['instance_id1', 'instance_id2', 'instance_id3']
        db.instance_group_members_add(self.context, id, members3)
        members = db.instance_group_members_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(members, members3)

    def test_instance_group_members_delete(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        members3 = ['instance_id1', 'instance_id2', 'instance_id3']
        db.instance_group_members_add(self.context, id, members3)
        members = db.instance_group_members_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(members, members3)
        for instance_id in members3[:]:
            db.instance_group_member_delete(self.context, id, instance_id)
            members3.remove(instance_id)
            members = db.instance_group_members_get(self.context, id)
            self._assertEqualListsOfPrimitivesAsSets(members, members3)

    def test_instance_group_members_invalid_ids(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_members_get,
                          self.context, 'invalid')
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_member_delete, self.context,
                          'invalidid', 'instance_id1')
        members = ['instance_id1', 'instance_id2']
        db.instance_group_members_add(self.context, id, members)
        self.assertRaises(exception.InstanceGroupMemberNotFound,
                          db.instance_group_member_delete,
                          self.context, id, 'invalid_id')


class InstanceGroupPoliciesDBApiTestCase(InstanceGroupDBApiTestCase):
    def test_instance_group_policies_on_create(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        policies = ['policy1', 'policy2']
        result = self._create_instance_group(self.context, values,
                                             policies=policies)
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']
        self._assertEqualObjects(result, values, ignored_keys)
        self._assertEqualListsOfPrimitivesAsSets(result['policies'], policies)

    def test_instance_group_policies_add(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        policies = db.instance_group_policies_get(self.context, id)
        self.assertEquals(policies, [])
        policies2 = ['policy1', 'policy2']
        db.instance_group_policies_add(self.context, id, policies2)
        policies = db.instance_group_policies_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(policies, policies2)

    def test_instance_group_policies_update(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        policies2 = ['policy1', 'policy2']
        db.instance_group_policies_add(self.context, id, policies2)
        policies = db.instance_group_policies_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(policies, policies2)
        policies3 = ['policy1', 'policy2', 'policy3']
        db.instance_group_policies_add(self.context, id, policies3)
        policies = db.instance_group_policies_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(policies, policies3)

    def test_instance_group_policies_delete(self):
        values = self._get_default_values()
        values['uuid'] = 'fake_id'
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        policies3 = ['policy1', 'policy2', 'policy3']
        db.instance_group_policies_add(self.context, id, policies3)
        policies = db.instance_group_policies_get(self.context, id)
        self._assertEqualListsOfPrimitivesAsSets(policies, policies3)
        for policy in policies3[:]:
            db.instance_group_policy_delete(self.context, id, policy)
            policies3.remove(policy)
            policies = db.instance_group_policies_get(self.context, id)
            self._assertEqualListsOfPrimitivesAsSets(policies, policies3)

    def test_instance_group_policies_invalid_ids(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        id = result['uuid']
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_policies_get,
                          self.context, 'invalid')
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_policy_delete, self.context,
                          'invalidid', 'policy1')
        policies = ['policy1', 'policy2']
        db.instance_group_policies_add(self.context, id, policies)
        self.assertRaises(exception.InstanceGroupPolicyNotFound,
                          db.instance_group_policy_delete,
                          self.context, id, 'invalid_policy')

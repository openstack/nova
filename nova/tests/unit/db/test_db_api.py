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

from dateutil import parser as dateutil_parser
import iso8601
import mock
import netaddr
from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import update_match
from oslo_db.sqlalchemy import utils as sqlalchemyutils
from oslo_serialization import jsonutils
from oslo_utils import fixture as utils_fixture
from oslo_utils.fixture import uuidsentinel
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
from six.moves import range
from sqlalchemy import Column
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import inspect
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy.orm import query
from sqlalchemy.orm import session as sqla_session
from sqlalchemy import sql
from sqlalchemy import Table

from nova import block_device
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova import context
from nova.db import api as db
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy import types as col_types
from nova.db.sqlalchemy import utils as db_utils
from nova import exception
from nova import objects
from nova.objects import fields
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_console_auth_token
from nova import utils


CONF = nova.conf.CONF

get_engine = sqlalchemy_api.get_engine


def _reservation_get(context, uuid):
    @sqlalchemy_api.pick_context_manager_reader
    def doit(context):
        return sqlalchemy_api.model_query(
            context, models.Reservation, read_deleted="no").filter_by(
            uuid=uuid).first()

    result = doit(context)
    if not result:
        raise exception.ReservationNotFound(uuid=uuid)

    return result


def _make_compute_node(host, node, hv_type, service_id):
    compute_node_dict = dict(vcpus=2, memory_mb=1024, local_gb=2048,
                        uuid=uuidutils.generate_uuid(),
                        vcpus_used=0, memory_mb_used=0,
                        local_gb_used=0, free_ram_mb=1024,
                        free_disk_gb=2048, hypervisor_type=hv_type,
                        hypervisor_version=1, cpu_info="",
                        running_vms=0, current_workload=0,
                        service_id=service_id,
                        host=host,
                        disk_available_least=100,
                        hypervisor_hostname=node,
                        host_ip='127.0.0.1',
                        supported_instances='',
                        pci_stats='',
                        metrics='',
                        extra_resources='',
                        cpu_allocation_ratio=16.0,
                        ram_allocation_ratio=1.5,
                        disk_allocation_ratio=1.0,
                        stats='', numa_topology='')
    # add some random stats
    stats = dict(num_instances=3, num_proj_12345=2,
            num_proj_23456=2, num_vm_building=3)
    compute_node_dict['stats'] = jsonutils.dumps(stats)
    return compute_node_dict


def _quota_create(context, project_id, user_id):
    """Create sample Quota objects."""
    quotas = {}
    user_quotas = {}
    for i in range(3):
        resource = 'resource%d' % i
        if i == 2:
            # test for project level resources
            resource = 'fixed_ips'
            quotas[resource] = db.quota_create(context,
                                               project_id,
                                               resource, i + 2).hard_limit
            user_quotas[resource] = quotas[resource]
        else:
            quotas[resource] = db.quota_create(context,
                                               project_id,
                                               resource, i + 1).hard_limit
            user_quotas[resource] = db.quota_create(context, project_id,
                                                    resource, i + 1,
                                                    user_id=user_id).hard_limit


@sqlalchemy_api.pick_context_manager_reader
def _assert_instance_id_mapping(_ctxt, tc, inst_uuid, expected_existing=False):
    # NOTE(mriedem): We can't use ec2_instance_get_by_uuid to assert
    # the instance_id_mappings record is gone because it hard-codes
    # read_deleted='yes' and will read the soft-deleted record. So we
    # do the model_query directly here. See bug 1061166.
    inst_id_mapping = sqlalchemy_api.model_query(
        _ctxt, models.InstanceIdMapping).filter_by(uuid=inst_uuid).first()
    if not expected_existing:
        tc.assertFalse(inst_id_mapping,
                       'instance_id_mapping not deleted for '
                       'instance: %s' % inst_uuid)
    else:
        tc.assertTrue(inst_id_mapping,
                      'instance_id_mapping not found for '
                      'instance: %s' % inst_uuid)


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


class HelperTestCase(test.TestCase):
    @mock.patch.object(sqlalchemy_api, 'joinedload')
    def test_joinedload_helper(self, mock_jl):
        query = sqlalchemy_api._joinedload_all('foo.bar.baz')

        # We call sqlalchemy.orm.joinedload() on the first element
        mock_jl.assert_called_once_with('foo')

        # Then first.joinedload(second)
        column2 = mock_jl.return_value
        column2.joinedload.assert_called_once_with('bar')

        # Then second.joinedload(third)
        column3 = column2.joinedload.return_value
        column3.joinedload.assert_called_once_with('baz')

        self.assertEqual(column3.joinedload.return_value, query)

    @mock.patch.object(sqlalchemy_api, 'joinedload')
    def test_joinedload_helper_single(self, mock_jl):
        query = sqlalchemy_api._joinedload_all('foo')

        # We call sqlalchemy.orm.joinedload() on the first element
        mock_jl.assert_called_once_with('foo')

        # We should have gotten back just the result of the joinedload()
        # call if there were no other elements
        self.assertEqual(mock_jl.return_value, query)


class DecoratorTestCase(test.TestCase):
    def _test_decorator_wraps_helper(self, decorator):
        def test_func():
            """Test docstring."""

        decorated_func = decorator(test_func)

        self.assertEqual(test_func.__name__, decorated_func.__name__)
        self.assertEqual(test_func.__doc__, decorated_func.__doc__)
        self.assertEqual(test_func.__module__, decorated_func.__module__)

    def test_require_context_decorator_wraps_functions_properly(self):
        self._test_decorator_wraps_helper(sqlalchemy_api.require_context)

    def test_require_deadlock_retry_wraps_functions_properly(self):
        self._test_decorator_wraps_helper(
            oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True))

    @mock.patch.object(enginefacade._TransactionContextManager, 'using')
    @mock.patch.object(enginefacade._TransactionContextManager, '_clone')
    def test_select_db_reader_mode_select_sync(self, mock_clone, mock_using):

        @db.select_db_reader_mode
        def func(self, context, value, use_slave=False):
            pass

        mock_clone.return_value = enginefacade._TransactionContextManager(
            mode=enginefacade._READER)
        ctxt = context.get_admin_context()
        value = 'some_value'
        func(self, ctxt, value)

        mock_clone.assert_called_once_with(mode=enginefacade._READER)
        mock_using.assert_called_once_with(ctxt)

    @mock.patch.object(enginefacade._TransactionContextManager, 'using')
    @mock.patch.object(enginefacade._TransactionContextManager, '_clone')
    def test_select_db_reader_mode_select_async(self, mock_clone, mock_using):

        @db.select_db_reader_mode
        def func(self, context, value, use_slave=False):
            pass

        mock_clone.return_value = enginefacade._TransactionContextManager(
            mode=enginefacade._ASYNC_READER)
        ctxt = context.get_admin_context()
        value = 'some_value'
        func(self, ctxt, value, use_slave=True)

        mock_clone.assert_called_once_with(mode=enginefacade._ASYNC_READER)
        mock_using.assert_called_once_with(ctxt)

    @mock.patch.object(enginefacade._TransactionContextManager, 'using')
    @mock.patch.object(enginefacade._TransactionContextManager, '_clone')
    def test_select_db_reader_mode_no_use_slave_select_sync(self, mock_clone,
                                                            mock_using):

        @db.select_db_reader_mode
        def func(self, context, value):
            pass

        mock_clone.return_value = enginefacade._TransactionContextManager(
            mode=enginefacade._READER)
        ctxt = context.get_admin_context()
        value = 'some_value'
        func(self, ctxt, value)

        mock_clone.assert_called_once_with(mode=enginefacade._READER)
        mock_using.assert_called_once_with(ctxt)


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


@mock.patch.object(sqlalchemy_api, '_get_regexp_ops',
        return_value=(lambda x: x, 'LIKE'))
class UnsupportedDbRegexpTestCase(DbTestCase):

    def test_instance_get_all_by_filters_paginate(self, mock_get_regexp):
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
                          marker=uuidsentinel.uuid1)

    def test_instance_get_all_uuids_by_hosts(self, mock_get_regexp):
        test1 = self.create_instance_with_args(display_name='test1')
        test2 = self.create_instance_with_args(display_name='test2')
        test3 = self.create_instance_with_args(display_name='test3')
        uuids = [i.uuid for i in (test1, test2, test3)]
        results = db.instance_get_all_uuids_by_hosts(
            self.context, [test1.host])
        self.assertEqual(1, len(results))
        self.assertIn(test1.host, results)
        found_uuids = results[test1.host]
        self.assertEqual(sorted(uuids), sorted(found_uuids))

    def _assert_equals_inst_order(self, correct_order, filters,
                                  sort_keys=None, sort_dirs=None,
                                  limit=None, marker=None,
                                  match_keys=['uuid', 'vm_state',
                                              'display_name', 'id']):
        '''Retrieves instances based on the given filters and sorting
        information and verifies that the instances are returned in the
        correct sorted order by ensuring that the supplied keys match.
        '''
        result = db.instance_get_all_by_filters_sort(
            self.context, filters, limit=limit, marker=marker,
            sort_keys=sort_keys, sort_dirs=sort_dirs)
        self.assertEqual(len(correct_order), len(result))
        for inst1, inst2 in zip(result, correct_order):
            for key in match_keys:
                self.assertEqual(inst1.get(key), inst2.get(key))
        return result

    def test_instance_get_all_by_filters_sort_keys(self, mock_get_regexp):
        '''Verifies sort order and direction for multiple instances.'''
        # Instances that will reply to the query
        test1_active = self.create_instance_with_args(
                            display_name='test1',
                            vm_state=vm_states.ACTIVE)
        test1_error = self.create_instance_with_args(
                           display_name='test1',
                           vm_state=vm_states.ERROR)
        test1_error2 = self.create_instance_with_args(
                            display_name='test1',
                            vm_state=vm_states.ERROR)
        test2_active = self.create_instance_with_args(
                            display_name='test2',
                            vm_state=vm_states.ACTIVE)
        test2_error = self.create_instance_with_args(
                           display_name='test2',
                           vm_state=vm_states.ERROR)
        test2_error2 = self.create_instance_with_args(
                            display_name='test2',
                            vm_state=vm_states.ERROR)
        # Other instances in the DB, will not match name filter
        other_error = self.create_instance_with_args(
                           display_name='other',
                           vm_state=vm_states.ERROR)
        other_active = self.create_instance_with_args(
                            display_name='other',
                            vm_state=vm_states.ACTIVE)
        filters = {'display_name': '%test%'}

        # Verify different sort key/direction combinations
        sort_keys = ['display_name', 'vm_state', 'created_at']
        sort_dirs = ['asc', 'asc', 'asc']
        correct_order = [test1_active, test1_error, test1_error2,
                         test2_active, test2_error, test2_error2]
        self._assert_equals_inst_order(correct_order, filters,
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs)

        sort_dirs = ['asc', 'desc', 'asc']
        correct_order = [test1_error, test1_error2, test1_active,
                         test2_error, test2_error2, test2_active]
        self._assert_equals_inst_order(correct_order, filters,
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs)

        sort_dirs = ['desc', 'desc', 'asc']
        correct_order = [test2_error, test2_error2, test2_active,
                         test1_error, test1_error2, test1_active]
        self._assert_equals_inst_order(correct_order, filters,
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs)

        # created_at is added by default if not supplied, descending order
        sort_keys = ['display_name', 'vm_state']
        sort_dirs = ['desc', 'desc']
        correct_order = [test2_error2, test2_error, test2_active,
                         test1_error2, test1_error, test1_active]
        self._assert_equals_inst_order(correct_order, filters,
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs)

        # Now created_at should be in ascending order (defaults to the first
        # sort dir direction)
        sort_dirs = ['asc', 'asc']
        correct_order = [test1_active, test1_error, test1_error2,
                         test2_active, test2_error, test2_error2]
        self._assert_equals_inst_order(correct_order, filters,
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs)

        # Remove name filter, get all instances
        correct_order = [other_active, other_error,
                         test1_active, test1_error, test1_error2,
                         test2_active, test2_error, test2_error2]
        self._assert_equals_inst_order(correct_order, {},
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs)

        # Default sorting, 'created_at' then 'id' in desc order
        correct_order = [other_active, other_error,
                         test2_error2, test2_error, test2_active,
                         test1_error2, test1_error, test1_active]
        self._assert_equals_inst_order(correct_order, {})

    def test_instance_get_all_by_filters_sort_keys_paginate(self,
            mock_get_regexp):
        '''Verifies sort order with pagination.'''
        # Instances that will reply to the query
        test1_active = self.create_instance_with_args(
                            display_name='test1',
                            vm_state=vm_states.ACTIVE)
        test1_error = self.create_instance_with_args(
                           display_name='test1',
                           vm_state=vm_states.ERROR)
        test1_error2 = self.create_instance_with_args(
                            display_name='test1',
                            vm_state=vm_states.ERROR)
        test2_active = self.create_instance_with_args(
                            display_name='test2',
                            vm_state=vm_states.ACTIVE)
        test2_error = self.create_instance_with_args(
                           display_name='test2',
                           vm_state=vm_states.ERROR)
        test2_error2 = self.create_instance_with_args(
                            display_name='test2',
                            vm_state=vm_states.ERROR)
        # Other instances in the DB, will not match name filter
        self.create_instance_with_args(display_name='other')
        self.create_instance_with_args(display_name='other')
        filters = {'display_name': '%test%'}
        # Common sort information for every query
        sort_keys = ['display_name', 'vm_state', 'created_at']
        sort_dirs = ['asc', 'desc', 'asc']
        # Overall correct instance order based on the sort keys
        correct_order = [test1_error, test1_error2, test1_active,
                         test2_error, test2_error2, test2_active]

        # Limits of 1, 2, and 3, verify that the instances returned are in the
        # correct sorted order, update the marker to get the next correct page
        for limit in range(1, 4):
            marker = None
            # Include the maximum number of instances (ie, 6) to ensure that
            # the last query (with marker pointing to the last instance)
            # returns 0 servers
            for i in range(0, 7, limit):
                if i == len(correct_order):
                    correct = []
                else:
                    correct = correct_order[i:i + limit]
                insts = self._assert_equals_inst_order(
                    correct, filters,
                    sort_keys=sort_keys, sort_dirs=sort_dirs,
                    limit=limit, marker=marker)
                if correct:
                    marker = insts[-1]['uuid']
                    self.assertEqual(correct[-1]['uuid'], marker)

    def test_instance_get_deleted_by_filters_sort_keys_paginate(self,
            mock_get_regexp):
        '''Verifies sort order with pagination for deleted instances.'''
        ctxt = context.get_admin_context()
        # Instances that will reply to the query
        test1_active = self.create_instance_with_args(
                            display_name='test1',
                            vm_state=vm_states.ACTIVE)
        db.instance_destroy(ctxt, test1_active['uuid'])
        test1_error = self.create_instance_with_args(
                           display_name='test1',
                           vm_state=vm_states.ERROR)
        db.instance_destroy(ctxt, test1_error['uuid'])
        test1_error2 = self.create_instance_with_args(
                            display_name='test1',
                            vm_state=vm_states.ERROR)
        db.instance_destroy(ctxt, test1_error2['uuid'])
        test2_active = self.create_instance_with_args(
                            display_name='test2',
                            vm_state=vm_states.ACTIVE)
        db.instance_destroy(ctxt, test2_active['uuid'])
        test2_error = self.create_instance_with_args(
                           display_name='test2',
                           vm_state=vm_states.ERROR)
        db.instance_destroy(ctxt, test2_error['uuid'])
        test2_error2 = self.create_instance_with_args(
                            display_name='test2',
                            vm_state=vm_states.ERROR)
        db.instance_destroy(ctxt, test2_error2['uuid'])
        # Other instances in the DB, will not match name filter
        self.create_instance_with_args(display_name='other')
        self.create_instance_with_args(display_name='other')
        filters = {'display_name': '%test%', 'deleted': True}
        # Common sort information for every query
        sort_keys = ['display_name', 'vm_state', 'created_at']
        sort_dirs = ['asc', 'desc', 'asc']
        # Overall correct instance order based on the sort keys
        correct_order = [test1_error, test1_error2, test1_active,
                         test2_error, test2_error2, test2_active]

        # Limits of 1, 2, and 3, verify that the instances returned are in the
        # correct sorted order, update the marker to get the next correct page
        for limit in range(1, 4):
            marker = None
            # Include the maximum number of instances (ie, 6) to ensure that
            # the last query (with marker pointing to the last instance)
            # returns 0 servers
            for i in range(0, 7, limit):
                if i == len(correct_order):
                    correct = []
                else:
                    correct = correct_order[i:i + limit]
                insts = self._assert_equals_inst_order(
                    correct, filters,
                    sort_keys=sort_keys, sort_dirs=sort_dirs,
                    limit=limit, marker=marker)
                if correct:
                    marker = insts[-1]['uuid']
                    self.assertEqual(correct[-1]['uuid'], marker)


class ModelQueryTestCase(DbTestCase):
    def test_model_query_invalid_arguments(self):
        @sqlalchemy_api.pick_context_manager_reader
        def test(context):
            # read_deleted shouldn't accept invalid values
            self.assertRaises(ValueError, sqlalchemy_api.model_query,
                              context, models.Instance,
                              read_deleted=False)
            self.assertRaises(ValueError, sqlalchemy_api.model_query,
                              context, models.Instance,
                              read_deleted="foo")

            # Check model is a valid model
            self.assertRaises(TypeError, sqlalchemy_api.model_query,
                              context, "")

        test(self.context)

    @mock.patch.object(sqlalchemyutils, 'model_query')
    def test_model_query_use_context_session(self, mock_model_query):
        @sqlalchemy_api.main_context_manager.reader
        def fake_method(context):
            session = context.session
            sqlalchemy_api.model_query(context, models.Instance)
            return session

        session = fake_method(self.context)
        mock_model_query.assert_called_once_with(models.Instance, session,
                                                 None, deleted=False)


class EngineFacadeTestCase(DbTestCase):
    def test_use_single_context_session_writer(self):
        # Checks that session in context would not be overwritten by
        # annotation @sqlalchemy_api.main_context_manager.writer if annotation
        # is used twice.

        @sqlalchemy_api.main_context_manager.writer
        def fake_parent_method(context):
            session = context.session
            return fake_child_method(context), session

        @sqlalchemy_api.main_context_manager.writer
        def fake_child_method(context):
            session = context.session
            sqlalchemy_api.model_query(context, models.Instance)
            return session

        parent_session, child_session = fake_parent_method(self.context)
        self.assertEqual(parent_session, child_session)

    def test_use_single_context_session_reader(self):
        # Checks that session in context would not be overwritten by
        # annotation @sqlalchemy_api.main_context_manager.reader if annotation
        # is used twice.

        @sqlalchemy_api.main_context_manager.reader
        def fake_parent_method(context):
            session = context.session
            return fake_child_method(context), session

        @sqlalchemy_api.main_context_manager.reader
        def fake_child_method(context):
            session = context.session
            sqlalchemy_api.model_query(context, models.Instance)
            return session

        parent_session, child_session = fake_parent_method(self.context)
        self.assertEqual(parent_session, child_session)


class SqlAlchemyDbApiNoDbTestCase(test.NoDBTestCase):
    """No-DB test class for simple test cases that do not require a backend."""

    def test_manual_join_columns_immutable_list(self):
        # Tests that _manual_join_columns doesn't modify the list passed in.
        columns_to_join = ['system_metadata', 'test']
        manual_joins, columns_to_join2 = (
            sqlalchemy_api._manual_join_columns(columns_to_join))
        self.assertEqual(['system_metadata'], manual_joins)
        self.assertEqual(['test'], columns_to_join2)
        self.assertEqual(['system_metadata', 'test'], columns_to_join)

    def test_convert_objects_related_datetimes(self):

        t1 = timeutils.utcnow()
        t2 = t1 + datetime.timedelta(seconds=10)
        t3 = t2 + datetime.timedelta(hours=1)

        t2_utc = t2.replace(tzinfo=iso8601.UTC)
        t3_utc = t3.replace(tzinfo=iso8601.UTC)

        datetime_keys = ('created_at', 'deleted_at')

        test1 = {'created_at': t1, 'deleted_at': t2, 'updated_at': t3}
        expected_dict = {'created_at': t1, 'deleted_at': t2, 'updated_at': t3}
        sqlalchemy_api.convert_objects_related_datetimes(test1, *datetime_keys)
        self.assertEqual(test1, expected_dict)

        test2 = {'created_at': t1, 'deleted_at': t2_utc, 'updated_at': t3}
        expected_dict = {'created_at': t1, 'deleted_at': t2, 'updated_at': t3}
        sqlalchemy_api.convert_objects_related_datetimes(test2, *datetime_keys)
        self.assertEqual(test2, expected_dict)

        test3 = {'deleted_at': t2_utc, 'updated_at': t3_utc}
        expected_dict = {'deleted_at': t2, 'updated_at': t3_utc}
        sqlalchemy_api.convert_objects_related_datetimes(test3, *datetime_keys)
        self.assertEqual(test3, expected_dict)

    def test_convert_objects_related_datetimes_with_strings(self):
        t1 = '2015-05-28T17:15:53.000000'
        t2 = '2012-04-21T18:25:43-05:00'
        t3 = '2012-04-23T18:25:43.511Z'

        datetime_keys = ('created_at', 'deleted_at', 'updated_at')
        test1 = {'created_at': t1, 'deleted_at': t2, 'updated_at': t3}
        expected_dict = {
        'created_at': timeutils.parse_strtime(t1).replace(tzinfo=None),
        'deleted_at': timeutils.parse_isotime(t2).replace(tzinfo=None),
        'updated_at': timeutils.parse_isotime(t3).replace(tzinfo=None)}

        sqlalchemy_api.convert_objects_related_datetimes(test1)
        self.assertEqual(test1, expected_dict)

        sqlalchemy_api.convert_objects_related_datetimes(test1, *datetime_keys)
        self.assertEqual(test1, expected_dict)

    def test_get_regexp_op_for_database_sqlite(self):
        filter, op = sqlalchemy_api._get_regexp_ops('sqlite:///')
        self.assertEqual('|', filter('|'))
        self.assertEqual('REGEXP', op)

    def test_get_regexp_op_for_database_mysql(self):
        filter, op = sqlalchemy_api._get_regexp_ops(
                    'mysql+pymysql://root@localhost')
        self.assertEqual('\\|', filter('|'))
        self.assertEqual('REGEXP', op)

    def test_get_regexp_op_for_database_postgresql(self):
        filter, op = sqlalchemy_api._get_regexp_ops(
                    'postgresql://localhost')
        self.assertEqual('|', filter('|'))
        self.assertEqual('~', op)

    def test_get_regexp_op_for_database_unknown(self):
        filter, op = sqlalchemy_api._get_regexp_ops('notdb:///')
        self.assertEqual('|', filter('|'))
        self.assertEqual('LIKE', op)

    @mock.patch.object(sqlalchemy_api, 'main_context_manager')
    def test_get_engine(self, mock_ctxt_mgr):
        sqlalchemy_api.get_engine()
        mock_ctxt_mgr.writer.get_engine.assert_called_once_with()

    @mock.patch.object(sqlalchemy_api, 'main_context_manager')
    def test_get_engine_use_slave(self, mock_ctxt_mgr):
        sqlalchemy_api.get_engine(use_slave=True)
        mock_ctxt_mgr.reader.get_engine.assert_called_once_with()

    def test_get_db_conf_with_connection(self):
        mock_conf_group = mock.MagicMock()
        mock_conf_group.connection = 'fakemain://'
        db_conf = sqlalchemy_api._get_db_conf(mock_conf_group,
                                              connection='fake://')
        self.assertEqual('fake://', db_conf['connection'])

    @mock.patch.object(sqlalchemy_api, 'api_context_manager')
    def test_get_api_engine(self, mock_ctxt_mgr):
        sqlalchemy_api.get_api_engine()
        mock_ctxt_mgr.writer.get_engine.assert_called_once_with()

    @mock.patch.object(sqlalchemy_api, '_instance_get_by_uuid')
    @mock.patch.object(sqlalchemy_api, '_instances_fill_metadata')
    @mock.patch('oslo_db.sqlalchemy.utils.paginate_query')
    def test_instance_get_all_by_filters_paginated_allows_deleted_marker(
            self, mock_paginate, mock_fill, mock_get):
        ctxt = mock.MagicMock()
        ctxt.elevated.return_value = mock.sentinel.elevated
        sqlalchemy_api.instance_get_all_by_filters_sort(ctxt, {}, marker='foo')
        mock_get.assert_called_once_with(mock.sentinel.elevated, 'foo')
        ctxt.elevated.assert_called_once_with(read_deleted='yes')

    def test_replace_sub_expression(self):
        ret = sqlalchemy_api._safe_regex_mysql('|')
        self.assertEqual('\\|', ret)

        ret = sqlalchemy_api._safe_regex_mysql('||')
        self.assertEqual('\\|\\|', ret)

        ret = sqlalchemy_api._safe_regex_mysql('a||')
        self.assertEqual('a\\|\\|', ret)

        ret = sqlalchemy_api._safe_regex_mysql('|a|')
        self.assertEqual('\\|a\\|', ret)

        ret = sqlalchemy_api._safe_regex_mysql('||a')
        self.assertEqual('\\|\\|a', ret)


class SqlAlchemyDbApiTestCase(DbTestCase):
    def test_instance_get_all_by_host(self):
        ctxt = context.get_admin_context()

        self.create_instance_with_args()
        self.create_instance_with_args()
        self.create_instance_with_args(host='host2')

        @sqlalchemy_api.pick_context_manager_reader
        def test(context):
            return sqlalchemy_api.instance_get_all_by_host(
                context, 'host1')

        result = test(ctxt)

        self.assertEqual(2, len(result))
        # make sure info_cache and security_groups were auto-joined
        instance = result[0]
        self.assertIn('info_cache', instance)
        self.assertIn('security_groups', instance)

    def test_instance_get_all_by_host_no_joins(self):
        """Tests that we don't join on the info_cache and security_groups
        tables if columns_to_join is an empty list.
        """
        self.create_instance_with_args()

        @sqlalchemy_api.pick_context_manager_reader
        def test(ctxt):
            return sqlalchemy_api.instance_get_all_by_host(
                ctxt, 'host1', columns_to_join=[])

        result = test(context.get_admin_context())
        self.assertEqual(1, len(result))
        # make sure info_cache and security_groups were not auto-joined
        instance = result[0]
        self.assertNotIn('info_cache', instance)
        self.assertNotIn('security_groups', instance)

    def test_instance_get_all_uuids_by_hosts(self):
        ctxt = context.get_admin_context()
        self.create_instance_with_args()
        self.create_instance_with_args()
        self.create_instance_with_args(host='host2')

        @sqlalchemy_api.pick_context_manager_reader
        def test1(context):
            return sqlalchemy_api._instance_get_all_uuids_by_hosts(
                context, ['host1'])

        @sqlalchemy_api.pick_context_manager_reader
        def test2(context):
            return sqlalchemy_api._instance_get_all_uuids_by_hosts(
                context, ['host1', 'host2'])

        result = test1(ctxt)

        self.assertEqual(1, len(result))
        self.assertEqual(2, len(result['host1']))
        self.assertEqual(six.text_type, type(result['host1'][0]))

        result = test2(ctxt)

        self.assertEqual(2, len(result))
        self.assertEqual(2, len(result['host1']))
        self.assertEqual(1, len(result['host2']))

    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    def test_instance_get_active_by_window_joined_paging(self, mock_uuids):
        mock_uuids.side_effect = ['BBB', 'ZZZ', 'AAA', 'CCC']

        ctxt = context.get_admin_context()
        now = datetime.datetime(2015, 10, 2)
        self.create_instance_with_args(project_id='project-ZZZ')
        self.create_instance_with_args(project_id='project-ZZZ')
        self.create_instance_with_args(project_id='project-ZZZ')
        self.create_instance_with_args(project_id='project-AAA')

        # no limit or marker
        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=now, columns_to_join=[])
        actual_uuids = [row['uuid'] for row in result]
        self.assertEqual(['CCC', 'AAA', 'BBB', 'ZZZ'], actual_uuids)

        # just limit
        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=now, columns_to_join=[], limit=2)
        actual_uuids = [row['uuid'] for row in result]
        self.assertEqual(['CCC', 'AAA'], actual_uuids)

        # limit & marker
        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=now, columns_to_join=[], limit=2, marker='CCC')
        actual_uuids = [row['uuid'] for row in result]
        self.assertEqual(['AAA', 'BBB'], actual_uuids)

        # unknown marker
        self.assertRaises(
            exception.MarkerNotFound,
            sqlalchemy_api.instance_get_active_by_window_joined,
            ctxt, begin=now, columns_to_join=[], limit=2, marker='unknown')

    def test_instance_get_active_by_window_joined(self):
        now = datetime.datetime(2013, 10, 10, 17, 16, 37, 156701)
        start_time = now - datetime.timedelta(minutes=10)
        now1 = now + datetime.timedelta(minutes=1)
        now2 = now + datetime.timedelta(minutes=2)
        now3 = now + datetime.timedelta(minutes=3)
        ctxt = context.get_admin_context()
        # used for testing columns_to_join
        network_info = jsonutils.dumps({'ckey': 'cvalue'})
        sample_data = {
            'metadata': {'mkey1': 'mval1', 'mkey2': 'mval2'},
            'system_metadata': {'smkey1': 'smval1', 'smkey2': 'smval2'},
            'info_cache': {'network_info': network_info},
        }
        self.create_instance_with_args(launched_at=now, **sample_data)
        self.create_instance_with_args(launched_at=now1, terminated_at=now2,
                                       **sample_data)
        self.create_instance_with_args(launched_at=now2, terminated_at=now3,
                                       **sample_data)
        self.create_instance_with_args(launched_at=now3, terminated_at=None,
                                       **sample_data)

        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=now)
        self.assertEqual(4, len(result))
        # verify that all default columns are joined
        meta = utils.metadata_to_dict(result[0]['metadata'])
        self.assertEqual(sample_data['metadata'], meta)
        sys_meta = utils.metadata_to_dict(result[0]['system_metadata'])
        self.assertEqual(sample_data['system_metadata'], sys_meta)
        self.assertIn('info_cache', result[0])

        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=now3, columns_to_join=['info_cache'])
        self.assertEqual(2, len(result))
        # verify that only info_cache is loaded
        meta = utils.metadata_to_dict(result[0]['metadata'])
        self.assertEqual({}, meta)
        self.assertIn('info_cache', result[0])

        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=start_time, end=now)
        self.assertEqual(0, len(result))

        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=start_time, end=now2,
            columns_to_join=['system_metadata'])
        self.assertEqual(2, len(result))
        # verify that only system_metadata is loaded
        meta = utils.metadata_to_dict(result[0]['metadata'])
        self.assertEqual({}, meta)
        sys_meta = utils.metadata_to_dict(result[0]['system_metadata'])
        self.assertEqual(sample_data['system_metadata'], sys_meta)
        self.assertNotIn('info_cache', result[0])

        result = sqlalchemy_api.instance_get_active_by_window_joined(
            ctxt, begin=now2, end=now3,
            columns_to_join=['metadata', 'info_cache'])
        self.assertEqual(2, len(result))
        # verify that only metadata and info_cache are loaded
        meta = utils.metadata_to_dict(result[0]['metadata'])
        self.assertEqual(sample_data['metadata'], meta)
        sys_meta = utils.metadata_to_dict(result[0]['system_metadata'])
        self.assertEqual({}, sys_meta)
        self.assertIn('info_cache', result[0])
        self.assertEqual(network_info, result[0]['info_cache']['network_info'])

    @mock.patch('nova.db.sqlalchemy.api.instance_get_all_by_filters_sort')
    def test_instance_get_all_by_filters_calls_sort(self,
                                                    mock_get_all_filters_sort):
        '''Verifies instance_get_all_by_filters calls the sort function.'''
        # sort parameters should be wrapped in a list, all other parameters
        # should be passed through
        ctxt = context.get_admin_context()
        sqlalchemy_api.instance_get_all_by_filters(ctxt, {'foo': 'bar'},
            'sort_key', 'sort_dir', limit=100, marker='uuid',
            columns_to_join='columns')
        mock_get_all_filters_sort.assert_called_once_with(ctxt, {'foo': 'bar'},
            limit=100, marker='uuid', columns_to_join='columns',
            sort_keys=['sort_key'], sort_dirs=['sort_dir'])

    def test_instance_get_all_by_filters_sort_key_invalid(self):
        '''InvalidSortKey raised if an invalid key is given.'''
        for keys in [['foo'], ['uuid', 'foo']]:
            self.assertRaises(exception.InvalidSortKey,
                              db.instance_get_all_by_filters_sort,
                              self.context,
                              filters={},
                              sort_keys=keys)

    def test_instance_get_all_by_filters_sort_hidden(self):
        """Tests the default filtering behavior of the hidden column."""
        # Create a hidden instance record.
        self.create_instance_with_args(hidden=True)
        # Get instances which by default will filter out the hidden instance.
        instances = sqlalchemy_api.instance_get_all_by_filters_sort(
            self.context, filters={}, limit=10)
        self.assertEqual(0, len(instances))
        # Now explicitly filter for hidden instances.
        instances = sqlalchemy_api.instance_get_all_by_filters_sort(
            self.context, filters={'hidden': True}, limit=10)
        self.assertEqual(1, len(instances))


class ProcessSortParamTestCase(test.TestCase):

    def test_process_sort_params_defaults(self):
        '''Verifies default sort parameters.'''
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params([], [])
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['asc', 'asc'], sort_dirs)

        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(None, None)
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['asc', 'asc'], sort_dirs)

    def test_process_sort_params_override_default_keys(self):
        '''Verifies that the default keys can be overridden.'''
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_keys=['key1', 'key2', 'key3'])
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['asc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_override_default_dir(self):
        '''Verifies that the default direction can be overridden.'''
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_dir='dir1')
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['dir1', 'dir1'], sort_dirs)

    def test_process_sort_params_override_default_key_and_dir(self):
        '''Verifies that the default key and dir can be overridden.'''
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_keys=['key1', 'key2', 'key3'],
            default_dir='dir1')
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['dir1', 'dir1', 'dir1'], sort_dirs)

        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_keys=[], default_dir='dir1')
        self.assertEqual([], sort_keys)
        self.assertEqual([], sort_dirs)

    def test_process_sort_params_non_default(self):
        '''Verifies that non-default keys are added correctly.'''
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['key1', 'key2'], ['asc', 'desc'])
        self.assertEqual(['key1', 'key2', 'created_at', 'id'], sort_keys)
        # First sort_dir in list is used when adding the default keys
        self.assertEqual(['asc', 'desc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_default(self):
        '''Verifies that default keys are added correctly.'''
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], ['asc', 'desc'])
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['asc', 'desc', 'asc'], sort_dirs)

        # Include default key value, rely on default direction
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], [])
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['asc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_default_dir(self):
        '''Verifies that the default dir is applied to all keys.'''
        # Direction is set, ignore default dir
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], ['desc'], default_dir='dir')
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'desc', 'desc'], sort_dirs)

        # But should be used if no direction is set
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], [], default_dir='dir')
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['dir', 'dir', 'dir'], sort_dirs)

    def test_process_sort_params_unequal_length(self):
        '''Verifies that a sort direction list is applied correctly.'''
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2', 'key3'], ['desc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'desc', 'desc', 'desc'], sort_dirs)

        # Default direction is the first key in the list
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2', 'key3'], ['desc', 'asc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'asc', 'desc', 'desc'], sort_dirs)

        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2', 'key3'], ['desc', 'asc', 'asc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'asc', 'asc', 'desc'], sort_dirs)

    def test_process_sort_params_extra_dirs_lengths(self):
        '''InvalidInput raised if more directions are given.'''
        self.assertRaises(exception.InvalidInput,
                          sqlalchemy_api.process_sort_params,
                          ['key1', 'key2'],
                          ['asc', 'desc', 'desc'])

    def test_process_sort_params_invalid_sort_dir(self):
        '''InvalidInput raised if invalid directions are given.'''
        for dirs in [['foo'], ['asc', 'foo'], ['asc', 'desc', 'foo']]:
            self.assertRaises(exception.InvalidInput,
                              sqlalchemy_api.process_sort_params,
                              ['key'],
                              dirs)


class MigrationTestCase(test.TestCase):

    def setUp(self):
        super(MigrationTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        self._create()
        self._create()
        self._create(status='reverted')
        self._create(status='confirmed')
        self._create(status='error')
        self._create(status='failed')
        self._create(status='accepted')
        self._create(status='done')
        self._create(status='completed')
        self._create(status='cancelled')
        self._create(source_compute='host2', source_node='b',
                dest_compute='host1', dest_node='a')
        self._create(source_compute='host2', dest_compute='host3')
        self._create(source_compute='host3', dest_compute='host4')

    def _create(self, status='migrating', source_compute='host1',
                source_node='a', dest_compute='host2', dest_node='b',
                system_metadata=None, migration_type=None, uuid=None,
                created_at=None, updated_at=None, user_id=None,
                project_id=None):

        values = {'host': source_compute}
        instance = db.instance_create(self.ctxt, values)
        if system_metadata:
            db.instance_system_metadata_update(self.ctxt, instance['uuid'],
                                               system_metadata, False)

        values = {'status': status, 'source_compute': source_compute,
                  'source_node': source_node, 'dest_compute': dest_compute,
                  'dest_node': dest_node, 'instance_uuid': instance['uuid'],
                  'migration_type': migration_type, 'uuid': uuid}
        if created_at:
            values['created_at'] = created_at
        if updated_at:
            values['updated_at'] = updated_at
        if user_id:
            values['user_id'] = user_id
        if project_id:
            values['project_id'] = project_id
        db.migration_create(self.ctxt, values)
        return values

    def _assert_in_progress(self, migrations):
        for migration in migrations:
            self.assertNotEqual('confirmed', migration['status'])
            self.assertNotEqual('reverted', migration['status'])
            self.assertNotEqual('error', migration['status'])
            self.assertNotEqual('failed', migration['status'])
            self.assertNotEqual('done', migration['status'])
            self.assertNotEqual('cancelled', migration['status'])

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
        self.assertEqual(4, len(migrations))
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
        self.assertEqual(4, len(migrations))
        self._assert_in_progress(migrations)

    def test_instance_join(self):
        migrations = db.migration_get_in_progress_by_host_and_node(self.ctxt,
                'host2', 'b')
        for migration in migrations:
            instance = migration['instance']
            self.assertEqual(migration['instance_uuid'], instance['uuid'])

    def test_migration_get_by_uuid(self):
        migration1 = self._create(uuid=uuidsentinel.migration1_uuid)
        self._create(uuid=uuidsentinel.other_uuid)
        real_migration1 = db.migration_get_by_uuid(
            self.ctxt, uuidsentinel.migration1_uuid)
        for key in migration1:
            self.assertEqual(migration1[key], real_migration1[key])

    def test_migration_get_by_uuid_soft_deleted_and_deleted(self):
        migration1 = self._create(uuid=uuidsentinel.migration1_uuid)

        @sqlalchemy_api.pick_context_manager_writer
        def soft_delete_it(context):
            sqlalchemy_api.model_query(context, models.Migration).\
                filter_by(uuid=uuidsentinel.migration1_uuid).\
                soft_delete()

        @sqlalchemy_api.pick_context_manager_writer
        def delete_it(context):
            sqlalchemy_api.model_query(context, models.Migration,
                                       read_deleted="yes").\
                filter_by(uuid=uuidsentinel.migration1_uuid).\
                delete()

        soft_delete_it(self.ctxt)
        soft_deletd_migration1 = db.migration_get_by_uuid(
            self.ctxt, uuidsentinel.migration1_uuid)
        for key in migration1:
            self.assertEqual(migration1[key], soft_deletd_migration1[key])
        delete_it(self.ctxt)
        self.assertRaises(exception.MigrationNotFound,
                          db.migration_get_by_uuid, self.ctxt,
                          uuidsentinel.migration1_uuid)

    def test_migration_get_by_uuid_not_found(self):
        """Asserts that MigrationNotFound is raised if a migration is not
        found by a given uuid.
        """
        self.assertRaises(exception.MigrationNotFound,
                          db.migration_get_by_uuid, self.ctxt,
                          uuidsentinel.migration_not_found)

    def test_get_migrations_by_filters(self):
        filters = {"status": "migrating", "host": "host3",
                   "migration_type": None, "hidden": False}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        self.assertEqual(2, len(migrations))
        for migration in migrations:
            self.assertEqual(filters["status"], migration['status'])
            hosts = [migration['source_compute'], migration['dest_compute']]
            self.assertIn(filters["host"], hosts)

    def test_get_migrations_by_uuid_filters(self):
        mig_uuid1 = self._create(uuid=uuidsentinel.mig_uuid1)
        filters = {"uuid": [uuidsentinel.mig_uuid1]}
        mig_get = db.migration_get_all_by_filters(self.ctxt, filters)
        self.assertEqual(1, len(mig_get))
        for key in mig_uuid1:
            self.assertEqual(mig_uuid1[key], mig_get[0][key])

    def test_get_migrations_by_filters_with_multiple_statuses(self):
        filters = {"status": ["reverted", "confirmed"],
                   "migration_type": None, "hidden": False}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        self.assertEqual(2, len(migrations))
        for migration in migrations:
            self.assertIn(migration['status'], filters['status'])

    def test_get_migrations_by_filters_unicode_status(self):
        self._create(status=u"unicode")
        filters = {"status": u"unicode"}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        self.assertEqual(1, len(migrations))
        for migration in migrations:
            self.assertIn(migration['status'], filters['status'])

    def test_get_migrations_by_filters_with_type(self):
        self._create(status="special", source_compute="host9",
                     migration_type="evacuation")
        self._create(status="special", source_compute="host9",
                     migration_type="live-migration")
        filters = {"status": "special", "host": "host9",
                   "migration_type": "evacuation", "hidden": False}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        self.assertEqual(1, len(migrations))

    def test_get_migrations_by_filters_source_compute(self):
        filters = {'source_compute': 'host2'}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        self.assertEqual(2, len(migrations))
        sources = [x['source_compute'] for x in migrations]
        self.assertEqual(['host2', 'host2'], sources)
        dests = [x['dest_compute'] for x in migrations]
        self.assertEqual(['host1', 'host3'], dests)

    def test_get_migrations_by_filters_instance_uuid(self):
        migrations = db.migration_get_all_by_filters(self.ctxt, filters={})
        for migration in migrations:
            filters = {'instance_uuid': migration['instance_uuid']}
            instance_migrations = db.migration_get_all_by_filters(
                self.ctxt, filters)
            self.assertEqual(1, len(instance_migrations))
            self.assertEqual(migration['instance_uuid'],
                             instance_migrations[0]['instance_uuid'])

    def test_get_migrations_by_filters_user_id(self):
        # Create two migrations with different user_id
        user_id1 = "fake_user_id"
        self._create(user_id=user_id1)
        user_id2 = "other_fake_user_id"
        self._create(user_id=user_id2)
        # Filter on only the first user_id
        filters = {"user_id": user_id1}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        # We should only get one migration back because we filtered on only
        # one of the two different user_id
        self.assertEqual(1, len(migrations))
        for migration in migrations:
            self.assertEqual(filters['user_id'], migration['user_id'])

    def test_get_migrations_by_filters_project_id(self):
        # Create two migrations with different project_id
        project_id1 = "fake_project_id"
        self._create(project_id=project_id1)
        project_id2 = "other_fake_project_id"
        self._create(project_id=project_id2)
        # Filter on only the first project_id
        filters = {"project_id": project_id1}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        # We should only get one migration back because we filtered on only
        # one of the two different project_id
        self.assertEqual(1, len(migrations))
        for migration in migrations:
            self.assertEqual(filters['project_id'], migration['project_id'])

    def test_get_migrations_by_filters_user_id_and_project_id(self):
        # Create two migrations with different user_id and project_id
        user_id1 = "fake_user_id"
        project_id1 = "fake_project_id"
        self._create(user_id=user_id1, project_id=project_id1)
        user_id2 = "other_fake_user_id"
        project_id2 = "other_fake_project_id"
        self._create(user_id=user_id2, project_id=project_id2)
        # Filter on only the first user_id and project_id
        filters = {"user_id": user_id1, "project_id": project_id1}
        migrations = db.migration_get_all_by_filters(self.ctxt, filters)
        # We should only get one migration back because we filtered on only
        # one of the two different user_id and project_id
        self.assertEqual(1, len(migrations))
        for migration in migrations:
            self.assertEqual(filters['user_id'], migration['user_id'])
            self.assertEqual(filters['project_id'], migration['project_id'])

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

    def test_migration_get_in_progress_by_instance(self):
        values = self._create(status='running',
                              migration_type="live-migration")
        results = db.migration_get_in_progress_by_instance(
                self.ctxt, values["instance_uuid"], "live-migration")

        self.assertEqual(1, len(results))

        for key in values:
            self.assertEqual(values[key], results[0][key])

        self.assertEqual("running", results[0]["status"])

    def test_migration_get_in_progress_by_instance_not_in_progress(self):
        values = self._create(migration_type="live-migration")
        results = db.migration_get_in_progress_by_instance(
                self.ctxt, values["instance_uuid"], "live-migration")

        self.assertEqual(0, len(results))

    def test_migration_get_in_progress_by_instance_not_live_migration(self):
        values = self._create(migration_type="resize")

        results = db.migration_get_in_progress_by_instance(
                self.ctxt, values["instance_uuid"], "live-migration")
        self.assertEqual(0, len(results))

        results = db.migration_get_in_progress_by_instance(
                self.ctxt, values["instance_uuid"])
        self.assertEqual(0, len(results))

    def test_migration_update_not_found(self):
        self.assertRaises(exception.MigrationNotFound,
                          db.migration_update, self.ctxt, 42, {})

    def test_get_migration_for_instance(self):
        migrations = db.migration_get_all_by_filters(self.ctxt, [])
        migration_id = migrations[0].id
        instance_uuid = migrations[0].instance_uuid
        instance_migration = db.migration_get_by_id_and_instance(
            self.ctxt, migration_id, instance_uuid)
        self.assertEqual(migration_id, instance_migration.id)
        self.assertEqual(instance_uuid, instance_migration.instance_uuid)

    def test_get_migration_for_instance_not_found(self):
        self.assertRaises(exception.MigrationNotFoundForInstance,
                          db.migration_get_by_id_and_instance, self.ctxt,
                          '500', '501')

    def _create_3_migration_after_time(self, time=None):
        time = time or timeutils.utcnow()
        tmp_time = time + datetime.timedelta(days=1)
        after_1hour = datetime.timedelta(hours=1)
        self._create(uuid=uuidsentinel.uuid_time1, created_at=tmp_time,
                     updated_at=tmp_time + after_1hour)
        tmp_time = time + datetime.timedelta(days=2)
        self._create(uuid=uuidsentinel.uuid_time2, created_at=tmp_time,
                     updated_at=tmp_time + after_1hour)
        tmp_time = time + datetime.timedelta(days=3)
        self._create(uuid=uuidsentinel.uuid_time3, created_at=tmp_time,
                     updated_at=tmp_time + after_1hour)

    def test_get_migrations_by_filters_with_limit(self):
        migrations = db.migration_get_all_by_filters(self.ctxt, {}, limit=3)
        self.assertEqual(3, len(migrations))

    def test_get_migrations_by_filters_with_limit_marker(self):
        self._create_3_migration_after_time()
        # order by created_at, desc: time3, time2, time1
        migrations = db.migration_get_all_by_filters(
            self.ctxt, {}, limit=2, marker=uuidsentinel.uuid_time3)
        # time3 as marker: time2, time1
        self.assertEqual(2, len(migrations))
        self.assertEqual(migrations[0]['uuid'], uuidsentinel.uuid_time2)
        self.assertEqual(migrations[1]['uuid'], uuidsentinel.uuid_time1)
        # time3 as marker, limit 2: time3, time2
        migrations = db.migration_get_all_by_filters(
            self.ctxt, {}, limit=1, marker=uuidsentinel.uuid_time3)
        self.assertEqual(1, len(migrations))
        self.assertEqual(migrations[0]['uuid'], uuidsentinel.uuid_time2)

    def test_get_migrations_by_filters_with_limit_marker_sort(self):
        self._create_3_migration_after_time()
        # order by created_at, desc: time3, time2, time1
        migrations = db.migration_get_all_by_filters(
            self.ctxt, {}, limit=2, marker=uuidsentinel.uuid_time3)
        # time2, time1
        self.assertEqual(2, len(migrations))
        self.assertEqual(migrations[0]['uuid'], uuidsentinel.uuid_time2)
        self.assertEqual(migrations[1]['uuid'], uuidsentinel.uuid_time1)

        # order by updated_at, desc: time1, time2, time3
        migrations = db.migration_get_all_by_filters(
            self.ctxt, {}, sort_keys=['updated_at'], sort_dirs=['asc'],
            limit=2, marker=uuidsentinel.uuid_time1)
        # time2, time3
        self.assertEqual(2, len(migrations))
        self.assertEqual(migrations[0]['uuid'], uuidsentinel.uuid_time2)
        self.assertEqual(migrations[1]['uuid'], uuidsentinel.uuid_time3)

    def test_get_migrations_by_filters_with_not_found_marker(self):
        self.assertRaises(exception.MarkerNotFound,
                          db.migration_get_all_by_filters, self.ctxt, {},
                          marker=uuidsentinel.not_found_marker)

    def test_get_migrations_by_filters_with_changes_since(self):
        changes_time = timeutils.utcnow(with_timezone=True)
        self._create_3_migration_after_time(changes_time)
        after_1day_2hours = datetime.timedelta(days=1, hours=2)
        filters = {"changes-since": changes_time + after_1day_2hours}
        migrations = db.migration_get_all_by_filters(
            self.ctxt, filters,
            sort_keys=['updated_at'], sort_dirs=['asc'])
        self.assertEqual(2, len(migrations))
        self.assertEqual(migrations[0]['uuid'], uuidsentinel.uuid_time2)
        self.assertEqual(migrations[1]['uuid'], uuidsentinel.uuid_time3)

    def test_get_migrations_by_filters_with_changes_before(self):
        changes_time = timeutils.utcnow(with_timezone=True)
        self._create_3_migration_after_time(changes_time)
        after_3day_2hours = datetime.timedelta(days=3, hours=2)
        filters = {"changes-before": changes_time + after_3day_2hours}
        migrations = db.migration_get_all_by_filters(
            self.ctxt, filters,
            sort_keys=['updated_at'], sort_dirs=['asc'])
        self.assertEqual(3, len(migrations))
        self.assertEqual(migrations[0]['uuid'], uuidsentinel.uuid_time1)
        self.assertEqual(migrations[1]['uuid'], uuidsentinel.uuid_time2)
        self.assertEqual(migrations[2]['uuid'], uuidsentinel.uuid_time3)


class ModelsObjectComparatorMixin(object):
    def _dict_from_object(self, obj, ignored_keys):
        if ignored_keys is None:
            ignored_keys = []

        return {k: v for k, v in obj.items()
                if k not in ignored_keys}

    def _assertEqualObjects(self, obj1, obj2, ignored_keys=None):
        obj1 = self._dict_from_object(obj1, ignored_keys)
        obj2 = self._dict_from_object(obj2, ignored_keys)

        self.assertEqual(len(obj1),
                         len(obj2),
                         "Keys mismatch: %s" %
                          str(set(obj1.keys()) ^ set(obj2.keys())))
        for key, value in obj1.items():
            self.assertEqual(value, obj2[key], "Key mismatch: %s" % key)

    def _assertEqualListsOfObjects(self, objs1, objs2, ignored_keys=None):
        obj_to_dict = lambda o: self._dict_from_object(o, ignored_keys)
        sort_key = lambda d: [d[k] for k in sorted(d)]
        conv_and_sort = lambda obj: sorted(map(obj_to_dict, obj), key=sort_key)

        self.assertEqual(conv_and_sort(objs1), conv_and_sort(objs2))

    def _assertEqualOrderedListOfObjects(self, objs1, objs2,
                                         ignored_keys=None):
        obj_to_dict = lambda o: self._dict_from_object(o, ignored_keys)
        conv = lambda objs: [obj_to_dict(obj) for obj in objs]

        self.assertEqual(conv(objs1), conv(objs2))

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

    def _test_security_group_rule_get_by_security_group(self, columns=None):
        instance = db.instance_create(self.ctxt,
                                      {'system_metadata': {'foo': 'bar'}})
        security_group = self._create_security_group({
                'instances': [instance]})
        security_group_rule = self._create_security_group_rule(
            {'parent_group': security_group, 'grantee_group': security_group})
        security_group_rule1 = self._create_security_group_rule(
            {'parent_group': security_group, 'grantee_group': security_group})
        found_rules = db.security_group_rule_get_by_security_group(
            self.ctxt, security_group['id'], columns_to_join=columns)
        self.assertEqual(len(found_rules), 2)
        rules_ids = [security_group_rule['id'], security_group_rule1['id']]
        for rule in found_rules:
            if columns is None:
                self.assertIn('grantee_group', dict(rule))
                self.assertIn('instances',
                              dict(rule.grantee_group))
                self.assertIn(
                    'system_metadata',
                    dict(rule.grantee_group.instances[0]))
                self.assertIn(rule['id'], rules_ids)
            else:
                self.assertNotIn('grantee_group', dict(rule))

    def test_security_group_rule_get_by_security_group(self):
        self._test_security_group_rule_get_by_security_group()

    def test_security_group_rule_get_by_security_group_no_joins(self):
        self._test_security_group_rule_get_by_security_group(columns=[])

    def test_security_group_rule_get_by_instance(self):
        instance = db.instance_create(self.ctxt, {})
        security_group = self._create_security_group({
                'instances': [instance]})
        security_group_rule = self._create_security_group_rule(
            {'parent_group': security_group, 'grantee_group': security_group})
        security_group_rule1 = self._create_security_group_rule(
            {'parent_group': security_group, 'grantee_group': security_group})
        security_group_rule_ids = [security_group_rule['id'],
                                   security_group_rule1['id']]
        found_rules = db.security_group_rule_get_by_instance(self.ctxt,
                                                             instance['uuid'])
        self.assertEqual(len(found_rules), 2)
        for rule in found_rules:
            self.assertIn('grantee_group', rule)
            self.assertIn(rule['id'], security_group_rule_ids)

    def test_security_group_rule_destroy(self):
        self._create_security_group({'name': 'fake1'})
        self._create_security_group({'name': 'fake2'})
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
        self._create_security_group_rule({})
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
        self.assertIsNotNone(security_group['id'])
        for key, value in self._get_base_values().items():
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
                columns_to_join=['instances',
                                 'rules']), security_group2)

    def test_security_group_destroy_with_instance(self):
        security_group1 = self._create_security_group({})

        instance = db.instance_create(self.ctxt, {})
        db.instance_add_security_group(self.ctxt, instance.uuid,
                                       security_group1.id)

        self.assertEqual(
            1,
            len(db.security_group_get_by_instance(self.ctxt, instance.uuid)))

        db.security_group_destroy(self.ctxt, security_group1['id'])

        self.assertEqual(
            0,
            len(db.security_group_get_by_instance(self.ctxt, instance.uuid)))

    def test_security_group_get(self):
        security_group1 = self._create_security_group({})
        self._create_security_group({'name': 'fake_sec_group2'})
        real_security_group = db.security_group_get(self.ctxt,
                                              security_group1['id'],
                                              columns_to_join=['instances',
                                                               'rules'])
        self._assertEqualObjects(security_group1,
                                 real_security_group)

    def test_security_group_get_with_instance_columns(self):
        instance = db.instance_create(self.ctxt,
                                      {'system_metadata': {'foo': 'bar'}})
        secgroup = self._create_security_group({'instances': [instance]})
        secgroup = db.security_group_get(
            self.ctxt, secgroup['id'],
            columns_to_join=['instances.system_metadata'])
        inst = secgroup.instances[0]
        self.assertIn('system_metadata', dict(inst).keys())

    def test_security_group_get_no_instances(self):
        instance = db.instance_create(self.ctxt, {})
        sid = self._create_security_group({'instances': [instance]})['id']

        security_group = db.security_group_get(self.ctxt, sid,
                                               columns_to_join=['instances'])
        self.assertIn('instances', security_group.__dict__)

        security_group = db.security_group_get(self.ctxt, sid)
        self.assertNotIn('instances', security_group.__dict__)

    def test_security_group_get_not_found_exception(self):
        self.assertRaises(exception.SecurityGroupNotFound,
                          db.security_group_get, self.ctxt, 100500)

    def test_security_group_get_by_name(self):
        security_group1 = self._create_security_group({'name': 'fake1'})
        security_group2 = self._create_security_group({'name': 'fake2'})

        real_security_group1 = db.security_group_get_by_name(
                                self.ctxt,
                                security_group1['project_id'],
                                security_group1['name'],
                                columns_to_join=None)
        real_security_group2 = db.security_group_get_by_name(
                                self.ctxt,
                                security_group2['project_id'],
                                security_group2['name'],
                                columns_to_join=None)
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

        self.assertEqual(expected, real)

    def test_security_group_ensure_default(self):
        self.ctxt.project_id = 'fake'
        self.ctxt.user_id = 'fake'
        self.assertEqual(0, len(db.security_group_get_by_project(
                                    self.ctxt,
                                    self.ctxt.project_id)))

        db.security_group_ensure_default(self.ctxt)

        security_groups = db.security_group_get_by_project(
                            self.ctxt,
                            self.ctxt.project_id)

        self.assertEqual(1, len(security_groups))
        self.assertEqual("default", security_groups[0]["name"])

    @mock.patch.object(sqlalchemy_api, '_security_group_get_by_names')
    def test_security_group_ensure_default_called_concurrently(self, sg_mock):
        # make sure NotFound is always raised here to trick Nova to insert the
        # duplicate security group entry
        sg_mock.side_effect = exception.NotFound

        # create the first db entry
        self.ctxt.project_id = 1
        db.security_group_ensure_default(self.ctxt)
        security_groups = db.security_group_get_by_project(
                            self.ctxt,
                            self.ctxt.project_id)
        self.assertEqual(1, len(security_groups))

        # create the second one and ensure the exception is handled properly
        default_group = db.security_group_ensure_default(self.ctxt)
        self.assertEqual('default', default_group.name)

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
                                    new_values,
                                    columns_to_join=['rules.grantee_group'])
        for key, value in new_values.items():
            self.assertEqual(updated_group[key], value)
        self.assertEqual(updated_group['rules'], [])

    def test_security_group_update_to_duplicate(self):
        self._create_security_group(
                {'name': 'fake1', 'project_id': 'fake_proj1'})
        security_group2 = self._create_security_group(
                {'name': 'fake1', 'project_id': 'fake_proj2'})

        self.assertRaises(exception.SecurityGroupExists,
                          db.security_group_update,
                          self.ctxt, security_group2['id'],
                          {'project_id': 'fake_proj1'})


@mock.patch('time.sleep', new=lambda x: None)
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
                ignored_keys=['metadata', 'system_metadata', 'info_cache',
                              'extra'])

    def _assertEqualListsOfInstances(self, list1, list2):
        self._assertEqualListsOfObjects(list1, list2,
                ignored_keys=['metadata', 'system_metadata', 'info_cache',
                              'extra'])

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

    @mock.patch.object(sqlalchemy_api, 'security_group_ensure_default')
    def test_instance_create_with_deadlock_retry(self, mock_sg):
        mock_sg.side_effect = [db_exc.DBDeadlock(), None]
        instance = self.create_instance_with_args()
        self.assertTrue(uuidutils.is_uuid_like(instance['uuid']))

    def test_instance_create_with_object_values(self):
        values = {
            'access_ip_v4': netaddr.IPAddress('1.2.3.4'),
            'access_ip_v6': netaddr.IPAddress('::1'),
            }
        dt_keys = ('created_at', 'deleted_at', 'updated_at',
                   'launched_at', 'terminated_at')
        dt = timeutils.utcnow()
        dt_utc = dt.replace(tzinfo=iso8601.UTC)
        for key in dt_keys:
            values[key] = dt_utc
        inst = db.instance_create(self.ctxt, values)
        self.assertEqual(inst['access_ip_v4'], '1.2.3.4')
        self.assertEqual(inst['access_ip_v6'], '::1')
        for key in dt_keys:
            self.assertEqual(inst[key], dt)

    def test_instance_update_with_object_values(self):
        values = {
            'access_ip_v4': netaddr.IPAddress('1.2.3.4'),
            'access_ip_v6': netaddr.IPAddress('::1'),
            }
        dt_keys = ('created_at', 'deleted_at', 'updated_at',
                   'launched_at', 'terminated_at')
        dt = timeutils.utcnow()
        dt_utc = dt.replace(tzinfo=iso8601.UTC)
        for key in dt_keys:
            values[key] = dt_utc
        inst = db.instance_create(self.ctxt, {})
        inst = db.instance_update(self.ctxt, inst['uuid'], values)
        self.assertEqual(inst['access_ip_v4'], '1.2.3.4')
        self.assertEqual(inst['access_ip_v6'], '::1')
        for key in dt_keys:
            self.assertEqual(inst[key], dt)

    def test_instance_update_no_metadata_clobber(self):
        meta = {'foo': 'bar'}
        sys_meta = {'sfoo': 'sbar'}
        values = {
            'metadata': meta,
            'system_metadata': sys_meta,
            }
        inst = db.instance_create(self.ctxt, {})
        inst = db.instance_update(self.ctxt, inst['uuid'], values)
        self.assertEqual(meta, utils.metadata_to_dict(inst['metadata']))
        self.assertEqual(sys_meta,
                         utils.metadata_to_dict(inst['system_metadata']))

    def test_instance_get_all_with_meta(self):
        self.create_instance_with_args()
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
        self.assertEqual(expected, actual["created_at"])

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

    def test_instance_get_all_by_filters_empty_list_filter(self):
        filters = {'uuid': []}
        instances = db.instance_get_all_by_filters_sort(self.ctxt, filters)
        self.assertEqual([], instances)

    @mock.patch('nova.db.sqlalchemy.api.undefer')
    @mock.patch('nova.db.sqlalchemy.api.joinedload')
    def test_instance_get_all_by_filters_extra_columns(self,
                                                       mock_joinedload,
                                                       mock_undefer):
        db.instance_get_all_by_filters_sort(
            self.ctxt, {},
            columns_to_join=['info_cache', 'extra.pci_requests'])
        mock_joinedload.assert_called_once_with('info_cache')
        mock_undefer.assert_called_once_with('extra.pci_requests')

    @mock.patch('nova.db.sqlalchemy.api.undefer')
    @mock.patch('nova.db.sqlalchemy.api.joinedload')
    def test_instance_get_active_by_window_extra_columns(self,
                                                         mock_joinedload,
                                                         mock_undefer):
        now = datetime.datetime(2013, 10, 10, 17, 16, 37, 156701)
        db.instance_get_active_by_window_joined(
            self.ctxt, now,
            columns_to_join=['info_cache', 'extra.pci_requests'])
        mock_joinedload.assert_called_once_with('info_cache')
        mock_undefer.assert_called_once_with('extra.pci_requests')

    def test_instance_get_all_by_filters_with_meta(self):
        self.create_instance_with_args()
        for inst in db.instance_get_all_by_filters(self.ctxt, {}):
            meta = utils.metadata_to_dict(inst['metadata'])
            self.assertEqual(meta, self.sample_data['metadata'])
            sys_meta = utils.metadata_to_dict(inst['system_metadata'])
            self.assertEqual(sys_meta, self.sample_data['system_metadata'])

    def test_instance_get_all_by_filters_without_meta(self):
        self.create_instance_with_args()
        result = db.instance_get_all_by_filters(self.ctxt, {},
                                                columns_to_join=[])
        for inst in result:
            meta = utils.metadata_to_dict(inst['metadata'])
            self.assertEqual(meta, {})
            sys_meta = utils.metadata_to_dict(inst['system_metadata'])
            self.assertEqual(sys_meta, {})

    def test_instance_get_all_by_filters_with_fault(self):
        inst = self.create_instance_with_args()
        result = db.instance_get_all_by_filters(self.ctxt, {},
                                                columns_to_join=['fault'])
        self.assertIsNone(result[0]['fault'])
        db.instance_fault_create(self.ctxt,
                                 {'instance_uuid': inst['uuid'],
                                  'code': 123})
        fault2 = db.instance_fault_create(self.ctxt,
                                          {'instance_uuid': inst['uuid'],
                                           'code': 123})
        result = db.instance_get_all_by_filters(self.ctxt, {},
                                                columns_to_join=['fault'])
        # Make sure we get the latest fault
        self.assertEqual(fault2['id'], result[0]['fault']['id'])

    def test_instance_get_all_by_filters(self):
        instances = [self.create_instance_with_args() for i in range(3)]
        filtered_instances = db.instance_get_all_by_filters(self.ctxt, {})
        self._assertEqualListsOfInstances(instances, filtered_instances)

    def test_instance_get_all_by_filters_zero_limit(self):
        self.create_instance_with_args()
        instances = db.instance_get_all_by_filters(self.ctxt, {}, limit=0)
        self.assertEqual([], instances)

    def test_instance_metadata_get_multi(self):
        uuids = [self.create_instance_with_args()['uuid'] for i in range(3)]

        @sqlalchemy_api.pick_context_manager_reader
        def test(context):
            return sqlalchemy_api._instance_metadata_get_multi(
                context, uuids)

        meta = test(self.ctxt)
        for row in meta:
            self.assertIn(row['instance_uuid'], uuids)

    @mock.patch.object(query.Query, 'filter')
    def test_instance_metadata_get_multi_no_uuids(self, mock_query_filter):
        with sqlalchemy_api.main_context_manager.reader.using(self.ctxt):
            sqlalchemy_api._instance_metadata_get_multi(self.ctxt, [])
        self.assertFalse(mock_query_filter.called)

    def test_instance_system_system_metadata_get_multi(self):
        uuids = [self.create_instance_with_args()['uuid'] for i in range(3)]

        @sqlalchemy_api.pick_context_manager_reader
        def test(context):
            return sqlalchemy_api._instance_system_metadata_get_multi(
                context, uuids)

        sys_meta = test(self.ctxt)
        for row in sys_meta:
            self.assertIn(row['instance_uuid'], uuids)

    @mock.patch.object(query.Query, 'filter')
    def test_instance_system_metadata_get_multi_no_uuids(self,
                                               mock_query_filter):
        sqlalchemy_api._instance_system_metadata_get_multi(self.ctxt, [])
        self.assertFalse(mock_query_filter.called)

    def test_instance_get_all_by_filters_regex(self):
        i1 = self.create_instance_with_args(display_name='test1')
        i2 = self.create_instance_with_args(display_name='teeeest2')
        self.create_instance_with_args(display_name='diff')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'display_name': 't.*st.'})
        self._assertEqualListsOfInstances(result, [i1, i2])

    def test_instance_get_all_by_filters_changes_since(self):
        i1 = self.create_instance_with_args(updated_at=
                                            '2013-12-05T15:03:25.000000')
        i2 = self.create_instance_with_args(updated_at=
                                            '2013-12-05T15:03:26.000000')
        changes_since = iso8601.parse_date('2013-12-05T15:03:25.000000')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'changes-since':
                                                 changes_since})
        self._assertEqualListsOfInstances([i1, i2], result)

        changes_since = iso8601.parse_date('2013-12-05T15:03:26.000000')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'changes-since':
                                                 changes_since})
        self._assertEqualListsOfInstances([i2], result)

        db.instance_destroy(self.ctxt, i1['uuid'])
        filters = {}
        filters['changes-since'] = changes_since
        filters['marker'] = i1['uuid']
        result = db.instance_get_all_by_filters(self.ctxt,
                                                filters)
        self._assertEqualListsOfInstances([i2], result)

    def test_instance_get_all_by_filters_changes_before(self):
        i1 = self.create_instance_with_args(updated_at=
                                            '2013-12-05T15:03:25.000000')
        i2 = self.create_instance_with_args(updated_at=
                                            '2013-12-05T15:03:26.000000')
        changes_before = iso8601.parse_date('2013-12-05T15:03:26.000000')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'changes-before':
                                                 changes_before})
        self._assertEqualListsOfInstances([i1, i2], result)

        changes_before = iso8601.parse_date('2013-12-05T15:03:25.000000')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'changes-before':
                                                 changes_before})
        self._assertEqualListsOfInstances([i1], result)

        db.instance_destroy(self.ctxt, i2['uuid'])
        filters = {}
        filters['changes-before'] = changes_before
        filters['marker'] = i2['uuid']
        result = db.instance_get_all_by_filters(self.ctxt,
                                                filters)
        self._assertEqualListsOfInstances([i1], result)

    def test_instance_get_all_by_filters_changes_time_period(self):
        i1 = self.create_instance_with_args(updated_at=
                                            '2013-12-05T15:03:25.000000')
        i2 = self.create_instance_with_args(updated_at=
                                            '2013-12-05T15:03:26.000000')
        i3 = self.create_instance_with_args(updated_at=
                                            '2013-12-05T15:03:27.000000')
        changes_since = iso8601.parse_date('2013-12-05T15:03:25.000000')
        changes_before = iso8601.parse_date('2013-12-05T15:03:27.000000')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'changes-since':
                                                 changes_since,
                                                 'changes-before':
                                                 changes_before})
        self._assertEqualListsOfInstances([i1, i2, i3], result)

        changes_since = iso8601.parse_date('2013-12-05T15:03:26.000000')
        changes_before = iso8601.parse_date('2013-12-05T15:03:27.000000')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'changes-since':
                                                 changes_since,
                                                 'changes-before':
                                                 changes_before})
        self._assertEqualListsOfInstances([i2, i3], result)

        db.instance_destroy(self.ctxt, i1['uuid'])
        filters = {}
        filters['changes-since'] = changes_since
        filters['changes-before'] = changes_before
        filters['marker'] = i1['uuid']
        result = db.instance_get_all_by_filters(self.ctxt,
                                                filters)
        self._assertEqualListsOfInstances([i2, i3], result)

    def test_instance_get_all_by_filters_exact_match(self):
        instance = self.create_instance_with_args(host='host1')
        self.create_instance_with_args(host='host12')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'host': 'host1'})
        self._assertEqualListsOfInstances([instance], result)

    def test_instance_get_all_by_filters_locked_key_true(self):
        instance = self.create_instance_with_args(locked=True)
        self.create_instance_with_args(locked=False)
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'locked': True})
        self._assertEqualListsOfInstances([instance], result)

    def test_instance_get_all_by_filters_locked_key_false(self):
        self.create_instance_with_args(locked=True)
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'locked': False})
        self._assertEqualListsOfInstances([], result)

    def test_instance_get_all_by_filters_metadata(self):
        instance = self.create_instance_with_args(metadata={'foo': 'bar'})
        self.create_instance_with_args()
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'metadata': {'foo': 'bar'}})
        self._assertEqualListsOfInstances([instance], result)

    def test_instance_get_all_by_filters_system_metadata(self):
        instance = self.create_instance_with_args(
                system_metadata={'foo': 'bar'})
        self.create_instance_with_args()
        result = db.instance_get_all_by_filters(self.ctxt,
                {'system_metadata': {'foo': 'bar'}})
        self._assertEqualListsOfInstances([instance], result)

    def test_instance_get_all_by_filters_unicode_value(self):
        i1 = self.create_instance_with_args(display_name=u'test♥')
        i2 = self.create_instance_with_args(display_name=u'test')
        i3 = self.create_instance_with_args(display_name=u'test♥test')
        self.create_instance_with_args(display_name='diff')
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'display_name': u'test'})
        self._assertEqualListsOfInstances([i1, i2, i3], result)

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'display_name': u'test♥'})
        self._assertEqualListsOfInstances(result, [i1, i3])

    def test_instance_get_by_uuid(self):
        inst = self.create_instance_with_args()
        result = db.instance_get_by_uuid(self.ctxt, inst['uuid'])
        # instance_create() will return a fault=None, so delete it before
        # comparing the result of instance_get_by_uuid()
        del inst.fault
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
                          'deleted', 'deleted_at', 'info_cache',
                          'pci_devices', 'extra'])

    def test_instance_get_all_by_filters_deleted_and_soft_deleted(self):
        inst1 = self.create_instance_with_args()
        inst2 = self.create_instance_with_args(vm_state=vm_states.SOFT_DELETED)
        self.create_instance_with_args()
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'deleted': True})
        self._assertEqualListsOfObjects([inst1, inst2], result,
            ignored_keys=['metadata', 'system_metadata',
                          'deleted', 'deleted_at', 'info_cache',
                          'pci_devices', 'extra'])

    def test_instance_get_all_by_filters_deleted_no_soft_deleted(self):
        inst1 = self.create_instance_with_args()
        self.create_instance_with_args(vm_state=vm_states.SOFT_DELETED)
        self.create_instance_with_args()
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'deleted': True,
                                                 'soft_deleted': False})
        self._assertEqualListsOfObjects([inst1], result,
                ignored_keys=['deleted', 'deleted_at', 'metadata',
                              'system_metadata', 'info_cache', 'pci_devices',
                              'extra'])

    def test_instance_get_all_by_filters_alive_and_soft_deleted(self):
        inst1 = self.create_instance_with_args()
        inst2 = self.create_instance_with_args(vm_state=vm_states.SOFT_DELETED)
        inst3 = self.create_instance_with_args()
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'deleted': False,
                                                 'soft_deleted': True})
        self._assertEqualListsOfInstances([inst2, inst3], result)

    def test_instance_get_all_by_filters_not_deleted(self):
        inst1 = self.create_instance_with_args()
        self.create_instance_with_args(vm_state=vm_states.SOFT_DELETED)
        inst3 = self.create_instance_with_args()
        inst4 = self.create_instance_with_args(vm_state=vm_states.ACTIVE)
        db.instance_destroy(self.ctxt, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'deleted': False})
        self.assertIsNone(inst3.vm_state)
        self._assertEqualListsOfInstances([inst3, inst4], result)

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

    def test_instance_get_all_by_host_and_node(self):
        instance = self.create_instance_with_args(
            system_metadata={'foo': 'bar'})
        result = db.instance_get_all_by_host_and_node(
            self.ctxt, 'h1', 'n1',
            columns_to_join=['system_metadata', 'extra'])
        self.assertEqual(instance['uuid'], result[0]['uuid'])
        self.assertEqual('bar', result[0]['system_metadata'][0]['value'])
        self.assertEqual(instance['uuid'], result[0]['extra']['instance_uuid'])

    @mock.patch('nova.db.sqlalchemy.api._instances_fill_metadata')
    @mock.patch('nova.db.sqlalchemy.api._instance_get_all_query')
    def test_instance_get_all_by_host_and_node_fills_manually(self,
                                                              mock_getall,
                                                              mock_fill):
        db.instance_get_all_by_host_and_node(
            self.ctxt, 'h1', 'n1',
            columns_to_join=['metadata', 'system_metadata', 'extra', 'foo'])
        self.assertEqual(sorted(['extra', 'foo']),
                         sorted(mock_getall.call_args[1]['joins']))
        self.assertEqual(sorted(['metadata', 'system_metadata']),
                         sorted(mock_fill.call_args[1]['manual_joins']))

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

    def test_instance_get_all_by_grantee_security_groups(self):
        instance1 = self.create_instance_with_args()
        instance2 = self.create_instance_with_args()
        instance3 = self.create_instance_with_args()
        secgroup1 = self._create_security_group(
            {'name': 'fake-secgroup1', 'instances': [instance1]})
        secgroup2 = self._create_security_group(
            {'name': 'fake-secgroup2', 'instances': [instance1]})
        secgroup3 = self._create_security_group(
            {'name': 'fake-secgroup3', 'instances': [instance2]})
        secgroup4 = self._create_security_group(
            {'name': 'fake-secgroup4', 'instances': [instance2, instance3]})
        self._create_security_group_rule({'grantee_group': secgroup1,
                                          'parent_group': secgroup3})
        self._create_security_group_rule({'grantee_group': secgroup2,
                                          'parent_group': secgroup4})
        group_ids = [secgroup['id'] for secgroup in [secgroup1, secgroup2]]
        instances = db.instance_get_all_by_grantee_security_groups(self.ctxt,
                                                                   group_ids)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertEqual(len(instances), 2)
        self.assertIn(instance2['uuid'], instance_uuids)
        self.assertIn(instance3['uuid'], instance_uuids)

    def test_instance_get_all_by_grantee_security_groups_empty_group_ids(self):
        results = db.instance_get_all_by_grantee_security_groups(self.ctxt, [])
        self.assertEqual([], results)

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
                          'metadata', 'system_metadata', 'pci_devices',
                          'extra'])
        db.instance_update(self.ctxt, instance['uuid'], {"task_state": None})

        # Ensure the newly rebooted instance is not returned.
        self.create_instance_with_args(task_state="rebooting",
                                       updated_at=timeutils.utcnow())
        results = db.instance_get_all_hung_in_rebooting(self.ctxt, 10)
        self.assertEqual([], results)

    def test_instance_update_with_expected_vm_state(self):
        instance = self.create_instance_with_args(vm_state='foo')
        db.instance_update(self.ctxt, instance['uuid'], {'host': 'h1',
                                       'expected_vm_state': ('foo', 'bar')})

    def test_instance_update_with_unexpected_vm_state(self):
        instance = self.create_instance_with_args(vm_state='foo')
        self.assertRaises(exception.InstanceUpdateConflict,
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

    def test_delete_block_device_mapping_on_instance_destroy(self):
        # Makes sure that the block device mapping is deleted when the
        # related instance is deleted.
        ctxt = context.get_admin_context()
        instance = db.instance_create(ctxt, dict(display_name='bdm-test'))
        bdm = {
            'volume_id': uuidsentinel.uuid1,
            'device_name': '/dev/vdb',
            'instance_uuid': instance['uuid'],
        }
        bdm = db.block_device_mapping_create(ctxt, bdm, legacy=False)
        db.instance_destroy(ctxt, instance['uuid'])
        # make sure the bdm is deleted as well
        bdms = db.block_device_mapping_get_all_by_instance(
            ctxt, instance['uuid'])
        self.assertEqual([], bdms)

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

    def test_delete_instance_faults_on_instance_destroy(self):
        ctxt = context.get_admin_context()
        uuid = uuidsentinel.uuid1
        # Create faults
        db.instance_create(ctxt, {'uuid': uuid})

        fault_values = {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuid,
            'code': 404,
            'host': 'localhost'
        }
        fault = db.instance_fault_create(ctxt, fault_values)

        # Retrieve the fault to ensure it was successfully added
        faults = db.instance_fault_get_by_instance_uuids(ctxt, [uuid])
        self.assertEqual(1, len(faults[uuid]))
        self._assertEqualObjects(fault, faults[uuid][0])
        db.instance_destroy(ctxt, uuid)
        faults = db.instance_fault_get_by_instance_uuids(ctxt, [uuid])
        # Make sure instance faults is deleted as well
        self.assertEqual(0, len(faults[uuid]))

    def test_delete_migrations_on_instance_destroy(self):
        ctxt = context.get_admin_context()
        uuid = uuidsentinel.uuid1
        db.instance_create(ctxt, {'uuid': uuid})

        migrations_values = {'instance_uuid': uuid}
        migration = db.migration_create(ctxt, migrations_values)

        migrations = db.migration_get_all_by_filters(
            ctxt, {'instance_uuid': uuid})

        self.assertEqual(1, len(migrations))
        self._assertEqualObjects(migration, migrations[0])

        instance = db.instance_destroy(ctxt, uuid)
        migrations = db.migration_get_all_by_filters(
            ctxt, {'instance_uuid': uuid})

        self.assertTrue(instance.deleted)
        self.assertEqual(0, len(migrations))

    def test_delete_virtual_interfaces_on_instance_destroy(self):
        # Create the instance.
        ctxt = context.get_admin_context()
        uuid = uuidsentinel.uuid1
        db.instance_create(ctxt, {'uuid': uuid})
        # Create the VirtualInterface.
        db.virtual_interface_create(ctxt, {'instance_uuid': uuid})
        # Make sure the vif is tied to the instance.
        vifs = db.virtual_interface_get_by_instance(ctxt, uuid)
        self.assertEqual(1, len(vifs))
        # Destroy the instance and verify the vif is gone as well.
        db.instance_destroy(ctxt, uuid)
        self.assertEqual(
            0, len(db.virtual_interface_get_by_instance(ctxt, uuid)))

    def test_instance_update_and_get_original(self):
        instance = self.create_instance_with_args(vm_state='building')
        (old_ref, new_ref) = db.instance_update_and_get_original(self.ctxt,
                            instance['uuid'], {'vm_state': 'needscoffee'})
        self.assertEqual('building', old_ref['vm_state'])
        self.assertEqual('needscoffee', new_ref['vm_state'])

    def test_instance_update_and_get_original_metadata(self):
        instance = self.create_instance_with_args()
        columns_to_join = ['metadata']
        (old_ref, new_ref) = db.instance_update_and_get_original(
            self.ctxt, instance['uuid'], {'vm_state': 'needscoffee'},
            columns_to_join=columns_to_join)
        meta = utils.metadata_to_dict(new_ref['metadata'])
        self.assertEqual(meta, self.sample_data['metadata'])
        sys_meta = utils.metadata_to_dict(new_ref['system_metadata'])
        self.assertEqual(sys_meta, {})

    def test_instance_update_and_get_original_metadata_none_join(self):
        instance = self.create_instance_with_args()
        (old_ref, new_ref) = db.instance_update_and_get_original(
            self.ctxt, instance['uuid'], {'metadata': {'mk1': 'mv3'}})
        meta = utils.metadata_to_dict(new_ref['metadata'])
        self.assertEqual(meta, {'mk1': 'mv3'})

    def test_instance_update_and_get_original_no_conflict_on_session(self):
        @sqlalchemy_api.pick_context_manager_writer
        def test(context):
            instance = self.create_instance_with_args()
            (old_ref, new_ref) = db.instance_update_and_get_original(
                context, instance['uuid'], {'metadata': {'mk1': 'mv3'}})

            # test some regular persisted fields
            self.assertEqual(old_ref.uuid, new_ref.uuid)
            self.assertEqual(old_ref.project_id, new_ref.project_id)

            # after a copy operation, we can assert:

            # 1. the two states have their own InstanceState
            old_insp = inspect(old_ref)
            new_insp = inspect(new_ref)
            self.assertNotEqual(old_insp, new_insp)

            # 2. only one of the objects is still in our Session
            self.assertIs(new_insp.session, self.ctxt.session)
            self.assertIsNone(old_insp.session)

            # 3. The "new" object remains persistent and ready
            # for updates
            self.assertTrue(new_insp.persistent)

            # 4. the "old" object is detached from this Session.
            self.assertTrue(old_insp.detached)

        test(self.ctxt)

    def test_instance_update_and_get_original_conflict_race(self):
        # Ensure that we correctly process expected_task_state when retrying
        # due to an unknown conflict

        # This requires modelling the MySQL read view, which means that if we
        # have read something in the current transaction and we read it again,
        # we will read the same data every time even if another committed
        # transaction has since altered that data. In this test we have an
        # instance whose task state was originally None, but has been set to
        # SHELVING by another, concurrent transaction. Therefore the first time
        # we read the data we will read None, but when we restart the
        # transaction we will read the correct data.

        instance = self.create_instance_with_args(
                task_state=task_states.SHELVING)

        instance_out_of_date = copy.copy(instance)
        instance_out_of_date['task_state'] = None

        # NOTE(mdbooth): SQLA magic which makes this dirty object look
        # like a freshly loaded one.
        sqla_session.make_transient(instance_out_of_date)
        sqla_session.make_transient_to_detached(instance_out_of_date)

        # update_on_match will fail first time because the actual task state
        # (SHELVING) doesn't match the expected task state (None). However,
        # we ensure that the first time we fetch the instance object we get
        # out-of-date data. This forces us to retry the operation to find out
        # what really went wrong.
        with mock.patch.object(sqlalchemy_api, '_instance_get_by_uuid',
                    side_effect=[instance_out_of_date, instance]), \
                 mock.patch.object(sqlalchemy_api, '_instance_update',
                     side_effect=sqlalchemy_api._instance_update):
            self.assertRaises(exception.UnexpectedTaskStateError,
                              db.instance_update_and_get_original,
                              self.ctxt, instance['uuid'],
                              {'expected_task_state': [None]})
            sqlalchemy_api._instance_update.assert_has_calls([
                mock.call(self.ctxt, instance['uuid'],
                          {'expected_task_state': [None]}, None,
                          original=instance_out_of_date),
                mock.call(self.ctxt, instance['uuid'],
                          {'expected_task_state': [None]}, None,
                          original=instance),
            ])

    def test_instance_update_and_get_original_conflict_race_fallthrough(self):
        # Ensure that is update_match continuously fails for no discernable
        # reason, we evantually raise UnknownInstanceUpdateConflict
        instance = self.create_instance_with_args()

        # Reproduce the conditions of a race between fetching and updating the
        # instance by making update_on_match fail for no discernable reason.
        with mock.patch.object(update_match, 'update_on_match',
                        side_effect=update_match.NoRowsMatched):
            self.assertRaises(exception.UnknownInstanceUpdateConflict,
                              db.instance_update_and_get_original,
                              self.ctxt,
                              instance['uuid'],
                              {'metadata': {'mk1': 'mv3'}})

    def test_instance_update_and_get_original_expected_host(self):
        # Ensure that we allow update when expecting a host field
        instance = self.create_instance_with_args()

        (orig, new) = db.instance_update_and_get_original(
            self.ctxt, instance['uuid'], {'host': None},
            expected={'host': 'h1'})

        self.assertIsNone(new['host'])

    def test_instance_update_and_get_original_expected_host_fail(self):
        # Ensure that we detect a changed expected host and raise
        # InstanceUpdateConflict
        instance = self.create_instance_with_args()

        try:
            db.instance_update_and_get_original(
                self.ctxt, instance['uuid'], {'host': None},
                expected={'host': 'h2'})
        except exception.InstanceUpdateConflict as ex:
            self.assertEqual(ex.kwargs['instance_uuid'], instance['uuid'])
            self.assertEqual(ex.kwargs['actual'], {'host': 'h1'})
            self.assertEqual(ex.kwargs['expected'], {'host': ['h2']})
        else:
            self.fail('InstanceUpdateConflict was not raised')

    def test_instance_update_and_get_original_expected_host_none(self):
        # Ensure that we allow update when expecting a host field of None
        instance = self.create_instance_with_args(host=None)

        (old, new) = db.instance_update_and_get_original(
            self.ctxt, instance['uuid'], {'host': 'h1'},
            expected={'host': None})
        self.assertEqual('h1', new['host'])

    def test_instance_update_and_get_original_expected_host_none_fail(self):
        # Ensure that we detect a changed expected host of None and raise
        # InstanceUpdateConflict
        instance = self.create_instance_with_args()

        try:
            db.instance_update_and_get_original(
                self.ctxt, instance['uuid'], {'host': None},
                expected={'host': None})
        except exception.InstanceUpdateConflict as ex:
            self.assertEqual(ex.kwargs['instance_uuid'], instance['uuid'])
            self.assertEqual(ex.kwargs['actual'], {'host': 'h1'})
            self.assertEqual(ex.kwargs['expected'], {'host': [None]})
        else:
            self.fail('InstanceUpdateConflict was not raised')

    def test_instance_update_and_get_original_expected_task_state_single_fail(self):  # noqa
        # Ensure that we detect a changed expected task and raise
        # UnexpectedTaskStateError
        instance = self.create_instance_with_args()

        try:
            db.instance_update_and_get_original(
                self.ctxt, instance['uuid'], {
                    'host': None,
                    'expected_task_state': task_states.SCHEDULING
                })
        except exception.UnexpectedTaskStateError as ex:
            self.assertEqual(ex.kwargs['instance_uuid'], instance['uuid'])
            self.assertEqual(ex.kwargs['actual'], {'task_state': None})
            self.assertEqual(ex.kwargs['expected'],
                             {'task_state': [task_states.SCHEDULING]})
        else:
            self.fail('UnexpectedTaskStateError was not raised')

    def test_instance_update_and_get_original_expected_task_state_single_pass(self):  # noqa
        # Ensure that we allow an update when expected task is correct
        instance = self.create_instance_with_args()

        (orig, new) = db.instance_update_and_get_original(
            self.ctxt, instance['uuid'], {
                'host': None,
                'expected_task_state': None
            })
        self.assertIsNone(new['host'])

    def test_instance_update_and_get_original_expected_task_state_multi_fail(self):  # noqa
        # Ensure that we detect a changed expected task and raise
        # UnexpectedTaskStateError when there are multiple potential expected
        # tasks
        instance = self.create_instance_with_args()

        try:
            db.instance_update_and_get_original(
                self.ctxt, instance['uuid'], {
                    'host': None,
                    'expected_task_state': [task_states.SCHEDULING,
                                            task_states.REBUILDING]
                })
        except exception.UnexpectedTaskStateError as ex:
            self.assertEqual(ex.kwargs['instance_uuid'], instance['uuid'])
            self.assertEqual(ex.kwargs['actual'], {'task_state': None})
            self.assertEqual(ex.kwargs['expected'],
                             {'task_state': [task_states.SCHEDULING,
                                              task_states.REBUILDING]})
        else:
            self.fail('UnexpectedTaskStateError was not raised')

    def test_instance_update_and_get_original_expected_task_state_multi_pass(self):  # noqa
        # Ensure that we allow an update when expected task is in a list of
        # expected tasks
        instance = self.create_instance_with_args()

        (orig, new) = db.instance_update_and_get_original(
            self.ctxt, instance['uuid'], {
                'host': None,
                'expected_task_state': [task_states.SCHEDULING, None]
            })
        self.assertIsNone(new['host'])

    def test_instance_update_and_get_original_expected_task_state_deleting(self):  # noqa
        # Ensure that we raise UnexpectedDeletingTaskStateError when task state
        # is not as expected, and it is DELETING
        instance = self.create_instance_with_args(
            task_state=task_states.DELETING)

        try:
            db.instance_update_and_get_original(
                self.ctxt, instance['uuid'], {
                    'host': None,
                    'expected_task_state': task_states.SCHEDULING
                })
        except exception.UnexpectedDeletingTaskStateError as ex:
            self.assertEqual(ex.kwargs['instance_uuid'], instance['uuid'])
            self.assertEqual(ex.kwargs['actual'],
                             {'task_state': task_states.DELETING})
            self.assertEqual(ex.kwargs['expected'],
                             {'task_state': [task_states.SCHEDULING]})
        else:
            self.fail('UnexpectedDeletingTaskStateError was not raised')

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
        self.ctxt.read_deleted = 'yes'
        self.assertNotIn('gigawatts',
            db.instance_system_metadata_get(self.ctxt, instance.uuid))

    def test_security_group_in_use(self):
        db.instance_create(self.ctxt, dict(host='foo'))

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

        self.assertRaises(exception.InvalidUUID,
                          db.instance_floating_address_get_all,
                          ctxt, 'invalid_uuid')

    def test_instance_stringified_ips(self):
        instance = self.create_instance_with_args()
        instance = db.instance_update(
            self.ctxt, instance['uuid'],
            {'access_ip_v4': netaddr.IPAddress('1.2.3.4'),
             'access_ip_v6': netaddr.IPAddress('::1')})
        self.assertIsInstance(instance['access_ip_v4'], six.string_types)
        self.assertIsInstance(instance['access_ip_v6'], six.string_types)
        instance = db.instance_get_by_uuid(self.ctxt, instance['uuid'])
        self.assertIsInstance(instance['access_ip_v4'], six.string_types)
        self.assertIsInstance(instance['access_ip_v6'], six.string_types)

    @mock.patch('nova.db.sqlalchemy.api._check_instance_exists_in_project',
                return_value=None)
    def test_instance_destroy(self, mock_check_inst_exists):
        ctxt = context.get_admin_context()
        values = {
            'metadata': {'key': 'value'},
            'system_metadata': {'key': 'value'}
        }
        inst_uuid = self.create_instance_with_args(**values)['uuid']
        db.instance_tag_set(ctxt, inst_uuid, [u'tag1', u'tag2'])
        db.instance_destroy(ctxt, inst_uuid)

        self.assertRaises(exception.InstanceNotFound,
                          db.instance_get, ctxt, inst_uuid)
        self.assertIsNone(db.instance_info_cache_get(ctxt, inst_uuid))
        self.assertEqual({}, db.instance_metadata_get(ctxt, inst_uuid))
        self.assertEqual([], db.instance_tag_get_by_instance_uuid(
            ctxt, inst_uuid))

        _assert_instance_id_mapping(ctxt, self, inst_uuid)
        ctxt.read_deleted = 'yes'
        self.assertEqual(values['system_metadata'],
                         db.instance_system_metadata_get(ctxt, inst_uuid))

    def test_instance_destroy_already_destroyed(self):
        ctxt = context.get_admin_context()
        instance = self.create_instance_with_args()
        db.instance_destroy(ctxt, instance['uuid'])
        self.assertRaises(exception.InstanceNotFound,
                          db.instance_destroy, ctxt, instance['uuid'])

    def test_instance_destroy_hard(self):
        ctxt = context.get_admin_context()
        instance = self.create_instance_with_args()
        uuid = instance['uuid']
        utc_now = timeutils.utcnow()

        action_values = {
            'action': 'run_instance',
            'instance_uuid': uuid,
            'request_id': ctxt.request_id,
            'user_id': ctxt.user_id,
            'project_id': ctxt.project_id,
            'start_time': utc_now,
            'updated_at': utc_now,
            'message': 'action-message'
        }
        action = db.action_start(ctxt, action_values)

        action_event_values = {
            'event': 'schedule',
            'action_id': action['id'],
            'instance_uuid': uuid,
            'start_time': utc_now,
            'request_id': ctxt.request_id,
            'host': 'fake-host',
        }
        db.action_event_start(ctxt, action_event_values)

        security_group_values = {
            'name': 'fake_sec_group',
            'user_id': ctxt.user_id,
            'project_id': ctxt.project_id,
            'instances': []
            }
        security_group = db.security_group_create(ctxt, security_group_values)
        db.instance_add_security_group(ctxt, uuid, security_group['id'])

        instance_fault_values = {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuid,
            'code': 404,
            'host': 'localhost'
        }
        db.instance_fault_create(ctxt, instance_fault_values)

        bdm_values = {
            'instance_uuid': uuid,
            'device_name': '/dev/vda',
            'source_type': 'volume',
            'destination_type': 'volume',
        }
        block_dev = block_device.BlockDeviceDict(bdm_values)
        db.block_device_mapping_create(self.ctxt, block_dev, legacy=False)

        # Crate a second BDM that is soft-deleted to simulate that the
        # volume was detached and the BDM was deleted before the instance
        # was hard destroyed.
        bdm2_values = {
            'instance_uuid': uuid,
            'device_name': '/dev/vdb',
            'source_type': 'volume',
            'destination_type': 'volume',
        }
        block_dev2 = block_device.BlockDeviceDict(bdm2_values)
        bdm2 = db.block_device_mapping_create(
            self.ctxt, block_dev2, legacy=False)
        db.block_device_mapping_destroy(self.ctxt, bdm2.id)

        migration_values = {
            "status": "finished",
            "instance_uuid": uuid,
            "dest_compute": "fake_host2"
        }
        db.migration_create(self.ctxt, migration_values)

        db.virtual_interface_create(ctxt, {'instance_uuid': uuid})

        pool_values = {
            'address': '192.168.10.10',
            'username': 'user1',
            'password': 'passwd1',
            'console_type': 'type1',
            'public_hostname': 'public_host1',
            'host': 'host1',
            'compute_host': 'compute_host1',
        }
        console_pool = db.console_pool_create(ctxt, pool_values)
        console_values = {
            'instance_name': instance['name'],
            'instance_uuid': uuid,
            'password': 'pass',
            'port': 7878,
            'pool_id': console_pool['id']
        }
        db.console_create(self.ctxt, console_values)

        # Hard delete the instance
        db.instance_destroy(ctxt, uuid, hard_delete=True)

        # Check that related records are deleted
        with utils.temporary_mutation(ctxt, read_deleted="yes"):
            # Assert that all information related to the instance is not found
            # even using a context that can read soft deleted records.
            self.assertEqual(0, len(db.actions_get(ctxt, uuid)))
            self.assertEqual(0, len(db.action_events_get(ctxt, action['id'])))
            db_sg = db.security_group_get_by_name(
                ctxt, ctxt.project_id, security_group_values['name'])
            self.assertEqual(0, len(db_sg['instances']))
            instance_faults = db.instance_fault_get_by_instance_uuids(
                ctxt, [uuid])
            self.assertEqual(0, len(instance_faults[uuid]))
            inst_bdms = db.block_device_mapping_get_all_by_instance(ctxt, uuid)
            self.assertEqual(0, len(inst_bdms))
            filters = {"instance_uuid": uuid}
            inst_migrations = db.migration_get_all_by_filters(ctxt, filters)
            self.assertEqual(0, len(inst_migrations))
            vifs = db.virtual_interface_get_by_instance(ctxt, uuid)
            self.assertEqual(0, len(vifs))
            self.assertIsNone(db.instance_info_cache_get(ctxt, uuid))
            self.assertEqual({}, db.instance_metadata_get(ctxt, uuid))
            self.assertIsNone(db.instance_extra_get_by_instance_uuid(
                ctxt, uuid))
            system_meta = db.instance_system_metadata_get(ctxt, uuid)
            self.assertEqual({}, system_meta)
            _assert_instance_id_mapping(ctxt, self, uuid)
            self.assertRaises(exception.InstanceNotFound,
                              db.instance_destroy, ctxt, uuid)
            # NOTE(ttsiouts): Should these also be valid?
            # instance_consoles = db.console_get_all_by_instance(ctxt, uuid)
            # self.assertEqual(0, len(instance_consoles))
            # Also FixedIp has the instance_uuid as a foreign key

    def test_check_instance_exists(self):
        instance = self.create_instance_with_args()

        @sqlalchemy_api.pick_context_manager_reader
        def test(context):
            self.assertIsNone(sqlalchemy_api._check_instance_exists_in_project(
                context, instance['uuid']))

        test(self.ctxt)

    def test_check_instance_exists_non_existing_instance(self):
        @sqlalchemy_api.pick_context_manager_reader
        def test(ctxt):
            self.assertRaises(exception.InstanceNotFound,
                              sqlalchemy_api._check_instance_exists_in_project,
                              self.ctxt, '123')

        test(self.ctxt)

    def test_check_instance_exists_from_different_tenant(self):
        context1 = context.RequestContext('user1', 'project1')
        context2 = context.RequestContext('user2', 'project2')
        instance = self.create_instance_with_args(context=context1)

        @sqlalchemy_api.pick_context_manager_reader
        def test1(context):
            self.assertIsNone(sqlalchemy_api._check_instance_exists_in_project(
            context, instance['uuid']))

        test1(context1)

        @sqlalchemy_api.pick_context_manager_reader
        def test2(context):
            self.assertRaises(exception.InstanceNotFound,
                              sqlalchemy_api._check_instance_exists_in_project,
                              context, instance['uuid'])

        test2(context2)

    def test_check_instance_exists_admin_context(self):
        some_context = context.RequestContext('some_user', 'some_project')
        instance = self.create_instance_with_args(context=some_context)

        @sqlalchemy_api.pick_context_manager_reader
        def test(context):
            # Check that method works correctly with admin context
            self.assertIsNone(sqlalchemy_api._check_instance_exists_in_project(
                context, instance['uuid']))

        test(self.ctxt)


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
        db.instance_metadata_update(self.ctxt, instance['uuid'],
                                    {'new_key': 'new_value'}, False)
        metadata = db.instance_metadata_get(self.ctxt, instance['uuid'])
        self.assertEqual(metadata, {'key': 'value', 'new_key': 'new_value'})

        # This should leave only one key/value pair
        db.instance_metadata_update(self.ctxt, instance['uuid'],
                                    {'new_key': 'new_value'}, True)
        metadata = db.instance_metadata_get(self.ctxt, instance['uuid'])
        self.assertEqual(metadata, {'new_key': 'new_value'})


class InstanceExtraTestCase(test.TestCase):
    def setUp(self):
        super(InstanceExtraTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.instance = db.instance_create(self.ctxt, {})

    def test_instance_extra_get_by_uuid_instance_create(self):
        inst_extra = db.instance_extra_get_by_instance_uuid(
                self.ctxt, self.instance['uuid'])
        self.assertIsNotNone(inst_extra)

    def test_instance_extra_update_by_uuid(self):
        db.instance_extra_update_by_uuid(self.ctxt, self.instance['uuid'],
                                         {'numa_topology': 'changed',
                                          'trusted_certs': "['123', 'foo']",
                                          'resources': "['res0', 'res1']",
                                          })
        inst_extra = db.instance_extra_get_by_instance_uuid(
            self.ctxt, self.instance['uuid'])
        self.assertEqual('changed', inst_extra.numa_topology)
        # NOTE(jackie-truong): trusted_certs is stored as a Text type in
        # instance_extra and read as a list of strings
        self.assertEqual("['123', 'foo']", inst_extra.trusted_certs)
        self.assertEqual("['res0', 'res1']", inst_extra.resources)

    def test_instance_extra_update_by_uuid_and_create(self):
        @sqlalchemy_api.pick_context_manager_writer
        def test(context):
            sqlalchemy_api.model_query(context, models.InstanceExtra).\
                    filter_by(instance_uuid=self.instance['uuid']).\
                    delete()

        test(self.ctxt)

        inst_extra = db.instance_extra_get_by_instance_uuid(
            self.ctxt, self.instance['uuid'])
        self.assertIsNone(inst_extra)

        db.instance_extra_update_by_uuid(self.ctxt, self.instance['uuid'],
                                         {'numa_topology': 'changed'})

        inst_extra = db.instance_extra_get_by_instance_uuid(
            self.ctxt, self.instance['uuid'])
        self.assertEqual('changed', inst_extra.numa_topology)

    def test_instance_extra_get_with_columns(self):
        extra = db.instance_extra_get_by_instance_uuid(
            self.ctxt, self.instance['uuid'],
            columns=['numa_topology', 'vcpu_model', 'trusted_certs',
                     'resources'])
        self.assertRaises(SQLAlchemyError,
                          extra.__getitem__, 'pci_requests')
        self.assertIn('numa_topology', extra)
        self.assertIn('vcpu_model', extra)
        self.assertIn('trusted_certs', extra)
        self.assertIn('resources', extra)


class ServiceTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _get_base_values(self):
        return {
            'uuid': None,
            'host': 'fake_host',
            'binary': 'fake_binary',
            'topic': 'fake_topic',
            'report_count': 3,
            'disabled': False,
            'forced_down': False
        }

    def _create_service(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.service_create(self.ctxt, v)

    def test_service_create(self):
        service = self._create_service({})
        self.assertIsNotNone(service['id'])
        for key, value in self._get_base_values().items():
            self.assertEqual(value, service[key])

    def test_service_create_disabled(self):
        self.flags(enable_new_services=False)
        service = self._create_service({'binary': 'nova-compute'})
        self.assertTrue(service['disabled'])

    def test_service_create_disabled_reason(self):
        self.flags(enable_new_services=False)
        service = self._create_service({'binary': 'nova-compute'})
        msg = "New compute service disabled due to config option."
        self.assertEqual(msg, service['disabled_reason'])

    def test_service_create_disabled_non_compute_ignored(self):
        """Tests that enable_new_services=False has no effect on
        auto-disabling a new non-nova-compute service.
        """
        self.flags(enable_new_services=False)
        service = self._create_service({'binary': 'nova-scheduler'})
        self.assertFalse(service['disabled'])
        self.assertIsNone(service['disabled_reason'])

    def test_service_destroy(self):
        service1 = self._create_service({})
        service2 = self._create_service({'host': 'fake_host2'})

        db.service_destroy(self.ctxt, service1['id'])
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, self.ctxt, service1['id'])
        self._assertEqualObjects(db.service_get(self.ctxt, service2['id']),
                                 service2, ignored_keys=['compute_node'])

    def test_service_destroy_not_nova_compute(self):
        service = self._create_service({'binary': 'nova-consoleauth',
                                        'host': 'host1'})
        compute_node_dict = _make_compute_node('host1', 'node1', 'kvm', None)
        compute_node = db.compute_node_create(self.ctxt, compute_node_dict)
        db.service_destroy(self.ctxt, service['id'])
        # make sure ComputeHostNotFound is not raised
        db.compute_node_get(self.ctxt, compute_node['id'])

    def test_service_update(self):
        service = self._create_service({})
        new_values = {
            'uuid': uuidsentinel.service,
            'host': 'fake_host1',
            'binary': 'fake_binary1',
            'topic': 'fake_topic1',
            'report_count': 4,
            'disabled': True
        }
        db.service_update(self.ctxt, service['id'], new_values)
        updated_service = db.service_get(self.ctxt, service['id'])
        for key, value in new_values.items():
            self.assertEqual(value, updated_service[key])

    def test_service_update_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_update, self.ctxt, 100500, {})

    def test_service_update_with_set_forced_down(self):
        service = self._create_service({})
        db.service_update(self.ctxt, service['id'], {'forced_down': True})
        updated_service = db.service_get(self.ctxt, service['id'])
        self.assertTrue(updated_service['forced_down'])

    def test_service_update_with_unset_forced_down(self):
        service = self._create_service({'forced_down': True})
        db.service_update(self.ctxt, service['id'], {'forced_down': False})
        updated_service = db.service_get(self.ctxt, service['id'])
        self.assertFalse(updated_service['forced_down'])

    def test_service_get(self):
        service1 = self._create_service({})
        self._create_service({'host': 'some_other_fake_host'})
        real_service1 = db.service_get(self.ctxt, service1['id'])
        self._assertEqualObjects(service1, real_service1,
                                 ignored_keys=['compute_node'])

    def test_service_get_by_uuid(self):
        service1 = self._create_service({'uuid': uuidsentinel.service1_uuid})
        self._create_service({'host': 'some_other_fake_host',
                              'uuid': uuidsentinel.other_uuid})
        real_service1 = db.service_get_by_uuid(
            self.ctxt, uuidsentinel.service1_uuid)
        self._assertEqualObjects(service1, real_service1,
                                 ignored_keys=['compute_node'])

    def test_service_get_by_uuid_not_found(self):
        """Asserts that ServiceNotFound is raised if a service is not found by
        a given uuid.
        """
        self.assertRaises(exception.ServiceNotFound, db.service_get_by_uuid,
                          self.ctxt, uuidsentinel.service_not_found)

    def test_service_get_minimum_version(self):
        self._create_service({'version': 1,
                              'host': 'host3',
                              'binary': 'compute',
                              'forced_down': True})
        self._create_service({'version': 2,
                              'host': 'host1',
                              'binary': 'compute'})
        self._create_service({'version': 3,
                              'host': 'host2',
                              'binary': 'compute'})
        self._create_service({'version': 0,
                              'host': 'host0',
                              'binary': 'compute',
                              'deleted': 1})
        self.assertEqual({'compute': 2},
                         db.service_get_minimum_version(self.ctxt,
                                                        ['compute']))

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

    def test_service_get_by_host_and_binary(self):
        service1 = self._create_service({'host': 'host1', 'binary': 'foo'})
        self._create_service({'host': 'host2', 'binary': 'bar'})

        real_service1 = db.service_get_by_host_and_binary(self.ctxt,
                                                         host='host1',
                                                         binary='foo')
        self._assertEqualObjects(service1, real_service1)

    def test_service_get_by_host_and_binary_raises(self):
        self.assertRaises(exception.HostBinaryNotFound,
                          db.service_get_by_host_and_binary, self.ctxt,
                          host='host1', binary='baz')

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

    def test_service_get_all_by_binary(self):
        values = [
            {'host': 'host1', 'binary': 'b1'},
            {'host': 'host2', 'binary': 'b1'},
            {'disabled': True, 'binary': 'b1'},
            {'host': 'host3', 'binary': 'b2'}
        ]
        services = [self._create_service(vals) for vals in values]
        expected = services[:2]
        real = db.service_get_all_by_binary(self.ctxt, 'b1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_all_by_binary_include_disabled(self):
        values = [
            {'host': 'host1', 'binary': 'b1'},
            {'host': 'host2', 'binary': 'b1'},
            {'disabled': True, 'binary': 'b1'},
            {'host': 'host3', 'binary': 'b2'}
        ]
        services = [self._create_service(vals) for vals in values]
        expected = services[:3]
        real = db.service_get_all_by_binary(self.ctxt, 'b1',
                                            include_disabled=True)
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_all_computes_by_hv_type(self):
        values = [
            {'host': 'host1', 'binary': 'nova-compute'},
            {'host': 'host2', 'binary': 'nova-compute', 'disabled': True},
            {'host': 'host3', 'binary': 'nova-compute'},
            {'host': 'host4', 'binary': 'b2'}
        ]
        services = [self._create_service(vals) for vals in values]
        compute_nodes = [
            _make_compute_node('host1', 'node1', 'ironic', services[0]['id']),
            _make_compute_node('host1', 'node2', 'ironic', services[0]['id']),
            _make_compute_node('host2', 'node3', 'ironic', services[1]['id']),
            _make_compute_node('host3', 'host3', 'kvm', services[2]['id']),
        ]
        [db.compute_node_create(self.ctxt, cn) for cn in compute_nodes]

        expected = services[:1]
        real = db.service_get_all_computes_by_hv_type(self.ctxt,
                                                      'ironic',
                                                      include_disabled=False)
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_all_computes_by_hv_type_include_disabled(self):
        values = [
            {'host': 'host1', 'binary': 'nova-compute'},
            {'host': 'host2', 'binary': 'nova-compute', 'disabled': True},
            {'host': 'host3', 'binary': 'nova-compute'},
            {'host': 'host4', 'binary': 'b2'}
        ]
        services = [self._create_service(vals) for vals in values]
        compute_nodes = [
            _make_compute_node('host1', 'node1', 'ironic', services[0]['id']),
            _make_compute_node('host1', 'node2', 'ironic', services[0]['id']),
            _make_compute_node('host2', 'node3', 'ironic', services[1]['id']),
            _make_compute_node('host3', 'host3', 'kvm', services[2]['id']),
        ]
        [db.compute_node_create(self.ctxt, cn) for cn in compute_nodes]

        expected = services[:2]
        real = db.service_get_all_computes_by_hv_type(self.ctxt,
                                                      'ironic',
                                                      include_disabled=True)
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
            {'host': 'host1', 'binary': 'nova-compute'},
            {'host': 'host2', 'binary': 'nova-scheduler'},
            {'host': 'host3', 'binary': 'nova-compute'}
        ]
        services = [self._create_service(vals) for vals in values]

        real_service = db.service_get_by_compute_host(self.ctxt, 'host1')
        self._assertEqualObjects(services[0], real_service)

        self.assertRaises(exception.ComputeHostNotFound,
                          db.service_get_by_compute_host,
                          self.ctxt, 'non-exists-host')

    def test_service_get_by_compute_host_not_found(self):
        self.assertRaises(exception.ComputeHostNotFound,
                          db.service_get_by_compute_host,
                          self.ctxt, 'non-exists-host')

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

    def test_migrate_service_uuids(self):
        # Start with nothing.
        total, done = db.service_uuids_online_data_migration(self.ctxt, 10)
        self.assertEqual(0, total)
        self.assertEqual(0, done)

        # Create two services, one with a uuid and one without.
        db.service_create(self.ctxt,
                          dict(host='host1', binary='nova-compute',
                               topic='compute', report_count=1,
                               disabled=False))
        db.service_create(self.ctxt,
                          dict(host='host2', binary='nova-compute',
                               topic='compute', report_count=1,
                               disabled=False, uuid=uuidsentinel.host2))

        # Now migrate them, we should find one and update one.
        total, done = db.service_uuids_online_data_migration(
            self.ctxt, 10)
        self.assertEqual(1, total)
        self.assertEqual(1, done)

        # Get the services back to make sure the original uuid didn't change.
        services = db.service_get_all_by_binary(self.ctxt, 'nova-compute')
        self.assertEqual(2, len(services))
        for service in services:
            if service['host'] == 'host2':
                self.assertEqual(uuidsentinel.host2, service['uuid'])
            else:
                self.assertIsNotNone(service['uuid'])

        # Run the online migration again to see nothing was processed.
        total, done = db.service_uuids_online_data_migration(
            self.ctxt, 10)
        self.assertEqual(0, total)
        self.assertEqual(0, done)

    def test_migration_migrate_to_uuid(self):
        total, done = sqlalchemy_api.migration_migrate_to_uuid(self.ctxt, 10)
        self.assertEqual(0, total)
        self.assertEqual(0, done)

        # Create two migrations, one with a uuid and one without.
        db.migration_create(self.ctxt,
                            dict(source_compute='src', source_node='srcnode',
                                 dest_compute='dst', dest_node='dstnode',
                                 status='running'))
        db.migration_create(self.ctxt,
                            dict(source_compute='src', source_node='srcnode',
                                 dest_compute='dst', dest_node='dstnode',
                                 status='running',
                                 uuid=uuidsentinel.migration2))

        # Now migrate them, we should find one and update one
        total, done = sqlalchemy_api.migration_migrate_to_uuid(self.ctxt, 10)
        self.assertEqual(1, total)
        self.assertEqual(1, done)

        # Get the migrations back to make sure the original uuid didn't change.
        migrations = db.migration_get_all_by_filters(self.ctxt, {})
        uuids = [m.uuid for m in migrations]
        self.assertIn(uuidsentinel.migration2, uuids)
        self.assertNotIn(None, uuids)

        # Run the online migration again to see nothing was processed.
        total, done = sqlalchemy_api.migration_migrate_to_uuid(self.ctxt, 10)
        self.assertEqual(0, total)
        self.assertEqual(0, done)


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

    def _create_action_values(self, uuid, action='run_instance',
                              ctxt=None, extra=None, instance_create=True):
        if ctxt is None:
            ctxt = self.ctxt

        if instance_create:
            db.instance_create(ctxt, {'uuid': uuid})

        utc_now = timeutils.utcnow()
        values = {
            'action': action,
            'instance_uuid': uuid,
            'request_id': ctxt.request_id,
            'user_id': ctxt.user_id,
            'project_id': ctxt.project_id,
            'start_time': utc_now,
            'updated_at': utc_now,
            'message': 'action-message'
        }
        if extra is not None:
            values.update(extra)
        return values

    def _create_event_values(self, uuid, event='schedule',
                             ctxt=None, extra=None):
        if ctxt is None:
            ctxt = self.ctxt
        values = {
            'event': event,
            'instance_uuid': uuid,
            'request_id': ctxt.request_id,
            'start_time': timeutils.utcnow(),
            'host': 'fake-host',
            'details': 'fake-details',
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
        uuid = uuidsentinel.uuid1

        action_values = self._create_action_values(uuid)
        action = db.action_start(self.ctxt, action_values)

        ignored_keys = self.IGNORED_FIELDS + ['finish_time']
        self._assertEqualObjects(action_values, action, ignored_keys)

        self._assertActionSaved(action, uuid)

    def test_instance_action_finish(self):
        """Create an instance action."""
        uuid = uuidsentinel.uuid1

        action_values = self._create_action_values(uuid)
        db.action_start(self.ctxt, action_values)

        action_values['finish_time'] = timeutils.utcnow()
        action = db.action_finish(self.ctxt, action_values)
        self._assertEqualObjects(action_values, action, self.IGNORED_FIELDS)

        self._assertActionSaved(action, uuid)

    def test_instance_action_finish_without_started_event(self):
        """Create an instance finish action."""
        uuid = uuidsentinel.uuid1

        action_values = self._create_action_values(uuid)
        action_values['finish_time'] = timeutils.utcnow()
        self.assertRaises(exception.InstanceActionNotFound, db.action_finish,
                          self.ctxt, action_values)

    def test_instance_actions_get_by_instance(self):
        """Ensure we can get actions by UUID."""
        uuid1 = uuidsentinel.uuid1

        expected = []

        action_values = self._create_action_values(uuid1)
        action = db.action_start(self.ctxt, action_values)
        expected.append(action)

        action_values['action'] = 'resize'
        action = db.action_start(self.ctxt, action_values)
        expected.append(action)

        # Create some extra actions
        uuid2 = uuidsentinel.uuid2
        ctxt2 = context.get_admin_context()
        action_values = self._create_action_values(uuid2, 'reboot', ctxt2)
        db.action_start(ctxt2, action_values)
        db.action_start(ctxt2, action_values)

        # Retrieve the action to ensure it was successfully added
        actions = db.actions_get(self.ctxt, uuid1)
        self._assertEqualListsOfObjects(expected, actions)

    def test_instance_actions_get_are_in_order(self):
        """Ensure retrived actions are in order."""
        uuid1 = uuidsentinel.uuid1

        extra = {
            'created_at': timeutils.utcnow()
        }

        action_values = self._create_action_values(uuid1, extra=extra)
        action1 = db.action_start(self.ctxt, action_values)

        action_values['action'] = 'delete'
        action2 = db.action_start(self.ctxt, action_values)

        actions = db.actions_get(self.ctxt, uuid1)
        self.assertEqual(2, len(actions))

        self._assertEqualOrderedListOfObjects([action2, action1], actions)

    def test_instance_actions_get_with_limit(self):
        """Test list instance actions can support pagination."""
        uuid1 = uuidsentinel.uuid1

        extra = {
            'created_at': timeutils.utcnow()
        }

        action_values = self._create_action_values(uuid1, extra=extra)
        action1 = db.action_start(self.ctxt, action_values)

        action_values['action'] = 'delete'
        action_values['request_id'] = 'req-' + uuidsentinel.reqid1
        db.action_start(self.ctxt, action_values)

        actions = db.actions_get(self.ctxt, uuid1)
        self.assertEqual(2, len(actions))

        actions = db.actions_get(self.ctxt, uuid1, limit=1)
        self.assertEqual(1, len(actions))

        actions = db.actions_get(
            self.ctxt, uuid1, limit=1,
            marker=action_values['request_id'])
        self.assertEqual(1, len(actions))
        self._assertEqualListsOfObjects([action1], actions)

    def test_instance_actions_get_with_changes_since(self):
        """Test list instance actions can support timestamp filter."""
        uuid1 = uuidsentinel.uuid1

        extra = {
            'created_at': timeutils.utcnow()
        }

        action_values = self._create_action_values(uuid1, extra=extra)
        db.action_start(self.ctxt, action_values)

        timestamp = timeutils.utcnow()
        action_values['start_time'] = timestamp
        action_values['updated_at'] = timestamp
        action_values['action'] = 'delete'
        action2 = db.action_start(self.ctxt, action_values)

        actions = db.actions_get(self.ctxt, uuid1)
        self.assertEqual(2, len(actions))
        self.assertNotEqual(actions[0]['updated_at'],
                            actions[1]['updated_at'])
        actions = db.actions_get(
            self.ctxt, uuid1, filters={'changes-since': timestamp})
        self.assertEqual(1, len(actions))
        self._assertEqualListsOfObjects([action2], actions)

    def test_instance_actions_get_with_changes_before(self):
        """Test list instance actions can support timestamp filter."""
        uuid1 = uuidsentinel.uuid1

        expected = []
        extra = {
            'created_at': timeutils.utcnow()
        }

        action_values = self._create_action_values(uuid1, extra=extra)
        action = db.action_start(self.ctxt, action_values)
        expected.append(action)

        timestamp = timeutils.utcnow()
        action_values['start_time'] = timestamp
        action_values['updated_at'] = timestamp
        action_values['action'] = 'delete'
        action = db.action_start(self.ctxt, action_values)
        expected.append(action)

        actions = db.actions_get(self.ctxt, uuid1)
        self.assertEqual(2, len(actions))
        self.assertNotEqual(actions[0]['updated_at'],
                            actions[1]['updated_at'])
        actions = db.actions_get(
            self.ctxt, uuid1, filters={'changes-before': timestamp})
        self.assertEqual(2, len(actions))
        self._assertEqualListsOfObjects(expected, actions)

    def test_instance_actions_get_with_not_found_marker(self):
        self.assertRaises(exception.MarkerNotFound,
                          db.actions_get, self.ctxt, uuidsentinel.uuid1,
                          marker=uuidsentinel.not_found_marker)

    def test_instance_action_get_by_instance_and_action(self):
        """Ensure we can get an action by instance UUID and action id."""
        ctxt2 = context.get_admin_context()
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2

        action_values = self._create_action_values(uuid1)
        db.action_start(self.ctxt, action_values)
        request_id = action_values['request_id']

        # NOTE(rpodolyaka): ensure we use a different req id for the 2nd req
        action_values['action'] = 'resize'
        action_values['request_id'] = 'req-00000000-7522-4d99-7ff-111111111111'
        db.action_start(self.ctxt, action_values)

        action_values = self._create_action_values(uuid2, 'reboot', ctxt2)
        db.action_start(ctxt2, action_values)
        db.action_start(ctxt2, action_values)

        action = db.action_get_by_request_id(self.ctxt, uuid1, request_id)
        self.assertEqual('run_instance', action['action'])
        self.assertEqual(self.ctxt.request_id, action['request_id'])

    def test_instance_action_get_by_instance_and_action_by_order(self):
        instance_uuid = uuidsentinel.uuid1

        t1 = {
            'created_at': timeutils.utcnow()
        }
        t2 = {
            'created_at': timeutils.utcnow() + datetime.timedelta(seconds=5)
        }
        # Create a confirmResize action
        action_values = self._create_action_values(
            instance_uuid, action='confirmResize', extra=t1)
        a1 = db.action_start(self.ctxt, action_values)

        # Create a delete action with same instance uuid and req id
        action_values = self._create_action_values(
            instance_uuid, action='delete', extra=t2, instance_create=False)
        a2 = db.action_start(self.ctxt, action_values)

        self.assertEqual(a1['request_id'], a2['request_id'])
        self.assertEqual(a1['instance_uuid'], a2['instance_uuid'])
        self.assertTrue(a1['created_at'] < a2['created_at'])

        action = db.action_get_by_request_id(self.ctxt, instance_uuid,
                                             a1['request_id'])
        # Only get the delete action(last created)
        self.assertEqual(action['action'], a2['action'])

    def test_instance_action_event_start(self):
        """Create an instance action event."""
        uuid = uuidsentinel.uuid1

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
        uuid = uuidsentinel.uuid1

        event_values = self._create_event_values(uuid)
        self.assertRaises(exception.InstanceActionNotFound,
                          db.action_event_start, self.ctxt, event_values)

    def test_instance_action_event_finish_without_started_event(self):
        """Finish an instance action event."""
        uuid = uuidsentinel.uuid1

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
        uuid = uuidsentinel.uuid1

        event_values = {
            'finish_time': timeutils.utcnow() + datetime.timedelta(seconds=5),
            'result': 'Success'
        }
        event_values = self._create_event_values(uuid, extra=event_values)
        self.assertRaises(exception.InstanceActionNotFound,
                          db.action_event_finish, self.ctxt, event_values)

    def test_instance_action_event_finish_success(self):
        """Finish an instance action event."""
        uuid = uuidsentinel.uuid1

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
        uuid = uuidsentinel.uuid1

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
        uuid = uuidsentinel.uuid1

        action = db.action_start(self.ctxt, self._create_action_values(uuid))

        event_values = {'start_time': timeutils.utcnow().isoformat()}
        event_values = self._create_event_values(uuid, extra=event_values)
        event = db.action_event_start(self.ctxt, event_values)

        self._assertActionEventSaved(event, action['id'])

    def test_instance_action_events_get_are_in_order(self):
        """Ensure retrived action events are in order."""
        uuid1 = uuidsentinel.uuid1

        action = db.action_start(self.ctxt,
                                 self._create_action_values(uuid1))

        extra1 = {
            'created_at': timeutils.utcnow()
        }
        extra2 = {
            'created_at': timeutils.utcnow() + datetime.timedelta(seconds=5)
        }

        event_val1 = self._create_event_values(uuid1, 'schedule', extra=extra1)
        event_val2 = self._create_event_values(uuid1, 'run', extra=extra1)
        event_val3 = self._create_event_values(uuid1, 'stop', extra=extra2)

        event1 = db.action_event_start(self.ctxt, event_val1)
        event2 = db.action_event_start(self.ctxt, event_val2)
        event3 = db.action_event_start(self.ctxt, event_val3)

        events = db.action_events_get(self.ctxt, action['id'])
        self.assertEqual(3, len(events))

        self._assertEqualOrderedListOfObjects([event3, event2, event1], events,
                                              ['instance_uuid', 'request_id'])

    def test_instance_action_event_get_by_id(self):
        """Get a specific instance action event."""
        ctxt2 = context.get_admin_context()
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2

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

    def test_instance_action_event_start_with_different_request_id(self):
        uuid = uuidsentinel.uuid1

        action_values = self._create_action_values(uuid)
        action = db.action_start(self.ctxt, action_values)

        # init_host case
        fake_admin_context = context.get_admin_context()
        event_values = self._create_event_values(uuid, ctxt=fake_admin_context)
        event = db.action_event_start(fake_admin_context, event_values)
        event_values['action_id'] = action['id']
        ignored = self.IGNORED_FIELDS + ['finish_time', 'traceback', 'result']
        self._assertEqualObjects(event_values, event, ignored)

        self._assertActionEventSaved(event, action['id'])

    def test_instance_action_event_finish_with_different_request_id(self):
        uuid = uuidsentinel.uuid1

        action = db.action_start(self.ctxt, self._create_action_values(uuid))

        # init_host case
        fake_admin_context = context.get_admin_context()
        db.action_event_start(fake_admin_context, self._create_event_values(
            uuid, ctxt=fake_admin_context))

        event_values = {
            'finish_time': timeutils.utcnow() + datetime.timedelta(seconds=5),
            'result': 'Success'
        }
        event_values = self._create_event_values(uuid, ctxt=fake_admin_context,
                                                 extra=event_values)
        event = db.action_event_finish(fake_admin_context, event_values)

        self._assertActionEventSaved(event, action['id'])
        action = db.action_get_by_request_id(self.ctxt, uuid,
                                             self.ctxt.request_id)
        self.assertNotEqual('Error', action['message'])

    def test_instance_action_updated_with_event_start_and_finish_action(self):
        uuid = uuidsentinel.uuid1
        action = db.action_start(self.ctxt, self._create_action_values(uuid))
        updated_create = action['updated_at']
        self.assertIsNotNone(updated_create)
        event_values = self._create_event_values(uuid)

        # event start action
        time_start = timeutils.utcnow() + datetime.timedelta(seconds=5)
        event_values['start_time'] = time_start
        db.action_event_start(self.ctxt, event_values)
        action = db.action_get_by_request_id(self.ctxt, uuid,
                                             self.ctxt.request_id)
        updated_event_start = action['updated_at']
        self.assertEqual(time_start.isoformat(),
                         updated_event_start.isoformat())
        self.assertTrue(updated_event_start > updated_create)

        # event finish action
        time_finish = timeutils.utcnow() + datetime.timedelta(seconds=10)
        event_values = {
            'finish_time': time_finish,
            'result': 'Success'
        }
        event_values = self._create_event_values(uuid, extra=event_values)
        db.action_event_finish(self.ctxt, event_values)
        action = db.action_get_by_request_id(self.ctxt, uuid,
                                             self.ctxt.request_id)
        updated_event_finish = action['updated_at']
        self.assertEqual(time_finish.isoformat(),
                         updated_event_finish.isoformat())
        self.assertTrue(updated_event_finish > updated_event_start)

    def test_instance_action_not_updated_with_unknown_event_request(self):
        """Tests that we don't update the action.updated_at field when
        starting or finishing an action event if we couldn't find the
        action by the request_id.
        """
        # Create a valid action - this represents an active user request.
        uuid = uuidsentinel.uuid1
        action = db.action_start(self.ctxt, self._create_action_values(uuid))
        updated_create = action['updated_at']
        self.assertIsNotNone(updated_create)
        event_values = self._create_event_values(uuid)

        # Now start an event on an unknown request ID and admin context where
        # project_id won't be set.
        time_start = timeutils.utcnow() + datetime.timedelta(seconds=5)
        event_values['start_time'] = time_start
        random_request_id = 'req-%s' % uuidsentinel.request_id
        event_values['request_id'] = random_request_id
        admin_context = context.get_admin_context()
        event_ref = db.action_event_start(admin_context, event_values)
        # The event would be created on the existing action.
        self.assertEqual(action['id'], event_ref['action_id'])
        # And the action.update_at should be the same as before the event was
        # started.
        action = db.action_get_by_request_id(self.ctxt, uuid,
                                             self.ctxt.request_id)
        self.assertEqual(updated_create, action['updated_at'])

        # Now finish the event on the unknown request ID and admin context.
        time_finish = timeutils.utcnow() + datetime.timedelta(seconds=10)
        event_values = {
            'finish_time': time_finish,
            'request_id': random_request_id,
            'result': 'Success'
        }
        event_values = self._create_event_values(uuid, extra=event_values)
        db.action_event_finish(admin_context, event_values)
        # And the action.update_at should be the same as before the event was
        # finished.
        action = db.action_get_by_request_id(self.ctxt, uuid,
                                             self.ctxt.request_id)
        self.assertEqual(updated_create, action['updated_at'])


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
        uuid = uuidsentinel.uuid1

        # Ensure no faults registered for this instance
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, [uuid])
        self.assertEqual(0, len(faults[uuid]))

        # Create a fault
        fault_values = self._create_fault_values(uuid)
        db.instance_create(self.ctxt, {'uuid': uuid})
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
        uuids = [uuidsentinel.uuid1, uuidsentinel.uuid2]
        fault_codes = [404, 500]
        expected = {}

        # Create faults
        for uuid in uuids:
            db.instance_create(self.ctxt, {'uuid': uuid})

            expected[uuid] = []
            for code in fault_codes:
                fault_values = self._create_fault_values(uuid, code)
                fault = db.instance_fault_create(self.ctxt, fault_values)
                # We expect the faults to be returned ordered by created_at in
                # descending order, so insert the newly created fault at the
                # front of our list.
                expected[uuid].insert(0, fault)

        # Ensure faults are saved
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, uuids)
        self.assertEqual(len(expected), len(faults))
        for uuid in uuids:
            self._assertEqualOrderedListOfObjects(expected[uuid], faults[uuid])

    def test_instance_fault_get_latest_by_instance(self):
        """Ensure we can retrieve only latest faults for instance."""
        uuids = [uuidsentinel.uuid1, uuidsentinel.uuid2]
        fault_codes = [404, 500]
        expected = {}

        # Create faults
        for uuid in uuids:
            db.instance_create(self.ctxt, {'uuid': uuid})

            expected[uuid] = []
            for code in fault_codes:
                fault_values = self._create_fault_values(uuid, code)
                fault = db.instance_fault_create(self.ctxt, fault_values)
                expected[uuid].append(fault)

        # We are only interested in the latest fault for each instance
        for uuid in expected:
            expected[uuid] = expected[uuid][-1:]

        # Ensure faults are saved
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, uuids,
                                                         latest=True)
        self.assertEqual(len(expected), len(faults))
        for uuid in uuids:
            self._assertEqualListsOfObjects(expected[uuid], faults[uuid])

    def test_instance_faults_get_by_instance_uuids_no_faults(self):
        uuid = uuidsentinel.uuid1
        # None should be returned when no faults exist.
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, [uuid])
        expected = {uuid: []}
        self.assertEqual(expected, faults)

    @mock.patch.object(query.Query, 'filter')
    def test_instance_faults_get_by_instance_uuids_no_uuids(self, mock_filter):
        faults = db.instance_fault_get_by_instance_uuids(self.ctxt, [])
        self.assertEqual({}, faults)
        self.assertFalse(mock_filter.called)


@mock.patch('time.sleep', new=lambda x: None)
class FixedIPTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(FixedIPTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

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

        for host, ips in host_ips.items():
            for ip in ips:
                instance_uuid = self._create_instance(host=host)
                db.fixed_ip_create(self.ctxt, {'address': ip})
                db.fixed_ip_associate(self.ctxt, ip, instance_uuid)

        for host, ips in host_ips.items():
            ips_on_host = [x['address']
                           for x in db.fixed_ip_get_by_host(self.ctxt, host)]
            self._assertEqualListsOfPrimitivesAsSets(ips_on_host, ips)

    def test_fixed_ip_get_by_network_host_not_found_exception(self):
        self.assertRaises(
            exception.FixedIpNotFoundForNetworkHost,
            db.fixed_ip_get_by_network_host,
            self.ctxt, 1, 'ignore')

    def test_fixed_ip_get_by_network_host_fixed_ip_found(self):
        db.fixed_ip_create(self.ctxt, dict(network_id=1, host='host'))

        fip = db.fixed_ip_get_by_network_host(self.ctxt, 1, 'host')

        self.assertEqual(1, fip['network_id'])
        self.assertEqual('host', fip['host'])

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
        self.assertEqual(0, len(ips_list))

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

    def test_fixed_ip_associate_succeeds_retry_on_deadlock(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip()

        def fake_first():
            if mock_first.call_count == 1:
                raise db_exc.DBDeadlock()
            else:
                return objects.Instance(id=1, address=address, reserved=False,
                                        instance_uuid=None, network_id=None)

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        side_effect=fake_first) as mock_first:
            db.fixed_ip_associate(self.ctxt, address, instance_uuid,
                                  network_id=network['id'])
            self.assertEqual(2, mock_first.call_count)

        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], instance_uuid)
        self.assertEqual(fixed_ip['network_id'], network['id'])

    def test_fixed_ip_associate_succeeds_retry_on_no_rows_updated(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip()

        def fake_first():
            if mock_first.call_count == 1:
                return objects.Instance(id=2, address=address, reserved=False,
                                        instance_uuid=None, network_id=None)
            else:
                return objects.Instance(id=1, address=address, reserved=False,
                                        instance_uuid=None, network_id=None)

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        side_effect=fake_first) as mock_first:
            db.fixed_ip_associate(self.ctxt, address, instance_uuid,
                                  network_id=network['id'])
            self.assertEqual(2, mock_first.call_count)

        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], instance_uuid)
        self.assertEqual(fixed_ip['network_id'], network['id'])

    def test_fixed_ip_associate_succeeds_retry_limit_exceeded(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip()

        def fake_first():
            return objects.Instance(id=2, address=address, reserved=False,
                                    instance_uuid=None, network_id=None)

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        side_effect=fake_first) as mock_first:
            self.assertRaises(exception.FixedIpAssociateFailed,
                              db.fixed_ip_associate, self.ctxt, address,
                              instance_uuid, network_id=network['id'])
            # 5 reties + initial attempt
            self.assertEqual(6, mock_first.call_count)

    def test_fixed_ip_associate_ip_not_in_network_with_no_retries(self):
        instance_uuid = self._create_instance()

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        return_value=None) as mock_first:
            self.assertRaises(exception.FixedIpNotFoundForNetwork,
                              db.fixed_ip_associate,
                              self.ctxt, None, instance_uuid)
            self.assertEqual(1, mock_first.call_count)

    def test_fixed_ip_associate_no_network_id_with_no_retries(self):
        # Tests that trying to associate an instance to a fixed IP on a network
        # but without specifying the network ID during associate will fail.
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})
        address = self.create_fixed_ip(network_id=network['id'])

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        return_value=None) as mock_first:
            self.assertRaises(exception.FixedIpNotFoundForNetwork,
                              db.fixed_ip_associate,
                              self.ctxt, address, instance_uuid)
            self.assertEqual(1, mock_first.call_count)

    def test_fixed_ip_associate_with_vif(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})
        vif = db.virtual_interface_create(self.ctxt, {})
        address = self.create_fixed_ip()

        fixed_ip = db.fixed_ip_associate(self.ctxt, address, instance_uuid,
                                         network_id=network['id'],
                                         virtual_interface_id=vif['id'])

        self.assertTrue(fixed_ip['allocated'])
        self.assertEqual(vif['id'], fixed_ip['virtual_interface_id'])

    def test_fixed_ip_associate_not_allocated_without_vif(self):
        instance_uuid = self._create_instance()
        address = self.create_fixed_ip()

        fixed_ip = db.fixed_ip_associate(self.ctxt, address, instance_uuid)

        self.assertFalse(fixed_ip['allocated'])
        self.assertIsNone(fixed_ip['virtual_interface_id'])

    def test_fixed_ip_associate_pool_invalid_uuid(self):
        instance_uuid = '123'
        self.assertRaises(exception.InvalidUUID, db.fixed_ip_associate_pool,
                          self.ctxt, None, instance_uuid)

    def test_fixed_ip_associate_pool_no_more_fixed_ips(self):
        instance_uuid = self._create_instance()
        self.assertRaises(exception.NoMoreFixedIps, db.fixed_ip_associate_pool,
                          self.ctxt, None, instance_uuid)

    def test_fixed_ip_associate_pool_ignores_leased_addresses(self):
        instance_uuid = self._create_instance()
        params = {'address': '192.168.1.5',
                  'leased': True}
        db.fixed_ip_create(self.ctxt, params)
        self.assertRaises(exception.NoMoreFixedIps, db.fixed_ip_associate_pool,
                          self.ctxt, None, instance_uuid)

    def test_fixed_ip_associate_pool_succeeds(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip(network_id=network['id'])
        db.fixed_ip_associate_pool(self.ctxt, network['id'], instance_uuid)
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], instance_uuid)

    def test_fixed_ip_associate_pool_order(self):
        """Test that fixed_ip always uses oldest fixed_ip.

        We should always be using the fixed ip with the oldest
        updated_at.
        """
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})
        self.addCleanup(timeutils.clear_time_override)
        start = timeutils.utcnow()
        for i in range(1, 4):
            now = start - datetime.timedelta(hours=i)
            timeutils.set_time_override(now)
            address = self.create_fixed_ip(
                updated_at=now,
                address='10.1.0.%d' % i,
                network_id=network['id'])
        db.fixed_ip_associate_pool(self.ctxt, network['id'], instance_uuid)
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], instance_uuid)

    def test_fixed_ip_associate_pool_succeeds_fip_ref_network_id_is_none(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        self.create_fixed_ip(network_id=None)
        fixed_ip = db.fixed_ip_associate_pool(self.ctxt,
                                              network['id'], instance_uuid)
        self.assertEqual(instance_uuid, fixed_ip['instance_uuid'])
        self.assertEqual(network['id'], fixed_ip['network_id'])

    def test_fixed_ip_associate_pool_succeeds_retry(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        address = self.create_fixed_ip(network_id=network['id'])

        def fake_first():
            if mock_first.call_count == 1:
                return {'network_id': network['id'], 'address': 'invalid',
                        'instance_uuid': None, 'host': None, 'id': 1}
            else:
                return {'network_id': network['id'], 'address': address,
                        'instance_uuid': None, 'host': None, 'id': 1}

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        side_effect=fake_first) as mock_first:
            db.fixed_ip_associate_pool(self.ctxt, network['id'], instance_uuid)
            self.assertEqual(2, mock_first.call_count)

        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(instance_uuid, fixed_ip['instance_uuid'])

    def test_fixed_ip_associate_pool_retry_limit_exceeded(self):
        instance_uuid = self._create_instance()
        network = db.network_create_safe(self.ctxt, {})

        self.create_fixed_ip(network_id=network['id'])

        def fake_first():
            return {'network_id': network['id'], 'address': 'invalid',
                    'instance_uuid': None, 'host': None, 'id': 1}

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        side_effect=fake_first) as mock_first:
            self.assertRaises(exception.FixedIpAssociateFailed,
                              db.fixed_ip_associate_pool, self.ctxt,
                              network['id'], instance_uuid)
            # 5 retries + initial attempt
            self.assertEqual(6, mock_first.call_count)

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
        ignored_keys = ['created_at', 'id', 'deleted_at', 'updated_at',
                        'virtual_interface', 'network', 'floating_ips']
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
        values = {'address': '192.168.1.5', 'instance_uuid': instance_uuid}
        vif = db.virtual_interface_create(self.ctxt, values)
        param = {
            'reserved': False,
            'deleted': 0,
            'leased': False,
            'host': '127.0.0.1',
            'address': address,
            'allocated': False,
            'instance_uuid': instance_uuid,
            'network_id': network_id,
            'virtual_interface_id': vif['id']
        }
        db.fixed_ip_create(self.ctxt, param)

        db.fixed_ip_disassociate(self.ctxt, address)
        fixed_ip_data = db.fixed_ip_get_by_address(self.ctxt, address)
        ignored_keys = ['created_at', 'id', 'deleted_at',
                        'updated_at', 'instance_uuid',
                        'virtual_interface_id']
        self._assertEqualObjects(param, fixed_ip_data, ignored_keys)
        self.assertIsNone(fixed_ip_data['instance_uuid'])
        self.assertIsNone(fixed_ip_data['virtual_interface_id'])

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
        self.assertRaises(exception.Forbidden, db.fixed_ip_get,
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

    def test_fixed_ip_get_by_address(self):
        instance_uuid = self._create_instance()
        db.fixed_ip_create(self.ctxt, {'address': '1.2.3.4',
                                       'instance_uuid': instance_uuid,
                                       })
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, '1.2.3.4',
                                              columns_to_join=['instance'])
        self.assertIn('instance', fixed_ip.__dict__)
        self.assertEqual(instance_uuid, fixed_ip.instance.uuid)

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


@mock.patch('time.sleep', new=lambda x: None)
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

    @mock.patch.object(query.Query, 'first', side_effect=db_exc.DBError())
    def test_floating_ip_get_with_long_id_not_found(self, mock_query):
        self.assertRaises(exception.InvalidID,
                          db.floating_ip_get, self.ctxt, 123456789101112)
        mock_query.assert_called_once_with()

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
        for pool, addresses in pools.items():
            for address in addresses:
                vals = {'pool': pool, 'address': address, 'project_id': None}
                self._create_floating_ip(vals)

        project_id = self._get_base_values()['project_id']
        for pool, addresses in pools.items():
            alloc_addrs = []
            for i in addresses:
                float_addr = db.floating_ip_allocate_address(self.ctxt,
                                                             project_id, pool)
                alloc_addrs.append(float_addr)
            self._assertEqualListsOfPrimitivesAsSets(alloc_addrs, addresses)

    def test_floating_ip_allocate_auto_assigned(self):
        addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3', '1.1.1.4']

        float_ips = []
        for i in range(0, 2):
            float_ips.append(self._create_floating_ip(
                {"address": addresses[i]}))
        for i in range(2, 4):
            float_ips.append(self._create_floating_ip({"address": addresses[i],
                                                       "auto_assigned": True}))

        for i in range(0, 2):
            float_ip = db.floating_ip_get(self.ctxt, float_ips[i].id)
            self.assertFalse(float_ip.auto_assigned)
        for i in range(2, 4):
            float_ip = db.floating_ip_get(self.ctxt, float_ips[i].id)
            self.assertTrue(float_ip.auto_assigned)

    def test_floating_ip_allocate_address_no_more_floating_ips(self):
        self.assertRaises(exception.NoMoreFloatingIps,
                          db.floating_ip_allocate_address,
                          self.ctxt, 'any_project_id', 'no_such_pool')

    def test_floating_ip_allocate_not_authorized(self):
        ctxt = context.RequestContext(user_id='a', project_id='abc',
                                      is_admin=False)
        self.assertRaises(exception.Forbidden,
                          db.floating_ip_allocate_address,
                          ctxt, 'other_project_id', 'any_pool')

    def test_floating_ip_allocate_address_succeeds_retry(self):
        pool = 'pool0'
        address = '0.0.0.0'
        vals = {'pool': pool, 'address': address, 'project_id': None}
        floating_ip = self._create_floating_ip(vals)

        project_id = self._get_base_values()['project_id']

        def fake_first():
            if mock_first.call_count == 1:
                return {'pool': pool, 'project_id': None, 'fixed_ip_id': None,
                        'address': address, 'id': 'invalid_id'}
            else:
                return {'pool': pool, 'project_id': None, 'fixed_ip_id': None,
                        'address': address, 'id': 1}

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        side_effect=fake_first) as mock_first:
            float_addr = db.floating_ip_allocate_address(self.ctxt,
                                                         project_id, pool)
            self.assertEqual(address, float_addr)
            self.assertEqual(2, mock_first.call_count)

        float_ip = db.floating_ip_get(self.ctxt, floating_ip.id)
        self.assertEqual(project_id, float_ip['project_id'])

    def test_floating_ip_allocate_address_retry_limit_exceeded(self):
        pool = 'pool0'
        address = '0.0.0.0'
        vals = {'pool': pool, 'address': address, 'project_id': None}
        self._create_floating_ip(vals)

        project_id = self._get_base_values()['project_id']

        def fake_first():
            return {'pool': pool, 'project_id': None, 'fixed_ip_id': None,
                    'address': address, 'id': 'invalid_id'}

        with mock.patch('sqlalchemy.orm.query.Query.first',
                        side_effect=fake_first) as mock_first:
            self.assertRaises(exception.FloatingIpAllocateFailed,
                              db.floating_ip_allocate_address, self.ctxt,
                              project_id, pool)
            # 5 retries + initial attempt
            self.assertEqual(6, mock_first.call_count)

    def test_floating_ip_allocate_address_no_more_ips_with_no_retries(self):
        with mock.patch('sqlalchemy.orm.query.Query.first',
                        return_value=None) as mock_first:
            self.assertRaises(exception.NoMoreFloatingIps,
                              db.floating_ip_allocate_address,
                              self.ctxt, 'any_project_id', 'no_such_pool')
            self.assertEqual(1, mock_first.call_count)

    def _get_existing_ips(self):
        return [ip['address'] for ip in db.floating_ip_get_all(self.ctxt)]

    def test_floating_ip_bulk_create(self):
        expected_ips = ['1.1.1.1', '1.1.1.2', '1.1.1.3', '1.1.1.4']
        result = db.floating_ip_bulk_create(self.ctxt,
                                   [{'address': x} for x in expected_ips],
                                   want_result=False)
        self.assertIsNone(result)
        self._assertEqualListsOfPrimitivesAsSets(self._get_existing_ips(),
                                                 expected_ips)

    def test_floating_ip_bulk_create_duplicate(self):
        ips = ['1.1.1.1', '1.1.1.2', '1.1.1.3', '1.1.1.4']
        prepare_ips = lambda x: {'address': x}

        result = db.floating_ip_bulk_create(self.ctxt,
                                            list(map(prepare_ips, ips)))
        self.assertEqual(ips, [ip.address for ip in result])
        self.assertRaises(exception.FloatingIpExists,
                          db.floating_ip_bulk_create,
                          self.ctxt,
                          list(map(prepare_ips, ['1.1.1.5', '1.1.1.4'])),
                          want_result=False)
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          db.floating_ip_get_by_address,
                          self.ctxt, '1.1.1.5')

    def test_floating_ip_bulk_destroy(self):
        ips_for_delete = []
        ips_for_non_delete = []

        def create_ips(i, j):
            return [{'address': '1.1.%s.%s' % (i, k)} for k in range(1, j + 1)]

        # NOTE(boris-42): Create more than 256 ip to check that
        #                 _ip_range_splitter works properly.
        for i in range(1, 3):
            ips_for_delete.extend(create_ips(i, 255))
        ips_for_non_delete.extend(create_ips(3, 255))

        result = db.floating_ip_bulk_create(self.ctxt,
                                   ips_for_delete + ips_for_non_delete,
                                   want_result=False)
        self.assertIsNone(result)

        non_bulk_ips_for_delete = create_ips(4, 3)
        non_bulk_ips_for_non_delete = create_ips(5, 3)
        non_bulk_ips = non_bulk_ips_for_delete + non_bulk_ips_for_non_delete
        for dct in non_bulk_ips:
            self._create_floating_ip(dct)
        ips_for_delete.extend(non_bulk_ips_for_delete)
        ips_for_non_delete.extend(non_bulk_ips_for_non_delete)

        db.floating_ip_bulk_destroy(self.ctxt, ips_for_delete)

        expected_addresses = [x['address'] for x in ips_for_non_delete]
        self._assertEqualListsOfPrimitivesAsSets(self._get_existing_ips(),
                                                 expected_addresses)

    def test_floating_ip_create(self):
        floating_ip = self._create_floating_ip({})
        ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                        'created_at']

        self.assertIsNotNone(floating_ip['id'])
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

        project_id = self.ctxt.project_id
        float_ips = [self._create_floating_ip({'address': address,
                                               'project_id': project_id})
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

        fixed_ip = db.floating_ip_fixed_ip_associate(self.ctxt,
                                                     float_addresses[0],
                                                     fixed_addresses[0],
                                                     'host')
        self.assertEqual(fixed_ip.address, fixed_addresses[0])

    def test_floating_ip_fixed_ip_associate_float_ip_not_found(self):
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          db.floating_ip_fixed_ip_associate,
                          self.ctxt, '10.10.10.10', 'some', 'some')

    def test_floating_ip_associate_failed(self):
        fixed_ip = self._create_fixed_ip({'address': '7.7.7.7'})
        self.assertRaises(exception.FloatingIpAssociateFailed,
                          db.floating_ip_fixed_ip_associate,
                          self.ctxt, '10.10.10.10', fixed_ip, 'some')

    def test_floating_ip_deallocate(self):
        values = {'address': '1.1.1.1', 'project_id': 'fake', 'host': 'fake'}
        float_ip = self._create_floating_ip(values)
        rows_updated = db.floating_ip_deallocate(self.ctxt, float_ip.address)
        self.assertEqual(1, rows_updated)

        updated_float_ip = db.floating_ip_get(self.ctxt, float_ip.id)
        self.assertIsNone(updated_float_ip.project_id)
        self.assertIsNone(updated_float_ip.host)
        self.assertFalse(updated_float_ip.auto_assigned)

    def test_floating_ip_deallocate_address_not_found(self):
        self.assertEqual(0, db.floating_ip_deallocate(self.ctxt, '2.2.2.2'))

    def test_floating_ip_deallocate_address_associated_ip(self):
        float_address = '1.1.1.1'
        fixed_address = '2.2.2.1'

        project_id = self.ctxt.project_id
        float_ip = self._create_floating_ip({'address': float_address,
                                             'project_id': project_id})
        fixed_addr = self._create_fixed_ip({'address': fixed_address})
        db.floating_ip_fixed_ip_associate(self.ctxt, float_ip.address,
                                          fixed_addr, 'host')
        self.assertEqual(0, db.floating_ip_deallocate(self.ctxt,
                                                      float_address))

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

        project_id = self.ctxt.project_id
        float_ips = [self._create_floating_ip({'address': address,
                                               'project_id': project_id})
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
            self.assertIsNone(updated_float_ip.fixed_ip_id)
            self.assertIsNone(updated_float_ip.host)

    def test_floating_ip_disassociate_not_found(self):
        self.assertRaises(exception.FloatingIpNotFoundForAddress,
                          db.floating_ip_disassociate, self.ctxt,
                          '11.11.11.11')

    def test_floating_ip_get_all(self):
        addresses = ['1.1.1.1', '1.1.1.2', '1.1.1.3']
        float_ips = [self._create_floating_ip({'address': addr})
                        for addr in addresses]
        self._assertEqualListsOfObjects(float_ips,
                                        db.floating_ip_get_all(self.ctxt),
                                        ignored_keys="fixed_ip")

    def test_floating_ip_get_all_associated(self):
        instance = db.instance_create(self.ctxt, {'uuid': 'fake'})
        project_id = self.ctxt.project_id
        float_ip = self._create_floating_ip({'address': '1.1.1.1',
                                             'project_id': project_id})
        fixed_ip = self._create_fixed_ip({'address': '2.2.2.2',
                                          'instance_uuid': instance.uuid})
        db.floating_ip_fixed_ip_associate(self.ctxt,
                                          float_ip.address,
                                          fixed_ip,
                                          'host')
        float_ips = db.floating_ip_get_all(self.ctxt)
        self.assertEqual(1, len(float_ips))
        self.assertEqual(float_ip.address, float_ips[0].address)
        self.assertEqual(fixed_ip, float_ips[0].fixed_ip.address)
        self.assertEqual(instance.uuid, float_ips[0].fixed_ip.instance_uuid)

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
        for host, addresses in hosts.items():
            hosts_with_float_ips[host] = []
            for address in addresses:
                float_ip = self._create_floating_ip({'host': host,
                                                     'address': address})
                hosts_with_float_ips[host].append(float_ip)

        for host, float_ips in hosts_with_float_ips.items():
            real_float_ips = db.floating_ip_get_all_by_host(self.ctxt, host)
            self._assertEqualListsOfObjects(float_ips, real_float_ips,
                                            ignored_keys="fixed_ip")

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
        for project_id, addresses in projects.items():
            projects_with_float_ips[project_id] = []
            for address in addresses:
                float_ip = self._create_floating_ip({'project_id': project_id,
                                                     'address': address})
                projects_with_float_ips[project_id].append(float_ip)

        for project_id, float_ips in projects_with_float_ips.items():
            real_float_ips = db.floating_ip_get_all_by_project(self.ctxt,
                                                               project_id)
            self._assertEqualListsOfObjects(float_ips, real_float_ips,
                                            ignored_keys='fixed_ip')

    def test_floating_ip_get_all_by_project_not_authorized(self):
        ctxt = context.RequestContext(user_id='a', project_id='abc',
                                      is_admin=False)
        self.assertRaises(exception.Forbidden,
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

    @mock.patch.object(query.Query, 'first', side_effect=db_exc.DBError())
    def test_floating_ip_get_by_invalid_address(self, mock_query):
        self.assertRaises(exception.InvalidIpAddressError,
                          db.floating_ip_get_by_address,
                          self.ctxt, 'non_exists_host')
        mock_query.assert_called_once_with()

    def test_floating_ip_get_by_fixed_address(self):
        fixed_float = [
            ('1.1.1.1', '2.2.2.1'),
            ('1.1.1.2', '2.2.2.2'),
            ('1.1.1.3', '2.2.2.3')
        ]

        for fixed_addr, float_addr in fixed_float:
            project_id = self.ctxt.project_id
            self._create_floating_ip({'address': float_addr,
                                      'project_id': project_id})
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
            project_id = self.ctxt.project_id
            self._create_floating_ip({'address': float_addr,
                                      'project_id': project_id})
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
        floating_ref = db.floating_ip_update(self.ctxt, float_ip['address'],
                                             values)
        self.assertIsNotNone(floating_ref)
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

    def test_destroy_with_equal_any_constraint_met_single_value(self):
        ctx = context.get_admin_context()
        instance = db.instance_create(ctx, {'task_state': 'deleting'})
        constraint = db.constraint(task_state=db.equal_any('deleting'))
        db.instance_destroy(ctx, instance['uuid'], constraint)
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          ctx, instance['uuid'])

    def test_destroy_with_equal_any_constraint_met(self):
        ctx = context.get_admin_context()
        instance = db.instance_create(ctx, {'task_state': 'deleting'})
        constraint = db.constraint(task_state=db.equal_any('deleting',
                                                           'error'))
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
        self.useFixture(utils_fixture.TimeFixture(now))
        start_time = now - datetime.timedelta(seconds=10)

        expected_vol_usages = {
            u'1': {'volume_id': u'1',
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
            u'2': {'volume_id': u'2',
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
                   'tot_last_refreshed': None}
        }

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
        for usage in vol_usages:
            _compare(usage, expected_vol_usages[usage.volume_id])

    def test_vol_usage_update_totals_update(self):
        ctxt = context.get_admin_context()
        now = datetime.datetime(1, 1, 1, 1, 0, 0)
        start_time = now - datetime.timedelta(seconds=10)
        now1 = now + datetime.timedelta(minutes=1)
        now2 = now + datetime.timedelta(minutes=2)
        now3 = now + datetime.timedelta(minutes=3)

        time_fixture = self.useFixture(utils_fixture.TimeFixture(now))
        db.vol_usage_update(ctxt, u'1', rd_req=100, rd_bytes=200,
                            wr_req=300, wr_bytes=400,
                            instance_id='fake-instance-uuid',
                            project_id='fake-project-uuid',
                            user_id='fake-user-uuid',
                            availability_zone='fake-az')
        current_usage = db.vol_get_usage_by_time(ctxt, start_time)[0]
        self.assertEqual(current_usage['tot_reads'], 0)
        self.assertEqual(current_usage['curr_reads'], 100)

        time_fixture.advance_time_delta(now1 - now)
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

        time_fixture.advance_time_delta(now2 - now1)
        db.vol_usage_update(ctxt, u'1', rd_req=300, rd_bytes=400,
                            wr_req=500, wr_bytes=600,
                            instance_id='fake-instance-uuid',
                            project_id='fake-project-uuid',
                            availability_zone='fake-az',
                            user_id='fake-user-uuid')
        current_usage = db.vol_get_usage_by_time(ctxt, start_time)[0]
        self.assertEqual(current_usage['tot_reads'], 200)
        self.assertEqual(current_usage['curr_reads'], 300)

        time_fixture.advance_time_delta(now3 - now2)
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

        self.assertEqual(1, len(vol_usages))
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
        # less than the previous values
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
        # right after an instance has rebooted / recovered and before
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
        # less than the previous values
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
        self.begin = (now - datetime.timedelta(seconds=10)).isoformat()
        self.end = (now - datetime.timedelta(seconds=5)).isoformat()
        self.task_name = 'fake-task-name'
        self.host = 'fake-host'
        self.message = 'Fake task message'
        db.task_log_begin_task(self.context, self.task_name, self.begin,
                               self.end, self.host, message=self.message)

    def test_task_log_get(self):
        result = db.task_log_get(self.context, self.task_name, self.begin,
                                 self.end, self.host)
        self.assertEqual(result['task_name'], self.task_name)
        self.assertEqual(result['period_beginning'],
                         timeutils.parse_strtime(self.begin))
        self.assertEqual(result['period_ending'],
                         timeutils.parse_strtime(self.end))
        self.assertEqual(result['host'], self.host)
        self.assertEqual(result['message'], self.message)

    def test_task_log_get_all(self):
        result = db.task_log_get_all(self.context, self.task_name, self.begin,
                                     self.end, host=self.host)
        self.assertEqual(len(result), 1)
        result = db.task_log_get_all(self.context, self.task_name, self.begin,
                                     self.end, host=self.host, state='')
        self.assertEqual(len(result), 0)

    def test_task_log_begin_task(self):
        db.task_log_begin_task(self.context, 'fake', self.begin,
                               self.end, self.host, task_items=42,
                               message=self.message)
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

    def test_task_log_end_task_task_not_running(self):
        self.assertRaises(exception.TaskNotRunning,
                          db.task_log_end_task, self.context, 'nonexistent',
                          self.begin, self.end, self.host, 42,
                          message=self.message)


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
        self.assertIsNotNone(bdm)
        self.assertTrue(uuidutils.is_uuid_like(bdm['uuid']))

    def test_block_device_mapping_create_with_blank_uuid(self):
        bdm = self._create_bdm({'uuid': ''})
        self.assertIsNotNone(bdm)
        self.assertTrue(uuidutils.is_uuid_like(bdm['uuid']))

    def test_block_device_mapping_create_with_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID,
                          self._create_bdm, {'uuid': 'invalid-uuid'})

    def test_block_device_mapping_create_with_attachment_id(self):
        bdm = self._create_bdm({'attachment_id': uuidsentinel.attachment_id})
        self.assertEqual(uuidsentinel.attachment_id, bdm.attachment_id)

    def test_block_device_mapping_update(self):
        bdm = self._create_bdm({})
        self.assertIsNone(bdm.attachment_id)
        result = db.block_device_mapping_update(
            self.ctxt, bdm['id'],
            {'destination_type': 'moon',
             'attachment_id': uuidsentinel.attachment_id},
            legacy=False)
        uuid = bdm['instance_uuid']
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(bdm_real[0]['destination_type'], 'moon')
        self.assertEqual(uuidsentinel.attachment_id, bdm_real[0].attachment_id)
        # Also make sure the update call returned correct data
        self.assertEqual(dict(bdm_real[0]),
                         dict(result))

    def test_block_device_mapping_update_or_create(self):
        values = {
            'instance_uuid': self.instance['uuid'],
            'device_name': 'fake_name',
            'source_type': 'volume',
            'destination_type': 'volume'
        }
        # check create
        bdm = db.block_device_mapping_update_or_create(self.ctxt,
                                                       copy.deepcopy(values),
                                                       legacy=False)
        self.assertTrue(uuidutils.is_uuid_like(bdm['uuid']))
        uuid = values['instance_uuid']
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdm_real), 1)
        self.assertEqual(bdm_real[0]['device_name'], 'fake_name')

        # check update
        bdm0 = copy.deepcopy(values)
        bdm0['destination_type'] = 'camelot'
        db.block_device_mapping_update_or_create(self.ctxt, bdm0,
                                                 legacy=False)
        bdm_real = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdm_real), 1)
        bdm_real = bdm_real[0]
        self.assertEqual(bdm_real['device_name'], 'fake_name')
        self.assertEqual(bdm_real['destination_type'], 'camelot')

        # check create without device_name
        bdm1 = copy.deepcopy(values)
        bdm1['device_name'] = None
        db.block_device_mapping_update_or_create(self.ctxt, bdm1, legacy=False)
        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        with_device_name = [b for b in bdms if b['device_name'] is not None]
        without_device_name = [b for b in bdms if b['device_name'] is None]
        self.assertEqual(2, len(bdms))
        self.assertEqual(len(with_device_name), 1,
                         'expected 1 bdm with device_name, found %d' %
                         len(with_device_name))
        self.assertEqual(len(without_device_name), 1,
                         'expected 1 bdm without device_name, found %d' %
                         len(without_device_name))

        # check create multiple devices without device_name
        bdm2 = dict(values)
        bdm2['device_name'] = None
        db.block_device_mapping_update_or_create(self.ctxt, bdm2, legacy=False)
        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        with_device_name = [b for b in bdms if b['device_name'] is not None]
        without_device_name = [b for b in bdms if b['device_name'] is None]
        self.assertEqual(len(with_device_name), 1,
                         'expected 1 bdm with device_name, found %d' %
                         len(with_device_name))
        self.assertEqual(len(without_device_name), 2,
                         'expected 2 bdms without device_name, found %d' %
                         len(without_device_name))

    def test_block_device_mapping_update_or_create_with_uuid(self):
        # Test that we are able to change device_name when calling
        # block_device_mapping_update_or_create with a uuid.
        bdm = self._create_bdm({})
        values = {
            'uuid': bdm['uuid'],
            'instance_uuid': bdm['instance_uuid'],
            'device_name': 'foobar',
        }
        db.block_device_mapping_update_or_create(self.ctxt, values,
                                                 legacy=False)
        real_bdms = db.block_device_mapping_get_all_by_instance(
            self.ctxt, bdm['instance_uuid'])
        self.assertEqual(1, len(real_bdms))
        self.assertEqual('foobar', real_bdms[0]['device_name'])

    def test_block_device_mapping_update_or_create_with_blank_uuid(self):
        # Test that create with block_device_mapping_update_or_create raises an
        # exception if given an invalid uuid
        values = {
            'uuid': '',
            'instance_uuid': uuidsentinel.instance,
            'device_name': 'foobar',
        }
        db.block_device_mapping_update_or_create(self.ctxt, values)

        real_bdms = db.block_device_mapping_get_all_by_instance(
            self.ctxt, uuidsentinel.instance)
        self.assertEqual(1, len(real_bdms))
        self.assertTrue(uuidutils.is_uuid_like(real_bdms[0]['uuid']))

    def test_block_device_mapping_update_or_create_with_invalid_uuid(self):
        # Test that create with block_device_mapping_update_or_create raises an
        # exception if given an invalid uuid
        values = {
            'uuid': 'invalid-uuid',
            'instance_uuid': uuidsentinel.instance,
            'device_name': 'foobar',
        }
        self.assertRaises(exception.InvalidUUID,
                          db.block_device_mapping_update_or_create,
                          self.ctxt, values)

    def test_block_device_mapping_update_or_create_multiple_ephemeral(self):
        uuid = self.instance['uuid']
        values = {
            'instance_uuid': uuid,
            'source_type': 'blank',
            'guest_format': 'myformat',
        }

        bdm1 = dict(values)
        bdm1['device_name'] = '/dev/sdb'
        db.block_device_mapping_update_or_create(self.ctxt, bdm1, legacy=False)

        bdm2 = dict(values)
        bdm2['device_name'] = '/dev/sdc'
        db.block_device_mapping_update_or_create(self.ctxt, bdm2, legacy=False)

        bdm_real = sorted(
            db.block_device_mapping_get_all_by_instance(self.ctxt, uuid),
            key=lambda bdm: bdm['device_name']
        )

        self.assertEqual(len(bdm_real), 2)
        for bdm, device_name in zip(bdm_real, ['/dev/sdb', '/dev/sdc']):
            self.assertEqual(bdm['device_name'], device_name)
            self.assertEqual(bdm['guest_format'], 'myformat')

    def test_block_device_mapping_update_or_create_check_remove_virt(self):
        uuid = self.instance['uuid']
        values = {
            'instance_uuid': uuid,
            'source_type': 'blank',
            'destination_type': 'local',
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

    def test_block_device_mapping_get_all_by_instance_uuids(self):
        uuid1 = self.instance['uuid']
        uuid2 = db.instance_create(self.ctxt, {})['uuid']

        bdms_values = [{'instance_uuid': uuid1,
                        'device_name': '/dev/vda'},
                       {'instance_uuid': uuid2,
                        'device_name': '/dev/vdb'},
                       {'instance_uuid': uuid2,
                        'device_name': '/dev/vdc'}]

        for bdm in bdms_values:
            self._create_bdm(bdm)

        bdms = db.block_device_mapping_get_all_by_instance_uuids(
            self.ctxt, [])
        self.assertEqual(len(bdms), 0)

        bdms = db.block_device_mapping_get_all_by_instance_uuids(
            self.ctxt, [uuid2])
        self.assertEqual(len(bdms), 2)

        bdms = db.block_device_mapping_get_all_by_instance_uuids(
            self.ctxt, [uuid1, uuid2])
        self.assertEqual(len(bdms), 3)

    def test_block_device_mapping_get_all_by_instance(self):
        uuid1 = self.instance['uuid']
        uuid2 = db.instance_create(self.ctxt, {})['uuid']

        bdms_values = [{'instance_uuid': uuid1,
                        'device_name': '/dev/vda'},
                       {'instance_uuid': uuid2,
                        'device_name': '/dev/vdb'},
                       {'instance_uuid': uuid2,
                        'device_name': '/dev/vdc'}]

        for bdm in bdms_values:
            self._create_bdm(bdm)

        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid1)
        self.assertEqual(len(bdms), 1)
        self.assertEqual(bdms[0]['device_name'], '/dev/vda')

        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid2)
        self.assertEqual(len(bdms), 2)

    def test_block_device_mapping_destroy(self):
        bdm = self._create_bdm({})
        db.block_device_mapping_destroy(self.ctxt, bdm['id'])
        bdm = db.block_device_mapping_get_all_by_instance(self.ctxt,
                                                          bdm['instance_uuid'])
        self.assertEqual(len(bdm), 0)

    def test_block_device_mapping_destroy_by_instance_and_volume(self):
        vol_id1 = '69f5c254-1a5b-4fff-acf7-cb369904f58f'
        vol_id2 = '69f5c254-1a5b-4fff-acf7-cb369904f59f'

        self._create_bdm({'device_name': '/dev/vda', 'volume_id': vol_id1})
        self._create_bdm({'device_name': '/dev/vdb', 'volume_id': vol_id2})

        uuid = self.instance['uuid']
        db.block_device_mapping_destroy_by_instance_and_volume(self.ctxt, uuid,
                                                               vol_id1)
        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdms), 1)
        self.assertEqual(bdms[0]['device_name'], '/dev/vdb')

    def test_block_device_mapping_destroy_by_instance_and_device(self):
        self._create_bdm({'device_name': '/dev/vda'})
        self._create_bdm({'device_name': '/dev/vdb'})

        uuid = self.instance['uuid']
        params = (self.ctxt, uuid, '/dev/vdb')
        db.block_device_mapping_destroy_by_instance_and_device(*params)

        bdms = db.block_device_mapping_get_all_by_instance(self.ctxt, uuid)
        self.assertEqual(len(bdms), 1)
        self.assertEqual(bdms[0]['device_name'], '/dev/vda')

    def test_block_device_mapping_get_all_by_volume_id(self):
        self._create_bdm({'volume_id': 'fake_id'})
        self._create_bdm({'volume_id': 'fake_id'})
        bdms = db.block_device_mapping_get_all_by_volume_id(self.ctxt,
                                                            'fake_id')
        self.assertEqual(bdms[0]['volume_id'], 'fake_id')
        self.assertEqual(bdms[1]['volume_id'], 'fake_id')
        self.assertEqual(2, len(bdms))

    def test_block_device_mapping_get_all_by_volume_id_join_instance(self):
        self._create_bdm({'volume_id': 'fake_id'})
        bdms = db.block_device_mapping_get_all_by_volume_id(self.ctxt,
                                                            'fake_id',
                                                            ['instance'])
        self.assertEqual(bdms[0]['volume_id'], 'fake_id')
        self.assertEqual(bdms[0]['instance']['uuid'], self.instance['uuid'])

    def test_block_device_mapping_get_by_instance_and_volume_id(self):
        self._create_bdm({'volume_id': 'fake_id'})
        bdm = db.block_device_mapping_get_by_instance_and_volume_id(self.ctxt,
                'fake_id', self.instance['uuid'])
        self.assertEqual(bdm['volume_id'], 'fake_id')
        self.assertEqual(bdm['instance_uuid'], self.instance['uuid'])

    def test_block_device_mapping_get_by_instance_and_volume_id_multiplebdms(
            self):
        self._create_bdm({'volume_id': 'fake_id',
                          'instance_uuid': self.instance['uuid']})
        self._create_bdm({'volume_id': 'fake_id',
                          'instance_uuid': self.instance['uuid']})
        db_bdm = db.block_device_mapping_get_by_instance_and_volume_id(
            self.ctxt, 'fake_id', self.instance['uuid'])
        self.assertIsNotNone(db_bdm)
        self.assertEqual(self.instance['uuid'], db_bdm['instance_uuid'])

    def test_block_device_mapping_get_by_instance_and_volume_id_multiattach(
            self):
        self.instance2 = db.instance_create(self.ctxt, {})
        self._create_bdm({'volume_id': 'fake_id',
                          'instance_uuid': self.instance['uuid']})
        self._create_bdm({'volume_id': 'fake_id',
                          'instance_uuid': self.instance2['uuid']})
        bdm = db.block_device_mapping_get_by_instance_and_volume_id(self.ctxt,
                'fake_id', self.instance['uuid'])
        self.assertEqual(bdm['volume_id'], 'fake_id')
        self.assertEqual(bdm['instance_uuid'], self.instance['uuid'])

        bdm2 = db.block_device_mapping_get_by_instance_and_volume_id(
                self.ctxt, 'fake_id', self.instance2['uuid'])
        self.assertEqual(bdm2['volume_id'], 'fake_id')
        self.assertEqual(bdm2['instance_uuid'], self.instance2['uuid'])


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
        agent_build = db.agent_build_create(
            self.ctxt, {'hypervisor': 'kvm', 'os': 'FreeBSD',
                        'architecture': fields.Architecture.X86_64})
        self.assertIsNone(db.agent_build_get_by_triple(
            self.ctxt, 'kvm', 'FreeBSD', 'i386'))
        self._assertEqualObjects(agent_build, db.agent_build_get_by_triple(
            self.ctxt, 'kvm', 'FreeBSD', fields.Architecture.X86_64))

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
                  'architecture': fields.Architecture.X86_64}
        db.agent_build_create(self.ctxt, values)
        self.assertRaises(exception.AgentBuildExists, db.agent_build_create,
                          self.ctxt, values)

    def test_agent_build_get_all_by_hypervisor(self):
        values = {'hypervisor': 'kvm', 'os': 'FreeBSD',
                  'architecture': fields.Architecture.X86_64}
        created = db.agent_build_create(self.ctxt, values)
        actual = db.agent_build_get_all(self.ctxt, hypervisor='kvm')
        self._assertEqualListsOfObjects([created], actual)


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
            'uuid': uuidutils.generate_uuid(),
            'tag': 'fake-tag',
        }

    def _create_virt_interface(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.virtual_interface_create(self.ctxt, v)

    def test_virtual_interface_create(self):
        vif = self._create_virt_interface({})
        self.assertIsNotNone(vif['id'])
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

    @mock.patch.object(query.Query, 'first', side_effect=db_exc.DBError())
    def test_virtual_interface_get_by_address_data_error_exception(self,
                                                mock_query):
        self.assertRaises(exception.InvalidIpAddressError,
                          db.virtual_interface_get_by_address,
                          self.ctxt,
                          "i.nv.ali.ip")
        mock_query.assert_called_once_with()

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
        # multiple nic of same instance
        vifs2 = [self._create_virt_interface({'address': 'fake3',
                                              'instance_uuid': inst_uuid2}),
                 self._create_virt_interface({'address': 'fake4',
                                              'instance_uuid': inst_uuid2})]
        vifs1_real = db.virtual_interface_get_by_instance(self.ctxt,
                                                          self.instance_uuid)
        vifs2_real = db.virtual_interface_get_by_instance(self.ctxt,
                                                          inst_uuid2)
        self._assertEqualListsOfObjects(vifs1, vifs1_real)
        self._assertEqualOrderedListOfObjects(vifs2, vifs2_real)

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

    def test_virtual_interface_delete(self):
        values = [dict(address='fake1'), dict(address='fake2'),
                  dict(address='fake3')]
        vifs = []
        for vals in values:
            vifs.append(self._create_virt_interface(
                dict(vals, instance_uuid=self.instance_uuid)))

        db.virtual_interface_delete(self.ctxt, vifs[0]['id'])

        real_vifs = db.virtual_interface_get_by_instance(self.ctxt,
                                                         self.instance_uuid)
        self.assertEqual(2, len(real_vifs))

    def test_virtual_interface_get_all(self):
        inst_uuid2 = db.instance_create(self.ctxt, {})['uuid']
        values = [dict(address='fake1'), dict(address='fake2'),
                  dict(address='fake3', instance_uuid=inst_uuid2)]

        vifs = [self._create_virt_interface(val) for val in values]
        real_vifs = db.virtual_interface_get_all(self.ctxt)
        self._assertEqualListsOfObjects(vifs, real_vifs)

    def test_virtual_interface_update(self):
        instance_uuid = db.instance_create(self.ctxt, {})['uuid']
        network_id = db.network_create_safe(self.ctxt, {})['id']
        create = {'address': 'fake1',
                  'network_id': network_id,
                  'instance_uuid': instance_uuid,
                  'uuid': uuidsentinel.vif_uuid,
                  'tag': 'foo'}
        update = {'tag': 'bar'}
        updated = {'address': 'fake1',
                   'network_id': network_id,
                   'instance_uuid': instance_uuid,
                   'uuid': uuidsentinel.vif_uuid,
                   'tag': 'bar',
                   'deleted': 0}
        ignored_keys = ['created_at', 'id', 'deleted_at', 'updated_at']
        vif_addr = db.virtual_interface_create(self.ctxt, create)['address']
        db.virtual_interface_update(self.ctxt, vif_addr, update)
        updated_vif = db.virtual_interface_get_by_address(self.ctxt,
                                                          updated['address'])
        self._assertEqualObjects(updated, updated_vif, ignored_keys)


@mock.patch('time.sleep', new=lambda x: None)
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
            network.id, virtual_interface_id=virtual_interface['id'])
        return network, instance

    def test_network_get_associated_default_route(self):
        network, instance = self._get_associated_fixed_ip('host.net',
            '192.0.2.0/30', '192.0.2.1')
        network2 = db.network_create_safe(self.ctxt,
            {'project_id': 'project1', 'cidr': '192.0.3.0/30'})
        ip = '192.0.3.1'
        virtual_interface = db.virtual_interface_create(self.ctxt,
            {'instance_uuid': instance.uuid, 'network_id': network2.id,
            'address': ip})
        db.fixed_ip_create(self.ctxt, {'address': ip,
            'network_id': network2.id, 'allocated': True,
            'virtual_interface_id': virtual_interface.id})
        db.fixed_ip_associate(self.ctxt, ip, instance.uuid,
            network2.id)
        data = db.network_get_associated_fixed_ips(self.ctxt, network.id)
        self.assertEqual(1, len(data))
        self.assertTrue(data[0]['default_route'])
        data = db.network_get_associated_fixed_ips(self.ctxt, network2.id)
        self.assertEqual(1, len(data))
        self.assertFalse(data[0]['default_route'])

    def test_network_get_associated_fixed_ips(self):
        network, instance = self._get_associated_fixed_ip('host.net',
            '192.0.2.0/30', '192.0.2.1')
        data = db.network_get_associated_fixed_ips(self.ctxt, network.id)
        self.assertEqual(1, len(data))
        self.assertEqual('192.0.2.1', data[0]['address'])
        self.assertEqual('192.0.2.1', data[0]['vif_address'])
        self.assertEqual(instance.uuid, data[0]['instance_uuid'])
        self.assertTrue(data[0][fields.PciDeviceStatus.ALLOCATED])

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
        db.network_get(self.ctxt, network['id'])
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
        self.assertTrue(db.network_in_use_on_host(self.ctxt, 1, 'foo'))
        self.assertFalse(db.network_in_use_on_host(self.ctxt, 1, 'bar'))

    def test_network_update_nonexistent(self):
        self.assertRaises(exception.NetworkNotFound,
            db.network_update, self.ctxt, 123456, {})

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
        self.assertRaises(exception.NetworkNotFound, db.network_set_host,
                          self.ctxt, 123456, 'nonexistent')

    def test_network_set_host_already_set_correct(self):
        values = {'host': 'example.com', 'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)
        self.assertIsNone(db.network_set_host(self.ctxt, network.id,
                          'example.com'))

    def test_network_set_host_already_set_incorrect(self):
        values = {'host': 'example.com', 'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)
        self.assertIsNone(db.network_set_host(self.ctxt, network.id,
                                              'new.example.com'))

    def test_network_set_host_with_initially_no_host(self):
        values = {'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)
        db.network_set_host(self.ctxt, network.id, 'example.com')
        self.assertEqual('example.com',
            db.network_get(self.ctxt, network.id).host)

    def test_network_set_host_succeeds_retry_on_deadlock(self):
        values = {'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)

        def fake_update(params):
            if mock_update.call_count == 1:
                raise db_exc.DBDeadlock()
            else:
                return 1

        with mock.patch('sqlalchemy.orm.query.Query.update',
                        side_effect=fake_update) as mock_update:
            db.network_set_host(self.ctxt, network.id, 'example.com')
            self.assertEqual(2, mock_update.call_count)

    def test_network_set_host_succeeds_retry_on_no_rows_updated(self):
        values = {'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)

        def fake_update(params):
            if mock_update.call_count == 1:
                return 0
            else:
                return 1

        with mock.patch('sqlalchemy.orm.query.Query.update',
                        side_effect=fake_update) as mock_update:
            db.network_set_host(self.ctxt, network.id, 'example.com')
            self.assertEqual(2, mock_update.call_count)

    def test_network_set_host_failed_with_retry_on_no_rows_updated(self):
        values = {'project_id': 'project1'}
        network = db.network_create_safe(self.ctxt, values)

        with mock.patch('sqlalchemy.orm.query.Query.update',
                        return_value=0) as mock_update:
            self.assertRaises(exception.NetworkSetHostFailed,
                              db.network_set_host, self.ctxt, network.id,
                              'example.com')
            # 5 retries + initial attempt
            self.assertEqual(6, mock_update.call_count)

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
        db.network_get_all_by_host(self.ctxt, host)
        self._assertEqualListsOfObjects([net1, net2],
            db.network_get_all_by_host(self.ctxt, host))
        # network with instance with host set
        net3 = db.network_create_safe(self.ctxt, {})
        instance = db.instance_create(self.ctxt, {'host': host})
        db.fixed_ip_create(self.ctxt, {'network_id': net3.id,
            'instance_uuid': instance.uuid})
        self._assertEqualListsOfObjects([net1, net2, net3],
            db.network_get_all_by_host(self.ctxt, host))

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

    def test_network_get_all_admin_user(self):
        network1 = db.network_create_safe(self.ctxt, {})
        network2 = db.network_create_safe(self.ctxt,
                                          {'project_id': 'project1'})
        self._assertEqualListsOfObjects([network1, network2],
                                        db.network_get_all(self.ctxt,
                                                           project_only=True))

    def test_network_get_all_normal_user(self):
        normal_ctxt = context.RequestContext('fake', 'fake')
        db.network_create_safe(self.ctxt, {})
        db.network_create_safe(self.ctxt, {'project_id': 'project1'})
        network1 = db.network_create_safe(self.ctxt,
                                          {'project_id': 'fake'})
        network_db = db.network_get_all(normal_ctxt, project_only=True)
        self.assertEqual(1, len(network_db))
        self._assertEqualObjects(network1, network_db[0])

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
            'type': 'ssh',
            'user_id': 'test_user_id_1',
            'public_key': 'test_public_key_1',
            'fingerprint': 'test_fingerprint_1'
        }
        key_pair = self._create_key_pair(param)

        self.assertIsNotNone(key_pair['id'])
        ignored_keys = ['deleted', 'created_at', 'updated_at',
                        'deleted_at', 'id']
        self._assertEqualObjects(key_pair, param, ignored_keys)

    def test_key_pair_create_with_duplicate_name(self):
        params = {'name': 'test_name', 'user_id': 'test_user_id',
                  'type': 'ssh'}
        self._create_key_pair(params)
        self.assertRaises(exception.KeyPairExists, self._create_key_pair,
                          params)

    def test_key_pair_get(self):
        params = [
            {'name': 'test_1', 'user_id': 'test_user_id_1', 'type': 'ssh'},
            {'name': 'test_2', 'user_id': 'test_user_id_2', 'type': 'ssh'},
            {'name': 'test_3', 'user_id': 'test_user_id_3', 'type': 'ssh'}
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
        param = {'name': 'test_1', 'user_id': 'test_user_id_1', 'type': 'ssh'}
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
            {'name': 'test_1', 'user_id': 'test_user_id_1', 'type': 'ssh'},
            {'name': 'test_2', 'user_id': 'test_user_id_1', 'type': 'ssh'},
            {'name': 'test_3', 'user_id': 'test_user_id_2', 'type': 'ssh'}
        ]
        key_pairs_user_1 = [self._create_key_pair(p) for p in params
                            if p['user_id'] == 'test_user_id_1']
        key_pairs_user_2 = [self._create_key_pair(p) for p in params
                            if p['user_id'] == 'test_user_id_2']

        real_keys_1 = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id_1')
        real_keys_2 = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id_2')

        self._assertEqualListsOfObjects(key_pairs_user_1, real_keys_1)
        self._assertEqualListsOfObjects(key_pairs_user_2, real_keys_2)

    def test_key_pair_get_all_by_user_limit_and_marker(self):
        params = [
            {'name': 'test_1', 'user_id': 'test_user_id', 'type': 'ssh'},
            {'name': 'test_2', 'user_id': 'test_user_id', 'type': 'ssh'},
            {'name': 'test_3', 'user_id': 'test_user_id', 'type': 'ssh'}
        ]

        # check all 3 keypairs
        keys = [self._create_key_pair(p) for p in params]
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id')
        self._assertEqualListsOfObjects(keys, db_keys)

        # check only 1 keypair
        expected_keys = [keys[0]]
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id',
                                              limit=1)
        self._assertEqualListsOfObjects(expected_keys, db_keys)

        # check keypairs after 'test_1'
        expected_keys = [keys[1], keys[2]]
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id',
                                              marker='test_1')
        self._assertEqualListsOfObjects(expected_keys, db_keys)

        # check only 1 keypairs after 'test_1'
        expected_keys = [keys[1]]
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_id',
                                              limit=1,
                                              marker='test_1')
        self._assertEqualListsOfObjects(expected_keys, db_keys)

        # check non-existing keypair
        self.assertRaises(exception.MarkerNotFound,
                          db.key_pair_get_all_by_user,
                          self.ctxt, 'test_user_id',
                          limit=1, marker='unknown_kp')

    def test_key_pair_get_all_by_user_different_users(self):
        params1 = [
            {'name': 'test_1', 'user_id': 'test_user_1', 'type': 'ssh'},
            {'name': 'test_2', 'user_id': 'test_user_1', 'type': 'ssh'},
            {'name': 'test_3', 'user_id': 'test_user_1', 'type': 'ssh'}
        ]
        params2 = [
            {'name': 'test_1', 'user_id': 'test_user_2', 'type': 'ssh'},
            {'name': 'test_2', 'user_id': 'test_user_2', 'type': 'ssh'},
            {'name': 'test_3', 'user_id': 'test_user_2', 'type': 'ssh'}
        ]

        # create keypairs for two users
        keys1 = [self._create_key_pair(p) for p in params1]
        keys2 = [self._create_key_pair(p) for p in params2]

        # check all 2 keypairs for test_user_1
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_1')
        self._assertEqualListsOfObjects(keys1, db_keys)

        # check all 2 keypairs for test_user_2
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_2')
        self._assertEqualListsOfObjects(keys2, db_keys)

        # check only 1 keypair for test_user_1
        expected_keys = [keys1[0]]
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_1',
                                              limit=1)
        self._assertEqualListsOfObjects(expected_keys, db_keys)

        # check keypairs after 'test_1' for test_user_2
        expected_keys = [keys2[1], keys2[2]]
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_2',
                                              marker='test_1')
        self._assertEqualListsOfObjects(expected_keys, db_keys)

        # check only 1 keypairs after 'test_1' for test_user_1
        expected_keys = [keys1[1]]
        db_keys = db.key_pair_get_all_by_user(self.ctxt, 'test_user_1',
                                              limit=1,
                                              marker='test_1')
        self._assertEqualListsOfObjects(expected_keys, db_keys)

        # check non-existing keypair for test_user_2
        self.assertRaises(exception.MarkerNotFound,
                          db.key_pair_get_all_by_user,
                          self.ctxt, 'test_user_2',
                          limit=1, marker='unknown_kp')

    def test_key_pair_count_by_user(self):
        params = [
            {'name': 'test_1', 'user_id': 'test_user_id_1', 'type': 'ssh'},
            {'name': 'test_2', 'user_id': 'test_user_id_1', 'type': 'ssh'},
            {'name': 'test_3', 'user_id': 'test_user_id_2', 'type': 'ssh'}
        ]
        for p in params:
            self._create_key_pair(p)

        count_1 = db.key_pair_count_by_user(self.ctxt, 'test_user_id_1')
        self.assertEqual(count_1, 2)

        count_2 = db.key_pair_count_by_user(self.ctxt, 'test_user_id_2')
        self.assertEqual(count_2, 1)

    def test_key_pair_destroy(self):
        param = {'name': 'test_1', 'user_id': 'test_user_id_1', 'type': 'ssh'}
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

    def test_quota_destroy_all_by_project(self):
        _quota_create(self.ctxt, 'project1', 'user1')
        db.quota_destroy_all_by_project(self.ctxt, 'project1')
        self.assertEqual(db.quota_get_all_by_project(self.ctxt, 'project1'),
                            {'project_id': 'project1'})
        self.assertEqual(db.quota_get_all_by_project_and_user(self.ctxt,
                            'project1', 'user1'),
                            {'project_id': 'project1', 'user_id': 'user1'})

    def test_quota_destroy_all_by_project_and_user(self):
        _quota_create(self.ctxt, 'project1', 'user1')
        db.quota_destroy_all_by_project_and_user(self.ctxt, 'project1',
                                                 'user1')
        self.assertEqual(db.quota_get_all_by_project_and_user(self.ctxt,
                            'project1', 'user1'),
                            {'project_id': 'project1',
                             'user_id': 'user1'})

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
        self.values = [uuidutils.generate_uuid() for i in range(3)]
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
                          self.ctxt, uuidsentinel.uuid1)


class ComputeNodeTestCase(test.TestCase, ModelsObjectComparatorMixin):

    _ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at', 'updated_at']

    def setUp(self):
        super(ComputeNodeTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.service_dict = dict(host='host1', binary='nova-compute',
                            topic=compute_rpcapi.RPC_TOPIC,
                            report_count=1, disabled=False)
        self.service = db.service_create(self.ctxt, self.service_dict)
        self.compute_node_dict = dict(vcpus=2, memory_mb=1024, local_gb=2048,
                                 uuid=uuidutils.generate_uuid(),
                                 vcpus_used=0, memory_mb_used=0,
                                 local_gb_used=0, free_ram_mb=1024,
                                 free_disk_gb=2048, hypervisor_type="xen",
                                 hypervisor_version=1, cpu_info="",
                                 running_vms=0, current_workload=0,
                                 service_id=self.service['id'],
                                 host=self.service['host'],
                                 disk_available_least=100,
                                 hypervisor_hostname='abracadabra104',
                                 host_ip='127.0.0.1',
                                 supported_instances='',
                                 pci_stats='',
                                 metrics='',
                                 mapped=0,
                                 extra_resources='',
                                 cpu_allocation_ratio=16.0,
                                 ram_allocation_ratio=1.5,
                                 disk_allocation_ratio=1.0,
                                 stats='', numa_topology='')
        # add some random stats
        self.stats = dict(num_instances=3, num_proj_12345=2,
                     num_proj_23456=2, num_vm_building=3)
        self.compute_node_dict['stats'] = jsonutils.dumps(self.stats)
        self.flags(reserved_host_memory_mb=0)
        self.flags(reserved_host_disk_mb=0)
        self.item = db.compute_node_create(self.ctxt, self.compute_node_dict)

    def test_compute_node_create(self):
        self._assertEqualObjects(self.compute_node_dict, self.item,
                                ignored_keys=self._ignored_keys + ['stats'])
        new_stats = jsonutils.loads(self.item['stats'])
        self.assertEqual(self.stats, new_stats)

    def test_compute_node_create_duplicate_host_hypervisor_hostname(self):
        """Tests to make sure that DBDuplicateEntry is raised when trying to
        create a duplicate ComputeNode with the same host and
        hypervisor_hostname values but different uuid values. This makes
        sure that when _compute_node_get_and_update_deleted returns None
        the DBDuplicateEntry is re-raised.
        """
        other_node = dict(self.compute_node_dict)
        other_node['uuid'] = uuidutils.generate_uuid()
        self.assertRaises(db_exc.DBDuplicateEntry,
                          db.compute_node_create, self.ctxt, other_node)

    def test_compute_node_get_all(self):
        nodes = db.compute_node_get_all(self.ctxt)
        self.assertEqual(1, len(nodes))
        node = nodes[0]
        self._assertEqualObjects(self.compute_node_dict, node,
                    ignored_keys=self._ignored_keys +
                                 ['stats', 'service'])
        new_stats = jsonutils.loads(node['stats'])
        self.assertEqual(self.stats, new_stats)

    def test_compute_node_get_all_mapped_less_than(self):
        cn = dict(self.compute_node_dict,
                  hostname='foo',
                  hypervisor_hostname='foo',
                  mapped=None,
                  uuid=uuidutils.generate_uuid())
        db.compute_node_create(self.ctxt, cn)
        cn = dict(self.compute_node_dict,
                  hostname='bar',
                  hypervisor_hostname='nar',
                  mapped=3,
                  uuid=uuidutils.generate_uuid())
        db.compute_node_create(self.ctxt, cn)
        cns = db.compute_node_get_all_mapped_less_than(self.ctxt, 1)
        self.assertEqual(2, len(cns))

    def test_compute_node_get_all_by_pagination(self):
        service_dict = dict(host='host2', binary='nova-compute',
                            topic=compute_rpcapi.RPC_TOPIC,
                            report_count=1, disabled=False)
        service = db.service_create(self.ctxt, service_dict)
        compute_node_dict = dict(vcpus=2, memory_mb=1024, local_gb=2048,
                                 uuid=uuidsentinel.fake_compute_node,
                                 vcpus_used=0, memory_mb_used=0,
                                 local_gb_used=0, free_ram_mb=1024,
                                 free_disk_gb=2048, hypervisor_type="xen",
                                 hypervisor_version=1, cpu_info="",
                                 running_vms=0, current_workload=0,
                                 service_id=service['id'],
                                 host=service['host'],
                                 disk_available_least=100,
                                 hypervisor_hostname='abcde11',
                                 host_ip='127.0.0.1',
                                 supported_instances='',
                                 pci_stats='',
                                 metrics='',
                                 mapped=0,
                                 extra_resources='',
                                 cpu_allocation_ratio=16.0,
                                 ram_allocation_ratio=1.5,
                                 disk_allocation_ratio=1.0,
                                 stats='', numa_topology='')
        stats = dict(num_instances=2, num_proj_12345=1,
                     num_proj_23456=1, num_vm_building=2)
        compute_node_dict['stats'] = jsonutils.dumps(stats)
        db.compute_node_create(self.ctxt, compute_node_dict)

        nodes = db.compute_node_get_all_by_pagination(self.ctxt,
                                                      limit=1, marker=1)
        self.assertEqual(1, len(nodes))
        node = nodes[0]
        self._assertEqualObjects(compute_node_dict, node,
                    ignored_keys=self._ignored_keys +
                                 ['stats', 'service'])
        new_stats = jsonutils.loads(node['stats'])
        self.assertEqual(stats, new_stats)

        nodes = db.compute_node_get_all_by_pagination(self.ctxt)
        self.assertEqual(2, len(nodes))
        node = nodes[0]
        self._assertEqualObjects(self.compute_node_dict, node,
                    ignored_keys=self._ignored_keys +
                                 ['stats', 'service'])
        new_stats = jsonutils.loads(node['stats'])
        self.assertEqual(self.stats, new_stats)
        self.assertRaises(exception.MarkerNotFound,
                          db.compute_node_get_all_by_pagination,
                          self.ctxt, limit=1, marker=999)

    def test_compute_node_get_all_deleted_compute_node(self):
        # Create a service and compute node and ensure we can find its stats;
        # delete the service and compute node when done and loop again
        for x in range(2, 5):
            # Create a service
            service_data = self.service_dict.copy()
            service_data['host'] = 'host-%s' % x
            service = db.service_create(self.ctxt, service_data)

            # Create a compute node
            compute_node_data = self.compute_node_dict.copy()
            compute_node_data['uuid'] = uuidutils.generate_uuid()
            compute_node_data['service_id'] = service['id']
            compute_node_data['stats'] = jsonutils.dumps(self.stats.copy())
            compute_node_data['hypervisor_hostname'] = 'hypervisor-%s' % x
            node = db.compute_node_create(self.ctxt, compute_node_data)

            # Ensure the "new" compute node is found
            nodes = db.compute_node_get_all(self.ctxt)
            self.assertEqual(2, len(nodes))
            found = None
            for n in nodes:
                if n['id'] == node['id']:
                    found = n
                    break
            self.assertIsNotNone(found)
            # Now ensure the match has stats!
            self.assertNotEqual(jsonutils.loads(found['stats']), {})

            # Now delete the newly-created compute node to ensure the related
            # compute node stats are wiped in a cascaded fashion
            db.compute_node_delete(self.ctxt, node['id'])

            # Clean up the service
            db.service_destroy(self.ctxt, service['id'])

    def test_compute_node_get_all_mult_compute_nodes_one_service_entry(self):
        service_data = self.service_dict.copy()
        service_data['host'] = 'host2'
        service = db.service_create(self.ctxt, service_data)

        existing_node = dict(self.item.items())
        expected = [existing_node]

        for name in ['bm_node1', 'bm_node2']:
            compute_node_data = self.compute_node_dict.copy()
            compute_node_data['uuid'] = uuidutils.generate_uuid()
            compute_node_data['service_id'] = service['id']
            compute_node_data['stats'] = jsonutils.dumps(self.stats)
            compute_node_data['hypervisor_hostname'] = name
            node = db.compute_node_create(self.ctxt, compute_node_data)

            node = dict(node)

            expected.append(node)

        result = sorted(db.compute_node_get_all(self.ctxt),
                        key=lambda n: n['hypervisor_hostname'])

        self._assertEqualListsOfObjects(expected, result,
                    ignored_keys=['stats'])

    def test_compute_node_get_all_by_host_with_distinct_hosts(self):
        # Create another service with another node
        service2 = self.service_dict.copy()
        service2['host'] = 'host2'
        db.service_create(self.ctxt, service2)
        compute_node_another_host = self.compute_node_dict.copy()
        compute_node_another_host['uuid'] = uuidutils.generate_uuid()
        compute_node_another_host['stats'] = jsonutils.dumps(self.stats)
        compute_node_another_host['hypervisor_hostname'] = 'node_2'
        compute_node_another_host['host'] = 'host2'

        node = db.compute_node_create(self.ctxt, compute_node_another_host)

        result = db.compute_node_get_all_by_host(self.ctxt, 'host1')
        self._assertEqualListsOfObjects([self.item], result)
        result = db.compute_node_get_all_by_host(self.ctxt, 'host2')
        self._assertEqualListsOfObjects([node], result)

    def test_compute_node_get_all_by_host_with_same_host(self):
        # Create another node on top of the same service
        compute_node_same_host = self.compute_node_dict.copy()
        compute_node_same_host['uuid'] = uuidutils.generate_uuid()
        compute_node_same_host['stats'] = jsonutils.dumps(self.stats)
        compute_node_same_host['hypervisor_hostname'] = 'node_3'

        node = db.compute_node_create(self.ctxt, compute_node_same_host)

        expected = [self.item, node]
        result = sorted(db.compute_node_get_all_by_host(
                        self.ctxt, 'host1'),
                        key=lambda n: n['hypervisor_hostname'])

        ignored = ['stats']
        self._assertEqualListsOfObjects(expected, result,
                                        ignored_keys=ignored)

    def test_compute_node_get_all_by_host_not_found(self):
        self.assertRaises(exception.ComputeHostNotFound,
                          db.compute_node_get_all_by_host, self.ctxt, 'wrong')

    def test_compute_nodes_get_by_service_id_one_result(self):
        expected = [self.item]
        result = db.compute_nodes_get_by_service_id(
            self.ctxt, self.service['id'])

        ignored = ['stats']
        self._assertEqualListsOfObjects(expected, result,
                                        ignored_keys=ignored)

    def test_compute_nodes_get_by_service_id_multiple_results(self):
        # Create another node on top of the same service
        compute_node_same_host = self.compute_node_dict.copy()
        compute_node_same_host['uuid'] = uuidutils.generate_uuid()
        compute_node_same_host['stats'] = jsonutils.dumps(self.stats)
        compute_node_same_host['hypervisor_hostname'] = 'node_2'

        node = db.compute_node_create(self.ctxt, compute_node_same_host)

        expected = [self.item, node]
        result = sorted(db.compute_nodes_get_by_service_id(
                        self.ctxt, self.service['id']),
                        key=lambda n: n['hypervisor_hostname'])

        ignored = ['stats']
        self._assertEqualListsOfObjects(expected, result,
                                        ignored_keys=ignored)

    def test_compute_nodes_get_by_service_id_not_found(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.compute_nodes_get_by_service_id, self.ctxt,
                          'fake')

    def test_compute_node_get_by_host_and_nodename(self):
        # Create another node on top of the same service
        compute_node_same_host = self.compute_node_dict.copy()
        compute_node_same_host['uuid'] = uuidutils.generate_uuid()
        compute_node_same_host['stats'] = jsonutils.dumps(self.stats)
        compute_node_same_host['hypervisor_hostname'] = 'node_2'

        node = db.compute_node_create(self.ctxt, compute_node_same_host)

        expected = node
        result = db.compute_node_get_by_host_and_nodename(
            self.ctxt, 'host1', 'node_2')

        self._assertEqualObjects(expected, result,
                    ignored_keys=self._ignored_keys +
                                 ['stats', 'service'])

    def test_compute_node_get_by_host_and_nodename_not_found(self):
        self.assertRaises(exception.ComputeHostNotFound,
                          db.compute_node_get_by_host_and_nodename,
                          self.ctxt, 'host1', 'wrong')

    def test_compute_node_get_by_nodename(self):
        # Create another node on top of the same service
        compute_node_same_host = self.compute_node_dict.copy()
        compute_node_same_host['uuid'] = uuidutils.generate_uuid()
        compute_node_same_host['stats'] = jsonutils.dumps(self.stats)
        compute_node_same_host['hypervisor_hostname'] = 'node_2'

        node = db.compute_node_create(self.ctxt, compute_node_same_host)

        expected = node
        result = db.compute_node_get_by_nodename(
            self.ctxt, 'node_2')

        self._assertEqualObjects(expected, result,
                    ignored_keys=self._ignored_keys +
                                 ['stats', 'service'])

    def test_compute_node_get_by_nodename_not_found(self):
        self.assertRaises(exception.ComputeHostNotFound,
                          db.compute_node_get_by_nodename,
                          self.ctxt, 'wrong')

    def test_compute_node_get(self):
        compute_node_id = self.item['id']
        node = db.compute_node_get(self.ctxt, compute_node_id)
        self._assertEqualObjects(self.compute_node_dict, node,
                ignored_keys=self._ignored_keys +
                             ['stats', 'service'])
        new_stats = jsonutils.loads(node['stats'])
        self.assertEqual(self.stats, new_stats)

    def test_compute_node_update(self):
        compute_node_id = self.item['id']
        stats = jsonutils.loads(self.item['stats'])
        # change some values:
        stats['num_instances'] = 8
        stats['num_tribbles'] = 1
        values = {
            'vcpus': 4,
            'stats': jsonutils.dumps(stats),
        }
        item_updated = db.compute_node_update(self.ctxt, compute_node_id,
                                              values)
        self.assertEqual(4, item_updated['vcpus'])
        new_stats = jsonutils.loads(item_updated['stats'])
        self.assertEqual(stats, new_stats)

    def test_compute_node_delete(self):
        compute_node_id = self.item['id']
        db.compute_node_delete(self.ctxt, compute_node_id)
        nodes = db.compute_node_get_all(self.ctxt)
        self.assertEqual(len(nodes), 0)

    def test_compute_node_search_by_hypervisor(self):
        nodes_created = []
        new_service = copy.copy(self.service_dict)
        for i in range(3):
            new_service['binary'] += str(i)
            new_service['topic'] += str(i)
            service = db.service_create(self.ctxt, new_service)
            self.compute_node_dict['service_id'] = service['id']
            self.compute_node_dict['hypervisor_hostname'] = 'testhost' + str(i)
            self.compute_node_dict['stats'] = jsonutils.dumps(self.stats)
            self.compute_node_dict['uuid'] = uuidutils.generate_uuid()
            node = db.compute_node_create(self.ctxt, self.compute_node_dict)
            nodes_created.append(node)
        nodes = db.compute_node_search_by_hypervisor(self.ctxt, 'host')
        self.assertEqual(3, len(nodes))
        self._assertEqualListsOfObjects(nodes_created, nodes,
                        ignored_keys=self._ignored_keys + ['stats', 'service'])

    def test_compute_node_statistics(self):
        service_dict = dict(host='hostA', binary='nova-compute',
                            topic=compute_rpcapi.RPC_TOPIC,
                            report_count=1, disabled=False)
        service = db.service_create(self.ctxt, service_dict)
        # Define the various values for the new compute node
        new_vcpus = 4
        new_memory_mb = 4096
        new_local_gb = 2048
        new_vcpus_used = 1
        new_memory_mb_used = 1024
        new_local_gb_used = 100
        new_free_ram_mb = 3072
        new_free_disk_gb = 1948
        new_running_vms = 1
        new_current_workload = 0

        # Calculate the expected values by adding the values for the new
        # compute node to those for self.item
        itm = self.item
        exp_count = 2
        exp_vcpus = new_vcpus + itm['vcpus']
        exp_memory_mb = new_memory_mb + itm['memory_mb']
        exp_local_gb = new_local_gb + itm['local_gb']
        exp_vcpus_used = new_vcpus_used + itm['vcpus_used']
        exp_memory_mb_used = new_memory_mb_used + itm['memory_mb_used']
        exp_local_gb_used = new_local_gb_used + itm['local_gb_used']
        exp_free_ram_mb = new_free_ram_mb + itm['free_ram_mb']
        exp_free_disk_gb = new_free_disk_gb + itm['free_disk_gb']
        exp_running_vms = new_running_vms + itm['running_vms']
        exp_current_workload = new_current_workload + itm['current_workload']

        # Create the new compute node
        compute_node_dict = dict(vcpus=new_vcpus,
                                 memory_mb=new_memory_mb,
                                 local_gb=new_local_gb,
                                 uuid=uuidsentinel.fake_compute_node,
                                 vcpus_used=new_vcpus_used,
                                 memory_mb_used=new_memory_mb_used,
                                 local_gb_used=new_local_gb_used,
                                 free_ram_mb=new_free_ram_mb,
                                 free_disk_gb=new_free_disk_gb,
                                 hypervisor_type="xen",
                                 hypervisor_version=1,
                                 cpu_info="",
                                 running_vms=new_running_vms,
                                 current_workload=new_current_workload,
                                 service_id=service['id'],
                                 host=service['host'],
                                 disk_available_least=100,
                                 hypervisor_hostname='abracadabra',
                                 host_ip='127.0.0.2',
                                 supported_instances='',
                                 pci_stats='',
                                 metrics='',
                                 extra_resources='',
                                 cpu_allocation_ratio=16.0,
                                 ram_allocation_ratio=1.5,
                                 disk_allocation_ratio=1.0,
                                 stats='',
                                 numa_topology='')
        db.compute_node_create(self.ctxt, compute_node_dict)

        # Get the stats, and make sure the stats agree with the expected
        # amounts.
        stats = db.compute_node_statistics(self.ctxt)
        self.assertEqual(exp_count, stats['count'])
        self.assertEqual(exp_vcpus, stats['vcpus'])
        self.assertEqual(exp_memory_mb, stats['memory_mb'])
        self.assertEqual(exp_local_gb, stats['local_gb'])
        self.assertEqual(exp_vcpus_used, stats['vcpus_used'])
        self.assertEqual(exp_memory_mb_used, stats['memory_mb_used'])
        self.assertEqual(exp_local_gb_used, stats['local_gb_used'])
        self.assertEqual(exp_free_ram_mb, stats['free_ram_mb'])
        self.assertEqual(exp_free_disk_gb, stats['free_disk_gb'])
        self.assertEqual(exp_running_vms, stats['running_vms'])
        self.assertEqual(exp_current_workload, stats['current_workload'])

    def test_compute_node_statistics_disabled_service(self):
        serv = db.service_get_by_host_and_topic(
            self.ctxt, 'host1', compute_rpcapi.RPC_TOPIC)
        db.service_update(self.ctxt, serv['id'], {'disabled': True})
        stats = db.compute_node_statistics(self.ctxt)
        self.assertEqual(stats.pop('count'), 0)

    def test_compute_node_statistics_with_old_service_id(self):
        # NOTE(sbauza): This test is only for checking backwards compatibility
        # with old versions of compute_nodes not providing host column.
        # This test could be removed once we are sure that all compute nodes
        # are populating the host field thanks to the ResourceTracker

        service2 = self.service_dict.copy()
        service2['host'] = 'host2'
        db_service2 = db.service_create(self.ctxt, service2)
        compute_node_old_host = self.compute_node_dict.copy()
        compute_node_old_host['uuid'] = uuidutils.generate_uuid()
        compute_node_old_host['stats'] = jsonutils.dumps(self.stats)
        compute_node_old_host['hypervisor_hostname'] = 'node_2'
        compute_node_old_host['service_id'] = db_service2['id']
        compute_node_old_host.pop('host')

        db.compute_node_create(self.ctxt, compute_node_old_host)
        stats = db.compute_node_statistics(self.ctxt)
        self.assertEqual(2, stats.pop('count'))

    def test_compute_node_statistics_with_other_service(self):
        other_service = self.service_dict.copy()
        other_service['topic'] = 'fake-topic'
        other_service['binary'] = 'nova-api'
        db.service_create(self.ctxt, other_service)

        stats = db.compute_node_statistics(self.ctxt)
        data = {'count': 1,
                'vcpus_used': 0,
                'local_gb_used': 0,
                'memory_mb': 1024,
                'current_workload': 0,
                'vcpus': 2,
                'running_vms': 0,
                'free_disk_gb': 2048,
                'disk_available_least': 100,
                'local_gb': 2048,
                'free_ram_mb': 1024,
                'memory_mb_used': 0}
        for key, value in data.items():
            self.assertEqual(value, stats.pop(key))

    def test_compute_node_statistics_delete_and_recreate_service(self):
        # Test added for bug #1692397, this test tests that deleted
        # service record will not be selected when calculate compute
        # node statistics.

        # Let's first assert what we expect the setup to look like.
        self.assertEqual(1, len(db.service_get_all_by_binary(
            self.ctxt, 'nova-compute')))
        self.assertEqual(1, len(db.compute_node_get_all_by_host(
            self.ctxt, 'host1')))
        # Get the statistics for the original node/service before we delete
        # the service.
        original_stats = db.compute_node_statistics(self.ctxt)

        # At this point we have one compute_nodes record and one services
        # record pointing at the same host. Now we need to simulate the user
        # deleting the service record in the API, which will only delete very
        # old compute_nodes records where the service and compute node are
        # linked via the compute_nodes.service_id column, which is the case
        # in this test class; at some point we should decouple those to be more
        # modern.
        db.service_destroy(self.ctxt, self.service['id'])

        # Now we're going to simulate that the nova-compute service was
        # restarted, which will create a new services record with a unique
        # uuid but it will have the same host, binary and topic values as the
        # deleted service. The unique constraints don't fail in this case since
        # they include the deleted column and this service and the old service
        # have a different deleted value.
        service2_dict = self.service_dict.copy()
        service2_dict['uuid'] = uuidsentinel.service2_uuid
        db.service_create(self.ctxt, service2_dict)

        # Again, because of the way the setUp is done currently, the compute
        # node was linked to the original now-deleted service, so when we
        # deleted that service it also deleted the compute node record, so we
        # have to simulate the ResourceTracker in the nova-compute worker
        # re-creating the compute nodes record.
        new_compute_node = self.compute_node_dict.copy()
        del new_compute_node['service_id']  # make it a new style compute node
        new_compute_node['uuid'] = uuidsentinel.new_compute_uuid
        db.compute_node_create(self.ctxt, new_compute_node)

        # Now get the stats for all compute nodes (we just have one) and it
        # should just be for a single service, not double, as we should ignore
        # the (soft) deleted service.
        stats = db.compute_node_statistics(self.ctxt)
        self.assertDictEqual(original_stats, stats)

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

    def test_service_destroy_with_compute_node(self):
        db.service_destroy(self.ctxt, self.service['id'])
        self.assertRaises(exception.ComputeHostNotFound,
                          db.compute_node_get_model, self.ctxt,
                          self.item['id'])

    def test_service_destroy_with_old_compute_node(self):
        # NOTE(sbauza): This test is only for checking backwards compatibility
        # with old versions of compute_nodes not providing host column.
        # This test could be removed once we are sure that all compute nodes
        # are populating the host field thanks to the ResourceTracker
        compute_node_old_host_dict = self.compute_node_dict.copy()
        compute_node_old_host_dict['uuid'] = uuidutils.generate_uuid()
        compute_node_old_host_dict.pop('host')
        item_old = db.compute_node_create(self.ctxt,
                                          compute_node_old_host_dict)

        db.service_destroy(self.ctxt, self.service['id'])
        self.assertRaises(exception.ComputeHostNotFound,
                          db.compute_node_get_model, self.ctxt,
                          item_old['id'])

    @mock.patch("nova.db.sqlalchemy.api.compute_node_get_model")
    def test_dbapi_compute_node_get_model(self, mock_get_model):
        cid = self.item["id"]
        db.compute_node_get_model(self.ctxt, cid)
        mock_get_model.assert_called_once_with(self.ctxt, cid)

    @mock.patch("nova.db.sqlalchemy.api.model_query")
    def test_compute_node_get_model(self, mock_model_query):

        class FakeFiltered(object):
            def first(self):
                return mock.sentinel.first

        fake_filtered_cn = FakeFiltered()

        class FakeModelQuery(object):
            def filter_by(self, id):
                return fake_filtered_cn

        mock_model_query.return_value = FakeModelQuery()
        result = sqlalchemy_api.compute_node_get_model(self.ctxt,
                                                       self.item["id"])
        self.assertEqual(result, mock.sentinel.first)
        mock_model_query.assert_called_once_with(self.ctxt, models.ComputeNode)


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
        for i in range(len(cidr_samples)):
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
        return [{k: v + str(x) for k, v in base_values.items()}
                for x in range(1, 4)]

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
        self.console_pools = [db.console_pool_create(self.ctxt, val)
                         for val in pools_data]
        instance_uuid = uuidsentinel.uuid1
        db.instance_create(self.ctxt, {'uuid': instance_uuid})
        self.console_data = [{'instance_name': 'name' + str(x),
                              'instance_uuid': instance_uuid,
                              'password': 'pass' + str(x),
                              'port': 7878 + x,
                              'pool_id': self.console_pools[x]['id']}
                             for x in range(len(pools_data))]
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

    def test_console_get_all_by_instance_with_pool(self):
        instance_uuid = self.consoles[0]['instance_uuid']
        consoles_get = db.console_get_all_by_instance(self.ctxt, instance_uuid,
                                                      columns_to_join=['pool'])
        self._assertEqualListsOfObjects(self.consoles, consoles_get,
                                        ignored_keys=['pool'])
        self._assertEqualListsOfObjects([pool for pool in self.console_pools],
                                        [c['pool'] for c in consoles_get])

    def test_console_get_all_by_instance_empty(self):
        consoles_get = db.console_get_all_by_instance(self.ctxt,
                                                uuidsentinel.uuid2)
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
                          uuidsentinel.uuid2)

    def test_console_get_not_found(self):
        self.assertRaises(exception.ConsoleNotFound, db.console_get,
                          self.ctxt, 100500)

    def test_console_get_not_found_instance(self):
        self.assertRaises(exception.ConsoleNotFoundForInstance, db.console_get,
                          self.ctxt, self.consoles[0]['id'],
                          uuidsentinel.uuid2)


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
        self.assertIsNotNone(console_pool.get('id'))
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

    def test_dnsdomain_unregister(self):
        db.dnsdomain_register_for_zone(self.ctxt, self.domain, self.testzone)
        db.dnsdomain_unregister(self.ctxt, self.domain)
        domain = db.dnsdomain_get(self.ctxt, self.domain)
        self.assertIsNone(domain)

    def test_dnsdomain_get_all(self):
        d_list = ['test.domain.one', 'test.domain.two']
        db.dnsdomain_register_for_zone(self.ctxt, d_list[0], 'zone')
        db.dnsdomain_register_for_zone(self.ctxt, d_list[1], 'zone')
        db_list = db.dnsdomain_get_all(self.ctxt)
        db_domain_list = [d.domain for d in db_list]
        self.assertEqual(sorted(d_list), sorted(db_domain_list))


class BwUsageTestCase(test.TestCase, ModelsObjectComparatorMixin):

    _ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at', 'updated_at']

    def setUp(self):
        super(BwUsageTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.useFixture(test.TimeOverride())

    def test_bw_usage_get_by_uuids(self):
        now = timeutils.utcnow()
        start_period = now - datetime.timedelta(seconds=10)
        start_period_str = start_period.isoformat()
        uuid3_refreshed = now - datetime.timedelta(seconds=5)
        uuid3_refreshed_str = uuid3_refreshed.isoformat()

        expected_bw_usages = {
            'fake_uuid1': {'uuid': 'fake_uuid1',
                           'mac': 'fake_mac1',
                           'start_period': start_period,
                           'bw_in': 100,
                           'bw_out': 200,
                           'last_ctr_in': 12345,
                           'last_ctr_out': 67890,
                           'last_refreshed': now},
            'fake_uuid2': {'uuid': 'fake_uuid2',
                           'mac': 'fake_mac2',
                           'start_period': start_period,
                           'bw_in': 200,
                           'bw_out': 300,
                           'last_ctr_in': 22345,
                           'last_ctr_out': 77890,
                           'last_refreshed': now},
            'fake_uuid3': {'uuid': 'fake_uuid3',
                           'mac': 'fake_mac3',
                           'start_period': start_period,
                           'bw_in': 400,
                           'bw_out': 500,
                           'last_ctr_in': 32345,
                           'last_ctr_out': 87890,
                           'last_refreshed': uuid3_refreshed}
        }

        bw_usages = db.bw_usage_get_by_uuids(self.ctxt,
                ['fake_uuid1', 'fake_uuid2'], start_period_str)
        # No matches
        self.assertEqual(len(bw_usages), 0)

        # Add 3 entries
        db.bw_usage_update(self.ctxt, 'fake_uuid1',
                'fake_mac1', start_period_str,
                100, 200, 12345, 67890)
        db.bw_usage_update(self.ctxt, 'fake_uuid2',
                'fake_mac2', start_period_str,
                100, 200, 42, 42)
        # Test explicit refreshed time
        db.bw_usage_update(self.ctxt, 'fake_uuid3',
                'fake_mac3', start_period_str,
                400, 500, 32345, 87890,
                last_refreshed=uuid3_refreshed_str)
        # Update 2nd entry
        db.bw_usage_update(self.ctxt, 'fake_uuid2',
                'fake_mac2', start_period_str,
                200, 300, 22345, 77890)

        bw_usages = db.bw_usage_get_by_uuids(self.ctxt,
                ['fake_uuid1', 'fake_uuid2', 'fake_uuid3'], start_period_str)
        self.assertEqual(len(bw_usages), 3)
        for usage in bw_usages:
            self._assertEqualObjects(expected_bw_usages[usage['uuid']], usage,
                                     ignored_keys=self._ignored_keys)

    def _test_bw_usage_update(self, **expected_bw_usage):
        bw_usage = db.bw_usage_update(self.ctxt, **expected_bw_usage)
        self._assertEqualObjects(expected_bw_usage, bw_usage,
                                 ignored_keys=self._ignored_keys)

        uuid = expected_bw_usage['uuid']
        mac = expected_bw_usage['mac']
        start_period = expected_bw_usage['start_period']
        bw_usage = db.bw_usage_get(self.ctxt, uuid, start_period, mac)
        self._assertEqualObjects(expected_bw_usage, bw_usage,
                                 ignored_keys=self._ignored_keys)

    def _create_bw_usage(self, context, uuid, mac, start_period, bw_in, bw_out,
                         last_ctr_in, last_ctr_out, id, last_refreshed=None):
        with sqlalchemy_api.get_context_manager(context).writer.using(context):
            bwusage = models.BandwidthUsage()
            bwusage.start_period = start_period
            bwusage.uuid = uuid
            bwusage.mac = mac
            bwusage.last_refreshed = last_refreshed
            bwusage.bw_in = bw_in
            bwusage.bw_out = bw_out
            bwusage.last_ctr_in = last_ctr_in
            bwusage.last_ctr_out = last_ctr_out
            bwusage.id = id
            bwusage.save(context.session)

    def test_bw_usage_update_exactly_one_record(self):
        now = timeutils.utcnow()
        start_period = now - datetime.timedelta(seconds=10)
        uuid = 'fake_uuid'

        # create two equal bw_usages with IDs 1 and 2
        for id in range(1, 3):
            bw_usage = {'uuid': uuid,
                        'mac': 'fake_mac',
                        'start_period': start_period,
                        'bw_in': 100,
                        'bw_out': 200,
                        'last_ctr_in': 12345,
                        'last_ctr_out': 67890,
                        'last_refreshed': now,
                        'id': id}
            self._create_bw_usage(self.ctxt, **bw_usage)

        # check that we have two equal bw_usages
        self.assertEqual(
            2, len(db.bw_usage_get_by_uuids(self.ctxt, [uuid], start_period)))

        # update 'last_ctr_in' field in one bw_usage
        updated_bw_usage = {'uuid': uuid,
                            'mac': 'fake_mac',
                            'start_period': start_period,
                            'bw_in': 100,
                            'bw_out': 200,
                            'last_ctr_in': 54321,
                            'last_ctr_out': 67890,
                            'last_refreshed': now}
        result = db.bw_usage_update(self.ctxt, **updated_bw_usage)

        # check that only bw_usage with ID 1 was updated
        self.assertEqual(1, result['id'])
        self._assertEqualObjects(updated_bw_usage, result,
                                 ignored_keys=self._ignored_keys)

    def test_bw_usage_get(self):
        now = timeutils.utcnow()
        start_period = now - datetime.timedelta(seconds=10)
        start_period_str = start_period.isoformat()

        expected_bw_usage = {'uuid': 'fake_uuid1',
                             'mac': 'fake_mac1',
                             'start_period': start_period,
                             'bw_in': 100,
                             'bw_out': 200,
                             'last_ctr_in': 12345,
                             'last_ctr_out': 67890,
                             'last_refreshed': now}

        bw_usage = db.bw_usage_get(self.ctxt, 'fake_uuid1', start_period_str,
                                   'fake_mac1')
        self.assertIsNone(bw_usage)
        self._test_bw_usage_update(**expected_bw_usage)

    def test_bw_usage_update_new(self):
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

        self._test_bw_usage_update(**expected_bw_usage)

    def test_bw_usage_update_existing(self):
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

        self._test_bw_usage_update(**expected_bw_usage)

        expected_bw_usage['bw_in'] = 300
        expected_bw_usage['bw_out'] = 400
        expected_bw_usage['last_ctr_in'] = 23456
        expected_bw_usage['last_ctr_out'] = 78901

        self._test_bw_usage_update(**expected_bw_usage)


class Ec2TestCase(test.TestCase):

    def setUp(self):
        super(Ec2TestCase, self).setUp()
        self.ctxt = context.RequestContext('fake_user', 'fake_project')

    def test_ec2_ids_not_found_are_printable(self):
        def check_exc_format(method, value):
            try:
                method(self.ctxt, value)
            except exception.NotFound as exc:
                self.assertIn(six.text_type(value), six.text_type(exc))

        check_exc_format(db.get_instance_uuid_by_ec2_id, 123456)
        check_exc_format(db.ec2_snapshot_get_by_ec2_id, 123456)
        check_exc_format(db.ec2_snapshot_get_by_uuid, 'fake')

    def test_ec2_volume_create(self):
        vol = db.ec2_volume_create(self.ctxt, 'fake-uuid')
        self.assertIsNotNone(vol['id'])
        self.assertEqual(vol['uuid'], 'fake-uuid')

    def test_ec2_volume_get_by_id(self):
        vol = db.ec2_volume_create(self.ctxt, 'fake-uuid')
        vol2 = db.ec2_volume_get_by_id(self.ctxt, vol['id'])
        self.assertEqual(vol2['uuid'], vol['uuid'])

    def test_ec2_volume_get_by_uuid(self):
        vol = db.ec2_volume_create(self.ctxt, 'fake-uuid')
        vol2 = db.ec2_volume_get_by_uuid(self.ctxt, vol['uuid'])
        self.assertEqual(vol2['id'], vol['id'])

    def test_ec2_snapshot_create(self):
        snap = db.ec2_snapshot_create(self.ctxt, 'fake-uuid')
        self.assertIsNotNone(snap['id'])
        self.assertEqual(snap['uuid'], 'fake-uuid')

    def test_ec2_snapshot_get_by_ec2_id(self):
        snap = db.ec2_snapshot_create(self.ctxt, 'fake-uuid')
        snap2 = db.ec2_snapshot_get_by_ec2_id(self.ctxt, snap['id'])
        self.assertEqual(snap2['uuid'], 'fake-uuid')

    def test_ec2_snapshot_get_by_uuid(self):
        snap = db.ec2_snapshot_create(self.ctxt, 'fake-uuid')
        snap2 = db.ec2_snapshot_get_by_uuid(self.ctxt, 'fake-uuid')
        self.assertEqual(snap['id'], snap2['id'])

    def test_ec2_snapshot_get_by_ec2_id_not_found(self):
        self.assertRaises(exception.SnapshotNotFound,
                          db.ec2_snapshot_get_by_ec2_id,
                          self.ctxt, 123456)

    def test_ec2_snapshot_get_by_uuid_not_found(self):
        self.assertRaises(exception.SnapshotNotFound,
                          db.ec2_snapshot_get_by_uuid,
                          self.ctxt, 'fake-uuid')

    def test_ec2_instance_create(self):
        inst = db.ec2_instance_create(self.ctxt, 'fake-uuid')
        self.assertIsNotNone(inst['id'])
        self.assertEqual(inst['uuid'], 'fake-uuid')

    def test_ec2_instance_get_by_uuid(self):
        inst = db.ec2_instance_create(self.ctxt, 'fake-uuid')
        inst2 = db.ec2_instance_get_by_uuid(self.ctxt, 'fake-uuid')
        self.assertEqual(inst['id'], inst2['id'])

    def test_ec2_instance_get_by_id(self):
        inst = db.ec2_instance_create(self.ctxt, 'fake-uuid')
        inst2 = db.ec2_instance_get_by_id(self.ctxt, inst['id'])
        self.assertEqual(inst['id'], inst2['id'])

    def test_ec2_instance_get_by_uuid_not_found(self):
        self.assertRaises(exception.InstanceNotFound,
                          db.ec2_instance_get_by_uuid,
                          self.ctxt, 'uuid-not-present')

    def test_ec2_instance_get_by_id_not_found(self):
        self.assertRaises(exception.InstanceNotFound,
                          db.ec2_instance_get_by_uuid,
                          self.ctxt, 12345)

    def test_get_instance_uuid_by_ec2_id(self):
        inst = db.ec2_instance_create(self.ctxt, 'fake-uuid')
        inst_uuid = db.get_instance_uuid_by_ec2_id(self.ctxt, inst['id'])
        self.assertEqual(inst_uuid, 'fake-uuid')

    def test_get_instance_uuid_by_ec2_id_not_found(self):
        self.assertRaises(exception.InstanceNotFound,
                          db.get_instance_uuid_by_ec2_id,
                          self.ctxt, 100500)


class ArchiveTestCase(test.TestCase, ModelsObjectComparatorMixin):

    def setUp(self):
        super(ArchiveTestCase, self).setUp()
        self.engine = get_engine()
        self.metadata = MetaData(self.engine)
        self.conn = self.engine.connect()
        self.instance_id_mappings = models.InstanceIdMapping.__table__
        self.shadow_instance_id_mappings = sqlalchemyutils.get_table(
            self.engine, "shadow_instance_id_mappings")
        self.dns_domains = models.DNSDomain.__table__
        self.shadow_dns_domains = sqlalchemyutils.get_table(
            self.engine, "shadow_dns_domains")
        self.consoles = models.Console.__table__
        self.shadow_consoles = sqlalchemyutils.get_table(
            self.engine, "shadow_consoles")
        self.console_pools = models.ConsolePool.__table__
        self.shadow_console_pools = sqlalchemyutils.get_table(
            self.engine, "shadow_console_pools")
        self.instances = models.Instance.__table__
        self.shadow_instances = sqlalchemyutils.get_table(
            self.engine, "shadow_instances")
        self.instance_actions = models.InstanceAction.__table__
        self.shadow_instance_actions = sqlalchemyutils.get_table(
            self.engine, "shadow_instance_actions")
        self.instance_actions_events = models.InstanceActionEvent.__table__
        self.shadow_instance_actions_events = sqlalchemyutils.get_table(
            self.engine, "shadow_instance_actions_events")
        self.migrations = models.Migration.__table__
        self.shadow_migrations = sqlalchemyutils.get_table(
            self.engine, "shadow_migrations")

        self.uuidstrs = []
        for _ in range(6):
            self.uuidstrs.append(uuidutils.generate_uuid(dashed=False))

    def _assert_shadow_tables_empty_except(self, *exceptions):
        """Ensure shadow tables are empty

        This method ensures that all the shadow tables in the schema,
        except for specificially named exceptions, are empty. This
        makes sure that archiving isn't moving unexpected content.
        """
        metadata = MetaData(bind=self.engine)
        metadata.reflect()
        for table in metadata.tables:
            if table.startswith("shadow_") and table not in exceptions:
                rows = self.conn.execute("select * from %s" % table).fetchall()
                self.assertEqual(rows, [], "Table %s not empty" % table)

    def test_shadow_tables(self):
        metadata = MetaData(bind=self.engine)
        metadata.reflect()
        for table_name in metadata.tables:
            # NOTE(rpodolyaka): migration 209 introduced a few new tables,
            #                   which don't have shadow tables and it's
            #                   completely OK, so we should skip them here
            if table_name.startswith("dump_"):
                continue

            # NOTE(snikitin): migration 266 introduced a new table 'tags',
            #                 which have no shadow table and it's
            #                 completely OK, so we should skip it here
            # NOTE(cdent): migration 314 introduced three new
            # ('resource_providers', 'allocations' and 'inventories')
            # with no shadow table and it's OK, so skip.
            # 318 adds one more: 'resource_provider_aggregates'.
            # NOTE(PaulMurray): migration 333 adds 'console_auth_tokens'
            if table_name in ['tags', 'resource_providers', 'allocations',
                              'inventories', 'resource_provider_aggregates',
                              'console_auth_tokens']:
                continue

            if table_name.startswith("shadow_"):
                self.assertIn(table_name[7:], metadata.tables)
                continue
            self.assertTrue(db_utils.check_shadow_table(self.engine,
                                                        table_name))
        self._assert_shadow_tables_empty_except()

    def test_archive_deleted_rows(self):
        # Add 6 rows to table
        for uuidstr in self.uuidstrs:
            ins_stmt = self.instance_id_mappings.insert().values(uuid=uuidstr)
            self.conn.execute(ins_stmt)
        # Set 4 to deleted
        update_statement = self.instance_id_mappings.update().\
                where(self.instance_id_mappings.c.uuid.in_(self.uuidstrs[:4]))\
                .values(deleted=1, deleted_at=timeutils.utcnow())
        self.conn.execute(update_statement)
        qiim = sql.select([self.instance_id_mappings]).where(self.
                                instance_id_mappings.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qiim).fetchall()
        # Verify we have 6 in main
        self.assertEqual(len(rows), 6)
        qsiim = sql.select([self.shadow_instance_id_mappings]).\
                where(self.shadow_instance_id_mappings.c.uuid.in_(
                                                                self.uuidstrs))
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we have 0 in shadow
        self.assertEqual(len(rows), 0)
        # Archive 2 rows
        results = db.archive_deleted_rows(max_rows=2)
        expected = dict(instance_id_mappings=2)
        self._assertEqualObjects(expected, results[0])
        rows = self.conn.execute(qiim).fetchall()
        # Verify we have 4 left in main
        self.assertEqual(len(rows), 4)
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we have 2 in shadow
        self.assertEqual(len(rows), 2)
        # Archive 2 more rows
        results = db.archive_deleted_rows(max_rows=2)
        expected = dict(instance_id_mappings=2)
        self._assertEqualObjects(expected, results[0])
        rows = self.conn.execute(qiim).fetchall()
        # Verify we have 2 left in main
        self.assertEqual(len(rows), 2)
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we have 4 in shadow
        self.assertEqual(len(rows), 4)
        # Try to archive more, but there are no deleted rows left.
        results = db.archive_deleted_rows(max_rows=2)
        expected = dict()
        self._assertEqualObjects(expected, results[0])
        rows = self.conn.execute(qiim).fetchall()
        # Verify we still have 2 left in main
        self.assertEqual(len(rows), 2)
        rows = self.conn.execute(qsiim).fetchall()
        # Verify we still have 4 in shadow
        self.assertEqual(len(rows), 4)

        # Ensure only deleted rows were deleted
        self._assert_shadow_tables_empty_except(
            'shadow_instance_id_mappings')

    def test_archive_deleted_rows_before(self):
        # Add 6 rows to table
        for uuidstr in self.uuidstrs:
            ins_stmt = self.instances.insert().values(uuid=uuidstr)
            self.conn.execute(ins_stmt)
            ins_stmt = self.instance_actions.insert().\
                    values(instance_uuid=uuidstr)
            result = self.conn.execute(ins_stmt)
            instance_action_uuid = result.inserted_primary_key[0]
            ins_stmt = self.instance_actions_events.insert().\
                    values(action_id=instance_action_uuid)
            self.conn.execute(ins_stmt)

        # Set 1 to deleted before 2017-01-01
        deleted_at = timeutils.parse_strtime('2017-01-01T00:00:00.0')
        update_statement = self.instances.update().\
                where(self.instances.c.uuid.in_(self.uuidstrs[0:1]))\
                .values(deleted=1, deleted_at=deleted_at)
        self.conn.execute(update_statement)

        # Set 1 to deleted before 2017-01-02
        deleted_at = timeutils.parse_strtime('2017-01-02T00:00:00.0')
        update_statement = self.instances.update().\
                where(self.instances.c.uuid.in_(self.uuidstrs[1:2]))\
                .values(deleted=1, deleted_at=deleted_at)
        self.conn.execute(update_statement)

        # Set 2 to deleted now
        update_statement = self.instances.update().\
                where(self.instances.c.uuid.in_(self.uuidstrs[2:4]))\
                .values(deleted=1, deleted_at=timeutils.utcnow())
        self.conn.execute(update_statement)
        qiim = sql.select([self.instances]).where(self.
                                instances.c.uuid.in_(self.uuidstrs))
        qsiim = sql.select([self.shadow_instances]).\
                where(self.shadow_instances.c.uuid.in_(self.uuidstrs))

        # Verify we have 6 in main
        rows = self.conn.execute(qiim).fetchall()
        self.assertEqual(len(rows), 6)
        # Make sure 'before' comparison is for < not <=, nothing deleted
        before_date = dateutil_parser.parse('2017-01-01', fuzzy=True)
        _, uuids, _ = db.archive_deleted_rows(max_rows=1, before=before_date)
        self.assertEqual([], uuids)

        # Archive rows deleted before 2017-01-02
        before_date = dateutil_parser.parse('2017-01-02', fuzzy=True)
        results = db.archive_deleted_rows(max_rows=100, before=before_date)
        expected = dict(instances=1,
                        instance_actions=1,
                        instance_actions_events=1)
        self._assertEqualObjects(expected, results[0])

        # Archive 1 row deleted before 2017-01-03. instance_action_events
        # should be the table with row deleted due to FK contraints
        before_date = dateutil_parser.parse('2017-01-03', fuzzy=True)
        results = db.archive_deleted_rows(max_rows=1, before=before_date)
        expected = dict(instance_actions_events=1)
        self._assertEqualObjects(expected, results[0])
        # Archive all other rows deleted before 2017-01-03. This should
        # delete row in instance_actions, then row in instances due to FK
        # constraints
        results = db.archive_deleted_rows(max_rows=100, before=before_date)
        expected = dict(instances=1, instance_actions=1)
        self._assertEqualObjects(expected, results[0])

        # Verify we have 4 left in main
        rows = self.conn.execute(qiim).fetchall()
        self.assertEqual(len(rows), 4)
        # Verify we have 2 in shadow
        rows = self.conn.execute(qsiim).fetchall()
        self.assertEqual(len(rows), 2)

        # Archive everything else, make sure default operation without
        # before argument didn't break
        results = db.archive_deleted_rows(max_rows=1000)
        # Verify we have 2 left in main
        rows = self.conn.execute(qiim).fetchall()
        self.assertEqual(len(rows), 2)
        # Verify we have 4 in shadow
        rows = self.conn.execute(qsiim).fetchall()
        self.assertEqual(len(rows), 4)

    def test_archive_deleted_rows_for_every_uuid_table(self):
        tablenames = []
        for model_class in six.itervalues(models.__dict__):
            if hasattr(model_class, "__tablename__"):
                tablenames.append(model_class.__tablename__)
        tablenames.sort()
        for tablename in tablenames:
            self._test_archive_deleted_rows_for_one_uuid_table(tablename)

    def _test_archive_deleted_rows_for_one_uuid_table(self, tablename):
        """:returns: 0 on success, 1 if no uuid column, 2 if insert failed."""
        # NOTE(cdent): migration 314 adds the resource_providers
        # table with a uuid column that does not archive, so skip.
        skip_tables = ['resource_providers']
        if tablename in skip_tables:
            return 1
        main_table = sqlalchemyutils.get_table(self.engine, tablename)
        if not hasattr(main_table.c, "uuid"):
            # Not a uuid table, so skip it.
            return 1
        shadow_table = sqlalchemyutils.get_table(
            self.engine, "shadow_" + tablename)
        # Add 6 rows to table
        for uuidstr in self.uuidstrs:
            ins_stmt = main_table.insert().values(uuid=uuidstr)
            try:
                self.conn.execute(ins_stmt)
            except (db_exc.DBError, OperationalError):
                # This table has constraints that require a table-specific
                # insert, so skip it.
                return 2
        # Set 4 to deleted
        update_statement = main_table.update().\
                where(main_table.c.uuid.in_(self.uuidstrs[:4]))\
                .values(deleted=1, deleted_at=timeutils.utcnow())
        self.conn.execute(update_statement)
        qmt = sql.select([main_table]).where(main_table.c.uuid.in_(
                                             self.uuidstrs))
        rows = self.conn.execute(qmt).fetchall()
        # Verify we have 6 in main
        self.assertEqual(len(rows), 6)
        qst = sql.select([shadow_table]).\
                where(shadow_table.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qst).fetchall()
        # Verify we have 0 in shadow
        self.assertEqual(len(rows), 0)
        # Archive 2 rows
        sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                       tablename,
                                                       max_rows=2,
                                                       before=None)
        # Verify we have 4 left in main
        rows = self.conn.execute(qmt).fetchall()
        self.assertEqual(len(rows), 4)
        # Verify we have 2 in shadow
        rows = self.conn.execute(qst).fetchall()
        self.assertEqual(len(rows), 2)
        # Archive 2 more rows
        sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                       tablename,
                                                       max_rows=2,
                                                       before=None)
        # Verify we have 2 left in main
        rows = self.conn.execute(qmt).fetchall()
        self.assertEqual(len(rows), 2)
        # Verify we have 4 in shadow
        rows = self.conn.execute(qst).fetchall()
        self.assertEqual(len(rows), 4)
        # Try to archive more, but there are no deleted rows left.
        sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                       tablename,
                                                       max_rows=2,
                                                       before=None)
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
                           values(deleted=True, deleted_at=timeutils.utcnow())
        self.conn.execute(update_statement)
        qdd = sql.select([self.dns_domains], self.dns_domains.c.domain ==
                                            uuidstr0)
        rows = self.conn.execute(qdd).fetchall()
        self.assertEqual(len(rows), 1)
        qsdd = sql.select([self.shadow_dns_domains],
                        self.shadow_dns_domains.c.domain == uuidstr0)
        rows = self.conn.execute(qsdd).fetchall()
        self.assertEqual(len(rows), 0)
        db.archive_deleted_rows(max_rows=1)
        rows = self.conn.execute(qdd).fetchall()
        self.assertEqual(len(rows), 0)
        rows = self.conn.execute(qsdd).fetchall()
        self.assertEqual(len(rows), 1)
        self._assert_shadow_tables_empty_except(
            'shadow_dns_domains',
        )

    def test_archive_deleted_rows_shadow_insertions_equals_deletions(self):
        # Add 2 rows to table
        for uuidstr in self.uuidstrs[:2]:
            ins_stmt = self.instance_id_mappings.insert().values(uuid=uuidstr)
            self.conn.execute(ins_stmt)
        # Set both to deleted
        update_statement = self.instance_id_mappings.update().\
                where(self.instance_id_mappings.c.uuid.in_(self.uuidstrs[:2]))\
                .values(deleted=1)
        self.conn.execute(update_statement)
        qiim = sql.select([self.instance_id_mappings]).where(self.
                            instance_id_mappings.c.uuid.in_(self.uuidstrs[:2]))
        rows = self.conn.execute(qiim).fetchall()
        # Verify we have 2 in main
        self.assertEqual(len(rows), 2)

        qsiim = sql.select([self.shadow_instance_id_mappings]).\
                where(self.shadow_instance_id_mappings.c.uuid.in_(
                                                            self.uuidstrs[:2]))
        shadow_rows = self.conn.execute(qsiim).fetchall()
        # Verify we have 0 in shadow
        self.assertEqual(len(shadow_rows), 0)

        # Archive the rows
        db.archive_deleted_rows(max_rows=2)

        main_rows = self.conn.execute(qiim).fetchall()
        shadow_rows = self.conn.execute(qsiim).fetchall()
        # Verify the insertions into shadow is same as deletions from main
        self.assertEqual(len(shadow_rows), len(rows) - len(main_rows))

    def _check_sqlite_version_less_than_3_7(self):
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

    def test_archive_deleted_rows_fk_constraint(self):
        # consoles.pool_id depends on console_pools.id
        self._check_sqlite_version_less_than_3_7()
        ins_stmt = self.console_pools.insert().values(deleted=1,
                                                deleted_at=timeutils.utcnow())
        result = self.conn.execute(ins_stmt)
        id1 = result.inserted_primary_key[0]
        ins_stmt = self.consoles.insert().values(deleted=1,
                                                deleted_at=timeutils.utcnow(),
                                                pool_id=id1)
        result = self.conn.execute(ins_stmt)
        result.inserted_primary_key[0]
        # The first try to archive console_pools should fail, due to FK.
        num = sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                             "console_pools",
                                                             max_rows=None,
                                                             before=None)
        self.assertEqual(num[0], 0)
        # Then archiving consoles should work.
        num = sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                             "consoles",
                                                             max_rows=None,
                                                             before=None)
        self.assertEqual(num[0], 1)
        # Then archiving console_pools should work.
        num = sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                             "console_pools",
                                                             max_rows=None,
                                                             before=None)
        self.assertEqual(num[0], 1)
        self._assert_shadow_tables_empty_except(
            'shadow_console_pools',
            'shadow_consoles'
        )

    def test_archive_deleted_rows_for_migrations(self):
        # migrations.instance_uuid depends on instances.uuid
        self._check_sqlite_version_less_than_3_7()
        instance_uuid = uuidsentinel.instance
        ins_stmt = self.instances.insert().values(
                        uuid=instance_uuid,
                        deleted=1,
                        deleted_at=timeutils.utcnow())
        self.conn.execute(ins_stmt)
        ins_stmt = self.migrations.insert().values(instance_uuid=instance_uuid,
                                                   deleted=0)
        self.conn.execute(ins_stmt)
        # The first try to archive instances should fail, due to FK.
        num = sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                             "instances",
                                                             max_rows=None,
                                                             before=None)
        self.assertEqual(0, num[0])
        # Then archiving migrations should work.
        num = sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                             "migrations",
                                                             max_rows=None,
                                                             before=None)
        self.assertEqual(1, num[0])
        # Then archiving instances should work.
        num = sqlalchemy_api._archive_deleted_rows_for_table(self.metadata,
                                                             "instances",
                                                             max_rows=None,
                                                             before=None)
        self.assertEqual(1, num[0])
        self._assert_shadow_tables_empty_except(
            'shadow_instances',
            'shadow_migrations'
        )

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
                .values(deleted=1, deleted_at=timeutils.utcnow())
        self.conn.execute(update_statement)
        update_statement2 = self.instances.update().\
                where(self.instances.c.uuid.in_(self.uuidstrs[:4]))\
                .values(deleted=1, deleted_at=timeutils.utcnow())
        self.conn.execute(update_statement2)
        # Verify we have 6 in each main table
        qiim = sql.select([self.instance_id_mappings]).where(
                         self.instance_id_mappings.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qiim).fetchall()
        self.assertEqual(len(rows), 6)
        qi = sql.select([self.instances]).where(self.instances.c.uuid.in_(
                                             self.uuidstrs))
        rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(rows), 6)
        # Verify we have 0 in each shadow table
        qsiim = sql.select([self.shadow_instance_id_mappings]).\
                where(self.shadow_instance_id_mappings.c.uuid.in_(
                                                            self.uuidstrs))
        rows = self.conn.execute(qsiim).fetchall()
        self.assertEqual(len(rows), 0)
        qsi = sql.select([self.shadow_instances]).\
                where(self.shadow_instances.c.uuid.in_(self.uuidstrs))
        rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(rows), 0)
        # Archive 7 rows, which should be 4 in one table and 3 in the other.
        db.archive_deleted_rows(max_rows=7)
        # Verify we have 5 left in the two main tables combined
        iim_rows = self.conn.execute(qiim).fetchall()
        i_rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(iim_rows) + len(i_rows), 5)
        # Verify we have 7 in the two shadow tables combined.
        siim_rows = self.conn.execute(qsiim).fetchall()
        si_rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(siim_rows) + len(si_rows), 7)
        # Archive the remaining deleted rows.
        db.archive_deleted_rows(max_rows=1)
        # Verify we have 4 total left in both main tables.
        iim_rows = self.conn.execute(qiim).fetchall()
        i_rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(iim_rows) + len(i_rows), 4)
        # Verify we have 8 in shadow
        siim_rows = self.conn.execute(qsiim).fetchall()
        si_rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(siim_rows) + len(si_rows), 8)
        # Try to archive more, but there are no deleted rows left.
        db.archive_deleted_rows(max_rows=500)
        # Verify we have 4 total left in both main tables.
        iim_rows = self.conn.execute(qiim).fetchall()
        i_rows = self.conn.execute(qi).fetchall()
        self.assertEqual(len(iim_rows) + len(i_rows), 4)
        # Verify we have 8 in shadow
        siim_rows = self.conn.execute(qsiim).fetchall()
        si_rows = self.conn.execute(qsi).fetchall()
        self.assertEqual(len(siim_rows) + len(si_rows), 8)
        self._assert_shadow_tables_empty_except(
            'shadow_instances',
            'shadow_instance_id_mappings'
        )


class PciDeviceDBApiTestCase(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(PciDeviceDBApiTestCase, self).setUp()
        self.user_id = 'fake_user'
        self.project_id = 'fake_project'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.admin_context = context.get_admin_context()
        self.ignored_keys = ['id', 'deleted', 'deleted_at', 'updated_at',
                             'created_at']
        self._compute_node = None

    def _get_fake_pci_devs(self):
        return {'id': 3353,
                'uuid': uuidsentinel.pci_device1,
                'compute_node_id': 1,
                'address': '0000:0f:08.7',
                'vendor_id': '8086',
                'product_id': '1520',
                'numa_node': 1,
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'dev_id': 'pci_0000:0f:08.7',
                'extra_info': '{}',
                'label': 'label_8086_1520',
                'status': fields.PciDeviceStatus.AVAILABLE,
                'instance_uuid': '00000000-0000-0000-0000-000000000010',
                'request_id': None,
                'parent_addr': '0000:0f:00.1',
                }, {'id': 3356,
                'uuid': uuidsentinel.pci_device3356,
                'compute_node_id': 1,
                'address': '0000:0f:03.7',
                'parent_addr': '0000:0f:03.0',
                'vendor_id': '8083',
                'product_id': '1523',
                'numa_node': 0,
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'dev_id': 'pci_0000:0f:08.7',
                'extra_info': '{}',
                'label': 'label_8086_1520',
                'status': fields.PciDeviceStatus.AVAILABLE,
                'instance_uuid': '00000000-0000-0000-0000-000000000010',
                'request_id': None,
                }

    @property
    def compute_node(self):
        if self._compute_node is None:
            self._compute_node = db.compute_node_create(self.admin_context, {
                'vcpus': 0,
                'memory_mb': 0,
                'local_gb': 0,
                'vcpus_used': 0,
                'memory_mb_used': 0,
                'local_gb_used': 0,
                'hypervisor_type': 'fake',
                'hypervisor_version': 0,
                'cpu_info': 'fake',
                })
        return self._compute_node

    def _create_fake_pci_devs(self):
        v1, v2 = self._get_fake_pci_devs()
        for i in v1, v2:
            i['compute_node_id'] = self.compute_node['id']

        db.pci_device_update(self.admin_context, v1['compute_node_id'],
                             v1['address'], v1)
        db.pci_device_update(self.admin_context, v2['compute_node_id'],
                             v2['address'], v2)

        return (v1, v2)

    def test_pci_device_get_by_addr(self):
        v1, v2 = self._create_fake_pci_devs()
        result = db.pci_device_get_by_addr(self.admin_context, 1,
                                           '0000:0f:08.7')
        self._assertEqualObjects(v1, result, self.ignored_keys)

    def test_pci_device_get_by_addr_not_found(self):
        self._create_fake_pci_devs()
        self.assertRaises(exception.PciDeviceNotFound,
                          db.pci_device_get_by_addr, self.admin_context,
                          1, '0000:0f:08:09')

    def test_pci_device_get_all_by_parent_addr(self):
        v1, v2 = self._create_fake_pci_devs()
        results = db.pci_device_get_all_by_parent_addr(self.admin_context, 1,
                                                      '0000:0f:00.1')
        self._assertEqualListsOfObjects([v1], results, self.ignored_keys)

    def test_pci_device_get_all_by_parent_addr_empty(self):
        v1, v2 = self._create_fake_pci_devs()
        results = db.pci_device_get_all_by_parent_addr(self.admin_context, 1,
                                                      '0000:0f:01.6')
        self.assertEqual(len(results), 0)

    def test_pci_device_get_by_id(self):
        v1, v2 = self._create_fake_pci_devs()
        result = db.pci_device_get_by_id(self.admin_context, 3353)
        self._assertEqualObjects(v1, result, self.ignored_keys)

    def test_pci_device_get_by_id_not_found(self):
        self._create_fake_pci_devs()
        self.assertRaises(exception.PciDeviceNotFoundById,
                          db.pci_device_get_by_id,
                          self.admin_context, 3354)

    def test_pci_device_get_all_by_node(self):
        v1, v2 = self._create_fake_pci_devs()
        results = db.pci_device_get_all_by_node(self.admin_context, 1)
        self._assertEqualListsOfObjects(results, [v1, v2], self.ignored_keys)

    def test_pci_device_get_all_by_node_empty(self):
        v1, v2 = self._get_fake_pci_devs()
        results = db.pci_device_get_all_by_node(self.admin_context, 9)
        self.assertEqual(len(results), 0)

    def test_pci_device_get_by_instance_uuid(self):
        v1, v2 = self._create_fake_pci_devs()
        v1['status'] = fields.PciDeviceStatus.ALLOCATED
        v2['status'] = fields.PciDeviceStatus.ALLOCATED
        db.pci_device_update(self.admin_context, v1['compute_node_id'],
                             v1['address'], v1)
        db.pci_device_update(self.admin_context, v2['compute_node_id'],
                             v2['address'], v2)
        results = db.pci_device_get_all_by_instance_uuid(
            self.context,
            '00000000-0000-0000-0000-000000000010')
        self._assertEqualListsOfObjects(results, [v1, v2], self.ignored_keys)

    def test_pci_device_get_by_instance_uuid_check_status(self):
        v1, v2 = self._create_fake_pci_devs()
        v1['status'] = fields.PciDeviceStatus.ALLOCATED
        v2['status'] = fields.PciDeviceStatus.CLAIMED
        db.pci_device_update(self.admin_context, v1['compute_node_id'],
                             v1['address'], v1)
        db.pci_device_update(self.admin_context, v2['compute_node_id'],
                             v2['address'], v2)
        results = db.pci_device_get_all_by_instance_uuid(
            self.context,
            '00000000-0000-0000-0000-000000000010')
        self._assertEqualListsOfObjects(results, [v1], self.ignored_keys)

    def test_pci_device_update(self):
        v1, v2 = self._create_fake_pci_devs()
        v1['status'] = fields.PciDeviceStatus.ALLOCATED
        db.pci_device_update(self.admin_context, v1['compute_node_id'],
                             v1['address'], v1)
        result = db.pci_device_get_by_addr(
            self.admin_context, 1, '0000:0f:08.7')
        self._assertEqualObjects(v1, result, self.ignored_keys)

        v1['status'] = fields.PciDeviceStatus.CLAIMED
        db.pci_device_update(self.admin_context, v1['compute_node_id'],
                             v1['address'], v1)
        result = db.pci_device_get_by_addr(
            self.admin_context, 1, '0000:0f:08.7')
        self._assertEqualObjects(v1, result, self.ignored_keys)

    def test_pci_device_destroy(self):
        v1, v2 = self._create_fake_pci_devs()
        results = db.pci_device_get_all_by_node(self.admin_context,
                                                self.compute_node['id'])
        self._assertEqualListsOfObjects(results, [v1, v2], self.ignored_keys)
        db.pci_device_destroy(self.admin_context, v1['compute_node_id'],
                              v1['address'])
        results = db.pci_device_get_all_by_node(self.admin_context,
                                                self.compute_node['id'])
        self._assertEqualListsOfObjects(results, [v2], self.ignored_keys)

    def test_pci_device_destroy_exception(self):
        v1, v2 = self._get_fake_pci_devs()
        self.assertRaises(exception.PciDeviceNotFound,
                          db.pci_device_destroy,
                          self.admin_context,
                          v1['compute_node_id'],
                          v1['address'])

    def _create_fake_pci_devs_old_format(self):
        v1, v2 = self._get_fake_pci_devs()

        for v in (v1, v2):
            v['parent_addr'] = None
            v['extra_info'] = jsonutils.dumps(
                {'phys_function': 'fake-phys-func'})

            db.pci_device_update(self.admin_context, v['compute_node_id'],
                                 v['address'], v)


@mock.patch('time.sleep', new=lambda x: None)
class RetryOnDeadlockTestCase(test.TestCase):
    def test_without_deadlock(self):
        @oslo_db_api.wrap_db_retry(max_retries=5,
                                   retry_on_deadlock=True)
        def call_api(*args, **kwargs):
            return True
        self.assertTrue(call_api())

    def test_raise_deadlock(self):
        self.attempts = 2

        @oslo_db_api.wrap_db_retry(max_retries=5,
                                   retry_on_deadlock=True)
        def call_api(*args, **kwargs):
            while self.attempts:
                self.attempts = self.attempts - 1
                raise db_exc.DBDeadlock("fake exception")
            return True
        self.assertTrue(call_api())


class TestSqlalchemyTypesRepr(
        test_fixtures.OpportunisticDBTestMixin, test.NoDBTestCase):

    def setUp(self):
        # NOTE(sdague): the oslo_db base test case completely
        # invalidates our logging setup, we actually have to do that
        # before it is called to keep this from vomitting all over our
        # test output.
        self.useFixture(nova_fixtures.StandardLogging())

        super(TestSqlalchemyTypesRepr, self).setUp()
        self.engine = enginefacade.writer.get_engine()
        meta = MetaData(bind=self.engine)
        self.table = Table(
            'cidr_tbl',
            meta,
            Column('id', Integer, primary_key=True),
            Column('addr', col_types.CIDR())
        )
        self.table.create()
        self.addCleanup(meta.drop_all)

    def test_cidr_repr(self):
        addrs = [('192.168.3.0/24', '192.168.3.0/24'),
                 ('2001:db8::/64', '2001:db8::/64'),
                 ('192.168.3.0', '192.168.3.0/32'),
                 ('2001:db8::', '2001:db8::/128'),
                 (None, None)]
        with self.engine.begin() as conn:
            for i in addrs:
                conn.execute(self.table.insert(), {'addr': i[0]})

            query = self.table.select().order_by(self.table.c.id)
            result = conn.execute(query)
            for idx, row in enumerate(result):
                self.assertEqual(addrs[idx][1], row.addr)


class TestMySQLSqlalchemyTypesRepr(TestSqlalchemyTypesRepr):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestPostgreSQLSqlalchemyTypesRepr(TestSqlalchemyTypesRepr):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class TestDBInstanceTags(test.TestCase):

    sample_data = {
        'project_id': 'project1',
        'hostname': 'example.com',
        'host': 'h1',
        'node': 'n1',
        'metadata': {'mkey1': 'mval1', 'mkey2': 'mval2'},
        'system_metadata': {'smkey1': 'smval1', 'smkey2': 'smval2'},
        'info_cache': {'ckey': 'cvalue'}
    }

    def setUp(self):
        super(TestDBInstanceTags, self).setUp()
        self.user_id = 'user1'
        self.project_id = 'project1'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def _create_instance(self):
        inst = db.instance_create(self.context, self.sample_data)
        return inst['uuid']

    def _get_tags_from_resp(self, tag_refs):
        return [(t.resource_id, t.tag) for t in tag_refs]

    def test_instance_tag_add(self):
        uuid = self._create_instance()

        tag = u'tag'
        tag_ref = db.instance_tag_add(self.context, uuid, tag)
        self.assertEqual(uuid, tag_ref.resource_id)
        self.assertEqual(tag, tag_ref.tag)

        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)

        # Check the tag for the instance was added
        tags = self._get_tags_from_resp(tag_refs)
        self.assertEqual([(uuid, tag)], tags)

    def test_instance_tag_add_duplication(self):
        uuid = self._create_instance()
        tag = u'tag'

        for x in range(5):
            db.instance_tag_add(self.context, uuid, tag)

        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)

        # Check the only one tag for the instance was added
        tags = self._get_tags_from_resp(tag_refs)
        self.assertEqual([(uuid, tag)], tags)

    def test_instance_tag_set(self):
        uuid = self._create_instance()

        tag1 = u'tag1'
        tag2 = u'tag2'
        tag3 = u'tag3'
        tag4 = u'tag4'

        # Set tags to the instance
        db.instance_tag_set(self.context, uuid, [tag1, tag2])
        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)

        # Check the tags for the instance were set
        tags = self._get_tags_from_resp(tag_refs)
        expected = [(uuid, tag1), (uuid, tag2)]
        self.assertEqual(expected, tags)

        # Set new tags to the instance
        db.instance_tag_set(self.context, uuid, [tag3, tag4, tag2])
        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)

        # Check the tags for the instance were replaced
        tags = self._get_tags_from_resp(tag_refs)
        expected = [(uuid, tag3), (uuid, tag4), (uuid, tag2)]
        self.assertEqual(set(expected), set(tags))

    @mock.patch('nova.db.sqlalchemy.models.Tag.__table__.insert',
                return_value=models.Tag.__table__.insert())
    def test_instance_tag_set_empty_add(self, mock_insert):
        uuid = self._create_instance()
        tag1 = u'tag1'
        tag2 = u'tag2'

        db.instance_tag_set(self.context, uuid, [tag1, tag2])

        # Check insert() was called to insert 'tag1' and 'tag2'
        mock_insert.assert_called_once_with(None)

        mock_insert.reset_mock()
        db.instance_tag_set(self.context, uuid, [tag1])

        # Check insert() wasn't called because there are no tags for creation
        mock_insert.assert_not_called()

    @mock.patch('sqlalchemy.orm.query.Query.delete')
    def test_instance_tag_set_empty_delete(self, mock_delete):
        uuid = self._create_instance()
        db.instance_tag_set(self.context, uuid, [u'tag1', u'tag2'])

        # Check delete() wasn't called because there are no tags for deletion
        mock_delete.assert_not_called()

        db.instance_tag_set(self.context, uuid, [u'tag1', u'tag3'])

        # Check delete() was called to delete 'tag2'
        mock_delete.assert_called_once_with(synchronize_session=False)

    def test_instance_tag_get_by_instance_uuid(self):
        uuid1 = self._create_instance()
        uuid2 = self._create_instance()

        tag1 = u'tag1'
        tag2 = u'tag2'
        tag3 = u'tag3'

        db.instance_tag_add(self.context, uuid1, tag1)
        db.instance_tag_add(self.context, uuid2, tag1)
        db.instance_tag_add(self.context, uuid2, tag2)
        db.instance_tag_add(self.context, uuid2, tag3)

        # Check the tags for the first instance
        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid1)
        tags = self._get_tags_from_resp(tag_refs)
        expected = [(uuid1, tag1)]

        self.assertEqual(expected, tags)

        # Check the tags for the second instance
        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid2)
        tags = self._get_tags_from_resp(tag_refs)
        expected = [(uuid2, tag1), (uuid2, tag2), (uuid2, tag3)]

        self.assertEqual(expected, tags)

    def test_instance_tag_get_by_instance_uuid_no_tags(self):
        uuid = self._create_instance()
        self.assertEqual([], db.instance_tag_get_by_instance_uuid(self.context,
                                                                  uuid))

    def test_instance_tag_delete(self):
        uuid = self._create_instance()
        tag1 = u'tag1'
        tag2 = u'tag2'

        db.instance_tag_add(self.context, uuid, tag1)
        db.instance_tag_add(self.context, uuid, tag2)

        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)
        tags = self._get_tags_from_resp(tag_refs)
        expected = [(uuid, tag1), (uuid, tag2)]

        # Check the tags for the instance were added
        self.assertEqual(expected, tags)

        db.instance_tag_delete(self.context, uuid, tag1)

        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)
        tags = self._get_tags_from_resp(tag_refs)
        expected = [(uuid, tag2)]
        self.assertEqual(expected, tags)

    def test_instance_tag_delete_non_existent(self):
        uuid = self._create_instance()
        self.assertRaises(exception.InstanceTagNotFound,
                          db.instance_tag_delete, self.context, uuid, u'tag')

    def test_instance_tag_delete_all(self):
        uuid = self._create_instance()
        tag1 = u'tag1'
        tag2 = u'tag2'

        db.instance_tag_add(self.context, uuid, tag1)
        db.instance_tag_add(self.context, uuid, tag2)

        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)
        tags = self._get_tags_from_resp(tag_refs)
        expected = [(uuid, tag1), (uuid, tag2)]

        # Check the tags for the instance were added
        self.assertEqual(expected, tags)

        db.instance_tag_delete_all(self.context, uuid)

        tag_refs = db.instance_tag_get_by_instance_uuid(self.context, uuid)
        tags = self._get_tags_from_resp(tag_refs)
        self.assertEqual([], tags)

    def test_instance_tag_exists(self):
        uuid = self._create_instance()
        tag1 = u'tag1'
        tag2 = u'tag2'

        db.instance_tag_add(self.context, uuid, tag1)

        # NOTE(snikitin): Make sure it's actually a bool
        self.assertTrue(db.instance_tag_exists(self.context, uuid,
                                                        tag1))
        self.assertFalse(db.instance_tag_exists(self.context, uuid,
                                                         tag2))

    def test_instance_tag_add_to_non_existing_instance(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, db.instance_tag_add,
                          self.context, 'fake_uuid', 'tag')

    def test_instance_tag_set_to_non_existing_instance(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, db.instance_tag_set,
                          self.context, 'fake_uuid', ['tag1', 'tag2'])

    def test_instance_tag_get_from_non_existing_instance(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound,
                          db.instance_tag_get_by_instance_uuid, self.context,
                          'fake_uuid')

    def test_instance_tag_delete_from_non_existing_instance(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, db.instance_tag_delete,
                          self.context, 'fake_uuid', 'tag')

    def test_instance_tag_delete_all_from_non_existing_instance(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound,
                          db.instance_tag_delete_all,
                          self.context, 'fake_uuid')

    def test_instance_tag_exists_non_existing_instance(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound,
                          db.instance_tag_exists,
                          self.context, 'fake_uuid', 'tag')


@mock.patch('time.sleep', new=lambda x: None)
class TestInstanceInfoCache(test.TestCase):
    def setUp(self):
        super(TestInstanceInfoCache, self).setUp()
        user_id = 'fake'
        project_id = 'fake'
        self.context = context.RequestContext(user_id, project_id)

    def test_instance_info_cache_get(self):
        instance = db.instance_create(self.context, {})
        network_info = 'net'
        db.instance_info_cache_update(self.context, instance.uuid,
                                      {'network_info': network_info})
        info_cache = db.instance_info_cache_get(self.context, instance.uuid)
        self.assertEqual(network_info, info_cache.network_info)

    def test_instance_info_cache_update(self):
        instance = db.instance_create(self.context, {})

        network_info1 = 'net1'
        db.instance_info_cache_update(self.context, instance.uuid,
                                      {'network_info': network_info1})
        info_cache = db.instance_info_cache_get(self.context, instance.uuid)
        self.assertEqual(network_info1, info_cache.network_info)

        network_info2 = 'net2'
        db.instance_info_cache_update(self.context, instance.uuid,
                                      {'network_info': network_info2})
        info_cache = db.instance_info_cache_get(self.context, instance.uuid)
        self.assertEqual(network_info2, info_cache.network_info)

    def test_instance_info_cache_delete(self):
        instance = db.instance_create(self.context, {})
        network_info = 'net'
        db.instance_info_cache_update(self.context, instance.uuid,
                                      {'network_info': network_info})
        info_cache = db.instance_info_cache_get(self.context, instance.uuid)
        self.assertEqual(network_info, info_cache.network_info)
        db.instance_info_cache_delete(self.context, instance.uuid)
        info_cache = db.instance_info_cache_get(self.context, instance.uuid)
        self.assertIsNone(info_cache)

    def test_instance_info_cache_update_duplicate(self):
        instance1 = db.instance_create(self.context, {})
        instance2 = db.instance_create(self.context, {})

        network_info1 = 'net1'
        db.instance_info_cache_update(self.context, instance1.uuid,
                                      {'network_info': network_info1})
        network_info2 = 'net2'
        db.instance_info_cache_update(self.context, instance2.uuid,
                                      {'network_info': network_info2})

        # updating of instance_uuid causes unique constraint failure,
        # using of savepoint helps to continue working with existing session
        # after DB errors, so exception was successfully handled
        db.instance_info_cache_update(self.context, instance2.uuid,
                                      {'instance_uuid': instance1.uuid})

        info_cache1 = db.instance_info_cache_get(self.context, instance1.uuid)
        self.assertEqual(network_info1, info_cache1.network_info)
        info_cache2 = db.instance_info_cache_get(self.context, instance2.uuid)
        self.assertEqual(network_info2, info_cache2.network_info)

    def test_instance_info_cache_create_using_update(self):
        network_info = 'net'
        instance_uuid = uuidsentinel.uuid1
        db.instance_info_cache_update(self.context, instance_uuid,
                                      {'network_info': network_info})
        info_cache = db.instance_info_cache_get(self.context, instance_uuid)
        self.assertEqual(network_info, info_cache.network_info)
        self.assertEqual(instance_uuid, info_cache.instance_uuid)

    @mock.patch.object(models.InstanceInfoCache, 'update')
    def test_instance_info_cache_retried_on_deadlock(self, update):
        update.side_effect = [db_exc.DBDeadlock(), db_exc.DBDeadlock(), None]

        instance = db.instance_create(self.context, {})
        network_info = 'net'
        updated = db.instance_info_cache_update(self.context, instance.uuid,
                                                {'network_info': network_info})
        self.assertEqual(instance.uuid, updated.instance_uuid)

    @mock.patch.object(models.InstanceInfoCache, 'update')
    def test_instance_info_cache_not_retried_on_deadlock_forever(self, update):
        update.side_effect = db_exc.DBDeadlock

        instance = db.instance_create(self.context, {})
        network_info = 'net'

        self.assertRaises(db_exc.DBDeadlock,
                          db.instance_info_cache_update,
                          self.context, instance.uuid,
                          {'network_info': network_info})


class TestInstanceTagsFiltering(test.TestCase):
    sample_data = {
        'project_id': 'project1'
    }

    def setUp(self):
        super(TestInstanceTagsFiltering, self).setUp()
        self.ctxt = context.RequestContext('user1', 'project1')

    def _create_instance_with_kwargs(self, **kw):
        context = kw.pop('context', self.ctxt)
        data = self.sample_data.copy()
        data.update(kw)
        return db.instance_create(context, data)

    def _create_instances(self, count):
        return [self._create_instance_with_kwargs()['uuid']
                for i in range(count)]

    def _assertEqualInstanceUUIDs(self, expected_uuids, observed_instances):
        observed_uuids = [inst['uuid'] for inst in observed_instances]
        self.assertEqual(sorted(expected_uuids), sorted(observed_uuids))

    def test_instance_get_all_by_filters_tag_any(self):
        uuids = self._create_instances(3)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't1', u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't3'])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags-any': [u't1', u't2']})
        self._assertEqualInstanceUUIDs([uuids[0], uuids[1]], result)

    def test_instance_get_all_by_filters_tag_any_empty(self):
        uuids = self._create_instances(2)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't1', u't2'])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags-any': [u't3', u't4']})
        self.assertEqual([], result)

    def test_instance_get_all_by_filters_tag(self):
        uuids = self._create_instances(3)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1', u't3'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2', u't3'])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags': [u't1', u't2']})
        self._assertEqualInstanceUUIDs([uuids[1], uuids[2]], result)

    def test_instance_get_all_by_filters_tag_empty(self):
        uuids = self._create_instances(2)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't1', u't2'])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags': [u't3']})
        self.assertEqual([], result)

    def test_instance_get_all_by_filters_tag_any_and_tag(self):
        uuids = self._create_instances(3)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't1', u't2', u't4'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't2', u't3'])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags': [u't1', u't2'],
                                                 'tags-any': [u't3', u't4']})
        self._assertEqualInstanceUUIDs([uuids[1]], result)

    def test_instance_get_all_by_filters_tags_and_project_id(self):
        context1 = context.RequestContext('user1', 'p1')
        context2 = context.RequestContext('user2', 'p2')

        uuid1 = self._create_instance_with_kwargs(
            context=context1, project_id='p1')['uuid']
        uuid2 = self._create_instance_with_kwargs(
            context=context1, project_id='p1')['uuid']
        uuid3 = self._create_instance_with_kwargs(
            context=context2, project_id='p2')['uuid']

        db.instance_tag_set(context1, uuid1, [u't1', u't2'])
        db.instance_tag_set(context1, uuid2, [u't1', u't2', u't4'])
        db.instance_tag_set(context2, uuid3, [u't1', u't2', u't3', u't4'])

        result = db.instance_get_all_by_filters(context.get_admin_context(),
                                                {'tags': [u't1', u't2'],
                                                 'tags-any': [u't3', u't4'],
                                                 'project_id': 'p1'})
        self._assertEqualInstanceUUIDs([uuid2], result)

    def test_instance_get_all_by_filters_not_tags(self):
        uuids = self._create_instances(8)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't2'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[3], [u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[4], [u't3'])
        db.instance_tag_set(self.ctxt, uuids[5], [u't1', u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[6], [u't3', u't4'])
        db.instance_tag_set(self.ctxt, uuids[7], [])

        result = db.instance_get_all_by_filters(
            self.ctxt, {'not-tags': [u't1', u't2']})

        self._assertEqualInstanceUUIDs([uuids[0], uuids[1], uuids[3], uuids[4],
                                        uuids[6], uuids[7]], result)

    def test_instance_get_all_by_filters_not_tags_multiple_cells(self):
        """Test added for bug 1682693.

        In cells v2 scenario, db.instance_get_all_by_filters() will
        be called multiple times to search across all cells. This
        test tests that filters for all cells remain the same in the
        loop.
        """
        uuids = self._create_instances(8)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't2'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[3], [u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[4], [u't3'])
        db.instance_tag_set(self.ctxt, uuids[5], [u't1', u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[6], [u't3', u't4'])
        db.instance_tag_set(self.ctxt, uuids[7], [])

        filters = {'not-tags': [u't1', u't2']}

        result = db.instance_get_all_by_filters(self.ctxt, filters)

        self._assertEqualInstanceUUIDs([uuids[0], uuids[1], uuids[3], uuids[4],
                                        uuids[6], uuids[7]], result)

    def test_instance_get_all_by_filters_not_tags_any(self):
        uuids = self._create_instances(8)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't2'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[3], [u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[4], [u't3'])
        db.instance_tag_set(self.ctxt, uuids[5], [u't1', u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[6], [u't3', u't4'])
        db.instance_tag_set(self.ctxt, uuids[7], [])

        result = db.instance_get_all_by_filters(
            self.ctxt, {'not-tags-any': [u't1', u't2']})
        self._assertEqualInstanceUUIDs([uuids[4], uuids[6], uuids[7]], result)

    def test_instance_get_all_by_filters_not_tags_and_tags(self):
        uuids = self._create_instances(5)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1', u't2', u't4', u't5'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't1', u't2', u't4'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[3], [u't1', u't3'])
        db.instance_tag_set(self.ctxt, uuids[4], [])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags': [u't1', u't2'],
                                                 'not-tags': [u't4', u't5']})
        self._assertEqualInstanceUUIDs([uuids[1], uuids[2]], result)

    def test_instance_get_all_by_filters_tags_contradictory(self):
        uuids = self._create_instances(4)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[3], [])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags': [u't1'],
                                                 'not-tags': [u't1']})
        self.assertEqual([], result)
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags': [u't1'],
                                                 'not-tags-any': [u't1']})
        self.assertEqual([], result)
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags-any': [u't1'],
                                                 'not-tags-any': [u't1']})
        self.assertEqual([], result)
        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags-any': [u't1'],
                                                 'not-tags': [u't1']})
        self.assertEqual([], result)

    def test_instance_get_all_by_filters_not_tags_and_tags_any(self):
        uuids = self._create_instances(6)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't2'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[3], [u't1', u't3'])
        db.instance_tag_set(self.ctxt, uuids[4], [u't1', u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[5], [])

        result = db.instance_get_all_by_filters(self.ctxt,
                                                {'tags-any': [u't1', u't2'],
                                                 'not-tags': [u't1', u't2']})
        self._assertEqualInstanceUUIDs([uuids[0], uuids[1], uuids[3]], result)

    def test_instance_get_all_by_filters_not_tags_and_not_tags_any(self):
        uuids = self._create_instances(6)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't2', u't5'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[3], [u't1', u't3'])
        db.instance_tag_set(self.ctxt, uuids[4], [u't1', u't2', u't4', u't5'])
        db.instance_tag_set(self.ctxt, uuids[5], [])

        result = db.instance_get_all_by_filters(self.ctxt,
                                              {'not-tags': [u't1', u't2'],
                                               'not-tags-any': [u't3', u't4']})
        self._assertEqualInstanceUUIDs([uuids[0], uuids[1], uuids[5]], result)

    def test_instance_get_all_by_filters_all_tag_filters(self):
        uuids = self._create_instances(9)

        db.instance_tag_set(self.ctxt, uuids[0], [u't1', u't3', u't7'])
        db.instance_tag_set(self.ctxt, uuids[1], [u't1', u't2'])
        db.instance_tag_set(self.ctxt, uuids[2], [u't1', u't2', u't7'])
        db.instance_tag_set(self.ctxt, uuids[3], [u't1', u't2', u't3', u't5'])
        db.instance_tag_set(self.ctxt, uuids[4], [u't1', u't2', u't3', u't7'])
        db.instance_tag_set(self.ctxt, uuids[5], [u't1', u't2', u't3'])
        db.instance_tag_set(self.ctxt, uuids[6], [u't1', u't2', u't3', u't4',
                                                  u't5'])
        db.instance_tag_set(self.ctxt, uuids[7], [u't1', u't2', u't3', u't4',
                                                  u't5', u't6'])
        db.instance_tag_set(self.ctxt, uuids[8], [])

        result = db.instance_get_all_by_filters(self.ctxt,
                                              {'tags': [u't1', u't2'],
                                               'tags-any': [u't3', u't4'],
                                               'not-tags': [u't5', u't6'],
                                               'not-tags-any': [u't7', u't8']})
        self._assertEqualInstanceUUIDs([uuids[3], uuids[5], uuids[6]], result)


class ConsoleAuthTokenTestCase(test.TestCase):

    def _create_instances(self, uuids):
        for uuid in uuids:
            db.instance_create(self.context,
                               {'uuid': uuid,
                                'project_id': self.context.project_id})

    def _create(self, token_hash, instance_uuid, expire_offset, host=None):
        t = copy.deepcopy(fake_console_auth_token.fake_token_dict)
        del t['id']
        t['token_hash'] = token_hash
        t['instance_uuid'] = instance_uuid
        t['expires'] = timeutils.utcnow_ts() + expire_offset
        if host:
            t['host'] = host
        db.console_auth_token_create(self.context, t)

    def setUp(self):
        super(ConsoleAuthTokenTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')

    def test_console_auth_token_create_no_instance(self):
        t = copy.deepcopy(fake_console_auth_token.fake_token_dict)
        del t['id']
        self.assertRaises(exception.InstanceNotFound,
                          db.console_auth_token_create,
                          self.context, t)

    def test_console_auth_token_get_valid_deleted_instance(self):
        uuid1 = uuidsentinel.uuid1
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        self._create_instances([uuid1])
        self._create(hash1, uuid1, 100)

        db_obj1 = db.console_auth_token_get_valid(self.context, hash1, uuid1)
        self.assertIsNotNone(db_obj1, "a valid token should be in database")

        db.instance_destroy(self.context, uuid1)
        self.assertRaises(exception.InstanceNotFound,
                          db.console_auth_token_get_valid,
                          self.context, hash1, uuid1)

    def test_console_auth_token_destroy_all_by_instance(self):
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        hash2 = utils.get_sha256_str(uuidsentinel.token2)
        hash3 = utils.get_sha256_str(uuidsentinel.token3)
        self._create_instances([uuid1, uuid2])
        self._create(hash1, uuid1, 100)
        self._create(hash2, uuid1, 100)
        self._create(hash3, uuid2, 100)

        db_obj1 = db.console_auth_token_get_valid(self.context, hash1, uuid1)
        db_obj2 = db.console_auth_token_get_valid(self.context, hash2, uuid1)
        db_obj3 = db.console_auth_token_get_valid(self.context, hash3, uuid2)
        self.assertIsNotNone(db_obj1, "a valid token should be in database")
        self.assertIsNotNone(db_obj2, "a valid token should be in database")
        self.assertIsNotNone(db_obj3, "a valid token should be in database")

        db.console_auth_token_destroy_all_by_instance(self.context, uuid1)

        db_obj4 = db.console_auth_token_get_valid(self.context, hash1, uuid1)
        db_obj5 = db.console_auth_token_get_valid(self.context, hash2, uuid1)
        db_obj6 = db.console_auth_token_get_valid(self.context, hash3, uuid2)
        self.assertIsNone(db_obj4, "no valid token should be in database")
        self.assertIsNone(db_obj5, "no valid token should be in database")
        self.assertIsNotNone(db_obj6, "a valid token should be in database")

    def test_console_auth_token_get_valid_by_expiry(self):
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        hash2 = utils.get_sha256_str(uuidsentinel.token2)
        self.addCleanup(timeutils.clear_time_override)
        timeutils.set_time_override(timeutils.utcnow())
        self._create_instances([uuid1, uuid2])

        self._create(hash1, uuid1, 10)
        timeutils.advance_time_seconds(100)
        self._create(hash2, uuid2, 10)

        db_obj1 = db.console_auth_token_get_valid(self.context, hash1, uuid1)
        db_obj2 = db.console_auth_token_get_valid(self.context, hash2, uuid2)
        self.assertIsNone(db_obj1, "the token should have expired")
        self.assertIsNotNone(db_obj2, "a valid token should be found here")

    def test_console_auth_token_get_valid_by_uuid(self):
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        self._create_instances([uuid1, uuid2])

        self._create(hash1, uuid1, 10)

        db_obj1 = db.console_auth_token_get_valid(self.context, hash1, uuid1)
        db_obj2 = db.console_auth_token_get_valid(self.context, hash1, uuid2)
        self.assertIsNotNone(db_obj1, "a valid token should be found here")
        self.assertEqual(hash1, db_obj1['token_hash'])
        self.assertIsNone(db_obj2, "the token uuid should not match")

    def test_console_auth_token_destroy_expired(self):
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2
        uuid3 = uuidsentinel.uuid3
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        hash2 = utils.get_sha256_str(uuidsentinel.token2)
        hash3 = utils.get_sha256_str(uuidsentinel.token3)
        self.addCleanup(timeutils.clear_time_override)
        timeutils.set_time_override(timeutils.utcnow())
        self._create_instances([uuid1, uuid2, uuid3])

        self._create(hash1, uuid1, 10)
        self._create(hash2, uuid2, 10, host='other-host')
        timeutils.advance_time_seconds(100)
        self._create(hash3, uuid3, 10)

        db.console_auth_token_destroy_expired(self.context)

        # the api only supports getting unexpired tokens
        # but by rolling back time we can see if a token that
        # should be deleted is still there
        timeutils.advance_time_seconds(-100)
        db_obj1 = db.console_auth_token_get_valid(self.context, hash1, uuid1)
        db_obj2 = db.console_auth_token_get_valid(self.context, hash2, uuid2)
        db_obj3 = db.console_auth_token_get_valid(self.context, hash3, uuid3)
        self.assertIsNone(db_obj1, "the token should have been deleted")
        self.assertIsNone(db_obj2, "the token should have been deleted")
        self.assertIsNotNone(db_obj3, "a valid token should be found here")

    def test_console_auth_token_destroy_expired_by_host(self):
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2
        uuid3 = uuidsentinel.uuid3
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        hash2 = utils.get_sha256_str(uuidsentinel.token2)
        hash3 = utils.get_sha256_str(uuidsentinel.token3)
        self.addCleanup(timeutils.clear_time_override)
        timeutils.set_time_override(timeutils.utcnow())
        self._create_instances([uuid1, uuid2, uuid3])

        self._create(hash1, uuid1, 10)
        self._create(hash2, uuid2, 10, host='other-host')
        timeutils.advance_time_seconds(100)
        self._create(hash3, uuid3, 10)

        db.console_auth_token_destroy_expired_by_host(
            self.context, 'fake-host')

        # the api only supports getting unexpired tokens
        # but by rolling back time we can see if a token that
        # should be deleted is still there
        timeutils.advance_time_seconds(-100)
        db_obj1 = db.console_auth_token_get_valid(self.context, hash1, uuid1)
        db_obj2 = db.console_auth_token_get_valid(self.context, hash2, uuid2)
        db_obj3 = db.console_auth_token_get_valid(self.context, hash3, uuid3)
        self.assertIsNone(db_obj1, "the token should have been deleted")
        self.assertIsNotNone(db_obj2, "a valid token should be found here")
        self.assertIsNotNone(db_obj3, "a valid token should be found here")

    def test_console_auth_token_get_valid_without_uuid_deleted_instance(self):
        uuid1 = uuidsentinel.uuid1
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        self._create_instances([uuid1])
        self._create(hash1, uuid1, 100)

        db_obj1 = db.console_auth_token_get_valid(self.context, hash1)
        self.assertIsNotNone(db_obj1, "a valid token should be in database")

        db.instance_destroy(self.context, uuid1)
        db_obj1 = db.console_auth_token_get_valid(self.context, hash1)
        self.assertIsNone(db_obj1, "the token should have been deleted")

    def test_console_auth_token_get_valid_without_uuid_by_expiry(self):
        uuid1 = uuidsentinel.uuid1
        uuid2 = uuidsentinel.uuid2
        hash1 = utils.get_sha256_str(uuidsentinel.token1)
        hash2 = utils.get_sha256_str(uuidsentinel.token2)
        self.addCleanup(timeutils.clear_time_override)
        timeutils.set_time_override(timeutils.utcnow())
        self._create_instances([uuid1, uuid2])

        self._create(hash1, uuid1, 10)
        timeutils.advance_time_seconds(100)
        self._create(hash2, uuid2, 10)

        db_obj1 = db.console_auth_token_get_valid(self.context, hash1)
        db_obj2 = db.console_auth_token_get_valid(self.context, hash2)
        self.assertIsNone(db_obj1, "the token should have expired")
        self.assertIsNotNone(db_obj2, "a valid token should be found here")


class SortMarkerHelper(test.TestCase):
    def setUp(self):
        super(SortMarkerHelper, self).setUp()

        self.context = context.RequestContext('fake', 'fake')
        self.instances = []

        launched = datetime.datetime(2005, 4, 30, 13, 00, 00)
        td = datetime.timedelta

        values = {
            'key_name': ['dan', 'dan', 'taylor', 'jax'],
            'memory_mb': [512, 1024, 512, 256],
            'launched_at': [launched + td(1), launched - td(256),
                            launched + td(32), launched - td(5000)],
        }

        for i in range(0, 4):
            inst = {'user_id': self.context.user_id,
                    'project_id': self.context.project_id,
                    'auto_disk_config': bool(i % 2),
                    'vcpus': 1}
            for key in values:
                inst[key] = values[key].pop(0)
            db_instance = db.instance_create(self.context, inst)
            self.instances.append(db_instance)

    def test_with_one_key(self):
        """Test instance_get_by_sort_filters() with one sort key."""
        # If we sort ascending by key_name and our marker was something
        # just after jax, taylor would be the next one.
        marker = db.instance_get_by_sort_filters(
            self.context,
            ['key_name'], ['asc'], ['jaxz'])
        self.assertEqual(self.instances[2]['uuid'], marker)

    def _test_with_multiple_keys(self, sort_keys, sort_dirs, value_fn):
        """Test instance_get_by_sort_filters() with multiple sort keys.

        Since this returns the marker it's looking for, it's actually really
        hard to test this like we normally would with pagination, i.e. marching
        through the instances in order. Attempting to do so covered up a bug
        in this previously.

        So, for a list of marker values, query and assert we get the instance
        we expect.
        """

        # For the query below, ordering memory_mb asc, key_name desc,
        # The following is the expected ordering of the instances we
        # have to test:
        #
        #   256-jax
        #   512-taylor
        #   512-dan
        #   1024-dan

        steps = [
            (200, 'foo', 3),  # all less than 256-jax
            (256, 'xyz', 3),  # name comes before jax
            (256, 'jax', 3),  # all equal to 256-jax
            (256, 'abc', 2),  # name after jax
            (500, 'foo', 2),  # all greater than 256-jax
            (512, 'xyz', 2),  # name before taylor and dan
            (512, 'mno', 0),  # name after taylor, before dan-512
            (512, 'abc', 1),  # name after dan-512
            (999, 'foo', 1),  # all greater than 512-taylor
            (1024, 'xyz', 1),  # name before dan
            (1024, 'abc', None),  # name after dan
            (2048, 'foo', None),  # all greater than 1024-dan
        ]

        for mem, name, expected in steps:
            marker = db.instance_get_by_sort_filters(
                self.context,
                sort_keys,
                sort_dirs,
                value_fn(mem, name))
            if expected is None:
                self.assertIsNone(marker)
            else:
                expected_inst = self.instances[expected]
                got_inst = [inst for inst in self.instances
                            if inst['uuid'] == marker][0]
                self.assertEqual(
                    expected_inst['uuid'],
                    marker,
                    'marker %s-%s expected %s-%s got %s-%s' % (
                        mem, name,
                        expected_inst['memory_mb'], expected_inst['key_name'],
                        got_inst['memory_mb'], got_inst['key_name']))

    def test_with_two_keys(self):
        """Test instance_get_by_sort_filters() with two sort_keys."""
        self._test_with_multiple_keys(
            ['memory_mb', 'key_name'],
            ['asc', 'desc'],
            lambda mem, name: [mem, name])

    def test_with_three_keys(self):
        """Test instance_get_by_sort_filters() with three sort_keys.

        This inserts another key in the middle of memory_mb,key_name
        which is always equal in all the test instances. We do this
        to make sure that we are only including the equivalence fallback
        on the final sort_key, otherwise we might stall out in the
        middle of a series of instances with equivalent values for
        a key in the middle of sort_keys.
        """
        self._test_with_multiple_keys(
            ['memory_mb', 'vcpus', 'key_name'],
            ['asc', 'asc', 'desc'],
            lambda mem, name: [mem, 1, name])

    def test_no_match(self):
        marker = db.instance_get_by_sort_filters(self.context,
                                                 ['memory_mb'], ['asc'],
                                                 [4096])
        # None of our instances have >= 4096mb, so nothing matches
        self.assertIsNone(marker)

    def test_by_bool(self):
        """Verify that we can use booleans in sort_keys."""
        # If we sort ascending by auto_disk_config, the first one
        # with True for that value would be the second instance we
        # create, because bool(1 % 2) == True.
        marker = db.instance_get_by_sort_filters(
            self.context,
            ['auto_disk_config', 'id'], ['asc', 'asc'], [True, 2])
        self.assertEqual(self.instances[1]['uuid'], marker)

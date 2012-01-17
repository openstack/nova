# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Unit tests for the DB API"""

import datetime

from nova import test
from nova import context
from nova import exception
from nova import db
from nova import flags
from nova import utils

FLAGS = flags.FLAGS


def _setup_networking(instance_id, ip='1.2.3.4', flo_addr='1.2.1.2'):
    ctxt = context.get_admin_context()
    network_ref = db.project_get_networks(ctxt,
                                           'fake',
                                           associate=True)[0]
    vif = {'address': '56:12:12:12:12:12',
           'network_id': network_ref['id'],
           'instance_id': instance_id}
    vif_ref = db.virtual_interface_create(ctxt, vif)

    fixed_ip = {'address': ip,
                'network_id': network_ref['id'],
                'virtual_interface_id': vif_ref['id'],
                'allocated': True,
                'instance_id': instance_id}
    db.fixed_ip_create(ctxt, fixed_ip)
    fix_ref = db.fixed_ip_get_by_address(ctxt, ip)
    db.floating_ip_create(ctxt, {'address': flo_addr,
                                 'fixed_ip_id': fix_ref['id']})


class DbApiTestCase(test.TestCase):
    def setUp(self):
        super(DbApiTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def test_instance_get_project_vpn(self):
        values = {'instance_type_id': FLAGS.default_instance_type,
                  'image_ref': FLAGS.vpn_image_id,
                  'project_id': self.project_id,
                 }
        instance = db.instance_create(self.context, values)
        result = db.instance_get_project_vpn(self.context.elevated(),
                                             self.project_id)
        self.assertEqual(instance['id'], result['id'])

    def test_instance_get_all_by_filters(self):
        args = {'reservation_id': 'a', 'image_ref': 1, 'host': 'host1'}
        inst1 = db.instance_create(self.context, args)
        inst2 = db.instance_create(self.context, args)
        result = db.instance_get_all_by_filters(self.context, {})
        self.assertTrue(2, len(result))

    def test_instance_get_all_by_filters_deleted(self):
        args1 = {'reservation_id': 'a', 'image_ref': 1, 'host': 'host1'}
        inst1 = db.instance_create(self.context, args1)
        args2 = {'reservation_id': 'b', 'image_ref': 1, 'host': 'host1'}
        inst2 = db.instance_create(self.context, args2)
        db.instance_destroy(self.context.elevated(), inst1['id'])
        result = db.instance_get_all_by_filters(self.context.elevated(), {})
        self.assertEqual(2, len(result))
        self.assertIn(inst1.id, [result[0].id, result[1].id])
        self.assertIn(inst2.id, [result[0].id, result[1].id])
        if inst1.id == result[0].id:
            self.assertTrue(result[0].deleted)
        else:
            self.assertTrue(result[1].deleted)

    def test_migration_get_all_unconfirmed(self):
        ctxt = context.get_admin_context()

        # Ensure no migrations are returned.
        results = db.migration_get_all_unconfirmed(ctxt, 10)
        self.assertEqual(0, len(results))

        # Ensure one migration older than 10 seconds is returned.
        updated_at = datetime.datetime(2000, 01, 01, 12, 00, 00)
        values = {"status": "FINISHED", "updated_at": updated_at}
        migration = db.migration_create(ctxt, values)
        results = db.migration_get_all_unconfirmed(ctxt, 10)
        self.assertEqual(1, len(results))
        db.migration_update(ctxt, migration.id, {"status": "CONFIRMED"})

        # Ensure the new migration is not returned.
        updated_at = datetime.datetime.utcnow()
        values = {"status": "FINISHED", "updated_at": updated_at}
        migration = db.migration_create(ctxt, values)
        results = db.migration_get_all_unconfirmed(ctxt, 10)
        self.assertEqual(0, len(results))
        db.migration_update(ctxt, migration.id, {"status": "CONFIRMED"})

    def test_instance_get_all_hung_in_rebooting(self):
        ctxt = context.get_admin_context()

        # Ensure no instances are returned.
        results = db.instance_get_all_hung_in_rebooting(ctxt, 10)
        self.assertEqual(0, len(results))

        # Ensure one rebooting instance with updated_at older than 10 seconds
        # is returned.
        updated_at = datetime.datetime(2000, 01, 01, 12, 00, 00)
        values = {"task_state": "rebooting", "updated_at": updated_at}
        instance = db.instance_create(ctxt, values)
        results = db.instance_get_all_hung_in_rebooting(ctxt, 10)
        self.assertEqual(1, len(results))
        db.instance_update(ctxt, instance.id, {"task_state": None})

        # Ensure the newly rebooted instance is not returned.
        updated_at = datetime.datetime.utcnow()
        values = {"task_state": "rebooting", "updated_at": updated_at}
        instance = db.instance_create(ctxt, values)
        results = db.instance_get_all_hung_in_rebooting(ctxt, 10)
        self.assertEqual(0, len(results))
        db.instance_update(ctxt, instance.id, {"task_state": None})

    def test_network_create_safe(self):
        ctxt = context.get_admin_context()
        values = {'host': 'localhost', 'project_id': 'project1'}
        network = db.network_create_safe(ctxt, values)
        self.assertNotEqual(None, network.uuid)
        self.assertEqual(36, len(network.uuid))
        db_network = db.network_get(ctxt, network.id)
        self.assertEqual(network.uuid, db_network.uuid)

    def test_instance_update_with_instance_id(self):
        """ test instance_update() works when an instance id is passed """
        ctxt = context.get_admin_context()

        # Create an instance with some metadata
        metadata = {'host': 'foo'}
        values = {'metadata': metadata}
        instance = db.instance_create(ctxt, values)

        # Update the metadata
        metadata = {'host': 'bar'}
        values = {'metadata': metadata}
        db.instance_update(ctxt, instance.id, values)

        # Retrieve the metadata to ensure it was successfully updated
        instance_meta = db.instance_metadata_get(ctxt, instance.id)
        self.assertEqual('bar', instance_meta['host'])

    def test_instance_update_with_instance_uuid(self):
        """ test instance_update() works when an instance UUID is passed """
        ctxt = context.get_admin_context()

        # Create an instance with some metadata
        metadata = {'host': 'foo'}
        values = {'metadata': metadata}
        instance = db.instance_create(ctxt, values)

        # Update the metadata
        metadata = {'host': 'bar'}
        values = {'metadata': metadata}
        db.instance_update(ctxt, instance.uuid, values)

        # Retrieve the metadata to ensure it was successfully updated
        instance_meta = db.instance_metadata_get(ctxt, instance.id)
        self.assertEqual('bar', instance_meta['host'])

    def test_instance_fault_create(self):
        """Ensure we can create an instance fault"""
        ctxt = context.get_admin_context()
        uuid = str(utils.gen_uuid())

        # Create a fault
        fault_values = {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuid,
            'code': 404,
        }
        db.instance_fault_create(ctxt, fault_values)

        # Retrieve the fault to ensure it was successfully added
        faults = db.instance_fault_get_by_instance_uuids(ctxt, [uuid])
        self.assertEqual(404, faults[uuid][0]['code'])

    def test_instance_fault_get_by_instance(self):
        """ ensure we can retrieve an instance fault by  instance UUID """
        ctxt = context.get_admin_context()
        instance1 = db.instance_create(ctxt, {})
        instance2 = db.instance_create(ctxt, {})
        uuids = [instance1['uuid'], instance2['uuid']]

        # Create faults
        fault_values = {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuids[0],
            'code': 404,
        }
        fault1 = db.instance_fault_create(ctxt, fault_values)

        fault_values = {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuids[0],
            'code': 500,
        }
        fault2 = db.instance_fault_create(ctxt, fault_values)

        fault_values = {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuids[1],
            'code': 404,
        }
        fault3 = db.instance_fault_create(ctxt, fault_values)

        fault_values = {
            'message': 'message',
            'details': 'detail',
            'instance_uuid': uuids[1],
            'code': 500,
        }
        fault4 = db.instance_fault_create(ctxt, fault_values)

        instance_faults = db.instance_fault_get_by_instance_uuids(ctxt, uuids)

        expected = {
                uuids[0]: [fault2, fault1],
                uuids[1]: [fault4, fault3],
        }

        self.assertEqual(instance_faults, expected)

    def test_instance_faults_get_by_instance_uuids_no_faults(self):
        """None should be returned when no faults exist"""
        ctxt = context.get_admin_context()
        instance1 = db.instance_create(ctxt, {})
        instance2 = db.instance_create(ctxt, {})
        uuids = [instance1['uuid'], instance2['uuid']]
        instance_faults = db.instance_fault_get_by_instance_uuids(ctxt, uuids)
        expected = {uuids[0]: [], uuids[1]: []}
        self.assertEqual(expected, instance_faults)


def _get_fake_aggr_values():
    return {'name': 'fake_aggregate',
            'availability_zone': 'fake_avail_zone', }


def _get_fake_aggr_metadata():
    return {'fake_key1': 'fake_value1',
            'fake_key2': 'fake_value2'}


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
        db.aggregate_host_add(context, result.id, host)
    return result


class AggregateDBApiTestCase(test.TestCase):
    def setUp(self):
        super(AggregateDBApiTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def tearDown(self):
        super(AggregateDBApiTestCase, self).tearDown()

    def test_aggregate_create(self):
        """Ensure aggregate can be created with no metadata."""
        result = _create_aggregate(metadata=None)
        self.assertEqual(result['operational_state'], 'building')

    def test_aggregate_create_raise_exist_exc(self):
        """Ensure aggregate names are distinct."""
        _create_aggregate(metadata=None)
        self.assertRaises(exception.AggregateNameExists,
                          _create_aggregate, metadata=None)

    def test_aggregate_get_raise_not_found(self):
        """Ensure AggregateNotFound is raised when getting an aggregate."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_get,
                          ctxt, aggregate_id)

    def test_aggregate_metadata_get_raise_not_found(self):
        """Ensure AggregateNotFound is raised when getting metadata."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_metadata_get,
                          ctxt, aggregate_id)

    def test_aggregate_create_with_metadata(self):
        """Ensure aggregate can be created with metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        expected_metadata = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertDictMatch(expected_metadata, _get_fake_aggr_metadata())

    def test_aggregate_create_low_privi_context(self):
        """Ensure right context is applied when creating aggregate."""
        self.assertRaises(exception.AdminRequired,
                          db.aggregate_create,
                          self.context, _get_fake_aggr_values())

    def test_aggregate_delete_raise_not_found(self):
        """Ensure AggregateNotFound is raised when deleting an aggregate."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_delete,
                          ctxt, aggregate_id)

    def test_aggregate_delete(self):
        """Ensure we can delete an aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        db.aggregate_delete(ctxt, result['id'])
        expected = db.aggregate_get_all(ctxt, read_deleted='no')
        self.assertEqual(0, len(expected))

    def test_aggregate_update(self):
        """Ensure an aggregate can be updated."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        new_values = _get_fake_aggr_values()
        new_values['availability_zone'] = 'different_avail_zone'
        updated = db.aggregate_update(ctxt, 1, new_values)
        self.assertNotEqual(result.availability_zone,
                            updated.availability_zone)

    def test_aggregate_update_with_metadata(self):
        """Ensure an aggregate can be updated with metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        self.assertDictMatch(_get_fake_aggr_metadata(), expected)

    def test_aggregate_update_with_existing_metadata(self):
        """Ensure an aggregate can be updated with existing metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        values['metadata']['fake_key1'] = 'foo'
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        self.assertDictMatch(values['metadata'], expected)

    def test_aggregate_update_raise_not_found(self):
        """Ensure AggregateNotFound is raised when updating an aggregate."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        new_values = _get_fake_aggr_values()
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_update, ctxt, aggregate_id, new_values)

    def test_aggregate_get_all(self):
        """Ensure we can get all aggregates."""
        ctxt = context.get_admin_context()
        counter = 3
        for c in xrange(counter):
            _create_aggregate(context=ctxt,
                              values={'name': 'fake_aggregate_%d' % c,
                                      'availability_zone': 'fake_avail_zone'},
                              metadata=None)
        results = db.aggregate_get_all(ctxt)
        self.assertEqual(len(results), counter)

    def test_aggregate_get_all_non_deleted(self):
        """Ensure we get only non-deleted aggregates."""
        ctxt = context.get_admin_context()
        add_counter = 5
        remove_counter = 2
        aggregates = []
        for c in xrange(1, add_counter):
            values = {'name': 'fake_aggregate_%d' % c,
                      'availability_zone': 'fake_avail_zone'}
            aggregates.append(_create_aggregate(context=ctxt,
                                                values=values, metadata=None))
        for c in xrange(1, remove_counter):
            db.aggregate_delete(ctxt, aggregates[c - 1].id)
        results = db.aggregate_get_all(ctxt, read_deleted='no')
        self.assertEqual(len(results), add_counter - remove_counter)

    def test_aggregate_metadata_add(self):
        """Ensure we can add metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result.id, metadata)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        self.assertDictMatch(metadata, expected)

    def test_aggregate_metadata_update(self):
        """Ensure we can update metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        metadata = _get_fake_aggr_metadata()
        key = metadata.keys()[0]
        db.aggregate_metadata_delete(ctxt, result.id, key)
        new_metadata = {key: 'foo'}
        db.aggregate_metadata_add(ctxt, result.id, new_metadata)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        metadata[key] = 'foo'
        self.assertDictMatch(metadata, expected)

    def test_aggregate_metadata_delete(self):
        """Ensure we can delete metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result.id, metadata)
        db.aggregate_metadata_delete(ctxt, result.id, metadata.keys()[0])
        expected = db.aggregate_metadata_get(ctxt, result.id)
        del metadata[metadata.keys()[0]]
        self.assertDictMatch(metadata, expected)

    def test_aggregate_metadata_delete_raise_not_found(self):
        """Ensure AggregateMetadataNotFound is raised when deleting."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateMetadataNotFound,
                          db.aggregate_metadata_delete,
                          ctxt, result.id, 'foo_key')

    def test_aggregate_host_add(self):
        """Ensure we can add host to the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        expected = db.aggregate_host_get_all(ctxt, result.id)
        self.assertEqual(_get_fake_aggr_hosts(), expected)

    def test_aggregate_host_add_duplicate_raise_conflict(self):
        """Ensure we cannot add host to distinct aggregates."""
        ctxt = context.get_admin_context()
        _create_aggregate_with_hosts(context=ctxt, metadata=None)
        self.assertRaises(exception.AggregateHostConflict,
                          _create_aggregate_with_hosts, ctxt,
                          values={'name': 'fake_aggregate2',
                                  'availability_zone': 'fake_avail_zone2', },
                          metadata=None)

    def test_aggregate_host_add_duplicate_raise_exist_exc(self):
        """Ensure we cannot add host to the same aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        self.assertRaises(exception.AggregateHostExists,
                          db.aggregate_host_add,
                          ctxt, result.id, _get_fake_aggr_hosts()[0])

    def test_aggregate_host_add_raise_not_found(self):
        """Ensure AggregateFound when adding a host."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        host = _get_fake_aggr_hosts()[0]
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_host_add,
                          ctxt, aggregate_id, host)

    def test_aggregate_host_delete(self):
        """Ensure we can add host to the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        db.aggregate_host_delete(ctxt, result.id,
                                 _get_fake_aggr_hosts()[0])
        expected = db.aggregate_host_get_all(ctxt, result.id,
                                             read_deleted='no')
        self.assertEqual(0, len(expected))

    def test_aggregate_host_delete_raise_not_found(self):
        """Ensure AggregateHostNotFound is raised when deleting a host."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateHostNotFound,
                          db.aggregate_host_delete,
                          ctxt, result.id, _get_fake_aggr_hosts()[0])

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

"""Unit tests for the DB API"""

import datetime
import uuid as stdlib_uuid

from nova import context
from nova import db
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import timeutils
from nova import test
from nova.tests import matchers


CONF = cfg.CONF
CONF.import_opt('reserved_host_memory_mb', 'nova.compute.resource_tracker')
CONF.import_opt('reserved_host_disk_mb', 'nova.compute.resource_tracker')


class DbApiTestCase(test.TestCase):
    def setUp(self):
        super(DbApiTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def create_instances_with_args(self, **kwargs):
        args = {'reservation_id': 'a', 'image_ref': 1, 'host': 'host1',
                'project_id': self.project_id, 'vm_state': 'fake'}
        if 'context' in kwargs:
            ctxt = kwargs.pop('context')
            args['project_id'] = ctxt.project_id
        else:
            ctxt = self.context
        args.update(kwargs)
        return db.instance_create(ctxt, args)

    def test_create_instance_unique_hostname(self):
        otherprojectcontext = context.RequestContext(self.user_id,
                                          "%s2" % self.project_id)

        self.create_instances_with_args(hostname='fake_name')

        # With scope 'global' any duplicate should fail, be it this project:
        self.flags(osapi_compute_unique_server_name_scope='global')
        self.assertRaises(exception.InstanceExists,
                          self.create_instances_with_args,
                          hostname='fake_name')

        # or another:
        self.assertRaises(exception.InstanceExists,
                          self.create_instances_with_args,
                          context=otherprojectcontext,
                          hostname='fake_name')

        # With scope 'project' a duplicate in the project should fail:
        self.flags(osapi_compute_unique_server_name_scope='project')
        self.assertRaises(exception.InstanceExists,
                          self.create_instances_with_args,
                          hostname='fake_name')

        # With scope 'project' a duplicate in a different project should work:
        self.flags(osapi_compute_unique_server_name_scope='project')
        self.create_instances_with_args(context=otherprojectcontext,
                                        hostname='fake_name')

        self.flags(osapi_compute_unique_server_name_scope=None)

    def test_ec2_ids_not_found_are_printable(self):
        def check_exc_format(method):
            try:
                method(self.context, 'fake')
            except exception.NotFound as exc:
                self.assertTrue('fake' in unicode(exc))

        check_exc_format(db.get_ec2_volume_id_by_uuid)
        check_exc_format(db.get_volume_uuid_by_ec2_id)
        check_exc_format(db.get_ec2_snapshot_id_by_uuid)
        check_exc_format(db.get_snapshot_uuid_by_ec2_id)
        check_exc_format(db.get_ec2_instance_id_by_uuid)
        check_exc_format(db.get_instance_uuid_by_ec2_id)

    def test_instance_get_all_by_filters(self):
        self.create_instances_with_args()
        self.create_instances_with_args()
        result = db.instance_get_all_by_filters(self.context, {})
        self.assertEqual(2, len(result))

    def test_instance_get_all_by_filters_regex(self):
        self.create_instances_with_args(display_name='test1')
        self.create_instances_with_args(display_name='teeeest2')
        self.create_instances_with_args(display_name='diff')
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': 't.*st.'})
        self.assertEqual(2, len(result))

    def test_instance_get_all_by_filters_regex_unsupported_db(self):
        """Ensure that the 'LIKE' operator is used for unsupported dbs."""
        self.flags(sql_connection="notdb://")
        self.create_instances_with_args(display_name='test1')
        self.create_instances_with_args(display_name='test.*')
        self.create_instances_with_args(display_name='diff')
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': 'test.*'})
        self.assertEqual(1, len(result))
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': '%test%'})
        self.assertEqual(2, len(result))

    def test_instance_get_all_by_filters_metadata(self):
        self.create_instances_with_args(metadata={'foo': 'bar'})
        self.create_instances_with_args()
        result = db.instance_get_all_by_filters(self.context,
                                                {'metadata': {'foo': 'bar'}})
        self.assertEqual(1, len(result))

    def test_instance_get_all_by_filters_unicode_value(self):
        self.create_instances_with_args(display_name=u'test♥')
        result = db.instance_get_all_by_filters(self.context,
                                                {'display_name': u'test'})
        self.assertEqual(1, len(result))

    def test_instance_get_all_by_filters_deleted(self):
        inst1 = self.create_instances_with_args()
        inst2 = self.create_instances_with_args(reservation_id='b')
        db.instance_destroy(self.context, inst1['uuid'])
        result = db.instance_get_all_by_filters(self.context, {})
        self.assertEqual(2, len(result))
        self.assertIn(inst1['id'], [result[0]['id'], result[1]['id']])
        self.assertIn(inst2['id'], [result[0]['id'], result[1]['id']])
        if inst1['id'] == result[0]['id']:
            self.assertTrue(result[0]['deleted'])
        else:
            self.assertTrue(result[1]['deleted'])

    def test_instance_get_all_by_filters_paginate(self):
        self.flags(sql_connection="notdb://")
        test1 = self.create_instances_with_args(display_name='test1')
        test2 = self.create_instances_with_args(display_name='test2')
        test3 = self.create_instances_with_args(display_name='test3')

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

    def test_migration_get_unconfirmed_by_dest_compute(self):
        ctxt = context.get_admin_context()

        # Ensure no migrations are returned.
        results = db.migration_get_unconfirmed_by_dest_compute(ctxt, 10,
                'fake_host')
        self.assertEqual(0, len(results))

        # Ensure no migrations are returned.
        results = db.migration_get_unconfirmed_by_dest_compute(ctxt, 10,
                'fake_host2')
        self.assertEqual(0, len(results))

        updated_at = datetime.datetime(2000, 01, 01, 12, 00, 00)
        values = {"status": "finished", "updated_at": updated_at,
                "dest_compute": "fake_host2"}
        migration = db.migration_create(ctxt, values)

        # Ensure different host is not returned
        results = db.migration_get_unconfirmed_by_dest_compute(ctxt, 10,
                'fake_host')
        self.assertEqual(0, len(results))

        # Ensure one migration older than 10 seconds is returned.
        results = db.migration_get_unconfirmed_by_dest_compute(ctxt, 10,
                'fake_host2')
        self.assertEqual(1, len(results))
        db.migration_update(ctxt, migration['id'], {"status": "CONFIRMED"})

        # Ensure the new migration is not returned.
        updated_at = timeutils.utcnow()
        values = {"status": "finished", "updated_at": updated_at,
                "dest_compute": "fake_host2"}
        migration = db.migration_create(ctxt, values)
        results = db.migration_get_unconfirmed_by_dest_compute(ctxt, 10,
                "fake_host2")
        self.assertEqual(0, len(results))
        db.migration_update(ctxt, migration['id'], {"status": "CONFIRMED"})

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
        db.instance_update(ctxt, instance['uuid'], {"task_state": None})

        # Ensure the newly rebooted instance is not returned.
        updated_at = timeutils.utcnow()
        values = {"task_state": "rebooting", "updated_at": updated_at}
        instance = db.instance_create(ctxt, values)
        results = db.instance_get_all_hung_in_rebooting(ctxt, 10)
        self.assertEqual(0, len(results))
        db.instance_update(ctxt, instance['uuid'], {"task_state": None})

    def test_network_create_safe(self):
        ctxt = context.get_admin_context()
        values = {'host': 'localhost', 'project_id': 'project1'}
        network = db.network_create_safe(ctxt, values)
        self.assertNotEqual(None, network['uuid'])
        self.assertEqual(36, len(network['uuid']))
        db_network = db.network_get(ctxt, network['id'])
        self.assertEqual(network['uuid'], db_network['uuid'])

    def test_network_delete_safe(self):
        ctxt = context.get_admin_context()
        values = {'host': 'localhost', 'project_id': 'project1'}
        network = db.network_create_safe(ctxt, values)
        db_network = db.network_get(ctxt, network['id'])
        values = {'network_id': network['id'], 'address': 'fake1'}
        address1 = db.fixed_ip_create(ctxt, values)
        values = {'network_id': network['id'],
                  'address': 'fake2',
                  'allocated': True}
        address2 = db.fixed_ip_create(ctxt, values)
        self.assertRaises(exception.NetworkInUse,
                          db.network_delete_safe, ctxt, network['id'])
        db.fixed_ip_update(ctxt, address2, {'allocated': False})
        network = db.network_delete_safe(ctxt, network['id'])
        self.assertRaises(exception.FixedIpNotFoundForAddress,
                          db.fixed_ip_get_by_address, ctxt, address1)
        ctxt = ctxt.elevated(read_deleted='yes')
        fixed_ip = db.fixed_ip_get_by_address(ctxt, address1)
        self.assertTrue(fixed_ip['deleted'])

    def test_network_create_with_duplicate_vlan(self):
        ctxt = context.get_admin_context()
        values1 = {'host': 'localhost', 'project_id': 'project1', 'vlan': 1}
        values2 = {'host': 'something', 'project_id': 'project1', 'vlan': 1}
        db.network_create_safe(ctxt, values1)
        self.assertRaises(exception.DuplicateVlan,
                          db.network_create_safe, ctxt, values2)

    def test_instance_update_with_instance_uuid(self):
        """ test instance_update() works when an instance UUID is passed """
        ctxt = context.get_admin_context()

        # Create an instance with some metadata
        values = {'metadata': {'host': 'foo'},
                  'system_metadata': {'original_image_ref': 'blah'}}
        instance = db.instance_create(ctxt, values)

        # Update the metadata
        values = {'metadata': {'host': 'bar'},
                  'system_metadata': {'original_image_ref': 'baz'}}
        db.instance_update(ctxt, instance['uuid'], values)

        # Retrieve the user-provided metadata to ensure it was successfully
        # updated
        instance_meta = db.instance_metadata_get(ctxt, instance['uuid'])
        self.assertEqual('bar', instance_meta['host'])

        # Retrieve the system metadata to ensure it was successfully updated
        system_meta = db.instance_system_metadata_get(ctxt, instance['uuid'])
        self.assertEqual('baz', system_meta['original_image_ref'])

    def test_instance_update_of_instance_type_id(self):
        ctxt = context.get_admin_context()

        inst_type1 = db.instance_type_get_by_name(ctxt, 'm1.tiny')
        inst_type2 = db.instance_type_get_by_name(ctxt, 'm1.small')

        values = {'instance_type_id': inst_type1['id']}
        instance = db.instance_create(ctxt, values)

        self.assertEqual(instance['instance_type']['id'], inst_type1['id'])
        self.assertEqual(instance['instance_type']['name'],
                inst_type1['name'])

        values = {'instance_type_id': inst_type2['id']}
        instance = db.instance_update(ctxt, instance['uuid'], values)

        self.assertEqual(instance['instance_type']['id'], inst_type2['id'])
        self.assertEqual(instance['instance_type']['name'],
                inst_type2['name'])

    def test_instance_update_unique_name(self):
        otherprojectcontext = context.RequestContext(self.user_id,
                                          "%s2" % self.project_id)

        inst = self.create_instances_with_args(hostname='fake_name')
        uuid1p1 = inst['uuid']
        inst = self.create_instances_with_args(hostname='fake_name2')
        uuid2p1 = inst['uuid']

        inst = self.create_instances_with_args(context=otherprojectcontext,
                                               hostname='fake_name3')
        uuid1p2 = inst['uuid']

        # osapi_compute_unique_server_name_scope is unset so this should work:
        values = {'hostname': 'fake_name2'}
        db.instance_update(self.context, uuid1p1, values)
        values = {'hostname': 'fake_name'}
        db.instance_update(self.context, uuid1p1, values)

        # With scope 'global' any duplicate should fail.
        self.flags(osapi_compute_unique_server_name_scope='global')
        self.assertRaises(exception.InstanceExists,
                          db.instance_update,
                          self.context,
                          uuid2p1,
                          values)

        self.assertRaises(exception.InstanceExists,
                          db.instance_update,
                          otherprojectcontext,
                          uuid1p2,
                          values)

        # But we should definitely be able to update our name if we aren't
        #  really changing it.
        case_only_values = {'hostname': 'fake_NAME'}
        db.instance_update(self.context, uuid1p1, case_only_values)

        # With scope 'project' a duplicate in the project should fail:
        self.flags(osapi_compute_unique_server_name_scope='project')
        self.assertRaises(exception.InstanceExists,
                          db.instance_update,
                          self.context,
                          uuid2p1,
                          values)

        # With scope 'project' a duplicate in a different project should work:
        self.flags(osapi_compute_unique_server_name_scope='project')
        db.instance_update(otherprojectcontext, uuid1p2, values)

    def test_instance_update_with_and_get_original(self):
        ctxt = context.get_admin_context()

        # Create an instance with some metadata
        values = {'vm_state': 'building'}
        instance = db.instance_create(ctxt, values)

        (old_ref, new_ref) = db.instance_update_and_get_original(ctxt,
                instance['uuid'], {'vm_state': 'needscoffee'})
        self.assertEquals("building", old_ref["vm_state"])
        self.assertEquals("needscoffee", new_ref["vm_state"])

    def test_instance_update_with_extra_specs(self):
        """Ensure _extra_specs are returned from _instance_update"""
        ctxt = context.get_admin_context()

        # create a flavor
        inst_type_dict = dict(
                    name="test_flavor",
                    memory_mb=1,
                    vcpus=1,
                    root_gb=1,
                    ephemeral_gb=1,
                    flavorid=105)
        inst_type_ref = db.instance_type_create(ctxt, inst_type_dict)

        # add some extra spec to our flavor
        spec = {'test_spec': 'foo'}
        db.instance_type_extra_specs_update_or_create(
                    ctxt,
                    inst_type_ref['flavorid'],
                    spec)

        # create instance, just populates db, doesn't pull extra_spec
        instance = db.instance_create(
                    ctxt,
                    {'instance_type_id': inst_type_ref['id']})
        self.assertNotIn('extra_specs', instance)

        # update instance, used when starting instance to set state, etc
        (old_ref, new_ref) = db.instance_update_and_get_original(
                    ctxt,
                    instance['uuid'],
                    {})
        self.assertEquals(spec, old_ref['extra_specs'])
        self.assertEquals(spec, new_ref['extra_specs'])

    def test_instance_fault_create(self):
        """Ensure we can create an instance fault"""
        ctxt = context.get_admin_context()
        uuid = str(stdlib_uuid.uuid4())

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

    def test_dns_registration(self):
        domain1 = 'test.domain.one'
        domain2 = 'test.domain.two'
        testzone = 'testzone'
        ctxt = context.get_admin_context()

        db.dnsdomain_register_for_zone(ctxt, domain1, testzone)
        domain_ref = db.dnsdomain_get(ctxt, domain1)
        zone = domain_ref['availability_zone']
        scope = domain_ref['scope']
        self.assertEqual(scope, 'private')
        self.assertEqual(zone, testzone)

        db.dnsdomain_register_for_project(ctxt, domain2,
                                           self.project_id)
        domain_ref = db.dnsdomain_get(ctxt, domain2)
        project = domain_ref['project_id']
        scope = domain_ref['scope']
        self.assertEqual(project, self.project_id)
        self.assertEqual(scope, 'public')

        expected = [domain1, domain2]
        domains = db.dnsdomain_list(ctxt)
        self.assertEqual(expected, domains)

        db.dnsdomain_unregister(ctxt, domain1)
        db.dnsdomain_unregister(ctxt, domain2)

    def test_network_get_associated_fixed_ips(self):
        ctxt = context.get_admin_context()
        values = {'host': 'foo', 'hostname': 'myname'}
        instance = db.instance_create(ctxt, values)
        values = {'address': 'bar', 'instance_uuid': instance['uuid']}
        vif = db.virtual_interface_create(ctxt, values)
        values = {'address': 'baz',
                  'network_id': 1,
                  'allocated': True,
                  'instance_uuid': instance['uuid'],
                  'virtual_interface_id': vif['id']}
        fixed_address = db.fixed_ip_create(ctxt, values)
        data = db.network_get_associated_fixed_ips(ctxt, 1)
        self.assertEqual(len(data), 1)
        record = data[0]
        self.assertEqual(record['address'], fixed_address)
        self.assertEqual(record['instance_uuid'], instance['uuid'])
        self.assertEqual(record['network_id'], 1)
        self.assertEqual(record['instance_created'], instance['created_at'])
        self.assertEqual(record['instance_updated'], instance['updated_at'])
        self.assertEqual(record['instance_hostname'], instance['hostname'])
        self.assertEqual(record['vif_id'], vif['id'])
        self.assertEqual(record['vif_address'], vif['address'])
        data = db.network_get_associated_fixed_ips(ctxt, 1, 'nothing')
        self.assertEqual(len(data), 0)

    def test_network_get_all_by_host(self):
        ctxt = context.get_admin_context()
        data = db.network_get_all_by_host(ctxt, 'foo')
        self.assertEqual(len(data), 0)
        # dummy network
        net = db.network_create_safe(ctxt, {})
        # network with host set
        net = db.network_create_safe(ctxt, {'host': 'foo'})
        data = db.network_get_all_by_host(ctxt, 'foo')
        self.assertEqual(len(data), 1)
        # network with fixed ip with host set
        net = db.network_create_safe(ctxt, {})
        values = {'host': 'foo', 'network_id': net['id']}
        fixed_address = db.fixed_ip_create(ctxt, values)
        data = db.network_get_all_by_host(ctxt, 'foo')
        self.assertEqual(len(data), 2)
        # network with instance with host set
        net = db.network_create_safe(ctxt, {})
        instance = db.instance_create(ctxt, {'host': 'foo'})
        values = {'instance_uuid': instance['uuid']}
        vif = db.virtual_interface_create(ctxt, values)
        values = {'network_id': net['id'],
                  'virtual_interface_id': vif['id']}
        fixed_address = db.fixed_ip_create(ctxt, values)
        data = db.network_get_all_by_host(ctxt, 'foo')
        self.assertEqual(len(data), 3)

    def _timeout_test(self, ctxt, timeout, multi_host):
        values = {'host': 'foo'}
        instance = db.instance_create(ctxt, values)
        values = {'multi_host': multi_host, 'host': 'bar'}
        net = db.network_create_safe(ctxt, values)
        old = time = timeout - datetime.timedelta(seconds=5)
        new = time = timeout + datetime.timedelta(seconds=5)
        # should deallocate
        values = {'allocated': False,
                  'instance_uuid': instance['uuid'],
                  'network_id': net['id'],
                  'updated_at': old}
        db.fixed_ip_create(ctxt, values)
        # still allocated
        values = {'allocated': True,
                  'instance_uuid': instance['uuid'],
                  'network_id': net['id'],
                  'updated_at': old}
        db.fixed_ip_create(ctxt, values)
        # wrong network
        values = {'allocated': False,
                  'instance_uuid': instance['uuid'],
                  'network_id': None,
                  'updated_at': old}
        db.fixed_ip_create(ctxt, values)
        # too new
        values = {'allocated': False,
                  'instance_uuid': instance['uuid'],
                  'network_id': None,
                  'updated_at': new}
        db.fixed_ip_create(ctxt, values)

    def test_fixed_ip_disassociate_all_by_timeout_single_host(self):
        now = timeutils.utcnow()
        ctxt = context.get_admin_context()
        self._timeout_test(ctxt, now, False)
        result = db.fixed_ip_disassociate_all_by_timeout(ctxt, 'foo', now)
        self.assertEqual(result, 0)
        result = db.fixed_ip_disassociate_all_by_timeout(ctxt, 'bar', now)
        self.assertEqual(result, 1)

    def test_fixed_ip_disassociate_all_by_timeout_multi_host(self):
        now = timeutils.utcnow()
        ctxt = context.get_admin_context()
        self._timeout_test(ctxt, now, True)
        result = db.fixed_ip_disassociate_all_by_timeout(ctxt, 'foo', now)
        self.assertEqual(result, 1)
        result = db.fixed_ip_disassociate_all_by_timeout(ctxt, 'bar', now)
        self.assertEqual(result, 0)

    def test_get_vol_mapping_non_admin(self):
        ref = db.ec2_volume_create(self.context, 'fake-uuid')
        ec2_id = db.get_ec2_volume_id_by_uuid(self.context, 'fake-uuid')
        self.assertEqual(ref['id'], ec2_id)

    def test_get_snap_mapping_non_admin(self):
        ref = db.ec2_snapshot_create(self.context, 'fake-uuid')
        ec2_id = db.get_ec2_snapshot_id_by_uuid(self.context, 'fake-uuid')
        self.assertEqual(ref['id'], ec2_id)

    def test_bw_usage_calls(self):
        ctxt = context.get_admin_context()
        now = timeutils.utcnow()
        timeutils.set_time_override(now)
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

        def _compare(bw_usage, expected):
            for key, value in expected.items():
                self.assertEqual(bw_usage[key], value)

        bw_usages = db.bw_usage_get_by_uuids(ctxt,
                ['fake_uuid1', 'fake_uuid2'], start_period)
        # No matches
        self.assertEqual(len(bw_usages), 0)

        # Add 3 entries
        db.bw_usage_update(ctxt, 'fake_uuid1',
                'fake_mac1', start_period,
                100, 200, 12345, 67890)
        db.bw_usage_update(ctxt, 'fake_uuid2',
                'fake_mac2', start_period,
                100, 200, 42, 42)
        # Test explicit refreshed time
        db.bw_usage_update(ctxt, 'fake_uuid3',
                'fake_mac3', start_period,
                400, 500, 32345, 87890,
                last_refreshed=uuid3_refreshed)
        # Update 2nd entry
        db.bw_usage_update(ctxt, 'fake_uuid2',
                'fake_mac2', start_period,
                200, 300, 22345, 77890)

        bw_usages = db.bw_usage_get_by_uuids(ctxt,
                ['fake_uuid1', 'fake_uuid2', 'fake_uuid3'], start_period)
        self.assertEqual(len(bw_usages), 3)
        _compare(bw_usages[0], expected_bw_usages[0])
        _compare(bw_usages[1], expected_bw_usages[1])
        _compare(bw_usages[2], expected_bw_usages[2])
        timeutils.clear_time_override()


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
        db.aggregate_host_add(context, result['id'], host)
    return result


class AggregateDBApiTestCase(test.TestCase):
    def setUp(self):
        super(AggregateDBApiTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def test_aggregate_create(self):
        """Ensure aggregate can be created with no metadata."""
        result = _create_aggregate(metadata=None)
        self.assertEquals(result['name'], 'fake_aggregate')

    def test_aggregate_create_avoid_name_conflict(self):
        """Test we can avoid conflict on deleted aggregates."""
        r1 = _create_aggregate(metadata=None)
        db.aggregate_delete(context.get_admin_context(), r1['id'])
        values = {'name': r1['name'], 'availability_zone': 'new_zone'}
        r2 = _create_aggregate(values=values)
        self.assertEqual(r2['name'], values['name'])
        self.assertEqual(r2['availability_zone'], values['availability_zone'])

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
        self.assertThat(expected_metadata,
                        matchers.DictMatches(_get_fake_aggr_metadata()))

    def test_aggregate_create_delete_create_with_metadata(self):
        """Ensure aggregate metadata is deleted bug 1052479."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        expected_metadata = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(expected_metadata,
                        matchers.DictMatches(_get_fake_aggr_metadata()))
        db.aggregate_delete(ctxt, result['id'])
        result = _create_aggregate(metadata=None)
        expected_metadata = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertEqual(expected_metadata, {})

    def test_aggregate_create_low_privi_context(self):
        """Ensure right context is applied when creating aggregate."""
        self.assertRaises(exception.AdminRequired,
                          db.aggregate_create,
                          self.context, _get_fake_aggr_values())

    def test_aggregate_get(self):
        """Ensure we can get aggregate with all its relations."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt)
        expected = db.aggregate_get(ctxt, result['id'])
        self.assertEqual(_get_fake_aggr_hosts(), expected['hosts'])
        self.assertEqual(_get_fake_aggr_metadata(), expected['metadetails'])

    def test_aggregate_get_by_host(self):
        """Ensure we can get aggregates by host."""
        ctxt = context.get_admin_context()
        values = {'name': 'fake_aggregate2',
            'availability_zone': 'fake_avail_zone', }
        a1 = _create_aggregate_with_hosts(context=ctxt)
        a2 = _create_aggregate_with_hosts(context=ctxt, values=values)
        r1 = db.aggregate_get_by_host(ctxt, 'foo.openstack.org')
        self.assertEqual([a1['id'], a2['id']], [x['id'] for x in r1])

    def test_aggregate_get_by_host_with_key(self):
        """Ensure we can get aggregates by host."""
        ctxt = context.get_admin_context()
        values = {'name': 'fake_aggregate2',
            'availability_zone': 'fake_avail_zone', }
        a1 = _create_aggregate_with_hosts(context=ctxt,
                                          metadata={'goodkey': 'good'})
        a2 = _create_aggregate_with_hosts(context=ctxt, values=values)
        # filter result by key
        r1 = db.aggregate_get_by_host(ctxt, 'foo.openstack.org', key='goodkey')
        self.assertEqual([a1['id']], [x['id'] for x in r1])

    def test_aggregate_metdata_get_by_host(self):
        """Ensure we can get aggregates by host."""
        ctxt = context.get_admin_context()
        values = {'name': 'fake_aggregate2',
            'availability_zone': 'fake_avail_zone', }
        values2 = {'name': 'fake_aggregate3',
            'availability_zone': 'fake_avail_zone', }
        a1 = _create_aggregate_with_hosts(context=ctxt)
        a2 = _create_aggregate_with_hosts(context=ctxt, values=values)
        a3 = _create_aggregate_with_hosts(context=ctxt, values=values2,
                hosts=['bar.openstack.org'], metadata={'badkey': 'bad'})
        r1 = db.aggregate_metadata_get_by_host(ctxt, 'foo.openstack.org')
        self.assertEqual(r1['fake_key1'], set(['fake_value1']))
        self.assertFalse('badkey' in r1)

    def test_aggregate_metdata_get_by_host_with_key(self):
        """Ensure we can get aggregates by host."""
        ctxt = context.get_admin_context()
        values = {'name': 'fake_aggregate2',
            'availability_zone': 'fake_avail_zone', }
        values2 = {'name': 'fake_aggregate3',
            'availability_zone': 'fake_avail_zone', }
        a1 = _create_aggregate_with_hosts(context=ctxt)
        a2 = _create_aggregate_with_hosts(context=ctxt, values=values)
        a3 = _create_aggregate_with_hosts(context=ctxt, values=values2,
                hosts=['foo.openstack.org'], metadata={'good': 'value'})
        r1 = db.aggregate_metadata_get_by_host(ctxt, 'foo.openstack.org',
                                               key='good')
        self.assertEqual(r1['good'], set(['value']))
        self.assertFalse('fake_key1' in r1)
        # Delete metadata
        db.aggregate_metadata_delete(ctxt, a3['id'], 'good')
        r2 = db.aggregate_metadata_get_by_host(ctxt, 'foo.openstack.org',
                                               key='good')
        self.assertFalse('good' in r2)

    def test_aggregate_get_by_host_not_found(self):
        """Ensure AggregateHostNotFound is raised with unknown host."""
        ctxt = context.get_admin_context()
        _create_aggregate_with_hosts(context=ctxt)
        self.assertEqual([], db.aggregate_get_by_host(ctxt, 'unknown_host'))

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
        expected = db.aggregate_get_all(ctxt)
        self.assertEqual(0, len(expected))
        aggregate = db.aggregate_get(ctxt.elevated(read_deleted='yes'),
                                     result['id'])
        self.assertEqual(aggregate['deleted'], True)

    def test_aggregate_update(self):
        """Ensure an aggregate can be updated."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        new_values = _get_fake_aggr_values()
        new_values['availability_zone'] = 'different_avail_zone'
        updated = db.aggregate_update(ctxt, 1, new_values)
        self.assertNotEqual(result['availability_zone'],
                            updated['availability_zone'])

    def test_aggregate_update_with_metadata(self):
        """Ensure an aggregate can be updated with metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(_get_fake_aggr_metadata(),
                        matchers.DictMatches(expected))

    def test_aggregate_update_with_existing_metadata(self):
        """Ensure an aggregate can be updated with existing metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        values['metadata']['fake_key1'] = 'foo'
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(values['metadata'], matchers.DictMatches(expected))

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
            db.aggregate_delete(ctxt, aggregates[c - 1]['id'])
        results = db.aggregate_get_all(ctxt)
        self.assertEqual(len(results), add_counter - remove_counter)

    def test_aggregate_metadata_add(self):
        """Ensure we can add metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result['id'], metadata)
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_update(self):
        """Ensure we can update metadata for the aggregate."""
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
        """Ensure we can delete metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result['id'], metadata)
        db.aggregate_metadata_delete(ctxt, result['id'], metadata.keys()[0])
        expected = db.aggregate_metadata_get(ctxt, result['id'])
        del metadata[metadata.keys()[0]]
        self.assertThat(metadata, matchers.DictMatches(expected))

    def test_aggregate_metadata_delete_raise_not_found(self):
        """Ensure AggregateMetadataNotFound is raised when deleting."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateMetadataNotFound,
                          db.aggregate_metadata_delete,
                          ctxt, result['id'], 'foo_key')

    def test_aggregate_host_add(self):
        """Ensure we can add host to the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        expected = db.aggregate_host_get_all(ctxt, result['id'])
        self.assertEqual(_get_fake_aggr_hosts(), expected)

    def test_aggregate_host_add_deleted(self):
        """Ensure we can add a host that was previously deleted."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        host = _get_fake_aggr_hosts()[0]
        db.aggregate_host_delete(ctxt, result['id'], host)
        db.aggregate_host_add(ctxt, result['id'], host)
        expected = db.aggregate_host_get_all(ctxt, result['id'])
        self.assertEqual(len(expected), 1)

    def test_aggregate_host_add_duplicate_works(self):
        """Ensure we can add host to distinct aggregates."""
        ctxt = context.get_admin_context()
        r1 = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        r2 = _create_aggregate_with_hosts(ctxt,
                          values={'name': 'fake_aggregate2',
                                  'availability_zone': 'fake_avail_zone2', },
                          metadata=None)
        h1 = db.aggregate_host_get_all(ctxt, r1['id'])
        h2 = db.aggregate_host_get_all(ctxt, r2['id'])
        self.assertEqual(h1, h2)

    def test_aggregate_host_add_duplicate_raise_exist_exc(self):
        """Ensure we cannot add host to the same aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        self.assertRaises(exception.AggregateHostExists,
                          db.aggregate_host_add,
                          ctxt, result['id'], _get_fake_aggr_hosts()[0])

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
        db.aggregate_host_delete(ctxt, result['id'],
                                 _get_fake_aggr_hosts()[0])
        expected = db.aggregate_host_get_all(ctxt, result['id'])
        self.assertEqual(0, len(expected))

    def test_aggregate_host_delete_raise_not_found(self):
        """Ensure AggregateHostNotFound is raised when deleting a host."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateHostNotFound,
                          db.aggregate_host_delete,
                          ctxt, result['id'], _get_fake_aggr_hosts()[0])


class CapacityTestCase(test.TestCase):
    def setUp(self):
        super(CapacityTestCase, self).setUp()

        self.ctxt = context.get_admin_context()

        service_dict = dict(host='host1', binary='binary1',
                            topic='compute', report_count=1,
                            disabled=False)
        self.service = db.service_create(self.ctxt, service_dict)

        self.compute_node_dict = dict(vcpus=2, memory_mb=1024, local_gb=2048,
                                 vcpus_used=0, memory_mb_used=0,
                                 local_gb_used=0, free_ram_mb=1024,
                                 free_disk_gb=2048, hypervisor_type="xen",
                                 hypervisor_version=1, cpu_info="",
                                 running_vms=0, current_workload=0,
                                 service_id=self.service['id'])
        # add some random stats
        stats = dict(num_instances=3, num_proj_12345=2,
                     num_proj_23456=2, num_vm_building=3)
        self.compute_node_dict['stats'] = stats

        self.flags(reserved_host_memory_mb=0)
        self.flags(reserved_host_disk_mb=0)

    def _create_helper(self, host):
        self.compute_node_dict['host'] = host
        return db.compute_node_create(self.ctxt, self.compute_node_dict)

    def _stats_as_dict(self, stats):
        d = {}
        for s in stats:
            key = s['key']
            d[key] = s['value']
        return d

    def test_compute_node_create(self):
        item = self._create_helper('host1')
        self.assertEquals(item['free_ram_mb'], 1024)
        self.assertEquals(item['free_disk_gb'], 2048)
        self.assertEquals(item['running_vms'], 0)
        self.assertEquals(item['current_workload'], 0)

        stats = self._stats_as_dict(item['stats'])
        self.assertEqual(3, stats['num_instances'])
        self.assertEqual(2, stats['num_proj_12345'])
        self.assertEqual(3, stats['num_vm_building'])

    def test_compute_node_get_all(self):
        item = self._create_helper('host1')
        nodes = db.compute_node_get_all(self.ctxt)
        self.assertEqual(1, len(nodes))

        node = nodes[0]
        self.assertEqual(2, node['vcpus'])

        stats = self._stats_as_dict(node['stats'])
        self.assertEqual(3, int(stats['num_instances']))
        self.assertEqual(2, int(stats['num_proj_12345']))
        self.assertEqual(3, int(stats['num_vm_building']))

    def test_compute_node_update(self):
        item = self._create_helper('host1')

        compute_node_id = item['id']
        stats = self._stats_as_dict(item['stats'])

        # change some values:
        stats['num_instances'] = 8
        stats['num_tribbles'] = 1
        values = {
            'vcpus': 4,
            'stats': stats,
        }
        item = db.compute_node_update(self.ctxt, compute_node_id, values)
        stats = self._stats_as_dict(item['stats'])

        self.assertEqual(4, item['vcpus'])
        self.assertEqual(8, int(stats['num_instances']))
        self.assertEqual(2, int(stats['num_proj_12345']))
        self.assertEqual(1, int(stats['num_tribbles']))

    def test_compute_node_stat_prune(self):
        item = self._create_helper('host1')
        for stat in item['stats']:
            if stat['key'] == 'num_instances':
                num_instance_stat = stat
                break

        values = {
            'stats': dict(num_instances=1)
        }
        db.compute_node_update(self.ctxt, item['id'], values, prune_stats=True)
        item = db.compute_node_get_all(self.ctxt)[0]
        self.assertEqual(1, len(item['stats']))

        stat = item['stats'][0]
        self.assertEqual(num_instance_stat['id'], stat['id'])
        self.assertEqual(num_instance_stat['key'], stat['key'])
        self.assertEqual(1, int(stat['value']))


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
                source_node='a', dest_compute='host2', dest_node='b'):

        values = {'host': source_compute}
        instance = db.instance_create(self.ctxt, values)

        values = {'status': status, 'source_compute': source_compute,
                  'source_node': source_node, 'dest_compute': dest_compute,
                  'dest_node': dest_node, 'instance_uuid': instance['uuid']}
        db.migration_create(self.ctxt, values)

    def _assert_in_progress(self, migrations):
        for migration in migrations:
            self.assertNotEqual('confirmed', migration['status'])
            self.assertNotEqual('reverted', migration['status'])

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


class TestIpAllocation(test.TestCase):

    def setUp(self):
        super(TestIpAllocation, self).setUp()
        self.ctxt = context.get_admin_context()
        self.instance = db.instance_create(self.ctxt, {})
        self.network = db.network_create_safe(self.ctxt, {})

    def create_fixed_ip(self, **params):
        default_params = {'address': '192.168.0.1'}
        default_params.update(params)
        return db.fixed_ip_create(self.ctxt, default_params)

    def test_fixed_ip_associate_fails_if_ip_not_in_network(self):
        self.assertRaises(exception.FixedIpNotFoundForNetwork,
                          db.fixed_ip_associate,
                          self.ctxt, None, self.instance['uuid'])

    def test_fixed_ip_associate_fails_if_ip_in_use(self):
        address = self.create_fixed_ip(instance_uuid=self.instance['uuid'])
        self.assertRaises(exception.FixedIpAlreadyInUse,
                          db.fixed_ip_associate,
                          self.ctxt, address, self.instance['uuid'])

    def test_fixed_ip_associate_succeeds(self):
        address = self.create_fixed_ip(network_id=self.network['id'])
        db.fixed_ip_associate(self.ctxt, address, self.instance['uuid'],
                              network_id=self.network['id'])
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], self.instance['uuid'])

    def test_fixed_ip_associate_succeeds_and_sets_network(self):
        address = self.create_fixed_ip()
        db.fixed_ip_associate(self.ctxt, address, self.instance['uuid'],
                              network_id=self.network['id'])
        fixed_ip = db.fixed_ip_get_by_address(self.ctxt, address)
        self.assertEqual(fixed_ip['instance_uuid'], self.instance['uuid'])
        self.assertEqual(fixed_ip['network_id'], self.network['id'])


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

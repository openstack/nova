#    Copyright 2014 Red Hat, Inc.
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
import netaddr
from oslo_versionedobjects import base as ovo_base

from nova import exception
from nova import objects
from nova.objects import floating_ip
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_fixed_ip
from nova.tests.unit.objects import test_network
from nova.tests.unit.objects import test_objects

fake_floating_ip = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'address': '172.17.0.1',
    'fixed_ip_id': None,
    'project_id': None,
    'host': None,
    'auto_assigned': False,
    'pool': None,
    'interface': None,
    'fixed_ip': None,
}


class _TestFloatingIPObject(object):
    def _compare(self, obj, db_obj):
        for field in obj.fields:
            if field in floating_ip.FLOATING_IP_OPTIONAL_ATTRS:
                if obj.obj_attr_is_set(field):
                    obj_val = obj[field].id
                    db_val = db_obj[field]['id']
                else:
                    continue
            else:
                obj_val = obj[field]
                db_val = db_obj[field]
            if isinstance(obj_val, netaddr.IPAddress):
                obj_val = str(obj_val)
            self.assertEqual(db_val, obj_val)

    @mock.patch('nova.db.api.floating_ip_get')
    def test_get_by_id(self, get):
        db_floatingip = dict(fake_floating_ip,
                             fixed_ip=test_fixed_ip.fake_fixed_ip)
        get.return_value = db_floatingip
        floatingip = floating_ip.FloatingIP.get_by_id(self.context, 123)
        get.assert_called_once_with(self.context, 123)
        self._compare(floatingip, db_floatingip)

    @mock.patch('nova.db.api.floating_ip_get_by_address')
    def test_get_by_address(self, get):
        get.return_value = fake_floating_ip
        floatingip = floating_ip.FloatingIP.get_by_address(self.context,
                                                           '1.2.3.4')
        get.assert_called_once_with(self.context, '1.2.3.4')
        self._compare(floatingip, fake_floating_ip)

    @mock.patch('nova.db.api.floating_ip_get_pools')
    def test_get_pool_names(self, get):
        get.return_value = [{'name': 'a'}, {'name': 'b'}]
        self.assertEqual(['a', 'b'],
                         floating_ip.FloatingIP.get_pool_names(self.context))

    @mock.patch('nova.db.api.floating_ip_allocate_address')
    def test_allocate_address(self, allocate):
        allocate.return_value = '1.2.3.4'
        self.assertEqual('1.2.3.4',
                         floating_ip.FloatingIP.allocate_address(self.context,
                                                                 'project',
                                                                 'pool'))
        allocate.assert_called_with(self.context, 'project', 'pool',
                                    auto_assigned=False)

    @mock.patch('nova.db.api.floating_ip_fixed_ip_associate')
    def test_associate(self, associate):
        db_fixed = dict(test_fixed_ip.fake_fixed_ip,
                        network=test_network.fake_network)
        associate.return_value = db_fixed
        floatingip = floating_ip.FloatingIP.associate(self.context,
                                                      '172.17.0.1',
                                                      '192.168.1.1',
                                                      'host')
        associate.assert_called_with(self.context, '172.17.0.1',
                                     '192.168.1.1', 'host')
        self.assertEqual(db_fixed['id'], floatingip.fixed_ip.id)
        self.assertEqual('172.17.0.1', str(floatingip.address))
        self.assertEqual('host', floatingip.host)

    @mock.patch('nova.db.api.floating_ip_deallocate')
    def test_deallocate(self, deallocate):
        floating_ip.FloatingIP.deallocate(self.context, '1.2.3.4')
        deallocate.assert_called_with(self.context, '1.2.3.4')

    @mock.patch('nova.db.api.floating_ip_destroy')
    def test_destroy(self, destroy):
        floating_ip.FloatingIP.destroy(self.context, '1.2.3.4')
        destroy.assert_called_with(self.context, '1.2.3.4')

    @mock.patch('nova.db.api.floating_ip_disassociate')
    def test_disassociate(self, disassociate):
        db_fixed = dict(test_fixed_ip.fake_fixed_ip,
                        network=test_network.fake_network)
        disassociate.return_value = db_fixed
        floatingip = floating_ip.FloatingIP.disassociate(self.context,
                                                         '1.2.3.4')
        disassociate.assert_called_with(self.context, '1.2.3.4')
        self.assertEqual(db_fixed['id'], floatingip.fixed_ip.id)
        self.assertEqual('1.2.3.4', str(floatingip.address))

    @mock.patch('nova.db.api.floating_ip_update')
    def test_save(self, update):
        update.return_value = fake_floating_ip
        floatingip = floating_ip.FloatingIP(context=self.context,
                                            id=123, address='1.2.3.4',
                                            host='foo')
        floatingip.obj_reset_changes(['address', 'id'])
        floatingip.save()
        self.assertEqual(set(), floatingip.obj_what_changed())
        update.assert_called_with(self.context, '1.2.3.4',
                                  {'host': 'foo'})

    def test_save_errors(self):
        floatingip = floating_ip.FloatingIP(context=self.context,
                                            id=123, host='foo')
        floatingip.obj_reset_changes()
        floating_ip.address = '1.2.3.4'
        self.assertRaises(exception.ObjectActionError, floatingip.save)

        floatingip.obj_reset_changes()
        floatingip.fixed_ip_id = 1
        self.assertRaises(exception.ObjectActionError, floatingip.save)

    @mock.patch('nova.db.api.floating_ip_update')
    def test_save_no_fixedip(self, update):
        update.return_value = fake_floating_ip
        floatingip = floating_ip.FloatingIP(context=self.context,
                                            id=123)
        floatingip.fixed_ip = objects.FixedIP(context=self.context,
                                              id=456)
        self.assertNotIn('fixed_ip', update.calls[1])

    @mock.patch('nova.db.api.floating_ip_get_all')
    def test_get_all(self, get):
        get.return_value = [fake_floating_ip]
        floatingips = floating_ip.FloatingIPList.get_all(self.context)
        self.assertEqual(1, len(floatingips))
        self._compare(floatingips[0], fake_floating_ip)
        get.assert_called_with(self.context)

    @mock.patch('nova.db.api.floating_ip_get_all_by_host')
    def test_get_by_host(self, get):
        get.return_value = [fake_floating_ip]
        floatingips = floating_ip.FloatingIPList.get_by_host(self.context,
                                                             'host')
        self.assertEqual(1, len(floatingips))
        self._compare(floatingips[0], fake_floating_ip)
        get.assert_called_with(self.context, 'host')

    @mock.patch('nova.db.api.floating_ip_get_all_by_project')
    def test_get_by_project(self, get):
        get.return_value = [fake_floating_ip]
        floatingips = floating_ip.FloatingIPList.get_by_project(self.context,
                                                                'project')
        self.assertEqual(1, len(floatingips))
        self._compare(floatingips[0], fake_floating_ip)
        get.assert_called_with(self.context, 'project')

    @mock.patch('nova.db.api.floating_ip_get_by_fixed_address')
    def test_get_by_fixed_address(self, get):
        get.return_value = [fake_floating_ip]
        floatingips = floating_ip.FloatingIPList.get_by_fixed_address(
            self.context, '1.2.3.4')
        self.assertEqual(1, len(floatingips))
        self._compare(floatingips[0], fake_floating_ip)
        get.assert_called_with(self.context, '1.2.3.4')

    @mock.patch('nova.db.api.floating_ip_get_by_fixed_ip_id')
    def test_get_by_fixed_ip_id(self, get):
        get.return_value = [fake_floating_ip]
        floatingips = floating_ip.FloatingIPList.get_by_fixed_ip_id(
            self.context, 123)
        self.assertEqual(1, len(floatingips))
        self._compare(floatingips[0], fake_floating_ip)
        get.assert_called_with(self.context, 123)

    @mock.patch('nova.db.api.instance_floating_address_get_all')
    def test_get_addresses_by_instance(self, get_all):
        expected = ['1.2.3.4', '4.5.6.7']
        get_all.return_value = list(expected)
        ips = floating_ip.FloatingIP.get_addresses_by_instance(
            self.context, {'uuid': '1234'})
        self.assertEqual(expected, ips)
        get_all.assert_called_once_with(self.context, '1234')

    def test_make_ip_info(self):
        result = objects.FloatingIPList.make_ip_info('1.2.3.4', 'pool', 'eth0')
        self.assertEqual({'address': '1.2.3.4', 'pool': 'pool',
                          'interface': 'eth0'},
                         result)

    @mock.patch('nova.db.api.floating_ip_bulk_create')
    def test_bulk_create(self, create_mock):
        def fake_create(ctxt, ip_info, want_result=False):
            return [{'id': 1, 'address': ip['address'], 'fixed_ip_id': 1,
                     'project_id': fakes.FAKE_PROJECT_ID, 'host': 'host',
                     'auto_assigned': False, 'pool': ip['pool'],
                     'interface': ip['interface'], 'fixed_ip': None,
                     'created_at': None, 'updated_at': None,
                     'deleted_at': None, 'deleted': False}
                    for ip in ip_info]

        create_mock.side_effect = fake_create
        ips = [objects.FloatingIPList.make_ip_info('1.1.1.1', 'pool', 'eth0'),
               objects.FloatingIPList.make_ip_info('1.1.1.2', 'loop', 'eth1')]
        result = objects.FloatingIPList.create(None, ips)
        self.assertIsNone(result)
        result = objects.FloatingIPList.create(None, ips, want_result=True)
        self.assertEqual('1.1.1.1', str(result[0].address))
        self.assertEqual('1.1.1.2', str(result[1].address))

    @mock.patch('nova.db.api.floating_ip_bulk_destroy')
    def test_bulk_destroy(self, destroy_mock):
        ips = [{'address': '1.2.3.4'}, {'address': '4.5.6.7'}]
        objects.FloatingIPList.destroy(None, ips)
        destroy_mock.assert_called_once_with(None, ips)

    def test_backport_fixedip_1_1(self):
        floating = objects.FloatingIP()
        fixed = objects.FixedIP()
        floating.fixed_ip = fixed
        versions = ovo_base.obj_tree_get_versions('FloatingIP')
        versions['FixedIP'] = '1.1'
        primitive = floating.obj_to_primitive(target_version='1.1',
                                              version_manifest=versions)
        self.assertEqual('1.1',
            primitive['nova_object.data']['fixed_ip']['nova_object.version'])

    def test_get_count_by_project(self):
        ips = [objects.FloatingIPList.make_ip_info('1.1.1.1', 'pool', 'eth0')]
        objects.FloatingIPList.create(self.context, ips)
        floating_ip.FloatingIP.allocate_address(self.context,
                                                self.context.project_id,
                                                'pool')
        self.assertEqual(1, floating_ip.FloatingIPList.get_count_by_project(
            self.context, self.context.project_id))


class TestFloatingIPObject(test_objects._LocalTest,
                           _TestFloatingIPObject):
    pass


class TestRemoteFloatingIPObject(test_objects._RemoteTest,
                                 _TestFloatingIPObject):
    pass


class TestNeutronFloatingIPObject(test.NoDBTestCase):
    def test_create_with_uuid_id(self):
        uuid = 'fc9b4956-fd97-11e5-86aa-5e5517507c66'
        fip = objects.floating_ip.NeutronFloatingIP(id=uuid)

        self.assertEqual(uuid, fip.id)

    def test_create_with_uuid_fixed_id(self):
        uuid = 'fc9b4c3a-fd97-11e5-86aa-5e5517507c66'
        fip = objects.floating_ip.NeutronFloatingIP(fixed_ip_id=uuid)

        self.assertEqual(uuid, fip.fixed_ip_id)

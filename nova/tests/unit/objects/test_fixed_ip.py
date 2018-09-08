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

import datetime

import iso8601
import mock
import netaddr
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_versionedobjects import base as ovo_base

from nova import exception
from nova.objects import fixed_ip
from nova.objects import instance as instance_obj
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_network
from nova.tests.unit.objects import test_objects
from nova import utils

fake_fixed_ip = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'address': '192.168.1.100',
    'network_id': None,
    'virtual_interface_id': None,
    'instance_uuid': None,
    'allocated': False,
    'leased': False,
    'reserved': False,
    'host': None,
    'network': None,
    'virtual_interface': None,
    'floating_ips': [],
    }


class _TestFixedIPObject(object):
    def _compare(self, obj, db_obj):
        for field in obj.fields:
            if field in ('default_route', 'floating_ips'):
                continue
            if field in fixed_ip.FIXED_IP_OPTIONAL_ATTRS:
                if obj.obj_attr_is_set(field) and db_obj[field] is not None:
                    obj_val = obj[field].uuid
                    db_val = db_obj[field]['uuid']
                else:
                    continue
            else:
                obj_val = obj[field]
                db_val = db_obj[field]
            if isinstance(obj_val, netaddr.IPAddress):
                obj_val = str(obj_val)
            self.assertEqual(db_val, obj_val)

    @mock.patch('nova.db.api.fixed_ip_get')
    def test_get_by_id(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_id(self.context, 123)
        get.assert_called_once_with(self.context, 123, get_network=False)
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_get')
    @mock.patch('nova.db.api.network_get')
    def test_get_by_id_with_extras(self, network_get, fixed_get):
        db_fixed = dict(fake_fixed_ip,
                        network=test_network.fake_network)
        fixed_get.return_value = db_fixed
        fixedip = fixed_ip.FixedIP.get_by_id(self.context, 123,
                                             expected_attrs=['network'])
        fixed_get.assert_called_once_with(self.context, 123, get_network=True)
        self._compare(fixedip, db_fixed)
        self.assertEqual(db_fixed['network']['uuid'], fixedip.network.uuid)
        self.assertFalse(network_get.called)

    @mock.patch('nova.db.api.fixed_ip_get_by_address')
    def test_get_by_address(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_address(self.context, '1.2.3.4')
        get.assert_called_once_with(self.context, '1.2.3.4',
                                    columns_to_join=[])
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_get_by_address')
    @mock.patch('nova.db.api.network_get')
    @mock.patch('nova.db.api.instance_get')
    def test_get_by_address_with_extras(self, instance_get, network_get,
                                        fixed_get):
        db_fixed = dict(fake_fixed_ip, network=test_network.fake_network,
                        instance=fake_instance.fake_db_instance())
        fixed_get.return_value = db_fixed
        fixedip = fixed_ip.FixedIP.get_by_address(self.context, '1.2.3.4',
                                                  expected_attrs=['network',
                                                                  'instance'])
        fixed_get.assert_called_once_with(self.context, '1.2.3.4',
                                          columns_to_join=['network',
                                                           'instance'])
        self._compare(fixedip, db_fixed)
        self.assertEqual(db_fixed['network']['uuid'], fixedip.network.uuid)
        self.assertEqual(db_fixed['instance']['uuid'], fixedip.instance.uuid)
        self.assertFalse(network_get.called)
        self.assertFalse(instance_get.called)

    @mock.patch('nova.db.api.fixed_ip_get_by_address')
    @mock.patch('nova.db.api.network_get')
    @mock.patch('nova.db.api.instance_get')
    def test_get_by_address_with_extras_deleted_instance(self, instance_get,
                                                         network_get,
                                                         fixed_get):
        db_fixed = dict(fake_fixed_ip, network=test_network.fake_network,
                        instance=None)
        fixed_get.return_value = db_fixed
        fixedip = fixed_ip.FixedIP.get_by_address(self.context, '1.2.3.4',
                                                  expected_attrs=['network',
                                                                  'instance'])
        fixed_get.assert_called_once_with(self.context, '1.2.3.4',
                                          columns_to_join=['network',
                                                           'instance'])
        self._compare(fixedip, db_fixed)
        self.assertEqual(db_fixed['network']['uuid'], fixedip.network.uuid)
        self.assertIsNone(fixedip.instance)
        self.assertFalse(network_get.called)
        self.assertFalse(instance_get.called)

    @mock.patch('nova.db.api.fixed_ip_get_by_floating_address')
    def test_get_by_floating_address(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_floating_address(self.context,
                                                           '1.2.3.4')
        get.assert_called_once_with(self.context, '1.2.3.4')
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_get_by_floating_address')
    def test_get_by_floating_address_none(self, get):
        get.return_value = None
        fixedip = fixed_ip.FixedIP.get_by_floating_address(self.context,
                                                           '1.2.3.4')
        get.assert_called_once_with(self.context, '1.2.3.4')
        self.assertIsNone(fixedip)

    @mock.patch('nova.db.api.fixed_ip_get_by_network_host')
    def test_get_by_network_and_host(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_network_and_host(self.context,
                                                           123, 'host')
        get.assert_called_once_with(self.context, 123, 'host')
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_associate')
    def test_associate(self, associate):
        associate.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.associate(self.context, '1.2.3.4',
                                             uuids.instance)
        associate.assert_called_with(self.context, '1.2.3.4', uuids.instance,
                                     network_id=None, reserved=False,
                                     virtual_interface_id=None)
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_associate')
    def test_associate_with_vif(self, associate):
        associate.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.associate(self.context, '1.2.3.4',
                                             uuids.instance,
                                             vif_id=0)
        associate.assert_called_with(self.context, '1.2.3.4',
                                     uuids.instance,
                                     network_id=None, reserved=False,
                                     virtual_interface_id=0)
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_associate_pool')
    def test_associate_pool(self, associate):
        associate.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.associate_pool(self.context, 123,
                                                  uuids.instance, 'host')
        associate.assert_called_with(self.context, 123,
                                     instance_uuid=uuids.instance,
                                     host='host', virtual_interface_id=None)
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_associate_pool')
    def test_associate_pool_with_vif(self, associate):
        associate.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.associate_pool(self.context, 123,
                                                  uuids.instance, 'host',
                                                  vif_id=0)
        associate.assert_called_with(self.context, 123,
                                     instance_uuid=uuids.instance,
                                     host='host', virtual_interface_id=0)
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_disassociate')
    def test_disassociate_by_address(self, disassociate):
        fixed_ip.FixedIP.disassociate_by_address(self.context, '1.2.3.4')
        disassociate.assert_called_with(self.context, '1.2.3.4')

    @mock.patch('nova.db.api.fixed_ip_disassociate_all_by_timeout')
    def test_disassociate_all_by_timeout(self, disassociate):
        now = timeutils.utcnow()
        now_tz = timeutils.parse_isotime(
            utils.isotime(now)).replace(
                tzinfo=iso8601.UTC)
        disassociate.return_value = 123
        result = fixed_ip.FixedIP.disassociate_all_by_timeout(self.context,
                                                              'host', now)
        self.assertEqual(123, result)
        # NOTE(danms): be pedantic about timezone stuff
        args, kwargs = disassociate.call_args_list[0]
        self.assertEqual(now_tz, args[2])
        self.assertEqual((self.context, 'host'), args[:2])
        self.assertEqual({}, kwargs)

    @mock.patch('nova.db.api.fixed_ip_create')
    def test_create(self, create):
        create.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP(context=self.context, address='1.2.3.4')
        fixedip.create()
        create.assert_called_once_with(
            self.context, {'address': '1.2.3.4'})
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_update')
    def test_save(self, update):
        update.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP(context=self.context, address='1.2.3.4',
                                   instance_uuid=uuids.instance)
        self.assertRaises(exception.ObjectActionError, fixedip.save)
        fixedip.obj_reset_changes(['address'])
        fixedip.save()
        update.assert_called_once_with(self.context, '1.2.3.4',
                                       {'instance_uuid': uuids.instance})

    @mock.patch('nova.db.api.fixed_ip_disassociate')
    def test_disassociate(self, disassociate):
        fixedip = fixed_ip.FixedIP(context=self.context, address='1.2.3.4',
                                   instance_uuid=uuids.instance)
        fixedip.obj_reset_changes()
        fixedip.disassociate()
        disassociate.assert_called_once_with(self.context, '1.2.3.4')
        self.assertIsNone(fixedip.instance_uuid)

    @mock.patch('nova.db.api.fixed_ip_get_all')
    def test_get_all(self, get_all):
        get_all.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_all(self.context)
        self.assertEqual(1, len(fixedips))
        get_all.assert_called_once_with(self.context)
        self._compare(fixedips[0], fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_get_by_instance')
    def test_get_by_instance(self, get):
        get.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_by_instance_uuid(self.context,
                                                             uuids.instance)
        self.assertEqual(1, len(fixedips))
        get.assert_called_once_with(self.context, uuids.instance)
        self._compare(fixedips[0], fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ip_get_by_host')
    def test_get_by_host(self, get):
        get.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_by_host(self.context, 'host')
        self.assertEqual(1, len(fixedips))
        get.assert_called_once_with(self.context, 'host')
        self._compare(fixedips[0], fake_fixed_ip)

    @mock.patch('nova.db.api.fixed_ips_by_virtual_interface')
    def test_get_by_virtual_interface_id(self, get):
        get.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_by_virtual_interface_id(
            self.context, 123)
        self.assertEqual(1, len(fixedips))
        get.assert_called_once_with(self.context, 123)
        self._compare(fixedips[0], fake_fixed_ip)

    def test_floating_ips_do_not_lazy_load(self):
        fixedip = fixed_ip.FixedIP()
        self.assertRaises(NotImplementedError, lambda: fixedip.floating_ips)

    @mock.patch('nova.db.api.fixed_ip_bulk_create')
    def test_bulk_create(self, bulk):
        fixed_ips = [fixed_ip.FixedIP(address='192.168.1.1'),
                     fixed_ip.FixedIP(address='192.168.1.2')]
        fixed_ip.FixedIPList.bulk_create(self.context, fixed_ips)
        bulk.assert_called_once_with(self.context,
                                     [{'address': '192.168.1.1'},
                                      {'address': '192.168.1.2'}])

    @mock.patch('nova.db.api.network_get_associated_fixed_ips')
    def test_get_by_network(self, get):
        info = {'address': '1.2.3.4',
                'instance_uuid': uuids.instance,
                'network_id': 0,
                'vif_id': 1,
                'vif_address': 'de:ad:be:ee:f0:00',
                'instance_hostname': 'fake-host',
                'instance_updated': datetime.datetime(1955, 11, 5),
                'instance_created': datetime.datetime(1955, 11, 5),
                'allocated': True,
                'leased': True,
                'default_route': True,
                }
        get.return_value = [info]
        fixed_ips = fixed_ip.FixedIPList.get_by_network(
            self.context, {'id': 0}, host='fake-host')
        get.assert_called_once_with(self.context, 0, host='fake-host')
        self.assertEqual(1, len(fixed_ips))
        fip = fixed_ips[0]
        self.assertEqual('1.2.3.4', str(fip.address))
        self.assertEqual(uuids.instance, fip.instance_uuid)
        self.assertEqual(0, fip.network_id)
        self.assertEqual(1, fip.virtual_interface_id)
        self.assertTrue(fip.allocated)
        self.assertTrue(fip.leased)
        self.assertEqual(uuids.instance, fip.instance.uuid)
        self.assertEqual('fake-host', fip.instance.hostname)
        self.assertIsInstance(fip.instance.created_at, datetime.datetime)
        self.assertIsInstance(fip.instance.updated_at, datetime.datetime)
        self.assertEqual(1, fip.virtual_interface.id)
        self.assertEqual(info['vif_address'], fip.virtual_interface.address)

    @mock.patch('nova.db.api.network_get_associated_fixed_ips')
    def test_backport_default_route(self, mock_get):
        info = {'address': '1.2.3.4',
                'instance_uuid': uuids.instance,
                'network_id': 0,
                'vif_id': 1,
                'vif_address': 'de:ad:be:ee:f0:00',
                'instance_hostname': 'fake-host',
                'instance_updated': datetime.datetime(1955, 11, 5),
                'instance_created': datetime.datetime(1955, 11, 5),
                'allocated': True,
                'leased': True,
                'default_route': True,
                }
        mock_get.return_value = [info]
        fixed_ips = fixed_ip.FixedIPList.get_by_network(
            self.context, {'id': 0}, host='fake-host')
        primitive = fixed_ips[0].obj_to_primitive()
        self.assertIn('default_route', primitive['nova_object.data'])
        versions = ovo_base.obj_tree_get_versions('FixedIP')
        fixed_ips[0].obj_make_compatible_from_manifest(
            primitive['nova_object.data'],
            target_version='1.1',
            version_manifest=versions)
        self.assertNotIn('default_route', primitive['nova_object.data'])

    def test_get_count_by_project(self):
        instance = instance_obj.Instance(context=self.context,
                                         uuid=uuids.instance,
                                         project_id=self.context.project_id)
        instance.create()
        ip = fixed_ip.FixedIP(context=self.context,
                              address='192.168.1.1',
                              instance_uuid=instance.uuid)
        ip.create()
        self.assertEqual(1, fixed_ip.FixedIPList.get_count_by_project(
            self.context, self.context.project_id))


class TestFixedIPObject(test_objects._LocalTest,
                        _TestFixedIPObject):
    pass


class TestRemoteFixedIPObject(test_objects._RemoteTest,
                              _TestFixedIPObject):
    pass

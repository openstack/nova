# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

"""Tests For miscellaneous util methods used with compute."""

import copy
import string
import uuid

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import importutils
import six
import testtools

from nova.compute import flavors
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova.network import api as network_api
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.objects import instance as instance_obj
from nova import rpc
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network
from nova.tests.unit import fake_notifier
from nova.tests.unit import fake_server_actions
import nova.tests.unit.image.fake
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_flavor
from nova import utils
from nova.virt import driver

CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('compute_driver', 'nova.virt.driver')


class ComputeValidateDeviceTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeValidateDeviceTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        # check if test name includes "xen"
        if 'xen' in self.id():
            self.flags(compute_driver='xenapi.XenAPIDriver')
            self.instance = objects.Instance(uuid=uuid.uuid4().hex,
                root_device_name=None,
                default_ephemeral_device=None)
        else:
            self.instance = objects.Instance(uuid=uuid.uuid4().hex,
                root_device_name='/dev/vda',
                default_ephemeral_device='/dev/vdb')

        flavor = objects.Flavor(**test_flavor.fake_flavor)
        self.instance.system_metadata = {}
        with mock.patch.object(self.instance, 'save'):
            self.instance.set_flavor(flavor)
        self.instance.default_swap_device = None

        self.data = []

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       lambda context, instance, use_slave=False: self.data)

    def _update_flavor(self, flavor_info):
        self.flavor = {
            'id': 1,
            'name': 'foo',
            'memory_mb': 128,
            'vcpus': 1,
            'root_gb': 10,
            'ephemeral_gb': 10,
            'flavorid': 1,
            'swap': 0,
            'rxtx_factor': 1.0,
            'vcpu_weight': 1,
            }
        self.flavor.update(flavor_info)
        with mock.patch.object(self.instance, 'save'):
            self.instance.set_flavor(self.flavor)

    def _validate_device(self, device=None):
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, self.instance['uuid'])
        return compute_utils.get_device_name_for_instance(
                self.context, self.instance, bdms, device)

    @staticmethod
    def _fake_bdm(device):
        return fake_block_device.FakeDbBlockDeviceDict({
            'source_type': 'volume',
            'destination_type': 'volume',
            'device_name': device,
            'no_device': None,
            'volume_id': 'fake',
            'snapshot_id': None,
            'guest_format': None
        })

    def test_wrap(self):
        self.data = []
        for letter in string.ascii_lowercase[2:]:
            self.data.append(self._fake_bdm('/dev/vd' + letter))
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdaa')

    def test_wrap_plus_one(self):
        self.data = []
        for letter in string.ascii_lowercase[2:]:
            self.data.append(self._fake_bdm('/dev/vd' + letter))
        self.data.append(self._fake_bdm('/dev/vdaa'))
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdab')

    def test_later(self):
        self.data = [
            self._fake_bdm('/dev/vdc'),
            self._fake_bdm('/dev/vdd'),
            self._fake_bdm('/dev/vde'),
        ]
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdf')

    def test_gap(self):
        self.data = [
            self._fake_bdm('/dev/vdc'),
            self._fake_bdm('/dev/vde'),
        ]
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdd')

    def test_no_bdms(self):
        self.data = []
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdc')

    def test_lxc_names_work(self):
        self.instance['root_device_name'] = '/dev/a'
        self.instance['ephemeral_device_name'] = '/dev/b'
        self.data = []
        device = self._validate_device()
        self.assertEqual(device, '/dev/c')

    def test_name_conversion(self):
        self.data = []
        device = self._validate_device('/dev/c')
        self.assertEqual(device, '/dev/vdc')
        device = self._validate_device('/dev/sdc')
        self.assertEqual(device, '/dev/vdc')
        device = self._validate_device('/dev/xvdc')
        self.assertEqual(device, '/dev/vdc')

    def test_invalid_device_prefix(self):
        self.assertRaises(exception.InvalidDevicePath,
                          self._validate_device, '/baddata/vdc')

    def test_device_in_use(self):
        exc = self.assertRaises(exception.DevicePathInUse,
                          self._validate_device, '/dev/vda')
        self.assertIn('/dev/vda', six.text_type(exc))

    def test_swap(self):
        self.instance['default_swap_device'] = "/dev/vdc"
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdd')

    def test_swap_no_ephemeral(self):
        self.instance.default_ephemeral_device = None
        self.instance.default_swap_device = "/dev/vdb"
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdc')

    def test_ephemeral_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 10,
                'swap': 0,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdc')

    def test_swap_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 0,
                'swap': 10,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdb')

    def test_swap_and_ephemeral_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 10,
                'swap': 10,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdd')

    def test_swap_and_one_attachment_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 0,
                'swap': 10,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdb')
        self.data.append(self._fake_bdm(device))
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdd')

    def test_no_dev_root_device_name_get_next_name(self):
        self.instance['root_device_name'] = 'vda'
        device = self._validate_device()
        self.assertEqual('/dev/vdc', device)


class DefaultDeviceNamesForInstanceTestCase(test.NoDBTestCase):

    def setUp(self):
        super(DefaultDeviceNamesForInstanceTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.ephemerals = block_device_obj.block_device_make_list(
                self.context,
                [fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 1, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vdb',
                  'source_type': 'blank',
                  'destination_type': 'local',
                  'delete_on_termination': True,
                  'guest_format': None,
                  'boot_index': -1})])

        self.swap = block_device_obj.block_device_make_list(
                self.context,
                [fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 2, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vdc',
                  'source_type': 'blank',
                  'destination_type': 'local',
                  'delete_on_termination': True,
                  'guest_format': 'swap',
                  'boot_index': -1})])

        self.block_device_mapping = block_device_obj.block_device_make_list(
                self.context,
                [fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 3, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vda',
                  'source_type': 'volume',
                  'destination_type': 'volume',
                  'volume_id': 'fake-volume-id-1',
                  'boot_index': 0}),
                 fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 4, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vdd',
                  'source_type': 'snapshot',
                  'destination_type': 'volume',
                  'snapshot_id': 'fake-snapshot-id-1',
                  'boot_index': -1}),
                 fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 5, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vde',
                  'source_type': 'blank',
                  'destination_type': 'volume',
                  'boot_index': -1})])
        self.flavor = {'swap': 4}
        self.instance = {'uuid': 'fake_instance', 'ephemeral_gb': 2}
        self.is_libvirt = False
        self.root_device_name = '/dev/vda'
        self.update_called = False

        def fake_extract_flavor(instance):
            return self.flavor

        def fake_driver_matches(driver_string):
            if driver_string == 'libvirt.LibvirtDriver':
                return self.is_libvirt
            return False

        self.patchers = []
        self.patchers.append(
                mock.patch.object(objects.BlockDeviceMapping, 'save'))
        self.patchers.append(
                mock.patch.object(
                    flavors, 'extract_flavor',
                    new=mock.Mock(side_effect=fake_extract_flavor)))
        self.patchers.append(
                mock.patch.object(driver,
                                  'compute_driver_matches',
                                  new=mock.Mock(
                                      side_effect=fake_driver_matches)))
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        super(DefaultDeviceNamesForInstanceTestCase, self).tearDown()
        for patcher in self.patchers:
            patcher.stop()

    def _test_default_device_names(self, *block_device_lists):
        compute_utils.default_device_names_for_instance(self.instance,
                                                        self.root_device_name,
                                                        *block_device_lists)

    def test_only_block_device_mapping(self):
        # Test no-op
        original_bdm = copy.deepcopy(self.block_device_mapping)
        self._test_default_device_names([], [], self.block_device_mapping)
        for original, new in zip(original_bdm, self.block_device_mapping):
            self.assertEqual(original.device_name, new.device_name)

        # Assert it defaults the missing one as expected
        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names([], [], self.block_device_mapping)
        self.assertEqual('/dev/vdb',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vdc',
                         self.block_device_mapping[2]['device_name'])

    def test_with_ephemerals(self):
        # Test ephemeral gets assigned
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual(self.ephemerals[0]['device_name'], '/dev/vdb')

        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual('/dev/vdc',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[2]['device_name'])

    def test_with_swap(self):
        # Test swap only
        self.swap[0]['device_name'] = None
        self._test_default_device_names([], self.swap, [])
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdb')

        # Test swap and block_device_mapping
        self.swap[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names([], self.swap,
                                        self.block_device_mapping)
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdb')
        self.assertEqual('/dev/vdc',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[2]['device_name'])

    def test_all_together(self):
        # Test swap missing
        self.swap[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdc')

        # Test swap and eph missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual(self.ephemerals[0]['device_name'], '/dev/vdb')
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdc')

        # Test all missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self.block_device_mapping[2]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual(self.ephemerals[0]['device_name'], '/dev/vdb')
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdc')
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])
        self.assertEqual('/dev/vde',
                         self.block_device_mapping[2]['device_name'])


class UsageInfoTestCase(test.TestCase):

    def setUp(self):
        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)

        super(UsageInfoTestCase, self).setUp()
        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                       fake_get_nw_info)

        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

        self.flags(use_local=True, group='conductor')
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   network_manager='nova.network.manager.FlatManager')
        self.compute = importutils.import_object(CONF.compute_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

        def fake_show(meh, context, id, **kwargs):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.tests.unit.image.fake._FakeImageService,
                       'show', fake_show)
        fake_network.set_stub_network_methods(self.stubs)
        fake_server_actions.stub_out_action_events(self.stubs)

    def _create_instance(self, params=None):
        """Create a test instance."""
        params = params or {}
        flavor = flavors.get_flavor_by_name('m1.tiny')
        sys_meta = flavors.save_flavor_info({}, flavor)
        inst = {}
        inst['image_ref'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['instance_type_id'] = flavor['id']
        inst['system_metadata'] = sys_meta
        inst['ami_launch_index'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['info_cache'] = {'network_info': '[]'}
        inst.update(params)
        return db.instance_create(self.context, inst)['id']

    def test_notify_usage_exists(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = objects.Instance.get_by_id(self.context, instance_id,
                                              expected_attrs=[
                                                  'system_metadata'])
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        instance.system_metadata.update(sys_metadata)
        instance.save()
        compute_utils.notify_usage_exists(
            rpc.get_notifier('compute'), self.context, instance)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.exists')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertIn(attr, payload,
                          "Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance, [], [])

    def test_notify_usage_exists_deleted_instance(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = objects.Instance.get_by_id(self.context, instance_id,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        instance.system_metadata.update(sys_metadata)
        instance.save()
        self.compute.terminate_instance(self.context, instance, [], [])
        instance = objects.Instance.get_by_id(
                self.context.elevated(read_deleted='yes'), instance_id,
                expected_attrs=['system_metadata'])
        compute_utils.notify_usage_exists(
            rpc.get_notifier('compute'), self.context, instance)
        msg = fake_notifier.NOTIFICATIONS[-1]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.exists')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertIn(attr, payload, "Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)

    def test_notify_usage_exists_instance_not_found(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = objects.Instance.get_by_id(self.context, instance_id,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        self.compute.terminate_instance(self.context, instance, [], [])
        compute_utils.notify_usage_exists(
            rpc.get_notifier('compute'), self.context, instance)
        msg = fake_notifier.NOTIFICATIONS[-1]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.exists')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertIn(attr, payload, "Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'], {})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)

    def test_notify_about_instance_usage(self):
        instance_id = self._create_instance()
        instance = objects.Instance.get_by_id(self.context, instance_id,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        instance.system_metadata.update(sys_metadata)
        instance.save()
        extra_usage_info = {'image_name': 'fake_name'}
        compute_utils.notify_about_instance_usage(
            rpc.get_notifier('compute'),
            self.context, instance, 'create.start',
            extra_usage_info=extra_usage_info)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.create.start')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description', 'image_meta'):
            self.assertIn(attr, payload, "Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        self.assertEqual(payload['image_name'], 'fake_name')
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance, [], [])

    def test_notify_about_aggregate_update_with_id(self):
        # Set aggregate payload
        aggregate_payload = {'aggregate_id': 1}
        compute_utils.notify_about_aggregate_update(self.context,
                                                    "create.end",
                                                    aggregate_payload)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'aggregate.create.end')
        payload = msg.payload
        self.assertEqual(payload['aggregate_id'], 1)

    def test_notify_about_aggregate_update_with_name(self):
        # Set aggregate payload
        aggregate_payload = {'name': 'fakegroup'}
        compute_utils.notify_about_aggregate_update(self.context,
                                                    "create.start",
                                                    aggregate_payload)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'aggregate.create.start')
        payload = msg.payload
        self.assertEqual(payload['name'], 'fakegroup')

    def test_notify_about_aggregate_update_without_name_id(self):
        # Set empty aggregate payload
        aggregate_payload = {}
        compute_utils.notify_about_aggregate_update(self.context,
                                                    "create.start",
                                                    aggregate_payload)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)


class ComputeGetImageMetadataTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ComputeGetImageMetadataTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')

        self.image = {
            "min_ram": 10,
            "min_disk": 1,
            "disk_format": "raw",
            "container_format": "bare",
            "properties": {},
        }

        self.mock_image_api = mock.Mock()
        self.mock_image_api.get.return_value = self.image

        self.ctx = context.RequestContext('fake', 'fake')

        sys_meta = {
            'image_min_ram': 10,
            'image_min_disk': 1,
            'image_disk_format': 'raw',
            'image_container_format': 'bare',
        }

        flavor = objects.Flavor(
                 id=0,
                 name='m1.fake',
                 memory_mb=10,
                 vcpus=1,
                 root_gb=1,
                 ephemeral_gb=1,
                 flavorid='0',
                 swap=1,
                 rxtx_factor=0.0,
                 vcpu_weight=None)

        instance = fake_instance.fake_db_instance(
            memory_mb=0, root_gb=0,
            system_metadata=sys_meta)
        self.instance_obj = objects.Instance._from_db_object(
            self.ctx, objects.Instance(), instance,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)
        with mock.patch.object(self.instance_obj, 'save'):
            self.instance_obj.set_flavor(flavor)

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    def test_get_image_meta(self, mock_get):
        mock_get.return_value = objects.Flavor(extra_specs={})
        image_meta = compute_utils.get_image_metadata(
            self.ctx, self.mock_image_api, 'fake-image', self.instance_obj)

        self.image['properties'] = 'DONTCARE'
        self.assertThat(self.image, matchers.DictMatches(image_meta))

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    def test_get_image_meta_with_image_id_none(self, mock_flavor_get):
        mock_flavor_get.return_value = objects.Flavor(extra_specs={})
        self.image['properties'] = {'fake_property': 'fake_value'}

        inst = self.instance_obj

        with mock.patch.object(flavors,
                               "extract_flavor") as mock_extract_flavor:
            with mock.patch.object(utils, "get_system_metadata_from_image"
                                   ) as mock_get_sys_metadata:
                image_meta = compute_utils.get_image_metadata(
                    self.ctx, self.mock_image_api, None, inst)

                self.assertEqual(0, self.mock_image_api.get.call_count)
                self.assertEqual(0, mock_extract_flavor.call_count)
                self.assertEqual(0, mock_get_sys_metadata.call_count)
                self.assertNotIn('fake_property', image_meta['properties'])

        # Checking mock_image_api_get is called with 0 image_id
        # as 0 is a valid image ID
        image_meta = compute_utils.get_image_metadata(self.ctx,
                                                      self.mock_image_api,
                                                      0, self.instance_obj)
        self.assertEqual(1, self.mock_image_api.get.call_count)
        self.assertIn('fake_property', image_meta['properties'])

    def _test_get_image_meta_exception(self, error):
        self.mock_image_api.get.side_effect = error

        image_meta = compute_utils.get_image_metadata(
            self.ctx, self.mock_image_api, 'fake-image', self.instance_obj)

        self.image['properties'] = 'DONTCARE'
        # NOTE(danms): The trip through system_metadata will stringify things
        for key in self.image:
            self.image[key] = str(self.image[key])
        self.assertThat(self.image, matchers.DictMatches(image_meta))

    def test_get_image_meta_no_image(self):
        error = exception.ImageNotFound(image_id='fake-image')
        self._test_get_image_meta_exception(error)

    def test_get_image_meta_not_authorized(self):
        error = exception.ImageNotAuthorized(image_id='fake-image')
        self._test_get_image_meta_exception(error)

    def test_get_image_meta_bad_request(self):
        error = exception.Invalid()
        self._test_get_image_meta_exception(error)

    def test_get_image_meta_unexpected_exception(self):
        error = test.TestingException()
        with testtools.ExpectedException(test.TestingException):
            self._test_get_image_meta_exception(error)

    def test_get_image_meta_no_image_system_meta(self):
        for k in self.instance_obj.system_metadata.keys():
            if k.startswith('image_'):
                del self.instance_obj.system_metadata[k]

        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as get:
            get.return_value = objects.Flavor(extra_specs={})
            image_meta = compute_utils.get_image_metadata(
                self.ctx, self.mock_image_api, 'fake-image', self.instance_obj)

        self.image['properties'] = 'DONTCARE'
        self.assertThat(self.image, matchers.DictMatches(image_meta))

    def test_get_image_meta_no_image_no_image_system_meta(self):
        e = exception.ImageNotFound(image_id='fake-image')
        self.mock_image_api.get.side_effect = e

        for k in self.instance_obj.system_metadata.keys():
            if k.startswith('image_'):
                del self.instance_obj.system_metadata[k]

        with mock.patch('nova.objects.Flavor.get_by_flavor_id') as get:
            get.return_value = objects.Flavor(extra_specs={})
            image_meta = compute_utils.get_image_metadata(
                self.ctx, self.mock_image_api, 'fake-image', self.instance_obj)

        expected = {'properties': 'DONTCARE'}
        self.assertThat(expected, matchers.DictMatches(image_meta))


class ComputeUtilsGetValFromSysMetadata(test.NoDBTestCase):

    def test_get_value_from_system_metadata(self):
        instance = fake_instance.fake_instance_obj('fake-context')
        system_meta = {'int_val': 1,
                       'int_string': '2',
                       'not_int': 'Nope'}
        instance.system_metadata = system_meta

        result = compute_utils.get_value_from_system_metadata(
                   instance, 'int_val', int, 0)
        self.assertEqual(1, result)

        result = compute_utils.get_value_from_system_metadata(
                   instance, 'int_string', int, 0)
        self.assertEqual(2, result)

        result = compute_utils.get_value_from_system_metadata(
                   instance, 'not_int', int, 0)
        self.assertEqual(0, result)


class ComputeUtilsGetNWInfo(test.NoDBTestCase):
    def test_instance_object_none_info_cache(self):
        inst = fake_instance.fake_instance_obj('fake-context',
                                               expected_attrs=['info_cache'])
        self.assertIsNone(inst.info_cache)
        result = compute_utils.get_nw_info_for_instance(inst)
        self.assertEqual(jsonutils.dumps([]), result.json())

    def test_instance_dict_none_info_cache(self):
        inst = fake_instance.fake_db_instance(info_cache=None)
        self.assertIsNone(inst['info_cache'])
        result = compute_utils.get_nw_info_for_instance(inst)
        self.assertEqual(jsonutils.dumps([]), result.json())


class ComputeUtilsGetRebootTypes(test.NoDBTestCase):
    def setUp(self):
        super(ComputeUtilsGetRebootTypes, self).setUp()
        self.context = context.RequestContext('fake', 'fake')

    def test_get_reboot_type_started_soft(self):
        reboot_type = compute_utils.get_reboot_type(task_states.REBOOT_STARTED,
                                                    power_state.RUNNING)
        self.assertEqual(reboot_type, 'SOFT')

    def test_get_reboot_type_pending_soft(self):
        reboot_type = compute_utils.get_reboot_type(task_states.REBOOT_PENDING,
                                                    power_state.RUNNING)
        self.assertEqual(reboot_type, 'SOFT')

    def test_get_reboot_type_hard(self):
        reboot_type = compute_utils.get_reboot_type('foo', power_state.RUNNING)
        self.assertEqual(reboot_type, 'HARD')

    def test_get_reboot_not_running_hard(self):
        reboot_type = compute_utils.get_reboot_type('foo', 'bar')
        self.assertEqual(reboot_type, 'HARD')


class ComputeUtilsTestCase(test.NoDBTestCase):
    def test_exception_to_dict_with_long_message_3_bytes(self):
        # Generate Chinese byte string whose length is 300. This Chinese UTF-8
        # character occupies 3 bytes. After truncating, the byte string length
        # should be 255.
        msg = encodeutils.safe_decode('\xe8\xb5\xb5' * 100)
        exc = exception.NovaException(message=msg)
        fault_dict = compute_utils.exception_to_dict(exc)
        byte_message = encodeutils.safe_encode(fault_dict["message"])
        self.assertEqual(255, len(byte_message))

    def test_exception_to_dict_with_long_message_2_bytes(self):
        # Generate Russian byte string whose length is 300. This Russian UTF-8
        # character occupies 2 bytes. After truncating, the byte string length
        # should be 254.
        msg = encodeutils.safe_decode('\xd0\x92' * 150)
        exc = exception.NovaException(message=msg)
        fault_dict = compute_utils.exception_to_dict(exc)
        byte_message = encodeutils.safe_encode(fault_dict["message"])
        self.assertEqual(254, len(byte_message))

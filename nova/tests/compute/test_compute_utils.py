# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

"""Tests For miscellaneous util methods used with compute."""

import string

from nova.compute import instance_types
from nova.compute import utils as compute_utils
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova.network import api as network_api
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier_api
from nova.openstack.common.notifier import test_notifier
from nova import test
from nova.tests import fake_network
import nova.tests.image.fake

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('compute_driver', 'nova.virt.driver')


class ComputeValidateDeviceTestCase(test.TestCase):
    def setUp(self):
        super(ComputeValidateDeviceTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        # check if test name includes "xen"
        if 'xen' in self.id():
            self.flags(compute_driver='xenapi.XenAPIDriver')
            self.instance = {
                    'uuid': 'fake',
                    'root_device_name': None,
                    'instance_type_id': 'fake',
            }
        else:
            self.instance = {
                    'uuid': 'fake',
                    'root_device_name': '/dev/vda',
                    'default_ephemeral_device': '/dev/vdb',
                    'instance_type_id': 'fake',
            }
        self.data = []

        def fake_get(instance_type_id, ctxt=None):
            return self.instance_type

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       lambda context, instance: self.data)

    def _validate_device(self, device=None):
        bdms = db.block_device_mapping_get_all_by_instance(
            self.context, self.instance['uuid'])
        return compute_utils.get_device_name_for_instance(self.context,
                                                          self.instance,
                                                          bdms,
                                                          device)

    @staticmethod
    def _fake_bdm(device):
        return {
            'device_name': device,
            'no_device': None,
            'volume_id': 'fake',
            'snapshot_id': None
        }

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

    def test_invalid_bdms(self):
        self.instance['root_device_name'] = "baddata"
        self.assertRaises(exception.InvalidDevicePath,
                          self._validate_device)

    def test_invalid_device_prefix(self):
        self.assertRaises(exception.InvalidDevicePath,
                          self._validate_device, '/baddata/vdc')

    def test_device_in_use(self):
        self.assertRaises(exception.DevicePathInUse,
                          self._validate_device, '/dev/vdb')

    def test_swap(self):
        self.instance['default_swap_device'] = "/dev/vdc"
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdd')

    def test_swap_no_ephemeral(self):
        del self.instance['default_ephemeral_device']
        self.instance['default_swap_device'] = "/dev/vdb"
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdc')

    def test_ephemeral_xenapi(self):
        self.instance_type = {
            'ephemeral_gb': 10,
            'swap': 0,
        }
        self.stubs.Set(instance_types, 'get_instance_type',
                       lambda instance_type_id, ctxt=None: self.instance_type)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdc')

    def test_swap_xenapi(self):
        self.instance_type = {
            'ephemeral_gb': 0,
            'swap': 10,
        }
        self.stubs.Set(instance_types, 'get_instance_type',
                       lambda instance_type_id, ctxt=None: self.instance_type)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdb')

    def test_swap_and_ephemeral_xenapi(self):
        self.instance_type = {
            'ephemeral_gb': 10,
            'swap': 10,
        }
        self.stubs.Set(instance_types, 'get_instance_type',
                       lambda instance_type_id, ctxt=None: self.instance_type)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdd')

    def test_swap_and_one_attachment_xenapi(self):
        self.instance_type = {
            'ephemeral_gb': 0,
            'swap': 10,
        }
        self.stubs.Set(instance_types, 'get_instance_type',
                       lambda instance_type_id, ctxt=None: self.instance_type)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdb')
        self.data.append(self._fake_bdm(device))
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdd')


class UsageInfoTestCase(test.TestCase):

    def setUp(self):
        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1,
                                                          spectacular=True)

        super(UsageInfoTestCase, self).setUp()
        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                       fake_get_nw_info)

        notifier_api._reset_drivers()
        self.addCleanup(notifier_api._reset_drivers)
        self.flags(use_local=True, group='conductor')
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   notification_driver=[test_notifier.__name__],
                   network_manager='nova.network.manager.FlatManager')
        self.compute = importutils.import_object(CONF.compute_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.tests.image.fake._FakeImageService,
                       'show', fake_show)
        fake_network.set_stub_network_methods(self.stubs)

    def _create_instance(self, params={}):
        """Create a test instance."""
        inst = {}
        inst['image_ref'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst.update(params)
        return db.instance_create(self.context, inst)['id']

    def test_notify_usage_exists(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = db.instance_get(self.context, instance_id)
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        db.instance_system_metadata_update(self.context, instance['uuid'],
                sys_metadata, False)
        instance = db.instance_get(self.context, instance_id)
        compute_utils.notify_usage_exists(self.context, instance)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.exists')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEquals(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance)

    def test_notify_usage_exists_deleted_instance(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = db.instance_get(self.context, instance_id)
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        db.instance_system_metadata_update(self.context, instance['uuid'],
                sys_metadata, False)
        self.compute.terminate_instance(self.context, instance)
        instance = db.instance_get(self.context.elevated(read_deleted='yes'),
                                   instance_id)
        compute_utils.notify_usage_exists(self.context, instance)
        msg = test_notifier.NOTIFICATIONS[-1]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.exists')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEquals(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)

    def test_notify_usage_exists_instance_not_found(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = db.instance_get(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance)
        compute_utils.notify_usage_exists(self.context, instance)
        msg = test_notifier.NOTIFICATIONS[-1]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.exists')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEquals(payload['image_meta'], {})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)

    def test_notify_about_instance_usage(self):
        instance_id = self._create_instance()
        instance = db.instance_get(self.context, instance_id)
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        extra_usage_info = {'image_name': 'fake_name'}
        db.instance_system_metadata_update(self.context, instance['uuid'],
                sys_metadata, False)
        # NOTE(russellb) Make sure our instance has the latest system_metadata
        # in it.
        instance = db.instance_get(self.context, instance_id)
        compute_utils.notify_about_instance_usage(self.context, instance,
        'create.start', extra_usage_info=extra_usage_info)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.create.start')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEquals(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        self.assertEquals(payload['image_name'], 'fake_name')
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance)

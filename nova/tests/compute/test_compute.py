# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
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
"""Tests for compute service."""

import base64
import contextlib
import copy
import datetime
import operator
import sys
import testtools
import time
import traceback
import uuid

import mock
import mox
from oslo.config import cfg

import nova
from nova import availability_zones
from nova import block_device
from nova import compute
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import manager as compute_manager
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import manager as conductor_manager
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova.network import api as network_api
from nova.network import model as network_model
from nova.network.security_group import openstack_driver
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova.objects import migration as migration_obj
from nova.objects import quotas as quotas_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import policy
from nova import quota
from nova import test
from nova.tests.compute import fake_resource_tracker
from nova.tests.db import fakes as db_fakes
from nova.tests import fake_instance
from nova.tests import fake_instance_actions
from nova.tests import fake_network
from nova.tests import fake_network_cache_model
from nova.tests import fake_notifier
from nova.tests.image import fake as fake_image
from nova.tests import matchers
from nova.tests.objects import test_migration
from nova import utils
from nova.virt import event
from nova.virt import fake
from nova.volume import cinder

QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('live_migration_retry_count', 'nova.compute.manager')
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')


FAKE_IMAGE_REF = 'fake-image-ref'

NODENAME = 'fakenode1'


def get_primitive_instance_by_uuid(context, instance_uuid):
    """
    Helper method to get an instance and then convert it to
    a primitive form using jsonutils.
    """
    instance = db.instance_get_by_uuid(context, instance_uuid)
    return jsonutils.to_primitive(instance)


def unify_instance(instance):
    """Return a dict-like instance for both object-initiated and
    model-initiated sources that can reasonably be compared.
    """
    newdict = dict()
    for k, v in instance.iteritems():
        if isinstance(v, datetime.datetime):
            # NOTE(danms): DB models and Instance objects have different
            # timezone expectations
            v = v.replace(tzinfo=None)
        elif k == 'fault':
            # NOTE(danms): DB models don't have 'fault'
            continue
        elif k == 'pci_devices':
            # NOTE(yonlig.he) pci devices need lazy loading
            # fake db does not support it yet.
            continue
        newdict[k] = v
    return newdict


class FakeSchedulerAPI(object):

    def run_instance(self, ctxt, request_spec, admin_password,
            injected_files, requested_networks, is_first_time,
            filter_properties):
        pass

    def live_migration(self, ctxt, block_migration, disk_over_commit,
            instance, dest):
        pass

    def prep_resize(self, ctxt, instance, instance_type, image, request_spec,
            filter_properties, reservations):
        pass


class BaseTestCase(test.TestCase):

    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   network_manager='nova.network.manager.FlatManager')
        fake.set_nodes([NODENAME])
        self.flags(use_local=True, group='conductor')

        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

        self.compute = importutils.import_object(CONF.compute_manager)

        # override tracker with a version that doesn't need the database:
        fake_rt = fake_resource_tracker.FakeResourceTracker(self.compute.host,
                    self.compute.driver, NODENAME)
        self.compute._resource_tracker_dict[NODENAME] = fake_rt

        def fake_get_compute_nodes_in_db(context):
            fake_compute_nodes = [{'local_gb': 259,
                                   'vcpus_used': 0,
                                   'deleted': 0,
                                   'hypervisor_type': 'powervm',
                                   'created_at': '2013-04-01T00:27:06.000000',
                                   'local_gb_used': 0,
                                   'updated_at': '2013-04-03T00:35:41.000000',
                                   'hypervisor_hostname': 'fake_phyp1',
                                   'memory_mb_used': 512,
                                   'memory_mb': 131072,
                                   'current_workload': 0,
                                   'vcpus': 16,
                                   'cpu_info': 'ppc64,powervm,3940',
                                   'running_vms': 0,
                                   'free_disk_gb': 259,
                                   'service_id': 7,
                                   'hypervisor_version': 7,
                                   'disk_available_least': 265856,
                                   'deleted_at': None,
                                   'free_ram_mb': 130560,
                                   'id': 2}]
            return fake_compute_nodes

        def fake_compute_node_delete(context, compute_node):
            self.assertEqual(compute_node.get('hypervisor_hostname'),
                             'fake_phyp1')

        self.stubs.Set(self.compute, '_get_compute_nodes_in_db',
                fake_get_compute_nodes_in_db)
        self.stubs.Set(self.compute.conductor_api, 'compute_node_delete',
                fake_compute_node_delete)

        self.compute.update_available_resource(
                context.get_admin_context())

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

        def fake_show(meh, context, id):
            if id:
                return {'id': id, 'min_disk': None, 'min_ram': None,
                        'name': 'fake_name',
                        'status': 'active',
                        'properties': {'kernel_id': 'fake_kernel_id',
                                       'ramdisk_id': 'fake_ramdisk_id',
                                       'something_else': 'meow'}}
            else:
                raise exception.ImageNotFound(image_id=id)

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        fake_rpcapi = FakeSchedulerAPI()
        self.stubs.Set(self.compute, 'scheduler_rpcapi', fake_rpcapi)
        fake_network.set_stub_network_methods(self.stubs)
        fake_instance_actions.stub_out_action_events(self.stubs)

        def fake_get_nw_info(cls, ctxt, instance, *args, **kwargs):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)

        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                       fake_get_nw_info)
        self.stubs.Set(network_api.API, 'allocate_for_instance',
                       fake_get_nw_info)
        self.compute_api = compute.API()

        # Just to make long lines short
        self.rt = self.compute._get_resource_tracker(NODENAME)

    def tearDown(self):
        timeutils.clear_time_override()
        ctxt = context.get_admin_context()
        fake_image.FakeImageService_reset()
        instances = db.instance_get_all(ctxt)
        for instance in instances:
            db.instance_destroy(ctxt, instance['uuid'])
        fake.restore_nodes()
        super(BaseTestCase, self).tearDown()

    def _create_fake_instance(self, params=None, type_name='m1.tiny',
                              services=False):
        """Create a test instance."""
        if not params:
            params = {}

        def make_fake_sys_meta():
            sys_meta = params.pop("system_metadata", {})
            inst_type = flavors.get_flavor_by_name(type_name)
            for key in flavors.system_metadata_flavor_props:
                sys_meta['instance_type_%s' % key] = inst_type[key]
            return sys_meta

        inst = {}
        inst['vm_state'] = vm_states.ACTIVE
        inst['task_state'] = None
        inst['image_ref'] = FAKE_IMAGE_REF
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['host'] = 'fake_host'
        inst['node'] = NODENAME
        type_id = flavors.get_flavor_by_name(type_name)['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['memory_mb'] = 0
        inst['vcpus'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['architecture'] = 'x86_64'
        inst['os_type'] = 'Linux'
        inst['system_metadata'] = make_fake_sys_meta()
        inst['locked'] = False
        inst['created_at'] = timeutils.utcnow()
        inst['updated_at'] = timeutils.utcnow()
        inst['launched_at'] = timeutils.utcnow()
        inst['security_groups'] = []
        inst.update(params)
        if services:
            _create_service_entries(self.context.elevated(),
                    {'fake_zone': [inst['host']]})
        return db.instance_create(self.context, inst)

    def _objectify(self, db_inst):
        return instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), db_inst,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)

    def _create_fake_instance_obj(self, params=None, type_name='m1.tiny'):
        db_inst = self._create_fake_instance(params, type_name=type_name)
        return self._objectify(db_inst)

    def _create_instance_type(self, params=None):
        """Create a test instance type."""
        if not params:
            params = {}

        context = self.context.elevated()
        inst = {}
        inst['name'] = 'm1.small'
        inst['memory_mb'] = 1024
        inst['vcpus'] = 1
        inst['root_gb'] = 20
        inst['ephemeral_gb'] = 10
        inst['flavorid'] = '1'
        inst['swap'] = 2048
        inst['rxtx_factor'] = 1
        inst.update(params)
        return db.flavor_create(context, inst)['id']

    def _create_group(self):
        values = {'name': 'testgroup',
                  'description': 'testgroup',
                  'user_id': self.user_id,
                  'project_id': self.project_id}
        return db.security_group_create(self.context, values)

    def _stub_migrate_server(self):
        def _fake_migrate_server(*args, **kwargs):
            pass

        self.stubs.Set(conductor_manager.ComputeTaskManager,
                       'migrate_server', _fake_migrate_server)


class ComputeVolumeTestCase(BaseTestCase):

    def setUp(self):
        super(ComputeVolumeTestCase, self).setUp()
        self.volume_id = 'fake'
        self.fetched_attempts = 0
        self.instance = {
            'id': 'fake',
            'uuid': 'fake',
            'name': 'fake',
            'root_device_name': '/dev/vda',
        }
        self.stubs.Set(self.compute.volume_api, 'get', lambda *a, **kw:
                       {'id': self.volume_id})
        self.stubs.Set(self.compute.driver, 'get_volume_connector',
                       lambda *a, **kw: None)
        self.stubs.Set(self.compute.volume_api, 'initialize_connection',
                       lambda *a, **kw: {})
        self.stubs.Set(self.compute.volume_api, 'terminate_connection',
                       lambda *a, **kw: None)
        self.stubs.Set(self.compute.volume_api, 'attach',
                       lambda *a, **kw: None)
        self.stubs.Set(self.compute.volume_api, 'detach',
                       lambda *a, **kw: None)
        self.stubs.Set(self.compute.volume_api, 'check_attach',
                       lambda *a, **kw: None)

        def store_cinfo(context, *args):
            self.cinfo = jsonutils.loads(args[-1].get('connection_info'))

        self.stubs.Set(self.compute.conductor_api,
                       'block_device_mapping_update',
                       store_cinfo)
        self.stubs.Set(self.compute.conductor_api,
                       'block_device_mapping_update_or_create',
                       store_cinfo)

    def test_attach_volume_serial(self):
        def fake_get_volume_encryption_metadata(self, context, volume_id):
            return {}
        self.stubs.Set(cinder.API, 'get_volume_encryption_metadata',
                       fake_get_volume_encryption_metadata)

        instance = self._create_fake_instance()
        self.compute.attach_volume(self.context, self.volume_id,
                                   '/dev/vdb', instance)
        self.assertEqual(self.cinfo.get('serial'), self.volume_id)

    def test_await_block_device_created_to_slow(self):

        def never_get(context, vol_id):
            return {
                'status': 'creating',
                'id': 'blah',
            }

        self.stubs.Set(self.compute.volume_api, 'get', never_get)
        self.assertRaises(exception.VolumeNotCreated,
                          self.compute._await_block_device_map_created,
                          self.context, '1', max_tries=2, wait_between=0.1)

    def test_await_block_device_created_slow(self):
        c = self.compute

        def slow_get(context, vol_id):
            while self.fetched_attempts < 2:
                self.fetched_attempts += 1
                return {
                    'status': 'creating',
                    'id': 'blah',
                }
            return {
                'status': 'available',
                'id': 'blah',
            }

        self.stubs.Set(c.volume_api, 'get', slow_get)
        attempts = c._await_block_device_map_created(self.context, '1',
                                                     max_tries=4,
                                                     wait_between=0.1)
        self.assertEqual(attempts, 3)

    def test_boot_volume_serial(self):
        block_device_mapping = [
        block_device.BlockDeviceDict({
            'id': 1,
            'no_device': None,
            'source_type': 'volume',
            'destination_type': 'volume',
            'snapshot_id': None,
            'volume_id': self.volume_id,
            'device_name': '/dev/vdb',
            'delete_on_termination': False,
        })]
        self.compute._prep_block_device(self.context, self.instance,
                                        block_device_mapping)
        self.assertEqual(self.cinfo.get('serial'), self.volume_id)

    def test_boot_volume_metadata(self, metadata=True):
        def volume_api_get(*args, **kwargs):
            if metadata:
                return {
                    'volume_image_metadata': {'vol_test_key': 'vol_test_value'}
                }
            else:
                return {}

        self.stubs.Set(self.compute_api.volume_api, 'get', volume_api_get)

        block_device_mapping = [{
            'id': 1,
            'device_name': 'vda',
            'no_device': None,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': self.volume_id,
            'delete_on_termination': False,
        }]

        image_meta = self.compute_api._get_bdm_image_metadata(
            self.context, block_device_mapping)
        if metadata:
            self.assertEqual(image_meta['vol_test_key'], 'vol_test_value')
        else:
            self.assertEqual(image_meta, {})

        # Test it with new-style BDMs
        block_device_mapping = [{
            'boot_index': 0,
            'source_type': 'volume',
            'destination_type': 'volume',
            'volume_id': self.volume_id,
            'delete_on_termination': False,
        }]

        image_meta = self.compute_api._get_bdm_image_metadata(
            self.context, block_device_mapping, legacy_bdm=False)
        if metadata:
            self.assertEqual(image_meta['vol_test_key'], 'vol_test_value')
        else:
            self.assertEqual(image_meta, {})

    def test_boot_volume_no_metadata(self):
        self.test_boot_volume_metadata(metadata=False)

    def test_boot_image_metadata(self, metadata=True):
        def image_api_show(*args, **kwargs):
            if metadata:
                return {
                    'properties': {'img_test_key': 'img_test_value'}
                }
            else:
                return {}

        self.stubs.Set(self.compute_api.image_service, 'show', image_api_show)

        block_device_mapping = [{
            'boot_index': 0,
            'source_type': 'image',
            'destination_type': 'local',
            'image_id': "fake-image",
            'delete_on_termination': True,
        }]

        image_meta = self.compute_api._get_bdm_image_metadata(
            self.context, block_device_mapping, legacy_bdm=False)

        if metadata:
            self.assertEqual(image_meta['img_test_key'], 'img_test_value')
        else:
            self.assertEqual(image_meta, {})

    def test_boot_image_no_metadata(self):
        self.test_boot_image_metadata(metadata=False)

    def test_poll_volume_usage_disabled(self):
        ctxt = 'MockContext'
        self.mox.StubOutWithMock(self.compute, '_get_host_volume_bdms')
        self.mox.StubOutWithMock(utils, 'last_completed_audit_period')
        # None of the mocks should be called.
        self.mox.ReplayAll()

        CONF.volume_usage_poll_interval = 0
        self.compute._poll_volume_usage(ctxt)
        self.mox.UnsetStubs()

    def test_poll_volume_usage_interval_not_elapsed(self):
        ctxt = 'MockContext'
        self.mox.StubOutWithMock(self.compute, '_get_host_volume_bdms')
        self.mox.StubOutWithMock(utils, 'last_completed_audit_period')
        self.mox.StubOutWithMock(self.compute.driver, 'get_all_volume_usage')
        self.mox.StubOutWithMock(time, 'time')
        # Following methods will be called.
        utils.last_completed_audit_period().AndReturn((0, 0))
        time.time().AndReturn(10)
        self.mox.ReplayAll()

        CONF.volume_usage_poll_interval = 2
        self.compute._last_vol_usage_poll = 9
        self.compute._poll_volume_usage(ctxt)
        self.mox.UnsetStubs()

    def test_poll_volume_usage_returns_no_vols(self):
        ctxt = 'MockContext'
        self.compute.host = 'MockHost'
        self.mox.StubOutWithMock(self.compute, '_get_host_volume_bdms')
        self.mox.StubOutWithMock(utils, 'last_completed_audit_period')
        self.mox.StubOutWithMock(self.compute.driver, 'get_all_volume_usage')
        # Following methods are called.
        utils.last_completed_audit_period().AndReturn((0, 0))
        self.compute._get_host_volume_bdms(ctxt, 'MockHost').AndReturn([])
        self.mox.ReplayAll()

        CONF.volume_usage_poll_interval = 10
        self.compute._last_vol_usage_poll = 0
        self.compute._poll_volume_usage(ctxt)
        self.mox.UnsetStubs()

    def test_poll_volume_usage_with_data(self):
        ctxt = 'MockContext'
        self.compute.host = 'MockHost'
        self.mox.StubOutWithMock(utils, 'last_completed_audit_period')
        self.mox.StubOutWithMock(self.compute, '_get_host_volume_bdms')
        self.mox.StubOutWithMock(self.compute, '_update_volume_usage_cache')
        self.stubs.Set(self.compute.driver, 'get_all_volume_usage',
                       lambda x, y: [3, 4])
        # All the mocks are called
        utils.last_completed_audit_period().AndReturn((10, 20))
        self.compute._get_host_volume_bdms(ctxt, 'MockHost').AndReturn([1, 2])
        self.compute._update_volume_usage_cache(ctxt, [3, 4])
        self.mox.ReplayAll()
        CONF.volume_usage_poll_interval = 10
        self.compute._last_vol_usage_poll = 0
        self.compute._poll_volume_usage(ctxt)
        self.assertTrue(self.compute._last_vol_usage_poll > 0,
                        "_last_vol_usage_poll was not properly updated <%s>" %
                        self.compute._last_vol_usage_poll)
        self.mox.UnsetStubs()

    def test_detach_volume_usage(self):
        # Test that detach volume update the volume usage cache table correctly
        instance = self._create_fake_instance()
        bdm = {'id': 1,
               'device_name': '/dev/vdb',
               'connection_info': '{}',
               'instance_uuid': instance['uuid'],
               'volume_id': 1}

        self.mox.StubOutWithMock(self.compute, '_get_instance_volume_bdm')
        self.mox.StubOutWithMock(self.compute.driver, 'block_stats')
        self.mox.StubOutWithMock(self.compute, '_get_host_volume_bdms')
        self.mox.StubOutWithMock(self.compute.driver, 'get_all_volume_usage')

        # The following methods will be called
        self.compute._get_instance_volume_bdm(self.context, instance, 1).\
            AndReturn(bdm)
        self.compute.driver.block_stats(instance['name'], 'vdb').\
            AndReturn([1L, 30L, 1L, 20L, None])
        self.compute._get_host_volume_bdms(self.context, 'fake-mini').\
            AndReturn(bdm)
        self.compute.driver.get_all_volume_usage(self.context, bdm).\
            AndReturn([{'volume': 1,
                        'rd_req': 1,
                        'rd_bytes': 10,
                        'wr_req': 1,
                        'wr_bytes': 5,
                        'instance': instance}])

        self.mox.ReplayAll()

        def fake_get_volume_encryption_metadata(self, context, volume_id):
            return {}
        self.stubs.Set(cinder.API, 'get_volume_encryption_metadata',
                       fake_get_volume_encryption_metadata)

        self.compute.attach_volume(self.context, 1, '/dev/vdb', instance)

        # Poll volume usage & then detach the volume. This will update the
        # total fields in the volume usage cache.
        CONF.volume_usage_poll_interval = 10
        self.compute._poll_volume_usage(self.context)
        # Check that a volume.usage and volume.attach notification was sent
        self.assertEqual(2, len(fake_notifier.NOTIFICATIONS))

        self.compute.detach_volume(self.context, 1, instance)

        # Check that volume.attach, 2 volume.usage, and volume.detach
        # notifications were sent
        self.assertEquals(4, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals('compute.instance.volume.attach', msg.event_type)
        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEquals('volume.usage', msg.event_type)
        payload = msg.payload
        self.assertEquals(instance['uuid'], payload['instance_id'])
        self.assertEquals('fake', payload['user_id'])
        self.assertEquals('fake', payload['tenant_id'])
        self.assertEquals(1, payload['reads'])
        self.assertEquals(30, payload['read_bytes'])
        self.assertEquals(1, payload['writes'])
        self.assertEquals(20, payload['write_bytes'])
        self.assertEquals(None, payload['availability_zone'])
        msg = fake_notifier.NOTIFICATIONS[3]
        self.assertEquals('compute.instance.volume.detach', msg.event_type)

        # Check the database for the
        volume_usages = db.vol_get_usage_by_time(self.context, 0)
        self.assertEqual(1, len(volume_usages))
        volume_usage = volume_usages[0]
        self.assertEqual(0, volume_usage['curr_reads'])
        self.assertEqual(0, volume_usage['curr_read_bytes'])
        self.assertEqual(0, volume_usage['curr_writes'])
        self.assertEqual(0, volume_usage['curr_write_bytes'])
        self.assertEqual(1, volume_usage['tot_reads'])
        self.assertEqual(30, volume_usage['tot_read_bytes'])
        self.assertEqual(1, volume_usage['tot_writes'])
        self.assertEqual(20, volume_usage['tot_write_bytes'])

    def test_prepare_image_mapping(self):
        swap_size = 1
        ephemeral_size = 1
        instance_type = {'swap': swap_size,
                         'ephemeral_gb': ephemeral_size}
        instance = self._create_fake_instance()
        mappings = [
                {'virtual': 'ami', 'device': 'sda1'},
                {'virtual': 'root', 'device': '/dev/sda1'},

                {'virtual': 'swap', 'device': 'sdb4'},

                {'virtual': 'ephemeral0', 'device': 'sdc1'},
                {'virtual': 'ephemeral1', 'device': 'sdc2'},
        ]

        preped_bdm = self.compute_api._prepare_image_mapping(
            instance_type, instance['uuid'], mappings)

        expected_result = [
            {
                'device_name': '/dev/sdb4',
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'guest_format': 'swap',
                'boot_index': -1,
                'volume_size': swap_size
            },
            {
                'device_name': '/dev/sdc1',
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'guest_format': CONF.default_ephemeral_format,
                'boot_index': -1,
                'volume_size': ephemeral_size
            },
            {
                'device_name': '/dev/sdc2',
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'guest_format': CONF.default_ephemeral_format,
                'boot_index': -1,
                'volume_size': ephemeral_size
            }
        ]

        for expected, got in zip(expected_result, preped_bdm):
            self.assertThat(expected, matchers.IsSubDictOf(got))

    def test_validate_bdm(self):
        def fake_get(self, context, res_id):
            return {'id': res_id}

        def fake_check_attach(*args, **kwargs):
            pass

        self.stubs.Set(cinder.API, 'get', fake_get)
        self.stubs.Set(cinder.API, 'get_snapshot', fake_get)
        self.stubs.Set(cinder.API, 'check_attach',
                       fake_check_attach)

        volume_id = '55555555-aaaa-bbbb-cccc-555555555555'
        snapshot_id = '66666666-aaaa-bbbb-cccc-555555555555'

        instance = self._create_fake_instance()
        instance_type = {'swap': 1, 'ephemeral_gb': 2}
        mappings = [
            {
                'device_name': '/dev/sdb4',
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'guest_format': 'swap',
                'boot_index': -1,
                'volume_size': 1
            },
            {
                'device_name': '/dev/sda1',
                'source_type': 'volume',
                'destination_type': 'volume',
                'device_type': 'disk',
                'volume_id': volume_id,
                'guest_format': None,
                'boot_index': 1,
                'volume_size': 6
            },
            {
                'device_name': '/dev/sda2',
                'source_type': 'snapshot',
                'destination_type': 'volume',
                'snapshot_id': snapshot_id,
                'device_type': 'disk',
                'guest_format': None,
                'boot_index': 0,
                'volume_size': 4
            },
            {
                'device_name': '/dev/sda3',
                'source_type': 'image',
                'destination_type': 'local',
                'device_type': 'disk',
                'guest_format': None,
                'boot_index': 2,
                'volume_size': 1
            }
        ]

        # Make sure it passes at first
        self.compute_api._validate_bdm(self.context, instance,
                                       instance_type, mappings)

        # Boot sequence
        mappings[2]['boot_index'] = 2
        self.assertRaises(exception.InvalidBDMBootSequence,
                          self.compute_api._validate_bdm,
                          self.context, instance, instance_type,
                          mappings)
        mappings[2]['boot_index'] = 0

        # number of local block_devices
        self.flags(max_local_block_devices=1)
        self.assertRaises(exception.InvalidBDMLocalsLimit,
                          self.compute_api._validate_bdm,
                          self.context, instance, instance_type,
                          mappings)
        ephemerals = [
            {
                'device_name': '/dev/vdb',
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'volume_id': volume_id,
                'guest_format': None,
                'boot_index': -1,
                'volume_size': 1
            },
            {
                'device_name': '/dev/vdc',
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'volume_id': volume_id,
                'guest_format': None,
                'boot_index': -1,
                'volume_size': 1
            }]

        self.flags(max_local_block_devices=4)
        # More ephemerals are OK as long as they are not over the size limit
        self.compute_api._validate_bdm(self.context, instance,
                                       instance_type, mappings + ephemerals)

        # Ephemerals over the size limit
        ephemerals[0]['volume_size'] = 3
        self.assertRaises(exception.InvalidBDMEphemeralSize,
                          self.compute_api._validate_bdm,
                          self.context, instance, instance_type,
                          mappings + ephemerals)
        self.assertRaises(exception.InvalidBDMEphemeralSize,
                          self.compute_api._validate_bdm,
                          self.context, instance, instance_type,
                          mappings + [ephemerals[0]])

        # Swap over the size limit
        mappings[0]['volume_size'] = 3
        self.assertRaises(exception.InvalidBDMSwapSize,
                          self.compute_api._validate_bdm,
                          self.context, instance, instance_type,
                          mappings)
        mappings[0]['volume_size'] = 1

        additional_swap = [
            {
                'device_name': '/dev/vdb',
                'source_type': 'blank',
                'destination_type': 'local',
                'device_type': 'disk',
                'guest_format': 'swap',
                'boot_index': -1,
                'volume_size': 1
            }]

        # More than one swap
        self.assertRaises(exception.InvalidBDMFormat,
                          self.compute_api._validate_bdm,
                          self.context, instance, instance_type,
                          mappings + additional_swap)

    def test_validate_bdm_media_service_exceptions(self):
        instance_type = {'swap': 1, 'ephemeral_gb': 1}
        all_mappings = [{'id': 1,
                         'no_device': None,
                         'source_type': 'volume',
                         'destination_type': 'volume',
                         'snapshot_id': None,
                         'volume_id': self.volume_id,
                         'device_name': 'vda',
                         'boot_index': 0,
                         'delete_on_termination': False}]

        # Check that the volume status is 'available' and reject if not
        def fake_volume_get_1(self, context, volume_id):
            return {'id': volume_id,
                    'status': 'creating',
                    'attach_status': 'detached'}
        self.stubs.Set(cinder.API, 'get', fake_volume_get_1)

        self.assertRaises(exception.InvalidBDMVolume,
                          self.compute_api._validate_bdm,
                          self.context, self.instance,
                          instance_type, all_mappings)

        # Check that the volume attach_status is 'detached' and reject if not
        def fake_volume_get_2(self, context, volume_id):
            return {'id': volume_id,
                    'status': 'available',
                    'attach_status': 'attached'}
        self.stubs.Set(cinder.API, 'get', fake_volume_get_2)

        self.assertRaises(exception.InvalidBDMVolume,
                          self.compute_api._validate_bdm,
                          self.context, self.instance,
                          instance_type, all_mappings)

        # Check that the volume status is 'available' and attach_status is
        # 'detached' and accept the request if so
        def fake_volume_get_3(self, context, volume_id):
            return {'id': volume_id,
                    'status': 'available',
                    'attach_status': 'detached'}
        self.stubs.Set(cinder.API, 'get', fake_volume_get_3)

        self.compute_api._validate_bdm(self.context, self.instance,
                                       instance_type, all_mappings)

    def test_volume_snapshot_create(self):
        self.assertRaises(rpc_common.ClientException,
                self.compute.volume_snapshot_create, self.context,
                self.instance, 'fake_id', {})

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(NotImplementedError,
                self.compute.volume_snapshot_create, self.context,
                self.instance, 'fake_id', {})

    def test_volume_snapshot_delete(self):
        self.assertRaises(rpc_common.ClientException,
                self.compute.volume_snapshot_delete, self.context,
                self.instance, 'fake_id', 'fake_id2', {})

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(NotImplementedError,
                self.compute.volume_snapshot_delete, self.context,
                self.instance, 'fake_id', 'fake_id2', {})


class ComputeTestCase(BaseTestCase):
    def test_wrap_instance_fault(self):
        inst = {"uuid": "fake_uuid"}

        called = {'fault_added': False}

        def did_it_add_fault(*args):
            called['fault_added'] = True

        self.stubs.Set(compute_utils, 'add_instance_fault_from_exc',
                       did_it_add_fault)

        @compute_manager.wrap_instance_fault
        def failer(self2, context, instance):
            raise NotImplementedError()

        self.assertRaises(NotImplementedError, failer,
                          self.compute, self.context, instance=inst)

        self.assertTrue(called['fault_added'])

    def test_wrap_instance_fault_instance_in_args(self):
        inst = {"uuid": "fake_uuid"}

        called = {'fault_added': False}

        def did_it_add_fault(*args):
            called['fault_added'] = True

        self.stubs.Set(compute_utils, 'add_instance_fault_from_exc',
                       did_it_add_fault)

        @compute_manager.wrap_instance_fault
        def failer(self2, context, instance):
            raise NotImplementedError()

        self.assertRaises(NotImplementedError, failer,
                          self.compute, self.context, inst)

        self.assertTrue(called['fault_added'])

    def test_wrap_instance_fault_no_instance(self):
        inst_uuid = "fake_uuid"

        called = {'fault_added': False}

        def did_it_add_fault(*args):
            called['fault_added'] = True

        self.stubs.Set(compute_utils, 'add_instance_fault_from_exc',
                       did_it_add_fault)

        @compute_manager.wrap_instance_fault
        def failer(self2, context, instance_uuid):
            raise exception.InstanceNotFound(instance_id=instance_uuid)

        self.assertRaises(exception.InstanceNotFound, failer,
                          self.compute, self.context, inst_uuid)

        self.assertFalse(called['fault_added'])

    def test_wrap_instance_event(self):
        inst = {"uuid": "fake_uuid"}

        called = {'started': False,
                  'finished': False}

        def did_it_update_start(self2, context, values):
            called['started'] = True

        def did_it_update_finish(self2, context, values):
            called['finished'] = True

        self.stubs.Set(conductor_manager.ConductorManager,
                       'action_event_start', did_it_update_start)

        self.stubs.Set(conductor_manager.ConductorManager,
                       'action_event_finish', did_it_update_finish)

        @compute_manager.wrap_instance_event
        def fake_event(self, context, instance):
            pass

        fake_event(self.compute, self.context, instance=inst)

        self.assertTrue(called['started'])
        self.assertTrue(called['finished'])

    def test_wrap_instance_event_log_exception(self):
        inst = {"uuid": "fake_uuid"}

        called = {'started': False,
                  'finished': False,
                  'message': ''}

        def did_it_update_start(self2, context, values):
            called['started'] = True

        def did_it_update_finish(self2, context, values):
            called['finished'] = True
            called['message'] = values['message']

        self.stubs.Set(conductor_manager.ConductorManager,
                       'action_event_start', did_it_update_start)

        self.stubs.Set(conductor_manager.ConductorManager,
                       'action_event_finish', did_it_update_finish)

        @compute_manager.wrap_instance_event
        def fake_event(self2, context, instance):
            raise exception.NovaException()

        self.assertRaises(exception.NovaException, fake_event,
                          self.compute, self.context, instance=inst)

        self.assertTrue(called['started'])
        self.assertTrue(called['finished'])
        self.assertEqual('An unknown exception occurred.', called['message'])

    def test_object_compat(self):
        db_inst = fake_instance.fake_db_instance()

        @compute_manager.object_compat
        def test_fn(_self, context, instance):
            self.assertTrue(isinstance(instance, instance_obj.Instance))
            self.assertEqual(instance.uuid, db_inst['uuid'])

        test_fn(None, self.context, instance=db_inst)

    def test_create_instance_with_img_ref_associates_config_drive(self):
        # Make sure create associates a config drive.

        instance = jsonutils.to_primitive(self._create_fake_instance(
                        params={'config_drive': '1234', }))

        try:
            self.compute.run_instance(self.context, instance=instance)
            instances = db.instance_get_all(self.context)
            instance = instances[0]

            self.assertTrue(instance['config_drive'])
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_create_instance_associates_config_drive(self):
        # Make sure create associates a config drive.

        instance = jsonutils.to_primitive(self._create_fake_instance(
                        params={'config_drive': '1234', }))

        try:
            self.compute.run_instance(self.context, instance=instance)
            instances = db.instance_get_all(self.context)
            instance = instances[0]

            self.assertTrue(instance['config_drive'])
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_create_instance_unlimited_memory(self):
        # Default of memory limit=None is unlimited.
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())
        params = {"memory_mb": 999999999999}
        filter_properties = {'limits': {'memory_mb': None}}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)
        self.assertEqual(999999999999, self.rt.compute_node['memory_mb_used'])

    def test_create_instance_unlimited_disk(self):
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())
        params = {"root_gb": 999999999999,
                  "ephemeral_gb": 99999999999}
        filter_properties = {'limits': {'disk_gb': None}}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_multiple_instances_then_starve(self):
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())
        filter_properties = {'limits': {'memory_mb': 4096, 'disk_gb': 1000}}
        params = {"memory_mb": 1024, "root_gb": 128, "ephemeral_gb": 128}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                                  filter_properties=filter_properties)
        self.assertEquals(1024, self.rt.compute_node['memory_mb_used'])
        self.assertEquals(256, self.rt.compute_node['local_gb_used'])

        params = {"memory_mb": 2048, "root_gb": 256, "ephemeral_gb": 256}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                                  filter_properties=filter_properties)
        self.assertEquals(3072, self.rt.compute_node['memory_mb_used'])
        self.assertEquals(768, self.rt.compute_node['local_gb_used'])

        params = {"memory_mb": 8192, "root_gb": 8192, "ephemeral_gb": 8192}
        instance = self._create_fake_instance(params)
        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_multiple_instance_with_neutron_port(self):
        instance_type = flavors.get_default_flavor()

        def fake_is_neutron():
            return True
        self.stubs.Set(utils, 'is_neutron', fake_is_neutron)
        self.assertRaises(exception.MultiplePortsNotApplicable,
                          self.compute_api.create,
                          self.context,
                          instance_type=instance_type,
                          image_href=None,
                          max_count=2,
                          requested_networks=[(None, None, 'adadds')])

    def test_create_instance_with_oversubscribed_ram(self):
        # Test passing of oversubscribed ram policy from the scheduler.

        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource(NODENAME)
        total_mem_mb = resources['memory_mb']

        oversub_limit_mb = total_mem_mb * 1.5
        instance_mb = int(total_mem_mb * 1.45)

        # build an instance, specifying an amount of memory that exceeds
        # total_mem_mb, but is less than the oversubscribed limit:
        params = {"memory_mb": instance_mb, "root_gb": 128,
                  "ephemeral_gb": 128}
        instance = self._create_fake_instance(params)

        limits = {'memory_mb': oversub_limit_mb}
        filter_properties = {'limits': limits}
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(instance_mb, self.rt.compute_node['memory_mb_used'])

    def test_create_instance_with_oversubscribed_ram_fail(self):
        """Test passing of oversubscribed ram policy from the scheduler, but
        with insufficient memory.
        """
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource(NODENAME)
        total_mem_mb = resources['memory_mb']

        oversub_limit_mb = total_mem_mb * 1.5
        instance_mb = int(total_mem_mb * 1.55)

        # build an instance, specifying an amount of memory that exceeds
        # total_mem_mb, but is less than the oversubscribed limit:
        params = {"memory_mb": instance_mb, "root_gb": 128,
                  "ephemeral_gb": 128}
        instance = self._create_fake_instance(params)

        filter_properties = {'limits': {'memory_mb': oversub_limit_mb}}

        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_instance_with_oversubscribed_cpu(self):
        # Test passing of oversubscribed cpu policy from the scheduler.

        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())
        limits = {'vcpu': 3}
        filter_properties = {'limits': limits}

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource(NODENAME)
        self.assertEqual(1, resources['vcpus'])

        # build an instance, specifying an amount of memory that exceeds
        # total_mem_mb, but is less than the oversubscribed limit:
        params = {"memory_mb": 10, "root_gb": 1,
                  "ephemeral_gb": 1, "vcpus": 2}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(2, self.rt.compute_node['vcpus_used'])

        # create one more instance:
        params = {"memory_mb": 10, "root_gb": 1,
                  "ephemeral_gb": 1, "vcpus": 1}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(3, self.rt.compute_node['vcpus_used'])

        # delete the instance:
        instance['vm_state'] = vm_states.DELETED
        self.rt.update_usage(self.context,
                instance=instance)

        self.assertEqual(2, self.rt.compute_node['vcpus_used'])

        # now oversubscribe vcpus and fail:
        params = {"memory_mb": 10, "root_gb": 1,
                  "ephemeral_gb": 1, "vcpus": 2}
        instance = self._create_fake_instance(params)

        limits = {'vcpu': 3}
        filter_properties = {'limits': limits}
        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_instance_with_oversubscribed_disk(self):
        # Test passing of oversubscribed disk policy from the scheduler.

        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource(NODENAME)
        total_disk_gb = resources['local_gb']

        oversub_limit_gb = total_disk_gb * 1.5
        instance_gb = int(total_disk_gb * 1.45)

        # build an instance, specifying an amount of disk that exceeds
        # total_disk_gb, but is less than the oversubscribed limit:
        params = {"root_gb": instance_gb, "memory_mb": 10}
        instance = self._create_fake_instance(params)

        limits = {'disk_gb': oversub_limit_gb}
        filter_properties = {'limits': limits}
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(instance_gb, self.rt.compute_node['local_gb_used'])

    def test_create_instance_with_oversubscribed_disk_fail(self):
        """Test passing of oversubscribed disk policy from the scheduler, but
        with insufficient disk.
        """
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.rt.update_available_resource(self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource(NODENAME)
        total_disk_gb = resources['local_gb']

        oversub_limit_gb = total_disk_gb * 1.5
        instance_gb = int(total_disk_gb * 1.55)

        # build an instance, specifying an amount of disk that exceeds
        # total_disk_gb, but is less than the oversubscribed limit:
        params = {"root_gb": instance_gb, "memory_mb": 10}
        instance = self._create_fake_instance(params)

        limits = {'disk_gb': oversub_limit_gb}
        filter_properties = {'limits': limits}
        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_instance_without_node_param(self):
        instance = self._create_fake_instance({'node': None})

        self.compute.run_instance(self.context, instance=instance)
        instances = db.instance_get_all(self.context)
        instance = instances[0]

        self.assertEqual(NODENAME, instance['node'])

    def test_create_instance_no_image(self):
        # Create instance with no image provided.
        params = {'image_ref': ''}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance)
        self._assert_state({'vm_state': vm_states.ACTIVE,
                            'task_state': None})

    def test_default_access_ip(self):
        self.flags(default_access_ip_network_name='test1')
        fake_network.unset_stub_network_methods(self.stubs)
        instance = jsonutils.to_primitive(self._create_fake_instance())

        orig_update = self.compute._instance_update

        # Make sure the access_ip_* updates happen in the same DB
        # update as the set to ACTIVE.
        def _instance_update(ctxt, instance_uuid, **kwargs):
            if kwargs.get('vm_state', None) == vm_states.ACTIVE:
                self.assertEqual(kwargs['access_ip_v4'], '192.168.1.100')
                self.assertEqual(kwargs['access_ip_v6'], '2001:db8:0:1::1')
            return orig_update(ctxt, instance_uuid, **kwargs)

        self.stubs.Set(self.compute, '_instance_update', _instance_update)

        try:
            self.compute.run_instance(self.context, instance=instance,
                    is_first_time=True)
            instances = db.instance_get_all(self.context)
            instance = instances[0]

            self.assertEqual(instance['access_ip_v4'], '192.168.1.100')
            self.assertEqual(instance['access_ip_v6'], '2001:db8:0:1::1')
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_no_default_access_ip(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())

        try:
            self.compute.run_instance(self.context, instance=instance,
                    is_first_time=True)
            instances = db.instance_get_all(self.context)
            instance = instances[0]

            self.assertFalse(instance['access_ip_v4'])
            self.assertFalse(instance['access_ip_v6'])
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_fail_to_schedule_persists(self):
        # check the persistence of the ERROR(scheduling) state.
        params = {'vm_state': vm_states.ERROR,
                  'task_state': task_states.SCHEDULING}
        self._create_fake_instance(params=params)
        #check state is failed even after the periodic poll
        self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.SCHEDULING})

    def test_run_instance_setup_block_device_mapping_fail(self):
        """block device mapping failure test.

        Make sure that when there is a block device mapping problem,
        the instance goes to ERROR state, keeping the task state
        """
        def fake(*args, **kwargs):
            raise exception.InvalidBDM()
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       '_prep_block_device', fake)
        instance = self._create_fake_instance()
        self.assertRaises(exception.InvalidBDM, self.compute.run_instance,
                          self.context, instance=instance)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})
        self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})

    def test_run_instance_spawn_fail(self):
        """spawn failure test.

        Make sure that when there is a spawning problem,
        the instance goes to ERROR state, keeping the task state.
        """
        def fake(*args, **kwargs):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver, 'spawn', fake)
        instance = self._create_fake_instance()
        self.assertRaises(test.TestingException, self.compute.run_instance,
                          self.context, instance=instance)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})
        self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})

    def test_run_instance_dealloc_network_instance_not_found(self):
        """spawn network deallocate test.

        Make sure that when an instance is not found during spawn
        that the network is deallocated
        """
        instance = self._create_fake_instance()

        def fake(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id="fake")

        self.stubs.Set(self.compute.driver, 'spawn', fake)
        self.mox.StubOutWithMock(self.compute, '_deallocate_network')
        self.compute._deallocate_network(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        self.compute.run_instance(self.context, instance=instance)

    def test_run_instance_bails_on_missing_instance(self):
        # Make sure that run_instance() will quickly ignore a deleted instance
        called = {}
        instance = self._create_fake_instance()

        def fake_instance_update(self, *a, **args):
            called['instance_update'] = True
            raise exception.InstanceNotFound(instance_id='foo')
        self.stubs.Set(self.compute, '_instance_update', fake_instance_update)

        self.compute.run_instance(self.context, instance)
        self.assertIn('instance_update', called)

    def test_can_terminate_on_error_state(self):
        # Make sure that the instance can be terminated in ERROR state.
        #check failed to schedule --> terminate
        params = {'vm_state': vm_states.ERROR}
        instance = self._create_fake_instance(params=params)
        self.compute.terminate_instance(self.context, instance=instance)
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          self.context, instance['uuid'])
        # Double check it's not there for admins, either.
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          self.context.elevated(), instance['uuid'])

    def test_run_terminate(self):
        # Make sure it is possible to  run and terminate instance.
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        self.compute.terminate_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)

        admin_deleted_context = context.get_admin_context(
                read_deleted="only")
        instance = db.instance_get_by_uuid(admin_deleted_context,
                                           instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.DELETED)
        self.assertEqual(instance['task_state'], None)

    def test_run_terminate_with_vol_attached(self):
        """Make sure it is possible to  run and terminate instance with volume
        attached
        """
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        def fake_check_attach(*args, **kwargs):
            pass

        def fake_reserve_volume(*args, **kwargs):
            pass

        def fake_volume_get(self, context, volume_id):
            return {'id': volume_id}

        def fake_rpc_reserve_block_device_name(self, context, **kwargs):
            pass

        self.stubs.Set(cinder.API, 'get', fake_volume_get)
        self.stubs.Set(cinder.API, 'check_attach', fake_check_attach)
        self.stubs.Set(cinder.API, 'reserve_volume',
                       fake_reserve_volume)
        self.stubs.Set(compute_rpcapi.ComputeAPI,
                       'reserve_block_device_name',
                       fake_rpc_reserve_block_device_name)

        self.compute_api.attach_volume(self.context, instance, 1,
                                       '/dev/vdc')

        self.compute.terminate_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)
        bdms = db.block_device_mapping_get_all_by_instance(self.context,
                                                           instance['uuid'])
        self.assertEqual(len(bdms), 0)

    def test_run_terminate_no_image(self):
        """
        Make sure instance started without image (from volume)
        can be termintad without issues
        """
        params = {'image_ref': ''}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance)
        self._assert_state({'vm_state': vm_states.ACTIVE,
                            'task_state': None})

        self.compute.terminate_instance(self.context, instance=instance)
        instances = db.instance_get_all(self.context)
        self.assertEqual(len(instances), 0)

    def test_terminate_no_network(self):
        # This is as reported in LP bug 1008875
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        # Make it look like this is no instance
        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.compute._get_instance_nw_info(
                mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(
                    exception.NetworkNotFound(network_id='fake')
                )
        self.mox.ReplayAll()

        self.compute.terminate_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)

    def test_terminate_no_fixed_ips(self):
        # This is as reported in LP bug 1192893
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.compute._get_instance_nw_info(
                mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(
                    exception.NoMoreFixedIps()
                )
        self.mox.ReplayAll()

        self.compute.terminate_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)

    def test_run_terminate_timestamps(self):
        # Make sure timestamps are set for launched and destroyed.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance['launched_at'] = None
        self.assertEqual(instance['launched_at'], None)
        self.assertEqual(instance['deleted_at'], None)
        launch = timeutils.utcnow()
        self.compute.run_instance(self.context, instance=instance)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assert_(instance['launched_at'] > launch)
        self.assertEqual(instance['deleted_at'], None)
        terminate = timeutils.utcnow()
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))
        with utils.temporary_mutation(self.context, read_deleted='only'):
            instance = db.instance_get_by_uuid(self.context,
                    instance['uuid'])
        self.assert_(instance['launched_at'] < terminate)
        self.assert_(instance['deleted_at'] > terminate)

    def test_run_terminate_deallocate_net_failure_sets_error_state(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        def _fake_deallocate_network(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.compute, '_deallocate_network',
                _fake_deallocate_network)

        try:
            self.compute.terminate_instance(self.context, instance=instance)
        except test.TestingException:
            pass

        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)

    def test_stop(self):
        # Ensure instance can be stopped.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.POWERING_OFF})
        inst_uuid = instance['uuid']
        extra = ['system_metadata', 'metadata']
        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     inst_uuid,
                                                     expected_attrs=extra)
        self.compute.stop_instance(self.context, instance=inst_obj)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_start(self):
        # Ensure instance can be started.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.POWERING_OFF})
        extra = ['system_metadata', 'metadata']
        inst_uuid = instance['uuid']
        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     inst_uuid,
                                                     expected_attrs=extra)
        self.compute.stop_instance(self.context, instance=inst_obj)
        inst_obj.task_state = task_states.POWERING_ON
        inst_obj.save(self.context)
        self.compute.start_instance(self.context, instance=inst_obj)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_stop_start_no_image(self):
        params = {'image_ref': ''}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.POWERING_OFF})
        extra = ['system_metadata', 'metadata']
        inst_uuid = instance['uuid']
        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     inst_uuid,
                                                     expected_attrs=extra)
        self.compute.stop_instance(self.context, instance=inst_obj)
        inst_obj.task_state = task_states.POWERING_ON
        inst_obj.save(self.context)
        self.compute.start_instance(self.context, instance=inst_obj)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_rescue(self):
        # Ensure instance can be rescued and unrescued.

        called = {'rescued': False,
                  'unrescued': False}

        def fake_rescue(self, context, instance_ref, network_info, image_meta,
                        rescue_password):
            called['rescued'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'rescue', fake_rescue)

        def fake_unrescue(self, instance_ref, network_info):
            called['unrescued'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'unrescue',
                       fake_unrescue)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        db.instance_update(self.context, instance_uuid,
                           {"task_state": task_states.RESCUING})
        self.compute.rescue_instance(self.context, instance=instance)
        self.assertTrue(called['rescued'])
        db.instance_update(self.context, instance_uuid,
                           {"task_state": task_states.UNRESCUING})
        self.compute.unrescue_instance(self.context, instance=instance)
        self.assertTrue(called['unrescued'])

        self.compute.terminate_instance(self.context, instance=instance)

    def test_rescue_notifications(self):
        # Ensure notifications on instance rescue.
        def fake_rescue(self, context, instance_ref, network_info, image_meta,
                        rescue_password):
            pass
        self.stubs.Set(nova.virt.fake.FakeDriver, 'rescue', fake_rescue)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        fake_notifier.NOTIFICATIONS = []
        db.instance_update(self.context, instance_uuid,
                           {"task_state": task_states.RESCUING})
        self.compute.rescue_instance(self.context, instance=instance)

        expected_notifications = ['compute.instance.exists',
                                  'compute.instance.rescue.start',
                                  'compute.instance.rescue.end']
        self.assertEquals([m.event_type for m in fake_notifier.NOTIFICATIONS],
                          expected_notifications)
        for n, msg in enumerate(fake_notifier.NOTIFICATIONS):
            self.assertEquals(msg.event_type, expected_notifications[n])
            self.assertEquals(msg.priority, 'INFO')
            payload = msg.payload
            self.assertEquals(payload['tenant_id'], self.project_id)
            self.assertEquals(payload['user_id'], self.user_id)
            self.assertEquals(payload['instance_id'], instance_uuid)
            self.assertEquals(payload['instance_type'], 'm1.tiny')
            type_id = flavors.get_flavor_by_name('m1.tiny')['id']
            self.assertEquals(str(payload['instance_type_id']), str(type_id))
            self.assertTrue('display_name' in payload)
            self.assertTrue('created_at' in payload)
            self.assertTrue('launched_at' in payload)
            image_ref_url = glance.generate_image_url(FAKE_IMAGE_REF)
            self.assertEquals(payload['image_ref_url'], image_ref_url)
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertTrue('rescue_image_name' in msg.payload)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_unrescue_notifications(self):
        # Ensure notifications on instance rescue.
        def fake_unrescue(self, instance_ref, network_info):
            pass
        self.stubs.Set(nova.virt.fake.FakeDriver, 'unrescue',
                       fake_unrescue)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        fake_notifier.NOTIFICATIONS = []
        db.instance_update(self.context, instance_uuid,
                           {"task_state": task_states.UNRESCUING})
        self.compute.unrescue_instance(self.context, instance=instance)

        expected_notifications = ['compute.instance.unrescue.start',
                                  'compute.instance.unrescue.end']
        self.assertEquals([m.event_type for m in fake_notifier.NOTIFICATIONS],
                          expected_notifications)
        for n, msg in enumerate(fake_notifier.NOTIFICATIONS):
            self.assertEquals(msg.event_type, expected_notifications[n])
            self.assertEquals(msg.priority, 'INFO')
            payload = msg.payload
            self.assertEquals(payload['tenant_id'], self.project_id)
            self.assertEquals(payload['user_id'], self.user_id)
            self.assertEquals(payload['instance_id'], instance_uuid)
            self.assertEquals(payload['instance_type'], 'm1.tiny')
            type_id = flavors.get_flavor_by_name('m1.tiny')['id']
            self.assertEquals(str(payload['instance_type_id']), str(type_id))
            self.assertTrue('display_name' in payload)
            self.assertTrue('created_at' in payload)
            self.assertTrue('launched_at' in payload)
            image_ref_url = glance.generate_image_url(FAKE_IMAGE_REF)
            self.assertEquals(payload['image_ref_url'], image_ref_url)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_rescue_handle_err(self):
        # If the driver fails to rescue, instance state should remain the same
        # and the exception should be converted to InstanceNotRescuable
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.mox.StubOutWithMock(self.compute, '_get_rescue_image')
        self.mox.StubOutWithMock(nova.virt.fake.FakeDriver, 'rescue')

        self.compute._get_rescue_image(
            mox.IgnoreArg(), instance).AndReturn({})
        nova.virt.fake.FakeDriver.rescue(
            mox.IgnoreArg(), instance, [], mox.IgnoreArg(), 'password'
            ).AndRaise(RuntimeError("Try again later"))

        self.mox.ReplayAll()

        expected_message = ('Instance %s cannot be rescued: '
                            'Driver Error: Try again later' % instance['uuid'])
        instance['vm_state'] = 'some_random_state'

        with testtools.ExpectedException(
                exception.InstanceNotRescuable, expected_message):
                self.compute.rescue_instance(
                    self.context, instance=instance,
                    rescue_password='password')

        self.assertEqual('some_random_state', instance['vm_state'])

    def test_power_on(self):
        # Ensure instance can be powered on.

        called = {'power_on': False}

        def fake_driver_power_on(self, context, instance, network_info,
                                 block_device_info):
            called['power_on'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'power_on',
                       fake_driver_power_on)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        extra = ['system_metadata', 'metadata']
        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     instance['uuid'],
                                                     expected_attrs=extra)
        inst_obj.task_state = task_states.POWERING_ON
        inst_obj.save(self.context)
        self.compute.start_instance(self.context, instance=inst_obj)
        self.assertTrue(called['power_on'])
        self.compute.terminate_instance(self.context, instance=inst_obj)

    def test_power_off(self):
        # Ensure instance can be powered off.

        called = {'power_off': False}

        def fake_driver_power_off(self, instance):
            called['power_off'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'power_off',
                       fake_driver_power_off)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        extra = ['system_metadata', 'metadata']
        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     instance['uuid'],
                                                     expected_attrs=extra)
        inst_obj.task_state = task_states.POWERING_OFF
        inst_obj.save(self.context)
        self.compute.stop_instance(self.context, instance=inst_obj)
        self.assertTrue(called['power_off'])
        self.compute.terminate_instance(self.context, instance=inst_obj)

    def test_pause(self):
        # Ensure instance can be paused and unpaused.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.PAUSING})
        fake_notifier.NOTIFICATIONS = []
        self.compute.pause_instance(self.context, instance=instance)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'compute.instance.pause.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'compute.instance.pause.end')
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.UNPAUSING})
        fake_notifier.NOTIFICATIONS = []
        self.compute.unpause_instance(self.context, instance=instance)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'compute.instance.unpause.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'compute.instance.unpause.end')
        self.compute.terminate_instance(self.context, instance=instance)

    def test_suspend(self):
        # ensure instance can be suspended and resumed.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.SUSPENDING})
        self.compute.suspend_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.RESUMING})
        self.compute.resume_instance(self.context, instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_suspend_error(self):
        # Ensure vm_state is ERROR when suspend error occurs.
        def fake(*args, **kwargs):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver, 'suspend', fake)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)
        self.assertRaises(test.TestingException,
                          self.compute.suspend_instance,
                          self.context,
                          instance=instance)
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_suspend_not_implemented(self):
        # Ensure expected exception is raised and the vm_state of instance
        # restore to original value if suspend is not implemented by driver
        def fake(*args, **kwargs):
            raise NotImplementedError('suspend test')
        self.stubs.Set(self.compute.driver, 'suspend', fake)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_state = instance['vm_state']

        self.compute.run_instance(self.context, instance=instance)
        self.assertRaises(NotImplementedError,
                          self.compute.suspend_instance,
                          self.context,
                          instance=instance)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance_state, instance['vm_state'])
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_rebuild(self):
        # Ensure instance can be rebuilt.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        image_ref = instance['image_ref']
        sys_metadata = db.instance_system_metadata_get(self.context,
                        instance['uuid'])
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context, instance,
                                      image_ref, image_ref,
                                      injected_files=[],
                                      new_pass="new_password",
                                      orig_sys_metadata=sys_metadata,
                                      bdms=[])
        self.compute.terminate_instance(self.context, instance=instance)

    def test_rebuild_no_image(self):
        # Ensure instance can be rebuilt when started with no image.
        params = {'image_ref': ''}
        instance = self._create_fake_instance(params)
        sys_metadata = db.instance_system_metadata_get(self.context,
                        instance['uuid'])
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context, instance,
                                      '', '', injected_files=[],
                                      new_pass="new_password",
                                      orig_sys_metadata=sys_metadata)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_rebuild_launched_at_time(self):
        # Ensure instance can be rebuilt.
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        image_ref = instance['image_ref']

        self.compute.run_instance(self.context, instance=instance)
        timeutils.set_time_override(cur_time)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context, instance,
                                      image_ref, image_ref,
                                      injected_files=[],
                                      new_pass="new_password",
                                      bdms=[])
        instance = db.instance_get_by_uuid(self.context, instance_uuid,)
        self.assertEquals(cur_time, instance['launched_at'])
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_rebuild_with_injected_files(self):
        # Ensure instance can be rebuilt with injected files.
        injected_files = [
            ('/a/b/c', base64.b64encode('foobarbaz')),
        ]

        self.decoded_files = [
            ('/a/b/c', 'foobarbaz'),
        ]

        def _spawn(context, instance, image_meta, injected_files,
                   admin_password, network_info, block_device_info):
            self.assertEqual(self.decoded_files, injected_files)

        self.stubs.Set(self.compute.driver, 'spawn', _spawn)
        instance = jsonutils.to_primitive(self._create_fake_instance())
        image_ref = instance['image_ref']
        sys_metadata = db.instance_system_metadata_get(self.context,
                        instance['uuid'])
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context, instance,
                                      image_ref, image_ref,
                                      injected_files=injected_files,
                                      new_pass="new_password",
                                      orig_sys_metadata=sys_metadata,
                                      bdms=[])
        self.compute.terminate_instance(self.context, instance=instance)

    def _test_reboot(self, soft,
                     test_delete=False, test_unrescue=False,
                     fail_reboot=False, fail_running=False):
        # This is a true unit test, so we don't need the network stubs.
        fake_network.unset_stub_network_methods(self.stubs)

        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_volume_block_device_info')
        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute, '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute, '_instance_update')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.compute.driver, 'reboot')

        # FIXME(comstud): I don't feel like the context needs to
        # be elevated at all.  Hopefully remove elevated from
        # reboot_instance and remove the stub here in a future patch.
        # econtext would just become self.context below then.
        econtext = self.context.elevated()

        db_instance = fake_instance.fake_db_instance(
            **dict(uuid='fake-instance',
                   power_state=power_state.NOSTATE,
                   vm_state=vm_states.ACTIVE,
                   launched_at=timeutils.utcnow()))
        instance = instance_obj.Instance._from_db_object(
            econtext, instance_obj.Instance(), db_instance)

        updated_dbinstance1 = fake_instance.fake_db_instance(
            **dict(uuid='updated-instance1',
                   power_state=10003,
                   vm_state=vm_states.ACTIVE,
                   launched_at=timeutils.utcnow()))
        updated_dbinstance2 = fake_instance.fake_db_instance(
            **dict(uuid='updated-instance2',
                   power_state=10003,
                   vm_state=vm_states.ACTIVE,
                   launched_at=timeutils.utcnow()))

        if test_unrescue:
            instance['vm_state'] = vm_states.RESCUED
        instance.obj_reset_changes()

        fake_nw_model = network_model.NetworkInfo()

        fake_block_dev_info = 'fake_block_dev_info'
        fake_power_state1 = 10001
        fake_power_state2 = power_state.RUNNING
        fake_power_state3 = 10002
        reboot_type = soft and 'SOFT' or 'HARD'

        # Beginning of calls we expect.

        self.mox.StubOutWithMock(self.context, 'elevated')
        self.context.elevated().AndReturn(econtext)

        self.compute._get_instance_volume_block_device_info(
            econtext, instance).AndReturn(fake_block_dev_info)
        self.compute._get_instance_nw_info(econtext,
                                           instance).AndReturn(
                                                   fake_nw_model)
        self.compute._notify_about_instance_usage(econtext,
                                                  instance,
                                                  'reboot.start')
        self.compute._get_power_state(econtext,
                instance).AndReturn(fake_power_state1)
        db.instance_update_and_get_original(econtext, instance['uuid'],
                                            {'power_state': fake_power_state1},
                                            update_cells=False,
                                            columns_to_join=['system_metadata']
                                            ).AndReturn((None,
                                                         updated_dbinstance1))

        expected_nw_info = fake_nw_model

        # Annoying.  driver.reboot is wrapped in a try/except, and
        # doesn't re-raise.  It eats exception generated by mox if
        # this is called with the wrong args, so we have to hack
        # around it.
        reboot_call_info = {}
        expected_call_info = {
            'args': (econtext, instance, expected_nw_info,
                     reboot_type),
            'kwargs': {'block_device_info': fake_block_dev_info}}

        def fake_reboot(*args, **kwargs):
            reboot_call_info['args'] = args
            reboot_call_info['kwargs'] = kwargs

            # NOTE(sirp): Since `bad_volumes_callback` is a function defined
            # within `reboot_instance`, we don't have access to its value and
            # can't stub it out, thus we skip that comparison.
            kwargs.pop('bad_volumes_callback')
            if fail_reboot:
                raise exception.InstanceNotFound(instance_id='instance-0000')

        self.stubs.Set(self.compute.driver, 'reboot', fake_reboot)

        # Power state should be updated again
        if not fail_reboot or fail_running:
            new_power_state = fake_power_state2
            self.compute._get_power_state(econtext,
                    instance).AndReturn(fake_power_state2)
        else:
            new_power_state = fake_power_state3
            self.compute._get_power_state(econtext,
                    instance).AndReturn(fake_power_state3)

        if test_delete:
            db.instance_update_and_get_original(
                econtext, updated_dbinstance1['uuid'],
                {'power_state': new_power_state,
                 'task_state': None,
                 'vm_state': vm_states.ACTIVE},
                update_cells=False,
                columns_to_join=['system_metadata'],
                ).AndRaise(exception.InstanceNotFound(
                    instance_id=instance['uuid']))
            self.compute._notify_about_instance_usage(
                econtext,
                instance,
                'reboot.end')
        elif fail_reboot and not fail_running:
            db.instance_update_and_get_original(
                econtext, updated_dbinstance1['uuid'],
                {'vm_state': vm_states.ERROR},
                update_cells=False,
                columns_to_join=['system_metadata'],
                ).AndRaise(exception.InstanceNotFound(
                    instance_id=instance['uuid']))
        else:
            db.instance_update_and_get_original(
                econtext, updated_dbinstance1['uuid'],
                {'power_state': new_power_state,
                 'task_state': None,
                 'vm_state': vm_states.ACTIVE},
                update_cells=False,
                columns_to_join=['system_metadata'],
                ).AndReturn((None, updated_dbinstance2))
            self.compute._notify_about_instance_usage(
                econtext,
                instance,
                'reboot.end')

        self.mox.ReplayAll()

        if not fail_reboot or fail_running:
            self.compute.reboot_instance(self.context, instance=instance,
                                         block_device_info=None,
                                         reboot_type=reboot_type)
        else:
            self.assertRaises(exception.InstanceNotFound,
                              self.compute.reboot_instance,
                              self.context, instance=instance,
                              block_device_info=None,
                              reboot_type=reboot_type)

        self.assertEqual(expected_call_info, reboot_call_info)

    def test_reboot_soft(self):
        self._test_reboot(True)

    def test_reboot_soft_and_delete(self):
        self._test_reboot(True, True)

    def test_reboot_soft_and_rescued(self):
        self._test_reboot(True, False, True)

    def test_reboot_soft_and_delete_and_rescued(self):
        self._test_reboot(True, True, True)

    def test_reboot_hard(self):
        self._test_reboot(False)

    def test_reboot_hard_and_delete(self):
        self._test_reboot(False, True)

    def test_reboot_hard_and_rescued(self):
        self._test_reboot(False, False, True)

    def test_reboot_hard_and_delete_and_rescued(self):
        self._test_reboot(False, True, True)

    def test_reboot_fail(self):
        self._test_reboot(False, fail_reboot=True)

    def test_reboot_fail_running(self):
        self._test_reboot(False, fail_reboot=True,
                          fail_running=True)

    def test_get_instance_volume_block_device_info_source_image(self):
        def _fake_get_instance_volume_bdms(context, instance, legacy=True):
            bdms = [{
                'id': 3,
                'volume_id': u'4cbc9e62-6ba0-45dd-b647-934942ead7d6',
                'instance_uuid': 'fake-instance',
                'device_name': '/dev/vda',
                'connection_info': '{"driver_volume_type": "rbd"}',
                'source_type': 'image',
                'destination_type': 'volume',
                'image_id': 'fake-image-id-1',
                'boot_index': 0
            }]

            return bdms

        with mock.patch.object(self.compute, '_get_instance_volume_bdms',
                               _fake_get_instance_volume_bdms):
            block_device_info = (
                self.compute._get_instance_volume_block_device_info(
                    self.context, self._create_fake_instance())
            )
            expected = {
                'block_device_mapping': [{
                    'connection_info': {
                        'driver_volume_type': 'rbd'
                    },
                    'mount_device': '/dev/vda',
                    'delete_on_termination': None
                }]
            }
            self.assertEqual(block_device_info, expected)

    def test_set_admin_password(self):
        # Ensure instance can have its admin password set.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.UPDATING_PASSWORD})

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

        self.compute.set_admin_password(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_set_admin_password_bad_state(self):
        # Test setting password while instance is rebuilding.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'], {
            "power_state": power_state.NOSTATE,
        })
        instance = jsonutils.to_primitive(db.instance_get_by_uuid(
                                          self.context, instance['uuid']))

        self.assertEqual(instance['power_state'], power_state.NOSTATE)

        def fake_driver_get_info(self2, _instance):
            return {'state': power_state.NOSTATE,
                    'max_mem': 0,
                    'mem': 0,
                    'num_cpu': 2,
                    'cpu_time': 0}

        self.stubs.Set(nova.virt.fake.FakeDriver, 'get_info',
                       fake_driver_get_info)

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.UPDATING_PASSWORD})
        self.assertRaises(exception.InstancePasswordSetFailed,
                          self.compute.set_admin_password,
                          self.context,
                          instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def _do_test_set_admin_password_driver_error(self, exc, expected_vm_state,
                                                 expected_task_state,
                                                 expected_exception):
        """Ensure expected exception is raised if set_admin_password fails."""

        def fake_sleep(_time):
            pass

        self.stubs.Set(time, 'sleep', fake_sleep)

        def fake_driver_set_pass(self2, _instance, _pwd):
            raise exc

        self.stubs.Set(nova.virt.fake.FakeDriver, 'set_admin_password',
                       fake_driver_set_pass)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.UPDATING_PASSWORD})

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

        #error raised from the driver should not reveal internal information
        #so a new error is raised
        self.assertRaises(expected_exception,
                          self.compute.set_admin_password,
                          self.context,
                          instance=jsonutils.to_primitive(inst_ref))

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], expected_vm_state)
        self.assertEqual(inst_ref['task_state'], expected_task_state)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_set_admin_password_driver_not_authorized(self):
        """
        Ensure expected exception is raised if set_admin_password not
        authorized.
        """
        exc = exception.NotAuthorized(_('Internal error'))
        expected_exception = exception.InstancePasswordSetFailed
        self._do_test_set_admin_password_driver_error(exc,
                                                vm_states.ERROR,
                                                None,
                                                expected_exception)

    def test_set_admin_password_driver_not_implemented(self):
        """
        Ensure expected exception is raised if set_admin_password not
        implemented by driver.
        """
        exc = NotImplementedError()
        expected_exception = NotImplementedError
        self._do_test_set_admin_password_driver_error(exc,
                                                      vm_states.ACTIVE,
                                                      None,
                                                      expected_exception)

    def test_inject_file(self):
        # Ensure we can write a file to an instance.
        called = {'inject': False}

        def fake_driver_inject_file(self2, instance, path, contents):
            self.assertEqual(path, "/tmp/test")
            self.assertEqual(contents, "File Contents")
            called['inject'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'inject_file',
                       fake_driver_inject_file)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        self.compute.inject_file(self.context, "/tmp/test",
                "File Contents", instance=instance)
        self.assertTrue(called['inject'])
        self.compute.terminate_instance(self.context, instance=instance)

    def test_inject_network_info(self):
        # Ensure we can inject network info.
        called = {'inject': False}

        def fake_driver_inject_network(self, instance, network_info):
            called['inject'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'inject_network_info',
                       fake_driver_inject_network)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        inst_obj = self._objectify(instance)
        self.compute.inject_network_info(self.context, instance=inst_obj)
        self.assertTrue(called['inject'])
        self.compute.terminate_instance(self.context, instance=instance)

    def test_reset_network(self):
        # Ensure we can reset networking on an instance.
        called = {'count': 0}

        def fake_driver_reset_network(self, instance):
            called['count'] += 1

        self.stubs.Set(nova.virt.fake.FakeDriver, 'reset_network',
                       fake_driver_reset_network)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        self.compute.reset_network(self.context,
                                   instance=self._objectify(instance))

        self.assertEqual(called['count'], 1)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_live_snapshot(self):
        # Ensure instance can be live_snapshotted.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        name = "myfakesnapshot"
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.IMAGE_LIVE_SNAPSHOT})
        self.compute.live_snapshot_instance(self.context, name,
                                            instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_live_snapshot_fails(self):
        # Ensure task_state is set to None if snapshot fails.
        def fake_live_snapshot(*args, **kwargs):
            raise test.TestingException()

        self.fake_image_delete_called = False

        def fake_delete(self_, context, image_id):
            self.fake_image_delete_called = True

        self.stubs.Set(self.compute.driver, 'live_snapshot',
                       fake_live_snapshot)
        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'delete', fake_delete)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.IMAGE_LIVE_SNAPSHOT})
        self.assertRaises(test.TestingException,
                          self.compute.live_snapshot_instance,
                          self.context, "failing_snapshot", instance=instance)
        self.assertTrue(self.fake_image_delete_called)
        self._assert_state({'task_state': None})
        self.compute.terminate_instance(self.context, instance=instance)

    def _get_snapshotting_instance(self):
        # Ensure instance can be snapshotted.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        instance = db.instance_update(
                self.context, instance['uuid'],
                {"task_state": task_states.IMAGE_SNAPSHOT})
        return self._objectify(instance)

    def test_snapshot(self):
        inst_obj = self._get_snapshotting_instance()
        self.compute.snapshot_instance(self.context, image_id='fakesnap',
                                       instance=inst_obj)

    def test_snapshot_no_image(self):
        inst_obj = self._get_snapshotting_instance()
        inst_obj.image_ref = ''
        inst_obj.save()
        self.compute.snapshot_instance(self.context, image_id='fakesnap',
                                       instance=inst_obj)

    def _test_snapshot_fails(self, raise_during_cleanup):
        def fake_snapshot(*args, **kwargs):
            raise test.TestingException()

        self.fake_image_delete_called = False

        def fake_delete(self_, context, image_id):
            self.fake_image_delete_called = True
            if raise_during_cleanup:
                raise Exception()

        self.stubs.Set(self.compute.driver, 'snapshot', fake_snapshot)
        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'delete', fake_delete)

        inst_obj = self._get_snapshotting_instance()
        self.assertRaises(test.TestingException,
                          self.compute.snapshot_instance,
                          self.context, image_id='fakesnap',
                          instance=inst_obj)
        self.assertTrue(self.fake_image_delete_called)
        self._assert_state({'task_state': None})

    def test_snapshot_fails(self):
        self._test_snapshot_fails(False)

    def test_snapshot_fails_cleanup_ignores_exception(self):
        self._test_snapshot_fails(True)

    def test_snapshot_fails_with_glance_error(self):
        def fake_snapshot(*args, **kwargs):
            raise exception.ImageNotFound(image_id='xxx')

        self.stubs.Set(self.compute.driver, 'snapshot', fake_snapshot)
        fake_image.stub_out_image_service(self.stubs)

        inst_obj = self._get_snapshotting_instance()

        self.compute.snapshot_instance(
                          self.context, image_id='fakesnap',
                          instance=inst_obj)
        self._assert_state({'task_state': None})

    def test_snapshot_handles_cases_when_instance_is_deleted(self):
        inst_obj = self._get_snapshotting_instance()
        inst_obj.task_state = task_states.DELETING
        inst_obj.save()
        self.compute.snapshot_instance(self.context, image_id='fakesnap',
                                       instance=inst_obj)

    def test_snapshot_handles_cases_when_instance_is_not_found(self):
        inst_obj = self._get_snapshotting_instance()
        inst_obj2 = instance_obj.Instance.get_by_uuid(self.context,
                                                      inst_obj.uuid)
        inst_obj2.destroy()
        self.compute.snapshot_instance(self.context, image_id='fakesnap',
                                       instance=inst_obj)

    def _assert_state(self, state_dict):
        """Assert state of VM is equal to state passed as parameter."""
        instances = db.instance_get_all(self.context)
        self.assertEqual(len(instances), 1)

        if 'vm_state' in state_dict:
            self.assertEqual(state_dict['vm_state'], instances[0]['vm_state'])
        if 'task_state' in state_dict:
            self.assertEqual(state_dict['task_state'],
                             instances[0]['task_state'])
        if 'power_state' in state_dict:
            self.assertEqual(state_dict['power_state'],
                             instances[0]['power_state'])

    def test_console_output(self):
        # Make sure we can get console output from instance.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        output = self.compute.get_console_output(self.context,
                instance=instance)
        self.assertEqual(output, 'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE')
        self.compute.terminate_instance(self.context, instance=instance)

    def test_console_output_tail(self):
        # Make sure we can get console output from instance.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        output = self.compute.get_console_output(self.context,
                instance=instance, tail_length=2)
        self.assertEqual(output, 'ANOTHER\nLAST LINE')
        self.compute.terminate_instance(self.context, instance=instance)

    def test_novnc_vnc_console(self):
        # Make sure we can a vnc console for an instance.
        self.flags(vnc_enabled=True)
        self.flags(enabled=False, group='spice')

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        # Try with the full instance
        console = self.compute.get_vnc_console(self.context, 'novnc',
                                               instance=instance)
        self.assert_(console)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_validate_console_port_vnc(self):
        self.flags(vnc_enabled=True)
        self.flags(enabled=True, group='spice')
        instance = jsonutils.to_primitive(self._create_fake_instance())

        def fake_driver_get_console(*args, **kwargs):
            return {'host': "fake_host", 'port': "5900",
                    'internal_access_path': None}
        self.stubs.Set(self.compute.driver, "get_vnc_console",
                       fake_driver_get_console)

        self.assertTrue(self.compute.validate_console_port(self.context,
                                                            instance,
                                                            "5900",
                                                            "novnc"))

    def test_validate_console_port_spice(self):
        self.flags(vnc_enabled=True)
        self.flags(enabled=True, group='spice')
        instance = jsonutils.to_primitive(self._create_fake_instance())

        def fake_driver_get_console(*args, **kwargs):
            return {'host': "fake_host", 'port': "5900",
                    'internal_access_path': None}
        self.stubs.Set(self.compute.driver, "get_spice_console",
                       fake_driver_get_console)

        self.assertTrue(self.compute.validate_console_port(self.context,
                                                            instance,
                                                            "5900",
                                                            "spice-html5"))

    def test_validate_console_port_wrong_port(self):
        self.flags(vnc_enabled=True)
        self.flags(enabled=True, group='spice')
        instance = jsonutils.to_primitive(self._create_fake_instance())

        def fake_driver_get_console(*args, **kwargs):
            return {'host': "fake_host", 'port': "5900",
                    'internal_access_path': None}
        self.stubs.Set(self.compute.driver, "get_vnc_console",
                       fake_driver_get_console)

        self.assertFalse(self.compute.validate_console_port(self.context,
                                                            instance,
                                                            "wrongport",
                                                            "spice-html5"))

    def test_xvpvnc_vnc_console(self):
        # Make sure we can a vnc console for an instance.
        self.flags(vnc_enabled=True)
        self.flags(enabled=False, group='spice')

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        console = self.compute.get_vnc_console(self.context, 'xvpvnc',
                                               instance=instance)
        self.assert_(console)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_invalid_vnc_console_type(self):
        # Raise useful error if console type is an unrecognised string.
        self.flags(vnc_enabled=True)
        self.flags(enabled=False, group='spice')

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(rpc_common.ClientException,
                          self.compute.get_vnc_console,
                          self.context, 'invalid', instance=instance)

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(exception.ConsoleTypeInvalid,
                          self.compute.get_vnc_console,
                          self.context, 'invalid', instance=instance)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_missing_vnc_console_type(self):
        # Raise useful error is console type is None.
        self.flags(vnc_enabled=True)
        self.flags(enabled=False, group='spice')

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(rpc_common.ClientException,
                          self.compute.get_vnc_console,
                          self.context, None, instance=instance)

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(exception.ConsoleTypeInvalid,
                          self.compute.get_vnc_console,
                          self.context, None, instance=instance)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_spicehtml5_spice_console(self):
        # Make sure we can a spice console for an instance.
        self.flags(vnc_enabled=False)
        self.flags(enabled=True, group='spice')

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        # Try with the full instance
        console = self.compute.get_spice_console(self.context, 'spice-html5',
                                               instance=instance)
        self.assert_(console)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_invalid_spice_console_type(self):
        # Raise useful error if console type is an unrecognised string
        self.flags(vnc_enabled=False)
        self.flags(enabled=True, group='spice')

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(rpc_common.ClientException,
                          self.compute.get_spice_console,
                          self.context, 'invalid', instance=instance)

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(exception.ConsoleTypeInvalid,
                          self.compute.get_spice_console,
                          self.context, 'invalid', instance=instance)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_missing_spice_console_type(self):
        # Raise useful error is console type is None
        self.flags(vnc_enabled=False)
        self.flags(enabled=True, group='spice')

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(rpc_common.ClientException,
                          self.compute.get_spice_console,
                          self.context, None, instance=instance)

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(exception.ConsoleTypeInvalid,
                          self.compute.get_spice_console,
                          self.context, None, instance=instance)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_vnc_console_instance_not_ready(self):
        self.flags(vnc_enabled=True)
        self.flags(enabled=False, group='spice')
        instance = self._create_fake_instance(
                params={'vm_state': vm_states.BUILDING})
        instance = jsonutils.to_primitive(instance)

        def fake_driver_get_console(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id=instance['uuid'])

        self.stubs.Set(self.compute.driver, "get_vnc_console",
                       fake_driver_get_console)

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(exception.InstanceNotReady,
                self.compute.get_vnc_console, self.context, 'novnc',
                instance=instance)

    def test_spice_console_instance_not_ready(self):
        self.flags(vnc_enabled=False)
        self.flags(enabled=True, group='spice')
        instance = self._create_fake_instance(
                params={'vm_state': vm_states.BUILDING})
        instance = jsonutils.to_primitive(instance)

        def fake_driver_get_console(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id=instance['uuid'])

        self.stubs.Set(self.compute.driver, "get_spice_console",
                       fake_driver_get_console)

        self.compute = utils.ExceptionHelper(self.compute)

        self.assertRaises(exception.InstanceNotReady,
                self.compute.get_spice_console, self.context, 'spice-html5',
                instance=instance)

    def test_diagnostics(self):
        # Make sure we can get diagnostics for an instance.
        expected_diagnostic = {'cpu0_time': 17300000000,
                             'memory': 524288,
                             'vda_errors': -1,
                             'vda_read': 262144,
                             'vda_read_req': 112,
                             'vda_write': 5778432,
                             'vda_write_req': 488,
                             'vnet1_rx': 2070139,
                             'vnet1_rx_drop': 0,
                             'vnet1_rx_errors': 0,
                             'vnet1_rx_packets': 26701,
                             'vnet1_tx': 140208,
                             'vnet1_tx_drop': 0,
                             'vnet1_tx_errors': 0,
                             'vnet1_tx_packets': 662,
                            }

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        diagnostics = self.compute.get_diagnostics(self.context,
                instance=instance)
        self.assertEqual(diagnostics, expected_diagnostic)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_add_fixed_ip_usage_notification(self):
        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(network_api.API, 'add_fixed_ip_to_instance',
                       dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'inject_network_info', dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'reset_network', dummy)

        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 0)
        self.compute.add_fixed_ip_to_instance(self.context, network_id=1,
                instance=instance)

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 2)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_remove_fixed_ip_usage_notification(self):
        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(network_api.API, 'remove_fixed_ip_from_instance',
                       dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'inject_network_info', dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'reset_network', dummy)

        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 0)
        self.compute.remove_fixed_ip_from_instance(self.context, 1,
                                                   instance=instance)

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 2)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_run_instance_usage_notification(self):
        # Ensure run instance generates appropriate usage notification.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)
        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 2)
        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.event_type, 'compute.instance.create.start')
        self.assertEquals(msg.payload['image_name'], 'fake_name')
        # The last event is the one with the sugar in it.
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg.priority, 'INFO')
        self.assertEquals(msg.event_type, 'compute.instance.create.end')
        payload = msg.payload
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['image_name'], 'fake_name')
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], inst_ref['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEquals(str(payload['instance_flavor_id']), str(flavor_id))
        self.assertEquals(payload['state'], 'active')
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertTrue('fixed_ips' in payload)
        self.assertTrue(payload['launched_at'])
        image_ref_url = glance.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.assertEqual('Success', payload['message'])
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_run_instance_end_notification_on_abort(self):
        # Test that an end notif is sent if the build is aborted
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']

        def build_inst_abort(*args, **kwargs):
            raise exception.BuildAbortException(reason="already deleted",
                    instance_uuid=instance_uuid)

        self.stubs.Set(self.compute, '_build_instance', build_inst_abort)

        self.compute.run_instance(self.context, instance=instance)
        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.event_type, 'compute.instance.create.start')
        msg = fake_notifier.NOTIFICATIONS[1]

        self.assertEquals(msg.event_type, 'compute.instance.create.end')
        self.assertEquals('INFO', msg.priority)
        payload = msg.payload
        message = payload['message']
        self.assertTrue(message.find("already deleted") != -1)

    def test_run_instance_error_notification_on_reschedule(self):
        # Test that error notif is sent if the build got rescheduled
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']

        def build_inst_fail(*args, **kwargs):
            raise exception.RescheduledException(instance_uuid=instance_uuid,
                    reason="something bad happened")

        self.stubs.Set(self.compute, '_build_instance', build_inst_fail)

        self.compute.run_instance(self.context, instance=instance)

        self.assertTrue(len(fake_notifier.NOTIFICATIONS) >= 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.event_type, 'compute.instance.create.start')
        msg = fake_notifier.NOTIFICATIONS[1]

        self.assertEquals(msg.event_type, 'compute.instance.create.error')
        self.assertEquals('ERROR', msg.priority)
        payload = msg.payload
        message = payload['message']
        self.assertTrue(message.find("something bad happened") != -1)

    def test_run_instance_error_notification_on_failure(self):
        # Test that error notif is sent if build fails hard
        instance = jsonutils.to_primitive(self._create_fake_instance())

        def build_inst_fail(*args, **kwargs):
            raise test.TestingException("i'm dying")

        self.stubs.Set(self.compute, '_build_instance', build_inst_fail)

        self.assertRaises(test.TestingException, self.compute.run_instance,
                self.context, instance=instance)

        self.assertTrue(len(fake_notifier.NOTIFICATIONS) >= 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.event_type, 'compute.instance.create.start')
        msg = fake_notifier.NOTIFICATIONS[1]

        self.assertEquals(msg.event_type, 'compute.instance.create.error')
        self.assertEquals('ERROR', msg.priority)
        payload = msg.payload
        message = payload['message']
        self.assertTrue(message.find("i'm dying") != -1)

    def test_terminate_usage_notification(self):
        # Ensure terminate_instance generates correct usage notification.
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        fake_notifier.NOTIFICATIONS = []
        timeutils.set_time_override(cur_time)
        self.compute.terminate_instance(self.context, instance=instance)

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 4)

        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.priority, 'INFO')
        self.assertEquals(msg.event_type, 'compute.instance.delete.start')
        msg1 = fake_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg1.event_type, 'compute.instance.shutdown.start')
        msg1 = fake_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg1.event_type, 'compute.instance.shutdown.end')
        msg1 = fake_notifier.NOTIFICATIONS[3]
        self.assertEquals(msg1.event_type, 'compute.instance.delete.end')
        payload = msg1.payload
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEquals(str(payload['instance_flavor_id']), str(flavor_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertTrue('terminated_at' in payload)
        self.assertTrue('deleted_at' in payload)
        self.assertEqual(payload['terminated_at'], timeutils.strtime(cur_time))
        image_ref_url = glance.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)

    def test_run_instance_existing(self):
        # Ensure failure when running an instance that already exists.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        self.assertRaises(exception.InstanceExists,
                          self.compute.run_instance,
                          self.context,
                          instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_run_instance_queries_macs(self):
        # run_instance should ask the driver for node mac addresses and pass
        # that to the network_api in use.
        fake_network.unset_stub_network_methods(self.stubs)
        instance = jsonutils.to_primitive(self._create_fake_instance())

        macs = set(['01:23:45:67:89:ab'])
        self.mox.StubOutWithMock(self.compute.network_api,
                                 "allocate_for_instance")
        self.compute.network_api.allocate_for_instance(
            mox.IgnoreArg(),
            mox.IgnoreArg(),
            requested_networks=None,
            vpn=False, macs=macs,
            conductor_api=self.compute.conductor_api,
            security_groups=[], dhcp_options=None).AndReturn(
                fake_network.fake_get_instance_nw_info(self.stubs, 1, 1))

        self.mox.StubOutWithMock(self.compute.driver, "macs_for_instance")
        self.compute.driver.macs_for_instance(instance).AndReturn(macs)
        self.mox.ReplayAll()
        self.compute.run_instance(self.context, instance=instance)

    def test_instance_set_to_error_on_uncaught_exception(self):
        # Test that instance is set to error state when exception is raised.
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.mox.StubOutWithMock(self.compute.network_api,
                                 "allocate_for_instance")
        self.mox.StubOutWithMock(self.compute.network_api,
                                 "deallocate_for_instance")
        self.compute.network_api.allocate_for_instance(
                mox.IgnoreArg(),
                mox.IgnoreArg(),
                requested_networks=None,
                vpn=False, macs=None,
                conductor_api=self.compute.conductor_api,
                security_groups=[], dhcp_options=None
                ).AndRaise(rpc_common.RemoteError())
        self.compute.network_api.deallocate_for_instance(
                mox.IgnoreArg(),
                mox.IgnoreArg(),
                requested_networks=None).MultipleTimes()

        fake_network.unset_stub_network_methods(self.stubs)

        self.mox.ReplayAll()

        self.assertRaises(rpc_common.RemoteError,
                          self.compute.run_instance,
                          self.context,
                          instance=instance)

        instance = db.instance_get_by_uuid(context.get_admin_context(),
                                           instance['uuid'])
        self.assertEqual(vm_states.ERROR, instance['vm_state'])

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_delete_instance_succedes_on_volume_fail(self):
        instance = self._create_fake_instance_obj()

        def fake_cleanup_volumes(context, instance):
            raise test.TestingException()

        self.stubs.Set(self.compute, '_cleanup_volumes',
                       fake_cleanup_volumes)

        self.compute._delete_instance(self.context, instance=instance,
                                      bdms={})

    def test_delete_instance_keeps_net_on_power_off_fail(self):
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')
        self.mox.StubOutWithMock(self.compute, '_deallocate_network')
        exp = exception.InstancePowerOffFailure(reason='')
        self.compute.driver.destroy(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    context=mox.IgnoreArg()).AndRaise(exp)
        # mox will detect if _deallocate_network gets called unexpectedly
        self.mox.ReplayAll()
        instance = self._create_fake_instance()
        self.assertRaises(exception.InstancePowerOffFailure,
                          self.compute._delete_instance,
                          self.context,
                          instance=jsonutils.to_primitive(instance),
                          bdms={})

    def test_delete_instance_loses_net_on_other_fail(self):
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')
        self.mox.StubOutWithMock(self.compute, '_deallocate_network')
        exp = test.TestingException()
        self.compute.driver.destroy(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    context=mox.IgnoreArg()).AndRaise(exp)
        self.compute._deallocate_network(mox.IgnoreArg(),
                                         mox.IgnoreArg(),
                                         mox.IgnoreArg())
        self.mox.ReplayAll()
        instance = self._create_fake_instance()
        self.assertRaises(test.TestingException,
                          self.compute._delete_instance,
                          self.context,
                          instance=jsonutils.to_primitive(instance),
                          bdms={})

    def test_delete_instance_deletes_console_auth_tokens(self):
        instance = self._create_fake_instance_obj()
        self.flags(vnc_enabled=True)

        self.tokens_deleted = False

        def fake_delete_tokens(*args, **kwargs):
            self.tokens_deleted = True

        cauth_rpcapi = self.compute.consoleauth_rpcapi
        self.stubs.Set(cauth_rpcapi, 'delete_tokens_for_instance',
                       fake_delete_tokens)

        self.compute._delete_instance(self.context, instance=instance,
                                      bdms={})

        self.assertTrue(self.tokens_deleted)

    def test_delete_instance_deletes_console_auth_tokens_cells(self):
        instance = self._create_fake_instance_obj()
        self.flags(vnc_enabled=True)
        self.flags(enable=True, group='cells')

        self.tokens_deleted = False

        def fake_delete_tokens(*args, **kwargs):
            self.tokens_deleted = True

        cells_rpcapi = self.compute.cells_rpcapi
        self.stubs.Set(cells_rpcapi, 'consoleauth_delete_tokens',
                       fake_delete_tokens)

        self.compute._delete_instance(self.context, instance=instance,
                                      bdms={})

        self.assertTrue(self.tokens_deleted)

    def test_instance_termination_exception_sets_error(self):
        """Test that we handle InstanceTerminationFailure
        which is propagated up from the underlying driver.
        """
        instance = self._create_fake_instance_obj()

        def fake_delete_instance(context, instance, bdms,
                                 reservations=None):
            raise exception.InstanceTerminationFailure(reason='')

        self.stubs.Set(self.compute, '_delete_instance',
                       fake_delete_instance)

        self.compute.terminate_instance(self.context, instance=instance)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)

    def test_network_is_deallocated_on_spawn_failure(self):
        # When a spawn fails the network must be deallocated.
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.mox.StubOutWithMock(self.compute, "_prep_block_device")
        self.compute._prep_block_device(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(rpc.common.RemoteError('', '', ''))

        self.mox.ReplayAll()

        self.assertRaises(rpc.common.RemoteError,
                          self.compute.run_instance,
                          self.context, instance=instance)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_lock(self):
        # FIXME(comstud): This test is such crap.  This is testing
        # compute API lock functionality in a test class for the compute
        # manager by running an instance.  Hello?  We should just have
        # unit tests in test_compute_api that test the check_instance_lock
        # decorator and make sure that appropriate compute_api methods
        # have the decorator.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        non_admin_context = context.RequestContext(None,
                                                   None,
                                                   is_admin=False)

        def check_task_state(task_state):
            instance = db.instance_get_by_uuid(self.context, instance_uuid)
            self.assertEqual(instance['task_state'], task_state)

        # should fail with locked nonadmin context
        inst_obj = instance_obj.Instance.get_by_uuid(self.context,
                                                     instance['uuid'])

        self.compute_api.lock(self.context, inst_obj)
        self.assertRaises(exception.InstanceIsLocked,
                          self.compute_api.reboot,
                          non_admin_context, inst_obj, 'SOFT')
        check_task_state(None)

        # should fail with invalid task state
        self.compute_api.unlock(self.context, inst_obj)
        instance = db.instance_update(self.context, instance_uuid,
                                      {'task_state': task_states.REBOOTING})
        inst_obj.refresh()
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.reboot,
                          non_admin_context, inst_obj, 'SOFT')
        check_task_state(task_states.REBOOTING)

        # should succeed with admin context
        instance = db.instance_update(self.context, instance_uuid,
                                      {'task_state': None})
        inst_obj.refresh()
        self.compute_api.reboot(self.context, inst_obj, 'SOFT')
        check_task_state(task_states.REBOOTING)
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def _check_locked_by(self, instance_uuid, locked_by):
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['locked'], locked_by != None)
        self.assertEqual(instance['locked_by'], locked_by)
        return instance

    def test_override_owner_lock(self):
        # FIXME(comstud): This test is such crap.  This is testing
        # compute API lock functionality in a test class for the compute
        # manager by running an instance.  Hello?  We should just have
        # unit tests in test_compute_api that test the check_instance_lock
        # decorator and make sure that appropriate compute_api methods
        # have the decorator.
        admin_context = context.RequestContext('admin-user',
                                               'admin-project',
                                               is_admin=True)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        # Ensure that an admin can override the owner lock
        inst_obj = self._objectify(instance)
        self.compute_api.lock(self.context, inst_obj)
        self._check_locked_by(instance_uuid, 'owner')
        self.compute_api.unlock(admin_context, inst_obj)
        self._check_locked_by(instance_uuid, None)

    def test_upgrade_owner_lock(self):
        # FIXME(comstud): This test is such crap.  This is testing
        # compute API lock functionality in a test class for the compute
        # manager by running an instance.  Hello?  We should just have
        # unit tests in test_compute_api that test the check_instance_lock
        # decorator and make sure that appropriate compute_api methods
        # have the decorator.
        admin_context = context.RequestContext('admin-user',
                                               'admin-project',
                                               is_admin=True)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        # Ensure that an admin can upgrade the lock and that
        # the owner can no longer unlock
        inst_obj = self._objectify(instance)
        self.compute_api.lock(self.context, inst_obj)
        self.compute_api.lock(admin_context, inst_obj)
        self._check_locked_by(instance_uuid, 'admin')
        inst_obj.refresh()
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.unlock,
                          self.context, inst_obj)
        self._check_locked_by(instance_uuid, 'admin')
        self.compute_api.unlock(admin_context, inst_obj)
        self._check_locked_by(instance_uuid, None)

    def _test_state_revert(self, instance, operation, pre_task_state,
                           kwargs=None):
        if kwargs is None:
            kwargs = {}

        # The API would have set task_state, so do that here to test
        # that the state gets reverted on failure
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": pre_task_state})

        orig_elevated = self.context.elevated
        orig_notify = self.compute._notify_about_instance_usage

        def _get_an_exception(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.context, 'elevated', _get_an_exception)
        self.stubs.Set(self.compute,
                       '_notify_about_instance_usage', _get_an_exception)

        func = getattr(self.compute, operation)

        self.assertRaises(test.TestingException,
                func, self.context, instance=instance, **kwargs)
        # self.context.elevated() is called in tearDown()
        self.stubs.Set(self.context, 'elevated', orig_elevated)
        self.stubs.Set(self.compute,
                       '_notify_about_instance_usage', orig_notify)

        # Fetch the instance's task_state and make sure it reverted to None.
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance["task_state"], None)

    def test_state_revert(self):
        # ensure that task_state is reverted after a failed operation.
        actions = [
            ("reboot_instance", task_states.REBOOTING),
            ("stop_instance", task_states.POWERING_OFF),
            ("start_instance", task_states.POWERING_ON),
            ("terminate_instance", task_states.DELETING),
            ("power_off_instance", task_states.POWERING_OFF),
            ("power_on_instance", task_states.POWERING_ON),
            ("soft_delete_instance", task_states.SOFT_DELETING),
            ("restore_instance", task_states.RESTORING),
            ("rebuild_instance", task_states.REBUILDING,
                                 {'orig_image_ref': None,
                                  'image_ref': None,
                                  'injected_files': [],
                                  'new_pass': ''}),
            ("set_admin_password", task_states.UPDATING_PASSWORD),
            ("rescue_instance", task_states.RESCUING),
            ("unrescue_instance", task_states.UNRESCUING),
            ("revert_resize", task_states.RESIZE_REVERTING,
                              {'migration_id': None}),
            ("prep_resize", task_states.RESIZE_PREP,
                            {'image': {},
                             'instance_type': {}}),
            ("resize_instance", task_states.RESIZE_PREP,
                                {'migration_id': None,
                                 'image': {}}),
            ("pause_instance", task_states.PAUSING),
            ("unpause_instance", task_states.UNPAUSING),
            ("suspend_instance", task_states.SUSPENDING),
            ("resume_instance", task_states.RESUMING),
            ]

        want_objects = ['stop_instance', 'start_instance',
                        'terminate_instance', 'soft_delete_instance',
                        'revert_resize', 'confirm_resize'
                        ]

        instance = self._create_fake_instance()
        inst_obj = instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), instance,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)
        for operation in actions:
            if operation[0] in want_objects:
                self._test_state_revert(inst_obj, *operation)
            else:
                self._test_state_revert(instance, *operation)

    def _ensure_quota_reservations_committed(self, expect_project=False,
                                             expect_user=False):
        """Mock up commit of quota reservations."""
        reservations = list('fake_res')
        self.mox.StubOutWithMock(nova.quota.QUOTAS, 'commit')
        nova.quota.QUOTAS.commit(mox.IgnoreArg(), reservations,
                                 project_id=(expect_project and
                                             self.context.project_id or
                                             None),
                                 user_id=(expect_user and
                                          self.context.user_id or
                                          None))
        self.mox.ReplayAll()
        return reservations

    def _ensure_quota_reservations_rolledback(self, expect_project=False,
                                              expect_user=False):
        """Mock up rollback of quota reservations."""
        reservations = list('fake_res')
        self.mox.StubOutWithMock(nova.quota.QUOTAS, 'rollback')
        nova.quota.QUOTAS.rollback(mox.IgnoreArg(), reservations,
                                   project_id=(expect_project and
                                               self.context.project_id or
                                               None),
                                   user_id=(expect_user and
                                            self.context.user_id or
                                            None))
        self.mox.ReplayAll()
        return reservations

    def test_quotas_succesful_delete(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        resvs = self._ensure_quota_reservations_committed(True, True)
        self.compute.terminate_instance(self.context, instance,
                                        bdms=None, reservations=resvs)

    def test_quotas_failed_delete(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())

        def fake_shutdown_instance(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.compute, '_shutdown_instance',
                       fake_shutdown_instance)

        resvs = self._ensure_quota_reservations_rolledback(True, True)
        self.assertRaises(test.TestingException,
                          self.compute.terminate_instance,
                          self.context, instance,
                          bdms=None, reservations=resvs)

    def test_quotas_succesful_soft_delete(self):
        instance = jsonutils.to_primitive(self._create_fake_instance(
            params=dict(task_state=task_states.SOFT_DELETING)))
        resvs = self._ensure_quota_reservations_committed(True, True)
        self.compute.soft_delete_instance(self.context, instance,
                                          reservations=resvs)

    def test_quotas_failed_soft_delete(self):
        instance = jsonutils.to_primitive(self._create_fake_instance(
            params=dict(task_state=task_states.SOFT_DELETING)))

        def fake_soft_delete(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.compute.driver, 'soft_delete',
                       fake_soft_delete)

        resvs = self._ensure_quota_reservations_rolledback(True, True)
        self.assertRaises(test.TestingException,
                          self.compute.soft_delete_instance,
                          self.context, instance,
                          reservations=resvs)

    def test_quotas_destroy_of_soft_deleted_instance(self):
        instance = jsonutils.to_primitive(self._create_fake_instance(
            params=dict(vm_state=vm_states.SOFT_DELETED)))
        # Termination should be successful, but quota reservations
        # rolled back because the instance was in SOFT_DELETED state.
        resvs = self._ensure_quota_reservations_rolledback()
        self.compute.terminate_instance(self.context, instance,
                                        bdms=None, reservations=resvs)

    def _stub_out_resize_network_methods(self):
        def fake(cls, ctxt, instance, *args, **kwargs):
            pass

        self.stubs.Set(network_api.API, 'setup_networks_on_host', fake)
        self.stubs.Set(network_api.API, 'migrate_instance_start', fake)
        self.stubs.Set(network_api.API, 'migrate_instance_finish', fake)

    def _test_finish_resize(self, power_on):
        # Contrived test to ensure finish_resize doesn't raise anything and
        # also tests resize from ACTIVE or STOPPED state which determines
        # if the resized instance is powered on or not.
        vm_state = None
        if power_on:
            vm_state = vm_states.ACTIVE
        else:
            vm_state = vm_states.STOPPED
        params = {'vm_state': vm_state}
        instance = self._create_fake_instance_obj(params)
        image = 'fake-image'
        disk_info = 'fake-disk-info'
        instance_type = flavors.get_default_flavor()
        instance.task_state = task_states.RESIZE_PREP
        instance.save()
        self.compute.prep_resize(self.context, instance=instance,
                                 instance_type=instance_type,
                                 image={})
        instance.task_state = task_states.RESIZE_MIGRATED
        instance.save()

        # NOTE(mriedem): make sure prep_resize set old_vm_state correctly
        sys_meta = instance.system_metadata
        self.assertTrue('old_vm_state' in sys_meta)
        if power_on:
            self.assertEqual(vm_states.ACTIVE, sys_meta['old_vm_state'])
        else:
            self.assertEqual(vm_states.STOPPED, sys_meta['old_vm_state'])
        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')

        orig_mig_save = migration.save
        orig_inst_save = instance.save
        network_api = self.compute.network_api
        conductor_api = self.compute.conductor_api

        self.mox.StubOutWithMock(network_api, 'setup_networks_on_host')
        self.mox.StubOutWithMock(conductor_api,
                                 'network_migrate_instance_finish')
        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute,
                                 '_notify_about_instance_usage')
        self.mox.StubOutWithMock(self.compute.driver, 'finish_migration')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_volume_block_device_info')
        self.mox.StubOutWithMock(migration, 'save')
        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.context, 'elevated')

        def _mig_save(context):
            self.assertEqual(migration.status, 'finished')
            self.assertEqual(vm_state, instance.vm_state)
            self.assertEqual(task_states.RESIZE_FINISH, instance.task_state)
            orig_mig_save()

        def _instance_save1():
            self.assertEqual(instance_type['id'],
                             instance.instance_type_id)
            orig_inst_save()

        def _instance_save2(expected_task_state=None):
            self.assertEqual(task_states.RESIZE_MIGRATED,
                             expected_task_state)
            self.assertEqual(task_states.RESIZE_FINISH, instance.task_state)
            orig_inst_save(expected_task_state=expected_task_state)

        def _instance_save3(expected_task_state=None):
            self.assertEqual(task_states.RESIZE_FINISH,
                             expected_task_state)
            self.assertEqual(vm_states.RESIZED, instance.vm_state)
            self.assertEqual(None, instance.task_state)
            self.assertIn('launched_at', instance.obj_what_changed())
            orig_inst_save(expected_task_state=expected_task_state)

        # First save to update flavor
        instance.save().WithSideEffects(_instance_save1)

        network_api.setup_networks_on_host(self.context, instance,
                                           'fake-mini')
        conductor_api.network_migrate_instance_finish(self.context,
                                                      mox.IsA(dict),
                                                      mox.IsA(dict))

        self.compute._get_instance_nw_info(
                self.context, instance).AndReturn('fake-nwinfo1')

        # 2nd save to update task state
        exp_kwargs = dict(expected_task_state=task_states.RESIZE_MIGRATED)
        instance.save(**exp_kwargs).WithSideEffects(_instance_save2)

        self.compute._notify_about_instance_usage(
                self.context, instance, 'finish_resize.start',
                network_info='fake-nwinfo1')

        self.compute._get_instance_volume_block_device_info(
                self.context, instance,
                refresh_conn_info=True).AndReturn('fake-bdminfo')
        # nova.conf sets the default flavor to m1.small and the test
        # sets the default flavor to m1.tiny so they should be different
        # which makes this a resize
        self.compute.driver.finish_migration(self.context, migration,
                                             instance, disk_info,
                                             'fake-nwinfo1',
                                             image, True,
                                             'fake-bdminfo', power_on)
        # Ensure instance status updates is after the migration finish
        self.context.elevated().AndReturn(self.context)
        migration.save(self.context).WithSideEffects(_mig_save)
        exp_kwargs = dict(expected_task_state=task_states.RESIZE_FINISH)
        instance.save(**exp_kwargs).WithSideEffects(_instance_save3)
        self.compute._notify_about_instance_usage(
                self.context, instance, 'finish_resize.end',
                network_info='fake-nwinfo1')
        # NOTE(comstud): This actually does the mox.ReplayAll()
        reservations = self._ensure_quota_reservations_committed()

        self.compute.finish_resize(self.context,
                migration=migration,
                disk_info=disk_info, image=image, instance=instance,
                reservations=reservations)

    def test_finish_resize_from_active(self):
        self._test_finish_resize(power_on=True)

    def test_finish_resize_from_stopped(self):
        self._test_finish_resize(power_on=False)

    def test_finish_resize_with_volumes(self):
        """Contrived test to ensure finish_resize doesn't raise anything."""

        # create instance
        instance = self._create_fake_instance_obj()

        # create volume
        volume_id = 'fake'
        volume = {'instance_uuid': None,
                  'device_name': None,
                  'volume_id': volume_id}

        # stub out volume attach
        def fake_volume_get(self, context, volume):
            return volume
        self.stubs.Set(cinder.API, "get", fake_volume_get)

        def fake_get_volume_encryption_metadata(self, context, volume_id):
            return {}
        self.stubs.Set(cinder.API, 'get_volume_encryption_metadata',
                       fake_get_volume_encryption_metadata)

        orig_connection_data = {
            'target_discovered': True,
            'target_iqn': 'iqn.2010-10.org.openstack:%s.1' % volume_id,
            'target_portal': '127.0.0.0.1:3260',
            'volume_id': volume_id,
        }
        connection_info = {
            'driver_volume_type': 'iscsi',
            'data': orig_connection_data,
        }

        def fake_init_conn(self, context, volume, session):
            return connection_info
        self.stubs.Set(cinder.API, "initialize_connection", fake_init_conn)

        def fake_attach(self, context, volume_id, instance_uuid, device_name):
            volume['instance_uuid'] = instance_uuid
            volume['device_name'] = device_name
        self.stubs.Set(cinder.API, "attach", fake_attach)

        # stub out virt driver attach
        def fake_get_volume_connector(*args, **kwargs):
            return {}
        self.stubs.Set(self.compute.driver, 'get_volume_connector',
                       fake_get_volume_connector)

        def fake_attach_volume(*args, **kwargs):
            pass
        self.stubs.Set(self.compute.driver, 'attach_volume',
                       fake_attach_volume)

        # attach volume to instance
        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.attach_volume(self.context, volume['volume_id'],
                                   '/dev/vdc', instance_p)

        # assert volume attached correctly
        self.assertEquals(volume['device_name'], '/dev/vdc')
        disk_info = db.block_device_mapping_get_all_by_instance(
            self.context, instance.uuid)
        self.assertEquals(len(disk_info), 1)
        for bdm in disk_info:
            self.assertEquals(bdm['device_name'], volume['device_name'])
            self.assertEquals(bdm['connection_info'],
                              jsonutils.dumps(connection_info))

        # begin resize
        instance_type = flavors.get_default_flavor()
        instance.task_state = task_states.RESIZE_PREP
        instance.save()
        self.compute.prep_resize(self.context, instance=instance,
                                 instance_type=instance_type,
                                 image={})

        # fake out detach for prep_resize (and later terminate)
        def fake_terminate_connection(self, context, volume, connector):
            connection_info['data'] = None
        self.stubs.Set(cinder.API, "terminate_connection",
                       fake_terminate_connection)

        self._stub_out_resize_network_methods()

        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')
        self.compute.resize_instance(self.context, instance=instance,
                migration=migration, image={},
                instance_type=jsonutils.to_primitive(instance_type))

        # assert bdm is unchanged
        disk_info = db.block_device_mapping_get_all_by_instance(
            self.context, instance.uuid)
        self.assertEquals(len(disk_info), 1)
        for bdm in disk_info:
            self.assertEquals(bdm['device_name'], volume['device_name'])
            cached_connection_info = jsonutils.loads(bdm['connection_info'])
            self.assertEquals(cached_connection_info['data'],
                              orig_connection_data)
        # but connection was terminated
        self.assertEquals(connection_info['data'], None)

        # stub out virt driver finish_migration
        def fake(*args, **kwargs):
            pass
        self.stubs.Set(self.compute.driver, 'finish_migration', fake)

        instance.task_state = task_states.RESIZE_MIGRATED
        instance.save()

        reservations = self._ensure_quota_reservations_committed()

        # new initialize connection
        new_connection_data = dict(orig_connection_data)
        new_iqn = 'iqn.2010-10.org.openstack:%s.2' % volume_id,
        new_connection_data['target_iqn'] = new_iqn

        def fake_init_conn_with_data(self, context, volume, session):
            connection_info['data'] = new_connection_data
            return connection_info
        self.stubs.Set(cinder.API, "initialize_connection",
                       fake_init_conn_with_data)

        self.compute.finish_resize(self.context,
                migration=migration,
                disk_info={}, image={}, instance=instance,
                reservations=reservations)

        # assert volume attached correctly
        disk_info = db.block_device_mapping_get_all_by_instance(
            self.context, instance['uuid'])
        self.assertEquals(len(disk_info), 1)
        for bdm in disk_info:
            self.assertEquals(bdm['connection_info'],
                              jsonutils.dumps(connection_info))

        # stub out detach
        def fake_detach(self, context, volume_uuid):
            volume['device_path'] = None
            volume['instance_uuid'] = None
        self.stubs.Set(cinder.API, "detach", fake_detach)

        # clean up
        self.compute.terminate_instance(self.context, instance=instance)

    def test_finish_resize_handles_error(self):
        # Make sure we don't leave the instance in RESIZE on error.

        def throw_up(*args, **kwargs):
            raise test.TestingException()

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', throw_up)

        self._stub_out_resize_network_methods()

        reservations = self._ensure_quota_reservations_rolledback()

        instance = self._create_fake_instance_obj()
        instance_type = flavors.get_default_flavor()

        self.compute.prep_resize(self.context, instance=instance,
                                 instance_type=instance_type,
                                 image={}, reservations=reservations)

        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')

        instance.refresh()
        instance.task_state = task_states.RESIZE_MIGRATED
        instance.save()
        self.assertRaises(test.TestingException, self.compute.finish_resize,
                          self.context,
                          migration=migration,
                          disk_info={}, image={}, instance=instance,
                          reservations=reservations)
        # NOTE(comstud): error path doesn't use objects, so our object
        # is not updated.  Refresh and compare against the DB.
        instance.refresh()
        self.assertEqual(vm_states.ERROR, instance.vm_state)

    def test_rebuild_instance_notification(self):
        # Ensure notifications on instance migrate/resize.
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        inst_ref = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=inst_ref)
        timeutils.set_time_override(cur_time)

        fake_notifier.NOTIFICATIONS = []
        instance = db.instance_get_by_uuid(self.context, inst_ref['uuid'])
        orig_sys_metadata = db.instance_system_metadata_get(self.context,
                inst_ref['uuid'])
        image_ref = instance["image_ref"]
        new_image_ref = image_ref + '-new_image_ref'
        db.instance_update(self.context, inst_ref['uuid'],
                           {'image_ref': new_image_ref})

        password = "new_password"

        instance = db.instance_get_by_uuid(self.context, inst_ref['uuid'])

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context,
                                      jsonutils.to_primitive(instance),
                                      image_ref, new_image_ref,
                                      injected_files=[],
                                      new_pass=password,
                                      orig_sys_metadata=orig_sys_metadata,
                                      bdms=[])

        instance = db.instance_get_by_uuid(self.context, inst_ref['uuid'])

        image_ref_url = glance.generate_image_url(image_ref)
        new_image_ref_url = glance.generate_image_url(new_image_ref)

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 3)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.event_type,
                          'compute.instance.exists')
        self.assertEquals(msg.payload['image_ref_url'], image_ref_url)
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg.event_type,
                          'compute.instance.rebuild.start')
        self.assertEquals(msg.payload['image_ref_url'], new_image_ref_url)
        self.assertEquals(msg.payload['image_name'], 'fake_name')
        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg.event_type,
                          'compute.instance.rebuild.end')
        self.assertEquals(msg.priority, 'INFO')
        payload = msg.payload
        self.assertEquals(payload['image_name'], 'fake_name')
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], inst_ref['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEquals(str(payload['instance_flavor_id']), str(flavor_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEqual(payload['launched_at'], timeutils.strtime(cur_time))
        self.assertEquals(payload['image_ref_url'], new_image_ref_url)
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_finish_resize_instance_notification(self):
        # Ensure notifications on instance migrate/resize.
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        instance = self._create_fake_instance_obj()
        new_type = flavors.get_flavor_by_name('m1.small')
        new_type = jsonutils.to_primitive(new_type)
        new_type_id = new_type['id']
        flavor_id = new_type['flavorid']
        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)

        instance.host = 'foo'
        instance.task_state = task_states.RESIZE_PREP
        instance.save()

        self.compute.prep_resize(self.context, instance=instance,
                instance_type=new_type, image={})

        self._stub_out_resize_network_methods()

        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')
        self.compute.resize_instance(self.context, instance=instance,
                migration=migration, image={}, instance_type=new_type)
        timeutils.set_time_override(cur_time)
        fake_notifier.NOTIFICATIONS = []

        self.compute.finish_resize(self.context,
                migration=migration,
                disk_info={}, image={}, instance=instance)

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.event_type,
                          'compute.instance.finish_resize.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg.event_type,
                          'compute.instance.finish_resize.end')
        self.assertEquals(msg.priority, 'INFO')
        payload = msg.payload
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance.uuid)
        self.assertEquals(payload['instance_type'], 'm1.small')
        self.assertEquals(str(payload['instance_type_id']), str(new_type_id))
        self.assertEquals(str(payload['instance_flavor_id']), str(flavor_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEqual(payload['launched_at'], timeutils.strtime(cur_time))
        image_ref_url = glance.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance)

    def test_resize_instance_notification(self):
        # Ensure notifications on instance migrate/resize.
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        instance = self._create_fake_instance_obj()

        self.compute.run_instance(self.context, instance=instance)
        timeutils.set_time_override(cur_time)
        fake_notifier.NOTIFICATIONS = []

        instance.host = 'foo'
        instance.task_state = task_states.RESIZE_PREP
        instance.save()

        instance_type = flavors.get_default_flavor()
        self.compute.prep_resize(self.context, instance=instance,
                instance_type=instance_type, image={})
        db.migration_get_by_instance_and_status(self.context.elevated(),
                                                instance.uuid,
                                                'pre-migrating')

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 3)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg.event_type,
                          'compute.instance.exists')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg.event_type,
                          'compute.instance.resize.prep.start')
        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg.event_type,
                          'compute.instance.resize.prep.end')
        self.assertEquals(msg.priority, 'INFO')
        payload = msg.payload
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance.uuid)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEquals(str(payload['instance_flavor_id']), str(flavor_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        image_ref_url = glance.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_prep_resize_instance_migration_error_on_same_host(self):
        """Ensure prep_resize raise a migration error if destination is set on
        the same source host and allow_resize_to_same_host is false
        """
        self.flags(host="foo", allow_resize_to_same_host=False)

        instance = self._create_fake_instance_obj()

        reservations = self._ensure_quota_reservations_rolledback()

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)
        instance.host = self.compute.host
        instance.save()
        instance_type = flavors.get_default_flavor()

        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                          self.context, instance=instance,
                          instance_type=instance_type, image={},
                          reservations=reservations)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_prep_resize_instance_migration_error_on_none_host(self):
        """Ensure prep_resize raises a migration error if destination host is
        not defined
        """
        instance = self._create_fake_instance_obj()

        reservations = self._ensure_quota_reservations_rolledback()

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)
        instance.host = None
        instance.save()
        instance_type = flavors.get_default_flavor()

        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                          self.context, instance=instance,
                          instance_type=instance_type, image={},
                          reservations=reservations)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_resize_instance_driver_error(self):
        # Ensure instance status set to Error on resize error.

        def throw_up(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.compute.driver, 'migrate_disk_and_power_off',
                       throw_up)

        instance = self._create_fake_instance_obj()
        instance_type = flavors.get_default_flavor()

        reservations = self._ensure_quota_reservations_rolledback()

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)
        instance.host = 'foo'
        instance.save()
        self.compute.prep_resize(self.context, instance=instance,
                                 instance_type=instance_type, image={},
                                 reservations=reservations)
        instance.task_state = task_states.RESIZE_PREP
        instance.save()
        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')

        #verify
        self.assertRaises(test.TestingException, self.compute.resize_instance,
                          self.context, instance=instance,
                          migration=migration, image={},
                          reservations=reservations,
                          instance_type=jsonutils.to_primitive(instance_type))
        # NOTE(comstud): error path doesn't use objects, so our object
        # is not updated.  Refresh and compare against the DB.
        instance.refresh()
        self.assertEqual(instance.vm_state, vm_states.ERROR)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_resize_instance_driver_rollback(self):
        # Ensure instance status set to Running after rollback.

        def throw_up(*args, **kwargs):
            raise exception.InstanceFaultRollback(test.TestingException())

        self.stubs.Set(self.compute.driver, 'migrate_disk_and_power_off',
                       throw_up)

        instance = self._create_fake_instance_obj()
        instance_type = flavors.get_default_flavor()
        reservations = self._ensure_quota_reservations_rolledback()
        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)
        instance.host = 'foo'
        instance.save()
        self.compute.prep_resize(self.context, instance=instance,
                                 instance_type=instance_type, image={},
                                 reservations=reservations)
        instance.task_state = task_states.RESIZE_PREP
        instance.save()

        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')

        self.assertRaises(test.TestingException, self.compute.resize_instance,
                          self.context, instance=instance,
                          migration=migration, image={},
                          reservations=reservations,
                          instance_type=jsonutils.to_primitive(instance_type))
        # NOTE(comstud): error path doesn't use objects, so our object
        # is not updated.  Refresh and compare against the DB.
        instance.refresh()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        self.assertEqual(instance.task_state, None)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_resize_instance(self):
        # Ensure instance can be migrated/resized.
        instance = self._create_fake_instance_obj()
        instance_type = flavors.get_default_flavor()

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)
        instance.host = 'foo'
        instance.save()
        self.compute.prep_resize(self.context, instance=instance,
                instance_type=instance_type, image={})

        # verify 'old_vm_state' was set on system_metadata
        instance.refresh()
        sys_meta = instance.system_metadata
        self.assertEqual(vm_states.ACTIVE, sys_meta['old_vm_state'])

        self._stub_out_resize_network_methods()

        instance.task_state = task_states.RESIZE_PREP
        instance.save()

        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')

        self.compute.resize_instance(self.context, instance=instance,
                migration=migration, image={},
                instance_type=jsonutils.to_primitive(instance_type))
        self.assertEqual(migration.dest_compute, instance.host)
        self.compute.terminate_instance(self.context, instance=instance)

    def _test_confirm_resize(self, power_on):
        # Common test case method for confirm_resize
        def fake(*args, **kwargs):
            pass

        def fake_confirm_migration_driver(*args, **kwargs):
            # Confirm the instance uses the new type in finish_resize
            inst = args[1]
            sys_meta = inst['system_metadata']
            self.assertEqual(sys_meta['instance_type_flavorid'], '3')

        old_vm_state = None
        p_state = None
        if power_on:
            old_vm_state = vm_states.ACTIVE
            p_state = power_state.RUNNING
        else:
            old_vm_state = vm_states.STOPPED
            p_state = power_state.SHUTDOWN
        params = {'vm_state': old_vm_state, 'power_state': p_state}
        instance = self._create_fake_instance_obj(params)

        self.flags(allow_resize_to_same_host=True)
        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.driver, 'confirm_migration',
                       fake_confirm_migration_driver)

        self._stub_out_resize_network_methods()

        reservations = self._ensure_quota_reservations_committed()

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)

        # Confirm the instance size before the resize starts
        instance.refresh()
        instance_type_ref = db.flavor_get(self.context,
                                          instance.instance_type_id)
        self.assertEqual(instance_type_ref['flavorid'], '1')

        instance.vm_state = old_vm_state
        instance.power_state = p_state
        instance.save()

        new_instance_type_ref = db.flavor_get_by_flavor_id(
                self.context, 3)
        new_instance_type_p = jsonutils.to_primitive(new_instance_type_ref)
        self.compute.prep_resize(self.context,
                instance=instance,
                instance_type=new_instance_type_p,
                image={}, reservations=reservations)

        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')

        # NOTE(mriedem): ensure prep_resize set old_vm_state in system_metadata
        sys_meta = instance.system_metadata
        self.assertEqual(old_vm_state, sys_meta['old_vm_state'])
        instance.task_state = task_states.RESIZE_PREP
        instance.save()
        self.compute.resize_instance(self.context, instance=instance,
                                     migration=migration,
                                     image={},
                                     instance_type=new_instance_type_p)
        self.compute.finish_resize(self.context,
                    migration=migration,
                    disk_info={}, image={}, instance=instance)

        # Prove that the instance size is now the new size
        instance_type_ref = db.flavor_get(self.context,
                instance.instance_type_id)
        self.assertEqual(instance_type_ref['flavorid'], '3')

        # Finally, confirm the resize and verify the new flavor is applied
        instance.task_state = None
        instance.save()
        self.compute.confirm_resize(self.context, instance=instance,
                                    reservations=reservations,
                                    migration=migration)

        instance.refresh()

        instance_type_ref = db.flavor_get(self.context,
                instance.instance_type_id)
        self.assertEqual(instance_type_ref['flavorid'], '3')
        self.assertEqual('fake-mini', migration.source_compute)
        self.assertEqual(old_vm_state, instance.vm_state)
        self.assertEqual(None, instance.task_state)
        self.assertEqual(p_state, instance.power_state)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_confirm_resize_from_active(self):
        self._test_confirm_resize(power_on=True)

    def test_confirm_resize_from_stopped(self):
        self._test_confirm_resize(power_on=False)

    def _test_finish_revert_resize(self, power_on,
                                   remove_old_vm_state=False):
        """
        Convenience method that does most of the work for the
        test_finish_revert_resize tests.
        :param power_on -- True if testing resize from ACTIVE state, False if
        testing resize from STOPPED state.
        :param remove_old_vm_state -- True if testing a case where the
        'old_vm_state' system_metadata is not present when the
        finish_revert_resize method is called.
        """
        def fake(*args, **kwargs):
            pass

        def fake_finish_revert_migration_driver(*args, **kwargs):
            # Confirm the instance uses the old type in finish_revert_resize
            inst = args[0]
            sys_meta = inst.system_metadata
            self.assertEqual(sys_meta['instance_type_flavorid'], '1')

        old_vm_state = None
        if power_on:
            old_vm_state = vm_states.ACTIVE
        else:
            old_vm_state = vm_states.STOPPED
        params = {'vm_state': old_vm_state}
        instance = self._create_fake_instance_obj(params)

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.driver, 'finish_revert_migration',
                       fake_finish_revert_migration_driver)

        self._stub_out_resize_network_methods()

        reservations = self._ensure_quota_reservations_committed()

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)

        instance.refresh()
        instance_type_ref = db.flavor_get(self.context,
                                          instance.instance_type_id)
        self.assertEqual(instance_type_ref['flavorid'], '1')

        old_vm_state = instance['vm_state']

        instance.host = 'foo'
        instance.vm_state = old_vm_state
        instance.save()

        new_instance_type_ref = db.flavor_get_by_flavor_id(
                self.context, 3)
        new_instance_type_p = jsonutils.to_primitive(new_instance_type_ref)
        self.compute.prep_resize(self.context,
                instance=instance,
                instance_type=new_instance_type_p,
                image={}, reservations=reservations)

        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')

        # NOTE(mriedem): ensure prep_resize set old_vm_state in system_metadata
        sys_meta = instance.system_metadata
        self.assertEqual(old_vm_state, sys_meta['old_vm_state'])
        instance.task_state = task_states.RESIZE_PREP
        instance.save()
        self.compute.resize_instance(self.context, instance=instance,
                                     migration=migration,
                                     image={},
                                     instance_type=new_instance_type_p)
        self.compute.finish_resize(self.context,
                    migration=migration,
                    disk_info={}, image={}, instance=instance)

        # Prove that the instance size is now the new size
        instance_type_ref = db.flavor_get(self.context,
                                          instance['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '3')

        instance.task_state = task_states.RESIZE_REVERTING
        instance.save()

        self.compute.revert_resize(self.context,
                migration=migration, instance=instance,
                reservations=reservations)

        instance.refresh()
        if remove_old_vm_state:
            # need to wipe out the old_vm_state from system_metadata
            # before calling finish_revert_resize
            sys_meta = instance.system_metadata
            sys_meta.pop('old_vm_state')
            # Have to reset for save() to work
            instance.system_metadata = sys_meta
            instance.save()

        self.compute.finish_revert_resize(self.context,
                migration=migration,
                instance=instance, reservations=reservations)

        self.assertEqual(instance.task_state, None)

        instance_type_ref = db.flavor_get(self.context,
                instance['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '1')
        self.assertEqual(instance.host, migration.source_compute)
        if remove_old_vm_state:
            self.assertEqual(vm_states.ACTIVE, instance.vm_state)
        else:
            self.assertEqual(old_vm_state, instance.vm_state)

    def test_finish_revert_resize_from_active(self):
        self._test_finish_revert_resize(power_on=True)

    def test_finish_revert_resize_from_stopped(self):
        self._test_finish_revert_resize(power_on=False)

    def test_finish_revert_resize_from_stopped_remove_old_vm_state(self):
        # in  this case we resize from STOPPED but end up with ACTIVE
        # because the old_vm_state value is not present in
        # finish_revert_resize
        self._test_finish_revert_resize(power_on=False,
                                        remove_old_vm_state=True)

    def _test_cleanup_stored_instance_types(self, old, new, revert=False):
        instance = self._create_fake_instance_obj()
        migration = dict(old_instance_type_id=old,
                         new_instance_type_id=new)
        instance.system_metadata = dict(instance_type_id=old)
        sys_meta = dict(instance.system_metadata)
        self.mox.StubOutWithMock(flavors, 'extract_flavor')
        self.mox.StubOutWithMock(flavors, 'delete_flavor_info')
        self.mox.StubOutWithMock(flavors, 'save_flavor_info')
        if revert:
            flavors.extract_flavor(instance, 'old_').AndReturn(
                {'instance_type_id': old})
            flavors.save_flavor_info(
                sys_meta, {'instance_type_id': old}).AndReturn(sys_meta)
        else:
            flavors.extract_flavor(instance).AndReturn(
                {'instance_type_id': new})
        flavors.delete_flavor_info(
            sys_meta, 'old_').AndReturn(sys_meta)
        flavors.delete_flavor_info(
            sys_meta, 'new_').AndReturn(sys_meta)

        self.mox.ReplayAll()
        res = self.compute._cleanup_stored_instance_types(migration, instance,
                                                          revert)
        self.assertEqual(res,
                         (sys_meta,
                          {'instance_type_id': revert and old or new}))

    def test_cleanup_stored_instance_types_for_resize(self):
        self._test_cleanup_stored_instance_types('1', '2')

    def test_cleanup_stored_instance_types_for_resize_with_update(self):
        self._test_cleanup_stored_instance_types('1', '2', True)

    def test_cleanup_stored_instance_types_for_migration(self):
        self._test_cleanup_stored_instance_types('1', '1')

    def test_cleanup_stored_instance_types_for_migration_with_update(self):
        self._test_cleanup_stored_instance_types('1', '1', True)

    def test_get_by_flavor_id(self):
        type = flavors.get_flavor_by_flavor_id(1)
        self.assertEqual(type['name'], 'm1.tiny')

    def test_resize_same_source_fails(self):
        """Ensure instance fails to migrate when source and destination are
        the same host.
        """
        reservations = self._ensure_quota_reservations_rolledback()
        instance = self._create_fake_instance_obj()
        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)
        instance.refresh()
        instance_type = flavors.get_default_flavor()
        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                self.context, instance=instance,
                instance_type=instance_type, image={},
                reservations=reservations)
        self.compute.terminate_instance(self.context, instance)

    def test_resize_instance_handles_migration_error(self):
        # Ensure vm_state is ERROR when error occurs.
        def raise_migration_failure(*args):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver,
                'migrate_disk_and_power_off',
                raise_migration_failure)

        reservations = self._ensure_quota_reservations_rolledback()

        instance = self._create_fake_instance_obj()
        instance_type = flavors.get_default_flavor()

        instance_p = obj_base.obj_to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance_p)
        instance.host = 'foo'
        instance.save()
        self.compute.prep_resize(self.context, instance=instance,
                                 instance_type=instance_type,
                                 image={}, reservations=reservations)
        migration = migration_obj.Migration.get_by_instance_and_status(
                self.context.elevated(),
                instance.uuid, 'pre-migrating')
        instance.task_state = task_states.RESIZE_PREP
        instance.save()
        self.assertRaises(test.TestingException, self.compute.resize_instance,
                          self.context, instance=instance,
                          migration=migration, image={},
                          reservations=reservations,
                          instance_type=jsonutils.to_primitive(instance_type))
        # NOTE(comstud): error path doesn't use objects, so our object
        # is not updated.  Refresh and compare against the DB.
        instance.refresh()
        self.assertEqual(instance.vm_state, vm_states.ERROR)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_pre_live_migration_instance_has_no_fixed_ip(self):
        # Confirm that no exception is raised if there is no fixed ip on
        # pre_live_migration
        instance = jsonutils.to_primitive(self._create_fake_instance())
        c = context.get_admin_context()

        self.mox.ReplayAll()
        self.compute.driver.pre_live_migration(mox.IsA(c), mox.IsA(instance),
                                               {'block_device_mapping': []},
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg())

    def test_pre_live_migration_works_correctly(self):
        # Confirm setup_compute_volume is called when volume is mounted.
        def stupid(*args, **kwargs):
            return fake_network.fake_get_instance_nw_info(self.stubs)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       '_get_instance_nw_info', stupid)

        # creating instance testdata
        instance = jsonutils.to_primitive(self._create_fake_instance(
                                          {'host': 'dummy'}))
        c = context.get_admin_context()
        nw_info = fake_network.fake_get_instance_nw_info(self.stubs)

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'pre_live_migration')
        self.compute.driver.pre_live_migration(mox.IsA(c), mox.IsA(instance),
                                               {'block_device_mapping': []},
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg(),
                                               mox.IgnoreArg())
        self.mox.StubOutWithMock(self.compute.driver,
                                 'ensure_filtering_rules_for_instance')
        self.compute.driver.ensure_filtering_rules_for_instance(
            mox.IsA(instance), nw_info)

        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_networks_on_host')
        self.compute.network_api.setup_networks_on_host(c, instance,
                                                        self.compute.host)

        fake_notifier.NOTIFICATIONS = []
        # start test
        self.mox.ReplayAll()
        migrate_data = {'is_shared_instance_path': False}
        ret = self.compute.pre_live_migration(c, instance=instance,
                                              block_migration=False,
                                              migrate_data=migrate_data)
        self.assertEqual(ret, None)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'compute.instance.live_migration.pre.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'compute.instance.live_migration.pre.end')

        # cleanup
        db.instance_destroy(c, instance['uuid'])

    def test_live_migration_exception_rolls_back(self):
        # Confirm exception when pre_live_migration fails.
        c = context.get_admin_context()

        src_host = 'fake-src-host'
        instance = dict(uuid='fake_instance', host=src_host,
                        name='fake-name')
        updated_instance = self._create_fake_instance(
                                               {'host': 'fake-dest-host'})
        dest_host = updated_instance['host']
        fake_bdms = [dict(volume_id='vol1-id'), dict(volume_id='vol2-id')]

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver,
                                 'get_instance_disk_info')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'pre_live_migration')
        self.mox.StubOutWithMock(self.compute, '_instance_update')
        self.mox.StubOutWithMock(self.compute, '_get_instance_volume_bdms')
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_networks_on_host')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'remove_volume_connection')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'rollback_live_migration_at_destination')

        self.compute.driver.get_instance_disk_info(
                instance['name']).AndReturn('fake_disk')
        self.compute.compute_rpcapi.pre_live_migration(c,
                instance, True, 'fake_disk', dest_host,
                {}).AndRaise(test.TestingException())

        self.compute._instance_update(c, instance['uuid'],
                host=src_host, vm_state=vm_states.ACTIVE,
                task_state=None,
                expected_task_state=task_states.MIGRATING).AndReturn(
                        updated_instance)
        self.compute.network_api.setup_networks_on_host(c,
                updated_instance, self.compute.host)
        self.compute._get_instance_volume_bdms(c,
                updated_instance).AndReturn(fake_bdms)
        self.compute.compute_rpcapi.remove_volume_connection(
                c, updated_instance, 'vol1-id', dest_host)
        self.compute.compute_rpcapi.remove_volume_connection(
                c, updated_instance, 'vol2-id', dest_host)
        self.compute.compute_rpcapi.rollback_live_migration_at_destination(
                c, updated_instance, dest_host, destroy_disks=True)

        # start test
        self.mox.ReplayAll()
        self.assertRaises(test.TestingException,
                          self.compute.live_migration,
                          c, dest=dest_host, block_migration=True,
                          instance=instance)

    def test_live_migration_works_correctly(self):
        # Confirm live_migration() works as expected correctly.
        # creating instance testdata
        c = context.get_admin_context()
        instance_ref = self._create_fake_instance()
        instance_ref['host'] = self.compute.host
        dest = 'desthost'
        inst_uuid = instance_ref['uuid']

        instance = jsonutils.to_primitive(instance_ref)

        migrate_data = {'is_shared_instance_path': False}

        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'pre_live_migration')
        self.compute.compute_rpcapi.pre_live_migration(
            c, instance, False, None, dest, migrate_data)

        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'network_migrate_instance_start')
        migration = {'source_compute': instance['host'], 'dest_compute': dest}
        self.compute.conductor_api.network_migrate_instance_start(c, instance,
                                                                  migration)
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'post_live_migration_at_destination')
        self.compute.compute_rpcapi.post_live_migration_at_destination(
            c, instance, False, dest)

        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_networks_on_host')
        self.compute.network_api.setup_networks_on_host(c, instance,
                                                        instance['host'],
                                                        teardown=True)

        # start test
        self.mox.ReplayAll()

        ret = self.compute.live_migration(c, dest=dest,
                                          instance=instance,
                                          migrate_data=migrate_data)
        self.assertEqual(ret, None)

        # cleanup
        db.instance_destroy(c, inst_uuid)

    def test_post_live_migration_no_shared_storage_working_correctly(self):
        """Confirm post_live_migration() works correctly as expected
           for non shared storage migration.
        """
        # Create stubs
        result = {}

        def fakedestroy(*args, **kwargs):
            result['destroyed'] = True
        self.stubs.Set(self.compute.driver, 'destroy', fakedestroy)
        dest = 'desthost'
        srchost = self.compute.host

        # creating testdata
        c = context.get_admin_context()
        inst_ref = jsonutils.to_primitive(self._create_fake_instance({
                                          'host': srchost,
                                          'state_description': 'migrating',
                                          'state': power_state.PAUSED}))
        inst_uuid = inst_ref['uuid']

        db.instance_update(c, inst_uuid,
                           {'task_state': task_states.MIGRATING,
                            'power_state': power_state.PAUSED})
        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'unfilter_instance')
        self.compute.driver.unfilter_instance(inst_ref, [])
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'network_migrate_instance_start')
        migration = {'source_compute': srchost, 'dest_compute': dest, }
        self.compute.conductor_api.network_migrate_instance_start(c, inst_ref,
                                                                  migration)

        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'post_live_migration_at_destination')
        self.compute.compute_rpcapi.post_live_migration_at_destination(
            c, inst_ref, False, dest)

        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_networks_on_host')
        self.compute.network_api.setup_networks_on_host(c, inst_ref,
                                                        self.compute.host,
                                                        teardown=True)

        # start test
        self.mox.ReplayAll()
        migrate_data = {'is_shared_instance_path': False}
        self.compute._post_live_migration(c, inst_ref, dest,
                                          migrate_data=migrate_data)
        self.assertTrue('destroyed' in result)
        self.assertTrue(result['destroyed'] == True)

    def test_post_live_migration_working_correctly(self):
        # Confirm post_live_migration() works as expected correctly.
        dest = 'desthost'
        srchost = self.compute.host

        # creating testdata
        c = context.get_admin_context()
        inst_ref = jsonutils.to_primitive(self._create_fake_instance({
                                'host': srchost,
                                'state_description': 'migrating',
                                'state': power_state.PAUSED}))
        inst_uuid = inst_ref['uuid']

        db.instance_update(c, inst_uuid,
                           {'task_state': task_states.MIGRATING,
                            'power_state': power_state.PAUSED})

        # creating mocks
        with contextlib.nested(
            mock.patch.object(self.compute.driver, 'post_live_migration'),
            mock.patch.object(self.compute.driver, 'unfilter_instance'),
            mock.patch.object(self.compute.conductor_api,
                              'network_migrate_instance_start'),
            mock.patch.object(self.compute.compute_rpcapi,
                              'post_live_migration_at_destination'),
            mock.patch.object(self.compute.driver, 'unplug_vifs'),
            mock.patch.object(self.compute.network_api,
                              'setup_networks_on_host')
        ) as (
            post_live_migration, unfilter_instance,
            network_migrate_instance_start, post_live_migration_at_destination,
            unplug_vifs, setup_networks_on_host
        ):
            self.compute._post_live_migration(c, inst_ref, dest)

            post_live_migration.assert_has_calls([
                mock.call(c, inst_ref, {'block_device_mapping': []})])
            unfilter_instance.assert_has_calls([mock.call(inst_ref, [])])
            migration = {'source_compute': srchost,
                         'dest_compute': dest, }
            network_migrate_instance_start.assert_has_calls([
                mock.call(c, inst_ref, migration)])
            post_live_migration_at_destination.assert_has_calls([
                mock.call(c, inst_ref, False, dest)])
            unplug_vifs.assert_has_calls([mock.call(inst_ref, [])])
            setup_networks_on_host.assert_has_calls([
                mock.call(c, inst_ref, self.compute.host, teardown=True)])

    def _begin_post_live_migration_at_destination(self):
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_networks_on_host')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'network_migrate_instance_finish')
        self.mox.StubOutWithMock(self.compute, '_get_power_state')
        self.mox.StubOutWithMock(self.compute, '_get_compute_info')

        params = {'task_state': task_states.MIGRATING,
                  'power_state': power_state.PAUSED, }
        self.instance = jsonutils.to_primitive(
                                  self._create_fake_instance(params))

        self.admin_ctxt = context.get_admin_context()
        self.instance = db.instance_get_by_uuid(self.admin_ctxt,
                                                self.instance['uuid'])

        self.compute.network_api.setup_networks_on_host(self.admin_ctxt,
                                                        self.instance,
                                                        self.compute.host)
        migration = {'source_compute': self.instance['host'],
                     'dest_compute': self.compute.host, }
        self.compute.conductor_api.network_migrate_instance_finish(
                self.admin_ctxt, self.instance, migration)
        fake_net_info = []
        fake_block_dev_info = {'foo': 'bar'}
        self.compute.driver.post_live_migration_at_destination(self.admin_ctxt,
                self.instance,
                fake_net_info,
                False,
                fake_block_dev_info)
        self.compute._get_power_state(self.admin_ctxt,
                                      self.instance).AndReturn(
                                                     'fake_power_state')

    def _finish_post_live_migration_at_destination(self):
        self.compute.network_api.setup_networks_on_host(self.admin_ctxt,
                mox.IgnoreArg(), self.compute.host)

        fake_notifier.NOTIFICATIONS = []
        self.mox.ReplayAll()

        self.compute.post_live_migration_at_destination(self.admin_ctxt,
                                                        self.instance)

        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'compute.instance.live_migration.post.dest.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'compute.instance.live_migration.post.dest.end')

        return self.compute.conductor_api.instance_get_by_uuid(self.admin_ctxt,
                                                        self.instance['uuid'])

    def test_post_live_migration_at_destination_with_compute_info(self):
        """The instance's node property should be updated correctly."""
        self._begin_post_live_migration_at_destination()
        hypervisor_hostname = 'fake_hypervisor_hostname'
        fake_compute_info = {'hypervisor_hostname': hypervisor_hostname}
        self.compute._get_compute_info(mox.IgnoreArg(),
                                       mox.IgnoreArg()).AndReturn(
                                                        fake_compute_info)
        updated = self._finish_post_live_migration_at_destination()
        self.assertEqual(updated['node'], hypervisor_hostname)

    def test_post_live_migration_at_destination_without_compute_info(self):
        """The instance's node property should be set to None if we fail to
           get compute_info.
        """
        self._begin_post_live_migration_at_destination()
        self.compute._get_compute_info(mox.IgnoreArg(),
                                       mox.IgnoreArg()).AndRaise(
                                                        exception.NotFound())
        updated = self._finish_post_live_migration_at_destination()
        self.assertIsNone(updated['node'])

    def test_rollback_live_migration_at_destination_correctly(self):
        # creating instance testdata
        c = context.get_admin_context()
        instance_ref = self._create_fake_instance({'host': 'dummy'})
        inst_uuid = instance_ref['uuid']
        inst_id = instance_ref['id']

        instance = jsonutils.to_primitive(db.instance_get(c, inst_id))
        fake_notifier.NOTIFICATIONS = []

        self.mox.StubOutWithMock(self.compute.network_api,
                                 'setup_networks_on_host')
        self.compute.network_api.setup_networks_on_host(c, instance,
                                                        self.compute.host,
                                                        teardown=True)

        # start test
        self.mox.ReplayAll()
        ret = self.compute.rollback_live_migration_at_destination(c,
                                          instance=instance)
        self.assertEqual(ret, None)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                       'compute.instance.live_migration.rollback.dest.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                        'compute.instance.live_migration.rollback.dest.end')

        # cleanup
        db.instance_destroy(c, inst_uuid)

    def test_run_kill_vm(self):
        # Detect when a vm is terminated behind the scenes.
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(self.context)
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        instance_name = instances[0]['name']
        self.compute.driver.test_remove_vm(instance_name)

        # Force the compute manager to do its periodic poll
        ctxt = context.get_admin_context()
        self.compute._sync_power_states(ctxt)

        instances = db.instance_get_all(self.context)
        LOG.info(_("After force-killing instances: %s"), instances)
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['task_state'], None)

    def test_add_instance_fault(self):
        instance = self._create_fake_instance()
        exc_info = None

        def fake_db_fault_create(ctxt, values):
            self.assertTrue('raise NotImplementedError' in values['details'])
            del values['details']

            expected = {
                'code': 500,
                'message': 'test',
                'instance_uuid': instance['uuid'],
                'host': self.compute.host
            }
            self.assertEquals(expected, values)

        try:
            raise NotImplementedError('test')
        except NotImplementedError:
            exc_info = sys.exc_info()

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        compute_utils.add_instance_fault_from_exc(ctxt,
                                                  self.compute.conductor_api,
                                                  instance,
                                                  NotImplementedError('test'),
                                                  exc_info)

    def test_add_instance_fault_with_remote_error(self):
        instance = self._create_fake_instance()
        exc_info = None

        def fake_db_fault_create(ctxt, values):
            self.assertTrue('raise rpc_common.RemoteError'
                in values['details'])
            del values['details']

            expected = {
                'code': 500,
                'instance_uuid': instance['uuid'],
                'message': 'Remote error: test My Test Message\nNone.',
                'host': self.compute.host
            }
            self.assertEquals(expected, values)

        try:
            raise rpc_common.RemoteError('test', 'My Test Message')
        except rpc_common.RemoteError as exc:
            exc_info = sys.exc_info()

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        compute_utils.add_instance_fault_from_exc(ctxt,
            self.compute.conductor_api, instance, exc, exc_info)

    def test_add_instance_fault_user_error(self):
        instance = self._create_fake_instance()
        exc_info = None

        def fake_db_fault_create(ctxt, values):

            expected = {
                'code': 400,
                'message': 'fake details',
                'details': '',
                'instance_uuid': instance['uuid'],
                'host': self.compute.host
            }
            self.assertEquals(expected, values)

        user_exc = exception.Invalid('fake details', code=400)

        try:
            raise user_exc
        except exception.Invalid:
            exc_info = sys.exc_info()

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        compute_utils.add_instance_fault_from_exc(ctxt,
            self.compute.conductor_api, instance, user_exc, exc_info)

    def test_add_instance_fault_no_exc_info(self):
        instance = self._create_fake_instance()

        def fake_db_fault_create(ctxt, values):
            expected = {
                'code': 500,
                'message': 'test',
                'details': '',
                'instance_uuid': instance['uuid'],
                'host': self.compute.host
            }
            self.assertEquals(expected, values)

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        compute_utils.add_instance_fault_from_exc(ctxt,
                                                  self.compute.conductor_api,
                                                  instance,
                                                  NotImplementedError('test'))

    def test_add_instance_fault_long_message(self):
        instance = self._create_fake_instance()

        message = 300 * 'a'

        def fake_db_fault_create(ctxt, values):
            expected = {
                'code': 500,
                'message': message[:255],
                'details': '',
                'instance_uuid': instance['uuid'],
                'host': self.compute.host
            }
            self.assertEquals(expected, values)

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        compute_utils.add_instance_fault_from_exc(ctxt,
                                                  self.compute.conductor_api,
                                                  instance,
                                                  NotImplementedError(message))

    def test_cleanup_running_deleted_instances(self):
        admin_context = context.get_admin_context()
        deleted_at = (timeutils.utcnow() -
                      datetime.timedelta(hours=1, minutes=5))
        instance1 = self._create_fake_instance({"deleted_at": deleted_at,
                                                "deleted": True})
        instance2 = self._create_fake_instance({"deleted_at": deleted_at,
                                                "deleted": True})

        self.mox.StubOutWithMock(self.compute, '_get_instances_on_driver')
        self.compute._get_instances_on_driver(
            admin_context, {'deleted': True,
                            'soft_deleted': False,
                            'host': self.compute.host}).AndReturn([instance1,
                                                                   instance2])
        self.flags(running_deleted_instance_timeout=3600,
                   running_deleted_instance_action='reap')

        bdms = []

        self.mox.StubOutWithMock(self.compute, "_shutdown_instance")
        # Simulate an error and make sure cleanup proceeds with next instance.
        self.compute._shutdown_instance(admin_context,
                                        instance1,
                                        bdms,
                                        notify=False).\
                                        AndRaise(test.TestingException)
        self.compute._shutdown_instance(admin_context,
                                        instance2,
                                        bdms,
                                        notify=False).AndReturn(None)

        self.mox.StubOutWithMock(self.compute, "_cleanup_volumes")
        self.compute._cleanup_volumes(admin_context,
                                      instance1['uuid'],
                                      bdms).AndReturn(None)

        self.mox.ReplayAll()
        self.compute._cleanup_running_deleted_instances(admin_context)

    def test_running_deleted_instances(self):
        admin_context = context.get_admin_context()

        self.compute.host = 'host'

        instance1 = {}
        instance1['deleted'] = True
        instance1['deleted_at'] = "sometimeago"

        self.mox.StubOutWithMock(self.compute, '_get_instances_on_driver')
        self.compute._get_instances_on_driver(
            admin_context, {'deleted': True,
                            'soft_deleted': False,
                            'host': self.compute.host}).AndReturn([instance1])

        self.mox.StubOutWithMock(timeutils, 'is_older_than')
        timeutils.is_older_than('sometimeago',
                    CONF.running_deleted_instance_timeout).AndReturn(True)

        self.mox.ReplayAll()
        val = self.compute._running_deleted_instances(admin_context)
        self.assertEqual(val, [instance1])

    def test_get_instance_nw_info(self):
        fake_network.unset_stub_network_methods(self.stubs)

        fake_instance = {'uuid': 'fake-instance'}
        fake_nw_info = network_model.NetworkInfo()

        self.mox.StubOutWithMock(self.compute.network_api,
                                 'get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'instance_info_cache_update')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'instance_get_by_uuid')

        self.compute.conductor_api.instance_get_by_uuid(
            self.context, fake_instance['uuid']).AndReturn(fake_instance)
        self.compute.network_api.get_instance_nw_info(self.context,
                fake_instance).AndReturn(fake_nw_info)

        self.mox.ReplayAll()

        result = self.compute._get_instance_nw_info(self.context,
                                                    fake_instance)
        self.assertEqual(fake_nw_info, result)

    def test_heal_instance_info_cache(self):
        # Update on every call for the test
        self.flags(heal_instance_info_cache_interval=-1)
        ctxt = context.get_admin_context()

        instance_map = {}
        instances = []
        for x in xrange(5):
            inst_uuid = 'fake-uuid-%s' % x
            instance_map[inst_uuid] = fake_instance.fake_db_instance(
                uuid=inst_uuid, host=CONF.host, created_at=None)
            # These won't be in our instance since they're not requested
            instances.append(instance_map[inst_uuid])

        call_info = {'get_all_by_host': 0, 'get_by_uuid': 0,
                'get_nw_info': 0, 'expected_instance': None}

        def fake_instance_get_all_by_host(context, host, columns_to_join):
            call_info['get_all_by_host'] += 1
            self.assertEqual([], columns_to_join)
            return instances[:]

        def fake_instance_get_by_uuid(context, instance_uuid, columns_to_join):
            if instance_uuid not in instance_map:
                raise exception.InstanceNotFound(instance_id=instance_uuid)
            call_info['get_by_uuid'] += 1
            self.assertEqual(['system_metadata'], columns_to_join)
            return instance_map[instance_uuid]

        # NOTE(comstud): Override the stub in setUp()
        def fake_get_instance_nw_info(context, instance):
            # Note that this exception gets caught in compute/manager
            # and is ignored.  However, the below increment of
            # 'get_nw_info' won't happen, and you'll get an assert
            # failure checking it below.
            self.assertEqual(call_info['expected_instance']['uuid'],
                             instance['uuid'])
            call_info['get_nw_info'] += 1

        self.stubs.Set(db, 'instance_get_all_by_host',
                fake_instance_get_all_by_host)
        self.stubs.Set(db, 'instance_get_by_uuid',
                fake_instance_get_by_uuid)
        self.stubs.Set(self.compute, '_get_instance_nw_info',
                fake_get_instance_nw_info)

        call_info['expected_instance'] = instances[0]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(1, call_info['get_all_by_host'])
        self.assertEqual(0, call_info['get_by_uuid'])
        self.assertEqual(1, call_info['get_nw_info'])

        call_info['expected_instance'] = instances[1]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(1, call_info['get_all_by_host'])
        self.assertEqual(1, call_info['get_by_uuid'])
        self.assertEqual(2, call_info['get_nw_info'])

        # Make an instance switch hosts
        instances[2]['host'] = 'not-me'
        # Make an instance disappear
        instance_map.pop(instances[3]['uuid'])
        # '2' and '3' should be skipped..
        call_info['expected_instance'] = instances[4]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(call_info['get_all_by_host'], 1)
        # Incremented for '2' and '4'.. '3' caused a raise above.
        self.assertEqual(call_info['get_by_uuid'], 3)
        self.assertEqual(call_info['get_nw_info'], 3)
        # Should be no more left.
        self.assertEqual(len(self.compute._instance_uuids_to_heal), 0)

        # This should cause a DB query now so we get first instance
        # back again
        call_info['expected_instance'] = instances[0]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(call_info['get_all_by_host'], 2)
        # Stays the same, because the instance came from the DB
        self.assertEqual(call_info['get_by_uuid'], 3)
        self.assertEqual(call_info['get_nw_info'], 4)

    def test_poll_rescued_instances(self):
        timed_out_time = timeutils.utcnow() - datetime.timedelta(minutes=5)
        not_timed_out_time = timeutils.utcnow()

        instances = [{'uuid': 'fake_uuid1', 'vm_state': vm_states.RESCUED,
                      'launched_at': timed_out_time},
                     {'uuid': 'fake_uuid2', 'vm_state': vm_states.RESCUED,
                      'launched_at': timed_out_time},
                     {'uuid': 'fake_uuid3', 'vm_state': vm_states.RESCUED,
                      'launched_at': not_timed_out_time}]
        unrescued_instances = {'fake_uuid1': False, 'fake_uuid2': False}

        def fake_instance_get_all_by_filters(context, filters,
                                             columns_to_join):
            self.assertEqual(columns_to_join, [])
            return instances

        def fake_unrescue(context, instance):
            unrescued_instances[instance['uuid']] = True

        self.stubs.Set(self.compute.conductor_api,
                       'instance_get_all_by_filters',
                       fake_instance_get_all_by_filters)
        self.stubs.Set(self.compute.conductor_api, 'compute_unrescue',
                       fake_unrescue)

        self.flags(rescue_timeout=60)
        ctxt = context.get_admin_context()

        self.compute._poll_rescued_instances(ctxt)

        for instance in unrescued_instances.values():
            self.assertTrue(instance)

    def test_poll_unconfirmed_resizes(self):
        instances = [
            fake_instance.fake_db_instance(uuid='fake_uuid1',
                                           vm_state=vm_states.RESIZED,
                                           task_state=None),
            fake_instance.fake_db_instance(uuid='noexist'),
            fake_instance.fake_db_instance(uuid='fake_uuid2',
                                           vm_state=vm_states.ERROR,
                                           task_state=None),
            fake_instance.fake_db_instance(uuid='fake_uuid3',
                                           vm_state=vm_states.ACTIVE,
                                           task_state=
                                           task_states.REBOOTING),
            fake_instance.fake_db_instance(uuid='fake_uuid4',
                                           vm_state=vm_states.RESIZED,
                                           task_state=None),
            fake_instance.fake_db_instance(uuid='fake_uuid5',
                                           vm_state=vm_states.ACTIVE,
                                           task_state=None),
            fake_instance.fake_db_instance(uuid='fake_uuid6',
                                           vm_state=vm_states.RESIZED,
                                           task_state='deleting')]
        expected_migration_status = {'fake_uuid1': 'confirmed',
                                     'noexist': 'error',
                                     'fake_uuid2': 'error',
                                     'fake_uuid3': 'error',
                                     'fake_uuid4': None,
                                     'fake_uuid5': 'error',
                                     'fake_uuid6': 'error'}
        migrations = []
        for i, instance in enumerate(instances, start=1):
            fake_mig = test_migration.fake_db_migration()
            fake_mig.update({'id': i,
                             'instance_uuid': instance['uuid'],
                             'status': None})
            migrations.append(fake_mig)

        def fake_instance_get_by_uuid(context, instance_uuid,
                columns_to_join=None):
            self.assertIn('metadata', columns_to_join)
            self.assertIn('system_metadata', columns_to_join)
            # raise InstanceNotFound exception for uuid 'noexist'
            if instance_uuid == 'noexist':
                raise exception.InstanceNotFound(instance_id=instance_uuid)
            for instance in instances:
                if instance['uuid'] == instance_uuid:
                    return instance

        def fake_migration_get_unconfirmed_by_dest_compute(context,
                resize_confirm_window, dest_compute):
            self.assertEqual(dest_compute, CONF.host)
            return migrations

        def fake_migration_update(context, mid, updates):
            for migration in migrations:
                if migration['id'] == mid:
                    migration.update(updates)
                    return migration

        def fake_confirm_resize(context, instance, migration=None):
            # raise exception for 'fake_uuid4' to check migration status
            # does not get set to 'error' on confirm_resize failure.
            if instance['uuid'] == 'fake_uuid4':
                raise test.TestingException('bomb')
            self.assertNotEqual(migration, None)
            for migration2 in migrations:
                if (migration2['instance_uuid'] ==
                        migration['instance_uuid']):
                    migration2['status'] = 'confirmed'

        self.stubs.Set(db, 'instance_get_by_uuid',
                fake_instance_get_by_uuid)
        self.stubs.Set(db, 'migration_get_unconfirmed_by_dest_compute',
                fake_migration_get_unconfirmed_by_dest_compute)
        self.stubs.Set(db, 'migration_update', fake_migration_update)
        self.stubs.Set(self.compute.compute_api, 'confirm_resize',
                fake_confirm_resize)

        def fetch_instance_migration_status(instance_uuid):
            for migration in migrations:
                if migration['instance_uuid'] == instance_uuid:
                    return migration['status']

        self.flags(resize_confirm_window=60)
        ctxt = context.get_admin_context()

        self.compute._poll_unconfirmed_resizes(ctxt)

        for uuid, status in expected_migration_status.iteritems():
            self.assertEqual(status, fetch_instance_migration_status(uuid))

    def test_instance_build_timeout_disabled(self):
        self.flags(instance_build_timeout=0)
        ctxt = context.get_admin_context()
        called = {'get_all': False, 'set_error_state': 0}
        created_at = timeutils.utcnow() + datetime.timedelta(seconds=-60)

        def fake_instance_get_all_by_filters(context, filters, *args, **kw):
            called['get_all'] = True
            self.assertIn('host', filters)
            self.assertEqual(kw['columns_to_join'], [])
            return instances[:]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                fake_instance_get_all_by_filters)

        def fake_set_instance_error_state(_ctxt, instance_uuid, **kwargs):
            called['set_error_state'] += 1

        self.stubs.Set(self.compute, '_set_instance_error_state',
                fake_set_instance_error_state)

        instance_map = {}
        instances = []
        for x in xrange(5):
            uuid = 'fake-uuid-%s' % x
            instance_map[uuid] = {'uuid': uuid, 'host': CONF.host,
                    'vm_state': vm_states.BUILDING,
                    'created_at': created_at}
            instances.append(instance_map[uuid])

        self.compute._check_instance_build_time(ctxt)
        self.assertFalse(called['get_all'])
        self.assertEqual(called['set_error_state'], 0)

    def test_instance_build_timeout(self):
        self.flags(instance_build_timeout=30)
        ctxt = context.get_admin_context()
        called = {'get_all': False, 'set_error_state': 0}
        created_at = timeutils.utcnow() + datetime.timedelta(seconds=-60)

        def fake_instance_get_all_by_filters(*args, **kwargs):
            called['get_all'] = True
            return instances[:]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                fake_instance_get_all_by_filters)

        def fake_set_instance_error_state(_ctxt, instance_uuid, **kwargs):
            called['set_error_state'] += 1

        self.stubs.Set(self.compute, '_set_instance_error_state',
                fake_set_instance_error_state)

        instance_map = {}
        instances = []
        for x in xrange(5):
            uuid = 'fake-uuid-%s' % x
            instance_map[uuid] = {'uuid': uuid, 'host': CONF.host,
                    'vm_state': vm_states.BUILDING,
                    'created_at': created_at}
            instances.append(instance_map[uuid])

        self.compute._check_instance_build_time(ctxt)
        self.assertTrue(called['get_all'])
        self.assertEqual(called['set_error_state'], 5)

    def test_instance_build_timeout_mixed_instances(self):
        self.flags(instance_build_timeout=30)
        ctxt = context.get_admin_context()
        called = {'get_all': False, 'set_error_state': 0}
        created_at = timeutils.utcnow() + datetime.timedelta(seconds=-60)

        def fake_instance_get_all_by_filters(*args, **kwargs):
            called['get_all'] = True
            return instances[:]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                fake_instance_get_all_by_filters)

        def fake_set_instance_error_state(_ctxt, instance_uuid, **kwargs):
            called['set_error_state'] += 1

        self.stubs.Set(self.compute, '_set_instance_error_state',
                fake_set_instance_error_state)

        instance_map = {}
        instances = []
        #expired instances
        for x in xrange(4):
            uuid = 'fake-uuid-%s' % x
            instance_map[uuid] = {'uuid': uuid, 'host': CONF.host,
                    'vm_state': vm_states.BUILDING,
                    'created_at': created_at}
            instances.append(instance_map[uuid])

        #not expired
        uuid = 'fake-uuid-5'
        instance_map[uuid] = {
            'uuid': uuid,
            'host': CONF.host,
            'vm_state': vm_states.BUILDING,
            'created_at': timeutils.utcnow(),
        }
        instances.append(instance_map[uuid])

        self.compute._check_instance_build_time(ctxt)
        self.assertTrue(called['get_all'])
        self.assertEqual(called['set_error_state'], 4)

    def test_get_resource_tracker_fail(self):
        self.assertRaises(exception.NovaException,
                          self.compute._get_resource_tracker,
                          'invalidnodename')

    def test_instance_update_host_check(self):
        # make sure rt usage doesn't happen if the host or node is different
        def fail_get(nodename):
            raise test.TestingException(_("wrong host/node"))
        self.stubs.Set(self.compute, '_get_resource_tracker', fail_get)

        instance = self._create_fake_instance({'host': 'someotherhost'})
        self.compute._instance_update(self.context, instance['uuid'])

        instance = self._create_fake_instance({'node': 'someothernode'})
        self.compute._instance_update(self.context, instance['uuid'])

        params = {'host': 'someotherhost', 'node': 'someothernode'}
        instance = self._create_fake_instance(params)
        self.compute._instance_update(self.context, instance['uuid'])

    def test_destroy_evacuated_instance_on_shared_storage(self):
        fake_context = context.get_admin_context()

        # instances in central db
        instances = [
            # those are still related to this host
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host})),
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host})),
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host}))
        ]

        # those are already been evacuated to other host
        evacuated_instance = self._create_fake_instance({'host': 'otherhost'})

        instances.append(evacuated_instance)

        self.mox.StubOutWithMock(self.compute,
                                 '_get_instances_on_driver')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_volume_block_device_info')
        self.mox.StubOutWithMock(self.compute,
                                 '_is_instance_storage_shared')
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')

        self.compute._get_instances_on_driver(
                fake_context, {'deleted': False}).AndReturn(instances)
        self.compute._get_instance_nw_info(fake_context,
                                           evacuated_instance).AndReturn(
                                                   'fake_network_info')
        self.compute._get_instance_volume_block_device_info(
                fake_context, evacuated_instance).AndReturn('fake_bdi')
        self.compute._is_instance_storage_shared(fake_context,
                        evacuated_instance).AndReturn(True)
        self.compute.driver.destroy(evacuated_instance,
                                    'fake_network_info',
                                    'fake_bdi',
                                    False)

        self.mox.ReplayAll()
        self.compute._destroy_evacuated_instances(fake_context)

    def test_destroy_evacuated_instance_with_disks(self):
        fake_context = context.get_admin_context()

        # instances in central db
        instances = [
            # those are still related to this host
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host})),
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host})),
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host}))
        ]

        # those are already been evacuated to other host
        evacuated_instance = self._create_fake_instance({'host': 'otherhost'})

        instances.append(evacuated_instance)

        self.mox.StubOutWithMock(self.compute,
                                 '_get_instances_on_driver')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_volume_block_device_info')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_instance_shared_storage_local')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'check_instance_shared_storage')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_instance_shared_storage_cleanup')
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')

        self.compute._get_instances_on_driver(
                fake_context, {'deleted': False}).AndReturn(instances)
        self.compute._get_instance_nw_info(fake_context,
                                           evacuated_instance).AndReturn(
                                                   'fake_network_info')
        self.compute._get_instance_volume_block_device_info(
                fake_context, evacuated_instance).AndReturn('fake_bdi')
        self.compute.driver.check_instance_shared_storage_local(fake_context,
                evacuated_instance).AndReturn({'filename': 'tmpfilename'})
        self.compute.compute_rpcapi.check_instance_shared_storage(fake_context,
                evacuated_instance,
                {'filename': 'tmpfilename'}).AndReturn(False)
        self.compute.driver.check_instance_shared_storage_cleanup(fake_context,
                {'filename': 'tmpfilename'})
        self.compute.driver.destroy(evacuated_instance,
                                    'fake_network_info',
                                    'fake_bdi',
                                    True)

        self.mox.ReplayAll()
        self.compute._destroy_evacuated_instances(fake_context)

    def test_destroy_evacuated_instance_not_implemented(self):
        fake_context = context.get_admin_context()

        # instances in central db
        instances = [
            # those are still related to this host
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host})),
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host})),
            jsonutils.to_primitive(self._create_fake_instance(
                                                {'host': self.compute.host}))
        ]

        # those are already been evacuated to other host
        evacuated_instance = self._create_fake_instance({'host': 'otherhost'})

        instances.append(evacuated_instance)

        self.mox.StubOutWithMock(self.compute,
                                 '_get_instances_on_driver')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_nw_info')
        self.mox.StubOutWithMock(self.compute,
                                 '_get_instance_volume_block_device_info')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_instance_shared_storage_local')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'check_instance_shared_storage')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_instance_shared_storage_cleanup')
        self.mox.StubOutWithMock(self.compute.driver, 'destroy')

        self.compute._get_instances_on_driver(
                fake_context, {'deleted': False}).AndReturn(instances)
        self.compute._get_instance_nw_info(fake_context,
                                           evacuated_instance).AndReturn(
                                                   'fake_network_info')
        self.compute._get_instance_volume_block_device_info(
                fake_context, evacuated_instance).AndReturn('fake_bdi')
        self.compute.driver.check_instance_shared_storage_local(fake_context,
                evacuated_instance).AndRaise(NotImplementedError())
        self.compute.driver.destroy(evacuated_instance,
                                    'fake_network_info',
                                    'fake_bdi',
                                    True)

        self.mox.ReplayAll()
        self.compute._destroy_evacuated_instances(fake_context)

    def test_complete_partial_deletion(self):
        admin_context = context.get_admin_context()
        instance = {
            'id': '1',
            'vm_state': vm_states.DELETED,
            'task_state': None,
            'system_metadata': [{'key': 'fake_key', 'value': 'fake_value'}],
            'vcpus': 1,
            'memory_mb': 1,
            'project_id': 'fake-prj',
            'user_id': 'fake-user',
            'deleted': 0
            }

        def fake_conductor(context, instance):
            instance['deleted'] = instance['id']

        self.stubs.Set(self.compute.conductor_api,
                       'instance_destroy',
                        fake_conductor)

        self.stubs.Set(self.compute,
                       '_get_instance_volume_bdms',
                       lambda *a, **k: None)

        self.stubs.Set(self.compute,
                       '_complete_deletion',
                       lambda *a, **k: None)

        self.stubs.Set(quotas_obj.Quotas, 'reserve', lambda *a, **k: None)

        self.compute._complete_partial_deletion(admin_context, instance)

        self.assertFalse(instance['deleted'] == 0)

    def test_init_instance_for_partial_deletion(self):
        admin_context = context.get_admin_context()
        instance = {'id': '1',
                    'vm_state': vm_states.DELETED,
                    'deleted': 0
                    }

        def fake_partial_deletion(context, instance):
            instance['deleted'] = instance['id']

        self.stubs.Set(self.compute,
                       '_complete_partial_deletion',
                       fake_partial_deletion)
        self.compute._init_instance(admin_context, instance)

        self.assertFalse(instance['deleted'] == 0)

    def test_partial_deletion_raise_exception(self):
        admin_context = context.get_admin_context()
        instance = {'id': '1',
                    'vm_state': vm_states.DELETED,
                    'deleted': 0
                    }
        self.mox.StubOutWithMock(self.compute, '_complete_partial_deletion')
        self.compute._complete_partial_deletion(
                                 admin_context, instance).AndRaise(ValueError)
        self.mox.ReplayAll()

        self.compute._init_instance(admin_context, instance)

    def test_add_remove_fixed_ip_updates_instance_updated_at(self):
        def _noop(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.network_api,
                       'add_fixed_ip_to_instance', _noop)
        self.stubs.Set(self.compute.network_api,
                       'remove_fixed_ip_from_instance', _noop)

        instance = self._create_fake_instance()
        updated_at_1 = instance['updated_at']

        self.compute.add_fixed_ip_to_instance(self.context, 'fake', instance)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        updated_at_2 = instance['updated_at']

        self.compute.remove_fixed_ip_from_instance(self.context, 'fake',
                                                   instance)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        updated_at_3 = instance['updated_at']

        updated_ats = (updated_at_1, updated_at_2, updated_at_3)
        self.assertEqual(len(updated_ats), len(set(updated_ats)))

    def test_no_pending_deletes_for_soft_deleted_instances(self):
        self.flags(reclaim_instance_interval=0)
        ctxt = context.get_admin_context()

        instance = self._create_fake_instance(
                params={'host': CONF.host,
                        'vm_state': vm_states.SOFT_DELETED,
                        'deleted_at': timeutils.utcnow()})

        self.compute._run_pending_deletes(ctxt)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertFalse(instance['cleaned'])

    def test_reclaim_queued_deletes(self):
        self.flags(reclaim_instance_interval=3600)
        ctxt = context.get_admin_context()

        # Active
        self._create_fake_instance(params={'host': CONF.host})

        # Deleted not old enough
        self._create_fake_instance(params={'host': CONF.host,
                                           'vm_state': vm_states.SOFT_DELETED,
                                           'deleted_at': timeutils.utcnow()})

        # Deleted old enough (only this one should be reclaimed)
        deleted_at = (timeutils.utcnow() -
                      datetime.timedelta(hours=1, minutes=5))
        instance = self._create_fake_instance(
                params={'host': CONF.host,
                        'vm_state': vm_states.SOFT_DELETED,
                        'deleted_at': deleted_at})

        # Restoring
        # NOTE(hanlind): This specifically tests for a race condition
        # where restoring a previously soft deleted instance sets
        # deleted_at back to None, causing reclaim to think it can be
        # deleted, see LP #1186243.
        self._create_fake_instance(
                params={'host': CONF.host,
                        'vm_state': vm_states.SOFT_DELETED,
                        'task_state': task_states.RESTORING})

        self.mox.StubOutWithMock(self.compute, '_delete_instance')
        self.compute._delete_instance(ctxt, mox.IsA(instance_obj.Instance), [])

        self.mox.ReplayAll()

        self.compute._reclaim_queued_deletes(ctxt)

    def test_reclaim_queued_deletes_continue_on_error(self):
        # Verify that reclaim continues on error.
        self.flags(reclaim_instance_interval=3600)
        ctxt = context.get_admin_context()

        deleted_at = (timeutils.utcnow() -
                      datetime.timedelta(hours=1, minutes=5))
        instance1 = self._create_fake_instance_obj(
                params={'host': CONF.host,
                        'vm_state': vm_states.SOFT_DELETED,
                        'deleted_at': deleted_at})
        instance2 = self._create_fake_instance_obj(
                params={'host': CONF.host,
                        'vm_state': vm_states.SOFT_DELETED,
                        'deleted_at': deleted_at})
        instances = []
        instances.append(instance1)
        instances.append(instance2)

        self.mox.StubOutWithMock(instance_obj.InstanceList,
                                 'get_by_filters')
        self.mox.StubOutWithMock(self.compute, '_deleted_old_enough')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(self.compute, '_delete_instance')

        instance_obj.InstanceList.get_by_filters(
            ctxt, mox.IgnoreArg(),
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS
            ).AndReturn(instances)

        # The first instance delete fails.
        self.compute._deleted_old_enough(instance1, 3600).AndReturn(True)
        self.compute.conductor_api.block_device_mapping_get_all_by_instance(
                ctxt, instance1).AndReturn(None)
        self.compute._delete_instance(ctxt, instance1,
                                      None).AndRaise(test.TestingException)

        # The second instance delete that follows.
        self.compute._deleted_old_enough(instance2, 3600).AndReturn(True)
        self.compute.conductor_api.block_device_mapping_get_all_by_instance(
                ctxt, instance2).AndReturn(None)
        self.compute._delete_instance(ctxt, instance2,
                                      None)

        self.mox.ReplayAll()

        self.compute._reclaim_queued_deletes(ctxt)

    def test_sync_power_states(self):
        ctxt = self.context.elevated()
        self._create_fake_instance({'host': self.compute.host})
        self._create_fake_instance({'host': self.compute.host})
        self._create_fake_instance({'host': self.compute.host})
        self.mox.StubOutWithMock(self.compute.driver, 'get_info')
        self.mox.StubOutWithMock(self.compute, '_sync_instance_power_state')

        # Check to make sure task continues on error.
        self.compute.driver.get_info(mox.IgnoreArg()).AndRaise(
            exception.InstanceNotFound(instance_id='fake-uuid'))
        self.compute._sync_instance_power_state(ctxt, mox.IgnoreArg(),
                                                power_state.NOSTATE).AndRaise(
            exception.InstanceNotFound(instance_id='fake-uuid'))

        self.compute.driver.get_info(mox.IgnoreArg()).AndReturn(
            {'state': power_state.RUNNING})
        self.compute._sync_instance_power_state(ctxt, mox.IgnoreArg(),
                                                power_state.RUNNING)
        self.compute.driver.get_info(mox.IgnoreArg()).AndReturn(
            {'state': power_state.SHUTDOWN})
        self.compute._sync_instance_power_state(ctxt, mox.IgnoreArg(),
                                                power_state.SHUTDOWN)
        self.mox.ReplayAll()
        self.compute._sync_power_states(ctxt)

    def _test_lifecycle_event(self, lifecycle_event, power_state):
        instance = self._create_fake_instance()
        uuid = instance['uuid']

        self.mox.StubOutWithMock(self.compute, '_sync_instance_power_state')
        if power_state != None:
            self.compute._sync_instance_power_state(
                mox.IgnoreArg(),
                mox.ContainsKeyValue('uuid', uuid),
                power_state)
        self.mox.ReplayAll()
        self.compute.handle_events(event.LifecycleEvent(uuid, lifecycle_event))
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def test_lifecycle_events(self):
        self._test_lifecycle_event(event.EVENT_LIFECYCLE_STOPPED,
                                   power_state.SHUTDOWN)
        self._test_lifecycle_event(event.EVENT_LIFECYCLE_STARTED,
                                   power_state.RUNNING)
        self._test_lifecycle_event(event.EVENT_LIFECYCLE_PAUSED,
                                   power_state.PAUSED)
        self._test_lifecycle_event(event.EVENT_LIFECYCLE_RESUMED,
                                   power_state.RUNNING)
        self._test_lifecycle_event(-1, None)

    def test_lifecycle_event_non_existent_instance(self):
        # No error raised for non-existent instance because of inherent race
        # between database updates and hypervisor events. See bug #1180501.
        event_instance = event.LifecycleEvent('does-not-exist',
                event.EVENT_LIFECYCLE_STOPPED)
        self.compute.handle_events(event_instance)

    def test_allow_confirm_resize_on_instance_in_deleting_task_state(self):
        instance = self._create_fake_instance_obj()
        old_type = flavors.extract_flavor(instance)
        new_type = flavors.get_flavor_by_flavor_id('4')
        sys_meta = instance.system_metadata
        sys_meta = flavors.save_flavor_info(sys_meta,
                                            old_type, 'old_')
        sys_meta = flavors.save_flavor_info(sys_meta,
                                            new_type, 'new_')
        sys_meta = flavors.save_flavor_info(sys_meta,
                                            new_type)

        fake_rt = self.mox.CreateMockAnything()

        def fake_drop_resize_claim(*args, **kwargs):
            pass

        def fake_get_resource_tracker(self):
            return fake_rt

        def fake_setup_networks_on_host(self, *args, **kwargs):
            pass

        self.stubs.Set(fake_rt, 'drop_resize_claim', fake_drop_resize_claim)
        self.stubs.Set(self.compute, '_get_resource_tracker',
                       fake_get_resource_tracker)
        self.stubs.Set(self.compute.network_api, 'setup_networks_on_host',
                       fake_setup_networks_on_host)

        migration = migration_obj.Migration()
        migration.instance_uuid = instance.uuid
        migration.status = 'finished'
        migration.create(self.context.elevated())

        instance.task_state = task_states.DELETING
        instance.vm_state = vm_states.RESIZED
        instance.system_metadata = sys_meta
        instance.save()

        self.compute.confirm_resize(self.context, instance=instance,
                                    migration=migration)
        instance.refresh()
        self.assertEqual(vm_states.ACTIVE, instance['vm_state'])

    def _get_instance_and_bdm_for_dev_defaults_tests(self):
        instance = self._create_fake_instance(
            params={'root_device_name': '/dev/vda'})
        block_device_mapping = [
            {'id': 3, 'instance_uuid': 'fake-instance',
             'device_name': '/dev/vda',
             'source_type': 'volume',
             'destination_type': 'volume',
             'image_id': 'fake-image-id-1',
             'boot_index': 0}]

        return instance, block_device_mapping

    def test_default_block_device_names_empty_instance_root_dev(self):
        instance, bdms = self._get_instance_and_bdm_for_dev_defaults_tests()
        instance['root_device_name'] = None
        self.mox.StubOutWithMock(self.compute, '_instance_update')
        self.mox.StubOutWithMock(self.compute,
                                 '_default_device_names_for_instance')
        self.compute._instance_update(self.context, instance['uuid'],
                                      root_device_name='/dev/vda')
        self.compute._default_device_names_for_instance(instance,
                                                        '/dev/vda',
                                                        mox.IgnoreArg(),
                                                        [], [], bdms)
        self.mox.ReplayAll()
        self.compute._default_block_device_names(self.context,
                                                 instance,
                                                 {}, bdms)

    def test_default_block_device_names_empty_root_device(self):
        instance, bdms = self._get_instance_and_bdm_for_dev_defaults_tests()
        bdms[0]['device_name'] = None
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'block_device_mapping_update')
        self.mox.StubOutWithMock(self.compute,
                                 '_default_device_names_for_instance')
        self.compute.conductor_api.block_device_mapping_update(
            self.context, bdms[0]['id'], {'device_name': '/dev/vda'})
        self.compute._default_device_names_for_instance(instance,
                                                        '/dev/vda',
                                                        mox.IgnoreArg(),
                                                        [], [], bdms)
        self.mox.ReplayAll()
        self.compute._default_block_device_names(self.context,
                                                 instance,
                                                 {}, bdms)

    def test_default_block_device_names_no_root_device(self):
        instance, bdms = self._get_instance_and_bdm_for_dev_defaults_tests()
        instance['root_device_name'] = None
        bdms[0]['device_name'] = None
        self.mox.StubOutWithMock(self.compute, '_instance_update')
        self.mox.StubOutWithMock(self.compute.conductor_api,
                                 'block_device_mapping_update')
        self.mox.StubOutWithMock(self.compute,
                                 '_default_root_device_name')
        self.mox.StubOutWithMock(self.compute,
                                 '_default_device_names_for_instance')

        self.compute._default_root_device_name(instance, mox.IgnoreArg(),
                                               bdms[0]).AndReturn('/dev/vda')
        self.compute._instance_update(self.context, instance['uuid'],
                                      root_device_name='/dev/vda')
        self.compute.conductor_api.block_device_mapping_update(
            self.context, bdms[0]['id'], {'device_name': '/dev/vda'})
        self.compute._default_device_names_for_instance(instance,
                                                        '/dev/vda',
                                                        mox.IgnoreArg(),
                                                        [], [], bdms)
        self.mox.ReplayAll()
        self.compute._default_block_device_names(self.context,
                                                 instance,
                                                 {}, bdms)


class ComputeAPITestCase(BaseTestCase):
    def setUp(self):
        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)

        super(ComputeAPITestCase, self).setUp()
        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                       fake_get_nw_info)
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())

        self.compute_api = compute.API(
                                   security_group_api=self.security_group_api)
        self.fake_image = {
            'id': 1,
            'name': 'fake_name',
            'status': 'active',
            'properties': {'kernel_id': 'fake_kernel_id',
                           'ramdisk_id': 'fake_ramdisk_id'},
        }

        def fake_show(obj, context, image_id):
            if image_id:
                return self.fake_image
            else:
                raise exception.ImageNotFound(image_id=image_id)

        self.fake_show = fake_show

    def _run_instance(self, params=None):
        instance = jsonutils.to_primitive(self._create_fake_instance(params,
                                          services=True))
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)
        return instance, instance_uuid

    def test_create_with_too_little_ram(self):
        # Test an instance type with too little memory.

        inst_type = flavors.get_default_flavor()
        inst_type['memory_mb'] = 1

        self.fake_image['min_ram'] = 2
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceTypeMemoryTooSmall,
            self.compute_api.create, self.context,
            inst_type, self.fake_image['id'])

        # Now increase the inst_type memory and make sure all is fine.
        inst_type['memory_mb'] = 2
        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, self.fake_image['id'])
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_create_with_too_little_disk(self):
        # Test an instance type with too little disk space.

        inst_type = flavors.get_default_flavor()
        inst_type['root_gb'] = 1

        self.fake_image['min_disk'] = 2
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
            self.compute_api.create, self.context,
            inst_type, self.fake_image['id'])

        # Now increase the inst_type disk space and make sure all is fine.
        inst_type['root_gb'] = 2
        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, self.fake_image['id'])
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_create_with_too_large_image(self):
        # Test an instance type with too little disk space.

        inst_type = flavors.get_default_flavor()
        inst_type['root_gb'] = 1

        self.fake_image['size'] = '1073741825'

        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
            self.compute_api.create, self.context,
            inst_type, self.fake_image['id'])

        # Reduce image to 1 GB limit and ensure it works
        self.fake_image['size'] = '1073741824'
        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, self.fake_image['id'])
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_create_just_enough_ram_and_disk(self):
        # Test an instance type with just enough ram and disk space.

        inst_type = flavors.get_default_flavor()
        inst_type['root_gb'] = 2
        inst_type['memory_mb'] = 2

        self.fake_image['min_ram'] = 2
        self.fake_image['min_disk'] = 2
        self.fake_image['name'] = 'fake_name'
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, self.fake_image['id'])
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_create_with_no_ram_and_disk_reqs(self):
        # Test an instance type with no min_ram or min_disk.

        inst_type = flavors.get_default_flavor()
        inst_type['root_gb'] = 1
        inst_type['memory_mb'] = 1

        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, self.fake_image['id'])
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_create_with_deleted_image(self):
        # If we're given a deleted image by glance, we should not be able to
        # build from it
        inst_type = flavors.get_default_flavor()

        self.fake_image['name'] = 'fake_name'
        self.fake_image['status'] = 'DELETED'
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        expected_message = (
            exception.ImageNotActive.msg_fmt % {'image_id':
            self.fake_image['id']})
        with testtools.ExpectedException(exception.ImageNotActive,
                                         expected_message):
            self.compute_api.create(self.context, inst_type,
                                    self.fake_image['id'])

    def test_create_instance_defaults_display_name(self):
        # Verify that an instance cannot be created without a display_name.
        cases = [dict(), dict(display_name=None)]
        for instance in cases:
            (ref, resv_id) = self.compute_api.create(self.context,
                flavors.get_default_flavor(),
                'fake-image-uuid', **instance)
            try:
                self.assertNotEqual(ref[0]['display_name'], None)
            finally:
                db.instance_destroy(self.context, ref[0]['uuid'])

    def test_create_instance_sets_system_metadata(self):
        # Make sure image properties are copied into system metadata.
        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=flavors.get_default_flavor(),
                image_href='fake-image-uuid')
        try:
            sys_metadata = db.instance_system_metadata_get(self.context,
                    ref[0]['uuid'])

            image_props = {'image_kernel_id': 'fake_kernel_id',
                     'image_ramdisk_id': 'fake_ramdisk_id',
                     'image_something_else': 'meow', }
            for key, value in image_props.iteritems():
                self.assertTrue(key in sys_metadata)
                self.assertEqual(value, sys_metadata[key])

        finally:
            db.instance_destroy(self.context, ref[0]['uuid'])

    def test_create_saves_type_in_system_metadata(self):
        instance_type = flavors.get_default_flavor()
        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=instance_type,
                image_href='some-fake-image')
        try:
            sys_metadata = db.instance_system_metadata_get(self.context,
                    ref[0]['uuid'])

            instance_type_props = ['name', 'memory_mb', 'vcpus', 'root_gb',
                                   'ephemeral_gb', 'flavorid', 'swap',
                                   'rxtx_factor', 'vcpu_weight']
            for key in instance_type_props:
                sys_meta_key = "instance_type_%s" % key
                self.assertTrue(sys_meta_key in sys_metadata)
                self.assertEqual(str(instance_type[key]),
                                 str(sys_metadata[sys_meta_key]))

        finally:
            db.instance_destroy(self.context, ref[0]['uuid'])

    def test_create_instance_associates_security_groups(self):
        # Make sure create associates security groups.
        group = self._create_group()
        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=flavors.get_default_flavor(),
                image_href='some-fake-image',
                security_group=['testgroup'])
        try:
            self.assertEqual(len(db.security_group_get_by_instance(
                             self.context, ref[0]['uuid'])), 1)
            group = db.security_group_get(self.context, group['id'])
            self.assert_(len(group['instances']) == 1)
        finally:
            db.security_group_destroy(self.context, group['id'])
            db.instance_destroy(self.context, ref[0]['uuid'])

    def test_create_instance_with_invalid_security_group_raises(self):
        instance_type = flavors.get_default_flavor()

        pre_build_len = len(db.instance_get_all(self.context))
        self.assertRaises(exception.SecurityGroupNotFoundForProject,
                          self.compute_api.create,
                          self.context,
                          instance_type=instance_type,
                          image_href=None,
                          security_group=['this_is_a_fake_sec_group'])
        self.assertEqual(pre_build_len,
                         len(db.instance_get_all(self.context)))

    def test_create_with_large_user_data(self):
        # Test an instance type with too much user data.

        inst_type = flavors.get_default_flavor()

        self.fake_image['min_ram'] = 2
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceUserDataTooLarge,
            self.compute_api.create, self.context, inst_type,
            self.fake_image['id'], user_data=('1' * 65536))

    def test_create_with_malformed_user_data(self):
        # Test an instance type with malformed user data.

        inst_type = flavors.get_default_flavor()

        self.fake_image['min_ram'] = 2
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceUserDataMalformed,
            self.compute_api.create, self.context, inst_type,
            self.fake_image['id'], user_data='banana')

    def test_create_with_base64_user_data(self):
        # Test an instance type with ok much user data.

        inst_type = flavors.get_default_flavor()

        self.fake_image['min_ram'] = 2
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        # NOTE(mikal): a string of length 48510 encodes to 65532 characters of
        # base64
        (refs, resv_id) = self.compute_api.create(
            self.context, inst_type, self.fake_image['id'],
            user_data=base64.encodestring('1' * 48510))
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_populate_instance_for_create(self):
        base_options = {'image_ref': self.fake_image['id'],
                        'system_metadata': utils.dict_to_metadata(
                                                            {'fake': 'value'})}
        instance = instance_obj.Instance()
        instance.update(base_options)
        inst_type = flavors.get_flavor_by_name("m1.tiny")
        instance = self.compute_api._populate_instance_for_create(
                                                    instance,
                                                    self.fake_image,
                                                    1,
                                                    security_groups=None,
                                                    instance_type=inst_type)
        self.assertEquals(str(base_options['image_ref']),
                          instance['system_metadata']['image_base_image_ref'])
        self.assertEquals(vm_states.BUILDING, instance['vm_state'])
        self.assertEquals(task_states.SCHEDULING, instance['task_state'])
        self.assertEquals(1, instance['launch_index'])
        self.assertIsNotNone(instance.get('uuid'))
        self.assertEqual([], instance.security_groups.objects)

    def test_default_hostname_generator(self):
        fake_uuids = [str(uuid.uuid4()) for x in xrange(4)]

        orig_populate = self.compute_api._populate_instance_for_create

        def _fake_populate(base_options, *args, **kwargs):
            base_options['uuid'] = fake_uuids.pop(0)
            return orig_populate(base_options, *args, **kwargs)

        self.stubs.Set(self.compute_api,
                '_populate_instance_for_create',
                _fake_populate)

        cases = [(None, 'server-%s' % fake_uuids[0]),
                 ('Hello, Server!', 'hello-server'),
                 ('<}\x1fh\x10e\x08l\x02l\x05o\x12!{>', 'hello'),
                 ('hello_server', 'hello-server')]
        for display_name, hostname in cases:
            (ref, resv_id) = self.compute_api.create(self.context,
                flavors.get_default_flavor(), image_href='some-fake-image',
                display_name=display_name)
            try:
                self.assertEqual(ref[0]['hostname'], hostname)
            finally:
                db.instance_destroy(self.context, ref[0]['uuid'])

    def test_destroy_instance_disassociates_security_groups(self):
        # Make sure destroying disassociates security groups.
        group = self._create_group()

        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=flavors.get_default_flavor(),
                image_href='some-fake-image',
                security_group=['testgroup'])
        try:
            db.instance_destroy(self.context, ref[0]['uuid'])
            group = db.security_group_get(self.context, group['id'])
            self.assert_(len(group['instances']) == 0)
        finally:
            db.security_group_destroy(self.context, group['id'])

    def test_destroy_security_group_disassociates_instances(self):
        # Make sure destroying security groups disassociates instances.
        group = self._create_group()

        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=flavors.get_default_flavor(),
                image_href='some-fake-image',
                security_group=['testgroup'])

        try:
            db.security_group_destroy(self.context, group['id'])
            admin_deleted_context = context.get_admin_context(
                    read_deleted="only")
            group = db.security_group_get(admin_deleted_context, group['id'])
            self.assert_(len(group['instances']) == 0)
        finally:
            db.instance_destroy(self.context, ref[0]['uuid'])

    def test_restore(self):
        # Ensure instance can be restored from a soft delete.
        instance, instance_uuid = self._run_instance(params={
                'host': CONF.host,
                'cell_name': 'foo'})

        instance = instance_obj.Instance.get_by_uuid(
            self.context, instance_uuid,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)
        self.compute_api.soft_delete(self.context, instance)

        instance.refresh()
        self.assertEqual(instance.task_state, task_states.SOFT_DELETING)

        # set the state that the instance gets when soft_delete finishes
        instance.vm_state = vm_states.SOFT_DELETED
        instance.task_state = None
        instance.save()

        # Ensure quotas are committed
        self.mox.StubOutWithMock(nova.quota.QUOTAS, 'commit')
        nova.quota.QUOTAS.commit(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.compute_api.restore(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.RESTORING)

        db.instance_destroy(self.context, instance['uuid'])

    def _test_rebuild(self, vm_state):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)
        # Set some image metadata that should get wiped out and reset
        # as well as some other metadata that should be preserved.
        db.instance_system_metadata_update(self.context, instance_uuid,
                {'image_kernel_id': 'old-data',
                 'image_ramdisk_id': 'old_data',
                 'image_something_else': 'old-data',
                 'image_should_remove': 'bye-bye',
                 'preserved': 'preserve this!'},
                True)

        # Make sure Compute API updates the image_ref before casting to
        # compute manager.
        orig_update = self.compute_api.update
        info = {'image_ref': None}

        def update_wrapper(*args, **kwargs):
            if 'image_ref' in kwargs:
                info['image_ref'] = kwargs['image_ref']
            return orig_update(*args, **kwargs)

        self.stubs.Set(self.compute_api, 'update', update_wrapper)

        image_ref = instance["image_ref"] + '-new_image_ref'
        password = "new_password"

        db.instance_update(self.context, instance['uuid'],
                           {"vm_state": vm_state})

        self.compute_api.rebuild(self.context, instance, image_ref, password)
        self.assertEqual(info['image_ref'], image_ref)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.REBUILDING)
        sys_metadata = db.instance_system_metadata_get(self.context,
                instance_uuid)
        self.assertEqual(sys_metadata,
                {'image_kernel_id': 'fake_kernel_id',
                'image_min_disk': '1',
                'image_ramdisk_id': 'fake_ramdisk_id',
                'image_something_else': 'meow',
                'preserved': 'preserve this!'})
        db.instance_destroy(self.context, instance['uuid'])

    def test_rebuild(self):
        self._test_rebuild(vm_state=vm_states.ACTIVE)

    def test_rebuild_in_error_state(self):
        self._test_rebuild(vm_state=vm_states.ERROR)

    def test_rebuild_in_error_not_launched(self):
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': ''}))
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)
        self.compute.run_instance(self.context, instance=instance)

        db.instance_update(self.context, instance['uuid'],
                           {"vm_state": vm_states.ERROR,
                            "launched_at": None})

        instance = db.instance_get_by_uuid(self.context, instance['uuid'])

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.rebuild,
                          self.context,
                          instance,
                          instance['image_ref'],
                          "new password")

    def test_rebuild_no_image(self):
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': ''}))
        instance_uuid = instance['uuid']
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)
        self.compute.run_instance(self.context, instance=instance)
        self.compute_api.rebuild(self.context, instance, '', 'new_password')

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.REBUILDING)

    def test_rebuild_with_deleted_image(self):
        # If we're given a deleted image by glance, we should not be able to
        # rebuild from it
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': '1'}))

        self.fake_image['name'] = 'fake_name'
        self.fake_image['status'] = 'DELETED'
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        expected_message = (
            exception.ImageNotActive.msg_fmt % {'image_id':
            self.fake_image['id']})
        with testtools.ExpectedException(exception.ImageNotActive,
                                         expected_message):
            self.compute_api.rebuild(self.context, instance,
                                     self.fake_image['id'], 'new_password')

    def test_rebuild_with_too_little_ram(self):
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': '1'}))

        def fake_extract_flavor(_inst):
            return dict(memory_mb=64, root_gb=1)

        self.stubs.Set(flavors, 'extract_flavor',
                       fake_extract_flavor)

        self.fake_image['min_ram'] = 128
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceTypeMemoryTooSmall,
            self.compute_api.rebuild, self.context,
            instance, self.fake_image['id'], 'new_password')

        # Reduce image memory requirements and make sure it works
        self.fake_image['min_ram'] = 64

        self.compute_api.rebuild(self.context,
                instance, self.fake_image['id'], 'new_password')
        db.instance_destroy(self.context, instance['uuid'])

    def test_rebuild_with_too_little_disk(self):
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': '1'}))

        def fake_extract_flavor(_inst):
            return dict(memory_mb=64, root_gb=1)

        self.stubs.Set(flavors, 'extract_flavor',
                       fake_extract_flavor)

        self.fake_image['min_disk'] = 2
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
            self.compute_api.rebuild, self.context,
            instance, self.fake_image['id'], 'new_password')

        # Reduce image disk requirements and make sure it works
        self.fake_image['min_disk'] = 1

        self.compute_api.rebuild(self.context,
                instance, self.fake_image['id'], 'new_password')
        db.instance_destroy(self.context, instance['uuid'])

    def test_rebuild_with_just_enough_ram_and_disk(self):
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': '1'}))

        def fake_extract_flavor(_inst):
            return dict(memory_mb=64, root_gb=1)

        self.stubs.Set(flavors, 'extract_flavor',
                       fake_extract_flavor)

        self.fake_image['min_ram'] = 64
        self.fake_image['min_disk'] = 1
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.compute_api.rebuild(self.context,
                instance, self.fake_image['id'], 'new_password')
        db.instance_destroy(self.context, instance['uuid'])

    def test_rebuild_with_no_ram_and_disk_reqs(self):
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': '1'}))

        def fake_extract_flavor(_inst):
            return dict(memory_mb=64, root_gb=1)

        self.stubs.Set(flavors, 'extract_flavor',
                       fake_extract_flavor)
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.compute_api.rebuild(self.context,
                instance, self.fake_image['id'], 'new_password')
        db.instance_destroy(self.context, instance['uuid'])

    def test_rebuild_with_too_large_image(self):
        instance = jsonutils.to_primitive(
            self._create_fake_instance(params={'image_ref': '1'}))

        def fake_extract_flavor(_inst):
            return dict(memory_mb=64, root_gb=1)

        self.stubs.Set(flavors, 'extract_flavor',
                       fake_extract_flavor)

        self.fake_image['size'] = '1073741825'
        self.stubs.Set(fake_image._FakeImageService, 'show', self.fake_show)

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
            self.compute_api.rebuild, self.context,
            instance, self.fake_image['id'], 'new_password')

        # Reduce image to 1 GB limit and ensure it works
        self.fake_image['size'] = '1073741824'
        self.compute_api.rebuild(self.context,
                instance, self.fake_image['id'], 'new_password')
        db.instance_destroy(self.context, instance['uuid'])

    def test_hostname_create(self):
        # Ensure instance hostname is set during creation.
        inst_type = flavors.get_flavor_by_name('m1.tiny')
        (instances, _) = self.compute_api.create(self.context,
                                                 inst_type,
                                                 image_href='some-fake-image',
                                                 display_name='test host')

        self.assertEqual('test-host', instances[0]['hostname'])

    def test_set_admin_password(self):
        # Ensure instance can have its admin password set.
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], None)

        def fake_rpc_method(context, topic, msg, do_cast=True):
            self.assertFalse(do_cast)

        self.stubs.Set(rpc, 'call', fake_rpc_method)

        self.compute_api.set_admin_password(self.context, inst_ref)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'],
                         task_states.UPDATING_PASSWORD)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_rescue_unrescue(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.ACTIVE)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.rescue(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.ACTIVE)
        self.assertEqual(instance['task_state'], task_states.RESCUING)

        params = {'vm_state': vm_states.RESCUED, 'task_state': None}
        db.instance_update(self.context, instance_uuid, params)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.compute_api.unrescue(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.RESCUED)
        self.assertEqual(instance['task_state'], task_states.UNRESCUING)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_rescue_volume_backed(self):
        # Instance started without an image
        volume_backed_inst_1 = jsonutils.to_primitive(
            self._create_fake_instance({'image_ref': ''}))

        # Instance started with a placeholder image (for metadata)
        volume_backed_inst_2 = jsonutils.to_primitive(
            self._create_fake_instance(
                {'image_ref': 'my_placeholder_img',
                 'root_device_name': '/dev/vda'})
            )

        def fake_get_instance_bdms(*args, **kwargs):
            return [{'device_name': '/dev/vda',
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'volume_id': 'bf0b6b00-a20c-11e2-9e96-0800200c9a66'}]

        self.stubs.Set(self.compute_api, 'get_instance_bdms',
                       fake_get_instance_bdms)

        def fake_volume_get(self, context, volume_id):
            return {'id': volume_id, 'status': 'in-use'}

        self.stubs.Set(cinder.API, 'get', fake_volume_get)

        self.compute.run_instance(self.context,
                                  instance=volume_backed_inst_1)
        self.compute.run_instance(self.context,
                                  instance=volume_backed_inst_2)

        self.assertRaises(exception.InstanceNotRescuable,
                          self.compute_api.rescue, self.context,
                          volume_backed_inst_1)
        self.assertRaises(exception.InstanceNotRescuable,
                          self.compute_api.rescue, self.context,
                          volume_backed_inst_2)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(volume_backed_inst_1))
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(volume_backed_inst_2))

    def test_get(self):
        # Test get instance.
        exp_instance = self._create_fake_instance()
        # NOTE(danms): Transform the db object in a similar way as
        # the API method will do.
        expected = obj_base.obj_to_primitive(
            instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), exp_instance,
                instance_obj.INSTANCE_DEFAULT_FIELDS + ['fault']))

        def fake_db_get(_context, _instance_uuid, columns_to_join=None):
            return exp_instance

        self.stubs.Set(db, 'instance_get_by_uuid', fake_db_get)

        instance = self.compute_api.get(self.context, exp_instance['uuid'])
        self.assertEquals(unify_instance(expected),
                          unify_instance(instance))

    def test_get_with_admin_context(self):
        # Test get instance.
        c = context.get_admin_context()
        exp_instance = self._create_fake_instance()
        # NOTE(danms): Transform the db object in a similar way as
        # the API method will do.
        expected = obj_base.obj_to_primitive(
            instance_obj.Instance._from_db_object(
                c, instance_obj.Instance(), exp_instance,
                instance_obj.INSTANCE_DEFAULT_FIELDS + ['fault']))

        def fake_db_get(context, instance_uuid, columns_to_join=None):
            return exp_instance

        self.stubs.Set(db, 'instance_get_by_uuid', fake_db_get)

        instance = self.compute_api.get(c, exp_instance['uuid'])
        self.assertEquals(unify_instance(expected),
                          unify_instance(instance))

    def test_get_with_integer_id(self):
        # Test get instance with an integer id.
        exp_instance = self._create_fake_instance()
        # NOTE(danms): Transform the db object in a similar way as
        # the API method will do.
        expected = obj_base.obj_to_primitive(
            instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), exp_instance,
                instance_obj.INSTANCE_DEFAULT_FIELDS + ['fault']))

        def fake_db_get(_context, _instance_id, columns_to_join=None):
            return exp_instance

        self.stubs.Set(db, 'instance_get', fake_db_get)

        instance = self.compute_api.get(self.context, exp_instance['id'])
        self.assertEquals(unify_instance(expected),
                          unify_instance(instance))

    def test_get_all_by_name_regexp(self):
        # Test searching instances by name (display_name).
        c = context.get_admin_context()
        instance1 = self._create_fake_instance({'display_name': 'woot'})
        instance2 = self._create_fake_instance({
                'display_name': 'woo'})
        instance3 = self._create_fake_instance({
                'display_name': 'not-woot'})

        instances = self.compute_api.get_all(c,
                search_opts={'name': '^woo.*'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance1['uuid'] in instance_uuids)
        self.assertTrue(instance2['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': '^woot.*'})
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertEqual(len(instances), 1)
        self.assertTrue(instance1['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': '.*oot.*'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance1['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': '^n.*'})
        self.assertEqual(len(instances), 1)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance3['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': 'noth.*'})
        self.assertEqual(len(instances), 0)

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

    def test_get_all_by_multiple_options_at_once(self):
        # Test searching by multiple options at once.
        c = context.get_admin_context()
        network_manager = fake_network.FakeNetworkManager()
        self.stubs.Set(self.compute_api.network_api,
                       'get_instance_uuids_by_ip_filter',
                       network_manager.get_instance_uuids_by_ip_filter)

        instance1 = self._create_fake_instance({
                'display_name': 'woot',
                'id': 1,
                'uuid': '00000000-0000-0000-0000-000000000010'})
        instance2 = self._create_fake_instance({
                'display_name': 'woo',
                'id': 20,
                'uuid': '00000000-0000-0000-0000-000000000020'})
        instance3 = self._create_fake_instance({
                'display_name': 'not-woot',
                'id': 30,
                'uuid': '00000000-0000-0000-0000-000000000030'})

        # ip ends up matching 2nd octet here.. so all 3 match ip
        # but 'name' only matches one
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.1', 'name': 'not.*'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance3['uuid'])

        # ip ends up matching any ip with a '1' in the last octet..
        # so instance 1 and 3.. but name should only match #1
        # but 'name' only matches one
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.1$', 'name': '^woo.*'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance1['uuid'])

        # same as above but no match on name (name matches instance1
        # but the ip query doesn't
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.2$', 'name': '^woot.*'})
        self.assertEqual(len(instances), 0)

        # ip matches all 3... ipv6 matches #2+#3...name matches #3
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.1',
                             'name': 'not.*',
                             'ip6': '^.*12.*34.*'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance3['uuid'])

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

    def test_get_all_by_image(self):
        # Test searching instances by image.

        c = context.get_admin_context()
        instance1 = self._create_fake_instance({'image_ref': '1234'})
        instance2 = self._create_fake_instance({'image_ref': '4567'})
        instance3 = self._create_fake_instance({'image_ref': '4567'})

        instances = self.compute_api.get_all(c, search_opts={'image': '123'})
        self.assertEqual(len(instances), 0)

        instances = self.compute_api.get_all(c, search_opts={'image': '1234'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance1['uuid'])

        instances = self.compute_api.get_all(c, search_opts={'image': '4567'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance2['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        # Test passing a list as search arg
        instances = self.compute_api.get_all(c,
                                    search_opts={'image': ['1234', '4567']})
        self.assertEqual(len(instances), 3)

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

    def test_get_all_by_flavor(self):
        # Test searching instances by image.

        c = context.get_admin_context()
        instance1 = self._create_fake_instance({'instance_type_id': 1})
        instance2 = self._create_fake_instance({'instance_type_id': 2})
        instance3 = self._create_fake_instance({'instance_type_id': 2})

        # NOTE(comstud): Migrations set up the instance_types table
        # for us.  Therefore, we assume the following is true for
        # these tests:
        # instance_type_id 1 == flavor 3
        # instance_type_id 2 == flavor 1
        # instance_type_id 3 == flavor 4
        # instance_type_id 4 == flavor 5
        # instance_type_id 5 == flavor 2

        instances = self.compute_api.get_all(c,
                search_opts={'flavor': 5})
        self.assertEqual(len(instances), 0)

        # ensure unknown filter maps to an exception
        self.assertRaises(exception.FlavorNotFound,
                          self.compute_api.get_all, c,
                          search_opts={'flavor': 99})

        instances = self.compute_api.get_all(c, search_opts={'flavor': 3})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['id'], instance1['id'])

        instances = self.compute_api.get_all(c, search_opts={'flavor': 1})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance2['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

    def test_get_all_by_state(self):
        # Test searching instances by state.

        c = context.get_admin_context()
        instance1 = self._create_fake_instance({
            'power_state': power_state.SHUTDOWN,
        })
        instance2 = self._create_fake_instance({
            'power_state': power_state.RUNNING,
        })
        instance3 = self._create_fake_instance({
            'power_state': power_state.RUNNING,
        })

        instances = self.compute_api.get_all(c,
                search_opts={'power_state': power_state.SUSPENDED})
        self.assertEqual(len(instances), 0)

        instances = self.compute_api.get_all(c,
                search_opts={'power_state': power_state.SHUTDOWN})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance1['uuid'])

        instances = self.compute_api.get_all(c,
                search_opts={'power_state': power_state.RUNNING})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance2['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        # Test passing a list as search arg
        instances = self.compute_api.get_all(c,
                search_opts={'power_state': [power_state.SHUTDOWN,
                        power_state.RUNNING]})
        self.assertEqual(len(instances), 3)

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

    def test_get_all_by_metadata(self):
        # Test searching instances by metadata.

        c = context.get_admin_context()
        instance0 = self._create_fake_instance()
        instance1 = self._create_fake_instance({
                'metadata': {'key1': 'value1'}})
        instance2 = self._create_fake_instance({
                'metadata': {'key2': 'value2'}})
        instance3 = self._create_fake_instance({
                'metadata': {'key3': 'value3'}})
        instance4 = self._create_fake_instance({
                'metadata': {'key3': 'value3',
                             'key4': 'value4'}})

        # get all instances
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {}})
        self.assertEqual(len(instances), 5)

        # wrong key/value combination
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key1': 'value3'}})
        self.assertEqual(len(instances), 0)

        # non-existing keys
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key5': 'value1'}})
        self.assertEqual(len(instances), 0)

        # find existing instance
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key2': 'value2'}})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance2['uuid'])

        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key3': 'value3'}})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance3['uuid'] in instance_uuids)
        self.assertTrue(instance4['uuid'] in instance_uuids)

        # multiple criteria as a dict
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key3': 'value3',
                                          'key4': 'value4'}})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance4['uuid'])

        # multiple criteria as a list
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': [{'key4': 'value4'},
                                          {'key3': 'value3'}]})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance4['uuid'])

        db.instance_destroy(c, instance0['uuid'])
        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])
        db.instance_destroy(c, instance4['uuid'])

    def test_all_instance_metadata(self):
        instance1 = self._create_fake_instance({'metadata': {'key1': 'value1'},
                                               'user_id': 'user1',
                                               'project_id': 'project1'})

        instance2 = self._create_fake_instance({'metadata': {'key2': 'value2'},
                                               'user_id': 'user2',
                                               'project_id': 'project2'})

        _context = self.context
        _context.user_id = 'user1'
        _context.project_id = 'project1'
        metadata = self.compute_api.get_all_instance_metadata(_context,
                                                              search_filts=[])
        self.assertTrue(len(metadata) == 1)
        self.assertEqual(metadata[0]['key'], 'key1')

        _context.user_id = 'user2'
        _context.project_id = 'project2'
        metadata = self.compute_api.get_all_instance_metadata(_context,
                                                              search_filts=[])
        self.assertTrue(len(metadata) == 1)
        self.assertEqual(metadata[0]['key'], 'key2')

        _context = context.get_admin_context()
        metadata = self.compute_api.get_all_instance_metadata(_context,
                                                              search_filts=[])
        self.assertTrue(len(metadata) == 2)

    def test_instance_metadata(self):
        meta_changes = [None]
        self.flags(notify_on_state_change='vm_state')

        def fake_change_instance_metadata(inst, ctxt, diff, instance=None,
                                          instance_uuid=None):
            meta_changes[0] = diff
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'change_instance_metadata',
                       fake_change_instance_metadata)

        _context = context.get_admin_context()
        instance = self._create_fake_instance({'metadata': {'key1': 'value1'}})
        instance = dict(instance.iteritems())

        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key1': 'value1'})

        self.compute_api.update_instance_metadata(_context, instance,
                                                  {'key2': 'value2'})
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key1': 'value1', 'key2': 'value2'})
        self.assertEqual(meta_changes, [{'key2': ['+', 'value2']}])

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        payload = msg.payload
        self.assertTrue('metadata' in payload)
        self.assertEquals(payload['metadata'], metadata)

        new_metadata = {'key2': 'bah', 'key3': 'value3'}
        self.compute_api.update_instance_metadata(_context, instance,
                                                  new_metadata, delete=True)
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, new_metadata)
        self.assertEqual(meta_changes, [{
                    'key1': ['-'],
                    'key2': ['+', 'bah'],
                    'key3': ['+', 'value3'],
                    }])

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[1]
        payload = msg.payload
        self.assertTrue('metadata' in payload)
        self.assertEquals(payload['metadata'], metadata)

        self.compute_api.delete_instance_metadata(_context, instance, 'key2')
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key3': 'value3'})
        self.assertEqual(meta_changes, [{'key2': ['-']}])

        self.assertEquals(len(fake_notifier.NOTIFICATIONS), 3)
        msg = fake_notifier.NOTIFICATIONS[2]
        payload = msg.payload
        self.assertTrue('metadata' in payload)
        self.assertEquals(payload['metadata'], {})

        db.instance_destroy(_context, instance['uuid'])

    def test_disallow_metadata_changes_during_building(self):
        def fake_change_instance_metadata(inst, ctxt, diff, instance=None,
                                          instance_uuid=None):
            pass
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'change_instance_metadata',
                       fake_change_instance_metadata)

        instance = self._create_fake_instance({'vm_state': vm_states.BUILDING})
        instance = dict(instance)

        self.assertRaises(exception.InstanceInvalidState,
                self.compute_api.delete_instance_metadata, self.context,
                instance, "key")

        self.assertRaises(exception.InstanceInvalidState,
                self.compute_api.update_instance_metadata, self.context,
                instance, "key")

    def test_get_instance_faults(self):
        # Get an instances latest fault.
        instance = self._create_fake_instance()

        fault_fixture = {
                'code': 404,
                'instance_uuid': instance['uuid'],
                'message': "HTTPNotFound",
                'details': "Stock details for test",
                'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
            }

        def return_fault(_ctxt, instance_uuids):
            return dict.fromkeys(instance_uuids, [fault_fixture])

        self.stubs.Set(nova.db,
                       'instance_fault_get_by_instance_uuids',
                       return_fault)

        _context = context.get_admin_context()
        output = self.compute_api.get_instance_faults(_context, [instance])
        expected = {instance['uuid']: [fault_fixture]}
        self.assertEqual(output, expected)

        db.instance_destroy(_context, instance['uuid'])

    @staticmethod
    def _parse_db_block_device_mapping(bdm_ref):
        attr_list = ('delete_on_termination', 'device_name', 'no_device',
                     'virtual_name', 'volume_id', 'volume_size', 'snapshot_id')
        bdm = {}
        for attr in attr_list:
            val = bdm_ref.get(attr, None)
            if val:
                bdm[attr] = val

        return bdm

    def test_update_block_device_mapping(self):
        swap_size = ephemeral_size = 1
        instance_type = {'swap': swap_size, 'ephemeral_gb': ephemeral_size}
        instance = self._create_fake_instance()
        mappings = [
                {'virtual': 'ami', 'device': 'sda1'},
                {'virtual': 'root', 'device': '/dev/sda1'},

                {'virtual': 'swap', 'device': 'sdb4'},
                {'virtual': 'swap', 'device': 'sdb3'},
                {'virtual': 'swap', 'device': 'sdb2'},
                {'virtual': 'swap', 'device': 'sdb1'},

                {'virtual': 'ephemeral0', 'device': 'sdc1'},
                {'virtual': 'ephemeral1', 'device': 'sdc2'},
                {'virtual': 'ephemeral2', 'device': 'sdc3'}]
        block_device_mapping = [
                # root
                {'device_name': '/dev/sda1',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '00000000-aaaa-bbbb-cccc-000000000000',
                 'delete_on_termination': False},

                # overwrite swap
                {'device_name': '/dev/sdb2',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '11111111-aaaa-bbbb-cccc-111111111111',
                 'delete_on_termination': False},
                {'device_name': '/dev/sdb3',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '22222222-aaaa-bbbb-cccc-222222222222'},
                {'device_name': '/dev/sdb4',
                 'no_device': True},

                # overwrite ephemeral
                {'device_name': '/dev/sdc1',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '33333333-aaaa-bbbb-cccc-333333333333',
                 'delete_on_termination': False},
                {'device_name': '/dev/sdc2',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '33333333-aaaa-bbbb-cccc-444444444444',
                 'delete_on_termination': False},
                {'device_name': '/dev/sdc3',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '44444444-aaaa-bbbb-cccc-555555555555'},
                {'device_name': '/dev/sdc4',
                 'no_device': True},

                # volume
                {'device_name': '/dev/sdd1',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '55555555-aaaa-bbbb-cccc-666666666666',
                 'delete_on_termination': False},
                {'device_name': '/dev/sdd2',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '66666666-aaaa-bbbb-cccc-777777777777'},
                {'device_name': '/dev/sdd3',
                 'source_type': 'snapshot', 'destination_type': 'volume',
                 'snapshot_id': '77777777-aaaa-bbbb-cccc-888888888888'},
                {'device_name': '/dev/sdd4',
                 'no_device': True}]

        image_mapping = self.compute_api._prepare_image_mapping(
            instance_type, instance['uuid'], mappings)
        self.compute_api._update_block_device_mapping(
            self.context, instance_type, instance['uuid'], image_mapping)

        bdms = [block_device.BlockDeviceDict(bdm) for bdm in
                db.block_device_mapping_get_all_by_instance(
                    self.context, instance['uuid'])]
        expected_result = [
            {'source_type': 'blank', 'destination_type': 'local',
             'guest_format': 'swap', 'device_name': '/dev/sdb1',
             'volume_size': swap_size, 'delete_on_termination': True},
            {'source_type': 'blank', 'destination_type': 'local',
             'guest_format': CONF.default_ephemeral_format,
             'device_name': '/dev/sdc3', 'delete_on_termination': True},
            {'source_type': 'blank', 'destination_type': 'local',
             'guest_format': CONF.default_ephemeral_format,
             'device_name': '/dev/sdc1', 'delete_on_termination': True},
             {'source_type': 'blank', 'destination_type': 'local',
             'guest_format': CONF.default_ephemeral_format,
             'device_name': '/dev/sdc2', 'delete_on_termination': True},
            ]
        bdms.sort(key=operator.itemgetter('device_name'))
        expected_result.sort(key=operator.itemgetter('device_name'))
        self.assertEqual(len(bdms), len(expected_result))
        for expected, got in zip(expected_result, bdms):
            self.assertThat(expected, matchers.IsSubDictOf(got))

        self.compute_api._update_block_device_mapping(
            self.context, flavors.get_default_flavor(),
            instance['uuid'], block_device_mapping)
        bdms = [block_device.BlockDeviceDict(bdm) for bdm in
                db.block_device_mapping_get_all_by_instance(
                        self.context, instance['uuid'])]
        expected_result = [
            {'snapshot_id': '00000000-aaaa-bbbb-cccc-000000000000',
               'device_name': '/dev/sda1'},

            {'source_type': 'blank', 'destination_type': 'local',
             'guest_format': 'swap', 'device_name': '/dev/sdb1',
             'volume_size': swap_size, 'delete_on_termination': True},
            {'device_name': '/dev/sdb2',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '11111111-aaaa-bbbb-cccc-111111111111',
             'delete_on_termination': False},
            {'device_name': '/dev/sdb3',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '22222222-aaaa-bbbb-cccc-222222222222'},
            {'device_name': '/dev/sdb4', 'no_device': True},

            {'device_name': '/dev/sdc1',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '33333333-aaaa-bbbb-cccc-333333333333',
             'delete_on_termination': False},
            {'device_name': '/dev/sdc2',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '33333333-aaaa-bbbb-cccc-444444444444',
             'delete_on_termination': False},
            {'device_name': '/dev/sdc3',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '44444444-aaaa-bbbb-cccc-555555555555'},
            {'no_device': True, 'device_name': '/dev/sdc4'},

            {'device_name': '/dev/sdd1',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '55555555-aaaa-bbbb-cccc-666666666666',
             'delete_on_termination': False},
            {'device_name': '/dev/sdd2',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '66666666-aaaa-bbbb-cccc-777777777777'},
            {'device_name': '/dev/sdd3',
             'source_type': 'snapshot', 'destination_type': 'volume',
             'snapshot_id': '77777777-aaaa-bbbb-cccc-888888888888'},
            {'no_device': True, 'device_name': '/dev/sdd4'}]
        bdms.sort(key=operator.itemgetter('device_name'))
        expected_result.sort(key=operator.itemgetter('device_name'))
        self.assertEqual(len(bdms), len(expected_result))
        for expected, got in zip(expected_result, bdms):
            self.assertThat(expected, matchers.IsSubDictOf(got))

        for bdm in db.block_device_mapping_get_all_by_instance(
                self.context, instance['uuid']):
            db.block_device_mapping_destroy(self.context, bdm['id'])
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.compute.terminate_instance(self.context,
                                        jsonutils.to_primitive(instance))

    def test_check_and_transform_bdm(self):
        base_options = {'root_device_name': 'vdb',
                        'image_ref': FAKE_IMAGE_REF}
        fake_legacy_bdms = [
            {'device_name': '/dev/vda',
             'volume_id': '33333333-aaaa-bbbb-cccc-333333333333',
             'delete_on_termination': False}]

        image_meta = {'properties': {'block_device_mapping': [
            {'device_name': '/dev/vda',
             'snapshot_id': '33333333-aaaa-bbbb-cccc-333333333333'}]}}

        # We get an image BDM
        transformed_bdm = self.compute_api._check_and_transform_bdm(
            base_options, {}, 1, 1, fake_legacy_bdms, True)
        self.assertEqual(len(transformed_bdm), 2)

        # No image BDM created if image already defines a root BDM
        base_options['root_device_name'] = 'vda'
        transformed_bdm = self.compute_api._check_and_transform_bdm(
            base_options, image_meta, 1, 1, [], True)
        self.assertEqual(len(transformed_bdm), 1)

        # No image BDM created
        transformed_bdm = self.compute_api._check_and_transform_bdm(
            base_options, {}, 1, 1, fake_legacy_bdms, True)
        self.assertEqual(len(transformed_bdm), 1)

        # Volumes with multiple instances fails
        self.assertRaises(exception.InvalidRequest,
            self.compute_api._check_and_transform_bdm,
            base_options, {}, 1, 2, fake_legacy_bdms, True)

        checked_bdm = self.compute_api._check_and_transform_bdm(
            base_options, {}, 1, 1, transformed_bdm, True)
        self.assertEqual(checked_bdm, transformed_bdm)

    def test_volume_size(self):
        ephemeral_size = 2
        swap_size = 3
        volume_size = 5

        swap_bdm = {'source_type': 'blank', 'guest_format': 'swap'}
        ephemeral_bdm = {'source_type': 'blank', 'guest_format': None}
        volume_bdm = {'source_type': 'volume', 'volume_size': volume_size}

        inst_type = {'ephemeral_gb': ephemeral_size, 'swap': swap_size}
        self.assertEqual(
            self.compute_api._volume_size(inst_type, ephemeral_bdm),
            ephemeral_size)
        ephemeral_bdm['volume_size'] = 42
        self.assertEqual(
            self.compute_api._volume_size(inst_type, ephemeral_bdm), 42)
        self.assertEqual(
            self.compute_api._volume_size(inst_type, swap_bdm),
            swap_size)
        swap_bdm['volume_size'] = 42
        self.assertEqual(
                self.compute_api._volume_size(inst_type, swap_bdm), 42)
        self.assertEqual(
            self.compute_api._volume_size(inst_type, volume_bdm),
            volume_size)

    def test_is_volume_backed_instance(self):
        ctxt = self.context

        instance = self._create_fake_instance({'image_ref': None})
        self.assertTrue(
            self.compute_api.is_volume_backed_instance(ctxt, instance, None))

        instance = self._create_fake_instance({'root_device_name': 'vda'})
        self.assertFalse(
            self.compute_api.is_volume_backed_instance(ctxt, instance, []))
        bdms = [{'device_name': '/dev/vda',
                 'volume_id': None,
                 'snapshot_id': None}]
        self.assertFalse(
            self.compute_api.is_volume_backed_instance(ctxt, instance, bdms))

        bdms = [{'device_name': '/dev/vda',
                 'volume_id': None,
                 'snapshot_id': None},
                {'device_name': '/dev/vdb',
                 'volume_id': 'c2ec2156-d75e-11e2-985b-5254009297d6',
                 'snapshot_id': None}]
        self.assertFalse(
            self.compute_api.is_volume_backed_instance(ctxt, instance, bdms))

        bdms = [{'device_name': '/dev/vda',
                 'volume_id': 'de8836ac-d75e-11e2-8271-5254009297d6',
                 'snapshot_id': None},
                {'device_name': '/dev/vdb',
                 'volume_id': 'c2ec2156-d75e-11e2-985b-5254009297d6',
                 'snapshot_id': None}]
        self.assertTrue(
            self.compute_api.is_volume_backed_instance(ctxt, instance, bdms))

        bdms = [{'device_name': '/dev/vda',
                 'volume_id': 'de8836ac-d75e-11e2-8271-5254009297d6',
                 'snapshot_id': 'f561c730-d75e-11e2-b505-5254009297d6'},
                {'device_name': '/dev/vdb',
                 'volume_id': 'c2ec2156-d75e-11e2-985b-5254009297d6',
                 'snapshot_id': None}]
        self.assertTrue(
            self.compute_api.is_volume_backed_instance(ctxt, instance, bdms))

    def test_reservation_id_one_instance(self):
        """Verify building an instance has a reservation_id that
        matches return value from create.
        """
        (refs, resv_id) = self.compute_api.create(self.context,
                flavors.get_default_flavor(), image_href='some-fake-image')
        try:
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]['reservation_id'], resv_id)
        finally:
            db.instance_destroy(self.context, refs[0]['uuid'])

    def test_reservation_ids_two_instances(self):
        """Verify building 2 instances at once results in a
        reservation_id being returned equal to reservation id set
        in both instances.
        """
        (refs, resv_id) = self.compute_api.create(self.context,
                flavors.get_default_flavor(), image_href='some-fake-image',
                min_count=2, max_count=2)
        try:
            self.assertEqual(len(refs), 2)
            self.assertNotEqual(resv_id, None)
        finally:
            for instance in refs:
                self.assertEqual(instance['reservation_id'], resv_id)

        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_multi_instance_display_name_template(self):
        self.flags(multi_instance_display_name_template='%(name)s')
        (refs, resv_id) = self.compute_api.create(self.context,
                flavors.get_default_flavor(), image_href='some-fake-image',
                min_count=2, max_count=2, display_name='x')
        self.assertEqual(refs[0]['display_name'], 'x')
        self.assertEqual(refs[0]['hostname'], 'x')
        self.assertEqual(refs[1]['display_name'], 'x')
        self.assertEqual(refs[1]['hostname'], 'x')

        self.flags(multi_instance_display_name_template='%(name)s-%(count)s')
        (refs, resv_id) = self.compute_api.create(self.context,
                flavors.get_default_flavor(), image_href='some-fake-image',
                min_count=2, max_count=2, display_name='x')
        self.assertEqual(refs[0]['display_name'], 'x-1')
        self.assertEqual(refs[0]['hostname'], 'x-1')
        self.assertEqual(refs[1]['display_name'], 'x-2')
        self.assertEqual(refs[1]['hostname'], 'x-2')

        self.flags(multi_instance_display_name_template='%(name)s-%(uuid)s')
        (refs, resv_id) = self.compute_api.create(self.context,
                flavors.get_default_flavor(), image_href='some-fake-image',
                min_count=2, max_count=2, display_name='x')
        self.assertEqual(refs[0]['display_name'], 'x-%s' % refs[0]['uuid'])
        self.assertEqual(refs[0]['hostname'], 'x-%s' % refs[0]['uuid'])
        self.assertEqual(refs[1]['display_name'], 'x-%s' % refs[1]['uuid'])
        self.assertEqual(refs[1]['hostname'], 'x-%s' % refs[1]['uuid'])

    def test_instance_architecture(self):
        # Test the instance architecture.
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['architecture'], 'x86_64')
        db.instance_destroy(self.context, i_ref['uuid'])

    def test_instance_unknown_architecture(self):
        # Test if the architecture is unknown.
        instance = jsonutils.to_primitive(self._create_fake_instance(
                        params={'architecture': ''}))
        try:
            self.compute.run_instance(self.context, instance=instance)
            instance = db.instance_get_by_uuid(self.context,
                    instance['uuid'])
            self.assertNotEqual(instance['architecture'], 'Unknown')
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_instance_name_template(self):
        # Test the instance_name template.
        self.flags(instance_name_template='instance-%d')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], 'instance-%d' % i_ref['id'])
        db.instance_destroy(self.context, i_ref['uuid'])

        self.flags(instance_name_template='instance-%(uuid)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], 'instance-%s' % i_ref['uuid'])
        db.instance_destroy(self.context, i_ref['uuid'])

        self.flags(instance_name_template='%(id)d-%(uuid)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], '%d-%s' %
                (i_ref['id'], i_ref['uuid']))
        db.instance_destroy(self.context, i_ref['uuid'])

        # not allowed.. default is uuid
        self.flags(instance_name_template='%(name)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], i_ref['uuid'])
        db.instance_destroy(self.context, i_ref['uuid'])

    def test_add_remove_fixed_ip(self):
        instance = self._create_fake_instance(params={'host': CONF.host})
        self.stubs.Set(self.compute_api.network_api, 'deallocate_for_instance',
                       lambda *a, **kw: None)
        self.compute_api.add_fixed_ip(self.context, instance, '1')
        self.compute_api.remove_fixed_ip(self.context, instance, '192.168.1.1')
        self.compute_api.delete(self.context, self._objectify(instance))

    def test_attach_volume_invalid(self):
        self.assertRaises(exception.InvalidDevicePath,
                self.compute_api.attach_volume,
                self.context,
                {'locked': False, 'vm_state': vm_states.ACTIVE,
                 'launched_at': timeutils.utcnow()},
                None,
                '/invalid')

    def test_no_attach_volume_in_rescue_state(self):
        def fake(*args, **kwargs):
            pass

        def fake_volume_get(self, context, volume_id):
            return {'id': volume_id}

        self.stubs.Set(cinder.API, 'get', fake_volume_get)
        self.stubs.Set(cinder.API, 'check_attach', fake)
        self.stubs.Set(cinder.API, 'reserve_volume', fake)

        self.assertRaises(exception.InstanceInvalidState,
                self.compute_api.attach_volume,
                self.context,
                {'uuid': 'fake_uuid', 'locked': False,
                'vm_state': vm_states.RESCUED},
                None,
                '/dev/vdb')

    def test_no_detach_volume_in_rescue_state(self):
        # Ensure volume can be detached from instance

        params = {'vm_state': vm_states.RESCUED}
        instance = self._create_fake_instance(params=params)

        volume = {'id': 1, 'attach_status': 'in-use',
                  'instance_uuid': instance['uuid']}

        self.assertRaises(exception.InstanceInvalidState,
                self.compute_api.detach_volume,
                self.context, instance, volume)

    def test_no_rescue_in_volume_state_attaching(self):
        # Make sure a VM cannot be rescued while volume is being attached
        instance = self._create_fake_instance()

        def fake_get_instance_bdms(*args, **kwargs):
            return [{'device_name': '/dev/vda',
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'volume_id': 'bf0b6b00-a20c-11e2-9e96-0800200c9a66'}]

        self.stubs.Set(self.compute_api, 'get_instance_bdms',
                       fake_get_instance_bdms)

        def fake_volume_get(self, context, volume_id):
            return {'id': volume_id, 'status': 'attaching'}

        self.stubs.Set(cinder.API, 'get', fake_volume_get)

        volume = {'id': 'bf0b6b00-a20c-11e2-9e96-0800200c9a66',
                  'state': 'active', 'instance_uuid': instance['uuid']}

        self.assertRaises(exception.InvalidVolume,
                self.compute_api.rescue, self.context, instance)

    def test_vnc_console(self):
        # Make sure we can a vnc console for an instance.

        fake_instance = {'uuid': 'fake_uuid',
                         'host': 'fake_compute_host'}
        fake_console_type = "novnc"
        fake_connect_info = {'token': 'fake_token',
                             'console_type': fake_console_type,
                             'host': 'fake_console_host',
                             'port': 'fake_console_port',
                             'internal_access_path': 'fake_access_path',
                             'instance_uuid': fake_instance['uuid']}
        fake_connect_info2 = copy.deepcopy(fake_connect_info)
        fake_connect_info2['access_url'] = 'fake_console_url'

        self.mox.StubOutWithMock(rpc, 'call')

        rpc_msg1 = {'method': 'get_vnc_console',
                    'namespace': None,
                    'args': {'instance': fake_instance,
                             'console_type': fake_console_type},
                   'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION}
        rpc_msg2 = {'method': 'authorize_console',
                    'namespace': None,
                    'args': fake_connect_info,
                    'version': '1.2'}

        rpc.call(self.context, 'compute.%s' % fake_instance['host'],
                rpc_msg1, None).AndReturn(fake_connect_info2)
        rpc.call(self.context, CONF.consoleauth_topic,
                rpc_msg2, None).AndReturn(None)

        self.mox.ReplayAll()

        console = self.compute_api.get_vnc_console(self.context,
                fake_instance, fake_console_type)
        self.assertEqual(console, {'url': 'fake_console_url'})

    def test_get_vnc_console_no_host(self):
        instance = self._create_fake_instance(params={'host': ''})

        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.get_vnc_console,
                          self.context, instance, 'novnc')

        db.instance_destroy(self.context, instance['uuid'])

    def test_spice_console(self):
        # Make sure we can a spice console for an instance.

        fake_instance = {'uuid': 'fake_uuid',
                         'host': 'fake_compute_host'}
        fake_console_type = "spice-html5"
        fake_connect_info = {'token': 'fake_token',
                             'console_type': fake_console_type,
                             'host': 'fake_console_host',
                             'port': 'fake_console_port',
                             'internal_access_path': 'fake_access_path',
                             'instance_uuid': fake_instance['uuid']}
        fake_connect_info2 = copy.deepcopy(fake_connect_info)
        fake_connect_info2['access_url'] = 'fake_console_url'

        self.mox.StubOutWithMock(rpc, 'call')

        rpc_msg1 = {'method': 'get_spice_console',
                    'namespace': None,
                    'args': {'instance': fake_instance,
                             'console_type': fake_console_type},
                   'version': '2.24'}
        rpc_msg2 = {'method': 'authorize_console',
                    'namespace': None,
                    'args': fake_connect_info,
                    'version': '1.2'}

        rpc.call(self.context, 'compute.%s' % fake_instance['host'],
                rpc_msg1, None).AndReturn(fake_connect_info2)
        rpc.call(self.context, CONF.consoleauth_topic,
                rpc_msg2, None).AndReturn(None)

        self.mox.ReplayAll()

        console = self.compute_api.get_spice_console(self.context,
                fake_instance, fake_console_type)
        self.assertEqual(console, {'url': 'fake_console_url'})

    def test_get_spice_console_no_host(self):
        instance = self._create_fake_instance(params={'host': ''})

        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.get_spice_console,
                          self.context, instance, 'spice')

        db.instance_destroy(self.context, instance['uuid'])

    def test_console_output(self):
        fake_instance = {'uuid': 'fake_uuid',
                         'host': 'fake_compute_host'}
        fake_tail_length = 699
        fake_console_output = 'fake console output'

        self.mox.StubOutWithMock(rpc, 'call')

        rpc_msg = {'method': 'get_console_output',
                   'namespace': None,
                   'args': {'instance': fake_instance,
                            'tail_length': fake_tail_length},
                   'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION}
        rpc.call(self.context, 'compute.%s' % fake_instance['host'],
                rpc_msg, None).AndReturn(fake_console_output)

        self.mox.ReplayAll()

        output = self.compute_api.get_console_output(self.context,
                fake_instance, tail_length=fake_tail_length)
        self.assertEqual(output, fake_console_output)

    def test_console_output_no_host(self):
        instance = self._create_fake_instance(params={'host': ''})

        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.get_console_output,
                          self.context, instance)

        db.instance_destroy(self.context, instance['uuid'])

    def test_attach_interface(self):
        new_type = flavors.get_flavor_by_flavor_id('4')
        sys_meta = flavors.save_flavor_info({}, new_type)

        instance = {
            'image_ref': 'foo',
            'system_metadata': sys_meta,
            }
        self.mox.StubOutWithMock(self.compute.network_api,
                                 'allocate_port_for_instance')
        nwinfo = [fake_network_cache_model.new_vif()]
        network_id = nwinfo[0]['network']['id']
        port_id = nwinfo[0]['id']
        req_ip = '1.2.3.4'
        self.compute.network_api.allocate_port_for_instance(
            self.context, instance, port_id, network_id, req_ip,
            conductor_api=self.compute.conductor_api).AndReturn(nwinfo)
        self.mox.ReplayAll()
        vif = self.compute.attach_interface(self.context,
                                            instance,
                                            network_id,
                                            port_id,
                                            req_ip)
        self.assertEqual(vif['id'], network_id)
        return nwinfo, port_id

    def test_detach_interface(self):
        nwinfo, port_id = self.test_attach_interface()
        self.stubs.Set(self.compute, '_get_instance_nw_info',
                       lambda *a, **k: nwinfo)
        self.stubs.Set(self.compute.network_api,
                       'deallocate_port_for_instance',
                       lambda a, b, c, conductor_api=None: [])
        self.compute.detach_interface(self.context, {}, port_id)
        self.assertEqual(self.compute.driver._interfaces, {})

    def test_attach_volume(self):
        # Ensure instance can be soft rebooted.

        called = {}

        def fake_check_attach(*args, **kwargs):
            called['fake_check_attach'] = True

        def fake_reserve_volume(*args, **kwargs):
            called['fake_reserve_volume'] = True

        def fake_volume_get(self, context, volume_id):
            called['fake_volume_get'] = True
            return {'id': volume_id}

        def fake_rpc_attach_volume(self, context, **kwargs):
            called['fake_rpc_attach_volume'] = True

        def fake_rpc_reserve_block_device_name(self, context, **kwargs):
            called['fake_rpc_reserve_block_device_name'] = True

        self.stubs.Set(cinder.API, 'get', fake_volume_get)
        self.stubs.Set(cinder.API, 'check_attach', fake_check_attach)
        self.stubs.Set(cinder.API, 'reserve_volume',
                       fake_reserve_volume)
        self.stubs.Set(compute_rpcapi.ComputeAPI,
                       'reserve_block_device_name',
                       fake_rpc_reserve_block_device_name)
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'attach_volume',
                       fake_rpc_attach_volume)

        instance = self._create_fake_instance()
        self.compute_api.attach_volume(self.context, instance, 1, '/dev/vdb')
        self.assertTrue(called.get('fake_check_attach'))
        self.assertTrue(called.get('fake_reserve_volume'))
        self.assertTrue(called.get('fake_reserve_volume'))
        self.assertTrue(called.get('fake_rpc_reserve_block_device_name'))
        self.assertTrue(called.get('fake_rpc_attach_volume'))

    def test_attach_volume_no_device(self):

        called = {}

        def fake_check_attach(*args, **kwargs):
            called['fake_check_attach'] = True

        def fake_reserve_volume(*args, **kwargs):
            called['fake_reserve_volume'] = True

        def fake_volume_get(self, context, volume_id):
            called['fake_volume_get'] = True
            return {'id': volume_id}

        def fake_rpc_attach_volume(self, context, **kwargs):
            called['fake_rpc_attach_volume'] = True

        self.stubs.Set(cinder.API, 'get', fake_volume_get)
        self.stubs.Set(cinder.API, 'check_attach', fake_check_attach)
        self.stubs.Set(cinder.API, 'reserve_volume',
                       fake_reserve_volume)
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'attach_volume',
                       fake_rpc_attach_volume)

    def test_detach_volume(self):
        # Ensure volume can be detached from instance
        called = {}
        instance = self._create_fake_instance()
        volume = {'id': 1, 'attach_status': 'in-use',
                  'instance_uuid': instance['uuid']}

        def fake_check_detach(*args, **kwargs):
            called['fake_check_detach'] = True

        def fake_begin_detaching(*args, **kwargs):
            called['fake_begin_detaching'] = True

        def fake_rpc_detach_volume(self, context, **kwargs):
            called['fake_rpc_detach_volume'] = True

        self.stubs.Set(cinder.API, 'check_detach', fake_check_detach)
        self.stubs.Set(cinder.API, 'begin_detaching', fake_begin_detaching)
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'detach_volume',
                       fake_rpc_detach_volume)

        self.compute_api.detach_volume(self.context,
                instance, volume)
        self.assertTrue(called.get('fake_check_detach'))
        self.assertTrue(called.get('fake_begin_detaching'))
        self.assertTrue(called.get('fake_rpc_detach_volume'))

    def test_detach_invalid_volume(self):
        # Ensure exception is raised while detaching an un-attached volume
        instance = {'uuid': 'uuid1',
                    'locked': False,
                    'launched_at': timeutils.utcnow(),
                    'vm_state': vm_states.ACTIVE}
        volume = {'id': 1, 'attach_status': 'detached'}

        self.assertRaises(exception.InvalidVolume,
                          self.compute_api.detach_volume, self.context,
                          instance, volume)

    def test_detach_unattached_volume(self):
        # Ensure exception is raised when volume's idea of attached
        # instance doesn't match.
        instance = {'uuid': 'uuid1',
                    'locked': False,
                    'launched_at': timeutils.utcnow(),
                    'vm_state': vm_states.ACTIVE}
        volume = {'id': 1, 'attach_status': 'in-use',
                  'instance_uuid': 'uuid2'}

        self.assertRaises(exception.VolumeUnattached,
                          self.compute_api.detach_volume, self.context,
                          instance, volume)

    def test_detach_volume_libvirt_is_down(self):
        # Ensure rollback during detach if libvirt goes down

        called = {}
        instance = self._create_fake_instance()

        def fake_get_instance_volume_bdm(*args, **kwargs):
            return {'device_name': '/dev/vdb', 'volume_id': 1,
                    'connection_info': '{"test": "test"}'}

        def fake_libvirt_driver_instance_exists(*args, **kwargs):
            called['fake_libvirt_driver_instance_exists'] = True
            return False

        def fake_libvirt_driver_detach_volume_fails(*args, **kwargs):
            called['fake_libvirt_driver_detach_volume_fails'] = True
            raise AttributeError()

        def fake_roll_detaching(*args, **kwargs):
            called['fake_roll_detaching'] = True

        self.stubs.Set(cinder.API, 'roll_detaching', fake_roll_detaching)
        self.stubs.Set(self.compute, "_get_instance_volume_bdm",
                       fake_get_instance_volume_bdm)
        self.stubs.Set(self.compute.driver, "instance_exists",
                       fake_libvirt_driver_instance_exists)
        self.stubs.Set(self.compute.driver, "detach_volume",
                       fake_libvirt_driver_detach_volume_fails)

        self.assertRaises(AttributeError, self.compute.detach_volume,
                          self.context, 1, instance)
        self.assertTrue(called.get('fake_libvirt_driver_instance_exists'))
        self.assertTrue(called.get('fake_roll_detaching'))

    def test_terminate_with_volumes(self):
        # Make sure that volumes get detached during instance termination.
        admin = context.get_admin_context()
        instance = self._create_fake_instance()

        volume_id = 'fake'
        values = {'instance_uuid': instance['uuid'],
                  'device_name': '/dev/vdc',
                  'delete_on_termination': False,
                  'volume_id': volume_id,
                  }
        db.block_device_mapping_create(admin, values)

        def fake_volume_get(self, context, volume_id):
            return {'id': volume_id}
        self.stubs.Set(cinder.API, "get", fake_volume_get)

        # Stub out and record whether it gets detached
        result = {"detached": False}

        def fake_detach(self, context, volume_id_param):
            result["detached"] = volume_id_param == volume_id
        self.stubs.Set(cinder.API, "detach", fake_detach)

        def fake_terminate_connection(self, context, volume_id, connector):
            return {}
        self.stubs.Set(cinder.API, "terminate_connection",
                       fake_terminate_connection)

        # Kill the instance and check that it was detached
        self.compute.terminate_instance(admin, instance=instance)
        self.assertTrue(result["detached"])

    def test_terminate_deletes_all_bdms(self):
        admin = context.get_admin_context()
        instance = self._create_fake_instance()

        img_bdm = {'instance_uuid': instance['uuid'],
                   'device_name': '/dev/vda',
                   'source_type': 'image',
                   'destination_type': 'local',
                   'delete_on_termination': False,
                   'boot_index': 0,
                   'image_id': 'fake_image'}
        vol_bdm = {'instance_uuid': instance['uuid'],
                   'device_name': '/dev/vdc',
                   'source_type': 'volume',
                   'destination_type': 'volume',
                   'delete_on_termination': False,
                   'volume_id': 'fake_vol'}
        for bdm in img_bdm, vol_bdm:
            db.block_device_mapping_create(admin, bdm, legacy=False)

        self.stubs.Set(self.compute, 'volume_api', mox.MockAnything())
        self.stubs.Set(self.compute, '_prep_block_device', mox.MockAnything())
        self.compute.run_instance(self.context, instance=instance)

        self.compute.terminate_instance(self.context, instance=instance)
        bdms = db.block_device_mapping_get_all_by_instance(admin,
                                                           instance['uuid'])
        self.assertEquals(len(bdms), 0)

    def test_inject_network_info(self):
        instance = self._create_fake_instance(params={'host': CONF.host})
        self.compute.run_instance(self.context,
                instance=jsonutils.to_primitive(instance))
        instance = self.compute_api.get(self.context, instance['uuid'],
                                        want_objects=True)
        self.compute_api.inject_network_info(self.context, instance)
        self.stubs.Set(self.compute_api.network_api,
                       'deallocate_for_instance',
                       lambda *a, **kw: None)
        self.compute_api.delete(self.context, instance)

    def test_reset_network(self):
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context,
                instance=jsonutils.to_primitive(instance))
        instance = self.compute_api.get(self.context, instance['uuid'],
                                        want_objects=True)
        self.compute_api.reset_network(self.context, instance)

    def test_lock(self):
        instance = self._create_fake_instance_obj()
        self.stubs.Set(self.compute_api.network_api, 'deallocate_for_instance',
                       lambda *a, **kw: None)
        self.compute_api.lock(self.context, instance)

    def test_unlock(self):
        instance = self._create_fake_instance_obj()
        self.stubs.Set(self.compute_api.network_api, 'deallocate_for_instance',
                       lambda *a, **kw: None)
        self.compute_api.unlock(self.context, instance)

    def test_get_lock(self):
        instance = self._create_fake_instance()
        self.assertFalse(self.compute_api.get_lock(self.context, instance))
        db.instance_update(self.context, instance['uuid'], {'locked': True})
        self.assertTrue(self.compute_api.get_lock(self.context, instance))

    def test_add_remove_security_group(self):
        instance = self._create_fake_instance()

        self.compute.run_instance(self.context,
                instance=jsonutils.to_primitive(instance))
        instance = self.compute_api.get(self.context, instance['uuid'])
        security_group_name = self._create_group()['name']

        self.security_group_api.add_to_instance(self.context,
                                                instance,
                                                security_group_name)
        self.security_group_api.remove_from_instance(self.context,
                                                     instance,
                                                     security_group_name)

    def test_get_diagnostics(self):
        instance = self._create_fake_instance()

        rpcapi = compute_rpcapi.ComputeAPI
        self.mox.StubOutWithMock(rpcapi, 'get_diagnostics')
        rpcapi.get_diagnostics(self.context, instance=instance)
        self.mox.ReplayAll()

        self.compute_api.get_diagnostics(self.context, instance)

        self.stubs.Set(self.compute_api.network_api, 'deallocate_for_instance',
                       lambda *a, **kw: None)
        self.compute_api.delete(self.context, self._objectify(instance))

    def test_inject_file(self):
        # Ensure we can write a file to an instance.
        instance = self._create_fake_instance()
        self.compute_api.inject_file(self.context, instance,
                                     "/tmp/test", "File Contents")
        db.instance_destroy(self.context, instance['uuid'])

    def test_secgroup_refresh(self):
        instance = self._create_fake_instance()

        def rule_get(*args, **kwargs):
            mock_rule = db_fakes.FakeModel({'parent_group_id': 1})
            return [mock_rule]

        def group_get(*args, **kwargs):
            mock_group = db_fakes.FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(
                   self.compute_api.db,
                   'security_group_rule_get_by_security_group_grantee',
                   rule_get)
        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, CONF.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "namespace": None,
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                    compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_members_refresh(self.context, [1])

    def test_secgroup_refresh_once(self):
        instance = self._create_fake_instance()

        def rule_get(*args, **kwargs):
            mock_rule = db_fakes.FakeModel({'parent_group_id': 1})
            return [mock_rule]

        def group_get(*args, **kwargs):
            mock_group = db_fakes.FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(
                   self.compute_api.db,
                   'security_group_rule_get_by_security_group_grantee',
                   rule_get)
        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, CONF.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "namespace": None,
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                   compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_members_refresh(self.context, [1, 2])

    def test_secgroup_refresh_none(self):
        def rule_get(*args, **kwargs):
            mock_rule = db_fakes.FakeModel({'parent_group_id': 1})
            return [mock_rule]

        def group_get(*args, **kwargs):
            mock_group = db_fakes.FakeModel({'instances': []})
            return mock_group

        self.stubs.Set(
                   self.compute_api.db,
                   'security_group_rule_get_by_security_group_grantee',
                   rule_get)
        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        self.mox.ReplayAll()

        self.security_group_api.trigger_members_refresh(self.context, [1])

    def test_secrule_refresh(self):
        instance = self._create_fake_instance()

        def group_get(*args, **kwargs):
            mock_group = db_fakes.FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, CONF.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "namespace": None,
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                   compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_rules_refresh(self.context, [1])

    def test_secrule_refresh_once(self):
        instance = self._create_fake_instance()

        def group_get(*args, **kwargs):
            mock_group = db_fakes.FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, CONF.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "namespace": None,
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                   compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_rules_refresh(self.context, [1, 2])

    def test_secrule_refresh_none(self):
        def group_get(*args, **kwargs):
            mock_group = db_fakes.FakeModel({'instances': []})
            return mock_group

        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        self.mox.ReplayAll()

        self.security_group_api.trigger_rules_refresh(self.context, [1, 2])

    def test_live_migrate(self):
        instance, instance_uuid = self._run_instance()
        instance = self._objectify(instance)

        rpcapi = self.compute_api.compute_task_api
        self.mox.StubOutWithMock(rpcapi, 'live_migrate_instance')
        rpcapi.live_migrate_instance(self.context, instance, 'fake_dest_host',
                                     block_migration=True,
                                     disk_over_commit=True)

        self.mox.ReplayAll()

        self.compute_api.live_migrate(self.context, instance,
                                      block_migration=True,
                                      disk_over_commit=True,
                                      host_name='fake_dest_host')

        instance.refresh()
        self.assertEqual(instance['task_state'], task_states.MIGRATING)

    def test_evacuate(self):
        instance = jsonutils.to_primitive(self._create_fake_instance(
                                          services=True))
        instance_uuid = instance['uuid']
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        def fake_service_is_up(*args, **kwargs):
            return False

        def fake_rebuild_instance(*args, **kwargs):
            db.instance_update(self.context, instance_uuid,
                               {'host': kwargs['host']})

        self.stubs.Set(self.compute_api.servicegroup_api, 'service_is_up',
                fake_service_is_up)
        self.stubs.Set(self.compute_api.compute_rpcapi, 'rebuild_instance',
                fake_rebuild_instance)
        self.compute_api.evacuate(self.context.elevated(),
                                  instance,
                                  host='fake_dest_host',
                                  on_shared_storage=True,
                                  admin_password=None)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.REBUILDING)
        self.assertEqual(instance['host'], 'fake_dest_host')

        db.instance_destroy(self.context, instance['uuid'])

    def test_fail_evacuate_from_non_existing_host(self):
        inst = {}
        inst['vm_state'] = vm_states.ACTIVE
        inst['launched_at'] = timeutils.utcnow()
        inst['image_ref'] = FAKE_IMAGE_REF
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['host'] = 'fake_host'
        inst['node'] = NODENAME
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['memory_mb'] = 0
        inst['vcpus'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['architecture'] = 'x86_64'
        inst['os_type'] = 'Linux'

        instance = jsonutils.to_primitive(db.instance_create(self.context,
                                                             inst))
        instance_uuid = instance['uuid']
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        self.assertRaises(exception.ComputeHostNotFound,
                self.compute_api.evacuate, self.context.elevated(), instance,
                host='fake_dest_host', on_shared_storage=True,
                admin_password=None)

        db.instance_destroy(self.context, instance['uuid'])

    def test_fail_evacuate_from_running_host(self):
        instance = jsonutils.to_primitive(self._create_fake_instance(
                                          services=True))
        instance_uuid = instance['uuid']
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        def fake_service_is_up(*args, **kwargs):
            return True

        self.stubs.Set(self.compute_api.servicegroup_api, 'service_is_up',
                fake_service_is_up)

        self.assertRaises(exception.ComputeServiceUnavailable,
                self.compute_api.evacuate, self.context.elevated(), instance,
                host='fake_dest_host', on_shared_storage=True,
                admin_password=None)

        db.instance_destroy(self.context, instance['uuid'])

    def test_fail_evacuate_instance_in_wrong_state(self):
        instances = [
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.BUILDING})),
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.PAUSED})),
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.SUSPENDED})),
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.RESCUED})),
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.RESIZED})),
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.SOFT_DELETED})),
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.DELETED})),
            jsonutils.to_primitive(self._create_fake_instance(
                                    {'vm_state': vm_states.ERROR}))
        ]

        for instance in instances:
            self.assertRaises(exception.InstanceInvalidState,
                self.compute_api.evacuate, self.context, instance,
                host='fake_dest_host', on_shared_storage=True,
                admin_password=None)
            db.instance_destroy(self.context, instance['uuid'])

    def test_get_migrations(self):
        migration = test_migration.fake_db_migration(uuid="1234")
        filters = {'host': 'host1'}
        self.mox.StubOutWithMock(db, "migration_get_all_by_filters")
        db.migration_get_all_by_filters(self.context,
                                        filters).AndReturn([migration])
        self.mox.ReplayAll()

        migrations = self.compute_api.get_migrations(self.context,
                                                             filters)
        self.assertEqual(1, len(migrations))
        self.assertEqual(migrations[0].id, migration['id'])

    def _setup_get_instance_bdm_mox(self):
        new_bdm = object()

        self.mox.StubOutWithMock(self.compute_api.db,
                       'block_device_mapping_get_all_by_instance')
        self.compute_api.db.\
            block_device_mapping_get_all_by_instance(
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(new_bdm)
        return new_bdm

    def test_get_instance_bdms_legacy(self):
        expected = self._setup_get_instance_bdm_mox()
        self.mox.ReplayAll()

        instance = {'uuid': 'fake-instance'}

        self.assertEqual(expected,
                         self.compute_api.get_instance_bdms({},
                            instance, legacy=False))

    def test_get_instance_bdms_default(self):
        new_bdm = self._setup_get_instance_bdm_mox()
        expected = legacy_bdm = object()

        self.mox.StubOutWithMock(block_device, 'legacy_mapping')
        block_device.legacy_mapping(new_bdm).AndReturn(legacy_bdm)
        self.mox.ReplayAll()

        instance = {'uuid': 'fake-instance'}

        self.assertEqual(expected,
                         self.compute_api.get_instance_bdms({}, instance))


def fake_rpc_method(context, topic, msg, do_cast=True):
    pass


def _create_service_entries(context, values={'avail_zone1': ['fake_host1',
                                                             'fake_host2'],
                                             'avail_zone2': ['fake_host3'], }):
    for avail_zone, hosts in values.iteritems():
        for host in hosts:
            db.service_create(context,
                              {'host': host,
                               'binary': 'nova-compute',
                               'topic': 'compute',
                               'report_count': 0})
    return values


class ComputeAPIAggrTestCase(BaseTestCase):
    """This is for unit coverage of aggregate-related methods
    defined in nova.compute.api.
    """

    def setUp(self):
        super(ComputeAPIAggrTestCase, self).setUp()
        self.api = compute_api.AggregateAPI()
        self.context = context.get_admin_context()
        self.stubs.Set(rpc, 'call', fake_rpc_method)
        self.stubs.Set(rpc, 'cast', fake_rpc_method)

    def test_aggregate_no_zone(self):
        # Ensure we can create an aggregate without an availability  zone
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         None)
        self.api.delete_aggregate(self.context, aggr['id'])
        db.aggregate_get(self.context.elevated(read_deleted='yes'),
                         aggr['id'])
        self.assertRaises(exception.AggregateNotFound,
                          self.api.delete_aggregate, self.context, aggr['id'])

    def test_update_aggregate(self):
        # Ensure metadata can be updated.
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        fake_notifier.NOTIFICATIONS = []
        aggr = self.api.update_aggregate(self.context, aggr['id'],
                                         {'name': 'new_fake_aggregate'})
        self.assertEqual(availability_zones._get_cache().get('cache'), None)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'aggregate.updateprop.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'aggregate.updateprop.end')

    def test_update_aggregate_metadata(self):
        # Ensure metadata can be updated.
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        metadata = {'foo_key1': 'foo_value1',
                    'foo_key2': 'foo_value2', }
        fake_notifier.NOTIFICATIONS = []
        aggr = self.api.update_aggregate_metadata(self.context, aggr['id'],
                                                  metadata)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'aggregate.updatemetadata.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'aggregate.updatemetadata.end')
        metadata['foo_key1'] = None
        expected = self.api.update_aggregate_metadata(self.context,
                                             aggr['id'], metadata)
        self.assertThat(expected['metadata'],
                        matchers.DictMatches({'availability_zone': 'fake_zone',
                        'foo_key2': 'foo_value2'}))

    def test_delete_aggregate(self):
        # Ensure we can delete an aggregate.
        fake_notifier.NOTIFICATIONS = []
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'aggregate.create.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'aggregate.create.end')
        fake_notifier.NOTIFICATIONS = []
        self.api.delete_aggregate(self.context, aggr['id'])
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'aggregate.delete.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'aggregate.delete.end')
        db.aggregate_get(self.context.elevated(read_deleted='yes'),
                         aggr['id'])
        self.assertRaises(exception.AggregateNotFound,
                          self.api.delete_aggregate, self.context, aggr['id'])

    def test_delete_non_empty_aggregate(self):
        # Ensure InvalidAggregateAction is raised when non empty aggregate.
        _create_service_entries(self.context,
                                {'fake_availability_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_availability_zone')
        self.api.add_host_to_aggregate(self.context, aggr['id'], 'fake_host')
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.delete_aggregate, self.context, aggr['id'])

    def test_add_host_to_aggregate(self):
        # Ensure we can add a host to an aggregate.
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        fake_host = values[fake_zone][0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)

        def fake_add_aggregate_host(*args, **kwargs):
            hosts = kwargs["aggregate"]["hosts"]
            self.assertTrue(fake_host in hosts)

        self.stubs.Set(self.api.compute_rpcapi, 'add_aggregate_host',
                       fake_add_aggregate_host)

        fake_notifier.NOTIFICATIONS = []
        aggr = self.api.add_host_to_aggregate(self.context,
                                              aggr['id'], fake_host)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'aggregate.addhost.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'aggregate.addhost.end')
        self.assertEqual(len(aggr['hosts']), 1)

    def test_add_host_to_aggr_with_no_az(self):
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        fake_host = values[fake_zone][0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        aggr = self.api.add_host_to_aggregate(self.context, aggr['id'],
                                              fake_host)
        aggr_no_az = self.api.create_aggregate(self.context, 'fake_aggregate2',
                                               None)
        aggr_no_az = self.api.add_host_to_aggregate(self.context,
                                                    aggr_no_az['id'],
                                                    fake_host)
        self.assertIn(fake_host, aggr['hosts'])
        self.assertIn(fake_host, aggr_no_az['hosts'])

    def test_add_host_no_az_metadata(self):
        # NOTE(mtreinish) based on how create works this is not how the
        # the metadata is supposed to end up in the database but it has
        # been seen. See lp bug #1209007. This test just confirms that
        # the host is still added to the aggregate if there is no
        # availability zone metadata.
        def fake_aggregate_metadata_get_by_metadata_key(*args, **kwargs):
            return {'meta_key': 'fake_value'}
        self.stubs.Set(self.compute.db,
                       'aggregate_metadata_get_by_metadata_key',
                       fake_aggregate_metadata_get_by_metadata_key)
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        fake_host = values[fake_zone][0]
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         fake_zone)
        aggr = self.api.add_host_to_aggregate(self.context, aggr['id'],
                                              fake_host)
        self.assertIn(fake_host, aggr['hosts'])

    def test_add_host_to_multi_az(self):
        # Ensure we can't add a host to different availability zone
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        fake_host = values[fake_zone][0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        aggr = self.api.add_host_to_aggregate(self.context,
                                              aggr['id'], fake_host)
        self.assertEqual(len(aggr['hosts']), 1)
        fake_zone2 = "another_zone"
        aggr2 = self.api.create_aggregate(self.context,
                                         'fake_aggregate2', fake_zone2)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.add_host_to_aggregate,
                          self.context, aggr2['id'], fake_host)

    def test_add_host_to_aggregate_multiple(self):
        # Ensure we can add multiple hosts to an aggregate.
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        self.assertEqual(len(aggr['hosts']), len(values[fake_zone]))

    def test_add_host_to_aggregate_raise_not_found(self):
        # Ensure ComputeHostNotFound is raised when adding invalid host.
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        fake_notifier.NOTIFICATIONS = []
        self.assertRaises(exception.ComputeHostNotFound,
                          self.api.add_host_to_aggregate,
                          self.context, aggr['id'], 'invalid_host')
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        self.assertEqual(fake_notifier.NOTIFICATIONS[1].publisher_id,
                         'compute.fake-mini')

    def test_remove_host_from_aggregate_active(self):
        # Ensure we can remove a host from an aggregate.
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        host_to_remove = values[fake_zone][0]

        def fake_remove_aggregate_host(*args, **kwargs):
            hosts = kwargs["aggregate"]["hosts"]
            self.assertFalse(host_to_remove in hosts)

        self.stubs.Set(self.api.compute_rpcapi, 'remove_aggregate_host',
                       fake_remove_aggregate_host)

        fake_notifier.NOTIFICATIONS = []
        expected = self.api.remove_host_from_aggregate(self.context,
                                                       aggr['id'],
                                                       host_to_remove)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.event_type,
                         'aggregate.removehost.start')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg.event_type,
                         'aggregate.removehost.end')
        self.assertEqual(len(aggr['hosts']) - 1, len(expected['hosts']))

    def test_remove_host_from_aggregate_raise_not_found(self):
        # Ensure ComputeHostNotFound is raised when removing invalid host.
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        self.assertRaises(exception.ComputeHostNotFound,
                          self.api.remove_host_from_aggregate,
                          self.context, aggr['id'], 'invalid_host')

    def test_aggregate_list(self):
        aggregate = self.api.create_aggregate(self.context,
                                              'fake_aggregate',
                                              'fake_zone')
        metadata = {'foo_key1': 'foo_value1',
                    'foo_key2': 'foo_value2'}
        meta_aggregate = self.api.create_aggregate(self.context,
                                                   'fake_aggregate2',
                                                   'fake_zone2')
        self.api.update_aggregate_metadata(self.context, meta_aggregate['id'],
                                           metadata)
        aggregate_list = self.api.get_aggregate_list(self.context)
        self.assertIn(aggregate['id'],
                      map(lambda x: x['id'], aggregate_list))
        self.assertIn(meta_aggregate['id'],
                      map(lambda x: x['id'], aggregate_list))
        self.assertIn('fake_aggregate',
                      map(lambda x: x['name'], aggregate_list))
        self.assertIn('fake_aggregate2',
                      map(lambda x: x['name'], aggregate_list))
        self.assertIn('fake_zone',
                      map(lambda x: x['availability_zone'], aggregate_list))
        self.assertIn('fake_zone2',
                      map(lambda x: x['availability_zone'], aggregate_list))
        test_meta_aggregate = aggregate_list[1]
        self.assertIn('foo_key1', test_meta_aggregate.get('metadata'))
        self.assertIn('foo_key2', test_meta_aggregate.get('metadata'))
        self.assertEquals('foo_value1',
                          test_meta_aggregate.get('metadata')['foo_key1'])
        self.assertEquals('foo_value2',
                          test_meta_aggregate.get('metadata')['foo_key2'])

    def test_aggregate_list_with_hosts(self):
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        host_aggregate = self.api.create_aggregate(self.context,
                                                   'fake_aggregate',
                                                   fake_zone)
        self.api.add_host_to_aggregate(self.context, host_aggregate['id'],
                                       values[fake_zone][0])
        aggregate_list = self.api.get_aggregate_list(self.context)
        aggregate = aggregate_list[0]
        self.assertIn(values[fake_zone][0], aggregate.get('hosts'))


class ComputeAggrTestCase(BaseTestCase):
    """This is for unit coverage of aggregate-related methods
    defined in nova.compute.manager.
    """

    def setUp(self):
        super(ComputeAggrTestCase, self).setUp()
        self.context = context.get_admin_context()
        values = {'name': 'test_aggr'}
        az = {'availability_zone': 'test_zone'}
        self.aggr = db.aggregate_create(self.context, values, metadata=az)

    def test_add_aggregate_host(self):
        def fake_driver_add_to_aggregate(context, aggregate, host, **_ignore):
            fake_driver_add_to_aggregate.called = True
            return {"foo": "bar"}
        self.stubs.Set(self.compute.driver, "add_to_aggregate",
                       fake_driver_add_to_aggregate)

        self.compute.add_aggregate_host(self.context, "host",
                aggregate=jsonutils.to_primitive(self.aggr))
        self.assertTrue(fake_driver_add_to_aggregate.called)

    def test_remove_aggregate_host(self):
        def fake_driver_remove_from_aggregate(context, aggregate, host,
                                              **_ignore):
            fake_driver_remove_from_aggregate.called = True
            self.assertEqual("host", host, "host")
            return {"foo": "bar"}
        self.stubs.Set(self.compute.driver, "remove_from_aggregate",
                       fake_driver_remove_from_aggregate)

        self.compute.remove_aggregate_host(self.context,
                aggregate=jsonutils.to_primitive(self.aggr), host="host")
        self.assertTrue(fake_driver_remove_from_aggregate.called)

    def test_add_aggregate_host_passes_slave_info_to_driver(self):
        def driver_add_to_aggregate(context, aggregate, host, **kwargs):
            self.assertEquals(self.context, context)
            self.assertEquals(aggregate['id'], self.aggr['id'])
            self.assertEquals(host, "the_host")
            self.assertEquals("SLAVE_INFO", kwargs.get("slave_info"))

        self.stubs.Set(self.compute.driver, "add_to_aggregate",
                       driver_add_to_aggregate)

        self.compute.add_aggregate_host(self.context, "the_host",
                slave_info="SLAVE_INFO",
                aggregate=jsonutils.to_primitive(self.aggr))

    def test_remove_from_aggregate_passes_slave_info_to_driver(self):
        def driver_remove_from_aggregate(context, aggregate, host, **kwargs):
            self.assertEquals(self.context, context)
            self.assertEquals(aggregate['id'], self.aggr['id'])
            self.assertEquals(host, "the_host")
            self.assertEquals("SLAVE_INFO", kwargs.get("slave_info"))

        self.stubs.Set(self.compute.driver, "remove_from_aggregate",
                       driver_remove_from_aggregate)

        self.compute.remove_aggregate_host(self.context,
                aggregate=jsonutils.to_primitive(self.aggr), host="the_host",
                slave_info="SLAVE_INFO")


class ComputePolicyTestCase(BaseTestCase):

    def setUp(self):
        super(ComputePolicyTestCase, self).setUp()

        self.compute_api = compute.API()

    def test_actions_are_prefixed(self):
        self.mox.StubOutWithMock(policy, 'enforce')
        nova.policy.enforce(self.context, 'compute:reboot', {})
        self.mox.ReplayAll()
        compute_api.check_policy(self.context, 'reboot', {})

    def test_wrapped_method(self):
        instance = self._create_fake_instance(params={'host': None,
                                                      'cell_name': 'foo'})

        # force delete to fail
        rules = {"compute:delete": [["false:false"]]}
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.delete, self.context, instance)

        # reset rules to allow deletion
        rules = {"compute:delete": []}
        self.policy.set_rules(rules)

        self.compute_api.delete(self.context, self._objectify(instance))

    def test_create_fail(self):
        rules = {"compute:create": [["false:false"]]}
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.create, self.context, '1', '1')

    def test_create_attach_volume_fail(self):
        rules = {
            "compute:create": [],
            "compute:create:attach_network": [["false:false"]],
            "compute:create:attach_volume": [],
        }
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.create, self.context, '1', '1',
                          requested_networks='blah',
                          block_device_mapping='blah')

    def test_create_attach_network_fail(self):
        rules = {
            "compute:create": [],
            "compute:create:attach_network": [],
            "compute:create:attach_volume": [["false:false"]],
        }
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.create, self.context, '1', '1',
                          requested_networks='blah',
                          block_device_mapping='blah')

    def test_get_fail(self):
        instance = self._create_fake_instance()

        rules = {
            "compute:get": [["false:false"]],
        }
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.get, self.context, instance['uuid'])

    def test_get_all_fail(self):
        rules = {
            "compute:get_all": [["false:false"]],
        }
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.get_all, self.context)

    def test_get_instance_faults(self):
        instance1 = self._create_fake_instance()
        instance2 = self._create_fake_instance()
        instances = [instance1, instance2]

        rules = {
            "compute:get_instance_faults": [["false:false"]],
        }
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.get_instance_faults,
                          context.get_admin_context(), instances)

    def test_force_host_fail(self):
        rules = {"compute:create": [],
                 "compute:create:forced_host": [["role:fake"]],
                 "network:validate_networks": []}
        self.policy.set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.create, self.context, None, '1',
                          availability_zone='1:1')

    def test_force_host_pass(self):
        rules = {"compute:create": [],
                 "compute:create:forced_host": [],
                 "network:validate_networks": []}
        self.policy.set_rules(rules)

        self.compute_api.create(self.context, None, '1',
                                availability_zone='1:1')


class DisabledInstanceTypesTestCase(BaseTestCase):
    """
    Some instance-types are marked 'disabled' which means that they will not
    show up in customer-facing listings. We do, however, want those
    instance-types to be available for emergency migrations and for rebuilding
    of existing instances.

    One legitimate use of the 'disabled' field would be when phasing out a
    particular instance-type. We still want customers to be able to use an
    instance that of the old type, and we want Ops to be able perform
    migrations against it, but we *don't* want customers building new slices
    with ths phased-out instance-type.
    """
    def setUp(self):
        super(DisabledInstanceTypesTestCase, self).setUp()
        self.compute_api = compute.API()
        self.inst_type = flavors.get_default_flavor()

    def test_can_build_instance_from_visible_instance_type(self):
        self.inst_type['disabled'] = False
        # Assert that exception.InstanceTypeNotFound is not raised
        self.compute_api.create(self.context, self.inst_type,
                                image_href='some-fake-image')

    def test_cannot_build_instance_from_disabled_instance_type(self):
        self.inst_type['disabled'] = True
        self.assertRaises(exception.InstanceTypeNotFound,
            self.compute_api.create, self.context, self.inst_type, None)

    def test_can_resize_to_visible_instance_type(self):
        instance = self._create_fake_instance_obj()
        orig_get_flavor_by_flavor_id =\
                flavors.get_flavor_by_flavor_id

        def fake_get_flavor_by_flavor_id(flavor_id, ctxt=None,
                                                read_deleted="yes"):
            instance_type = orig_get_flavor_by_flavor_id(flavor_id,
                                                                ctxt,
                                                                read_deleted)
            instance_type['disabled'] = False
            return instance_type

        self.stubs.Set(flavors, 'get_flavor_by_flavor_id',
                       fake_get_flavor_by_flavor_id)

        # FIXME(sirp): for legacy this raises FlavorNotFound instead of
        # InstanceTypeNotFound; we should eventually make it raise
        # InstanceTypeNotFound for consistency.
        self._stub_migrate_server()
        self.compute_api.resize(self.context, instance, '4')

    def test_cannot_resize_to_disabled_instance_type(self):
        instance = self._create_fake_instance_obj()
        orig_get_flavor_by_flavor_id = \
                flavors.get_flavor_by_flavor_id

        def fake_get_flavor_by_flavor_id(flavor_id, ctxt=None,
                                                read_deleted="yes"):
            instance_type = orig_get_flavor_by_flavor_id(flavor_id,
                                                                ctxt,
                                                                read_deleted)
            instance_type['disabled'] = True
            return instance_type

        self.stubs.Set(flavors, 'get_flavor_by_flavor_id',
                       fake_get_flavor_by_flavor_id)

        # FIXME(sirp): for legacy this raises FlavorNotFound instead of
        # InstanceTypeNot; we should eventually make it raise
        # InstanceTypeNotFound for consistency.
        self.assertRaises(exception.FlavorNotFound,
            self.compute_api.resize, self.context, instance, '4')


class ComputeReschedulingTestCase(BaseTestCase):
    """Tests re-scheduling logic for new build requests."""

    def setUp(self):
        super(ComputeReschedulingTestCase, self).setUp()

        self.expected_task_state = task_states.SCHEDULING

        def fake_update(*args, **kwargs):
            self.updated_task_state = kwargs.get('task_state')
        self.stubs.Set(self.compute, '_instance_update', fake_update)

    def _reschedule(self, request_spec=None, filter_properties=None,
                    exc_info=None):
        if not filter_properties:
            filter_properties = {}

        instance_uuid = "12-34-56-78-90"

        admin_password = None
        injected_files = None
        requested_networks = None
        is_first_time = False

        scheduler_method = self.compute.scheduler_rpcapi.run_instance
        method_args = (request_spec, admin_password, injected_files,
                       requested_networks, is_first_time, filter_properties)
        return self.compute._reschedule(self.context, request_spec,
                filter_properties, instance_uuid, scheduler_method,
                method_args, self.expected_task_state, exc_info=exc_info)

    def test_reschedule_no_filter_properties(self):
        # no filter_properties will disable re-scheduling.
        self.assertFalse(self._reschedule())

    def test_reschedule_no_retry_info(self):
        # no retry info will also disable re-scheduling.
        filter_properties = {}
        self.assertFalse(self._reschedule(filter_properties=filter_properties))

    def test_reschedule_no_request_spec(self):
        # no request spec will also disable re-scheduling.
        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)
        self.assertFalse(self._reschedule(filter_properties=filter_properties))

    def test_reschedule_success(self):
        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)
        request_spec = {'instance_uuids': ['foo', 'bar']}
        try:
            raise test.TestingException("just need an exception")
        except test.TestingException:
            exc_info = sys.exc_info()
            exc_str = traceback.format_exception(*exc_info)

        self.assertTrue(self._reschedule(filter_properties=filter_properties,
            request_spec=request_spec, exc_info=exc_info))
        self.assertEqual(1, len(request_spec['instance_uuids']))
        self.assertEqual(self.updated_task_state, self.expected_task_state)
        self.assertEqual(exc_str, filter_properties['retry']['exc'])


class ComputeReschedulingResizeTestCase(ComputeReschedulingTestCase):
    """Test re-scheduling logic for prep_resize requests."""

    def setUp(self):
        super(ComputeReschedulingResizeTestCase, self).setUp()
        self.expected_task_state = task_states.RESIZE_PREP

    def _reschedule(self, request_spec=None, filter_properties=None,
                    exc_info=None):
        if not filter_properties:
            filter_properties = {}

        instance_uuid = "12-34-56-78-90"
        instance = fake_instance.fake_db_instance(uuid=instance_uuid)
        instance = self._objectify(instance)
        instance_type = {}
        image = None
        reservations = None

        scheduler_method = self.compute.scheduler_rpcapi.prep_resize
        method_args = (instance, instance_type, image, request_spec,
                filter_properties, reservations)

        return self.compute._reschedule(self.context, request_spec,
                filter_properties, instance_uuid, scheduler_method,
                method_args, self.expected_task_state, exc_info=exc_info)


class InnerTestingException(Exception):
    pass


class ComputeRescheduleOrErrorTestCase(BaseTestCase):
    """Test logic and exception handling around rescheduling or re-raising
    original exceptions when builds fail.
    """

    def setUp(self):
        super(ComputeRescheduleOrErrorTestCase, self).setUp()
        self.instance = self._create_fake_instance()

    def test_reschedule_or_error_called(self):
        """Basic sanity check to make sure _reschedule_or_error is called
        when a build fails.
        """
        self.mox.StubOutWithMock(self.compute, '_spawn')
        self.mox.StubOutWithMock(self.compute, '_reschedule_or_error')

        self.compute._spawn(mox.IgnoreArg(), self.instance, mox.IgnoreArg(),
                [], mox.IgnoreArg(), [], None, set_access_ip=False).AndRaise(
                        test.TestingException("BuildError"))
        self.compute._reschedule_or_error(mox.IgnoreArg(), self.instance,
                mox.IgnoreArg(), None, None, None,
                False, None, {}, [], False).AndReturn(True)

        self.mox.ReplayAll()
        self.compute._run_instance(self.context, None, {}, None, None, None,
                False, None, self.instance, False)

    def test_shutdown_instance_fail(self):
        """Test shutdown instance failing before re-scheduling logic can even
        run.
        """
        instance_uuid = self.instance['uuid']
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')

        try:
            raise test.TestingException("Original")
        except Exception:
            exc_info = sys.exc_info()

            compute_utils.add_instance_fault_from_exc(self.context,
                    self.compute.conductor_api,
                    self.instance, exc_info[0], exc_info=exc_info)
            self.compute._shutdown_instance(self.context, self.instance,
                    mox.IgnoreArg(),
                    mox.IgnoreArg()).AndRaise(InnerTestingException("Error"))
            self.compute._log_original_error(exc_info, instance_uuid)

            self.mox.ReplayAll()

            # should raise the deallocation exception, not the original build
            # error:
            self.assertRaises(InnerTestingException,
                    self.compute._reschedule_or_error, self.context,
                    self.instance, exc_info, None, None, None, False, None, {})

    def test_reschedule_fail(self):
        # Test handling of exception from _reschedule.
        try:
            raise test.TestingException("Original")
        except Exception:
            exc_info = sys.exc_info()

        instance_uuid = self.instance['uuid']
        method_args = (None, None, None, None, False, {})
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self.mox.StubOutWithMock(self.compute, '_reschedule')

        self.compute._shutdown_instance(self.context, self.instance,
                                        mox.IgnoreArg(),
                                        mox.IgnoreArg())
        self.compute._cleanup_volumes(self.context, instance_uuid,
                                        mox.IgnoreArg())
        self.compute._reschedule(self.context, None, instance_uuid,
                {}, self.compute.scheduler_rpcapi.run_instance,
                method_args, task_states.SCHEDULING, exc_info).AndRaise(
                        InnerTestingException("Inner"))

        self.mox.ReplayAll()

        self.assertFalse(self.compute._reschedule_or_error(self.context,
            self.instance, exc_info, None, None, None, False, None, {}))

    def test_reschedule_false(self):
        # Test not-rescheduling, but no nested exception.
        instance_uuid = self.instance['uuid']
        method_args = (None, None, None, None, False, {})
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self.mox.StubOutWithMock(self.compute, '_reschedule')

        try:
            raise test.TestingException("Original")
        except Exception:
            exc_info = sys.exc_info()
            compute_utils.add_instance_fault_from_exc(self.context,
                    self.compute.conductor_api,
                    self.instance, exc_info[0], exc_info=exc_info)

            self.compute._shutdown_instance(self.context, self.instance,
                                            mox.IgnoreArg(),
                                            mox.IgnoreArg())
            self.compute._cleanup_volumes(self.context, instance_uuid,
                                            mox.IgnoreArg())
            self.compute._reschedule(self.context, None, {}, instance_uuid,
                    self.compute.scheduler_rpcapi.run_instance, method_args,
                    task_states.SCHEDULING, exc_info).AndReturn(False)

            self.mox.ReplayAll()

            # re-scheduling is False, the original build error should be
            # raised here:
            self.assertFalse(self.compute._reschedule_or_error(self.context,
                self.instance, exc_info, None, None, None, False, None, {}))

    def test_reschedule_true(self):
        # Test behavior when re-scheduling happens.
        instance_uuid = self.instance['uuid']
        method_args = (None, None, None, None, False, {})
        self.mox.StubOutWithMock(self.compute, '_shutdown_instance')
        self.mox.StubOutWithMock(self.compute, '_cleanup_volumes')
        self.mox.StubOutWithMock(self.compute, '_reschedule')

        try:
            raise test.TestingException("Original")
        except Exception:
            exc_info = sys.exc_info()

            compute_utils.add_instance_fault_from_exc(self.context,
                    self.compute.conductor_api,
                    self.instance, exc_info[0], exc_info=exc_info)
            self.compute._shutdown_instance(self.context, self.instance,
                                            mox.IgnoreArg(),
                                            mox.IgnoreArg())
            self.compute._cleanup_volumes(self.context, instance_uuid,
                                          mox.IgnoreArg())
            self.compute._reschedule(self.context, None, {}, instance_uuid,
                    self.compute.scheduler_rpcapi.run_instance,
                    method_args, task_states.SCHEDULING, exc_info).AndReturn(
                            True)
            self.compute._log_original_error(exc_info, instance_uuid)

            self.mox.ReplayAll()

            # re-scheduling is True, original error is logged, but nothing
            # is raised:
            self.compute._reschedule_or_error(self.context, self.instance,
                    exc_info, None, None, None, False, None, {})

    def test_no_reschedule_on_delete_during_spawn(self):
        # instance should not be rescheduled if instance is deleted
        # during the build
        self.mox.StubOutWithMock(self.compute, '_spawn')
        self.mox.StubOutWithMock(self.compute, '_reschedule_or_error')

        exc = exception.UnexpectedTaskStateError(expected=task_states.SPAWNING,
                actual=task_states.DELETING)
        self.compute._spawn(mox.IgnoreArg(), self.instance, mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg(), set_access_ip=False).AndRaise(exc)

        self.mox.ReplayAll()
        # test succeeds if mocked method '_reschedule_or_error' is not
        # called.
        self.compute._run_instance(self.context, None, {}, None, None, None,
                False, None, self.instance, False)

    def test_no_reschedule_on_unexpected_task_state(self):
        # instance shouldn't be rescheduled if unexpected task state arises.
        # the exception should get reraised.
        self.mox.StubOutWithMock(self.compute, '_spawn')
        self.mox.StubOutWithMock(self.compute, '_reschedule_or_error')

        exc = exception.UnexpectedTaskStateError(expected=task_states.SPAWNING,
                actual=task_states.SCHEDULING)
        self.compute._spawn(mox.IgnoreArg(), self.instance, mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg(), set_access_ip=False).AndRaise(exc)

        self.mox.ReplayAll()
        self.assertRaises(exception.UnexpectedTaskStateError,
                self.compute._run_instance, self.context, None, {}, None, None,
                None, False, None, self.instance, False)

    def test_no_reschedule_on_block_device_fail(self):
        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.mox.StubOutWithMock(self.compute, '_reschedule_or_error')

        exc = exception.InvalidBDM()

        self.compute._prep_block_device(mox.IgnoreArg(), self.instance,
                                        mox.IgnoreArg()).AndRaise(exc)

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidBDM, self.compute._run_instance,
                          self.context, None, {}, None, None, None, False,
                          None, self.instance, False)


class ComputeRescheduleResizeOrReraiseTestCase(BaseTestCase):
    """Test logic and exception handling around rescheduling prep resize
    requests
    """
    def setUp(self):
        super(ComputeRescheduleResizeOrReraiseTestCase, self).setUp()
        self.instance = self._create_fake_instance()
        self.instance_uuid = self.instance['uuid']
        self.instance_type = flavors.get_flavor_by_name(
                "m1.tiny")

    def test_reschedule_resize_or_reraise_called(self):
        """Verify the rescheduling logic gets called when there is an error
        during prep_resize.
        """
        inst_obj = self._create_fake_instance_obj()

        self.mox.StubOutWithMock(self.compute.db, 'migration_create')
        self.mox.StubOutWithMock(self.compute, '_reschedule_resize_or_reraise')

        self.compute.db.migration_create(mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(test.TestingException("Original"))

        self.compute._reschedule_resize_or_reraise(mox.IgnoreArg(), None,
                inst_obj, mox.IgnoreArg(), self.instance_type, None, None,
                None)

        self.mox.ReplayAll()

        self.compute.prep_resize(self.context, image=None,
                                 instance=inst_obj,
                                 instance_type=self.instance_type)

    def test_reschedule_fails_with_exception(self):
        """Original exception should be raised if the _reschedule method
        raises another exception
        """
        instance = self._create_fake_instance_obj()
        method_args = (None, instance, self.instance_type, None, None,
                None)
        self.mox.StubOutWithMock(self.compute, "_reschedule")

        self.compute._reschedule(
                self.context, None, None, instance.uuid,
                self.compute.scheduler_rpcapi.prep_resize, method_args,
                task_states.RESIZE_PREP).AndRaise(
                        InnerTestingException("Inner"))
        self.mox.ReplayAll()

        try:
            raise test.TestingException("Original")
        except Exception:
            exc_info = sys.exc_info()
            self.assertRaises(test.TestingException,
                    self.compute._reschedule_resize_or_reraise, self.context,
                    None, instance, exc_info, self.instance_type, None,
                    {}, {})

    def test_reschedule_false(self):
        """Original exception should be raised if the resize is not
        rescheduled.
        """
        instance = self._create_fake_instance_obj()
        method_args = (None, instance, self.instance_type, None, None, None)
        self.mox.StubOutWithMock(self.compute, "_reschedule")

        self.compute._reschedule(
                self.context, None, None, instance.uuid,
                self.compute.scheduler_rpcapi.prep_resize, method_args,
                task_states.RESIZE_PREP).AndReturn(False)
        self.mox.ReplayAll()

        try:
            raise test.TestingException("Original")
        except Exception:
            exc_info = sys.exc_info()
            self.assertRaises(test.TestingException,
                    self.compute._reschedule_resize_or_reraise, self.context,
                    None, instance, exc_info, self.instance_type, None,
                    {}, {})

    def test_reschedule_true(self):
        # If rescheduled, the original resize exception should be logged.
        instance = self._create_fake_instance_obj()
        instance_p = obj_base.obj_to_primitive(instance)
        method_args = (instance_p, self.instance_type, None, {}, {}, None)
        try:
            raise test.TestingException("Original")
        except Exception:
            exc_info = sys.exc_info()

            self.mox.StubOutWithMock(self.compute, "_reschedule")
            self.mox.StubOutWithMock(self.compute, "_log_original_error")
            self.compute._reschedule(self.context, {}, {},
                    instance.uuid,
                    self.compute.scheduler_rpcapi.prep_resize, method_args,
                    task_states.RESIZE_PREP, exc_info).AndReturn(True)

            self.compute._log_original_error(exc_info, instance.uuid)
            self.mox.ReplayAll()

            self.compute._reschedule_resize_or_reraise(self.context, None,
                    instance, exc_info, self.instance_type, None, {}, {})


class ComputeInactiveImageTestCase(BaseTestCase):
    def setUp(self):
        super(ComputeInactiveImageTestCase, self).setUp()

        def fake_show(meh, context, id):
            return {'id': id, 'min_disk': None, 'min_ram': None,
                    'name': 'fake_name',
                    'status': 'deleted',
                    'properties': {'kernel_id': 'fake_kernel_id',
                                   'ramdisk_id': 'fake_ramdisk_id',
                                   'something_else': 'meow'}}

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)
        self.compute_api = compute.API()

    def test_create_instance_with_deleted_image(self):
        # Make sure we can't start an instance with a deleted image.
        inst_type = flavors.get_flavor_by_name('m1.tiny')
        self.assertRaises(exception.ImageNotActive,
                          self.compute_api.create,
                          self.context, inst_type, 'fake-image-uuid')


class EvacuateHostTestCase(BaseTestCase):
    def setUp(self):
        super(EvacuateHostTestCase, self).setUp()
        self.inst_ref = jsonutils.to_primitive(self._create_fake_instance
                                          ({'host': 'fake_host_2',
                                            'node': 'fakenode2'}))
        db.instance_update(self.context, self.inst_ref['uuid'],
                           {"task_state": task_states.REBUILDING})

    def tearDown(self):
        db.instance_destroy(self.context, self.inst_ref['uuid'])
        super(EvacuateHostTestCase, self).tearDown()

    def _rebuild(self, on_shared_storage=True):
        def fake(cls, ctxt, instance, *args, **kwargs):
            pass

        self.stubs.Set(network_api.API, 'setup_networks_on_host', fake)

        orig_image_ref = None
        image_ref = None
        injected_files = None
        self.compute.rebuild_instance(
                self.context, self.inst_ref, orig_image_ref, image_ref,
                injected_files, 'newpass', recreate=True,
                on_shared_storage=on_shared_storage)

    def test_rebuild_on_host_updated_target(self):
        """Confirm evacuate scenario updates host and node."""
        self.stubs.Set(self.compute.driver, 'instance_on_disk', lambda x: True)

        def fake_get_compute_info(context, host):
            self.assertTrue(context.is_admin)
            self.assertEquals('fake-mini', host)
            return {'hypervisor_hostname': self.rt.nodename}

        self.stubs.Set(self.compute, '_get_compute_info',
                       fake_get_compute_info)
        self.mox.ReplayAll()

        self._rebuild()

        # Should be on destination host
        instance = db.instance_get(self.context, self.inst_ref['id'])
        self.assertEqual(instance['host'], self.compute.host)
        self.assertEqual(NODENAME, instance['node'])

    def test_rebuild_on_host_updated_target_node_not_found(self):
        """Confirm evacuate scenario where compute_node isn't found."""
        self.stubs.Set(self.compute.driver, 'instance_on_disk', lambda x: True)

        def fake_get_compute_info(context, host):
            raise exception.NotFound(_("Host %s not found") % host)

        self.stubs.Set(self.compute, '_get_compute_info',
                       fake_get_compute_info)
        self.mox.ReplayAll()

        self._rebuild()

        # Should be on destination host
        instance = db.instance_get(self.context, self.inst_ref['id'])
        self.assertEqual(instance['host'], self.compute.host)
        self.assertIsNone(instance['node'])

    def test_rebuild_with_instance_in_stopped_state(self):
        """Confirm evacuate scenario updates vm_state to stopped
        if instance is in stopped state
        """
        #Initialize the VM to stopped state
        db.instance_update(self.context, self.inst_ref['uuid'],
                           {"vm_state": vm_states.STOPPED})
        self.inst_ref['vm_state'] = vm_states.STOPPED

        self.stubs.Set(self.compute.driver, 'instance_on_disk', lambda x: True)
        self.mox.ReplayAll()

        self._rebuild()

        #Check the vm state is reset to stopped
        instance = db.instance_get(self.context, self.inst_ref['id'])
        self.assertEqual(instance['vm_state'], vm_states.STOPPED)

    def test_rebuild_with_wrong_shared_storage(self):
        """Confirm evacuate scenario does not update host."""
        self.stubs.Set(self.compute.driver, 'instance_on_disk', lambda x: True)
        self.mox.ReplayAll()

        self.assertRaises(exception.InvalidSharedStorage,
                          lambda: self._rebuild(on_shared_storage=False))

        # Should remain on original host
        instance = db.instance_get(self.context, self.inst_ref['id'])
        self.assertEqual(instance['host'], 'fake_host_2')

    def test_rebuild_on_host_with_volumes(self):
        """Confirm evacuate scenario reconnects volumes."""
        values = {'instance_uuid': self.inst_ref['uuid'],
                  'source_type': 'volume',
                  'device_name': '/dev/vdc',
                  'delete_on_termination': False,
                  'volume_id': 'fake_volume_id'}

        db.block_device_mapping_create(self.context, values)

        def fake_volume_get(self, context, volume):
            return {'id': 'fake_volume_id'}
        self.stubs.Set(cinder.API, "get", fake_volume_get)

        # Stub out and record whether it gets detached
        result = {"detached": False}

        def fake_detach(self, context, volume):
            result["detached"] = volume["id"] == 'fake_volume_id'
        self.stubs.Set(cinder.API, "detach", fake_detach)

        def fake_terminate_connection(self, context, volume, connector):
            return {}
        self.stubs.Set(cinder.API, "terminate_connection",
                       fake_terminate_connection)

        # make sure volumes attach, detach are called
        self.mox.StubOutWithMock(self.compute.volume_api, 'detach')
        self.compute.volume_api.detach(mox.IsA(self.context), mox.IgnoreArg())

        self.mox.StubOutWithMock(self.compute, '_prep_block_device')
        self.compute._prep_block_device(mox.IsA(self.context),
                                        mox.IsA(self.inst_ref),
                                        mox.IgnoreArg())

        self.stubs.Set(self.compute.driver, 'instance_on_disk', lambda x: True)
        self.mox.ReplayAll()

        self._rebuild()

        # cleanup
        for bdms in db.block_device_mapping_get_all_by_instance(
                self.context, self.inst_ref['uuid']):
            db.block_device_mapping_destroy(self.context, bdms['id'])

    def test_rebuild_on_host_with_shared_storage(self):
        """Confirm evacuate scenario on shared storage."""
        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.compute.driver.spawn(mox.IsA(self.context),
                mox.IsA(self.inst_ref), {}, mox.IgnoreArg(), 'newpass',
                network_info=mox.IgnoreArg(),
                block_device_info=mox.IgnoreArg())

        self.stubs.Set(self.compute.driver, 'instance_on_disk', lambda x: True)
        self.mox.ReplayAll()

        self._rebuild()

    def test_rebuild_on_host_without_shared_storage(self):
        """Confirm evacuate scenario without shared storage
        (rebuild from image)
        """
        fake_image = {'id': 1,
                      'name': 'fake_name',
                      'properties': {'kernel_id': 'fake_kernel_id',
                                     'ramdisk_id': 'fake_ramdisk_id'}}

        self.mox.StubOutWithMock(self.compute.driver, 'spawn')
        self.compute.driver.spawn(mox.IsA(self.context),
                mox.IsA(self.inst_ref), mox.IsA(fake_image), mox.IgnoreArg(),
                mox.IsA('newpass'), network_info=mox.IgnoreArg(),
                block_device_info=mox.IgnoreArg())

        self.stubs.Set(self.compute.driver, 'instance_on_disk',
                       lambda x: False)
        self.mox.ReplayAll()

        self._rebuild(on_shared_storage=False)

    def test_rebuild_on_host_instance_exists(self):
        """Rebuild if instance exists raises an exception."""
        db.instance_update(self.context, self.inst_ref['uuid'],
                           {"task_state": task_states.SCHEDULING})
        self.compute.run_instance(self.context, instance=self.inst_ref)

        self.stubs.Set(self.compute.driver, 'instance_on_disk', lambda x: True)
        self.assertRaises(exception.InstanceExists,
                          lambda: self._rebuild(on_shared_storage=True))

    def test_driver_doesnt_support_recreate(self):
        with utils.temporary_mutation(self.compute.driver.capabilities,
                                      supports_recreate=False):
            self.stubs.Set(self.compute.driver, 'instance_on_disk',
                           lambda x: True)
            self.assertRaises(exception.InstanceRecreateNotSupported,
                              lambda: self._rebuild(on_shared_storage=True))


class ComputeInjectedFilesTestCase(BaseTestCase):
    # Test that running instances with injected_files decodes files correctly

    def setUp(self):
        super(ComputeInjectedFilesTestCase, self).setUp()
        self.instance = self._create_fake_instance()
        self.stubs.Set(self.compute.driver, 'spawn', self._spawn)

    def _spawn(self, context, instance, image_meta, injected_files,
            admin_password, nw_info, block_device_info, db_api=None):
        self.assertEqual(self.expected, injected_files)

    def _test(self, injected_files, decoded_files):
        self.expected = decoded_files
        self.compute.run_instance(self.context, self.instance,
                                  injected_files=injected_files)

    def test_injected_none(self):
        # test an input of None for injected_files
        self._test(None, [])

    def test_injected_empty(self):
        # test an input of [] for injected_files
        self._test([], [])

    def test_injected_success(self):
        # test with valid b64 encoded content.
        injected_files = [
            ('/a/b/c', base64.b64encode('foobarbaz')),
            ('/d/e/f', base64.b64encode('seespotrun')),
        ]

        decoded_files = [
            ('/a/b/c', 'foobarbaz'),
            ('/d/e/f', 'seespotrun'),
        ]
        self._test(injected_files, decoded_files)

    def test_injected_invalid(self):
        # test with invalid b64 encoded content
        injected_files = [
            ('/a/b/c', base64.b64encode('foobarbaz')),
            ('/d/e/f', 'seespotrun'),
        ]

        self.assertRaises(exception.Base64Exception, self.compute.run_instance,
                self.context, self.instance, injected_files=injected_files)

    def test_reschedule(self):
        # test that rescheduling is done with original encoded files
        expected = [
            ('/a/b/c', base64.b64encode('foobarbaz')),
            ('/d/e/f', base64.b64encode('seespotrun')),
        ]

        def _roe(context, instance, exc_info, requested_networks,
                 admin_password, injected_files, is_first_time, request_spec,
                 filter_properties, bdms=None, legacy_bdm_in_spec=False):
            self.assertEqual(expected, injected_files)
            return True

        def spawn_explode(context, instance, image_meta, injected_files,
                admin_password, nw_info, block_device_info):
            # force reschedule logic to execute
            raise test.TestingException(_("spawn error"))

        self.stubs.Set(self.compute.driver, 'spawn', spawn_explode)
        self.stubs.Set(self.compute, '_reschedule_or_error', _roe)

        self.compute.run_instance(self.context, self.instance,
                                  injected_files=expected)


class CheckConfigDriveTestCase(test.TestCase):
    # NOTE(sirp): `TestCase` is far too heavyweight for this test, this should
    # probably derive from a `test.FastTestCase` that omits DB and env
    # handling
    def setUp(self):
        super(CheckConfigDriveTestCase, self).setUp()
        self.compute_api = compute.API()

    def _assertCheck(self, expected, config_drive):
        self.assertEqual(expected,
                         self.compute_api._check_config_drive(config_drive))

    def _assertInvalid(self, config_drive):
        self.assertRaises(exception.ConfigDriveInvalidValue,
                          self.compute_api._check_config_drive,
                          config_drive)

    def test_config_drive_false_values(self):
        self._assertCheck('', None)
        self._assertCheck('', '')
        self._assertCheck('', 'False')
        self._assertCheck('', 'f')
        self._assertCheck('', '0')

    def test_config_drive_true_values(self):
        self._assertCheck(True, 'True')
        self._assertCheck(True, 't')
        self._assertCheck(True, '1')

    def test_config_drive_bogus_values_raise(self):
        self._assertInvalid('asd')
        self._assertInvalid(uuidutils.generate_uuid())


class CheckRequestedImageTestCase(test.TestCase):
    def setUp(self):
        super(CheckRequestedImageTestCase, self).setUp()
        self.compute_api = compute.API()
        self.context = context.RequestContext(
                'fake_user_id', 'fake_project_id')

        self.instance_type = flavors.get_default_flavor()
        self.instance_type['memory_mb'] = 64
        self.instance_type['root_gb'] = 1

    def test_no_image_specified(self):
        self.compute_api._check_requested_image(self.context, None, {},
                self.instance_type)

    def test_image_status_must_be_active(self):
        image = dict(id='123', status='foo')

        self.assertRaises(exception.ImageNotActive,
                self.compute_api._check_requested_image, self.context,
                image['id'], image, self.instance_type)

        image['status'] = 'active'
        self.compute_api._check_requested_image(self.context, image['id'],
                image, self.instance_type)

    def test_image_min_ram_check(self):
        image = dict(id='123', status='active', min_ram='65')

        self.assertRaises(exception.InstanceTypeMemoryTooSmall,
                self.compute_api._check_requested_image, self.context,
                image['id'], image, self.instance_type)

        image['min_ram'] = '64'
        self.compute_api._check_requested_image(self.context, image['id'],
                image, self.instance_type)

    def test_image_min_disk_check(self):
        image = dict(id='123', status='active', min_disk='2')

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
                self.compute_api._check_requested_image, self.context,
                image['id'], image, self.instance_type)

        image['min_disk'] = '1'
        self.compute_api._check_requested_image(self.context, image['id'],
                image, self.instance_type)

    def test_image_too_large(self):
        image = dict(id='123', status='active', size='1073741825')

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
                self.compute_api._check_requested_image, self.context,
                image['id'], image, self.instance_type)

        image['size'] = '1073741824'
        self.compute_api._check_requested_image(self.context, image['id'],
                image, self.instance_type)

    def test_root_gb_zero_disables_size_check(self):
        self.instance_type['root_gb'] = 0
        image = dict(id='123', status='active', size='1073741825')

        self.compute_api._check_requested_image(self.context, image['id'],
                image, self.instance_type)

    def test_root_gb_zero_disables_min_disk(self):
        self.instance_type['root_gb'] = 0
        image = dict(id='123', status='active', min_disk='2')

        self.compute_api._check_requested_image(self.context, image['id'],
                image, self.instance_type)


class ComputeAPIClassNameTestCase(test.TestCase):
    def setUp(self):
        super(ComputeAPIClassNameTestCase, self).setUp()

    def test_default_compute_api_class_name(self):
        result = compute._get_compute_api_class_name()
        self.assertEqual('nova.compute.api.API', result)

    def test_cell_compute_api_class_name(self):
        self.flags(enable=True, group='cells')
        self.flags(cell_type='api', group='cells')
        result = compute._get_compute_api_class_name()
        self.assertEqual('nova.compute.cells_api.ComputeCellsAPI', result)
        self.flags(cell_type='compute', group='cells')
        result = compute._get_compute_api_class_name()
        self.assertEqual('nova.compute.api.API', result)

    def test_cell_compute_api_class_name_deprecated(self):
        self.flags(enable=True, group='cells')
        self.flags(cell_type='', group='cells')
        api_cls_name = 'nova.compute.cells_api.ComputeCellsAPI'
        self.flags(compute_api_class=api_cls_name)
        result = compute._get_compute_api_class_name()
        self.assertEqual('nova.compute.cells_api.ComputeCellsAPI', result)
        api_cls_name = 'nova.compute.api.API'
        self.flags(compute_api_class=api_cls_name)
        result = compute._get_compute_api_class_name()
        self.assertEqual('nova.compute.api.API', result)

    def test_illegal_cell_compute_api_class_name(self):
        self.flags(enable=True, group='cells')
        self.flags(cell_type='fake_cell_type', group='cells')
        self.assertRaises(exception.InvalidInput,
                          compute._get_compute_api_class_name)


class ComputeManagerV3TestCase(test.TestCase):
    def test_v3_passes_through_to_v2(self):
        self.count = 0

        def _fake(*args, **kwargs):
            self.count += 1

        manager = compute_manager.ComputeManager()
        proxy = compute_manager.ComputeV3Proxy(manager)
        for m in proxy.supported_methods:
            self.stubs.Set(manager, m, _fake)
            getattr(proxy, m)()
        self.assertEqual(self.count, len(proxy.supported_methods))

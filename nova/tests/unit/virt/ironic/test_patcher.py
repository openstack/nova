# Copyright 2014 Red Hat, Inc.
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

from oslo.config import cfg

from nova import context as nova_context
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.ironic import utils as ironic_utils
from nova.virt.ironic import patcher

CONF = cfg.CONF


class IronicDriverFieldsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IronicDriverFieldsTestCase, self).setUp()
        self.image_meta = ironic_utils.get_test_image_meta()
        self.flavor = ironic_utils.get_test_flavor()
        self.ctx = nova_context.get_admin_context()
        self.instance = fake_instance.fake_instance_obj(self.ctx)
        # Generic expected patches
        self._expected_deploy_patch = [{'path': '/instance_info/image_source',
                                        'value': self.image_meta['id'],
                                        'op': 'add'},
                                       {'path': '/instance_info/root_gb',
                                        'value': str(self.instance['root_gb']),
                                        'op': 'add'},
                                       {'path': '/instance_info/swap_mb',
                                        'value': str(self.flavor['swap']),
                                        'op': 'add'}]
        self._expected_cleanup_patch = []

    def test_create_generic(self):
        node = ironic_utils.get_test_node(driver='fake')
        patcher_obj = patcher.create(node)
        self.assertIsInstance(patcher_obj, patcher.GenericDriverFields)

    def test_create_pxe(self):
        node = ironic_utils.get_test_node(driver='pxe_fake')
        patcher_obj = patcher.create(node)
        self.assertIsInstance(patcher_obj, patcher.PXEDriverFields)

    def test_generic_get_deploy_patch(self):
        node = ironic_utils.get_test_node(driver='fake')
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertEqual(sorted(self._expected_deploy_patch), sorted(patch))

    def test_generic_get_deploy_patch_ephemeral(self):
        CONF.set_override('default_ephemeral_format', 'testfmt')
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   ephemeral_gb=10)
        patch = patcher.create(node).get_deploy_patch(
                instance, self.image_meta, self.flavor)
        expected = [{'path': '/instance_info/ephemeral_gb',
                     'value': str(instance.ephemeral_gb),
                     'op': 'add'},
                    {'path': '/instance_info/ephemeral_format',
                     'value': 'testfmt',
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        self.assertEqual(sorted(expected), sorted(patch))

    def test_generic_get_deploy_patch_preserve_ephemeral(self):
        node = ironic_utils.get_test_node(driver='fake')
        for preserve in [True, False]:
            patch = patcher.create(node).get_deploy_patch(
                    self.instance, self.image_meta, self.flavor,
                    preserve_ephemeral=preserve)
            expected = [{'path': '/instance_info/preserve_ephemeral',
                         'value': str(preserve), 'op': 'add', }]
            expected += self._expected_deploy_patch
            self.assertEqual(sorted(expected), sorted(patch))

    def test_generic_get_cleanup_patch(self):
        node = ironic_utils.get_test_node(driver='fake')
        patch = patcher.create(node).get_cleanup_patch(self.instance, None,
                                                       self.flavor)
        self.assertEqual(self._expected_cleanup_patch, patch)

    def test_pxe_get_deploy_patch(self):
        node = ironic_utils.get_test_node(driver='pxe_fake')
        extra_specs = self.flavor['extra_specs']
        expected = [{'path': '/driver_info/pxe_deploy_kernel',
                     'value': extra_specs['baremetal:deploy_kernel_id'],
                     'op': 'add'},
                    {'path': '/driver_info/pxe_deploy_ramdisk',
                     'value': extra_specs['baremetal:deploy_ramdisk_id'],
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertEqual(sorted(expected), sorted(patch))

    def test_pxe_get_deploy_patch_no_flavor_kernel_ramdisk_ids(self):
        flavor = ironic_utils.get_test_flavor(extra_specs={})
        node = ironic_utils.get_test_node(driver='pxe_fake')
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, flavor)
        # If there's no extra_specs patch should be exactly like a
        # generic patch
        self.assertEqual(sorted(self._expected_deploy_patch), sorted(patch))

    def test_pxe_get_cleanup_patch(self):
        driver_info = {'pxe_deploy_kernel': 'fake-kernel-id',
                       'pxe_deploy_ramdisk': 'fake-ramdisk-id'}
        node = ironic_utils.get_test_node(driver='pxe_fake',
                                          driver_info=driver_info)
        patch = patcher.create(node).get_cleanup_patch(self.instance, None,
                                                       self.flavor)
        expected = [{'path': '/driver_info/pxe_deploy_kernel',
                     'op': 'remove'},
                    {'path': '/driver_info/pxe_deploy_ramdisk',
                     'op': 'remove'}]
        self.assertEqual(sorted(expected), sorted(patch))

    def test_pxe_get_cleanup_patch_no_flavor_kernel_ramdisk_ids(self):
        self.flavor = ironic_utils.get_test_flavor(extra_specs={})
        node = ironic_utils.get_test_node(driver='pxe_fake')
        patch = patcher.create(node).get_cleanup_patch(self.instance, None,
                                                       self.flavor)
        # If there's no extra_specs patch should be exactly like a
        # generic patch
        self.assertEqual(self._expected_cleanup_patch, patch)

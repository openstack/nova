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

import operator

from oslo_config import cfg

from nova import context as nova_context
from nova import objects
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
        self.instance.flavor = self.flavor
        self.node = ironic_utils.get_test_node(driver='fake')
        # Generic expected patches
        self._expected_deploy_patch = [
            {'path': '/instance_info/image_source',
             'value': self.image_meta.id,
             'op': 'add'},
            {'path': '/instance_info/root_gb',
             'value': str(self.instance.flavor.root_gb),
             'op': 'add'},
            {'path': '/instance_info/swap_mb',
             'value': str(self.flavor['swap']),
             'op': 'add'},
            {'path': '/instance_info/display_name',
             'value': self.instance['display_name'],
             'op': 'add'},
            {'path': '/instance_info/vcpus',
             'value': str(self.instance.flavor.vcpus),
             'op': 'add'},
            {'path': '/instance_info/memory_mb',
             'value': str(self.instance.flavor.memory_mb),
             'op': 'add'},
            {'path': '/instance_info/local_gb',
             'value': str(self.node.properties.get('local_gb', 0)),
             'op': 'add'},
            {'path': '/instance_info/nova_host_id',
             'value': u'fake-host',
             'op': 'add'},
        ]

    def assertPatchEqual(self, expected, observed):
        self.assertEqual(
            sorted(expected, key=operator.itemgetter('path', 'value')),
            sorted(observed, key=operator.itemgetter('path', 'value'))
        )

    def test_create_generic(self):
        node = ironic_utils.get_test_node(driver='pxe_fake')
        patcher_obj = patcher.create(node)
        self.assertIsInstance(patcher_obj, patcher.GenericDriverFields)

    def test_generic_get_deploy_patch(self):
        node = ironic_utils.get_test_node(driver='fake')
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(self._expected_deploy_patch, patch)

    def test_generic_get_deploy_patch_capabilities(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.flavor['extra_specs']['capabilities:boot_mode'] = 'bios'
        expected = [{'path': '/instance_info/capabilities',
                     'value': '{"boot_mode": "bios"}',
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_capabilities_op(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.flavor['extra_specs']['capabilities:boot_mode'] = '<in> bios'
        expected = [{'path': '/instance_info/capabilities',
                     'value': '{"boot_mode": "<in> bios"}',
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_capabilities_nested_key(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.flavor['extra_specs']['capabilities:key1:key2'] = '<in> bios'
        expected = [{'path': '/instance_info/capabilities',
                     'value': '{"key1:key2": "<in> bios"}',
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_traits(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.flavor['extra_specs']['trait:CUSTOM_FOO'] = 'required'
        expected = [{'path': '/instance_info/traits',
                     'value': ["CUSTOM_FOO"],
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_traits_granular(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.flavor['extra_specs']['trait1:CUSTOM_FOO'] = 'required'
        expected = [{'path': '/instance_info/traits',
                     'value': ["CUSTOM_FOO"],
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_traits_ignores_not_required(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.flavor['extra_specs']['trait:CUSTOM_FOO'] = 'invalid'
        expected = self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_image_traits_required(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.image_meta.properties = objects.ImageMetaProps(
            traits_required=['CUSTOM_TRUSTED'])
        expected = [{'path': '/instance_info/traits',
                     'value': ["CUSTOM_TRUSTED"],
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
            self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_image_flavor_traits_required(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.flavor['extra_specs']['trait:CUSTOM_FOO'] = 'required'
        self.image_meta.properties = objects.ImageMetaProps(
            traits_required=['CUSTOM_TRUSTED'])
        expected = [{'path': '/instance_info/traits',
                     'value': ["CUSTOM_FOO", "CUSTOM_TRUSTED"],
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
            self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_image_flavor_traits_none(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.image_meta.properties = objects.ImageMetaProps()
        expected = self._expected_deploy_patch
        patch = patcher.create(node).get_deploy_patch(
            self.instance, self.image_meta, self.flavor)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_boot_from_volume_image_traits_required(
            self):
        node = ironic_utils.get_test_node(driver='fake')
        self.image_meta.properties = objects.ImageMetaProps(
            traits_required=['CUSTOM_TRUSTED'])
        expected_deploy_patch_volume = [patch for patch in
                                        self._expected_deploy_patch
                                        if patch['path'] !=
                                        '/instance_info/image_source']
        expected = [{'path': '/instance_info/traits',
                     'value': ["CUSTOM_TRUSTED"],
                     'op': 'add'}]
        expected += expected_deploy_patch_volume
        patch = patcher.create(node).get_deploy_patch(
            self.instance, self.image_meta, self.flavor,
            boot_from_volume=True)
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_ephemeral(self):
        CONF.set_override('default_ephemeral_format', 'testfmt')
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(
            self.ctx,
            flavor=objects.Flavor(root_gb=1, vcpus=1,
                                  memory_mb=1, ephemeral_gb=10))
        patch = patcher.create(node).get_deploy_patch(
                instance, self.image_meta, self.flavor)
        expected = [{'path': '/instance_info/ephemeral_gb',
                     'value': str(instance.flavor.ephemeral_gb),
                     'op': 'add'},
                    {'path': '/instance_info/ephemeral_format',
                     'value': 'testfmt',
                     'op': 'add'}]
        expected += self._expected_deploy_patch
        self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_preserve_ephemeral(self):
        node = ironic_utils.get_test_node(driver='fake')
        for preserve in [True, False]:
            patch = patcher.create(node).get_deploy_patch(
                    self.instance, self.image_meta, self.flavor,
                    preserve_ephemeral=preserve)
            expected = [{'path': '/instance_info/preserve_ephemeral',
                         'value': str(preserve), 'op': 'add', }]
            expected += self._expected_deploy_patch
            self.assertPatchEqual(expected, patch)

    def test_generic_get_deploy_patch_boot_from_volume(self):
        node = ironic_utils.get_test_node(driver='fake')
        expected = [patch for patch in self._expected_deploy_patch
                    if patch['path'] != '/instance_info/image_source']
        patch = patcher.create(node).get_deploy_patch(
                self.instance, self.image_meta, self.flavor,
                boot_from_volume=True)
        self.assertPatchEqual(expected, patch)

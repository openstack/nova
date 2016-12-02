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

from oslo_utils import versionutils

from nova import objects
from nova.objects import fields as obj_fields
from nova.scheduler.filters import image_props_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestImagePropsFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestImagePropsFilter, self).setUp()
        self.filt_cls = image_props_filter.ImagePropertiesFilter()

    def test_image_properties_filter_passes_same_inst_props_and_version(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.X86_64,
                img_hv_type=obj_fields.HVType.KVM,
                hw_vm_mode=obj_fields.VMMode.HVM,
                img_hv_requested_version='>=6.0,<6.2'))
        spec_obj = objects.RequestSpec(image=img_props)
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_fails_different_inst_props(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.ARMV7,
                img_hv_type=obj_fields.HVType.QEMU,
                hw_vm_mode=obj_fields.VMMode.HVM))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_fails_different_hyper_version(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.X86_64,
                img_hv_type=obj_fields.HVType.KVM,
                hw_vm_mode=obj_fields.VMMode.HVM,
                img_hv_requested_version='>=6.2'))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'enabled': True,
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_passes_partial_inst_props(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.X86_64,
                hw_vm_mode=obj_fields.VMMode.HVM))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_fails_partial_inst_props(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.X86_64,
                hw_vm_mode=obj_fields.VMMode.HVM))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.XEN,
                obj_fields.VMMode.XEN)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_passes_without_inst_props(self):
        spec_obj = objects.RequestSpec(image=None)
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_fails_without_host_props(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.X86_64,
                img_hv_type=obj_fields.HVType.KVM,
                hw_vm_mode=obj_fields.VMMode.HVM))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'enabled': True,
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_passes_without_hyper_version(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.X86_64,
                img_hv_type=obj_fields.HVType.KVM,
                hw_vm_mode=obj_fields.VMMode.HVM,
                img_hv_requested_version='>=6.0'))
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'enabled': True,
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)]}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_fails_with_unsupported_hyper_ver(self):
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture=obj_fields.Architecture.X86_64,
                img_hv_type=obj_fields.HVType.KVM,
                hw_vm_mode=obj_fields.VMMode.HVM,
                img_hv_requested_version='>=6.0'))
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'enabled': True,
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': 5000}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_pv_mode_compat(self):
        # if an old image has 'pv' for a vm_mode it should be treated as xen
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_vm_mode='pv'))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.XEN,
                obj_fields.VMMode.XEN)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_hvm_mode_compat(self):
        # if an old image has 'hv' for a vm_mode it should be treated as xen
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_vm_mode='hv'))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_xen_arch_compat(self):
        # if an old image has 'x86_32' for arch it should be treated as i686
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_architecture='x86_32'))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.I686,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_xen_hv_type_compat(self):
        # if an old image has 'xapi' for hv_type it should be treated as xen
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                img_hv_type='xapi'))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.I686,
                obj_fields.HVType.XEN,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_image_properties_filter_baremetal_vmmode_compat(self):
        # if an old image has 'baremetal' for vmmode it should be
        # treated as hvm
        img_props = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_vm_mode='baremetal'))
        hypervisor_version = versionutils.convert_version_to_int('6.0.0')
        spec_obj = objects.RequestSpec(image=img_props)
        capabilities = {
            'supported_instances': [(
                obj_fields.Architecture.I686,
                obj_fields.HVType.BAREMETAL,
                obj_fields.VMMode.HVM)],
            'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

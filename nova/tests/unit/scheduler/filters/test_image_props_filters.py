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

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import vm_mode
from nova.scheduler.filters import image_props_filter
from nova import test
from nova.tests.unit.scheduler import fakes
from nova import utils


class TestImagePropsFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestImagePropsFilter, self).setUp()
        self.filt_cls = image_props_filter.ImagePropertiesFilter()

    def test_image_properties_filter_passes_same_inst_props_and_version(self):
        img_props = {'properties': {'_architecture': arch.X86_64,
                                    'hypervisor_type': hv_type.KVM,
                                    'vm_mode': vm_mode.HVM,
                                    'hypervisor_version_requires': '>=6.0,<6.2'
        }}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_different_inst_props(self):
        img_props = {'properties': {'architecture': arch.ARMV7,
                                    'hypervisor_type': hv_type.QEMU,
                                    'vm_mode': vm_mode.HVM}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_different_hyper_version(self):
        img_props = {'properties': {'architecture': arch.X86_64,
                                    'hypervisor_type': hv_type.KVM,
                                    'vm_mode': vm_mode.HVM,
                                    'hypervisor_version_requires': '>=6.2'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'enabled': True,
                        'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_passes_partial_inst_props(self):
        img_props = {'properties': {'architecture': arch.X86_64,
                                    'vm_mode': vm_mode.HVM}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_partial_inst_props(self):
        img_props = {'properties': {'architecture': arch.X86_64,
                                    'vm_mode': vm_mode.HVM}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.X86_64, hv_type.XEN, vm_mode.XEN)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_passes_without_inst_props(self):
        filter_properties = {'request_spec': {}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_without_host_props(self):
        img_props = {'properties': {'architecture': arch.X86_64,
                                    'hypervisor_type': hv_type.KVM,
                                    'vm_mode': vm_mode.HVM}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'enabled': True,
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_passes_without_hyper_version(self):
        img_props = {'properties': {'architecture': arch.X86_64,
                                    'hypervisor_type': hv_type.KVM,
                                    'vm_mode': vm_mode.HVM,
                                    'hypervisor_version_requires': '>=6.0'}}
        filter_properties = {'request_spec': {'image': img_props}}
        capabilities = {'enabled': True,
                        'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)]}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_with_unsupported_hyper_ver(self):
        img_props = {'properties': {'architecture': arch.X86_64,
                                    'hypervisor_type': hv_type.KVM,
                                    'vm_mode': vm_mode.HVM,
                                    'hypervisor_version_requires': '>=6.0'}}
        filter_properties = {'request_spec': {'image': img_props}}
        capabilities = {'enabled': True,
                        'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': 5000}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_pv_mode_compat(self):
        # if an old image has 'pv' for a vm_mode it should be treated as xen
        img_props = {'properties': {'vm_mode': 'pv'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.X86_64, hv_type.XEN, vm_mode.XEN)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_hvm_mode_compat(self):
        # if an old image has 'hv' for a vm_mode it should be treated as xen
        img_props = {'properties': {'vm_mode': 'hv'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.X86_64, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_xen_arch_compat(self):
        # if an old image has 'x86_32' for arch it should be treated as i686
        img_props = {'properties': {'architecture': 'x86_32'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.I686, hv_type.KVM, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_xen_hv_type_compat(self):
        # if an old image has 'xapi' for hv_type it should be treated as xen
        img_props = {'properties': {'hypervisor_type': 'xapi'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.I686, hv_type.XEN, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_baremetal_vmmode_compat(self):
        # if an old image has 'baremetal' for vmmode it should be
        # treated as hvm
        img_props = {'properties': {'vm_mode': 'baremetal'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances':
                        [(arch.I686, hv_type.BAREMETAL, vm_mode.HVM)],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

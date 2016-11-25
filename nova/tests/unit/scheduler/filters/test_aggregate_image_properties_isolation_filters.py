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

from nova import objects
from nova.scheduler.filters import aggregate_image_properties_isolation as aipi
from nova import test
from nova.tests.unit.scheduler import fakes


@mock.patch('nova.scheduler.filters.utils.aggregate_metadata_get_by_host')
class TestAggImagePropsIsolationFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestAggImagePropsIsolationFilter, self).setUp()
        self.filt_cls = aipi.AggregateImagePropertiesIsolation()

    def test_aggregate_image_properties_isolation_passes(self, agg_mock):
        agg_mock.return_value = {'hw_vm_mode': set(['hvm'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_passes_comma(self, agg_mock):
        agg_mock.return_value = {'hw_vm_mode': set(['hvm', 'xen'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_bad_comma(self,
            agg_mock):
        agg_mock.return_value = {'os_distro': set(['windows', 'linux'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                os_distro='windows,')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_multi_props_passes(self,
            agg_mock):
        agg_mock.return_value = {'hw_vm_mode': set(['hvm']),
                                 'hw_cpu_cores': set(['2'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm', hw_cpu_cores=2)))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_with_meta_passes(self,
            agg_mock):
        agg_mock.return_value = {'hw_vm_mode': set(['hvm'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps()))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_imgprops_passes(self,
            agg_mock):
        agg_mock.return_value = {}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_not_match_fails(self,
            agg_mock):
        agg_mock.return_value = {'hw_vm_mode': set(['hvm'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='xen')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_not_match2_fails(self,
            agg_mock):
        agg_mock.return_value = {'hw_vm_mode': set(['hvm']),
                                 'hw_cpu_cores': set(['1'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm', hw_cpu_cores=2)))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_namespace(self,
            agg_mock):
        self.flags(aggregate_image_properties_isolation_namespace='hw',
                   group='filter_scheduler')
        self.flags(aggregate_image_properties_isolation_separator='_',
                   group='filter_scheduler')
        agg_mock.return_value = {'hw_vm_mode': set(['hvm']),
                                 'img_owner_id': set(['foo'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm', img_owner_id='wrong')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_iso_props_with_custom_meta(self,
            agg_mock):
        agg_mock.return_value = {'os': set(['linux'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                os_type='linux')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_iso_props_with_matching_meta_pass(self,
            agg_mock):
        agg_mock.return_value = {'os_type': set(['linux'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                os_type='linux')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_iso_props_with_matching_meta_fail(
            self, agg_mock):
        agg_mock.return_value = {'os_type': set(['windows'])}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                os_type='linux')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

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
        agg_mock.return_value = {'hw_vm_mode': 'hvm'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_passes_comma(self, agg_mock):
        agg_mock.return_value = {'hw_vm_mode': 'hvm,xen'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_multi_props_passes(self,
            agg_mock):
        agg_mock.return_value = {'hw_vm_mode': 'hvm', 'hw_cpu_cores': '2'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm', hw_cpu_cores=2)))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_with_meta_passes(self,
            agg_mock):
        agg_mock.return_value = {'hw_vm_mode': 'hvm'}
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
        agg_mock.return_value = {'hw_vm_mode': 'hvm'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='xen')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_not_match2_fails(self,
            agg_mock):
        agg_mock.return_value = {'hw_vm_mode': 'hvm', 'hw_cpu_cores': '1'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm', hw_cpu_cores=2)))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_aggregate_image_properties_isolation_props_namespace(self,
            agg_mock):
        self.flags(aggregate_image_properties_isolation_namespace="hw")
        self.flags(aggregate_image_properties_isolation_separator="_")
        agg_mock.return_value = {'hw_vm_mode': 'hvm', 'img_owner_id': 'foo'}
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            image=objects.ImageMeta(properties=objects.ImageMetaProps(
                hw_vm_mode='hvm', img_owner_id='wrong')))
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

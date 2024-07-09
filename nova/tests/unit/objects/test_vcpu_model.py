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

from nova import objects
from nova.objects import fields as obj_fields
from nova.tests.unit.objects import test_objects

fake_cpu_model_feature = {
    'policy': obj_fields.CPUFeaturePolicy.REQUIRE,
    'name': 'sse2',
}

fake_cpu_model_feature_obj = objects.VirtCPUFeature(
    **fake_cpu_model_feature)

fake_vcpumodel_dict = {
    'arch': obj_fields.Architecture.I686,
    'vendor': 'fake-vendor',
    'match': obj_fields.CPUMatch.EXACT,
    'topology': objects.VirtCPUTopology(sockets=1, cores=1, threads=1),
    'features': [fake_cpu_model_feature_obj],
    'mode': obj_fields.CPUMode.HOST_MODEL,
    'model': 'fake-model',
}
fake_vcpumodel = objects.VirtCPUModel(**fake_vcpumodel_dict)


class _TestVirtCPUFeatureObj(object):
    def test_policy_limitation(self):
        obj = objects.VirtCPUFeature()
        self.assertRaises(ValueError, setattr, obj, 'policy', 'foo')


class TestVirtCPUFeatureObj(test_objects._LocalTest,
                        _TestVirtCPUFeatureObj):
    pass


class TestRemoteVirtCPUFeatureObj(test_objects._LocalTest,
                                     _TestVirtCPUFeatureObj):
    pass


class _TestVirtCPUModel(object):
    def test_create(self):
        model = objects.VirtCPUModel(**fake_vcpumodel_dict)
        self.assertEqual(fake_vcpumodel_dict['model'], model.model)
        self.assertEqual(fake_vcpumodel_dict['topology'].sockets,
                         model.topology.sockets)
        feature = model.features[0]
        self.assertEqual(fake_cpu_model_feature['policy'],
                         feature.policy)

    def test_defaults(self):
        model = objects.VirtCPUModel()
        self.assertIsNone(model.mode)
        self.assertIsNone(model.model)
        self.assertIsNone(model.vendor)
        self.assertIsNone(model.arch)
        self.assertIsNone(model.match)
        self.assertEqual([], model.features)
        self.assertIsNone(model.topology)

    def test_arch_field(self):
        model = objects.VirtCPUModel(**fake_vcpumodel_dict)
        self.assertRaises(ValueError, setattr, model, 'arch', 'foo')

    def test_serialize(self):
        model_in = objects.VirtCPUModel(**fake_vcpumodel_dict)
        model_out = objects.VirtCPUModel.from_json(model_in.to_json())

        self.assertEqual(model_in.mode, model_out.mode)
        self.assertEqual(model_in.model, model_out.model)
        self.assertEqual(model_in.vendor, model_out.vendor)
        self.assertEqual(model_in.arch, model_out.arch)
        self.assertEqual(model_in.match, model_out.match)
        self.assertEqual(model_in.features[0].policy,
                         model_out.features[0].policy)
        self.assertEqual(model_in.features[0].name, model_out.features[0].name)
        self.assertEqual(model_in.topology.sockets, model_out.topology.sockets)
        self.assertEqual(model_in.topology.cores, model_out.topology.cores)
        self.assertEqual(model_in.topology.threads, model_out.topology.threads)


class TestVirtCPUModel(test_objects._LocalTest,
                        _TestVirtCPUModel):
    pass


class TestRemoteVirtCPUModel(test_objects._LocalTest,
                              _TestVirtCPUModel):
    pass

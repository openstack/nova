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
from nova.compute import cpumodel
from nova import objects
from nova.tests.unit.objects import test_objects

fake_cpu_model_feature = {
    'policy': cpumodel.POLICY_REQUIRE,
    'name': 'sse2',
}

fake_cpu_model_feature_obj = objects.VirtCPUFeature(
    **fake_cpu_model_feature)

fake_vcpumodel_dict = {
    'arch': arch.I686,
    'vendor': 'fake-vendor',
    'match': cpumodel.MATCH_EXACT,
    'topology': objects.VirtCPUTopology(sockets=1, cores=1, threads=1),
    'features': [fake_cpu_model_feature_obj],
    'mode': cpumodel.MODE_HOST_MODEL,
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
        modelin = objects.VirtCPUModel(**fake_vcpumodel_dict)
        modelout = objects.VirtCPUModel.from_json(modelin.to_json())

        self.assertEqual(modelin.mode, modelout.mode)
        self.assertEqual(modelin.model, modelout.model)
        self.assertEqual(modelin.vendor, modelout.vendor)
        self.assertEqual(modelin.arch, modelout.arch)
        self.assertEqual(modelin.match, modelout.match)
        self.assertEqual(modelin.features[0].policy,
                         modelout.features[0].policy)
        self.assertEqual(modelin.features[0].name, modelout.features[0].name)
        self.assertEqual(modelin.topology.sockets, modelout.topology.sockets)
        self.assertEqual(modelin.topology.cores, modelout.topology.cores)
        self.assertEqual(modelin.topology.threads, modelout.topology.threads)


class TestVirtCPUModel(test_objects._LocalTest,
                        _TestVirtCPUModel):
    pass


class TestRemoteVirtCPUModel(test_objects._LocalTest,
                              _TestVirtCPUModel):
    pass

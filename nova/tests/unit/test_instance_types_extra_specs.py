# Copyright 2011 University of Southern California
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
"""
Unit Tests for instance types extra specs code
"""

from nova import context
from nova import objects
from nova.objects import fields
from nova import test


class InstanceTypeExtraSpecsTestCase(test.TestCase):

    def setUp(self):
        super(InstanceTypeExtraSpecsTestCase, self).setUp()
        self.context = context.get_admin_context()
        flavor = objects.Flavor(context=self.context,
                                name="cg1.4xlarge",
                                memory_mb=22000,
                                vcpus=8,
                                root_gb=1690,
                                ephemeral_gb=2000,
                                flavorid=105)
        self.specs = dict(cpu_arch=fields.Architecture.X86_64,
                          cpu_model="Nehalem",
                          xpu_arch="fermi",
                          xpus="2",
                          xpu_model="Tesla 2050")
        flavor.extra_specs = self.specs
        flavor.create()
        self.flavor = flavor
        self.instance_type_id = flavor.id
        self.flavorid = flavor.flavorid

    def tearDown(self):
        # Remove the instance type from the database
        self.flavor.destroy()
        super(InstanceTypeExtraSpecsTestCase, self).tearDown()

    def test_instance_type_specs_get(self):
        flavor = objects.Flavor.get_by_flavor_id(self.context,
                                                 self.flavorid)
        self.assertEqual(self.specs, flavor.extra_specs)

    def test_flavor_extra_specs_delete(self):
        del self.specs["xpu_model"]
        del self.flavor.extra_specs['xpu_model']
        self.flavor.save()
        flavor = objects.Flavor.get_by_flavor_id(self.context,
                                                 self.flavorid)
        self.assertEqual(self.specs, flavor.extra_specs)

    def test_instance_type_extra_specs_update(self):
        self.specs["cpu_model"] = "Sandy Bridge"
        self.flavor.extra_specs["cpu_model"] = "Sandy Bridge"
        self.flavor.save()
        flavor = objects.Flavor.get_by_flavor_id(self.context,
                                                 self.flavorid)
        self.assertEqual(self.specs, flavor.extra_specs)

    def test_instance_type_extra_specs_create(self):
        net_attrs = {
            "net_arch": "ethernet",
            "net_mbps": "10000"
        }
        self.specs.update(net_attrs)
        self.flavor.extra_specs.update(net_attrs)
        self.flavor.save()
        flavor = objects.Flavor.get_by_flavor_id(self.context,
                                                 self.flavorid)
        self.assertEqual(self.specs, flavor.extra_specs)

    def test_instance_type_get_with_extra_specs(self):
        flavor = objects.Flavor.get_by_id(self.context, 5)
        self.assertEqual(flavor.extra_specs, {})

    def test_instance_type_get_by_name_with_extra_specs(self):
        flavor = objects.Flavor.get_by_name(self.context,
                                            "cg1.4xlarge")
        self.assertEqual(flavor.extra_specs, self.specs)
        flavor = objects.Flavor.get_by_name(self.context,
                                            "m1.small")
        self.assertEqual(flavor.extra_specs, {})

    def test_instance_type_get_by_flavor_id_with_extra_specs(self):
        flavor = objects.Flavor.get_by_flavor_id(self.context, 105)
        self.assertEqual(flavor.extra_specs, self.specs)
        flavor = objects.Flavor.get_by_flavor_id(self.context, 2)
        self.assertEqual(flavor.extra_specs, {})

    def test_instance_type_get_all(self):
        flavors = objects.FlavorList.get_all(self.context)

        name2specs = {flavor.name: flavor.extra_specs
                      for flavor in flavors}

        self.assertEqual(name2specs['cg1.4xlarge'], self.specs)
        self.assertEqual(name2specs['m1.small'], {})

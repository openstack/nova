# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from nova import db
from nova import test


class InstanceTypeExtraSpecsTestCase(test.TestCase):

    def setUp(self):
        super(InstanceTypeExtraSpecsTestCase, self).setUp()
        self.context = context.get_admin_context()
        values = dict(name="cg1.4xlarge",
                      memory_mb=22000,
                      vcpus=8,
                      local_gb=1690,
                      flavorid=105)
        specs = dict(cpu_arch="x86_64",
                        cpu_model="Nehalem",
                        xpu_arch="fermi",
                        xpus=2,
                        xpu_model="Tesla 2050")
        values['extra_specs'] = specs
        ref = db.instance_type_create(self.context,
                                          values)
        self.instance_type_id = ref.id

    def tearDown(self):
        # Remove the instance type from the database
        db.instance_type_purge(self.context, "cg1.4xlarge")
        super(InstanceTypeExtraSpecsTestCase, self).tearDown()

    def test_instance_type_specs_get(self):
        expected_specs = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050")
        actual_specs = db.instance_type_extra_specs_get(
                              self.context,
                              self.instance_type_id)
        self.assertEquals(expected_specs, actual_specs)

    def test_instance_type_extra_specs_delete(self):
        expected_specs = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2")
        db.instance_type_extra_specs_delete(self.context,
                                      self.instance_type_id,
                                      "xpu_model")
        actual_specs = db.instance_type_extra_specs_get(
                              self.context,
                              self.instance_type_id)
        self.assertEquals(expected_specs, actual_specs)

    def test_instance_type_extra_specs_update(self):
        expected_specs = dict(cpu_arch="x86_64",
                                 cpu_model="Sandy Bridge",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050")
        db.instance_type_extra_specs_update_or_create(
                              self.context,
                              self.instance_type_id,
                              dict(cpu_model="Sandy Bridge"))
        actual_specs = db.instance_type_extra_specs_get(
                              self.context,
                              self.instance_type_id)
        self.assertEquals(expected_specs, actual_specs)

    def test_instance_type_extra_specs_create(self):
        expected_specs = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050",
                                 net_arch="ethernet",
                                 net_mbps="10000")
        db.instance_type_extra_specs_update_or_create(
                              self.context,
                              self.instance_type_id,
                              dict(net_arch="ethernet",
                                   net_mbps=10000))
        actual_specs = db.instance_type_extra_specs_get(
                              self.context,
                              self.instance_type_id)
        self.assertEquals(expected_specs, actual_specs)

    def test_instance_type_get_with_extra_specs(self):
        instance_type = db.instance_type_get(
                            self.context,
                            self.instance_type_id)
        self.assertEquals(instance_type['extra_specs'],
                          dict(cpu_arch="x86_64",
                               cpu_model="Nehalem",
                               xpu_arch="fermi",
                               xpus="2",
                               xpu_model="Tesla 2050"))
        instance_type = db.instance_type_get(
                            self.context,
                            5)
        self.assertEquals(instance_type['extra_specs'], {})

    def test_instance_type_get_by_name_with_extra_specs(self):
        instance_type = db.instance_type_get_by_name(
                            self.context,
                            "cg1.4xlarge")
        self.assertEquals(instance_type['extra_specs'],
                          dict(cpu_arch="x86_64",
                               cpu_model="Nehalem",
                               xpu_arch="fermi",
                               xpus="2",
                               xpu_model="Tesla 2050"))

        instance_type = db.instance_type_get_by_name(
                            self.context,
                            "m1.small")
        self.assertEquals(instance_type['extra_specs'], {})

    def test_instance_type_get_by_flavor_id_with_extra_specs(self):
        instance_type = db.instance_type_get_by_flavor_id(
                            self.context,
                            105)
        self.assertEquals(instance_type['extra_specs'],
                          dict(cpu_arch="x86_64",
                               cpu_model="Nehalem",
                               xpu_arch="fermi",
                               xpus="2",
                               xpu_model="Tesla 2050"))

        instance_type = db.instance_type_get_by_flavor_id(
                            self.context,
                            2)
        self.assertEquals(instance_type['extra_specs'], {})

    def test_instance_type_get_all(self):
        specs = dict(cpu_arch="x86_64",
                        cpu_model="Nehalem",
                        xpu_arch="fermi",
                        xpus='2',
                        xpu_model="Tesla 2050")

        types = db.instance_type_get_all(self.context)

        name2specs = {}
        for instance_type in types:
            name = instance_type['name']
            name2specs[name] = instance_type['extra_specs']

        self.assertEquals(name2specs['cg1.4xlarge'], specs)
        self.assertEquals(name2specs['m1.small'], {})

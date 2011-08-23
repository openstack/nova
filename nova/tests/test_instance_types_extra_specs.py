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
from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy import models


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
        ref = db.api.instance_type_create(self.context,
                                          values)
        self.instance_type_id = ref.id

    def tearDown(self):
        # Remove the instance type from the database
        db.api.instance_type_purge(context.get_admin_context(), "cg1.4xlarge")
        super(InstanceTypeExtraSpecsTestCase, self).tearDown()

    def test_instance_type_specs_get(self):
        expected_specs = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050")
        actual_specs = db.api.instance_type_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(expected_specs, actual_specs)

    def test_instance_type_extra_specs_delete(self):
        expected_specs = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2")
        db.api.instance_type_extra_specs_delete(context.get_admin_context(),
                                      self.instance_type_id,
                                      "xpu_model")
        actual_specs = db.api.instance_type_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(expected_specs, actual_specs)

    def test_instance_type_extra_specs_update(self):
        expected_specs = dict(cpu_arch="x86_64",
                                 cpu_model="Sandy Bridge",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050")
        db.api.instance_type_extra_specs_update_or_create(
                              context.get_admin_context(),
                              self.instance_type_id,
                              dict(cpu_model="Sandy Bridge"))
        actual_specs = db.api.instance_type_extra_specs_get(
                              context.get_admin_context(),
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
        db.api.instance_type_extra_specs_update_or_create(
                              context.get_admin_context(),
                              self.instance_type_id,
                              dict(net_arch="ethernet",
                                   net_mbps=10000))
        actual_specs = db.api.instance_type_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(expected_specs, actual_specs)

    def test_instance_type_get_with_extra_specs(self):
        instance_type = db.api.instance_type_get(
                            context.get_admin_context(),
                            self.instance_type_id)
        self.assertEquals(instance_type['extra_specs'],
                          dict(cpu_arch="x86_64",
                               cpu_model="Nehalem",
                               xpu_arch="fermi",
                               xpus="2",
                               xpu_model="Tesla 2050"))
        instance_type = db.api.instance_type_get(
                            context.get_admin_context(),
                            5)
        self.assertEquals(instance_type['extra_specs'], {})

    def test_instance_type_get_by_name_with_extra_specs(self):
        instance_type = db.api.instance_type_get_by_name(
                            context.get_admin_context(),
                            "cg1.4xlarge")
        self.assertEquals(instance_type['extra_specs'],
                          dict(cpu_arch="x86_64",
                               cpu_model="Nehalem",
                               xpu_arch="fermi",
                               xpus="2",
                               xpu_model="Tesla 2050"))

        instance_type = db.api.instance_type_get_by_name(
                            context.get_admin_context(),
                            "m1.small")
        self.assertEquals(instance_type['extra_specs'], {})

    def test_instance_type_get_by_flavor_id_with_extra_specs(self):
        instance_type = db.api.instance_type_get_by_flavor_id(
                            context.get_admin_context(),
                            105)
        self.assertEquals(instance_type['extra_specs'],
                          dict(cpu_arch="x86_64",
                               cpu_model="Nehalem",
                               xpu_arch="fermi",
                               xpus="2",
                               xpu_model="Tesla 2050"))

        instance_type = db.api.instance_type_get_by_flavor_id(
                            context.get_admin_context(),
                            2)
        self.assertEquals(instance_type['extra_specs'], {})

    def test_instance_type_get_all(self):
        specs = dict(cpu_arch="x86_64",
                        cpu_model="Nehalem",
                        xpu_arch="fermi",
                        xpus='2',
                        xpu_model="Tesla 2050")

        types = db.api.instance_type_get_all(context.get_admin_context())

        self.assertEquals(types['cg1.4xlarge']['extra_specs'], specs)
        self.assertEquals(types['m1.small']['extra_specs'], {})

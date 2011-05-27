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
Unit Tests for instance types metadata code
"""

from nova import context
from nova import db
from nova import test
from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy import models


class InstanceTypeMetadataTestCase(test.TestCase):
    
    def setUp(self):
        super(InstanceTypeMetadataTestCase, self).setUp()
        self.context = context.get_admin_context()
        values = dict(name="cg1.4xlarge",
                      memory_mb=22000,
                      vcpus=8,
                      local_gb=1690,
                      flavorid=105)
        metadata = dict(cpu_arch="x86_64",
                        cpu_model="Nehalem",
                        xpu_arch="fermi",
                        xpus=2,
                        xpu_model="Tesla 2050")
        values['meta'] = metadata
        ref = db.api.instance_type_create(self.context,
                                          values)
        self.instance_type_id = ref.id
        
    def tearDown(self):
        # Remove the instance type from the database
        db.api.instance_type_purge(context.get_admin_context(), "cg1.4xlarge")
        super(InstanceTypeMetadataTestCase, self).tearDown()
        
    def test_instance_type_metadata_get(self):
        expected_metadata = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050")
        actual_metadata = db.api.instance_type_metadata_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(expected_metadata, actual_metadata)
        
    def test_instance_type_metadata_delete(self):
        expected_metadata = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2")
        db.api.instance_type_metadata_delete(context.get_admin_context(), 
                                      self.instance_type_id,
                                      "xpu_model")
        actual_metadata = db.api.instance_type_metadata_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(expected_metadata, actual_metadata)
        
    def test_instance_type_metadata_update(self):
        expected_metadata = dict(cpu_arch="x86_64",
                                 cpu_model="Sandy Bridge",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050")
        db.api.instance_type_metadata_update_or_create(
                              context.get_admin_context(),
                              self.instance_type_id,
                              dict(cpu_model="Sandy Bridge"))
        actual_metadata = db.api.instance_type_metadata_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(expected_metadata, actual_metadata)
    
    def test_instance_type_metadata_create(self):
        expected_metadata = dict(cpu_arch="x86_64",
                                 cpu_model="Nehalem",
                                 xpu_arch="fermi",
                                 xpus="2",
                                 xpu_model="Tesla 2050", 
                                 net_arch="ethernet",
                                 net_mbps="10000")
        db.api.instance_type_metadata_update_or_create(
                              context.get_admin_context(),
                              self.instance_type_id,
                              dict(net_arch="ethernet",
                                   net_mbps=10000))
        actual_metadata = db.api.instance_type_metadata_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(expected_metadata, actual_metadata)

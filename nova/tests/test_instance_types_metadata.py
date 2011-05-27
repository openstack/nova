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

import nova.db.api

from nova import context
from nova import test
from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy import models


class InstanceTypeMetadataTestCase(test.TestCase):
    
    def setUp(self):
        super(InstanceTypeMetadataTestCase, self).setUp()
        values = dict(name="cg1.4xlarge",
                      memory_mb=22000,
                      vcpus=8,
                      local_gb=1690,
                      flavorid=105)
        metadata = dict(cpu_arch="x86_64",
                        cpu_model="Nehalem",
                        xpu_arch="fermi",
                        xpus=2,
                        xpu_model="Tesla 2050", 
                        net_arch="ethernet",
                        net_mbps=10000)
        
        metadata_refs = []
        for k,v in metadata.iteritems():
            metadata_ref = models.InstanceTypeMetadata()
            metadata_ref['key'] = k
            metadata_ref['value'] = v
            metadata_refs.append(metadata_ref)
        values['meta'] = metadata_refs

        instance_type_ref = models.InstanceTypes()
        instance_type_ref.update(values)
        
            
        session = get_session()
        with session.begin():
            instance_type_ref.save(session=session)
        self.instance_type_id = instance_type_ref.id
        
    def test_instance_type_metadata_get(self):
        self.assertEquals( \
         nova.db.api.instance_type_metadata_get(context.get_admin_context(),
                                                self.instance_type_id),
                          {'foo' : 'bar'})

         
            
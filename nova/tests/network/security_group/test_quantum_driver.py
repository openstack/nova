# Copyright 2013 OpenStack Foundation
# All Rights Reserved
#
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
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import mox
from quantumclient.v2_0 import client

from nova import context
from nova.network import quantumv2
from nova.network.security_group import quantum_driver
from nova import test


class TestQuantumDriver(test.TestCase):
    def setUp(self):
        super(TestQuantumDriver, self).setUp()
        self.mox.StubOutWithMock(quantumv2, 'get_client')
        self.moxed_client = self.mox.CreateMock(client.Client)
        quantumv2.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
            self.moxed_client)
        self.context = context.RequestContext('userid', 'my_tenantid')
        setattr(self.context,
                'auth_token',
                'bff4a5a6b9eb4ea2a6efec6eefb77936')

    def test_list_with_project(self):
        project_id = '0af70a4d22cf4652824ddc1f2435dd85'
        security_groups_list = {'security_groups': []}
        self.moxed_client.list_security_groups(tenant_id=project_id).AndReturn(
            security_groups_list)
        self.mox.ReplayAll()

        sg_api = quantum_driver.SecurityGroupAPI()
        sg_api.list(self.context, project=project_id)

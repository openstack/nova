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

from neutronclient.common import exceptions as n_exc
from neutronclient.v2_0 import client

from nova.api.openstack.compute.contrib import security_groups
from nova import context
from nova import exception
from nova.network import neutronv2
from nova.network.security_group import neutron_driver
from nova import test


class TestNeutronDriver(test.TestCase):
    def setUp(self):
        super(TestNeutronDriver, self).setUp()
        self.mox.StubOutWithMock(neutronv2, 'get_client')
        self.moxed_client = self.mox.CreateMock(client.Client)
        neutronv2.get_client(mox.IgnoreArg()).MultipleTimes().AndReturn(
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

        sg_api = neutron_driver.SecurityGroupAPI()
        sg_api.list(self.context, project=project_id)

    def test_create_security_group_exceed_quota(self):
        name = 'test-security-group'
        description = 'test-security-group'
        body = {'security_group': {'name': name,
                                   'description': description}}
        message = "Quota exceeded for resources: ['security_group']"
        self.moxed_client.create_security_group(
            body).AndRaise(n_exc.NeutronClientException(status_code=409,
                                                        message=message))
        self.mox.ReplayAll()
        sg_api = security_groups.NativeNeutronSecurityGroupAPI()
        self.assertRaises(exception.SecurityGroupLimitExceeded,
                          sg_api.create_security_group, self.context, name,
                          description)

    def test_create_security_group_rules_exceed_quota(self):
        vals = {'protocol': 'tcp', 'cidr': '0.0.0.0/0',
                'parent_group_id': '7ae75663-277e-4a0e-8f87-56ea4e70cb47',
                'group_id': None, 'from_port': 1025, 'to_port': 1025}
        body = {'security_group_rules': [{'remote_group_id': None,
                'direction': 'ingress', 'protocol': 'tcp', 'ethertype': 'IPv4',
                'port_range_max': 1025, 'port_range_min': 1025,
                'security_group_id': '7ae75663-277e-4a0e-8f87-56ea4e70cb47',
                'remote_ip_prefix': '0.0.0.0/0'}]}
        name = 'test-security-group'
        message = "Quota exceeded for resources: ['security_group_rule']"
        self.moxed_client.create_security_group_rule(
            body).AndRaise(n_exc.NeutronClientException(status_code=409,
                                                        message=message))
        self.mox.ReplayAll()
        sg_api = security_groups.NativeNeutronSecurityGroupAPI()
        self.assertRaises(exception.SecurityGroupLimitExceeded,
                          sg_api.add_rules, self.context, None, name, [vals])

# Copyright (c) 2012 OpenStack, LLC.
# All Rights Reserved.
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

from nova.compute import api
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests import fake_hosts


class HostApiTestCase(test.TestCase):
    """
    Tests 'host' subset of the compute api
    """

    def setUp(self):
        super(HostApiTestCase, self).setUp()
        self.compute_rpcapi = api.compute_rpcapi
        self.api = api.HostAPI()

    def test_bad_host_set_enabled(self):
        """
        Tests that actions on single hosts that don't exist blow up without
        having to reach the host via rpc.  Should raise HostNotFound if you
        try to update a host that is not in the DB
        """
        self.assertRaises(exception.HostNotFound, self.api.set_host_enabled,
                context.get_admin_context(), "bogus_host_name", False)

    def test_list_compute_hosts(self):
        ctx = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_get_all')
        db.service_get_all(ctx, False).AndReturn(fake_hosts.SERVICES_LIST)
        self.mox.ReplayAll()
        compute_hosts = self.api.list_hosts(ctx, service="compute")
        self.mox.VerifyAll()
        expected = [host for host in fake_hosts.HOST_LIST
                    if host["service"] == "compute"]
        self.assertEqual(expected, compute_hosts)

    def test_describe_host(self):
        """
        Makes sure that describe_host returns the correct information
        given our fake input.
        """
        ctx = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'service_get_all_compute_by_host')
        host_name = 'host_c1'
        db.service_get_all_compute_by_host(ctx, host_name).AndReturn(
            [{'host': 'fake_host',
              'compute_node': [
                {'vcpus': 4,
                 'vcpus_used': 1,
                 'memory_mb': 8192,
                 'memory_mb_used': 2048,
                 'local_gb': 1024,
                 'local_gb_used': 648}
              ]
            }])
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        db.instance_get_all_by_host(ctx, 'fake_host').AndReturn(
            [{'project_id': 42,
              'vcpus': 1,
              'memory_mb': 2048,
              'root_gb': 648,
              'ephemeral_gb': 0,
            }])
        self.mox.ReplayAll()
        result = self.api.describe_host(ctx, host_name)
        self.assertEqual(result,
            [{'resource': {'cpu': 4,
                           'disk_gb': 1024,
                           'host': 'host_c1',
                           'memory_mb': 8192,
                           'project': '(total)'}},
             {'resource': {'cpu': 1,
                           'disk_gb': 648,
                           'host': 'host_c1',
                           'memory_mb': 2048,
                           'project': '(used_now)'}},
             {'resource': {'cpu': 1,
                           'disk_gb': 648,
                           'host': 'host_c1',
                           'memory_mb': 2048,
                           'project': '(used_max)'}},
             {'resource': {'cpu': 1,
                           'disk_gb': 648,
                           'host': 'host_c1',
                           'memory_mb': 2048,
                           'project': 42}}]
        )
        self.mox.VerifyAll()

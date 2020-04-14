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

import mock
from oslo_utils.fixture import uuidsentinel as uuids
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute import server_topology
from nova import exception
from nova import objects
from nova.objects import instance_numa as numa
from nova import test
from nova.tests.unit.api.openstack import fakes


class ServerTopologyTestV278(test.NoDBTestCase):
    mock_method = 'get_by_instance_uuid'
    api_version = '2.78'

    def setUp(self):
        super(ServerTopologyTestV278, self).setUp()
        self.uuid = uuids.instance
        self.req = fakes.HTTPRequest.blank(
            '/v2/%s/servers/%s/topology' % (fakes.FAKE_PROJECT_ID, self.uuid),
            version=self.api_version,
            use_admin_context=True)
        self.controller = server_topology.ServerTopologyController()
        self.context = self.req.environ['nova.context']

    def _fake_numa(self, cpu_pinning=None):
        ce0 = numa.InstanceNUMACell(node=0, memory=1024, pagesize=4, id=0,
            cpu_topology=None,
            cpu_pinning=cpu_pinning,
            cpuset=set([0, 1]))

        return numa.InstanceNUMATopology(cells=[ce0])

    @mock.patch.object(common, 'get_instance',
               side_effect=exc.HTTPNotFound('Fake'))
    def test_get_topology_with_invalid_instance(self, mock_get):
        excep = self.assertRaises(exc.HTTPNotFound,
            self.controller.index,
            self.req,
            self.uuid)
        self.assertEqual("Fake", str(excep))

    @mock.patch.object(common, 'get_instance')
    def test_get_topology_with_no_topology(self, fake_get):
        expect = {'nodes': [], 'pagesize_kb': None}
        inst = objects.instance.Instance(uuid=self.uuid, host='123',
            project_id=self.context.project_id)
        inst.numa_topology = None
        fake_get.return_value = inst

        output = self.controller.index(self.req, self.uuid)
        self.assertEqual(expect, output)

    @mock.patch.object(common, 'get_instance')
    def test_get_topology_cpu_pinning_with_none(self, fake_get):
        expect = {'nodes': [
                    {'memory_mb': 1024,
                     'siblings': [],
                     'vcpu_set': set([0, 1]),
                     'host_node': 0,
                     'cpu_pinning':{}}],
                     'pagesize_kb': 4}

        inst = objects.instance.Instance(uuid=self.uuid, host='123',
            project_id=self.context.project_id)
        inst.numa_topology = self._fake_numa(cpu_pinning=None)
        fake_get.return_value = inst

        output = self.controller.index(self.req, self.uuid)
        self.assertEqual(expect, output)

        inst.numa_topology = self._fake_numa(cpu_pinning={})
        fake_get.return_value = inst
        output = self.controller.index(self.req, self.uuid)
        self.assertEqual(expect, output)

    def test_hit_topology_before278(self):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/servers/%s/topology' % (fakes.FAKE_PROJECT_ID, self.uuid),
            version='2.77')
        excep = self.assertRaises(exception.VersionNotFoundForAPIMethod,
                         self.controller.index,
                         req,
                         self.uuid)
        self.assertEqual(400, excep.code)

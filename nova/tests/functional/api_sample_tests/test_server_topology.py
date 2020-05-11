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

from nova.objects import instance_numa as numa
from nova.objects import virt_cpu_topology as cpu_topo
from nova.tests.functional.api_sample_tests import test_servers


def fake_get_numa():
    cpu_info = {'sockets': 2, 'cores': 1, 'threads': 2}
    cpu_topology = cpu_topo.VirtCPUTopology.from_dict(cpu_info)
    cell_0 = numa.InstanceNUMACell(node=0, memory=1024, pagesize=4, id=0,
           cpu_topology=cpu_topology,
           cpu_pinning={0: 0, 1: 5},
           cpuset=set(),
           pcpuset=set([0, 1]))

    cell_1 = numa.InstanceNUMACell(node=1, memory=2048, pagesize=4, id=1,
           cpu_topology=cpu_topology,
           cpu_pinning={2: 1, 3: 8},
           cpuset=set(),
           pcpuset=set([2, 3]))

    return numa.InstanceNUMATopology(cells=[cell_0, cell_1])


class ServerTopologySamplesJson(test_servers.ServersSampleBase):
    microversion = '2.78'
    scenarios = [('v2_78', {'api_major_version': 'v2.1'})]
    sample_dir = "os-server-topology"

    def setUp(self):
        super(ServerTopologySamplesJson, self).setUp()

        def _load_numa(self, *args, **argv):
            self.numa_topology = fake_get_numa()

        self.stub_out('nova.objects.instance.Instance._load_numa_topology',
                      _load_numa)


class ServerTopologySamplesJsonTestV278_Admin(ServerTopologySamplesJson):
    ADMIN_API = True

    def test_get_servers_topology_admin(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s/topology' % uuid)
        self._verify_response(
            'servers-topology-resp', {}, response, 200)


class ServerTopologySamplesJsonTestV278(ServerTopologySamplesJson):
    ADMIN_API = False

    def test_get_servers_topology_user(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s/topology' % uuid)
        self._verify_response(
            'servers-topology-resp-user', {}, response, 200)

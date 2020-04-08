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

from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova.compute import api as compute
from nova.policies import server_topology as st_policies


class ServerTopologyController(wsgi.Controller):

    def __init__(self, *args, **kwargs):
        super(ServerTopologyController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.Controller.api_version("2.78")
    @wsgi.expected_errors(404)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, server_id,
                                       expected_attrs=['numa_topology',
                                       'vcpu_model'])

        context.can(st_policies.BASE_POLICY_NAME % 'index',
                    target={'project_id': instance.project_id})

        host_policy = (st_policies.BASE_POLICY_NAME % 'host:index')
        show_host_info = context.can(host_policy, fatal=False)

        return self._get_numa_topology(context, instance, show_host_info)

    def _get_numa_topology(self, context, instance, show_host_info):

        if instance.numa_topology is None:
            return {
                'nodes': [],
                'pagesize_kb': None
            }

        topo = {}
        cells = []
        pagesize_kb = None

        for cell_ in instance.numa_topology.cells:
            cell = {}
            cell['vcpu_set'] = cell_.cpuset
            cell['siblings'] = cell_.siblings
            cell['memory_mb'] = cell_.memory

            if show_host_info:
                cell['host_node'] = cell_.id
                if cell_.cpu_pinning is None:
                    cell['cpu_pinning'] = {}
                else:
                    cell['cpu_pinning'] = cell_.cpu_pinning

            if cell_.pagesize:
                pagesize_kb = cell_.pagesize

            cells.append(cell)

        topo['nodes'] = cells
        topo['pagesize_kb'] = pagesize_kb

        return topo

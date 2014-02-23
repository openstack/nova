# Copyright (c) 2012 OpenStack Foundation
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

"""The hypervisors admin extension."""

import webob.exc

from nova.api.openstack import extensions
from nova import compute
from nova import exception
from nova.openstack.common.gettextutils import _


ALIAS = "os-hypervisors"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class HypervisorsController(object):
    """The Hypervisors API controller for the OpenStack API."""

    def __init__(self):
        self.host_api = compute.HostAPI()
        super(HypervisorsController, self).__init__()

    def _view_hypervisor(self, hypervisor, detail, servers=None, **kwargs):
        hyp_dict = {
            'id': hypervisor['id'],
            'hypervisor_hostname': hypervisor['hypervisor_hostname'],
            }

        if detail and not servers:
            for field in ('vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
                          'memory_mb_used', 'local_gb_used',
                          'hypervisor_type', 'hypervisor_version',
                          'free_ram_mb', 'free_disk_gb', 'current_workload',
                          'running_vms', 'cpu_info', 'disk_available_least',
                          'host_ip'):
                hyp_dict[field] = hypervisor[field]

            hyp_dict['service'] = {
                'id': hypervisor['service_id'],
                'host': hypervisor['service']['host'],
                }

        if servers != None:
            hyp_dict['servers'] = [dict(name=serv['name'], id=serv['uuid'])
                                   for serv in servers]

        # Add any additional info
        if kwargs:
            hyp_dict.update(kwargs)

        return hyp_dict

    @extensions.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        authorize(context)
        compute_nodes = self.host_api.compute_node_get_all(context)
        req.cache_db_compute_nodes(compute_nodes)
        return dict(hypervisors=[self._view_hypervisor(hyp, False)
                                 for hyp in compute_nodes])

    @extensions.expected_errors(())
    def detail(self, req):
        context = req.environ['nova.context']
        authorize(context)
        compute_nodes = self.host_api.compute_node_get_all(context)
        req.cache_db_compute_nodes(compute_nodes)
        return dict(hypervisors=[self._view_hypervisor(hyp, True)
                                 for hyp in compute_nodes])

    @extensions.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        try:
            hyp = self.host_api.compute_node_get(context, id)
            req.cache_db_compute_node(hyp)
        except (ValueError, exception.ComputeHostNotFound):
            msg = _("Hypervisor with ID '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        return dict(hypervisor=self._view_hypervisor(hyp, True))

    @extensions.expected_errors((404, 501))
    def uptime(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        try:
            hyp = self.host_api.compute_node_get(context, id)
            req.cache_db_compute_node(hyp)
        except (ValueError, exception.ComputeHostNotFound):
            msg = _("Hypervisor with ID '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        # Get the uptime
        try:
            host = hyp['service']['host']
            uptime = self.host_api.get_host_uptime(context, host)
        except NotImplementedError:
            msg = _("Virt driver does not implement uptime function.")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        return dict(hypervisor=self._view_hypervisor(hyp, False,
                                                     uptime=uptime))

    @extensions.expected_errors(400)
    def search(self, req):
        context = req.environ['nova.context']
        authorize(context)
        query = req.GET.get('query', None)
        if not query:
            msg = _("Need parameter 'query' to specify "
                    "which hypervisor to filter on")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        hypervisors = self.host_api.compute_node_search_by_hypervisor(
            context, query)
        return dict(hypervisors=[self._view_hypervisor(hyp, False)
                                 for hyp in hypervisors])

    @extensions.expected_errors(404)
    def servers(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        try:
            compute_node = self.host_api.compute_node_get(context, id)
        except (ValueError, exception.ComputeHostNotFound):
            msg = _("Hypervisor with ID '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        instances = self.host_api.instance_get_all_by_host(context,
            compute_node['service']['host'])
        return dict(hypervisor=self._view_hypervisor(compute_node, False,
            instances))

    @extensions.expected_errors(())
    def statistics(self, req):
        context = req.environ['nova.context']
        authorize(context)
        stats = self.host_api.compute_node_statistics(context)
        return dict(hypervisor_statistics=stats)


class Hypervisors(extensions.V3APIExtensionBase):
    """Admin-only hypervisor administration."""

    name = "Hypervisors"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = [extensions.ResourceExtension(ALIAS,
                HypervisorsController(),
                collection_actions={'detail': 'GET',
                                    'search': 'GET',
                                    'statistics': 'GET'},
                member_actions={'uptime': 'GET',
                                'servers': 'GET'})]

        return resources

    def get_controller_extensions(self):
        return []

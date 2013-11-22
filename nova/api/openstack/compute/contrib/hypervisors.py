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
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova.openstack.common.gettextutils import _


authorize = extensions.extension_authorizer('compute', 'hypervisors')


def make_hypervisor(elem, detail):
    elem.set('hypervisor_hostname')
    elem.set('id')
    if detail:
        elem.set('vcpus')
        elem.set('memory_mb')
        elem.set('local_gb')
        elem.set('vcpus_used')
        elem.set('memory_mb_used')
        elem.set('local_gb_used')
        elem.set('hypervisor_type')
        elem.set('hypervisor_version')
        elem.set('free_ram_mb')
        elem.set('free_disk_gb')
        elem.set('current_workload')
        elem.set('running_vms')
        elem.set('cpu_info')
        elem.set('disk_available_least')

        service = xmlutil.SubTemplateElement(elem, 'service',
                                             selector='service')
        service.set('id')
        service.set('host')


class HypervisorIndexTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisors')
        elem = xmlutil.SubTemplateElement(root, 'hypervisor',
                                          selector='hypervisors')
        make_hypervisor(elem, False)
        return xmlutil.MasterTemplate(root, 1)


class HypervisorDetailTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisors')
        elem = xmlutil.SubTemplateElement(root, 'hypervisor',
                                          selector='hypervisors')
        make_hypervisor(elem, True)
        return xmlutil.MasterTemplate(root, 1)


class HypervisorTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisor', selector='hypervisor')
        make_hypervisor(root, True)
        return xmlutil.MasterTemplate(root, 1)


class HypervisorUptimeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisor', selector='hypervisor')
        make_hypervisor(root, False)
        root.set('uptime')
        return xmlutil.MasterTemplate(root, 1)


class HypervisorServersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisors')
        elem = xmlutil.SubTemplateElement(root, 'hypervisor',
                                          selector='hypervisors')
        make_hypervisor(elem, False)

        servers = xmlutil.SubTemplateElement(elem, 'servers')
        server = xmlutil.SubTemplateElement(servers, 'server',
                                            selector='servers')
        server.set('name')
        server.set('uuid')

        return xmlutil.MasterTemplate(root, 1)


class HypervisorStatisticsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisor_statistics',
                                       selector='hypervisor_statistics')
        root.set('count')
        root.set('vcpus')
        root.set('memory_mb')
        root.set('local_gb')
        root.set('vcpus_used')
        root.set('memory_mb_used')
        root.set('local_gb_used')
        root.set('free_ram_mb')
        root.set('free_disk_gb')
        root.set('current_workload')
        root.set('running_vms')
        root.set('disk_available_least')

        return xmlutil.MasterTemplate(root, 1)


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
                          'running_vms', 'cpu_info', 'disk_available_least'):
                hyp_dict[field] = hypervisor[field]

            hyp_dict['service'] = {
                'id': hypervisor['service_id'],
                'host': hypervisor['service']['host'],
                }

        if servers:
            hyp_dict['servers'] = [dict(name=serv['name'], uuid=serv['uuid'])
                                   for serv in servers]

        # Add any additional info
        if kwargs:
            hyp_dict.update(kwargs)

        return hyp_dict

    @wsgi.serializers(xml=HypervisorIndexTemplate)
    def index(self, req):
        context = req.environ['nova.context']
        authorize(context)
        compute_nodes = self.host_api.compute_node_get_all(context)
        req.cache_db_compute_nodes(compute_nodes)
        return dict(hypervisors=[self._view_hypervisor(hyp, False)
                                 for hyp in compute_nodes])

    @wsgi.serializers(xml=HypervisorDetailTemplate)
    def detail(self, req):
        context = req.environ['nova.context']
        authorize(context)
        compute_nodes = self.host_api.compute_node_get_all(context)
        req.cache_db_compute_nodes(compute_nodes)
        return dict(hypervisors=[self._view_hypervisor(hyp, True)
                                 for hyp in compute_nodes])

    @wsgi.serializers(xml=HypervisorTemplate)
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

    @wsgi.serializers(xml=HypervisorUptimeTemplate)
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

    @wsgi.serializers(xml=HypervisorIndexTemplate)
    def search(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        hypervisors = self.host_api.compute_node_search_by_hypervisor(
                context, id)
        if hypervisors:
            return dict(hypervisors=[self._view_hypervisor(hyp, False)
                                     for hyp in hypervisors])
        else:
            msg = _("No hypervisor matching '%s' could be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

    @wsgi.serializers(xml=HypervisorServersTemplate)
    def servers(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        compute_nodes = self.host_api.compute_node_search_by_hypervisor(
                context, id)
        if not compute_nodes:
            msg = _("No hypervisor matching '%s' could be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        hypervisors = []
        for compute_node in compute_nodes:
            instances = self.host_api.instance_get_all_by_host(context,
                    compute_node['service']['host'])
            hyp = self._view_hypervisor(compute_node, False, instances)
            hypervisors.append(hyp)
        return dict(hypervisors=hypervisors)

    @wsgi.serializers(xml=HypervisorStatisticsTemplate)
    def statistics(self, req):
        context = req.environ['nova.context']
        authorize(context)
        stats = self.host_api.compute_node_statistics(context)
        return dict(hypervisor_statistics=stats)


class Hypervisors(extensions.ExtensionDescriptor):
    """Admin-only hypervisor administration."""

    name = "Hypervisors"
    alias = "os-hypervisors"
    namespace = "http://docs.openstack.org/compute/ext/hypervisors/api/v1.1"
    updated = "2012-06-21T00:00:00+00:00"

    def get_resources(self):
        resources = [extensions.ResourceExtension('os-hypervisors',
                HypervisorsController(),
                collection_actions={'detail': 'GET',
                                    'statistics': 'GET'},
                member_actions={'uptime': 'GET',
                                'search': 'GET',
                                'servers': 'GET'})]

        return resources

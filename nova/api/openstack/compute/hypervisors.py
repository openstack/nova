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

from oslo_log import log as logging
from oslo_serialization import jsonutils
import webob.exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.views import hypervisors as hyper_view
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _
from nova.policies import hypervisors as hv_policies
from nova import servicegroup

LOG = logging.getLogger(__name__)

ALIAS = "os-hypervisors"


class HypervisorsController(wsgi.Controller):
    """The Hypervisors API controller for the OpenStack API."""

    _view_builder_class = hyper_view.ViewBuilder

    def __init__(self):
        self.host_api = compute.HostAPI()
        self.servicegroup_api = servicegroup.API()
        super(HypervisorsController, self).__init__()

    def _view_hypervisor(self, hypervisor, service, detail, req, servers=None,
                         **kwargs):
        alive = self.servicegroup_api.service_is_up(service)
        hyp_dict = {
            'id': hypervisor.id,
            'hypervisor_hostname': hypervisor.hypervisor_hostname,
            'state': 'up' if alive else 'down',
            'status': ('disabled' if service.disabled
                       else 'enabled'),
            }

        if detail and not servers:
            for field in ('vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
                          'memory_mb_used', 'local_gb_used',
                          'hypervisor_type', 'hypervisor_version',
                          'free_ram_mb', 'free_disk_gb', 'current_workload',
                          'running_vms', 'disk_available_least', 'host_ip'):
                hyp_dict[field] = getattr(hypervisor, field)

            hyp_dict['service'] = {
                'id': service.id,
                'host': hypervisor.host,
                'disabled_reason': service.disabled_reason,
                }

            if api_version_request.is_supported(req, min_version='2.28'):
                if hypervisor.cpu_info:
                    hyp_dict['cpu_info'] = jsonutils.loads(hypervisor.cpu_info)
                else:
                    hyp_dict['cpu_info'] = {}
            else:
                hyp_dict['cpu_info'] = hypervisor.cpu_info

        if servers:
            hyp_dict['servers'] = [dict(name=serv['name'], uuid=serv['uuid'])
                                   for serv in servers]

        # Add any additional info
        if kwargs:
            hyp_dict.update(kwargs)

        return hyp_dict

    @wsgi.Controller.api_version("2.33")  # noqa
    @extensions.expected_errors((400))
    def index(self, req):
        limit, marker = common.get_limit_and_marker(req)
        return self._index(req, limit=limit, marker=marker, links=True)

    @wsgi.Controller.api_version("2.1", "2.32")  # noqa
    @extensions.expected_errors(())
    def index(self, req):
        return self._index(req)

    def _index(self, req, limit=None, marker=None, links=False):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME)

        try:
            compute_nodes = self.host_api.compute_node_get_all(
                context, limit=limit, marker=marker)
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise webob.exc.HTTPBadRequest(explanation=msg)
        req.cache_db_compute_nodes(compute_nodes)
        hypervisors_list = []
        for hyp in compute_nodes:
            try:
                service = self.host_api.service_get_by_compute_host(
                    context, hyp.host)
                hypervisors_list.append(
                    self._view_hypervisor(
                        hyp, service, False, req))
            except (exception.ComputeHostNotFound,
                    exception.HostMappingNotFound):
                # The compute service could be deleted which doesn't delete
                # the compute node record, that has to be manually removed
                # from the database so we just ignore it when listing nodes.
                LOG.debug('Unable to find service for compute node %s. The '
                          'service may be deleted and compute nodes need to '
                          'be manually cleaned up.', hyp.host)

        hypervisors_dict = dict(hypervisors=hypervisors_list)
        if links:
            hypervisors_links = self._view_builder.get_links(req,
                                                             hypervisors_list)
            if hypervisors_links:
                hypervisors_dict['hypervisors_links'] = hypervisors_links
        return hypervisors_dict

    @wsgi.Controller.api_version("2.33")  # noqa
    @extensions.expected_errors((400))
    def detail(self, req):
        limit, marker = common.get_limit_and_marker(req)
        return self._detail(req, limit=limit, marker=marker, links=True)

    @wsgi.Controller.api_version("2.1", "2.32")  # noqa
    @extensions.expected_errors(())
    def detail(self, req):
        return self._detail(req)

    def _detail(self, req, limit=None, marker=None, links=False):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME)

        try:
            compute_nodes = self.host_api.compute_node_get_all(
                context, limit=limit, marker=marker)
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise webob.exc.HTTPBadRequest(explanation=msg)
        req.cache_db_compute_nodes(compute_nodes)
        hypervisors_list = []
        for hyp in compute_nodes:
            try:
                service = self.host_api.service_get_by_compute_host(
                    context, hyp.host)
                hypervisors_list.append(
                    self._view_hypervisor(
                        hyp, service, True, req))
            except (exception.ComputeHostNotFound,
                    exception.HostMappingNotFound):
                # The compute service could be deleted which doesn't delete
                # the compute node record, that has to be manually removed
                # from the database so we just ignore it when listing nodes.
                LOG.debug('Unable to find service for compute node %s. The '
                          'service may be deleted and compute nodes need to '
                          'be manually cleaned up.', hyp.host)
        hypervisors_dict = dict(hypervisors=hypervisors_list)
        if links:
            hypervisors_links = self._view_builder.get_links(
                req, hypervisors_list, detail=True)
            if hypervisors_links:
                hypervisors_dict['hypervisors_links'] = hypervisors_links
        return hypervisors_dict

    @extensions.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME)
        try:
            hyp = self.host_api.compute_node_get(context, id)
            req.cache_db_compute_node(hyp)
            service = self.host_api.service_get_by_compute_host(
                context, hyp.host)
        except (ValueError, exception.ComputeHostNotFound,
                exception.HostMappingNotFound):
            msg = _("Hypervisor with ID '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        return dict(hypervisor=self._view_hypervisor(
            hyp, service, True, req))

    @extensions.expected_errors((400, 404, 501))
    def uptime(self, req, id):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME)
        try:
            hyp = self.host_api.compute_node_get(context, id)
            req.cache_db_compute_node(hyp)
        except (ValueError, exception.ComputeHostNotFound):
            msg = _("Hypervisor with ID '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        # Get the uptime
        try:
            host = hyp.host
            uptime = self.host_api.get_host_uptime(context, host)
            service = self.host_api.service_get_by_compute_host(context, host)
        except NotImplementedError:
            common.raise_feature_not_supported()
        except exception.ComputeServiceUnavailable as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.HostMappingNotFound:
            # NOTE(danms): This mirrors the compute_node_get() behavior
            # where the node is missing, resulting in NotFound instead of
            # BadRequest if we fail on the map lookup.
            msg = _("Hypervisor with ID '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        return dict(hypervisor=self._view_hypervisor(hyp, service, False, req,
                                                     uptime=uptime))

    @extensions.expected_errors(404)
    def search(self, req, id):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME)
        hypervisors = self.host_api.compute_node_search_by_hypervisor(
                context, id)
        if hypervisors:
            try:
                return dict(hypervisors=[
                    self._view_hypervisor(
                        hyp,
                        self.host_api.service_get_by_compute_host(context,
                                                                  hyp.host),
                        False, req)
                    for hyp in hypervisors])
            except exception.HostMappingNotFound:
                msg = _("No hypervisor matching '%s' could be found.") % id
                raise webob.exc.HTTPNotFound(explanation=msg)
        else:
            msg = _("No hypervisor matching '%s' could be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

    @extensions.expected_errors(404)
    def servers(self, req, id):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME)
        compute_nodes = self.host_api.compute_node_search_by_hypervisor(
                context, id)
        if not compute_nodes:
            msg = _("No hypervisor matching '%s' could be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        hypervisors = []
        for compute_node in compute_nodes:
            try:
                instances = self.host_api.instance_get_all_by_host(context,
                    compute_node.host)
                service = self.host_api.service_get_by_compute_host(
                    context, compute_node.host)
            except exception.HostMappingNotFound as e:
                raise webob.exc.HTTPNotFound(explanation=e.format_message())
            hyp = self._view_hypervisor(compute_node, service, False, req,
                                        instances)
            hypervisors.append(hyp)
        return dict(hypervisors=hypervisors)

    @extensions.expected_errors(())
    def statistics(self, req):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME)
        stats = self.host_api.compute_node_statistics(context)
        return dict(hypervisor_statistics=stats)


class Hypervisors(extensions.V21APIExtensionBase):
    """Admin-only hypervisor administration."""

    name = "Hypervisors"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = [extensions.ResourceExtension(ALIAS,
                HypervisorsController(),
                collection_actions={'detail': 'GET',
                                    'statistics': 'GET'},
                member_actions={'uptime': 'GET',
                                'search': 'GET',
                                'servers': 'GET'})]

        return resources

    def get_controller_extensions(self):
        return []

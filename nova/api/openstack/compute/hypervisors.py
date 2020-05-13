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
from oslo_utils import strutils
from oslo_utils import uuidutils
import webob.exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import hypervisors as hyper_schema
from nova.api.openstack.compute.views import hypervisors as hyper_view
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova.policies import hypervisors as hv_policies
from nova import servicegroup
from nova import utils

LOG = logging.getLogger(__name__)

UUID_FOR_ID_MIN_VERSION = '2.53'


class HypervisorsController(wsgi.Controller):
    """The Hypervisors API controller for the OpenStack API."""

    _view_builder_class = hyper_view.ViewBuilder

    def __init__(self):
        super(HypervisorsController, self).__init__()
        self.host_api = compute.HostAPI()
        self.servicegroup_api = servicegroup.API()

    def _view_hypervisor(self, hypervisor, service, detail, req, servers=None,
                         with_servers=False, **kwargs):
        alive = self.servicegroup_api.service_is_up(service)
        # The 2.53 microversion returns the compute node uuid rather than id.
        uuid_for_id = api_version_request.is_supported(
            req, min_version=UUID_FOR_ID_MIN_VERSION)
        hyp_dict = {
            'id': hypervisor.uuid if uuid_for_id else hypervisor.id,
            'hypervisor_hostname': hypervisor.hypervisor_hostname,
            'state': 'up' if alive else 'down',
            'status': ('disabled' if service.disabled
                       else 'enabled'),
            }

        if detail:
            for field in ('vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
                          'memory_mb_used', 'local_gb_used',
                          'hypervisor_type', 'hypervisor_version',
                          'free_ram_mb', 'free_disk_gb', 'current_workload',
                          'running_vms', 'disk_available_least', 'host_ip'):
                hyp_dict[field] = getattr(hypervisor, field)

            service_id = service.uuid if uuid_for_id else service.id
            hyp_dict['service'] = {
                'id': service_id,
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
        # The 2.75 microversion adds 'servers' field always in response.
        # Empty list if there are no servers on hypervisors and it is
        # requested in request.
        elif with_servers and api_version_request.is_supported(
                req, min_version='2.75'):
            hyp_dict['servers'] = []

        # Add any additional info
        if kwargs:
            hyp_dict.update(kwargs)

        return hyp_dict

    def _get_compute_nodes_by_name_pattern(self, context, hostname_match):
        compute_nodes = self.host_api.compute_node_search_by_hypervisor(
                context, hostname_match)
        if not compute_nodes:
            msg = (_("No hypervisor matching '%s' could be found.") %
                   hostname_match)
            raise webob.exc.HTTPNotFound(explanation=msg)
        return compute_nodes

    def _get_hypervisors(self, req, detail=False, limit=None, marker=None,
                         links=False):
        """Get hypervisors for the given request.

        :param req: nova.api.openstack.wsgi.Request for the GET request
        :param detail: If True, return a detailed response.
        :param limit: An optional user-supplied page limit.
        :param marker: An optional user-supplied marker for paging.
        :param links: If True, return links in the response for paging.
        """
        context = req.environ['nova.context']

        # The 2.53 microversion moves the search and servers routes into
        # GET /os-hypervisors and GET /os-hypervisors/detail with query
        # parameters.
        if api_version_request.is_supported(
                req, min_version=UUID_FOR_ID_MIN_VERSION):
            hypervisor_match = req.GET.get('hypervisor_hostname_pattern')
            with_servers = strutils.bool_from_string(
                req.GET.get('with_servers', False), strict=True)
        else:
            hypervisor_match = None
            with_servers = False

        if hypervisor_match is not None:
            # We have to check for 'limit' in the request itself because
            # the limit passed in is CONF.api.max_limit by default.
            if 'limit' in req.GET or marker:
                # Paging with hostname pattern isn't supported.
                raise webob.exc.HTTPBadRequest(
                    _('Paging over hypervisors with the '
                      'hypervisor_hostname_pattern query parameter is not '
                      'supported.'))

            # Explicitly do not try to generate links when querying with the
            # hostname pattern since the request in the link would fail the
            # check above.
            links = False

            # Get all compute nodes with a hypervisor_hostname that matches
            # the given pattern. If none are found then it's a 404 error.
            compute_nodes = self._get_compute_nodes_by_name_pattern(
                context, hypervisor_match)
        else:
            # Get all compute nodes.
            try:
                compute_nodes = self.host_api.compute_node_get_all(
                    context, limit=limit, marker=marker)
            except exception.MarkerNotFound:
                msg = _('marker [%s] not found') % marker
                raise webob.exc.HTTPBadRequest(explanation=msg)

        hypervisors_list = []
        for hyp in compute_nodes:
            try:
                instances = None
                if with_servers:
                    instances = self.host_api.instance_get_all_by_host(
                        context, hyp.host)
                service = self.host_api.service_get_by_compute_host(
                    context, hyp.host)
                hypervisors_list.append(
                    self._view_hypervisor(
                        hyp, service, detail, req, servers=instances,
                        with_servers=with_servers))
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
                req, hypervisors_list, detail)
            if hypervisors_links:
                hypervisors_dict['hypervisors_links'] = hypervisors_links
        return hypervisors_dict

    @wsgi.Controller.api_version(UUID_FOR_ID_MIN_VERSION)
    @validation.query_schema(hyper_schema.list_query_schema_v253,
                             UUID_FOR_ID_MIN_VERSION)
    @wsgi.expected_errors((400, 404))
    def index(self, req):
        """Starting with the 2.53 microversion, the id field in the response
        is the compute_nodes.uuid value. Also, the search and servers routes
        are superseded and replaced with query parameters for listing
        hypervisors by a hostname pattern and whether or not to include
        hosted servers in the response.
        """
        limit, marker = common.get_limit_and_marker(req)
        return self._index(req, limit=limit, marker=marker, links=True)

    @wsgi.Controller.api_version("2.33", "2.52")  # noqa
    @validation.query_schema(hyper_schema.list_query_schema_v233)
    @wsgi.expected_errors(400)
    def index(self, req):  # noqa
        limit, marker = common.get_limit_and_marker(req)
        return self._index(req, limit=limit, marker=marker, links=True)

    @wsgi.Controller.api_version("2.1", "2.32")  # noqa
    @wsgi.expected_errors(())
    def index(self, req):  # noqa
        return self._index(req)

    def _index(self, req, limit=None, marker=None, links=False):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME % 'list', target={})
        return self._get_hypervisors(req, detail=False, limit=limit,
                                     marker=marker, links=links)

    @wsgi.Controller.api_version(UUID_FOR_ID_MIN_VERSION)
    @validation.query_schema(hyper_schema.list_query_schema_v253,
                             UUID_FOR_ID_MIN_VERSION)
    @wsgi.expected_errors((400, 404))
    def detail(self, req):
        """Starting with the 2.53 microversion, the id field in the response
        is the compute_nodes.uuid value. Also, the search and servers routes
        are superseded and replaced with query parameters for listing
        hypervisors by a hostname pattern and whether or not to include
        hosted servers in the response.
        """
        limit, marker = common.get_limit_and_marker(req)
        return self._detail(req, limit=limit, marker=marker, links=True)

    @wsgi.Controller.api_version("2.33", "2.52")  # noqa
    @validation.query_schema(hyper_schema.list_query_schema_v233)
    @wsgi.expected_errors((400))
    def detail(self, req):  # noqa
        limit, marker = common.get_limit_and_marker(req)
        return self._detail(req, limit=limit, marker=marker, links=True)

    @wsgi.Controller.api_version("2.1", "2.32")  # noqa
    @wsgi.expected_errors(())
    def detail(self, req):  # noqa
        return self._detail(req)

    def _detail(self, req, limit=None, marker=None, links=False):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME % 'list-detail', target={})
        return self._get_hypervisors(req, detail=True, limit=limit,
                                     marker=marker, links=links)

    @staticmethod
    def _validate_id(req, hypervisor_id):
        """Validates that the id is a uuid for microversions that require it.

        :param req: The HTTP request object which contains the requested
            microversion information.
        :param hypervisor_id: The provided hypervisor id.
        :raises: webob.exc.HTTPBadRequest if the requested microversion is
            greater than or equal to 2.53 and the id is not a uuid.
        :raises: webob.exc.HTTPNotFound if the requested microversion is
            less than 2.53 and the id is not an integer.
        """
        expect_uuid = api_version_request.is_supported(
            req, min_version=UUID_FOR_ID_MIN_VERSION)
        if expect_uuid:
            if not uuidutils.is_uuid_like(hypervisor_id):
                msg = _('Invalid uuid %s') % hypervisor_id
                raise webob.exc.HTTPBadRequest(explanation=msg)
        else:
            try:
                utils.validate_integer(hypervisor_id, 'id')
            except exception.InvalidInput:
                msg = (_("Hypervisor with ID '%s' could not be found.") %
                       hypervisor_id)
                raise webob.exc.HTTPNotFound(explanation=msg)

    @wsgi.Controller.api_version(UUID_FOR_ID_MIN_VERSION)
    @validation.query_schema(hyper_schema.show_query_schema_v253,
                             UUID_FOR_ID_MIN_VERSION)
    @wsgi.expected_errors((400, 404))
    def show(self, req, id):
        """The 2.53 microversion requires that the id is a uuid and as a result
        it can also return a 400 response if an invalid uuid is passed.

        The 2.53 microversion also supports the with_servers query parameter
        to include a list of servers on the given hypervisor if requested.
        """
        with_servers = strutils.bool_from_string(
            req.GET.get('with_servers', False), strict=True)
        return self._show(req, id, with_servers)

    @wsgi.Controller.api_version("2.1", "2.52")     # noqa F811
    @wsgi.expected_errors(404)
    def show(self, req, id):  # noqa
        return self._show(req, id)

    def _show(self, req, id, with_servers=False):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME % 'show', target={})

        self._validate_id(req, id)

        try:
            hyp = self.host_api.compute_node_get(context, id)
            instances = None
            if with_servers:
                instances = self.host_api.instance_get_all_by_host(
                    context, hyp.host)
            service = self.host_api.service_get_by_compute_host(
                context, hyp.host)
        except (ValueError, exception.ComputeHostNotFound,
                exception.HostMappingNotFound):
            msg = _("Hypervisor with ID '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        return dict(hypervisor=self._view_hypervisor(
            hyp, service, True, req, instances, with_servers))

    @wsgi.expected_errors((400, 404, 501))
    def uptime(self, req, id):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME % 'uptime', target={})

        self._validate_id(req, id)

        try:
            hyp = self.host_api.compute_node_get(context, id)
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

    @wsgi.Controller.api_version('2.1', '2.52')
    @wsgi.expected_errors(404)
    def search(self, req, id):
        """Prior to microversion 2.53 you could search for hypervisors by a
        hostname pattern on a dedicated route. Starting with 2.53, searching
        by a hostname pattern is a query parameter in the GET /os-hypervisors
        index and detail methods.
        """
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME % 'search', target={})
        hypervisors = self._get_compute_nodes_by_name_pattern(context, id)
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

    @wsgi.Controller.api_version('2.1', '2.52')
    @wsgi.expected_errors(404)
    def servers(self, req, id):
        """Prior to microversion 2.53 you could search for hypervisors by a
        hostname pattern and include servers on those hosts in the response on
        a dedicated route. Starting with 2.53, searching by a hostname pattern
        and including hosted servers is a query parameter in the
        GET /os-hypervisors index and detail methods.
        """
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME % 'servers', target={})
        compute_nodes = self._get_compute_nodes_by_name_pattern(context, id)
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

    @wsgi.expected_errors(())
    def statistics(self, req):
        context = req.environ['nova.context']
        context.can(hv_policies.BASE_POLICY_NAME % 'statistics', target={})
        stats = self.host_api.compute_node_statistics(context)
        return dict(hypervisor_statistics=stats)

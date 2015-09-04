#   Copyright (c) 2014 Umea University
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

"""The Fault Tolerance API extension."""

import webob

from nova.api.openstack.compute import servers
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import conductor
from nova import exception
from nova import objects
from nova import utils

from nova.openstack.common import log as logging
LOG = logging.getLogger(__name__)

authorize = extensions.extension_authorizer('compute', 'fault_tolerance')
soft_authorize = extensions.soft_extension_authorizer('compute',
                                                      'fault_tolerance')


class FaultServerToleranceController(servers.Controller):
    def __init__(self, *args, **kwargs):
        super(FaultServerToleranceController, self).__init__(*args, **kwargs)
        self.conductor_api = conductor.API()

    @wsgi.action('failover')
    def _failover(self, req, id, body):
        """Recover from a failure.

        The failover API call allows for third-party fault detection mechanisms
        to initiate recovery of failed instances in fault tolerance mode.

        If a primary instance has failed, a secondary instance is promoted to
        primary and all traffic is redirected without the client feeling it. If
        a secondary instance has failed it's removed. Finally, the
        primary/secondary relation is cleaned up.
        """
        context = req.environ["nova.context"]

        try:
            self.conductor_api.ft_failover(context, id)
        except (exception.InstanceNotFound,
                exception.FaultToleranceRelationByPrimaryNotFound,
                exception.FaultToleranceRelationBySecondaryNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceNotFaultTolerant as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())

        return webob.Response(status_int=200)

    @wsgi.extends
    def delete(self, req, resp_obj, id):
        """
        Extending the delete action to delete all secondary instances in
        relation to a primary instance getting deleted.
        """
        context = req.environ['nova.context']

        try:
            relations = (objects.FaultToleranceRelationList.
                         get_by_primary_instance_uuid(context, id))
            for relation in relations:
                LOG.debug("Attempting to delete secondary instance: %s",
                          relation.secondary_instance_uuid)

                (super(FaultServerToleranceController, self).
                    delete(req, relation.secondary_instance_uuid))

                LOG.debug("Successfully deleted secondary instance: %s",
                          relation.secondary_instance_uuid)

                relation.destroy()

            # TODO(ORBIT): Investigate if this could happen even though the
            #              instance remain undeleted.
            self.conductor_api.colo_deallocate_vlan(context, id)
        except exception.FaultToleranceRelationByPrimaryNotFound as e:
            LOG.debug(e.format_message())

    def _extend_server(self, req, server, relations):
        db_instance = req.get_db_instance(server['id'])

        has_relation = False
        for relation in relations:
            if server["id"] in relation:
                has_relation = True
                break

        status = "not_ft"
        if utils.ft_secondary(db_instance):
            status = "secondary"
            if not has_relation:
                status = "missing_primary"
        elif utils.ft_enabled(db_instance):
            status = "primary"
            if not has_relation:
                status = "missing_secondary"

        server["%s:ft_status" % Fault_tolerance.alias] = status

        return status

    def _get_relations(self, context, instance_uuids):
        relations = (objects.FaultToleranceRelationList.
                     get_by_instance_uuids(context, instance_uuids))
        return relations

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']

        db_instance = req.get_db_instance(id)

        is_secondary = utils.ft_secondary(db_instance)
        if is_secondary:
            authorize(context, action="show_secondary")

        resp_obj.attach(xml=FaultToleranceTemplate())

        relations = self._get_relations(context, [id])
        self._extend_server(req, resp_obj.obj['server'], relations)

    def _filter_passive_servers(self, req, resp_obj):
        for key, server in enumerate(list(resp_obj.obj['servers'])):
            db_instance = req.get_db_instance(server['id'])
            if utils.ft_secondary(db_instance):
                del resp_obj.obj['servers'][key]

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']

        if not soft_authorize(context, "show_secondary"):
            self._filter_passive_servers(req, resp_obj)

        resp_obj.attach(xml=FaultToleranceListTemplate())

        servers = resp_obj.obj['servers']
        server_ids = [server['id'] for server in servers]
        relations = self._get_relations(context, server_ids)
        for server in servers:
            status = self._extend_server(req, server, relations)


class Fault_tolerance(extensions.ExtensionDescriptor):
    """Fault tolerance server extension."""

    name = "FaultTolerance"
    alias = "OS-EXT-FT"
    namespace = ("http://docs.openstack.org/compute/"
                 "ext/fault_tolerance/api/v1.0")
    updated = "2015-01-13T00:00:00+00:00"

    def get_controller_extensions(self):
        servers_extension = extensions.ControllerExtension(
                self, 'servers', FaultServerToleranceController())
        return [servers_extension]


def _add_ft_element(elem):
    elem.set('{%s}ft_state' % Fault_tolerance.namespace,
             '%s:ft_state' % Fault_tolerance.alias)


class FaultToleranceTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        _add_ft_element(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Fault_tolerance.alias: Fault_tolerance.namespace})


class FaultToleranceListTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        _add_ft_element(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Fault_tolerance.alias: Fault_tolerance.namespace})

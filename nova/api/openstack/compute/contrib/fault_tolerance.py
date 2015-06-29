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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack.compute import servers
from nova import conductor
from nova import exception
from nova import objects

from nova.openstack.common import log as logging
LOG = logging.getLogger(__name__)


class FaultServerToleranceController(servers.Controller):
    def __init__(self, *args, **kwargs):
        super(FaultServerToleranceController, self).__init__(*args, **kwargs)
        self.conductor_api = conductor.API()

    @wsgi.action('failover')
    def _failover(self, req, id, body):
        """Failover to secondary instance."""
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
        relation to primary instances getting deleted.
        """
        context = req.environ['nova.context']

        try:
            relations = objects.FaultToleranceRelationList.\
                    get_by_primary_instance_uuid(context, id)
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

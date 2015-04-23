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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack.compute import servers
from nova import exception
from nova import objects

from nova.openstack.common import log as logging
LOG = logging.getLogger(__name__)


class FaultServerToleranceController(servers.Controller):
    def __init__(self, *args, **kwargs):
        super(FaultServerToleranceController, self).__init__(*args, **kwargs)

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

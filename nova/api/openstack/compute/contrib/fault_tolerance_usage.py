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

"""The ORBIT fault tolerance usage extension."""

from collections import defaultdict

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova import objects
from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)

# TODO(ORBIT)
# authorize = extensions.extension_authorizer('compute', 'fault_tolerance')
# soft_authorize = extensions.soft_extension_authorizer('compute',
#                                                       'fault_tolerance')


class FaultToleranceUsageController(wsgi.Controller):

    def __init__(self, *args, **kwargs):
        super(FaultToleranceUsageController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _extend(self, req, usage):
        """Move secondary instances usage data to the primary instance."""
        context = req.environ['nova.context']

        instance_uuids = []
        for server_usage in usage['server_usages']:
            instance_uuids.append(server_usage['instance_id'])

        opts = {'uuid': instance_uuids}
        instances = self.compute_api.get_all(context, search_opts=opts)

        primary_instance_uuids = []
        secondary_instance_uuids = []
        for instance in instances:
            if utils.ft_secondary(instance):
                secondary_instance_uuids.append(instance['uuid'])
            elif utils.ft_enabled(instance):
                primary_instance_uuids.append(instance['uuid'])

        relations = defaultdict(list)

        for key, server_usage in enumerate(usage['server_usages']):
            uuid = server_usage['instance_id']
            if uuid in secondary_instance_uuids:
                try:
                    r = (objects.FaultToleranceRelation.
                         get_by_secondary_instance_uuid(context, uuid))
                    relations[r.primary_instance_uuid].append(server_usage)
                except exception.FaultToleranceRelationBySecondaryNotFound as e:
                    LOG.warning("Found secondary instance without primary."
                                "Standalone secondary instances are currently "
                                "not supported and will therefore not show up "
                                "in the usage data. It's recommended that the "
                                "secondary instance is deleted."
                                "Error message: %s", e)

                del usage['server_usages'][key]

        for server_usage in usage['server_usages']:
            uuid = server_usage['instance_id']
            if uuid in primary_instance_uuids:
                server_usage['ft_secondary_usage'] = relations[uuid]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        self._extend(req, resp_obj.obj['tenant_usage'])

    @wsgi.extends
    def index(self, req, resp_obj):
        for usage in resp_obj.obj['tenant_usages']:
            if 'server_usages' in usage:
                self._extend(req, usage)


class Fault_tolerance_usage(extensions.ExtensionDescriptor):
    """Fault tolerance usage extension."""

    name = "FaultToleranceUsage"
    alias = "OS-EXT-FTU"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "fault_tolerance_usage/api/v1.0")
    updated = "2015-01-13T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = FaultToleranceUsageController()
        extension = extensions.ControllerExtension(self,
                                                   'os-simple-tenant-usage',
                                                   controller)
        return [extension]

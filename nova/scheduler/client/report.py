# Copyright (c) 2014 Red Hat, Inc.
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


from nova import conductor
from nova import exception
from nova.i18n import _LI
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class SchedulerReportClient(object):
    """Client class for updating the scheduler."""

    def __init__(self):
        self.conductor_api = conductor.API()

    def update_resource_stats(self, context, name, stats):
        """Creates or updates stats for the desired service.

        :param context: local context
        :param name: name of resource to update
        :type name: immutable (str or tuple)
        :param stats: updated stats to send to scheduler
        :type stats: dict
        """

        if 'id' in stats:
            compute_node_id = stats['id']
            updates = stats.copy()
            del updates['id']
        else:
            raise exception.ComputeHostNotCreated(name=str(name))

        self.conductor_api.compute_node_update(context,
                                               {'id': compute_node_id},
                                               updates)

        LOG.info(_LI('Compute_service record updated for '
                 '%s') % str(name))

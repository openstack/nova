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

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import exception
from nova.i18n import _LI
from nova import objects

LOG = logging.getLogger(__name__)


class SchedulerReportClient(object):
    """Client class for updating the scheduler."""

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

        if 'stats' in updates:
            # NOTE(danms): This is currently pre-serialized for us,
            # which we don't want if we're using the object. So,
            # fix it here, and follow up with removing this when the
            # RT is converted to proper objects.
            updates['stats'] = jsonutils.loads(updates['stats'])
        compute_node = objects.ComputeNode(context=context,
                                           id=compute_node_id)
        compute_node.obj_reset_changes()
        for k, v in updates.items():
            if k == 'pci_device_pools':
                # NOTE(danms): Since the updates are actually the result of
                # a obj_to_primitive() on some real objects, we need to convert
                # back to a real object (not from_dict() or _from_db_object(),
                # which expect a db-formatted object) but just an attr-based
                # reconstruction. When we start getting a ComputeNode from
                # scheduler this "bandage" can go away.
                if v:
                    devpools = [objects.PciDevicePool.from_dict(x) for x in v]
                else:
                    devpools = []
                compute_node.pci_device_pools = objects.PciDevicePoolList(
                    objects=devpools)
            else:
                setattr(compute_node, k, v)
        compute_node.save()

        LOG.info(_LI('Compute_service record updated for '
                 '%s') % str(name))

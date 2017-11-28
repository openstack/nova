# Copyright (c) 2017 IBM Corp.
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

from oslo_serialization import jsonutils
from oslo_versionedobjects import base as ovo_base
from oslo_versionedobjects import fields

from nova import objects
from nova.objects import base


@base.NovaObjectRegistry.register
class Selection(base.NovaObject, ovo_base.ComparableVersionedObject):
    """Represents a destination that has been selected by the Scheduler. Note
    that these objects are not persisted to the database.
    """

    # Version 1.0: Initial version
    VERSION = "1.0"

    fields = {
        "compute_node_uuid": fields.UUIDField(),
        "service_host": fields.StringField(),
        "nodename": fields.StringField(),
        "cell_uuid": fields.UUIDField(),
        "limits": fields.ObjectField("SchedulerLimits", nullable=True),
        # An allocation_request is a non-trivial dict, and so it will be stored
        # as an encoded string.
        "allocation_request": fields.StringField(nullable=True),
        "allocation_request_version": fields.StringField(nullable=True),
    }

    @classmethod
    def from_host_state(cls, host_state, allocation_request=None,
            allocation_request_version=None):
        """A convenience method for converting a HostState, an
        allocation_request, and an allocation_request_version into a Selection
        object. Note that allocation_request and allocation_request_version
        must be passed separately, as they are not part of the HostState.
        """
        allocation_request_json = jsonutils.dumps(allocation_request)
        limits = objects.SchedulerLimits.from_dict(host_state.limits)
        return cls(compute_node_uuid=host_state.uuid,
                   service_host=host_state.host,
                   nodename=host_state.nodename,
                   cell_uuid=host_state.cell_uuid,
                   limits=limits,
                   allocation_request=allocation_request_json,
                   allocation_request_version=allocation_request_version)

    def to_dict(self):
        if self.limits is not None:
            limits = self.limits.to_dict()
        else:
            limits = {}
        # The NUMATopologyFilter can set 'numa_topology' in the limits dict to
        # a NUMATopologyLimits object which we need to convert to a primitive
        # before this hits jsonutils.to_primitive(). We only check for that
        # known case specifically as we don't care about handling out of tree
        # filters or drivers injecting non-serializable things in the limits
        # dict.
        numa_limit = limits.get("numa_topology")
        if numa_limit is not None:
            limits['numa_topology'] = numa_limit.obj_to_primitive()
        return {
            'host': self.service_host,
            'nodename': self.nodename,
            'limits': limits,
        }

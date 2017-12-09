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

from nova.scheduler import rpcapi as scheduler_rpcapi


class SchedulerQueryClient(object):
    """Client class for querying to the scheduler."""

    def __init__(self):
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()

    def select_destinations(self, context, spec_obj, instance_uuids,
            return_objects=False, return_alternates=False):
        """Returns destinations(s) best suited for this request_spec and
        filter_properties.

        When return_objects is False, the result will be the "old-style" list
        of dicts with 'host', 'nodename' and 'limits' as keys. The value of
        return_alternates is ignored.

        When return_objects is True, the result will be a list of lists of
        Selection objects, with one list per instance. Each instance's list
        will contain a Selection representing the selected (and claimed) host,
        and, if return_alternates is True, zero or more Selection objects that
        represent alternate hosts. The number of alternates returned depends on
        the configuration setting `CONF.scheduler.max_attempts`.
        """
        return self.scheduler_rpcapi.select_destinations(context, spec_obj,
                instance_uuids, return_objects, return_alternates)

    def update_aggregates(self, context, aggregates):
        """Updates HostManager internal aggregates information.

        :param aggregates: Aggregate(s) to update
        :type aggregates: :class:`nova.objects.Aggregate`
                          or :class:`nova.objects.AggregateList`
        """
        self.scheduler_rpcapi.update_aggregates(context, aggregates)

    def delete_aggregate(self, context, aggregate):
        """Deletes HostManager internal information about a specific aggregate.

        :param aggregate: Aggregate to delete
        :type aggregate: :class:`nova.objects.Aggregate`
        """
        self.scheduler_rpcapi.delete_aggregate(context, aggregate)

    def update_instance_info(self, context, host_name, instance_info):
        """Updates the HostManager with the current information about the
        instances on a host.

        :param context: local context
        :param host_name: name of host sending the update
        :param instance_info: an InstanceList object.
        """
        self.scheduler_rpcapi.update_instance_info(context, host_name,
                                                   instance_info)

    def delete_instance_info(self, context, host_name, instance_uuid):
        """Updates the HostManager with the current information about an
        instance that has been deleted on a host.

        :param context: local context
        :param host_name: name of host sending the update
        :param instance_uuid: the uuid of the deleted instance
        """
        self.scheduler_rpcapi.delete_instance_info(context, host_name,
                                                   instance_uuid)

    def sync_instance_info(self, context, host_name, instance_uuids):
        """Notifies the HostManager of the current instances on a host by
        sending a list of the uuids for those instances. The HostManager can
        then compare that with its in-memory view of the instances to detect
        when they are out of sync.

        :param context: local context
        :param host_name: name of host sending the update
        :param instance_uuids: a list of UUID strings representing the current
                               instances on the specified host
        """
        self.scheduler_rpcapi.sync_instance_info(context, host_name,
                                                 instance_uuids)

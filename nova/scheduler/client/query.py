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

    def select_destinations(self, context, request_spec, filter_properties):
        """Returns destinations(s) best suited for this request_spec and
        filter_properties.

        The result should be a list of dicts with 'host', 'nodename' and
        'limits' as keys.
        """
        return self.scheduler_rpcapi.select_destinations(
            context, request_spec, filter_properties)

# Copyright (c) 2011 Openstack, LLC.
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


import nova.scheduler
from nova.scheduler.filters import abstract_filter


class AllHostsFilter(abstract_filter.AbstractHostFilter):
    """NOP host filter. Returns all hosts in ZoneManager."""
    def instance_type_to_filter(self, instance_type):
        """Return anything to prevent base-class from raising
        exception.
        """
        return (self._full_name(), instance_type)

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts from ZoneManager list."""
        return [(host, services)
               for host, services in zone_manager.service_states.iteritems()]

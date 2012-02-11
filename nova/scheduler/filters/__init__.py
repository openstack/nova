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

"""
There are three filters included: AllHosts, InstanceType & JSON.

AllHosts just returns the full, unfiltered list of hosts.
InstanceType is a hard coded matching mechanism based on flavor criteria.
JSON is an ad-hoc filter grammar.

Why JSON? The requests for instances may come in through the
REST interface from a user or a parent Zone.
Currently InstanceTypes are used for specifing the type of instance desired.
Specific Nova users have noted a need for a more expressive way of specifying
instance requirements. Since we don't want to get into building full DSL,
this filter is a simple form as an example of how this could be done.
In reality, most consumers will use the more rigid filters such as the
InstanceType filter.
"""
from nova.scheduler.filters.abstract_filter import AbstractHostFilter
from nova.scheduler.filters.affinity_filter import DifferentHostFilter
from nova.scheduler.filters.affinity_filter import SameHostFilter
from nova.scheduler.filters.affinity_filter import SimpleCIDRAffinityFilter
from nova.scheduler.filters.all_hosts_filter import AllHostsFilter
from nova.scheduler.filters.availability_zone_filter \
    import AvailabilityZoneFilter
from nova.scheduler.filters.isolated_hosts_filter import IsolatedHostsFilter
from nova.scheduler.filters.compute_filter import ComputeFilter
from nova.scheduler.filters.core_filter import CoreFilter
from nova.scheduler.filters.json_filter import JsonFilter
from nova.scheduler.filters.ram_filter import RamFilter

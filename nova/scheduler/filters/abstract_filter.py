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


class AbstractHostFilter(object):
    """Base class for host filters."""
    def instance_type_to_filter(self, instance_type):
        """Convert instance_type into a filter for most common use-case."""
        raise NotImplementedError()

    def filter_hosts(self, host_list, query, options):
        """Return a list of hosts that fulfill the filter."""
        raise NotImplementedError()

    def _full_name(self):
        """module.classname of the filter."""
        return "%s.%s" % (self.__module__, self.__class__.__name__)

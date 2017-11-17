# Copyright (c) 2011-2012 OpenStack Foundation
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


from nova.scheduler import filters


class AllHostsFilter(filters.BaseHostFilter):
    """NOOP host filter. Returns all hosts."""

    # list of hosts doesn't change within a request
    run_filter_once_per_request = True

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        return True

# Copyright (c) 2014 Rackspace Hosting
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

from nova.scheduler import filter_scheduler


class CachingScheduler(filter_scheduler.FilterScheduler):
    """Scheduler to test aggressive caching of the host list.

    Please note, this is a very opinionated scheduler. Be sure to
    review the caveats listed here before selecting this scheduler.

    The aim of this scheduler is to reduce server build times when
    you have large bursts of server builds, by reducing the time it
    takes, from the users point of view, to service each schedule
    request.

    There are two main parts to scheduling a users request:
    * getting the current state of the system
    * using filters and weights to pick the best host

    This scheduler tries its best to cache in memory the current
    state of the system, so we don't need to make the expensive
    call to get the current state of the system while processing
    a user's request, we can do that query in a periodic task
    before the user even issues their request.

    To reduce races, cached info of the chosen host is updated using
    the existing host state call: consume_from_instance

    Please note, the way this works, each scheduler worker has its own
    copy of the cache. So if you run multiple schedulers, you will get
    more retries, because the data stored on any additional scheduler will
    be more out of date, than if it was fetched from the database.

    In a similar way, if you have a high number of server deletes, the
    extra capacity from those deletes will not show up until the cache is
    refreshed.
    """

    def __init__(self, *args, **kwargs):
        super(CachingScheduler, self).__init__(*args, **kwargs)
        self.all_host_states = None

    def run_periodic_tasks(self, context):
        """Called from a periodic tasks in the manager."""
        elevated = context.elevated()
        # NOTE(johngarbutt) Fetching the list of hosts before we get
        # a user request, so no user requests have to wait while we
        # fetch the list of hosts.
        self.all_host_states = self._get_up_hosts(elevated)

    def _get_all_host_states(self, context):
        """Called from the filter scheduler, in a template pattern."""
        if self.all_host_states is None:
            # NOTE(johngarbutt) We only get here when we a scheduler request
            # comes in before the first run of the periodic task.
            # Rather than raise an error, we fetch the list of hosts.
            self.all_host_states = self._get_up_hosts(context)

        return self.all_host_states

    def _get_up_hosts(self, context):
        all_hosts_iterator = self.host_manager.get_all_host_states(context)
        return list(all_hosts_iterator)

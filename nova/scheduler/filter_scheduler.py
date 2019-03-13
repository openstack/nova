# Copyright (c) 2011 OpenStack Foundation
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
The FilterScheduler is for creating instances locally.
You can customize this scheduler by specifying your own Host Filters and
Weighing Functions.
"""

import random

from oslo_log import log as logging
from six.moves import range

import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova import rpc
from nova.scheduler import client
from nova.scheduler import driver
from nova.scheduler import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class FilterScheduler(driver.Scheduler):
    """Scheduler that can be used for filtering and weighing."""
    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)
        self.notifier = rpc.get_notifier('scheduler')
        scheduler_client = client.SchedulerClient()
        self.placement_client = scheduler_client.reportclient

    def select_destinations(self, context, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, provider_summaries,
            allocation_request_version=None, return_alternates=False):
        """Returns a list of lists of Selection objects, which represent the
        hosts and (optionally) alternates for each instance.

        :param context: The RequestContext object
        :param spec_obj: The RequestSpec object
        :param instance_uuids: List of UUIDs, one for each value of the spec
                               object's num_instances attribute
        :param alloc_reqs_by_rp_uuid: Optional dict, keyed by resource provider
                                      UUID, of the allocation_requests that may
                                      be used to claim resources against
                                      matched hosts. If None, indicates either
                                      the placement API wasn't reachable or
                                      that there were no allocation_requests
                                      returned by the placement API. If the
                                      latter, the provider_summaries will be an
                                      empty dict, not None.
        :param provider_summaries: Optional dict, keyed by resource provider
                                   UUID, of information that will be used by
                                   the filters/weighers in selecting matching
                                   hosts for a request. If None, indicates that
                                   the scheduler driver should grab all compute
                                   node information locally and that the
                                   Placement API is not used. If an empty dict,
                                   indicates the Placement API returned no
                                   potential matches for the requested
                                   resources.
        :param allocation_request_version: The microversion used to request the
                                           allocations.
        :param return_alternates: When True, zero or more alternate hosts are
                                  returned with each selected host. The number
                                  of alternates is determined by the
                                  configuration option
                                  `CONF.scheduler.max_attempts`.
        """
        self.notifier.info(
            context, 'scheduler.select_destinations.start',
            dict(request_spec=spec_obj.to_legacy_request_spec_dict()))

        host_selections = self._schedule(context, spec_obj, instance_uuids,
                alloc_reqs_by_rp_uuid, provider_summaries,
                allocation_request_version, return_alternates)
        self.notifier.info(
            context, 'scheduler.select_destinations.end',
            dict(request_spec=spec_obj.to_legacy_request_spec_dict()))
        return host_selections

    def _schedule(self, context, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, provider_summaries,
            allocation_request_version=None, return_alternates=False):
        """Returns a list of lists of Selection objects.

        :param context: The RequestContext object
        :param spec_obj: The RequestSpec object
        :param instance_uuids: List of instance UUIDs to place or move.
        :param alloc_reqs_by_rp_uuid: Optional dict, keyed by resource provider
                                      UUID, of the allocation_requests that may
                                      be used to claim resources against
                                      matched hosts. If None, indicates either
                                      the placement API wasn't reachable or
                                      that there were no allocation_requests
                                      returned by the placement API. If the
                                      latter, the provider_summaries will be an
                                      empty dict, not None.
        :param provider_summaries: Optional dict, keyed by resource provider
                                   UUID, of information that will be used by
                                   the filters/weighers in selecting matching
                                   hosts for a request. If None, indicates that
                                   the scheduler driver should grab all compute
                                   node information locally and that the
                                   Placement API is not used. If an empty dict,
                                   indicates the Placement API returned no
                                   potential matches for the requested
                                   resources.
        :param allocation_request_version: The microversion used to request the
                                           allocations.
        :param return_alternates: When True, zero or more alternate hosts are
                                  returned with each selected host. The number
                                  of alternates is determined by the
                                  configuration option
                                  `CONF.scheduler.max_attempts`.
        """
        elevated = context.elevated()

        # Find our local list of acceptable hosts by repeatedly
        # filtering and weighing our options. Each time we choose a
        # host, we virtually consume resources on it so subsequent
        # selections can adjust accordingly.

        # Note: remember, we are using a generator-iterator here. So only
        # traverse this list once. This can bite you if the hosts
        # are being scanned in a filter or weighing function.
        hosts = self._get_all_host_states(elevated, spec_obj,
            provider_summaries)

        # NOTE(sbauza): The RequestSpec.num_instances field contains the number
        # of instances created when the RequestSpec was used to first boot some
        # instances. This is incorrect when doing a move or resize operation,
        # so prefer the length of instance_uuids unless it is None.
        num_instances = (len(instance_uuids) if instance_uuids
                         else spec_obj.num_instances)

        # For each requested instance, we want to return a host whose resources
        # for the instance have been claimed, along with zero or more
        # alternates. These alternates will be passed to the cell that the
        # selected host is in, so that if for some reason the build fails, the
        # cell conductor can retry building the instance on one of these
        # alternates instead of having to simply fail. The number of alternates
        # is based on CONF.scheduler.max_attempts; note that if there are not
        # enough filtered hosts to provide the full number of alternates, the
        # list of hosts may be shorter than this amount.
        num_alts = (CONF.scheduler.max_attempts - 1
                    if return_alternates else 0)

        if (instance_uuids is None or
                not self.USES_ALLOCATION_CANDIDATES or
                alloc_reqs_by_rp_uuid is None):
            # We need to support the caching scheduler, which doesn't use the
            # placement API (and has USES_ALLOCATION_CANDIDATE = False) and
            # therefore we skip all the claiming logic for that scheduler
            # driver. Also, if there was a problem communicating with the
            # placement API, alloc_reqs_by_rp_uuid will be None, so we skip
            # claiming in that case as well. In the case where instance_uuids
            # is None, that indicates an older conductor, so we need to return
            # the objects without alternates. They will be converted back to
            # the older dict format representing HostState objects.
            return self._legacy_find_hosts(context, num_instances, spec_obj,
                                           hosts, num_alts,
                                           instance_uuids=instance_uuids)

        # A list of the instance UUIDs that were successfully claimed against
        # in the placement API. If we are not able to successfully claim for
        # all involved instances, we use this list to remove those allocations
        # before returning
        claimed_instance_uuids = []

        # The list of hosts that have been selected (and claimed).
        claimed_hosts = []

        for num, instance_uuid in enumerate(instance_uuids):
            # In a multi-create request, the first request spec from the list
            # is passed to the scheduler and that request spec's instance_uuid
            # might not be the same as the instance we're processing, so we
            # update the instance_uuid in that case before passing the request
            # spec to filters since at least one filter
            # (ServerGroupAntiAffinityFilter) depends on that information being
            # accurate.
            spec_obj.instance_uuid = instance_uuid
            # Reset the field so it's not persisted accidentally.
            spec_obj.obj_reset_changes(['instance_uuid'])

            hosts = self._get_sorted_hosts(spec_obj, hosts, num)
            if not hosts:
                # NOTE(jaypipes): If we get here, that means not all instances
                # in instance_uuids were able to be matched to a selected host.
                # Any allocations will be cleaned up in the
                # _ensure_sufficient_hosts() call.
                break

            # Attempt to claim the resources against one or more resource
            # providers, looping over the sorted list of possible hosts
            # looking for an allocation_request that contains that host's
            # resource provider UUID
            claimed_host = None
            for host in hosts:
                cn_uuid = host.uuid
                if cn_uuid not in alloc_reqs_by_rp_uuid:
                    msg = ("A host state with uuid = '%s' that did not have a "
                          "matching allocation_request was encountered while "
                          "scheduling. This host was skipped.")
                    LOG.debug(msg, cn_uuid)
                    continue

                alloc_reqs = alloc_reqs_by_rp_uuid[cn_uuid]
                # TODO(jaypipes): Loop through all allocation_requests instead
                # of just trying the first one. For now, since we'll likely
                # want to order the allocation_requests in the future based on
                # information in the provider summaries, we'll just try to
                # claim resources using the first allocation_request
                alloc_req = alloc_reqs[0]
                if utils.claim_resources(elevated, self.placement_client,
                        spec_obj, instance_uuid, alloc_req,
                        allocation_request_version=allocation_request_version):
                    claimed_host = host
                    break

            if claimed_host is None:
                # We weren't able to claim resources in the placement API
                # for any of the sorted hosts identified. So, clean up any
                # successfully-claimed resources for prior instances in
                # this request and return an empty list which will cause
                # select_destinations() to raise NoValidHost
                LOG.debug("Unable to successfully claim against any host.")
                break

            claimed_instance_uuids.append(instance_uuid)
            claimed_hosts.append(claimed_host)

            # Now consume the resources so the filter/weights will change for
            # the next instance.
            self._consume_selected_host(claimed_host, spec_obj,
                                        instance_uuid=instance_uuid)

        # Check if we were able to fulfill the request. If not, this call will
        # raise a NoValidHost exception.
        self._ensure_sufficient_hosts(context, claimed_hosts, num_instances,
                claimed_instance_uuids)

        # We have selected and claimed hosts for each instance. Now we need to
        # find alternates for each host.
        selections_to_return = self._get_alternate_hosts(
            claimed_hosts, spec_obj, hosts, num, num_alts,
            alloc_reqs_by_rp_uuid, allocation_request_version)
        return selections_to_return

    def _ensure_sufficient_hosts(self, context, hosts, required_count,
            claimed_uuids=None):
        """Checks that we have selected a host for each requested instance. If
        not, log this failure, remove allocations for any claimed instances,
        and raise a NoValidHost exception.
        """
        if len(hosts) == required_count:
            # We have enough hosts.
            return

        if claimed_uuids:
            self._cleanup_allocations(context, claimed_uuids)
        # NOTE(Rui Chen): If multiple creates failed, set the updated time
        # of selected HostState to None so that these HostStates are
        # refreshed according to database in next schedule, and release
        # the resource consumed by instance in the process of selecting
        # host.
        for host in hosts:
            host.updated = None

        # Log the details but don't put those into the reason since
        # we don't want to give away too much information about our
        # actual environment.
        LOG.debug('There are %(hosts)d hosts available but '
                  '%(required_count)d instances requested to build.',
                  {'hosts': len(hosts),
                   'required_count': required_count})
        reason = _('There are not enough hosts available.')
        raise exception.NoValidHost(reason=reason)

    def _cleanup_allocations(self, context, instance_uuids):
        """Removes allocations for the supplied instance UUIDs."""
        if not instance_uuids:
            return
        LOG.debug("Cleaning up allocations for %s", instance_uuids)
        for uuid in instance_uuids:
            self.placement_client.delete_allocation_for_instance(context, uuid)

    def _legacy_find_hosts(self, context, num_instances, spec_obj, hosts,
                           num_alts, instance_uuids=None):
        """Some schedulers do not do claiming, or we can sometimes not be able
        to if the Placement service is not reachable. Additionally, we may be
        working with older conductors that don't pass in instance_uuids.
        """
        # The list of hosts selected for each instance
        selected_hosts = []
        # This the overall list of values to be returned. There will be one
        # item per instance, and each item will be a list of Selection objects
        # representing the selected host along with zero or more alternates
        # from the same cell.
        selections_to_return = []

        for num in range(num_instances):
            instance_uuid = instance_uuids[num] if instance_uuids else None
            if instance_uuid:
                # Update the RequestSpec.instance_uuid before sending it to
                # the filters in case we're doing a multi-create request, but
                # don't persist the change.
                spec_obj.instance_uuid = instance_uuid
                spec_obj.obj_reset_changes(['instance_uuid'])
            hosts = self._get_sorted_hosts(spec_obj, hosts, num)
            if not hosts:
                # No hosts left, so break here, and the
                # _ensure_sufficient_hosts() call below will handle this.
                break
            selected_host = hosts[0]
            selected_hosts.append(selected_host)
            self._consume_selected_host(selected_host, spec_obj,
                                        instance_uuid=instance_uuid)

        # Check if we were able to fulfill the request. If not, this call will
        # raise a NoValidHost exception.
        self._ensure_sufficient_hosts(context, selected_hosts, num_instances)

        selections_to_return = self._get_alternate_hosts(selected_hosts,
                spec_obj, hosts, num, num_alts)
        return selections_to_return

    @staticmethod
    def _consume_selected_host(selected_host, spec_obj, instance_uuid=None):
        LOG.debug("Selected host: %(host)s", {'host': selected_host},
                  instance_uuid=instance_uuid)
        selected_host.consume_from_request(spec_obj)
        # If we have a server group, add the selected host to it for the
        # (anti-)affinity filters to filter out hosts for subsequent instances
        # in a multi-create request.
        if spec_obj.instance_group is not None:
            spec_obj.instance_group.hosts.append(selected_host.host)
            # hosts has to be not part of the updates when saving
            spec_obj.instance_group.obj_reset_changes(['hosts'])
            # The ServerGroupAntiAffinityFilter also relies on
            # HostState.instances being accurate within a multi-create request.
            if instance_uuid and instance_uuid not in selected_host.instances:
                # Set a stub since ServerGroupAntiAffinityFilter only cares
                # about the keys.
                selected_host.instances[instance_uuid] = (
                    objects.Instance(uuid=instance_uuid))

    def _get_alternate_hosts(self, selected_hosts, spec_obj, hosts, index,
                             num_alts, alloc_reqs_by_rp_uuid=None,
                             allocation_request_version=None):
        # We only need to filter/weigh the hosts again if we're dealing with
        # more than one instance and are going to be picking alternates.
        if index > 0 and num_alts > 0:
            # The selected_hosts have all had resources 'claimed' via
            # _consume_selected_host, so we need to filter/weigh and sort the
            # hosts again to get an accurate count for alternates.
            hosts = self._get_sorted_hosts(spec_obj, hosts, index)
        # This is the overall list of values to be returned. There will be one
        # item per instance, and each item will be a list of Selection objects
        # representing the selected host along with alternates from the same
        # cell.
        selections_to_return = []
        for selected_host in selected_hosts:
            # This is the list of hosts for one particular instance.
            if alloc_reqs_by_rp_uuid:
                selected_alloc_req = alloc_reqs_by_rp_uuid.get(
                        selected_host.uuid)[0]
            else:
                selected_alloc_req = None
            selection = objects.Selection.from_host_state(selected_host,
                    allocation_request=selected_alloc_req,
                    allocation_request_version=allocation_request_version)
            selected_plus_alts = [selection]
            cell_uuid = selected_host.cell_uuid
            # This will populate the alternates with many of the same unclaimed
            # hosts. This is OK, as it should be rare for a build to fail. And
            # if there are not enough hosts to fully populate the alternates,
            # it's fine to return fewer than we'd like. Note that we exclude
            # any claimed host from consideration as an alternate because it
            # will have had its resources reduced and will have a much lower
            # chance of being able to fit another instance on it.
            for host in hosts:
                if len(selected_plus_alts) >= num_alts + 1:
                    break
                if host.cell_uuid == cell_uuid and host not in selected_hosts:
                    if alloc_reqs_by_rp_uuid is not None:
                        alt_uuid = host.uuid
                        if alt_uuid not in alloc_reqs_by_rp_uuid:
                            msg = ("A host state with uuid = '%s' that did "
                                   "not have a matching allocation_request "
                                   "was encountered while scheduling. This "
                                   "host was skipped.")
                            LOG.debug(msg, alt_uuid)
                            continue

                        # TODO(jaypipes): Loop through all allocation_requests
                        # instead of just trying the first one. For now, since
                        # we'll likely want to order the allocation_requests in
                        # the future based on information in the provider
                        # summaries, we'll just try to claim resources using
                        # the first allocation_request
                        alloc_req = alloc_reqs_by_rp_uuid[alt_uuid][0]
                        alt_selection = (
                            objects.Selection.from_host_state(host, alloc_req,
                                    allocation_request_version))
                    else:
                        alt_selection = objects.Selection.from_host_state(host)
                    selected_plus_alts.append(alt_selection)
            selections_to_return.append(selected_plus_alts)
        return selections_to_return

    def _get_sorted_hosts(self, spec_obj, host_states, index):
        """Returns a list of HostState objects that match the required
        scheduling constraints for the request spec object and have been sorted
        according to the weighers.
        """
        filtered_hosts = self.host_manager.get_filtered_hosts(host_states,
            spec_obj, index)

        LOG.debug("Filtered %(hosts)s", {'hosts': filtered_hosts})

        if not filtered_hosts:
            return []

        weighed_hosts = self.host_manager.get_weighed_hosts(filtered_hosts,
            spec_obj)
        if CONF.filter_scheduler.shuffle_best_same_weighed_hosts:
            # NOTE(pas-ha) Randomize best hosts, relying on weighed_hosts
            # being already sorted by weight in descending order.
            # This decreases possible contention and rescheduling attempts
            # when there is a large number of hosts having the same best
            # weight, especially so when host_subset_size is 1 (default)
            best_hosts = [w for w in weighed_hosts
                          if w.weight == weighed_hosts[0].weight]
            random.shuffle(best_hosts)
            weighed_hosts = best_hosts + weighed_hosts[len(best_hosts):]
        # Log the weighed hosts before stripping off the wrapper class so that
        # the weight value gets logged.
        LOG.debug("Weighed %(hosts)s", {'hosts': weighed_hosts})
        # Strip off the WeighedHost wrapper class...
        weighed_hosts = [h.obj for h in weighed_hosts]

        # We randomize the first element in the returned list to alleviate
        # congestion where the same host is consistently selected among
        # numerous potential hosts for similar request specs.
        host_subset_size = CONF.filter_scheduler.host_subset_size
        if host_subset_size < len(weighed_hosts):
            weighed_subset = weighed_hosts[0:host_subset_size]
        else:
            weighed_subset = weighed_hosts
        chosen_host = random.choice(weighed_subset)
        weighed_hosts.remove(chosen_host)
        return [chosen_host] + weighed_hosts

    def _get_all_host_states(self, context, spec_obj, provider_summaries):
        """Template method, so a subclass can implement caching."""
        # NOTE(jaypipes): provider_summaries being None is treated differently
        # from an empty dict. provider_summaries is None when we want to grab
        # all compute nodes, for instance when using the caching scheduler.
        # The provider_summaries variable will be an empty dict when the
        # Placement API found no providers that match the requested
        # constraints, which in turn makes compute_uuids an empty list and
        # get_host_states_by_uuids will return an empty generator-iterator
        # also, which will eventually result in a NoValidHost error.
        compute_uuids = None
        if provider_summaries is not None:
            compute_uuids = list(provider_summaries.keys())
        return self.host_manager.get_host_states_by_uuids(context,
                                                          compute_uuids,
                                                          spec_obj)

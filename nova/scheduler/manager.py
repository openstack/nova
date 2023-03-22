# Copyright (c) 2010 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Scheduler Service
"""

import collections
import copy
import random

from keystoneauth1 import exceptions as ks_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_service import periodic_task

from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.i18n import _
from nova import manager
from nova import objects
from nova.objects import fields as fields_obj
from nova.objects import host_mapping as host_mapping_obj
from nova import quota
from nova import rpc
from nova.scheduler.client import report
from nova.scheduler import host_manager
from nova.scheduler import request_filter
from nova.scheduler import utils
from nova import servicegroup

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS

HOST_MAPPING_EXISTS_WARNING = False


class SchedulerManager(manager.Manager):
    """Chooses a host to run instances on.

    Filters and weighs compute hosts to determine the best host to schedule an
    instance to.
    """

    target = messaging.Target(version='4.5')

    _sentinel = object()

    def __init__(self, *args, **kwargs):
        self.host_manager = host_manager.HostManager()
        self.servicegroup_api = servicegroup.API()
        self.notifier = rpc.get_notifier('scheduler')
        self._placement_client = None

        try:
            # Test our placement client during initialization
            self.placement_client
        except (ks_exc.EndpointNotFound,
                ks_exc.DiscoveryFailure,
                ks_exc.RequestTimeout,
                ks_exc.GatewayTimeout,
                ks_exc.ConnectFailure) as e:
            # Non-fatal, likely transient (although not definitely);
            # continue startup but log the warning so that when things
            # fail later, it will be clear why we can not do certain
            # things.
            LOG.warning('Unable to initialize placement client (%s); '
                        'Continuing with startup, but scheduling '
                        'will not be possible.', e)
        except (ks_exc.MissingAuthPlugin,
                ks_exc.Unauthorized) as e:
            # This is almost definitely fatal mis-configuration. The
            # Unauthorized error might be transient, but it is
            # probably reasonable to consider it fatal.
            LOG.error('Fatal error initializing placement client; '
                      'config is incorrect or incomplete: %s', e)
            raise
        except Exception as e:
            # Unknown/unexpected errors here are fatal
            LOG.error('Fatal error initializing placement client: %s', e)
            raise

        super().__init__(service_name='scheduler', *args, **kwargs)

    @property
    def placement_client(self):
        return report.report_client_singleton()

    @periodic_task.periodic_task(
        spacing=CONF.scheduler.discover_hosts_in_cells_interval,
        run_immediately=True)
    def _discover_hosts_in_cells(self, context):
        global HOST_MAPPING_EXISTS_WARNING
        try:
            host_mappings = host_mapping_obj.discover_hosts(context)
            if host_mappings:
                LOG.info(
                    'Discovered %(count)i new hosts: %(hosts)s',
                    {
                        'count': len(host_mappings),
                        'hosts': ','.join([
                            '%s:%s' % (hm.cell_mapping.name, hm.host)
                            for hm in host_mappings
                        ]),
                    },
                )
        except exception.HostMappingExists as exp:
            msg = (
                'This periodic task should only be enabled on a single '
                'scheduler to prevent collisions between multiple '
                'schedulers: %s' % str(exp)
            )
            if not HOST_MAPPING_EXISTS_WARNING:
                LOG.warning(msg)
                HOST_MAPPING_EXISTS_WARNING = True
            else:
                LOG.debug(msg)

    def reset(self):
        # NOTE(tssurya): This is a SIGHUP handler which will reset the cells
        # and enabled cells caches in the host manager. So every time an
        # existing cell is disabled or enabled or a new cell is created, a
        # SIGHUP signal has to be sent to the scheduler for proper scheduling.
        # NOTE(mriedem): Similarly there is a host-to-cell cache which should
        # be reset if a host is deleted from a cell and "discovered" in another
        # cell.
        self.host_manager.refresh_cells_caches()

    @messaging.expected_exceptions(exception.NoValidHost)
    def select_destinations(
        self, context, request_spec=None,
        filter_properties=None, spec_obj=_sentinel, instance_uuids=None,
        return_objects=False, return_alternates=False,
    ):
        """Returns destinations(s) best suited for this RequestSpec.

        Starting in Queens, this method returns a list of lists of Selection
        objects, with one list for each requested instance. Each instance's
        list will have its first element be the Selection object representing
        the chosen host for the instance, and if return_alternates is True,
        zero or more alternate objects that could also satisfy the request. The
        number of alternates is determined by the configuration option
        `CONF.scheduler.max_attempts`.

        The ability of a calling method to handle this format of returned
        destinations is indicated by a True value in the parameter
        `return_objects`. However, there may still be some older conductors in
        a deployment that have not been updated to Queens, and in that case
        return_objects will be False, and the result will be a list of dicts
        with 'host', 'nodename' and 'limits' as keys. When return_objects is
        False, the value of return_alternates has no effect. The reason there
        are two kwarg parameters return_objects and return_alternates is so we
        can differentiate between callers that understand the Selection object
        format but *don't* want to get alternate hosts, as is the case with the
        conductors that handle certain move operations.
        """
        LOG.debug("Starting to schedule for instances: %s", instance_uuids)

        # TODO(sbauza): Change the method signature to only accept a spec_obj
        # argument once API v5 is provided.
        if spec_obj is self._sentinel:
            spec_obj = objects.RequestSpec.from_primitives(
                context, request_spec, filter_properties)

        is_rebuild = utils.request_is_rebuild(spec_obj)
        alloc_reqs_by_rp_uuid, provider_summaries, allocation_request_version \
            = None, None, None
        if not is_rebuild:
            try:
                request_filter.process_reqspec(context, spec_obj)
            except exception.RequestFilterFailed as e:
                raise exception.NoValidHost(reason=e.message)

            resources = utils.resources_from_request_spec(
                context, spec_obj, self.host_manager,
                enable_pinning_translate=True)
            res = self.placement_client.get_allocation_candidates(
                context, resources)
            if res is None:
                # We have to handle the case that we failed to connect to the
                # Placement service and the safe_connect decorator on
                # get_allocation_candidates returns None.
                res = None, None, None

            alloc_reqs, provider_summaries, allocation_request_version = res
            alloc_reqs = alloc_reqs or []
            provider_summaries = provider_summaries or {}

            # if the user requested pinned CPUs, we make a second query to
            # placement for allocation candidates using VCPUs instead of PCPUs.
            # This is necessary because users might not have modified all (or
            # any) of their compute nodes meaning said compute nodes will not
            # be reporting PCPUs yet. This is okay to do because the
            # NUMATopologyFilter (scheduler) or virt driver (compute node) will
            # weed out hosts that are actually using new style configuration
            # but simply don't have enough free PCPUs (or any PCPUs).
            # TODO(stephenfin): Remove when we drop support for 'vcpu_pin_set'
            if (
                resources.cpu_pinning_requested and
                not CONF.workarounds.disable_fallback_pcpu_query
            ):
                LOG.debug(
                    'Requesting fallback allocation candidates with '
                    'VCPU instead of PCPU'
                )
                resources = utils.resources_from_request_spec(
                    context, spec_obj, self.host_manager,
                    enable_pinning_translate=False)
                res = self.placement_client.get_allocation_candidates(
                    context, resources)
                if res:
                    # merge the allocation requests and provider summaries from
                    # the two requests together
                    alloc_reqs_fallback, provider_summaries_fallback, _ = res

                    alloc_reqs.extend(alloc_reqs_fallback)
                    provider_summaries.update(provider_summaries_fallback)

            if not alloc_reqs:
                LOG.info(
                    "Got no allocation candidates from the Placement API. "
                    "This could be due to insufficient resources or a "
                    "temporary occurrence as compute nodes start up."
                )
                raise exception.NoValidHost(reason="")

            # Build a dict of lists of allocation requests, keyed by
            # provider UUID, so that when we attempt to claim resources for
            # a host, we can grab an allocation request easily
            alloc_reqs_by_rp_uuid = collections.defaultdict(list)
            for ar in alloc_reqs:
                for rp_uuid in ar['allocations']:
                    alloc_reqs_by_rp_uuid[rp_uuid].append(ar)

        # Only return alternates if both return_objects and return_alternates
        # are True.
        return_alternates = return_alternates and return_objects

        selections = self._select_destinations(
            context, spec_obj, instance_uuids, alloc_reqs_by_rp_uuid,
            provider_summaries, allocation_request_version, return_alternates)

        # If `return_objects` is False, we need to convert the selections to
        # the older format, which is a list of host state dicts.
        if not return_objects:
            selection_dicts = [sel[0].to_dict() for sel in selections]
            return jsonutils.to_primitive(selection_dicts)

        return selections

    def _select_destinations(
        self, context, spec_obj, instance_uuids,
        alloc_reqs_by_rp_uuid, provider_summaries,
        allocation_request_version=None, return_alternates=False,
    ):
        self.notifier.info(
            context, 'scheduler.select_destinations.start',
            {'request_spec': spec_obj.to_legacy_request_spec_dict()})
        compute_utils.notify_about_scheduler_action(
            context=context, request_spec=spec_obj,
            action=fields_obj.NotificationAction.SELECT_DESTINATIONS,
            phase=fields_obj.NotificationPhase.START)

        # Only return alternates if both return_objects and return_alternates
        # are True.
        selections = self._schedule(
            context, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, provider_summaries,
            allocation_request_version, return_alternates)

        self.notifier.info(
            context, 'scheduler.select_destinations.end',
            {'request_spec': spec_obj.to_legacy_request_spec_dict()})
        compute_utils.notify_about_scheduler_action(
            context=context, request_spec=spec_obj,
            action=fields_obj.NotificationAction.SELECT_DESTINATIONS,
            phase=fields_obj.NotificationPhase.END)

        return selections

    def _schedule(
        self, context, spec_obj, instance_uuids, alloc_reqs_by_rp_uuid,
        provider_summaries, allocation_request_version=None,
        return_alternates=False
    ):
        """Returns a list of lists of Selection objects.

        :param context: The RequestContext object
        :param spec_obj: The RequestSpec object
        :param instance_uuids: List of instance UUIDs to place or move.
        :param alloc_reqs_by_rp_uuid: Optional dict, keyed by resource provider
            UUID, of the allocation_requests that may be used to claim
            resources against matched hosts. If None, indicates either the
            placement API wasn't reachable or that there were no
            allocation_requests returned by the placement API. If the latter,
            the provider_summaries will be an empty dict, not None.
        :param provider_summaries: Optional dict, keyed by resource provider
            UUID, of information that will be used by the filters/weighers in
            selecting matching hosts for a request. If None, indicates that
            we should grab all compute node information locally
            and that the Placement API is not used. If an empty dict, indicates
            the Placement API returned no potential matches for the requested
            resources.
        :param allocation_request_version: The microversion used to request the
            allocations.
        :param return_alternates: When True, zero or more alternate hosts are
            returned with each selected host. The number of alternates is
            determined by the configuration option
            `CONF.scheduler.max_attempts`.
        """
        elevated = context.elevated()

        # Find our local list of acceptable hosts by repeatedly
        # filtering and weighing our options. Each time we choose a
        # host, we virtually consume resources on it so subsequent
        # selections can adjust accordingly.

        def hosts_with_alloc_reqs(hosts_gen):
            """Extend the HostState objects returned by the generator with
            the allocation requests of that host
            """
            for host in hosts_gen:
                host.allocation_candidates = copy.deepcopy(
                    alloc_reqs_by_rp_uuid[host.uuid])
                yield host

        # Note: remember, we are using a generator-iterator here. So only
        # traverse this list once. This can bite you if the hosts
        # are being scanned in a filter or weighing function.
        hosts = self._get_all_host_states(
            elevated, spec_obj, provider_summaries)

        # alloc_reqs_by_rp_uuid is None during rebuild, so this mean we cannot
        # run filters that are using allocation candidates during rebuild
        if alloc_reqs_by_rp_uuid is not None:
            # wrap the generator to extend the HostState objects with the
            # allocation requests for that given host. This is needed to
            # support scheduler filters filtering on allocation candidates.
            hosts = hosts_with_alloc_reqs(hosts)

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
        num_alts = CONF.scheduler.max_attempts - 1 if return_alternates else 0

        if instance_uuids is None or alloc_reqs_by_rp_uuid is None:
            # If there was a problem communicating with the
            # placement API, alloc_reqs_by_rp_uuid will be None, so we skip
            # claiming in that case as well. In the case where instance_uuids
            # is None, that indicates an older conductor, so we need to return
            # the objects without alternates. They will be converted back to
            # the older dict format representing HostState objects.
            # TODO(stephenfin): Remove this when we bump scheduler the RPC API
            # version to 5.0
            # NOTE(gibi): We cannot remove this branch as it is actively used
            # when nova calls the scheduler during rebuild (not evacuate) to
            # check if the current host is still good for the new image used
            # for the rebuild. In this case placement cannot be used to
            # generate candidates as that would require space on the current
            # compute for double allocation. So no allocation candidates for
            # rebuild and therefore alloc_reqs_by_rp_uuid is None
            return self._legacy_find_hosts(
                context, num_instances, spec_obj, hosts, num_alts,
                instance_uuids=instance_uuids)

        # A list of the instance UUIDs that were successfully claimed against
        # in the placement API. If we are not able to successfully claim for
        # all involved instances, we use this list to remove those allocations
        # before returning
        claimed_instance_uuids = []

        # The list of hosts that have been selected (and claimed).
        claimed_hosts = []

        # The allocation request allocated on the given claimed host
        claimed_alloc_reqs = []

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
                if not host.allocation_candidates:
                    LOG.debug(
                        "The nova scheduler removed every allocation candidate"
                        "for host %s so this host was skipped.",
                        host
                    )
                    continue

                # TODO(jaypipes): Loop through all allocation_requests instead
                # of just trying the first one. For now, since we'll likely
                # want to order the allocation_requests in the future based on
                # information in the provider summaries, we'll just try to
                # claim resources using the first allocation_request
                alloc_req = host.allocation_candidates[0]
                if utils.claim_resources(
                    elevated, self.placement_client, spec_obj, instance_uuid,
                    alloc_req,
                    allocation_request_version=allocation_request_version,
                ):
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
            claimed_alloc_reqs.append(alloc_req)

            # update the provider mapping in the request spec based
            # on the allocated candidate as the _consume_selected_host depends
            # on this information to temporally consume PCI devices tracked in
            # placement
            for request_group in spec_obj.requested_resources:
                request_group.provider_uuids = alloc_req[
                    'mappings'][request_group.requester_id]

            # Now consume the resources so the filter/weights will change for
            # the next instance.
            self._consume_selected_host(
                claimed_host, spec_obj, instance_uuid=instance_uuid)

        # Check if we were able to fulfill the request. If not, this call will
        # raise a NoValidHost exception.
        self._ensure_sufficient_hosts(
            context, claimed_hosts, num_instances, claimed_instance_uuids)

        # We have selected and claimed hosts for each instance along with a
        # claimed allocation request. Now we need to find alternates for each
        # host.
        return self._get_alternate_hosts(
            claimed_hosts,
            spec_obj,
            hosts,
            num,
            num_alts,
            alloc_reqs_by_rp_uuid,
            allocation_request_version,
            claimed_alloc_reqs,
        )

    def _ensure_sufficient_hosts(
        self, context, hosts, required_count, claimed_uuids=None,
    ):
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
        LOG.debug(
            'There are %(hosts)d hosts available but '
            '%(required_count)d instances requested to build.',
            {'hosts': len(hosts), 'required_count': required_count})
        reason = _('There are not enough hosts available.')
        raise exception.NoValidHost(reason=reason)

    def _cleanup_allocations(self, context, instance_uuids):
        """Removes allocations for the supplied instance UUIDs."""
        if not instance_uuids:
            return

        LOG.debug("Cleaning up allocations for %s", instance_uuids)
        for uuid in instance_uuids:
            self.placement_client.delete_allocation_for_instance(
                context, uuid, force=True)

    def _legacy_find_hosts(
        self, context, num_instances, spec_obj, hosts, num_alts,
        instance_uuids=None,
    ):
        """Find hosts without invoking placement.

        We may not be able to claim if the Placement service is not reachable.
        Additionally, we may be working with older conductors that don't pass
        in instance_uuids.
        """
        # The list of hosts selected for each instance
        selected_hosts = []

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
            self._consume_selected_host(
                selected_host, spec_obj, instance_uuid=instance_uuid)

        # Check if we were able to fulfill the request. If not, this call will
        # raise a NoValidHost exception.
        self._ensure_sufficient_hosts(context, selected_hosts, num_instances)

        # This the overall list of values to be returned. There will be one
        # item per instance, and each item will be a list of Selection objects
        # representing the selected host along with zero or more alternates
        # from the same cell.
        return self._get_alternate_hosts(
            selected_hosts, spec_obj, hosts, num, num_alts)

    @staticmethod
    def _consume_selected_host(selected_host, spec_obj, instance_uuid=None):
        LOG.debug(
            "Selected host: %(host)s", {'host': selected_host},
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
                selected_host.instances[instance_uuid] = objects.Instance(
                    uuid=instance_uuid)

    def _get_alternate_hosts(
        self, selected_hosts, spec_obj, hosts, index, num_alts,
        alloc_reqs_by_rp_uuid=None, allocation_request_version=None,
        selected_alloc_reqs=None,
    ):
        """Generate the main Selection and possible alternate Selection
        objects for each "instance".

        :param selected_hosts: This is a list of HostState objects. Each
            HostState represents the main selection for a given instance being
            scheduled (we can have multiple instances during multi create).
        :param selected_alloc_reqs: This is a list of allocation requests that
            are already allocated in placement for the main Selection for each
            instance. This list is matching with selected_hosts by index. So
            for the first instance the selected host is selected_host[0] and
            the already allocated placement candidate is
            selected_alloc_reqs[0].
        """
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
        for i, selected_host in enumerate(selected_hosts):
            # This is the list of hosts for one particular instance.
            if alloc_reqs_by_rp_uuid:
                selected_alloc_req = selected_alloc_reqs[i]
            else:
                selected_alloc_req = None

            selection = objects.Selection.from_host_state(
                selected_host, allocation_request=selected_alloc_req,
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

                # TODO(gibi): In theory we could generate alternatives on the
                # same host if that host has different possible allocation
                # candidates for the request. But we don't do that today
                if host.cell_uuid == cell_uuid and host not in selected_hosts:
                    if alloc_reqs_by_rp_uuid is not None:
                        if not host.allocation_candidates:
                            msg = ("A host state with uuid = '%s' that did "
                                   "not have any remaining allocation_request "
                                   "was encountered while scheduling. This "
                                   "host was skipped.")
                            LOG.debug(msg, host.uuid)
                            continue

                        # TODO(jaypipes): Loop through all allocation_requests
                        # instead of just trying the first one. For now, since
                        # we'll likely want to order the allocation_requests in
                        # the future based on information in the provider
                        # summaries, we'll just try to claim resources using
                        # the first allocation_request
                        # NOTE(gibi): we are using, and re-using, allocation
                        # candidates for alternatives here. This is OK as
                        # these candidates are not yet allocated in placement
                        # and we don't know if an alternate will ever be used.
                        # To increase our success we could try to use different
                        # candidate for different alternative though.
                        alloc_req = host.allocation_candidates[0]
                        alt_selection = objects.Selection.from_host_state(
                            host, alloc_req, allocation_request_version)
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

        weighed_hosts = self.host_manager.get_weighed_hosts(
            filtered_hosts, spec_obj)
        if CONF.filter_scheduler.shuffle_best_same_weighed_hosts:
            # NOTE(pas-ha) Randomize best hosts, relying on weighed_hosts
            # being already sorted by weight in descending order.
            # This decreases possible contention and rescheduling attempts
            # when there is a large number of hosts having the same best
            # weight, especially so when host_subset_size is 1 (default)
            best_hosts = [
                w for w in weighed_hosts
                if w.weight == weighed_hosts[0].weight
            ]
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
        # The provider_summaries variable will be an empty dict when the
        # Placement API found no providers that match the requested
        # constraints, which in turn makes compute_uuids an empty list and
        # get_host_states_by_uuids will return an empty generator-iterator
        # also, which will eventually result in a NoValidHost error.
        compute_uuids = None
        if provider_summaries is not None:
            compute_uuids = list(provider_summaries.keys())
        return self.host_manager.get_host_states_by_uuids(
            context, compute_uuids, spec_obj)

    def update_aggregates(self, ctxt, aggregates):
        """Updates HostManager internal aggregates information.

        :param aggregates: Aggregate(s) to update
        :type aggregates: :class:`nova.objects.Aggregate`
            or :class:`nova.objects.AggregateList`
        """
        # NOTE(sbauza): We're dropping the user context now as we don't need it
        self.host_manager.update_aggregates(aggregates)

    def delete_aggregate(self, ctxt, aggregate):
        """Deletes HostManager internal information about a specific aggregate.

        :param aggregate: Aggregate to delete
        :type aggregate: :class:`nova.objects.Aggregate`
        """
        # NOTE(sbauza): We're dropping the user context now as we don't need it
        self.host_manager.delete_aggregate(aggregate)

    def update_instance_info(self, context, host_name, instance_info):
        """Receives information about changes to a host's instances, and
        updates the HostManager with that information.
        """
        self.host_manager.update_instance_info(
            context, host_name, instance_info)

    def delete_instance_info(self, context, host_name, instance_uuid):
        """Receives information about the deletion of one of a host's
        instances, and updates the HostManager with that information.
        """
        self.host_manager.delete_instance_info(
            context, host_name, instance_uuid)

    def sync_instance_info(self, context, host_name, instance_uuids):
        """Receives a sync request from a host, and passes it on to the
        HostManager.
        """
        self.host_manager.sync_instance_info(
            context, host_name, instance_uuids)

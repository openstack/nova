# Copyright 2019 SAP SE
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
BigVM service
"""
import itertools

import os_resource_classes as orc
import os_traits
from oslo_log import log as logging
from oslo_messaging import exceptions as oslo_exceptions
from oslo_service import periodic_task

import nova.conf
from nova import context as nova_context
from nova import exception
from nova import manager
from nova.objects.aggregate import AggregateList
from nova.objects.cell_mapping import CellMappingList
from nova.objects.compute_node import ComputeNodeList
from nova.objects.host_mapping import HostMappingList
from nova.scheduler.client.report import get_placement_request_id
from nova.scheduler.client.report import NESTED_PROVIDER_API_VERSION
from nova.scheduler.client.report import SchedulerReportClient
from nova.scheduler.utils import ResourceRequest
from nova import utils
from nova.utils import BIGVM_EXCLUSIVE_TRAIT
from nova.virt.vmwareapi import special_spawning

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

MEMORY_MB = orc.MEMORY_MB
BIGVM_RESOURCE = special_spawning.BIGVM_RESOURCE
BIGVM_DISABLED_TRAIT = 'CUSTOM_BIGVM_DISABLED'
MEMORY_RESERVABLE_MB_RESOURCE = utils.MEMORY_RESERVABLE_MB_RESOURCE
VMWARE_HV_TYPE = 'VMware vCenter Server'
SHARD_PREFIX = 'vc-'
HV_SIZE_BUCKET_THRESHOLD_PERCENT = 10


class BigVmManager(manager.Manager):
    """Takes care of the needs of big VMs"""

    def __init__(self, *args, **kwargs):
        self.placement_client = SchedulerReportClient()
        self.special_spawn_rpc = special_spawning.SpecialVmSpawningInterface()

        super(BigVmManager, self).__init__(service_name='bigvm',
                                           *args, **kwargs)

    @periodic_task.periodic_task(spacing=CONF.
                                 prepare_empty_host_for_spawning_interval,
                                 run_immediately=True)
    def _prepare_empty_host_for_spawning(self, context):
        """Handle freeing up hosts per hv_size per VC for spawning

        The general workflow is:
        1) Find all hypervisor sizes (hv_size) existing in a vCenter (VC)
           within an availability zone (az).
        2) Choose one host per hv_size per VC and create a child resource
           provider (rp) for it with a well-known name. This marks that
           host as responsible for the hv_size in that VC. The child rp has no
           resources, yet. This also triggers the vmware-driver to free up a
           host in the cluster.
        3) Either directly or in the next iteration every host without
           resources is checked for its status by calling the vmware
           driver. If we're done freeing up the host, we add the
           BIGVM_RESOURCE to the child rp to make it consumable.
        4) In every iteration, we check for reserved BIGVM_RESOURCEs on a
           child rp and if the host is still free. Reserving a resource happens
           after consumption, so we know the host is not longer free and have
           to clean up the child rp and the vmware part. The host might be used
           again if a migration happened in the background. We need to clean up
           the child rp in this case and redo the scheduling.

        We only want to fill up cluster memory to a certain point, configurable
        via bigvm_cluster_max_usage_percent and
        bigvm_cluster_max_reservation_percent. Resource-providers having more
        RAM usage or -reservation than those two respectively, will not be used
        for an hv_size - if they are not exclusively used for HANA flavors.
        Additionally, we check in every iteration, if we have to give up a
        freed-up host, because the cluster reached one of the limits.
        """
        client = self.placement_client

        # make sure our custom trait exists
        client._ensure_traits(context, [BIGVM_DISABLED_TRAIT,
                                        BIGVM_EXCLUSIVE_TRAIT])

        vcenters, bigvm_providers, vmware_providers = \
            self._get_providers(context)

        self._check_and_clean_providers(context, client, bigvm_providers,
                                        vmware_providers)

        missing_hv_sizes_per_vc = self._get_missing_hv_sizes(context,
            vcenters, bigvm_providers, vmware_providers)

        if not any(missing_hv_sizes_per_vc.values()):
            LOG.info('Free host for spawning defined for every '
                     'vCenter and hypervisor-size.')
            return

        def _flatten(list_of_lists):
            return itertools.chain.from_iterable(list_of_lists)

        # retrieve allocation candidates for all hv sizes. we later have to
        # filter them by VC, because our placement doesn't know about VCs.
        candidates = {}
        for hv_size in set(_flatten(missing_hv_sizes_per_vc.values())):
            resources = ResourceRequest()
            resources._add_resource(MEMORY_MB, hv_size)
            res = client.get_allocation_candidates(context, resources)
            if res is None:
                continue
            alloc_reqs, provider_summaries, allocation_request_version = res

            # filter out providers, that don't match the full host, e.g. don't
            # allow 3 TB on a 6 TB host, as we need a fully free host
            provider_summaries = {p: d for p, d in provider_summaries.items()
                    if vmware_providers.get(p, {}).get('hv_size') == hv_size}

            if not provider_summaries:
                LOG.warning('Could not find enough resources to free up a '
                            'host for hypervisor size %(hv_size)d.',
                            {'hv_size': hv_size})
                continue

            # filter out providers that are too full already
            filtered_provider_summaries = {}
            for p, d in provider_summaries.items():
                # Hosts exclusively used for hana_* flavors cannot be too full
                if BIGVM_EXCLUSIVE_TRAIT in d['traits']:
                    filtered_provider_summaries[p] = d
                    continue

                used = vmware_providers.get(p, {})\
                        .get('memory_mb_used_percent', 100)
                reserved = vmware_providers.get(p, {})\
                            .get('memory_reservable_mb_used_percent', 100)
                if (used > CONF.bigvm_cluster_max_usage_percent or
                    reserved > CONF.bigvm_cluster_max_reservation_percent):
                    continue
                filtered_provider_summaries[p] = d

            if not filtered_provider_summaries:
                LOG.warning('Could not find a resource-provider to free up a '
                            'host for hypervisor size %(hv_size)d, because '
                            'all clusters are already using more than '
                            '%(max_used)d%% of total memory or reserving more '
                            'than %(max_reserved)d%% of reservable memory.',
                            {'hv_size': hv_size,
                             'max_used': CONF.bigvm_cluster_max_usage_percent,
                             'max_reserved':
                                CONF.bigvm_cluster_max_reservation_percent})
                continue

            # filter out providers that are disabled in general or for bigVMs
            # specifically
            provider_summaries = filtered_provider_summaries
            filtered_provider_summaries = {}
            for p, d in provider_summaries.items():
                if os_traits.COMPUTE_STATUS_DISABLED in d['traits'] \
                        or BIGVM_DISABLED_TRAIT in d['traits']:
                    continue
                filtered_provider_summaries[p] = d

            if not filtered_provider_summaries:
                LOG.warning('Could not find a resource-provider to free up a '
                            'host for hypervisor size %(hv_size)d, because '
                            'all providers with enough space are disabled.',
                            {'hv_size': hv_size})
                continue

            candidates[hv_size] = (alloc_reqs, filtered_provider_summaries)

        for vc in vcenters:
            for hv_size in missing_hv_sizes_per_vc[vc]:
                if hv_size not in candidates:
                    LOG.warning('Could not find a resource-provider to free '
                                'up a host for hypervisor size %(hv_size)d in '
                                '%(vc)s.',
                                {'hv_size': hv_size, 'vc': vc})
                    continue
                alloc_reqs, provider_summaries = candidates[hv_size]

                # filter providers by VC, as placement returned all matching
                # providers
                providers = {p: d for p, d in provider_summaries.items()
                        if vmware_providers.get(p, {}).get('vc') == vc}

                # select the one with the least usage
                def _free_memory(p):
                    memory = providers[p]['resources'][MEMORY_MB]
                    return memory['capacity'] - memory['used']

                provider_uuids = sorted((p for p in providers),
                                        key=_free_memory, reverse=True)

                try:
                    for rp_uuid in provider_uuids:
                        host = vmware_providers[rp_uuid]['host']
                        cm = vmware_providers[rp_uuid]['cell_mapping']
                        with nova_context.target_cell(context, cm) as cctxt:
                            if self._free_host_for_provider(cctxt, rp_uuid,
                                                            host):
                                break
                except oslo_exceptions.MessagingTimeout as e:
                    # we don't know if the timeout happened after we started
                    # freeing a host already or because we couldn't reach the
                    # nova-compute node. Therefore, we move on to the next HV
                    # size for that VC and hope the timeout resolves for the
                    # next run.
                    LOG.exception(e)
                    LOG.warning('Skipping HV size %(hv_size)s in VC %(vc)s '
                                'because of error',
                                {'hv_size': hv_size, 'vc': vc})

    def _get_providers(self, context):
        """Return our special and the basic vmware resource-providers

        This returns a list of vcenters and two dicts, where the
        resource-provider uuid is the key.  The value contains a dict with the
        important information for each resource-provider, like host, az, vc and
        cell_mapping + either the hypervisor size (vmware provider) or the
        resource-provider dict (special provider).
        """
        client = self.placement_client

        vmware_hvs = {}
        for cm in CellMappingList.get_all(context):
            with nova_context.target_cell(context, cm) as cctxt:
                vmware_hvs.update({cn.uuid: cn.host for cn in
                    ComputeNodeList.get_by_hypervisor_type(cctxt,
                                                           VMWARE_HV_TYPE)
                    if not cn.deleted})

        host_azs = {}
        host_vcs = {}
        for agg in AggregateList.get_all(context):
            if not agg.availability_zone:
                continue

            if agg.name == agg.availability_zone:
                for host in agg.hosts:
                    host_azs[host] = agg.name
            elif agg.name.startswith(SHARD_PREFIX):
                for host in agg.hosts:
                    host_vcs[host] = agg.name

        vcenters = set(host_vcs.values())

        host_mappings = {hm.host: hm.cell_mapping
                         for hm in HostMappingList.get_all(context)}

        # find all resource-providers that we added and also a list of vmware
        # resource-providers
        bigvm_providers = {}
        vmware_providers = {}
        resp = client.get('/resource_providers',
                          version=NESTED_PROVIDER_API_VERSION)
        for rp in resp.json()['resource_providers']:
            if rp['name'].startswith(CONF.bigvm_deployment_rp_name_prefix):
                # We use the _root_ RP and not the parent because that will
                # always map to the ComputeNode, even if we decide to nest RPs
                # further.
                host_rp_uuid = rp['root_provider_uuid']
                host = vmware_hvs[host_rp_uuid]
                cell_mapping = host_mappings[host]
                bigvm_providers[rp['uuid']] = {'rp': rp,
                                               'host': host,
                                               'az': host_azs[host],
                                               'vc': host_vcs[host],
                                               'cell_mapping': cell_mapping,
                                               'host_rp_uuid': host_rp_uuid}
            elif rp['uuid'] not in vmware_hvs:  # ignore baremetal
                continue
            else:
                # retrieve inventory for MEMORY_MB & MEMORY_RESERVABLE_MB info
                url = '/resource_providers/{}/inventories'.format(rp['uuid'])
                resp = client.get(url)
                if resp.status_code != 200:
                    LOG.error('Could not retrieve inventory for RP %(rp)s.',
                              {'rp': rp['uuid']})
                    continue
                inventory = resp.json()["inventories"]
                # Note(jakobk): It's possible to encounter incomplete (e.g.
                # in-buildup) resource providers here, that don't have all the
                # usual resources set.
                memory_mb_inventory = inventory.get(MEMORY_MB)
                if not memory_mb_inventory:
                    LOG.info('no %(mem_res)s resource in RP %(rp)s',
                             {'mem_res': MEMORY_MB, 'rp': rp['uuid']})
                    continue
                memory_reservable_mb_inventory = inventory.get(
                    MEMORY_RESERVABLE_MB_RESOURCE)
                if not memory_reservable_mb_inventory:
                    LOG.debug('no %(memreserv_res)s in resource provider'
                              ' %(rp)s',
                              {'memreserv_res': MEMORY_RESERVABLE_MB_RESOURCE,
                               'rp': rp['uuid']})
                    continue

                # retrieve the usage
                url = '/resource_providers/{}/usages'
                resp = client.get(url.format(rp['uuid']))
                if resp.status_code != 200:
                    LOG.error('Could not retrieve usages for RP %(rp)s.',
                              {'rp': rp['uuid']})
                    continue
                usages = resp.json()['usages']

                hv_size = memory_mb_inventory['max_unit']
                memory_mb_total = (memory_mb_inventory['total'] -
                                   memory_mb_inventory['reserved'])
                try:
                    memory_mb_used_percent = (usages[MEMORY_MB] / float(
                                              memory_mb_total) * 100)
                except ZeroDivisionError:
                    LOG.warning('memory_mb_total is 0 for resource provider '
                                '%s', rp['uuid'])
                    memory_mb_used_percent = 100

                memory_reservable_mb_total = (
                    memory_reservable_mb_inventory['total'] -
                    memory_reservable_mb_inventory['reserved'])
                try:
                    memory_reservable_mb_used_percent = (
                        usages.get(MEMORY_RESERVABLE_MB_RESOURCE, 0) / float(
                        memory_reservable_mb_total) * 100)
                except ZeroDivisionError:
                    LOG.info('memory_reservable_mb_total is 0 for resource '
                             'provider %s', rp['uuid'])
                    memory_reservable_mb_used_percent = 100

                host = vmware_hvs[rp['uuid']]
                # ignore hypervisors we would never use anyways
                if hv_size < CONF.bigvm_mb:
                    LOG.debug('Ignoring %(host)s (%(hv_size)s < %(bigvm_mb)s)',
                              {'host': host, 'hv_size': hv_size,
                               'bigvm_mb': CONF.bigvm_mb})
                    continue

                cell_mapping = host_mappings[host]
                if host not in host_azs or host not in host_vcs:
                    # seen this happening during buildup
                    LOG.debug('Ignoring %(host)s as it is not assigned to an '
                              'AZ or VC.',
                              {'host': host})
                    continue

                # retrieve traits so we can find disabled and hana exclusive
                # hosts
                traits = client.get_provider_traits(context, rp['uuid'])
                vmware_providers[rp['uuid']] = {
                    'hv_size': hv_size,
                    'host': host,
                    'az': host_azs[host],
                    'vc': host_vcs[host],
                    'cell_mapping': cell_mapping,
                    'traits': traits,
                    'memory_mb_used_percent': memory_mb_used_percent,
                    'memory_reservable_mb_used_percent':
                        memory_reservable_mb_used_percent}

            # make sure the placement cache is filled
            client.get_provider_tree_and_ensure_root(context, rp['uuid'],
                                                     rp['name'])

        # retrieve all bigvm provider's inventories
        for rp_uuid, rp in bigvm_providers.items():
            inventory = client._get_inventory(context, rp_uuid)
            rp['inventory'] = inventory['inventories'] if inventory else {}

        # make sure grouping by hv_size works properly later on, even if there
        # are marginal differences in the reported hv_size. we need to have all
        # vmware_providers to have the same hv_size if they're in the same
        # "bucket", e.g. they're supposed to be 3 TB HVs. To make sure the
        # placement query for allocation-candidates works, we use the smallest
        # size and assign it to all in the same bucket.
        hv_size_bucket = None
        for rp_uuid, rp in sorted(vmware_providers.items(),
                                  key=lambda x: x[1]['hv_size']):
            if hv_size_bucket is None:
                # first one is always a new bucket
                hv_size_bucket = rp['hv_size']
                continue

            threshold = HV_SIZE_BUCKET_THRESHOLD_PERCENT * hv_size_bucket / 100
            if rp['hv_size'] - hv_size_bucket > threshold:
                # set key if the difference to the last key is over the
                # threshold
                hv_size_bucket = rp['hv_size']

            rp['hv_size'] = hv_size_bucket

        return (vcenters, bigvm_providers, vmware_providers)

    def _check_and_clean_providers(self, context, client, bigvm_providers,
                                   vmware_providers):

        # check for reserved resources which indicate that the free host was
        # consumed
        providers_to_delete = {rp_uuid: rp
                               for rp_uuid, rp in bigvm_providers.items()
                               if rp['inventory'].get(BIGVM_RESOURCE, {})
                                                 .get('reserved')}

        # check if we don't have a valid vmware provider for it (anymore) and
        # thus cannot be a valid provider ourselves
        providers_to_delete.update({
            rp_uuid: rp for rp_uuid, rp in bigvm_providers.items()
            if rp_uuid not in providers_to_delete and
               rp['host_rp_uuid'] not in vmware_providers})

        # check for resource-providers having more than
        # bigvm_cluster_max_usage_percent usage
        for rp_uuid, rp in bigvm_providers.items():
            if rp_uuid in providers_to_delete:
                # no need to check if we already remove it anyways
                continue

            host_rp = vmware_providers[rp['host_rp_uuid']]
            # Hosts exclusively used for hana_* flavors cannot be too full
            if BIGVM_EXCLUSIVE_TRAIT in host_rp['traits']:
                continue

            used_percent = host_rp['memory_mb_used_percent']
            if used_percent > CONF.bigvm_cluster_max_usage_percent:
                providers_to_delete[rp_uuid] = rp
                LOG.info('Resource-provider %(host_rp_uuid)s with free host '
                         'is overused on regular memory usage. Marking '
                         '%(rp_uuid)s for deletion.',
                         {'host_rp_uuid': rp['host_rp_uuid'],
                          'rp_uuid': rp_uuid})
                continue

            reserved_percent = host_rp['memory_reservable_mb_used_percent']
            if reserved_percent > CONF.bigvm_cluster_max_reservation_percent:
                providers_to_delete[rp_uuid] = rp
                LOG.info('Resource-provider %(host_rp_uuid)s with free host '
                         'is overused on reserved memory usage. Marking '
                         '%(rp_uuid)s for deletion.',
                         {'host_rp_uuid': rp['host_rp_uuid'],
                          'rp_uuid': rp_uuid})

        # check if a provider got used in the background without our knowledge
        for rp_uuid, rp in bigvm_providers.items():
            if rp_uuid in providers_to_delete:
                # no need to check if we already remove it anyways
                continue

            # if we have no resources on the resource-provider, we don't expect
            # it to be free, yet
            if not rp['inventory'].get(BIGVM_RESOURCE, {}):
                continue

            # ask the compute-node if the host is still free. anything other
            # than FREE_HOST_STATE_DONE means we've got an unexpected state and
            # should re-schedule that size
            cm = rp['cell_mapping']
            with nova_context.target_cell(context, cm) as cctxt:
                state = self.special_spawn_rpc.free_host(cctxt, rp['host'])
                if state != special_spawning.FREE_HOST_STATE_DONE:
                    LOG.info('Checking on already freed up host %(host)s '
                             'returned with state %(state)s. Marking '
                             '%(rp_uuid)s for deletion.',
                             {'host': rp['host'],
                              'state': state,
                              'rp_uuid': rp_uuid})
                    providers_to_delete[rp_uuid] = rp

        # check if a provider was disabled by now
        for rp_uuid, rp in bigvm_providers.items():
            if rp_uuid in providers_to_delete:
                # no need to check if we already remove it anyways
                continue

            host_rp = vmware_providers[rp['host_rp_uuid']]
            if os_traits.COMPUTE_STATUS_DISABLED in host_rp['traits'] \
                    or BIGVM_DISABLED_TRAIT in host_rp['traits']:
                providers_to_delete[rp_uuid] = rp
                LOG.info('Resource-provider %(host_rp_uuid)s got disabled in'
                         ' general or specifically for bigVMs. Marking'
                         ' %(rp_uuid)s for deletion.',
                         {'host_rp_uuid': rp['host_rp_uuid'],
                          'rp_uuid': rp_uuid})

        for rp_uuid, rp in providers_to_delete.items():
            self._clean_up_consumed_provider(context, rp_uuid, rp)

        # clean up our list of resource-providers from consumed or overused
        # hosts
        for rp_uuid in providers_to_delete:
            del bigvm_providers[rp_uuid]

    def _get_allocations_for_consumer(self, context, consumer_uuid):
        """Same as SchedulerReportClient.get_allocations_for_consumer() but
        includes user_id and project_id in the returned values, by doing the
        request with a newer version.
        """
        client = self.placement_client
        url = '/allocations/%s' % consumer_uuid
        resp = client.get(url, global_request_id=context.global_id,
                          version=1.17)
        if not resp:
            return {}
        else:
            return resp.json()

    def _remove_provider_from_consumer_allocations(self, context,
                                                   consumer_uuid, rp_uuid):
        """This is basically the same as
        SchedulerClient.remove_provider_from_instance_allocation, but without
        the resize-on-same-host detection - it simply removes the provider from
        the allocations of the consumer.
        """
        client = self.placement_client

        # get the allocation details, because we need user_id and
        # project_id to call the delete function
        current_allocs = \
            self._get_allocations_for_consumer(context, consumer_uuid)

        LOG.debug('Found the following allocations for consumer '
                  '%(consumer_uuid)s: %(allocations)s',
                  {'consumer_uuid': consumer_uuid,
                   'allocations': current_allocs})

        new_allocs = [
            {
                'resource_provider': {
                    'uuid': alloc_rp_uuid,
                },
                'resources': alloc['resources'],
            }
            for alloc_rp_uuid, alloc in current_allocs['allocations'].items()
            if alloc_rp_uuid != rp_uuid
        ]
        payload = {'allocations': new_allocs,
                   'project_id': current_allocs['project_id'],
                   'user_id': current_allocs['user_id']}
        LOG.debug("Sending updated allocation %s for instance %s after "
                  "removing resources for %s.",
                  new_allocs, consumer_uuid, rp_uuid)
        url = '/allocations/%s' % consumer_uuid
        r = client.put(url, payload, version='1.10',
                     global_request_id=context.global_id)
        if r.status_code != 204:
            LOG.warning("Failed to save allocation for %s. Got HTTP %s: %s",
                        consumer_uuid, r.status_code, r.text)
        return r.status_code == 204

    def _clean_up_consumed_provider(self, context, rp_uuid, rp):
        """Clean up after a resource-provider was consumed

        We need to remove all allocations, the resource-provider itself and
        also the hostgroup from the vCenter.
        """
        client = self.placement_client

        # find the consumer
        allocations = client.get_allocations_for_resource_provider(
                                                context, rp_uuid).allocations
        # we might have already deleted them and got killed or the VM got
        # deleted in the mean time
        failures = 0
        for consumer_uuid, resources in allocations.items():
            # delete the allocations
            # we can't use
            # SchedulerClient.remove_provider_from_instance_allocation here, as
            # this would detect a resize and try to remove the resources, but
            # keep an allocation. We need the specific allocation for our
            # resource-provider removed.
            if self._remove_provider_from_consumer_allocations(context,
                                                    consumer_uuid, rp_uuid):
                LOG.info('Removed bigvm allocations for %(consumer_uuid)s '
                         'from RP', {'consumer_uuid': consumer_uuid})
            else:
                LOG.error('Could not remove bigvm allocations for '
                          '%(consumer_uuid)s corresponding RP.',
                          {'consumer_uuid': consumer_uuid})
                failures += 1

        if failures:
            # skip removing the resource-provider because we couldn't
            # remove all allocations. we'll retry on the next run
            LOG.warning('Skippping removal of resource-provider '
                        '%(rp_uuid)s as we could not remove some '
                        'allocations.',
                        {'rp_uuid': rp_uuid})
            return

        # remove the hostgroup from the host
        cm = rp['cell_mapping']
        with nova_context.target_cell(context, cm) as cctxt:
            if not self.special_spawn_rpc.remove_host_from_hostgroup(cctxt,
                                                            rp['host']):
                LOG.warning('Skipping removal of resource-provider '
                            '%(rp_uuid)s as we could not remove the hostgroup '
                            'from the vCenter.',
                            {'rp_uuid': rp_uuid})
                return

        # delete the resource-provider
        client._delete_provider(rp_uuid)
        LOG.info('Removed resource-provider %(rp_uuid)s.',
                 {'rp_uuid': rp_uuid})

    def _get_missing_hv_sizes(self, context, vcenters,
                              bigvm_providers, vmware_providers):
        """Search and return hypervisor sizes having no freed-up host

        Returns a dict containing a set of hv sizes missing a freed-up host for
        each vCenter.
        """
        found_hv_sizes_per_vc = {vc: set() for vc in vcenters}

        for rp_uuid, rp in bigvm_providers.items():
            host_rp_uuid = rp['host_rp_uuid']
            hv_size = vmware_providers[host_rp_uuid]['hv_size']
            found_hv_sizes_per_vc[rp['vc']].add(hv_size)

            # if there are no resources in that resource-provider, it means,
            # that we started freeing up a host. We have to check the process
            # state and add the resources once it's done.
            if not rp['inventory'].get(BIGVM_RESOURCE):
                cm = rp['cell_mapping']
                with nova_context.target_cell(context, cm) as cctxt:
                    state = self.special_spawn_rpc.free_host(cctxt, rp['host'])

                if state == special_spawning.FREE_HOST_STATE_DONE:
                    self._add_resources_to_provider(context, rp_uuid, rp)
                elif state == special_spawning.FREE_HOST_STATE_ERROR:
                    LOG.warning('Freeing a host for spawning failed on '
                                '%(host)s.',
                                {'host': rp['host']})
                    # do some cleanup, so another compute-node is used
                    found_hv_sizes_per_vc[rp['vc']].remove(hv_size)
                    self._clean_up_consumed_provider(context, rp_uuid, rp)
                else:
                    LOG.info('Waiting for host on %(host)s to free up.',
                             {'host': rp['host']})

        hv_sizes_per_vc = {
            vc: set(rp['hv_size'] for rp in vmware_providers.values()
                    if rp['vc'] == vc)
            for vc in vcenters}

        missing_hv_sizes_per_vc = {
            vc: hv_sizes_per_vc[vc] - found_hv_sizes_per_vc[vc]
            for vc in vcenters}

        return missing_hv_sizes_per_vc

    def _add_resources_to_provider(self, context, rp_uuid, rp):
        """Add our custom resources to the provider so they can be consumed.

        This should be called once the host is freed up in the cluster.
        """
        client = self.placement_client
        inv_data = {BIGVM_RESOURCE: {
            # we use 2 here so we can reserve 1 later. in queens we can't
            # reserve $total
            'max_unit': 2, 'min_unit': 2, 'total': 2}}

        client._ensure_resource_provider(
            context, rp_uuid, rp['rp']['name'],
            parent_provider_uuid=rp['host_rp_uuid'])
        try:
            client.set_inventory_for_provider(context, rp_uuid, inv_data)
        except Exception as err:
            LOG.error('Adding inventory to the resource-provider for '
                      'spawning on %(host)s failed: %(err)s',
                      {'host': rp['host'], 'err': err})
        else:
            LOG.info('Added inventory to the resource-provider for spawning '
                     'on %(host)s.',
                     {'host': rp['host']})

    def _free_host_for_provider(self, context, rp_uuid, host):
        """Takes care of creating a child resource provider in placement to
        "claim" a resource-provider/host for freeing up a host. Then calls the
        driver to actually free up the host in the cluster.
        """
        client = self.placement_client
        needs_cleanup = True
        new_rp_uuid = None
        try:
            # TODO(jkulik) try to reserve the necessary memory for freeing a
            # full hypervisor

            # create a child resource-provider
            new_rp_name = '{}-{}'.format(CONF.bigvm_deployment_rp_name_prefix,
                                         host)
            # this is basically copied from placement client, but we don't want
            # to set the uuid manually which it doesn't support
            url = "/resource_providers"
            payload = {
                'name': new_rp_name,
                'parent_provider_uuid': rp_uuid
            }
            resp = client.post(url, payload,
                               version=NESTED_PROVIDER_API_VERSION,
                               global_request_id=context.global_id)
            placement_req_id = get_placement_request_id(resp)
            if resp.status_code == 201:
                new_rp_uuid = resp.headers['Location'].split('/')[-1]
                msg = ("[%(placement_req_id)s] Created resource provider "
                       "record via placement API for host %(host)s for "
                       "special spawning: %(rp_uuid)s")
                args = {
                    'host': host,
                    'placement_req_id': placement_req_id,
                    'rp_uuid': new_rp_uuid
                }
                LOG.info(msg, args)
            else:
                msg = ("[%(placement_req_id)s] Failed to create resource "
                       "provider record in placement API for %(host)s for "
                       "special spawning. Got %(status_code)d: %(err_text)s.")
                args = {
                    'host': host,
                    'status_code': resp.status_code,
                    'err_text': resp.text,
                    'placement_req_id': placement_req_id,
                }
                LOG.error(msg, args)
                raise exception.ResourceProviderCreationFailed(
                                                              name=new_rp_name)
            # make sure the placement cache is filled
            client.get_provider_tree_and_ensure_root(context, new_rp_uuid,
                                                     new_rp_name)

            # Remove the following once elektra doesn't look at aggregates
            # anymore to show spawnable bigvm flavors:

            # ensure the parent resource-provider has its uuid as aggregate set
            # in addition to its previous aggregates
            agg_info = client._get_provider_aggregates(context, rp_uuid)
            if rp_uuid not in agg_info.aggregates:
                agg_info.aggregates.add(rp_uuid)
                client.set_aggregates_for_provider(
                    context, rp_uuid, agg_info.aggregates,
                    generation=agg_info.generation)
            # add the newly-created resource-provider to the parent uuid's
            # aggregate
            client.set_aggregates_for_provider(context, new_rp_uuid, [rp_uuid])
            # Remove until here after elektra change.

            # find a host and let DRS free it up
            state = self.special_spawn_rpc.free_host(context, host)

            if state == special_spawning.FREE_HOST_STATE_DONE:
                # there were free resources available immediately
                needs_cleanup = False
                new_rp = {'host': host,
                          'rp': {'name': new_rp_name},
                          'host_rp_uuid': rp_uuid}
                self._add_resources_to_provider(context, new_rp_uuid, new_rp)
            elif state == special_spawning.FREE_HOST_STATE_STARTED:
                # it started working on it. we have to check back later
                # if it's done
                needs_cleanup = False
        finally:
            # clean up placement, if something went wrong
            if needs_cleanup and new_rp_uuid is not None:
                client._delete_provider(new_rp_uuid)

        return not needs_cleanup

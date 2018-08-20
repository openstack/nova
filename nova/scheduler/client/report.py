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

import collections
import contextlib
import copy
import functools
import random
import re
import retrying
import time

from keystoneauth1 import exceptions as ks_exc
import os_traits
from oslo_log import log as logging
from oslo_middleware import request_id
from oslo_utils import versionutils

from nova.compute import provider_tree
from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova import rc_fields as fields
from nova.scheduler import utils as scheduler_utils
from nova import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
VCPU = fields.ResourceClass.VCPU
MEMORY_MB = fields.ResourceClass.MEMORY_MB
DISK_GB = fields.ResourceClass.DISK_GB
_RE_INV_IN_USE = re.compile("Inventory for (.+) on resource provider "
                            "(.+) in use")
WARN_EVERY = 10
PLACEMENT_CLIENT_SEMAPHORE = 'placement_client'
CONSUMER_GENERATION_VERSION = '1.28'
GRANULAR_AC_VERSION = '1.25'
ALLOW_RESERVED_EQUAL_TOTAL_INVENTORY_VERSION = '1.26'
POST_RPS_RETURNS_PAYLOAD_API_VERSION = '1.20'
AGGREGATE_GENERATION_VERSION = '1.19'
NESTED_PROVIDER_API_VERSION = '1.14'
POST_ALLOCATIONS_API_VERSION = '1.13'

AggInfo = collections.namedtuple('AggInfo', ['aggregates', 'generation'])
TraitInfo = collections.namedtuple('TraitInfo', ['traits', 'generation'])


def warn_limit(self, msg):
    if self._warn_count:
        self._warn_count -= 1
    else:
        self._warn_count = WARN_EVERY
        LOG.warning(msg)


def safe_connect(f):
    @functools.wraps(f)
    def wrapper(self, *a, **k):
        try:
            return f(self, *a, **k)
        except ks_exc.EndpointNotFound:
            warn_limit(
                self, 'The placement API endpoint was not found.')
            # Reset client session so there is a new catalog, which
            # gets cached when keystone is first successfully contacted.
            self._client = self._create_client()
        except ks_exc.MissingAuthPlugin:
            warn_limit(
                self, 'No authentication information found for placement API.')
        except ks_exc.Unauthorized:
            warn_limit(
                self, 'Placement service credentials do not work.')
        except ks_exc.DiscoveryFailure:
            # TODO(_gryf): Looks like DiscoveryFailure is not the only missing
            # exception here. In Pike we should take care about keystoneauth1
            # failures handling globally.
            warn_limit(self,
                       'Discovering suitable URL for placement API failed.')
        except ks_exc.ConnectFailure:
            LOG.warning('Placement API service is not responding.')
    return wrapper


class Retry(Exception):
    def __init__(self, operation, reason):
        self.operation = operation
        self.reason = reason


def retries(f):
    """Decorator to retry a call three times if it raises Retry

    Note that this returns the actual value of the inner call on success
    or returns False if all the retries fail.
    """
    @functools.wraps(f)
    def wrapper(self, *a, **k):
        for retry in range(0, 4):
            try:
                sleep_time = random.uniform(0, retry * 2)
                time.sleep(sleep_time)
                return f(self, *a, **k)
            except Retry as e:
                LOG.debug(
                    'Unable to %(op)s because %(reason)s; retrying...',
                    {'op': e.operation, 'reason': e.reason})
        LOG.error('Failed scheduler client operation %s: out of retries',
                  f.__name__)
        return False
    return wrapper


def _compute_node_to_inventory_dict(compute_node):
    """Given a supplied `objects.ComputeNode` object, return a dict, keyed
    by resource class, of various inventory information.

    :param compute_node: `objects.ComputeNode` object to translate
    """
    result = {}

    # NOTE(jaypipes): Ironic virt driver will return 0 values for vcpus,
    # memory_mb and disk_gb if the Ironic node is not available/operable
    if compute_node.vcpus > 0:
        result[VCPU] = {
            'total': compute_node.vcpus,
            'reserved': CONF.reserved_host_cpus,
            'min_unit': 1,
            'max_unit': compute_node.vcpus,
            'step_size': 1,
            'allocation_ratio': compute_node.cpu_allocation_ratio,
        }
    if compute_node.memory_mb > 0:
        result[MEMORY_MB] = {
            'total': compute_node.memory_mb,
            'reserved': CONF.reserved_host_memory_mb,
            'min_unit': 1,
            'max_unit': compute_node.memory_mb,
            'step_size': 1,
            'allocation_ratio': compute_node.ram_allocation_ratio,
        }
    if compute_node.local_gb > 0:
        # TODO(johngarbutt) We should either move to reserved_host_disk_gb
        # or start tracking DISK_MB.
        reserved_disk_gb = compute_utils.convert_mb_to_ceil_gb(
            CONF.reserved_host_disk_mb)
        result[DISK_GB] = {
            'total': compute_node.local_gb,
            'reserved': reserved_disk_gb,
            'min_unit': 1,
            'max_unit': compute_node.local_gb,
            'step_size': 1,
            'allocation_ratio': compute_node.disk_allocation_ratio,
        }
    return result


def _instance_to_allocations_dict(instance):
    """Given an `objects.Instance` object, return a dict, keyed by resource
    class of the amount used by the instance.

    :param instance: `objects.Instance` object to translate
    """
    alloc_dict = scheduler_utils.resources_from_flavor(instance,
        instance.flavor)

    # Remove any zero allocations.
    return {key: val for key, val in alloc_dict.items() if val}


def _move_operation_alloc_request(source_allocs, dest_alloc_req):
    """Given existing allocations for a source host and a new allocation
    request for a destination host, return a new allocation_request that
    contains resources claimed against both source and destination, accounting
    for shared providers.

    Also accounts for a resize to the same host where the source and dest
    compute node resource providers are going to be the same. In that case
    we sum the resource allocations for the single provider.

    :param source_allocs: Dict, keyed by resource provider UUID, of resources
                          allocated on the source host
    :param dest_alloc_req: The allocation_request for resources against the
                           destination host
    """
    LOG.debug("Doubling-up allocation_request for move operation.")
    # Remove any allocations against resource providers that are
    # already allocated against on the source host (like shared storage
    # providers)
    cur_rp_uuids = set(source_allocs.keys())
    new_rp_uuids = set(dest_alloc_req['allocations']) - cur_rp_uuids

    current_allocs = {
        cur_rp_uuid: {'resources': alloc['resources']}
            for cur_rp_uuid, alloc in source_allocs.items()
    }
    new_alloc_req = {'allocations': current_allocs}
    for rp_uuid in dest_alloc_req['allocations']:
        if rp_uuid in new_rp_uuids:
            new_alloc_req['allocations'][rp_uuid] = dest_alloc_req[
                'allocations'][rp_uuid]
        elif not new_rp_uuids:
            # If there are no new_rp_uuids that means we're resizing to
            # the same host so we need to sum the allocations for
            # the compute node (and possibly shared providers) using both
            # the current and new allocations.
            # Note that we sum the allocations rather than take the max per
            # resource class between the current and new allocations because
            # the compute node/resource tracker is going to adjust for
            # decrementing any old allocations as necessary, the scheduler
            # shouldn't make assumptions about that.
            scheduler_utils.merge_resources(
                new_alloc_req['allocations'][rp_uuid]['resources'],
                dest_alloc_req['allocations'][rp_uuid]['resources'])

    LOG.debug("New allocation_request containing both source and "
              "destination hosts in move operation: %s", new_alloc_req)
    return new_alloc_req


def _extract_inventory_in_use(body):
    """Given an HTTP response body, extract the resource classes that were
    still in use when we tried to delete inventory.

    :returns: String of resource classes or None if there was no InventoryInUse
              error in the response body.
    """
    match = _RE_INV_IN_USE.search(body)
    if match:
        return match.group(1)
    return None


def get_placement_request_id(response):
    if response is not None:
        return response.headers.get(request_id.HTTP_RESP_HEADER_REQUEST_ID)


class SchedulerReportClient(object):
    """Client class for updating the scheduler."""

    def __init__(self, adapter=None):
        """Initialize the report client.

        :param adapter: A prepared keystoneauth1 Adapter for API communication.
                If unspecified, one is created based on config options in the
                [placement] section.
        """
        self._adapter = adapter
        # An object that contains a nova-compute-side cache of resource
        # provider and inventory information
        self._provider_tree = provider_tree.ProviderTree()
        # Track the last time we updated providers' aggregates and traits
        self._association_refresh_time = {}
        self._client = self._create_client()
        # NOTE(danms): Keep track of how naggy we've been
        self._warn_count = 0

    @utils.synchronized(PLACEMENT_CLIENT_SEMAPHORE)
    def _create_client(self):
        """Create the HTTP session accessing the placement service."""
        # Flush provider tree and associations so we start from a clean slate.
        self._provider_tree = provider_tree.ProviderTree()
        self._association_refresh_time = {}
        client = self._adapter or utils.get_ksa_adapter('placement')
        # Set accept header on every request to ensure we notify placement
        # service of our response body media type preferences.
        client.additional_headers = {'accept': 'application/json'}
        return client

    def get(self, url, version=None, global_request_id=None):
        headers = ({request_id.INBOUND_HEADER: global_request_id}
                   if global_request_id else {})
        return self._client.get(url, microversion=version, headers=headers)

    def post(self, url, data, version=None, global_request_id=None):
        headers = ({request_id.INBOUND_HEADER: global_request_id}
                   if global_request_id else {})
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        return self._client.post(url, json=data, microversion=version,
                                 headers=headers)

    def put(self, url, data, version=None, global_request_id=None):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        kwargs = {'microversion': version,
                  'headers': {request_id.INBOUND_HEADER:
                              global_request_id} if global_request_id else {}}
        if data is not None:
            kwargs['json'] = data
        return self._client.put(url, **kwargs)

    def delete(self, url, version=None, global_request_id=None):
        headers = ({request_id.INBOUND_HEADER: global_request_id}
                   if global_request_id else {})
        return self._client.delete(url, microversion=version, headers=headers)

    @safe_connect
    def get_allocation_candidates(self, context, resources):
        """Returns a tuple of (allocation_requests, provider_summaries,
        allocation_request_version).

        The allocation_requests are a collection of potential JSON objects that
        can be passed to the PUT /allocations/{consumer_uuid} Placement REST
        API to claim resources against one or more resource providers that meet
        the requested resource constraints.

        The provider summaries is a dict, keyed by resource provider UUID, of
        inventory and capacity information and traits for any resource
        provider involved in the allocation_requests.

        :returns: A tuple with a list of allocation_request dicts, a dict of
                  provider information, and the microversion used to request
                  this data from placement, or (None, None, None) if the
                  request failed

        :param context: The security context
        :param nova.scheduler.utils.ResourceRequest resources:
            A ResourceRequest object representing the requested resources,
            traits, and aggregates from the request spec.

        Example member_of (aggregates) value in resources:

            [('foo', 'bar'), ('baz',)]

        translates to:

            "Candidates are in either 'foo' or 'bar', but definitely in 'baz'"

        """
        version = GRANULAR_AC_VERSION
        qparams = resources.to_querystring()
        url = "/allocation_candidates?%s" % qparams
        resp = self.get(url, version=version,
                        global_request_id=context.global_id)
        if resp.status_code == 200:
            data = resp.json()
            return (data['allocation_requests'], data['provider_summaries'],
                    version)

        args = {
            'resource_request': str(resources),
            'status_code': resp.status_code,
            'err_text': resp.text,
        }
        msg = ("Failed to retrieve allocation candidates from placement "
               "API for filters: %(resource_request)s\n"
               "Got %(status_code)d: %(err_text)s.")
        LOG.error(msg, args)
        return None, None, None

    @safe_connect
    def _get_provider_aggregates(self, context, rp_uuid):
        """Queries the placement API for a resource provider's aggregates.

        :param rp_uuid: UUID of the resource provider to grab aggregates for.
        :return: A namedtuple comprising:
                    * .aggregates: A set() of string aggregate UUIDs, which may
                      be empty if the specified provider is associated with no
                      aggregates.
                    * .generation: The resource provider generation.
        :raise: ResourceProviderAggregateRetrievalFailed on errors.  In
                particular, we raise this exception (as opposed to returning
                None or the empty set()) if the specified resource provider
                does not exist.
        """
        resp = self.get("/resource_providers/%s/aggregates" % rp_uuid,
                        version=AGGREGATE_GENERATION_VERSION,
                        global_request_id=context.global_id)
        if resp.status_code == 200:
            data = resp.json()
            return AggInfo(aggregates=set(data['aggregates']),
                           generation=data['resource_provider_generation'])

        placement_req_id = get_placement_request_id(resp)
        msg = ("[%(placement_req_id)s] Failed to retrieve aggregates from "
               "placement API for resource provider with UUID %(uuid)s. "
               "Got %(status_code)d: %(err_text)s.")
        args = {
            'placement_req_id': placement_req_id,
            'uuid': rp_uuid,
            'status_code': resp.status_code,
            'err_text': resp.text,
        }
        LOG.error(msg, args)
        raise exception.ResourceProviderAggregateRetrievalFailed(uuid=rp_uuid)

    @safe_connect
    def _get_provider_traits(self, context, rp_uuid):
        """Queries the placement API for a resource provider's traits.

        :param context: The security context
        :param rp_uuid: UUID of the resource provider to grab traits for.
        :return: A namedtuple comprising:
                    * .traits: A set() of string trait names, which may be
                      empty if the specified provider has no traits.
                    * .generation: The resource provider generation.
        :raise: ResourceProviderTraitRetrievalFailed on errors.  In particular,
                we raise this exception (as opposed to returning None or the
                empty set()) if the specified resource provider does not exist.
        """
        resp = self.get("/resource_providers/%s/traits" % rp_uuid,
                        version='1.6', global_request_id=context.global_id)

        if resp.status_code == 200:
            json = resp.json()
            return TraitInfo(traits=set(json['traits']),
                             generation=json['resource_provider_generation'])

        placement_req_id = get_placement_request_id(resp)
        LOG.error(
            "[%(placement_req_id)s] Failed to retrieve traits from "
            "placement API for resource provider with UUID %(uuid)s. Got "
            "%(status_code)d: %(err_text)s.",
            {'placement_req_id': placement_req_id, 'uuid': rp_uuid,
             'status_code': resp.status_code, 'err_text': resp.text})
        raise exception.ResourceProviderTraitRetrievalFailed(uuid=rp_uuid)

    @safe_connect
    def _get_resource_provider(self, context, uuid):
        """Queries the placement API for a resource provider record with the
        supplied UUID.

        :param context: The security context
        :param uuid: UUID identifier for the resource provider to look up
        :return: A dict of resource provider information if found or None if no
                 such resource provider could be found.
        :raise: ResourceProviderRetrievalFailed on error.
        """
        resp = self.get("/resource_providers/%s" % uuid,
                        version=NESTED_PROVIDER_API_VERSION,
                        global_request_id=context.global_id)
        if resp.status_code == 200:
            data = resp.json()
            return data
        elif resp.status_code == 404:
            return None
        else:
            placement_req_id = get_placement_request_id(resp)
            msg = ("[%(placement_req_id)s] Failed to retrieve resource "
                   "provider record from placement API for UUID %(uuid)s. Got "
                   "%(status_code)d: %(err_text)s.")
            args = {
                'uuid': uuid,
                'status_code': resp.status_code,
                'err_text': resp.text,
                'placement_req_id': placement_req_id,
            }
            LOG.error(msg, args)
            raise exception.ResourceProviderRetrievalFailed(uuid=uuid)

    @safe_connect
    def _get_sharing_providers(self, context, agg_uuids):
        """Queries the placement API for a list of the resource providers
        associated with any of the specified aggregates and possessing the
        MISC_SHARES_VIA_AGGREGATE trait.

        :param context: The security context
        :param agg_uuids: Iterable of string UUIDs of aggregates to filter on.
        :return: A list of dicts of resource provider information, which may be
                 empty if no provider exists with the specified UUID.
        :raise: ResourceProviderRetrievalFailed on error.
        """
        if not agg_uuids:
            return []

        aggs = ','.join(agg_uuids)
        url = "/resource_providers?member_of=in:%s&required=%s" % (
            aggs, os_traits.MISC_SHARES_VIA_AGGREGATE)
        resp = self.get(url, version='1.18',
                        global_request_id=context.global_id)
        if resp.status_code == 200:
            return resp.json()['resource_providers']

        msg = _("[%(placement_req_id)s] Failed to retrieve sharing resource "
                "providers associated with the following aggregates from "
                "placement API: %(aggs)s. Got %(status_code)d: %(err_text)s.")
        args = {
            'aggs': aggs,
            'status_code': resp.status_code,
            'err_text': resp.text,
            'placement_req_id': get_placement_request_id(resp),
        }
        LOG.error(msg, args)
        raise exception.ResourceProviderRetrievalFailed(message=msg % args)

    @safe_connect
    def _get_providers_in_tree(self, context, uuid):
        """Queries the placement API for a list of the resource providers in
        the tree associated with the specified UUID.

        :param context: The security context
        :param uuid: UUID identifier for the resource provider to look up
        :return: A list of dicts of resource provider information, which may be
                 empty if no provider exists with the specified UUID.
        :raise: ResourceProviderRetrievalFailed on error.
        """
        resp = self.get("/resource_providers?in_tree=%s" % uuid,
                        version=NESTED_PROVIDER_API_VERSION,
                        global_request_id=context.global_id)

        if resp.status_code == 200:
            return resp.json()['resource_providers']

        # Some unexpected error
        placement_req_id = get_placement_request_id(resp)
        msg = ("[%(placement_req_id)s] Failed to retrieve resource provider "
               "tree from placement API for UUID %(uuid)s. Got "
               "%(status_code)d: %(err_text)s.")
        args = {
            'uuid': uuid,
            'status_code': resp.status_code,
            'err_text': resp.text,
            'placement_req_id': placement_req_id,
        }
        LOG.error(msg, args)
        raise exception.ResourceProviderRetrievalFailed(uuid=uuid)

    @safe_connect
    def _create_resource_provider(self, context, uuid, name,
                                  parent_provider_uuid=None):
        """Calls the placement API to create a new resource provider record.

        :param context: The security context
        :param uuid: UUID of the new resource provider
        :param name: Name of the resource provider
        :param parent_provider_uuid: Optional UUID of the immediate parent
        :return: A dict of resource provider information object representing
                 the newly-created resource provider.
        :raise: ResourceProviderCreationFailed or
                ResourceProviderRetrievalFailed on error.
        """
        url = "/resource_providers"
        payload = {
            'uuid': uuid,
            'name': name,
        }
        if parent_provider_uuid is not None:
            payload['parent_provider_uuid'] = parent_provider_uuid

        # Bug #1746075: First try the microversion that returns the new
        # provider's payload.
        resp = self.post(url, payload,
                         version=POST_RPS_RETURNS_PAYLOAD_API_VERSION,
                         global_request_id=context.global_id)

        placement_req_id = get_placement_request_id(resp)

        if resp:
            msg = ("[%(placement_req_id)s] Created resource provider record "
                   "via placement API for resource provider with UUID "
                   "%(uuid)s and name %(name)s.")
            args = {
                'uuid': uuid,
                'name': name,
                'placement_req_id': placement_req_id,
            }
            LOG.info(msg, args)
            return resp.json()

        # TODO(efried): Push error codes from placement, and use 'em.
        name_conflict = 'Conflicting resource provider name:'
        if resp.status_code == 409 and name_conflict not in resp.text:
            # Another thread concurrently created a resource provider with the
            # same UUID. Log a warning and then just return the resource
            # provider object from _get_resource_provider()
            msg = ("[%(placement_req_id)s] Another thread already created a "
                   "resource provider with the UUID %(uuid)s. Grabbing that "
                   "record from the placement API.")
            args = {
                'uuid': uuid,
                'placement_req_id': placement_req_id,
            }
            LOG.info(msg, args)
            return self._get_resource_provider(context, uuid)

        # A provider with the same *name* already exists, or some other error.
        msg = ("[%(placement_req_id)s] Failed to create resource provider "
               "record in placement API for UUID %(uuid)s. Got "
               "%(status_code)d: %(err_text)s.")
        args = {
            'uuid': uuid,
            'status_code': resp.status_code,
            'err_text': resp.text,
            'placement_req_id': placement_req_id,
        }
        LOG.error(msg, args)
        raise exception.ResourceProviderCreationFailed(name=name)

    def _ensure_resource_provider(self, context, uuid, name=None,
                                  parent_provider_uuid=None):
        """Ensures that the placement API has a record of a resource provider
        with the supplied UUID. If not, creates the resource provider record in
        the placement API for the supplied UUID, passing in a name for the
        resource provider.

        If found or created, the provider's UUID is returned from this method.
        If the resource provider for the supplied uuid was not found and the
        resource provider record could not be created in the placement API, an
        exception is raised.

        If this method returns successfully, callers are assured that the
        placement API contains a record of the provider; and that the local
        cache of resource provider information contains a record of:
        - The specified provider
        - All providers in its tree
        - All providers associated via aggregate with all providers in said
          tree
        and for each of those providers:
        - The UUIDs of its aggregates
        - The trait strings associated with the provider

        Note that if the provider did not exist prior to this call, the above
        reduces to just the specified provider as a root, with no aggregates or
        traits.

        :param context: The security context
        :param uuid: UUID identifier for the resource provider to ensure exists
        :param name: Optional name for the resource provider if the record
                     does not exist. If empty, the name is set to the UUID
                     value
        :param parent_provider_uuid: Optional UUID of the immediate parent,
                                     which must have been previously _ensured.
        """
        # NOTE(efried): We currently have no code path where we need to set the
        # parent_provider_uuid on a previously-parent-less provider - so we do
        # NOT handle that scenario here.
        # TODO(efried): Reinstate this optimization if possible.
        # For now, this is removed due to the following:
        # - update_provider_tree adds a child with some bogus inventory (bad
        #   resource class) or trait (invalid trait name).
        # - update_from_provider_tree creates the child in placement and adds
        #   it to the cache, then attempts to add the bogus inventory/trait.
        #   The latter fails, so update_from_provider_tree invalidates the
        #   cache entry by removing the child from the cache.
        # - Ordinarily, we would rely on the code below (_get_providers_in_tree
        #   and _provider_tree.populate_from_iterable) to restore the child to
        #   the cache on the next iteration.  BUT since the root is still
        #   present in the cache, the commented-out block will cause that part
        #   of this method to be skipped.
        # if self._provider_tree.exists(uuid):
        #     # If we had the requested provider locally, refresh it and its
        #     # descendants, but only if stale.
        #     for u in self._provider_tree.get_provider_uuids(uuid):
        #         self._refresh_associations(context, u, force=False)
        #     return uuid

        # We don't have it locally; check placement or create it.
        created_rp = None
        rps_to_refresh = self._get_providers_in_tree(context, uuid)
        if not rps_to_refresh:
            created_rp = self._create_resource_provider(
                context, uuid, name or uuid,
                parent_provider_uuid=parent_provider_uuid)
            # If @safe_connect can't establish a connection to the placement
            # service, like if placement isn't running or nova-compute is
            # mis-configured for authentication, we'll get None back and need
            # to treat it like we couldn't create the provider (because we
            # couldn't).
            if created_rp is None:
                raise exception.ResourceProviderCreationFailed(
                    name=name or uuid)
            # Don't add the created_rp to rps_to_refresh.  Since we just
            # created it, it has no aggregates or traits.

        self._provider_tree.populate_from_iterable(
            rps_to_refresh or [created_rp])

        # At this point, the whole tree exists in the local cache.

        for rp_to_refresh in rps_to_refresh:
            # NOTE(efried): _refresh_associations doesn't refresh inventory
            # (yet) - see that method's docstring for the why.
            self._refresh_and_get_inventory(context, rp_to_refresh['uuid'])
            self._refresh_associations(context, rp_to_refresh['uuid'],
                                       force=True)

        return uuid

    @safe_connect
    def _delete_provider(self, rp_uuid, global_request_id=None):
        resp = self.delete('/resource_providers/%s' % rp_uuid,
                           global_request_id=global_request_id)
        # Check for 404 since we don't need to warn/raise if we tried to delete
        # something which doesn"t actually exist.
        if resp or resp.status_code == 404:
            if resp:
                LOG.info("Deleted resource provider %s", rp_uuid)
            # clean the caches
            try:
                self._provider_tree.remove(rp_uuid)
            except ValueError:
                pass
            self._association_refresh_time.pop(rp_uuid, None)
            return

        msg = ("[%(placement_req_id)s] Failed to delete resource provider "
               "with UUID %(uuid)s from the placement API. Got "
               "%(status_code)d: %(err_text)s.")
        args = {
            'placement_req_id': get_placement_request_id(resp),
            'uuid': rp_uuid,
            'status_code': resp.status_code,
            'err_text': resp.text
        }
        LOG.error(msg, args)
        # On conflict, the caller may wish to delete allocations and
        # redrive.  (Note that this is not the same as a
        # PlacementAPIConflict case.)
        if resp.status_code == 409:
            raise exception.ResourceProviderInUse()
        raise exception.ResourceProviderDeletionFailed(uuid=rp_uuid)

    def _get_inventory(self, context, rp_uuid):
        url = '/resource_providers/%s/inventories' % rp_uuid
        result = self.get(url, global_request_id=context.global_id)
        if not result:
            return None
        return result.json()

    def _refresh_and_get_inventory(self, context, rp_uuid):
        """Helper method that retrieves the current inventory for the supplied
        resource provider according to the placement API.

        If the cached generation of the resource provider is not the same as
        the generation returned from the placement API, we update the cached
        generation and attempt to update inventory if any exists, otherwise
        return empty inventories.
        """
        curr = self._get_inventory(context, rp_uuid)
        if curr is None:
            return None

        self._provider_tree.update_inventory(
            rp_uuid, curr['inventories'],
            generation=curr['resource_provider_generation'])

        return curr

    def _refresh_associations(self, context, rp_uuid, force=False,
                              refresh_sharing=True):
        """Refresh aggregates, traits, and (optionally) aggregate-associated
        sharing providers for the specified resource provider uuid.

        Only refresh if there has been no refresh during the lifetime of
        this process, CONF.compute.resource_provider_association_refresh
        seconds have passed, or the force arg has been set to True.

        Note that we do *not* refresh inventories.  The reason is largely
        historical: all code paths that get us here are doing inventory refresh
        themselves.

        :param context: The security context
        :param rp_uuid: UUID of the resource provider to check for fresh
                        aggregates and traits
        :param force: If True, force the refresh
        :param refresh_sharing: If True, fetch all the providers associated
                                by aggregate with the specified provider,
                                including their traits and aggregates (but not
                                *their* sharing providers).
        :raise: On various placement API errors, one of:
                - ResourceProviderAggregateRetrievalFailed
                - ResourceProviderTraitRetrievalFailed
                - ResourceProviderRetrievalFailed
        """
        if force or self._associations_stale(rp_uuid):
            # Refresh aggregates
            agg_info = self._get_provider_aggregates(context, rp_uuid)
            # If @safe_connect makes the above return None, this will raise
            # TypeError. Good.
            aggs, generation = agg_info.aggregates, agg_info.generation
            msg = ("Refreshing aggregate associations for resource provider "
                   "%s, aggregates: %s")
            LOG.debug(msg, rp_uuid, ','.join(aggs or ['None']))

            # NOTE(efried): This will blow up if called for a RP that doesn't
            # exist in our _provider_tree.
            self._provider_tree.update_aggregates(
                rp_uuid, aggs, generation=generation)

            # Refresh traits
            trait_info = self._get_provider_traits(context, rp_uuid)
            # If @safe_connect makes the above return None, this will raise
            # TypeError. Good.
            traits, generation = trait_info.traits, trait_info.generation
            msg = ("Refreshing trait associations for resource provider %s, "
                   "traits: %s")
            LOG.debug(msg, rp_uuid, ','.join(traits or ['None']))
            # NOTE(efried): This will blow up if called for a RP that doesn't
            # exist in our _provider_tree.
            self._provider_tree.update_traits(
                rp_uuid, traits, generation=generation)

            if refresh_sharing:
                # Refresh providers associated by aggregate
                for rp in self._get_sharing_providers(context, aggs):
                    if not self._provider_tree.exists(rp['uuid']):
                        # NOTE(efried): Right now sharing providers are always
                        # treated as roots. This is deliberate. From the
                        # context of this compute's RP, it doesn't matter if a
                        # sharing RP is part of a tree.
                        self._provider_tree.new_root(
                            rp['name'], rp['uuid'],
                            generation=rp['generation'])
                    # Now we have to (populate or) refresh that guy's traits
                    # and aggregates (but not *his* aggregate-associated
                    # providers).  No need to override force=True for newly-
                    # added providers - the missing timestamp will always
                    # trigger them to refresh.
                    self._refresh_associations(context, rp['uuid'],
                                               force=force,
                                               refresh_sharing=False)
            self._association_refresh_time[rp_uuid] = time.time()

    def _associations_stale(self, uuid):
        """Respond True if aggregates and traits have not been refreshed
        "recently".

        Associations are stale if association_refresh_time for this uuid is not
        set or is more than CONF.compute.resource_provider_association_refresh
        seconds ago.
        """
        refresh_time = self._association_refresh_time.get(uuid, 0)
        return ((time.time() - refresh_time) >
                CONF.compute.resource_provider_association_refresh)

    def _update_inventory_attempt(self, context, rp_uuid, inv_data):
        """Update the inventory for this resource provider if needed.

        :param context: The security context
        :param rp_uuid: The resource provider UUID for the operation
        :param inv_data: The new inventory for the resource provider
        :returns: True if the inventory was updated (or did not need to be),
                  False otherwise.
        """
        # TODO(jaypipes): Should we really be calling the placement API to get
        # the current inventory for every resource provider each and every time
        # update_resource_stats() is called? :(
        curr = self._refresh_and_get_inventory(context, rp_uuid)
        if curr is None:
            return False

        cur_gen = curr['resource_provider_generation']

        # Check to see if we need to update placement's view
        if not self._provider_tree.has_inventory_changed(rp_uuid, inv_data):
            return True

        payload = {
            'resource_provider_generation': cur_gen,
            'inventories': inv_data,
        }
        url = '/resource_providers/%s/inventories' % rp_uuid
        # NOTE(vdrok): in microversion 1.26 it is allowed to have inventory
        # records with reserved value equal to total
        version = ALLOW_RESERVED_EQUAL_TOTAL_INVENTORY_VERSION
        result = self.put(url, payload, version=version,
                          global_request_id=context.global_id)
        if result.status_code == 409:
            LOG.info('[%(placement_req_id)s] Inventory update conflict for '
                     '%(resource_provider_uuid)s with generation ID '
                     '%(generation)s',
                     {'placement_req_id': get_placement_request_id(result),
                      'resource_provider_uuid': rp_uuid,
                      'generation': cur_gen})
            # NOTE(jaypipes): There may be cases when we try to set a
            # provider's inventory that results in attempting to delete an
            # inventory record for a resource class that has an active
            # allocation. We need to catch this particular case and raise an
            # exception here instead of returning False, since we should not
            # re-try the operation in this case.
            #
            # A use case for where this can occur is the following:
            #
            # 1) Provider created for each Ironic baremetal node in Newton
            # 2) Inventory records for baremetal node created for VCPU,
            #    MEMORY_MB and DISK_GB
            # 3) A Nova instance consumes the baremetal node and allocation
            #    records are created for VCPU, MEMORY_MB and DISK_GB matching
            #    the total amount of those resource on the baremetal node.
            # 3) Upgrade to Ocata and now resource tracker wants to set the
            #    provider's inventory to a single record of resource class
            #    CUSTOM_IRON_SILVER (or whatever the Ironic node's
            #    "resource_class" attribute is)
            # 4) Scheduler report client sends the inventory list containing a
            #    single CUSTOM_IRON_SILVER record and placement service
            #    attempts to delete the inventory records for VCPU, MEMORY_MB
            #    and DISK_GB. An exception is raised from the placement service
            #    because allocation records exist for those resource classes,
            #    and a 409 Conflict is returned to the compute node. We need to
            #    trigger a delete of the old allocation records and then set
            #    the new inventory, and then set the allocation record to the
            #    new CUSTOM_IRON_SILVER record.
            rc = _extract_inventory_in_use(result.text)
            if rc is not None:
                raise exception.InventoryInUse(
                    resource_classes=rc,
                    resource_provider=rp_uuid,
                )

            # Invalidate our cache and re-fetch the resource provider
            # to be sure to get the latest generation.
            self._provider_tree.remove(rp_uuid)
            # NOTE(jaypipes): We don't need to pass a name parameter to
            # _ensure_resource_provider() because we know the resource provider
            # record already exists. We're just reloading the record here.
            self._ensure_resource_provider(context, rp_uuid)
            return False
        elif not result:
            placement_req_id = get_placement_request_id(result)
            LOG.warning('[%(placement_req_id)s] Failed to update inventory '
                        'for resource provider %(uuid)s: %(status)i %(text)s',
                        {'placement_req_id': placement_req_id,
                         'uuid': rp_uuid,
                         'status': result.status_code,
                         'text': result.text})
            # log the body at debug level
            LOG.debug('[%(placement_req_id)s] Failed inventory update request '
                      'for resource provider %(uuid)s with body: %(payload)s',
                      {'placement_req_id': placement_req_id,
                       'uuid': rp_uuid,
                       'payload': payload})
            return False

        if result.status_code != 200:
            placement_req_id = get_placement_request_id(result)
            LOG.info('[%(placement_req_id)s] Received unexpected response '
                     'code %(code)i while trying to update inventory for '
                     'resource provider %(uuid)s: %(text)s',
                     {'placement_req_id': placement_req_id,
                      'uuid': rp_uuid,
                      'code': result.status_code,
                      'text': result.text})
            return False

        # Update our view of the generation for next time
        updated_inventories_result = result.json()
        new_gen = updated_inventories_result['resource_provider_generation']

        self._provider_tree.update_inventory(rp_uuid, inv_data,
                                             generation=new_gen)
        LOG.debug('Updated inventory for %s at generation %i',
                  rp_uuid, new_gen)
        return True

    @safe_connect
    def _update_inventory(self, context, rp_uuid, inv_data):
        for attempt in (1, 2, 3):
            if not self._provider_tree.exists(rp_uuid):
                # NOTE(danms): Either we failed to fetch/create the RP
                # on our first attempt, or a previous attempt had to
                # invalidate the cache, and we were unable to refresh
                # it. Bail and try again next time.
                LOG.warning('Unable to refresh my resource provider record')
                return False
            if self._update_inventory_attempt(context, rp_uuid, inv_data):
                return True
            time.sleep(1)
        return False

    def get_provider_tree_and_ensure_root(self, context, rp_uuid, name=None,
                                          parent_provider_uuid=None):
        """Returns a fresh ProviderTree representing all providers which are in
        the same tree or in the same aggregate as the specified provider,
        including their aggregates, traits, and inventories.

        If the specified provider does not exist, it is created with the
        specified UUID, name, and parent provider (which *must* already exist).

        :param context: The security context
        :param rp_uuid: UUID of the resource provider for which to populate the
                        tree.  (This doesn't need to be the UUID of the root.)
        :param name: Optional name for the resource provider if the record
                     does not exist. If empty, the name is set to the UUID
                     value
        :param parent_provider_uuid: Optional UUID of the immediate parent,
                                     which must have been previously _ensured.
        :return: A new ProviderTree object.
        """
        # TODO(efried): We would like to have the caller handle create-and/or-
        # cache-if-not-already, but the resource tracker is currently
        # structured to handle initialization and update in a single path.  At
        # some point this should be refactored, and this method can *just*
        # return a deep copy of the local _provider_tree cache.
        # (Re)populate the local ProviderTree
        self._ensure_resource_provider(
            context, rp_uuid, name=name,
            parent_provider_uuid=parent_provider_uuid)
        # Ensure inventories are up to date (for *all* cached RPs)
        for uuid in self._provider_tree.get_provider_uuids():
            self._refresh_and_get_inventory(context, uuid)
        # Return a *copy* of the tree.
        return copy.deepcopy(self._provider_tree)

    def set_inventory_for_provider(self, context, rp_uuid, rp_name, inv_data,
                                   parent_provider_uuid=None):
        """Given the UUID of a provider, set the inventory records for the
        provider to the supplied dict of resources.

        :param context: The security context
        :param rp_uuid: UUID of the resource provider to set inventory for
        :param rp_name: Name of the resource provider in case we need to create
                        a record for it in the placement API
        :param inv_data: Dict, keyed by resource class name, of inventory data
                         to set against the provider
        :param parent_provider_uuid:
                If the provider is not a root, this is required, and represents
                the UUID of the immediate parent, which is a provider for which
                this method has already been invoked.

        :raises: exc.InvalidResourceClass if a supplied custom resource class
                 name does not meet the placement API's format requirements.
        """
        self._ensure_resource_provider(
            context, rp_uuid, rp_name,
            parent_provider_uuid=parent_provider_uuid)

        # Auto-create custom resource classes coming from a virt driver
        self._ensure_resource_classes(context, set(inv_data))

        # NOTE(efried): Do not use the DELETE API introduced in microversion
        # 1.5, even if the new inventory is empty.  It provides no way of
        # sending the generation down, so no way to trigger/detect a conflict
        # if an out-of-band update occurs between when we GET the latest and
        # when we invoke the DELETE.  See bug #1746374.
        self._update_inventory(context, rp_uuid, inv_data)

    def _set_inventory_for_provider(self, context, rp_uuid, inv_data):
        """Given the UUID of a provider, set the inventory records for the
        provider to the supplied dict of resources.

        Compare and contrast with set_inventory_for_provider above.  This one
        is specially formulated for use by update_from_provider_tree.  Like the
        other method, we DO need to _ensure_resource_class - i.e. automatically
        create new resource classes specified in the inv_data.  However, UNLIKE
        the other method:
        - We don't use the DELETE API when inventory is empty, because that guy
          doesn't return content, and we need to update the cached provider
          tree with the new generation.
        - We raise exceptions (rather than returning a boolean) which are
          handled in a consistent fashion by update_from_provider_tree.
        - We don't invalidate the cache on failure.  That's controlled at a
          broader scope (based on errors from ANY of the set_*_for_provider
          methods, etc.) by update_from_provider_tree.
        - We don't retry.  In this code path, retries happen at the level of
          the resource tracker on the next iteration.
        - We take advantage of the cache and no-op if inv_data isn't different
          from what we have locally.  This is an optimization, not essential.
        - We don't _ensure_resource_provider or refresh_and_get_inventory,
          because that's already been done in the code paths leading up to
          update_from_provider_tree (by get_provider_tree).  This is an
          optimization, not essential.

        In short, this version is more in the spirit of set_traits_for_provider
        and set_aggregates_for_provider.

        :param context: The security context
        :param rp_uuid: The UUID of the provider whose inventory is to be
                        updated.
        :param inv_data: Dict, keyed by resource class name, of inventory data
                         to set for the provider.  Use None or the empty dict
                         to remove all inventory for the provider.
        :raises: InventoryInUse if inv_data indicates removal of inventory in a
                 resource class which has active allocations for this provider.
        :raises: InvalidResourceClass if inv_data contains a resource class
                 which cannot be created.
        :raises: ResourceProviderUpdateConflict if the provider's generation
                 doesn't match the generation in the cache.  Callers may choose
                 to retrieve the provider and its associations afresh and
                 redrive this operation.
        :raises: ResourceProviderUpdateFailed on any other placement API
                 failure.
        """
        # TODO(efried): Consolidate/refactor to one set_inventory_for_provider.

        # NOTE(efried): This is here because _ensure_resource_class already has
        # @safe_connect, so we don't want to decorate this whole method with it
        @safe_connect
        def do_put(url, payload):
            # NOTE(vdrok): in microversion 1.26 it is allowed to have inventory
            # records with reserved value equal to total
            return self.put(
                url, payload, global_request_id=context.global_id,
                version=ALLOW_RESERVED_EQUAL_TOTAL_INVENTORY_VERSION)

        # If not different from what we've got, short out
        if not self._provider_tree.has_inventory_changed(rp_uuid, inv_data):
            return

        # Ensure non-standard resource classes exist, creating them if needed.
        self._ensure_resource_classes(context, set(inv_data))

        url = '/resource_providers/%s/inventories' % rp_uuid
        inv_data = inv_data or {}
        generation = self._provider_tree.data(rp_uuid).generation
        payload = {
            'resource_provider_generation': generation,
            'inventories': inv_data,
        }
        resp = do_put(url, payload)

        if resp.status_code == 200:
            json = resp.json()
            self._provider_tree.update_inventory(
                rp_uuid, json['inventories'],
                generation=json['resource_provider_generation'])
            return

        # Some error occurred; log it
        msg = ("[%(placement_req_id)s] Failed to update inventory to "
               "[%(inv_data)s] for resource provider with UUID %(uuid)s.  Got "
               "%(status_code)d: %(err_text)s")
        args = {
            'placement_req_id': get_placement_request_id(resp),
            'uuid': rp_uuid,
            'inv_data': str(inv_data),
            'status_code': resp.status_code,
            'err_text': resp.text,
        }
        LOG.error(msg, args)

        if resp.status_code == 409:
            # If a conflict attempting to remove inventory in a resource class
            # with active allocations, raise InventoryInUse
            rc = _extract_inventory_in_use(resp.text)
            if rc is not None:
                raise exception.InventoryInUse(
                    resource_classes=rc,
                    resource_provider=rp_uuid,
                )
            # Other conflicts are generation mismatch: raise conflict exception
            raise exception.ResourceProviderUpdateConflict(
                uuid=rp_uuid, generation=generation, error=resp.text)

        # Otherwise, raise generic exception
        raise exception.ResourceProviderUpdateFailed(url=url, error=resp.text)

    @safe_connect
    def _ensure_traits(self, context, traits):
        """Make sure all specified traits exist in the placement service.

        :param context: The security context
        :param traits: Iterable of trait strings to ensure exist.
        :raises: TraitCreationFailed if traits contains a trait that did not
                 exist in placement, and couldn't be created.  When this
                 exception is raised, it is possible that *some* of the
                 requested traits were created.
        :raises: TraitRetrievalFailed if the initial query of existing traits
                 was unsuccessful.  In this scenario, it is guaranteed that
                 no traits were created.
        """
        if not traits:
            return

        # Query for all the requested traits.  Whichever ones we *don't* get
        # back, we need to create.
        # NOTE(efried): We don't attempt to filter based on our local idea of
        # standard traits, which may not be in sync with what the placement
        # service knows.  If the caller tries to ensure a nonexistent
        # "standard" trait, they deserve the TraitCreationFailed exception
        # they'll get.
        resp = self.get('/traits?name=in:' + ','.join(traits), version='1.6',
                        global_request_id=context.global_id)
        if resp.status_code == 200:
            traits_to_create = set(traits) - set(resp.json()['traits'])
            # Might be neat to have a batch create.  But creating multiple
            # traits will generally happen once, at initial startup, if at all.
            for trait in traits_to_create:
                resp = self.put('/traits/' + trait, None, version='1.6',
                                global_request_id=context.global_id)
                if not resp:
                    raise exception.TraitCreationFailed(name=trait,
                                                        error=resp.text)
            return

        # The initial GET failed
        msg = ("[%(placement_req_id)s] Failed to retrieve the list of traits. "
               "Got %(status_code)d: %(err_text)s")
        args = {
            'placement_req_id': get_placement_request_id(resp),
            'status_code': resp.status_code,
            'err_text': resp.text,
        }
        LOG.error(msg, args)
        raise exception.TraitRetrievalFailed(error=resp.text)

    @safe_connect
    def set_traits_for_provider(self, context, rp_uuid, traits):
        """Replace a provider's traits with those specified.

        The provider must exist - this method does not attempt to create it.

        :param context: The security context
        :param rp_uuid: The UUID of the provider whose traits are to be updated
        :param traits: Iterable of traits to set on the provider
        :raises: ResourceProviderUpdateConflict if the provider's generation
                 doesn't match the generation in the cache.  Callers may choose
                 to retrieve the provider and its associations afresh and
                 redrive this operation.
        :raises: ResourceProviderUpdateFailed on any other placement API
                 failure.
        :raises: TraitCreationFailed if traits contains a trait that did not
                 exist in placement, and couldn't be created.
        :raises: TraitRetrievalFailed if the initial query of existing traits
                 was unsuccessful.
        """
        # If not different from what we've got, short out
        if not self._provider_tree.have_traits_changed(rp_uuid, traits):
            return

        self._ensure_traits(context, traits)

        url = '/resource_providers/%s/traits' % rp_uuid
        # NOTE(efried): Don't use the DELETE API when traits is empty, because
        # that guy doesn't return content, and we need to update the cached
        # provider tree with the new generation.
        traits = list(traits) if traits else []
        generation = self._provider_tree.data(rp_uuid).generation
        payload = {
            'resource_provider_generation': generation,
            'traits': traits,
        }
        resp = self.put(url, payload, version='1.6',
                        global_request_id=context.global_id)

        if resp.status_code == 200:
            json = resp.json()
            self._provider_tree.update_traits(
                rp_uuid, json['traits'],
                generation=json['resource_provider_generation'])
            return

        # Some error occurred; log it
        msg = ("[%(placement_req_id)s] Failed to update traits to "
               "[%(traits)s] for resource provider with UUID %(uuid)s.  Got "
               "%(status_code)d: %(err_text)s")
        args = {
            'placement_req_id': get_placement_request_id(resp),
            'uuid': rp_uuid,
            'traits': ','.join(traits),
            'status_code': resp.status_code,
            'err_text': resp.text,
        }
        LOG.error(msg, args)

        # If a conflict, raise special conflict exception
        if resp.status_code == 409:
            raise exception.ResourceProviderUpdateConflict(
                uuid=rp_uuid, generation=generation, error=resp.text)

        # Otherwise, raise generic exception
        raise exception.ResourceProviderUpdateFailed(url=url, error=resp.text)

    @safe_connect
    def set_aggregates_for_provider(self, context, rp_uuid, aggregates,
            use_cache=True, generation=None):
        """Replace a provider's aggregates with those specified.

        The provider must exist - this method does not attempt to create it.

        :param context: The security context
        :param rp_uuid: The UUID of the provider whose aggregates are to be
                        updated.
        :param aggregates: Iterable of aggregates to set on the provider.
        :param use_cache: If False, indicates not to update the cache of
                          resource providers.
        :param generation: Resource provider generation. Required if use_cache
                           is False.
        :raises: ResourceProviderUpdateConflict if the provider's generation
                 doesn't match the generation in the cache.  Callers may choose
                 to retrieve the provider and its associations afresh and
                 redrive this operation.
        :raises: ResourceProviderUpdateFailed on any other placement API
                 failure.
        """
        # If a generation is specified, it trumps whatever's in the cache.
        # Otherwise...
        if generation is None:
            if use_cache:
                generation = self._provider_tree.data(rp_uuid).generation
            else:
                # Either cache or generation is required
                raise ValueError(
                    _("generation is required with use_cache=False"))

        # Check whether aggregates need updating.  We can only do this if we
        # have a cache entry with a matching generation.
        try:
            if (self._provider_tree.data(rp_uuid).generation == generation
                    and not self._provider_tree.have_aggregates_changed(
                        rp_uuid, aggregates)):
                return
        except ValueError:
            # Not found in the cache; proceed
            pass

        url = '/resource_providers/%s/aggregates' % rp_uuid
        aggregates = list(aggregates) if aggregates else []
        payload = {'aggregates': aggregates,
                   'resource_provider_generation': generation}
        resp = self.put(url, payload, version=AGGREGATE_GENERATION_VERSION,
                        global_request_id=context.global_id)

        if resp.status_code == 200:
            # Try to update the cache regardless.  If use_cache=False, ignore
            # any failures.
            try:
                data = resp.json()
                self._provider_tree.update_aggregates(
                    rp_uuid, data['aggregates'],
                    generation=data['resource_provider_generation'])
            except ValueError:
                if use_cache:
                    # The entry should've been there
                    raise
            return

        # Some error occurred; log it
        msg = ("[%(placement_req_id)s] Failed to update aggregates to "
               "[%(aggs)s] for resource provider with UUID %(uuid)s.  Got "
               "%(status_code)d: %(err_text)s")
        args = {
            'placement_req_id': get_placement_request_id(resp),
            'uuid': rp_uuid,
            'aggs': ','.join(aggregates),
            'status_code': resp.status_code,
            'err_text': resp.text,
        }

        # If a conflict, invalidate the cache and raise special exception
        if resp.status_code == 409:
            # No reason to condition cache invalidation on use_cache - if we
            # got a 409, the cache entry is still bogus if it exists; and the
            # below is a no-op if it doesn't.
            try:
                self._provider_tree.remove(rp_uuid)
            except ValueError:
                pass
            self._association_refresh_time.pop(rp_uuid, None)

            LOG.warning(msg, args)
            raise exception.ResourceProviderUpdateConflict(
                uuid=rp_uuid, generation=generation, error=resp.text)

        # Otherwise, raise generic exception
        LOG.error(msg, args)
        raise exception.ResourceProviderUpdateFailed(url=url, error=resp.text)

    @safe_connect
    def _ensure_resource_classes(self, context, names):
        """Make sure resource classes exist.

        :param context: The security context
        :param names: Iterable of string names of the resource classes to
                      check/create.  Must not be None.
        :raises: exception.InvalidResourceClass if an attempt is made to create
                 an invalid resource class.
        """
        # Placement API version that supports PUT /resource_classes/CUSTOM_*
        # to create (or validate the existence of) a consumer-specified
        # resource class.
        version = '1.7'
        to_ensure = set(n for n in names
                        if n.startswith(fields.ResourceClass.CUSTOM_NAMESPACE))

        for name in to_ensure:
            # no payload on the put request
            resp = self.put(
                "/resource_classes/%s" % name, None, version=version,
                global_request_id=context.global_id)
            if not resp:
                msg = ("Failed to ensure resource class record with placement "
                       "API for resource class %(rc_name)s. Got "
                       "%(status_code)d: %(err_text)s.")
                args = {
                    'rc_name': name,
                    'status_code': resp.status_code,
                    'err_text': resp.text,
                }
                LOG.error(msg, args)
                raise exception.InvalidResourceClass(resource_class=name)

    def update_compute_node(self, context, compute_node):
        """Creates or updates stats for the supplied compute node.

        :param context: The security context
        :param compute_node: updated nova.objects.ComputeNode to report
        :raises `exception.InventoryInUse` if the compute node has had changes
                to its inventory but there are still active allocations for
                resource classes that would be deleted by an update to the
                placement API.
        """
        self._ensure_resource_provider(context, compute_node.uuid,
                                       compute_node.hypervisor_hostname)
        inv_data = _compute_node_to_inventory_dict(compute_node)
        # NOTE(efried): Do not use the DELETE API introduced in microversion
        # 1.5, even if the new inventory is empty.  It provides no way of
        # sending the generation down, so no way to trigger/detect a conflict
        # if an out-of-band update occurs between when we GET the latest and
        # when we invoke the DELETE.  See bug #1746374.
        self._update_inventory(context, compute_node.uuid, inv_data)

    def update_from_provider_tree(self, context, new_tree):
        """Flush changes from a specified ProviderTree back to placement.

        The specified ProviderTree is compared against the local cache.  Any
        changes are flushed back to the placement service.  Upon successful
        completion, the local cache should reflect the specified ProviderTree.

        This method is best-effort and not atomic.  When exceptions are raised,
        it is possible that some of the changes have been flushed back, leaving
        the placement database in an inconsistent state.  This should be
        recoverable through subsequent calls.

        :param context: The security context
        :param new_tree: A ProviderTree instance representing the desired state
                         of providers in placement.
        :raises: ResourceProviderSyncFailed if any errors were encountered
                 attempting to perform the necessary API operations.
        """
        # NOTE(efried): We currently do not handle the "rename" case.  This is
        # where new_tree contains a provider named Y whose UUID already exists
        # but is named X.  Today the only way the consumer could accomplish
        # this is by deleting the provider and recreating it with the new name.

        @contextlib.contextmanager
        def catch_all(rp_uuid):
            """Convert all "expected" exceptions from placement API helpers to
            True or False.  Saves having to do try/except for every helper call
            below.
            """
            class Status(object):
                success = True
            s = Status()
            # TODO(efried): Make a base exception class from which all these
            # can inherit.
            helper_exceptions = (
                exception.InvalidResourceClass,
                exception.InventoryInUse,
                exception.ResourceProviderAggregateRetrievalFailed,
                exception.ResourceProviderDeletionFailed,
                exception.ResourceProviderInUse,
                exception.ResourceProviderRetrievalFailed,
                exception.ResourceProviderTraitRetrievalFailed,
                exception.ResourceProviderUpdateConflict,
                exception.ResourceProviderUpdateFailed,
                exception.TraitCreationFailed,
                exception.TraitRetrievalFailed,
            )
            try:
                yield s
            except helper_exceptions:
                s.success = False
                # Invalidate the caches
                try:
                    self._provider_tree.remove(rp_uuid)
                except ValueError:
                    pass
                self._association_refresh_time.pop(rp_uuid, None)

        # Overall indicator of success.  Will be set to False on any exception.
        success = True

        # Helper methods herein will be updating the local cache (this is
        # intentional) so we need to grab up front any data we need to operate
        # on in its "original" form.
        old_tree = self._provider_tree
        old_uuids = old_tree.get_provider_uuids()
        new_uuids = new_tree.get_provider_uuids()

        # Do provider deletion first, since it has the best chance of failing
        # for non-generation-conflict reasons (i.e. allocations).
        uuids_to_remove = set(old_uuids) - set(new_uuids)
        # We have to do deletions in bottom-up order, so we don't error
        # attempting to delete a parent who still has children.
        for uuid in reversed(old_uuids):
            if uuid not in uuids_to_remove:
                continue
            with catch_all(uuid) as status:
                self._delete_provider(uuid)
            success = success and status.success

        # Now create (or load) any "new" providers
        uuids_to_add = set(new_uuids) - set(old_uuids)
        # We have to do additions in top-down order, so we don't error
        # attempting to create a child before its parent exists.
        for uuid in new_uuids:
            if uuid not in uuids_to_add:
                continue
            provider = new_tree.data(uuid)
            with catch_all(uuid) as status:
                self._ensure_resource_provider(
                    context, uuid, name=provider.name,
                    parent_provider_uuid=provider.parent_uuid)
            success = success and status.success

        # At this point the local cache should have all the same providers as
        # new_tree.  Whether we added them or not, walk through and diff/flush
        # inventories, traits, and aggregates as necessary (the helper methods
        # are set up to check and short out when the relevant property does not
        # differ from what's in the cache).
        # If we encounter any error and remove a provider from the cache, all
        # its descendants are also removed, and set_*_for_provider methods on
        # it wouldn't be able to get started. Walking the tree in bottom-up
        # order ensures we at least try to process all of the providers.
        for uuid in reversed(new_uuids):
            pd = new_tree.data(uuid)
            with catch_all(pd.uuid) as status:
                self._set_inventory_for_provider(
                    context, pd.uuid, pd.inventory)
                self.set_aggregates_for_provider(
                    context, pd.uuid, pd.aggregates)
                self.set_traits_for_provider(context, pd.uuid, pd.traits)
            success = success and status.success

        if not success:
            raise exception.ResourceProviderSyncFailed()

    @safe_connect
    def get_allocations_for_consumer(self, context, consumer,
                                     include_generation=False):
        """Makes a GET /allocations/{consumer} call to Placement.

        :param context: The nova.context.RequestContext auth context
        :param consumer: UUID of the consumer resource
        :param include_generation: True if the response should be the
            full allocations response including ``consumer_generation`` (new
            in microversion 1.28), False if only the "allocations" dict from
            the response body should be returned.
        :returns: dict, see ``include_generation`` for details on format;
            returns None if unable to connect to Placement (see safe_connect)
        """
        url = '/allocations/%s' % consumer
        resp = self.get(
            url, version=CONSUMER_GENERATION_VERSION,
            global_request_id=context.global_id)
        if not resp:
            return {}
        else:
            # TODO(efried): refactor all callers to accept the whole response
            # so we can get rid of this condition
            if include_generation:
                return resp.json()
            return resp.json()['allocations']

    def get_allocations_for_consumer_by_provider(self, context, rp_uuid,
                                                 consumer):
        # NOTE(cdent): This trims to just the allocations being
        # used on this resource provider. In the future when there
        # are shared resources there might be other providers.
        allocations = self.get_allocations_for_consumer(context, consumer)
        if allocations is None:
            # safe_connect can return None on 404
            allocations = {}
        return allocations.get(
            rp_uuid, {}).get('resources', {})

    def _allocate_for_instance(self, context, rp_uuid, instance):
        my_allocations = _instance_to_allocations_dict(instance)
        current_allocations = self.get_allocations_for_consumer_by_provider(
            context, rp_uuid, instance.uuid)
        if current_allocations == my_allocations:
            allocstr = ','.join(['%s=%s' % (k, v)
                                 for k, v in my_allocations.items()])
            LOG.debug('Instance %(uuid)s allocations are unchanged: %(alloc)s',
                      {'uuid': instance.uuid, 'alloc': allocstr})
            return

        LOG.debug('Sending allocation for instance %s',
                  my_allocations,
                  instance=instance)
        res = self.put_allocations(context, rp_uuid, instance.uuid,
                                   my_allocations, instance.project_id,
                                   instance.user_id)
        if res:
            LOG.info('Submitted allocation for instance', instance=instance)

    # NOTE(jaypipes): Currently, this method is ONLY used in two places:
    # 1. By the scheduler to allocate resources on the selected destination
    #    hosts.
    # 2. By the conductor LiveMigrationTask to allocate resources on a forced
    #    destination host. This is a short-term fix for Pike which should be
    #    replaced in Queens by conductor calling the scheduler in the force
    #    host case.
    # This method should not be called by the resource tracker; instead, the
    # _allocate_for_instance() method is used which does not perform any
    # checking that a move operation is in place.
    @safe_connect
    @retries
    def claim_resources(self, context, consumer_uuid, alloc_request,
                        project_id, user_id, allocation_request_version=None):
        """Creates allocation records for the supplied instance UUID against
        the supplied resource providers.

        We check to see if resources have already been claimed for this
        consumer. If so, we assume that a move operation is underway and the
        scheduler is attempting to claim resources against the new (destination
        host). In order to prevent compute nodes currently performing move
        operations from being scheduled to improperly, we create a "doubled-up"
        allocation that consumes resources on *both* the source and the
        destination host during the move operation. When the move operation
        completes, the destination host (via _allocate_for_instance()) will
        end up setting allocations for the instance only on the destination
        host thereby freeing up resources on the source host appropriately.

        :param context: The security context
        :param consumer_uuid: The instance's UUID.
        :param alloc_request: The JSON body of the request to make to the
                              placement's PUT /allocations API
        :param project_id: The project_id associated with the allocations.
        :param user_id: The user_id associated with the allocations.
        :param allocation_request_version: The microversion used to request the
                                           allocations.
        :returns: True if the allocations were created, False otherwise.
        """
        # Older clients might not send the allocation_request_version, so
        # default to 1.10.
        # TODO(alex_xu): In the rocky, all the client should send the
        # allocation_request_version. So remove this default value.
        allocation_request_version = allocation_request_version or '1.10'
        # Ensure we don't change the supplied alloc request since it's used in
        # a loop within the scheduler against multiple instance claims
        ar = copy.deepcopy(alloc_request)

        # If the allocation_request_version less than 1.12, then convert the
        # allocation array format to the dict format. This conversion can be
        # remove in Rocky release.
        if versionutils.convert_version_to_tuple(
                allocation_request_version) < (1, 12):
            ar = {
                'allocations': {
                    alloc['resource_provider']['uuid']: {
                        'resources': alloc['resources']
                    } for alloc in ar['allocations']
                }
            }
            allocation_request_version = '1.12'

        url = '/allocations/%s' % consumer_uuid

        payload = ar

        # We first need to determine if this is a move operation and if so
        # create the "doubled-up" allocation that exists for the duration of
        # the move operation against both the source and destination hosts
        r = self.get(url, global_request_id=context.global_id)
        if r.status_code == 200:
            current_allocs = r.json()['allocations']
            if current_allocs:
                payload = _move_operation_alloc_request(current_allocs, ar)

        payload['project_id'] = project_id
        payload['user_id'] = user_id
        r = self.put(url, payload, version=allocation_request_version,
                     global_request_id=context.global_id)
        if r.status_code != 204:
            # NOTE(jaypipes): Yes, it sucks doing string comparison like this
            # but we have no error codes, only error messages.
            if 'concurrently updated' in r.text:
                reason = ('another process changed the resource providers '
                          'involved in our attempt to put allocations for '
                          'consumer %s' % consumer_uuid)
                raise Retry('claim_resources', reason)
            else:
                LOG.warning(
                    'Unable to submit allocation for instance '
                    '%(uuid)s (%(code)i %(text)s)',
                    {'uuid': consumer_uuid,
                     'code': r.status_code,
                     'text': r.text})
        return r.status_code == 204

    @safe_connect
    def remove_provider_from_instance_allocation(self, context, consumer_uuid,
                                                 rp_uuid, user_id, project_id,
                                                 resources):
        """Grabs an allocation for a particular consumer UUID, strips parts of
        the allocation that refer to a supplied resource provider UUID, and
        then PUTs the resulting allocation back to the placement API for the
        consumer.

        This is used to reconcile the "doubled-up" allocation that the
        scheduler constructs when claiming resources against the destination
        host during a move operation.

        If the move was between hosts, the entire allocation for rp_uuid will
        be dropped. If the move is a resize on the same host, then we will
        subtract resources from the single allocation to ensure we do not
        exceed the reserved or max_unit amounts for the resource on the host.

        :param context: The security context
        :param consumer_uuid: The instance/consumer UUID
        :param rp_uuid: The UUID of the provider whose resources we wish to
                        remove from the consumer's allocation
        :param user_id: The instance's user
        :param project_id: The instance's project
        :param resources: The resources to be dropped from the allocation
        """
        url = '/allocations/%s' % consumer_uuid

        # Grab the "doubled-up" allocation that we will manipulate
        r = self.get(url, global_request_id=context.global_id)
        if r.status_code != 200:
            LOG.warning("Failed to retrieve allocations for %s. Got HTTP %s",
                        consumer_uuid, r.status_code)
            return False

        current_allocs = r.json()['allocations']
        if not current_allocs:
            LOG.error("Expected to find current allocations for %s, but "
                      "found none.", consumer_uuid)
            return False

        # If the host isn't in the current allocation for the instance, don't
        # do anything
        if rp_uuid not in current_allocs:
            LOG.warning("Expected to find allocations referencing resource "
                        "provider %s for %s, but found none.",
                        rp_uuid, consumer_uuid)
            return True

        compute_providers = [uuid for uuid, alloc in current_allocs.items()
                             if 'VCPU' in alloc['resources']]
        LOG.debug('Current allocations for instance: %s', current_allocs,
                  instance_uuid=consumer_uuid)
        LOG.debug('Instance %s has resources on %i compute nodes',
                  consumer_uuid, len(compute_providers))

        new_allocs = [
            {
                'resource_provider': {
                    'uuid': alloc_rp_uuid,
                },
                'resources': alloc['resources'],
            }
            for alloc_rp_uuid, alloc in current_allocs.items()
            if alloc_rp_uuid != rp_uuid
        ]

        if len(compute_providers) == 1:
            # NOTE(danms): We are in a resize to same host scenario. Since we
            # are the only provider then we need to merge back in the doubled
            # allocation with our part subtracted
            peer_alloc = {
                'resource_provider': {
                    'uuid': rp_uuid,
                },
                'resources': current_allocs[rp_uuid]['resources']
            }
            LOG.debug('Original resources from same-host '
                      'allocation: %s', peer_alloc['resources'])
            scheduler_utils.merge_resources(peer_alloc['resources'],
                                            resources, -1)
            LOG.debug('Subtracting old resources from same-host '
                      'allocation: %s', peer_alloc['resources'])
            new_allocs.append(peer_alloc)

        payload = {'allocations': new_allocs}
        payload['project_id'] = project_id
        payload['user_id'] = user_id
        LOG.debug("Sending updated allocation %s for instance %s after "
                  "removing resources for %s.",
                  new_allocs, consumer_uuid, rp_uuid)
        r = self.put(url, payload, version='1.10',
                     global_request_id=context.global_id)
        if r.status_code != 204:
            LOG.warning("Failed to save allocation for %s. Got HTTP %s: %s",
                        consumer_uuid, r.status_code, r.text)
        return r.status_code == 204

    @safe_connect
    @retries
    def set_and_clear_allocations(self, context, rp_uuid, consumer_uuid,
                                  alloc_data, project_id, user_id,
                                  consumer_to_clear=None):
        """Create allocation records for the supplied consumer UUID while
        simultaneously clearing any allocations identified by the uuid
        in consumer_to_clear, for example a migration uuid when moving an
        instance to another host. This is for atomically managing so-called
        "doubled" migration records.

        :note Currently we only allocate against a single resource provider.
              Once shared storage and things like NUMA allocations are a
              reality, this will change to allocate against multiple providers.

        :param context: The security context
        :param rp_uuid: The UUID of the resource provider to allocate against.
        :param consumer_uuid: The consumer UUID for which allocations are
                              being set.
        :param alloc_data: Dict, keyed by resource class, of amounts to
                           consume.
        :param project_id: The project_id associated with the allocations.
        :param user_id: The user_id associated with the allocations.
        :param consumer_to_clear: A UUID identifying allocations for a
                                  consumer that should be cleared.
        :returns: True if the allocations were created, False otherwise.
        :raises: Retry if the operation should be retried due to a concurrent
                 update.
        """
        # FIXME(cdent): Fair amount of duplicate with put in here, but now
        # just working things through.
        payload = {
            consumer_uuid: {
                'allocations': {
                    rp_uuid: {
                        'resources': alloc_data
                    }
                },
                'project_id': project_id,
                'user_id': user_id,
            }
        }
        if consumer_to_clear:
            payload[consumer_to_clear] = {
                'allocations': {},
                'project_id': project_id,
                'user_id': user_id,
            }
        r = self.post('/allocations', payload,
                      version=POST_ALLOCATIONS_API_VERSION,
                      global_request_id=context.global_id)
        if r.status_code != 204:
            # NOTE(jaypipes): Yes, it sucks doing string comparison like this
            # but we have no error codes, only error messages.
            if 'concurrently updated' in r.text:
                reason = ('another process changed the resource providers '
                          'involved in our attempt to post allocations for '
                          'consumer %s' % consumer_uuid)
                raise Retry('set_and_clear_allocations', reason)
            else:
                LOG.warning(
                    'Unable to post allocations for instance '
                    '%(uuid)s (%(code)i %(text)s)',
                    {'uuid': consumer_uuid,
                     'code': r.status_code,
                     'text': r.text})
        return r.status_code == 204

    @safe_connect
    @retries
    def put_allocations(self, context, rp_uuid, consumer_uuid, alloc_data,
                        project_id, user_id):
        """Creates allocation records for the supplied instance UUID against
        the supplied resource provider.

        :note Currently we only allocate against a single resource provider.
              Once shared storage and things like NUMA allocations are a
              reality, this will change to allocate against multiple providers.

        :param context: The security context
        :param rp_uuid: The UUID of the resource provider to allocate against.
        :param consumer_uuid: The instance's UUID.
        :param alloc_data: Dict, keyed by resource class, of amounts to
                           consume.
        :param project_id: The project_id associated with the allocations.
        :param user_id: The user_id associated with the allocations.
        :returns: True if the allocations were created, False otherwise.
        :raises: Retry if the operation should be retried due to a concurrent
                 update.
        """
        payload = {
            'allocations': [
                {
                    'resource_provider': {
                        'uuid': rp_uuid,
                    },
                    'resources': alloc_data,
                },
            ],
            'project_id': project_id,
            'user_id': user_id,
        }
        url = '/allocations/%s' % consumer_uuid
        r = self.put(url, payload, version='1.8',
                     global_request_id=context.global_id)
        if r.status_code != 204:
            # NOTE(jaypipes): Yes, it sucks doing string comparison like this
            # but we have no error codes, only error messages.
            if 'concurrently updated' in r.text:
                reason = ('another process changed the resource providers '
                          'involved in our attempt to put allocations for '
                          'consumer %s' % consumer_uuid)
                raise Retry('put_allocations', reason)
            else:
                LOG.warning(
                    'Unable to submit allocation for instance '
                    '%(uuid)s (%(code)i %(text)s)',
                    {'uuid': consumer_uuid,
                     'code': r.status_code,
                     'text': r.text})
        return r.status_code == 204

    @safe_connect
    def delete_allocation_for_instance(self, context, uuid):
        url = '/allocations/%s' % uuid
        r = self.delete(url, global_request_id=context.global_id)
        if r:
            LOG.info('Deleted allocation for instance %s', uuid)
            return True
        else:
            # Check for 404 since we don't need to log a warning if we tried to
            # delete something which doesn't actually exist.
            if r.status_code != 404:
                LOG.warning('Unable to delete allocation for instance '
                            '%(uuid)s: (%(code)i %(text)s)',
                            {'uuid': uuid,
                             'code': r.status_code,
                             'text': r.text})
            return False

    def update_instance_allocation(self, context, compute_node, instance,
                                   sign):
        if sign > 0:
            self._allocate_for_instance(context, compute_node.uuid, instance)
        else:
            self.delete_allocation_for_instance(context, instance.uuid)

    @safe_connect
    def get_allocations_for_resource_provider(self, context, rp_uuid):
        url = '/resource_providers/%s/allocations' % rp_uuid
        resp = self.get(url, global_request_id=context.global_id)
        if not resp:
            return {}
        else:
            return resp.json()['allocations']

    def delete_resource_provider(self, context, compute_node, cascade=False):
        """Deletes the ResourceProvider record for the compute_node.

        :param context: The security context
        :param compute_node: The nova.objects.ComputeNode object that is the
                             resource provider being deleted.
        :param cascade: Boolean value that, when True, will first delete any
                        associated Allocation and Inventory records for the
                        compute node
        """
        nodename = compute_node.hypervisor_hostname
        host = compute_node.host
        rp_uuid = compute_node.uuid
        if cascade:
            # Delete any allocations for this resource provider.
            # Since allocations are by consumer, we get the consumers on this
            # host, which are its instances.
            instances = objects.InstanceList.get_by_host_and_node(context,
                    host, nodename)
            for instance in instances:
                self.delete_allocation_for_instance(context, instance.uuid)
        try:
            self._delete_provider(rp_uuid, global_request_id=context.global_id)
        except (exception.ResourceProviderInUse,
                exception.ResourceProviderDeletionFailed):
            # TODO(efried): Raise these.  Right now this is being left a no-op
            # for backward compatibility.
            pass

    @safe_connect
    def _get_provider_by_name(self, context, name):
        """Queries the placement API for resource provider information matching
        a supplied name.

        :param context: The security context
        :param name: Name of the resource provider to look up
        :return: A dict of resource provider information including the
                 provider's UUID and generation
        :raises: `exception.ResourceProviderNotFound` when no such provider was
                 found
        """
        resp = self.get("/resource_providers?name=%s" % name,
                        global_request_id=context.global_id)
        if resp.status_code == 200:
            data = resp.json()
            records = data['resource_providers']
            num_recs = len(records)
            if num_recs == 1:
                return records[0]
            elif num_recs > 1:
                msg = ("Found multiple resource provider records for resource "
                       "provider name %(rp_name)s: %(rp_uuids)s. "
                       "This should not happen.")
                LOG.warning(msg, {
                    'rp_name': name,
                    'rp_uuids': ','.join([r['uuid'] for r in records])
                })
        elif resp.status_code != 404:
            msg = ("Failed to retrieve resource provider information by name "
                   "for resource provider %s. Got %d: %s")
            LOG.warning(msg, name, resp.status_code, resp.text)

        raise exception.ResourceProviderNotFound(name_or_uuid=name)

    @retrying.retry(stop_max_attempt_number=4,
                    retry_on_exception=lambda e: isinstance(
                        e, exception.ResourceProviderUpdateConflict))
    def aggregate_add_host(self, context, agg_uuid, host_name):
        """Looks up a resource provider by the supplied host name, and adds the
        aggregate with supplied UUID to that resource provider.

        :note: This method does NOT use the cached provider tree. It is only
               called from the Compute API when a nova host aggregate is
               modified

        :param context: The security context
        :param agg_uuid: UUID of the aggregate being modified
        :param host_name: Name of the nova-compute service worker to look up a
                          resource provider for
        :raises: `exceptions.ResourceProviderNotFound` if no resource provider
                  matching the host name could be found from the placement API
        :raises: `exception.ResourceProviderAggregateRetrievalFailed` when
                 failing to get a provider's existing aggregates
        :raises: `exception.ResourceProviderUpdateFailed` if there was a
                 failure attempting to save the provider aggregates
        :raises: `exception.ResourceProviderUpdateConflict` if a concurrent
                 update to the provider was detected.
        """
        rp = self._get_provider_by_name(context, host_name)
        # NOTE(jaypipes): Unfortunately, due to @safe_connect,
        # _get_provider_by_name() can return None. If that happens, raise an
        # error so we can trap for it in the Nova API code and ignore in Rocky,
        # blow up in Stein.
        if rp is None:
            raise exception.PlacementAPIConnectFailure()
        rp_uuid = rp['uuid']

        # Now attempt to add the aggregate to the resource provider. We don't
        # want to overwrite any other aggregates the provider may be associated
        # with, however, so we first grab the list of aggregates for this
        # provider and add the aggregate to the list of aggregates it already
        # has
        agg_info = self._get_provider_aggregates(context, rp_uuid)
        # @safe_connect can make the above return None
        if agg_info is None:
            raise exception.PlacementAPIConnectFailure()
        existing_aggs, gen = agg_info.aggregates, agg_info.generation
        if agg_uuid in existing_aggs:
            return

        new_aggs = existing_aggs | set([agg_uuid])
        self.set_aggregates_for_provider(
            context, rp_uuid, new_aggs, use_cache=False, generation=gen)

    @retrying.retry(stop_max_attempt_number=4,
                    retry_on_exception=lambda e: isinstance(
                        e, exception.ResourceProviderUpdateConflict))
    def aggregate_remove_host(self, context, agg_uuid, host_name):
        """Looks up a resource provider by the supplied host name, and removes
        the aggregate with supplied UUID from that resource provider.

        :note: This method does NOT use the cached provider tree. It is only
               called from the Compute API when a nova host aggregate is
               modified

        :param context: The security context
        :param agg_uuid: UUID of the aggregate being modified
        :param host_name: Name of the nova-compute service worker to look up a
                          resource provider for
        :raises: `exceptions.ResourceProviderNotFound` if no resource provider
                  matching the host name could be found from the placement API
        :raises: `exception.ResourceProviderAggregateRetrievalFailed` when
                 failing to get a provider's existing aggregates
        :raises: `exception.ResourceProviderUpdateFailed` if there was a
                 failure attempting to save the provider aggregates
        :raises: `exception.ResourceProviderUpdateConflict` if a concurrent
                 update to the provider was detected.
        """
        rp = self._get_provider_by_name(context, host_name)
        # NOTE(jaypipes): Unfortunately, due to @safe_connect,
        # _get_provider_by_name() can return None. If that happens, raise an
        # error so we can trap for it in the Nova API code and ignore in Rocky,
        # blow up in Stein.
        if rp is None:
            raise exception.PlacementAPIConnectFailure()
        rp_uuid = rp['uuid']

        # Now attempt to remove the aggregate from the resource provider. We
        # don't want to overwrite any other aggregates the provider may be
        # associated with, however, so we first grab the list of aggregates for
        # this provider and remove the aggregate from the list of aggregates it
        # already has
        agg_info = self._get_provider_aggregates(context, rp_uuid)
        # @safe_connect can make the above return None
        if agg_info is None:
            raise exception.PlacementAPIConnectFailure()
        existing_aggs, gen = agg_info.aggregates, agg_info.generation
        if agg_uuid not in existing_aggs:
            return

        new_aggs = existing_aggs - set([agg_uuid])
        self.set_aggregates_for_provider(
            context, rp_uuid, new_aggs, use_cache=False, generation=gen)

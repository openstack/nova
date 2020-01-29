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
import time
import typing as ty

from keystoneauth1 import exceptions as ks_exc
import os_resource_classes as orc
import os_traits
from oslo_log import log as logging
from oslo_middleware import request_id
from oslo_utils import excutils
from oslo_utils import versionutils
import retrying
import six

from nova.compute import provider_tree
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova import utils


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
WARN_EVERY = 10
ROOT_REQUIRED_VERSION = '1.35'
RESHAPER_VERSION = '1.30'
CONSUMER_GENERATION_VERSION = '1.28'
ALLOW_RESERVED_EQUAL_TOTAL_INVENTORY_VERSION = '1.26'
POST_RPS_RETURNS_PAYLOAD_API_VERSION = '1.20'
AGGREGATE_GENERATION_VERSION = '1.19'
NESTED_PROVIDER_API_VERSION = '1.14'
POST_ALLOCATIONS_API_VERSION = '1.13'
GET_USAGES_VERSION = '1.9'

AggInfo = collections.namedtuple('AggInfo', ['aggregates', 'generation'])
TraitInfo = collections.namedtuple('TraitInfo', ['traits', 'generation'])
ProviderAllocInfo = collections.namedtuple(
    'ProviderAllocInfo', ['allocations'])


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


def _move_operation_alloc_request(source_allocs, dest_alloc_req):
    """Given existing allocations for a source host and a new allocation
    request for a destination host, return a new allocation_request that
    contains resources claimed against both source and destination, accounting
    for shared providers.

    This is expected to only be used during an evacuate operation.

    :param source_allocs: Dict, keyed by resource provider UUID, of resources
                          allocated on the source host
    :param dest_alloc_req: The allocation_request for resources against the
                           destination host
    """
    LOG.debug("Doubling-up allocation_request for move operation. Current "
              "allocations: %s", source_allocs)
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

    LOG.debug("New allocation_request containing both source and "
              "destination hosts in move operation: %s", new_alloc_req)
    return new_alloc_req


def get_placement_request_id(response):
    if response is not None:
        return response.headers.get(request_id.HTTP_RESP_HEADER_REQUEST_ID)


# TODO(mriedem): Consider making SchedulerReportClient a global singleton so
# that things like the compute API do not have to lazy-load it. That would
# likely require inspecting methods that use a ProviderTree cache to see if
# they need locks.
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
        self._provider_tree = None
        # Track the last time we updated providers' aggregates and traits
        self._association_refresh_time = None
        self._client = self._create_client()
        # NOTE(danms): Keep track of how naggy we've been
        self._warn_count = 0

    def clear_provider_cache(self, init=False):
        if not init:
            LOG.info("Clearing the report client's provider cache.")
        self._provider_tree = provider_tree.ProviderTree()
        self._association_refresh_time = {}

    def _clear_provider_cache_for_tree(self, rp_uuid):
        """Clear the provider cache for only the tree containing rp_uuid.

        This exists for situations where we encounter an error updating
        placement, and therefore need to refresh the provider tree cache before
        redriving the update. However, it would be wasteful and inefficient to
        clear the *entire* cache, which may contain many separate trees (e.g.
        ironic nodes or sharing providers) which should be unaffected by the
        error.

        :param rp_uuid: UUID of a resource provider, which may be anywhere in a
                        a tree hierarchy, i.e. need not be a root. For non-root
                        providers, we still clear the cache for the entire tree
                        including descendants, ancestors up to the root,
                        siblings/cousins and *their* ancestors/descendants.
        """
        try:
            uuids = self._provider_tree.get_provider_uuids_in_tree(rp_uuid)
        except ValueError:
            # If the provider isn't in the tree, it should also not be in the
            # timer dict, so nothing to clear.
            return

        # get_provider_uuids_in_tree returns UUIDs in top-down order, so the
        # first one is the root; and .remove() is recursive.
        self._provider_tree.remove(uuids[0])
        for uuid in uuids:
            self._association_refresh_time.pop(uuid, None)

    def _create_client(self):
        """Create the HTTP session accessing the placement service."""
        # Flush provider tree and associations so we start from a clean slate.
        self.clear_provider_cache(init=True)
        client = self._adapter or utils.get_sdk_adapter('placement')
        # Set accept header on every request to ensure we notify placement
        # service of our response body media type preferences.
        client.additional_headers = {'accept': 'application/json'}
        return client

    def get(self, url, version=None, global_request_id=None):
        return self._client.get(url, microversion=version,
                                global_request_id=global_request_id)

    def post(self, url, data, version=None, global_request_id=None):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        return self._client.post(url, json=data, microversion=version,
                                 global_request_id=global_request_id)

    def put(self, url, data, version=None, global_request_id=None):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        return self._client.put(url, json=data, microversion=version,
                                global_request_id=global_request_id)

    def delete(self, url, version=None, global_request_id=None):
        return self._client.delete(url, microversion=version,
                                   global_request_id=global_request_id)

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
        # Note that claim_resources() will use this version as well to
        # make allocations by `PUT /allocations/{consumer_uuid}`
        version = ROOT_REQUIRED_VERSION
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

    def get_provider_traits(self, context, rp_uuid):
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
        :raise: keystoneauth1.exceptions.ClientException if placement API
                communication fails.
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

    def get_resource_provider_name(self, context, uuid):
        """Return the name of a RP. It tries to use the internal of RPs or
        falls back to calling placement directly.

        :param context: The security context
        :param uuid: UUID identifier for the resource provider to look up
        :return: The name of the RP
        :raise: ResourceProviderRetrievalFailed if the RP is not in the cache
            and the communication with the placement is failed.
        :raise: ResourceProviderNotFound if the RP does not exist.
        """

        try:
            return self._provider_tree.data(uuid).name
        except ValueError:
            rsp = self._get_resource_provider(context, uuid)
            if rsp is None:
                raise exception.ResourceProviderNotFound(name_or_uuid=uuid)
            else:
                return rsp['name']

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

    def get_providers_in_tree(self, context, uuid):
        """Queries the placement API for a list of the resource providers in
        the tree associated with the specified UUID.

        :param context: The security context
        :param uuid: UUID identifier for the resource provider to look up
        :return: A list of dicts of resource provider information, which may be
                 empty if no provider exists with the specified UUID.
        :raise: ResourceProviderRetrievalFailed on error.
        :raise: keystoneauth1.exceptions.ClientException if placement API
                communication fails.
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
        - All sharing providers associated via aggregate with all providers in
          said tree
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
        :raise ResourceProviderCreationFailed: If we expected to be creating
                providers, but couldn't.
        :raise: keystoneauth1.exceptions.ClientException if placement API
                communication fails.
        """
        # NOTE(efried): We currently have no code path where we need to set the
        # parent_provider_uuid on a previously-parent-less provider - so we do
        # NOT handle that scenario here.

        # If we already have the root provider in the cache, and it's not
        # stale, don't refresh it; and use the cache to determine the
        # descendants to (soft) refresh.
        # NOTE(efried): This assumes the compute service only cares about
        # providers it "owns". If that ever changes, we'll need a way to find
        # out about out-of-band changes here. Options that have been
        # brainstormed at this time:
        # - Make this condition more frequently True
        # - Some kind of notification subscription so a separate thread is
        #   alerted when <thing we care about happens in placement>.
        # - "Cascading generations" - i.e. a change to a leaf node percolates
        #   generation bump up the tree so that we bounce 409 the next time we
        #   try to update anything and have to refresh.
        if (self._provider_tree.exists(uuid) and
                not self._associations_stale(uuid)):
            uuids_to_refresh = [
                u for u in self._provider_tree.get_provider_uuids(uuid)
                if self._associations_stale(u)]
        else:
            # We either don't have it locally or it's stale. Pull or create it.
            created_rp = None
            rps_to_refresh = self.get_providers_in_tree(context, uuid)
            if not rps_to_refresh:
                created_rp = self._create_resource_provider(
                    context, uuid, name or uuid,
                    parent_provider_uuid=parent_provider_uuid)
                # If @safe_connect can't establish a connection to the
                # placement service, like if placement isn't running or
                # nova-compute is mis-configured for authentication, we'll get
                # None back and need to treat it like we couldn't create the
                # provider (because we couldn't).
                if created_rp is None:
                    raise exception.ResourceProviderCreationFailed(
                        name=name or uuid)
                # Don't add the created_rp to rps_to_refresh.  Since we just
                # created it, it has no aggregates or traits.
                # But do mark it as having just been "refreshed".
                self._association_refresh_time[uuid] = time.time()

            self._provider_tree.populate_from_iterable(
                rps_to_refresh or [created_rp])

            uuids_to_refresh = [rp['uuid'] for rp in rps_to_refresh]

        # At this point, the whole tree exists in the local cache.

        for uuid_to_refresh in uuids_to_refresh:
            self._refresh_associations(context, uuid_to_refresh, force=True)

        return uuid

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
            # TODO(efried): Log.
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

        LOG.debug('Updating ProviderTree inventory for provider %s from '
                  '_refresh_and_get_inventory using data: %s', rp_uuid,
                  curr['inventories'])
        self._provider_tree.update_inventory(
            rp_uuid, curr['inventories'],
            generation=curr['resource_provider_generation'])

        return curr

    def _refresh_associations(self, context, rp_uuid, force=False,
                              refresh_sharing=True):
        """Refresh inventories, aggregates, traits, and (optionally) aggregate-
        associated sharing providers for the specified resource provider uuid.

        Only refresh if there has been no refresh during the lifetime of
        this process, CONF.compute.resource_provider_association_refresh
        seconds have passed, or the force arg has been set to True.

        :param context: The security context
        :param rp_uuid: UUID of the resource provider to check for fresh
                        inventories, aggregates, and traits
        :param force: If True, force the refresh
        :param refresh_sharing: If True, fetch all the providers associated
                                by aggregate with the specified provider,
                                including their inventories, traits, and
                                aggregates (but not *their* sharing providers).
        :raise: On various placement API errors, one of:
                - ResourceProviderAggregateRetrievalFailed
                - ResourceProviderTraitRetrievalFailed
                - ResourceProviderRetrievalFailed
        :raise: keystoneauth1.exceptions.ClientException if placement API
                communication fails.
        """
        if force or self._associations_stale(rp_uuid):
            # Refresh inventories
            msg = "Refreshing inventories for resource provider %s"
            LOG.debug(msg, rp_uuid)
            self._refresh_and_get_inventory(context, rp_uuid)
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
            trait_info = self.get_provider_traits(context, rp_uuid)
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
                    # Now we have to (populate or) refresh that provider's
                    # traits, aggregates, and inventories (but not *its*
                    # aggregate-associated providers). No need to override
                    # force=True for newly-added providers - the missing
                    # timestamp will always trigger them to refresh.
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

        Always False if CONF.compute.resource_provider_association_refresh is
        zero.
        """
        rpar = CONF.compute.resource_provider_association_refresh
        refresh_time = self._association_refresh_time.get(uuid, 0)
        # If refresh is disabled, associations are "never" stale. (But still
        # load them if we haven't yet done so.)
        if rpar == 0 and refresh_time != 0:
            # TODO(efried): If refresh is disabled, we could avoid touching the
            # _association_refresh_time dict anywhere, but that would take some
            # nontrivial refactoring.
            return False
        return (time.time() - refresh_time) > rpar

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
        # Return a *copy* of the tree.
        return copy.deepcopy(self._provider_tree)

    def set_inventory_for_provider(self, context, rp_uuid, inv_data):
        """Given the UUID of a provider, set the inventory records for the
        provider to the supplied dict of resources.

        The provider must exist - this method does not attempt to create it.

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
            LOG.debug('Inventory has not changed for provider %s based '
                      'on inventory data: %s', rp_uuid, inv_data)
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
            LOG.debug('Updated inventory for provider %s with generation %s '
                      'in Placement from set_inventory_for_provider using '
                      'data: %s', rp_uuid, generation, inv_data)
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
            err = resp.json()['errors'][0]
            # TODO(efried): If there's ever a lib exporting symbols for error
            # codes, use it.
            if err['code'] == 'placement.inventory.inuse':
                # The error detail includes the resource class and provider.
                raise exception.InventoryInUse(err['detail'])
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
    def set_traits_for_provider(
        self,
        context: nova_context.RequestContext,
        rp_uuid: str,
        traits: ty.Iterable[str],
        generation: int = None
    ):
        """Replace a provider's traits with those specified.

        The provider must exist - this method does not attempt to create it.

        :param context: The security context
        :param rp_uuid: The UUID of the provider whose traits are to be updated
        :param traits: Iterable of traits to set on the provider
        :param generation: The resource provider generation if known. If not
                           provided then the value from the provider tree cache
                           will be used.
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
        # that method doesn't return content, and we need to update the cached
        # provider tree with the new generation.
        traits = list(traits) if traits else []
        if generation is None:
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
            if (self._provider_tree.data(rp_uuid).generation == generation and
                    not self._provider_tree.have_aggregates_changed(
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
                        if n.startswith(orc.CUSTOM_NAMESPACE))

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

    def _reshape(self, context, inventories, allocations):
        """Perform atomic inventory & allocation data migration.

        :param context: The security context
        :param inventories: A dict, keyed by resource provider UUID, of:
                { "inventories": { inventory dicts, keyed by resource class },
                  "resource_provider_generation": $RP_GEN }
        :param allocations: A dict, keyed by consumer UUID, of:
                { "project_id": $PROJ_ID,
                  "user_id": $USER_ID,
                  "consumer_generation": $CONSUMER_GEN,
                  "allocations": {
                      $RP_UUID: {
                          "resources": { $RC: $AMOUNT, ... }
                      },
                      ...
                  }
                }
        :return: The Response object representing a successful API call.
        :raises: ReshapeFailed if the POST /reshaper request fails.
        :raises: keystoneauth1.exceptions.ClientException if placement API
                 communication fails.
        """
        # We have to make sure any new resource classes exist
        for invs in inventories.values():
            self._ensure_resource_classes(context, list(invs['inventories']))
        payload = {"inventories": inventories, "allocations": allocations}
        resp = self.post('/reshaper', payload, version=RESHAPER_VERSION,
                         global_request_id=context.global_id)
        if not resp:
            raise exception.ReshapeFailed(error=resp.text)

        return resp

    def _set_up_and_do_reshape(self, context, old_tree, new_tree, allocations):
        LOG.info("Performing resource provider inventory and allocation "
                 "data migration.")
        new_uuids = new_tree.get_provider_uuids()
        inventories = {}
        for rp_uuid in new_uuids:
            data = new_tree.data(rp_uuid)
            inventories[rp_uuid] = {
                "inventories": data.inventory,
                "resource_provider_generation": data.generation
            }
        # Even though we're going to delete them immediately, we still want
        # to send "inventory changes" for to-be-removed providers in this
        # reshape request so they're done atomically. This prevents races
        # where the scheduler could allocate between here and when we
        # delete the providers.
        to_remove = set(old_tree.get_provider_uuids()) - set(new_uuids)
        for rp_uuid in to_remove:
            inventories[rp_uuid] = {
                "inventories": {},
                "resource_provider_generation":
                    old_tree.data(rp_uuid).generation
            }
        # Now we're ready to POST /reshaper. This can raise ReshapeFailed,
        # but we also need to convert any other exception (including e.g.
        # PlacementAPIConnectFailure) to ReshapeFailed because we want any
        # failure here to be fatal to the caller.
        try:
            self._reshape(context, inventories, allocations)
        except exception.ReshapeFailed:
            raise
        except Exception as e:
            # Make sure the original stack trace gets logged.
            LOG.exception('Reshape failed')
            raise exception.ReshapeFailed(error=e)

    def update_from_provider_tree(self, context, new_tree, allocations=None):
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
        :param allocations: A dict, keyed by consumer UUID, of allocation
                            records of the form returned by
                            GET /allocations/{consumer_uuid} representing the
                            comprehensive final picture of the allocations for
                            each consumer therein. A value of None indicates
                            that no reshape is being performed.
        :raises: ResourceProviderUpdateConflict if a generation conflict was
                 encountered - i.e. we are attempting to update placement based
                 on a stale view of it.
        :raises: ResourceProviderSyncFailed if any errors were encountered
                 attempting to perform the necessary API operations, except
                 reshape (see below).
        :raises: ReshapeFailed if a reshape was signaled (allocations not None)
                 and it fails for any reason.
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        """
        # NOTE(efried): We currently do not handle the "rename" case.  This is
        # where new_tree contains a provider named Y whose UUID already exists
        # but is named X.

        @contextlib.contextmanager
        def catch_all(rp_uuid):
            """Convert all "expected" exceptions from placement API helpers to
            ResourceProviderSyncFailed* and invalidate the caches for the tree
            around `rp_uuid`.

            * Except ResourceProviderUpdateConflict, which signals the caller
              to redrive the operation; and ReshapeFailed, which triggers
              special error handling behavior in the resource tracker and
              compute manager.
            """
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
                exception.ResourceProviderUpdateFailed,
                exception.TraitCreationFailed,
                exception.TraitRetrievalFailed,
                # NOTE(efried): We do not trap/convert ReshapeFailed - that one
                # needs to bubble up right away and be handled specially.
            )
            try:
                yield
            except exception.ResourceProviderUpdateConflict:
                # Invalidate the tree around the failing provider and reraise
                # the conflict exception. This signals the resource tracker to
                # redrive the update right away rather than waiting until the
                # next periodic.
                with excutils.save_and_reraise_exception():
                    self._clear_provider_cache_for_tree(rp_uuid)
            except helper_exceptions:
                # Invalidate the relevant part of the cache. It gets rebuilt on
                # the next pass.
                self._clear_provider_cache_for_tree(rp_uuid)
                raise exception.ResourceProviderSyncFailed()

        # Helper methods herein will be updating the local cache (this is
        # intentional) so we need to grab up front any data we need to operate
        # on in its "original" form.
        old_tree = self._provider_tree
        old_uuids = old_tree.get_provider_uuids()
        new_uuids = new_tree.get_provider_uuids()
        uuids_to_add = set(new_uuids) - set(old_uuids)
        uuids_to_remove = set(old_uuids) - set(new_uuids)

        # In case a reshape is happening, we first have to create (or load) any
        # "new" providers.
        # We have to do additions in top-down order, so we don't error
        # attempting to create a child before its parent exists.
        for uuid in new_uuids:
            if uuid not in uuids_to_add:
                continue
            provider = new_tree.data(uuid)
            with catch_all(uuid):
                self._ensure_resource_provider(
                    context, uuid, name=provider.name,
                    parent_provider_uuid=provider.parent_uuid)
                # We have to stuff the freshly-created provider's generation
                # into the new_tree so we don't get conflicts updating its
                # inventories etc. later.
                # TODO(efried): We don't have a good way to set the generation
                # independently; this is a hack.
                new_tree.update_inventory(
                    uuid, new_tree.data(uuid).inventory,
                    generation=self._provider_tree.data(uuid).generation)

        # If we need to reshape, do it here.
        if allocations is not None:
            # NOTE(efried): We do not catch_all here, because ReshapeFailed
            # needs to bubble up right away and be handled specially.
            self._set_up_and_do_reshape(context, old_tree, new_tree,
                                        allocations)
            # The reshape updated provider generations, so the ones we have in
            # the cache are now stale. The inventory update below will short
            # out, but we would still bounce with a provider generation
            # conflict on the trait and aggregate updates.
            for uuid in new_uuids:
                # TODO(efried): GET /resource_providers?uuid=in:[list] would be
                # handy here. Meanwhile, this is an already-written, if not
                # obvious, way to refresh provider generations in the cache.
                with catch_all(uuid):
                    self._refresh_and_get_inventory(context, uuid)

        # Now we can do provider deletions, because we should have moved any
        # allocations off of them via reshape.
        # We have to do deletions in bottom-up order, so we don't error
        # attempting to delete a parent who still has children. (We get the
        # UUIDs in bottom-up order by reversing old_uuids, which was given to
        # us in top-down order per ProviderTree.get_provider_uuids().)
        for uuid in reversed(old_uuids):
            if uuid not in uuids_to_remove:
                continue
            with catch_all(uuid):
                self._delete_provider(uuid)

        # At this point the local cache should have all the same providers as
        # new_tree.  Whether we added them or not, walk through and diff/flush
        # inventories, traits, and aggregates as necessary. Note that, if we
        # reshaped above, any inventory changes have already been done. But the
        # helper methods are set up to check and short out when the relevant
        # property does not differ from what's in the cache.
        # If we encounter any error and remove a provider from the cache, all
        # its descendants are also removed, and set_*_for_provider methods on
        # it wouldn't be able to get started. Walking the tree in bottom-up
        # order ensures we at least try to process all of the providers. (We
        # get the UUIDs in bottom-up order by reversing new_uuids, which was
        # given to us in top-down order per ProviderTree.get_provider_uuids().)
        for uuid in reversed(new_uuids):
            pd = new_tree.data(uuid)
            with catch_all(pd.uuid):
                self.set_inventory_for_provider(
                    context, pd.uuid, pd.inventory)
                self.set_aggregates_for_provider(
                    context, pd.uuid, pd.aggregates)
                self.set_traits_for_provider(context, pd.uuid, pd.traits)

    # TODO(efried): Cut users of this method over to get_allocs_for_consumer
    def get_allocations_for_consumer(self, context, consumer):
        """Legacy method for allocation retrieval.

        Callers should move to using get_allocs_for_consumer, which handles
        errors properly and returns the entire payload.

        :param context: The nova.context.RequestContext auth context
        :param consumer: UUID of the consumer resource
        :returns: A dict of the form:
                {
                    $RP_UUID: {
                              "generation": $RP_GEN,
                              "resources": {
                                  $RESOURCE_CLASS: $AMOUNT
                                  ...
                              },
                    },
                    ...
                }
        """
        try:
            return self.get_allocs_for_consumer(
                context, consumer)['allocations']
        except ks_exc.ClientException as e:
            LOG.warning("Failed to get allocations for consumer %(consumer)s: "
                        "%(error)s", {'consumer': consumer, 'error': e})
            # Because this is what @safe_connect did
            return None
        except exception.ConsumerAllocationRetrievalFailed as e:
            LOG.warning(e)
            # Because this is how we used to treat non-200
            return {}

    def get_allocs_for_consumer(self, context, consumer):
        """Makes a GET /allocations/{consumer} call to Placement.

        :param context: The nova.context.RequestContext auth context
        :param consumer: UUID of the consumer resource
        :return: Dict of the form:
                { "allocations": {
                      $RP_UUID: {
                          "generation": $RP_GEN,
                          "resources": {
                              $RESOURCE_CLASS: $AMOUNT
                              ...
                          },
                      },
                      ...
                  },
                  "consumer_generation": $CONSUMER_GEN,
                  "project_id": $PROJ_ID,
                  "user_id": $USER_ID,
                }
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        :raises: ConsumerAllocationRetrievalFailed if the placement API call
                 fails
        """
        resp = self.get('/allocations/%s' % consumer,
                        version=CONSUMER_GENERATION_VERSION,
                        global_request_id=context.global_id)
        if not resp:
            # TODO(efried): Use code/title/detail to make a better exception
            raise exception.ConsumerAllocationRetrievalFailed(
                consumer_uuid=consumer, error=resp.text)

        return resp.json()

    def get_allocations_for_consumer_by_provider(self, context, rp_uuid,
                                                 consumer):
        """Return allocations for a consumer and a resource provider.

        :param context: The nova.context.RequestContext auth context
        :param rp_uuid: UUID of the resource provider
        :param consumer: UUID of the consumer
        :return: the resources dict of the consumer's allocation keyed by
                 resource classes
        """
        # NOTE(cdent): This trims to just the allocations being
        # used on this resource provider. In the future when there
        # are shared resources there might be other providers.
        allocations = self.get_allocations_for_consumer(context, consumer)
        if allocations is None:
            # safe_connect can return None on 404
            allocations = {}
        return allocations.get(
            rp_uuid, {}).get('resources', {})

    # NOTE(jaypipes): Currently, this method is ONLY used in three places:
    # 1. By the scheduler to allocate resources on the selected destination
    #    hosts.
    # 2. By the conductor LiveMigrationTask to allocate resources on a forced
    #    destination host. In this case, the source node allocations have
    #    already been moved to the migration record so the instance should not
    #    have allocations and _move_operation_alloc_request will not be called.
    # 3. By the conductor ComputeTaskManager to allocate resources on a forced
    #    destination host during evacuate. This case will call the
    #    _move_operation_alloc_request method.
    # This method should not be called by the resource tracker.
    @safe_connect
    @retries
    def claim_resources(self, context, consumer_uuid, alloc_request,
                        project_id, user_id, allocation_request_version,
                        consumer_generation=None):
        """Creates allocation records for the supplied instance UUID against
        the supplied resource providers.

        We check to see if resources have already been claimed for this
        consumer. If so, we assume that a move operation is underway and the
        scheduler is attempting to claim resources against the new (destination
        host). In order to prevent compute nodes currently performing move
        operations from being scheduled to improperly, we create a "doubled-up"
        allocation that consumes resources on *both* the source and the
        destination host during the move operation.

        :param context: The security context
        :param consumer_uuid: The instance's UUID.
        :param alloc_request: The JSON body of the request to make to the
                              placement's PUT /allocations API
        :param project_id: The project_id associated with the allocations.
        :param user_id: The user_id associated with the allocations.
        :param allocation_request_version: The microversion used to request the
                                           allocations.
        :param consumer_generation: The expected generation of the consumer.
                                    None if a new consumer is expected
        :returns: True if the allocations were created, False otherwise.
        :raise AllocationUpdateFailed: If consumer_generation in the
                                       alloc_request does not match with the
                                       placement view.
        """
        # Ensure we don't change the supplied alloc request since it's used in
        # a loop within the scheduler against multiple instance claims
        ar = copy.deepcopy(alloc_request)

        url = '/allocations/%s' % consumer_uuid

        payload = ar

        # We first need to determine if this is a move operation and if so
        # create the "doubled-up" allocation that exists for the duration of
        # the move operation against both the source and destination hosts
        r = self.get(url, global_request_id=context.global_id,
                     version=CONSUMER_GENERATION_VERSION)
        if r.status_code == 200:
            body = r.json()
            current_allocs = body['allocations']
            if current_allocs:
                if 'consumer_generation' not in ar:
                    # this is non-forced evacuation. Evacuation does not use
                    # the migration.uuid to hold the source host allocation
                    # therefore when the scheduler calls claim_resources() then
                    # the two allocations need to be combined. Scheduler does
                    # not know that this is not a new consumer as it only sees
                    # allocation candidates.
                    # Therefore we need to use the consumer generation from
                    # the above GET.
                    # If between the GET and the PUT the consumer generation
                    # changes in placement then we raise
                    # AllocationUpdateFailed.
                    # NOTE(gibi): This only detect a small portion of possible
                    # cases when allocation is modified outside of the this
                    # code path. The rest can only be detected if nova would
                    # cache at least the consumer generation of the instance.
                    consumer_generation = body['consumer_generation']
                else:
                    # this is forced evacuation and the caller
                    # claim_resources_on_destination() provides the consumer
                    # generation it sees in the conductor when it generates the
                    # request.
                    consumer_generation = ar['consumer_generation']
                payload = _move_operation_alloc_request(current_allocs, ar)

        payload['project_id'] = project_id
        payload['user_id'] = user_id

        if (versionutils.convert_version_to_tuple(
                allocation_request_version) >=
                versionutils.convert_version_to_tuple(
                    CONSUMER_GENERATION_VERSION)):
            payload['consumer_generation'] = consumer_generation

        r = self._put_allocations(
            context,
            consumer_uuid,
            payload,
            version=allocation_request_version)
        if r.status_code != 204:
            err = r.json()['errors'][0]
            if err['code'] == 'placement.concurrent_update':
                # NOTE(jaypipes): Yes, it sucks doing string comparison like
                # this but we have no error codes, only error messages.
                # TODO(gibi): Use more granular error codes when available
                if 'consumer generation conflict' in err['detail']:
                    reason = ('another process changed the consumer %s after '
                              'the report client read the consumer state '
                              'during the claim ' % consumer_uuid)
                    raise exception.AllocationUpdateFailed(
                        consumer_uuid=consumer_uuid, error=reason)

                # this is not a consumer generation conflict so it can only be
                # a resource provider generation conflict. The caller does not
                # provide resource provider generation so this is just a
                # placement internal race. We can blindly retry locally.
                reason = ('another process changed the resource providers '
                          'involved in our attempt to put allocations for '
                          'consumer %s' % consumer_uuid)
                raise Retry('claim_resources', reason)
        return r.status_code == 204

    def remove_resources_from_instance_allocation(
            self, context, consumer_uuid, resources):
        """Removes certain resources from the current allocation of the
        consumer.

        :param context: the request context
        :param consumer_uuid: the uuid of the consumer to update
        :param resources: a dict of resources. E.g.:
                              {
                                  <rp_uuid>: {
                                      <resource class>: amount
                                      <other resource class>: amount
                                  }
                                  <other_ rp_uuid>: {
                                      <other resource class>: amount
                                  }
                              }
        :raises AllocationUpdateFailed: if the requested resource cannot be
                removed from the current allocation (e.g. rp is missing from
                the allocation) or there was multiple generation conflict and
                we run out of retires.
        :raises ConsumerAllocationRetrievalFailed: If the current allocation
                cannot be read from placement.
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        """

        # NOTE(gibi): It is just a small wrapper to raise instead of return
        # if we run out of retries.
        if not self._remove_resources_from_instance_allocation(
                context, consumer_uuid, resources):
            error_reason = _("Cannot remove resources %s from the allocation "
                             "due to multiple successive generation conflicts "
                             "in placement.")
            raise exception.AllocationUpdateFailed(
                consumer_uuid=consumer_uuid,
                error=error_reason % resources)

    @retries
    def _remove_resources_from_instance_allocation(
            self, context, consumer_uuid, resources):
        if not resources:
            # Nothing to remove so do not query or update allocation in
            # placement.
            # The True value is only here because the retry decorator returns
            # False when runs out of retries. It would be nicer to raise in
            # that case too.
            return True

        current_allocs = self.get_allocs_for_consumer(context, consumer_uuid)

        if not current_allocs['allocations']:
            error_reason = _("Cannot remove resources %(resources)s from "
                             "allocation %(allocations)s. The allocation is "
                             "empty.")
            raise exception.AllocationUpdateFailed(
                consumer_uuid=consumer_uuid,
                error=error_reason %
                      {'resources': resources, 'allocations': current_allocs})

        try:
            for rp_uuid, resources_to_remove in resources.items():
                allocation_on_rp = current_allocs['allocations'][rp_uuid]
                for rc, value in resources_to_remove.items():
                    allocation_on_rp['resources'][rc] -= value

                    if allocation_on_rp['resources'][rc] < 0:
                        error_reason = _(
                            "Cannot remove resources %(resources)s from "
                            "allocation %(allocations)s. There are not enough "
                            "allocated resources left on %(rp_uuid)s resource "
                            "provider to remove %(amount)d amount of "
                            "%(resource_class)s resources.")
                        raise exception.AllocationUpdateFailed(
                            consumer_uuid=consumer_uuid,
                            error=error_reason %
                                  {'resources': resources,
                                   'allocations': current_allocs,
                                   'rp_uuid': rp_uuid,
                                   'amount': value,
                                   'resource_class': rc})

                    if allocation_on_rp['resources'][rc] == 0:
                        # if no allocation left for this rc then remove it
                        # from the allocation
                        del allocation_on_rp['resources'][rc]
        except KeyError as e:
            error_reason = _("Cannot remove resources %(resources)s from "
                             "allocation %(allocations)s. Key %(missing_key)s "
                             "is missing from the allocation.")
            # rp_uuid is missing from the allocation or resource class is
            # missing from the allocation
            raise exception.AllocationUpdateFailed(
                consumer_uuid=consumer_uuid,
                error=error_reason %
                      {'resources': resources,
                       'allocations': current_allocs,
                       'missing_key': e})

        # we have to remove the rps from the allocation that has no resources
        # any more
        current_allocs['allocations'] = {
            rp_uuid: alloc
            for rp_uuid, alloc in current_allocs['allocations'].items()
            if alloc['resources']}

        r = self._put_allocations(
            context, consumer_uuid, current_allocs)

        if r.status_code != 204:
            err = r.json()['errors'][0]
            if err['code'] == 'placement.concurrent_update':
                reason = ('another process changed the resource providers or '
                          'the consumer involved in our attempt to update '
                          'allocations for consumer %s so we cannot remove '
                          'resources %s from the current allocation %s' %
                          (consumer_uuid, resources, current_allocs))
                # NOTE(gibi): automatic retry is meaningful if we can still
                # remove the resources from the updated allocations. Retry
                # works here as this function (re)queries the allocations.
                raise Retry(
                    'remove_resources_from_instance_allocation', reason)

        # It is only here because the retry decorator returns False when runs
        # out of retries. It would be nicer to raise in that case too.
        return True

    def remove_provider_tree_from_instance_allocation(self, context,
                                                      consumer_uuid,
                                                      root_rp_uuid):
        """Removes every allocation from the consumer that is on the
        specified provider tree.

        Note that this function does not try to remove allocations from sharing
        providers.

        :param context: The security context
        :param consumer_uuid: The UUID of the consumer to manipulate
        :param root_rp_uuid: The root of the provider tree
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        :raises: ConsumerAllocationRetrievalFailed if this call cannot read
                 the current state of the allocations from placement
        :raises: ResourceProviderRetrievalFailed if it cannot collect the RPs
                 in the tree specified by root_rp_uuid.
        """
        current_allocs = self.get_allocs_for_consumer(context, consumer_uuid)
        if not current_allocs['allocations']:
            LOG.error("Expected to find current allocations for %s, but "
                      "found none.", consumer_uuid)
            # TODO(gibi): do not return False as none of the callers
            # do anything with the return value except log
            return False

        rps = self.get_providers_in_tree(context, root_rp_uuid)
        rp_uuids = [rp['uuid'] for rp in rps]

        # go through the current allocations and remove every RP from it that
        # belongs to the RP tree identified by the root_rp_uuid parameter
        has_changes = False
        for rp_uuid in rp_uuids:
            changed = bool(
                current_allocs['allocations'].pop(rp_uuid, None))
            has_changes = has_changes or changed

        # If nothing changed then don't do anything
        if not has_changes:
            LOG.warning(
                "Expected to find allocations referencing resource "
                "provider tree rooted at %s for %s, but found none.",
                root_rp_uuid, consumer_uuid)
            # TODO(gibi): do not return a value as none of the callers
            # do anything with the return value except logging
            return True

        r = self._put_allocations(context, consumer_uuid, current_allocs)
        # TODO(gibi): do not return a value as none of the callers
        # do anything with the return value except logging
        return r.status_code == 204

    def _put_allocations(
            self, context, consumer_uuid, payload,
            version=CONSUMER_GENERATION_VERSION):
        url = '/allocations/%s' % consumer_uuid
        r = self.put(url, payload, version=version,
                     global_request_id=context.global_id)
        if r.status_code != 204:
            LOG.warning("Failed to save allocation for %s. Got HTTP %s: %s",
                        consumer_uuid, r.status_code, r.text)
        return r

    @safe_connect
    @retries
    def move_allocations(self, context, source_consumer_uuid,
                         target_consumer_uuid):
        """Move allocations from one consumer to the other

        Note that this call moves the current allocation from the source
        consumer to the target consumer. If parallel update happens on either
        consumer during this call then Placement will detect that and
        this code will raise AllocationMoveFailed. If you want to move a known
        piece of allocation from source to target then this function might not
        be what you want as it always moves what source has in Placement.

        If the target consumer has allocations but the source consumer does
        not, this method assumes the allocations were already moved and
        returns True.

        :param context: The security context
        :param source_consumer_uuid: the UUID of the consumer from which
                                     allocations are moving
        :param target_consumer_uuid: the UUID of the target consumer for the
                                     allocations
        :returns: True if the move was successful (or already done),
                  False otherwise.
        :raises AllocationMoveFailed: If the source or the target consumer has
                                      been modified while this call tries to
                                      move allocations.
        """
        source_alloc = self.get_allocs_for_consumer(
            context, source_consumer_uuid)
        target_alloc = self.get_allocs_for_consumer(
            context, target_consumer_uuid)

        if target_alloc and target_alloc['allocations']:
            # Check to see if the source allocations still exist because if
            # they don't they might have already been moved to the target.
            if not (source_alloc and source_alloc['allocations']):
                LOG.info('Allocations not found for consumer %s; assuming '
                         'they were already moved to consumer %s',
                         source_consumer_uuid, target_consumer_uuid)
                return True
            LOG.debug('Overwriting current allocation %(allocation)s on '
                      'consumer %(consumer)s',
                      {'allocation': target_alloc,
                       'consumer': target_consumer_uuid})

        new_allocs = {
            source_consumer_uuid: {
                # 'allocations': {} means we are removing the allocation from
                # the source consumer
                'allocations': {},
                'project_id': source_alloc['project_id'],
                'user_id': source_alloc['user_id'],
                'consumer_generation': source_alloc['consumer_generation']},
            target_consumer_uuid: {
                'allocations': source_alloc['allocations'],
                # NOTE(gibi): Is there any case when we need to keep the
                # project_id and user_id of the target allocation that we are
                # about to overwrite?
                'project_id': source_alloc['project_id'],
                'user_id': source_alloc['user_id'],
                'consumer_generation': target_alloc.get('consumer_generation')
            }
        }
        r = self.post('/allocations', new_allocs,
                      version=CONSUMER_GENERATION_VERSION,
                      global_request_id=context.global_id)
        if r.status_code != 204:
            err = r.json()['errors'][0]
            if err['code'] == 'placement.concurrent_update':
                # NOTE(jaypipes): Yes, it sucks doing string comparison like
                # this but we have no error codes, only error messages.
                # TODO(gibi): Use more granular error codes when available
                if 'consumer generation conflict' in err['detail']:
                    raise exception.AllocationMoveFailed(
                        source_consumer=source_consumer_uuid,
                        target_consumer=target_consumer_uuid,
                        error=r.text)

                reason = ('another process changed the resource providers '
                          'involved in our attempt to post allocations for '
                          'consumer %s' % target_consumer_uuid)
                raise Retry('move_allocations', reason)
            else:
                LOG.warning(
                    'Unable to post allocations for consumer '
                    '%(uuid)s (%(code)i %(text)s)',
                    {'uuid': target_consumer_uuid,
                     'code': r.status_code,
                     'text': r.text})
        return r.status_code == 204

    @retries
    def put_allocations(self, context, consumer_uuid, payload):
        """Creates allocation records for the supplied consumer UUID based on
        the provided allocation dict

        :param context: The security context
        :param consumer_uuid: The instance's UUID.
        :param payload: Dict in the format expected by the placement
            PUT /allocations/{consumer_uuid} API
        :returns: True if the allocations were created, False otherwise.
        :raises: Retry if the operation should be retried due to a concurrent
            resource provider update.
        :raises: AllocationUpdateFailed if placement returns a consumer
            generation conflict
        :raises: PlacementAPIConnectFailure on failure to communicate with the
            placement API
        """

        try:
            r = self._put_allocations(context, consumer_uuid, payload)
        except ks_exc.ClientException:
            raise exception.PlacementAPIConnectFailure()

        if r.status_code != 204:
            err = r.json()['errors'][0]
            # NOTE(jaypipes): Yes, it sucks doing string comparison like this
            # but we have no error codes, only error messages.
            # TODO(gibi): Use more granular error codes when available
            if err['code'] == 'placement.concurrent_update':
                if 'consumer generation conflict' in err['detail']:
                    raise exception.AllocationUpdateFailed(
                        consumer_uuid=consumer_uuid, error=err['detail'])
                # this is not a consumer generation conflict so it can only be
                # a resource provider generation conflict. The caller does not
                # provide resource provider generation so this is just a
                # placement internal race. We can blindly retry locally.
                reason = ('another process changed the resource providers '
                          'involved in our attempt to put allocations for '
                          'consumer %s' % consumer_uuid)
                raise Retry('put_allocations', reason)
        return r.status_code == 204

    @safe_connect
    def delete_allocation_for_instance(self, context, uuid,
                                       consumer_type='instance'):
        """Delete the instance allocation from placement

        :param context: The security context
        :param uuid: the instance or migration UUID which will be used
                     as the consumer UUID towards placement
        :param consumer_type: The type of the consumer specified by uuid.
                              'instance' or 'migration' (Default: instance)
        :return: Returns True if the allocation is successfully deleted by this
                 call. Returns False if the allocation does not exist.
        :raises AllocationDeleteFailed: If the allocation cannot be read from
                placement or it is changed by another process while we tried to
                delete it.
        """
        url = '/allocations/%s' % uuid
        # We read the consumer generation then try to put an empty allocation
        # for that consumer. If between the GET and the PUT the consumer
        # generation changes then we raise AllocationDeleteFailed.
        # NOTE(gibi): This only detect a small portion of possible cases when
        # allocation is modified outside of the delete code path. The rest can
        # only be detected if nova would cache at least the consumer generation
        # of the instance.
        # NOTE(gibi): placement does not return 404 for non-existing consumer
        # but returns an empty consumer instead. Putting an empty allocation to
        # that non-existing consumer won't be 404 or other error either.
        r = self.get(url, global_request_id=context.global_id,
                     version=CONSUMER_GENERATION_VERSION)
        if not r:
            # at the moment there is no way placement returns a failure so we
            # could even delete this code
            LOG.warning('Unable to delete allocation for %(consumer_type)s '
                        '%(uuid)s. Got %(code)i while retrieving existing '
                        'allocations: (%(text)s)',
                        {'consumer_type': consumer_type,
                         'uuid': uuid,
                         'code': r.status_code,
                         'text': r.text})
            raise exception.AllocationDeleteFailed(consumer_uuid=uuid,
                                                   error=r.text)
        allocations = r.json()
        if allocations['allocations'] == {}:
            # the consumer did not exist in the first place
            LOG.debug('Cannot delete allocation for %s consumer in placement '
                      'as consumer does not exist', uuid)
            return False

        # removing all resources from the allocation will auto delete the
        # consumer in placement
        allocations['allocations'] = {}
        r = self.put(url, allocations, global_request_id=context.global_id,
                     version=CONSUMER_GENERATION_VERSION)
        if r.status_code == 204:
            LOG.info('Deleted allocation for %(consumer_type)s %(uuid)s',
                     {'consumer_type': consumer_type,
                      'uuid': uuid})
            return True
        else:
            LOG.warning('Unable to delete allocation for %(consumer_type)s '
                        '%(uuid)s: (%(code)i %(text)s)',
                        {'consumer_type': consumer_type,
                         'uuid': uuid,
                         'code': r.status_code,
                         'text': r.text})
            raise exception.AllocationDeleteFailed(consumer_uuid=uuid,
                                                   error=r.text)

    def get_allocations_for_resource_provider(self, context, rp_uuid):
        """Retrieves the allocations for a specific provider.

        :param context: The nova.context.RequestContext auth context
        :param rp_uuid: The UUID of the provider.
        :return: ProviderAllocInfo namedtuple.
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        :raises: ResourceProviderAllocationRetrievalFailed if the placement API
                 call fails.
        """
        url = '/resource_providers/%s/allocations' % rp_uuid
        resp = self.get(url, global_request_id=context.global_id)
        if not resp:
            raise exception.ResourceProviderAllocationRetrievalFailed(
                rp_uuid=rp_uuid, error=resp.text)

        data = resp.json()
        return ProviderAllocInfo(allocations=data['allocations'])

    def get_allocations_for_provider_tree(self, context, nodename):
        """Retrieve allocation records associated with all providers in the
        provider tree.

        This method uses the cache exclusively to discover providers. The
        caller must ensure that the cache is populated.

        This method is (and should remain) used exclusively in the reshaper
        flow by the resource tracker.

        Note that, in addition to allocations on providers in this compute
        node's provider tree, this method will return allocations on sharing
        providers if those allocations are associated with a consumer on this
        compute node. This is intentional and desirable. But it may also return
        allocations belonging to other hosts, e.g. if this is happening in the
        middle of an evacuate. ComputeDriver.update_provider_tree is supposed
        to ignore such allocations if they appear.

        :param context: The security context
        :param nodename: The name of a node for whose tree we are getting
                allocations.
        :returns: A dict, keyed by consumer UUID, of allocation records:
                { $CONSUMER_UUID: {
                      # The shape of each "allocations" dict below is identical
                      # to the return from GET /allocations/{consumer_uuid}
                      "allocations": {
                          $RP_UUID: {
                              "generation": $RP_GEN,
                              "resources": {
                                  $RESOURCE_CLASS: $AMOUNT,
                                  ...
                              },
                          },
                          ...
                      },
                      "project_id": $PROJ_ID,
                      "user_id": $USER_ID,
                      "consumer_generation": $CONSUMER_GEN,
                  },
                  ...
                }
        :raises: keystoneauth1.exceptions.ClientException if placement API
                 communication fails.
        :raises: ResourceProviderAllocationRetrievalFailed if a placement API
                 call fails.
        :raises: ValueError if there's no provider with the specified nodename.
        """
        # NOTE(efried): Despite our best efforts, there are some scenarios
        # (e.g. mid-evacuate) where we can still wind up returning allocations
        # against providers belonging to other hosts. We count on the consumer
        # of this information (i.e. the reshaper flow of a virt driver's
        # update_provider_tree) to ignore allocations associated with any
        # provider it is not reshaping - and it should never be reshaping
        # providers belonging to other hosts.

        # We can't get *all* allocations for associated sharing providers
        # because some of those will belong to consumers on other hosts. So we
        # have to discover all the consumers associated with the providers in
        # the "local" tree (we use the nodename to figure out which providers
        # are "local").
        # All we want to do at this point is accumulate the set of consumers we
        # care about.
        consumers = set()
        # TODO(efried): This could be more efficient if placement offered an
        # operation like GET /allocations?rp_uuid=in:<list>
        for u in self._provider_tree.get_provider_uuids(name_or_uuid=nodename):
            alloc_info = self.get_allocations_for_resource_provider(context, u)
            # The allocations dict is keyed by consumer UUID
            consumers.update(alloc_info.allocations)

        # Now get all the allocations for each of these consumers to build the
        # result. This will include allocations on sharing providers, which is
        # intentional and desirable. But it may also include allocations
        # belonging to other hosts, e.g. if this is happening in the middle of
        # an evacuate. ComputeDriver.update_provider_tree is supposed to ignore
        # such allocations if they appear.
        # TODO(efried): This could be more efficient if placement offered an
        # operation like GET /allocations?consumer_uuid=in:<list>
        return {consumer: self.get_allocs_for_consumer(context, consumer)
                for consumer in consumers}

    def delete_resource_provider(self, context, compute_node, cascade=False):
        """Deletes the ResourceProvider record for the compute_node.

        :param context: The security context
        :param compute_node: The nova.objects.ComputeNode object that is the
                             resource provider being deleted.
        :param cascade: Boolean value that, when True, will first delete any
                        associated Allocation records for the compute node
        :raises: keystoneauth1.exceptions.base.ClientException on failure to
                 communicate with the placement API
        """
        nodename = compute_node.hypervisor_hostname
        host = compute_node.host
        rp_uuid = compute_node.uuid
        if cascade:
            # Delete any allocations for this resource provider.
            # Since allocations are by consumer, we get the consumers on this
            # host, which are its instances.
            # NOTE(mriedem): This assumes the only allocations on this node
            # are instances, but there could be migration consumers if the
            # node is deleted during a migration or allocations from an
            # evacuated host (bug 1829479). Obviously an admin shouldn't
            # do that but...you know. I guess the provider deletion should fail
            # in that case which is what we'd want to happen.
            instance_uuids = objects.InstanceList.get_uuids_by_host_and_node(
                context, host, nodename)
            for instance_uuid in instance_uuids:
                self.delete_allocation_for_instance(context, instance_uuid)
        # Ensure to delete resource provider in tree by top-down
        # traversable order.
        rps_to_refresh = self.get_providers_in_tree(context, rp_uuid)
        self._provider_tree.populate_from_iterable(rps_to_refresh)
        provider_uuids = self._provider_tree.get_provider_uuids_in_tree(
            rp_uuid)
        for provider_uuid in provider_uuids[::-1]:
            try:
                self._delete_provider(provider_uuid,
                                      global_request_id=context.global_id)
            except (exception.ResourceProviderInUse,
                    exception.ResourceProviderDeletionFailed):
                # TODO(efried): Raise these.  Right now this is being
                #  left a no-op for backward compatibility.
                pass

    def get_provider_by_name(self, context, name):
        """Queries the placement API for resource provider information matching
        a supplied name.

        :param context: The security context
        :param name: Name of the resource provider to look up
        :return: A dict of resource provider information including the
                 provider's UUID and generation
        :raises: `exception.ResourceProviderNotFound` when no such provider was
                 found
        :raises: PlacementAPIConnectFailure if there was an issue making the
                 API call to placement.
        """
        try:
            resp = self.get("/resource_providers?name=%s" % name,
                            global_request_id=context.global_id)
        except ks_exc.ClientException as ex:
            LOG.error('Failed to get resource provider by name: %s. Error: %s',
                      name, six.text_type(ex))
            raise exception.PlacementAPIConnectFailure()

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
    def aggregate_add_host(self, context, agg_uuid, host_name=None,
                           rp_uuid=None):
        """Looks up a resource provider by the supplied host name, and adds the
        aggregate with supplied UUID to that resource provider.

        :note: This method does NOT use the cached provider tree. It is only
               called from the Compute API when a nova host aggregate is
               modified

        :param context: The security context
        :param agg_uuid: UUID of the aggregate being modified
        :param host_name: Name of the nova-compute service worker to look up a
                          resource provider for. Either host_name or rp_uuid is
                          required.
        :param rp_uuid: UUID of the resource provider to add to the aggregate.
                        Either host_name or rp_uuid is required.
        :raises: `exceptions.ResourceProviderNotFound` if no resource provider
                  matching the host name could be found from the placement API
        :raises: `exception.ResourceProviderAggregateRetrievalFailed` when
                 failing to get a provider's existing aggregates
        :raises: `exception.ResourceProviderUpdateFailed` if there was a
                 failure attempting to save the provider aggregates
        :raises: `exception.ResourceProviderUpdateConflict` if a concurrent
                 update to the provider was detected.
        :raises: PlacementAPIConnectFailure if there was an issue making an
                 API call to placement.
        """
        if host_name is None and rp_uuid is None:
            raise ValueError(_("Either host_name or rp_uuid is required"))
        if rp_uuid is None:
            rp_uuid = self.get_provider_by_name(context, host_name)['uuid']

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
        :raises: PlacementAPIConnectFailure if there was an issue making an
                 API call to placement.
        """
        rp_uuid = self.get_provider_by_name(context, host_name)['uuid']
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

    @staticmethod
    def _handle_usages_error_from_placement(resp, project_id, user_id=None):
        msg = ('[%(placement_req_id)s] Failed to retrieve usages for project '
               '%(project_id)s and user %(user_id)s. Got %(status_code)d: '
               '%(err_text)s')
        args = {'placement_req_id': get_placement_request_id(resp),
                'project_id': project_id,
                'user_id': user_id or 'N/A',
                'status_code': resp.status_code,
                'err_text': resp.text}
        LOG.error(msg, args)
        raise exception.UsagesRetrievalFailed(project_id=project_id,
                                              user_id=user_id or 'N/A')

    @retrying.retry(stop_max_attempt_number=4,
                    retry_on_exception=lambda e: isinstance(
                        e, ks_exc.ConnectFailure))
    def _get_usages(self, context, project_id, user_id=None):
        url = '/usages?project_id=%s' % project_id
        if user_id:
            url = ''.join([url, '&user_id=%s' % user_id])
        return self.get(url, version=GET_USAGES_VERSION,
                        global_request_id=context.global_id)

    def get_usages_counts_for_quota(self, context, project_id, user_id=None):
        """Get the usages counts for the purpose of counting quota usage.

        :param context: The request context
        :param project_id: The project_id to count across
        :param user_id: The user_id to count across
        :returns: A dict containing the project-scoped and user-scoped counts
                  if user_id is specified. For example:
                    {'project': {'cores': <count across project>,
                                 'ram': <count across project>},
                    {'user': {'cores': <count across user>,
                              'ram': <count across user>},
        :raises: `exception.UsagesRetrievalFailed` if a placement API call
                 fails
        """
        def _get_core_usages(usages):
            """For backward-compatible with existing behavior, the quota limit
            on flavor.vcpus. That included the shared and dedicated CPU. So
            we need to count both the orc.VCPU and orc.PCPU at here.
            """
            vcpus = usages['usages'].get(orc.VCPU, 0)
            pcpus = usages['usages'].get(orc.PCPU, 0)
            return vcpus + pcpus

        total_counts = {'project': {}}
        # First query counts across all users of a project
        LOG.debug('Getting usages for project_id %s from placement',
                  project_id)
        resp = self._get_usages(context, project_id)
        if resp:
            data = resp.json()
            # The response from placement will not contain a resource class if
            # there is no usage. We can consider a missing class to be 0 usage.
            cores = _get_core_usages(data)
            ram = data['usages'].get(orc.MEMORY_MB, 0)
            total_counts['project'] = {'cores': cores, 'ram': ram}
        else:
            self._handle_usages_error_from_placement(resp, project_id)
        # If specified, second query counts across one user in the project
        if user_id:
            LOG.debug('Getting usages for project_id %s and user_id %s from '
                      'placement', project_id, user_id)
            resp = self._get_usages(context, project_id, user_id=user_id)
            if resp:
                data = resp.json()
                cores = _get_core_usages(data)
                ram = data['usages'].get(orc.MEMORY_MB, 0)
                total_counts['user'] = {'cores': cores, 'ram': ram}
            else:
                self._handle_usages_error_from_placement(resp, project_id,
                                                         user_id=user_id)
        return total_counts

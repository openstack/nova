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

import copy
import functools
import re
import time

from keystoneauth1 import exceptions as ks_exc
from keystoneauth1 import loading as keystone
from oslo_log import log as logging
from six.moves.urllib import parse

from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.i18n import _LE, _LI, _LW
from nova import objects
from nova.objects import fields
from nova.scheduler import utils as scheduler_utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
VCPU = fields.ResourceClass.VCPU
MEMORY_MB = fields.ResourceClass.MEMORY_MB
DISK_GB = fields.ResourceClass.DISK_GB
_RE_INV_IN_USE = re.compile("Inventory for (.+) on resource provider "
                            "(.+) in use")
WARN_EVERY = 10


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
                self,
                _LW('The placement API endpoint not found. Placement is '
                    'optional in Newton, but required in Ocata. Please '
                    'enable the placement service before upgrading.'))
        except ks_exc.MissingAuthPlugin:
            warn_limit(
                self,
                _LW('No authentication information found for placement '
                    'API. Placement is optional in Newton, but required '
                    'in Ocata. Please enable the placement service '
                    'before upgrading.'))
        except ks_exc.Unauthorized:
            warn_limit(
                self,
                _LW('Placement service credentials do not work. '
                    'Placement is optional in Newton, but required '
                    'in Ocata. Please enable the placement service '
                    'before upgrading.'))
        except ks_exc.DiscoveryFailure:
            # TODO(_gryf): Looks like DiscoveryFailure is not the only missing
            # exception here. In Pike we should take care about keystoneauth1
            # failures handling globally.
            warn_limit(self,
                       _LW('Discovering suitable URL for placement API '
                           'failed.'))
        except ks_exc.ConnectFailure:
            msg = _LW('Placement API service is not responding.')
            LOG.warning(msg)
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
    request for a destination host, return a new allocation request that
    contains resources claimed against both source and destination, accounting
    for shared providers.

    Also accounts for a resize to the same host where the source and dest
    compute node resource providers are going to be the same. In that case
    we sum the resource allocations for the single provider.

    :param source_allocs: Dict, keyed by resource provider UUID, of resources
                          allocated on the source host
    :param dest_alloc_request: The allocation request for resources against the
                               destination host
    """
    LOG.debug("Doubling-up allocation request for move operation.")
    # Remove any allocations against resource providers that are
    # already allocated against on the source host (like shared storage
    # providers)
    cur_rp_uuids = set(source_allocs.keys())
    new_rp_uuids = set(a['resource_provider']['uuid']
                       for a in dest_alloc_req['allocations']) - cur_rp_uuids

    current_allocs = [
        {
            'resource_provider': {
                'uuid': cur_rp_uuid,
            },
            'resources': alloc['resources'],
        } for cur_rp_uuid, alloc in source_allocs.items()
    ]
    new_alloc_req = {'allocations': current_allocs}
    for alloc in dest_alloc_req['allocations']:
        if alloc['resource_provider']['uuid'] in new_rp_uuids:
            new_alloc_req['allocations'].append(alloc)
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
            for current_alloc in current_allocs:
                # Find the matching resource provider allocations by UUID.
                if (current_alloc['resource_provider']['uuid'] ==
                        alloc['resource_provider']['uuid']):
                    # Now sum the current allocation resource amounts with
                    # the new allocation resource amounts.
                    scheduler_utils.merge_resources(current_alloc['resources'],
                                                    alloc['resources'])

    LOG.debug("New allocation request containing both source and "
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
        return response.headers.get(
            'openstack-request-id',
            response.headers.get('x-openstack-request-id'))


class SchedulerReportClient(object):
    """Client class for updating the scheduler."""

    def __init__(self):
        # A dict, keyed by the resource provider UUID, of ResourceProvider
        # objects that will have their inventories and allocations tracked by
        # the placement API for the compute host
        self._resource_providers = {}
        # A dict, keyed by resource provider UUID, of sets of aggregate UUIDs
        # the provider is associated with
        self._provider_aggregate_map = {}
        auth_plugin = keystone.load_auth_from_conf_options(
            CONF, 'placement')
        self._client = keystone.load_session_from_conf_options(
            CONF, 'placement', auth=auth_plugin)
        # NOTE(danms): Keep track of how naggy we've been
        self._warn_count = 0
        self.ks_filter = {'service_type': 'placement',
                          'region_name': CONF.placement.os_region_name,
                          'interface': CONF.placement.os_interface}

    def get(self, url, version=None):
        kwargs = {}
        if version is not None:
            # TODO(mriedem): Perform some version discovery at some point.
            kwargs = {
                'headers': {
                    'OpenStack-API-Version': 'placement %s' % version
                },
            }
        return self._client.get(
            url,
            endpoint_filter=self.ks_filter, raise_exc=False, **kwargs)

    def post(self, url, data, version=None):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        kwargs = {}
        if version is not None:
            # TODO(mriedem): Perform some version discovery at some point.
            kwargs = {
                'headers': {
                    'OpenStack-API-Version': 'placement %s' % version
                },
            }
        return self._client.post(
            url, json=data,
            endpoint_filter=self.ks_filter, raise_exc=False, **kwargs)

    def put(self, url, data, version=None):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        kwargs = {}
        if version is not None:
            # TODO(mriedem): Perform some version discovery at some point.
            kwargs = {
                'headers': {
                    'OpenStack-API-Version': 'placement %s' % version
                },
            }
        if data:
            kwargs['json'] = data
        return self._client.put(
            url, endpoint_filter=self.ks_filter, raise_exc=False,
            **kwargs)

    def delete(self, url, version=None):
        kwargs = {}
        if version is not None:
            # TODO(mriedem): Perform some version discovery at some point.
            kwargs = {
                'headers': {
                    'OpenStack-API-Version': 'placement %s' % version
                },
            }
        return self._client.delete(
            url,
            endpoint_filter=self.ks_filter, raise_exc=False, **kwargs)

    @safe_connect
    def get_allocation_candidates(self, resources):
        """Returns a tuple of (allocation_requests, provider_summaries).

        The allocation requests are a collection of potential JSON objects that
        can be passed to the PUT /allocations/{consumer_uuid} Placement REST
        API to claim resources against one or more resource providers that meet
        the requested resource constraints.

        The provider summaries is a dict, keyed by resource provider UUID, of
        inventory and capacity information for any resource provider involved
        in the allocation requests.

        :returns: A tuple with a list of allocation request dicts and a dict of
                  provider information or (None, None) if the request failed

        :param resources: A dict, keyed by resource class name, of requested
                          amounts of those resources
        """
        resource_query = ",".join(
            sorted("%s:%s" % (rc, amount)
            for (rc, amount) in resources.items()))
        qs_params = {
            'resources': resource_query,
        }

        url = "/allocation_candidates?%s" % parse.urlencode(qs_params)
        resp = self.get(url, version='1.10')
        if resp.status_code == 200:
            data = resp.json()
            return data['allocation_requests'], data['provider_summaries']

        msg = ("Failed to retrieve allocation candidates from placement API "
               "for filters %(resources)s. Got %(status_code)d: %(err_text)s.")
        args = {
            'resources': resources,
            'status_code': resp.status_code,
            'err_text': resp.text,
        }
        LOG.error(msg, args)
        return None, None

    @safe_connect
    def _get_provider_aggregates(self, rp_uuid):
        """Queries the placement API for a resource provider's aggregates.
        Returns a set() of aggregate UUIDs or None if no such resource provider
        was found or there was an error communicating with the placement API.

        :param rp_uuid: UUID of the resource provider to grab aggregates for.
        """
        resp = self.get("/resource_providers/%s/aggregates" % rp_uuid,
                        version='1.1')
        if resp.status_code == 200:
            data = resp.json()
            return set(data['aggregates'])

        placement_req_id = get_placement_request_id(resp)
        if resp.status_code == 404:
            msg = _LW("[%(placement_req_id)s] Tried to get a provider's "
                      "aggregates; however the provider %(uuid)s does not "
                      "exist.")
            args = {
                'uuid': rp_uuid,
                'placement_req_id': placement_req_id,
            }
            LOG.warning(msg, args)
        else:
            msg = _LE("[%(placement_req_id)s] Failed to retrieve aggregates "
                      "from placement API for resource provider with UUID "
                      "%(uuid)s. Got %(status_code)d: %(err_text)s.")
            args = {
                'placement_req_id': placement_req_id,
                'uuid': rp_uuid,
                'status_code': resp.status_code,
                'err_text': resp.text,
            }
            LOG.error(msg, args)

    @safe_connect
    def _get_resource_provider(self, uuid):
        """Queries the placement API for a resource provider record with the
        supplied UUID.

        :param uuid: UUID identifier for the resource provider to look up
        :return: A dict of resource provider information if found or None if no
                 such resource provider could be found.
        :raise: ResourceProviderRetrievalFailed on error.
        """
        resp = self.get("/resource_providers/%s" % uuid)
        if resp.status_code == 200:
            data = resp.json()
            return data
        elif resp.status_code == 404:
            return None
        else:
            placement_req_id = get_placement_request_id(resp)
            msg = _LE("[%(placement_req_id)s] Failed to retrieve resource "
                      "provider record from placement API for UUID %(uuid)s. "
                      "Got %(status_code)d: %(err_text)s.")
            args = {
                'uuid': uuid,
                'status_code': resp.status_code,
                'err_text': resp.text,
                'placement_req_id': placement_req_id,
            }
            LOG.error(msg, args)
            raise exception.ResourceProviderRetrievalFailed(uuid=uuid)

    @safe_connect
    def _create_resource_provider(self, uuid, name):
        """Calls the placement API to create a new resource provider record.

        :param uuid: UUID of the new resource provider
        :param name: Name of the resource provider
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
        resp = self.post(url, payload)
        placement_req_id = get_placement_request_id(resp)
        if resp.status_code == 201:
            msg = _LI("[%(placement_req_id)s] Created resource provider "
                      "record via placement API for resource provider with "
                      "UUID %(uuid)s and name %(name)s.")
            args = {
                'uuid': uuid,
                'name': name,
                'placement_req_id': placement_req_id,
            }
            LOG.info(msg, args)
            return dict(
                    uuid=uuid,
                    name=name,
                    generation=0,
            )

        # TODO(efried): Push error codes from placement, and use 'em.
        name_conflict = 'Conflicting resource provider name:'
        if resp.status_code == 409 and name_conflict not in resp.text:
            # Another thread concurrently created a resource provider with the
            # same UUID. Log a warning and then just return the resource
            # provider object from _get_resource_provider()
            msg = _LI("[%(placement_req_id)s] Another thread already created "
                      "a resource provider with the UUID %(uuid)s. Grabbing "
                      "that record from the placement API.")
            args = {
                'uuid': uuid,
                'placement_req_id': placement_req_id,
            }
            LOG.info(msg, args)
            return self._get_resource_provider(uuid)

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

    def _ensure_resource_provider(self, uuid, name=None):
        """Ensures that the placement API has a record of a resource provider
        with the supplied UUID. If not, creates the resource provider record in
        the placement API for the supplied UUID, optionally passing in a name
        for the resource provider.

        The found or created resource provider object is returned from this
        method. If the resource provider object for the supplied uuid was not
        found and the resource provider record could not be created in the
        placement API, an exception is raised.

        If this method returns successfully, callers are assured both that
        the placement API contains a record of the provider and the local cache
        of resource provider information contains a record of the provider.

        :param uuid: UUID identifier for the resource provider to ensure exists
        :param name: Optional name for the resource provider if the record
                     does not exist. If empty, the name is set to the UUID
                     value
        """
        if uuid in self._resource_providers:
            # NOTE(jaypipes): This isn't optimal to check if aggregate
            # associations have changed each time we call
            # _ensure_resource_provider() and get a hit on the local cache of
            # provider objects, however the alternative is to force operators
            # to restart all their nova-compute workers every time they add or
            # change an aggregate. We might optionally want to add some sort of
            # cache refresh delay or interval as an optimization?
            msg = "Refreshing aggregate associations for resource provider %s"
            LOG.debug(msg, uuid)
            aggs = self._get_provider_aggregates(uuid)
            self._provider_aggregate_map[uuid] = aggs
            return self._resource_providers[uuid]

        rp = self._get_resource_provider(uuid)
        if rp is None:
            rp = self._create_resource_provider(uuid, name or uuid)
            # If @safe_connect can't establish a connection to the placement
            # service, like if placement isn't running or nova-compute is
            # mis-configured for authentication, we'll get None back and need
            # to treat it like we couldn't create the provider (because we
            # couldn't).
            if rp is None:
                raise exception.ResourceProviderCreationFailed(
                    name=name or uuid)

        msg = "Grabbing aggregate associations for resource provider %s"
        LOG.debug(msg, uuid)
        aggs = self._get_provider_aggregates(uuid)
        self._resource_providers[uuid] = rp
        self._provider_aggregate_map[uuid] = aggs
        return rp

    def _get_inventory(self, rp_uuid):
        url = '/resource_providers/%s/inventories' % rp_uuid
        result = self.get(url)
        if not result:
            return {'inventories': {}}
        return result.json()

    def _get_inventory_and_update_provider_generation(self, rp_uuid):
        """Helper method that retrieves the current inventory for the supplied
        resource provider according to the placement API. If the cached
        generation of the resource provider is not the same as the generation
        returned from the placement API, we update the cached generation.
        """
        curr = self._get_inventory(rp_uuid)

        # Update our generation immediately, if possible. Even if there
        # are no inventories we should always have a generation but let's
        # be careful.
        server_gen = curr.get('resource_provider_generation')
        if server_gen:
            my_rp = self._resource_providers[rp_uuid]
            if server_gen != my_rp['generation']:
                LOG.debug('Updating our resource provider generation '
                          'from %(old)i to %(new)i',
                          {'old': my_rp['generation'],
                           'new': server_gen})
            my_rp['generation'] = server_gen
        return curr

    def _update_inventory_attempt(self, rp_uuid, inv_data):
        """Update the inventory for this resource provider if needed.

        :param rp_uuid: The resource provider UUID for the operation
        :param inv_data: The new inventory for the resource provider
        :returns: True if the inventory was updated (or did not need to be),
                  False otherwise.
        """
        curr = self._get_inventory_and_update_provider_generation(rp_uuid)

        # Check to see if we need to update placement's view
        if inv_data == curr.get('inventories', {}):
            return True

        cur_rp_gen = self._resource_providers[rp_uuid]['generation']
        payload = {
            'resource_provider_generation': cur_rp_gen,
            'inventories': inv_data,
        }
        url = '/resource_providers/%s/inventories' % rp_uuid
        result = self.put(url, payload)
        if result.status_code == 409:
            LOG.info(_LI('[%(placement_req_id)s] Inventory update conflict '
                         'for %(resource_provider_uuid)s with generation ID '
                         '%(generation_id)s'),
                     {'placement_req_id': get_placement_request_id(result),
                      'resource_provider_uuid': rp_uuid,
                      'generation_id': cur_rp_gen})
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
            match = _RE_INV_IN_USE.search(result.text)
            if match:
                rc = match.group(1)
                raise exception.InventoryInUse(
                    resource_classes=rc,
                    resource_provider=rp_uuid,
                )

            # Invalidate our cache and re-fetch the resource provider
            # to be sure to get the latest generation.
            del self._resource_providers[rp_uuid]
            # NOTE(jaypipes): We don't need to pass a name parameter to
            # _ensure_resource_provider() because we know the resource provider
            # record already exists. We're just reloading the record here.
            self._ensure_resource_provider(rp_uuid)
            return False
        elif not result:
            placement_req_id = get_placement_request_id(result)
            LOG.warning(_LW('[%(placement_req_id)s] Failed to update '
                            'inventory for resource provider '
                            '%(uuid)s: %(status)i %(text)s'),
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
            LOG.info(
                _LI('[%(placement_req_id)s] Received unexpected response code '
                    '%(code)i while trying to update inventory for resource '
                    'provider %(uuid)s: %(text)s'),
                {'placement_req_id': placement_req_id,
                 'uuid': rp_uuid,
                 'code': result.status_code,
                 'text': result.text})
            return False

        # Update our view of the generation for next time
        updated_inventories_result = result.json()
        new_gen = updated_inventories_result['resource_provider_generation']

        self._resource_providers[rp_uuid]['generation'] = new_gen
        LOG.debug('Updated inventory for %s at generation %i',
                  rp_uuid, new_gen)
        return True

    @safe_connect
    def _update_inventory(self, rp_uuid, inv_data):
        for attempt in (1, 2, 3):
            if rp_uuid not in self._resource_providers:
                # NOTE(danms): Either we failed to fetch/create the RP
                # on our first attempt, or a previous attempt had to
                # invalidate the cache, and we were unable to refresh
                # it. Bail and try again next time.
                LOG.warning(_LW(
                    'Unable to refresh my resource provider record'))
                return False
            if self._update_inventory_attempt(rp_uuid, inv_data):
                return True
            time.sleep(1)
        return False

    @safe_connect
    def _delete_inventory(self, rp_uuid):
        """Deletes all inventory records for a resource provider with the
        supplied UUID.

        First attempt to DELETE the inventory using microversion 1.5. If
        this results in a 406, fail over to a PUT.
        """
        curr = self._get_inventory_and_update_provider_generation(rp_uuid)

        # Check to see if we need to update placement's view
        if not curr.get('inventories', {}):
            msg = "No inventory to delete from resource provider %s."
            LOG.debug(msg, rp_uuid)
            return

        msg = _LI("Compute node %s reported no inventory but previous "
                  "inventory was detected. Deleting existing inventory "
                  "records.")
        LOG.info(msg, rp_uuid)

        url = '/resource_providers/%s/inventories' % rp_uuid
        r = self.delete(url, version="1.5")
        placement_req_id = get_placement_request_id(r)
        cur_rp_gen = self._resource_providers[rp_uuid]['generation']
        msg_args = {
            'rp_uuid': rp_uuid,
            'placement_req_id': placement_req_id,
        }
        if r.status_code == 406:
            # microversion 1.5 not available so try the earlier way
            # TODO(cdent): When we're happy that all placement
            # servers support microversion 1.5 we can remove this
            # call and the associated code.
            LOG.debug('Falling back to placement API microversion 1.0 '
                      'for deleting all inventory for a resource provider.')
            payload = {
                'resource_provider_generation': cur_rp_gen,
                'inventories': {},
            }
            r = self.put(url, payload)
            placement_req_id = get_placement_request_id(r)
            msg_args['placement_req_id'] = placement_req_id
            if r.status_code == 200:
                # Update our view of the generation for next time
                updated_inv = r.json()
                new_gen = updated_inv['resource_provider_generation']

                self._resource_providers[rp_uuid]['generation'] = new_gen
                msg_args['generation'] = new_gen
                LOG.info(_LI("[%(placement_req_id)s] Deleted all inventory "
                             "for resource provider %(rp_uuid)s at generation "
                             "%(generation)i."),
                         msg_args)
                return

        if r.status_code == 204:
            self._resource_providers[rp_uuid]['generation'] = cur_rp_gen + 1
            LOG.info(_LI("[%(placement_req_id)s] Deleted all inventory for "
                         "resource provider %(rp_uuid)s."),
                     msg_args)
            return
        elif r.status_code == 404:
            # This can occur if another thread deleted the inventory and the
            # resource provider already
            LOG.debug("[%(placement_req_id)s] Resource provider %(rp_uuid)s "
                      "deleted by another thread when trying to delete "
                      "inventory. Ignoring.",
                      msg_args)
            self._resource_providers.pop(rp_uuid, None)
            self._provider_aggregate_map.pop(rp_uuid, None)
            return
        elif r.status_code == 409:
            rc_str = _extract_inventory_in_use(r.text)
            if rc_str is not None:
                msg = _LW("[%(placement_req_id)s] We cannot delete inventory "
                          "%(rc_str)s for resource provider %(rp_uuid)s "
                          "because the inventory is in use.")
                msg_args['rc_str'] = rc_str
                LOG.warning(msg, msg_args)
                return

        msg = _LE("[%(placement_req_id)s] Failed to delete inventory for "
                  "resource provider %(rp_uuid)s. Got error response: "
                  "%(err)s.")
        msg_args['err'] = r.text
        LOG.error(msg, msg_args)

    def set_inventory_for_provider(self, rp_uuid, rp_name, inv_data):
        """Given the UUID of a provider, set the inventory records for the
        provider to the supplied dict of resources.

        :param rp_uuid: UUID of the resource provider to set inventory for
        :param rp_name: Name of the resource provider in case we need to create
                        a record for it in the placement API
        :param inv_data: Dict, keyed by resource class name, of inventory data
                         to set against the provider

        :raises: exc.InvalidResourceClass if a supplied custom resource class
                 name does not meet the placement API's format requirements.
        """
        self._ensure_resource_provider(rp_uuid, rp_name)

        # Auto-create custom resource classes coming from a virt driver
        list(map(self._ensure_resource_class,
                 (rc_name for rc_name in inv_data
                  if rc_name not in fields.ResourceClass.STANDARD)))

        if inv_data:
            self._update_inventory(rp_uuid, inv_data)
        else:
            self._delete_inventory(rp_uuid)

    @safe_connect
    def _ensure_resource_class(self, name):
        """Make sure a custom resource class exists.

        First attempt to PUT the resource class using microversion 1.7. If
        this results in a 406, fail over to a GET and POST with version 1.2.

        Returns the name of the resource class if it was successfully
        created or already exists. Otherwise None.

        :param name: String name of the resource class to check/create.
        :raises: `exception.InvalidResourceClass` upon error.
        """
        # no payload on the put request
        response = self.put("/resource_classes/%s" % name, None, version="1.7")
        if 200 <= response.status_code < 300:
            return name
        elif response.status_code == 406:
            # microversion 1.7 not available so try the earlier way
            # TODO(cdent): When we're happy that all placement
            # servers support microversion 1.7 we can remove this
            # call and the associated code.
            LOG.debug('Falling back to placement API microversion 1.2 '
                      'for resource class management.')
            return self._get_or_create_resource_class(name)
        else:
            msg = _LE("Failed to ensure resource class record with "
                      "placement API for resource class %(rc_name)s. "
                      "Got %(status_code)d: %(err_text)s.")
            args = {
                'rc_name': name,
                'status_code': response.status_code,
                'err_text': response.text,
            }
            LOG.error(msg, args)
            raise exception.InvalidResourceClass(resource_class=name)

    def _get_or_create_resource_class(self, name):
        """Queries the placement API for a resource class supplied resource
        class string name. If the resource class does not exist, creates it.

        Returns the resource class name if exists or was created, else None.

        :param name: String name of the resource class to check/create.
        """
        resp = self.get("/resource_classes/%s" % name, version="1.2")
        if 200 <= resp.status_code < 300:
            return name
        elif resp.status_code == 404:
            self._create_resource_class(name)
            return name
        else:
            msg = _LE("Failed to retrieve resource class record from "
                      "placement API for resource class %(rc_name)s. "
                      "Got %(status_code)d: %(err_text)s.")
            args = {
                'rc_name': name,
                'status_code': resp.status_code,
                'err_text': resp.text,
            }
            LOG.error(msg, args)
            return None

    def _create_resource_class(self, name):
        """Calls the placement API to create a new resource class.

        :param name: String name of the resource class to create.

        :returns: None on successful creation.
        :raises: `exception.InvalidResourceClass` upon error.
        """
        url = "/resource_classes"
        payload = {
            'name': name,
        }
        resp = self.post(url, payload, version="1.2")
        if 200 <= resp.status_code < 300:
            msg = _LI("Created resource class record via placement API "
                      "for resource class %s.")
            LOG.info(msg, name)
        elif resp.status_code == 409:
            # Another thread concurrently created a resource class with the
            # same name. Log a warning and then just return
            msg = _LI("Another thread already created a resource class "
                      "with the name %s. Returning.")
            LOG.info(msg, name)
        else:
            msg = _LE("Failed to create resource class %(resource_class)s in "
                      "placement API. Got %(status_code)d: %(err_text)s.")
            args = {
                'resource_class': name,
                'status_code': resp.status_code,
                'err_text': resp.text,
            }
            LOG.error(msg, args)
            raise exception.InvalidResourceClass(resource_class=name)

    def update_compute_node(self, compute_node):
        """Creates or updates stats for the supplied compute node.

        :param compute_node: updated nova.objects.ComputeNode to report
        :raises `exception.InventoryInUse` if the compute node has had changes
                to its inventory but there are still active allocations for
                resource classes that would be deleted by an update to the
                placement API.
        """
        self._ensure_resource_provider(compute_node.uuid,
                                       compute_node.hypervisor_hostname)
        inv_data = _compute_node_to_inventory_dict(compute_node)
        if inv_data:
            self._update_inventory(compute_node.uuid, inv_data)
        else:
            self._delete_inventory(compute_node.uuid)

    @safe_connect
    def get_allocations_for_instance(self, rp_uuid, instance):
        url = '/allocations/%s' % instance.uuid
        resp = self.get(url)
        if not resp:
            return {}
        else:
            # NOTE(cdent): This trims to just the allocations being
            # used on this resource provider. In the future when there
            # are shared resources there might be other providers.
            return resp.json()['allocations'].get(
                rp_uuid, {}).get('resources', {})

    def _allocate_for_instance(self, rp_uuid, instance):
        my_allocations = _instance_to_allocations_dict(instance)
        current_allocations = self.get_allocations_for_instance(rp_uuid,
                                                                instance)
        if current_allocations == my_allocations:
            allocstr = ','.join(['%s=%s' % (k, v)
                                 for k, v in my_allocations.items()])
            LOG.debug('Instance %(uuid)s allocations are unchanged: %(alloc)s',
                      {'uuid': instance.uuid, 'alloc': allocstr})
            return

        LOG.debug('Sending allocation for instance %s',
                  my_allocations,
                  instance=instance)
        res = self.put_allocations(rp_uuid, instance.uuid, my_allocations,
                                   instance.project_id, instance.user_id)
        if res:
            LOG.info(_LI('Submitted allocation for instance'),
                     instance=instance)

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
    def claim_resources(self, consumer_uuid, alloc_request, project_id,
                        user_id, attempt=0):
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

        :note: This method will attempt to retry a claim that fails with a
        concurrent update up to 3 times

        :param consumer_uuid: The instance's UUID.
        :param alloc_request: The JSON body of the request to make to the
                              placement's PUT /allocations API
        :param project_id: The project_id associated with the allocations.
        :param user_id: The user_id associated with the allocations.
        :param attempt: The attempt at claiming this allocation request (used
                        in recursive retries)
        :returns: True if the allocations were created, False otherwise.
        """
        # Ensure we don't change the supplied alloc request since it's used in
        # a loop within the scheduler against multiple instance claims
        ar = copy.deepcopy(alloc_request)
        url = '/allocations/%s' % consumer_uuid

        payload = ar

        # We first need to determine if this is a move operation and if so
        # create the "doubled-up" allocation that exists for the duration of
        # the move operation against both the source and destination hosts
        r = self.get(url)
        if r.status_code == 200:
            current_allocs = r.json()['allocations']
            if current_allocs:
                payload = _move_operation_alloc_request(current_allocs, ar)

        payload['project_id'] = project_id
        payload['user_id'] = user_id
        r = self.put(url, payload, version='1.10')
        if r.status_code != 204:
            # NOTE(jaypipes): Yes, it sucks doing string comparison like this
            # but we have no error codes, only error messages.
            if attempt < 3 and 'concurrently updated' in r.text:
                # Another thread updated one or more of the resource providers
                # involved in the claim. It's safe to retry the claim
                # transaction.
                LOG.debug("Another process changed the resource providers "
                          "involved in our claim attempt for consumer %s. "
                          "Retrying claim, attempt: %s", consumer_uuid,
                          (attempt + 1))
                return self.claim_resources(consumer_uuid, alloc_request,
                    project_id, user_id, attempt=(attempt + 1))
            LOG.warning(
                'Unable to submit allocation for instance '
                '%(uuid)s (%(code)i %(text)s)',
                {'uuid': consumer_uuid,
                 'code': r.status_code,
                 'text': r.text})
        return r.status_code == 204

    @safe_connect
    def remove_provider_from_instance_allocation(self, consumer_uuid, rp_uuid,
                                                 user_id, project_id,
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

        :param consumer_uuid: The instance/consumer UUID
        :param rp_uuid: The UUID of the provider whose resources we wish to
                        remove from the consumer's allocation
        :param user_id: The instance's user
        :param project_id: The instance's project
        :param resources: The resources to be dropped from the allocation
        """
        url = '/allocations/%s' % consumer_uuid

        # Grab the "doubled-up" allocation that we will manipulate
        r = self.get(url)
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
        r = self.put(url, payload, version='1.10')
        if r.status_code != 204:
            LOG.warning("Failed to save allocation for %s. Got HTTP %s: %s",
                        consumer_uuid, r.status_code, r.text)
        return r.status_code == 204

    @safe_connect
    def put_allocations(self, rp_uuid, consumer_uuid, alloc_data, project_id,
                        user_id):
        """Creates allocation records for the supplied instance UUID against
        the supplied resource provider.

        :note Currently we only allocate against a single resource provider.
              Once shared storage and things like NUMA allocations are a
              reality, this will change to allocate against multiple providers.

        :param rp_uuid: The UUID of the resource provider to allocate against.
        :param consumer_uuid: The instance's UUID.
        :param alloc_data: Dict, keyed by resource class, of amounts to
                           consume.
        :param project_id: The project_id associated with the allocations.
        :param user_id: The user_id associated with the allocations.
        :returns: True if the allocations were created, False otherwise.
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
        r = self.put(url, payload, version='1.8')
        if r.status_code == 406:
            # microversion 1.8 not available so try the earlier way
            # TODO(melwitt): Remove this when we can be sure all placement
            # servers support version 1.8.
            payload.pop('project_id')
            payload.pop('user_id')
            r = self.put(url, payload)
        if r.status_code != 204:
            LOG.warning(
                'Unable to submit allocation for instance '
                    '%(uuid)s (%(code)i %(text)s)',
                {'uuid': consumer_uuid,
                 'code': r.status_code,
                 'text': r.text})
        return r.status_code == 204

    @safe_connect
    def delete_allocation_for_instance(self, uuid):
        url = '/allocations/%s' % uuid
        r = self.delete(url)
        if r:
            LOG.info(_LI('Deleted allocation for instance %s'),
                     uuid)
        else:
            # Check for 404 since we don't need to log a warning if we tried to
            # delete something which doesn't actually exist.
            if r.status_code != 404:
                LOG.warning(
                    _LW('Unable to delete allocation for instance '
                        '%(uuid)s: (%(code)i %(text)s)'),
                    {'uuid': uuid,
                     'code': r.status_code,
                     'text': r.text})

    def update_instance_allocation(self, compute_node, instance, sign):
        if sign > 0:
            self._allocate_for_instance(compute_node.uuid, instance)
        else:
            self.delete_allocation_for_instance(instance.uuid)

    @safe_connect
    def get_allocations_for_resource_provider(self, rp_uuid):
        url = '/resource_providers/%s/allocations' % rp_uuid
        resp = self.get(url)
        if not resp:
            return {}
        else:
            return resp.json()['allocations']

    @safe_connect
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
                self.delete_allocation_for_instance(instance.uuid)
        url = "/resource_providers/%s" % rp_uuid
        resp = self.delete(url)
        if resp:
            LOG.info(_LI("Deleted resource provider %s"), rp_uuid)
            # clean the caches
            self._resource_providers.pop(rp_uuid, None)
            self._provider_aggregate_map.pop(rp_uuid, None)
        else:
            # Check for 404 since we don't need to log a warning if we tried to
            # delete something which doesn"t actually exist.
            if resp.status_code != 404:
                LOG.warning(
                    _LW("Unable to delete resource provider "
                        "%(uuid)s: (%(code)i %(text)s)"),
                    {"uuid": rp_uuid,
                     "code": resp.status_code,
                     "text": resp.text})

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

import functools
import math
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


def convert_mb_to_ceil_gb(mb_value):
    gb_int = 0
    if mb_value:
        gb_float = mb_value / 1024.0
        # ensure we reserve/allocate enough space by rounding up to nearest GB
        gb_int = int(math.ceil(gb_float))
    return gb_int


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
        reserved_disk_gb = convert_mb_to_ceil_gb(CONF.reserved_host_disk_mb)
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
    # NOTE(danms): Boot-from-volume instances consume no local disk
    is_bfv = compute_utils.is_volume_backed_instance(instance._context,
                                                     instance)
    # TODO(johngarbutt) we have to round up swap MB to the next GB.
    # It would be better to claim disk in MB, but that is hard now.
    swap_in_gb = convert_mb_to_ceil_gb(instance.flavor.swap)
    disk = ((0 if is_bfv else instance.flavor.root_gb) +
            swap_in_gb + instance.flavor.ephemeral_gb)
    alloc_dict = {
        MEMORY_MB: instance.flavor.memory_mb,
        VCPU: instance.flavor.vcpus,
        DISK_GB: disk,
    }
    # Remove any zero allocations.
    return {key: val for key, val in alloc_dict.items() if val}


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

    def put(self, url, data):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        return self._client.put(
            url, json=data,
            endpoint_filter=self.ks_filter, raise_exc=False)

    def delete(self, url):
        return self._client.delete(
            url,
            endpoint_filter=self.ks_filter, raise_exc=False)

    # TODO(sbauza): Change that poor interface into passing a rich versioned
    # object that would provide the ResourceProvider requirements.
    @safe_connect
    def get_filtered_resource_providers(self, filters):
        """Returns a list of ResourceProviders matching the requirements
        expressed by the filters argument, which can include a dict named
        'resources' where amounts are keyed by resource class names.

        eg. filters = {'resources': {'VCPU': 1}}
        """
        resources = filters.pop("resources", None)
        if resources:
            resource_query = ",".join(sorted("%s:%s" % (rc, amount)
                                      for (rc, amount) in resources.items()))
            filters['resources'] = resource_query
        resp = self.get("/resource_providers?%s" % parse.urlencode(filters),
                        version='1.4')
        if resp.status_code == 200:
            data = resp.json()
            return data.get('resource_providers', [])
        else:
            msg = _LE("Failed to retrieve filtered list of resource providers "
                      "from placement API for filters %(filters)s. "
                      "Got %(status_code)d: %(err_text)s.")
            args = {
                'filters': filters,
                'status_code': resp.status_code,
                'err_text': resp.text,
            }
            LOG.error(msg, args)
            return None

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

        Returns a dict of resource provider information if found or None if no
        such resource provider could be found.

        :param uuid: UUID identifier for the resource provider to look up
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

    @safe_connect
    def _create_resource_provider(self, uuid, name):
        """Calls the placement API to create a new resource provider record.

        Returns a dict of resource provider information object representing
        the newly-created resource provider.

        :param uuid: UUID of the new resource provider
        :param name: Name of the resource provider
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
        elif resp.status_code == 409:
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
        else:
            msg = _LE("[%(placement_req_id)s] Failed to create resource "
                      "provider record in placement API for UUID %(uuid)s. "
                      "Got %(status_code)d: %(err_text)s.")
            args = {
                'uuid': uuid,
                'status_code': resp.status_code,
                'err_text': resp.text,
                'placement_req_id': placement_req_id,
            }
            LOG.error(msg, args)

    def _ensure_resource_provider(self, uuid, name=None):
        """Ensures that the placement API has a record of a resource provider
        with the supplied UUID. If not, creates the resource provider record in
        the placement API for the supplied UUID, optionally passing in a name
        for the resource provider.

        The found or created resource provider object is returned from this
        method. If the resource provider object for the supplied uuid was not
        found and the resource provider record could not be created in the
        placement API, we return None.

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
            name = name or uuid
            rp = self._create_resource_provider(uuid, name)
            if rp is None:
                return
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
        cur_rp_gen = self._resource_providers[rp_uuid]['generation']
        payload = {
            'resource_provider_generation': cur_rp_gen,
            'inventories': {},
        }
        r = self.put(url, payload)
        placement_req_id = get_placement_request_id(r)
        if r.status_code == 200:
            # Update our view of the generation for next time
            updated_inv = r.json()
            new_gen = updated_inv['resource_provider_generation']

            self._resource_providers[rp_uuid]['generation'] = new_gen
            msg_args = {
                'rp_uuid': rp_uuid,
                'generation': new_gen,
                'placement_req_id': placement_req_id,
            }
            LOG.info(_LI('[%(placement_req_id)s] Deleted all inventory for '
                         'resource provider %(rp_uuid)s at generation '
                         '%(generation)i'),
                     msg_args)
            return
        elif r.status_code == 409:
            rc_str = _extract_inventory_in_use(r.text)
            if rc_str is not None:
                msg = _LW("[%(placement_req_id)s] We cannot delete inventory "
                          "%(rc_str)s for resource provider %(rp_uuid)s "
                          "because the inventory is in use.")
                msg_args = {
                    'rp_uuid': rp_uuid,
                    'rc_str': rc_str,
                    'placement_req_id': placement_req_id,
                }
                LOG.warning(msg, msg_args)
                return

        msg = _LE("[%(placement_req_id)s] Failed to delete inventory for "
                  "resource provider %(rp_uuid)s. Got error response: %(err)s")
        msg_args = {
            'rp_uuid': rp_uuid,
            'err': r.text,
            'placement_req_id': placement_req_id,
        }
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

        new_inv = {}
        for rc_name, inv in inv_data.items():
            if rc_name not in fields.ResourceClass.STANDARD:
                # Auto-create custom resource classes coming from a virt driver
                self._get_or_create_resource_class(rc_name)

            new_inv[rc_name] = inv

        if new_inv:
            self._update_inventory(rp_uuid, new_inv)
        else:
            self._delete_inventory(rp_uuid)

    @safe_connect
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
    def _get_allocations_for_instance(self, rp_uuid, instance):
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
        current_allocations = self._get_allocations_for_instance(rp_uuid,
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
        res = self._put_allocations(rp_uuid, instance.uuid, my_allocations)
        if res:
            LOG.info(_LI('Submitted allocation for instance'),
                     instance=instance)

    @safe_connect
    def _put_allocations(self, rp_uuid, consumer_uuid, alloc_data):
        """Creates allocation records for the supplied instance UUID against
        the supplied resource provider.

        :note Currently we only allocate against a single resource provider.
              Once shared storage and things like NUMA allocations are a
              reality, this will change to allocate against multiple providers.

        :param rp_uuid: The UUID of the resource provider to allocate against.
        :param consumer_uuid: The instance's UUID.
        :param alloc_data: Dict, keyed by resource class, of amounts to
                           consume.
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
        }
        url = '/allocations/%s' % consumer_uuid
        r = self.put(url, payload)
        if r.status_code != 204:
            LOG.warning(
                _LW('Unable to submit allocation for instance '
                    '%(uuid)s (%(code)i %(text)s)'),
                {'uuid': consumer_uuid,
                 'code': r.status_code,
                 'text': r.text})
        return r.status_code == 204

    @safe_connect
    def _delete_allocation_for_instance(self, uuid):
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
            self._delete_allocation_for_instance(instance.uuid)

    @safe_connect
    def _get_allocations(self, rp_uuid):
        url = '/resource_providers/%s/allocations' % rp_uuid
        resp = self.get(url)
        if not resp:
            return {}
        else:
            return resp.json()['allocations']

    def remove_deleted_instances(self, compute_node, instance_uuids):
        allocations = self._get_allocations(compute_node.uuid)
        if allocations is None:
            allocations = {}

        instance_dict = {instance['uuid']: instance
                         for instance in instance_uuids}
        removed_instances = set(allocations.keys()) - set(instance_dict.keys())

        for uuid in removed_instances:
            LOG.warning(_LW('Deleting stale allocation for instance %s'),
                        uuid)
            self._delete_allocation_for_instance(uuid)

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
                self._delete_allocation_for_instance(instance.uuid)
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

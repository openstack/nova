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
import time

from keystoneauth1 import exceptions as ks_exc
from keystoneauth1 import loading as keystone
from keystoneauth1 import session
from oslo_log import log as logging

from nova.compute import utils as compute_utils
import nova.conf
from nova.i18n import _LE, _LI, _LW
from nova import objects
from nova.objects import fields

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
VCPU = fields.ResourceClass.VCPU
MEMORY_MB = fields.ResourceClass.MEMORY_MB
DISK_GB = fields.ResourceClass.DISK_GB


def safe_connect(f):
    @functools.wraps(f)
    def wrapper(self, *a, **k):
        try:
            # We've failed in a non recoverable way, fully give up.
            if self._disabled:
                return
            return f(self, *a, **k)
        except ks_exc.EndpointNotFound:
            msg = _LW("The placement API endpoint not found. Optional use of "
                      "placement API for reporting is now disabled.")
            LOG.warning(msg)
            self._disabled = True
        except ks_exc.MissingAuthPlugin:
            msg = _LW("No authentication information found for placement API. "
                      "Optional use of placement API for reporting is now "
                      "disabled.")
            LOG.warning(msg)
            self._disabled = True
        except ks_exc.ConnectFailure:
            msg = _LW('Placement API service is not responding.')
            LOG.warning(msg)
    return wrapper


class SchedulerReportClient(object):
    """Client class for updating the scheduler."""

    ks_filter = {'service_type': 'placement',
                 'region_name': CONF.placement.os_region_name}

    def __init__(self):
        # A dict, keyed by the resource provider UUID, of ResourceProvider
        # objects that will have their inventories and allocations tracked by
        # the placement API for the compute host
        self._resource_providers = {}
        auth_plugin = keystone.load_auth_from_conf_options(
            CONF, 'placement')
        self._client = session.Session(auth=auth_plugin)
        # TODO(sdague): use this to disable fully when we don't find
        # the endpoint.
        self._disabled = False

    def get(self, url):
        return self._client.get(
            url,
            endpoint_filter=self.ks_filter, raise_exc=False)

    def post(self, url, data):
        # NOTE(sdague): using json= instead of data= sets the
        # media type to application/json for us. Placement API is
        # more sensitive to this than other APIs in the OpenStack
        # ecosystem.
        return self._client.post(
            url, json=data,
            endpoint_filter=self.ks_filter, raise_exc=False)

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

    @safe_connect
    def _get_resource_provider(self, uuid):
        """Queries the placement API for a resource provider record with the
        supplied UUID.

        Returns an `objects.ResourceProvider` object if found or None if no
        such resource provider could be found.

        :param uuid: UUID identifier for the resource provider to look up
        """
        resp = self.get("/resource_providers/%s" % uuid)
        if resp.status_code == 200:
            data = resp.json()
            return objects.ResourceProvider(
                    uuid=uuid,
                    name=data['name'],
                    generation=data['generation'],
            )
        elif resp.status_code == 404:
            return None
        else:
            msg = _LE("Failed to retrieve resource provider record from "
                      "placement API for UUID %(uuid)s. "
                      "Got %(status_code)d: %(err_text)s.")
            args = {
                'uuid': uuid,
                'status_code': resp.status_code,
                'err_text': resp.text,
            }
            LOG.error(msg, args)

    @safe_connect
    def _create_resource_provider(self, uuid, name):
        """Calls the placement API to create a new resource provider record.

        Returns an `objects.ResourceProvider` object representing the
        newly-created resource provider object.

        :param uuid: UUID of the new resource provider
        :param name: Name of the resource provider
        """
        url = "/resource_providers"
        payload = {
            'uuid': uuid,
            'name': name,
        }
        resp = self.post(url, payload)
        if resp.status_code == 201:
            msg = _LI("Created resource provider record via placement API "
                      "for resource provider with UUID {0} and name {1}.")
            msg = msg.format(uuid, name)
            LOG.info(msg)
            return objects.ResourceProvider(
                    uuid=uuid,
                    name=name,
                    generation=1,
            )
        elif resp.status_code == 409:
            # Another thread concurrently created a resource provider with the
            # same UUID. Log a warning and then just return the resource
            # provider object from _get_resource_provider()
            msg = _LI("Another thread already created a resource provider "
                      "with the UUID {0}. Grabbing that record from "
                      "the placement API.")
            msg = msg.format(uuid)
            LOG.info(msg)
            return self._get_resource_provider(uuid)
        else:
            msg = _LE("Failed to create resource provider record in "
                      "placement API for UUID %(uuid)s. "
                      "Got %(status_code)d: %(err_text)s.")
            args = {
                'uuid': uuid,
                'status_code': resp.status_code,
                'err_text': resp.text,
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
            return self._resource_providers[uuid]

        rp = self._get_resource_provider(uuid)
        if rp is None:
            name = name or uuid
            rp = self._create_resource_provider(uuid, name)
            if rp is None:
                return
        self._resource_providers[uuid] = rp
        return rp

    def _compute_node_inventory(self, compute_node):
        inventories = {
            'VCPU': {
                'total': compute_node.vcpus,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': compute_node.cpu_allocation_ratio,
            },
            'MEMORY_MB': {
                'total': compute_node.memory_mb,
                'reserved': CONF.reserved_host_memory_mb,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': compute_node.ram_allocation_ratio,
            },
            'DISK_GB': {
                'total': compute_node.local_gb,
                'reserved': CONF.reserved_host_disk_mb * 1024,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': compute_node.disk_allocation_ratio,
            },
        }
        data = {
            'inventories': inventories,
        }
        return data

    def _get_inventory(self, compute_node):
        url = '/resource_providers/%s/inventories' % compute_node.uuid
        result = self.get(url)
        if not result:
            return {'inventories': {}}
        return result.json()

    def _update_inventory_attempt(self, compute_node):
        """Update the inventory for this compute node if needed.

        :param compute_node: The objects.ComputeNode for the operation
        :returns: True if the inventory was updated (or did not need to be),
                  False otherwise.
        """
        data = self._compute_node_inventory(compute_node)
        curr = self._get_inventory(compute_node)

        # Update our generation immediately, if possible. Even if there
        # are no inventories we should always have a generation but let's
        # be careful.
        server_gen = curr.get('resource_provider_generation')
        if server_gen:
            my_rp = self._resource_providers[compute_node.uuid]
            if server_gen != my_rp.generation:
                LOG.debug('Updating our resource provider generation '
                          'from %(old)i to %(new)i',
                          {'old': my_rp.generation,
                           'new': server_gen})
            my_rp.generation = server_gen

        # Check to see if we need to update placement's view
        if data['inventories'] == curr.get('inventories', {}):
            return True

        data['resource_provider_generation'] = (
            self._resource_providers[compute_node.uuid].generation)
        url = '/resource_providers/%s/inventories' % compute_node.uuid
        result = self.put(url, data)
        if result.status_code == 409:
            LOG.info(_LI('Inventory update conflict for %s'),
                     compute_node.uuid)
            # Invalidate our cache and re-fetch the resource provider
            # to be sure to get the latest generation.
            del self._resource_providers[compute_node.uuid]
            self._ensure_resource_provider(compute_node.uuid,
                                           compute_node.hypervisor_hostname)
            return False
        elif not result:
            LOG.warning(_LW('Failed to update inventory for '
                            '%(uuid)s: %(status)i %(text)s'),
                        {'uuid': compute_node.uuid,
                         'status': result.status_code,
                         'text': result.text})
            return False

        if result.status_code != 200:
            LOG.info(
                _LI('Received unexpected response code %(code)i while '
                    'trying to update inventory for compute node %(uuid)s'
                    ': %(text)s'),
                {'uuid': compute_node.uuid,
                 'code': result.status_code,
                 'text': result.text})
            return False

        # Update our view of the generation for next time
        updated_inventories_result = result.json()
        new_gen = updated_inventories_result['resource_provider_generation']

        self._resource_providers[compute_node.uuid].generation = new_gen
        LOG.debug('Updated inventory for %s at generation %i' % (
            compute_node.uuid, new_gen))
        return True

    @safe_connect
    def _update_inventory(self, compute_node):
        for attempt in (1, 2, 3):
            if compute_node.uuid not in self._resource_providers:
                # NOTE(danms): Either we failed to fetch/create the RP
                # on our first attempt, or a previous attempt had to
                # invalidate the cache, and we were unable to refresh
                # it. Bail and try again next time.
                LOG.warning(_LW(
                    'Unable to refresh my resource provider record'))
                return False
            if self._update_inventory_attempt(compute_node):
                return True
            time.sleep(1)
        return False

    def update_resource_stats(self, compute_node):
        """Creates or updates stats for the supplied compute node.

        :param compute_node: updated nova.objects.ComputeNode to report
        """
        compute_node.save()
        self._ensure_resource_provider(compute_node.uuid,
                                       compute_node.hypervisor_hostname)
        self._update_inventory(compute_node)

    def _allocations(self, instance):
        # NOTE(danms): Boot-from-volume instances consume no local disk
        is_bfv = compute_utils.is_volume_backed_instance(instance._context,
                                                         instance)
        disk = ((0 if is_bfv else instance.flavor.root_gb) +
                instance.flavor.swap +
                instance.flavor.ephemeral_gb)
        return {
            MEMORY_MB: instance.flavor.memory_mb,
            VCPU: instance.flavor.vcpus,
            DISK_GB: disk,
        }

    def _get_allocations_for_instance(self, compute_node, instance):
        url = '/allocations/%s' % instance.uuid
        resp = self.get(url)
        if not resp:
            return {}
        else:
            # NOTE(cdent): This trims to just the allocations being
            # used on this compute node. In the future when there
            # are shared resources there might be other providers.
            return resp.json()['allocations'].get(
                compute_node.uuid, {}).get('resources', {})

    @safe_connect
    def _allocate_for_instance(self, compute_node, instance):
        url = '/allocations/%s' % instance.uuid

        my_allocations = self._allocations(instance)
        current_allocations = self._get_allocations_for_instance(compute_node,
                                                                 instance)
        if current_allocations == my_allocations:
            allocstr = ','.join(['%s=%s' % (k, v)
                                 for k, v in my_allocations.items()])
            LOG.debug('Instance %(uuid)s allocations are unchanged: %(alloc)s',
                      {'uuid': instance.uuid, 'alloc': allocstr})
            return

        allocations = {
            'allocations': [
                {
                    'resource_provider': {
                        'uuid': compute_node.uuid,
                    },
                    'resources': my_allocations,
                },
            ],
        }
        LOG.debug('Sending allocation for instance %s',
                  allocations,
                  instance=instance)
        r = self.put(url, allocations)
        if r:
            LOG.info(_LI('Submitted allocation for instance'),
                     instance=instance)
        else:
            LOG.warning(
                _LW('Unable to submit allocation for instance '
                    '%(uuid)s (%(code)i %(text)s)'),
                {'uuid': instance.uuid,
                 'code': r.status_code,
                 'text': r.text})

    @safe_connect
    def _delete_allocation_for_instance(self, uuid):
        url = '/allocations/%s' % uuid
        r = self.delete(url)
        if r:
            LOG.info(_LI('Deleted allocation for instance %s'),
                     uuid)
        else:
            LOG.warning(
                _LW('Unable to delete allocation for instance '
                    '%(uuid)s: (%(code)i %(text)s)'),
                {'uuid': uuid,
                 'code': r.status_code,
                 'text': r.text})

    def update_instance_allocation(self, compute_node, instance, sign):
        if sign > 0:
            self._allocate_for_instance(compute_node, instance)
        else:
            self._delete_allocation_for_instance(instance.uuid)

    @safe_connect
    def _get_allocations(self, compute_node):
        url = '/resource_providers/%s/allocations' % compute_node.uuid
        resp = self.get(url)
        if not resp:
            return {}
        else:
            return resp.json()['allocations']

    def remove_deleted_instances(self, compute_node, instance_uuids):
        allocations = self._get_allocations(compute_node)
        if allocations is None:
            allocations = {}

        instance_dict = {instance['uuid']: instance
                         for instance in instance_uuids}
        removed_instances = set(allocations.keys()) - set(instance_dict.keys())

        for uuid in removed_instances:
            LOG.warning(_LW('Deleting stale allocation for instance %s'),
                        uuid)
            self._delete_allocation_for_instance(uuid)

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
"""Placement API handler for the reshaper.

The reshaper provides for atomically migrating resource provider inventories
and associated allocations when some of the inventory moves from one resource
provider to another, such as when a class of inventory moves from a parent
provider to a new child provider.
"""

import copy

from oslo_utils import excutils
import webob

from nova.api.openstack.placement import errors
from nova.api.openstack.placement import exception
# TODO(cdent): That we are doing this suggests that there's stuff to be
# extracted from the handler to a shared module.
from nova.api.openstack.placement.handlers import allocation
from nova.api.openstack.placement.handlers import inventory
from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.api.openstack.placement.policies import reshaper as policies
from nova.api.openstack.placement.schemas import reshaper as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
# TODO(cdent): placement needs its own version of this
from nova.i18n import _


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.30')
@util.require_content('application/json')
def reshape(req):
    context = req.environ['placement.context']
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    context.can(policies.RESHAPE)
    data = util.extract_json(req.body, schema.POST_RESHAPER_SCHEMA)
    inventories = data['inventories']
    allocations = data['allocations']
    # We're going to create several InventoryList, by rp uuid.
    inventory_by_rp = {}

    # TODO(cdent): this has overlaps with inventory:set_inventories
    # and is a mess of bad names and lack of method extraction.
    for rp_uuid, inventory_data in inventories.items():
        try:
            resource_provider = rp_obj.ResourceProvider.get_by_uuid(
                context, rp_uuid)
        except exception.NotFound as exc:
            raise webob.exc.HTTPBadRequest(
                _('Resource provider %(rp_uuid)s in inventories not found: '
                  '%(error)s') % {'rp_uuid': rp_uuid, 'error': exc},
                comment=errors.RESOURCE_PROVIDER_NOT_FOUND)

        # Do an early generation check.
        generation = inventory_data['resource_provider_generation']
        if generation != resource_provider.generation:
            raise webob.exc.HTTPConflict(
                _('resource provider generation conflict for provider %(rp)s: '
                  'actual: %(actual)s, given: %(given)s') %
                {'rp': rp_uuid,
                 'actual': resource_provider.generation,
                 'given': generation},
                comment=errors.CONCURRENT_UPDATE)

        inv_list = []
        for res_class, raw_inventory in inventory_data['inventories'].items():
            inv_data = copy.copy(inventory.INVENTORY_DEFAULTS)
            inv_data.update(raw_inventory)
            inv_obj = inventory.make_inventory_object(
                resource_provider, res_class, **inv_data)
            inv_list.append(inv_obj)
        inventory_by_rp[resource_provider] = rp_obj.InventoryList(
            objects=inv_list)

    # Make the consumer objects associated with the allocations.
    consumers, new_consumers_created = allocation.inspect_consumers(
        context, allocations, want_version)

    # Nest exception handling so that any exception results in new consumer
    # objects being deleted, then reraise for translating to HTTP exceptions.
    try:
        try:
            # When these allocations are created they get resource provider
            # objects which are different instances (usually with the same
            # data) from those loaded above when creating inventory objects.
            # The reshape method below is responsible for ensuring that the
            # resource providers and their generations do not conflict.
            allocation_objects = allocation.create_allocation_list(
                context, allocations, consumers)

            rp_obj.reshape(context, inventory_by_rp, allocation_objects)
        except Exception:
            with excutils.save_and_reraise_exception():
                allocation.delete_consumers(new_consumers_created)
    # Generation conflict is a (rare) possibility in a few different
    # places in reshape().
    except exception.ConcurrentUpdateDetected as exc:
        raise webob.exc.HTTPConflict(
            _('update conflict: %(error)s') % {'error': exc},
            comment=errors.CONCURRENT_UPDATE)
    # A NotFound here means a resource class that does not exist was named
    except exception.NotFound as exc:
        raise webob.exc.HTTPBadRequest(
            _('malformed reshaper data: %(error)s') % {'error': exc})
    # Distinguish inventory in use (has allocations on it)...
    except exception.InventoryInUse as exc:
        raise webob.exc.HTTPConflict(
            _('update conflict: %(error)s') % {'error': exc},
            comment=errors.INVENTORY_INUSE)
    # ...from allocations which won't fit for a variety of reasons.
    except exception.InvalidInventory as exc:
        raise webob.exc.HTTPConflict(
            _('Unable to allocate inventory: %(error)s') % {'error': exc})

    req.response.status = 204
    req.response.content_type = None
    return req.response

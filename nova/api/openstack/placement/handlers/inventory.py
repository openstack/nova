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
"""Inventory handlers for Placement API."""

import copy

from oslo_db import exception as db_exc
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.schemas import inventory as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import db
from nova import exception
from nova.i18n import _
from nova.objects import resource_provider as rp_obj


# NOTE(cdent): We keep our own representation of inventory defaults
# and output fields, separate from the versioned object to avoid
# inadvertent API changes when the object defaults are changed.
OUTPUT_INVENTORY_FIELDS = [
    'total',
    'reserved',
    'min_unit',
    'max_unit',
    'step_size',
    'allocation_ratio',
]
INVENTORY_DEFAULTS = {
    'reserved': 0,
    'min_unit': 1,
    'max_unit': db.MAX_INT,
    'step_size': 1,
    'allocation_ratio': 1.0
}


def _extract_inventory(body, schema):
    """Extract and validate inventory from JSON body."""
    data = util.extract_json(body, schema)

    inventory_data = copy.copy(INVENTORY_DEFAULTS)
    inventory_data.update(data)

    return inventory_data


def _extract_inventories(body, schema):
    """Extract and validate multiple inventories from JSON body."""
    data = util.extract_json(body, schema)

    inventories = {}
    for res_class, raw_inventory in data['inventories'].items():
        inventory_data = copy.copy(INVENTORY_DEFAULTS)
        inventory_data.update(raw_inventory)
        inventories[res_class] = inventory_data

    data['inventories'] = inventories
    return data


def _make_inventory_object(resource_provider, resource_class, **data):
    """Single place to catch malformed Inventories."""
    # TODO(cdent): Some of the validation checks that are done here
    # could be done via JSONschema (using, for example, "minimum":
    # 0) for non-negative integers. It's not clear if that is
    # duplication or decoupling so leaving it as this for now.
    try:
        inventory = rp_obj.Inventory(
            resource_provider=resource_provider,
            resource_class=resource_class, **data)
    except (ValueError, TypeError) as exc:
        raise webob.exc.HTTPBadRequest(
            _('Bad inventory %(class)s for resource provider '
              '%(rp_uuid)s: %(error)s') % {'class': resource_class,
                                           'rp_uuid': resource_provider.uuid,
                                           'error': exc})
    return inventory


def _send_inventories(req, resource_provider, inventories):
    """Send a JSON representation of a list of inventories."""
    response = req.response
    response.status = 200
    output, last_modified = _serialize_inventories(
        inventories, resource_provider.generation)
    response.body = encodeutils.to_utf8(jsonutils.dumps(output))
    response.content_type = 'application/json'
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    if want_version.matches((1, 15)):
        response.last_modified = last_modified
        response.cache_control = 'no-cache'
    return response


def _send_inventory(req, resource_provider, inventory, status=200):
    """Send a JSON representation of one single inventory."""
    response = req.response
    response.status = status
    response.body = encodeutils.to_utf8(jsonutils.dumps(_serialize_inventory(
        inventory, generation=resource_provider.generation)))
    response.content_type = 'application/json'
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    if want_version.matches((1, 15)):
        modified = util.pick_last_modified(None, inventory)
        response.last_modified = modified
        response.cache_control = 'no-cache'
    return response


def _serialize_inventory(inventory, generation=None):
    """Turn a single inventory into a dictionary."""
    data = {
        field: getattr(inventory, field)
        for field in OUTPUT_INVENTORY_FIELDS
    }
    if generation:
        data['resource_provider_generation'] = generation
    return data


def _serialize_inventories(inventories, generation):
    """Turn a list of inventories in a dict by resource class."""
    inventories_by_class = {inventory.resource_class: inventory
                            for inventory in inventories}
    inventories_dict = {}
    last_modified = None
    for resource_class, inventory in inventories_by_class.items():
        last_modified = util.pick_last_modified(last_modified, inventory)
        inventories_dict[resource_class] = _serialize_inventory(
            inventory, generation=None)
    return ({'resource_provider_generation': generation,
             'inventories': inventories_dict}, last_modified)


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
def create_inventory(req):
    """POST to create one inventory.

    On success return a 201 response, a location header pointing
    to the newly created inventory and an application/json representation
    of the inventory.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)
    data = _extract_inventory(req.body, schema.POST_INVENTORY_SCHEMA)
    resource_class = data.pop('resource_class')

    inventory = _make_inventory_object(resource_provider,
                                       resource_class,
                                       **data)

    try:
        resource_provider.add_inventory(inventory)
    except (exception.ConcurrentUpdateDetected,
            db_exc.DBDuplicateEntry) as exc:
        raise webob.exc.HTTPConflict(
            _('Update conflict: %(error)s') % {'error': exc})
    except (exception.InvalidInventoryCapacity,
            exception.NotFound) as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to create inventory for resource provider '
              '%(rp_uuid)s: %(error)s') % {'rp_uuid': resource_provider.uuid,
                                           'error': exc})

    response = req.response
    response.location = util.inventory_url(
        req.environ, resource_provider, resource_class)
    return _send_inventory(req, resource_provider, inventory,
                           status=201)


@wsgi_wrapper.PlacementWsgify
def delete_inventory(req):
    """DELETE to destroy a single inventory.

    If the inventory is in use or resource provider generation is out
    of sync return a 409.

    On success return a 204 and an empty body.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_class = util.wsgi_path_item(req.environ, 'resource_class')

    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)
    try:
        resource_provider.delete_inventory(resource_class)
    except (exception.ConcurrentUpdateDetected,
            exception.InventoryInUse) as exc:
        raise webob.exc.HTTPConflict(
            _('Unable to delete inventory of class %(class)s: %(error)s') %
            {'class': resource_class, 'error': exc})
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _('No inventory of class %(class)s found for delete: %(error)s') %
             {'class': resource_class, 'error': exc})

    response = req.response
    response.status = 204
    response.content_type = None
    return response


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def get_inventories(req):
    """GET a list of inventories.

    On success return a 200 with an application/json body representing
    a collection of inventories.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    try:
        rp = rp_obj.ResourceProvider.get_by_uuid(context, uuid)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %(uuid)s found : %(error)s") %
             {'uuid': uuid, 'error': exc})

    inv_list = rp_obj.InventoryList.get_all_by_resource_provider(context, rp)

    return _send_inventories(req, rp, inv_list)


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def get_inventory(req):
    """GET one inventory.

    On success return a 200 an application/json body representing one
    inventory.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_class = util.wsgi_path_item(req.environ, 'resource_class')
    try:
        rp = rp_obj.ResourceProvider.get_by_uuid(context, uuid)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %(uuid)s found : %(error)s") %
             {'uuid': uuid, 'error': exc})

    inv_list = rp_obj.InventoryList.get_all_by_resource_provider(context, rp)
    inventory = inv_list.find(resource_class)

    if not inventory:
        raise webob.exc.HTTPNotFound(
            _('No inventory of class %(class)s for %(rp_uuid)s') %
            {'class': resource_class, 'rp_uuid': uuid})

    return _send_inventory(req, rp, inventory)


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
def set_inventories(req):
    """PUT to set all inventory for a resource provider.

    Create, update and delete inventory as required to reset all
    the inventory.

    If the resource generation is out of sync, return a 409.
    If an inventory to be deleted is in use, return a 409.
    If any inventory to be created or updated has settings which are
    invalid (for example reserved exceeds capacity), return a 400.

    On success return a 200 with an application/json body representing
    the inventories.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)

    data = _extract_inventories(req.body, schema.PUT_INVENTORY_SCHEMA)
    if data['resource_provider_generation'] != resource_provider.generation:
        raise webob.exc.HTTPConflict(
            _('resource provider generation conflict'))

    inv_list = []
    for res_class, inventory_data in data['inventories'].items():
        inventory = _make_inventory_object(
            resource_provider, res_class, **inventory_data)
        inv_list.append(inventory)
    inventories = rp_obj.InventoryList(objects=inv_list)

    try:
        resource_provider.set_inventory(inventories)
    except exception.ResourceClassNotFound as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unknown resource class in inventory for resource provider '
              '%(rp_uuid)s: %(error)s') % {'rp_uuid': resource_provider.uuid,
                                           'error': exc})
    except exception.InventoryWithResourceClassNotFound as exc:
        raise webob.exc.HTTPConflict(
            _('Race condition detected when setting inventory. No inventory '
              'record with resource class for resource provider '
              '%(rp_uuid)s: %(error)s') % {'rp_uuid': resource_provider.uuid,
                                           'error': exc})
    except (exception.ConcurrentUpdateDetected,
            exception.InventoryInUse,
            db_exc.DBDuplicateEntry) as exc:
        raise webob.exc.HTTPConflict(
            _('update conflict: %(error)s') % {'error': exc})
    except exception.InvalidInventoryCapacity as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to update inventory for resource provider '
              '%(rp_uuid)s: %(error)s') % {'rp_uuid': resource_provider.uuid,
                                          'error': exc})

    return _send_inventories(req, resource_provider, inventories)


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.5', status_code=405)
def delete_inventories(req):
    """DELETE all inventory for a resource provider.

    Delete inventory as required to reset all the inventory.
    If an inventory to be deleted is in use, return a 409 Conflict.
    On success return a 204 No content.
    Return 405 Method Not Allowed if the wanted microversion does not match.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)

    inventories = rp_obj.InventoryList(objects=[])

    try:
        resource_provider.set_inventory(inventories)
    except exception.ConcurrentUpdateDetected:
        raise webob.exc.HTTPConflict(
            _('Unable to delete inventory for resource provider '
              '%(rp_uuid)s because the inventory was updated by '
              'another process. Please retry your request.')
              % {'rp_uuid': resource_provider.uuid})
    except exception.InventoryInUse as ex:
        # NOTE(mriedem): This message cannot change without impacting the
        # nova.scheduler.client.report._RE_INV_IN_USE regex.
        raise webob.exc.HTTPConflict(ex.format_message())

    response = req.response
    response.status = 204
    response.content_type = None

    return response


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
def update_inventory(req):
    """PUT to update one inventory.

    If the resource generation is out of sync, return a 409.
    If the inventory has settings which are invalid (for example
    reserved exceeds capacity), return a 400.

    On success return a 200 with an application/json body representing
    the inventory.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_class = util.wsgi_path_item(req.environ, 'resource_class')

    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)

    data = _extract_inventory(req.body, schema.BASE_INVENTORY_SCHEMA)
    if data['resource_provider_generation'] != resource_provider.generation:
        raise webob.exc.HTTPConflict(
            _('resource provider generation conflict'))

    inventory = _make_inventory_object(resource_provider,
                                       resource_class,
                                       **data)

    try:
        resource_provider.update_inventory(inventory)
    except (exception.ConcurrentUpdateDetected,
            db_exc.DBDuplicateEntry) as exc:
        raise webob.exc.HTTPConflict(
            _('update conflict: %(error)s') % {'error': exc})
    except exception.InventoryWithResourceClassNotFound as exc:
        raise webob.exc.HTTPBadRequest(
            _('No inventory record with resource class for resource provider '
              '%(rp_uuid)s: %(error)s') % {'rp_uuid': resource_provider.uuid,
                                           'error': exc})
    except exception.InvalidInventoryCapacity as exc:
        raise webob.exc.HTTPBadRequest(
            _('Unable to update inventory for resource provider '
              '%(rp_uuid)s: %(error)s') % {'rp_uuid': resource_provider.uuid,
                                          'error': exc})

    return _send_inventory(req, resource_provider, inventory)

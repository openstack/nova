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
"""Placement API handlers for setting and deleting allocations."""

import jsonschema
from oslo_serialization import jsonutils
import webob

from nova.api.openstack.placement import util
from nova import exception
from nova import objects


ALLOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "allocations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "resource_provider": {
                        "type": "object",
                        "properties": {
                            "uuid": {
                                "type": "string",
                                "format": "uuid"
                            }
                        },
                        "additionalProperties": False,
                        "required": ["uuid"]
                    },
                    "resources": {
                        "type": "object",
                        "patternProperties": {
                            "^[0-9A-Z_]+$": {
                                "type": "integer"
                            }
                        },
                        "additionalProperties": False
                    }
                },
                "required": [
                    "resource_provider",
                    "resources"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["allocations"],
    "additionalProperties": False
}


def _extract_allocations(body, schema):
    """Extract allocation data from a JSON body."""
    try:
        data = jsonutils.loads(body)
    except ValueError as exc:
        raise webob.exc.HTTPBadRequest(
            'Malformed JSON: %s' % exc,
            json_formatter=util.json_error_formatter)
    try:
        jsonschema.validate(data, schema,
                            format_checker=jsonschema.FormatChecker())
    except jsonschema.ValidationError as exc:
        raise webob.exc.HTTPBadRequest(
            'JSON does not validate: %s' % exc,
            json_formatter=util.json_error_formatter)
    return data


@webob.dec.wsgify
@util.require_content('application/json')
def set_allocations(req):
    context = req.environ['placement.context']
    consumer_uuid = util.wsgi_path_item(req.environ, 'consumer_uuid')
    data = _extract_allocations(req.body, ALLOCATION_SCHEMA)
    allocation_data = data['allocations']

    # If the body includes an allocation for a resource provider
    # that does not exist, raise a 400.
    allocation_objects = []
    for allocation in allocation_data:
        resource_provider_uuid = allocation['resource_provider']['uuid']

        try:
            resource_provider = objects.ResourceProvider.get_by_uuid(
                context, resource_provider_uuid)
        except exception.NotFound:
            raise webob.exc.HTTPBadRequest(
                "Allocation for resource provider '%s' "
                "that does not exist." % resource_provider_uuid,
                json_formatter=util.json_error_formatter)

        resources = allocation['resources']
        for resource_class in resources:
            try:
                allocation = objects.Allocation(
                    resource_provider=resource_provider,
                    consumer_id=consumer_uuid,
                    resource_class=resource_class,
                    used=resources[resource_class])
            except ValueError as exc:
                raise webob.exc.HTTPBadRequest(
                    "Allocation of class '%s' for "
                    "resource provider '%s' invalid: "
                    "%s" % (resource_class, resource_provider_uuid, exc))
            allocation_objects.append(allocation)

    allocations = objects.AllocationList(context, objects=allocation_objects)
    try:
        allocations.create_all()
    # InvalidInventory is a parent for several exceptions that
    # indicate either that Inventory is not present, or that
    # capacity limits have been exceeded.
    except exception.InvalidInventory as exc:
        raise webob.exc.HTTPConflict(
            'Unable to allocate inventory: %s' % exc,
            json_formatter=util.json_error_formatter)
    except exception.ConcurrentUpdateDetected as exc:
        raise webob.exc.HTTPConflict(
            'Inventory changed while attempting to allocate: %s' % exc,
            json_formatter=util.json_error_formatter)

    req.response.status = 204
    req.response.content_type = None
    return req.response


@webob.dec.wsgify
def delete_allocations(req):
    context = req.environ['placement.context']
    consumer_uuid = util.wsgi_path_item(req.environ, 'consumer_uuid')

    allocations = objects.AllocationList.get_all_by_consumer_id(
        context, consumer_uuid)
    if not allocations:
        raise webob.exc.HTTPNotFound(
            "No allocations for consumer '%s'" % consumer_uuid,
            json_formatter=util.json_error_formatter)
    allocations.delete_all()

    req.response.status = 204
    req.response.content_type = None
    return req.response

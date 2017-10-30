===========================
Resource provider inventory
===========================

See `Resource provider inventories`_ for a description.

This group of API calls works with a single inventory identified by ``resource_class``.
One inventory can be listed, created, updated and deleted per each call.

Show resource provider inventory
================================

.. rest_method:: GET /resource_providers/{uuid}/inventories/{resource_class}

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - resource_class: resource_class_path

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_provider_generation: resource_provider_generation
  - allocation_ratio: allocation_ratio
  - max_unit: max_unit
  - min_unit: min_unit
  - reserved: reserved
  - step_size: step_size
  - total: total

Response Example
----------------

.. literalinclude:: get-inventory.json
   :language: javascript

Update resource provider inventory
==================================

Replace the inventory record of the `{resource_class}` for the resource
provider identified by `{uuid}`.

.. rest_method:: PUT /resource_providers/{uuid}/inventories/{resource_class}

Normal Response Codes: 200

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - resource_class: resource_class_path
  - resource_provider_generation: resource_provider_generation
  - total: total
  - allocation_ratio: allocation_ratio_opt
  - max_unit: max_unit_opt
  - min_unit: min_unit_opt
  - reserved: reserved_opt
  - step_size: step_size_opt

Request example
---------------

.. literalinclude:: update-inventory-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_provider_generation: resource_provider_generation
  - allocation_ratio: allocation_ratio
  - max_unit: max_unit
  - min_unit: min_unit
  - reserved: reserved
  - step_size: step_size
  - total: total

Response Example
----------------

.. literalinclude:: update-inventory.json
   :language: javascript

Delete resource provider inventory
==================================

Delete the inventory record of the `{resource_class}` for
the resource provider identified by `{uuid}`.

See `Troubleshooting`_ section in ``Delete resource provider
inventories`` for a description. In addition, the request returns
HTTP 409 when there are allocations for the specified resource
provider and resource class.

.. _Troubleshooting: ?expanded=delete-resource-provider-inventories-detail#delete-resource-provider-inventories

.. rest_method:: DELETE /resource_providers/{uuid}/inventories/{resource_class}

Normal Response Codes: 204

Error response codes: itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - resource_class: resource_class_path

Response
--------

No body content is returned on a successful DELETE.

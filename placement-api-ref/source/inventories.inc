=============================
Resource provider inventories
=============================

Each resource provider has inventory records for one or more classes
of resources. An inventory record contains information about the total
and reserved amounts of the resource and any consumption constraints
for that resource against the provider.

List resource provider inventories
==================================

.. rest_method:: GET /resource_providers/{uuid}/inventories

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

.. rest_parameters:: parameters.yaml

  - inventories: inventories
  - resource_provider_generation: resource_provider_generation
  - allocation_ratio: allocation_ratio
  - max_unit: max_unit
  - min_unit: min_unit
  - reserved: reserved
  - step_size: step_size
  - total: total

Response Example
----------------

.. literalinclude:: get-inventories.json
   :language: javascript

Update resource provider inventories
====================================

Replaces the set of inventory records for the resource provider identified by `{uuid}`.

.. rest_method:: PUT /resource_providers/{uuid}/inventories

Normal Response Codes: 200

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - resource_provider_generation: resource_provider_generation
  - inventories: inventories
  - total: total
  - allocation_ratio: allocation_ratio_opt
  - max_unit: max_unit_opt
  - min_unit: min_unit_opt
  - reserved: reserved_opt
  - step_size: step_size_opt

Request example
---------------

.. literalinclude:: update-inventories-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_provider_generation: resource_provider_generation
  - inventories: inventories
  - allocation_ratio: allocation_ratio
  - max_unit: max_unit
  - min_unit: min_unit
  - reserved: reserved
  - step_size: step_size
  - total: total

Response Example
----------------

.. literalinclude:: update-inventories.json
   :language: javascript


Delete resource provider inventories
====================================

Deletes all inventory records for the resource provider identified by `{uuid}`.

**Troubleshooting**

The request returns an HTTP 409 when there are alllocations against
the provider or if the provider's inventory is updated by another
thread while attempting the operation.

.. note:: Method is available starting from version 1.5.

.. rest_method:: DELETE /resource_providers/{uuid}/inventories

Normal Response Codes: 204

Error response codes: itemNotFound(404), conflict(409)

.. note:: Since this request does not accept the resource provider generation,
          it is not safe to use when multiple threads are managing inventories
          for a single provider.  In such situations, use the
          ``PUT /resource_providers/{uuid}/inventories`` API with an empty
          ``inventories`` dict.

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

No body content is returned on a successful DELETE.

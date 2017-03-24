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

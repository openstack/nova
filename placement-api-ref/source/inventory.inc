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

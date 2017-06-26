=============================
Resource provider allocations
=============================

See `Allocations`_ for a description.

List resource provider allocations
==================================

Return a representation of all allocations made against this resource
provider, keyed by consumer uuid. Each allocation includes one or more
classes of resource and the amount consumed.

.. rest_method:: GET /resource_providers/{uuid}/allocations

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

.. rest_parameters:: parameters.yaml

  - allocations: resource_provider_allocations
  - resources: resources
  - resource_provider_generation: resource_provider_generation

Response Example
----------------

.. literalinclude:: get-resource_provider_allocations.json
   :language: javascript

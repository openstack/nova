========================
Resource provider usages
========================

Show the consumption of resources for a resource provider
in an aggregated form, i.e. without information for a particular consumer.
See `Resource provider allocations`_.

List resource provider usages
=============================

Return a report of usage information for resources associated with
the resource provider identified by `{uuid}`. The value is a dictionary
of resource classes paired with the sum of the allocations of that
resource class for this resource provider.

.. rest_method:: GET /resource_providers/{uuid}/usages

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_provider_generation: resource_provider_generation
  - usages: resource_provider_usages

Response Example
----------------

.. literalinclude:: get-resource_provider_usages.json
   :language: javascript

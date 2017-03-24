==================
Resource Providers
==================

Resource providers are entities which provide consumable inventory of one or
more classes of resource (such as disk or memory). They can be listed (with
filters), created, updated and deleted.

List Resource Providers
=======================

.. rest_method:: GET /resource_providers

List an optionally filtered collection of resource providers.

Normal Response Codes: 200

Request
-------

Several query parameters are available to filter the returned list of
resource providers. If multiple different parameters are provided, the results
of all filters are merged with a boolean `AND`.

.. rest_parameters:: parameters.yaml

  - resources: resources_query
  - member_of: member_of
  - uuid: resource_provider_uuid_query
  - name: resource_provider_name_query

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_providers: resource_providers
  - generation: resource_provider_generation
  - uuid: resource_provider_uuid
  - links: resource_provider_links
  - name: resource_provider_name


Response Example
----------------

.. literalinclude:: get-resource_providers.json
   :language: javascript

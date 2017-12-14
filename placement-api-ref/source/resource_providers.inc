==================
Resource Providers
==================

Resource providers are entities which provide consumable inventory of one or
more classes of resource (such as disk or memory). They can be listed (with
filters), created, updated and deleted.

List resource providers
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

  - name: resource_provider_name_query
  - uuid: resource_provider_uuid_query
  - member_of: member_of
  - resources: resources_query
  - in_tree: resource_provider_tree_query

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_providers: resource_providers
  - generation: resource_provider_generation
  - uuid: resource_provider_uuid
  - links: resource_provider_links
  - name: resource_provider_name
  - parent_provider_uuid: resource_provider_parent_provider_uuid_required
  - root_provider_uuid: resource_provider_root_provider_uuid_required

Response Example
----------------

.. literalinclude:: get-resource_providers.json
   :language: javascript

Create resource provider
========================

.. rest_method:: POST /resource_providers

Create a new resource provider.

Normal Response Codes: 201

Error response codes: conflict(409)

A `409 Conflict` response code will
be returned if another resource provider exists with the provided name
or uuid.

Request
-------

.. rest_parameters:: parameters.yaml

  - name: resource_provider_name
  - uuid: resource_provider_uuid_opt
  - parent_provider_uuid: resource_provider_parent_provider_uuid

Request example
---------------

.. literalinclude:: create-resource_providers-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: location

No body content is returned on a successful POST.

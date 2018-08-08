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

Error response codes: badRequest(400)

A `400 BadRequest` response code will be returned
if a resource class specified in ``resources`` request parameter
does not exist.

Request
-------

Several query parameters are available to filter the returned list of
resource providers. If multiple different parameters are provided, the results
of all filters are merged with a boolean `AND`.

.. rest_parameters:: parameters.yaml

  - name: resource_provider_name_query
  - uuid: resource_provider_uuid_query
  - member_of: member_of
  - resources: resources_query_1_4
  - in_tree: resource_provider_tree_query
  - required: resource_provider_required_query

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_providers: resource_providers
  - generation: resource_provider_generation
  - uuid: resource_provider_uuid
  - links: resource_provider_links
  - name: resource_provider_name
  - parent_provider_uuid: resource_provider_parent_provider_uuid_response_1_14
  - root_provider_uuid: resource_provider_root_provider_uuid_required

Response Example
----------------

.. literalinclude:: ./samples/resource_providers/get-resource_providers.json
   :language: javascript

Create resource provider
========================

.. rest_method:: POST /resource_providers

Create a new resource provider.

Normal Response Codes: 201 (microversions 1.0 - 1.19), 200 (microversions
1.20 - )

Error response codes: conflict(409)

A `409 Conflict` response code will
be returned if another resource provider exists with the provided name
or uuid.

Request
-------

.. rest_parameters:: parameters.yaml

  - name: resource_provider_name
  - uuid: resource_provider_uuid_opt
  - parent_provider_uuid: resource_provider_parent_provider_uuid_request

Request example
---------------

.. literalinclude:: ./samples/resource_providers/create-resource_providers-request.json
   :language: javascript

Response (microversions 1.0 - 1.19)
-----------------------------------

.. rest_parameters:: parameters.yaml

  - Location: location

No body content is returned on a successful POST.

Response (microversions 1.20 - )
--------------------------------

.. rest_parameters:: parameters.yaml

  - Location: location
  - generation: resource_provider_generation
  - uuid: resource_provider_uuid
  - links: resource_provider_links_v1_20
  - name: resource_provider_name
  - parent_provider_uuid: resource_provider_parent_provider_uuid_required_no_min
  - root_provider_uuid: resource_provider_root_provider_uuid_no_min

Response Example (microversions 1.20 - )
----------------------------------------

.. literalinclude:: ./samples/resource_providers/create-resource_provider.json
   :language: javascript

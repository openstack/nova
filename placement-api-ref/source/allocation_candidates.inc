=====================
Allocation candidates
=====================

.. note:: Allocation candidates API requests are availiable starting from version 1.10.

List allocation candidates
==========================

Returns a dictionary representing a collection of allocation requests
and resource provider summaries. Each allocation request has
information to form a ``PUT /allocations/{consumer_uuid}`` request to claim
resources against a related set of resource providers. Additional parameters
might be required, see `Update allocations`_. As several allocation
requests are available it's necessary to select one. To make a
decision, resource provider summaries are provided with the
inventory/capacity information. For example, this information is used by
nova-scheduler's FilterScheduler to make decisions about on which compute host
to build a server.

.. rest_method:: GET /allocation_candidates

Normal Response Codes: 200

Error response codes: badRequest(400)

Request
-------

.. rest_parameters:: parameters.yaml

  - resources: resources_query_ac
  - required: required_traits_unnumbered
  - member_of: member_of_1_21
  - resourcesN: resources_query_granular
  - requiredN: required_traits_granular
  - member_ofN: member_of_granular
  - group_policy: allocation_candidates_group_policy
  - limit: allocation_candidates_limit

Response (microversions 1.12 - )
--------------------------------

.. rest_parameters:: parameters.yaml

  - allocation_requests: allocation_requests
  - provider_summaries: provider_summaries_1_12
  - allocations: allocations_by_resource_provider
  - resources: resources
  - capacity: capacity
  - used: used
  - traits: traits_1_17
  - parent_provider_uuid: resource_provider_parent_provider_uuid_response_1_29
  - root_provider_uuid: resource_provider_root_provider_uuid_1_29

Response Example (microversions 1.29 - )
----------------------------------------

.. literalinclude:: ./samples/allocation_candidates/get-allocation_candidates-1.29.json
   :language: javascript

Response Example (microversions 1.17 - 1.28)
--------------------------------------------

.. literalinclude:: ./samples/allocation_candidates/get-allocation_candidates-1.17.json
   :language: javascript

Response Example (microversions 1.12 - 1.16)
--------------------------------------------

.. literalinclude:: ./samples/allocation_candidates/get-allocation_candidates-1.12.json
   :language: javascript

Response (microversions 1.10 - 1.11)
------------------------------------

.. rest_parameters:: parameters.yaml

  - allocation_requests: allocation_requests
  - provider_summaries: provider_summaries
  - allocations: allocations_array
  - resource_provider: resource_provider_object
  - uuid: resource_provider_uuid
  - resources: resources
  - capacity: capacity
  - used: used

Response Example (microversions 1.10 - 1.11)
--------------------------------------------

.. literalinclude:: ./samples/allocation_candidates/get-allocation_candidates.json
   :language: javascript

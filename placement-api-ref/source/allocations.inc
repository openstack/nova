===========
Allocations
===========

Allocations are records representing resources that have been assigned
and used by some consumer of that resource. They indicate the amount
of a particular resource that has been allocated to a given consumer
of that resource from a particular resource provider.

List allocations
================

List all allocation records for the consumer identified by
`{consumer_uuid}` on all the resource providers it is consuming.

.. rest_method:: GET /allocations/{consumer_uuid}

Normal Response Codes: 200

Request
-------

.. rest_parameters:: parameters.yaml

  - consumer_uuid: consumer_uuid

Response
--------

.. rest_parameters:: parameters.yaml

  - allocations: allocations_by_resource_provider
  - generation: resource_provider_generation
  - resources: resources

Response Example
----------------

.. literalinclude:: get-allocations.json
   :language: javascript

Update allocations
==================

Create or update one or more allocation records representing the consumption of
one or more classes of resources from one or more resource providers by
the consumer identified by `{consumer_uuid}`.
If allocations already exist for this consumer, they are replaced.

.. rest_method:: PUT /allocations/{consumer_uuid}

Normal Response Codes: 204

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

* `409 Conflict` if there is no available inventory in any of the
  resource providers for any specified resource classes or inventories
  are updated by another thread while attempting the operation.

Request
-------

.. rest_parameters:: parameters.yaml

  - consumer_uuid: consumer_uuid
  - allocations: allocations_array
  - resources: resources
  - resource_provider: resource_provider_object
  - uuid: resource_provider_uuid
  - project_id: project_id_body
  - user_id: user_id_body

Request example
---------------

.. literalinclude:: update-allocations-request.json
   :language: javascript

Response
--------

No body content is returned on a successful PUT.

Delete allocations
==================

Delete all allocation records for the consumer identified by
`{consumer_uuid}` on all resource providers it is consuming.

.. rest_method:: DELETE /allocations/{consumer_uuid}

Normal Response Codes: 204

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - consumer_uuid: consumer_uuid

Response
--------

No body content is returned on a successful DELETE.

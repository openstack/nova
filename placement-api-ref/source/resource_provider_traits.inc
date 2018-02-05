========================
Resource provider traits
========================

See `Traits`_ for a description.
This group of API requests queries/edits the association between
traits and resource providers.

.. note:: Traits API requests are availiable starting from version 1.6.

List resource provider traits
=============================

Return a list of traits for the resource provider identified by `{uuid}`.

.. rest_method:: GET /resource_providers/{uuid}/traits

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

.. rest_parameters:: parameters.yaml

  - traits: traits
  - resource_provider_generation: resource_provider_generation

Response Example
----------------

.. literalinclude:: get-resource_provider-traits.json
   :language: javascript

Update resource provider traits
===============================

Associate traits with the resource provider identified by `{uuid}`.
All the associated traits will be replaced by the traits specified in
the request body.

.. rest_method:: PUT /resource_providers/{uuid}/traits

Normal Response Codes: 200

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

* `400 Bad Request` if any of the specified traits are not valid. The valid
  traits can be queried by `GET /traits`.
* `409 Conflict` if the `resource_provider_generation` doesn't match with the
  server side.

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - traits: traits
  - resource_provider_generation: resource_provider_generation

Request example
---------------

.. literalinclude:: update-resource_provider-traits-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - traits: traits
  - resource_provider_generation: resource_provider_generation

Response Example
----------------

.. literalinclude:: update-resource_provider-traits.json
   :language: javascript


Delete resource provider traits
===============================

Dissociate all the traits from the resource provider identified by `{uuid}`.

.. rest_method:: DELETE /resource_providers/{uuid}/traits

Normal Response Codes: 204

Error response codes: itemNotFound(404), conflict(409)

* `409 Conflict` if the provider's traits are updated by another
  thread while attempting the operation.

.. note:: Since this request does not accept the resource provider generation,
          it is not safe to use when multiple threads are managing traits for
          a single provider.  In such situations, use the
          ``PUT /resource_providers/{uuid}/traits`` API with an empty
          ``traits`` list.

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

No body content is returned on a successful DELETE.

=================
Resource Provider
=================

See `Resource providers`_ for a description.
This group of API calls works with a single resource provider
identified by `uuid`. One resource provider can be listed, updated and
deleted.

Show resource provider
======================

.. rest_method:: GET /resource_providers/{uuid}

Return a representation of the resource provider identified by `{uuid}`.

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

.. rest_parameters:: parameters.yaml

  - generation: resource_provider_generation
  - uuid: resource_provider_uuid
  - links: resource_provider_links
  - name: resource_provider_name
  - parent_provider_uuid: resource_provider_parent_provider_uuid_required
  - root_provider_uuid: resource_provider_root_provider_uuid_required

Response Example
----------------

.. literalinclude:: get-resource_provider.json
   :language: javascript

Update resource provider
========================

.. rest_method:: PUT /resource_providers/{uuid}

Update the name of the resource provider identified by `{uuid}`.

Normal Response Codes: 200

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

A `409 Conflict` response code will be returned if another resource
provider exists with the provided name.

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - name: resource_provider_name
  - parent_provider_uuid: resource_provider_parent_provider_uuid

Request example
---------------

.. literalinclude:: update-resource_provider-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - generation: resource_provider_generation
  - uuid: resource_provider_uuid
  - links: resource_provider_links
  - name: resource_provider_name
  - parent_provider_uuid: resource_provider_parent_provider_uuid_required
  - root_provider_uuid: resource_provider_root_provider_uuid_required

Response Example
----------------

.. literalinclude:: update-resource_provider.json
   :language: javascript

Delete resource provider
========================

.. rest_method:: DELETE /resource_providers/{uuid}

Delete the resource provider identified by `{uuid}`.
This will also disassociate aggregates and delete inventories.

Normal Response Codes: 204

Error response codes: itemNotFound(404), conflict(409)

A `409 Conflict` response code will be returned if there exist
allocations records for any of the inventories that would be deleted
as a result of removing the resource provider.

This error code will be also returned if there are existing child resource
providers under the parent resource provider being deleted.

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

No body content is returned on a successful DELETE.

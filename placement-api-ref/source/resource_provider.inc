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


Response Example
----------------

.. literalinclude:: get-resource_provider.json
   :language: javascript

======
Traits
======

Traits are *qualitative* characteristics of resource providers.
The classic example for traits can be requesting disk from different
providers: a user may request 80GB of disk space for an instance
(quantitative), but may also expect that the disk be SSD instead of
spinning disk (qualitative). Traits provide a way to mark that a
storage provider is SSD or spinning.

.. note:: Traits API requests are availiable starting from version 1.6.

List traits
===========

Return a list of valid trait strings according to parameters specified.

.. rest_method:: GET /traits

Normal Response Codes: 200

Request
-------

Several query parameters are available to filter the returned list of
traits. If multiple different parameters are provided, the results
of all filters are merged with a boolean `AND`.

.. rest_parameters:: parameters.yaml

  - name: trait_name_query
  - associated: trait_associated

Response
--------

.. rest_parameters:: parameters.yaml

  - traits: traits

Response Example
----------------

.. literalinclude:: ./samples/traits/get-traits.json
   :language: javascript

Show traits
===========

Check if a trait name exists in this cloud.

.. rest_method:: GET /traits/{name}

Normal Response Codes: 204

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - name: trait_name

Response
--------

No body content is returned on a successful GET.

Update traits
=============

Insert a new custom trait. If traits already exists 204 will be returned.

There are two kinds of traits: the standard traits and the custom traits.
The standard traits are interoperable across different OpenStack cloud
deployments. The definition of standard traits comes from the `os-traits`
library. The standard traits are read-only in the placement API which means
that the user can't modify any standard traits through API.
The custom traits are used by admin users to manage the non-standard
qualitative information of resource providers.

.. rest_method:: PUT /traits/{name}

Normal Response Codes: 201, 204

Error response codes: badRequest(400)

* `400 BadRequest` if trait name is not prefixed with `CUSTOM_` prefix.

Request
-------

.. rest_parameters:: parameters.yaml

  - name: trait_name

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: location

No body content is returned on a successful PUT.

Delete traits
=============

Delete the trait specified be `{name}`. Note that only custom traits can be
deleted.

.. rest_method:: DELETE /traits/{name}

Normal Response Codes: 204

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

* `400 BadRequest` if the name to delete is standard trait.
* `404 Not Found` if no such trait exists.
* `409 Conflict` if the name to delete has associations with any
  ResourceProvider.

Request
-------

.. rest_parameters:: parameters.yaml

  - name: trait_name

Response
--------

No body content is returned on a successful DELETE.

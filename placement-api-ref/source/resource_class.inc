==============
Resource Class
==============

See `resource classes`_ for a description.
This group of API calls works with a single resource class
identified by `name`. One resource class can be listed, updated and
deleted.

.. note:: Resource class API calls are availiable starting from version 1.2.

Show resource class
===================

.. rest_method:: GET /resource_classes/{name}

Return a representation of the resource class identified by `{name}`.

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - name: resource_class_path

Response
--------

.. rest_parameters:: parameters.yaml

  - name: resource_class
  - links: resource_class_links

Response Example
----------------

.. literalinclude:: ./samples/resource_classes/get-resource_class.json
   :language: javascript

Update resource class
=====================

.. rest_method:: PUT /resource_classes/{name}

Create or validate the existence of single resource class identified by `{name}`.

.. note:: Method is available starting from version 1.7.

Normal Response Codes: 201, 204

A `201 Created` response code will be returned if the new resource class
is successfully created.
A `204 No Content` response code will be returned if the resource class
already exists.

Error response codes: badRequest(400)

Request
-------

.. rest_parameters:: parameters.yaml

  - name: resource_class_path_custom

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: location

No body content is returned on a successful PUT.

Update resource class (microversions 1.2 - 1.6)
===============================================

.. warning:: Changing resource class names using the <1.7 microversion is strongly discouraged.

.. rest_method:: PUT /resource_classes/{name}

Update the name of the resource class identified by `{name}`.

Normal Response Codes: 200

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

A `409 Conflict` response code will be returned if another resource
class exists with the provided name.

Request
-------

.. rest_parameters:: parameters.yaml

  - name: resource_class_path
  - name: resource_class_custom

Request example
---------------

.. literalinclude:: ./samples/resource_classes/update-resource_class-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - name: resource_class
  - links: resource_class_links

Response Example
----------------

.. literalinclude:: ./samples/resource_classes/update-resource_class.json
   :language: javascript

Delete resource class
=====================

.. rest_method:: DELETE /resource_classes/{name}

Delete the resource class identified by `{name}`.

Normal Response Codes: 204

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

A `400 BadRequest` response code will be returned if trying
to delete a standard resource class.

A `409 Conflict` response code will be returned if there exist
inventories for the resource class.

Request
-------

.. rest_parameters:: parameters.yaml

  - name: resource_class_path

Response
--------

No body content is returned on a successful DELETE.

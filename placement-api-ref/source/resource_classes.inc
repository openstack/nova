================
Resource Classes
================

Resource classes are entities that indicate standard or
deployer-specific resources that can be provided by a resource
provider.

.. note:: Resource class API calls are available starting from version 1.2.

List resource classes
=====================

.. rest_method:: GET /resource_classes

Return a list of all resource classes.

Normal Response Codes: 200

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_classes: resource_classes
  - links: resource_class_links
  - name: resource_class

Response Example
----------------

.. literalinclude:: ./samples/resource_classes/get-resource_classes.json
   :language: javascript

Create resource class
=====================

.. rest_method:: POST /resource_classes

Create a new resource class. The new class must be a *custom* resource class,
prefixed with `CUSTOM_` and distinct from the standard resource classes.

Normal Response Codes: 201

Error response codes: badRequest(400), conflict(409)

A `400 BadRequest` response code will be returned if the resource class
does not have prefix `CUSTOM_`.

A `409 Conflict` response code will
be returned if another resource class exists with the provided name.

Request
-------

.. rest_parameters:: parameters.yaml

  - name: resource_class_custom

Request example
---------------

.. literalinclude:: ./samples/resource_classes/create-resource_classes-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: location

No body content is returned on a successful POST.

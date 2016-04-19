.. -*- rst -*-

========
 Images
========

Lists, shows details for, and deletes images. Also sets, lists, shows
details for, and deletes image metadata.

An image is a collection of files that you use to create and rebuild a
server. By default, operators provide pre-built operating system images.
You can also create custom images. See Compute server actions.

By default, the ``policy.json`` file authorizes all users to view the
image size in the ``OS-EXT-IMG-SIZE:size`` extended attribute.

Show Image Details
==================

.. rest_method:: GET //v2.1/{tenant_id}/images/{image_id}

Shows details for an image.

Normal response codes: 200,203,,503,400,401,403,405,404

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - image_id: image_id

Response
--------

**Example Show Image Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-show-resp.json
   :language: javascript

Delete Image
============

.. rest_method:: DELETE //v2.1/{tenant_id}/images/{image_id}

Deletes an image.

Normal response codes: 204,,503,400,401,403,405,404

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - image_id: image_id

Response
--------

Show Image Metadata Item Details
================================

.. rest_method:: GET //v2.1/{tenant_id}/images/{image_id}/metadata/{key}

Shows details for a metadata item, by key, for an image.

Normal response codes: 200,203,,503,400,401,403,405,404

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - image_id: image_id
  - key: key

Response
--------

**Example Show Image Metadata Item Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-item-show-resp.json
   :language: javascript

Create Or Update Image Metadata Item
====================================

.. rest_method:: PUT //v2.1/{tenant_id}/images/{image_id}/metadata/{key}

Creates or updates a metadata item, by key, for an image.

Normal response codes: 200,,503,400,401,403,405,404,415,400,409

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - image_id: image_id
  - key: key

**Example Create Or Update Image Metadata Item: JSON request**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-item-update-req.json
   :language: javascript

Response
--------

**Example Create Or Update Image Metadata Item: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-item-update-resp.json
   :language: javascript

Delete Image Metadata Item
==========================

.. rest_method:: DELETE //v2.1/{tenant_id}/images/{image_id}/metadata/{key}

Deletes a metadata item, by key, for an image.

Normal response codes: 204,,503,400,401,403,405,404,409

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - image_id: image_id
  - key: key

Response
--------


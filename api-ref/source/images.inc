.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

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

List Images
===========

.. rest_method:: GET /images

List images.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Response
--------

**Example List Images: JSON response**

.. literalinclude:: ../../doc/api_samples/images/images-list-get-resp.json
   :language: javascript

List Images With Details
========================

.. rest_method:: GET /images/detail

List images with details.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Response
--------

**Example List Images Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/images-details-get-resp.json
   :language: javascript


Show Image Details
==================

.. rest_method:: GET /images/{image_id}

Shows details for an image.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id

Response
--------

**Example Show Image Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/images-details-get-resp.json
   :language: javascript

Delete Image
============

.. rest_method:: DELETE /images/{image_id}

Deletes an image.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id

Response
--------

List Image Metadata
===================

.. rest_method:: GET /images/{image_id}/metadata

List metadata of an image.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id

Response
--------

**Example Show Image Metadata Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-get-resp.json
   :language: javascript

Create Image Metadata
=====================

.. rest_method:: POST /images/{image_id}/metadata

Create an image metadata.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), requestEntityTooLarge(413)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id

**Example Create Image Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-post-req.json
   :language: javascript

Response
--------

**Example Create Image Metadata: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-post-resp.json
   :language: javascript

Update Image Metadata
=====================

.. rest_method:: PUT /images/{image_id}/metadata

Update an image metadata

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), requestEntityTooLarge(413)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id

**Example Update Image Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-put-req.json
   :language: javascript

Response
--------

**Example Update Image Metadata: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-put-resp.json
   :language: javascript

Show Image Metadata Item
========================

.. rest_method:: GET /images/{image_id}/metadata/{key}

Shows metadata item, by key, for an image.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id
  - key: key

Response
--------

**Example Show Image Metadata Item Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-meta-key-get.json
   :language: javascript

Create Or Update Image Metadata Item
====================================

.. rest_method:: PUT /images/{image_id}/metadata/{key}

Creates or updates a metadata item, by key, for an image.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id
  - key: key

**Example Create Or Update Image Metadata Item: JSON request**

.. literalinclude:: ../../doc/api_samples/images/image-meta-key-put-req.json
   :language: javascript

Response
--------

**Example Create Or Update Image Metadata Item: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-meta-key-put-resp.json
   :language: javascript

Delete Image Metadata Item
==========================

.. rest_method:: DELETE /images/{image_id}/metadata/{key}

Deletes a metadata item, by key, for an image.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id
  - key: key

Response
--------

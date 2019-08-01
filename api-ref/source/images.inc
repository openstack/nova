.. -*- rst -*-

====================
 Images (DEPRECATED)
====================

.. warning::

   These APIs are proxy calls to the Image service. Nova has
   deprecated all the proxy APIs and users should use the native APIs
   instead. All the Image services proxy APIs except image metadata
   APIs will fail with a 404 starting from microversion 2.36.
   The image metadata APIs will fail with a 404 starting from
   microversion 2.39.
   See: `Relevant Image APIs
   <https://docs.openstack.org/api-ref/image/v2/index.html>`__.

Lists, shows details and deletes images.
Also sets, lists, shows details, create, update and deletes image metadata.

An image is a collection of files that you use to create and rebuild a
server. By default, operators provide pre-built operating system images.
You can also create custom images. See: `Create Image Action
<https://docs.openstack.org/api-ref/compute/#create-image-createimage-action>`__.

By default, the ``policy.json`` file authorizes all users to view the
image size in the ``OS-EXT-IMG-SIZE:size`` extended attribute.

List Images
===========

.. rest_method:: GET /images

List images.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - changes-since: changes-since
  - server: image_server_query
  - name: image_name_query
  - status: image_status_query
  - minDisk: minDisk
  - minRam: minRam
  - type : image_type_query
  - limit : limit
  - marker : marker

Response
--------

.. rest_parameters:: parameters.yaml

   - images: images
   - id: image_id_body
   - name: image_name
   - links: links

**Example List Images: JSON response**

.. literalinclude:: ../../doc/api_samples/images/images-list-get-resp.json
   :language: javascript

List Images With Details
========================

.. rest_method:: GET /images/detail

List images with details.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - changes-since: changes-since
  - server: image_server_query
  - name: image_name_query
  - status: image_status_query
  - minDisk: minDisk
  - minRam: minRam
  - type : image_type_query
  - limit : limit
  - marker : marker

Response
--------

.. rest_parameters:: parameters.yaml

   - images: images
   - id: image_id_body
   - name: image_name
   - minRam: minRam_body
   - minDisk: minDisk_body
   - metadata: metadata_object
   - created: created
   - updated: updated
   - status: image_status
   - progress: image_progress
   - links: links
   - server: image_server
   - OS-EXT-IMG-SIZE:size: image_size
   - OS-DCF:diskConfig: OS-DCF:diskConfig

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

.. rest_parameters:: parameters.yaml

   - images: images
   - id: image_id_body
   - name: image_name
   - minRam: minRam_body
   - minDisk: minDisk_body
   - metadata: metadata_object
   - created: created
   - updated: updated
   - status: image_status
   - progress: image_progress
   - links: links
   - server: image_server
   - OS-EXT-IMG-SIZE:size: image_size
   - OS-DCF:diskConfig: OS-DCF:diskConfig

**Example Show Image Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-get-resp.json
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

There is no body content for the response of a successful DELETE action.

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

.. rest_parameters:: parameters.yaml

   - metadata: metadata_object

**Example List Image Metadata Details: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-get-resp.json
   :language: javascript

Create Image Metadata
=====================

.. rest_method:: POST /images/{image_id}/metadata

Create an image metadata.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id
  - metadata: metadata_object

**Example Create Image Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_object

**Example Create Image Metadata: JSON response**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-post-resp.json
   :language: javascript

Update Image Metadata
=====================

.. rest_method:: PUT /images/{image_id}/metadata

Update an image metadata

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - image_id: image_id
  - metadata: metadata_object

**Example Update Image Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/images/image-metadata-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_object

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

.. rest_parameters:: parameters.yaml

   - meta: meta

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
  - meta: meta

**Example Create Or Update Image Metadata Item: JSON request**

.. literalinclude:: ../../doc/api_samples/images/image-meta-key-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - meta: meta

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

There is no body content for the response of a successful DELETE action.

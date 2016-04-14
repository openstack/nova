.. -*- rst -*-

============
API Versions
============

Lists information for all API versions.

List Api Versions
=================

.. rest_method:: GET /

Lists information about all Compute API versions.

Normal response codes: 200,300

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

Response
--------

**Example List Api Versions: JSON request**

.. literalinclude:: ../../doc/api_samples/versions/versions-list-resp.json
   :language: javascript

Show Api V2.1
=============

.. rest_method:: GET /v2.1

Show information about Compute API v2.1.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

Response
--------

**Example Show Api V2.1: JSON request**

.. literalinclude:: ../../doc/api_samples/versions/versions-v21-show-resp.json
   :language: javascript

Show Api V2
===========

.. rest_method:: GET /v2

Show information about Compute API v2.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

Response
--------

**Example Show Api V2: JSON request**

.. literalinclude:: ../../doc/api_samples/versions/versions-v2-show-resp.json
   :language: javascript


.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

==========================================
 Floating IPs bulk (os-floating-ips-bulk)
==========================================

(nova-network only) Bulk-creates, deletes, and lists floating IPs.
Default pool name is ``nova``.

To view available pools, use the ``os-floating-ip-pools`` extension.

List Floating Ips
=================

.. rest_method:: GET /os-floating-ips-bulk

Lists all floating IPs.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Response
--------

**Example List Floating Ips: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-list-resp.json
   :language: javascript

Create Floating Ips
===================

.. rest_method:: POST /os-floating-ips-bulk

Bulk-creates floating IPs.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - ip_range: ip_range

**Example Create Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-create-req.json
   :language: javascript

Response
--------

**Example Create Floating Ips: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-create-resp.json
   :language: javascript

Bulk-Delete Floating Ips
========================

.. rest_method:: PUT /os-floating-ips-bulk/delete

Bulk-deletes floating IPs.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - ip_range: ip_range

**Example Bulk-Delete Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-delete-req.json
   :language: javascript

Response
--------

**Example Bulk-Delete Floating Ips: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-delete-resp.json
   :language: javascript

List Floating Ips By Host
=========================

.. rest_method:: GET /os-floating-ips-bulk/{host_name}

Lists all floating IPs for a host.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host_name: host_name

Response
--------

**Example List Floating Ips By Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-list-by-host-resp.json
   :language: javascript

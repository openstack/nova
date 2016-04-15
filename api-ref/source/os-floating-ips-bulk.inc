.. -*- rst -*-

==========================================
 Floating IPs bulk (os-floating-ips-bulk)
==========================================

(nova-network only) Bulk-creates, deletes, and lists floating IPs.
Default pool name is ``nova``.

To view available pools, use the ``os-floating-ip-pools`` extension.

List Floating Ips
=================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ips-bulk

Lists all floating IPs.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-list-resp.json
   :language: javascript

Create Floating Ips
===================

.. rest_method:: POST /v2.1/{tenant_id}/os-floating-ips-bulk

Bulk-creates floating IPs.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - ip_range: ip_range

**Example Create Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-create-req.json
   :language: javascript

Response
--------

**Example Create Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-create-resp.json
   :language: javascript

Bulk-Delete Floating Ips
========================

.. rest_method:: POST /v2.1/{tenant_id}/os-floating-ips-bulk/delete

Bulk-deletes floating IPs.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - ip_range: ip_range

**Example Bulk-Delete Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-delete-req.json
   :language: javascript

Response
--------

**Example Bulk-Delete Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-delete-resp.json
   :language: javascript

List Floating Ips By Host
=========================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ips-bulk/{host_name}

Lists all floating IPs for a host.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - host_name: host_name

Response
--------

**Example List Floating Ips By Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-list-by-host-resp.json
   :language: javascript


.. -*- rst -*-

========================================
 Usage reports (os-simple-tenant-usage)
========================================

Reports usage statistics on compute and storage resources.

List Tenant Usage For All Tenants
=================================

.. rest_method:: GET /v2.1/{tenant_id}/os-simple-tenant-usage

Lists usage information for all tenants.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Tenant Usage For All Tenants: JSON response**

.. literalinclude:: ../../doc/api_samples/os-simple-tenant-usage/simple-tenant-usage-get.json
   :language: javascript

Show Usage Details For Tenant
=============================

.. rest_method:: GET /v2.1/{tenant_id}/os-simple-tenant-usage/{tenant_id}

Shows usage details for a tenant.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example Show Usage Details For Tenant: JSON response**

.. literalinclude:: ../../doc/api_samples/os-simple-tenant-usage/simple-tenant-usage-get-specific.json
   :language: javascript

.. -*- rst -*-

====================================================
 Flavors access (flavors, os-flavor-access, action)
====================================================

Lists tenants who have access to a private flavor and adds private
flavor access to and removes private flavor access from tenants. By
default, only administrators can manage private flavor access. A private
flavor has ``is_public`` set to ``false`` while a public flavor has
``is_public`` set to ``true``.

List Flavor Access Information For Given Flavor
===============================================

.. rest_method:: GET /v2.1/{tenant_id}/flavors/os-flavor-access

Lists flavor access information.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Flavor Access Information For Given Flavor: JSON request**

.. literalinclude:: ../../doc/api_samples/os-flavor-access/flavor-access-list-resp.json
   :language: javascript

Add Flavor Access To Tenant
===========================

.. rest_method:: POST /v2.1/{tenant_id}/flavors/os-flavor-access/{flavor_id}/action

Adds flavor access to a tenant and flavor.

Specify the ``addTenantAccess`` action and the ``tenant_id`` in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id

**Example Add Flavor Access To Tenant: JSON request**

.. literalinclude:: ../../doc/api_samples/os-flavor-access/flavor-access-add-req.json
   :language: javascript

Response
--------

**Example Add Flavor Access To Tenant: JSON request**

.. literalinclude:: ../../doc/api_samples/os-flavor-access/flavor-access-add-resp.json
   :language: javascript

Remove Flavor Access From Tenant
================================

.. rest_method:: POST /v2.1/{tenant_id}/flavors/os-flavor-access/{flavor_id}/action

Removes flavor access from a tenant and flavor.

Specify the ``removeTenantAccess`` action and the ``tenant_id`` in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id

**Example Remove Flavor Access From Tenant: JSON request**

.. literalinclude:: ../../doc/api_samples/os-flavor-access/flavor-access-remove-req.json
   :language: javascript

Response
--------

**Example Remove Flavor Access From Tenant: JSON request**

.. literalinclude:: ../../doc/api_samples/os-flavor-access/flavor-access-remove-resp.json
   :language: javascript


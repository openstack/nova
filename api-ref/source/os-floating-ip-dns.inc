.. -*- rst -*-

==============================================
 Floating IP DNS records (os-floating-ip-dns)
==============================================

Manages DNS records associated with floating IP addresses. The API
dispatches requests to a DNS driver that is selected at startup.

List Dns Domains
================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ip-dns

Lists registered DNS domains published by the DNS drivers.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Dns Domains: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-domains-list-resp.json
   :language: javascript

Create Or Update Dns Domain
===========================

.. rest_method:: PUT /v2.1/{tenant_id}/os-floating-ip-dns/{domain}

Creates or updates a DNS domain.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - domain: domain

**Example Create Or Update Dns Domain: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-req.json
   :language: javascript

Response
--------

**Example Create Or Update Dns Domain: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-resp.json
   :language: javascript

Delete Dns Domain
=================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-floating-ip-dns/{domain}

Deletes a DNS domain and all associated host entries.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - domain: domain

Response
--------

Create Or Update Dns Entry
==========================

.. rest_method:: PUT /v2.1/{tenant_id}/os-floating-ip-dns/{domain}/entries/{name}

Creates or updates a DNS entry.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - domain: domain
  - name: name

**Example Create Or Update Dns Entry: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-entry-req.json
   :language: javascript

Response
--------

**Example Create Or Update Dns Entry: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-entry-resp.json
   :language: javascript

Find Unique Dns Entry
=====================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ip-dns/{domain}/entries/{name}

Finds a unique DNS entry for a domain and name.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - domain: domain
  - name: name

Response
--------

**Example Find Unique Dns Entry: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-entry-show-resp.json
   :language: javascript

Delete Dns Entry
================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-floating-ip-dns/{domain}/entries/{name}

Deletes a DNS entry.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - domain: domain
  - name: name

Response
--------

List Dns Entries
================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ip-dns/{domain}/entries/{ip}

Lists DNS entries for a domain and IP.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - domain: domain
  - ip: ip

Response
--------

**Example List Dns Entries: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-entry-by-ip-show-resp.json
   :language: javascript


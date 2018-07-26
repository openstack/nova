.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

=============================================
 Floating IP DNS records (os-floating-ip-dns)
=============================================

.. warning::

   Since these APIs are only implemented for **nova-network**, they are
   deprecated. These will fail with a 404 starting from microversion 2.36.
   They were removed in the 18.0.0 Rocky release.

Manages DNS records associated with floating IP addresses. The API
dispatches requests to a DNS driver that is selected at startup.

List DNS Domains
================

.. rest_method:: GET /os-floating-ip-dns

Lists registered DNS domains published by the DNS drivers.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), gone(410),
notImplemented(501)

Response
--------

**Example List Dns Domains: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-list-resp.json
   :language: javascript

Create Or Update DNS Domain
===========================

.. rest_method:: PUT /os-floating-ip-dns/{domain}

Creates or updates a DNS domain.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - domain: domain

**Example Create Or Update Dns Domain: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-req.json
   :language: javascript

Response
--------

**Example Create Or Update Dns Domain: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-resp.json
   :language: javascript

Delete DNS Domain
=================

.. rest_method:: DELETE /os-floating-ip-dns/{domain}

Deletes a DNS domain and all associated host entries.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - domain: domain

Response
--------

List DNS Entries
================

.. rest_method:: GET /os-floating-ip-dns/{domain}/entries/{ip}

Lists DNS entries for a domain and IP.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - domain: domain
  - ip: ip

Response
--------

**Example List DNS Entries: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-entry-list-resp.json
   :language: javascript

Find Unique DNS Entry
=====================

.. rest_method:: GET /os-floating-ip-dns/{domain}/entries/{name}

Finds a unique DNS entry for a domain and name.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - domain: domain
  - name: name

Response
--------

**Example Find Unique DNS Entry: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-entry-get-resp.json
   :language: javascript

Create Or Update DNS Entry
==========================

.. rest_method:: PUT /os-floating-ip-dns/{domain}/entries/{name}

Creates or updates a DNS entry.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), gone(410),
notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - domain: domain
  - name: name

**Example Create Or Update DNS Entry: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-entry-req.json
   :language: javascript

Response
--------

**Example Create Or Update DNS Entry: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-dns/floating-ip-dns-create-or-update-entry-resp.json
   :language: javascript

Delete DNS Entry
================

.. rest_method:: DELETE /os-floating-ip-dns/{domain}/entries/{name}

Deletes a DNS entry.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - domain: domain
  - name: name

Response
--------

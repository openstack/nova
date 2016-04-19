.. -*- rst -*-

================================
 Floating IPs (os-floating-ips)
================================

Lists floating IP addresses for a project. Also, creates (allocates) a
floating IP address for a project, shows floating IP address details,
and deletes (deallocates) a floating IP address from a project.

The cloud administrator configures a pool of floating IP addresses in
OpenStack Compute. The project quota defines the maximum number of
floating IP addresses that you can allocate to the project. After you
`allocate a floating IP
address <http://developer.openstack.org/api-ref-compute-v2.1.html#createFloatingIP>`__
for a project, you can:

-  `Add (associate) the floating IP
   address <http://developer.openstack.org/api-ref-compute-v2.1.html#addFloatingIp>`__
   with an instance in the project. You can associate only one floating
   IP address with an instance at a time.

-  `Remove (disassociate) the floating IP
   address <http://developer.openstack.org/api-ref-compute-v2.1.html#removeFloatingIp>`__
   from an instance in the project.

-  Delete, or deallocate, a floating IP from the project, which
   automatically deletes any associations for that IP address.

List Floating Ip Addresses
==========================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ips

Lists floating IP addresses associated with the tenant or account.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Floating Ip Addresses: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ips-list-resp.json
   :language: javascript

Create (Allocate) Floating Ip Address
=====================================

.. rest_method:: POST /v2.1/{tenant_id}/os-floating-ips

Creates, or allocates, a floating IP address for the current project. By default, the floating IP address is allocated from the public pool.

If more than one floating IP address pool is available, use the ``pool`` parameter to specify from which pool to allocate the IP address.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200,400

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - pool: pool

**Example Create (Allocate) Floating Ip Address: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ip-create-req.json
   :language: javascript

Response
--------

**Example Create (Allocate) Floating Ip Address: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ip-create-resp.json
   :language: javascript

Show Floating Ip Address Details
================================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ips/{floating_ip_id}

Shows details for a floating IP address, by ID, that is associated with the tenant or account.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - floating_ip_id: floating_ip_id

Response
--------

**Example Show Floating Ip Address Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ip-show-resp.json
   :language: javascript

Delete (Deallocate) Floating Ip Address
=======================================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-floating-ips/{floating_ip_id}

Deletes, or deallocates, a floating IP address from the current project and returns it to the pool from which it was allocated.

If the IP address is still associated with a running instance, it is automatically disassociated from that instance.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - floating_ip_id: floating_ip_id

Response
--------


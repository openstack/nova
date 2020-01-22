.. -*- rst -*-

============================================
 Floating IPs (os-floating-ips) (DEPRECATED)
============================================

.. warning::

   These APIs are proxy calls to the Network service. Nova has
   deprecated all the proxy APIs and users should use the native APIs
   instead. These will fail with a 404 starting from microversion 2.36.
   See: `Relevant Network APIs
   <https://docs.openstack.org/api-ref/network/v2/#networks>`__.

Lists floating IP addresses for a project. Also, creates (allocates) a
floating IP address for a project, shows floating IP address details,
and deletes (deallocates) a floating IP address from a project.

The cloud administrator configures a pool of floating IP addresses in
OpenStack Compute. The project quota defines the maximum number of
floating IP addresses that you can allocate to the project. After you
`allocate a floating IP
address <https://docs.openstack.org/api-ref/compute/#create-allocate-floating-ip-address>`__
for a project, you can:

-  `Add (associate) the floating IP
   address <https://docs.openstack.org/api-ref/compute/#add-associate-floating-ip-
   addfloatingip-action-deprecated>`__
   with an instance in the project. You can associate only one floating
   IP address with an instance at a time.

-  `Remove (disassociate) the floating IP
   address <https://docs.openstack.org/api-ref/compute/#remove-disassociate-
   floating-ip-removefloatingip-action-deprecated>`__
   from an instance in the project.

-  Delete, or deallocate, a floating IP from the project, which
   automatically deletes any associations for that IP address.

List Floating Ip Addresses
==========================

.. rest_method:: GET /os-floating-ips

Lists floating IP addresses associated with the tenant or account.

Policy defaults enable only users with the administrative role
or the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ips: floating_ips_list
  - fixed_ip: fixed_ip_address
  - id: floating_ip_id_value
  - instance_id: server_id
  - ip: floating_ip
  - pool: floating_ip_pool_name_or_id

**Example List Floating Ip Addresses**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ips-list-resp.json
   :language: javascript

Create (Allocate) Floating Ip Address
=====================================

.. rest_method:: POST /os-floating-ips

Creates, or allocates, a floating IP address for the current project.
By default, the floating IP address is allocated from the public pool.

If more than one floating IP address pool is available, use the
``pool`` parameter to specify from which pool to allocate the IP address.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - pool: floating_ip_pool_name_or_id

**Example Create (Allocate) Floating Ip Address**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ips-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ip: floating_ip_obj
  - fixed_ip: fixed_ip_address
  - id: floating_ip_id_value
  - instance_id: server_id
  - ip: floating_ip
  - pool: floating_ip_pool_name_or_id

**Example Create (Allocate) Floating Ip Address: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ips-create-resp.json
   :language: javascript

Show Floating Ip Address Details
================================

.. rest_method:: GET /os-floating-ips/{floating_ip_id}

Shows details for a floating IP address, by ID, that is associated with the tenant or account.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - floating_ip_id: floating_ip_id

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ip: floating_ip_obj
  - fixed_ip: fixed_ip_address
  - id: floating_ip_id_value
  - instance_id: server_id
  - ip: floating_ip
  - pool: floating_ip_pool_name_or_id

**Example Show Floating Ip Address Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips/floating-ips-get-resp.json
   :language: javascript

Delete (Deallocate) Floating Ip Address
=======================================

.. rest_method:: DELETE /os-floating-ips/{floating_ip_id}

Deletes, or deallocates, a floating IP address from the current project and
returns it to the pool from which it was allocated.

If the IP address is still associated with a running instance,
it is automatically disassociated from that instance.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - floating_ip_id: floating_ip_id

Response
--------

There is no body content for the response of a successful DELETE action.

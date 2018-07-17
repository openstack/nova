.. -*- rst -*-

=========================================
 Floating IPs bulk (os-floating-ips-bulk)
=========================================

.. warning::

   Since these APIs are only implemented for **nova-network**, they are
   deprecated. These will fail with a 404 starting from microversion 2.36.
   They were removed in the 18.0.0 Rocky release.

Bulk-creates, deletes, and lists floating IPs.
Default pool name is ``nova``.

To view available pools, use the ``os-floating-ip-pools`` extension.

List Floating Ips
=================

.. rest_method:: GET /os-floating-ips-bulk


Lists all floating IPs.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410)

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ip_info : floating_ips_list
  - address : floating_ip
  - fixed_ip : fixed_ip_address
  - instance_uuid : server_id
  - interface : virtual_interface
  - pool: floating_ip_pool_name
  - project_id : project_id_value

**Example List Floating Ips: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-list-resp.json
   :language: javascript

Create Floating Ips
===================

.. rest_method:: POST /os-floating-ips-bulk

Bulk-creates floating IPs.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
conflict(409), gone(410)

Request
-------

.. rest_parameters:: parameters.yaml

  - floating_ips_bulk_create : floating_ip_bulk_object
  - ip_range : ip_range
  - interface : virtual_interface_id_optional
  - pool: floating_ip_pool_name_optional


**Example Create Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ips_bulk_create : floating_ip_bulk_object
  - interface : virtual_interface
  - ip_range : ip_range
  - pool: floating_ip_pool_name

**Example Create Floating Ips: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-create-resp.json
   :language: javascript

Bulk-Delete Floating Ips
========================

.. rest_method:: PUT /os-floating-ips-bulk/delete

Bulk-deletes floating IPs.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410)

Request
-------

.. rest_parameters:: parameters.yaml

  - ip_range: ip_range_delete

**Example Bulk-Delete Floating Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-delete-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ips_bulk_delete : ip_range_delete

**Example Bulk-Delete Floating Ips: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-delete-resp.json
   :language: javascript

List Floating Ips By Host
=========================

.. rest_method:: GET /os-floating-ips-bulk/{host_name}

Lists all floating IPs for a host.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410)

Request
-------

.. rest_parameters:: parameters.yaml

  - host_name: host_name

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ip_info : floating_ips_list
  - address : floating_ip
  - fixed_ip : fixed_ip_address
  - instance_uuid : server_id
  - interface : virtual_interface
  - pool: floating_ip_pool_name
  - project_id : project_id_value


**Example List Floating Ips By Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ips-bulk/floating-ips-bulk-list-by-host-resp.json
   :language: javascript

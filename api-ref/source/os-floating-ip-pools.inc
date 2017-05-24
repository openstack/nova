.. -*- rst -*-

======================================================
 Floating IP pools (os-floating-ip-pools) (DEPRECATED)
======================================================

.. warning::

   These APIs are proxy calls to the Network service. Nova has
   deprecated all the proxy APIs and users should use the native APIs
   instead. These will fail with a 404 starting from microversion 2.36.
   See: `Relevant Network APIs
   <https://developer.openstack.org/api-ref/networking/v2/#networks>`__.

Manages groups of floating IPs.

List Floating Ip Pools
======================

.. rest_method:: GET /os-floating-ip-pools

Lists floating IP pools.

Policy defaults enable only users with the administrative role or user
who is authorized to operate on tenant <tenant_id> to perform this
operation. Cloud providers can change these permissions through the
``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - floating_ip_pools: floating_ip_pools
  - name: floating_ip_pool_name

**Example List Floating Ip Pools: JSON response**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-pools/floatingippools-list-resp.json
   :language: javascript

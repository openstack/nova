.. -*- rst -*-

===========================
 Ping instances (os-fping)
===========================

Pings instances and reports which ones are alive.

Ping Instances
==============

.. rest_method:: GET /v2.1/{tenant_id}/os-fping

Run the fping utility to ping instances and report which ones are alive.

Specify the ``all_tenants=1`` query parameter to ping instances for all tenants. For example:

GET /os-fping?all_tenants=1Specify the ``include`` and ``exclude`` query parameters to filter the results. For example:

GET /os-fping?all_tenants=1&include=uuid1,uuid2&exclude=uuid3,uuid4Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Query Parameters
~~~~~~~~~~~~~~~~

.. rest_parameters:: parameters.yaml

  - all_tenants: all_tenants
  - include: include
  - exclude: exclude

Response
--------

**Example Ping Instances: JSON request**

.. literalinclude:: ../../doc/api_samples/os-fping/fping-get-resp.json
   :language: javascript

Ping An Instance
================

.. rest_method:: GET /v2.1/{tenant_id}/os-fping/{instance_id}

Run the fping utility to ping an instance and report whether it is alive.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - instance_id: instance_id

Response
--------

**Example Ping An Instance: JSON request**

.. literalinclude:: ../../doc/api_samples/os-fping/fping-get-details-resp.json
   :language: javascript


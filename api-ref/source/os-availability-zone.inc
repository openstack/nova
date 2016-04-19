.. -*- rst -*-

===========================================
 Availability zones (os-availability-zone)
===========================================

Shows availability zone information.

Get Availability Zone Information
=================================

.. rest_method:: GET /v2.1/{tenant_id}/os-availability-zone

Gets availability zone information.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example Get availability zone information: JSON response**

.. literalinclude:: ../../doc/api_samples/os-availability-zone/availability-zone-list-resp.json
   :language: javascript

Get Detailed Availability Zone Information
==========================================

.. rest_method:: GET /v2.1/{tenant_id}/os-availability-zone/detail

Gets detailed availability zone information.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example Get detailed availability zone information: JSON response**

.. literalinclude:: ../../doc/api_samples/os-availability-zone/availability-zone-detail-resp.json
   :language: javascript


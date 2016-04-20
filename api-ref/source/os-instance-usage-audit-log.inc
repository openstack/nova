.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

========================================================
 Instance usage audit log (os-instance-usage-audit-log)
========================================================

Administrator only. Monitors task logs.

List Usage Audits For An Instance
=================================

.. rest_method:: GET /v2.1/{tenant_id}/os-instance_usage_audit_log

Lists usage audits for an instance.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Usage Audits For An Instance: JSON response**

.. literalinclude:: ../../doc/api_samples/os-instance-usage-audit-log/inst-usage-audit-log-index-get-resp.json
   :language: javascript

List Usage Audits Before Specified Time
=======================================

.. rest_method:: GET /v2.1/{tenant_id}/os-instance_usage_audit_log/{before_timestamp}

Lists usage audits that occurred before a specified time.

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

  - before_timestamp: before_timestamp

Response
--------

**Example List Usage Audits Before Specified Time: JSON response**

.. literalinclude:: ../../doc/api_samples/os-instance-usage-audit-log/inst-usage-audit-log-show-get-resp.json
   :language: javascript


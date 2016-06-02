.. -*- rst -*-

========================================================
 Server usage audit log (os-instance-usage-audit-log)
========================================================

Administrator only. Audit server usage of a tenant.

List Server Usage Audits For An Tenant
========================================

.. rest_method:: GET /os-instance_usage_audit_log

Lists usage audits for all servers on the given tenant.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example List Usage Audits For All Servers on tenant**

.. literalinclude:: ../../doc/api_samples/os-instance-usage-audit-log/inst-usage-audit-log-index-get-resp.json
   :language: javascript

List Usage Audits Before Specified Time
=======================================

.. rest_method:: GET /os-instance_usage_audit_log/{before_timestamp}

Lists usage audits that occurred before a specified time.

Normal response codes: 200

Error response codes: badRequest(400),unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - before_timestamp: before_timestamp

Response
--------

**Example List Usage Audits Before Specified Time**

.. literalinclude:: ../../doc/api_samples/os-instance-usage-audit-log/inst-usage-audit-log-show-get-resp.json
   :language: javascript

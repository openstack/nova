.. -*- rst -*-

========================================================
 Server usage audit log (os-instance-usage-audit-log)
========================================================

Audit server usage of the cloud. This API is dependent on the
``instance_usage_audit`` configuration option being set on all compute hosts
where usage auditing is required.

Policy defaults enable only users with the administrative role to perform
all os-instance-usage-audit-log related operations. Cloud providers can change
these permissions through the ``policy.json`` file.

List Server Usage Audits
========================

.. rest_method:: GET /os-instance_usage_audit_log

Lists usage audits for all servers on all compute hosts where usage auditing
is configured.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - instance_usage_audit_logs: instance_usage_audit_logs
  - hosts_not_run: host_not_run
  - log: instance_usage_audit_log
  - errors: errors
  - instances: instances_usage_audit
  - message: instance_usage_audit_log_message
  - state: instance_usage_audit_task_state
  - num_hosts: host_num
  - num_hosts_done: host_done_num
  - num_hosts_not_run: host_not_run_num
  - num_hosts_running: host_running_num
  - overall_status: overall_status
  - period_beginning: period_beginning
  - period_ending: period_ending
  - total_errors: total_errors
  - total_instances: total_instances


**Example List Usage Audits For All Servers**

.. literalinclude:: ../../doc/api_samples/os-instance-usage-audit-log/inst-usage-audit-log-index-get-resp.json
   :language: javascript

List Usage Audits Before Specified Time
=======================================

.. rest_method:: GET /os-instance_usage_audit_log/{before_timestamp}

Lists usage audits that occurred before a specified time.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - before_timestamp: before_timestamp

Response
--------

.. rest_parameters:: parameters.yaml

  - instance_usage_audit_log: instance_usage_audit_logs
  - hosts_not_run: host_not_run
  - log: instance_usage_audit_log
  - errors: errors
  - instances: instances_usage_audit
  - message: instance_usage_audit_log_message
  - state: instance_usage_audit_task_state
  - num_hosts: host_num
  - num_hosts_done: host_done_num
  - num_hosts_not_run: host_not_run_num
  - num_hosts_running: host_running_num
  - overall_status: overall_status
  - period_beginning: period_beginning
  - period_ending: period_ending
  - total_errors: total_errors
  - total_instances: total_instances


**Example List Usage Audits Before Specified Time**

.. literalinclude:: ../../doc/api_samples/os-instance-usage-audit-log/inst-usage-audit-log-show-get-resp.json
   :language: javascript

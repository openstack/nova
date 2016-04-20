.. -*- rst -*-

Trigger Crash Dump In Server (Trigger_Crash_Dump Action)
========================================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Trigger a crash dump in a server.

Specify the ``trigger_crash_dump`` action in the request body.

When a crash dump is triggered for a virtual server, it causes a system reboot. This action can cause data loss. Also, network connectivity can be lost. Once the server comes back online, you can find a Kernel Crash Dump file in a certain location of the filesystem. For example, for Ubuntu you can find it in the ``/var/crash`` directory.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

**Example Trigger crash dump: JSON request**

.. literalinclude:: ../../doc/api_samples/servers/v2.17/server-action-trigger-crash-dump.json
   :language: javascript

Response
--------

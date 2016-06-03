.. -*- rst -*-

Trigger Crash Dump In Server
============================

.. rest_method:: POST /servers/{server_id}/action

.. versionadded:: 2.17

Trigger a crash dump in a server.

When a server starts behaving oddly at a fundamental level, it maybe
be useful to get a kernel level crash dump to debug further. The crash
dump action forces a crash dump followed by a system reboot of the
server. Once the server comes back online, you can find a Kernel Crash
Dump file in a certain location of the filesystem. For example, for
Ubuntu you can find it in the ``/var/crash`` directory.

.. warning::

   This action can cause data loss. Also, network connectivity can be
   lost both during and after this operation.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401),
forbidden(403), itemNotFound(404), conflict(409)

* 400 is returned if the server does not support a crash dump (either
  by configuration or because the backend does not support it)
* 409 is returned if the server is not in a state where a crash dump
  action is allowed.

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - trigger_crash_dump: trigger_crash_dump

**Example Trigger crash dump: JSON request**

.. literalinclude:: ../../doc/api_samples/servers/v2.17/server-action-trigger-crash-dump.json
   :language: javascript

Response
--------

No body is returned on a successful submission.

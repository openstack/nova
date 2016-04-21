.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

Shelve Server (Shelve Action)
=============================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Shelves a server.

Specify the ``shelve`` action in the request body.

All associated data and resources are kept but anything still in memory is not retained. To restore a shelved instance, use the ``unshelve`` action. To remove a shelved instance, use the ``shelveOffload`` action.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Preconditions

The server status must be ``ACTIVE``, ``SHUTOFF``, ``PAUSED``, or ``SUSPENDED``.

If the server is locked, you must have administrator privileges to shelve the server.

Asynchronous Postconditions

After you successfully shelve a server, its status changes to ``SHELVED`` and the image status is ``ACTIVE``. The server instance data appears on the compute node that the Compute service manages.

If you boot the server from volumes or set the ``shelved_offload_time`` option to 0, the Compute service automatically deletes the instance on compute nodes and changes the server status to ``SHELVED_OFFLOADED``.

Troubleshooting

If the server status does not change to ``SHELVED`` or ``SHELVED_OFFLOADED``, the shelve operation failed. Ensure that you meet the preconditions and run the request again. If the request fails again, investigate whether another operation is running that causes a race condition.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - shelve: shelve

**Example Shelve server: JSON request**

.. literalinclude:: ../../doc/api_samples/os-shelve/os-shelve.json
   :language: javascript

Response
--------

Shelf-Offload (Remove) Server (Shelveoffload Action)
====================================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Shelf-offloads, or removes, a shelved server.

Specify the ``shelveOffload`` action in the request body.

Data and resource associations are deleted. If an instance is no longer needed, you can remove that instance from the hypervisor to minimize resource usage.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Preconditions

The server status must be ``SHELVED``.

If the server is locked, you must have administrator privileges to shelve-offload the server.

Asynchronous Postconditions

After you successfully shelve-offload a server, its status changes to ``SHELVED_OFFLOADED``. The server instance data appears on the compute node.

Troubleshooting

If the server status does not change to ``SHELVED_OFFLOADED``, the shelve-offload operation failed. Ensure that you meet the preconditions and run the request again. If the request fails again, investigate whether another operation is running that causes a race condition.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - shelveOffload: shelveOffload

**Example Shelve server: JSON request**

.. literalinclude:: ../../doc/api_samples/os-shelve/os-shelve-offload.json
   :language: javascript

Response
--------

Unshelve (Restore) Shelved Server (Unshelve Action)
===================================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Unshelves, or restores, a shelved server.

Specify the ``unshelve`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Preconditions

The server status must be ``SHELVED`` or ``SHELVED_OFFLOADED``.

If the server is locked, you must have administrator privileges to unshelve the server.

Asynchronous Postconditions

After you successfully shelve a server, its status changes to ``ACTIVE``. The server appears on the compute node.

The shelved image is deleted from the list of images returned by an API call.

Troubleshooting

If the server status does not change to ``ACTIVE``, the unshelve operation failed. Ensure that you meet the preconditions and run the request again. If the request fails again, investigate whether another operation is running that causes a race condition.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - unshelve: unshelve

**Example Unshelve server: JSON request**

.. literalinclude:: ../../doc/api_samples/os-shelve/os-unshelve.json
   :language: javascript

Response
--------


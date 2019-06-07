.. -*- rst -*-

Shelve Server (shelve Action)
=============================

.. rest_method:: POST /servers/{server_id}/action

Shelves a server.

Specify the ``shelve`` action in the request body.

All associated data and resources are kept but anything still in memory is not retained. To restore a shelved instance, use the ``unshelve`` action. To remove a shelved instance, use the ``shelveOffload`` action.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

**Preconditions**

The server status must be ``ACTIVE``, ``SHUTOFF``, ``PAUSED``, or ``SUSPENDED``.

If the server is locked, you must have administrator privileges to shelve the server.

**Asynchronous Postconditions**

After you successfully shelve a server, its status changes to ``SHELVED`` and the image status is ``ACTIVE``. The server instance data appears on the compute node that the Compute service manages.

If you boot the server from volumes or set the ``shelved_offload_time`` option to 0, the Compute service automatically deletes the instance on compute nodes and changes the server status to ``SHELVED_OFFLOADED``.

**Troubleshooting**

If the server status does not change to ``SHELVED`` or ``SHELVED_OFFLOADED``, the shelve operation failed. Ensure that you meet the preconditions and run the request again. If the request fails again, investigate whether another operation is running that causes a race condition.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - shelve: shelve

|

**Example Shelve server (shelve Action)**

.. literalinclude:: ../../doc/api_samples/os-shelve/os-shelve.json
   :language: javascript


Response
--------

If successful, this method does not return content in the response body.


Shelf-Offload (Remove) Server (shelveOffload Action)
====================================================

.. rest_method:: POST /servers/{server_id}/action

Shelf-offloads, or removes, a shelved server.

Specify the ``shelveOffload`` action in the request body.

Data and resource associations are deleted. If an instance is no longer needed, you can remove that instance from the hypervisor to minimize resource usage.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

**Preconditions**

The server status must be ``SHELVED``.

If the server is locked, you must have administrator privileges to shelve-offload the server.

**Asynchronous Postconditions**

After you successfully shelve-offload a server, its status changes to ``SHELVED_OFFLOADED``. The server instance data appears on the compute node.

**Troubleshooting**

If the server status does not change to ``SHELVED_OFFLOADED``, the shelve-offload operation failed. Ensure that you meet the preconditions and run the request again. If the request fails again, investigate whether another operation is running that causes a race condition.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - shelveOffload: shelveOffload

|

**Example Shelf-Offload server (shelveOffload Action)**

.. literalinclude:: ../../doc/api_samples/os-shelve/os-shelve-offload.json
   :language: javascript


Response
--------

If successful, this method does not return content in the response body.


Unshelve (Restore) Shelved Server (unshelve Action)
===================================================

.. rest_method:: POST /servers/{server_id}/action

Unshelves, or restores, a shelved server.

Specify the ``unshelve`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

**Preconditions**

The server status must be ``SHELVED`` or ``SHELVED_OFFLOADED``.

If the server is locked, you must have administrator privileges to unshelve the server.

**Asynchronous Postconditions**

After you successfully unshelve a server, its status changes to ``ACTIVE``.
The server appears on the compute node.

The shelved image is deleted from the list of images returned by an API call.

**Troubleshooting**

If the server status does not change to ``ACTIVE``, the unshelve operation failed. Ensure that you meet the preconditions and run the request again. If the request fails again, investigate whether another operation is running that causes a race condition.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - unshelve: unshelve
  - availability_zone: availability_zone_unshelve

|

**Example Unshelve server (unshelve Action)**

.. literalinclude:: ../../doc/api_samples/os-shelve/os-unshelve.json
   :language: javascript

**Example Unshelve server (unshelve Action) (v2.77)**

.. literalinclude:: ../../doc/api_samples/os-shelve/v2.77/os-unshelve.json
   :language: javascript


Response
--------

If successful, this method does not return content in the response body.

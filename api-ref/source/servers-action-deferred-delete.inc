.. -*- rst -*-

Force-Delete Server (forceDelete Action)
========================================

.. rest_method:: POST /servers/{server_id}/action

Force-deletes a server before deferred cleanup.

Specify the ``forceDelete`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - forceDelete: forceDelete

**Example Force-Delete Server (forceDelete Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-deferred-delete/force-delete-post-req.json
   :language: javascript

Response
--------

No body is returned on a successful submission.

Restore Soft-Deleted Instance (restore Action)
==============================================

.. rest_method:: POST /servers/{server_id}/action

Restores a previously soft-deleted server instance. You cannot use
this method to restore deleted instances.

Specify the ``restore`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - restore: restore

**Example Restore Soft-Deleted Instance (restore Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-deferred-delete/restore-post-req.json
   :language: javascript

Response
--------

No body is returned on a successful submission.

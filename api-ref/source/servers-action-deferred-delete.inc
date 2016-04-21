.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

Force-Delete Server (Forcedelete Action)
========================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Force-deletes a server before deferred cleanup.

Specify the ``forceDelete`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - forceDelete: forceDelete

**Example Force-Delete Server (Forcedelete Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-deferred-delete/force-delete-post-req.json
   :language: javascript

Response
--------

Restore Soft-Deleted Instance (Restore Action)
==============================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Restores a previously soft-deleted server instance. You cannot use this method to restore deleted instances.

Specify the ``restore`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - restore: restore

**Example Restore Soft-Deleted Instance (Restore Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-deferred-delete/restore-post-req.json
   :language: javascript

Response
--------


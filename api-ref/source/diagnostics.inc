.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

============================================
 Servers diagnostics (servers, diagnostics)
============================================

Shows the usage data for a server.

Show Server Diagnostics
=======================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/diagnostics

Shows basic usage data for a server.

Policy defaults enable only users with the administrative role. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), notfound(404), conflict(409), notimplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

Response
--------

**Example Server diagnostics: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-diagnostics/server-diagnostics-get-resp.json
   :language: javascript


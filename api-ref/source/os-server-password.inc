.. -*- rst -*-

================================================
 Servers password (servers, os-server-password)
================================================

Shows the encrypted administrative password. Also, clears the encrypted
administrative password for a server, which removes it from the metadata
server.

Show Server Password
====================

.. rest_method:: GET /servers/{server_id}/os-server-password

Shows the administrative password for a server.

This operation calls the metadata service to query metadata information and
does not read password information from the server itself.

The password saved in the metadata service is typically encrypted using the
public SSH key injected into this server, so the SSH private key is needed to
read the password.

Policy defaults enable only users with the administrative role or the owner
of the server to perform this operation. Cloud providers can change these
permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - password: password

**Example Show Server Password**

.. literalinclude:: ../../doc/api_samples/os-server-password/get-password-resp.json
   :language: javascript

Clear Admin Password
====================

.. rest_method:: DELETE /servers/{server_id}/os-server-password

Clears the encrypted administrative password for a server, which removes it
from the database.

This action does not actually change the instance server password.

Policy defaults enable only users with the administrative role or the owner
of the server to perform this operation. Cloud providers can change these
permissions through the ``policy.json`` file.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

If successful, this method does not return content in the response body.

.. -*- rst -*-

===============================================================
 Server consoles (servers, os-consoles, os-console-auth-token)
===============================================================

Manages server consoles.

Lists Consoles
==============

.. rest_method:: GET /servers/{server_id}/consoles

Lists all consoles for a server instance.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id


Response
--------

.. rest_parameters:: parameters.yaml

  - consoles: consoles
  - console: console
  - console_type: console_type
  - id: console_id_in_body

|

**Example List Consoles**

.. literalinclude:: ../../doc/api_samples/consoles/consoles-list-get-resp.json
   :language: javascript


Create Console
==============

.. rest_method:: POST /servers/{server_id}/consoles

Creates a console for a server instance.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id


Response
--------

No body content is returned on a successful POST.


Show Console Details
====================

.. rest_method:: GET /servers/{server_id}/consoles/{console_id}

Shows console details for a server instance.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - console_id: console_id


Response
--------

.. rest_parameters:: parameters.yaml

  - console: console
  - console_type: console_type
  - host: console_host
  - id: console_id_in_body
  - instance_name: instance_name
  - password: console_password
  - port: port

|

**Example Show Console Details**

.. literalinclude:: ../../doc/api_samples/consoles/consoles-get-resp.json
   :language: javascript


Delete Console
==============

.. rest_method:: DELETE /servers/{server_id}/consoles/{console_id}

Deletes a console for a server instance.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - id: console_id

Response
--------

No body content is returned on a successful DELETE.


Show Console Authentication Token
=================================

.. rest_method:: GET /servers/{server_id}/os-console-auth-token

Given the console authentication token for a server instance,
shows the related connection information.

This method is available for ``rdp-html5`` console type only.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id

|

Response
--------

.. rest_parameters:: parameters.yaml

  - console: console
  - instance_uuid: instance_id
  - host: console_host
  - port: port
  - internal_access_path: internal_access_path

|

**Example Show Console Authentication Token**

.. literalinclude:: ../../doc/api_samples/os-console-auth-tokens/get-console-connect-info-get-resp.json
   :language: javascript

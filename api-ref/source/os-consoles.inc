.. -*- rst -*-

===============================================================
 Server consoles (servers, os-consoles, os-console-auth-tokens)
===============================================================

Manages server consoles.

.. note:: This is only used in Xenserver VNC Proxy.

Lists Consoles
==============

.. rest_method:: GET /servers/{server_id}/consoles

Lists all consoles for a server.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

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

Creates a console for a server.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

If successful, this method does not return a response body.


Show Console Details
====================

.. rest_method:: GET /servers/{server_id}/consoles/{console_id}

Shows console details for a server.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
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
  - port: port_number

|

**Example Show Console Details**

.. literalinclude:: ../../doc/api_samples/consoles/consoles-get-resp.json
   :language: javascript


Delete Console
==============

.. rest_method:: DELETE /servers/{server_id}/consoles/{console_id}

Deletes a console for a server.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - console_id: console_id


Response
--------

If successful, this method does not return a response body.


Show Console Connection Information
===================================

.. rest_method:: GET /os-console-auth-tokens/{console_token}

Given the console authentication token for a server,
shows the related connection information.

This method used to be available only for the ``rdp-html5`` console type before
microversion 2.31. Starting from microversion 2.31 it's available for all
console types.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - console_token: console_token

|

Response
--------

.. rest_parameters:: parameters.yaml

  - console: console
  - instance_uuid: instance_id_body
  - host: console_host
  - port: port_number
  - internal_access_path: internal_access_path

|

**Example Show Console Authentication Token**

.. literalinclude:: ../../doc/api_samples/os-console-auth-tokens/get-console-connect-info-get-resp.json
   :language: javascript

.. -*- rst -*-

==================================================
 XenServer VNC Proxy (XVP) consoles (os-consoles)
==================================================

Manages server XVP consoles.

.. warning::

   These APIs are only applicable when using the XenServer virt driver.
   They were removed in the 21.0.0 (Ussuri) release.

Lists Consoles
==============

.. rest_method:: GET /servers/{server_id}/consoles

Lists all consoles for a server.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), gone(410)

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

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410)

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

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410)

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

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - console_id: console_id


Response
--------

If successful, this method does not return a response body.

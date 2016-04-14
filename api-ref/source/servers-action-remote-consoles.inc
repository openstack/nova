.. -*- rst -*-

Get Rdp Console (Os-Getrdpconsole Action)
=========================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Gets an `RDP <https://technet.microsoft.com/en-us/windowsserver/ee236407>`__ console for a server.

Specify the ``os-getRDPConsole`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - os-getRDPConsole: os-getRDPConsole

**Example Get Rdp Console (Os-Getrdpconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getRDPConsole-create-req.json
   :language: javascript

Response
--------

**Example Get Rdp Console (Os-Getrdpconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getRDPConsole-create-resp.json
   :language: javascript

Get Serial Console (Os-Getserialconsole Action)
===============================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Gets a serial console for a server.

Specify the ``os-getSerialConsole`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - os-getSerialConsole: os-getSerialConsole

**Example Get Serial Console (Os-Getserialconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getSerialConsole-create-req.json
   :language: javascript

Response
--------

**Example Get Serial Console (Os-Getserialconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getSerialConsole-create-resp.json
   :language: javascript

Get Spice Console (Os-Getspiceconsole Action)
=============================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Gets a SPICE console for a server.

Specify the ``os-getSPICEConsole`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - os-getSPICEConsole: os-getSPICEConsole

**Example Get Spice Console (Os-Getspiceconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getSPICEConsole-create-req.json
   :language: javascript

Response
--------

**Example Get Spice Console (Os-Getspiceconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getSPICEConsole-create-resp.json
   :language: javascript

Get Vnc Console (Os-Getvncconsole Action)
=========================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Gets a VNC console for a server.

Specify the ``os-getVNCConsole`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - os-getVNCConsole: os-getVNCConsole

**Example Get Vnc Console (Os-Getvncconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getVNCConsole-create-req.json
   :language: javascript

Response
--------

**Example Get Vnc Console (Os-Getvncconsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/getVNCConsole-create-resp.json
   :language: javascript


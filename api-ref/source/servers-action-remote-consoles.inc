.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

Get Rdp Console (os-getRDPConsole Action)
=========================================

.. rest_method:: POST /servers/{server_id}/action

Gets an `RDP <https://technet.microsoft.com/en-us/windowsserver/ee236407>`__ console for a server.

Specify the ``os-getRDPConsole`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - os-getRDPConsole: os-getRDPConsole
  - type: os-getRDPConsole-type

**Example Get Rdp Console (os-getRDPConsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-rdp-console-post-req.json
   :language: javascript

Response
--------

**Example Get Rdp Console (os-getRDPConsole Action): JSON response**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-rdp-console-post-resp.json
   :language: javascript

Get Serial Console (os-getSerialConsole Action)
===============================================

.. rest_method:: POST /servers/{server_id}/action

Gets a serial console for a server.

Specify the ``os-getSerialConsole`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - os-getSerialConsole: os-getSerialConsole
  - type: os-getSerialConsole-type

**Example Get Serial Console (os-getSerialConsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-serial-console-post-req.json
   :language: javascript

Response
--------

**Example Get Serial Console (os-getSerialConsole Action): JSON response**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-serial-console-post-resp.json
   :language: javascript

Get Spice Console (os-getSPICEConsole Action)
=============================================

.. rest_method:: POST /servers/{server_id}/action

Gets a SPICE console for a server.

Specify the ``os-getSPICEConsole`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - os-getSPICEConsole: os-getSPICEConsole
  - type: os-getSPICEConsole-type

**Example Get Spice Console (os-getSPICEConsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-spice-console-post-req.json
   :language: javascript

Response
--------

**Example Get Spice Console (os-getSPICEConsole Action): JSON response**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-spice-console-post-resp.json
   :language: javascript

Get Vnc Console (os-getVNCConsole Action)
=========================================

.. rest_method:: POST /servers/{server_id}/action

Gets a VNC console for a server.

Specify the ``os-getVNCConsole`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - os-getVNCConsole: os-getVNCConsole
  - type: os-getVNCConsole-type

**Example Get Vnc Console (os-getVNCConsole Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-vnc-console-post-req.json
   :language: javascript

Response
--------

**Example Get Vnc Console (os-getVNCConsole Action): JSON response**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-vnc-console-post-resp.json
   :language: javascript

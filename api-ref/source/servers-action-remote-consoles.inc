.. -*- rst -*-

Get RDP Console (os-getRDPConsole Action) (DEPRECATED)
======================================================

.. rest_method:: POST /servers/{server_id}/action
   max_version: 2.5

Gets an `RDP <https://technet.microsoft.com/en-us/windowsserver/ee236407>`__ console for a server.

.. warning::

   This action is deprecated in microversion 2.5 and superseded
   by the API `Server Consoles`_ in microversion 2.6.
   The new API offers a unified API for different console types.

The only supported connect type is ``rdp-html5``. The ``type`` parameter should
be set as ``rdp-html5``.

Specify the ``os-getRDPConsole`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - os-getRDPConsole: os-getRDPConsole
  - type: os-getRDPConsole-type

**Example Get RDP Console (os-getRDPConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-rdp-console-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - console: remote_console
    - type: os-getRDPConsole-type
    - url: os-getRDPConsole-url

**Example Get RDP Console (os-getRDPConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-rdp-console-post-resp.json
   :language: javascript

Get Serial Console (os-getSerialConsole Action) (DEPRECATED)
============================================================

.. rest_method:: POST /servers/{server_id}/action
   max_version: 2.5

Gets a serial console for a server.

.. warning::

   This action is deprecated in microversion 2.5 and superseded
   by the API `Server Consoles`_ in microversion 2.6.
   The new API offers a unified API for different console types.

Specify the ``os-getSerialConsole`` action in the request body.

The only supported connection type is ``serial``. The ``type`` parameter
should be set as ``serial``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - os-getSerialConsole: os-getSerialConsole
  - type: os-getSerialConsole-type

**Example Get Serial Console (os-getSerialConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-serial-console-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - console: remote_console
    - type: os-getSerialConsole-type
    - url: os-getSerialConsole-url

**Example Get Serial Console (os-getSerialConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-serial-console-post-resp.json
   :language: javascript

Get SPICE Console (os-getSPICEConsole Action) (DEPRECATED)
==========================================================

.. rest_method:: POST /servers/{server_id}/action
   max_version: 2.5

Gets a SPICE console for a server.

.. warning::

   This action is deprecated in microversion 2.5 and superseded
   by the API `Server Consoles`_ in microversion 2.6.
   The new API offers a unified API for different console types.

Specify the ``os-getSPICEConsole`` action in the request body.

The only supported connection type is ``spice-html5``. The ``type`` parameter
should be set to ``spice-html5``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - os-getSPICEConsole: os-getSPICEConsole
  - type: os-getSPICEConsole-type

**Example Get Spice Console (os-getSPICEConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-spice-console-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - console: remote_console
    - type: os-getSPICEConsole-type
    - url: os-getSPICEConsole-url

**Example Get SPICE Console (os-getSPICEConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-spice-console-post-resp.json
   :language: javascript

Get VNC Console (os-getVNCConsole Action) (DEPRECATED)
======================================================

.. rest_method:: POST /servers/{server_id}/action
   max_version: 2.5

Gets a VNC console for a server.

.. warning::

   This action is deprecated in microversion 2.5 and superseded
   by the API `Server Consoles`_ in microversion 2.6.
   The new API offers a unified API for different console types.

Specify the ``os-getVNCConsole`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - os-getVNCConsole: os-getVNCConsole
  - type: os-getVNCConsole-type

**Example Get Vnc Console (os-getVNCConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-vnc-console-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - console: remote_console
    - type: os-getVNCConsole-type
    - url: os-getVNCConsole-url

**Example Get VNC Console (os-getVNCConsole Action)**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/get-vnc-console-post-resp.json
   :language: javascript

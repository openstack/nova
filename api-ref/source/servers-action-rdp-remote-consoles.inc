.. -*- rst -*-

Get RDP Console (os-getRDPConsole Action)
=========================================

.. rest_method:: POST /servers/{server_id}/action
   max_version: 2.5

Gets an `RDP <https://technet.microsoft.com/en-us/windowsserver/ee236407>`__ console for a server.

.. warning::

   Along with HyperV driver, this action was removed in Nova 29.0.0
   (caracal) release.

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

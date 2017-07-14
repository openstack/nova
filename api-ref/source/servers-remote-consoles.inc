.. -*- rst -*-

======================
Server Remote Consoles
======================

Create server remote console.

Create Remote Console
=====================

.. rest_method:: POST /servers/{server_id}/remote-consoles

.. note:: Microversion 2.6 or greater is required for this API.

The API provides a unified request for creating a remote console. The user can
get a URL to connect the console from this API. The URL includes the token
which is used to get permission to access the console. Servers may support
different console protocols. To return a remote console using a specific
protocol, such as RDP, set the ``protocol`` parameter to ``rdp``. For the same
protocol, there may be different connection types such as ``vnc protocol and
novnc type`` or ``vnc protocol and xvpvnc type``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


   - server_id: server_id_path
   - remote_console: remote_console
   - protocol: remote_console_protocol
   - type: remote_console_type

**Example Get Remote VNC Console**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/v2.6/create-vnc-console-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

    - remote_console: remote_console
    - protocol: remote_console_protocol
    - type: remote_console_type
    - url: remote_console_url

**Example Get Remote VNC Console**

.. literalinclude:: ../../doc/api_samples/os-remote-consoles/v2.6/create-vnc-console-resp.json
   :language: javascript

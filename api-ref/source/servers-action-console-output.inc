.. -*- rst -*-

Show Console Output (Os-Getconsoleoutput Action)
================================================

.. rest_method:: POST /servers/{server_id}/action

Shows console output for a server instance.

This returns the text of the console since boot in a REST
response. The console content may be large, you can limit it with the
optional ``length`` parameter.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403),
notFound(404), conflict(409), methodNotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - os-getConsoleOutput: os-getConsoleOutput
  - length: length

**Example Get console output**

This requests the last 50 lines of the server in question.

.. literalinclude:: ../../doc/api_samples/os-console-output/console-output-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - output: console_output

**Example Get console output: JSON response**

.. literalinclude:: ../../doc/api_samples/os-console-output/console-output-post-resp.json
   :language: javascript

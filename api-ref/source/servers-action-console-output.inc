.. -*- rst -*-

Show Console Output (os-getConsoleOutput Action)
================================================

.. rest_method:: POST /servers/{server_id}/action

Shows console output for a server.

This API returns the text of the console since boot.
The content returned may be large. Limit the lines of console
text, beginning at the tail of the content, by setting
the optional ``length`` parameter in the request body.

The server to get console log from should set
``export LC_ALL=en_US.UTF-8`` in order to avoid incorrect unicode error.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403),
notFound(404), conflict(409), methodNotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - os-getConsoleOutput: os-getConsoleOutput
  - length: length

**Example Show Console Output (os-getConsoleOutput Action)**

This example requests the last 50 lines of console content
from the specified server.

.. literalinclude:: ../../doc/api_samples/os-console-output/console-output-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - output: console_output

**Example Show Console Output (os-getConsoleOutput Action)**

.. literalinclude:: ../../doc/api_samples/os-console-output/console-output-post-resp.json
   :language: javascript

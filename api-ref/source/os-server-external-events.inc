.. -*- rst -*-

====================================================
 Create external events (os-server-external-events)
====================================================

Creates one or more external events. The API dispatches each event to a
server instance.

Run Events
==========

.. rest_method:: POST /v2.1/{tenant_id}/os-server-external-events

Creates one or more external events, which the API dispatches to the instance.

You must assign this instance to a host. Otherwise, this call does not dispatch the event to the instance.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - events: events
  - name: name
  - tag: tag
  - server_uuid: server_uuid
  - status: status

**Example Run Events: JSON request**

.. literalinclude:: ../../doc/api_samples/os-server-external-events/event-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - events: events
  - code: code
  - name: name
  - server_uuid: server_uuid
  - status: status
  - tag: tag

**Example Run Events: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-external-events/event-create-resp.json
   :language: javascript


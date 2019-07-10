.. -*- rst -*-

================================================
 Servers actions (servers, os-instance-actions)
================================================

List actions and action details for a server.

List Actions For Server
=======================

.. rest_method:: GET /servers/{server_id}/os-instance-actions

Lists actions for a server.

Action information of deleted instances can be returned for requests
starting with microversion 2.21.

Policy defaults enable only users with the administrative role or the owner of
the server to perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - limit: instance_action_limit
  - marker: instance_action_marker
  - changes-since: changes_since_instance_action
  - changes-before: changes_before_instance_action

Response
--------

.. rest_parameters:: parameters.yaml


  - instanceActions: instanceActions
  - action: action
  - instance_uuid: instance_id_body
  - message: message
  - project_id: project_id_server_action
  - request_id: request_id_body
  - start_time: start_time
  - user_id: user_id_server_action
  - updated_at: updated_instance_action
  - links: instance_actions_next_links

**Example List Actions For Server: JSON response**

.. literalinclude:: ../../doc/api_samples/os-instance-actions/instance-actions-list-resp.json
   :language: javascript

**Example List Actions For Server With Links (v2.58):**

.. literalinclude:: ../../doc/api_samples/os-instance-actions/v2.58/instance-actions-list-with-limit-resp.json
   :language: javascript

Show Server Action Details
==========================

.. rest_method:: GET /servers/{server_id}/os-instance-actions/{request_id}

Shows details for a server action.

Action details of deleted instances can be returned for requests later
than microversion 2.21.

Policy defaults enable only users with the administrative role or the owner of
the server to perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - request_id: request_id

Response
--------


.. rest_parameters:: parameters.yaml


  - instanceAction: instanceAction
  - action: action
  - instance_uuid: instance_id_body
  - message: message
  - project_id: project_id_server_action
  - request_id: request_id_body
  - start_time: start_time
  - user_id: user_id_server_action
  - events: instance_action_events_2_50
  - events: instance_action_events_2_51
  - events.event: event
  - events.start_time: event_start_time
  - events.finish_time: event_finish_time
  - events.result: event_result
  - events.traceback: event_traceback
  - events.hostId: event_hostId
  - events.host: event_host
  - updated_at: updated_instance_action

**Example Show Server Action Details For Admin (v2.62)**

.. literalinclude:: ../../doc/api_samples/os-instance-actions/v2.62/instance-action-get-resp.json
   :language: javascript

**Example Show Server Action Details For Non-Admin (v2.62)**

.. literalinclude:: ../../doc/api_samples/os-instance-actions/v2.62/instance-action-get-non-admin-resp.json
   :language: javascript

.. -*- rst -*-

===================================
 Servers multiple create (servers)
===================================

Creates one or more servers.

Optionally, you can set ``"return_reservation_id": "True"`` in the
request body to request that a reservation ID be returned instead of the
newly created instance information. With this parameter, the response
shows only the reservation ID.

Create Multiple Servers
=======================

.. rest_method:: POST /v2.1/{tenant_id}/servers

Creates one or more servers.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_groups: security_groups
  - user_data: user_data
  - os-availability-zone:availability_zone: os-availability-zone:availability_zone
  - server: server
  - imageRef: imageRef
  - flavorRef: flavorRef
  - networks: networks
  - uuid: uuid
  - port: port
  - fixed_ip: fixed_ip
  - name: name
  - metadata: metadata
  - personality: personality
  - block_device_mapping_v2: block_device_mapping_v2
  - device_name: device_name
  - source_type: source_type
  - destination_type: destination_type
  - delete_on_termination: delete_on_termination
  - guest_format: guest_format
  - boot_index: boot_index
  - config_drive: config_drive
  - key_name: key_name
  - os:scheduler_hints: os:scheduler_hints
  - OS-DCF:diskConfig: OS-DCF:diskConfig
  - return_reservation_id: return_reservation_id

**Example Create multiple servers without reservation ID**

.. literalinclude:: ../../doc/api_samples/servers-multiple-create/multiple-create-no-resv-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - server: server
  - adminPass: adminPass
  - id: id
  - links: links
  - OS-DCF:diskConfig: OS-DCF:diskConfig
  - security_groups: security_groups

**Example Create multiple servers without reservation ID**

.. literalinclude:: ../../doc/api_samples/servers/server-create-resp.json
   :language: javascript

Create Multiple Servers With Reservation Id
===========================================

.. rest_method:: POST /v2.1/{tenant_id}/servers

Creates one or more servers with a reservation ID.

Set ``"return_reservation_id": "True"`` in the request body to request that a reservation ID be returned instead of the newly created instance information. With this parameter, the response shows only the reservation ID.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_groups: security_groups
  - user_data: user_data
  - os-availability-zone:availability_zone: os-availability-zone:availability_zone
  - server: server
  - imageRef: imageRef
  - flavorRef: flavorRef
  - networks: networks
  - uuid: uuid
  - port: port
  - fixed_ip: fixed_ip
  - name: name
  - metadata: metadata
  - personality: personality
  - block_device_mapping_v2: block_device_mapping_v2
  - device_name: device_name
  - source_type: source_type
  - destination_type: destination_type
  - delete_on_termination: delete_on_termination
  - guest_format: guest_format
  - boot_index: boot_index
  - config_drive: config_drive
  - key_name: key_name
  - os:scheduler_hints: os:scheduler_hints
  - OS-DCF:diskConfig: OS-DCF:diskConfig
  - return_reservation_id: return_reservation_id

**Example Create multiple servers with reservation ID**

.. literalinclude:: ../../doc/api_samples/servers-multiple-create/multiple-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - reservation_id: reservation_id

**Example Create multiple servers with reservation ID**

.. literalinclude:: ../../doc/api_samples/servers-multiple-create/multiple-create-resp.json
   :language: javascript


.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

=============================================================
 Servers virtual interfaces (servers, os-virtual-interfaces)
=============================================================

Lists virtual interfaces for a server instance.

List Virtual Interfaces
=======================

.. rest_method:: GET /servers/{server_id}/os-virtual-interfaces

Lists the virtual interfaces for an instance.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id

Response
--------

.. rest_parameters:: parameters.yaml

  - virtual_interfaces: virtual_interfaces
  - id: virtual_interface_id
  - mac_address: mac_address

**Example List Virtual Interfaces: JSON response**

.. literalinclude:: ../../doc/api_samples/os-virtual-interfaces/vifs-list-resp.json
   :language: javascript


.. -*- rst -*-

==================
 Hosts (os-hosts)
==================

Manages physical hosts. Some virt drivers do not support all host
functions. For more information, see `nova virt support
matrix <http://docs.openstack.org/developer/nova/support-matrix.html>`__

Policy defaults enable only users with the administrative role to perform
all os-hosts related operations. Cloud providers can change these permissions
through the ``policy.json`` file.

List Hosts
==========

.. rest_method:: GET /os-hosts

Lists hosts.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - hosts: hosts
  - zone: host_zone
  - host_name: host_name_body
  - service: host_service

**Example List Hosts**

.. literalinclude:: ../../doc/api_samples/os-hosts/hosts-list-resp.json
   :language: javascript

Show Host Details
=================

.. rest_method:: GET /os-hosts/{host_name}

Shows details for a host.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host_name: host_name

Response
--------

.. rest_parameters:: parameters.yaml

  - host: host_resource_array
  - resource: host_resource
  - host.project: host_project
  - host.cpu: host_cpu
  - host.memory_mb: host_memory_mb
  - host.disk_gb: host_disk_gb
  - host.host: host_name_body

**Example Show Host Details**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-resp.json
   :language: javascript

Update Host status
==================

.. rest_method:: PUT /os-hosts/{host_name}

Enables, disables a host or put a host in maintenance or normal mode.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - host_name: host_name
  - status: host_status_body_in
  - maintenance_mode: host_maintenance_mode_in

**Example Enable Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-put-maintenance-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - status: host_status_body
  - maintenance_mode: host_maintenance_mode

**Example Enable Host**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-put-maintenance-resp.json
   :language: javascript

Reboot Host
===========

.. rest_method:: GET /os-hosts/{host_name}/reboot

Reboots a host.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - host_name: host_name

Response
--------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - power_action: host_power_action

**Example Reboot Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-reboot.json
   :language: javascript

Shut Down Host
==============

.. rest_method:: GET /os-hosts/{host_name}/shutdown

Shuts down a host.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - host_name: host_name

Response
--------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - power_action: host_power_action

**Example Shut Down Host**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-shutdown.json
   :language: javascript

Start Host
==========

.. rest_method:: GET /os-hosts/{host_name}/startup

Starts a host.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - host_name: host_name

Response
--------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - power_action: host_power_action

**Example Start Host**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-startup.json
   :language: javascript

.. -*- rst -*-

============================================
 Servers diagnostics (servers, diagnostics)
============================================

Shows the usage data for a server.

Show Server Diagnostics
=======================

.. rest_method:: GET /servers/{server_id}/diagnostics

Shows basic usage data for a server.

Policy defaults enable only users with the administrative role. Cloud
providers can change these permissions through the ``policy.json``
file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), notfound(404), conflict(409), notimplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

Starting from **microversion 2.48** diagnostics response is standardized
across all virt drivers. The response should be considered a debug interface
only and not relied upon by programmatic tools. All response fields are listed
below. If the virt driver is unable to provide a specific field then this field
will be reported as ``None`` in the response.

.. rest_parameters:: parameters.yaml

  - config_drive: config_drive_diagnostics
  - state: vm_state_diagnostics
  - driver: driver_diagnostics
  - hypervisor: hypervisor_diagnostics
  - hypervisor_os: hypervisor_os_diagnostics
  - uptime: uptime_diagnostics
  - num_cpus: num_cpus_diagnostics
  - num_disks: num_disks_diagnostics
  - num_nics: num_nics_diagnostics
  - memory_details: memory_details_diagnostics
  - cpu_details: cpu_details_diagnostics
  - disk_details: disk_details_diagnostics
  - nic_details: nic_details_diagnostics

**Example Server diagnostics (2.48)**

.. literalinclude:: ../../doc/api_samples/os-server-diagnostics/v2.48/server-diagnostics-get-resp.json
   :language: javascript

.. warning::
   Before **microversion 2.48** the response format for diagnostics was not
   well defined. Each hypervisor had its own format.

**Example Server diagnostics (2.1)**

Below is an example of diagnostics for a libvirt based instance. The unit of the return
value is hypervisor specific, but in this case the unit of vnet1_rx* and
vnet1_tx* is octets.

.. literalinclude:: ../../doc/api_samples/os-server-diagnostics/server-diagnostics-get-resp.json
   :language: javascript

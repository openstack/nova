.. -*- rst -*-

===============================
 Hosts (os-hosts) (DEPRECATED)
===============================

.. warning::

    The ``os-hosts`` API is deprecated as of the 2.43 microversion. Requests
    made with microversion >= 2.43 will result in a 404 error. To list and show
    host details, use the :ref:`os-hypervisors` API. To enable or disable a
    service, use the :ref:`os-services` API. There is no replacement for the
    `shutdown`, `startup`, `reboot`, or `maintenance_mode` actions as those are
    system-level operations which should be outside of the control of the
    compute service.

Manages physical hosts. Some virt drivers do not support all host
functions. For more information, see `nova virt support
matrix <https://docs.openstack.org/nova/latest/user/support-matrix.html>`__

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
  - resource.project: host_project
  - resource.cpu: host_cpu
  - resource.memory_mb: host_memory_mb
  - resource.disk_gb: host_disk_gb
  - resource.host: host_name_body

**Example Show Host Details**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-resp.json
   :language: javascript

Update Host status
==================

.. rest_method:: PUT /os-hosts/{host_name}

Enables, disables a host or put a host in maintenance or normal mode.

.. warning::

  Putting a host into maintenance mode is only implemented by the XenServer
  compute driver and it has been reported that it does not actually evacuate
  all of the guests from the host, it just sets a flag in the Xen management
  console, and is therefore useless. There are other APIs that allow you to do
  the same thing which are supported across all compute drivers, which would be
  disabling a service and then migrating the instances off that host. See the
  `Operations Guide <https://wiki.openstack.org/wiki/OpsGuide/Compute_Node_Failures_and_Maintenance>`_
  for more information on maintenance.

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

.. warning::

  This is only supported by the XenServer and Hyper-v drivers. The backing
  drivers do no orchestration of dealing with guests in the nova database when
  performing a reboot of the host. The nova-compute service for that host may
  be temporarily disabled by the service group health check which would take it
  out of scheduling decisions, and the guests would be down, but the periodic
  task which checks for unexpectedly stopped instances runs in the nova-compute
  service, which might be dead now so the nova API would show the instances as
  running when in fact they are actually stopped. This API is also not tested
  in a live running OpenStack environment. Needless to say, it is not
  recommended to use this API and it is deprecated as of the 2.43 microversion.

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

.. warning::

  This is only supported by the XenServer and Hyper-v drivers. The backing
  drivers do no orchestration of dealing with guests in the nova database when
  performing a shutdown of the host. The nova-compute service for that host may
  be temporarily disabled by the service group health check which would take it
  out of scheduling decisions, and the guests would be down, but the periodic
  task which checks for unexpectedly stopped instances runs in the nova-compute
  service, which might be dead now so the nova API would show the instances as
  running when in fact they are actually stopped. This API is also not tested
  in a live running OpenStack environment. Needless to say, it is not
  recommended to use this API and it is deprecated as of the 2.43 microversion.

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

.. warning::

  This is not implemented by any in-tree compute drivers and therefore will
  always fail with a `501 NotImplemented` error. Needless to say, it is not
  recommended to use this API and it is deprecated as of the 2.43 microversion.

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

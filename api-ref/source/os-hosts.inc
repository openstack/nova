.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

==================
 Hosts (os-hosts)
==================

Manages physical hosts. Some virt drivers don not support all host
functions. For more information, see `nova virt support
matrix <http://docs.openstack.org/developer/nova/support-matrix.html>`__

List Hosts
==========

.. rest_method:: GET /v2.1/{tenant_id}/os-hosts

Lists hosts.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Hosts: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hosts/hosts-list-resp.json
   :language: javascript

Show Host Details
=================

.. rest_method:: GET /v2.1/{tenant_id}/os-hosts/{host_name}

Shows details for a host.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - host_name: host_name

Response
--------

**Example Show Host Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-resp.json
   :language: javascript

Update Host status
==================

.. rest_method:: PUT /v2.1/{tenant_id}/os-hosts/{host_name}

Enables, disables a host or put a host in maintenance or normal mode.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - host_name: host_name

**Example Enable Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-put-maintenance-req.json
   :language: javascript

Response
--------

**Example Enable Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-put-maintenance-resp.json
   :language: javascript

Reboot Host
===========

.. rest_method:: GET /v2.1/{tenant_id}/os-hosts/{host_name}/reboot

Reboots a host.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - host_name: host_name

Response
--------

**Example Reboot Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-reboot.json
   :language: javascript

Shut Down Host
==============

.. rest_method:: GET /v2.1/{tenant_id}/os-hosts/{host_name}/shutdown

Shuts down a host.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - host_name: host_name

Response
--------

**Example Shut Down Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-shutdown.json
   :language: javascript

Start Host
==========

.. rest_method:: GET /v2.1/{tenant_id}/os-hosts/{host_name}/startup

Starts a host.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - host_name: host_name

Response
--------

**Example Start Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hosts/host-get-startup.json
   :language: javascript


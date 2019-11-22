.. -*- rst -*-

.. _os-services:

================================
 Compute services (os-services)
================================

Lists all running Compute services in a region, enables or disables
scheduling for a Compute service and deletes a Compute service.

For an overview of Compute services, see `OpenStack
Compute <https://docs.openstack.org/nova/latest/install/get-started-compute.html>`__.

List Compute Services
=====================

.. rest_method:: GET /os-services

Lists all running Compute services.

Provides details why any services were disabled.

.. note:: Starting with microversion 2.69 if service details cannot be loaded
   due to a transient condition in the deployment like infrastructure failure,
   the response body for those unavailable compute services in the down cells
   will be missing keys. See `handling down cells
   <https://docs.openstack.org/api-guide/compute/down_cells.html>`__
   section of the Compute API guide for more information on the keys that
   would be returned in the partial constructs.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - binary: binary_query
  - host: host_query_service

Response
--------

.. rest_parameters:: parameters.yaml

  - services: services
  - id: service_id_body_2_52
  - id: service_id_body_2_53
  - binary: binary
  - disabled_reason: disabled_reason_body
  - host: host_name_body
  - state: service_state
  - status: service_status
  - updated_at: updated
  - zone: OS-EXT-AZ:availability_zone
  - forced_down: forced_down_2_11

**Example List Compute Services (v2.11)**

.. literalinclude:: ../../doc/api_samples/os-services/v2.11/services-list-get-resp.json
   :language: javascript

**Example List Compute Services (v2.69)**

This is a sample response for the services from the non-responsive part of the
deployment. The responses for the available service records will be normal
without any missing keys.

.. literalinclude:: ../../doc/api_samples/os-services/v2.69/services-list-get-resp.json
   :language: javascript

Disable Scheduling For A Compute Service
========================================

.. rest_method:: PUT /os-services/disable

Disables scheduling for a Compute service.

Specify the service by its host name and binary name.

.. note:: Starting with microversion 2.53 this API is superseded by
          ``PUT /os-services/{service_id}``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - binary: binary

**Example Disable Scheduling For A Compute Service**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - host: host_name_body
  - status: service_status

**Example Disable Scheduling For A Compute Service**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-put-resp.json
   :language: javascript

Disable Scheduling For A Compute Service and Log Disabled Reason
================================================================

.. rest_method:: PUT /os-services/disable-log-reason

Disables scheduling for a Compute service and logs information to the Compute
service table about why a Compute service was disabled.

Specify the service by its host name and binary name.

.. note:: Starting with microversion 2.53 this API is superseded by
          ``PUT /os-services/{service_id}``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - binary: binary
  - disabled_reason: disabled_reason_body

**Example Disable Scheduling For A Compute Service and Log Disabled Reason**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-log-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - disabled_reason: disabled_reason_body
  - host: host_name_body
  - status: service_status

**Example Disable Scheduling For A Compute Service and Log Disabled Reason**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-log-put-resp.json
   :language: javascript

Enable Scheduling For A Compute Service
=======================================

.. rest_method:: PUT /os-services/enable

Enables scheduling for a Compute service.

Specify the service by its host name and binary name.

.. note:: Starting with microversion 2.53 this API is superseded by
          ``PUT /os-services/{service_id}``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - binary: binary

**Example Enable Scheduling For A Compute Service**

.. literalinclude:: ../../doc/api_samples/os-services/service-enable-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - host: host_name_body
  - status: service_status

**Example Enable Scheduling For A Compute Service**

.. literalinclude:: ../../doc/api_samples/os-services/service-enable-put-resp.json
   :language: javascript

Update Forced Down
==================

.. rest_method:: PUT /os-services/force-down

Set or unset ``forced_down`` flag for the service. ``forced_down`` is a manual
override to tell nova that the service in question has been fenced manually by
the operations team (either hard powered off, or network unplugged). That
signals that it is safe to proceed with ``evacuate`` or other operations that
nova has safety checks to prevent for hosts that are up.

.. warning::

   Setting a service forced down without completely fencing it will likely
   result in the corruption of VMs on that host.

Action ``force-down`` available as of microversion 2.11.

Specify the service by its host name and binary name.

.. note:: Starting with microversion 2.53 this API is superseded by
          ``PUT /os-services/{service_id}``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - binary: binary
  - forced_down: forced_down_2_11

**Example Update Forced Down**

.. literalinclude:: ../../doc/api_samples/os-services/v2.11/service-force-down-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - host: host_name_body
  - forced_down: forced_down_2_11

|

**Example Update Forced Down**

.. literalinclude:: ../../doc/api_samples/os-services/v2.11/service-force-down-put-resp.json
   :language: javascript

Update Compute Service
======================

.. rest_method:: PUT /os-services/{service_id}

Update a compute service to enable or disable scheduling, including recording a
reason why a compute service was disabled from scheduling. Set or unset the
``forced_down`` flag for the service. This operation is only allowed on
services whose ``binary`` is ``nova-compute``.

This API is available starting with microversion 2.53.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - service_id: service_id_path_2_53_no_version
  - status: service_status_2_53_in
  - disabled_reason: disabled_reason_2_53_in
  - forced_down: forced_down_2_53_in

**Example Disable Scheduling For A Compute Service (v2.53)**

.. literalinclude:: ../../doc/api_samples/os-services/v2.53/service-disable-log-put-req.json
   :language: javascript

**Example Enable Scheduling For A Compute Service (v2.53)**

.. literalinclude:: ../../doc/api_samples/os-services/v2.53/service-enable-put-req.json
   :language: javascript

**Example Update Forced Down (v2.53)**

.. literalinclude:: ../../doc/api_samples/os-services/v2.53/service-force-down-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - id: service_id_body_2_53_no_version
  - binary: binary
  - disabled_reason: disabled_reason_body
  - host: host_name_body
  - state: service_state
  - status: service_status
  - updated_at: updated
  - zone: OS-EXT-AZ:availability_zone
  - forced_down: forced_down_2_53_out

**Example Disable Scheduling For A Compute Service (v2.53)**

.. literalinclude:: ../../doc/api_samples/os-services/v2.53/service-disable-log-put-resp.json
   :language: javascript

**Example Enable Scheduling For A Compute Service (v2.53)**

.. literalinclude:: ../../doc/api_samples/os-services/v2.53/service-enable-put-resp.json
   :language: javascript

**Example Update Forced Down (v2.53)**

.. literalinclude:: ../../doc/api_samples/os-services/v2.53/service-force-down-put-resp.json
   :language: javascript

Delete Compute Service
======================

.. rest_method:: DELETE /os-services/{service_id}

Deletes a service. If it's a ``nova-compute`` service, then the
corresponding host will be removed from all the host aggregates as well.

Attempts to delete a ``nova-compute`` service which is still hosting instances
will result in a 409 HTTPConflict response. The instances will need to be
migrated or deleted before a compute service can be deleted.

Similarly, attempts to delete a ``nova-compute`` service which is involved in
in-progress migrations will result in a 409 HTTPConflict response. The
migrations will need to be completed, for example confirming or reverting a
resize, or the instances will need to be deleted before the compute service can
be deleted.

.. important:: Be sure to stop the actual ``nova-compute`` process on the
               physical host *before* deleting the service with this API.
               Failing to do so can lead to the running service re-creating
               orphaned **compute_nodes** table records in the database.

Normal response codes: 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - service_id: service_id_path_2_52
  - service_id: service_id_path_2_53

Response
--------

If successful, this method does not return content in the response body.

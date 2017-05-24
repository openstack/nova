.. -*- rst -*-

.. _os-services:

================================
 Compute services (os-services)
================================

Lists all running Compute services in a region, enables or disables
scheduling for a Compute service, logs disabled Compute service
information, and deletes a Compute service.

For an overview of Compute services, see `OpenStack
Compute <https://docs.openstack.org/ocata/install-guide-obs/common/get-started-compute.html>`__.

List Compute Services
=====================

.. rest_method:: GET /os-services

Lists all running Compute services.

Provides details why any services were disabled.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - services: services
  - id: service_id_body
  - binary: binary
  - disabled_reason: disabled_reason_body
  - host: host_name_body
  - state: service_state
  - status: service_status
  - updated_at: updated
  - zone: OS-EXT-AZ:availability_zone
  - forced_down: forced_down

**Example List Compute Services**

.. literalinclude:: ../../doc/api_samples/os-services/v2.11/services-list-get-resp.json
   :language: javascript

Disable Scheduling For A Compute Service
========================================

.. rest_method:: PUT /os-services/disable

Disables scheduling for a Compute service with optional logging.

Specify the service by its host name and binary name.

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

Log Disabled Compute Service Information
========================================

.. rest_method:: PUT /os-services/disable-log-reason

Logs information to the Compute service table about why a Compute service was disabled.

Specify the service by its host name and binary name.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - binary: binary
  - disabled_reason: disabled_reason_body

**Example Log Disabled Compute Service Information**

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

**Example Log Disabled Compute Service Information**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-log-put-resp.json
   :language: javascript

Enable Scheduling For A Compute Service
=======================================

.. rest_method:: PUT /os-services/enable

Enables scheduling for a Compute service.

Specify the service by its host name and binary name.

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

Set or unset ``forced_down`` flag for the service.

Action ``force-down`` available as of microversion 2.11.

Specify the service by its host name and binary name.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - host: host_name_body
  - binary: binary
  - forced_down: forced_down

**Example Update Forced Down**

.. literalinclude:: ../../doc/api_samples/os-services/v2.11/service-force-down-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - host: host_name_body
  - forced_down: forced_down

|

**Example Update Forced Down**

.. literalinclude:: ../../doc/api_samples/os-services/v2.11/service-force-down-put-resp.json
   :language: javascript

Delete Compute Service
======================

.. rest_method:: DELETE /os-services/{service_id}

Deletes a Compute service. If it's a nova-compute service, then the
corresponding host will be removed from all the host aggregates as well.

Normal response codes: 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - service_id: service_id_path

Response
--------

If successful, this method does not return content in the response body.

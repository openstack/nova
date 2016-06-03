.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

================================
 Compute services (os-services)
================================

Lists all running Compute services for a tenant, enables or disables
scheduling for a Compute service, logs disabled Compute service
information, and deletes a Compute service.

For an overview of Compute services, see `OpenStack
Compute <http://docs.openstack.org/liberty/install-guide-obs/common/get_started_compute.html>`__.

List Compute Services
=====================

.. rest_method:: GET /os-services

Lists all running Compute services.

Includes reasons, if available, for why any services were disabled.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - services: services
  - id: id
  - binary: binary
  - disabled_reason: disabled_reason
  - host: host
  - state: service_state
  - status: service_status
  - updated_at: updated
  - forced_down: forced_down
  - zone: OS-EXT-AZ:availability_zone

**Example List Compute Services: JSON response**

.. literalinclude:: ../../doc/api_samples/os-services/services-list-get-resp.json
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


  - host: host
  - binary: binary

**Example Enable Scheduling For A Compute Service: JSON request**

.. literalinclude:: ../../doc/api_samples/os-services/service-enable-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - host: host
  - status: service_status

**Example Enable Scheduling For A Compute Service: JSON response**

.. literalinclude:: ../../doc/api_samples/os-services/service-enable-put-resp.json
   :language: javascript

Disable Scheduling For A Compute Service
========================================

.. rest_method:: PUT /os-services/disable

Disables scheduling for a Compute service.

Specify the service by its host name and binary name.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - host: host
  - binary: binary

**Example Disable Scheduling For A Compute Service: JSON request**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - host: host
  - status: service_status

**Example Disable Scheduling For A Compute Service: JSON response**

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


  - host: host
  - binary: binary
  - disabled_reason: disabled_reason

**Example Log Disabled Compute Service Information: JSON request**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-log-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - service: service
  - binary: binary
  - disabled_reason: disabled_reason
  - host: host
  - status: service_status

**Example Log Disabled Compute Service Information: JSON response**

.. literalinclude:: ../../doc/api_samples/os-services/service-disable-log-put-resp.json
   :language: javascript

Delete Compute Service
======================

.. rest_method:: DELETE /os-services/{service_id}

Deletes a Compute service.

Normal response codes: 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - service_id: service_id_path

Response
--------

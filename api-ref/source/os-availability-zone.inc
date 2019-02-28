.. -*- rst -*-

.. _os-availability-zone:

===========================================
 Availability zones (os-availability-zone)
===========================================

Lists and gets detailed availability zone information.

An availability zone is created or updated by setting the
availability_zone parameter in the ``create``, ``update``, or
``create or update`` methods of the Host Aggregates API.
See `Host Aggregates
<https://docs.openstack.org/nova/latest/user/aggregates.html>`_
for more details.


Get Availability Zone Information
=================================

.. rest_method:: GET /os-availability-zone

Lists availability zone information.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - availabilityZoneInfo: availability_zone_info
  - hosts: hosts.availability_zone_none
  - zoneName: OS-EXT-AZ:availability_zone
  - zoneState: availability_zone_state
  - available: available

|

**Example Get availability zone information**

.. literalinclude:: ../../doc/api_samples/os-availability-zone/availability-zone-list-resp.json
   :language: javascript

Get Detailed Availability Zone Information
==========================================

.. rest_method:: GET /os-availability-zone/detail

Gets detailed availability zone information.
Policy defaults enable only users with the administrative role to perform this operation.
Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - availabilityZoneInfo: availability_zone_info
  - hosts: hosts.availability_zone
  - zoneName: OS-EXT-AZ:availability_zone
  - zoneState: availability_zone_state
  - available: available

|

**Example Get detailed availability zone information**

.. literalinclude:: ../../doc/api_samples/os-availability-zone/availability-zone-detail-resp.json
   :language: javascript

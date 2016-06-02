.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

===========================================
 Availability zones (os-availability-zone)
===========================================

Shows availability zone information.

Get Availability Zone Information
=================================

.. rest_method:: GET /os-availability-zone

Gets availability zone information.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example Get availability zone information: JSON response**

.. literalinclude:: ../../doc/api_samples/os-availability-zone/availability-zone-list-resp.json
   :language: javascript

Get Detailed Availability Zone Information
==========================================

.. rest_method:: GET /os-availability-zone/detail

Gets detailed availability zone information.
Policy defaults enable only users with the administrative role to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example Get detailed availability zone information: JSON response**

.. literalinclude:: ../../doc/api_samples/os-availability-zone/availability-zone-detail-resp.json
   :language: javascript

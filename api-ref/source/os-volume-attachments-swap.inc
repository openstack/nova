.. -*- rst -*-

.. _os-volume-attachments-swap:

===============================================================================
Update ("swapping") Server volume attachments (servers, os-volume\_attachments)
===============================================================================

Update ("swapping") the server volume attachments which means swapping
the volume attached to the server.

Update(swapping) a volume attachment
====================================

.. rest_method:: PUT /servers/{server_id}/os-volume_attachments/{volume_id}

Update a volume attachment.

.. note:: This action only valid when the server is in ACTIVE, PAUSED and RESIZED state,
          or a conflict(409) error will be returned.

.. Important::

   When updating volumeId, this API **MUST**  only be used
   as part of a larger orchestrated volume
   migration operation initiated in the block storage
   service via the ``os-retype`` or ``os-migrate_volume``
   volume actions. Direct usage of this API is not supported
   and will be blocked by nova with a 409 conflict.
   Furthermore, updating ``volumeId`` via this API is only
   implemented by `certain compute drivers`_.

.. _certain compute drivers: https://docs.openstack.org/nova/latest/user/support-matrix.html#operation_swap_volume

Updating, or what is commonly referred to as "swapping", volume attachments
with volumes that have more than one read/write attachment, is not supported.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - volume_id: volume_id_swap_src
  - volumeAttachment: volumeAttachment_put
  - volumeId: volumeId_swap

**Example Update a volume attachment: JSON request**

.. literalinclude:: ../../doc/api_samples/os-volume_attachments/update-volume-req.json
   :language: javascript

Response
--------

No body is returned on successful request.

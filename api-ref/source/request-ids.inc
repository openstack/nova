.. -*- rst -*-

===========
Request IDs
===========

Users can specify the global request ID in the request header.
Users can receive the local request ID in the response header.

For more details about Request IDs, please reference: `Faults
<https://developer.openstack.org/api-guide/compute/faults.html>`_

**Request**

.. rest_parameters:: parameters.yaml

  - X-Openstack-Request-Id: x-openstack-request-id_req

**Response**

.. rest_parameters:: parameters.yaml

  - X-Compute-Request-Id: x-compute-request-id_resp
  - X-Openstack-Request-Id: x-openstack-request-id_resp

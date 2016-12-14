.. -*- rst -*-

===================================================
 Bare metal nodes (os-baremetal-nodes) (DEPRECATED)
===================================================

.. warning::

   These APIs are proxy calls to the Ironic service. They exist for
   legacy compatibility, but no new applications should use them.
   Nova has deprecated all the proxy APIs and users should use the native
   APIs instead. These will fail with a 404 starting from microversion 2.36.
   See: `Relevant Bare metal APIs
   <http://developer.openstack.org/api-ref/baremetal/index.html#nodes-nodes>`__.

Bare metal nodes.

List Bare Metal Nodes
=====================

.. rest_method:: GET /os-baremetal-nodes

Lists the bare metal nodes known by the compute environment.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403),
notImplemented(501)


Response
--------

.. rest_parameters:: parameters.yaml

   - nodes: baremetal_nodes
   - id: baremetal_id
   - interfaces: baremetal_interfaces
   - host: baremetal_host
   - task_state: baremetal_taskstate
   - cpus: baremetal_cpus
   - memory_mb: baremetal_mem
   - disk_gb: baremetal_disk

**Example List Bare Metal Nodes**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-list-resp.json
   :language: javascript

Show Bare Metal Node Details
============================

.. rest_method:: GET /os-baremetal-nodes/{node_id}

Shows details for a bare metal node.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403),
itemNotFound(404), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - node_id: node_id

Response
--------

.. rest_parameters:: parameters.yaml

   - node: baremetal_node
   - id: baremetal_id
   - instance_uuid: baremetal_instance_uuid
   - interfaces: baremetal_interfaces
   - host: baremetal_host
   - task_state: baremetal_taskstate
   - cpus: baremetal_cpus
   - memory_mb: baremetal_mem
   - disk_gb: baremetal_disk

**Example Show Bare Metal Node Details**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-get-resp.json
   :language: javascript

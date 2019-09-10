.. -*- rst -*-

=====================================
Servers Topology (servers, topology)
=====================================

Shows the NUMA topology information for a server.

Show Server Topology
====================

.. rest_method:: GET /servers/{server_id}/topology
.. versionadded:: 2.78

Shows NUMA topology information for a server.

Policy defaults enable only users with the administrative role or the owners
of the server to perform this operation. Cloud providers can change these
permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), notfound(404), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

All response fields are listed below. If some information is not available or
not allow by policy, the corresponding key value will not exist in response.

.. rest_parameters:: parameters.yaml

  - nodes: server_topology_nodes
  - nodes.cpu_pinning: server_topology_nodes_cpu_pinning
  - nodes.vcpu_set: server_topology_nodes_vcpu_set
  - nodes.siblings: server_topology_nodes_cpu_siblings
  - nodes.memory_mb: server_topology_nodes_memory_mb
  - nodes.host_node: server_topology_nodes_host_node
  - pagesize_kb: server_topology_pagesize_kb

**Example Server topology (2.xx)**

.. literalinclude:: ../../doc/api_samples/os-server-topology/v2.78/servers-topology-resp.json
   :language: javascript


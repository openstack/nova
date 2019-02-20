=================
Cross-cell resize
=================

Train spec: https://specs.openstack.org/openstack/nova-specs/specs/train/approved/cross-cell-resize.html

.. todo:: Flesh this out to describe what cross-cell resize is, how it is
  triggered (policy), related configuration (long_rpc_timeout) including
  the CrossCellWeigher, limitations and known issues, recovering from failures
  during a cross-cell resize, maybe a flow chart for the overall process in
  the code, minimum upgrade requirements and supported drivers (libvirt-only
  at this time).

Limitations
~~~~~~~~~~~

These are known to not yet be supported in the code:

* Instances with ports attached that have bandwidth-aware resource provider
  allocations.
* Reschedules

These are likely not to work since they have not been validated by testing:

* Instances with PCI devices attached.
* Instances with a NUMA topology.

==================
User Documentation
==================

End user guide
--------------

.. toctree::
   :maxdepth: 1

   availability-zones
   launch-instances
   metadata
   manage-ip-addresses
   certificate-validation
   resize
   reboot
   rescue
   availability-zones
   block-device-mapping
   /reference/api-microversion-history

.. todo:: The rest of this document should probably move to the admin guide.

Architecture Overview
---------------------

* :doc:`Nova architecture </user/architecture>`: An overview of how all the parts in
  nova fit together.

* :doc:`Block Device Mapping </user/block-device-mapping>`: One of the more
  complicated parts to understand is the Block Device Mapping parameters used
  to connect specific block devices to computes. This deserves its own deep
  dive.

See the :ref:`reference guide <reference-internals>` for details about more
internal subsystems.

Deployment Considerations
-------------------------

There is information you might want to consider before doing your deployment,
especially if it is going to be a larger deployment. For smaller deployments
the defaults from the :doc:`install guide </install/index>` will be sufficient.

* **Compute Driver Features Supported**: While the majority of nova deployments use
  libvirt/kvm, you can use nova with other compute drivers. Nova attempts to
  provide a unified feature set across these, however, not all features are
  implemented on all backends, and not all features are equally well tested.

  * :doc:`Feature Support by Use Case </user/feature-classification>`: A view of
    what features each driver supports based on what's important to some large
    use cases (General Purpose Cloud, NFV Cloud, HPC Cloud).

  * :doc:`Feature Support full list </user/support-matrix>`: A detailed dive through
    features in each compute driver backend.

* :doc:`Cells v2 Planning </user/cellsv2-layout>`: For large deployments, Cells v2
  allows sharding of your compute environment. Upfront planning is key to a
  successful Cells v2 layout.

* :placement-doc:`Placement service <>`: Overview of the placement
  service, including how it fits in with the rest of nova.

* :doc:`Running nova-api on wsgi </user/wsgi>`: Considerations for using a real
  WSGI container instead of the baked-in eventlet web server.

Maintenance
-----------

Once you are running nova, the following information is extremely useful.

* :doc:`Admin Guide </admin/index>`: A collection of guides for administrating
  nova.

* :doc:`Upgrades </user/upgrade>`: How nova is designed to be upgraded for minimal
  service impact, and the order you should do them in.

* :doc:`Quotas </user/quotas>`: Managing project quotas in nova.

* :doc:`Availablity Zones </admin/availability-zones>`: Availability Zones are
  an end-user visible logical abstraction for partitioning a cloud without
  knowing the physical infrastructure. They can be used to partition a cloud on
  arbitrary factors, such as location (country, datacenter, rack), network
  layout and/or power source.

* :doc:`Filter Scheduler </user/filter-scheduler>`: How the filter scheduler is
  configured, and how that will impact where compute instances land in your
  environment. If you are seeing unexpected distribution of compute instances
  in your hosts, you'll want to dive into this configuration.

* :doc:`Exposing custom metadata to compute instances </admin/vendordata>`: How
  and when you might want to extend the basic metadata exposed to compute
  instances (either via metadata server or config drive) for your specific
  purposes.

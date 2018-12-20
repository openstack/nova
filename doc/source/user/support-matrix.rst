
Feature Support Matrix
======================

.. TODO: Add UML (User-Mode Linux) hypervisor and its support status
   for the listed features to the support matrix.

When considering which capabilities should be marked as mandatory the
following general guiding principles were applied

* **Inclusivity** - people have shown ability to make effective
  use of a wide range of virtualization technologies with broadly
  varying feature sets. Aiming to keep the requirements as inclusive
  as possible, avoids second-guessing what a user may wish to use
  the cloud compute service for.

* **Bootstrapping** - a practical use case test is to consider that
  starting point for the compute deploy is an empty data center
  with new machines and network connectivity. The look at what
  are the minimum features required of a compute service, in order
  to get user instances running and processing work over the
  network.

* **Competition** - an early leader in the cloud compute service space
  was Amazon EC2. A sanity check for whether a feature should be
  mandatory is to consider whether it was available in the first
  public release of EC2. This had quite a narrow feature set, but
  none the less found very high usage in many use cases. So it
  serves to illustrate that many features need not be considered
  mandatory in order to get useful work done.

* **Reality** - there are many virt drivers currently shipped with
  Nova, each with their own supported feature set. Any feature which is
  missing in at least one virt driver that is already in-tree, must
  by inference be considered optional until all in-tree drivers
  support it. This does not rule out the possibility of a currently
  optional feature becoming mandatory at a later date, based on other
  principles above.

.. support_matrix:: support-matrix.ini

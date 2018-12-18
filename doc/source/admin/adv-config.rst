======================
Advanced configuration
======================

OpenStack clouds run on platforms that differ greatly in the capabilities that
they provide. By default, the Compute service seeks to abstract the underlying
hardware that it runs on, rather than exposing specifics about the underlying
host platforms. This abstraction manifests itself in many ways. For example,
rather than exposing the types and topologies of CPUs running on hosts, the
service exposes a number of generic CPUs (virtual CPUs, or vCPUs) and allows
for overcommitting of these. In a similar manner, rather than exposing the
individual types of network devices available on hosts, generic
software-powered network ports are provided. These features are designed to
allow high resource utilization and allows the service to provide a generic
cost-effective and highly scalable cloud upon which to build applications.

This abstraction is beneficial for most workloads. However, there are some
workloads where determinism and per-instance performance are important, if not
vital. In these cases, instances can be expected to deliver near-native
performance. The Compute service provides features to improve individual
instance for these kind of workloads.

.. include:: /common/numa-live-migration-warning.txt

.. toctree::
   :maxdepth: 2

   pci-passthrough
   cpu-topologies
   huge-pages
   virtual-gpu
   file-backed-memory

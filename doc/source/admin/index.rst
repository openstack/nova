=======
Compute
=======

The OpenStack Compute service allows you to control an
Infrastructure-as-a-Service (IaaS) cloud computing platform.  It gives you
control over instances and networks, and allows you to manage access to the
cloud through users and projects.

Compute does not include virtualization software. Instead, it defines drivers
that interact with underlying virtualization mechanisms that run on your host
operating system, and exposes functionality over a web-based API.

.. TODO(mriedem): This index page has a lot of content which should be
   organized into groups for things like configuration, operations,
   troubleshooting, etc.

.. toctree::
   :maxdepth: 2

   admin-password-injection.rst
   adv-config.rst
   arch.rst
   availability-zones.rst
   cells.rst
   config-drive.rst
   configuration/index.rst
   configuring-migrations.rst
   cpu-topologies.rst
   default-ports.rst
   evacuate.rst
   flavors.rst
   huge-pages.rst
   image-caching.rst
   live-migration-usage.rst
   manage-logs.rst
   manage-the-cloud.rst
   manage-users.rst
   manage-volumes.rst
   metadata-service.rst
   migration.rst
   migrate-instance-with-snapshot.rst
   networking-nova.rst
   networking.rst
   node-down.rst
   pci-passthrough.rst
   quotas2.rst
   quotas.rst
   remote-console-access.rst
   root-wrap-reference.rst
   security-groups.rst
   security.rst
   service-groups.rst
   services.rst
   ssh-configuration.rst
   support-compute.rst
   system-admin.rst
   secure-live-migration-with-qemu-native-tls.rst
   mitigation-for-Intel-MDS-security-flaws.rst
   vendordata.rst

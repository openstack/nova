==================
User Documentation
==================

The OpenStack Compute service allows you to control an
Infrastructure-as-a-Service (IaaS) cloud computing platform.  It gives you
control over instances and networks, and allows you to manage access to the
cloud through users and projects.

Compute does not include virtualization software. Instead, it defines drivers
that interact with underlying virtualization mechanisms that run on your host
operating system, and exposes functionality over a web-based API.

End user guide
--------------

.. toctree::
   :maxdepth: 1

   availability-zones
   security-groups
   launch-instances
   server-groups
   metadata
   manage-ip-addresses
   certificate-validation
   resize
   reboot
   rescue
   block-device-mapping
   /reference/api-microversion-history

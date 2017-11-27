===================
Configuration Guide
===================

The static configuration for nova lives in two main files: ``nova.conf`` and
``policy.json``. These are described below. For a bigger picture view on
configuring nova to solve specific problems, refer to the :doc:`Nova Admin
Guide </admin/index>`.

Configuration
-------------

* :doc:`Configuration Guide </admin/configuration/index>`: Detailed
  configuration guides for various parts of you Nova system. Helpful reference
  for setting up specific hypervisor backends.

* :doc:`Config Reference </configuration/config>`: A complete reference of all
  configuration options available in the ``nova.conf`` file.

* :doc:`Sample Config File </configuration/sample-config>`: A sample config
  file with inline documentation.

Policy
------

Nova, like most OpenStack projects, uses a policy language to restrict
permissions on REST API actions.

* :doc:`Policy Reference </configuration/policy>`: A complete reference of all
  policy points in nova and what they impact.

* :doc:`Sample Policy File </configuration/sample-policy>`: A sample policy
  file with inline documentation.

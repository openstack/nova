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

* :doc:`Config Reference <config>`: A complete reference of all
  configuration options available in the ``nova.conf`` file.

* :doc:`Sample Config File <sample-config>`: A sample config
  file with inline documentation.

Nova Policy
-----------

Nova, like most OpenStack projects, uses a policy language to restrict
permissions on REST API actions.

* :doc:`Policy Reference <policy>`: A complete reference of all
  policy points in nova and what they impact.

* :doc:`Sample Policy File <sample-policy>`: A sample nova
  policy file with inline documentation.

Placement Policy
----------------

Placement, like most OpenStack projects, uses a policy language to restrict
permissions on REST API actions.

* :doc:`Policy Reference <placement-policy>`: A complete
  reference of all policy points in placement and what they impact.

* :doc:`Sample Policy File <sample-placement-policy>`: A sample
  placement policy file with inline documentation.


.. # NOTE(mriedem): This is the section where we hide things that we don't
   # actually want in the table of contents but sphinx build would fail if
   # they aren't in the toctree somewhere.
.. toctree::
   :hidden:

   config
   sample-config
   policy
   sample-policy
   placement-policy
   sample-placement-policy

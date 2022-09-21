===================
Configuration Guide
===================

The static configuration for nova lives in two main files: ``nova.conf`` and
``policy.yaml``. These are described below. For a bigger picture view on
configuring nova to solve specific problems, refer to the :doc:`Nova Admin
Guide </admin/index>`.

Configuration
-------------

Nova, like most OpenStack projects, uses INI-style configuration files to
configure various services and utilities. This functionality is provided by the
`oslo.config`__ project. *oslo.config* supports loading configuration from both
individual configuration files and a directory of configuration files. By
default, nova will search the below directories for two config files -
``nova.conf`` and ``{prog}.conf``, where ``prog`` corresponds to the name of
the service or utility being configured such as :program:`nova-compute` - and
two config directories - ``nova.conf.d`` and ``{prog}.conf.d``:

- ``${HOME}/.nova``
- ``${HOME}``
- ``/etc/nova``
- ``/etc``
- ``${SNAP_COMMON}/etc/nova/``
- ``${SNAP}/etc/nova/``

Where a matching file is found, all other directories will be skipped.
This behavior can be overridden by using the ``--config-file`` and
``--config-dir`` options provided for each executable.

More information on how you can use the configuration options to configure
services and what configuration options are available can be found below.

* :doc:`Configuration Guide </admin/configuration/index>`: Detailed
  configuration guides for various parts of your Nova system. Helpful
  reference for setting up specific hypervisor backends.

* :doc:`Config Reference <config>`: A complete reference of all
  configuration options available in the ``nova.conf`` file.

.. only:: html

   * :doc:`Sample Config File <sample-config>`: A sample config
     file with inline documentation.

.. # NOTE(mriedem): This is the section where we hide things that we don't
   # actually want in the table of contents but sphinx build would fail if
   # they aren't in the toctree somewhere.
.. # NOTE(amotoki): toctree needs to be placed at the end of the section to
   # keep the document structure in the PDF doc.
.. toctree::
   :hidden:

   config

.. # NOTE(amotoki): Sample files are only available in HTML document.
   # Inline sample files with literalinclude hit LaTeX processing error
   # like TeX capacity exceeded and direct links are discouraged in PDF doc.
.. only:: html

   .. toctree::
      :hidden:

      sample-config

.. __: https://docs.openstack.org/oslo.config/latest/

Policy
------

Nova, like most OpenStack projects, uses a policy language to restrict
permissions on REST API actions. This functionality is provided by the
`oslo.policy`__ project. *oslo.policy* supports loading policy configuration
from both an individual configuration file, which defaults to ``policy.yaml``,
and one or more directories of configuration files, which defaults to
``policy.d``. These must be located in the same directory as the ``nova.conf``
file(s). This behavior can be overridden by setting the
:oslo.config:option:`oslo_policy.policy_file` and
:oslo.config:option:`oslo_policy.policy_dirs` configuration options.

More information on how nova's policy configuration works and about what
policies are available can be found below.

* :doc:`Policy Concepts <policy-concepts>`: Starting in the Ussuri
  release, Nova API policy defines new default roles with system scope
  capabilities. These new changes improve the security level and
  manageability of Nova API as they are richer in terms of handling access at
  system and project level token with 'Read' and 'Write' roles.

* :doc:`Policy Reference <policy>`: A complete reference of all
  policy points in nova and what they impact.

.. only:: html

   * :doc:`Sample Policy File <sample-policy>`: A sample nova
     policy file with inline documentation.

.. # NOTE(mriedem): This is the section where we hide things that we don't
   # actually want in the table of contents but sphinx build would fail if
   # they aren't in the toctree somewhere.
.. # NOTE(amotoki): toctree needs to be placed at the end of the section to
   # keep the document structure in the PDF doc.
.. toctree::
   :hidden:

   policy-concepts
   policy

.. # NOTE(amotoki): Sample files are only available in HTML document.
   # Inline sample files with literalinclude hit LaTeX processing error
   # like TeX capacity exceeded and direct links are discouraged in PDF doc.
.. only:: html

   .. toctree::
      :hidden:

      sample-policy

.. __: https://docs.openstack.org/oslo.policy/latest/

Extra Specs
-----------

Nova uses *flavor extra specs* as a way to provide additional information to
instances beyond basic information like amount of RAM or disk. This information
can range from hints for the scheduler to hypervisor-specific configuration
instructions for the instance.

* :doc:`Extra Spec Reference <extra-specs>`: A complete reference for all extra
  specs currently recognized and supported by nova.

.. toctree::
   :hidden:

   extra-specs

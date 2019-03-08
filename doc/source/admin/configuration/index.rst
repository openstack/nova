===============
 Configuration
===============

To configure your Compute installation, you must define configuration options
in these files:

* ``nova.conf`` contains most of the Compute configuration options and resides
  in the ``/etc/nova`` directory.

* ``api-paste.ini`` defines Compute limits and resides in the ``/etc/nova``
  directory.

* Configuration files for related services, such as the Image and Identity
  services.

A list of config options based on different topics can be found below:

.. toctree::
   :maxdepth: 1

   /admin/configuration/api.rst
   /admin/configuration/resize.rst
   /admin/configuration/fibre-channel.rst
   /admin/configuration/iscsi-offload.rst
   /admin/configuration/hypervisors.rst
   /admin/configuration/schedulers.rst
   /admin/configuration/logs.rst
   /admin/configuration/samples/index.rst

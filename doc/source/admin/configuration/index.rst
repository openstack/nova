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

   /admin/configuration/api
   /admin/configuration/resize
   /admin/configuration/cross-cell-resize
   /admin/configuration/fibre-channel
   /admin/configuration/iscsi-offload
   /admin/configuration/hypervisors
   /admin/configuration/schedulers
   /admin/configuration/logs
   /admin/configuration/samples/index

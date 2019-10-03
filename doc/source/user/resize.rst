==================
Resize an instance
==================

You can change the size of an instance by changing its flavor. This rebuilds
the instance and therefore results in a restart.

To list the VMs you want to resize, run:

.. code-block:: console

   $ openstack server list

Once you have the name or UUID of the server you wish to resize, resize it
using the :command:`openstack server resize` command:

.. code-block:: console

   $ openstack server resize --flavor FLAVOR SERVER

.. note::

   By default, the :command:`openstack server resize` command gives the guest
   operating system a chance to perform a controlled shutdown before the
   instance is powered off and the instance is resized. This behavior can be
   configured by the administrator but it can also be overridden on a per image
   basis using the ``os_shutdown_timeout`` image metadata setting. This allows
   different types of operating systems to specify how much time they need to
   shut down cleanly. See :glance-doc:`Useful image properties
   <admin/useful-image-properties>` for details.

Resizing can take some time. During this time, the instance status will be
``RESIZE``:

.. code-block:: console

   $ openstack server list
   +----------------------+----------------+--------+-----------------------------------------+
   | ID                   | Name           | Status | Networks                                |
   +----------------------+----------------+--------+-----------------------------------------+
   | 67bc9a9a-5928-47c... | myCirrosServer | RESIZE | admin_internal_net=192.168.111.139      |
   +----------------------+----------------+--------+-----------------------------------------+

When the resize completes, the instance status will be ``VERIFY_RESIZE``.
You can now confirm the resize to change the status to ``ACTIVE``:

.. code-block:: console

   $ openstack server resize confirm SERVER

.. note::

   The resized server may be automatically confirmed based on the
   administrator's configuration of the deployment.

If the resize does not work as expected, you can revert the resize. This will
revert the instance to the old flavor and change the status to ``ACTIVE``:

.. code-block:: console

   $ openstack server resize revert SERVER

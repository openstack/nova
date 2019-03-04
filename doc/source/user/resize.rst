==================
Resize an instance
==================

You can change the size of an instance by changing its flavor. This rebuilds
the instance and therefore results in a restart.

To resize an instance, use the :command:`openstack server resize` command:

.. code-block:: console

   $ openstack server resize --flavor FLAVOR SERVER

.. note::

   By default, the :command:`openstack server resize` command gives
   the guest operating
   system a chance to perform a controlled shutdown before the instance
   is powered off and the instance is resized.
   The shutdown behavior is configured by the
   :oslo.config:option:`shutdown_timeout` parameter that can be set in the
   ``nova.conf`` file. Its value stands for the overall
   period (in seconds) a guest operating system is allowed
   to complete the shutdown. The default timeout is 60 seconds.

   The timeout value can be overridden on a per image basis
   by means of ``os_shutdown_timeout`` that is an image metadata
   setting allowing different types of operating systems to specify
   how much time they need to shut down cleanly. See
   :glance-doc:`Useful image properties <admin/useful-image-properties>`
   for details.

Resizing can take some time.
During this time, the instance status will be ``RESIZE``:

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

   $ openstack server resize --confirm SERVER

.. note::

  The resized server may be automatically confirmed based on
  the administrator's configuration of the deployment.

If the resize fails or does not work as expected, you can revert the resize.
This will revert the instance to the old flavor and change the status to
``ACTIVE``:

.. code-block:: console

   $ openstack server resize --revert SERVER

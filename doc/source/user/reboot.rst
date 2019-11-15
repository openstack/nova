==================
Reboot an instance
==================

You can soft or hard reboot a running instance. A soft reboot attempts a
graceful shut down and restart of the instance. A hard reboot power
cycles the instance.

To reboot a server, use the :command:`openstack server reboot` command:

.. code-block:: console

   $ openstack server reboot SERVER

By default, when you reboot an instance it is a soft reboot.
To perform a hard reboot, pass the ``--hard`` parameter as follows:

.. code-block:: console

   $ openstack server reboot --hard SERVER

It is also possible to reboot a running instance into rescue mode. For example,
this operation may be required if a filesystem of an instance becomes corrupted
with prolonged use. See :doc:`rescue` for more details.

=============
rootwrap.conf
=============

The ``rootwrap.conf`` file defines configuration values
used by the rootwrap script when the Compute service needs
to escalate its privileges to those of the root user.

It is also possible to disable the root wrapper, and default
to sudo only. Configure the ``disable_rootwrap`` option in the
``[workaround]`` section of the ``nova.conf`` configuration file.

.. literalinclude:: /../../etc/nova/rootwrap.conf

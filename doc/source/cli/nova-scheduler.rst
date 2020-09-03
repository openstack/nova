==============
nova-scheduler
==============

.. program:: nova-scheduler

Synopsis
========

::

  nova-scheduler [<options>...]

Description
===========

:program:`nova-scheduler` is a server daemon that serves the Nova Scheduler
service, which is responsible for picking a compute node to run a given
instance on.

Options
=======

**General options**

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/policy.yaml``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

* :nova-doc:`OpenStack Nova <>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__

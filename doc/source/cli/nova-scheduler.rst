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

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: Debugger options

.. include:: opts/debugger.rst

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

:doc:`nova-compute(1) <nova-compute>`,
:doc:`nova-conductor(1) <nova-conductor>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__

==============
nova-conductor
==============

.. program:: nova-conductor

Synopsis
========

::

  nova-conductor [<options>...]

Description
===========

:program:`nova-conductor` is a server daemon that serves the Nova Conductor
service, which provides coordination and database query support for nova.

Options
=======

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: Debugger options

.. include:: opts/debugger.rst

Files
=====

* ``/etc/nova/nova.conf``

See Also
========

:doc:`nova-compute(1) <nova-compute>`,
:doc:`nova-manage(1) <nova-manage>`,
:doc:`nova-rootwrap(1) <nova-rootwrap>`,
:doc:`nova-scheduler(1) <nova-scheduler>`,
:doc:`nova-status(1) <nova-status>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__

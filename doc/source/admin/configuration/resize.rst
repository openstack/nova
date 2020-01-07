======
Resize
======

Resize (or Server resize) is the ability to change the flavor of a server, thus
allowing it to upscale or downscale according to user needs.  For this feature
to work properly, you might need to configure some underlying virt layers.

This document describes how to configure hosts for standard resize.
For information on :term:`cross-cell resize <Cross-Cell Resize>`, refer to
:doc:`/admin/configuration/cross-cell-resize`.

Virt drivers
------------

.. todo:: This section needs to be updated for other virt drivers, shared
          storage considerations, etc.

KVM
~~~

Resize on KVM is implemented currently by transferring the images between
compute nodes over ssh. For KVM you need hostnames to resolve properly and
passwordless ssh access between your compute hosts. Direct access from one
compute host to another is needed to copy the VM file across.

Cloud end users can find out how to resize a server by reading
:doc:`/user/resize`.

XenServer
~~~~~~~~~

To get resize to work with XenServer (and XCP), you need to establish a root
trust between all hypervisor nodes and provide an ``/image`` mount point to
your hypervisors dom0.

Automatic confirm
-----------------

There is a periodic task configured by configuration option
:oslo.config:option:`resize_confirm_window` (in seconds).
If this value is not 0, the ``nova-compute`` service will check whether
servers are in a resized state longer than the value of
:oslo.config:option:`resize_confirm_window` and if so will automatically
confirm the resize of the servers.

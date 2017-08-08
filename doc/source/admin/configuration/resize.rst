================
Configure resize
================

Resize (or Server resize) is the ability to change the flavor of a server, thus
allowing it to upscale or downscale according to user needs.  For this feature
to work properly, you might need to configure some underlying virt layers.

KVM
~~~

Resize on KVM is implemented currently by transferring the images between
compute nodes over ssh. For KVM you need hostnames to resolve properly and
passwordless ssh access between your compute hosts. Direct access from one
compute host to another is needed to copy the VM file across.

Cloud end users can find out how to resize a server by reading the `OpenStack
End User Guide <https://docs.openstack.org/user-guide/
cli_change_the_size_of_your_server.html>`_.

XenServer
~~~~~~~~~

To get resize to work with XenServer (and XCP), you need to establish a root
trust between all hypervisor nodes and provide an ``/image`` mount point to
your hypervisors dom0.

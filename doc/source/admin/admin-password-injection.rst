====================================
Injecting the administrator password
====================================

Compute can generate a random administrator (root) password and inject that
password into an instance. If this feature is enabled, users can run
:command:`ssh` to an instance without an :command:`ssh` keypair.  The random
password appears in the output of the :command:`openstack server create`
command.  You can also view and set the admin password from the dashboard.

.. rubric:: Password injection using the dashboard

By default, the dashboard will display the ``admin`` password and allow the
user to modify it.

If you do not want to support password injection, disable the password fields
by editing the dashboard's ``local_settings.py`` file.

.. code-block:: none

   OPENSTACK_HYPERVISOR_FEATURES = {
   ...
       'can_set_password': False,
   }

.. rubric:: Password injection on libvirt-based hypervisors

For hypervisors that use the libvirt back end (such as KVM, QEMU, and LXC),
admin password injection is disabled by default. To enable it, set this option
in ``/etc/nova/nova.conf``:

.. code-block:: ini

   [libvirt]
   inject_password=true

When enabled, Compute will modify the password of the admin account by editing
the ``/etc/shadow`` file inside the virtual machine instance.

.. note::

   Linux distribution guest only.

.. note::

   Users can only use :command:`ssh` to access the instance by using the admin
   password if the virtual machine image is a Linux distribution, and it has
   been configured to allow users to use :command:`ssh` as the root user. This
   is not the case for `Ubuntu cloud images <http://uec-images.ubuntu.com>`_
   which, by default, does not allow users to use :command:`ssh` to access the
   root account.

.. rubric:: Password injection and XenAPI (XenServer/XCP)

When using the XenAPI hypervisor back end, Compute uses the XenAPI agent to
inject passwords into guests. The virtual machine image must be configured with
the agent for password injection to work.

.. rubric:: Password injection and Windows images (all hypervisors)

For Windows virtual machines, configure the Windows image to retrieve the admin
password on boot by installing an agent such as `cloudbase-init
<https://cloudbase.it/cloudbase-init>`_.

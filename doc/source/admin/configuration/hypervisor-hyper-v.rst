===============================
Hyper-V virtualization platform
===============================

.. todo:: This is really installation guide material and should probably be
     moved.

It is possible to use Hyper-V as a compute node within an OpenStack Deployment.
The ``nova-compute`` service runs as ``openstack-compute``, a 32-bit service
directly upon the Windows platform with the Hyper-V role enabled. The necessary
Python components as well as the ``nova-compute`` service are installed
directly onto the Windows platform. Windows Clustering Services are not needed
for functionality within the OpenStack infrastructure.  The use of the Windows
Server 2012 platform is recommend for the best experience and is the platform
for active development.  The following Windows platforms have been tested as
compute nodes:

- Windows Server 2012
- Windows Server 2012 R2 Server and Core (with the Hyper-V role enabled)
- Hyper-V Server

Hyper-V configuration
~~~~~~~~~~~~~~~~~~~~~

The only OpenStack services required on a Hyper-V node are ``nova-compute`` and
``neutron-hyperv-agent``. Regarding the resources needed for this host you have
to consider that Hyper-V will require 16 GB - 20 GB of disk space for the OS
itself, including updates. Two NICs are required, one connected to the
management network and one to the guest data network.

The following sections discuss how to prepare the Windows Hyper-V node for
operation as an OpenStack compute node. Unless stated otherwise, any
configuration information should work for the Windows 2012 and 2012 R2
platforms.

Local storage considerations
----------------------------

The Hyper-V compute node needs to have ample storage for storing the virtual
machine images running on the compute nodes. You may use a single volume for
all, or partition it into an OS volume and VM volume.

.. _configure-ntp-windows:

Configure NTP
-------------

Network time services must be configured to ensure proper operation of the
OpenStack nodes. To set network time on your Windows host you must run the
following commands:

.. code-block:: bat

   C:\>net stop w32time
   C:\>w32tm /config "/manualpeerlist:pool.ntp.org,0x8" /syncfromflags:MANUAL
   C:\>net start w32time

Keep in mind that the node will have to be time synchronized with the other
nodes of your OpenStack environment, so it is important to use the same NTP
server. Note that in case of an Active Directory environment, you may do this
only for the AD Domain Controller.

Configure Hyper-V virtual switching
-----------------------------------

Information regarding the Hyper-V virtual Switch can be found in the `Hyper-V
Virtual Switch Overview`__.

To quickly enable an interface to be used as a Virtual Interface the
following PowerShell may be used:

.. code-block:: none

   PS C:\> $if = Get-NetIPAddress -IPAddress 192* | Get-NetIPInterface
   PS C:\> New-VMSwitch -NetAdapterName $if.ifAlias -Name YOUR_BRIDGE_NAME -AllowManagementOS $false

.. note::

   It is very important to make sure that when you are using a Hyper-V node
   with only 1 NIC the -AllowManagementOS option is set on ``True``, otherwise
   you will lose connectivity to the Hyper-V node.

__ https://technet.microsoft.com/en-us/library/hh831823.aspx

Enable iSCSI initiator service
------------------------------

To prepare the Hyper-V node to be able to attach to volumes provided by cinder
you must first make sure the Windows iSCSI initiator service is running and
started automatically.

.. code-block:: none

   PS C:\> Set-Service -Name MSiSCSI -StartupType Automatic
   PS C:\> Start-Service MSiSCSI

Configure shared nothing live migration
---------------------------------------

Detailed information on the configuration of live migration can be found in
`this guide`__

The following outlines the steps of shared nothing live migration.

#. The target host ensures that live migration is enabled and properly
   configured in Hyper-V.

#. The target host checks if the image to be migrated requires a base VHD and
   pulls it from the Image service if not already available on the target host.

#. The source host ensures that live migration is enabled and properly
   configured in Hyper-V.

#. The source host initiates a Hyper-V live migration.

#. The source host communicates to the manager the outcome of the operation.

The following three configuration options are needed in order to support
Hyper-V live migration and must be added to your ``nova.conf`` on the Hyper-V
compute node:

* This is needed to support shared nothing Hyper-V live migrations.  It is used
  in ``nova/compute/manager.py``.

  .. code-block:: ini

     instances_shared_storage = False

* This flag is needed to support live migration to hosts with different CPU
  features. This flag is checked during instance creation in order to limit the
  CPU features used by the VM.

  .. code-block:: ini

     limit_cpu_features = True

* This option is used to specify where instances are stored on disk.

  .. code-block:: ini

     instances_path = DRIVELETTER:\PATH\TO\YOUR\INSTANCES

Additional Requirements:

* Hyper-V 2012 R2 or Windows Server 2012 R2 with Hyper-V role enabled

* A Windows domain controller with the Hyper-V compute nodes as domain members

* The instances_path command-line option/flag needs to be the same on all hosts

* The ``openstack-compute`` service deployed with the setup must run with
  domain credentials. You can set the service credentials with:

.. code-block:: bat

   C:\>sc config openstack-compute obj="DOMAIN\username" password="password"

__ https://docs.microsoft.com/en-us/windows-server/virtualization/hyper-v/manage/Use-live-migration-without-Failover-Clustering-to-move-a-virtual-machine

How to setup live migration on Hyper-V
--------------------------------------

To enable 'shared nothing live' migration, run the 3 instructions below on each
Hyper-V host:

.. code-block:: none

   PS C:\> Enable-VMMigration
   PS C:\> Set-VMMigrationNetwork IP_ADDRESS
   PS C:\> Set-VMHost -VirtualMachineMigrationAuthenticationTypeKerberos

.. note::

   Replace the ``IP_ADDRESS`` with the address of the interface which will
   provide live migration.

Additional Reading
------------------

This article clarifies the various live migration options in Hyper-V:

`Hyper-V Live Migration of Yesterday
<https://ariessysadmin.blogspot.ro/2012/04/hyper-v-live-migration-of-windows.html>`_

Install nova-compute using OpenStack Hyper-V installer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In case you want to avoid all the manual setup, you can use Cloudbase
Solutions' installer. You can find it here:

`HyperVNovaCompute_Beta download
<https://www.cloudbase.it/downloads/HyperVNovaCompute_Beta.msi>`_

The tool installs an independent Python environment in order to avoid conflicts
with existing applications, and dynamically generates a ``nova.conf`` file
based on the parameters provided by you.

The tool can also be used for an automated and unattended mode for deployments
on a massive number of servers. More details about how to use the installer and
its features can be found here:

`Cloudbase <https://www.cloudbase.it>`_

.. _windows-requirements:

Requirements
~~~~~~~~~~~~

Python
------

Python 2.7 32bit must be installed as most of the libraries are not working
properly on the 64bit version.

**Setting up Python prerequisites**

#. Download and install Python 2.7 using the MSI installer from here:

   `python-2.7.3.msi download
   <https://www.python.org/ftp/python/2.7.3/python-2.7.3.msi>`_

   .. code-block:: none

      PS C:\> $src = "https://www.python.org/ftp/python/2.7.3/python-2.7.3.msi"
      PS C:\> $dest = "$env:temp\python-2.7.3.msi"
      PS C:\> Invoke-WebRequest -Uri $src -OutFile $dest
      PS C:\> Unblock-File $dest
      PS C:\> Start-Process $dest

#. Make sure that the ``Python`` and ``Python\Scripts`` paths are set up in the
   ``PATH`` environment variable.

   .. code-block:: none

      PS C:\> $oldPath = [System.Environment]::GetEnvironmentVariable("Path")
      PS C:\> $newPath = $oldPath + ";C:\python27\;C:\python27\Scripts\"
      PS C:\> [System.Environment]::SetEnvironmentVariable("Path", $newPath, [System.EnvironmentVariableTarget]::User

Python dependencies
-------------------

The following packages need to be downloaded and manually installed:

``setuptools``
  https://pypi.python.org/packages/2.7/s/setuptools/setuptools-0.6c11.win32-py2.7.exe

``pip``
  https://pip.pypa.io/en/latest/installing/

``PyMySQL``
  http://codegood.com/download/10/

``PyWin32``
  https://sourceforge.net/projects/pywin32/files/pywin32/Build%20217/pywin32-217.win32-py2.7.exe

``Greenlet``
  http://www.lfd.uci.edu/~gohlke/pythonlibs/#greenlet

``PyCryto``
  http://www.voidspace.org.uk/downloads/pycrypto26/pycrypto-2.6.win32-py2.7.exe

The following packages must be installed with pip:

* ``ecdsa``
* ``amqp``
* ``wmi``

.. code-block:: none

   PS C:\> pip install ecdsa
   PS C:\> pip install amqp
   PS C:\> pip install wmi

Other dependencies
------------------

``qemu-img`` is required for some of the image related operations.  You can get
it from here: http://qemu.weilnetz.de/.  You must make sure that the
``qemu-img`` path is set in the PATH environment variable.

Some Python packages need to be compiled, so you may use MinGW or Visual
Studio. You can get MinGW from here: http://sourceforge.net/projects/mingw/.
You must configure which compiler is to be used for this purpose by using the
``distutils.cfg`` file in ``$Python27\Lib\distutils``, which can contain:

.. code-block:: ini

   [build]
   compiler = mingw32

As a last step for setting up MinGW, make sure that the MinGW binaries'
directories are set up in PATH.

Install nova-compute
~~~~~~~~~~~~~~~~~~~~

Download the nova code
----------------------

#. Use Git to download the necessary source code.  The installer to run Git on
   Windows can be downloaded here:

   https://github.com/msysgit/msysgit/releases/download/Git-1.9.2-preview20140411/Git-1.9.2-preview20140411.exe

#. Download the installer. Once the download is complete, run the installer and
   follow the prompts in the installation wizard.  The default should be
   acceptable for the purposes of this guide.

   .. code-block:: none

      PS C:\> $src = "https://github.com/msysgit/msysgit/releases/download/Git-1.9.2-preview20140411/Git-1.9.2-preview20140411.exe"
      PS C:\> $dest = "$env:temp\Git-1.9.2-preview20140411.exe"
      PS C:\> Invoke-WebRequest -Uri $src -OutFile $dest
      PS C:\> Unblock-File $dest
      PS C:\> Start-Process $dest

#. Run the following to clone the nova code.

   .. code-block:: none

      PS C:\> git.exe clone https://opendev.org/openstack/nova

Install nova-compute service
----------------------------

To install ``nova-compute``, run:

.. code-block:: none

   PS C:\> cd c:\nova
   PS C:\> python setup.py install

Configure nova-compute
----------------------

The ``nova.conf`` file must be placed in ``C:\etc\nova`` for running OpenStack
on Hyper-V. Below is a sample ``nova.conf`` for Windows:

.. code-block:: ini

   [DEFAULT]
   auth_strategy = keystone
   image_service = nova.image.glance.GlanceImageService
   compute_driver = nova.virt.hyperv.driver.HyperVDriver
   volume_api_class = nova.volume.cinder.API
   fake_network = true
   instances_path = C:\Program Files (x86)\OpenStack\Instances
   use_cow_images = true
   force_config_drive = false
   injected_network_template = C:\Program Files (x86)\OpenStack\Nova\etc\interfaces.template
   policy_file = C:\Program Files (x86)\OpenStack\Nova\etc\policy.yaml
   mkisofs_cmd = C:\Program Files (x86)\OpenStack\Nova\bin\mkisofs.exe
   allow_resize_to_same_host = true
   running_deleted_instance_action = reap
   running_deleted_instance_poll_interval = 120
   resize_confirm_window = 5
   resume_guests_state_on_host_boot = true
   rpc_response_timeout = 1800
   lock_path = C:\Program Files (x86)\OpenStack\Log\
   rpc_backend = nova.openstack.common.rpc.impl_kombu
   rabbit_host = IP_ADDRESS
   rabbit_port = 5672
   rabbit_userid = guest
   rabbit_password = Passw0rd
   logdir = C:\Program Files (x86)\OpenStack\Log\
   logfile = nova-compute.log
   instance_usage_audit = true
   instance_usage_audit_period = hour

   [glance]
   api_servers = http://IP_ADDRESS:9292

   [neutron]
   endpoint_override = http://IP_ADDRESS:9696
   auth_strategy = keystone
   project_name = service
   username = neutron
   password = Passw0rd
   auth_url = http://IP_ADDRESS:5000/v3
   auth_type = password

   [hyperv]
   vswitch_name = newVSwitch0
   limit_cpu_features = false
   config_drive_inject_password = false
   qemu_img_cmd = C:\Program Files (x86)\OpenStack\Nova\bin\qemu-img.exe
   config_drive_cdrom = true
   dynamic_memory_ratio = 1
   enable_instance_metrics_collection = true

   [rdp]
   enabled = true
   html5_proxy_base_url = https://IP_ADDRESS:4430

Prepare images for use with Hyper-V
-----------------------------------

Hyper-V currently supports only the VHD and VHDX file format for virtual
machine instances. Detailed instructions for installing virtual machines on
Hyper-V can be found here:

`Create Virtual Machines
<http://technet.microsoft.com/en-us/library/cc772480.aspx>`_

Once you have successfully created a virtual machine, you can then upload the
image to `glance` using the `openstack-client`:

.. code-block:: none

   PS C:\> openstack image create --name "VM_IMAGE_NAME" --property hypervisor_type=hyperv --public \
             --container-format bare --disk-format vhd

.. note::

   VHD and VHDX files sizes can be bigger than their maximum internal size,
   as such you need to boot instances using a flavor with a slightly bigger
   disk size than the internal size of the disk file.
   To create VHDs, use the following PowerShell cmdlet:

   .. code-block:: none

      PS C:\> New-VHD DISK_NAME.vhd -SizeBytes VHD_SIZE

Inject interfaces and routes
----------------------------

The ``interfaces.template`` file describes the network interfaces and routes
available on your system and how to activate them. You can specify the location
of the file with the ``injected_network_template`` configuration option in
``/etc/nova/nova.conf``.

.. code-block:: ini

   injected_network_template = PATH_TO_FILE

A default template exists in ``nova/virt/interfaces.template``.

Run Compute with Hyper-V
------------------------

To start the ``nova-compute`` service, run this command from a console in the
Windows server:

.. code-block:: none

   PS C:\> C:\Python27\python.exe c:\Python27\Scripts\nova-compute --config-file c:\etc\nova\nova.conf

Troubleshoot Hyper-V configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* I ran the :command:`nova-manage service list` command from my controller;
  however, I'm not seeing smiley faces for Hyper-V compute nodes, what do I do?

  Verify that you are synchronized with a network time source.  For
  instructions about how to configure NTP on your Hyper-V compute node, see
  :ref:`configure-ntp-windows`.

* How do I restart the compute service?

  .. code-block:: none

     PS C:\> net stop nova-compute && net start nova-compute

* How do I restart the iSCSI initiator service?

  .. code-block:: none

     PS C:\> net stop msiscsi && net start msiscsi

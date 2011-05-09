..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.


The nova-manage command
=======================

Introduction
~~~~~~~~~~~~

The nova-manage command is used to perform many essential functions for
administration and ongoing maintenance of nova, such as user creation,
vpn management, and much more.

The standard pattern for executing a nova-manage command is:
``nova-manage <category> <command> [<args>]``

For example, to obtain a list of all projects:
``nova-manage project list``

Run without arguments to see a list of available command categories:
``nova-manage``

Categories are user, project, role, shell, vpn, and floating. Detailed descriptions are below.

You can also run with a category argument such as user to see a list of all commands in that category:
``nova-manage user``

These sections describe the available categories and arguments for nova-manage.

Nova Db
~~~~~~~

``nova-manage db version``

    Print the current database version.

``nova-manage db sync``

    Sync the database up to the most recent version. This is the standard way to create the db as well.

Nova User
~~~~~~~~~

``nova-manage user admin <username>``

    Create an admin user with the name <username>.

``nova-manage user create <username>``

    Create a normal user with the name <username>.

``nova-manage user delete <username>``

    Delete the user with the name <username>.

``nova-manage user exports <username>``

    Outputs a list of access key and secret keys for user to the screen

``nova-manage user list``

    Outputs a list of all the user names to the screen.

``nova-manage user modify <accesskey> <secretkey> <admin?T/F>``

    Updates the indicated user keys, indicating with T or F if the user is an admin user. Leave any argument blank if you do not want to update it.

Nova Project
~~~~~~~~~~~~

``nova-manage project add <projectname> <username>``

    Add a nova project with the name <projectname> to the database that will be administered by the named user.

``nova-manage project create <projectname> <projectmanager>``

    Create a new nova project with the name <projectname> (you still need to do nova-manage project add <projectname> to add it to the database). The <projectmanager> username is the administrator of the project.

``nova-manage project delete <projectname>``

    Delete a nova project with the name <projectname>.

``nova-manage project environment <projectname> <username>``

    Exports environment variables for the named project to a file named novarc.

``nova-manage project list``

    Outputs a list of all the projects to the screen.

``nova-manage project quota <projectname>``

    Outputs the size and specs of the project's instances including gigabytes, instances, floating IPs, volumes, and cores.

``nova-manage project remove <projectname>``

    Deletes the project with the name <projectname>.

``nova-manage project zipfile <projectname> <username> <directory for credentials>``

    Compresses all related files for a created project into a named zip file such as nova.zip.

Nova Role
~~~~~~~~~

nova-manage role <action> [<argument>]
``nova-manage role add <username> <rolename> <(optional) projectname>``

    Add a user to either a global or project-based role with the indicated <rolename> assigned to the named user. Role names can be one of the following five roles: admin, itsec, projectmanager, netadmin, developer. If you add the project name as the last argument then the role is assigned just for that project, otherwise the user is assigned the named role for all projects.

``nova-manage role has <username> <projectname>``
    Checks the user or project and responds with True if the user has a global role with a particular project.

``nova-manage role remove <username> <rolename>``
    Remove the indicated role from the user.

Nova Shell
~~~~~~~~~~

``nova-manage shell bpython``

    Starts a new bpython shell.

``nova-manage shell ipython``

    Starts a new ipython shell.

``nova-manage shell python``

    Starts a new python shell.

``nova-manage shell run``

    Starts a new shell using python.

``nova-manage shell script <path/scriptname>``

    Runs the named script from the specified path with flags set.

Nova VPN
~~~~~~~~

``nova-manage vpn list``

    Displays a list of projects, their IP prot numbers, and what state they're in.

``nova-manage vpn run <projectname>``

    Starts the VPN for the named project.

``nova-manage vpn spawn``

    Runs all VPNs.

Nova Floating IPs
~~~~~~~~~~~~~~~~~

``nova-manage floating create <host> <ip_range>``

    Creates floating IP addresses for the named host by the given range.

``nova-manage floating delete <ip_range>``

    Deletes floating IP addresses in the range given.

``nova-manage floating list``

    Displays a list of all floating IP addresses.

Nova Images
~~~~~~~~~~~

``nova-manage image image_register <path> <owner>``

    Registers an image with the image service.

``nova-manage image kernel_register <path> <owner>``

    Registers a kernel with the image service.

``nova-manage image ramdisk_register <path> <owner>``

    Registers a ramdisk with the image service.

``nova-manage image all_register <image_path> <kernel_path> <ramdisk_path> <owner>``

    Registers an image kernel and ramdisk with the image service.

``nova-manage image convert <directory>``

    Converts all images in directory from the old (Bexar) format to the new format.

Concept: Flags
--------------

python-gflags


Concept: Plugins
----------------

* Managers/Drivers: utils.import_object from string flag
* virt/connections: conditional loading from string flag
* db: LazyPluggable via string flag
* auth_manager: utils.import_class based on string flag
* Volumes: moving to pluggable driver instead of manager
* Network: pluggable managers
* Compute: same driver used, but pluggable at connection


Concept: IPC/RPC
----------------

Rabbit is the main messaging queue, used for all communication between Nova components and it also does the remote procedure calls and inter-process communication. 


Concept: Fakes
--------------

* auth
* ldap


Concept: Scheduler
------------------

* simple
* random


Concept: Security Groups
------------------------

Security groups


Concept: Certificate Authority
------------------------------

Nova does a small amount of certificate management.  These certificates are used for :ref:`project vpns <../cloudpipe>` and decrypting bundled images.


Concept: Images
---------------

* launching
* bundling

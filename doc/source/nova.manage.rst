..
      Copyright 2010 United States Government as represented by the
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


nova-manage
===========

Introduction
~~~~~~~~~~~~

The nova-manage command is used to perform many essential functions for
administration and ongoing maintenance of nova, such as user creation,
vpn management, and much more.

The standard pattern for executing a nova-manage command is:

``nova-manage <category> <command> [<args>]``

For example, to obtain a list of all projects:

``nova-manage project list``

You can run without arguments to see a list of available command categories:

``nova-manage``

You can run with a category argument to see a list of all commands in that
category:

``nova-manage user``

User Maintenance
~~~~~~~~~~~~~~~~

Users, including admins, are created through the ``user`` commands.

* user admin: creates a new admin and prints exports
    * arguments: name [access] [secret]
* user create: creates a new user and prints exports
    * arguments: name [access] [secret]
* user delete: deletes an existing user
    * arguments: name
* user exports: prints access and secrets for user in export format
    * arguments: name
* user list: lists all users
    * arguments: none
* user modify: update a users keys & admin flag
    *  arguments: accesskey secretkey admin
    *  leave any field blank to ignore it, admin should be 'T', 'F', or blank

Project Maintenance
~~~~~~~~~~~~~~~~~~~

* project add: Adds user to project
    * arguments: project user
* project create: Creates a new project
    * arguments: name project_manager [description]
* project delete: Deletes an existing project
    * arguments: project_id
* project environment: Exports environment variables to an sourcable file
    * arguments: project_id user_id [filename='novarc]
* project list: lists all projects
    * arguments: none
* project quota: Set or display quotas for project
    * arguments: project_id [key] [value]
* project remove: Removes user from project
    * arguments: project user
* project scrub: Deletes data associated with project
    * arguments: project
* project zipfile: Exports credentials for project to a zip file
    * arguments: project_id user_id [filename='nova.zip]

User Role Management
~~~~~~~~~~~~~~~~~~~~

* role add: adds role to user
    * if project is specified, adds project specific role
    * arguments: user, role [project]
* role has: checks to see if user has role
    * if project is specified, returns True if user has
      the global role and the project role
    * arguments: user, role [project]
* role remove: removes role from user
    * if project is specified, removes project specific role
    * arguments: user, role [project]


Nova Shell
~~~~~~~~~~

* shell bpython
    * start a new bpython shell
* shell ipython
    * start a new ipython shell
* shell python
    * start a new python shell
* shell run
    * ???
* shell script: Runs the script from the specifed path with flags set properly.
    * arguments: path

VPN Management
~~~~~~~~~~~~~~

* vpn list: Print a listing of the VPNs for all projects.
    * arguments: none
* vpn run: Start the VPN for a given project.
    * arguments: project
* vpn spawn: Run all VPNs.
    * arguments: none


Floating IP Management
~~~~~~~~~~~~~~~~~~~~~~

* floating create: Creates floating ips for host by range
    * arguments: host ip_range
* floating delete: Deletes floating ips by range
    * arguments: range
* floating list: Prints a listing of all floating ips
    * arguments: none

Network Management
~~~~~~~~~~~~~~~~~~

* network create: Creates fixed ips for host by range
    * arguments: [fixed_range=FLAG], [num_networks=FLAG],
                 [network_size=FLAG], [vlan_start=FLAG],
                 [vpn_start=FLAG]


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

Rabbit!


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

Nova does a small amount of certificate management.  These certificates are used for :ref:`project vpns <cloudpipe>` and decrypting bundled images.


Concept: Images
---------------

* launching
* bundling

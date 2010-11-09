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

Administration Guide
====================

How to deploy, monitor, and debug Nova.

Users and Access Keys
---------------------

Access to the ec2 api is controlled by an access and secret key.  The user's access key needs to be included in the request, and the request must be signed with the secret key.  Upon receipt of api requests, nova will verify the signature and execute commands on behalf of the user.

In order to begin using nova, you will need a to create a user.  This can be easily accomplished using the user create or user admin commands in nova-manage. `user create` will create a regular user, whereas `user admin` will create an admin user. The syntax of the command is nova-manage user create username [access] [secret]. For example::
  nova-manage user create john my-access-key a-super-secret-key

If you do not specify an access or secret key, a random uuid will be created automatically.

Projects
--------

Although the original ec2 api only supports users, nova adds the concept of projects. A user can specify which project he or she wishes to use by appending `:project_id` to his or her access key.  If no project is specified in the api request, nova will attempt to use a project with the same id as the user.

The api will return NotAuthorized if a normal user attempts to make requests for a project that he or she is not a member of.  Note that admins or users with special admin roles skip this check and can make requests for any project.

To create a project, use the `project create` command of nova-manage. The syntax is nova-manage project create projectname manager_id [description] You must specify a projectname and a manager_id. For example::
  nova-manage project create john_project john "This is a sample project"

You can add and remove users from projects with `project add` and `project remove`.

Roles
-----

Roles control the api actions that a user is allowed to perform.  For example, a user cannot allocate a public ip without the `netadmin` role. It is important to remember that a users de facto permissions in a project is the intersection of user (global) roles and project (local) roles.  So for john to have netadmin permissions in his project, he needs to separate roles specified.  You can add roles with `role add`.  The syntax is nova-manage role add user_id role [project_id]. Let's give john the netadmin role for his project::
  nova-manage role add john netadmin
  nova-manage role add john netadmin john_project

Credentials
-----------

Nova can generate a handy set of credentials for a user.  These credentials include a CA for bundling images and a file for setting environment variables to be used by euca2ools.  If you don't need to bundle images, just the environment script is required.  You can export one with the `project environment` command.  The syntax of the command is nova-manage project environment project_id user_id [filename]. If you don't specify a filename, it will be exported as novarc.  After generating the file, you can simply source it in bash to add the variables to your environment::
  nova-manage project environment john_project john
  . novarc

If you do need to bundle images, you will need to get all of the credentials using `project zipfile`. Note that zipfile will give you an error message if networks haven't been created yet.  Otherwise zipfile has the same syntax as environment, only the default file name is nova.zip.  Example usage::
  nova-manage project zipfile john_project john
  unzip nova.zip
  . novarc

Keypairs
--------

Images can be shared by many users, so it is dangerous to put passwords into the images.  Nova therefore supports injecting ssh keys into instances before they are booted.  This allows a user to login to the instances that he or she creates securely.  Generally the first thing that a user does when using the system is create a keypair.  Nova generates a public and private key pair, and sends the private key to the user.  The public key is stored so that it can be injected into instances.

Keypairs are created through the api.  They can be created on the command line using the euca2ools script euca-add-keypair.  Refer to the man page for the available options. Example usage::
  euca-add-keypair test > test.pem
  chmod 600 test.pem
  euca-run-instances -k test -t m1.tiny ami-tiny
  # wait for boot
  ssh -i test.pem root@ip.of.instance

Contents
--------

.. toctree::
   :maxdepth: 1

   quickstart
   getting.started
   binaries
   multi.node.install
   nova.manage
   flags
   monitoring

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

Managing Instances
==================

Keypairs
--------

Images can be shared by many users, so it is dangerous to put passwords into the images.  Nova therefore supports injecting ssh keys into instances before they are booted.  This allows a user to login to the instances that he or she creates securely.  Generally the first thing that a user does when using the system is create a keypair.  Nova generates a public and private key pair, and sends the private key to the user.  The public key is stored so that it can be injected into instances.

Keypairs are created through the api.  They can be created on the command line using the euca2ools script euca-add-keypair.  Refer to the man page for the available options. Example usage::

  euca-add-keypair test > test.pem
  chmod 600 test.pem
  euca-run-instances -k test -t m1.tiny ami-tiny
  # wait for boot
  ssh -i test.pem root@ip.of.instance


Basic Management
----------------
Instance management can be accomplished with euca commands:


To run an instance:

::

    euca-run-instances


To terminate an instance:

::

    euca-terminate-instances

To reboot an instance:

::

    euca-reboot-instances

See the euca2ools documentation for more information

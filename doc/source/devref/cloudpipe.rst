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


.. _cloudpipe:

Cloudpipe -- Per Project Vpns
=============================

Cloudpipe is a method for connecting end users to their project instances in vlan mode.


Overview
--------

The support code for cloudpipe implements admin commands (via nova-manage) to automatically create a vm for a project that allows users to vpn into the private network of their project. Access to this vpn is provided through a public port on the network host for the project.  This allows users to have free access to the virtual machines in their project without exposing those machines to the public internet.


Cloudpipe Image
---------------

The cloudpipe image is basically just a linux instance with openvpn installed.  It needs a simple script to grab user data from the metadata server, b64 decode it into a zip file, and run the autorun.sh script from inside the zip.  The autorun script will configure and run openvpn to run using the data from nova.

It is also useful to have a cron script that will periodically redownload the metadata and copy the new crl.  This will keep revoked users from connecting and will disconnect any users that are connected with revoked certificates when their connection is renegotiated (every hour).


Creating a Cloudpipe Image
--------------------------

Making a cloudpipe image is relatively easy.

# install openvpn on a base ubuntu image.
# set up a server.conf.template in /etc/openvpn/

.. literalinclude:: server.conf.template
   :language: bash
   :linenos:

# set up.sh in /etc/openvpn/

.. literalinclude:: up.sh
   :language: bash
   :linenos:

# set down.sh in /etc/openvpn/

.. literalinclude:: down.sh
   :language: bash
   :linenos:

# download and run the payload on boot from /etc/rc.local

.. literalinclude:: rc.local
   :language: bash
   :linenos:

# setup /etc/network/interfaces

.. literalinclude:: interfaces
   :language: bash
   :linenos:

# register the image and set the image id in your flagfile::

    --vpn_image_id=ami-xxxxxxxx

# you should set a few other flags to make vpns work properly::

    --use_project_ca
    --cnt_vpn_clients=5


Cloudpipe Launch
----------------

When you use nova-manage to launch a cloudpipe for a user, it goes through the following process:

#. creates a keypair called <project_id>-vpn and saves it in the keys directory
#. creates a security group <project_id>-vpn and opens up 1194 and icmp
#. creates a cert and private key for the vpn instance and saves it in the CA/projects/<project_id>/ directory
#. zips up the info and puts it b64 encoded as user data
#. launches an m1.tiny instance with the above settings using the flag-specified vpn image


Vpn Access
----------

In vlan networking mode, the second ip in each private network is reserved for the cloudpipe instance.  This gives a consistent ip to the instance so that nova-network can create forwarding rules for access from the outside world.  The network for each project is given a specific high-numbered port on the public ip of the network host.  This port is automatically forwarded to 1194 on the vpn instance.

If specific high numbered ports do not work for your users, you can always allocate and associate a public ip to the instance, and then change the vpn_public_ip and vpn_public_port in the database.  This will be turned into a nova-manage command or a flag soon.


Certificates and Revocation
---------------------------

If the use_project_ca flag is set (required to for cloudpipes to work securely), then each project has its own ca.  This ca is used to sign the certificate for the vpn, and is also passed to the user for bundling images.  When a certificate is revoked using nova-manage, a new Certificate Revocation List (crl) is generated.  As long as cloudpipe has an updated crl, it will block revoked users from connecting to the vpn.

The userdata for cloudpipe isn't currently updated when certs are revoked, so it is necessary to restart the cloudpipe instance if a user's credentials are revoked.


Restarting Cloudpipe VPN
------------------------

You can reboot a cloudpipe vpn through the api if something goes wrong (using euca-reboot-instances for example), but if you generate a new crl, you will have to terminate it and start it again using nova-manage vpn run.  The cloudpipe instance always gets the first ip in the subnet and it can take up to 10 minutes for the ip to be recovered.  If you try to start the new vpn instance too soon, the instance will fail to start because of a NoMoreAddresses error.  If you can't wait 10 minutes, you can manually update the ip with something like the following (use the right ip for the project)::

    euca-terminate-instances <instance_id>
    mysql nova -e "update fixed_ips set allocated=0, leased=0, instance_id=NULL where fixed_ip='10.0.0.2'"

You also will need to terminate the dnsmasq running for the user (make sure you use the right pid file)::

    sudo kill `cat /var/lib/nova/br100.pid`

Now you should be able to re-run the vpn::

    nova-manage vpn run <project_id>


Logging into Cloudpipe VPN
--------------------------

The keypair that was used to launch the cloudpipe instance should be in the keys/<project_id> folder.  You can use this key to log into the cloudpipe instance for debugging purposes.


The :mod:`nova.cloudpipe.pipelib` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.cloudpipe.pipelib
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`nova.api.cloudpipe` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.cloudpipe
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`nova.crypto` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.crypto
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


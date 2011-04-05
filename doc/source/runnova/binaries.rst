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

.. _binaries:

Nova Daemons
=============

The configuration of these binaries relies on "flagfiles" using the google
gflags package::

   $ nova-xxxxx --flagfile flagfile

The binaries can all run on the same machine or be spread out amongst multiple boxes in a large deployment.

nova-api
--------

Nova api receives xml requests and sends them to the rest of the system.  It is a wsgi app that routes and authenticate requests.  It supports the ec2 and openstack apis.

nova-objectstore
----------------

Nova objectstore is an ultra simple file-based storage system for images that replicates most of the S3 Api.  It will soon be replaced with Glance (http://glance.openstack.org) and a simple image manager. 

nova-compute
------------

Nova compute is responsible for managing virtual machines.  It loads a Service object which exposes the public methods on ComputeManager via rpc.

nova-volume
-----------

Nova volume is responsible for managing attachable block storage devices. It loads a Service object which exposes the public methods on VolumeManager via rpc.

nova-network
------------

Nova network is responsible for managing floating and fixed ips, dhcp, bridging and vlans.  It loads a Service object which exposes the public methods on one of the subclasses of NetworkManager.  Different networking strategies are as simple as changing the network_manager flag::

   $ nova-network --network_manager=nova.network.manager.FlatManager

IMPORTANT: Make sure that you also set the network_manager on nova-api and nova_compute, since make some calls to network manager in process instead of through rpc.  More information on the interactions between services, managers, and drivers can be found :ref:`here <service_manager_driver>`

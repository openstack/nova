..
      Copyright 2010-2011 OpenStack LLC

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

Object Model
============

.. graphviz::

   digraph foo {
     graph [rankdir="LR"];     node [fontsize=9 shape=box];
     Instances -> "Public IPs"      [arrowhead=crow];
     Instances -> "Security Groups" [arrowhead=crow];
     Users     -> Projects          [arrowhead=crow arrowtail=crow dir=both];
     Users     -> Keys              [arrowhead=crow];
     Instances -> Volumes           [arrowhead=crow];
     Projects  -> "Public IPs"      [arrowhead=crow];
     Projects  -> Instances         [arrowhead=crow];
     Projects  -> Volumes           [arrowhead=crow];
     Projects  -> Images            [arrowhead=crow];
     Images    -> Instances         [arrowhead=crow];
     Projects  -> "Security Groups" [arrowhead=crow];
     "Security Groups" -> Rules     [arrowhead=crow];
   }


Users
-----

Each Nova User is authorized based on their access key and secret key, assigned per-user. Read more at :doc:`/runnova/managing.users`.

Projects
--------

For Nova, access to images is based on the project. Read more at :doc:`/runnova/managing.projects`.

Images
------

Images are binary files that run the operating system. Read more at :doc:`/runnova/managing.images`.

Instances
---------

Instances are running virtual servers. Read more at :doc:`/runnova/managing.instances`.

Volumes
-------

Volumes offer extra block level storage to instances. Read more at `Managing Volumes <http://docs.openstack.org/openstack-compute/admin/content/ch05s07.html>`_.

Security Groups
---------------

In Nova, a security group is a named collection of network access rules, like firewall policies. Read more at `Security Groups <http://nova.openstack.org/nova.concepts.html#concept-security-groups>`_.

VLANs
-----

VLAN is the default network mode for Nova. Read more at :doc:`/runnova/network.vlan`.

IP Addresses
------------
Nova enables floating IP management.
..
      Copyright 2010 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration. 
      All Rights Reserved.

      Copyright 2010 Anso Labs, LLC

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

nova System Architecture
========================

Nova is built on a shared-nothing, messaging-based architecture. All of the major nova components can be run on multiple servers. This means that most component to component communication must go via message queue. In order to avoid blocking each component while waiting for a response, we use deferred objects, with a callback that gets triggered when a response is received.

In order to achieve shared-nothing with multiple copies of the same component (especially when the component is an API server that needs to reply with state information in a timely fashion), we need to keep all of our system state in a distributed data system. Updates to system state are written into this system, using atomic transactions when necessary. Requests for state are read out of this system. In limited cases, these read calls are memoized within controllers for short periods of time. (Such a limited case would be, for instance, the current list of system users.)


Components
----------

Below you will find a helpful explanation.

::

              [ User Manager ] ---- ( LDAP )
                        |  
                        |                / [ Storage ] - ( ATAoE )
  [ API server ] -> [ Cloud ]  < AMQP >   
                        |                \ [ Nodes ]   - ( libvirt/kvm )
                    < HTTP >
                        |
                     [ S3  ]


* API: receives http requests from boto, converts commands to/from API format, and sending requests to cloud controller
* Cloud Controller: global state of system, talks to ldap, s3, and node/storage workers through a queue
* Nodes: worker that spawns instances
* S3: tornado based http/s3 server
* User Manager: create/manage users, which are stored in ldap
* Network Controller: allocate and deallocate IPs and VLANs

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

Managing Networks
=================

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


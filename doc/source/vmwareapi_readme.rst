..

      Copyright (c) 2010 Citrix Systems, Inc.
      Copyright 2010 OpenStack LLC.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

VMware ESX/ESXi Server Support for OpenStack Compute
====================================================

Introduction
------------
A module named 'vmwareapi' is added to 'nova.virt' to add support of VMware ESX/ESXi hypervisor to OpenStack compute (Nova). Nova may now use VMware vSphere as a compute provider. 

The basic requirement is to support VMware vSphere 4.1 as a compute provider within Nova. As the deployment architecture, support both ESX and ESXi. VM storage is restricted to VMFS volumes on local drives. vCenter is not required by the current design, and is not currently supported. Instead, Nova Compute talks directly to ESX/ESXi.

The 'vmwareapi' module is integrated with Glance, so that VM images can be streamed from there for boot on ESXi using Glance server for image storage & retrieval.

Currently supports Nova's flat networking model (Flat Manager).

.. image:: images/vmwareapi_blockdiagram.jpg


System Requirements
-------------------
Following software components are required for building the cloud using OpenStack on top of ESX/ESXi Server(s): 

* OpenStack (Bexar Release)
* Glance Image service (Bexar Release) 
* VMware ESX v4.1 or VMware ESXi(licensed) v4.1

VMware ESX Requirements
-----------------------
* ESX credentials with administration/root privileges
* Single local hard disk at the ESX host
* An ESX Virtual Machine Port Group (For Flat Networking)
* An ESX physical network adapter (For VLAN networking)
* Need to enable "vSphere Web Access" in Configuration->Security Profile->Firewall   

Python dependencies 
-------------------
* suds-0.4

* Installation procedure on Ubuntu/Debian

::

 sudo apt-get install python-setuptools
 wget https://fedorahosted.org/releases/s/u/suds/python-suds-0.4.tar.gz
 tar -zxvf python-suds-0.4.tar.gz
 cd python-suds-0.4
 sudo python setup.py install

Configuration flags required for nova-compute 
---------------------------------------------
::
 
  --connection_type=vmwareapi 
  --vmwareapi_host_ip=<VMware ESX Host IP> 
  --vmwareapi_host_username=<VMware ESX Username>
  --vmwareapi_host_password=<VMware ESX Password>
  --network_driver=nova.network.vmwareapi_net [Optional, only for VLAN Networking]
  --vlan_interface=<Physical ethernet adapter name in VMware ESX host for vlan networking E.g vmnic0> [Optional, only for VLAN Networking]
  

Configuration flags required for nova-network 
---------------------------------------------
::
 
  --network_manager=nova.network.manager.FlatManager [or nova.network.manager.VlanManager]
  --flat_network_bridge=<ESX Virtual Machine Port Group> [Optional, only for Flat Networking]


Configuration flags required for nova-console
---------------------------------------------
::
 
  --console_manager=nova.console.vmrc_manager.ConsoleVMRCManager
  --console_driver=nova.console.vmrc.VMRCSessionConsole [Optional, only for OTP (One time Passwords) as against host credentials]

   
Other flags
-----------
::

  --image_service=nova.image.glance.GlanceImageService
  --glance_host=<Glance Host>
  --vmwareapi_wsdl_loc=<http://<WEB SERVER>/vimService.wsdl>

Note:- Due to a faulty wsdl being shipped with ESX vSphere 4.1 we need a working wsdl which can to be mounted on any webserver. Follow the below steps to download the SDK,

* Go to http://www.vmware.com/support/developer/vc-sdk/
* Go to section VMware vSphere Web Services SDK 4.0
* Click "Downloads"
* Enter VMware credentials when prompted for download
* Unzip the downloaded file vi-sdk-4.0.0-xxx.zip
* Go to SDK->WSDL->vim25 & host the files "vimService.wsdl" and "vim.wsdl" in a WEB SERVER
* Set the flag "--vmwareapi_wsdl_loc" with url, "http://<WEB SERVER>/vimService.wsdl"

FAQ 
---

1. What type of disk images are supported?

* Only VMware VMDK's are currently supported and of that support is available only for thick disks, thin provisioned disks are not supported.


2. How is IP address information injected into the guest?

* IP address information is injected through 'machine.id' vmx parameter (equivalent to XenStore in XenServer). This information can be retrived inside the guest using VMware tools.

    
3. What is the guest tool?

* The guest tool is a small python script that should be run either as a service or added to system startup. This script configures networking on the guest.


4. What type of consoles are supported?

* VMware VMRC based consoles are supported. There are 2 options for credentials one is OTP (Secure but creates multiple session entries in DB for each OpenStack console create request.) & other is host based credentials (It may not be secure as ESX credentials are transmitted as clear text).


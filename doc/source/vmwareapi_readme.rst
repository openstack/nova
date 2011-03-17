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

Currently supports Nova's flat networking model (Flat Manager) & VLAN networking model.

.. image:: images/vmwareapi_blockdiagram.jpg


System Requirements
-------------------
Following software components are required for building the cloud using OpenStack on top of ESX/ESXi Server(s): 

* OpenStack
* Glance Image service
* VMware ESX v4.1 or VMware ESXi(licensed) v4.1

VMware ESX Requirements
-----------------------
* ESX credentials with administration/root privileges
* Single local hard disk at the ESX host
* An ESX Virtual Machine Port Group (For Flat Networking)
* An ESX physical network adapter (For VLAN networking)
* Need to enable "vSphere Web Access" in  "vSphere client" UI at Configuration->Security Profile->Firewall   

Python dependencies 
-------------------
* suds-0.4

* Installation procedure on Ubuntu/Debian

::

 easy_install suds==0.4


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


VLAN Network Manager
--------------------
VLAN network support is added through a custom network driver in the nova-compute node i.e "nova.network.vmwareapi_net" and it uses a Physical ethernet adapter on the VMware ESX/ESXi host for VLAN Networking (the name of the ethernet adapter is specified as vlan_interface flag in the nova-compute configuration flag) in the nova-compute node.

Using the physical adapter name the associated Virtual Switch will be determined. In VMware ESX there can be only one Virtual Switch associated with a Physical adapter.

When VM Spawn request is issued with a VLAN ID the work flow looks like,

1. Check that a Physical adapter with the given name exists. If no, throw an error.If yes, goto next step.

2. Check if a Virtual Switch is associated with the Physical ethernet adapter with vlan interface name. If no, throw an error. If yes, goto next step.

3. Check if a port group with the network bridge name exists. If no, create a port group in the Virtual switch with the give name and VLAN id and goto step 6. If yes, goto next step.

4. Check if the port group is associated with the Virtual Switch. If no, throw an error. If yes, goto next step.

5. Check if the port group is associated with the given VLAN Id. If no, throw an error. If yes, goto next step.

6. Spawn the VM using this Port Group as the Network Name for the VM.


Guest console Support
---------------------
| VMware VMRC console is a built-in console method providing graphical control of the VM remotely.
|
|        VMRC Console types supported:
|            # Host based credentials
|                Not secure (Sends ESX admin credentials in clear text)
|
|            # OTP (One time passwords)
|                Secure but creates multiple session entries in DB for each OpenStack console create request.
|                Console sessions created is can be used only once.
|
|        Install browser based VMware ESX plugins/activex on the client machine to connect
|
|            Windows:-
|                Internet Explorer:
|                    https://<VMware ESX Host>/ui/plugin/vmware-vmrc-win32-x86.exe
|
|                Mozilla Firefox:
|                    https://<VMware ESX Host>/ui/plugin/vmware-vmrc-win32-x86.xpi
|
|            Linux:-
|                Mozilla Firefox
|                    32-Bit Linux:
|                        https://<VMware ESX Host>/ui/plugin/vmware-vmrc-linux-x86.xpi
|
|                    64-Bit Linux:
|                        https://<VMware ESX Host>/ui/plugin/vmware-vmrc-linux-x64.xpi
|
|        OpenStack Console Details:
|            console_type = vmrc+credentials | vmrc+session
|            host = <VMware ESX Host>
|            port = <VMware ESX Port>
|            password = {'vm_id': <VMware VM ID>,'username':<VMware ESX Username>, 'password':<VMware ESX Password>} //base64 + json encoded
|
|        Instantiate the plugin/activex object
|            # In Internet Explorer
|                <object id='vmrc' classid='CLSID:B94C2238-346E-4C5E-9B36-8CC627F35574'>
|                </object>
|
|            # Mozilla Firefox and other browsers
|                <object id='vmrc' type='application/x-vmware-vmrc;version=2.5.0.0'>
|                </object>
|
|        Open vmrc connection
|            # Host based credentials [type=vmrc+credentials]
|                <script type="text/javascript">
|                    var MODE_WINDOW = 2;
|                    var vmrc = document.getElementById('vmrc');
|                    vmrc.connect(<VMware ESX Host> + ':' + <VMware ESX Port>, <VMware ESX Username>, <VMware ESX Password>, '', <VMware VM ID>, MODE_WINDOW);
|                </script>
|
|            # OTP (One time passwords) [type=vmrc+session]
|                <script type="text/javascript">
|                    var MODE_WINDOW = 2;
|                    var vmrc = document.getElementById('vmrc');
|                    vmrc.connectWithSession(<VMware ESX Host> + ':' + <VMware ESX Port>, <VMware VM ID>, <VMware ESX Password>, MODE_WINDOW);
|                </script>


Assumptions
-----------
1. The VMware images uploaded to the image repositories have VMware Tools installed.


FAQ 
---

1. What type of disk images are supported?

* Only VMware VMDK's are currently supported and of that support is available only for thick disks, thin provisioned disks are not supported.


2. How is IP address information injected into the guest?

* IP address information is injected through 'machine.id' vmx parameter (equivalent to XenStore in XenServer). This information can be retrived inside the guest using VMware tools.

    
3. What is the guest tool?

* The guest tool is a small python script that should be run either as a service or added to system startup. This script configures networking on the guest. The guest tool is available at tools/esx/guest_tool.py


4. What type of consoles are supported?

* VMware VMRC based consoles are supported. There are 2 options for credentials one is OTP (Secure but creates multiple session entries in DB for each OpenStack console create request.) & other is host based credentials (It may not be secure as ESX credentials are transmitted as clear text).

5. What does 'Vim' refer to as far as vmwareapi module is concerned?

* Vim refers to VMware Virtual Infrastructure Methodology. This is not to be confused with "VIM" editor.


..
      Copyright 2011 Ken Pepple

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Managing Instance Types and Flavors
===================================

You can manage instance types and instance flavors using the nova-manage command-line interface coupled with the instance_type subcommand for nova-manage. 

What are Instance Types or Flavors ?
------------------------------------

Instance types describe the compute, memory and storage capacity of nova computing instances. In layman terms, this is the size (in terms of vCPUs, RAM, etc.) of the virtual server that you will be launching. In the EC2 API, these are called by names such as "m1.large" or "m1.tiny", while the OpenStack API terms these "flavors" with names like "512 MB Server". 

In Nova, "flavor" and "instance type" are equivalent terms. When you create an EC2 instance type, you are also creating a OpenStack API flavor. To reduce repetition, for the rest of this document I will refer to these as instance types.

Instance types can be in either the active or inactive state:
  * Active instance types are available to be used for launching instances
  * Inactive instance types are not available for launching instances

In the current (Cactus) version of nova, instance types can only be created by the nova administrator through the nova-manage command. Future versions of nova (in concert with the OpenStack API or EC2 API), may expose this functionality directly to users.

Basic Management
----------------

Instance types / flavor are managed through the nova-manage binary with 
the "instance_type" command and an appropriate subcommand. Note that you can also use 
the "flavor" command as a synonym for "instance_types".

To see all currently active instance types, use the list subcommand::

    # nova-manage instance_type list
    m1.medium: Memory: 4096MB, VCPUS: 2, Storage: 40GB, FlavorID: 3, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.large: Memory: 8192MB, VCPUS: 4, Storage: 80GB, FlavorID: 4, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.tiny: Memory: 512MB, VCPUS: 1, Storage: 0GB, FlavorID: 1, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.xlarge: Memory: 16384MB, VCPUS: 8, Storage: 160GB, FlavorID: 5, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.small: Memory: 2048MB, VCPUS: 1, Storage: 20GB, FlavorID: 2, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB

By default, the list subcommand only shows active instance types. To see all instance types (inactive and active), use the list subcommand with the "--all" flag::

    # nova-manage instance_type list --all
    m1.medium: Memory: 4096MB, VCPUS: 2, Storage: 40GB, FlavorID: 3, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.large: Memory: 8192MB, VCPUS: 4, Storage: 80GB, FlavorID: 4, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.tiny: Memory: 512MB, VCPUS: 1, Storage: 0GB, FlavorID: 1, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.xlarge: Memory: 16384MB, VCPUS: 8, Storage: 160GB, FlavorID: 5, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.small: Memory: 2048MB, VCPUS: 1, Storage: 20GB, FlavorID: 2, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB
    m1.deleted: Memory: 2048MB, VCPUS: 1, Storage: 20GB, FlavorID: 2, Swap: 0GB, RXTX Quota: 0GB, RXTX Cap: 0MB, inactive

To create an instance type, use the "create" subcommand with the following positional arguments:
 * memory (expressed in megabytes) 
 * vcpu(s) (integer)
 * local storage (expressed in gigabytes)
 * flavorid (unique integer)
 * swap space (expressed in megabytes, defaults to zero, optional)
 * RXTX quotas (expressed in gigabytes, defaults to zero, optional)
 * RXTX cap (expressed in gigabytes, defaults to zero, optional)

The following example creates an instance type named "m1.xxlarge"::

    # nova-manage instance_type create m1.xxlarge 32768 16 320 0 0 0
    m1.xxlarge created

To delete an instance type, use the "delete" subcommand and specify the name::

    # nova-manage instance_type delete m1.xxlarge
    m1.xxlarge deleted

Please note that the "delete" command only marks the instance type as 
inactive in the database; it does not actually remove the instance type. This is done
to preserve the instance type definition for long running instances (which may not 
terminate for months or years). If you are sure that you want to delete this instance 
type from the database, pass the "--purge" flag after the name::

    # nova-manage instance_type delete m1.xxlarge --purge
    m1.xxlarge purged

..
      Copyright 2011 OpenStack LLC 
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

      Source for illustrations in doc/source/image_src/zone_distsched_illustrations.odp
      (OpenOffice Impress format) Illustrations are "exported" to png and then scaled
      to 400x300 or 640x480 as needed and placed in the doc/source/images directory.
      
Distributed Scheduler
=====================

The Scheduler is akin to a Dating Service. Requests for the creation of new instances come in and the most applicable Compute nodes are selected from a large pool of potential candidates. In a small deployment we may be happy with the currently available Chance Scheduler which randomly selects a Host from the available pool. Or if you need something a little more fancy you may want to use the Availability Zone Scheduler, which selects Compute hosts from a logical partitioning of available hosts (within a single Zone). 

    .. image:: /images/dating_service.png 

But for larger deployments a more complex scheduling algorithm is required. Additionally, if you are using Zones in your Nova setup, you'll need a scheduler that understand how to pass instance requests from Zone to Zone.

This is the purpose of the Distributed Scheduler (DS). The DS utilizes the Capabilities of a Zone and its component services to make informed decisions on where a new instance should be created. When making this decision it consults not only all the Compute nodes in the current Zone, but the Compute nodes in each Child Zone. This continues recursively until the ideal host is found.

So, how does this all work?

This document will explain the strategy employed by the `BaseScheduler`, which is the base for all schedulers designed to work across zones, and its derivations. You should read the :doc:`devguide/zones` documentation before reading this.

    .. image:: /images/base_scheduler.png 

Costs & Weights
---------------
When deciding where to place an Instance, we compare a Weighted Cost for each Host. The Weighting, currently, is just the sum of each Cost. Costs are nothing more than integers from `0 - max_int`. Costs are computed by looking at the various Capabilities of the Host relative to the specs of the Instance being asked for. Trying to put a plain vanilla instance on a high performance host should have a very high cost. But putting a vanilla instance on a vanilla Host should have a low cost. 

Some Costs are more esoteric. Consider a rule that says we should prefer Hosts that don't already have an instance on it that is owned by the user requesting it (to mitigate against machine failures). Here we have to look at all the other Instances on the host to compute our cost. 

An example of some other costs might include selecting:
 * a GPU-based host over a standard CPU
 * a host with fast ethernet over a 10mbps line
 * a host that can run Windows instances
 * a host in the EU vs North America
 * etc

This Weight is computed for each Instance requested. If the customer asked for 1000 instances, the consumed resources on each Host are "virtually" depleted so the Cost can change accordingly. 

    .. image:: /images/costs_weights.png 
    
nova.scheduler.base_scheduler.BaseScheduler
------------------------------------------------------
As we explained in the Zones documentation, each Scheduler has a `ZoneManager` object that collects "Capabilities" about child Zones and each of the services running in the current Zone. The `BaseScheduler` uses this information to make its decisions.

Here is how it works:

 1. The compute nodes are filtered and the nodes remaining are weighed.
 2. Filtering the hosts is a simple matter of ensuring the compute node has ample resources (CPU, RAM, Disk, etc) to fulfil the request.
 3. Weighing of the remaining compute nodes assigns a number based on their suitability for the request.
 4. The same request is sent to each child Zone and step #1 is done there too. The resulting weighted list is returned to the parent.
 5. The parent Zone sorts and aggregates all the weights and a final build plan is constructed.
 6. The build plan is executed upon. Concurrently, instance create requests are sent to each of the selected hosts, be they local or in a child zone. Child Zones may forward the requests to their child Zones as needed.

    .. image:: /images/zone_overview.png 

`BaseScheduler` by itself is not capable of handling all the provisioning itself. You should also specify the filter classes and weighting classes to be used in determining which host is selected for new instance creation.

Filtering and Weighing
----------------------
The filtering (excluding compute nodes incapable of fulfilling the request) and weighing (computing the relative "fitness" of a compute node to fulfill the request) rules used are very subjective operations ... Service Providers will probably have a very different set of filtering and weighing rules than private cloud administrators. The filtering and weighing aspects of the `BaseScheduler` are flexible and extensible.

    .. image:: /images/filtering.png 

Requesting a new instance
-------------------------
Prior to the `BaseScheduler`, to request a new instance, a call was made to `nova.compute.api.create()`. The type of instance created depended on the value of the `InstanceType` record being passed in. The `InstanceType` determined the amount of disk, CPU, RAM and network required for the instance. Administrators can add new `InstanceType` records to suit their needs. For more complicated instance requests we need to go beyond the default fields in the `InstanceType` table.

`nova.compute.api.create()` performed the following actions:
 1. it validated all the fields passed into it.
 2. it created an entry in the `Instance` table for each instance requested
 3. it put one `run_instance` message in the scheduler queue for each instance requested
 4. the schedulers picked off the messages and decided which compute node should handle the request.
 5. the `run_instance` message was forwarded to the compute node for processing and the instance is created. 
 6. it returned a list of dicts representing each of the `Instance` records (even if the instance has not been activated yet). At least the `instance_ids` are valid. 

    .. image:: /images/nova.compute.api.create.png 

Generally, the simplest schedulers (like `ChanceScheduler` and `AvailabilityZoneScheduler`) only operate in the current Zone. They have no concept of child Zones.

The problem with this approach is each request is scattered amongst each of the schedulers. If we are asking for 1000 instances, each scheduler gets the requests one-at-a-time. There is no possability of optimizing the requests to take into account all 1000 instances as a group. We call this Single-Shot vs. All-at-Once. 

For the `BaseScheduler` we need to use the All-at-Once approach. We need to consider all the hosts across all the Zones before deciding where they should reside. In order to handle this we have a new method `nova.compute.api.create_all_at_once()`. This method does things a little differently:
 1. it validates all the fields passed into it.
 2. it creates a single `reservation_id` for all of instances created. This is a UUID.
 3. it creates a single `run_instance` request in the scheduler queue
 4. a scheduler picks the message off the queue and works on it.
 5. the scheduler sends off an OS API `POST /zones/select` command to each child Zone. The `BODY` payload of the call contains the `request_spec`.
 6. the child Zones use the `request_spec` to compute a weighted list for each instance requested. No attempt to actually create an instance is done at this point. We're only estimating the suitability of the Zones.
 7. if the child Zone has its own child Zones, the `/zones/select` call will be sent down to them as well.
 8. Finally, when all the estimates have bubbled back to the Zone that initiated the call, all the results are merged, sorted and processed.
 9. Now the instances can be created. The initiating Zone either forwards the `run_instance` message to the local Compute node to do the work, or it issues a `POST /servers` call to the relevant child Zone. The parameters to the child Zone call are the same as what was passed in by the user.
 10. The `reservation_id` is passed back to the caller. Later we explain how the user can check on the status of the command with this `reservation_id`.

    .. image:: /images/nova.compute.api.create_all_at_once.png 

The Catch
---------
This all seems pretty straightforward but, like most things, there's a catch. Zones are expected to operate in complete isolation from each other. Each Zone has its own AMQP service, database and set of Nova services. But for security reasons Zones should never leak information about the architectural layout internally. That means Zones cannot leak information about hostnames or service IP addresses outside of its world.

When `POST /zones/select` is called to estimate which compute node to use, time passes until the `POST /servers` call is issued. If we only passed the weight back from the `select` we would have to re-compute the appropriate compute node for the create command ... and we could end up with a different host. Somehow we need to remember the results of our computations and pass them outside of the Zone. Now, we could store this information in the local database and return a reference to it, but remember that the vast majority of weights are going to be ignored. Storing them in the database would result in a flood of disk access and then we have to clean up all these entries periodically. Recall that there are going to be many, many `select` calls issued to child Zones asking for estimates. 

Instead, we take a rather innovative approach to the problem. We encrypt all the child Zone internal details and pass them back the to parent Zone. In the case of a nested Zone layout, each nesting layer will encrypt the data from all of its children and pass that to its parent Zone. In the case of nested child Zones, each Zone re-encrypts the weighted list results and passes those values to the parent. Every Zone interface adds another layer of encryption, using its unique key.

Once a host is selected, it will either be local to the Zone that received the initial API call, or one of its child Zones. In the latter case, the parent Zone it simply passes the encrypted data for the selected host back to each of its child Zones during the `POST /servers` call as an extra parameter. If the child Zone can decrypt the data, then it is the correct Zone for the selected host; all other Zones will not be able to decrypt the data and will discard the request. This is why it is critical that each Zone has a unique value specified in its config in `--build_plan_encryption_key`: it controls the ability to locate the selected host without having to hard-code path information or other identifying information. The child Zone can then act on the decrypted data and either go directly to the Compute node previously selected if it is located in that Zone, or repeat the process with its child Zones until the target Zone containing the selected host is reached.

Throughout the `nova.api.openstack.servers`, `nova.api.openstack.zones`, `nova.compute.api.create*` and `nova.scheduler.base_scheduler` code you'll see references to `blob` and `child_blob`. These are the encrypted hints about which Compute node to use.

Reservation IDs
---------------

The OpenStack API allows a user to list all the instances they own via the `GET /servers/` command or the details on a particular instance via `GET /servers/###`. This mechanism is usually sufficient since OS API only allows for creating one instance at a time, unlike the EC2 API which allows you to specify a quantity of instances to be created.

NOTE: currently the `GET /servers` command is not Zone-aware since all operations done in child Zones are done via a single administrative account. Therefore, asking a child Zone to `GET /servers` would return all the active instances ... and that would not be what the user intended. Later, when the Keystone Auth system is integrated with Nova, this functionality will be enabled. 

We could use the OS API 1.1 Extensions mechanism to accept a `num_instances` parameter, but this would result in a different return code. Instead of getting back an `Instance` record, we would be getting back a `reservation_id`. So, instead, we've implemented a new command `POST /zones/boot` command which is nearly identical to `POST /servers` except that it takes a `num_instances` parameter and returns a `reservation_id`. Perhaps in OS API 2.x we can unify these approaches. 

Finally, we need to give the user a way to get information on each of the instances created under this `reservation_id`. Fortunately, this is still possible with the existing `GET /servers` command, so long as we add a new optional `reservation_id` parameter. 

`python-novaclient` will be extended to support both of these changes.

Host Filter
-----------

As we mentioned earlier, filtering hosts is a very deployment-specific process. Service Providers may have a different set of criteria for filtering Compute nodes than a University. To faciliate this the `nova.scheduler.filters` module supports a variety of filtering strategies as well as an easy means for plugging in your own algorithms.

The filter used is determined by the `--default_host_filters` flag, which points to a Python Class. By default this flag is set to `[AllHostsFilter]` which simply returns all available hosts. But there are others:

 * `InstanceTypeFilter` provides host filtering based on the memory and disk size specified in the `InstanceType` record passed into `run_instance`. 

 * `JSONFilter` filters hosts based on simple JSON expression grammar. Using a LISP-like JSON structure the caller can request instances based on criteria well beyond what `InstanceType` specifies. See `nova.tests.test_host_filter` for examples.

To create your own `HostFilter` the user simply has to derive from `nova.scheduler.filters.AbstractHostFilter` and implement two methods: `instance_type_to_filter` and `filter_hosts`. Since Nova is currently dependent on the `InstanceType` structure, the `instance_type_to_filter` method should take an `InstanceType` and turn it into an internal data structure usable by your filter. This is for backward compatibility with existing OpenStack and EC2 API calls. If you decide to create your own call for creating instances not based on `Flavors` or `InstanceTypes` you can ignore this method. The real work is done in `filter_hosts` which must return a list of host tuples for each appropriate host. The set of available hosts is in the `host_list` parameter passed into the call as well as the filter query. The host tuple contains (`<hostname>`, `<additional data>`) where `<additional data>` is whatever you want it to be. By default, it is the capabilities reported by the host.
     
Cost Scheduler Weighing
-----------------------
Every `BaseScheduler` subclass should also override the `weigh_hosts` method. This takes the list of filtered hosts (generated by the `filter_hosts` method) and returns a list of weight dicts. The weight dicts must contain two keys: `weight` and `hostname` where `weight` is simply an integer (lower is better) and `hostname` is the name of the host. The list does not need to be sorted, this will be done by the `BaseScheduler` when all the results have been assembled. 

Simple Scheduling Across Zones
----------------------------
The `BaseScheduler` uses the default `filter_hosts` method, which will use either any filters specified in the request's `filter` parameter, or, if that is not specified, the filters specified in the `FLAGS.default_host_filters` setting. Its `weight_hosts` method simply returns a weight of 1 for all hosts. But, from this, you can see calls being routed from Zone to Zone and follow the flow of things. 

The `--scheduler_driver` flag is how you specify the scheduler class name.

Flags
-----

All this Zone and Distributed Scheduler stuff can seem a little daunting to configure, but it's actually not too bad. Here are some of the main flags you should set in your `nova.conf` file:

::

  --allow_admin_api=true
  --enable_zone_routing=true
  --zone_name=zone1
  --build_plan_encryption_key=c286696d887c9aa0611bbb3e2025a45b
  --scheduler_driver=nova.scheduler.base_scheduler.BaseScheduler
  --default_host_filter=nova.scheduler.filters.AllHostsFilter

`--allow_admin_api` must be set for OS API to enable the new `/zones/*` commands.
`--enable_zone_routing` must be set for OS API commands such as `create()`, `pause()` and `delete()` to get routed from Zone to Zone when looking for instances. 
`--zone_name` is only required in child Zones. The default Zone name is `nova`, but you may want to name your child Zones something useful. Duplicate Zone names are not an issue.
`build_plan_encryption_key` is the SHA-256 key for encrypting/decrypting the Host information when it leaves a Zone. Be sure to change this key for each Zone you create. Do not duplicate keys.
`scheduler_driver` is the real workhorse of the operation. For Distributed Scheduler, you need to specify a class derived from `nova.scheduler.base_scheduler.BaseScheduler`.
`default_host_filter` is the host filter to be used for filtering candidate Compute nodes. 

Some optional flags which are handy for debugging are:

::

  --connection_type=fake
  --verbose

Using the `Fake` virtualization driver is handy when you're setting this stuff up so you're not dealing with a million possible issues at once. When things seem to working correctly, switch back to whatever hypervisor your deployment uses.

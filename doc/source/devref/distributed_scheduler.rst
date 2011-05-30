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

Distributed Scheduler
=====

The Scheduler is akin to a Dating Service. Requests for the creation of new instances come in and Compute nodes are selected for where the work should be performed. In a small deployment we may be happy with the currently available Change Scheduler which randomly selects a Host from the available pool. Or if you need something a little more fancy you may want to use the Availability Zone Scheduler, which selects Compute hosts from a logical partitioning of available hosts (within a single Zone). 

But for larger deployments a more complex scheduling algorithm is required. Additionally, if you are using Zones in your Nova setup, you'll need a scheduler that understand how to pass instance requests from Zone to Zone.

This is the purpose of the Distributed Scheduler (DS). The DS utilizes the Capabilities of a Zone and its component services to make informed decisions on where a new instance should be created. When making this decision it consults not only all the Compute nodes in the current Zone, but the Compute nodes in each Child Zone. This continues recursively until the ideal host is found.

So, how does this all work?

This document will explain the strategy employed by the `ZoneAwareScheduler` and its derivations. You should read the Zones documentation before reading this.

Costs & Weights
----------
When deciding where to place an Instance, we compare a Weighted Cost for each Host. The Weighting, currently, is just the sum of each Cost. Costs are nothing more than integers from `0 - max_int`. Costs are computed by looking at the various Capabilities of the Host relative to the specs of the Instance being asked for. Trying to put an Instance with 8G of RAM on a Host that only has 4G remaining would have a very high cost. But putting a 512m RAM instance on an empty Host should have a low cost. 

Some Costs are more esoteric. Consider a rule that says we should prefer Hosts that don't already have an instance on it that is owned by the user requesting it (to mitigate against machine failures). Here we have to look at all the other Instances on the host to compute our cost. 

An example of some other costs might include selecting:
* a GPU-based host over a standard CPU
* a host with fast ethernet over a 10mbps line
* a host than can run Windows instances
* a host in the EU vs North America
* etc

This Weight is computed for each Instance requested. If the customer asked for 1000 instances, the consumed resources on each Host are "virtually" depleted so the Cost can change accordingly. 

nova.scheduler.zone_aware_scheduler.ZoneAwareScheduler
-----------
As we explained in the Zones documentation, each Scheduler has a `ZoneManager` object that collects "Capabilities" about Child Zones and each of the Services running in the current Zone. The `ZoneAwareScheduler` uses this information to make its decisions.

Here is how it works:

1. The Compute nodes are Filtered and the nodes remaining are Weighed.
1a. Filtering the hosts is a simple matter of ensuring the Compute node has ample resources (CPU, RAM, DISK, etc) to fulfil the request. 
1b. Weighing of the remaining Compute nodes assigns a number based on their suitability for the request.
2. The same request is sent to each Child Zone and step #1 is done there too. The resulting Weighted List is returned to the parent.
3. The Parent Zone sorts and aggregates all the Weights and a final Build Plan is constructed.
4. The Build Plan is executed upon. Concurrently, Instance Create requests are sent to each of the selected Hosts, be they local or in a child zone. Child Zones may forward the requests to their Child Zones as needed.

`ZoneAwareScheduler` by itself is not capable of handling all the provisioning itself. Derived classes are used to select which Host filtering and Weighing strategy will be used. We'll go into more detail on that later. 

Filtering and Weighing
------------
Filtering (excluding Compute nodes incapable of fulfilling the request) and Weighing (computing the relative "fitness" of a Compute node to fulfill the request) are very subjective operations. Service Providers will probably have a very different set of filtering and weighing rules than private cloud administrators. The filtering and weighing aspects of the `ZoneAwareScheduler` are flexible and extensible. We will explain how to do this later in this document.

Requesting a new instance
------------
To request a new instance, a call is made to `nova.compute.api.create()`. The type of instance created depends on the value of the `InstanceType` record being passed in. The `InstanceType` determines the amount of disk, cpu, ram and network required for the instance. Administrators can add new `InstanceType` records to suit their needs. For more complicated instance requests we need to go beyond the default fields in the `InstanceType` table, but we'll discuss that later.

`nova.compute.api.create()` performs the following actions:
1. it validates all the fields passed into it.
2. it creates an entry in the `Instance` table for each instance requested
3. it puts one `run_instance` message in the scheduler queue for each instance requested
4. the schedulers pick off the messages and decide which Compute node should handle the request.
5. the `run_instance` message is forwarded to the Compute node for processing and the instance is created. 
6. it returns a list of dicts representing each of the `Instance` records (even if the instance has not been activated yet). At least the `instance_id`'s are valid. 

Generally, the standard schedulers (like `ChangeScheduler` and `AvailabilityZoneScheduler`) only operate in the current Zone. They have no concept of Child Zones.

The problem with this approach is that each request is scattered amongst each of the schedulers. If we are asking for 1000 instances, each scheduler gets the requests one-at-a-time. There is no possability of optimizing the requests to take into account all 1000 instances as a group. We call this Single-Shot vs. All-at-Once. 

For the `ZoneAwareScheduler` we need to use the All-at-Once approach. We need to consider all the hosts across all the Zones before deciding where they should reside. In order to handle this we have a new method `nova.compute.api.create_all_at_once()`. This method does things a little differently:
1. it validates all the fields passed into it.
2. it creates a single `reservation_id` for all of instances created. This is a UUID.
3. it creates a single `run_instance` request in the scheduler queue
4. a scheduler picks the message off the queue and works on it.
5. the scheduler sends off an OS API `POST /zones/select` command to each Child Zone. The `BODY` payload of the call contains the `request_spec`.
6. the Child Zones use the `request_spec` to compute a weighted list for each instance requested. No attempt to actually create an instance is done at this point. We're only estimating the suitability of the Zones.
7. if the Child Zone has its own Child Zone's, the `/zones/select` call will be sent down to them as well.
8. Finally, when all the estimates have bubbled back to the Zone that initiated the call, all the results are merged, sorted and processed.
9. Now the instances can be created. The initiating Zone either forwards the `run_instance` message to the local Compute node to do the work, or it issues a `POST /servers` call to the relevant Child Zone. The parameters to the Child Zone call are the same as what was passed in by the user.
10. The `reservation_id` is passed back to the caller. Later we explain how the user can check on the status of the command with this `reservation_id`.

The Catch
-------------
This all seems pretty straightforward but, like most things, there's a catch. Zones are expected to operate in complete isolation from each other. Each Zone has its own AMQP service, Database and set of Nova Services. But, for security reasons Zones should never leak information about the architectural layout internally. That means Zones cannot leak information about hostnames or service IP addresses outside of its world.

When `POST /zones/select` is called to estimate which Compute node to use, time passes until the `POST /servers` call is issued. If we only passed the Weight back from the `select` we would have to re-compute the appropriate Compute node for the create command ... and we could end up with a different host. Somehow we need to remember the results of our computations and pass them outside of the Zone. Now, we could store this information in the local database and return a reference to it, but remember that the vast majority of weights are going be ignored. Storing them in the database would result in a flood of disk access and then we have to clean up all these entries periodically. Recall that there are going to be many many `select` calls issued to Child Zones asking for estimates. 

Instead, we take a rather innovative approach to the problem. We encrypt all the child zone internal details and pass them back the to parent Zone. If the parent zone decides to use a child Zone for the instance it simply passes the encrypted data back to the child during the `POST /servers` call as an extra parameter. The child Zone can then decrypt the hint and go directly to the Compute node previously selected. If the estimate isn't used, it is simply discarded by the parent.

In the case of nested child Zones, each Zone re-encrypts the weighted list results and passes those values to the parent.

Throughout the `nova.api.openstack.servers`, `nova.api.openstack.zones`, `nova.compute.api.create*` and `nova.scheduler.zone_aware_scheduler` code you'll see references to `blob` and `child_blob`. These are the encrypted hints about which Compute node to use.

Reservation ID's
---------------

NOTE: The features described in this section are related to the up-coming 'merge-4' branch. 

The OpenStack API allows a user to list all the instances they own via the `GET /servers/` command or the details on a particular instance via `GET /servers/###`. This mechanism is usually sufficient since OS API only allows for creating one instance at a time, unlike the EC2 API which allows you to specify a quantity of instances to be created.

NOTE: currently the `GET /servers` command is not Zone-aware since all operations done in child Zones are done via a single administrative account. Therefore, asking a child Zone to `GET /servers` would return all the active instances ... and that would be bad. Later, when the Keystone Auth system is integrated with Nova, this functionality will be enabled. 

We could use the OS API 1.1 Extensions mechanism to accept a `num_instances` parameter, but this would result in a different return code. Instead of getting back an `Instance` record, we would be getting back a `reservation_id`. So, instead, we've implemented a new command `POST /zones/servers` command which is nearly identical to `POST /servers` except that it takes a `num_instances` parameter and returns a `reservation_id`. Perhaps in OS API 2.x we can unify these approaches. 

Finally, we need to give the user a way to get information on each of the instances created under this `reservation_id`. Fortunately, this is still possible with the existing `GET /servers` command, so long as we add a new optional `reservation_id` parameter. 

`python-novaclient` will be extended to support both of these changes.

Host Filter
--------------


Cost Scheduler Weighing
--------------



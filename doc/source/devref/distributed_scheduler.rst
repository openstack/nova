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

The Scheduler is akin to a Dating Service. Requests for the creation of new instances come in and the most applicable Compute nodes are selected from a large pool of potential candidates. In a small deployment we may be happy with the currently available Chance Scheduler which randomly selects a Host from the available pool. Or if you need something a little more fancy you may want to use the Distributed Scheduler, which selects Compute hosts from a logical partitioning of available hosts (within a single Zone).

    .. image:: /images/dating_service.png 

The Distributed Scheduler (DS) supports filtering and weighing to make informed decisions on where a new instance should be created.

So, how does this all work?

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
    
Filtering and Weighing
----------------------
The filtering (excluding compute nodes incapable of fulfilling the request) and weighing (computing the relative "fitness" of a compute node to fulfill the request) rules used are very subjective operations ... Service Providers will probably have a very different set of filtering and weighing rules than private cloud administrators. The filtering and weighing aspects of the `DistributedScheduler` are flexible and extensible.

    .. image:: /images/filtering.png 

Host Filter
-----------

As we mentioned earlier, filtering hosts is a very deployment-specific process. Service Providers may have a different set of criteria for filtering Compute nodes than a University. To facilitate this, the `DistributedScheduler` supports a variety of filtering strategies as well as an easy means for plugging in your own algorithms.  Specifying filters involves 2 settings.  One makes filters available for use.  The second specifies which filters to use by default (out of the filters available).  The reason for this second option is that there may be support to allow end-users to specify specific filters during a build at some point in the future.

Making filters available:

Filters are made available to the scheduler via the `--scheduler_available_filters` setting.  This setting can be specified more than once and should contain lists of filter class names (with full paths) to make available.  Specifying 'nova.scheduler.filters.standard_filters' will cause all standard filters under 'nova.scheduler.filters' to be made available.  That is the default setting.  Additionally, you can specify your own classes to be made available.  For example, 'myfilter.MyFilterClass' can be specified.  Now that you've configured which filters are available, you should set which ones you actually want to use by default.

Setting the default filtering classes:

The default filters to use are set via the `--scheduler_default_filters` setting.  This setting should contain a list of class names.  You should not specify the full paths with these class names.  By default this flag is set to `['AvailabilityZoneFilter', 'RamFilter', 'ComputeFilter']`.  Below is a list of standard filter classes:

 * `AllHostsFilter` includes all hosts (essentially is a No-op filter)
 * `AvailabilityZoneFilter` provides host filtering based on availability_zone
 * `ComputeFilter` provides host filtering based on `InstanceType` extra_specs, comparing against host capability announcements
 * `CoreFilter` provides host filtering based on number of cpu cores
 * `DifferentHostFilter` provides host filtering based on scheduler_hint's 'different_host' value.  With the scheduler_hints extension, this allows one to put a new instance on a different host from another instance
 * `IsolatedHostsFilter` provides host filtering based on the 'isolated_hosts' and 'isolated_images' flags/settings.
 * `JSONFilter` filters hosts based on simple JSON expression grammar. Using a LISP-like JSON structure the caller can request instances based on criteria well beyond what `ComputeFilter` specifies. See `nova.tests.scheduler.test_host_filters` for examples.
 * `RamFilter` provides host filtering based on the memory needed vs memory free
 * `SameHostFilter` provides host filtering based on scheduler_hint's 'same_host' value.  With the scheduler_hints extension, this allows one to put a new instance on the same host as another instance
 * `SimpleCIDRAffinityFilter` provides host filtering based on scheduler_hint's 'build_near_host_ip' value.  With the scheduler_hints extension, this allows one to put a new instance on a host within the same IP block.

To create your own `HostFilter` the user simply has to derive from `nova.scheduler.filters.BaseHostFilter` and implement one method: `host_passes`.  This method accepts a `HostState` instance describing a host as well as a `filter_properties` dictionary.  Host capabilities can be found in `HostState`.capabilities and other properites can be found in `filter_properties` like `instance_type`, etc.  Your method should return True if it passes the filter.

Flags
-----

Here are some of the main flags you should set in your `nova.conf` file:

::

  --scheduler_driver=nova.scheduler.distributed_scheduler.DistributedScheduler
  --scheduler_available_filters=nova.scheduler.filters.standard_filters
  # --scheduler_available_filters=myfilter.MyOwnFilter
  --scheduler_default_filters=RamFilter,ComputeFilter,MyOwnFilter

`scheduler_driver` is the real workhorse of the operation. For Distributed Scheduler, you need to specify a class derived from `nova.scheduler.distributed_scheduler.DistributedScheduler`.
`scheduler_default_filters` are the host filters to be used for filtering candidate Compute nodes.

Some optional flags which are handy for debugging are:

::

  --connection_type=fake
  --verbose

Using the `Fake` virtualization driver is handy when you're setting this stuff up so you're not dealing with a million possible issues at once. When things seem to working correctly, switch back to whatever hypervisor your deployment uses.

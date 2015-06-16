..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

====================
Scheduler Evolution
====================

The scheduler evolution has been a priority item for both the kilo and liberty
releases: http://specs.openstack.org/openstack/nova-specs/#priorities

Over time the scheduler and the rest of nova have become very tightly
coupled. This effort is focusing on a better separation of concerns between
the nova-scheduler and the rest of Nova.

Once this effort has completed, its conceivable that the nova-scheduler could
become a separate git repo, outside of Nova but within the compute project.
But this is not the current focus of this effort.

Problem Use Cases
==================

Many users are wanting to do more advanced things with the scheduler, but the
current architecture is just not ready to support those in a maintainable way.
Lets look at a few key use cases that need to be easier to support once this
initial work is complete.

Cross Project Affinity
-----------------------

It is possible that when you boot from a volume, you want it to pick a compute
node that is close to that volume, automatically.
There are similar use cases around a pre-created port and needing to be in a
particular location for the best performance of that port.

Accessing Aggregates in Filters and Weights
--------------------------------------------

Any DB access in a filter or weight seriously slows down the scheduler.
Until the end of kilo, there was no way to deal with the scheduler access
information about aggregates without querying the DB in every call to
host_passes() in a filter.

Filter Scheduler Alternatives
------------------------------

For certain use cases, radically different schedulers may perform much better
than the filter scheduler. We should not block this innovation. It is
unreasonable to assume a single scheduler will work for all use cases.

However, we really need a single strong scheduler interface, to enable these
sorts of innovation in a maintainable way.

Project Scale issues
---------------------

There are interesting ideas for new schedulers, like the solver scheduler.
There are frequently requests to add new scheduler filters and weights for
to look at various different aspects of the compute host.
Currently the Nova team just doesn't have the bandwidth to deal with all these
requests. A dedicated scheduler team could work on these items independently
from the rest of Nova.

The problem we currently have, is that the nova-scheduler code is not separate
from the rest of Nova, so its not currently possible to work on the scheduler
in isolation. We need a stable interface before we can make the split.

Key areas we are evolving
==========================

Here we discuss, at a high level, areas that are being addressed as part of
the scheduler evolution work.

Fixing the Scheduler DB model
------------------------------

We need the Nova and scheduler data models to be independent of each other.

The first step is breaking the link between the ComputeNode and Service
DB tables. In theory where the Service information is stored should be
pluggable through the service group API, and should be independent of the
scheduler service. For example, it could be managed via zookeeper rather
than polling the Nova DB.

There are also places where filters and weights call into the Nova DB to
find out information about aggregates. This needs to be sent to the
scheduler, rather than reading directly form the nova database.

Versioning Scheduler Placement Interfaces
------------------------------------------

At the start of kilo, the scheduler is passed a set of dictionaries across
a versioned RPC interface. The dictionaries can create problems with the
backwards compatibility needed for live-upgrades.

Luckily we already have the oslo.versionedobjects infrastructure we can use
to model this data in a way that can be versioned across releases.

This effort is mostly focusing around the request_spec.

Sending host and node stats to the scheduler
---------------------------------------------

Periodically nova-compute updates the scheduler state stored in
the database.

We need a good way to model the data that is being sent from the compute
nodes into the scheduler, so over time, the scheduler can move to having
its own database.

This is linked to the work on the resource tracker.

Updating the Scheduler about other data
----------------------------------------

For things like host aggregates, we need the scheduler to cache information
about those, and know when there are changes so it can update its cache.

Over time, its possible that we need to send cinder and neutron data, so
the scheduler can use that data to help pick a nova-compute host.

Resource Tracker
-----------------

The recent work to add support for NUMA and PCI pass through have shown we
have no good pattern to extend the resource tracker. Ideally we want to keep
the innovation inside the Nova tree, but we also need it to be easier.

This is very related to the effort to re-think how we model resources, as
covered by the discussion.

Parallelism and Concurrency
----------------------------

The current design of the nova-scheduler is very racy, and can lead to
excessive numbers of build retries before the correct host is found.
The recent NUMA features are particularly impacted by how the scheduler
currently works.
All this has lead to many people only running a single nova-scheduler
process configured to use a very small greenthread pool.

The work on cells v2 will mean that we soon need the scheduler to scale for
much larger problems. The current scheduler works best with less than 1k nodes
but we will need the scheduler to work with at least 10k nodes.

Various ideas have been discussed to reduce races when running multiple
nova-scheduler processes.
One idea is to use two-phase commit "style" resource tracker claims.
Another idea involves using incremental updates so it is more efficient to
keep the scheduler's state up to date, potentially using Kafka.

For more details, see the backlog spec that describes more of the details
around this problem.

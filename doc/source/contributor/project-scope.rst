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

Scope of the Nova project
==========================

Nova is focusing on doing an awesome job of its core mission.
This document aims to clarify that core mission.

This is a living document to help record where we agree about what Nova
should and should not be doing, and why.
Please treat this as a discussion of interesting, and hopefully useful,
examples. It is not intended to be an exhaustive policy statement.

.. _nova-mission:

Mission
-------

Our mission statement starts with:

    To implement services and associated libraries to provide massively
    scalable, on demand, self service access to compute resources.

Our official mission statement also includes the following examples of
compute resources: bare metal, virtual machines, and containers.
For the full official mission statement see:
https://governance.openstack.org/tc/reference/projects/nova.html#mission

This document aims to help clarify what the mission statement means.

Compute Resources
------------------

Nova is all about access to compute resources. This section looks at the
types of compute resource Nova works with.

Virtual Servers
****************

Nova was originally focused purely on providing access to virtual servers
running on a variety of different hypervisors.
The majority of users use Nova only to provide access to virtual servers
from a single hypervisor, however, its possible to have a Nova deployment
include multiple different types of hypervisors, while at the same time
offering containers and bare metal servers.

Containers
***********

The Nova API is not a good fit for a lot of container use cases.
The Magnum project intends to deliver a good container experience built
on top of Nova.

Nova allows you to use containers in a similar way to how you would use
on demand virtual machines. We want to maintain this distinction, so we
maintain the integrity and usefulness of the existing Nova API.

For example, Nova is not designed to spin up new containers for every apache
request, nor do we plan to control what goes on inside containers.
They get the same metadata provided to them as virtual machines, to do
with as they see fit.

Bare Metal Servers
*******************

Ironic project has been pioneering the idea of treating physical machines in
a similar way to on demand virtual machines.

Nova's driver is able to allow a multi-tenant cloud style use of Ironic
controlled resources.

While currently there are operations that are a fundamental part of our
virtual machine abstraction that are not currently available in ironic,
such as attaching iSCSI volumes, it does not fundamentally change the
semantics of our API, and as such is a suitable Nova driver. Moreover,
it is expected that gap with shrink over time.

Driver Parity
**************

Our goal for the Nova API is to provide a consistent abstraction to access
on demand compute resources. We are not aiming to expose all features of all
hypervisors. Where the details of the underlying hypervisor leak through
our APIs, we have failed in this goal, and we must work towards better
abstractions that are more `interoperable`_.
This is one reason why we put so much emphasis on the use of Tempest in third
party CI systems.

The key tenet of driver parity is that if a feature is supported in a driver,
it must feel the same to users, as if they where using any of the other
drivers that also support that feature. The exception is that, if possible for
widely different performance characteristics, but the effect of that API call
must be identical.

Following on from that, should a feature only be added to one of the drivers,
we must make every effort to ensure another driver could be implemented to
match that behavior.

It is important that drivers support enough features, so the API actually
provides a consistent abstraction. For example, being unable to create a
server or delete a server would severely undermine that goal.
In fact, Nova only ever manages resources it creates.

.. _interoperable: https://www.openstack.org/brand/interop/

Upgrades
---------

Nova is widely used in production. As such we need to respect the needs of our
existing users. At the same time we need evolve the current code base,
including both adding and removing features.

This section outlines how we expect people to upgrade, and what we do to help
existing users that upgrade in the way we expect.

Upgrade expectations
*********************

Our upgrade plan is to concentrate on upgrades from N-1 to the Nth release.
So for someone running juno, they would have to upgrade to kilo before
upgrading to liberty.
This is designed to balance the need for a smooth upgrade, against having to
keep maintaining the compatibility code to make that upgrade possible.
We talk about this approach as users consuming the stable branch.

In addition, we also support users upgrading from the master branch,
technically, between any two commits within the same release cycle.
In certain cases, when crossing release boundaries, you
must upgrade to the stable branch, before upgrading to the tip of master.
This is to support those that are doing some level of
"Continuous Deployment" from the tip of master into production.
Many of the public cloud provides running OpenStack use this approach so they
are able to get access to bug fixes and features they work on into production
sooner.

This becomes important when you consider reverting a commit that turns out to
have been bad idea. We have to assume any public API change may have already
been deployed into production, and as such cannot be reverted.
In a similar way, a database migration may have been deployed.

Any commit that will affect an upgrade gets the UpgradeImpact tag added to
the commit message, so there is no requirement to wait for release notes.

Don't break existing users
****************************

As a community we are aiming towards a smooth upgrade process, where users
must be unaware you have just upgraded your deployment, except that there
might be additional feature available and improved stability and performance
of some existing features.

We don't ever want to remove features our users rely on. Sometimes we need to
migrate users to a new implementation of that feature, which may require extra
steps by the deployer, but the end users must be unaffected by such changes.
However there are times when some features become a problem to maintain, and
fall into disrepair. We aim to be honest with our users and highlight the
issues we have, so we are in a position to find help to fix that situation.
Ideally we are able to rework the feature so it can be maintained, but in some
rare cases, the feature no longer works, is not tested, and no one is stepping
forward to maintain that feature, the best option can be to remove that
feature.

When we remove features, we need to warn users by first marking those features as
deprecated, before we finally remove the feature. The idea is to get feedback
on how important the feature is to our user base. Where a feature is important
we work with the whole community to find a path forward for those users.

API Scope
----------

Nova aims to provide a highly interoperable and stable REST API for our users
to get self-service access to compute resources.

No more API Proxies
********************

Nova API current has some APIs that are now (in kilo) mostly just a proxy
to other OpenStack services. If it were possible to remove a public API, these
are some we might start with. As such, we don't want to add any more.

The first example is the API that is a proxy to the Glance v1 API.
As Glance moves to deprecate its v1 API, we need to translate calls
from the old v1 API we expose, to Glance's v2 API.

The next API to mention is the networking APIs, in particular the
security groups API. If you are using nova-network, Nova is still the only
way to perform these network operations.
But if you use Neutron, security groups has a much richer Neutron API,
and if you use both Nova API and Neutron API, the miss match can lead to
some very unexpected results, in certain cases.

Our intention is to avoid adding to the problems we already have in this area.

No more Orchestration
**********************

Nova is a low level infrastructure API. It is plumbing upon which richer
ideas can be built. Heat and Magnum being great examples of that.

While we have some APIs that could be considered orchestration, and we must
continue to maintain those, we do not intend to add any more APIs that do
orchestration.

Third Party APIs
*****************

Nova aims to focus on making a great API that is highly interoperable across
all Nova deployments.

We have historically done a very poor job of implementing and maintaining
compatibility with third party APIs inside the Nova tree.

As such, all new efforts should instead focus on external projects that
provide third party compatibility on top of the Nova API. Where needed, we
will work with those projects to extend the Nova API such that its
possible to add that functionality on top of the Nova API. However, we do
not intend to add API calls for those services to persist third party API
specific information in the Nova database. Instead we want to focus on
additions that enhance the existing Nova API.

Scalability
------------

Our mission includes the text "massively scalable". Lets discuss what that
means.

Nova has three main axes of scale: Number of API requests, number of compute
nodes and number of active instances.
In many cases the number of compute nodes and active instances are so closely
related, you rarely need to consider those separately.
There are other items, such as the number of tenants, and the number of
instances per tenant. But, again, these are very rarely the key scale issue.
Its possible to have a small cloud with lots of requests for very short
lived VMs, or a large cloud with lots of longer lived VMs.
These need to scale out different components of the Nova system to reach
their required level of scale.

Ideally all Nova components are either scaled out to match the number of API
requests and build requests, or scaled out to match the number of running
servers. If we create components that have their load increased relative to
both of these items, we can run into inefficiencies or resource contention.
Although it is possible to make that work in some cases, this should always
be considered.

We intend Nova to be usable for both small and massive deployments.
Where small involves 1-10 hypervisors and massive deployments are single
regions with greater than 10,000 hypervisors. That should be seen as our
current goal, not an upper limit.

There are some features that would not scale well for either the small scale
or the very large scale. Ideally we would not accept these features, but if
there is a strong case to add such features, we must work hard to ensure
you can run without that feature at the scale you are required to run.

IaaS not Batch Processing
--------------------------

Currently Nova focuses on providing on-demand compute resources in the style
of classic Infrastructure-as-a-service clouds. A large pool of compute
resources that people can consume in a self-service way.

Nova is not currently optimized for dealing with a larger number of requests
for compute resources compared with the amount of compute resources
currently available.
We generally assume that a level of spare capacity is maintained for future
requests. This is needed for users who want to quickly scale out, and extra
capacity becomes available again as users scale in.
While spare capacity is also not required, we are not optimizing for a
system that aims to run at 100% capacity at all times.
As such our quota system is more focused on limiting the current level of
resource usage, rather than ensuring a fair balance of resources between all
incoming requests.
This doesn't exclude adding features to support making a better use of spare
capacity, such as "spot instances".

There have been discussions around how to change Nova to work better for
batch job processing.
But the current focus is on how to layer such an abstraction on top of the
basic primitives Nova currently provides, possibly adding additional APIs
where that makes good sense. Should this turn out to be impractical, we may
have to revise our approach.

Deployment and Packaging
-------------------------

Nova does not plan on creating its own packaging or deployment systems.

Our CI infrastructure is powered by Devstack. This can also be used by
developers to test their work on a full deployment of Nova.

We do not develop any deployment or packaging for production deployments.
Being widely adopted by many distributions and commercial products, we
instead choose to work with all those parties to ensure they are able to
effectively package and deploy Nova.

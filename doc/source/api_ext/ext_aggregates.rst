About This Extension
====================

This extension introduces the concept of aggregates into Nova. Host aggregates are different from zones and availability zones: while the former allows the partition of Nova deployments into logical groups for load balancing and instance distribution, the latter are for providing some form of physical isolation and redundancy from other availability zones (e.g. by using separate power supply and network gears). Availability zones do not necessarily mean geographic distribution whereas zones usually do. Host aggregates can be regarded as a mechanism to further partitioning an availability zone, i.e. into multiple groups of hosts that share common resources like storage and network. This enables a finer level of granularity in which to structure an entire OpenStack deployment. Aggregates allows higher availability of a single guest instance within an availability zone, it enables advanced VM placement strategies, and more importantly it enables hosts' zero-downtime upgrades (for example, via VM live migration across members of the aggregate, thus causing no disruption to guest instances).

You can use this extension when you have multiple Compute nodes installed (only XenServer/XCP via xenapi driver is currently supported), and you want to leverage the capabilities of the underlying hypervisor resource pools. For example, you want to enable VM live migration (i.e. VM migration within the pool) or enable host maintenance with zero-downtime for guest instances. Please, note that VM migration across pools (i.e. storage migration) is not yet supported in XenServer/XCP, but will be added when available. Bear in mind that the two migration techniques are not mutually exclusive and can be used in combination for a higher level of flexibility in your cloud management.

To find more about it, please read http://wiki.openstack.org/host-aggregates or quick-search for 'aggregates' on the Nova developer guide.

Pre-requisites depend on the kind of hypervisor support you are going to use. As for XenServer/XCP, the same requirements for resource pools apply.

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://mycloud.com/v1.1/tenant/extensions.

Extension Overview
------------------

Name
	Host Aggregates

Namespace
	http://docs.openstack.org/compute/ext/aggregates/api/v1.1

Alias
	OS-AGGREGATES

Contact
	Armando Migliaccio <armando.migliaccio@citrix.com>

Status
	Released

Extension Version
	v1.0 (2012-02-28)

Dependencies
    Compute API 1.1

Doc Link (PDF)
	http://

Doc Link (WADL)
	http://

Short Description
	This extension enables the use of hypervisor resource pools in Nova.

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension.

Extension Query Response: XML::

	<extension name="Aggregates" namespace="http://docs.openstack.org/compute/ext/aggregates/api/v1.1" alias="os-aggregates" updated="2012-01-12T00:00:00+00:00"><description>Admin-only aggregate administration</description></extension>

Extension Query Response: JSON::

    {"extension": {"updated": "2012-01-12T00:00:00+00:00", "name": "Aggregates", "links": [], "namespace": "http://docs.openstack.org/compute/ext/aggregates/api/v1.1", "alias": "os-aggregates", "description": "Admin-only aggregate administration"}}


Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2012-02-28    Initial draft
============= =====================================


Summary of Changes
==================
This extension to the OpenStack Compute API allows the creation and management of host aggregates (i.e. pools of compute nodes).

New Action
----------

When a new aggregate has been created, actions can be executed using:

	POST /v1.1/<tenant-id>/os-aggregates/<aggregate-id>/action

Valid actions are:

set_metadata
add_host
remove_host

Normal response Code: 200

For example, to set metadata for an aggregate the following xml must be submitted:

{"set_metadata": {"metadata": {"foo_key": "foo_value"}}}

For example, to add a host to an aggregate, the following xml must be submitted:

{"add_host": {"host": "<host-id>"}}

For example, to remove a host from an aggregate, the following xml must be submitted:

{"remove_host": {"host": "<host-id>"}}

Error Response Code(s) conflict (409), badRequest (400), itemNotFound (404)

New Faults
----------
None

New Headers
-----------
None

New Resources
-------------
None

New States
----------
None

Changes to the Cloud Servers Specification
------------------------------------------

None
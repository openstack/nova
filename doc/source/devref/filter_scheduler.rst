Filter Scheduler
================

The **Filter Scheduler** supports `filtering` and `weighting` to make informed
decisions on where a new instance should be created. This Scheduler supports
only working with Compute Nodes.

Filtering
---------

.. image:: /images/filteringWorkflow1.png

During its work Filter Scheduler firstly makes dictionary of unfiltered hosts,
then filters them using filter properties and finally chooses hosts for the
requested number of instances (each time it chooses the least costed host and
appends it to the list of selected costs).

If it turns up, that it can't find candidates for the next instance, it means
that there are no more appropriate instances locally.

If we speak about `filtering` and `weighting`, their work is quite flexible
in the Filter Scheduler. There are a lot of filtering strategies for the
Scheduler to support. Also you can even implement `your own algorithm of
filtering`.

There are some standard filter classes to use (:mod:`nova.scheduler.filters`):

* |AllHostsFilter| - frankly speaking, this filter does no operation. It
  passes all the available hosts.
* |ImagePropertiesFilter| - filters hosts based on properties defined
  on the instance's image.  It passes hosts that can support the specified
  image properties contained in the instance.
* |AvailabilityZoneFilter| - filters hosts by availability zone. It passes
  hosts matching the availability zone specified in the instance properties.
* |ComputeCapabilitiesFilter| - checks that the capabilities provided by the
  host compute service satisfy any extra specifications associated with the
  instance type.  It passes hosts that can create the specified instance type.

  The extra specifications can have a scope at the beginning of the key string
  of a key/value pair. The scope format is "scope:key" and can be nested,
  i.e. key_string := scope:key_string. Example like "capabilities:cpu_info:
  features" is valid scope format. A key string without any ':' is non-scope
  format. Each filter defines it's valid scope, and not all filters accept
  non-scope format.

  The extra specifications can have an operator at the beginning of the value
  string of a key/value pair. If there is no operator specified, then a
  default operator of 's==' is used. Valid operators are:

::

  * = (equal to or greater than as a number; same as vcpus case)
  * == (equal to as a number)
  * != (not equal to as a number)
  * >= (greater than or equal to as a number)
  * <= (less than or equal to as a number)
  * s== (equal to as a string)
  * s!= (not equal to as a string)
  * s>= (greater than or equal to as a string)
  * s> (greater than as a string)
  * s<= (less than or equal to as a string)
  * s< (less than as a string)
  * <in> (substring)
  * <or> (find one of these)

  Examples are: ">= 5", "s== 2.1.0", "<in> gcc", and "<or> fpu <or> gpu"

* |AggregateInstanceExtraSpecsFilter| - checks that the aggregate metadata
  satisfies any extra specifications associated with the instance type (that
  have no scope).  It passes hosts that can create the specified instance type.
  The extra specifications can have the same operators as
  |ComputeCapabilitiesFilter|.
* |ComputeFilter| - passes all hosts that are operational and enabled.
* |CoreFilter| - filters based on CPU core utilization. It passes hosts with
  sufficient number of CPU cores.
* |IsolatedHostsFilter| - filter based on "image_isolated" and "host_isolated"
  flags.
* |JsonFilter| - allows simple JSON-based grammar for selecting hosts.
* |RamFilter| - filters hosts by their RAM. Only hosts with sufficient RAM
  to host the instance are passed.
* |SimpleCIDRAffinityFilter| - allows to put a new instance on a host within
  the same IP block.
* |DifferentHostFilter| - allows to put the instance on a different host from a
  set of instances.
* |SameHostFilter| - puts the instance on the same host as another instance in
  a set of of instances.
* |RetryFilter| - filters hosts that have been attempted for scheduling.
  Only passes hosts that have not been previously attempted.
* |TrustedFilter| - filters hosts based on their trust.  Only passes hosts
  that meet the trust requirements specified in the instance properties.
* |TypeAffinityFilter| - Only passes hosts that are not already running an
  instance of the requested type.
* |AggregateTypeAffinityFilter| - limits instance_type by aggregate.

Now we can focus on these standard filter classes in details. I will pass the
simplest ones, such as |AllHostsFilter|, |CoreFilter| and |RamFilter| are,
because their functionality is quite simple and can be understood just from the
code. For example class |RamFilter| has the next realization:

::

    class RamFilter(filters.BaseHostFilter):
        """Ram Filter with over subscription flag"""

        def host_passes(self, host_state, filter_properties):
            """Only return hosts with sufficient available RAM."""
            instance_type = filter_properties.get('instance_type')
            requested_ram = instance_type['memory_mb']
            free_ram_mb = host_state.free_ram_mb
            total_usable_ram_mb = host_state.total_usable_ram_mb
            used_ram_mb = total_usable_ram_mb - free_ram_mb
            return total_usable_ram_mb * FLAGS.ram_allocation_ratio  - used_ram_mb >= requested_ram

Here `ram_allocation_ratio` means the virtual RAM to physical RAM allocation
ratio (it is 1.5 by default). Really, nice and simple.

Next standard filter to describe is |AvailabilityZoneFilter| and it isn't
difficult too. This filter just looks at the availability zone of compute node
and availability zone from the properties of the request. Each compute service
has its own availability zone. So deployment engineers have an option to run
scheduler with availability zones support and can configure availability zones
on each compute host. This classes method `host_passes` returns `True` if
availability zone mentioned in request is the same on the current compute host.

The |ImagePropertiesFilter| filters hosts based on the architecture,
hypervisor type, and virtual machine mode specified in the
instance.  E.g., an instance might require a host that supports the arm
architecture on a qemu compute host.  The |ImagePropertiesFilter| will only
pass hosts that can satisfy this request.  These instance
properties are populated from properties define on the instance's image.
E.g. an image can be decorated with these properties using
`glance image-update img-uuid --property architecture=arm --property
hypervisor_type=qemu`
Only hosts that satisfy these requirements will pass the
|ImagePropertiesFilter|.

|ComputeCapabilitiesFilter| checks if the host satisfies any 'extra specs'
specified on the instance type.  The 'extra specs' can contain key/value pairs.
The key for the filter is either non-scope format (i.e. no ':' contained), or
scope format in capabilities scope (i.e. 'capabilities:xxx:yyy'). One example
of capabilities scope is "capabilities:cpu_info:features", which will match
host's cpu features capabilities. The |ComputeCapabilitiesFilter| will only
pass hosts whose capabilities satisfy the requested specifications.  All hosts
are passed if no 'extra specs' are specified.

|ComputeFilter| is quite simple and passes any host whose compute service is
enabled and operational.

Now we are going to |IsolatedHostsFilter|. There can be some special hosts
reserved for specific images. These hosts are called **isolated**. So the
images to run on the isolated hosts are also called isolated. This Scheduler
checks if `image_isolated` flag named in instance specifications is the same
that the host has.

|DifferentHostFilter| - its method `host_passes` returns `True` if host to
place instance on is different from all the hosts used by set of instances.

|SameHostFilter| does the opposite to what |DifferentHostFilter| does. So its
`host_passes` returns `True` if the host we want to place instance on is one
of the set of instances uses.

|SimpleCIDRAffinityFilter| looks at the subnet mask and investigates if
the network address of the current host is in the same sub network as it was
defined in the request.

|JsonFilter| - this filter provides the opportunity to write complicated
queries for the hosts capabilities filtering, based on simple JSON-like syntax.
There can be used the following operations for the host states properties:
'=', '<', '>', 'in', '<=', '>=', that can be combined with the following
logical operations: 'not', 'or', 'and'. For example, there is the query you can
find in tests:

::

    ['and',
        ['>=', '$free_ram_mb', 1024],
        ['>=', '$free_disk_mb', 200 * 1024]
    ]

This query will filter all hosts with free RAM greater or equal than 1024 MB
and at the same time with free disk space greater or equal than 200 GB.

Many filters use data from `scheduler_hints`, that is defined in the moment of
creation of the new server for the user. The only exception for this rule is
|JsonFilter|, that takes data in some strange difficult to understand way.

The |RetryFilter| filters hosts that have already been attempted for scheduling.
It only passes hosts that have not been previously attempted.

The |TrustedFilter| filters hosts based on their trust.  Only passes hosts
that match the trust requested in the `extra_specs' for the flavor. The key
for this filter must be scope format as `trust:trusted_host', where `trust'
is the scope of the key and `trusted_host' is the actual key value.
The value of this pair (`trusted'/`untrusted') must match the
integrity of a host (obtained from the Attestation service) before it is
passed by the |TrustedFilter|.

To use filters you specify next two settings:

* `scheduler_available_filters` - Defines filter classes made available to the
   scheduler.  This setting can be used multiple times.
* `scheduler_default_filters` - Of the available filters, defines those that
  the scheduler uses by default.

The default values for these settings in nova.conf are:

::

    --scheduler_available_filters=nova.scheduler.filters.standard_filters
    --scheduler_default_filters=RamFilter,ComputeFilter,AvailabilityZoneFilter,ComputeCapabilitiesFilter,ImagePropertiesFilter

With this configuration, all filters in `nova.scheduler.filters`
would be available, and by default the |RamFilter|, |ComputeFilter|,
|AvailabilityZoneFilter|, |ComputeCapabilitiesFilter|, and
|ImagePropertiesFilter| would be used.

If you want to create **your own filter** you just need to inherit from
|BaseHostFilter| and implement one method:
`host_passes`. This method should return `True` if host passes the filter. It
takes `host_state` (describes host) and `filter_properties` dictionary as the
parameters.

As an example, nova.conf could contain the following scheduler-related
settings:

::

    --scheduler_driver=nova.scheduler.FilterScheduler
    --scheduler_available_filters=nova.scheduler.filters.standard_filters
    --scheduler_available_filters=myfilter.MyFilter
    --scheduler_default_filters=RamFilter,ComputeFilter,MyFilter

With these settings, nova will use the `FilterScheduler` for the scheduler
driver.  The standard nova filters and MyFilter are available to the
FilterScheduler.  The RamFilter, ComputeFilter, and MyFilter are used by
default when no filters are specified in the request.

Costs and weights
-----------------

Filter Scheduler uses so-called **weights** and **costs** during its work.

`Costs` are the computed integers, expressing hosts measure of fitness to be
chosen as a result of the request. Of course, costs are computed due to hosts
characteristics compared with characteristics from the request. So trying to
put instance on a not appropriate host (for example, trying to put really
simple and plain instance on a high performance host) would have high cost, and
putting instance on an appropriate host would have low.

So let's find out, how does all this computing work happen.

Before weighting Filter Scheduler creates the list of tuples containing weights
and cost functions to use for weighing hosts. These functions can be got from
cache, if this operation had been done before (this cache depends on `topic` of
node, Filter Scheduler works with only the Compute Nodes, so the topic would be
"`compute`" here). If there is no cost functions in cache associated with
"compute", Filter Scheduler tries to get these cost functions from `nova.conf`.
Weight in tuple means weight of cost function matching with it. It also can be
got from `nova.conf`. After that Scheduler weights host, using selected cost
functions. It does this using `weighted_sum` method, which parameters are:

* `weighted_fns` - list of cost functions created with their weights;
* `host_states` - hosts to be weighted;
* `weighing_properties` - dictionary of values that can influence weights.

This method firstly creates a grid of function results (it just counts value of
each function using `host_state` and `weighing_properties`) - `scores`, where
it would be one row per host and one function per column. The next step is to
multiply value from the each cell of the grid by the weight of appropriate cost
function. And the final step is to sum values in the each row - it would be the
weight of host, described in this line. This method returns the host with the
lowest weight - the best one.

If we concentrate on cost functions, it would be important to say that we use
`compute_fill_first_cost_fn` function by default, which simply returns hosts
free RAM:

::

    def compute_fill_first_cost_fn(host_state, weighing_properties):
        """More free ram = higher weight. So servers will less free ram will be
           preferred."""
        return host_state.free_ram_mb

You can implement your own variant of cost function for the hosts capabilities
you would like to mention. Using different cost functions (as you understand,
there can be a lot of ones used in the same time) can make the chose of next
host for the creating of the new instance flexible.

These cost functions should be set up in the `nova.conf` with the flag
`least_cost_functions` (there can be more than one functions separated by
commas). By default this line would look like this:

::

    --least_cost_functions=nova.scheduler.least_cost.compute_fill_first_cost_fn

As for weights of cost functions, they also should be described in `nova.conf`.
The line with this description looks the following way:
**function_name_weight**.

As for default cost function, it would be: `compute_fill_first_cost_fn_weight`,
and by default it is -1.0.

::

    --compute_fill_first_cost_fn_weight=-1.0

Negative function's weight means that the more free RAM Compute Node has, the
better it is. Nova tries to spread instances as much as possible over the
Compute Nodes. Positive weight here would mean that Nova would fill up a single
Compute Node first.

Filter Scheduler finds local list of acceptable hosts by repeated filtering and
weighing. Each time it chooses a host, it virtually consumes resources on it,
so subsequent selections can adjust accordingly. It is useful if the customer
asks for the some large amount of instances, because weight is computed for
each instance requested.

.. image:: /images/filteringWorkflow2.png

In the end Filter Scheduler sorts selected hosts by their weight and provisions
instances on them.

P.S.: you can find more examples of using Filter Scheduler and standard filters
in :mod:`nova.tests.scheduler`.

.. |AllHostsFilter| replace:: :class:`AllHostsFilter <nova.scheduler.filters.all_hosts_filter.AllHostsFilter>`
.. |ImagePropertiesFilter| replace:: :class:`ImagePropertiesFilter <nova.scheduler.filters.image_props_filter.ImagePropertiesFilter>`
.. |AvailabilityZoneFilter| replace:: :class:`AvailabilityZoneFilter <nova.scheduler.filters.availability_zone_filter.AvailabilityZoneFilter>`
.. |BaseHostFilter| replace:: :class:`BaseHostFilter <nova.scheduler.filters.BaseHostFilter>`
.. |ComputeCapabilitiesFilter| replace:: :class:`ComputeCapabilitiesFilter <nova.scheduler.filters.compute_capabilities_filter.ComputeCapabilitiesFilter>`
.. |ComputeFilter| replace:: :class:`ComputeFilter <nova.scheduler.filters.compute_filter.ComputeFilter>`
.. |CoreFilter| replace:: :class:`CoreFilter <nova.scheduler.filters.core_filter.CoreFilter>`
.. |IsolatedHostsFilter| replace:: :class:`IsolatedHostsFilter <nova.scheduler.filters.isolated_hosts_filter>`
.. |JsonFilter| replace:: :class:`JsonFilter <nova.scheduler.filters.json_filter.JsonFilter>`
.. |RamFilter| replace:: :class:`RamFilter <nova.scheduler.filters.ram_filter.RamFilter>`
.. |SimpleCIDRAffinityFilter| replace:: :class:`SimpleCIDRAffinityFilter <nova.scheduler.filters.affinity_filter.SimpleCIDRAffinityFilter>`
.. |DifferentHostFilter| replace:: :class:`DifferentHostFilter <nova.scheduler.filters.affinity_filter.DifferentHostFilter>`
.. |SameHostFilter| replace:: :class:`SameHostFilter <nova.scheduler.filters.affinity_filter.SameHostFilter>`
.. |RetryFilter| replace:: :class:`RetryFilter <nova.scheduler.filters.retry_filter.RetryFilter>`
.. |TrustedFilter| replace:: :class:`TrustedFilter <nova.scheduler.filters.trusted_filter.TrustedFilter>`
.. |TypeAffinityFilter| replace:: :class:`TypeAffinityFilter <nova.scheduler.filters.type_filter.TypeAffinityFilter>`
.. |AggregateTypeAffinityFilter| replace:: :class:`AggregateTypeAffinityFilter <nova.scheduler.filters.type_filter.AggregateTypeAffinityFilter>`
.. |AggregateInstanceExtraSpecsFilter| replace:: :class:`AggregateInstanceExtraSpecsFilter <nova.scheduler.filters.aggregate_instance_extra_specs.AggregateInstanceExtraSpecsFilter>`

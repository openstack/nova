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
  returns all the available hosts after its work.
* |AvailabilityZoneFilter| - filters hosts by availability zone. It returns
  hosts with the same availability zone as the requested instance has in its
  properties.
* |ComputeFilter| - checks that the capabilities provided by the compute
  service satisfy the extra specifications, associated with the instance type.
  It returns a list of hosts that can create instance type.
* |CoreFilter| - filters based on CPU core utilization. It will approve host if
  it has sufficient number of CPU cores.
* |IsolatedHostsFilter| - filter based on "image_isolated" and "host_isolated"
  flags.
* |JsonFilter| - allows simple JSON-based grammar for selecting hosts.
* |RamFilter| - filters hosts by their RAM. So, it returns only the hosts with
  enough available RAM.
* |SimpleCIDRAffinityFilter| - allows to put a new instance on a host within
  the same IP block.
* |DifferentHostFilter| - allows to put the instance on a different host from a
  set of instances.
* |SameHostFilter| - puts the instance on the same host as another instance in
  a set of of instances.

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

|ComputeFilter| checks if host can create `instance_type`. Let's note that
instance types describe the compute, memory and storage capacity of nova
compute nodes, it is the list of characteristics such as number of vCPUs,
amount RAM and so on. So |ComputeFilter| looks at hosts' capabilities (host
without requested specifications can't be chosen for the creating of the
instance), checks if the hosts service is up based on last heartbeat. Finally,
this Scheduler can verify if host satisfies some `extra specifications`
associated with the instance type (of course if there are no such extra
specifications, every host suits them).

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
creation of the new server for the user. The only exeption for this rule is
|JsonFilter|, that takes data in some strange difficult to understand way.

To use filters you specify next two settings:

* `scheduler_available_filters` - points available filters.
* `scheduler_default_filters` - points filters to be used by default from the
  list of available ones.

Host Manager sets up these flags in `nova.conf` by default on the next values:

::

    --scheduler_available_filters=nova.scheduler.filters.standard_filters
    --scheduler_default_filters=RamFilter,ComputeFilter,AvailabilityZoneFilter

These two lines mean, that all the filters in the `nova.scheduler.filters`
would be available, and the default ones would be |RamFilter|, |ComputeFilter|
and |AvailabilityZoneFilter|. 

If you want to create **your own filter** you just need to inherit from
|BaseHostFilter| and implement one method:
`host_passes`. This method should return `True` if host passes the filter. It
takes `host_state` (describes host) and `filter_properties` dictionary as the
parameters.

So in the end file nova.conf should contain lines like these:

::

    --scheduler_driver=nova.scheduler.FilterScheduler
    --scheduler_available_filters=nova.scheduler.filters.standard_filters
    --scheduler_available_filters=myfilter.MyFilter
    --scheduler_default_filters=RamFilter,ComputeFilter,MyFilter

As you see, flag `scheduler_driver` is set up for the `FilterSchedule`,
available filters can be specified more than once and description of the
default filters should not contain full paths with class names you need, only
class names.

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
.. |AvailabilityZoneFilter| replace:: :class:`AvailabilityZoneFilter <nova.scheduler.filters.availability_zone_filter.AvailabilityZoneFilter>`
.. |BaseHostFilter| replace:: :class:`BaseHostFilter <nova.scheduler.filters.BaseHostFilter>`
.. |ComputeFilter| replace:: :class:`ComputeFilter <nova.scheduler.filters.compute_filter.ComputeFilter>`
.. |CoreFilter| replace:: :class:`CoreFilter <nova.scheduler.filters.core_filter.CoreFilter>`
.. |IsolatedHostsFilter| replace:: :class:`IsolatedHostsFilter <nova.scheduler.filters.isolated_hosts_filter>`
.. |JsonFilter| replace:: :class:`JsonFilter <nova.scheduler.filters.json_filter.JsonFilter>`
.. |RamFilter| replace:: :class:`RamFilter <nova.scheduler.filters.ram_filter.RamFilter>`
.. |SimpleCIDRAffinityFilter| replace:: :class:`SimpleCIDRAffinityFilter <nova.scheduler.filters.affinity_filter.SimpleCIDRAffinityFilter>`
.. |DifferentHostFilter| replace:: :class:`DifferentHostFilter <nova.scheduler.filters.affinity_filter.DifferentHostFilter>`
.. |SameHostFilter| replace:: :class:`SameHostFilter <nova.scheduler.filters.affinity_filter.SameHostFilter>`

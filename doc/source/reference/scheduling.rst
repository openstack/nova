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

============
 Scheduling
============

This is an overview of how scheduling works in nova from Pike onwards. For
information on the scheduler itself, refer to :doc:`/user/filter-scheduler`.
For an overview of why we've changed how the scheduler works, refer to
:doc:`/reference/scheduler-evolution`.

Overview
--------

The scheduling process is described below.

.. note:: This is current as of the 16.0.0 Pike release. Any mention of
    alternative hosts passed between the scheduler and conductor(s) is future
    work.

.. actdiag::

    actdiag {
        build-spec -> send-spec -> send-reqs -> query -> return-rps ->
            create -> filter -> claim -> return-hosts -> send-hosts;

        lane conductor {
            label = "Conductor";
            build-spec [label = "Build request spec object", height = 38];
            send-spec [label = "Submit request spec to scheduler", height = 38];
            send-hosts [label = "Submit list of suitable hosts to target cell", height = 51];
        }

        lane scheduler {
            label = "Scheduler";
            send-reqs [label = "Submit resource requirements to placement", height = 64];
            create [label = "Create a HostState object for each RP returned from Placement", height = 64];
            filter [label = "Filter and weigh results", height = 38];
            return-hosts [label = "Return a list of selected host & alternates, along with their allocations, to the conductor", height = 89];
        }

        lane placement {
            label = "Placement";
            query [label = "Query to determine the RPs representing compute nodes to satisfy requirements", height = 64];
            return-rps [label = "Return list of resource providers and their corresponding allocations to scheduler", height = 89];
            claim [label = "Create allocations against selected compute node", height = 64];
        }
    }

As the above diagram illustrates, scheduling works like so:

#. Scheduler gets a request spec from the "super conductor", containing
   resource requirements. The "super conductor" operates at the top level of a
   deployment, as contrasted with the "cell conductor", which operates within a
   particular cell.

#. Scheduler sends those requirements to placement.

#. Placement runs a query to determine the resource providers (in this case,
   compute nodes) that can satisfy those requirements.

#. Placement then constructs a data structure for each compute node as
   documented in the `spec`__. The data structure contains summaries of the
   matching resource provider information for each compute node, along with the
   AllocationRequest that will be used to claim the requested resources if that
   compute node is selected.

#. Placement returns this data structure to the Scheduler.

#. The Scheduler creates HostState objects for each compute node contained in
   the provider summaries. These HostState objects contain the information
   about the host that will be used for subsequent filtering and weighing.

#. Since the request spec can specify one or more instances to be scheduled.
   The Scheduler repeats the next several steps for each requested instance.

#. Scheduler runs these HostState objects through the filters and weighers to
   further refine and rank the hosts to match the request.

#. Scheduler then selects the HostState at the top of the ranked list, and
   determines its matching AllocationRequest from the data returned by
   Placement. It uses that AllocationRequest as the body of the request sent to
   Placement to claim the resources.

#. If the claim is not successful, that indicates that another process has
   consumed those resources, and the host is no longer able to satisfy the
   request. In that event, the Scheduler moves on to the next host in the list,
   repeating the process until it is able to successfully claim the resources.

#. Once the Scheduler has found a host for which a successful claim has been
   made, it needs to select a number of "alternate" hosts. These are hosts
   from the ranked list that are in the same cell as the selected host, which
   can be used by the cell conductor in the event that the build on the
   selected host fails for some reason. The number of alternates is determined
   by the configuration option `scheduler.max_attempts`.

#. Scheduler creates two list structures for each requested instance: one for
   the hosts (selected + alternates), and the other for their matching
   AllocationRequests.

#. To create the alternates, Scheduler determines the cell of the selected
   host. It then iterates through the ranked list of HostState objects to find
   a number of additional hosts in that same cell. It adds those hosts to the
   host list, and their AllocationRequest to the allocation list.

#. Once those lists are created, the Scheduler has completed what it needs to
   do for a requested instance.

#. Scheduler repeats this process for any additional requested instances. When
   all instances have been scheduled, it creates a 2-tuple to return to the
   super conductor, with the first element of the tuple being a list of lists
   of hosts, and the second being a list of lists of the AllocationRequests.

#. Scheduler returns that 2-tuple to the super conductor.

#. For each requested instance, the super conductor determines the cell of the
   selected host. It then sends a 2-tuple of ([hosts], [AllocationRequests])
   for that instance to the target cell conductor.

#. Target cell conductor tries to build the instance on the selected host. If
   it fails, it uses the AllocationRequest data for that host to unclaim the
   resources for the selected host. It then iterates through the list of
   alternates by first attempting to claim the resources, and if successful,
   building the instance on that host. Only when all alternates fail does the
   build request fail.

__ https://specs.openstack.org/openstack/nova-specs/specs/pike/approved/placement-allocation-requests.html

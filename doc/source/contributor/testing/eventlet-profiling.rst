=======================
Profiling With Eventlet
=======================

When performance of one of the Nova services is worse than expected, and other
sorts of analysis do not lead to candidate fixes, profiling is an excellent
tool for producing detailed analysis of what methods in the code are called the
most and which consume the most time.

Because most Nova services use eventlet_, the standard profiling tool provided
with Python, cProfile_, will not work. Something is required to keep track of
changing tasks. Thankfully eventlet comes with
``eventlet.green.profile.Profile``, a mostly undocumented class that provides a
similar (but not identical) API to the one provided by Python's ``Profile``
while outputting the same format.

.. note:: The eventlet Profile outputs the ``prof`` format produced by
          ``profile``, which is not the same as that output by ``cProfile``.
          Some analysis tools (for example, SnakeViz_) only read the latter
          so the options for analyzing eventlet profiling are not always
          deluxe (see below).

Setup
=====

This guide assumes the Nova service being profiled is running devstack, but
that is not necessary. What is necessary is that the code associated with the
service can be changed and the service restarted, in place.

Profiling the entire service will produce mostly noise and the output will be
confusing because different tasks will operate during the profile run. It is
better to begin the process with a candidate task or method *within* the
service that can be associated with an identifier. For example,
``select_destinations`` in the ``SchedulerManager`` can be associated with the
list of ``instance_uuids`` passed to it and it runs only once for that set of
instance UUIDs.

The process for profiling is:

#. Identify the method to be profiled.

#. Populate the environment with sufficient resources to exercise the code. For
   example you may wish to use the FakeVirtDriver_ to have nova aware of
   multiple ``nova-compute`` processes. Or you may wish to launch many
   instances if you are evaluating a method that loops over instances.

#. At the start of that method, change the code to instantiate a ``Profile``
   object and ``start()`` it.

#. At the end of that method, change the code to ``stop()`` profiling and write
   the data (with ``dump_stats()``) to a reasonable location.

#. Restart the service.

#. Cause the method being evaluated to run.

#. Analyze the profile data with the pstats_ module.

.. note:: ``stop()`` and ``start()`` are two of the ways in which the eventlet
          ``Profile`` API differs from the stdlib. There the methods are
          ``enable()`` and ``disable()``.

Example
=======

For this example we will analyze ``select_destinations`` in the
``FilterScheduler``. A known problem is that it does excessive work when
presented with too many candidate results from the Placement service. We'd like
to know why.

We'll configure and run devstack_ with FakeVirtDriver_ so there are several
candidate hypervisors (the following ``local.conf`` is also useful for other
profiling and benchmarking scenarios so not all changes are relevant here):

.. code-block:: ini

    [[local|localrc]]
    ADMIN_PASSWORD=secret
    DATABASE_PASSWORD=$ADMIN_PASSWORD
    RABBIT_PASSWORD=$ADMIN_PASSWORD
    SERVICE_PASSWORD=$ADMIN_PASSWORD
    VIRT_DRIVER=fake
    # You may use different numbers of fake computes, but be careful: 100 will
    # completely overwhelm a 16GB, 16VPCU server. In the test profiles below a
    # value of 50 was used, on a 16GB, 16VCPU server.
    NUMBER_FAKE_NOVA_COMPUTE=25
    disable_service cinder
    disable_service horizon
    disable_service dstat
    disable_service tempest

    [[post-config|$NOVA_CONF]]
    rpc_response_timeout = 300

    # Disable filtering entirely. For some profiling this will not be what you
    # want.
    [filter_scheduler]
    enabled_filters = '""'
    # Send only one type of notifications to avoid notification overhead.
    [notifications]
    notification_format = unversioned

Change the code in ``nova/scheduler/manager.py`` as follows to start the
profiler at the start of the ``_select_destinations`` call and to dump the
statistics at the end. For example:

.. code-block:: diff

    diff --git nova/scheduler/manager.py nova/scheduler/manager.py
    index 9cee6b3bfc..4859b21fb1 100644
    --- nova/scheduler/manager.py
    +++ nova/scheduler/manager.py
    @@ -237,6 +237,10 @@ class SchedulerManager(manager.Manager):
             alloc_reqs_by_rp_uuid, provider_summaries,
             allocation_request_version=None, return_alternates=False,
         ):
    +        from eventlet.green import profile
    +        pr = profile.Profile()
    +        pr.start()
    +
             self.notifier.info(
                 context, 'scheduler.select_destinations.start',
                 {'request_spec': spec_obj.to_legacy_request_spec_dict()})
    @@ -260,6 +264,9 @@ class SchedulerManager(manager.Manager):
                 action=fields_obj.NotificationAction.SELECT_DESTINATIONS,
                 phase=fields_obj.NotificationPhase.END)

    +        pr.stop()
    +        pr.dump_stats('/tmp/select_destinations/%s.prof' % ':'.join(instance_uuids))
    +
             return selections

         def _schedule(

Make a ``/tmp/select_destinations`` directory that is writable by the user
nova-scheduler will run as. This is where the profile output will go.

Restart the scheduler service. Note that ``systemctl restart`` may not kill
things sufficiently dead, so::

    sudo systemctl stop devstack@n-sch
    sleep 5
    sudo systemctl start devstack@n-sch

Create a server (which will call ``select_destinations``)::

    openstack server create --image cirros-0.4.0-x86_64-disk --flavor c1 x1

In ``/tmp/select_destinations`` there should be a file with a name using the
UUID of the created server with a ``.prof`` extension.

Change to that directory and view the profile using the pstats
`interactive mode`_::

    python3 -m pstats ef044142-f3b8-409d-9af6-c60cea39b273.prof

.. note:: The major version of python used to analyze the profile data must be
          the same as the version used to run the process being profiled.

Sort stats by their cumulative time::

    ef044142-f3b8-409d-9af6-c60cea39b273.prof% sort cumtime
    ef044142-f3b8-409d-9af6-c60cea39b273.prof% stats 10
    Tue Aug  6 17:17:56 2019    ef044142-f3b8-409d-9af6-c60cea39b273.prof

             603477 function calls (587772 primitive calls) in 2.294 seconds

       Ordered by: cumulative time
       List reduced from 2484 to 10 due to restriction <10>

       ncalls  tottime  percall  cumtime  percall filename:lineno(function)
            1    0.000    0.000    1.957    1.957 profile:0(start)
            1    0.000    0.000    1.911    1.911 /mnt/share/opt/stack/nova/nova/scheduler/filter_scheduler.py:113(_schedule)
            1    0.000    0.000    1.834    1.834 /mnt/share/opt/stack/nova/nova/scheduler/filter_scheduler.py:485(_get_all_host_states)
            1    0.000    0.000    1.834    1.834 /mnt/share/opt/stack/nova/nova/scheduler/host_manager.py:757(get_host_states_by_uuids)
            1    0.004    0.004    1.818    1.818 /mnt/share/opt/stack/nova/nova/scheduler/host_manager.py:777(_get_host_states)
      104/103    0.001    0.000    1.409    0.014 /usr/local/lib/python3.6/dist-packages/oslo_versionedobjects/base.py:170(wrapper)
           50    0.001    0.000    1.290    0.026 /mnt/share/opt/stack/nova/nova/scheduler/host_manager.py:836(_get_instance_info)
           50    0.001    0.000    1.289    0.026 /mnt/share/opt/stack/nova/nova/scheduler/host_manager.py:820(_get_instances_by_host)
          103    0.001    0.000    0.890    0.009 /usr/local/lib/python3.6/dist-packages/sqlalchemy/orm/query.py:3325(__iter__)
           50    0.001    0.000    0.776    0.016 /mnt/share/opt/stack/nova/nova/objects/host_mapping.py:99(get_by_host)

From this we can make a couple of useful inferences about ``get_by_host``:

* It is called once for each of the 50 ``FakeVirtDriver`` hypervisors
  configured for these tests.

* It (and the methods it calls internally) consumes about 40% of the entire
  time spent running (``0.776 / 1.957``) the ``select_destinations`` method
  (indicated by ``profile:0(start)``, above).

Several other sort modes can be used. List those that are available by entering
``sort`` without arguments.

Caveats
=======

Real world use indicates that the eventlet profiler is not perfect. There are
situations where it will not always track switches between greenlets as well as
it could. This can result in profile data that does not make sense or random
slowdowns in the system being profiled. There is no one size fits all solution
to these issues; profiling eventlet services is more an art than science.
However, this section tries to provide a (hopefully) growing body of advice on
what to do to work around problems.

General Advice
--------------

* Try to profile chunks of code that operate mostly within one module or class
  and do not have many collaborators. The more convoluted the path through
  the code, the more confused the profiler gets.

* Similarly, where possible avoid profiling code that will trigger many
  greenlet context switches; either specific spawns, or multiple types of I/O.
  Instead, narrow the focus of the profiler.

* If possible, avoid RPC.

In nova-compute
---------------

The creation of this caveat section was inspired by issues experienced while
profiling ``nova-compute``. The ``nova-compute`` process is not allowed to
speak with a database server directly. Instead communication is mediated
through the conductor, communication happening via ``oslo.versionedobjects``
and remote calls. Profiling methods such as ``update_available_resource`` in
the ResourceTracker, which needs information from the database, results in
profile data that can be analyzed but is incorrect and misleading.

This can be worked around by temporarily changing ``nova-compute`` to allow it
to speak to the database directly:

.. code-block:: diff

    diff --git a/nova/cmd/compute.py b/nova/cmd/compute.py
    index 01fd20de2e..655d503158 100644
    --- a/nova/cmd/compute.py
    +++ b/nova/cmd/compute.py
    @@ -50,8 +50,10 @@ def main():

         gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)

    -    cmd_common.block_db_access('nova-compute')
    -    objects_base.NovaObject.indirection_api = conductor_rpcapi.ConductorAPI()
    +    # Temporarily allow access to the database. You must update the config file
    +    # used by this process to set [database]/connection to the cell1 database.
    +    # cmd_common.block_db_access('nova-compute')
    +    # objects_base.NovaObject.indirection_api = conductor_rpcapi.ConductorAPI()
         objects.Service.enable_min_version_cache()
         server = service.Service.create(binary='nova-compute',
                                         topic=compute_rpcapi.RPC_TOPIC)

The configuration file used by the ``nova-compute`` process must also be
updated to ensure that it contains a setting for the relevant database:

.. code-block:: ini

    [database]
    connection = mysql+pymysql://root:secret@127.0.0.1/nova_cell1?charset=utf8

In a single node devstack setup ``nova_cell1`` is the right choice. The
connection string will vary in other setups.

Once these changes are made, along with the profiler changes indicated in the
example above, ``nova-compute`` can be restarted and with luck some useful
profiling data will emerge.

.. _eventlet: https://eventlet.net/
.. _cProfile: https://docs.python.org/3/library/profile.html
.. _SnakeViz: https://jiffyclub.github.io/snakeviz/
.. _devstack: https://docs.openstack.org/devstack/latest/
.. _FakeVirtDriver: https://docs.openstack.org/devstack/latest/guides/nova.html#fake-virt-driver
.. _pstats: https://docs.python.org/3/library/profile.html#pstats.Stats
.. _interactive mode: https://www.stefaanlippens.net/python_profiling_with_pstats_interactive_mode/

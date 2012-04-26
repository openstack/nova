# Copyright (c) 2011 OpenStack, LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
The FilterScheduler is for creating instances locally.
You can customize this scheduler by specifying your own Host Filters and
Weighing Functions.
"""

import operator

from nova import exception
from nova import flags
from nova import log as logging
from nova.notifier import api as notifier
from nova.openstack.common import importutils
from nova.scheduler import driver
from nova.scheduler import least_cost
from nova.scheduler import scheduler_options


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class FilterScheduler(driver.Scheduler):
    """Scheduler that can be used for filtering and weighing."""
    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)
        self.cost_function_cache = {}
        self.options = scheduler_options.SchedulerOptions()

    def schedule(self, context, topic, method, *args, **kwargs):
        """The schedule() contract requires we return the one
        best-suited host for this request.

        NOTE: We're only focused on compute instances right now,
        so this method will always raise NoValidHost()."""
        msg = _("No host selection for %s defined.") % topic
        raise exception.NoValidHost(reason=msg)

    def schedule_run_instance(self, context, request_spec, *args, **kwargs):
        """This method is called from nova.compute.api to provision
        an instance.  We first create a build plan (a list of WeightedHosts)
        and then provision.

        Returns a list of the instances created.
        """

        elevated = context.elevated()
        num_instances = request_spec.get('num_instances', 1)
        LOG.debug(_("Attempting to build %(num_instances)d instance(s)") %
                locals())

        payload = dict(request_spec=request_spec)
        notifier.notify(context, notifier.publisher_id("scheduler"),
                        'scheduler.run_instance.start', notifier.INFO, payload)

        weighted_hosts = self._schedule(context, "compute", request_spec,
                                        *args, **kwargs)

        if not weighted_hosts:
            raise exception.NoValidHost(reason="")

        # NOTE(comstud): Make sure we do not pass this through.  It
        # contains an instance of RpcContext that cannot be serialized.
        kwargs.pop('filter_properties', None)

        instances = []
        for num in xrange(num_instances):
            if not weighted_hosts:
                break
            weighted_host = weighted_hosts.pop(0)

            request_spec['instance_properties']['launch_index'] = num
            instance = self._provision_resource(elevated, weighted_host,
                                                request_spec, kwargs)

            if instance:
                instances.append(instance)

        notifier.notify(context, notifier.publisher_id("scheduler"),
                        'scheduler.run_instance.end', notifier.INFO, payload)

        return instances

    def schedule_prep_resize(self, context, request_spec, *args, **kwargs):
        """Select a target for resize.

        Selects a target host for the instance, post-resize, and casts
        the prep_resize operation to it.
        """

        hosts = self._schedule(context, 'compute', request_spec,
                               *args, **kwargs)
        if not hosts:
            raise exception.NoValidHost(reason="")
        host = hosts.pop(0)

        # NOTE(comstud): Make sure we do not pass this through.  It
        # contains an instance of RpcContext that cannot be serialized.
        kwargs.pop('filter_properties', None)

        # Forward off to the host
        driver.cast_to_compute_host(context, host.host_state.host,
                'prep_resize', **kwargs)

    def _provision_resource(self, context, weighted_host, request_spec,
            kwargs):
        """Create the requested resource in this Zone."""
        instance = self.create_instance_db_entry(context, request_spec)

        payload = dict(request_spec=request_spec,
                       weighted_host=weighted_host.to_dict(),
                       instance_id=instance['uuid'])
        notifier.notify(context, notifier.publisher_id("scheduler"),
                        'scheduler.run_instance.scheduled', notifier.INFO,
                        payload)

        driver.cast_to_compute_host(context, weighted_host.host_state.host,
                'run_instance', instance_uuid=instance['uuid'], **kwargs)
        inst = driver.encode_instance(instance, local=True)
        # So if another instance is created, create_instance_db_entry will
        # actually create a new entry, instead of assume it's been created
        # already
        del request_spec['instance_properties']['uuid']
        return inst

    def _get_configuration_options(self):
        """Fetch options dictionary. Broken out for testing."""
        return self.options.get_configuration()

    def populate_filter_properties(self, request_spec, filter_properties):
        """Stuff things into filter_properties.  Can be overriden in a
        subclass to add more data.
        """
        pass

    def _schedule(self, context, topic, request_spec, *args, **kwargs):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()
        if topic != "compute":
            msg = _("Scheduler only understands Compute nodes (for now)")
            raise NotImplementedError(msg)

        instance_properties = request_spec['instance_properties']
        instance_type = request_spec.get("instance_type", None)

        cost_functions = self.get_cost_functions()
        config_options = self._get_configuration_options()

        filter_properties = kwargs.get('filter_properties', {})
        filter_properties.update({'context': context,
                                  'request_spec': request_spec,
                                  'config_options': config_options,
                                  'instance_type': instance_type})

        self.populate_filter_properties(request_spec,
                                        filter_properties)

        # Find our local list of acceptable hosts by repeatedly
        # filtering and weighing our options. Each time we choose a
        # host, we virtually consume resources on it so subsequent
        # selections can adjust accordingly.

        # unfiltered_hosts_dict is {host : ZoneManager.HostInfo()}
        unfiltered_hosts_dict = self.host_manager.get_all_host_states(
                elevated, topic)

        # Note: remember, we are using an iterator here. So only
        # traverse this list once. This can bite you if the hosts
        # are being scanned in a filter or weighing function.
        hosts = unfiltered_hosts_dict.itervalues()

        num_instances = request_spec.get('num_instances', 1)
        selected_hosts = []
        for num in xrange(num_instances):
            # Filter local hosts based on requirements ...
            hosts = self.host_manager.filter_hosts(hosts,
                    filter_properties)
            if not hosts:
                # Can't get any more locally.
                break

            LOG.debug(_("Filtered %(hosts)s") % locals())

            # weighted_host = WeightedHost() ... the best
            # host for the job.
            # TODO(comstud): filter_properties will also be used for
            # weighing and I plan fold weighing into the host manager
            # in a future patch.  I'll address the naming of this
            # variable at that time.
            weighted_host = least_cost.weighted_sum(cost_functions,
                    hosts, filter_properties)
            LOG.debug(_("Weighted %(weighted_host)s") % locals())
            selected_hosts.append(weighted_host)

            # Now consume the resources so the filter/weights
            # will change for the next instance.
            weighted_host.host_state.consume_from_instance(
                    instance_properties)

        selected_hosts.sort(key=operator.attrgetter('weight'))
        return selected_hosts[:num_instances]

    def get_cost_functions(self, topic=None):
        """Returns a list of tuples containing weights and cost functions to
        use for weighing hosts
        """
        if topic is None:
            # Schedulers only support compute right now.
            topic = "compute"
        if topic in self.cost_function_cache:
            return self.cost_function_cache[topic]

        cost_fns = []
        for cost_fn_str in FLAGS.least_cost_functions:
            if '.' in cost_fn_str:
                short_name = cost_fn_str.split('.')[-1]
            else:
                short_name = cost_fn_str
                cost_fn_str = "%s.%s.%s" % (
                        __name__, self.__class__.__name__, short_name)
            if not (short_name.startswith('%s_' % topic) or
                    short_name.startswith('noop')):
                continue

            try:
                # NOTE: import_class is somewhat misnamed since
                # the weighing function can be any non-class callable
                # (i.e., no 'self')
                cost_fn = importutils.import_class(cost_fn_str)
            except ImportError:
                raise exception.SchedulerCostFunctionNotFound(
                        cost_fn_str=cost_fn_str)

            try:
                flag_name = "%s_weight" % cost_fn.__name__
                weight = getattr(FLAGS, flag_name)
            except AttributeError:
                raise exception.SchedulerWeightFlagNotFound(
                        flag_name=flag_name)
            cost_fns.append((weight, cost_fn))

        self.cost_function_cache[topic] = cost_fns
        return cost_fns

# Copyright (c) 2011 Openstack, LLC.
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
The DistributedScheduler is for creating instances locally or across zones.
You can customize this scheduler by specifying your own Host Filters and
Weighing Functions.
"""

import json
import operator

import M2Crypto

from novaclient import v1_1 as novaclient
from novaclient import exceptions as novaclient_exceptions
from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.scheduler import api
from nova.scheduler import driver
from nova.scheduler import least_cost
from nova.scheduler import scheduler_options
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_list('default_host_filters', ['InstanceTypeFilter'],
        'Which filters to use for filtering hosts when not specified '
        'in the request.')

LOG = logging.getLogger('nova.scheduler.distributed_scheduler')


class InvalidBlob(exception.NovaException):
    message = _("Ill-formed or incorrectly routed 'blob' data sent "
            "to instance create request.")


class DistributedScheduler(driver.Scheduler):
    """Scheduler that can work across any nova deployment, from simple
    deployments to multiple nested zones.
    """
    def __init__(self, *args, **kwargs):
        super(DistributedScheduler, self).__init__(*args, **kwargs)
        self.cost_function_cache = {}
        self.options = scheduler_options.SchedulerOptions()

    def schedule(self, context, topic, method, *args, **kwargs):
        """The schedule() contract requires we return the one
        best-suited host for this request.

        NOTE: We're only focused on compute instances right now,
        so this method will always raise NoValidHost()."""
        msg = _("No host selection for %s defined." % topic)
        raise exception.NoValidHost(reason=msg)

    def schedule_run_instance(self, context, request_spec, *args, **kwargs):
        """This method is called from nova.compute.api to provision
        an instance. However we need to look at the parameters being
        passed in to see if this is a request to:
        1. Create build plan (a list of WeightedHosts) and then provision, or
        2. Use the WeightedHost information in the request parameters
           to simply create the instance (either in this zone or
           a child zone).

        returns a list of the instances created.
        """

        elevated = context.elevated()
        num_instances = request_spec.get('num_instances', 1)
        LOG.debug(_("Attempting to build %(num_instances)d instance(s)") %
                locals())

        weighted_hosts = []

        # Having a 'blob' hint means we've already provided a build plan.
        # We need to turn this back into a WeightedHost object.
        blob = request_spec.get('blob', None)
        if blob:
            weighted_hosts.append(self._make_weighted_host_from_blob(blob))
        else:
            # No plan ... better make one.
            weighted_hosts = self._schedule(elevated, "compute", request_spec,
                                        *args, **kwargs)

        if not weighted_hosts:
            raise exception.NoValidHost(reason=_(""))

        instances = []
        for num in xrange(num_instances):
            if not weighted_hosts:
                break
            weighted_host = weighted_hosts.pop(0)

            instance = None
            if weighted_host.host:
                instance = self._provision_resource_locally(elevated,
                                        weighted_host, request_spec, kwargs)
            else:
                instance = self._ask_child_zone_to_create_instance(elevated,
                                        weighted_host, request_spec, kwargs)

            if instance:
                instances.append(instance)

        return instances

    def schedule_prep_resize(self, context, request_spec, *args, **kwargs):
        """Select a target for resize.

        Selects a target host for the instance, post-resize, and casts
        the prep_resize operation to it.
        """

        # We need the new instance type ID...
        instance_type_id = kwargs['instance_type_id']

        elevated = context.elevated()
        LOG.debug(_("Attempting to determine target host for resize to "
                    "instance type %(instance_type_id)s") % locals())

        # Convert it to an actual instance type
        instance_type = db.instance_type_get(elevated, instance_type_id)

        # Now let's grab a possibility
        hosts = self._schedule(elevated, 'compute', request_spec,
                               *args, **kwargs)
        if not hosts:
            raise exception.NoValidHost(reason=_(""))
        host = hosts.pop(0)

        # Forward off to the host
        driver.cast_to_host(context, 'compute', host.host, 'prep_resize',
                            **kwargs)

    def select(self, context, request_spec, *args, **kwargs):
        """Select returns a list of weights and zone/host information
        corresponding to the best hosts to service the request. Any
        internal zone information will be encrypted so as not to reveal
        anything about our inner layout.
        """
        elevated = context.elevated()
        weighted_hosts = self._schedule(elevated, "compute", request_spec,
                *args, **kwargs)
        return [weighted_host.to_dict() for weighted_host in weighted_hosts]

    def _call_zone_method(self, context, method, specs, zones):
        """Call novaclient zone method. Broken out for testing."""
        return api.call_zone_method(context, method, specs=specs, zones=zones)

    def _provision_resource_locally(self, context, weighted_host, request_spec,
                                    kwargs):
        """Create the requested resource in this Zone."""
        instance = self.create_instance_db_entry(context, request_spec)
        driver.cast_to_compute_host(context, weighted_host.host,
                'run_instance', instance_uuid=instance['uuid'], **kwargs)
        inst = driver.encode_instance(instance, local=True)
        # So if another instance is created, create_instance_db_entry will
        # actually create a new entry, instead of assume it's been created
        # already
        del request_spec['instance_properties']['uuid']
        return inst

    def _make_weighted_host_from_blob(self, blob):
        """Returns the decrypted blob as a WeightedHost object
        or None if invalid. Broken out for testing.
        """
        decryptor = crypto.decryptor(FLAGS.build_plan_encryption_key)
        try:
            json_entry = decryptor(blob)
            # Extract our WeightedHost values
            wh_dict = json.loads(json_entry)
            host = wh_dict.get('host', None)
            blob = wh_dict.get('blob', None)
            zone = wh_dict.get('zone', None)
            return least_cost.WeightedHost(wh_dict['weight'],
                        host=host, blob=blob, zone=zone)

        except M2Crypto.EVP.EVPError:
            raise InvalidBlob()

    def _ask_child_zone_to_create_instance(self, context, weighted_host,
            request_spec, kwargs):
        """Once we have determined that the request should go to one
        of our children, we need to fabricate a new POST /servers/
        call with the same parameters that were passed into us.
        This request is always for a single instance.

        Note that we have to reverse engineer from our args to get back the
        image, flavor, ipgroup, etc. since the original call could have
        come in from EC2 (which doesn't use these things).
        """
        instance_type = request_spec['instance_type']
        instance_properties = request_spec['instance_properties']

        name = instance_properties['display_name']
        image_ref = instance_properties['image_ref']
        meta = instance_properties['metadata']
        flavor_id = instance_type['flavorid']
        reservation_id = instance_properties['reservation_id']
        files = kwargs['injected_files']

        zone = db.zone_get(context.elevated(), weighted_host.zone)
        zone_name = zone.name
        url = zone.api_url
        LOG.debug(_("Forwarding instance create call to zone '%(zone_name)s'. "
                "ReservationID=%(reservation_id)s") % locals())
        nova = None
        try:
            # This operation is done as the caller, not the zone admin.
            nova = novaclient.Client(zone.username, zone.password, None, url,
                                     token=context.auth_token,
                                     region_name=zone_name)
            nova.authenticate()
        except novaclient_exceptions.BadRequest, e:
            raise exception.NotAuthorized(_("Bad credentials attempting "
                    "to talk to zone at %(url)s.") % locals())
        # NOTE(Vek): Novaclient has two different calling conventions
        #            for this call, depending on whether you're using
        #            1.0 or 1.1 API: in 1.0, there's an ipgroups
        #            argument after flavor_id which isn't present in
        #            1.1.  To work around this, all the extra
        #            arguments are passed as keyword arguments
        #            (there's a reasonable default for ipgroups in the
        #            novaclient call).
        instance = nova.servers.create(name, image_ref, flavor_id,
                            meta=meta, files=files,
                            zone_blob=weighted_host.blob,
                            reservation_id=reservation_id)
        return driver.encode_instance(instance._info, local=False)

    def _adjust_child_weights(self, child_results, zones):
        """Apply the Scale and Offset values from the Zone definition
        to adjust the weights returned from the child zones. Returns
        a list of WeightedHost objects: [WeightedHost(), ...]
        """
        weighted_hosts = []
        for zone_id, result in child_results:
            if not result:
                continue

            for zone_rec in zones:
                if zone_rec['id'] != zone_id:
                    continue
                for item in result:
                    try:
                        offset = zone_rec['weight_offset']
                        scale = zone_rec['weight_scale']
                        raw_weight = item['weight']
                        cooked_weight = offset + scale * raw_weight

                        weighted_hosts.append(least_cost.WeightedHost(
                           host=None, weight=cooked_weight,
                           zone=zone_id, blob=item['blob']))
                    except KeyError:
                        LOG.exception(_("Bad child zone scaling values "
                                "for Zone: %(zone_id)s") % locals())
        return weighted_hosts

    def _zone_get_all(self, context):
        """Broken out for testing."""
        return db.zone_get_all(context)

    def _get_configuration_options(self):
        """Fetch options dictionary. Broken out for testing."""
        return self.options.get_configuration()

    def _schedule(self, elevated, topic, request_spec, *args, **kwargs):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        if topic != "compute":
            msg = _("Scheduler only understands Compute nodes (for now)")
            raise NotImplementedError(msg)

        instance_type = request_spec.get("instance_type", None)
        if not instance_type:
            msg = _("Scheduler only understands InstanceType-based" \
                    "provisioning.")
            raise NotImplementedError(msg)

        cost_functions = self.get_cost_functions()

        ram_requirement_mb = instance_type['memory_mb']
        disk_requirement_gb = instance_type['local_gb']

        options = self._get_configuration_options()

        # Find our local list of acceptable hosts by repeatedly
        # filtering and weighing our options. Each time we choose a
        # host, we virtually consume resources on it so subsequent
        # selections can adjust accordingly.

        # unfiltered_hosts_dict is {host : ZoneManager.HostInfo()}
        unfiltered_hosts_dict = self.zone_manager.get_all_host_data(elevated)
        unfiltered_hosts = unfiltered_hosts_dict.items()

        num_instances = request_spec.get('num_instances', 1)
        selected_hosts = []
        for num in xrange(num_instances):
            # Filter local hosts based on requirements ...
            filtered_hosts = self._filter_hosts(topic, request_spec,
                    unfiltered_hosts, options)

            if not filtered_hosts:
                # Can't get any more locally.
                break

            LOG.debug(_("Filtered %(filtered_hosts)s") % locals())

            # weighted_host = WeightedHost() ... the best
            # host for the job.
            weighted_host = least_cost.weighted_sum(cost_functions,
                                                filtered_hosts, options)
            LOG.debug(_("Weighted %(weighted_host)s") % locals())
            selected_hosts.append(weighted_host)

            # Now consume the resources so the filter/weights
            # will change for the next instance.
            weighted_host.hostinfo.consume_resources(disk_requirement_gb,
                                        ram_requirement_mb)

        # Next, tack on the host weights from the child zones
        if not request_spec.get('local_zone', False):
            json_spec = json.dumps(request_spec)
            all_zones = self._zone_get_all(elevated)
            child_results = self._call_zone_method(elevated, "select",
                    specs=json_spec, zones=all_zones)
            selected_hosts.extend(self._adjust_child_weights(
                                                    child_results, all_zones))
        selected_hosts.sort(key=operator.attrgetter('weight'))
        return selected_hosts[:num_instances]

    def _get_filter_classes(self):
        # Imported here to avoid circular imports
        from nova.scheduler import filters

        def get_itm(nm):
            return getattr(filters, nm)

        return [get_itm(itm) for itm in dir(filters)
                if isinstance(get_itm(itm), type)
                and issubclass(get_itm(itm), filters.AbstractHostFilter)
                and get_itm(itm) is not filters.AbstractHostFilter]

    def _choose_host_filters(self, filters=None):
        """Since the caller may specify which filters to use we need
        to have an authoritative list of what is permissible. This
        function checks the filter names against a predefined set
        of acceptable filters.
        """
        if not filters:
            filters = FLAGS.default_host_filters
        if not isinstance(filters, (list, tuple)):
            filters = [filters]
        good_filters = []
        bad_filters = []
        filter_classes = self._get_filter_classes()
        for filter_name in filters:
            found_class = False
            for cls in filter_classes:
                if cls.__name__ == filter_name:
                    good_filters.append(cls())
                    found_class = True
                    break
            if not found_class:
                bad_filters.append(filter_name)
        if bad_filters:
            msg = ", ".join(bad_filters)
            raise exception.SchedulerHostFilterNotFound(filter_name=msg)
        return good_filters

    def _filter_hosts(self, topic, request_spec, hosts, options):
        """Filter the full host list. hosts = [(host, HostInfo()), ...].
        This method returns a subset of hosts, in the same format."""
        selected_filters = self._choose_host_filters()

        # Filter out original host
        try:
            if request_spec['avoid_original_host']:
                original_host = request_spec['instance_properties']['host']
                hosts = [(h, hi) for h, hi in hosts if h != original_host]
        except (KeyError, TypeError):
            pass

        # TODO(sandy): We're only using InstanceType-based specs
        # currently. Later we'll need to snoop for more detailed
        # host filter requests.
        instance_type = request_spec.get("instance_type", None)
        if instance_type is None:
            # No way to select; return the specified hosts.
            return hosts

        for selected_filter in selected_filters:
            query = selected_filter.instance_type_to_filter(instance_type)
            hosts = selected_filter.filter_hosts(hosts, query, options)

        return hosts

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
                cost_fn = utils.import_class(cost_fn_str)
            except exception.ClassNotFound:
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

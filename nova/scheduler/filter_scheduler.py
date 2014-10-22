# Copyright (c) 2011 OpenStack Foundation
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

import random

from oslo.config import cfg

from nova.compute import rpcapi as compute_rpcapi
from nova import exception
from nova.i18n import _, _LW
from nova import objects
from nova.openstack.common import log as logging
from nova import rpc
from nova.scheduler import driver
from nova.scheduler import scheduler_options
from nova.scheduler import utils as scheduler_utils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


filter_scheduler_opts = [
    cfg.IntOpt('scheduler_host_subset_size',
               default=1,
               help='New instances will be scheduled on a host chosen '
                    'randomly from a subset of the N best hosts. This '
                    'property defines the subset size that a host is '
                    'chosen from. A value of 1 chooses the '
                    'first host returned by the weighing functions. '
                    'This value must be at least 1. Any value less than 1 '
                    'will be ignored, and 1 will be used instead')
]

CONF.register_opts(filter_scheduler_opts)


class FilterScheduler(driver.Scheduler):
    """Scheduler that can be used for filtering and weighing."""
    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)
        self.options = scheduler_options.SchedulerOptions()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.notifier = rpc.get_notifier('scheduler')
        self._supports_affinity = scheduler_utils.validate_filter(
            'ServerGroupAffinityFilter')
        self._supports_anti_affinity = scheduler_utils.validate_filter(
            'ServerGroupAntiAffinityFilter')

    # NOTE(alaski): Remove this method when the scheduler rpc interface is
    # bumped to 4.x as it is no longer used.
    def schedule_run_instance(self, context, request_spec,
                              admin_password, injected_files,
                              requested_networks, is_first_time,
                              filter_properties, legacy_bdm_in_spec):
        """Provisions instances that needs to be scheduled

        Applies filters and weighters on request properties to get a list of
        compute hosts and calls them to spawn instance(s).
        """
        payload = dict(request_spec=request_spec)
        self.notifier.info(context, 'scheduler.run_instance.start', payload)

        instance_uuids = request_spec.get('instance_uuids')
        LOG.info(_("Attempting to build %(num_instances)d instance(s) "
                    "uuids: %(instance_uuids)s"),
                  {'num_instances': len(instance_uuids),
                   'instance_uuids': instance_uuids})
        LOG.debug("Request Spec: %s" % request_spec)

        # check retry policy.  Rather ugly use of instance_uuids[0]...
        # but if we've exceeded max retries... then we really only
        # have a single instance.
        scheduler_utils.populate_retry(filter_properties,
                                       instance_uuids[0])
        weighed_hosts = self._schedule(context, request_spec,
                                       filter_properties)

        # NOTE: Pop instance_uuids as individual creates do not need the
        # set of uuids. Do not pop before here as the upper exception
        # handler fo NoValidHost needs the uuid to set error state
        instance_uuids = request_spec.pop('instance_uuids')

        # NOTE(comstud): Make sure we do not pass this through.  It
        # contains an instance of RpcContext that cannot be serialized.
        filter_properties.pop('context', None)

        for num, instance_uuid in enumerate(instance_uuids):
            request_spec['instance_properties']['launch_index'] = num

            try:
                try:
                    weighed_host = weighed_hosts.pop(0)
                    LOG.info(_("Choosing host %(weighed_host)s "
                                "for instance %(instance_uuid)s"),
                              {'weighed_host': weighed_host,
                               'instance_uuid': instance_uuid})
                except IndexError:
                    raise exception.NoValidHost(reason="")

                self._provision_resource(context, weighed_host,
                                         request_spec,
                                         filter_properties,
                                         requested_networks,
                                         injected_files, admin_password,
                                         is_first_time,
                                         instance_uuid=instance_uuid,
                                         legacy_bdm_in_spec=legacy_bdm_in_spec)
            except Exception as ex:
                # NOTE(vish): we don't reraise the exception here to make sure
                #             that all instances in the request get set to
                #             error properly
                driver.handle_schedule_error(context, ex, instance_uuid,
                                             request_spec)
            # scrub retry host list in case we're scheduling multiple
            # instances:
            retry = filter_properties.get('retry', {})
            retry['hosts'] = []

        self.notifier.info(context, 'scheduler.run_instance.end', payload)

    def select_destinations(self, context, request_spec, filter_properties):
        """Selects a filtered set of hosts and nodes."""
        self.notifier.info(context, 'scheduler.select_destinations.start',
                           dict(request_spec=request_spec))

        num_instances = request_spec['num_instances']
        selected_hosts = self._schedule(context, request_spec,
                                        filter_properties)

        # Couldn't fulfill the request_spec
        if len(selected_hosts) < num_instances:
            # Log the details but don't put those into the reason since
            # we don't want to give away too much information about our
            # actual environment.
            LOG.debug('There are %(hosts)d hosts available but '
                      '%(num_instances)d instances requested to build.',
                      {'hosts': len(selected_hosts),
                       'num_instances': num_instances})

            reason = _('There are not enough hosts available.')
            raise exception.NoValidHost(reason=reason)

        dests = [dict(host=host.obj.host, nodename=host.obj.nodename,
                      limits=host.obj.limits) for host in selected_hosts]

        self.notifier.info(context, 'scheduler.select_destinations.end',
                           dict(request_spec=request_spec))
        return dests

    def _provision_resource(self, context, weighed_host, request_spec,
            filter_properties, requested_networks, injected_files,
            admin_password, is_first_time, instance_uuid=None,
            legacy_bdm_in_spec=True):
        """Create the requested resource in this Zone."""
        # NOTE(vish): add our current instance back into the request spec
        request_spec['instance_uuids'] = [instance_uuid]
        payload = dict(request_spec=request_spec,
                       weighted_host=weighed_host.to_dict(),
                       instance_id=instance_uuid)
        self.notifier.info(context,
                           'scheduler.run_instance.scheduled', payload)

        # Update the metadata if necessary
        try:
            updated_instance = driver.instance_update_db(context,
                                                         instance_uuid)
        except exception.InstanceNotFound:
            LOG.warning(_LW("Instance disappeared during scheduling"),
                        context=context, instance_uuid=instance_uuid)

        else:
            scheduler_utils.populate_filter_properties(filter_properties,
                    weighed_host.obj)

            self.compute_rpcapi.run_instance(context,
                    instance=updated_instance,
                    host=weighed_host.obj.host,
                    request_spec=request_spec,
                    filter_properties=filter_properties,
                    requested_networks=requested_networks,
                    injected_files=injected_files,
                    admin_password=admin_password, is_first_time=is_first_time,
                    node=weighed_host.obj.nodename,
                    legacy_bdm_in_spec=legacy_bdm_in_spec)

    def _get_configuration_options(self):
        """Fetch options dictionary. Broken out for testing."""
        return self.options.get_configuration()

    def populate_filter_properties(self, request_spec, filter_properties):
        """Stuff things into filter_properties.  Can be overridden in a
        subclass to add more data.
        """
        # Save useful information from the request spec for filter processing:
        project_id = request_spec['instance_properties']['project_id']
        os_type = request_spec['instance_properties']['os_type']
        filter_properties['project_id'] = project_id
        filter_properties['os_type'] = os_type

    def _setup_instance_group(self, context, filter_properties):
        """Update filter_properties with server group info.

        :returns: True if filter_properties has been updated, False if not.
        """
        scheduler_hints = filter_properties.get('scheduler_hints') or {}
        group_hint = scheduler_hints.get('group', None)
        if not group_hint:
            return False

        group = objects.InstanceGroup.get_by_hint(context, group_hint)
        policies = set(('anti-affinity', 'affinity'))
        if not any((policy in policies) for policy in group.policies):
            return False

        if ('affinity' in group.policies and
                not self._supports_affinity):
            msg = _("ServerGroupAffinityFilter not configured")
            LOG.error(msg)
            raise exception.NoValidHost(reason=msg)
        if ('anti-affinity' in group.policies and
                not self._supports_anti_affinity):
            msg = _("ServerGroupAntiAffinityFilter not configured")
            LOG.error(msg)
            raise exception.NoValidHost(reason=msg)

        filter_properties.setdefault('group_hosts', set())
        user_hosts = set(filter_properties['group_hosts'])
        group_hosts = set(group.get_hosts(context))
        filter_properties['group_hosts'] = user_hosts | group_hosts
        filter_properties['group_policies'] = group.policies

        return True

    def _schedule(self, context, request_spec, filter_properties):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()
        instance_properties = request_spec['instance_properties']
        instance_type = request_spec.get("instance_type", None)
        instance_uuids = request_spec.get("instance_uuids", None)

        update_group_hosts = self._setup_instance_group(context,
                filter_properties)

        config_options = self._get_configuration_options()

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

        # Note: remember, we are using an iterator here. So only
        # traverse this list once. This can bite you if the hosts
        # are being scanned in a filter or weighing function.
        hosts = self._get_all_host_states(elevated)

        selected_hosts = []
        if instance_uuids:
            num_instances = len(instance_uuids)
        else:
            num_instances = request_spec.get('num_instances', 1)
        for num in xrange(num_instances):
            # Filter local hosts based on requirements ...
            hosts = self.host_manager.get_filtered_hosts(hosts,
                    filter_properties, index=num)
            if not hosts:
                # Can't get any more locally.
                break

            LOG.debug("Filtered %(hosts)s", {'hosts': hosts})

            weighed_hosts = self.host_manager.get_weighed_hosts(hosts,
                    filter_properties)

            LOG.debug("Weighed %(hosts)s", {'hosts': weighed_hosts})

            scheduler_host_subset_size = CONF.scheduler_host_subset_size
            if scheduler_host_subset_size > len(weighed_hosts):
                scheduler_host_subset_size = len(weighed_hosts)
            if scheduler_host_subset_size < 1:
                scheduler_host_subset_size = 1

            chosen_host = random.choice(
                weighed_hosts[0:scheduler_host_subset_size])
            selected_hosts.append(chosen_host)

            # Now consume the resources so the filter/weights
            # will change for the next instance.
            # NOTE (baoli) adding and deleting pci_requests is a temporary
            # fix to avoid DB access in consume_from_instance() while getting
            # pci_requests. The change can be removed once pci_requests is
            # part of the instance object that is passed into the scheduler
            # APIs
            pci_requests = filter_properties.get('pci_requests')
            if pci_requests:
                instance_properties['pci_requests'] = pci_requests
            chosen_host.obj.consume_from_instance(instance_properties)
            if pci_requests:
                del instance_properties['pci_requests']
            if update_group_hosts is True:
                filter_properties['group_hosts'].add(chosen_host.obj.host)
        return selected_hosts

    def _get_all_host_states(self, context):
        """Template method, so a subclass can implement caching."""
        return self.host_manager.get_all_host_states(context)

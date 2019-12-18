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

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import availability_zones
from nova.compute import utils as compute_utils
from nova.conductor.tasks import base
from nova.conductor.tasks import cross_cell_migrate
from nova import exception
from nova.i18n import _
from nova import objects
from nova.scheduler.client import report
from nova.scheduler import utils as scheduler_utils

LOG = logging.getLogger(__name__)


def replace_allocation_with_migration(context, instance, migration):
    """Replace instance's allocation with one for a migration.

    :raises: keystoneauth1.exceptions.base.ClientException on failure to
             communicate with the placement API
    :raises: ConsumerAllocationRetrievalFailed if reading the current
             allocation from placement fails
    :raises: ComputeHostNotFound if the host of the instance is not found in
             the databse
    :raises: AllocationMoveFailed if moving the allocation from the
             instance.uuid to the migration.uuid fails due to parallel
             placement operation on the instance consumer
    :raises: NoValidHost if placement rejectes the update for other reasons
             (e.g. not enough resources)
    :returns: (source_compute_node, migration_allocation)
    """
    try:
        source_cn = objects.ComputeNode.get_by_host_and_nodename(
            context, instance.host, instance.node)
    except exception.ComputeHostNotFound:
        LOG.error('Unable to find record for source '
                  'node %(node)s on %(host)s',
                  {'host': instance.host, 'node': instance.node},
                  instance=instance)
        # A generic error like this will just error out the migration
        # and do any rollback required
        raise

    reportclient = report.SchedulerReportClient()

    orig_alloc = reportclient.get_allocs_for_consumer(
        context, instance.uuid)['allocations']
    root_alloc = orig_alloc.get(source_cn.uuid, {}).get('resources', {})
    if not root_alloc:
        LOG.debug('Unable to find existing allocations for instance on '
                  'source compute node: %s. This is normal if you are not '
                  'using the FilterScheduler.', source_cn.uuid,
                  instance=instance)
        return None, None

    # FIXME(gibi): This method is flawed in that it does not handle allocations
    # against sharing providers in any special way. This leads to duplicate
    # allocations against the sharing provider during migration.
    success = reportclient.move_allocations(context, instance.uuid,
                                            migration.uuid)
    if not success:
        LOG.error('Unable to replace resource claim on source '
                  'host %(host)s node %(node)s for instance',
                  {'host': instance.host,
                   'node': instance.node},
                  instance=instance)
        # Mimic the "no space" error that could have come from the
        # scheduler. Once we have an atomic replace operation, this
        # would be a severe error.
        raise exception.NoValidHost(
            reason=_('Unable to replace instance claim on source'))
    else:
        LOG.debug('Created allocations for migration %(mig)s on %(rp)s',
                  {'mig': migration.uuid, 'rp': source_cn.uuid})

    return source_cn, orig_alloc


def revert_allocation_for_migration(context, source_cn, instance, migration):
    """Revert an allocation made for a migration back to the instance."""

    reportclient = report.SchedulerReportClient()

    # FIXME(gibi): This method is flawed in that it does not handle allocations
    # against sharing providers in any special way. This leads to duplicate
    # allocations against the sharing provider during migration.
    success = reportclient.move_allocations(context, migration.uuid,
                                            instance.uuid)
    if not success:
        LOG.error('Unable to replace resource claim on source '
                  'host %(host)s node %(node)s for instance',
                  {'host': instance.host,
                   'node': instance.node},
                  instance=instance)
    else:
        LOG.debug('Created allocations for instance %(inst)s on %(rp)s',
                  {'inst': instance.uuid, 'rp': source_cn.uuid})


class MigrationTask(base.TaskBase):
    def __init__(self, context, instance, flavor,
                 request_spec, clean_shutdown, compute_rpcapi,
                 query_client, report_client, host_list, network_api):
        super(MigrationTask, self).__init__(context, instance)
        self.clean_shutdown = clean_shutdown
        self.request_spec = request_spec
        self.flavor = flavor

        self.compute_rpcapi = compute_rpcapi
        self.query_client = query_client
        self.reportclient = report_client
        self.host_list = host_list
        self.network_api = network_api

        # Persist things from the happy path so we don't have to look
        # them up if we need to roll back
        self._migration = None
        self._held_allocations = None
        self._source_cn = None

    def _preallocate_migration(self):
        # If this is a rescheduled migration, don't create a new record.
        migration_type = ("resize" if self.instance.flavor.id != self.flavor.id
                else "migration")
        filters = {"instance_uuid": self.instance.uuid,
                   "migration_type": migration_type,
                   "status": "pre-migrating"}
        migrations = objects.MigrationList.get_by_filters(self.context,
                filters).objects
        if migrations:
            migration = migrations[0]
        else:
            migration = objects.Migration(context=self.context.elevated())
            migration.old_instance_type_id = self.instance.flavor.id
            migration.new_instance_type_id = self.flavor.id
            migration.status = 'pre-migrating'
            migration.instance_uuid = self.instance.uuid
            migration.source_compute = self.instance.host
            migration.source_node = self.instance.node
            migration.migration_type = migration_type
            migration.create()

        self._migration = migration

        self._source_cn, self._held_allocations = (
            replace_allocation_with_migration(self.context,
                                              self.instance,
                                              self._migration))

        return migration

    def _set_requested_destination_cell(self, legacy_props):
        instance_mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.context, self.instance.uuid)
        if not ('requested_destination' in self.request_spec and
                self.request_spec.requested_destination):
            self.request_spec.requested_destination = objects.Destination()
        targeted = 'host' in self.request_spec.requested_destination
        # NOTE(mriedem): If the user is allowed to perform a cross-cell resize
        # then add the current cell to the request spec as "preferred" so the
        # scheduler will (by default) weigh hosts within the current cell over
        # hosts in another cell, all other things being equal. If the user is
        # not allowed to perform cross-cell resize, then we limit the request
        # spec and tell the scheduler to only look at hosts in the current
        # cell.
        cross_cell_allowed = (
            self.request_spec.requested_destination.allow_cross_cell_move)
        if targeted and cross_cell_allowed:
            # If a target host is specified it might be in another cell so
            # we cannot restrict the cell in this case. We would not prefer
            # the source cell in that case either since we know where the
            # user wants it to go. We just let the scheduler figure it out.
            self.request_spec.requested_destination.cell = None
        else:
            self.request_spec.requested_destination.cell = (
                instance_mapping.cell_mapping)

        # NOTE(takashin): In the case that the target host is specified,
        # if the migration is failed, it is not necessary to retry
        # the cold migration to the same host. So make sure that
        # reschedule will not occur.
        if targeted:
            legacy_props.pop('retry', None)
            self.request_spec.retry = None

        # Log our plan before calling the scheduler.
        if cross_cell_allowed and targeted:
            LOG.debug('Not restricting cell for targeted cold migration.',
                      instance=self.instance)
        elif cross_cell_allowed:
            LOG.debug('Allowing migration from cell %(cell)s',
                      {'cell': instance_mapping.cell_mapping.identity},
                      instance=self.instance)
        else:
            LOG.debug('Restricting to cell %(cell)s while migrating',
                      {'cell': instance_mapping.cell_mapping.identity},
                      instance=self.instance)

    def _is_selected_host_in_source_cell(self, selection):
        """Checks if the given Selection is in the same cell as the instance

        :param selection: Selection object returned from the scheduler
            ``select_destinations`` method.
        :returns: True if the host Selection is in the same cell as the
            instance, False otherwise.
        """
        # Note that the context is already targeted to the current cell in
        # which the instance exists.
        same_cell = selection.cell_uuid == self.context.cell_uuid
        if not same_cell:
            LOG.debug('Selected target host %s is in cell %s and instance is '
                      'in cell: %s', selection.service_host,
                      selection.cell_uuid, self.context.cell_uuid,
                      instance=self.instance)
        return same_cell

    def _support_resource_request(self, selection):
        """Returns true if the host is new enough to support resource request
        during migration and that the RPC API version is not pinned during
        rolling upgrade.
        """
        svc = objects.Service.get_by_host_and_binary(
            self.context, selection.service_host, 'nova-compute')
        return (svc.version >= 39 and
                self.compute_rpcapi.supports_resize_with_qos_port(
                    self.context))

    # TODO(gibi): Remove this compat code when nova doesn't need to support
    # Train computes any more.
    def _get_host_supporting_request(self, selection_list):
        """Return the first compute selection from the selection_list where
        the service is new enough to support resource request during migration
        and the resources claimed successfully.

        :param selection_list: a list of Selection objects returned by the
            scheduler
        :return: A two tuple. The first item is a Selection object
            representing the host that supports the request. The second item
            is a list of Selection objects representing the remaining alternate
            hosts.
        :raises MaxRetriesExceeded: if none of the hosts in the selection_list
            is new enough to support the request or we cannot claim resource
            on any of the hosts that are new enough.
        """

        if not self.request_spec.requested_resources:
            return selection_list[0], selection_list[1:]

        # Scheduler allocated resources on the first host. So check if the
        # first host is new enough
        if self._support_resource_request(selection_list[0]):
            return selection_list[0], selection_list[1:]

        # First host is old, so we need to use an alternate. Therefore we have
        # to remove the allocation from the first host.
        self.reportclient.delete_allocation_for_instance(
            self.context, self.instance.uuid)
        LOG.debug(
            'Scheduler returned host %(host)s as a possible migration target '
            'but that host is not new enough to support the migration with '
            'resource request %(request)s or the compute RPC is pinned to '
            'less than 5.2. Trying alternate hosts.',
            {'host': selection_list[0].service_host,
             'request': self.request_spec.requested_resources},
            instance=self.instance)

        alternates = selection_list[1:]

        for i, selection in enumerate(alternates):
            if self._support_resource_request(selection):
                # this host is new enough so we need to try to claim resources
                # on it
                if selection.allocation_request:
                    alloc_req = jsonutils.loads(
                        selection.allocation_request)
                    resource_claimed = scheduler_utils.claim_resources(
                        self.context, self.reportclient, self.request_spec,
                        self.instance.uuid, alloc_req,
                        selection.allocation_request_version)

                    if not resource_claimed:
                        LOG.debug(
                            'Scheduler returned alternate host %(host)s as a '
                            'possible migration target but resource claim '
                            'failed on that host. Trying another alternate.',
                            {'host': selection.service_host},
                            instance=self.instance)
                    else:
                        return selection, alternates[i + 1:]

                else:
                    # Some deployments use different schedulers that do not
                    # use Placement, so they will not have an
                    # allocation_request to claim with. For those cases,
                    # there is no concept of claiming, so just assume that
                    # the resources are available.
                    return selection, alternates[i + 1:]

            else:
                LOG.debug(
                    'Scheduler returned alternate host %(host)s as a possible '
                    'migration target but that host is not new enough to '
                    'support the migration with resource request %(request)s '
                    'or the compute RPC is pinned to less than 5.2. '
                    'Trying another alternate.',
                    {'host': selection.service_host,
                     'request': self.request_spec.requested_resources},
                    instance=self.instance)

        # if we reach this point then none of the hosts was new enough for the
        # request or we failed to claim resources on every alternate
        reason = ("Exhausted all hosts available during compute service level "
                  "check for instance %(instance_uuid)s." %
                  {"instance_uuid": self.instance.uuid})
        raise exception.MaxRetriesExceeded(reason=reason)

    def _execute(self):
        # NOTE(sbauza): Force_hosts/nodes needs to be reset if we want to make
        # sure that the next destination is not forced to be the original host.
        # This needs to be done before the populate_retry call otherwise
        # retries will be disabled if the server was created with a forced
        # host/node.
        self.request_spec.reset_forced_destinations()

        # TODO(sbauza): Remove once all the scheduler.utils methods accept a
        # RequestSpec object in the signature.
        legacy_props = self.request_spec.to_legacy_filter_properties_dict()
        scheduler_utils.setup_instance_group(self.context, self.request_spec)
        # If a target host is set in a requested destination,
        # 'populate_retry' need not be executed.
        if not ('requested_destination' in self.request_spec and
                    self.request_spec.requested_destination and
                        'host' in self.request_spec.requested_destination):
            scheduler_utils.populate_retry(legacy_props,
                                           self.instance.uuid)

        port_res_req = self.network_api.get_requested_resource_for_instance(
            self.context, self.instance.uuid)
        # NOTE(gibi): When cyborg or other module wants to handle similar
        # non-nova resources then here we have to collect all the external
        # resource requests in a single list and add them to the RequestSpec.
        self.request_spec.requested_resources = port_res_req

        self._set_requested_destination_cell(legacy_props)

        # Once _preallocate_migration() is done, the source node allocation is
        # moved from the instance consumer to the migration record consumer,
        # and the instance consumer doesn't have any allocations. If this is
        # the first time through here (not a reschedule), select_destinations
        # below will allocate resources on the selected destination node for
        # the instance consumer. If we're rescheduling, host_list is not None
        # and we'll call claim_resources for the instance and the selected
        # alternate. If we exhaust our alternates and raise MaxRetriesExceeded,
        # the rollback() method should revert the allocation swaparoo and move
        # the source node allocation from the migration record back to the
        # instance record.
        migration = self._preallocate_migration()

        self.request_spec.ensure_project_and_user_id(self.instance)
        self.request_spec.ensure_network_metadata(self.instance)
        compute_utils.heal_reqspec_is_bfv(
            self.context, self.request_spec, self.instance)
        # On an initial call to migrate, 'self.host_list' will be None, so we
        # have to call the scheduler to get a list of acceptable hosts to
        # migrate to. That list will consist of a selected host, along with
        # zero or more alternates. On a reschedule, though, the alternates will
        # be passed to this object and stored in 'self.host_list', so we can
        # pop the first alternate from the list to use for the destination, and
        # pass the remaining alternates to the compute.
        if self.host_list is None:
            selection = self._schedule()
            if not self._is_selected_host_in_source_cell(selection):
                # If the selected host is in another cell, we need to execute
                # another task to do the cross-cell migration.
                LOG.info('Executing cross-cell resize task starting with '
                         'target host: %s', selection.service_host,
                         instance=self.instance)
                task = cross_cell_migrate.CrossCellMigrationTask(
                    self.context, self.instance, self.flavor,
                    self.request_spec, self._migration, self.compute_rpcapi,
                    selection, self.host_list)
                task.execute()
                return
        else:
            # This is a reschedule that will use the supplied alternate hosts
            # in the host_list as destinations.
            selection = self._reschedule()

        scheduler_utils.populate_filter_properties(legacy_props, selection)

        (host, node) = (selection.service_host, selection.nodename)

        # The availability_zone field was added in v1.1 of the Selection
        # object so make sure to handle the case where it is missing.
        if 'availability_zone' in selection:
            self.instance.availability_zone = selection.availability_zone
        else:
            self.instance.availability_zone = (
                availability_zones.get_host_availability_zone(
                    self.context, host))

        LOG.debug("Calling prep_resize with selected host: %s; "
                  "Selected node: %s; Alternates: %s", host, node,
                  self.host_list, instance=self.instance)
        # RPC cast to the destination host to start the migration process.
        self.compute_rpcapi.prep_resize(
            # NOTE(mriedem): Using request_spec.image here is potentially
            # dangerous if it is not kept up to date (i.e. rebuild/unshelve);
            # seems like the sane thing to do would be to pass the current
            # instance.image_meta since that is what MoveClaim will use for
            # any NUMA topology claims on the destination host...
            self.context, self.instance, self.request_spec.image,
            self.flavor, host, migration,
            request_spec=self.request_spec, filter_properties=legacy_props,
            node=node, clean_shutdown=self.clean_shutdown,
            host_list=self.host_list)

    def _schedule(self):
        selection_lists = self.query_client.select_destinations(
            self.context, self.request_spec, [self.instance.uuid],
            return_objects=True, return_alternates=True)
        # Since there is only ever one instance to migrate per call, we
        # just need the first returned element.
        selection_list = selection_lists[0]

        selection, self.host_list = self._get_host_supporting_request(
            selection_list)

        scheduler_utils.fill_provider_mapping(self.request_spec, selection)
        return selection

    def _reschedule(self):
        # Since the resources on these alternates may have been consumed and
        # might not be able to support the migrated instance, we need to first
        # claim the resources to verify the host still has sufficient
        # available resources.
        elevated = self.context.elevated()
        host_available = False
        selection = None
        while self.host_list and not host_available:
            selection = self.host_list.pop(0)
            if (self.request_spec.requested_resources and not
                    self._support_resource_request(selection)):
                LOG.debug(
                    'Scheduler returned alternate host %(host)s as a possible '
                    'migration target for re-schedule but that host is not '
                    'new enough to support the migration with resource '
                    'request %(request)s. Trying another alternate.',
                    {'host': selection.service_host,
                     'request': self.request_spec.requested_resources},
                    instance=self.instance)
                continue
            if selection.allocation_request:
                alloc_req = jsonutils.loads(selection.allocation_request)
            else:
                alloc_req = None
            if alloc_req:
                # If this call succeeds, the resources on the destination
                # host will be claimed by the instance.
                host_available = scheduler_utils.claim_resources(
                    elevated, self.reportclient, self.request_spec,
                    self.instance.uuid, alloc_req,
                    selection.allocation_request_version)
                if host_available:
                    scheduler_utils.fill_provider_mapping(
                        self.request_spec, selection)
            else:
                # Some deployments use different schedulers that do not
                # use Placement, so they will not have an
                # allocation_request to claim with. For those cases,
                # there is no concept of claiming, so just assume that
                # the host is valid.
                host_available = True
        # There are no more available hosts. Raise a MaxRetriesExceeded
        # exception in that case.
        if not host_available:
            reason = ("Exhausted all hosts available for retrying build "
                      "failures for instance %(instance_uuid)s." %
                      {"instance_uuid": self.instance.uuid})
            raise exception.MaxRetriesExceeded(reason=reason)
        return selection

    def rollback(self, ex):
        if self._migration:
            self._migration.status = 'error'
            self._migration.save()

        if not self._held_allocations:
            return

        # NOTE(danms): We created new-style migration-based
        # allocations for the instance, but failed before we kicked
        # off the migration in the compute. Normally the latter would
        # do that cleanup but we never got that far, so do it here and
        # now.

        revert_allocation_for_migration(self.context, self._source_cn,
                                        self.instance, self._migration)

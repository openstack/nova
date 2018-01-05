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
from nova.conductor.tasks import base
from nova import exception
from nova.i18n import _
from nova import objects
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils

LOG = logging.getLogger(__name__)


def replace_allocation_with_migration(context, instance, migration):
    """Replace instance's allocation with one for a migration.

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

    schedclient = scheduler_client.SchedulerClient()
    reportclient = schedclient.reportclient

    orig_alloc = reportclient.get_allocations_for_consumer_by_provider(
        context, source_cn.uuid, instance.uuid)
    if not orig_alloc:
        LOG.debug('Unable to find existing allocations for instance on '
                  'source compute node: %s. This is normal if you are not '
                  'using the FilterScheduler.', source_cn.uuid,
                  instance=instance)
        return None, None

    # FIXME(danms): This method is flawed in that it asssumes allocations
    # against only one provider. So, this may overwite allocations against
    # a shared provider, if we had one.
    success = reportclient.set_and_clear_allocations(
        context, source_cn.uuid, migration.uuid, orig_alloc,
        instance.project_id, instance.user_id, consumer_to_clear=instance.uuid)
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


def revert_allocation_for_migration(context, source_cn, instance, migration,
                                    orig_alloc):
    """Revert an allocation made for a migration back to the instance."""

    schedclient = scheduler_client.SchedulerClient()
    reportclient = schedclient.reportclient

    # FIXME(danms): This method is flawed in that it asssumes allocations
    # against only one provider. So, this may overwite allocations against
    # a shared provider, if we had one.
    success = reportclient.set_and_clear_allocations(
        context, source_cn.uuid, instance.uuid, orig_alloc,
        instance.project_id, instance.user_id,
        consumer_to_clear=migration.uuid)
    if not success:
        LOG.error('Unable to replace resource claim on source '
                  'host %(host)s node %(node)s for instance',
                  {'host': instance.host,
                   'node': instance.node},
                  instance=instance)
    else:
        LOG.debug('Created allocations for instance %(inst)s on %(rp)s',
                  {'inst': instance.uuid, 'rp': source_cn.uuid})


def should_do_migration_allocation(context):
    minver = objects.Service.get_minimum_version_multi(context,
                                                       ['nova-compute'])
    return minver >= 23


class MigrationTask(base.TaskBase):
    def __init__(self, context, instance, flavor,
                 request_spec, clean_shutdown, compute_rpcapi,
                 scheduler_client, host_list):
        super(MigrationTask, self).__init__(context, instance)
        self.clean_shutdown = clean_shutdown
        self.request_spec = request_spec
        self.flavor = flavor

        self.compute_rpcapi = compute_rpcapi
        self.scheduler_client = scheduler_client
        self.reportclient = scheduler_client.reportclient
        self.host_list = host_list

        # Persist things from the happy path so we don't have to look
        # them up if we need to roll back
        self._migration = None
        self._held_allocations = None
        self._source_cn = None

    def _preallocate_migration(self):
        if not should_do_migration_allocation(self.context):
            # NOTE(danms): We can't pre-create the migration since we have
            # old computes. Let the compute do it (legacy behavior).
            return None

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

    def _execute(self):
        # TODO(sbauza): Remove that once prep_resize() accepts a  RequestSpec
        # object in the signature and all the scheduler.utils methods too
        legacy_spec = self.request_spec.to_legacy_request_spec_dict()
        legacy_props = self.request_spec.to_legacy_filter_properties_dict()
        scheduler_utils.setup_instance_group(self.context, self.request_spec)
        # If a target host is set in a requested destination,
        # 'populate_retry' need not be executed.
        if not ('requested_destination' in self.request_spec and
                    self.request_spec.requested_destination and
                        'host' in self.request_spec.requested_destination):
            scheduler_utils.populate_retry(legacy_props,
                                           self.instance.uuid)

        # NOTE(sbauza): Force_hosts/nodes needs to be reset
        # if we want to make sure that the next destination
        # is not forced to be the original host
        self.request_spec.reset_forced_destinations()

        # NOTE(danms): Right now we only support migrate to the same
        # cell as the current instance, so request that the scheduler
        # limit thusly.
        instance_mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.context, self.instance.uuid)
        LOG.debug('Requesting cell %(cell)s while migrating',
                  {'cell': instance_mapping.cell_mapping.identity},
                  instance=self.instance)
        if ('requested_destination' in self.request_spec and
                self.request_spec.requested_destination):
            self.request_spec.requested_destination.cell = (
                instance_mapping.cell_mapping)
            # NOTE(takashin): In the case that the target host is specified,
            # if the migration is failed, it is not necessary to retry
            # the cold migration to the same host. So make sure that
            # reschedule will not occur.
            if 'host' in self.request_spec.requested_destination:
                legacy_props.pop('retry', None)
                self.request_spec.retry = None
        else:
            self.request_spec.requested_destination = objects.Destination(
                cell=instance_mapping.cell_mapping)

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

        self.request_spec.ensure_project_id(self.instance)
        # On an initial call to migrate, 'self.host_list' will be None, so we
        # have to call the scheduler to get a list of acceptable hosts to
        # migrate to. That list will consist of a selected host, along with
        # zero or more alternates. On a reschedule, though, the alternates will
        # be passed to this object and stored in 'self.host_list', so we can
        # pop the first alternate from the list to use for the destination, and
        # pass the remaining alternates to the compute.
        if self.host_list is None:
            selection_lists = self.scheduler_client.select_destinations(
                    self.context, self.request_spec, [self.instance.uuid],
                    return_objects=True, return_alternates=True)
            # Since there is only ever one instance to migrate per call, we
            # just need the first returned element.
            selection_list = selection_lists[0]
            # The selected host is the first item in the list, with the
            # alternates being the remainder of the list.
            selection, self.host_list = selection_list[0], selection_list[1:]
        else:
            # This is a reschedule that will use the supplied alternate hosts
            # in the host_list as destinations. Since the resources on these
            # alternates may have been consumed and might not be able to
            # support the migrated instance, we need to first claim the
            # resources to verify the host still has sufficient availabile
            # resources.
            elevated = self.context.elevated()
            host_available = False
            while self.host_list and not host_available:
                selection = self.host_list.pop(0)
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

        scheduler_utils.populate_filter_properties(legacy_props, selection)
        # context is not serializable
        legacy_props.pop('context', None)

        (host, node) = (selection.service_host, selection.nodename)

        self.instance.availability_zone = (
            availability_zones.get_host_availability_zone(
                self.context, host))

        # FIXME(sbauza): Serialize/Unserialize the legacy dict because of
        # oslo.messaging #1529084 to transform datetime values into strings.
        # tl;dr: datetimes in dicts are not accepted as correct values by the
        # rpc fake driver.
        legacy_spec = jsonutils.loads(jsonutils.dumps(legacy_spec))

        LOG.debug("Calling prep_resize with selected host: %s; "
                  "Selected node: %s; Alternates: %s", host, node,
                  self.host_list, instance=self.instance)
        # RPC cast to the destination host to start the migration process.
        self.compute_rpcapi.prep_resize(
            self.context, self.instance, legacy_spec['image'],
            self.flavor, host, migration,
            request_spec=legacy_spec, filter_properties=legacy_props,
            node=node, clean_shutdown=self.clean_shutdown,
            host_list=self.host_list)

    def rollback(self):
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
                                        self.instance, self._migration,
                                        self._held_allocations)

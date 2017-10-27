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
        source_cn.uuid, instance.uuid)
    if not orig_alloc:
        LOG.error('Unable to find existing allocations for instance',
                  instance=instance)
        # A generic error like this will just error out the migration
        # and do any rollback required
        raise exception.InstanceUnacceptable(
            instance_id=instance.uuid,
            reason=_('Instance has no source node allocation'))

    # FIXME(danms): Since we don't have an atomic operation to adjust
    # allocations for multiple consumers, we have to have space on the
    # source for double the claim before we delete the old one
    # FIXME(danms): This method is flawed in that it asssumes allocations
    # against only one provider. So, this may overwite allocations against
    # a shared provider, if we had one.
    success = reportclient.put_allocations(source_cn.uuid, migration.uuid,
                                           orig_alloc,
                                           instance.project_id,
                                           instance.user_id)
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

    reportclient.delete_allocation_for_instance(instance.uuid)

    return source_cn, orig_alloc


def revert_allocation_for_migration(source_cn, instance, migration,
                                    orig_alloc):
    """Revert an allocation made for a migration back to the instance."""

    schedclient = scheduler_client.SchedulerClient()
    reportclient = schedclient.reportclient

    # FIXME(danms): Since we don't have an atomic operation to adjust
    # allocations for multiple consumers, we have to have space on the
    # source for double the claim before we delete the old one
    # FIXME(danms): This method is flawed in that it asssumes allocations
    # against only one provider. So, this may overwite allocations against
    # a shared provider, if we had one.
    success = reportclient.put_allocations(source_cn.uuid, instance.uuid,
                                           orig_alloc,
                                           instance.project_id,
                                           instance.user_id)
    if not success:
        LOG.error('Unable to replace resource claim on source '
                  'host %(host)s node %(node)s for instance',
                  {'host': instance.host,
                   'node': instance.node},
                  instance=instance)
    else:
        LOG.debug('Created allocations for instance %(inst)s on %(rp)s',
                  {'inst': instance.uuid, 'rp': source_cn.uuid})

    reportclient.delete_allocation_for_instance(migration.uuid)

    # TODO(danms): Remove this late retry logic when we can replace
    # the above two-step process with a single atomic one. Until then,
    # we just re-attempt the claim for the instance now that we have
    # cleared what should be an equal amount of space by deleting the
    # holding migraton.

    if not success:
        # NOTE(danms): We failed to claim the resources for the
        # instance above before the delete of the migration's
        # claim. Try again to claim for the instance. This is just
        # a racy attempt to be atomic and avoid stranding this
        # instance without an allocation. When we have an atomic
        # replace operation we should remove this.
        success = reportclient.put_allocations(source_cn.uuid,
                                               instance.uuid,
                                               orig_alloc,
                                               instance.project_id,
                                               instance.user_id)
        if success:
            LOG.debug(
                'Created allocations for instance %(inst)s on %(rp)s '
                '(retried)',
                {'inst': instance.uuid, 'rp': source_cn.uuid})
        else:
            LOG.error('Unable to replace resource claim on source '
                      'host %(host)s node %(node)s for instance (retried)',
                      {'host': instance.host,
                       'node': instance.node},
                      instance=instance)


def should_do_migration_allocation(context):
    minver = objects.Service.get_minimum_version_multi(context,
                                                       ['nova-compute'])
    return minver >= 23


class MigrationTask(base.TaskBase):
    def __init__(self, context, instance, flavor,
                 request_spec, reservations, clean_shutdown, compute_rpcapi,
                 scheduler_client):
        super(MigrationTask, self).__init__(context, instance)
        self.clean_shutdown = clean_shutdown
        self.request_spec = request_spec
        self.reservations = reservations
        self.flavor = flavor

        self.compute_rpcapi = compute_rpcapi
        self.scheduler_client = scheduler_client

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

        migration = objects.Migration(context=self.context.elevated())
        migration.old_instance_type_id = self.instance.flavor.id
        migration.new_instance_type_id = self.flavor.id
        migration.status = 'pre-migrating'
        migration.instance_uuid = self.instance.uuid
        migration.source_compute = self.instance.host
        migration.source_node = self.instance.node
        migration.migration_type = (self.instance.flavor.id != self.flavor.id
                                    and 'resize' or 'migration')
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

        migration = self._preallocate_migration()
        # For now, don't request alternates. A later patch in the series will
        # modify migration to use alternates instead of calling the scheduler
        # again.
        selection_lists = self.scheduler_client.select_destinations(
                self.context, self.request_spec, [self.instance.uuid],
                return_objects=True, return_alternates=False)
        # We only need the first item in the first list, as there is only one
        # instance, and we don't care about any alternates.
        selection = selection_lists[0][0]

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

        # RPC cast to the destination host to start the migration process.
        self.compute_rpcapi.prep_resize(
            self.context, self.instance, legacy_spec['image'],
            self.flavor, host, migration, self.reservations,
            request_spec=legacy_spec, filter_properties=legacy_props,
            node=node, clean_shutdown=self.clean_shutdown)

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

        revert_allocation_for_migration(self._source_cn, self.instance,
                                        self._migration,
                                        self._held_allocations)

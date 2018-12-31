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

import collections
import copy

from oslo_log import log as logging
import oslo_messaging as messaging

from nova import availability_zones
from nova.conductor.tasks import base
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import network
from nova.network.neutronv2 import constants as neutron_constants
from nova import objects
from nova.volume import cinder

LOG = logging.getLogger(__name__)


def clone_creatable_object(ctxt, obj, delete_fields=None):
    """Targets the object at the given context and removes its id attribute

    Dirties all of the set fields on a new copy of the object.
    This is necessary before the object is created in a new cell.

    :param ctxt: cell-targeted nova auth request context to set on the clone
    :param obj: the object to re-target
    :param delete_fields: list of fields to delete from the new object;
        note that the ``id`` field is always deleted
    :returns: Cloned version of ``obj`` with all set fields marked as
        "changed" so they will be persisted on a subsequent
        ``obj.create()`` call.
    """
    if delete_fields is None:
        delete_fields = []
    if 'id' not in delete_fields:
        delete_fields.append('id')
    new_obj = obj.obj_clone()
    new_obj._context = ctxt
    for field in obj.obj_fields:
        if field in obj:
            if field in delete_fields:
                delattr(new_obj, field)
            else:
                # Dirty the field since obj_clone does not modify
                # _changed_fields.
                setattr(new_obj, field, getattr(obj, field))
    return new_obj


class TargetDBSetupTask(base.TaskBase):
    """Sub-task to create the instance data in the target cell DB.

    This is needed before any work can be done with the instance in the target
    cell, like validating the selected target compute host.
    """
    def __init__(self, context, instance, source_migration,
                 target_cell_context):
        """Initialize this task.

        :param context: source-cell targeted auth RequestContext
        :param instance: source-cell Instance object
        :param source_migration: source-cell Migration object for this
            operation
        :param target_cell_context: target-cell targeted auth RequestContext
        """
        super(TargetDBSetupTask, self).__init__(context, instance)
        self.target_ctx = target_cell_context
        self.source_migration = source_migration

        self._target_cell_instance = None

    def _copy_migrations(self, migrations):
        """Copy migration records from the source cell to the target cell.

        :param migrations: MigrationList object of source cell DB records.
        :returns: Migration record in the target cell database that matches
            the active migration in the source cell.
        """
        target_cell_migration = None
        for migration in migrations:
            migration = clone_creatable_object(self.target_ctx, migration)
            migration.create()
            if self.source_migration.uuid == migration.uuid:
                # Save this off so subsequent tasks don't need to look it up.
                target_cell_migration = migration
        return target_cell_migration

    def _execute(self):
        """Creates the instance and its related records in the target cell

        Instance.pci_devices are not copied over since those records are
        tightly coupled to the compute_nodes records and are meant to track
        inventory and allocations of PCI devices on a specific compute node.
        The instance.pci_requests are what "move" with the instance to the
        target cell and will result in new PCIDevice allocations on the target
        compute node in the target cell during the resize_claim.

        The instance.services field is not copied over since that represents
        the nova-compute service mapped to the instance.host, which will not
        make sense in the target cell.

        :returns: A two-item tuple of the Instance and Migration object
            created in the target cell
        """
        LOG.debug(
            'Creating (hidden) instance and its related records in the target '
            'cell: %s', self.target_ctx.cell_uuid, instance=self.instance)
        # We also have to create the BDMs and tags separately, just like in
        # ComputeTaskManager.schedule_and_build_instances, so get those out
        # of the source cell DB first before we start creating anything.
        # NOTE(mriedem): Console auth tokens are not copied over to the target
        # cell DB since they will be regenerated in the target cell as needed.
        # Similarly, expired console auth tokens will be automatically cleaned
        # from the source cell.
        bdms = self.instance.get_bdms()
        vifs = objects.VirtualInterfaceList.get_by_instance_uuid(
            self.context, self.instance.uuid)
        tags = self.instance.tags
        # We copy instance actions to preserve the history of the instance
        # in case the resize is confirmed.
        actions = objects.InstanceActionList.get_by_instance_uuid(
            self.context, self.instance.uuid)
        migrations = objects.MigrationList.get_by_filters(
            self.context, filters={'instance_uuid': self.instance.uuid})

        # db.instance_create cannot handle some fields which might be loaded on
        # the instance object, so we omit those from the cloned object and
        # explicitly create the ones we care about (like tags) below. Things
        # like pci_devices and services will not make sense in the target DB
        # so we omit those as well.
        # TODO(mriedem): Determine if we care about copying faults over to the
        # target cell in case people use those for auditing (remember that
        # faults are only shown in the API for ERROR/DELETED instances and only
        # the most recent fault is shown).
        inst = clone_creatable_object(
            self.target_ctx, self.instance,
            delete_fields=['fault', 'pci_devices', 'services', 'tags'])
        # This part is important - we want to create the instance in the target
        # cell as "hidden" so while we have two copies of the instance in
        # different cells, listing servers out of the API will filter out the
        # hidden one.
        inst.hidden = True
        inst.create()
        self._target_cell_instance = inst  # keep track of this for rollbacks

        # TODO(mriedem): Consider doing all of the inserts in a single
        # transaction context. If any of the following creates fail, the
        # rollback should perform a cascading hard-delete anyway.

        # Do the same dance for the other instance-related records.
        for bdm in bdms:
            bdm = clone_creatable_object(self.target_ctx, bdm)
            bdm.create()
        for vif in vifs:
            vif = clone_creatable_object(self.target_ctx, vif)
            vif.create()
        if tags:
            primitive_tags = [tag.tag for tag in tags]
            objects.TagList.create(self.target_ctx, inst.uuid, primitive_tags)
        for action in actions:
            new_action = clone_creatable_object(self.target_ctx, action)
            new_action.create()
            # For each pre-existing action, we need to also re-create its
            # events in the target cell.
            events = objects.InstanceActionEventList.get_by_action(
                self.context, action.id)
            for event in events:
                new_event = clone_creatable_object(self.target_ctx, event)
                new_event.create(action.instance_uuid, action.request_id)

        target_cell_migration = self._copy_migrations(migrations)

        return inst, target_cell_migration

    def rollback(self):
        """Deletes the instance data from the target cell in case of failure"""
        if self._target_cell_instance:
            # Deleting the instance in the target cell DB should perform a
            # cascading delete of all related records, e.g. BDMs, VIFs, etc.
            LOG.debug('Destroying instance from target cell: %s',
                      self.target_ctx.cell_uuid,
                      instance=self._target_cell_instance)
            # This needs to be a hard delete because if resize fails later for
            # some reason, we want to be able to retry the resize to this cell
            # again without hitting a duplicate entry unique constraint error.
            self._target_cell_instance.destroy(hard_delete=True)


class PrepResizeAtDestTask(base.TaskBase):
    """Task used to verify a given target host in a target cell.

    Upon successful completion, port bindings and volume attachments
    should be created for the target host in the target cell and resources
    should be claimed on the target host for the resize. Also, the instance
    task_state should be ``resize_prep``.
    """

    def __init__(self, context, instance, flavor, target_migration,
                 request_spec, compute_rpcapi, host_selection, network_api,
                 volume_api):
        """Construct the PrepResizeAtDestTask instance

        :param context: The user request auth context. This should be targeted
            at the target cell.
        :param instance: The instance being migrated (this is the target cell
            copy of the instance record).
        :param flavor: The new flavor if performing resize and not just a
            cold migration
        :param target_migration: The Migration object from the target cell DB.
        :param request_spec: nova.objects.RequestSpec object for the operation
        :param compute_rpcapi: instance of nova.compute.rpcapi.ComputeAPI
        :param host_selection: nova.objects.Selection which is a possible
            target host for the cross-cell resize
        :param network_api: The neutron (client side) networking API.
        :param volume_api: The cinder (client side) block-storage API.
        """
        super(PrepResizeAtDestTask, self).__init__(context, instance)
        self.flavor = flavor
        self.target_migration = target_migration
        self.request_spec = request_spec
        self.compute_rpcapi = compute_rpcapi
        self.host_selection = host_selection
        self.network_api = network_api
        self.volume_api = volume_api

        # Keep track of anything we created so we can rollback.
        self._bindings_by_port_id = {}
        self._created_volume_attachment_ids = []

    def _create_port_bindings(self):
        """Creates inactive port bindings against the selected target host
        for the ports attached to the instance.

        The ``self._bindings_by_port_id`` variable will be set upon successful
        completion.

        :raises: MigrationPreCheckError if port binding failed
        """
        LOG.debug('Creating port bindings for destination host %s',
                  self.host_selection.service_host)
        try:
            self._bindings_by_port_id = self.network_api.bind_ports_to_host(
                self.context, self.instance, self.host_selection.service_host)
        except exception.PortBindingFailed:
            raise exception.MigrationPreCheckError(reason=_(
                'Failed to create port bindings for host %s') %
                self.host_selection.service_host)

    def _create_volume_attachments(self):
        """Create empty volume attachments for volume BDMs attached to the
        instance in the target cell.

        The BlockDeviceMapping.attachment_id field is updated for each
        volume BDM processed. Remember that these BDM records are from the
        target cell database so the changes will only go there.

        :return: BlockDeviceMappingList of volume BDMs with an updated
            attachment_id field for the newly created empty attachment for
            that BDM
        """
        LOG.debug('Creating volume attachments for destination host %s',
                  self.host_selection.service_host)
        volume_bdms = objects.BlockDeviceMappingList(objects=[
            bdm for bdm in self.instance.get_bdms() if bdm.is_volume])
        for bdm in volume_bdms:
            # Create the empty (no host connector) attachment.
            attach_ref = self.volume_api.attachment_create(
                self.context, bdm.volume_id, bdm.instance_uuid)
            # Keep track of what we create for rollbacks.
            self._created_volume_attachment_ids.append(attach_ref['id'])
            # Update the BDM in the target cell database.
            bdm.attachment_id = attach_ref['id']
            # Note that ultimately the BDMs in the target cell are either
            # pointing at attachments that we can use, or this sub-task has
            # failed in which case we will fail the main task and should
            # rollback and delete the instance and its BDMs in the target cell
            # database, so that is why we do not track the original attachment
            # IDs in order to roll them back on the BDM records.
            bdm.save()
        return volume_bdms

    def _execute(self):
        """Performs pre-cross-cell resize checks/claims on the targeted host

        This ensures things like networking (ports) will continue to work on
        the target host in the other cell before we initiate the migration of
        the server.

        Resources are also claimed on the target host which in turn creates the
        MigrationContext for the instance in the target cell database.

        :returns: MigrationContext created in the target cell database during
            the resize_claim in the destination compute service.
        :raises: nova.exception.MigrationPreCheckError if the pre-check
            validation fails for the given host selection; this indicates an
            alternative host *may* work but this one does not.
        """
        destination = self.host_selection.service_host
        LOG.debug('Verifying selected host %s for cross-cell resize.',
                  destination, instance=self.instance)

        # Validate networking by creating port bindings for this host.
        self._create_port_bindings()

        # Create new empty volume attachments for the volume BDMs attached
        # to the instance. Technically this is not host specific and we could
        # do this outside of the PrepResizeAtDestTask sub-task but volume
        # attachments are meant to be cheap and plentiful so it is nice to
        # keep them self-contained within each execution of this task and
        # rollback anything we created if we fail.
        self._create_volume_attachments()

        try:
            LOG.debug('Calling destination host %s to prepare for cross-cell '
                      'resize and claim resources.', destination)
            return self.compute_rpcapi.prep_snapshot_based_resize_at_dest(
                self.context, self.instance, self.flavor,
                self.host_selection.nodename, self.target_migration,
                self.host_selection.limits, self.request_spec, destination)
        except messaging.MessagingTimeout:
            msg = _('RPC timeout while checking if we can cross-cell migrate '
                    'to host: %s') % destination
            raise exception.MigrationPreCheckError(reason=msg)

    def rollback(self):
        # Rollback anything we created.
        host = self.host_selection.service_host
        # Cleanup any destination host port bindings.
        LOG.debug('Cleaning up port bindings for destination host %s', host)
        for port_id in self._bindings_by_port_id:
            try:
                self.network_api.delete_port_binding(
                    self.context, port_id, host)
            except Exception:
                # Don't raise if we fail to cleanup, just log it.
                LOG.exception('An error occurred while cleaning up binding '
                              'for port %s on host %s.', port_id, host,
                              instance=self.instance)

        # Cleanup any destination host volume attachments.
        LOG.debug(
            'Cleaning up volume attachments for destination host %s', host)
        for attachment_id in self._created_volume_attachment_ids:
            try:
                self.volume_api.attachment_delete(self.context, attachment_id)
            except Exception:
                # Don't raise if we fail to cleanup, just log it.
                LOG.exception('An error occurred while cleaning up volume '
                              'attachment %s.', attachment_id,
                              instance=self.instance)


class CrossCellMigrationTask(base.TaskBase):
    """Orchestrates a cross-cell cold migration (resize)."""

    def __init__(self, context, instance, flavor,
                 request_spec, source_migration, compute_rpcapi,
                 host_selection, alternate_hosts):
        """Construct the CrossCellMigrationTask instance

        :param context: The user request auth context. This should be targeted
            to the source cell in which the instance is currently running.
        :param instance: The instance being migrated (from the source cell)
        :param flavor: The new flavor if performing resize and not just a
            cold migration
        :param request_spec: nova.objects.RequestSpec with scheduling details
        :param source_migration: nova.objects.Migration record for this
            operation (from the source cell)
        :param compute_rpcapi: instance of nova.compute.rpcapi.ComputeAPI
        :param host_selection: nova.objects.Selection of the initial
            selected target host from the scheduler where the selected host
            is in another cell which is different from the cell in which
            the instance is currently running
        :param alternate_hosts: list of 0 or more nova.objects.Selection
            objects representing alternate hosts within the same target cell
            as ``host_selection``.
        """
        super(CrossCellMigrationTask, self).__init__(context, instance)
        self.request_spec = request_spec
        self.flavor = flavor
        self.source_migration = source_migration
        self.compute_rpcapi = compute_rpcapi
        self.host_selection = host_selection
        self.alternate_hosts = alternate_hosts

        self._target_cell_instance = None
        self._target_cell_context = None

        self.network_api = network.API()
        self.volume_api = cinder.API()

        # Keep an ordered dict of the sub-tasks completed so we can call their
        # rollback routines if something fails.
        self._completed_tasks = collections.OrderedDict()

    def _get_target_cell_mapping(self):
        """Get the target host CellMapping for the selected host

        :returns: nova.objects.CellMapping for the cell of the selected target
            host
        :raises: nova.exception.CellMappingNotFound if the cell mapping for
            the selected target host cannot be found (this should not happen
            if the scheduler just selected it)
        """
        return objects.CellMapping.get_by_uuid(
            self.context, self.host_selection.cell_uuid)

    def _setup_target_cell_db(self):
        """Creates the instance and its related records in the target cell

        Upon successful completion the self._target_cell_context and
        self._target_cell_instance variables are set.

        :returns: The active Migration object from the target cell DB.
        """
        LOG.debug('Setting up the target cell database for the instance and '
                  'its related records.', instance=self.instance)
        target_cell_mapping = self._get_target_cell_mapping()
        # Clone the context targeted at the source cell and then target the
        # clone at the target cell.
        self._target_cell_context = copy.copy(self.context)
        nova_context.set_target_cell(
            self._target_cell_context, target_cell_mapping)
        task = TargetDBSetupTask(
            self.context, self.instance, self.source_migration,
            self._target_cell_context)
        self._target_cell_instance, target_cell_migration = task.execute()
        self._completed_tasks['TargetDBSetupTask'] = task
        return target_cell_migration

    def _perform_external_api_checks(self):
        """Performs checks on external service APIs for support.

        * Checks that the neutron port binding-extended API is available

        :raises: MigrationPreCheckError if any checks fail
        """
        LOG.debug('Making sure neutron is new enough for cross-cell resize.')
        # Check that the port binding-extended API extension is available in
        # neutron because if it's not we can just fail fast.
        if not self.network_api.supports_port_binding_extension(self.context):
            raise exception.MigrationPreCheckError(
                reason=_("Required networking service API extension '%s' "
                         "not found.") %
                neutron_constants.PORT_BINDING_EXTENDED)

    def _prep_resize_at_dest(self, target_cell_migration):
        """Executes PrepResizeAtDestTask and updates the source migration.

        :param target_cell_migration: Migration record from the target cell DB
        :returns: Refreshed Migration record from the target cell DB after the
            resize_claim on the destination host has updated the record.
        """
        # TODO(mriedem): Check alternates if the primary selected host fails;
        # note that alternates are always in the same cell as the selected host
        # so if the primary fails pre-checks, the alternates may also fail. We
        # could reschedule but the scheduler does not yet have an ignore_cells
        # capability like ignore_hosts.

        # We set the target cell instance new_flavor attribute now since the
        # ResourceTracker.resize_claim on the destination host uses it.
        self._target_cell_instance.new_flavor = self.flavor

        verify_task = PrepResizeAtDestTask(
            self._target_cell_context, self._target_cell_instance, self.flavor,
            target_cell_migration, self.request_spec, self.compute_rpcapi,
            self.host_selection, self.network_api, self.volume_api)
        target_cell_migration_context = verify_task.execute()
        self._completed_tasks['PrepResizeAtDestTask'] = verify_task

        # Stash the old vm_state so we can set the resized/reverted instance
        # back to the same state later, i.e. if STOPPED do not power on the
        # guest.
        self._target_cell_instance.system_metadata['old_vm_state'] = (
            self._target_cell_instance.vm_state)
        # Update the target cell instance availability zone now that we have
        # prepared the resize on the destination host. We do this in conductor
        # to avoid the "up-call" from the compute service to the API database.
        self._target_cell_instance.availability_zone = (
            availability_zones.get_host_availability_zone(
                self.context, self.host_selection.service_host))
        self._target_cell_instance.save()

        # We need to mirror the MigrationContext, created in the target cell
        # database, into the source cell database. Keep in mind that the
        # MigrationContext has pci_devices and a migration_id in it which
        # are specific to the target cell database. The only one we care about
        # correcting for the source cell database is migration_id since that
        # is used to route neutron external events to the source and target
        # hosts.
        self.instance.migration_context = (
            target_cell_migration_context.obj_clone())
        self.instance.migration_context.migration_id = self.source_migration.id
        self.instance.save()

        return self._update_migration_from_dest_after_claim(
            target_cell_migration)

    def _update_migration_from_dest_after_claim(self, target_cell_migration):
        """Update the source cell migration record with target cell info.

        The PrepResizeAtDestTask runs a resize_claim on the target compute
        host service in the target cell which sets fields about the destination
        in the migration record in the target cell. We need to reflect those
        changes back into the migration record in the source cell.

        :param target_cell_migration: Migration record from the target cell DB
        :returns: Refreshed Migration record from the target cell DB after the
            resize_claim on the destination host has updated the record.
        """
        # Copy information about the dest compute that was set on the dest
        # migration record during the resize claim on the dest host.
        # We have to get a fresh copy of the target cell migration record to
        # pick up the changes made in the dest compute service.
        target_cell_migration = objects.Migration.get_by_uuid(
            self._target_cell_context, target_cell_migration.uuid)
        self.source_migration.dest_compute = target_cell_migration.dest_compute
        self.source_migration.dest_node = target_cell_migration.dest_node
        self.source_migration.dest_host = target_cell_migration.dest_host
        self.source_migration.save()

        return target_cell_migration

    def _execute(self):
        """Execute high-level orchestration of the cross-cell resize"""
        # We are committed to a cross-cell move at this point so update the
        # migration record to reflect that. If we fail after this we are not
        # going to go back and try to run the MigrationTask to do a same-cell
        # migration, so we set the cross_cell_move flag early for audit/debug
        # in case something fails later and the operator wants to know if this
        # was a cross-cell or same-cell move operation.
        self.source_migration.cross_cell_move = True
        self.source_migration.save()
        # Make sure neutron APIs we need are available.
        self._perform_external_api_checks()

        # Before preparing the target host create the instance record data
        # in the target cell database since we cannot do anything in the
        # target cell without having an instance record there. Remember that
        # we lose the cell-targeting on the request context over RPC so we
        # cannot simply pass the source cell context and instance over RPC
        # to the target compute host and assume changes get mirrored back to
        # the source cell database.
        target_cell_migration = self._setup_target_cell_db()

        # Claim resources and validate the selected host in the target cell.
        target_cell_migration = self._prep_resize_at_dest(
            target_cell_migration)

        # TODO(mriedem): If image-backed, snapshot the server from source host
        # and store it in the migration_context for spawn. Should we do this
        # in PrepResizeAtDestTask? Re-using compute_rpcapi.snapshot_instance()
        # would be nice but it sets the task_state=None and sends different
        # notifications from a normal resize (but do those matter?).
        # TODO(mriedem): Stop the server on the source host.
        # TODO(mriedem): Copy data to dest cell DB.
        # TODO(mriedem): Update instance mapping to dest cell DB.
        # TODO(mriedem): Spawn in target cell host:
        # - Use new flavor to spawn guest
        # - Wait for ACTIVE or keep powered off
        # - Activate target host port bindings
        # - Update/complete volume attachments and update BDM.attachment_id.

    def rollback(self):
        """Rollback based on how sub-tasks completed

        Sub-tasks should rollback appropriately for whatever they do but here
        we need to handle cleaning anything up from successful tasks, e.g. if
        tasks A and B were successful but task C fails, then we might need to
        cleanup changes from A and B here.
        """
        # Rollback the completed tasks in reverse order.
        for task_name in reversed(self._completed_tasks):
            try:
                self._completed_tasks[task_name].rollback()
            except Exception:
                LOG.exception('Rollback for task %s failed.', task_name)

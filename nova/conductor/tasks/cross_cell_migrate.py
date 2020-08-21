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
from oslo_utils import excutils

from nova import availability_zones
from nova.compute import instance_actions
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor.tasks import base
from nova import conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.image import glance
from nova.network import constants as neutron_constants
from nova.network import neutron
from nova import objects
from nova.objects import fields
from nova.scheduler import utils as scheduler_utils
from nova.volume import cinder

LOG = logging.getLogger(__name__)
CONF = conf.CONF


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

    def rollback(self, ex):
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

    def rollback(self, ex):
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


class PrepResizeAtSourceTask(base.TaskBase):
    """Task to prepare the instance at the source host for the resize.

    Will power off the instance at the source host, create and upload a
    snapshot image for a non-volume-backed server, and disconnect volumes and
    networking from the source host.

    The vm_state is recorded with the "old_vm_state" key in the
    instance.system_metadata field prior to powering off the instance so the
    revert flow can determine if the guest should be running or stopped.

    Returns the snapshot image ID, if one was created, from the ``execute``
    method.

    Upon successful completion, the instance.task_state will be
    ``resize_migrated`` and the migration.status will be ``post-migrating``.
    """

    def __init__(self, context, instance, migration, request_spec,
                 compute_rpcapi, image_api):
        """Initializes this PrepResizeAtSourceTask instance.

        :param context: nova auth context targeted at the source cell
        :param instance: Instance object from the source cell
        :param migration: Migration object from the source cell
        :param request_spec: RequestSpec object for the resize operation
        :param compute_rpcapi: instance of nova.compute.rpcapi.ComputeAPI
        :param image_api: instance of nova.image.glance.API
        """
        super(PrepResizeAtSourceTask, self).__init__(context, instance)
        self.migration = migration
        self.request_spec = request_spec
        self.compute_rpcapi = compute_rpcapi
        self.image_api = image_api
        self._image_id = None

    def _execute(self):
        # Save off the vm_state so we can use that later on the source host
        # if the resize is reverted - it is used to determine if the reverted
        # guest should be powered on.
        self.instance.system_metadata['old_vm_state'] = self.instance.vm_state
        self.instance.task_state = task_states.RESIZE_MIGRATING

        # If the instance is not volume-backed, create a snapshot of the root
        # disk.
        if not self.request_spec.is_bfv:
            # Create an empty image.
            name = '%s-resize-temp' % self.instance.display_name
            image_meta = compute_utils.create_image(
                self.context, self.instance, name, 'snapshot', self.image_api)
            self._image_id = image_meta['id']
            LOG.debug('Created snapshot image %s for cross-cell resize.',
                      self._image_id, instance=self.instance)

        self.instance.save(expected_task_state=task_states.RESIZE_PREP)

        # RPC call the source host to prepare for resize.
        self.compute_rpcapi.prep_snapshot_based_resize_at_source(
            self.context, self.instance, self.migration,
            snapshot_id=self._image_id)

        return self._image_id

    def rollback(self, ex):
        # If we created a snapshot image, attempt to delete it.
        if self._image_id:
            compute_utils.delete_image(
                self.context, self.instance, self.image_api, self._image_id)
        # If the compute service successfully powered off the guest but failed
        # to snapshot (or timed out during the snapshot), then the
        # _sync_power_states periodic task should mark the instance as stopped
        # and the user can start/reboot it.
        # If the compute service powered off the instance, snapshot it and
        # destroyed the guest and then a failure occurred, the instance should
        # have been set to ERROR status (by the compute service) so the user
        # has to hard reboot or rebuild it.
        LOG.error('Preparing for cross-cell resize at the source host %s '
                  'failed. The instance may need to be hard rebooted.',
                  self.instance.host, instance=self.instance)


class FinishResizeAtDestTask(base.TaskBase):
    """Task to finish the resize at the destination host.

    Calls the finish_snapshot_based_resize_at_dest method on the destination
    compute service which sets up networking and block storage and spawns
    the guest on the destination host. Upon successful completion of this
    task, the migration status should be 'finished', the instance task_state
    should be None and the vm_state should be 'resized'. The instance host/node
    information should also reflect the destination compute.

    If the compute call is successful, the task will change the instance
    mapping to point at the target cell and hide the source cell instance thus
    making the confirm/revert operations act on the target cell instance.
    """

    def __init__(self, context, instance, migration, source_cell_instance,
                 compute_rpcapi, target_cell_mapping, snapshot_id,
                 request_spec):
        """Initialize this task.

        :param context: nova auth request context targeted at the target cell
        :param instance: Instance object in the target cell database
        :param migration: Migration object in the target cell database
        :param source_cell_instance: Instance object in the source cell DB
        :param compute_rpcapi: instance of nova.compute.rpcapi.ComputeAPI
        :param target_cell_mapping: CellMapping object for the target cell
        :param snapshot_id: ID of the image snapshot to use for a
            non-volume-backed instance.
        :param request_spec: nova.objects.RequestSpec object for the operation
        """
        super(FinishResizeAtDestTask, self).__init__(context, instance)
        self.migration = migration
        self.source_cell_instance = source_cell_instance
        self.compute_rpcapi = compute_rpcapi
        self.target_cell_mapping = target_cell_mapping
        self.snapshot_id = snapshot_id
        self.request_spec = request_spec

    def _finish_snapshot_based_resize_at_dest(self):
        """Synchronously RPC calls finish_snapshot_based_resize_at_dest

        If the finish_snapshot_based_resize_at_dest method fails in the
        compute service, this method will update the source cell instance
        data to reflect the error (vm_state='error', copy the fault and
        instance action events for that compute method).
        """
        LOG.debug('Finishing cross-cell resize at the destination host %s',
                  self.migration.dest_compute, instance=self.instance)
        # prep_snapshot_based_resize_at_source in the source cell would have
        # changed the source cell instance.task_state to resize_migrated and
        # we need to reflect that in the target cell instance before calling
        # the destination compute.
        self.instance.task_state = task_states.RESIZE_MIGRATED
        self.instance.save()
        event_name = 'compute_finish_snapshot_based_resize_at_dest'
        source_cell_context = self.source_cell_instance._context
        try:
            with compute_utils.EventReporter(
                    source_cell_context, event_name,
                    self.migration.dest_compute, self.instance.uuid):
                self.compute_rpcapi.finish_snapshot_based_resize_at_dest(
                    self.context, self.instance, self.migration,
                    self.snapshot_id, self.request_spec)
            # finish_snapshot_based_resize_at_dest updates the target cell
            # instance so we need to refresh it here to have the latest copy.
            self.instance.refresh()
        except Exception:
            # We need to mimic the error handlers on
            # finish_snapshot_based_resize_at_dest in the destination compute
            # service so those changes are reflected in the source cell
            # instance.
            with excutils.save_and_reraise_exception(logger=LOG):
                # reverts_task_state and _error_out_instance_on_exception:
                self.source_cell_instance.task_state = None
                self.source_cell_instance.vm_state = vm_states.ERROR
                self.source_cell_instance.save()
                # wrap_instance_fault (this is best effort)
                self._copy_latest_fault(source_cell_context)

    def _copy_latest_fault(self, source_cell_context):
        """Copies the latest instance fault from the target cell to the source

        :param source_cell_context: nova auth request context targeted at the
            source cell
        """
        try:
            # Get the latest fault from the target cell database.
            fault = objects.InstanceFault.get_latest_for_instance(
                self.context, self.instance.uuid)
            if fault:
                fault_clone = clone_creatable_object(source_cell_context,
                                                     fault)
                fault_clone.create()
        except Exception:
            LOG.exception(
                'Failed to copy instance fault from target cell DB',
                instance=self.instance)

    def _update_instance_mapping(self):
        """Swaps the hidden field value on the source and target cell instance
        and updates the instance mapping to point at the target cell.
        """
        LOG.debug('Marking instance in source cell as hidden and updating '
                  'instance mapping to point at target cell %s.',
                  self.target_cell_mapping.identity, instance=self.instance)
        # Get the instance mapping first to make the window of time where both
        # instances are hidden=False as small as possible.
        instance_mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.context, self.instance.uuid)
        # Mark the target cell instance record as hidden=False so it will show
        # up when listing servers. Note that because of how the API filters
        # duplicate instance records, even if the user is listing servers at
        # this exact moment only one copy of the instance will be returned.
        self.instance.hidden = False
        self.instance.save()
        # Update the instance mapping to point at the target cell. This is so
        # that the confirm/revert actions will be performed on the resized
        # instance in the target cell rather than the destroyed guest in the
        # source cell. Note that we could do this before finishing the resize
        # on the dest host, but it makes sense to defer this until the
        # instance is successfully resized in the dest host because if that
        # fails, we want to be able to rebuild in the source cell to recover
        # the instance.
        instance_mapping.cell_mapping = self.target_cell_mapping
        # If this fails the cascading task failures should delete the instance
        # in the target cell database so we do not need to hide it again.
        instance_mapping.save()
        # Mark the source cell instance record as hidden=True to hide it from
        # the user when listing servers.
        self.source_cell_instance.hidden = True
        self.source_cell_instance.save()

    def _execute(self):
        # Finish the resize on the destination host in the target cell.
        self._finish_snapshot_based_resize_at_dest()
        # Do the instance.hidden/instance_mapping.cell_mapping swap.
        self._update_instance_mapping()

    def rollback(self, ex):
        # The method executed in this task are self-contained for rollbacks.
        pass


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

        self.network_api = neutron.API()
        self.volume_api = cinder.API()
        self.image_api = glance.API()

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

        :returns: A 2-item tuple of:

            - The active Migration object from the target cell DB
            - The CellMapping for the target cell
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
        return target_cell_migration, target_cell_mapping

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

    def _prep_resize_at_source(self):
        """Executes PrepResizeAtSourceTask

        :return: The image snapshot ID if the instance is not volume-backed,
            else None.
        """
        LOG.debug('Preparing source host %s for cross-cell resize.',
                  self.source_migration.source_compute, instance=self.instance)
        prep_source_task = PrepResizeAtSourceTask(
            self.context, self.instance, self.source_migration,
            self.request_spec, self.compute_rpcapi, self.image_api)
        snapshot_id = prep_source_task.execute()
        self._completed_tasks['PrepResizeAtSourceTask'] = prep_source_task
        return snapshot_id

    def _finish_resize_at_dest(
            self, target_cell_migration, target_cell_mapping, snapshot_id):
        """Executes FinishResizeAtDestTask

        :param target_cell_migration: Migration object from the target cell DB
        :param target_cell_mapping: CellMapping object for the target cell
        :param snapshot_id: ID of the image snapshot to use for a
            non-volume-backed instance.
        """
        task = FinishResizeAtDestTask(
            self._target_cell_context, self._target_cell_instance,
            target_cell_migration, self.instance, self.compute_rpcapi,
            target_cell_mapping, snapshot_id, self.request_spec)
        task.execute()
        self._completed_tasks['FinishResizeAtDestTask'] = task

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
        target_cell_migration, target_cell_mapping = (
            self._setup_target_cell_db())

        # Claim resources and validate the selected host in the target cell.
        target_cell_migration = self._prep_resize_at_dest(
            target_cell_migration)

        # Prepare the instance at the source host (stop it, optionally snapshot
        # it, disconnect volumes and VIFs, etc).
        snapshot_id = self._prep_resize_at_source()

        # Finish the resize at the destination host, swap the hidden fields
        # on the instances and update the instance mapping.
        self._finish_resize_at_dest(
            target_cell_migration, target_cell_mapping, snapshot_id)

    def rollback(self, ex):
        """Rollback based on how sub-tasks completed

        Sub-tasks should rollback appropriately for whatever they do but here
        we need to handle cleaning anything up from successful tasks, e.g. if
        tasks A and B were successful but task C fails, then we might need to
        cleanup changes from A and B here.
        """
        # Rollback the completed tasks in reverse order.
        for task_name in reversed(self._completed_tasks):
            try:
                self._completed_tasks[task_name].rollback(ex)
            except Exception:
                LOG.exception('Rollback for task %s failed.', task_name)


def get_inst_and_cell_map_from_source(
        target_cell_context, source_compute, instance_uuid):
    """Queries the instance from the source cell database.

    :param target_cell_context: nova auth request context targeted at the
        target cell database
    :param source_compute: name of the source compute service host
    :param instance_uuid: UUID of the instance
    :returns: 2-item tuple of:

        - Instance object from the source cell database.
        - CellMapping object of the source cell mapping
    """
    # We can get the source cell via the host mapping based on the
    # source_compute in the migration object.
    source_host_mapping = objects.HostMapping.get_by_host(
        target_cell_context, source_compute)
    source_cell_mapping = source_host_mapping.cell_mapping
    # Clone the context targeted at the target cell and then target the
    # clone at the source cell.
    source_cell_context = copy.copy(target_cell_context)
    nova_context.set_target_cell(source_cell_context, source_cell_mapping)
    # Now get the instance from the source cell DB using the source
    # cell context which will make the source cell instance permanently
    # targeted to the source cell database.
    instance = objects.Instance.get_by_uuid(
        source_cell_context, instance_uuid,
        expected_attrs=['flavor', 'info_cache', 'system_metadata'])
    return instance, source_cell_mapping


class ConfirmResizeTask(base.TaskBase):
    """Task which orchestrates a cross-cell resize confirm operation

    When confirming a cross-cell resize, the instance is in both the source
    and target cell databases and on the source and target compute hosts.
    The API operation is performed on the target cell instance and it is the
    job of this task to cleanup the source cell host and database and
    update the status of the instance in the target cell.

    This can be called either asynchronously from the API service during a
    normal confirmResize server action or synchronously when deleting a server
    in VERIFY_RESIZE status.
    """

    def __init__(self, context, instance, migration, legacy_notifier,
                 compute_rpcapi):
        """Initialize this ConfirmResizeTask instance

        :param context: nova auth request context targeted at the target cell
        :param instance: Instance object in "resized" status from the target
            cell
        :param migration: Migration object from the target cell for the resize
            operation expected to have status "confirming"
        :param legacy_notifier: LegacyValidatingNotifier for sending legacy
            unversioned notifications
        :param compute_rpcapi: instance of nova.compute.rpcapi.ComputeAPI
        """
        super(ConfirmResizeTask, self).__init__(context, instance)
        self.migration = migration
        self.legacy_notifier = legacy_notifier
        self.compute_rpcapi = compute_rpcapi

    def _send_resize_confirm_notification(self, instance, phase):
        """Sends an unversioned and versioned resize.confirm.(phase)
        notification.

        :param instance: The instance whose resize is being confirmed.
        :param phase: The phase for the resize.confirm operation (either
            "start" or "end").
        """
        ctxt = instance._context
        # Send the legacy unversioned notification.
        compute_utils.notify_about_instance_usage(
            self.legacy_notifier, ctxt, instance, 'resize.confirm.%s' % phase)
        # Send the versioned notification.
        compute_utils.notify_about_instance_action(
            ctxt, instance, CONF.host,
            action=fields.NotificationAction.RESIZE_CONFIRM,
            phase=phase)

    def _cleanup_source_host(self, source_instance):
        """Cleans up the instance from the source host.

        Creates a confirmResize instance action in the source cell DB.

        Destroys the guest from the source hypervisor, cleans up networking
        and storage and frees up resource usage on the source host.

        :param source_instance: Instance object from the source cell DB
        """
        ctxt = source_instance._context
        # The confirmResize instance action has to be created in the source
        # cell database before calling the compute service to properly
        # track action events. Note that the API created the same action
        # record but on the target cell instance.
        objects.InstanceAction.action_start(
            ctxt, source_instance.uuid, instance_actions.CONFIRM_RESIZE,
            want_result=False)
        # Get the Migration record from the source cell database.
        source_migration = objects.Migration.get_by_uuid(
            ctxt, self.migration.uuid)
        LOG.debug('Cleaning up source host %s for cross-cell resize confirm.',
                  source_migration.source_compute, instance=source_instance)
        # The instance.old_flavor field needs to be set before the source
        # host drops the MoveClaim in the ResourceTracker.
        source_instance.old_flavor = source_instance.flavor
        # Use the EventReport context manager to create the same event that
        # the source compute will create but in the target cell DB so we do not
        # have to explicitly copy it over from source to target DB.
        event_name = 'compute_confirm_snapshot_based_resize_at_source'
        with compute_utils.EventReporter(
                self.context, event_name, source_migration.source_compute,
                source_instance.uuid):
            self.compute_rpcapi.confirm_snapshot_based_resize_at_source(
                ctxt, source_instance, source_migration)

    def _finish_confirm_in_target_cell(self):
        """Sets "terminal" states on the migration and instance in target cell.

        This is similar to how ``confirm_resize`` works in the compute service
        for same-cell resize.
        """
        LOG.debug('Updating migration and instance status in target cell DB.',
                  instance=self.instance)
        # Update the target cell migration.
        self.migration.status = 'confirmed'
        self.migration.save()
        # Update the target cell instance.
        # Delete stashed information for the resize.
        self.instance.old_flavor = None
        self.instance.new_flavor = None
        self.instance.system_metadata.pop('old_vm_state', None)
        self._set_vm_and_task_state()
        self.instance.drop_migration_context()
        # There are multiple possible task_states set on the instance because
        # if we are called from the confirmResize instance action the
        # task_state should be None, but if we are called from
        # _confirm_resize_on_deleting then the instance is being deleted.
        self.instance.save(expected_task_state=[
            None, task_states.DELETING, task_states.SOFT_DELETING])

    def _set_vm_and_task_state(self):
        """Sets the target cell instance vm_state based on the power_state.

        The task_state is set to None.
        """
        # The old_vm_state could be STOPPED but the user might have manually
        # powered up the instance to confirm the resize/migrate, so we need to
        # check the current power state on the instance and set the vm_state
        # appropriately. We default to ACTIVE because if the power state is
        # not SHUTDOWN, we assume the _sync_power_states periodic task in the
        # compute service will clean it up.
        p_state = self.instance.power_state
        if p_state == power_state.SHUTDOWN:
            vm_state = vm_states.STOPPED
            LOG.debug("Resized/migrated instance is powered off. "
                      "Setting vm_state to '%s'.", vm_state,
                      instance=self.instance)
        else:
            vm_state = vm_states.ACTIVE
        self.instance.vm_state = vm_state
        self.instance.task_state = None

    def _execute(self):
        # First get the instance from the source cell so we can cleanup.
        source_cell_instance = get_inst_and_cell_map_from_source(
            self.context, self.migration.source_compute, self.instance.uuid)[0]
        # Send the resize.confirm.start notification(s) using the source
        # cell instance since we start there.
        self._send_resize_confirm_notification(
            source_cell_instance, fields.NotificationPhase.START)
        # RPC call the source compute to cleanup.
        self._cleanup_source_host(source_cell_instance)
        # Now we can delete the instance in the source cell database.
        LOG.info('Deleting instance record from source cell %s',
                 source_cell_instance._context.cell_uuid,
                 instance=source_cell_instance)
        # This needs to be a hard delete because we want to be able to resize
        # back to this cell without hitting a duplicate entry unique constraint
        # error.
        source_cell_instance.destroy(hard_delete=True)
        # Update the information in the target cell database.
        self._finish_confirm_in_target_cell()
        # Send the resize.confirm.end notification using the target cell
        # instance since we end there.
        self._send_resize_confirm_notification(
            self.instance, fields.NotificationPhase.END)

    def rollback(self, ex):
        with excutils.save_and_reraise_exception():
            LOG.exception(
                'An error occurred while confirming the resize for instance '
                'in target cell %s. Depending on the error, a copy of the '
                'instance may still exist in the source cell database which '
                'contains the source host %s. At this point the instance is '
                'on the target host %s and anything left in the source cell '
                'can be cleaned up.', self.context.cell_uuid,
                self.migration.source_compute, self.migration.dest_compute,
                instance=self.instance)
            # If anything failed set the migration status to 'error'.
            self.migration.status = 'error'
            self.migration.save()
            # Put the instance in the target DB into ERROR status, record
            # a fault and send an error notification.
            updates = {'vm_state': vm_states.ERROR, 'task_state': None}
            request_spec = objects.RequestSpec.get_by_instance_uuid(
                self.context, self.instance.uuid)
            scheduler_utils.set_vm_state_and_notify(
                self.context, self.instance.uuid, 'compute_task',
                'migrate_server', updates, ex, request_spec)


class RevertResizeTask(base.TaskBase):
    """Task to orchestrate a cross-cell resize revert operation.

    This task is responsible for coordinating the cleanup of the resources
    in the target cell and restoring the server and its related resources
    (e.g. networking and volumes) in the source cell.

    Upon successful completion the instance mapping should point back at the
    source cell, the source cell instance should no longer be hidden and the
    instance in the target cell should be destroyed.
    """

    def __init__(self, context, instance, migration, legacy_notifier,
                 compute_rpcapi):
        """Initialize this RevertResizeTask instance

        :param context: nova auth request context targeted at the target cell
        :param instance: Instance object in "resized" status from the target
            cell with task_state "resize_reverting"
        :param migration: Migration object from the target cell for the resize
            operation expected to have status "reverting"
        :param legacy_notifier: LegacyValidatingNotifier for sending legacy
            unversioned notifications
        :param compute_rpcapi: instance of nova.compute.rpcapi.ComputeAPI
        """
        super(RevertResizeTask, self).__init__(context, instance)
        self.migration = migration
        self.legacy_notifier = legacy_notifier
        self.compute_rpcapi = compute_rpcapi

        # These are used for rollback handling.
        self._source_cell_migration = None
        self._source_cell_instance = None

        self.volume_api = cinder.API()

    def _send_resize_revert_notification(self, instance, phase):
        """Sends an unversioned and versioned resize.revert.(phase)
        notification.

        :param instance: The instance whose resize is being reverted.
        :param phase: The phase for the resize.revert operation (either
            "start" or "end").
        """
        ctxt = instance._context
        # Send the legacy unversioned notification.
        compute_utils.notify_about_instance_usage(
            self.legacy_notifier, ctxt, instance, 'resize.revert.%s' % phase)
        # Send the versioned notification.
        compute_utils.notify_about_instance_action(
            ctxt, instance, CONF.host,
            action=fields.NotificationAction.RESIZE_REVERT,
            phase=phase)

    @staticmethod
    def _update_source_obj_from_target_cell(source_obj, target_obj):
        """Updates the object from the source cell using the target cell object

        WARNING: This method does not support objects with nested objects, i.e.
        objects that have fields which are other objects. An error will be
        raised in that case.

        All fields on the source object are updated from the target object
        except for the ``id`` and ``created_at`` fields since those value must
        not change during an update. The ``updated_at`` field is also skipped
        because saving changes to ``source_obj`` will automatically update the
        ``updated_at`` field.

        It is expected that the two objects represent the same thing but from
        different cell databases, so for example, a uuid field (if one exists)
        should not change.

        Note that the changes to ``source_obj`` are not persisted in this
        method.

        :param source_obj: Versioned object from the source cell database
        :param target_obj: Versioned object from the target cell database
        :raises: ObjectActionError if nested object fields are encountered
        """
        ignore_fields = ['created_at', 'id', 'updated_at']
        for field in source_obj.obj_fields:
            if field in target_obj and field not in ignore_fields:
                if isinstance(source_obj.fields[field], fields.ObjectField):
                    raise exception.ObjectActionError(
                        action='_update_source_obj_from_target_cell',
                        reason='nested objects are not supported')
                setattr(source_obj, field, getattr(target_obj, field))

    def _update_bdms_in_source_cell(self, source_cell_context):
        """Update BlockDeviceMapppings in the source cell database.

        It is possible to attach/detach volumes to/from a resized instance,
        which would create/delete BDM records in the target cell, so we have
        to recreate newly attached BDMs in the source cell database and
        delete any old BDMs that were detached while resized in the target
        cell.

        :param source_cell_context: nova auth request context targeted at the
            source cell database
        """
        bdms_from_source_cell = (
            objects.BlockDeviceMappingList.get_by_instance_uuid(
                source_cell_context, self.instance.uuid))
        source_cell_bdms_by_uuid = {
            bdm.uuid: bdm for bdm in bdms_from_source_cell}
        bdms_from_target_cell = (
            objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, self.instance.uuid))
        # Copy new/updated BDMs from the target cell DB to the source cell DB.
        for bdm in bdms_from_target_cell:
            if bdm.uuid in source_cell_bdms_by_uuid:
                # Remove this BDM from the list since we want to preserve it
                # along with its attachment_id.
                source_cell_bdms_by_uuid.pop(bdm.uuid)
            else:
                # Newly attached BDM while in the target cell, so create it
                # in the source cell.
                source_bdm = clone_creatable_object(source_cell_context, bdm)
                # revert_snapshot_based_resize_at_dest is going to delete the
                # attachment for this BDM so we need to create a new empty
                # attachment to reserve this volume so that
                # finish_revert_snapshot_based_resize_at_source can use it.
                attach_ref = self.volume_api.attachment_create(
                    source_cell_context, bdm.volume_id, self.instance.uuid)
                source_bdm.attachment_id = attach_ref['id']
                LOG.debug('Creating BlockDeviceMapping with volume ID %s '
                          'and attachment %s in the source cell database '
                          'since the volume was attached while the server was '
                          'resized.', bdm.volume_id, attach_ref['id'],
                          instance=self.instance)
                source_bdm.create()
        # If there are any source bdms left that were not processed from the
        # target cell bdms, it means those source bdms were detached while
        # resized in the target cell, and we need to delete them from the
        # source cell so they don't re-appear once the revert is complete.
        self._delete_orphan_source_cell_bdms(source_cell_bdms_by_uuid.values())

    def _delete_orphan_source_cell_bdms(self, source_cell_bdms):
        """Deletes orphaned BDMs and volume attachments from the source cell.

        If any volumes were detached while the server was resized into the
        target cell they are destroyed here so they do not show up again once
        the instance is mapped back to the source cell.

        :param source_cell_bdms: Iterator of BlockDeviceMapping objects.
        """
        for bdm in source_cell_bdms:
            LOG.debug('Destroying BlockDeviceMapping with volume ID %s and '
                      'attachment ID %s from source cell database during '
                      'cross-cell resize revert since the volume was detached '
                      'while the server was resized.', bdm.volume_id,
                      bdm.attachment_id, instance=self.instance)
            # First delete the (empty) attachment, created by
            # prep_snapshot_based_resize_at_source, so it is not leaked.
            try:
                self.volume_api.attachment_delete(
                    bdm._context, bdm.attachment_id)
            except Exception as e:
                LOG.error('Failed to delete attachment %s for volume %s. The '
                          'attachment may be leaked and needs to be manually '
                          'cleaned up. Error: %s', bdm.attachment_id,
                          bdm.volume_id, e, instance=self.instance)
            bdm.destroy()

    def _update_instance_actions_in_source_cell(self, source_cell_context):
        """Update instance action records in the source cell database

        We need to copy the REVERT_RESIZE instance action and related events
        from the target cell to the source cell. Otherwise the revert operation
        in the source compute service will not be able to lookup the correct
        instance action to track events.

        :param source_cell_context: nova auth request context targeted at the
            source cell database
        """
        # FIXME(mriedem): This is a hack to just get revert working on
        # the source; we need to re-create any actions created in the target
        # cell DB after the instance was moved while it was in
        # VERIFY_RESIZE status, like if volumes were attached/detached.
        # Can we use a changes-since filter for that, i.e. find the last
        # instance action for the instance in the source cell database and then
        # get all instance actions from the target cell database that were
        # created after that time.
        action = objects.InstanceAction.get_by_request_id(
            self.context, self.instance.uuid, self.context.request_id)
        new_action = clone_creatable_object(source_cell_context, action)
        new_action.create()
        # Also create the events under this action.
        events = objects.InstanceActionEventList.get_by_action(
            self.context, action.id)
        for event in events:
            new_event = clone_creatable_object(source_cell_context, event)
            new_event.create(action.instance_uuid, action.request_id)

    def _update_migration_in_source_cell(self, source_cell_context):
        """Update the migration record in the source cell database.

        Updates the migration record in the source cell database based on the
        current information about the migration in the target cell database.

        :param source_cell_context: nova auth request context targeted at the
            source cell database
        :return: Migration object of the updated source cell database migration
            record
        """
        source_cell_migration = objects.Migration.get_by_uuid(
            source_cell_context, self.migration.uuid)
        # The only change we really expect here is the status changing to
        # "reverting".
        self._update_source_obj_from_target_cell(
            source_cell_migration, self.migration)
        source_cell_migration.save()
        return source_cell_migration

    def _update_instance_in_source_cell(self, instance):
        """Updates the instance and related records in the source cell DB.

        Before reverting in the source cell we need to copy the
        latest state information from the target cell database where the
        instance lived before the revert. This is because data about the
        instance could have changed while it was in VERIFY_RESIZE status, like
        attached volumes.

        :param instance: Instance object from the source cell database
        :return: Migration object of the updated source cell database migration
            record
        """
        LOG.debug('Updating instance-related records in the source cell '
                  'database based on target cell database information.',
                  instance=instance)
        # Copy information from the target cell instance that we need in the
        # source cell instance for doing the revert on the source compute host.
        instance.system_metadata['old_vm_state'] = (
            self.instance.system_metadata.get('old_vm_state'))
        instance.old_flavor = instance.flavor
        instance.task_state = task_states.RESIZE_REVERTING
        instance.save()

        source_cell_context = instance._context
        self._update_bdms_in_source_cell(source_cell_context)
        self._update_instance_actions_in_source_cell(source_cell_context)
        source_cell_migration = self._update_migration_in_source_cell(
            source_cell_context)

        # NOTE(mriedem): We do not have to worry about ports changing while
        # resized since the API does not allow attach/detach interface while
        # resized. Same for tags.
        return source_cell_migration

    def _update_instance_mapping(
            self, source_cell_instance, source_cell_mapping):
        """Swaps the hidden field value on the source and target cell instance
        and updates the instance mapping to point at the source cell.

        :param source_cell_instance: Instance object from the source cell DB
        :param source_cell_mapping: CellMapping object for the source cell
        """
        LOG.debug('Marking instance in target cell as hidden and updating '
                  'instance mapping to point at source cell %s.',
                  source_cell_mapping.identity, instance=source_cell_instance)
        # Get the instance mapping first to make the window of time where both
        # instances are hidden=False as small as possible.
        instance_mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.context, self.instance.uuid)
        # Mark the source cell instance record as hidden=False so it will show
        # up when listing servers. Note that because of how the API filters
        # duplicate instance records, even if the user is listing servers at
        # this exact moment only one copy of the instance will be returned.
        source_cell_instance.hidden = False
        source_cell_instance.save()
        # Update the instance mapping to point at the source cell. We do this
        # before cleaning up the target host/cell because that is really best
        # effort and if something fails on the target we want the user to
        # now interact with the instance in the source cell with the original
        # flavor because they are ultimately trying to revert and get back
        # there, so if they hard reboot/rebuild after an error (for example)
        # that should happen in the source cell.
        instance_mapping.cell_mapping = source_cell_mapping
        instance_mapping.save()
        # Mark the target cell instance record as hidden=True to hide it from
        # the user when listing servers.
        self.instance.hidden = True
        self.instance.save()

    def _execute(self):
        # Send the resize.revert.start notification(s) using the target
        # cell instance since we start there.
        self._send_resize_revert_notification(
            self.instance, fields.NotificationPhase.START)

        source_cell_instance, source_cell_mapping = (
            get_inst_and_cell_map_from_source(
                self.context, self.migration.source_compute,
                self.instance.uuid))
        self._source_cell_instance = source_cell_instance

        # Update the source cell database information based on the target cell
        # database, i.e. the instance/migration/BDMs/action records. Do all of
        # this before updating the instance mapping in case it fails.
        source_cell_migration = self._update_instance_in_source_cell(
            source_cell_instance)

        # Swap the instance.hidden values and update the instance mapping to
        # point at the source cell. From here on out the user will see and
        # operate on the instance in the source cell.
        self._update_instance_mapping(
            source_cell_instance, source_cell_mapping)
        # Save off the source cell migration record for rollbacks.
        self._source_cell_migration = source_cell_migration

        # Clean the instance from the target host.
        LOG.debug('Calling destination host %s to revert cross-cell resize.',
                  self.migration.dest_compute, instance=self.instance)
        # Use the EventReport context manager to create the same event that
        # the dest compute will create but in the source cell DB so we do not
        # have to explicitly copy it over from target to source DB.
        event_name = 'compute_revert_snapshot_based_resize_at_dest'
        with compute_utils.EventReporter(
                source_cell_instance._context, event_name,
                self.migration.dest_compute, self.instance.uuid):
            self.compute_rpcapi.revert_snapshot_based_resize_at_dest(
                self.context, self.instance, self.migration)
            # NOTE(mriedem): revert_snapshot_based_resize_at_dest updates the
            # target cell instance so if we need to do something with it here
            # in the future before destroying it, it should be refreshed.

        # Destroy the instance and its related records from the target cell DB.
        LOG.info('Deleting instance record from target cell %s',
                 self.context.cell_uuid, instance=source_cell_instance)
        # This needs to be a hard delete because if we retry the resize to the
        # target cell we could hit a duplicate entry unique constraint error.
        self.instance.destroy(hard_delete=True)

        # Launch the guest at the source host with the old flavor.
        LOG.debug('Calling source host %s to finish reverting cross-cell '
                  'resize.', self.migration.source_compute,
                  instance=self.instance)
        self.compute_rpcapi.finish_revert_snapshot_based_resize_at_source(
            source_cell_instance._context, source_cell_instance,
            source_cell_migration)
        # finish_revert_snapshot_based_resize_at_source updates the source cell
        # instance so refresh it here so we have the latest copy.
        source_cell_instance.refresh()

        # Finish the conductor_revert_snapshot_based_resize event in the source
        # cell DB. ComputeTaskManager.revert_snapshot_based_resize uses the
        # wrap_instance_event decorator to create this action/event in the
        # target cell DB but now that the target cell instance is gone the
        # event needs to show up in the source cell DB.
        objects.InstanceActionEvent.event_finish(
            source_cell_instance._context, source_cell_instance.uuid,
            'conductor_revert_snapshot_based_resize', want_result=False)

        # Send the resize.revert.end notification using the instance from
        # the source cell since we end there.
        self._send_resize_revert_notification(
            source_cell_instance, fields.NotificationPhase.END)

    def rollback(self, ex):
        with excutils.save_and_reraise_exception():
            # If we have updated the instance mapping to point at the source
            # cell we update the records in the source cell, otherwise we
            # update the records in the target cell.
            instance_at_source = self._source_cell_migration is not None
            migration = self._source_cell_migration or self.migration
            instance = self._source_cell_instance or self.instance
            # NOTE(mriedem): This exception log is fairly generic. We could
            # probably make this more targeted based on what we know of the
            # state of the system if we want to make it more detailed, e.g.
            # the execute method could "record" checkpoints to be used here
            # or we could check to see if the instance was deleted from the
            # target cell by trying to refresh it and handle InstanceNotFound.
            LOG.exception(
                'An error occurred while reverting the resize for instance. '
                'The instance is mapped to the %s cell %s. If the instance '
                'was deleted from the target cell %s then the target host %s '
                'was already cleaned up. If the instance is back in the '
                'source cell then you can try hard-rebooting it to recover.',
                ('source' if instance_at_source else 'target'),
                migration._context.cell_uuid, self.context.cell_uuid,
                migration.dest_compute, instance=instance)
            # If anything failed set the migration status to 'error'.
            migration.status = 'error'
            migration.save()
            # Put the instance into ERROR status, record a fault and send an
            # error notification.
            updates = {'vm_state': vm_states.ERROR, 'task_state': None}
            request_spec = objects.RequestSpec.get_by_instance_uuid(
                self.context, instance.uuid)
            scheduler_utils.set_vm_state_and_notify(
                instance._context, instance.uuid, 'compute_task',
                'migrate_server', updates, ex, request_spec)

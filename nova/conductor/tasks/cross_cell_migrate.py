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
    def __init__(self, context, instance, migration, target_cell_context):
        """Initialize this task.

        :param context: source-cell targeted auth RequestContext
        :param instance: source-cell Instance object
        :param migration: source-cell Migration object for this operation
        :param target_cell_context: target-cell targeted auth RequestContext
        """
        super(TargetDBSetupTask, self).__init__(context, instance)
        self.target_ctx = target_cell_context
        self.migration = migration

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
            if self.migration.uuid == migration.uuid:
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


class CrossCellMigrationTask(base.TaskBase):
    """Orchestrates a cross-cell cold migration (resize)."""

    def __init__(self, context, instance, flavor,
                 request_spec, migration, compute_rpcapi,
                 host_selection, alternate_hosts):
        """Construct the CrossCellMigrationTask instance

        :param context: The user request auth context. This should be targeted
            to the source cell in which the instance is currently running.
        :param instance: The instance being migrated (from the source cell)
        :param flavor: The new flavor if performing resize and not just a
            cold migration
        :param request_spec: nova.objects.RequestSpec with scheduling details
        :param migration: nova.objects.Migration record for this operation
            (from the source cell)
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
        self.migration = migration
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
            self.context, self.instance, self.migration,
            self._target_cell_context)
        self._target_cell_instance, target_cell_migration = task.execute()
        self._completed_tasks['TargetDBSetupTask'] = task
        return target_cell_migration

    def _perform_external_api_checks(self):
        """Performs checks on external service APIs for support.

        * Checks that the neutron port binding-extended API is available
        * Checks that the 3.44 volume attachments API is available

        :raises: MigrationPreCheckError if any checks fail
        """
        LOG.debug('Making sure cinder and neutron are new enough for '
                  'cross-cell resize.')
        # Check that the port binding-extended API extension is available in
        # neutron because if it's not we can just fail fast.
        if not self.network_api.supports_port_binding_extension(self.context):
            raise exception.MigrationPreCheckError(
                reason=_("Required networking service API extension '%s' "
                         "not found.") %
                neutron_constants.PORT_BINDING_EXTENDED)

        # Check that Cinder API 3.44 is available otherwise we can't use the
        # volume attachments API.
        try:
            cinder.is_microversion_supported(self.context, '3.44')
        except exception.CinderAPIVersionNotAvailable as ex:
            raise exception.MigrationPreCheckError(
                reason=ex.format_message())

    def _execute(self):
        """Execute high-level orchestration of the cross-cell resize"""
        # We are committed to a cross-cell move at this point so update the
        # migration record to reflect that.
        self.migration.cross_cell_move = True
        self.migration.save()
        # Make sure neutron and cinder APIs we need are available.
        self._perform_external_api_checks()

        # Before preparing the target host create the instance record data
        # in the target cell database since we cannot do anything in the
        # target cell without having an instance record there. Remember that
        # we lose the cell-targeting on the request context over RPC so we
        # cannot simply pass the source cell context and instance over RPC
        # to the target compute host and assume changes get mirrored back to
        # the source cell database.
        self._setup_target_cell_db()

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

# Copyright (c) 2012 Rackspace Hosting
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
Cells Service Manager
"""
import datetime
import time

from oslo_log import log as logging
import oslo_messaging
from oslo_service import periodic_task
from oslo_utils import importutils
from oslo_utils import timeutils
import six
from six.moves import range

from nova.cells import messaging
from nova.cells import state as cells_state
from nova.cells import utils as cells_utils
import nova.conf
from nova import context
from nova import exception
from nova.i18n import _LW
from nova import manager
from nova import objects
from nova.objects import base as base_obj
from nova.objects import instance as instance_obj


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class CellsManager(manager.Manager):
    """The nova-cells manager class.  This class defines RPC
    methods that the local cell may call.  This class is NOT used for
    messages coming from other cells.  That communication is
    driver-specific.

    Communication to other cells happens via the nova.cells.messaging module.
    The MessageRunner from that module will handle routing the message to
    the correct cell via the communications driver.  Most methods below
    create 'targeted' (where we want to route a message to a specific cell)
    or 'broadcast' (where we want a message to go to multiple cells)
    messages.

    Scheduling requests get passed to the scheduler class.
    """

    target = oslo_messaging.Target(version='1.37')

    def __init__(self, *args, **kwargs):
        LOG.warning(_LW('The cells feature of Nova is considered experimental '
                        'by the OpenStack project because it receives much '
                        'less testing than the rest of Nova. This may change '
                        'in the future, but current deployers should be aware '
                        'that the use of it in production right now may be '
                        'risky. Also note that cells does not currently '
                        'support rolling upgrades, it is assumed that cells '
                        'deployments are upgraded lockstep so n-1 cells '
                        'compatibility does not work.'))
        # Mostly for tests.
        cell_state_manager = kwargs.pop('cell_state_manager', None)
        super(CellsManager, self).__init__(service_name='cells',
                                           *args, **kwargs)
        if cell_state_manager is None:
            cell_state_manager = cells_state.CellStateManager
        self.state_manager = cell_state_manager()
        self.msg_runner = messaging.MessageRunner(self.state_manager)
        cells_driver_cls = importutils.import_class(
                CONF.cells.driver)
        self.driver = cells_driver_cls()
        self.instances_to_heal = iter([])

    def post_start_hook(self):
        """Have the driver start its servers for inter-cell communication.
        Also ask our child cells for their capacities and capabilities so
        we get them more quickly than just waiting for the next periodic
        update.  Receiving the updates from the children will cause us to
        update our parents.  If we don't have any children, just update
        our parents immediately.
        """
        # FIXME(comstud): There's currently no hooks when services are
        # stopping, so we have no way to stop servers cleanly.
        self.driver.start_servers(self.msg_runner)
        ctxt = context.get_admin_context()
        if self.state_manager.get_child_cells():
            self.msg_runner.ask_children_for_capabilities(ctxt)
            self.msg_runner.ask_children_for_capacities(ctxt)
        else:
            self._update_our_parents(ctxt)

    @periodic_task.periodic_task
    def _update_our_parents(self, ctxt):
        """Update our parent cells with our capabilities and capacity
        if we're at the bottom of the tree.
        """
        self.msg_runner.tell_parents_our_capabilities(ctxt)
        self.msg_runner.tell_parents_our_capacities(ctxt)

    @periodic_task.periodic_task
    def _heal_instances(self, ctxt):
        """Periodic task to send updates for a number of instances to
        parent cells.

        On every run of the periodic task, we will attempt to sync
        'CONF.cells.instance_update_num_instances' number of instances.
        When we get the list of instances, we shuffle them so that multiple
        nova-cells services aren't attempting to sync the same instances
        in lockstep.

        If CONF.cells.instance_update_at_threshold is set, only attempt
        to sync instances that have been updated recently.  The CONF
        setting defines the maximum number of seconds old the updated_at
        can be.  Ie, a threshold of 3600 means to only update instances
        that have modified in the last hour.
        """

        if not self.state_manager.get_parent_cells():
            # No need to sync up if we have no parents.
            return

        info = {'updated_list': False}

        def _next_instance():
            try:
                instance = next(self.instances_to_heal)
            except StopIteration:
                if info['updated_list']:
                    return
                threshold = CONF.cells.instance_updated_at_threshold
                updated_since = None
                if threshold > 0:
                    updated_since = timeutils.utcnow() - datetime.timedelta(
                            seconds=threshold)
                self.instances_to_heal = cells_utils.get_instances_to_sync(
                        ctxt, updated_since=updated_since, shuffle=True,
                        uuids_only=True)
                info['updated_list'] = True
                try:
                    instance = next(self.instances_to_heal)
                except StopIteration:
                    return
            return instance

        rd_context = ctxt.elevated(read_deleted='yes')

        for i in range(CONF.cells.instance_update_num_instances):
            while True:
                # Yield to other greenthreads
                time.sleep(0)
                instance_uuid = _next_instance()
                if not instance_uuid:
                    return
                try:
                    instance = objects.Instance.get_by_uuid(rd_context,
                            instance_uuid)
                except exception.InstanceNotFound:
                    continue
                self._sync_instance(ctxt, instance)
                break

    def _sync_instance(self, ctxt, instance):
        """Broadcast an instance_update or instance_destroy message up to
        parent cells.
        """
        if instance.deleted:
            self.instance_destroy_at_top(ctxt, instance)
        else:
            self.instance_update_at_top(ctxt, instance)

    def build_instances(self, ctxt, build_inst_kwargs):
        """Pick a cell (possibly ourselves) to build new instance(s) and
        forward the request accordingly.
        """
        # Target is ourselves first.
        filter_properties = build_inst_kwargs.get('filter_properties')
        if (filter_properties is not None and
            not isinstance(filter_properties['instance_type'],
                           objects.Flavor)):
            # NOTE(danms): Handle pre-1.30 build_instances() call. Remove me
            # when we bump the RPC API version to 2.0.
            flavor = objects.Flavor(**filter_properties['instance_type'])
            build_inst_kwargs['filter_properties'] = dict(
                filter_properties, instance_type=flavor)
        instances = build_inst_kwargs['instances']
        if not isinstance(instances[0], objects.Instance):
            # NOTE(danms): Handle pre-1.32 build_instances() call. Remove me
            # when we bump the RPC API version to 2.0
            build_inst_kwargs['instances'] = instance_obj._make_instance_list(
                ctxt, objects.InstanceList(), instances, ['system_metadata',
                                                          'metadata'])
        our_cell = self.state_manager.get_my_state()
        self.msg_runner.build_instances(ctxt, our_cell, build_inst_kwargs)

    def get_cell_info_for_neighbors(self, _ctxt):
        """Return cell information for our neighbor cells."""
        return self.state_manager.get_cell_info_for_neighbors()

    def run_compute_api_method(self, ctxt, cell_name, method_info, call):
        """Call a compute API method in a specific cell."""
        response = self.msg_runner.run_compute_api_method(ctxt,
                                                          cell_name,
                                                          method_info,
                                                          call)
        if call:
            return response.value_or_raise()

    def instance_update_at_top(self, ctxt, instance):
        """Update an instance at the top level cell."""
        self.msg_runner.instance_update_at_top(ctxt, instance)

    def instance_destroy_at_top(self, ctxt, instance):
        """Destroy an instance at the top level cell."""
        self.msg_runner.instance_destroy_at_top(ctxt, instance)

    def instance_delete_everywhere(self, ctxt, instance, delete_type):
        """This is used by API cell when it didn't know what cell
        an instance was in, but the instance was requested to be
        deleted or soft_deleted.  So, we'll broadcast this everywhere.
        """
        if isinstance(instance, dict):
            instance = objects.Instance._from_db_object(ctxt,
                    objects.Instance(), instance)
        self.msg_runner.instance_delete_everywhere(ctxt, instance,
                                                   delete_type)

    def instance_fault_create_at_top(self, ctxt, instance_fault):
        """Create an instance fault at the top level cell."""
        self.msg_runner.instance_fault_create_at_top(ctxt, instance_fault)

    def bw_usage_update_at_top(self, ctxt, bw_update_info):
        """Update bandwidth usage at top level cell."""
        self.msg_runner.bw_usage_update_at_top(ctxt, bw_update_info)

    def sync_instances(self, ctxt, project_id, updated_since, deleted):
        """Force a sync of all instances, potentially by project_id,
        and potentially since a certain date/time.
        """
        self.msg_runner.sync_instances(ctxt, project_id, updated_since,
                                       deleted)

    def service_get_all(self, ctxt, filters):
        """Return services in this cell and in all child cells."""
        responses = self.msg_runner.service_get_all(ctxt, filters)
        ret_services = []
        # 1 response per cell.  Each response is a list of services.
        for response in responses:
            services = response.value_or_raise()
            for service in services:
                service = cells_utils.add_cell_to_service(
                    service, response.cell_name)
                ret_services.append(service)
        return ret_services

    @oslo_messaging.expected_exceptions(exception.CellRoutingInconsistency)
    def service_get_by_compute_host(self, ctxt, host_name):
        """Return a service entry for a compute host in a certain cell."""
        cell_name, host_name = cells_utils.split_cell_and_item(host_name)
        response = self.msg_runner.service_get_by_compute_host(ctxt,
                                                               cell_name,
                                                               host_name)
        service = response.value_or_raise()
        service = cells_utils.add_cell_to_service(service, response.cell_name)
        return service

    def get_host_uptime(self, ctxt, host_name):
        """Return host uptime for a compute host in a certain cell

        :param host_name: fully qualified hostname. It should be in format of
         parent!child@host_id
        """
        cell_name, host_name = cells_utils.split_cell_and_item(host_name)
        response = self.msg_runner.get_host_uptime(ctxt, cell_name,
                                                   host_name)
        return response.value_or_raise()

    def service_update(self, ctxt, host_name, binary, params_to_update):
        """Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        :returns: the service reference
        """
        cell_name, host_name = cells_utils.split_cell_and_item(host_name)
        response = self.msg_runner.service_update(
            ctxt, cell_name, host_name, binary, params_to_update)
        service = response.value_or_raise()
        service = cells_utils.add_cell_to_service(service, response.cell_name)
        return service

    def service_delete(self, ctxt, cell_service_id):
        """Deletes the specified service."""
        cell_name, service_id = cells_utils.split_cell_and_item(
            cell_service_id)
        self.msg_runner.service_delete(ctxt, cell_name, service_id)

    @oslo_messaging.expected_exceptions(exception.CellRoutingInconsistency)
    def proxy_rpc_to_manager(self, ctxt, topic, rpc_message, call, timeout):
        """Proxy an RPC message as-is to a manager."""
        compute_topic = CONF.compute_topic
        cell_and_host = topic[len(compute_topic) + 1:]
        cell_name, host_name = cells_utils.split_cell_and_item(cell_and_host)
        response = self.msg_runner.proxy_rpc_to_manager(ctxt, cell_name,
                host_name, topic, rpc_message, call, timeout)
        return response.value_or_raise()

    def task_log_get_all(self, ctxt, task_name, period_beginning,
                         period_ending, host=None, state=None):
        """Get task logs from the DB from all cells or a particular
        cell.

        If 'host' is not None, host will be of the format 'cell!name@host',
        with '@host' being optional.  The query will be directed to the
        appropriate cell and return all task logs, or task logs matching
        the host if specified.

        'state' also may be None.  If it's not, filter by the state as well.
        """
        if host is None:
            cell_name = None
        else:
            cell_name, host = cells_utils.split_cell_and_item(host)
            # If no cell name was given, assume that the host name is the
            # cell_name and that the target is all hosts
            if cell_name is None:
                cell_name, host = host, cell_name
        responses = self.msg_runner.task_log_get_all(ctxt, cell_name,
                task_name, period_beginning, period_ending,
                host=host, state=state)
        # 1 response per cell.  Each response is a list of task log
        # entries.
        ret_task_logs = []
        for response in responses:
            task_logs = response.value_or_raise()
            for task_log in task_logs:
                cells_utils.add_cell_to_task_log(task_log,
                                                 response.cell_name)
                ret_task_logs.append(task_log)
        return ret_task_logs

    @oslo_messaging.expected_exceptions(exception.CellRoutingInconsistency)
    def compute_node_get(self, ctxt, compute_id):
        """Get a compute node by ID in a specific cell."""
        cell_name, compute_id = cells_utils.split_cell_and_item(
                compute_id)
        response = self.msg_runner.compute_node_get(ctxt, cell_name,
                                                    compute_id)
        node = response.value_or_raise()
        node = cells_utils.add_cell_to_compute_node(node, cell_name)
        return node

    def compute_node_get_all(self, ctxt, hypervisor_match=None):
        """Return list of compute nodes in all cells."""
        responses = self.msg_runner.compute_node_get_all(ctxt,
                hypervisor_match=hypervisor_match)
        # 1 response per cell.  Each response is a list of compute_node
        # entries.
        ret_nodes = []
        for response in responses:
            nodes = response.value_or_raise()
            for node in nodes:
                node = cells_utils.add_cell_to_compute_node(node,
                                                            response.cell_name)
                ret_nodes.append(node)
        return ret_nodes

    def compute_node_stats(self, ctxt):
        """Return compute node stats totals from all cells."""
        responses = self.msg_runner.compute_node_stats(ctxt)
        totals = {}
        for response in responses:
            data = response.value_or_raise()
            for key, val in six.iteritems(data):
                totals.setdefault(key, 0)
                totals[key] += val
        return totals

    def actions_get(self, ctxt, cell_name, instance_uuid):
        response = self.msg_runner.actions_get(ctxt, cell_name, instance_uuid)
        return response.value_or_raise()

    def action_get_by_request_id(self, ctxt, cell_name, instance_uuid,
                                 request_id):
        response = self.msg_runner.action_get_by_request_id(ctxt, cell_name,
                                                            instance_uuid,
                                                            request_id)
        return response.value_or_raise()

    def action_events_get(self, ctxt, cell_name, action_id):
        response = self.msg_runner.action_events_get(ctxt, cell_name,
                                                     action_id)
        return response.value_or_raise()

    def consoleauth_delete_tokens(self, ctxt, instance_uuid):
        """Delete consoleauth tokens for an instance in API cells."""
        self.msg_runner.consoleauth_delete_tokens(ctxt, instance_uuid)

    def validate_console_port(self, ctxt, instance_uuid, console_port,
                              console_type):
        """Validate console port with child cell compute node."""
        instance = objects.Instance.get_by_uuid(ctxt, instance_uuid)
        if not instance.cell_name:
            raise exception.InstanceUnknownCell(instance_uuid=instance_uuid)
        response = self.msg_runner.validate_console_port(ctxt,
                instance.cell_name, instance_uuid, console_port,
                console_type)
        return response.value_or_raise()

    def get_capacities(self, ctxt, cell_name):
        return self.state_manager.get_capacities(cell_name)

    def bdm_update_or_create_at_top(self, ctxt, bdm, create=None):
        """BDM was created/updated in this cell.  Tell the API cells."""
        # TODO(ndipanov): Move inter-cell RPC to use objects
        bdm = base_obj.obj_to_primitive(bdm)
        self.msg_runner.bdm_update_or_create_at_top(ctxt, bdm, create=create)

    def bdm_destroy_at_top(self, ctxt, instance_uuid, device_name=None,
                           volume_id=None):
        """BDM was destroyed for instance in this cell.  Tell the API cells."""
        self.msg_runner.bdm_destroy_at_top(ctxt, instance_uuid,
                                           device_name=device_name,
                                           volume_id=volume_id)

    def get_migrations(self, ctxt, filters):
        """Fetch migrations applying the filters."""
        target_cell = None
        if "cell_name" in filters:
            _path_cell_sep = cells_utils.PATH_CELL_SEP
            target_cell = '%s%s%s' % (CONF.cells.name, _path_cell_sep,
                                      filters['cell_name'])

        responses = self.msg_runner.get_migrations(ctxt, target_cell,
                                                       False, filters)
        migrations = []
        for response in responses:
            migrations += response.value_or_raise()
        return migrations

    def instance_update_from_api(self, ctxt, instance, expected_vm_state,
                        expected_task_state, admin_state_reset):
        """Update an instance in its cell."""
        self.msg_runner.instance_update_from_api(ctxt, instance,
                                                 expected_vm_state,
                                                 expected_task_state,
                                                 admin_state_reset)

    def start_instance(self, ctxt, instance):
        """Start an instance in its cell."""
        self.msg_runner.start_instance(ctxt, instance)

    def stop_instance(self, ctxt, instance, do_cast=True,
                      clean_shutdown=True):
        """Stop an instance in its cell."""
        response = self.msg_runner.stop_instance(ctxt, instance,
                                                 do_cast=do_cast,
                                                 clean_shutdown=clean_shutdown)
        if not do_cast:
            return response.value_or_raise()

    def cell_create(self, ctxt, values):
        return self.state_manager.cell_create(ctxt, values)

    def cell_update(self, ctxt, cell_name, values):
        return self.state_manager.cell_update(ctxt, cell_name, values)

    def cell_delete(self, ctxt, cell_name):
        return self.state_manager.cell_delete(ctxt, cell_name)

    def cell_get(self, ctxt, cell_name):
        return self.state_manager.cell_get(ctxt, cell_name)

    def reboot_instance(self, ctxt, instance, reboot_type):
        """Reboot an instance in its cell."""
        self.msg_runner.reboot_instance(ctxt, instance, reboot_type)

    def pause_instance(self, ctxt, instance):
        """Pause an instance in its cell."""
        self.msg_runner.pause_instance(ctxt, instance)

    def unpause_instance(self, ctxt, instance):
        """Unpause an instance in its cell."""
        self.msg_runner.unpause_instance(ctxt, instance)

    def suspend_instance(self, ctxt, instance):
        """Suspend an instance in its cell."""
        self.msg_runner.suspend_instance(ctxt, instance)

    def resume_instance(self, ctxt, instance):
        """Resume an instance in its cell."""
        self.msg_runner.resume_instance(ctxt, instance)

    def terminate_instance(self, ctxt, instance, delete_type='delete'):
        """Delete an instance in its cell."""
        # NOTE(rajesht): The `delete_type` parameter is passed so that it will
        # be routed to destination cell, where instance deletion will happen.
        self.msg_runner.terminate_instance(ctxt, instance,
                                           delete_type=delete_type)

    def soft_delete_instance(self, ctxt, instance):
        """Soft-delete an instance in its cell."""
        self.msg_runner.soft_delete_instance(ctxt, instance)

    def resize_instance(self, ctxt, instance, flavor,
                        extra_instance_updates,
                        clean_shutdown=True):
        """Resize an instance in its cell."""
        self.msg_runner.resize_instance(ctxt, instance,
                                        flavor, extra_instance_updates,
                                        clean_shutdown=clean_shutdown)

    def live_migrate_instance(self, ctxt, instance, block_migration,
                              disk_over_commit, host_name):
        """Live migrate an instance in its cell."""
        self.msg_runner.live_migrate_instance(ctxt, instance,
                                              block_migration,
                                              disk_over_commit,
                                              host_name)

    def revert_resize(self, ctxt, instance):
        """Revert a resize for an instance in its cell."""
        self.msg_runner.revert_resize(ctxt, instance)

    def confirm_resize(self, ctxt, instance):
        """Confirm a resize for an instance in its cell."""
        self.msg_runner.confirm_resize(ctxt, instance)

    def reset_network(self, ctxt, instance):
        """Reset networking for an instance in its cell."""
        self.msg_runner.reset_network(ctxt, instance)

    def inject_network_info(self, ctxt, instance):
        """Inject networking for an instance in its cell."""
        self.msg_runner.inject_network_info(ctxt, instance)

    def snapshot_instance(self, ctxt, instance, image_id):
        """Snapshot an instance in its cell."""
        self.msg_runner.snapshot_instance(ctxt, instance, image_id)

    def backup_instance(self, ctxt, instance, image_id, backup_type, rotation):
        """Backup an instance in its cell."""
        self.msg_runner.backup_instance(ctxt, instance, image_id,
                                        backup_type, rotation)

    def rebuild_instance(self, ctxt, instance, image_href, admin_password,
                         files_to_inject, preserve_ephemeral, kwargs):
        self.msg_runner.rebuild_instance(ctxt, instance, image_href,
                                         admin_password, files_to_inject,
                                         preserve_ephemeral, kwargs)

    def set_admin_password(self, ctxt, instance, new_pass):
        self.msg_runner.set_admin_password(ctxt, instance, new_pass)

    def get_keypair_at_top(self, ctxt, user_id, name):
        responses = self.msg_runner.get_keypair_at_top(ctxt, user_id, name)
        keypairs = [resp.value for resp in responses if resp.value is not None]

        if len(keypairs) == 0:
            return None
        elif len(keypairs) > 1:
            cell_names = ', '.join([resp.cell_name for resp in responses
                                    if resp.value is not None])
            LOG.warning(_LW("The same keypair name '%(name)s' exists in the "
                            "following cells: %(cell_names)s. The keypair "
                            "value from the first cell is returned."),
                        {'name': name, 'cell_names': cell_names})

        return keypairs[0]

#    Copyright 2013 IBM Corp.
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

"""Handles database requests from other nova services."""

import copy
import itertools

import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import timeutils
import six

from nova.api.ec2 import ec2utils
from nova import block_device
from nova.cells import rpcapi as cells_rpcapi
from nova.compute import api as compute_api
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor.tasks import live_migrate
from nova.db import base
from nova import exception
from nova.i18n import _, _LE, _LW
from nova import image
from nova import manager
from nova import network
from nova.network.security_group import openstack_driver
from nova import notifications
from nova import objects
from nova.objects import base as nova_object
from nova.openstack.common import log as logging
from nova import quota
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils

LOG = logging.getLogger(__name__)

# Instead of having a huge list of arguments to instance_update(), we just
# accept a dict of fields to update and use this whitelist to validate it.
allowed_updates = ['task_state', 'vm_state', 'expected_task_state',
                   'power_state', 'access_ip_v4', 'access_ip_v6',
                   'launched_at', 'terminated_at', 'host', 'node',
                   'memory_mb', 'vcpus', 'root_gb', 'ephemeral_gb',
                   'instance_type_id', 'root_device_name', 'launched_on',
                   'progress', 'vm_mode', 'default_ephemeral_device',
                   'default_swap_device', 'root_device_name',
                   'system_metadata', 'updated_at'
                   ]

# Fields that we want to convert back into a datetime object.
datetime_fields = ['launched_at', 'terminated_at', 'updated_at']


class ConductorManager(manager.Manager):
    """Mission: Conduct things.

    The methods in the base API for nova-conductor are various proxy operations
    performed on behalf of the nova-compute service running on compute nodes.
    Compute nodes are not allowed to directly access the database, so this set
    of methods allows them to get specific work done without locally accessing
    the database.

    The nova-conductor service also exposes an API in the 'compute_task'
    namespace.  See the ComputeTaskManager class for details.
    """

    target = messaging.Target(version='2.1')

    def __init__(self, *args, **kwargs):
        super(ConductorManager, self).__init__(service_name='conductor',
                                               *args, **kwargs)
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())
        self._network_api = None
        self._compute_api = None
        self.compute_task_mgr = ComputeTaskManager()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        self.additional_endpoints.append(self.compute_task_mgr)

    @property
    def network_api(self):
        # NOTE(danms): We need to instantiate our network_api on first use
        # to avoid the circular dependency that exists between our init
        # and network_api's
        if self._network_api is None:
            self._network_api = network.API()
        return self._network_api

    @property
    def compute_api(self):
        if self._compute_api is None:
            self._compute_api = compute_api.API()
        return self._compute_api

    def ping(self, context, arg):
        # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
        # now a part of the base rpc API.
        return jsonutils.to_primitive({'service': 'conductor', 'arg': arg})

    @messaging.expected_exceptions(KeyError, ValueError,
                                   exception.InvalidUUID,
                                   exception.InstanceNotFound,
                                   exception.UnexpectedTaskStateError)
    def instance_update(self, context, instance_uuid,
                        updates, service):
        for key, value in updates.iteritems():
            if key not in allowed_updates:
                LOG.error(_LE("Instance update attempted for "
                              "'%(key)s' on %(instance_uuid)s"),
                          {'key': key, 'instance_uuid': instance_uuid})
                raise KeyError("unexpected update keyword '%s'" % key)
            if key in datetime_fields and isinstance(value, six.string_types):
                updates[key] = timeutils.parse_strtime(value)

        # NOTE(danms): the send_update() call below is going to want to know
        # about the flavor, so we need to join the appropriate things here,
        # and objectify the result.
        old_ref, instance_ref = self.db.instance_update_and_get_original(
            context, instance_uuid, updates,
            columns_to_join=['system_metadata'])
        inst_obj = objects.Instance._from_db_object(
            context, objects.Instance(),
            instance_ref, expected_attrs=['system_metadata'])
        notifications.send_update(context, old_ref, inst_obj, service)
        return jsonutils.to_primitive(instance_ref)

    @messaging.expected_exceptions(exception.InstanceNotFound)
    def instance_get_by_uuid(self, context, instance_uuid,
                             columns_to_join):
        return jsonutils.to_primitive(
            self.db.instance_get_by_uuid(context, instance_uuid,
                columns_to_join))

    def instance_get_all_by_host(self, context, host, node,
                                 columns_to_join):
        if node is not None:
            result = self.db.instance_get_all_by_host_and_node(
                context.elevated(), host, node)
        else:
            result = self.db.instance_get_all_by_host(context.elevated(), host,
                                                      columns_to_join)
        return jsonutils.to_primitive(result)

    def migration_get_in_progress_by_host_and_node(self, context,
                                                   host, node):
        migrations = self.db.migration_get_in_progress_by_host_and_node(
            context, host, node)
        return jsonutils.to_primitive(migrations)

    @messaging.expected_exceptions(exception.AggregateHostExists)
    def aggregate_host_add(self, context, aggregate, host):
        host_ref = self.db.aggregate_host_add(context.elevated(),
                aggregate['id'], host)

        return jsonutils.to_primitive(host_ref)

    @messaging.expected_exceptions(exception.AggregateHostNotFound)
    def aggregate_host_delete(self, context, aggregate, host):
        self.db.aggregate_host_delete(context.elevated(),
                aggregate['id'], host)

    def aggregate_metadata_get_by_host(self, context, host,
                                       key='availability_zone'):
        result = self.db.aggregate_metadata_get_by_host(context, host, key)
        return jsonutils.to_primitive(result)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in, bw_out, last_ctr_in, last_ctr_out,
                        last_refreshed, update_cells):
        if [bw_in, bw_out, last_ctr_in, last_ctr_out].count(None) != 4:
            self.db.bw_usage_update(context, uuid, mac, start_period,
                                    bw_in, bw_out, last_ctr_in, last_ctr_out,
                                    last_refreshed,
                                    update_cells=update_cells)
        usage = self.db.bw_usage_get(context, uuid, start_period, mac)
        return jsonutils.to_primitive(usage)

    def provider_fw_rule_get_all(self, context):
        rules = self.db.provider_fw_rule_get_all(context)
        return jsonutils.to_primitive(rules)

    # NOTE(danms): This can be removed in version 3.0 of the RPC API
    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        info = self.db.agent_build_get_by_triple(context, hypervisor, os,
                                                 architecture)
        return jsonutils.to_primitive(info)

    def block_device_mapping_update_or_create(self, context, values, create):
        if create is None:
            bdm = self.db.block_device_mapping_update_or_create(context,
                                                                values)
        elif create is True:
            bdm = self.db.block_device_mapping_create(context, values)
        else:
            bdm = self.db.block_device_mapping_update(context,
                                                      values['id'],
                                                      values)
        bdm_obj = objects.BlockDeviceMapping._from_db_object(
                context, objects.BlockDeviceMapping(), bdm)
        self.cells_rpcapi.bdm_update_or_create_at_top(context, bdm_obj,
                                                      create=create)

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy):
        bdms = self.db.block_device_mapping_get_all_by_instance(
            context, instance['uuid'])
        if legacy:
            bdms = block_device.legacy_mapping(bdms)
        return jsonutils.to_primitive(bdms)

    def instance_get_all_by_filters(self, context, filters, sort_key,
                                    sort_dir, columns_to_join,
                                    use_slave):
        result = self.db.instance_get_all_by_filters(
            context, filters, sort_key, sort_dir,
            columns_to_join=columns_to_join, use_slave=use_slave)
        return jsonutils.to_primitive(result)

    def instance_get_active_by_window(self, context, begin, end,
                                      project_id, host):
        # Unused, but cannot remove until major RPC version bump
        result = self.db.instance_get_active_by_window(context, begin, end,
                                                       project_id, host)
        return jsonutils.to_primitive(result)

    def instance_get_active_by_window_joined(self, context, begin, end,
                                             project_id, host):
        result = self.db.instance_get_active_by_window_joined(
            context, begin, end, project_id, host)
        return jsonutils.to_primitive(result)

    def instance_destroy(self, context, instance):
        result = self.db.instance_destroy(context, instance['uuid'])
        return jsonutils.to_primitive(result)

    def instance_fault_create(self, context, values):
        result = self.db.instance_fault_create(context, values)
        return jsonutils.to_primitive(result)

    # NOTE(kerrin): The last_refreshed argument is unused by this method
    # and can be removed in v3.0 of the RPC API.
    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed, update_totals):
        vol_usage = self.db.vol_usage_update(context, vol_id,
                                             rd_req, rd_bytes,
                                             wr_req, wr_bytes,
                                             instance['uuid'],
                                             instance['project_id'],
                                             instance['user_id'],
                                             instance['availability_zone'],
                                             update_totals)

        # We have just updated the database, so send the notification now
        self.notifier.info(context, 'volume.usage',
                           compute_utils.usage_volume_info(vol_usage))

    @messaging.expected_exceptions(exception.ComputeHostNotFound,
                                   exception.HostBinaryNotFound)
    def service_get_all_by(self, context, topic, host, binary):
        if not any((topic, host, binary)):
            result = self.db.service_get_all(context)
        elif all((topic, host)):
            if topic == 'compute':
                result = self.db.service_get_by_compute_host(context, host)
                # FIXME(comstud) Potentially remove this on bump to v3.0
                result = [result]
            else:
                result = self.db.service_get_by_host_and_topic(context,
                                                               host, topic)
        elif all((host, binary)):
            result = self.db.service_get_by_args(context, host, binary)
        elif topic:
            result = self.db.service_get_all_by_topic(context, topic)
        elif host:
            result = self.db.service_get_all_by_host(context, host)

        return jsonutils.to_primitive(result)

    @messaging.expected_exceptions(exception.InstanceActionNotFound)
    def action_event_start(self, context, values):
        evt = self.db.action_event_start(context, values)
        return jsonutils.to_primitive(evt)

    @messaging.expected_exceptions(exception.InstanceActionNotFound,
                                   exception.InstanceActionEventNotFound)
    def action_event_finish(self, context, values):
        evt = self.db.action_event_finish(context, values)
        return jsonutils.to_primitive(evt)

    def service_create(self, context, values):
        svc = self.db.service_create(context, values)
        return jsonutils.to_primitive(svc)

    @messaging.expected_exceptions(exception.ServiceNotFound)
    def service_destroy(self, context, service_id):
        self.db.service_destroy(context, service_id)

    def compute_node_create(self, context, values):
        result = self.db.compute_node_create(context, values)
        return jsonutils.to_primitive(result)

    def compute_node_update(self, context, node, values):
        result = self.db.compute_node_update(context, node['id'], values)
        return jsonutils.to_primitive(result)

    def compute_node_delete(self, context, node):
        result = self.db.compute_node_delete(context, node['id'])
        return jsonutils.to_primitive(result)

    @messaging.expected_exceptions(exception.ServiceNotFound)
    def service_update(self, context, service, values):
        svc = self.db.service_update(context, service['id'], values)
        return jsonutils.to_primitive(svc)

    def task_log_get(self, context, task_name, begin, end, host, state):
        result = self.db.task_log_get(context, task_name, begin, end, host,
                                      state)
        return jsonutils.to_primitive(result)

    def task_log_begin_task(self, context, task_name, begin, end, host,
                            task_items, message):
        result = self.db.task_log_begin_task(context.elevated(), task_name,
                                             begin, end, host, task_items,
                                             message)
        return jsonutils.to_primitive(result)

    def task_log_end_task(self, context, task_name, begin, end, host,
                          errors, message):
        result = self.db.task_log_end_task(context.elevated(), task_name,
                                           begin, end, host, errors, message)
        return jsonutils.to_primitive(result)

    def notify_usage_exists(self, context, instance, current_period,
                            ignore_missing_network_data,
                            system_metadata, extra_usage_info):
        if not isinstance(instance, objects.Instance):
            attrs = ['metadata', 'system_metadata']
            instance = objects.Instance._from_db_object(context,
                                                        objects.Instance(),
                                                        instance,
                                                        expected_attrs=attrs)
        compute_utils.notify_usage_exists(self.notifier, context, instance,
                                          current_period,
                                          ignore_missing_network_data,
                                          system_metadata, extra_usage_info)

    def security_groups_trigger_handler(self, context, event, args):
        self.security_group_api.trigger_handler(event, context, *args)

    def security_groups_trigger_members_refresh(self, context, group_ids):
        self.security_group_api.trigger_members_refresh(context, group_ids)

    def network_migrate_instance_start(self, context, instance, migration):
        self.network_api.migrate_instance_start(context, instance, migration)

    def network_migrate_instance_finish(self, context, instance, migration):
        self.network_api.migrate_instance_finish(context, instance, migration)

    def quota_commit(self, context, reservations, project_id=None,
                     user_id=None):
        quota.QUOTAS.commit(context, reservations, project_id=project_id,
                            user_id=user_id)

    def quota_rollback(self, context, reservations, project_id=None,
                       user_id=None):
        quota.QUOTAS.rollback(context, reservations, project_id=project_id,
                              user_id=user_id)

    def get_ec2_ids(self, context, instance):
        ec2_ids = {}

        ec2_ids['instance-id'] = ec2utils.id_to_ec2_inst_id(instance['uuid'])
        ec2_ids['ami-id'] = ec2utils.glance_id_to_ec2_id(context,
                                                         instance['image_ref'])
        for image_type in ['kernel', 'ramdisk']:
            image_id = instance.get('%s_id' % image_type)
            if image_id is not None:
                ec2_image_type = ec2utils.image_type(image_type)
                ec2_id = ec2utils.glance_id_to_ec2_id(context, image_id,
                                                      ec2_image_type)
                ec2_ids['%s-id' % image_type] = ec2_id

        return ec2_ids

    def compute_unrescue(self, context, instance):
        self.compute_api.unrescue(context, instance)

    def _object_dispatch(self, target, method, context, args, kwargs):
        """Dispatch a call to an object method.

        This ensures that object methods get called and any exception
        that is raised gets wrapped in an ExpectedException for forwarding
        back to the caller (without spamming the conductor logs).
        """
        try:
            # NOTE(danms): Keep the getattr inside the try block since
            # a missing method is really a client problem
            return getattr(target, method)(context, *args, **kwargs)
        except Exception:
            raise messaging.ExpectedException()

    def object_class_action(self, context, objname, objmethod,
                            objver, args, kwargs):
        """Perform a classmethod action on an object."""
        objclass = nova_object.NovaObject.obj_class_from_name(objname,
                                                              objver)
        result = self._object_dispatch(objclass, objmethod, context,
                                       args, kwargs)
        # NOTE(danms): The RPC layer will convert to primitives for us,
        # but in this case, we need to honor the version the client is
        # asking for, so we do it before returning here.
        return (result.obj_to_primitive(target_version=objver)
                if isinstance(result, nova_object.NovaObject) else result)

    def object_action(self, context, objinst, objmethod, args, kwargs):
        """Perform an action on an object."""
        oldobj = objinst.obj_clone()
        result = self._object_dispatch(objinst, objmethod, context,
                                       args, kwargs)
        updates = dict()
        # NOTE(danms): Diff the object with the one passed to us and
        # generate a list of changes to forward back
        for name, field in objinst.fields.items():
            if not objinst.obj_attr_is_set(name):
                # Avoid demand-loading anything
                continue
            if (not oldobj.obj_attr_is_set(name) or
                    getattr(oldobj, name) != getattr(objinst, name)):
                updates[name] = field.to_primitive(objinst, name,
                                                   getattr(objinst, name))
        # This is safe since a field named this would conflict with the
        # method anyway
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result

    def object_backport(self, context, objinst, target_version):
        return objinst.obj_to_primitive(target_version=target_version)


class ComputeTaskManager(base.Base):
    """Namespace for compute methods.

    This class presents an rpc API for nova-conductor under the 'compute_task'
    namespace.  The methods here are compute operations that are invoked
    by the API service.  These methods see the operation to completion, which
    may involve coordinating activities on multiple compute nodes.
    """

    target = messaging.Target(namespace='compute_task', version='1.11')

    def __init__(self):
        super(ComputeTaskManager, self).__init__()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.image_api = image.API()
        self.scheduler_client = scheduler_client.SchedulerClient()

    @messaging.expected_exceptions(exception.NoValidHost,
                                   exception.ComputeServiceUnavailable,
                                   exception.InvalidHypervisorType,
                                   exception.InvalidCPUInfo,
                                   exception.UnableToMigrateToSelf,
                                   exception.DestinationHypervisorTooOld,
                                   exception.InvalidLocalStorage,
                                   exception.InvalidSharedStorage,
                                   exception.HypervisorUnavailable,
                                   exception.InstanceNotRunning,
                                   exception.MigrationPreCheckError,
                                   exception.LiveMigrationWithOldNovaNotSafe,
                                   exception.UnsupportedPolicyException)
    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
            flavor, block_migration, disk_over_commit, reservations=None,
            clean_shutdown=True):
        if instance and not isinstance(instance, nova_object.NovaObject):
            # NOTE(danms): Until v2 of the RPC API, we need to tolerate
            # old-world instance objects here
            attrs = ['metadata', 'system_metadata', 'info_cache',
                     'security_groups']
            instance = objects.Instance._from_db_object(
                context, objects.Instance(), instance,
                expected_attrs=attrs)
        # NOTE(melwitt): Remove this in version 2.0 of the RPC API
        if flavor and not isinstance(flavor, objects.Flavor):
            # Code downstream may expect extra_specs to be populated since it
            # is receiving an object, so lookup the flavor to ensure this.
            flavor = objects.Flavor.get_by_id(context, flavor['id'])
        if live and not rebuild and not flavor:
            self._live_migrate(context, instance, scheduler_hint,
                               block_migration, disk_over_commit)
        elif not live and not rebuild and flavor:
            instance_uuid = instance['uuid']
            with compute_utils.EventReporter(context, 'cold_migrate',
                                             instance_uuid):
                self._cold_migrate(context, instance, flavor,
                                   scheduler_hint['filter_properties'],
                                   reservations, clean_shutdown)
        else:
            raise NotImplementedError()

    def _cold_migrate(self, context, instance, flavor, filter_properties,
                      reservations, clean_shutdown):
        image_ref = instance.image_ref
        image = compute_utils.get_image_metadata(
            context, self.image_api, image_ref, instance)

        request_spec = scheduler_utils.build_request_spec(
            context, image, [instance], instance_type=flavor)

        quotas = objects.Quotas.from_reservations(context,
                                                  reservations,
                                                  instance=instance)
        try:
            scheduler_utils.setup_instance_group(context, request_spec,
                                                 filter_properties)
            scheduler_utils.populate_retry(filter_properties, instance['uuid'])
            hosts = self.scheduler_client.select_destinations(
                    context, request_spec, filter_properties)
            host_state = hosts[0]
        except exception.NoValidHost as ex:
            vm_state = instance.vm_state
            if not vm_state:
                vm_state = vm_states.ACTIVE
            updates = {'vm_state': vm_state, 'task_state': None}
            self._set_vm_state_and_notify(context, instance.uuid,
                                          'migrate_server',
                                          updates, ex, request_spec)
            quotas.rollback()

            # if the flavor IDs match, it's migrate; otherwise resize
            if flavor['id'] == instance['instance_type_id']:
                msg = _("No valid host found for cold migrate")
            else:
                msg = _("No valid host found for resize")
            raise exception.NoValidHost(reason=msg)
        except exception.UnsupportedPolicyException as ex:
            with excutils.save_and_reraise_exception():
                vm_state = instance.vm_state
                if not vm_state:
                    vm_state = vm_states.ACTIVE
                updates = {'vm_state': vm_state, 'task_state': None}
                self._set_vm_state_and_notify(context, instance.uuid,
                                              'migrate_server',
                                              updates, ex, request_spec)
                quotas.rollback()

        try:
            scheduler_utils.populate_filter_properties(filter_properties,
                                                       host_state)
            # context is not serializable
            filter_properties.pop('context', None)

            (host, node) = (host_state['host'], host_state['nodename'])
            self.compute_rpcapi.prep_resize(
                context, image, instance,
                flavor, host,
                reservations, request_spec=request_spec,
                filter_properties=filter_properties, node=node,
                clean_shutdown=clean_shutdown)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                updates = {'vm_state': instance.vm_state,
                           'task_state': None}
                self._set_vm_state_and_notify(context, instance.uuid,
                                              'migrate_server',
                                              updates, ex, request_spec)
                quotas.rollback()

    def _set_vm_state_and_notify(self, context, instance_uuid, method, updates,
                                 ex, request_spec):
        scheduler_utils.set_vm_state_and_notify(
                context, instance_uuid, 'compute_task', method, updates,
                ex, request_spec, self.db)

    def _live_migrate(self, context, instance, scheduler_hint,
                      block_migration, disk_over_commit):
        destination = scheduler_hint.get("host")

        def _set_vm_state(context, instance, ex, vm_state=None,
                          task_state=None):
            request_spec = {'instance_properties': {
                'uuid': instance['uuid'], },
            }
            scheduler_utils.set_vm_state_and_notify(context,
                instance.uuid,
                'compute_task', 'migrate_server',
                dict(vm_state=vm_state,
                     task_state=task_state,
                     expected_task_state=task_states.MIGRATING,),
                ex, request_spec, self.db)

        try:
            live_migrate.execute(context, instance, destination,
                             block_migration, disk_over_commit)
        except (exception.NoValidHost,
                exception.ComputeServiceUnavailable,
                exception.InvalidHypervisorType,
                exception.InvalidCPUInfo,
                exception.UnableToMigrateToSelf,
                exception.DestinationHypervisorTooOld,
                exception.InvalidLocalStorage,
                exception.InvalidSharedStorage,
                exception.HypervisorUnavailable,
                exception.InstanceNotRunning,
                exception.MigrationPreCheckError,
                exception.LiveMigrationWithOldNovaNotSafe) as ex:
            with excutils.save_and_reraise_exception():
                # TODO(johngarbutt) - eventually need instance actions here
                _set_vm_state(context, instance, ex, instance.vm_state)
        except Exception as ex:
            LOG.error(_LE('Migration of instance %(instance_id)s to host'
                          ' %(dest)s unexpectedly failed.'),
                      {'instance_id': instance['uuid'], 'dest': destination},
                      exc_info=True)
            _set_vm_state(context, instance, ex, vm_states.ERROR,
                          instance['task_state'])
            raise exception.MigrationError(reason=six.text_type(ex))

    def build_instances(self, context, instances, image, filter_properties,
            admin_password, injected_files, requested_networks,
            security_groups, block_device_mapping=None, legacy_bdm=True):
        # TODO(ndipanov): Remove block_device_mapping and legacy_bdm in version
        #                 2.0 of the RPC API.
        request_spec = scheduler_utils.build_request_spec(context, image,
                                                          instances)
        # TODO(danms): Remove this in version 2.0 of the RPC API
        if (requested_networks and
                not isinstance(requested_networks,
                               objects.NetworkRequestList)):
            requested_networks = objects.NetworkRequestList(
                objects=[objects.NetworkRequest.from_tuple(t)
                         for t in requested_networks])
        # TODO(melwitt): Remove this in version 2.0 of the RPC API
        flavor = filter_properties.get('instance_type')
        if flavor and not isinstance(flavor, objects.Flavor):
            # Code downstream may expect extra_specs to be populated since it
            # is receiving an object, so lookup the flavor to ensure this.
            flavor = objects.Flavor.get_by_id(context, flavor['id'])
            filter_properties = dict(filter_properties, instance_type=flavor)

        try:
            scheduler_utils.setup_instance_group(context, request_spec,
                                                 filter_properties)
            # check retry policy. Rather ugly use of instances[0]...
            # but if we've exceeded max retries... then we really only
            # have a single instance.
            scheduler_utils.populate_retry(filter_properties,
                instances[0].uuid)
            hosts = self.scheduler_client.select_destinations(context,
                    request_spec, filter_properties)
        except Exception as exc:
            updates = {'vm_state': vm_states.ERROR, 'task_state': None}
            for instance in instances:
                self._set_vm_state_and_notify(
                    context, instance.uuid, 'build_instances', updates,
                    exc, request_spec)
            return

        for (instance, host) in itertools.izip(instances, hosts):
            try:
                instance.refresh()
            except (exception.InstanceNotFound,
                    exception.InstanceInfoCacheNotFound):
                LOG.debug('Instance deleted during build', instance=instance)
                continue
            local_filter_props = copy.deepcopy(filter_properties)
            scheduler_utils.populate_filter_properties(local_filter_props,
                host)
            # The block_device_mapping passed from the api doesn't contain
            # instance specific information
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

            self.compute_rpcapi.build_and_run_instance(context,
                    instance=instance, host=host['host'], image=image,
                    request_spec=request_spec,
                    filter_properties=local_filter_props,
                    admin_password=admin_password,
                    injected_files=injected_files,
                    requested_networks=requested_networks,
                    security_groups=security_groups,
                    block_device_mapping=bdms, node=host['nodename'],
                    limits=host['limits'])

    def _delete_image(self, context, image_id):
        return self.image_api.delete(context, image_id)

    def _schedule_instances(self, context, image, filter_properties,
            *instances):
        request_spec = scheduler_utils.build_request_spec(context, image,
                instances)
        scheduler_utils.setup_instance_group(context, request_spec,
                                             filter_properties)
        hosts = self.scheduler_client.select_destinations(context,
                request_spec, filter_properties)
        return hosts

    def unshelve_instance(self, context, instance):
        sys_meta = instance.system_metadata

        def safe_image_show(ctx, image_id):
            if image_id:
                return self.image_api.get(ctx, image_id, show_deleted=False)
            else:
                raise exception.ImageNotFound(image_id='')

        if instance.vm_state == vm_states.SHELVED:
            instance.task_state = task_states.POWERING_ON
            instance.save(expected_task_state=task_states.UNSHELVING)
            self.compute_rpcapi.start_instance(context, instance)
            snapshot_id = sys_meta.get('shelved_image_id')
            if snapshot_id:
                self._delete_image(context, snapshot_id)
        elif instance.vm_state == vm_states.SHELVED_OFFLOADED:
            image = None
            image_id = sys_meta.get('shelved_image_id')
            # No need to check for image if image_id is None as
            # "shelved_image_id" key is not set for volume backed
            # instance during the shelve process
            if image_id:
                with compute_utils.EventReporter(
                    context, 'get_image_info', instance.uuid):
                    try:
                        image = safe_image_show(context, image_id)
                    except exception.ImageNotFound:
                        instance.vm_state = vm_states.ERROR
                        instance.save()

                        reason = _('Unshelve attempted but the image %s '
                                   'cannot be found.') % image_id

                        LOG.error(reason, instance=instance)
                        raise exception.UnshelveException(
                            instance_id=instance.uuid, reason=reason)

            try:
                with compute_utils.EventReporter(context, 'schedule_instances',
                                                 instance.uuid):
                    filter_properties = {}
                    hosts = self._schedule_instances(context, image,
                                                     filter_properties,
                                                     instance)
                    host_state = hosts[0]
                    scheduler_utils.populate_filter_properties(
                            filter_properties, host_state)
                    (host, node) = (host_state['host'], host_state['nodename'])
                    self.compute_rpcapi.unshelve_instance(
                            context, instance, host, image=image,
                            filter_properties=filter_properties, node=node)
            except (exception.NoValidHost,
                    exception.UnsupportedPolicyException):
                instance.task_state = None
                instance.save()
                LOG.warning(_LW("No valid host found for unshelve instance"),
                            instance=instance)
                return
        else:
            LOG.error(_LE('Unshelve attempted but vm_state not SHELVED or '
                          'SHELVED_OFFLOADED'), instance=instance)
            instance.vm_state = vm_states.ERROR
            instance.save()
            return

        for key in ['shelved_at', 'shelved_image_id', 'shelved_host']:
            if key in sys_meta:
                del(sys_meta[key])
        instance.system_metadata = sys_meta
        instance.save()

    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata,
                         bdms, recreate, on_shared_storage,
                         preserve_ephemeral=False, host=None):

        with compute_utils.EventReporter(context, 'rebuild_server',
                                          instance.uuid):
            if not host:
                # NOTE(lcostantino): Retrieve scheduler filters for the
                # instance when the feature is available
                filter_properties = {'ignore_hosts': [instance.host]}
                request_spec = scheduler_utils.build_request_spec(context,
                                                                  image_ref,
                                                                  [instance])
                try:
                    scheduler_utils.setup_instance_group(context, request_spec,
                                                         filter_properties)
                    hosts = self.scheduler_client.select_destinations(context,
                                                            request_spec,
                                                            filter_properties)
                    host = hosts.pop(0)['host']
                except exception.NoValidHost as ex:
                    with excutils.save_and_reraise_exception():
                        self._set_vm_state_and_notify(context, instance.uuid,
                                'rebuild_server',
                                {'vm_state': instance.vm_state,
                                 'task_state': None}, ex, request_spec)
                        LOG.warning(_LW("No valid host found for rebuild"),
                                    instance=instance)
                except exception.UnsupportedPolicyException as ex:
                    with excutils.save_and_reraise_exception():
                        self._set_vm_state_and_notify(context, instance.uuid,
                                'rebuild_server',
                                {'vm_state': instance.vm_state,
                                 'task_state': None}, ex, request_spec)
                        LOG.warning(_LW("Server with unsupported policy "
                                        "cannot be rebuilt"),
                                    instance=instance)

            self.compute_rpcapi.rebuild_instance(context,
                    instance=instance,
                    new_pass=new_pass,
                    injected_files=injected_files,
                    image_ref=image_ref,
                    orig_image_ref=orig_image_ref,
                    orig_sys_metadata=orig_sys_metadata,
                    bdms=bdms,
                    recreate=recreate,
                    on_shared_storage=on_shared_storage,
                    preserve_ephemeral=preserve_ephemeral,
                    host=host)

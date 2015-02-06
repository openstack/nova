#    Copyright 2013 IBM Corp.
#    Copyright 2013 Red Hat, Inc.
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

"""Client side of the conductor RPC API."""

from oslo_config import cfg
import oslo_messaging as messaging
from oslo_serialization import jsonutils

from nova.objects import base as objects_base
from nova import rpc

CONF = cfg.CONF

rpcapi_cap_opt = cfg.StrOpt('conductor',
        help='Set a version cap for messages sent to conductor services')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')


class ConductorAPI(object):
    """Client side of the conductor RPC API

    API version history:

    * 1.0 - Initial version.
    * 1.1 - Added migration_update
    * 1.2 - Added instance_get_by_uuid and instance_get_all_by_host
    * 1.3 - Added aggregate_host_add and aggregate_host_delete
    * 1.4 - Added migration_get
    * 1.5 - Added bw_usage_update
    * 1.6 - Added get_backdoor_port()
    * 1.7 - Added aggregate_get_by_host, aggregate_metadata_add,
      and aggregate_metadata_delete
    * 1.8 - Added security_group_get_by_instance and
      security_group_rule_get_by_security_group
    * 1.9 - Added provider_fw_rule_get_all
    * 1.10 - Added agent_build_get_by_triple
    * 1.11 - Added aggregate_get
    * 1.12 - Added block_device_mapping_update_or_create
    * 1.13 - Added block_device_mapping_get_all_by_instance
    * 1.14 - Added block_device_mapping_destroy
    * 1.15 - Added instance_get_all_by_filters and
      instance_get_all_hung_in_rebooting and
      instance_get_active_by_window
      Deprecated instance_get_all_by_host
    * 1.16 - Added instance_destroy
    * 1.17 - Added instance_info_cache_delete
    * 1.18 - Added instance_type_get
    * 1.19 - Added vol_get_usage_by_time and vol_usage_update
    * 1.20 - Added migration_get_unconfirmed_by_dest_compute
    * 1.21 - Added service_get_all_by
    * 1.22 - Added ping
    * 1.23 - Added instance_get_all
             Un-Deprecate instance_get_all_by_host
    * 1.24 - Added instance_get
    * 1.25 - Added action_event_start and action_event_finish
    * 1.26 - Added instance_info_cache_update
    * 1.27 - Added service_create
    * 1.28 - Added binary arg to service_get_all_by
    * 1.29 - Added service_destroy
    * 1.30 - Added migration_create
    * 1.31 - Added migration_get_in_progress_by_host_and_node
    * 1.32 - Added optional node to instance_get_all_by_host
    * 1.33 - Added compute_node_create and compute_node_update
    * 1.34 - Added service_update
    * 1.35 - Added instance_get_active_by_window_joined
    * 1.36 - Added instance_fault_create
    * 1.37 - Added task_log_get, task_log_begin_task, task_log_end_task
    * 1.38 - Added service name to instance_update
    * 1.39 - Added notify_usage_exists
    * 1.40 - Added security_groups_trigger_handler and
      security_groups_trigger_members_refresh
      Remove instance_get_active_by_window
    * 1.41 - Added fixed_ip_get_by_instance, network_get,
      instance_floating_address_get_all, quota_commit,
      quota_rollback
    * 1.42 - Added get_ec2_ids, aggregate_metadata_get_by_host
    * 1.43 - Added compute_stop
    * 1.44 - Added compute_node_delete
    * 1.45 - Added project_id to quota_commit and quota_rollback
    * 1.46 - Added compute_confirm_resize
    * 1.47 - Added columns_to_join to instance_get_all_by_host and
      instance_get_all_by_filters
    * 1.48 - Added compute_unrescue

    ... Grizzly supports message version 1.48.  So, any changes to existing
    methods in 2.x after that point should be done such that they can
    handle the version_cap being set to 1.48.

    * 1.49 - Added columns_to_join to instance_get_by_uuid
    * 1.50 - Added object_action() and object_class_action()
    * 1.51 - Added the 'legacy' argument to
             block_device_mapping_get_all_by_instance
    * 1.52 - Pass instance objects for compute_confirm_resize
    * 1.53 - Added compute_reboot
    * 1.54 - Added 'update_cells' argument to bw_usage_update
    * 1.55 - Pass instance objects for compute_stop
    * 1.56 - Remove compute_confirm_resize and
             migration_get_unconfirmed_by_dest_compute
    * 1.57 - Remove migration_create()
    * 1.58 - Remove migration_get()

    ... Havana supports message version 1.58.  So, any changes to existing
    methods in 1.x after that point should be done such that they can
    handle the version_cap being set to 1.58.

    * 1.59 - Remove instance_info_cache_update()
    * 1.60 - Remove aggregate_metadata_add() and aggregate_metadata_delete()
    * ...  - Remove security_group_get_by_instance() and
             security_group_rule_get_by_security_group()
    * 1.61 - Return deleted instance from instance_destroy()
    * 1.62 - Added object_backport()
    * 1.63 - Changed the format of values['stats'] from a dict to a JSON string
             in compute_node_update()
    * 1.64 - Added use_slave to instance_get_all_filters()
           - Remove instance_type_get()
           - Remove aggregate_get()
           - Remove aggregate_get_by_host()
           - Remove instance_get()
           - Remove migration_update()
           - Remove block_device_mapping_destroy()

    * 2.0  - Drop backwards compatibility
           - Remove quota_rollback() and quota_commit()
           - Remove aggregate_host_add() and aggregate_host_delete()
           - Remove network_migrate_instance_start() and
             network_migrate_instance_finish()

    ... Icehouse supports message version 2.0.  So, any changes to
    existing methods in 2.x after that point should be done such
    that they can handle the version_cap being set to 2.0.

    * Remove instance_destroy()
    * Remove compute_unrescue()
    * Remove instance_get_all_by_filters()
    * Remove instance_get_active_by_window_joined()
    * Remove instance_fault_create()
    * Remove action_event_start() and action_event_finish()
    * Remove instance_get_by_uuid()
    * Remove agent_build_get_by_triple()

    * 2.1  - Make notify_usage_exists() take an instance object

    ... Juno supports message version 2.0.  So, any changes to
    existing methods in 2.x after that point should be done such
    that they can handle the version_cap being set to 2.0.

    """

    VERSION_ALIASES = {
        'grizzly': '1.48',
        'havana': '1.58',
        'icehouse': '2.0',
        'juno': '2.0',
    }

    def __init__(self):
        super(ConductorAPI, self).__init__()
        target = messaging.Target(topic=CONF.conductor.topic, version='2.0')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.conductor,
                                               CONF.upgrade_levels.conductor)
        serializer = objects_base.NovaObjectSerializer()
        self.client = rpc.get_client(target,
                                     version_cap=version_cap,
                                     serializer=serializer)

    def instance_update(self, context, instance_uuid, updates,
                        service=None):
        updates_p = jsonutils.to_primitive(updates)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'instance_update',
                          instance_uuid=instance_uuid,
                          updates=updates_p,
                          service=service)

    def migration_get_in_progress_by_host_and_node(self, context,
                                                   host, node):
        cctxt = self.client.prepare()
        return cctxt.call(context,
                          'migration_get_in_progress_by_host_and_node',
                          host=host, node=node)

    def aggregate_metadata_get_by_host(self, context, host, key):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'aggregate_metadata_get_by_host',
                          host=host,
                          key=key)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in=None, bw_out=None,
                        last_ctr_in=None, last_ctr_out=None,
                        last_refreshed=None, update_cells=True):
        msg_kwargs = dict(uuid=uuid, mac=mac, start_period=start_period,
                          bw_in=bw_in, bw_out=bw_out, last_ctr_in=last_ctr_in,
                          last_ctr_out=last_ctr_out,
                          last_refreshed=last_refreshed,
                          update_cells=update_cells)

        cctxt = self.client.prepare()
        return cctxt.call(context, 'bw_usage_update', **msg_kwargs)

    def provider_fw_rule_get_all(self, context):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'provider_fw_rule_get_all')

    def block_device_mapping_update_or_create(self, context, values,
                                              create=None):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'block_device_mapping_update_or_create',
                          values=values, create=create)

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy=True):
        instance_p = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'block_device_mapping_get_all_by_instance',
                          instance=instance_p, legacy=legacy)

    def vol_get_usage_by_time(self, context, start_time):
        start_time_p = jsonutils.to_primitive(start_time)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'vol_get_usage_by_time',
                          start_time=start_time_p)

    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed=None,
                         update_totals=False):
        instance_p = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'vol_usage_update',
                          vol_id=vol_id, rd_req=rd_req,
                          rd_bytes=rd_bytes, wr_req=wr_req,
                          wr_bytes=wr_bytes,
                          instance=instance_p, last_refreshed=last_refreshed,
                          update_totals=update_totals)

    def service_get_all_by(self, context, topic=None, host=None, binary=None):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'service_get_all_by',
                          topic=topic, host=host, binary=binary)

    def instance_get_all_by_host(self, context, host, node=None,
                                 columns_to_join=None):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'instance_get_all_by_host',
                          host=host, node=node,
                          columns_to_join=columns_to_join)

    def service_create(self, context, values):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'service_create', values=values)

    def service_destroy(self, context, service_id):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'service_destroy', service_id=service_id)

    def compute_node_create(self, context, values):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'compute_node_create', values=values)

    def compute_node_update(self, context, node, values):
        node_p = jsonutils.to_primitive(node)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'compute_node_update',
                          node=node_p, values=values)

    def compute_node_delete(self, context, node):
        node_p = jsonutils.to_primitive(node)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'compute_node_delete', node=node_p)

    def service_update(self, context, service, values):
        service_p = jsonutils.to_primitive(service)

        # (NOTE:jichenjc)If we're calling this periodically, it makes no
        # sense for the RPC timeout to be more than the service
        # report interval. Select 5 here is only find a reaonable long
        # interval as threshold.
        timeout = CONF.report_interval
        if timeout and timeout > 5:
            timeout -= 1

        if timeout:
            cctxt = self.client.prepare(timeout=timeout)
        else:
            cctxt = self.client.prepare()

        return cctxt.call(context, 'service_update',
                          service=service_p, values=values)

    def task_log_get(self, context, task_name, begin, end, host, state=None):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'task_log_get',
                          task_name=task_name, begin=begin, end=end,
                          host=host, state=state)

    def task_log_begin_task(self, context, task_name, begin, end, host,
                            task_items=None, message=None):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'task_log_begin_task',
                          task_name=task_name,
                          begin=begin, end=end, host=host,
                          task_items=task_items, message=message)

    def task_log_end_task(self, context, task_name, begin, end, host, errors,
                          message=None):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'task_log_end_task',
                          task_name=task_name, begin=begin, end=end,
                          host=host, errors=errors, message=message)

    def notify_usage_exists(self, context, instance, current_period=False,
                            ignore_missing_network_data=True,
                            system_metadata=None, extra_usage_info=None):
        if self.client.can_send_version('2.1'):
            version = '2.1'
        else:
            version = '2.0'
            instance = jsonutils.to_primitive(instance)
        system_metadata_p = jsonutils.to_primitive(system_metadata)
        extra_usage_info_p = jsonutils.to_primitive(extra_usage_info)
        cctxt = self.client.prepare(version=version)
        return cctxt.call(
            context, 'notify_usage_exists',
            instance=instance,
            current_period=current_period,
            ignore_missing_network_data=ignore_missing_network_data,
            system_metadata=system_metadata_p,
            extra_usage_info=extra_usage_info_p)

    def security_groups_trigger_handler(self, context, event, args):
        args_p = jsonutils.to_primitive(args)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'security_groups_trigger_handler',
                          event=event, args=args_p)

    def security_groups_trigger_members_refresh(self, context, group_ids):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'security_groups_trigger_members_refresh',
                          group_ids=group_ids)

    def get_ec2_ids(self, context, instance):
        instance_p = jsonutils.to_primitive(instance)
        cctxt = self.client.prepare()
        return cctxt.call(context, 'get_ec2_ids',
                          instance=instance_p)

    def object_class_action(self, context, objname, objmethod, objver,
                            args, kwargs):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'object_class_action',
                          objname=objname, objmethod=objmethod,
                          objver=objver, args=args, kwargs=kwargs)

    def object_action(self, context, objinst, objmethod, args, kwargs):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'object_action', objinst=objinst,
                          objmethod=objmethod, args=args, kwargs=kwargs)

    def object_backport(self, context, objinst, target_version):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'object_backport', objinst=objinst,
                          target_version=target_version)


class ComputeTaskAPI(object):
    """Client side of the conductor 'compute' namespaced RPC API

    API version history:

    1.0 - Initial version (empty).
    1.1 - Added unified migrate_server call.
    1.2 - Added build_instances
    1.3 - Added unshelve_instance
    1.4 - Added reservations to migrate_server.
    1.5 - Added the leagacy_bdm parameter to build_instances
    1.6 - Made migrate_server use instance objects
    1.7 - Do not send block_device_mapping and legacy_bdm to build_instances
    1.8 - Add rebuild_instance
    1.9 - Converted requested_networks to NetworkRequestList object
    1.10 - Made migrate_server() and build_instances() send flavor objects
    1.11 - Added clean_shutdown to migrate_server()

    """

    def __init__(self):
        super(ComputeTaskAPI, self).__init__()
        target = messaging.Target(topic=CONF.conductor.topic,
                                  namespace='compute_task',
                                  version='1.0')
        serializer = objects_base.NovaObjectSerializer()
        self.client = rpc.get_client(target, serializer=serializer)

    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
                  flavor, block_migration, disk_over_commit,
                  reservations=None, clean_shutdown=True):
        kw = {'instance': instance, 'scheduler_hint': scheduler_hint,
              'live': live, 'rebuild': rebuild, 'flavor': flavor,
              'block_migration': block_migration,
              'disk_over_commit': disk_over_commit,
              'reservations': reservations,
              'clean_shutdown': clean_shutdown}
        version = '1.11'
        if not self.client.can_send_version(version):
            del kw['clean_shutdown']
            version = '1.10'
        if not self.client.can_send_version(version):
            kw['flavor'] = objects_base.obj_to_primitive(flavor)
            version = '1.6'
        if not self.client.can_send_version(version):
            kw['instance'] = jsonutils.to_primitive(
                    objects_base.obj_to_primitive(instance))
            version = '1.4'
        cctxt = self.client.prepare(version=version)
        return cctxt.call(context, 'migrate_server', **kw)

    def build_instances(self, context, instances, image, filter_properties,
            admin_password, injected_files, requested_networks,
            security_groups, block_device_mapping, legacy_bdm=True):
        image_p = jsonutils.to_primitive(image)
        version = '1.10'
        if not self.client.can_send_version(version):
            version = '1.9'
            if 'instance_type' in filter_properties:
                flavor = filter_properties['instance_type']
                flavor_p = objects_base.obj_to_primitive(flavor)
                filter_properties = dict(filter_properties,
                                         instance_type=flavor_p)
        kw = {'instances': instances, 'image': image_p,
               'filter_properties': filter_properties,
               'admin_password': admin_password,
               'injected_files': injected_files,
               'requested_networks': requested_networks,
               'security_groups': security_groups}
        if not self.client.can_send_version(version):
            version = '1.8'
            kw['requested_networks'] = kw['requested_networks'].as_tuples()
        if not self.client.can_send_version('1.7'):
            version = '1.5'
            kw.update({'block_device_mapping': block_device_mapping,
                       'legacy_bdm': legacy_bdm})

        cctxt = self.client.prepare(version=version)
        cctxt.cast(context, 'build_instances', **kw)

    def unshelve_instance(self, context, instance):
        cctxt = self.client.prepare(version='1.3')
        cctxt.cast(context, 'unshelve_instance', instance=instance)

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
            image_ref, orig_image_ref, orig_sys_metadata, bdms,
            recreate=False, on_shared_storage=False, host=None,
            preserve_ephemeral=False, kwargs=None):
        cctxt = self.client.prepare(version='1.8')
        cctxt.cast(ctxt, 'rebuild_instance',
                   instance=instance, new_pass=new_pass,
                   injected_files=injected_files, image_ref=image_ref,
                   orig_image_ref=orig_image_ref,
                   orig_sys_metadata=orig_sys_metadata, bdms=bdms,
                   recreate=recreate, on_shared_storage=on_shared_storage,
                   preserve_ephemeral=preserve_ephemeral,
                   host=host)

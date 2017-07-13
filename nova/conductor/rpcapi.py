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

import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_versionedobjects import base as ovo_base

import nova.conf
from nova.objects import base as objects_base
from nova import profiler
from nova import rpc

CONF = nova.conf.CONF


@profiler.trace_cls("rpc")
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
           - Remove vol_get_usage_by_time

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

    ... Juno supports message version 2.0.  So, any changes to
    existing methods in 2.x after that point should be done such
    that they can handle the version_cap being set to 2.0.

    * 2.1  - Make notify_usage_exists() take an instance object
    * Remove bw_usage_update()
    * Remove notify_usage_exists()

    ... Kilo supports message version 2.1.  So, any changes to
    existing methods in 2.x after that point should be done such
    that they can handle the version_cap being set to 2.1.

    * Remove get_ec2_ids()
    * Remove service_get_all_by()
    * Remove service_create()
    * Remove service_destroy()
    * Remove service_update()
    * Remove migration_get_in_progress_by_host_and_node()
    * Remove aggregate_metadata_get_by_host()
    * Remove block_device_mapping_update_or_create()
    * Remove block_device_mapping_get_all_by_instance()
    * Remove instance_get_all_by_host()
    * Remove compute_node_update()
    * Remove compute_node_delete()
    * Remove security_groups_trigger_handler()
    * Remove task_log_get()
    * Remove task_log_begin_task()
    * Remove task_log_end_task()
    * Remove security_groups_trigger_members_refresh()
    * Remove vol_usage_update()
    * Remove instance_update()

    * 2.2 - Add object_backport_versions()
    * 2.3 - Add object_class_action_versions()
    * Remove compute_node_create()
    * Remove object_backport()

    * 3.0  - Drop backwards compatibility

    ... Liberty, Mitaka, Newton, and Ocata support message version 3.0.  So,
    any changes to existing methods in 3.x after that point should be done such
    that they can handle the version_cap being set to 3.0.

    * Remove provider_fw_rule_get_all()
    """

    VERSION_ALIASES = {
        'grizzly': '1.48',
        'havana': '1.58',
        'icehouse': '2.0',
        'juno': '2.0',
        'kilo': '2.1',
        'liberty': '3.0',
        'mitaka': '3.0',
        'newton': '3.0',
        'ocata': '3.0',
    }

    def __init__(self):
        super(ConductorAPI, self).__init__()
        target = messaging.Target(topic=CONF.conductor.topic, version='3.0')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.conductor,
                                               CONF.upgrade_levels.conductor)
        serializer = objects_base.NovaObjectSerializer()
        self.client = rpc.get_client(target,
                                     version_cap=version_cap,
                                     serializer=serializer)

    # TODO(hanlind): This method can be removed once oslo.versionedobjects
    # has been converted to use version_manifests in remotable_classmethod
    # operations, which will use the new class action handler.
    def object_class_action(self, context, objname, objmethod, objver,
                            args, kwargs):
        versions = ovo_base.obj_tree_get_versions(objname)
        return self.object_class_action_versions(context,
                                                 objname,
                                                 objmethod,
                                                 versions,
                                                 args, kwargs)

    def object_class_action_versions(self, context, objname, objmethod,
                                     object_versions, args, kwargs):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'object_class_action_versions',
                          objname=objname, objmethod=objmethod,
                          object_versions=object_versions,
                          args=args, kwargs=kwargs)

    def object_action(self, context, objinst, objmethod, args, kwargs):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'object_action', objinst=objinst,
                          objmethod=objmethod, args=args, kwargs=kwargs)

    def object_backport_versions(self, context, objinst, object_versions):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'object_backport_versions', objinst=objinst,
                          object_versions=object_versions)


@profiler.trace_cls("rpc")
class ComputeTaskAPI(object):
    """Client side of the conductor 'compute' namespaced RPC API

    API version history:

    1.0 - Initial version (empty).
    1.1 - Added unified migrate_server call.
    1.2 - Added build_instances
    1.3 - Added unshelve_instance
    1.4 - Added reservations to migrate_server.
    1.5 - Added the legacy_bdm parameter to build_instances
    1.6 - Made migrate_server use instance objects
    1.7 - Do not send block_device_mapping and legacy_bdm to build_instances
    1.8 - Add rebuild_instance
    1.9 - Converted requested_networks to NetworkRequestList object
    1.10 - Made migrate_server() and build_instances() send flavor objects
    1.11 - Added clean_shutdown to migrate_server()
    1.12 - Added request_spec to rebuild_instance()
    1.13 - Added request_spec to migrate_server()
    1.14 - Added request_spec to unshelve_instance()
    1.15 - Added live_migrate_instance
    1.16 - Added schedule_and_build_instances
    1.17 - Added tags to schedule_and_build_instances()
    """

    def __init__(self):
        super(ComputeTaskAPI, self).__init__()
        target = messaging.Target(topic=CONF.conductor.topic,
                                  namespace='compute_task',
                                  version='1.0')
        serializer = objects_base.NovaObjectSerializer()
        self.client = rpc.get_client(target, serializer=serializer)

    def live_migrate_instance(self, context, instance, scheduler_hint,
                              block_migration, disk_over_commit, request_spec):
        kw = {'instance': instance, 'scheduler_hint': scheduler_hint,
              'block_migration': block_migration,
              'disk_over_commit': disk_over_commit,
              'request_spec': request_spec,
              }
        version = '1.15'
        cctxt = self.client.prepare(version=version)
        cctxt.cast(context, 'live_migrate_instance', **kw)

    # TODO(melwitt): Remove the reservations parameter in version 2.0 of the
    # RPC API.
    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
                  flavor, block_migration, disk_over_commit,
                  reservations=None, clean_shutdown=True, request_spec=None):
        kw = {'instance': instance, 'scheduler_hint': scheduler_hint,
              'live': live, 'rebuild': rebuild, 'flavor': flavor,
              'block_migration': block_migration,
              'disk_over_commit': disk_over_commit,
              'reservations': reservations,
              'clean_shutdown': clean_shutdown,
              'request_spec': request_spec,
              }
        version = '1.13'
        if not self.client.can_send_version(version):
            del kw['request_spec']
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
            bdm_p = objects_base.obj_to_primitive(block_device_mapping)
            kw.update({'block_device_mapping': bdm_p,
                       'legacy_bdm': legacy_bdm})

        cctxt = self.client.prepare(version=version)
        cctxt.cast(context, 'build_instances', **kw)

    def schedule_and_build_instances(self, context, build_requests,
                                     request_specs,
                                     image, admin_password, injected_files,
                                     requested_networks,
                                     block_device_mapping,
                                     tags=None):
        version = '1.17'
        kw = {'build_requests': build_requests,
              'request_specs': request_specs,
              'image': jsonutils.to_primitive(image),
              'admin_password': admin_password,
              'injected_files': injected_files,
              'requested_networks': requested_networks,
              'block_device_mapping': block_device_mapping,
              'tags': tags}

        if not self.client.can_send_version(version):
            version = '1.16'
            del kw['tags']

        cctxt = self.client.prepare(version=version)
        cctxt.cast(context, 'schedule_and_build_instances', **kw)

    def unshelve_instance(self, context, instance, request_spec=None):
        version = '1.14'
        kw = {'instance': instance,
              'request_spec': request_spec
              }
        if not self.client.can_send_version(version):
            version = '1.3'
            del kw['request_spec']
        cctxt = self.client.prepare(version=version)
        cctxt.cast(context, 'unshelve_instance', **kw)

    def rebuild_instance(self, ctxt, instance, new_pass, injected_files,
            image_ref, orig_image_ref, orig_sys_metadata, bdms,
            recreate=False, on_shared_storage=False, host=None,
            preserve_ephemeral=False, request_spec=None, kwargs=None):
        version = '1.12'
        kw = {'instance': instance,
              'new_pass': new_pass,
              'injected_files': injected_files,
              'image_ref': image_ref,
              'orig_image_ref': orig_image_ref,
              'orig_sys_metadata': orig_sys_metadata,
              'bdms': bdms,
              'recreate': recreate,
              'on_shared_storage': on_shared_storage,
              'preserve_ephemeral': preserve_ephemeral,
              'host': host,
              'request_spec': request_spec,
              }
        if not self.client.can_send_version(version):
            version = '1.8'
            del kw['request_spec']
        cctxt = self.client.prepare(version=version)
        cctxt.cast(ctxt, 'rebuild_instance', **kw)

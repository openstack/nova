# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import functools

import nova.api.openstack
from nova.api.openstack.compute import admin_actions
from nova.api.openstack.compute import admin_password
from nova.api.openstack.compute import agents
from nova.api.openstack.compute import aggregates
from nova.api.openstack.compute import assisted_volume_snapshots
from nova.api.openstack.compute import attach_interfaces
from nova.api.openstack.compute import availability_zone
from nova.api.openstack.compute import baremetal_nodes
from nova.api.openstack.compute import cells
from nova.api.openstack.compute import certificates
from nova.api.openstack.compute import cloudpipe
from nova.api.openstack.compute import config_drive
from nova.api.openstack.compute import console_auth_tokens
from nova.api.openstack.compute import console_output
from nova.api.openstack.compute import consoles
from nova.api.openstack.compute import create_backup
from nova.api.openstack.compute import deferred_delete
from nova.api.openstack.compute import evacuate
from nova.api.openstack.compute import extended_availability_zone
from nova.api.openstack.compute import extended_server_attributes
from nova.api.openstack.compute import extended_status
from nova.api.openstack.compute import extended_volumes
from nova.api.openstack.compute import extension_info
from nova.api.openstack.compute import fixed_ips
from nova.api.openstack.compute import flavor_access
from nova.api.openstack.compute import flavor_manage
from nova.api.openstack.compute import flavors
from nova.api.openstack.compute import flavors_extraspecs
from nova.api.openstack.compute import floating_ip_dns
from nova.api.openstack.compute import floating_ip_pools
from nova.api.openstack.compute import floating_ips
from nova.api.openstack.compute import floating_ips_bulk
from nova.api.openstack.compute import fping
from nova.api.openstack.compute import hide_server_addresses
from nova.api.openstack.compute import hosts
from nova.api.openstack.compute import hypervisors
from nova.api.openstack.compute import image_metadata
from nova.api.openstack.compute import image_size
from nova.api.openstack.compute import images
from nova.api.openstack.compute import instance_actions
from nova.api.openstack.compute import instance_usage_audit_log
from nova.api.openstack.compute import ips
from nova.api.openstack.compute import keypairs
from nova.api.openstack.compute import limits
from nova.api.openstack.compute import lock_server
from nova.api.openstack.compute import migrate_server
from nova.api.openstack.compute import migrations
from nova.api.openstack.compute import multinic
from nova.api.openstack.compute import networks
from nova.api.openstack.compute import networks_associate
from nova.api.openstack.compute import pause_server
from nova.api.openstack.compute import quota_classes
from nova.api.openstack.compute import quota_sets
from nova.api.openstack.compute import remote_consoles
from nova.api.openstack.compute import rescue
from nova.api.openstack.compute import security_group_default_rules
from nova.api.openstack.compute import security_groups
from nova.api.openstack.compute import server_diagnostics
from nova.api.openstack.compute import server_external_events
from nova.api.openstack.compute import server_groups
from nova.api.openstack.compute import server_metadata
from nova.api.openstack.compute import server_migrations
from nova.api.openstack.compute import server_password
from nova.api.openstack.compute import server_tags
from nova.api.openstack.compute import server_usage
from nova.api.openstack.compute import servers
from nova.api.openstack.compute import services
from nova.api.openstack.compute import shelve
from nova.api.openstack.compute import simple_tenant_usage
from nova.api.openstack.compute import suspend_server
from nova.api.openstack.compute import tenant_networks
from nova.api.openstack.compute import used_limits
from nova.api.openstack.compute import versionsV21
from nova.api.openstack.compute import virtual_interfaces
from nova.api.openstack.compute import volumes
from nova.api.openstack import wsgi
import nova.conf
from nova import wsgi as base_wsgi


CONF = nova.conf.CONF


def _create_controller(main_controller, controller_list,
                      action_controller_list):
    """This is a helper method to create controller with a
    list of extended controller. This is for backward compatible
    with old extension interface. Finally, the controller for the
    same resource will be merged into single one controller.
    """

    controller = wsgi.Resource(main_controller())
    for ctl in controller_list:
        controller.register_extensions(ctl())
    for ctl in action_controller_list:
        controller.register_actions(ctl())
    return controller


agents_controller = functools.partial(
    _create_controller, agents.AgentController, [], [])


aggregates_controller = functools.partial(
    _create_controller, aggregates.AggregateController, [], [])


assisted_volume_snapshots_controller = functools.partial(
    _create_controller,
    assisted_volume_snapshots.AssistedVolumeSnapshotsController, [], [])


availability_zone_controller = functools.partial(
    _create_controller, availability_zone.AvailabilityZoneController, [], [])


baremetal_nodes_controller = functools.partial(
    _create_controller, baremetal_nodes.BareMetalNodeController, [], [])


cells_controller = functools.partial(
    _create_controller, cells.CellsController, [], [])


certificates_controller = functools.partial(
    _create_controller, certificates.CertificatesController, [], [])


cloudpipe_controller = functools.partial(
    _create_controller, cloudpipe.CloudpipeController, [], [])


extensions_controller = functools.partial(
    _create_controller, extension_info.ExtensionInfoController, [], [])


fixed_ips_controller = functools.partial(_create_controller,
    fixed_ips.FixedIPController, [], [])


flavor_controller = functools.partial(_create_controller,
    flavors.FlavorsController,
    [],
    [
        flavor_manage.FlavorManageController,
        flavor_access.FlavorActionController
    ]
)


flavor_access_controller = functools.partial(_create_controller,
    flavor_access.FlavorAccessController, [], [])


flavor_extraspec_controller = functools.partial(_create_controller,
    flavors_extraspecs.FlavorExtraSpecsController, [], [])


floating_ip_dns_controller = functools.partial(_create_controller,
    floating_ip_dns.FloatingIPDNSDomainController, [], [])


floating_ip_dnsentry_controller = functools.partial(_create_controller,
    floating_ip_dns.FloatingIPDNSEntryController, [], [])


floating_ip_pools_controller = functools.partial(_create_controller,
    floating_ip_pools.FloatingIPPoolsController, [], [])


floating_ips_controller = functools.partial(_create_controller,
    floating_ips.FloatingIPController, [], [])


floating_ips_bulk_controller = functools.partial(_create_controller,
    floating_ips_bulk.FloatingIPBulkController, [], [])


fping_controller = functools.partial(_create_controller,
    fping.FpingController, [], [])


hosts_controller = functools.partial(
    _create_controller, hosts.HostController, [], [])


hypervisors_controller = functools.partial(
    _create_controller, hypervisors.HypervisorsController, [], [])


images_controller = functools.partial(
    _create_controller, images.ImagesController,
    [image_size.ImageSizeController], [])


image_metadata_controller = functools.partial(
    _create_controller, image_metadata.ImageMetadataController,
    [], [])


instance_actions_controller = functools.partial(_create_controller,
    instance_actions.InstanceActionsController, [], [])


instance_usage_audit_log_controller = functools.partial(_create_controller,
    instance_usage_audit_log.InstanceUsageAuditLogController, [], [])


ips_controller = functools.partial(_create_controller,
    ips.IPsController, [], [])


keypairs_controller = functools.partial(
    _create_controller, keypairs.KeypairController, [], [])


limits_controller = functools.partial(
    _create_controller, limits.LimitsController,
    [
        used_limits.UsedLimitsController,
    ],
    [])


migrations_controller = functools.partial(_create_controller,
    migrations.MigrationsController, [], [])


networks_controller = functools.partial(_create_controller,
    networks.NetworkController, [],
    [networks_associate.NetworkAssociateActionController])


quota_classes_controller = functools.partial(_create_controller,
    quota_classes.QuotaClassSetsController, [], [])


quota_set_controller = functools.partial(_create_controller,
    quota_sets.QuotaSetsController, [], [])


security_group_controller = functools.partial(_create_controller,
    security_groups.SecurityGroupController, [], [])


security_group_default_rules_controller = functools.partial(_create_controller,
    security_group_default_rules.SecurityGroupDefaultRulesController, [], [])


security_group_rules_controller = functools.partial(_create_controller,
    security_groups.SecurityGroupRulesController, [], [])


server_controller = functools.partial(_create_controller,
    servers.ServersController,
    [
        config_drive.ConfigDriveController,
        extended_availability_zone.ExtendedAZController,
        extended_server_attributes.ExtendedServerAttributesController,
        extended_status.ExtendedStatusController,
        extended_volumes.ExtendedVolumesController,
        hide_server_addresses.Controller,
        keypairs.Controller,
        security_groups.SecurityGroupsOutputController,
        server_usage.ServerUsageController,
    ],
    [
        admin_actions.AdminActionsController,
        admin_password.AdminPasswordController,
        console_output.ConsoleOutputController,
        create_backup.CreateBackupController,
        deferred_delete.DeferredDeleteController,
        evacuate.EvacuateController,
        floating_ips.FloatingIPActionController,
        lock_server.LockServerController,
        migrate_server.MigrateServerController,
        multinic.MultinicController,
        pause_server.PauseServerController,
        remote_consoles.RemoteConsolesController,
        rescue.RescueController,
        security_groups.SecurityGroupActionController,
        shelve.ShelveController,
        suspend_server.SuspendServerController
    ]
)


console_auth_tokens_controller = functools.partial(_create_controller,
    console_auth_tokens.ConsoleAuthTokensController, [], [])


consoles_controller = functools.partial(_create_controller,
    consoles.ConsolesController, [], [])


server_diagnostics_controller = functools.partial(_create_controller,
    server_diagnostics.ServerDiagnosticsController, [], [])


server_external_events_controller = functools.partial(_create_controller,
    server_external_events.ServerExternalEventsController, [], [])


server_groups_controller = functools.partial(_create_controller,
    server_groups.ServerGroupController, [], [])


server_metadata_controller = functools.partial(_create_controller,
    server_metadata.ServerMetadataController, [], [])


server_migrations_controller = functools.partial(_create_controller,
    server_migrations.ServerMigrationsController, [], [])


server_os_interface_controller = functools.partial(_create_controller,
    attach_interfaces.InterfaceAttachmentController, [], [])


server_password_controller = functools.partial(_create_controller,
    server_password.ServerPasswordController, [], [])


server_remote_consoles_controller = functools.partial(_create_controller,
    remote_consoles.RemoteConsolesController, [], [])


server_security_groups_controller = functools.partial(_create_controller,
    security_groups.ServerSecurityGroupController, [], [])


server_tags_controller = functools.partial(_create_controller,
    server_tags.ServerTagsController, [], [])


server_volume_attachments_controller = functools.partial(_create_controller,
    volumes.VolumeAttachmentController, [], [])


services_controller = functools.partial(_create_controller,
    services.ServiceController, [], [])


simple_tenant_usage_controller = functools.partial(_create_controller,
    simple_tenant_usage.SimpleTenantUsageController, [], [])


snapshots_controller = functools.partial(_create_controller,
    volumes.SnapshotController, [], [])


tenant_networks_controller = functools.partial(_create_controller,
    tenant_networks.TenantNetworkController, [], [])


version_controller = functools.partial(_create_controller,
    versionsV21.VersionsController, [], [])


virtual_interfaces_controller = functools.partial(_create_controller,
    virtual_interfaces.ServerVirtualInterfaceController, [], [])


volumes_controller = functools.partial(_create_controller,
    volumes.VolumeController, [], [])


# NOTE(alex_xu): This is structure of this route list as below:
# (
#     ('Route path': {
#         'HTTP method: [
#             'Controller',
#             'The method of controller is used to handle this route'
#         ],
#         ...
#     }),
#     ...
# )
#
# Also note that this is ordered tuple. For example, the '/servers/detail'
# should be in the front of '/servers/{id}', otherwise the request to
# '/servers/detail' always matches to '/servers/{id}' as the id is 'detail'.
ROUTE_LIST = (
    # NOTE: This is a redirection from '' to '/'. The request to the '/v2.1'
    # or '/2.0' without the ending '/' will get a response with status code
    # '302' returned.
    ('', '/'),
    ('/', {
        'GET': [version_controller, 'show']
    }),
    ('/versions/{id}', {
        'GET': [version_controller, 'show']
    }),
    ('/extensions', {
        'GET': [extensions_controller, 'index'],
    }),
    ('/extensions/{id}', {
        'GET': [extensions_controller, 'show'],
    }),
    ('/flavors', {
        'GET': [flavor_controller, 'index'],
        'POST': [flavor_controller, 'create']
    }),
    ('/flavors/detail', {
        'GET': [flavor_controller, 'detail']
    }),
    ('/flavors/{id}', {
        'GET': [flavor_controller, 'show'],
        'PUT': [flavor_controller, 'update'],
        'DELETE': [flavor_controller, 'delete']
    }),
    ('/flavors/{id}/action', {
        'POST': [flavor_controller, 'action']
    }),
    ('/flavors/{flavor_id}/os-extra_specs', {
        'GET': [flavor_extraspec_controller, 'index'],
        'POST': [flavor_extraspec_controller, 'create']
    }),
    ('/flavors/{flavor_id}/os-extra_specs/{id}', {
        'GET': [flavor_extraspec_controller, 'show'],
        'PUT': [flavor_extraspec_controller, 'update'],
        'DELETE': [flavor_extraspec_controller, 'delete']
    }),
    ('/flavors/{flavor_id}/os-flavor-access', {
        'GET': [flavor_access_controller, 'index']
    }),
    ('/images', {
        'GET': [images_controller, 'index']
    }),
    ('/images/detail', {
        'GET': [images_controller, 'detail'],
    }),
    ('/images/{id}', {
        'GET': [images_controller, 'show'],
        'DELETE': [images_controller, 'delete']
    }),
    ('/images/{image_id}/metadata', {
        'GET': [image_metadata_controller, 'index'],
        'POST': [image_metadata_controller, 'create'],
        'PUT': [image_metadata_controller, 'update_all']
    }),
    ('/images/{image_id}/metadata/{id}', {
        'GET': [image_metadata_controller, 'show'],
        'PUT': [image_metadata_controller, 'update'],
        'DELETE': [image_metadata_controller, 'delete']
    }),
    ('/limits', {
        'GET': [limits_controller, 'index']
    }),
    ('/os-agents', {
        'GET': [agents_controller, 'index'],
        'POST': [agents_controller, 'create']
    }),
    ('/os-agents/{id}', {
        'PUT': [agents_controller, 'update'],
        'DELETE': [agents_controller, 'delete']
    }),
    ('/os-aggregates', {
        'GET': [aggregates_controller, 'index'],
        'POST': [aggregates_controller, 'create']
    }),
    ('/os-aggregates/{id}', {
        'GET': [aggregates_controller, 'show'],
        'PUT': [aggregates_controller, 'update'],
        'DELETE': [aggregates_controller, 'delete']
    }),
    ('/os-aggregates/{id}/action', {
        'POST': [aggregates_controller, 'action'],
    }),
    ('/os-assisted-volume-snapshots', {
        'POST': [assisted_volume_snapshots_controller, 'create']
    }),
    ('/os-assisted-volume-snapshots/{id}', {
        'DELETE': [assisted_volume_snapshots_controller, 'delete']
    }),
    ('/os-availability-zone', {
        'GET': [availability_zone_controller, 'index']
    }),
    ('/os-availability-zone/detail', {
        'GET': [availability_zone_controller, 'detail'],
    }),
    ('/os-baremetal-nodes', {
        'GET': [baremetal_nodes_controller, 'index'],
        'POST': [baremetal_nodes_controller, 'create']
    }),
    ('/os-baremetal-nodes/{id}', {
        'GET': [baremetal_nodes_controller, 'show'],
        'DELETE': [baremetal_nodes_controller, 'delete']
    }),
    ('/os-baremetal-nodes/{id}/action', {
        'POST': [baremetal_nodes_controller, 'action']
    }),
    ('/os-cells', {
        'POST': [cells_controller, 'create'],
        'GET': [cells_controller, 'index'],
    }),
    ('/os-cells/capacities', {
        'GET': [cells_controller, 'capacities']
    }),
    ('/os-cells/detail', {
        'GET': [cells_controller, 'detail']
    }),
    ('/os-cells/info', {
        'GET': [cells_controller, 'info']
    }),
    ('/os-cells/sync_instances', {
        'POST': [cells_controller, 'sync_instances']
    }),
    ('/os-cells/{id}', {
        'GET': [cells_controller, 'show'],
        'PUT': [cells_controller, 'update'],
        'DELETE': [cells_controller, 'delete']
    }),
    ('/os-cells/{id}/capacities', {
        'GET': [cells_controller, 'capacities']
    }),
    ('/os-certificates', {
        'POST': [certificates_controller, 'create']
    }),
    ('/os-certificates/{id}', {
        'GET': [certificates_controller, 'show']
    }),
    ('/os-cloudpipe', {
        'GET': [cloudpipe_controller, 'index'],
        'POST': [cloudpipe_controller, 'create']
    }),
    ('/os-cloudpipe/{id}', {
        'PUT': [cloudpipe_controller, 'update']
    }),
    ('/os-console-auth-tokens/{id}', {
        'GET': [console_auth_tokens_controller, 'show']
    }),
    ('/os-fixed-ips/{id}', {
        'GET': [fixed_ips_controller, 'show']
    }),
    ('/os-fixed-ips/{id}/action', {
        'POST': [fixed_ips_controller, 'action'],
    }),
    ('/os-floating-ip-dns', {
        'GET': [floating_ip_dns_controller, 'index']
    }),
    ('/os-floating-ip-dns/{id}', {
        'PUT': [floating_ip_dns_controller, 'update'],
        'DELETE': [floating_ip_dns_controller, 'delete']
    }),
    ('/os-floating-ip-dns/{domain_id}/entries/{id}', {
        'GET': [floating_ip_dnsentry_controller, 'show'],
        'PUT': [floating_ip_dnsentry_controller, 'update'],
        'DELETE': [floating_ip_dnsentry_controller, 'delete']
    }),
    ('/os-floating-ip-pools', {
        'GET': [floating_ip_pools_controller, 'index'],
    }),
    ('/os-floating-ips', {
        'GET': [floating_ips_controller, 'index'],
        'POST': [floating_ips_controller, 'create']
    }),
    ('/os-floating-ips/{id}', {
        'GET': [floating_ips_controller, 'show'],
        'DELETE': [floating_ips_controller, 'delete']
    }),
    ('/os-floating-ips-bulk', {
        'GET': [floating_ips_bulk_controller, 'index'],
        'POST': [floating_ips_bulk_controller, 'create']
    }),
    ('/os-floating-ips-bulk/{id}', {
        'GET': [floating_ips_bulk_controller, 'show'],
        'PUT': [floating_ips_bulk_controller, 'update']
    }),
    ('/os-fping', {
        'GET': [fping_controller, 'index']
    }),
    ('/os-fping/{id}', {
        'GET': [fping_controller, 'show']
    }),
    ('/os-hosts', {
        'GET': [hosts_controller, 'index']
    }),
    ('/os-hosts/{id}', {
        'GET': [hosts_controller, 'show'],
        'PUT': [hosts_controller, 'update']
    }),
    ('/os-hosts/{id}/reboot', {
        'GET': [hosts_controller, 'reboot']
    }),
    ('/os-hosts/{id}/shutdown', {
        'GET': [hosts_controller, 'shutdown']
    }),
    ('/os-hosts/{id}/startup', {
        'GET': [hosts_controller, 'startup']
    }),
    ('/os-hypervisors', {
        'GET': [hypervisors_controller, 'index']
    }),
    ('/os-hypervisors/detail', {
        'GET': [hypervisors_controller, 'detail']
    }),
    ('/os-hypervisors/statistics', {
        'GET': [hypervisors_controller, 'statistics']
    }),
    ('/os-hypervisors/{id}', {
        'GET': [hypervisors_controller, 'show']
    }),
    ('/os-hypervisors/{id}/search', {
        'GET': [hypervisors_controller, 'search']
    }),
    ('/os-hypervisors/{id}/servers', {
        'GET': [hypervisors_controller, 'servers']
    }),
    ('/os-hypervisors/{id}/uptime', {
        'GET': [hypervisors_controller, 'uptime']
    }),
    ('/os-instance_usage_audit_log', {
        'GET': [instance_usage_audit_log_controller, 'index']
    }),
    ('/os-instance_usage_audit_log/{id}', {
        'GET': [instance_usage_audit_log_controller, 'show']
    }),
    ('/os-keypairs', {
        'GET': [keypairs_controller, 'index'],
        'POST': [keypairs_controller, 'create']
    }),
    ('/os-keypairs/{id}', {
        'GET': [keypairs_controller, 'show'],
        'DELETE': [keypairs_controller, 'delete']
    }),
    ('/os-migrations', {
        'GET': [migrations_controller, 'index']
    }),
    ('/os-networks', {
        'GET': [networks_controller, 'index'],
        'POST': [networks_controller, 'create']
    }),
    ('/os-networks/add', {
        'POST': [networks_controller, 'add']
    }),
    ('/os-networks/{id}', {
        'GET': [networks_controller, 'show'],
        'DELETE': [networks_controller, 'delete']
    }),
    ('/os-networks/{id}/action', {
        'POST': [networks_controller, 'action'],
    }),
    ('/os-quota-class-sets/{id}', {
        'GET': [quota_classes_controller, 'show'],
        'PUT': [quota_classes_controller, 'update']
    }),
    ('/os-quota-sets/{id}', {
        'GET': [quota_set_controller, 'show'],
        'PUT': [quota_set_controller, 'update'],
        'DELETE': [quota_set_controller, 'delete']
    }),
    ('/os-quota-sets/{id}/detail', {
        'GET': [quota_set_controller, 'detail']
    }),
    ('/os-quota-sets/{id}/defaults', {
        'GET': [quota_set_controller, 'defaults']
    }),
    ('/os-security-group-default-rules', {
        'GET': [security_group_default_rules_controller, 'index'],
        'POST': [security_group_default_rules_controller, 'create']
    }),
    ('/os-security-group-default-rules/{id}', {
        'GET': [security_group_default_rules_controller, 'show'],
        'DELETE': [security_group_default_rules_controller, 'delete']
    }),
    ('/os-security-group-rules', {
        'POST': [security_group_rules_controller, 'create']
    }),
    ('/os-security-group-rules/{id}', {
        'DELETE': [security_group_rules_controller, 'delete']
    }),
    ('/os-security-groups', {
        'GET': [security_group_controller, 'index'],
        'POST': [security_group_controller, 'create']
    }),
    ('/os-security-groups/{id}', {
        'GET': [security_group_controller, 'show'],
        'PUT': [security_group_controller, 'update'],
        'DELETE': [security_group_controller, 'delete']
    }),
    ('/os-server-external-events', {
        'POST': [server_external_events_controller, 'create']
    }),
    ('/os-server-groups', {
        'GET': [server_groups_controller, 'index'],
        'POST': [server_groups_controller, 'create']
    }),
    ('/os-server-groups/{id}', {
        'GET': [server_groups_controller, 'show'],
        'DELETE': [server_groups_controller, 'delete']
    }),
    ('/os-services', {
        'GET': [services_controller, 'index']
    }),
    ('/os-services/{id}', {
        'PUT': [services_controller, 'update'],
        'DELETE': [services_controller, 'delete']
    }),
    ('/os-simple-tenant-usage', {
        'GET': [simple_tenant_usage_controller, 'index']
    }),
    ('/os-simple-tenant-usage/{id}', {
        'GET': [simple_tenant_usage_controller, 'show']
    }),
    ('/os-snapshots', {
        'GET': [snapshots_controller, 'index'],
        'POST': [snapshots_controller, 'create']
    }),
    ('/os-snapshots/detail', {
        'GET': [snapshots_controller, 'detail']
    }),
    ('/os-snapshots/{id}', {
        'GET': [snapshots_controller, 'show'],
        'DELETE': [snapshots_controller, 'delete']
    }),
    ('/os-tenant-networks', {
        'GET': [tenant_networks_controller, 'index'],
        'POST': [tenant_networks_controller, 'create']
    }),
    ('/os-tenant-networks/{id}', {
        'GET': [tenant_networks_controller, 'show'],
        'DELETE': [tenant_networks_controller, 'delete']
    }),
    ('/os-volumes', {
        'GET': [volumes_controller, 'index'],
        'POST': [volumes_controller, 'create'],
    }),
    ('/os-volumes/detail', {
        'GET': [volumes_controller, 'detail'],
    }),
    ('/os-volumes/{id}', {
        'GET': [volumes_controller, 'show'],
        'DELETE': [volumes_controller, 'delete']
    }),
    # NOTE: '/os-volumes_boot' is a clone of '/servers'. We may want to
    # deprecate it in the future.
    ('/os-volumes_boot', {
        'GET': [server_controller, 'index'],
        'POST': [server_controller, 'create']
    }),
    ('/os-volumes_boot/detail', {
        'GET': [server_controller, 'detail']
    }),
    ('/os-volumes_boot/{id}', {
        'GET': [server_controller, 'show'],
        'PUT': [server_controller, 'update'],
        'DELETE': [server_controller, 'delete']
    }),
    ('/os-volumes_boot/{id}/action', {
        'POST': [server_controller, 'action']
    }),
    ('/servers', {
        'GET': [server_controller, 'index'],
        'POST': [server_controller, 'create']
    }),
    ('/servers/detail', {
        'GET': [server_controller, 'detail']
    }),
    ('/servers/{id}', {
        'GET': [server_controller, 'show'],
        'PUT': [server_controller, 'update'],
        'DELETE': [server_controller, 'delete']
    }),
    ('/servers/{id}/action', {
        'POST': [server_controller, 'action']
    }),
    ('/servers/{server_id}/consoles', {
        'GET': [consoles_controller, 'index'],
        'POST': [consoles_controller, 'create']
    }),
    ('/servers/{server_id}/consoles/{id}', {
        'GET': [consoles_controller, 'show'],
        'DELETE': [consoles_controller, 'delete']
    }),
    ('/servers/{server_id}/diagnostics', {
        'GET': [server_diagnostics_controller, 'index']
    }),
    ('/servers/{server_id}/ips', {
        'GET': [ips_controller, 'index']
    }),
    ('/servers/{server_id}/ips/{id}', {
        'GET': [ips_controller, 'show']
    }),
    ('/servers/{server_id}/metadata', {
        'GET': [server_metadata_controller, 'index'],
        'POST': [server_metadata_controller, 'create'],
        'PUT': [server_metadata_controller, 'update_all'],
    }),
    ('/servers/{server_id}/metadata/{id}', {
        'GET': [server_metadata_controller, 'show'],
        'PUT': [server_metadata_controller, 'update'],
        'DELETE': [server_metadata_controller, 'delete'],
    }),
    ('/servers/{server_id}/migrations', {
        'GET': [server_migrations_controller, 'index']
    }),
    ('/servers/{server_id}/migrations/{id}', {
        'GET': [server_migrations_controller, 'show'],
        'DELETE': [server_migrations_controller, 'delete']
    }),
    ('/servers/{server_id}/migrations/{id}/action', {
        'POST': [server_migrations_controller, 'action']
    }),
    ('/servers/{server_id}/os-instance-actions', {
        'GET': [instance_actions_controller, 'index']
    }),
    ('/servers/{server_id}/os-instance-actions/{id}', {
        'GET': [instance_actions_controller, 'show']
    }),
    ('/servers/{server_id}/os-interface', {
        'GET': [server_os_interface_controller, 'index'],
        'POST': [server_os_interface_controller, 'create']
    }),
    ('/servers/{server_id}/os-interface/{id}', {
        'GET': [server_os_interface_controller, 'show'],
        'DELETE': [server_os_interface_controller, 'delete']
    }),
    ('/servers/{server_id}/os-server-password', {
        'GET': [server_password_controller, 'index'],
        'DELETE': [server_password_controller, 'clear']
    }),
    ('/servers/{server_id}/os-virtual-interfaces', {
        'GET': [virtual_interfaces_controller, 'index']
    }),
    ('/servers/{server_id}/os-volume_attachments', {
        'GET': [server_volume_attachments_controller, 'index'],
        'POST': [server_volume_attachments_controller, 'create'],
    }),
    ('/servers/{server_id}/os-volume_attachments/{id}', {
        'GET': [server_volume_attachments_controller, 'show'],
        'PUT': [server_volume_attachments_controller, 'update'],
        'DELETE': [server_volume_attachments_controller, 'delete']
    }),
    ('/servers/{server_id}/remote-consoles', {
        'POST': [server_remote_consoles_controller, 'create']
    }),
    ('/servers/{server_id}/os-security-groups', {
        'GET': [server_security_groups_controller, 'index']
    }),
    ('/servers/{server_id}/tags', {
        'GET': [server_tags_controller, 'index'],
        'PUT': [server_tags_controller, 'update_all'],
        'DELETE': [server_tags_controller, 'delete_all'],
    }),
    ('/servers/{server_id}/tags/{id}', {
        'GET': [server_tags_controller, 'show'],
        'PUT': [server_tags_controller, 'update'],
        'DELETE': [server_tags_controller, 'delete']
    }),
)


class APIRouterV21(base_wsgi.Router):
    """Routes requests on the OpenStack API to the appropriate controller
    and method. The URL mapping based on the plain list `ROUTE_LIST` is built
    at here.
    """
    def __init__(self, custom_routes=None):
        """:param custom_routes: the additional routes can be added by this
               parameter. This parameter is used to test on some fake routes
               primarily.
        """
        super(APIRouterV21, self).__init__(nova.api.openstack.ProjectMapper())

        if custom_routes is None:
            custom_routes = tuple()

        for path, methods in ROUTE_LIST + custom_routes:
            # NOTE(alex_xu): The variable 'methods' is a dict in normal, since
            # the dict includes all the methods supported in the path. But
            # if the variable 'method' is a string, it means a redirection.
            # For example, the request to the '' will be redirect to the '/' in
            # the Nova API. To indicate that, using the target path instead of
            # a dict. The route entry just writes as "('', '/)".
            if isinstance(methods, str):
                self.map.redirect(path, methods)
                continue

            for method, controller_info in methods.items():
                # TODO(alex_xu): In the end, I want to create single controller
                # instance instead of create controller instance for each
                # route.
                controller = controller_info[0]()
                action = controller_info[1]
                self.map.create_route(path, method, controller, action)

    @classmethod
    def factory(cls, global_config, **local_config):
        """Simple paste factory, :class:`nova.wsgi.Router` doesn't have one."""
        return cls()

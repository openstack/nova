# Copyright 2013 IBM Corp.
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

import copy

from oslo_log import log as logging

import webob.exc

from nova.api.openstack.compute import admin_actions
from nova.api.openstack.compute import admin_password
from nova.api.openstack.compute import config_drive
from nova.api.openstack.compute import console_output
from nova.api.openstack.compute import create_backup
from nova.api.openstack.compute import deferred_delete
from nova.api.openstack.compute import evacuate
from nova.api.openstack.compute import extended_availability_zone
from nova.api.openstack.compute import extended_server_attributes
from nova.api.openstack.compute import extended_status
from nova.api.openstack.compute import extended_volumes
from nova.api.openstack.compute import hide_server_addresses
from nova.api.openstack.compute import lock_server
from nova.api.openstack.compute import migrate_server
from nova.api.openstack.compute import multinic
from nova.api.openstack.compute import pause_server
from nova.api.openstack.compute import rescue
from nova.api.openstack.compute import scheduler_hints
from nova.api.openstack.compute import server_usage
from nova.api.openstack.compute import servers
from nova.api.openstack.compute import shelve
from nova.api.openstack.compute import suspend_server
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import exception
from nova.policies import extensions as ext_policies

ALIAS = 'extensions'
LOG = logging.getLogger(__name__)

# NOTE(cyeoh): The following mappings are currently incomplete
# Having a v2.1 extension loaded can imply that several v2 extensions
# should also appear to be loaded (although they no longer do in v2.1)
v21_to_v2_extension_list_mapping = {
    'os-quota-sets': [{'name': 'UserQuotas', 'alias': 'os-user-quotas',
                       'description': 'Project user quota support.'},
                      {'name': 'ExtendedQuotas',
                       'alias': 'os-extended-quotas',
                       'description': ('Adds ability for admins to delete'
                        ' quota and optionally force the update Quota'
                        ' command.')}],
    'os-cells': [{'name': 'CellCapacities', 'alias': 'os-cell-capacities',
                 'description': ('Adding functionality to get cell'
                  ' capacities.')}],
    'os-baremetal-nodes': [{'name': 'BareMetalExtStatus',
                            'alias': 'os-baremetal-ext-status',
                            'description': ('Add extended status in'
                             ' Baremetal Nodes v2 API.')}],
    'os-block-device-mapping': [{'name': 'BlockDeviceMappingV2Boot',
                                 'alias': 'os-block-device-mapping-v2-boot',
                                 'description': ('Allow boot with the new BDM'
                                 ' data format.')}],
    'os-cloudpipe': [{'name': 'CloudpipeUpdate',
                      'alias': 'os-cloudpipe-update',
                      'description': ('Adds the ability to set the vpn'
                      ' ip/port for cloudpipe instances.')}],
    'servers': [{'name': 'Createserverext', 'alias': 'os-create-server-ext',
                 'description': ('Extended support to the Create Server'
                 ' v1.1 API.')},
                {'name': 'ExtendedIpsMac', 'alias': 'OS-EXT-IPS-MAC',
                 'description': 'Adds mac address parameter to the ip list.'},
                {'name': 'ExtendedIps', 'alias': 'OS-EXT-IPS',
                 'description': 'Adds type parameter to the ip list.'},
                {'name': 'ServerListMultiStatus',
                 'alias': 'os-server-list-multi-status',
                 'description': ('Allow to filter the servers by a set of'
                 ' status values.')},
                {'name': 'ServerSortKeys', 'alias': 'os-server-sort-keys',
                 'description': 'Add sorting support in get Server v2 API.'},
                {'name': 'ServerStartStop', 'alias': 'os-server-start-stop',
                 'description': 'Start/Stop instance compute API support.'}],
    'flavors': [{'name': 'FlavorDisabled', 'alias': 'OS-FLV-DISABLED',
                 'description': ('Support to show the disabled status'
                 ' of a flavor.')},
                {'name': 'FlavorExtraData', 'alias': 'OS-FLV-EXT-DATA',
                 'description': 'Provide additional data for flavors.'},
                {'name': 'FlavorSwap', 'alias': 'os-flavor-swap',
                 'description': ('Support to show the swap status of a'
                 ' flavor.')}],
    'os-services': [{'name': 'ExtendedServicesDelete',
                     'alias': 'os-extended-services-delete',
                     'description': 'Extended services deletion support.'},
                    {'name': 'ExtendedServices', 'alias':
                     'os-extended-services',
                     'description': 'Extended services support.'}],
    'os-evacuate': [{'name': 'ExtendedEvacuateFindHost',
                     'alias': 'os-extended-evacuate-find-host',
                     'description': ('Enables server evacuation without'
                     ' target host. Scheduler will select one to target.')}],
    'os-floating-ips': [{'name': 'ExtendedFloatingIps',
                     'alias': 'os-extended-floating-ips',
                     'description': ('Adds optional fixed_address to the add'
                     ' floating IP command.')}],
    'os-hypervisors': [{'name': 'ExtendedHypervisors',
                     'alias': 'os-extended-hypervisors',
                     'description': 'Extended hypervisors support.'},
                     {'name': 'HypervisorStatus',
                     'alias': 'os-hypervisor-status',
                     'description': 'Show hypervisor status.'}],
    'os-networks': [{'name': 'ExtendedNetworks',
                     'alias': 'os-extended-networks',
                     'description': 'Adds additional fields to networks.'}],
    'os-rescue': [{'name': 'ExtendedRescueWithImage',
                   'alias': 'os-extended-rescue-with-image',
                   'description': ('Allow the user to specify the image to'
                   ' use for rescue.')}],
    'os-extended-status': [{'name': 'ExtendedStatus',
                   'alias': 'OS-EXT-STS',
                   'description': 'Extended Status support.'}],
    'os-used-limits': [{'name': 'UsedLimitsForAdmin',
                        'alias': 'os-used-limits-for-admin',
                        'description': ('Provide data to admin on limited'
                        ' resources used by other tenants.')}],
    'os-volumes': [{'name': 'VolumeAttachmentUpdate',
                    'alias': 'os-volume-attachment-update',
                    'description': ('Support for updating a volume'
                    ' attachment.')}],
    'os-server-groups': [{'name': 'ServerGroupQuotas',
                    'alias': 'os-server-group-quotas',
                    'description': 'Adds quota support to server groups.'}],
}

# v2.1 plugins which should never appear in the v2 extension list
# This should be the v2.1 alias, not the V2.0 alias
v2_extension_suppress_list = ['servers', 'images', 'versions', 'flavors',
                              'os-block-device-mapping-v1', 'os-consoles',
                              'extensions', 'image-metadata', 'ips', 'limits',
                              'server-metadata', 'server-migrations',
                              'os-server-tags'
                            ]

# v2.1 plugins which should appear under a different name in v2
v21_to_v2_alias_mapping = {
    'image-size': 'OS-EXT-IMG-SIZE',
    'os-remote-consoles': 'os-consoles',
    'os-disk-config': 'OS-DCF',
    'os-extended-availability-zone': 'OS-EXT-AZ',
    'os-extended-server-attributes': 'OS-EXT-SRV-ATTR',
    'os-multinic': 'NMN',
    'os-scheduler-hints': 'OS-SCH-HNT',
    'os-server-usage': 'OS-SRV-USG',
    'os-instance-usage-audit-log': 'os-instance_usage_audit_log',
}

# NOTE(sdague): this is the list of extension metadata that we display
# to the user for features that we provide. This exists for legacy
# purposes because applications were once asked to look for these
# things to decide if a feature is enabled. As we remove extensions
# completely from the code we're going to have a static list here to
# keep the surface metadata the same.
hardcoded_extensions = [
    {'name': 'Agents',
     'alias': 'os-agents',
     'description': 'Agents support.'
    },
    {'name': 'Aggregates',
     'alias': 'os-aggregates',
     'description': 'Admin-only aggregate administration.'
    },
    {'name': 'DiskConfig',
     'alias': 'os-disk-config',
     'description': 'Disk Management Extension.'},
    {'name': 'AccessIPs',
     'description': 'Access IPs support.',
     'alias': 'os-access-ips'},
    {'name': 'PreserveEphemeralOnRebuild',
     'description': ('Allow preservation of the '
                     'ephemeral partition on rebuild.'),
     'alias': 'os-preserve-ephemeral-rebuild'},
    {'name': 'Personality',
     'description': 'Personality support.',
     'alias': 'os-personality'},
    {'name': 'Flavors',
     'description': 'Flavors Extension.',
     'alias': 'flavors'},
    {'name': 'FlavorManage',
     'description': 'Flavor create/delete API support.',
     'alias': 'os-flavor-manage'},
    {'name': 'FlavorRxtx',
     'description': 'Support to show the rxtx status of a flavor.',
     'alias': 'os-flavor-rxtx'},
    {'name': 'FlavorExtraSpecs',
     'description': 'Flavors extra specs support.',
     'alias': 'os-flavor-extra-specs'},
    {'name': 'FlavorAccess',
     'description': 'Flavor access support.',
     'alias': 'os-flavor-access'},
    {'name': 'FloatingIpDns',
     'description': 'Floating IP DNS support.',
     'alias': 'os-floating-ip-dns'},
    {'name': 'FloatingIpPools',
     'description': 'Floating IPs support.',
     'alias': 'os-floating-ip-pools'},
    {'name': 'FloatingIps',
     'description': 'Floating IPs support.',
     'alias': 'os-floating-ips'},
    {'name': 'FloatingIpsBulk',
     'description': 'Bulk handling of Floating IPs.',
     'alias': 'os-floating-ips-bulk'},
    {'name': 'Keypairs',
     'description': 'Keypair Support.',
     'alias': 'os-keypairs'}
]


# TODO(alex_xu): This is a list of unused extension objs. Add those
# extension objs here for building a compatible extension API. Finally,
# we should remove those extension objs, and add corresponding entries
# in the 'hardcoded_extensions'.
unused_extension_objs = [
    admin_actions.AdminActions,
    admin_password.AdminPassword,
    config_drive.ConfigDrive,
    console_output.ConsoleOutput,
    create_backup.CreateBackup,
    deferred_delete.DeferredDelete,
    evacuate.Evacuate,
    extended_availability_zone.ExtendedAvailabilityZone,
    extended_server_attributes.ExtendedServerAttributes,
    extended_status.ExtendedStatus,
    extended_volumes.ExtendedVolumes,
    hide_server_addresses.HideServerAddresses,
    lock_server.LockServer,
    migrate_server.MigrateServer,
    multinic.Multinic,
    pause_server.PauseServer,
    rescue.Rescue,
    scheduler_hints.SchedulerHints,
    server_usage.ServerUsage,
    servers.Servers,
    shelve.Shelve,
    suspend_server.SuspendServer
]

# V2.1 does not support XML but we need to keep an entry in the
# /extensions information returned to the user for backwards
# compatibility
FAKE_XML_URL = "http://docs.openstack.org/compute/ext/fake_xml"
FAKE_UPDATED_DATE = "2014-12-03T00:00:00Z"


class FakeExtension(object):
    def __init__(self, name, alias, description=""):
        self.name = name
        self.alias = alias
        self.__doc__ = description
        self.version = -1


class ExtensionInfoController(wsgi.Controller):

    def __init__(self, extension_info):
        self.extension_info = extension_info

    def _translate(self, ext):
        ext_data = {}
        ext_data["name"] = ext.name
        ext_data["alias"] = ext.alias
        ext_data["description"] = ext.__doc__
        ext_data["namespace"] = FAKE_XML_URL
        ext_data["updated"] = FAKE_UPDATED_DATE
        ext_data["links"] = []
        return ext_data

    def _create_fake_ext(self, name, alias, description=""):
        return FakeExtension(name, alias, description)

    def _add_vif_extension(self, all_extensions):
        vif_extension = {}
        vif_extension_info = {'name': 'ExtendedVIFNet',
                              'alias': 'OS-EXT-VIF-NET',
                              'description': 'Adds network id parameter'
                                  ' to the virtual interface list.'}
        vif_extension[vif_extension_info["alias"]] = self._create_fake_ext(
            vif_extension_info["name"], vif_extension_info["alias"],
                vif_extension_info["description"])
        all_extensions.update(vif_extension)

    def _get_extensions(self, context):
        """Filter extensions list based on policy."""

        all_extensions = dict()

        for item in hardcoded_extensions:
            all_extensions[item['alias']] = self._create_fake_ext(
                item['name'],
                item['alias'],
                item['description']
            )

        for ext_cls in unused_extension_objs:
            ext = ext_cls(None)
            all_extensions[ext.alias] = ext

        for alias, ext in self.extension_info.get_extensions().items():
            all_extensions[alias] = ext

        # Add fake v2 extensions to list
        extra_exts = {}
        for alias in all_extensions:
            if alias in v21_to_v2_extension_list_mapping:
                for extra_ext in v21_to_v2_extension_list_mapping[alias]:
                    extra_exts[extra_ext["alias"]] = self._create_fake_ext(
                        extra_ext["name"], extra_ext["alias"],
                        extra_ext["description"])
        all_extensions.update(extra_exts)

        # Suppress extensions which we don't want to see in v2
        for suppress_ext in v2_extension_suppress_list:
            try:
                del all_extensions[suppress_ext]
            except KeyError:
                pass

        # v2.1 to v2 extension name mapping
        for rename_ext in v21_to_v2_alias_mapping:
            if rename_ext in all_extensions:
                new_name = v21_to_v2_alias_mapping[rename_ext]
                mod_ext = copy.deepcopy(
                    all_extensions.pop(rename_ext))
                mod_ext.alias = new_name
                all_extensions[new_name] = mod_ext

        return all_extensions

    @extensions.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        context.can(ext_policies.BASE_POLICY_NAME)
        all_extensions = self._get_extensions(context)
        # NOTE(gmann): This is for v2.1 compatible mode where
        # extension list should show all extensions as shown by v2.
        # Here we add VIF extension which has been removed from v2.1 list.
        if req.is_legacy_v2():
            self._add_vif_extension(all_extensions)
        sorted_ext_list = sorted(
            all_extensions.items())

        extensions = []
        for _alias, ext in sorted_ext_list:
            extensions.append(self._translate(ext))

        return dict(extensions=extensions)

    @extensions.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(ext_policies.BASE_POLICY_NAME)
        try:
            # NOTE(dprince): the extensions alias is used as the 'id' for show
            ext = self._get_extensions(context)[id]
        except KeyError:
            raise webob.exc.HTTPNotFound()

        return dict(extension=self._translate(ext))


class ExtensionInfo(extensions.V21APIExtensionBase):
    """Extension information."""

    name = "Extensions"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = [
            extensions.ResourceExtension(
                ALIAS, ExtensionInfoController(self.extension_info),
                member_name='extension')]
        return resources

    def get_controller_extensions(self):
        return []


class LoadedExtensionInfo(object):
    """Keep track of all loaded API extensions."""

    def __init__(self):
        self.extensions = {}

    def register_extension(self, ext):
        if not self._check_extension(ext):
            return False

        alias = ext.alias

        if alias in self.extensions:
            raise exception.NovaException("Found duplicate extension: %s"
                                          % alias)
        self.extensions[alias] = ext
        return True

    def _check_extension(self, extension):
        """Checks for required methods in extension objects."""
        try:
            extension.is_valid()
        except AttributeError:
            LOG.exception("Exception loading extension")
            return False

        return True

    def get_extensions(self):
        return self.extensions

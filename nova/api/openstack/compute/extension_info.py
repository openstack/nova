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

import webob.exc

from nova.api.openstack import wsgi
from nova.policies import extensions as ext_policies


EXTENSION_LIST = [
    {
        "alias": "NMN",
        "description": "Multiple network support.",
        "links": [],
        "name": "Multinic",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-DCF",
        "description": "Disk Management Extension.",
        "links": [],
        "name": "DiskConfig",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-EXT-AZ",
        "description": "Extended Availability Zone support.",
        "links": [],
        "name": "ExtendedAvailabilityZone",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-EXT-IMG-SIZE",
        "description": "Adds image size to image listings.",
        "links": [],
        "name": "ImageSize",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-EXT-IPS",
        "description": "Adds type parameter to the ip list.",
        "links": [],
        "name": "ExtendedIps",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-EXT-IPS-MAC",
        "description": "Adds mac address parameter to the ip list.",
        "links": [],
        "name": "ExtendedIpsMac",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-EXT-SRV-ATTR",
        "description": "Extended Server Attributes support.",
        "links": [],
        "name": "ExtendedServerAttributes",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-EXT-STS",
        "description": "Extended Status support.",
        "links": [],
        "name": "ExtendedStatus",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-FLV-DISABLED",
        "description": "Support to show the disabled status of a flavor.",
        "links": [],
        "name": "FlavorDisabled",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-FLV-EXT-DATA",
        "description": "Provide additional data for flavors.",
        "links": [],
        "name": "FlavorExtraData",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-SCH-HNT",
        "description": "Pass arbitrary key/value pairs to the scheduler.",
        "links": [],
        "name": "SchedulerHints",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "OS-SRV-USG",
        "description": "Adds launched_at and terminated_at on Servers.",
        "links": [],
        "name": "ServerUsage",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-access-ips",
        "description": "Access IPs support.",
        "links": [],
        "name": "AccessIPs",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-admin-actions",
        "description": "Enable admin-only server actions\n\n    "
                       "Actions include: resetNetwork, injectNetworkInfo, "
                        "os-resetState\n    ",
        "links": [],
        "name": "AdminActions",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-admin-password",
        "description": "Admin password management support.",
        "links": [],
        "name": "AdminPassword",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-agents",
        "description": "Agents support.",
        "links": [],
        "name": "Agents",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-aggregates",
        "description": "Admin-only aggregate administration.",
        "links": [],
        "name": "Aggregates",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-assisted-volume-snapshots",
        "description": "Assisted volume snapshots.",
        "links": [],
        "name": "AssistedVolumeSnapshots",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-attach-interfaces",
        "description": "Attach interface support.",
        "links": [],
        "name": "AttachInterfaces",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-availability-zone",
        "description": "1. Add availability_zone to the Create Server "
                       "API.\n       2. Add availability zones "
                       "describing.\n    ",
        "links": [],
        "name": "AvailabilityZone",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-baremetal-ext-status",
        "description": "Add extended status in Baremetal Nodes v2 API.",
        "links": [],
        "name": "BareMetalExtStatus",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-baremetal-nodes",
        "description": "Admin-only bare-metal node administration.",
        "links": [],
        "name": "BareMetalNodes",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-block-device-mapping",
        "description": "Block device mapping boot support.",
        "links": [],
        "name": "BlockDeviceMapping",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-block-device-mapping-v2-boot",
        "description": "Allow boot with the new BDM data format.",
        "links": [],
        "name": "BlockDeviceMappingV2Boot",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-cell-capacities",
        "description": "Adding functionality to get cell capacities.",
        "links": [],
        "name": "CellCapacities",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-cells",
        "description": "Enables cells-related functionality such as adding "
                       "neighbor cells,\n    listing neighbor cells, "
                       "and getting the capabilities of the local cell.\n    ",
        "links": [],
        "name": "Cells",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-certificates",
        "description": "Certificates support.",
        "links": [],
        "name": "Certificates",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-cloudpipe",
        "description": "Adds actions to create cloudpipe instances.\n\n    "
                       "When running with the Vlan network mode, you need a "
                       "mechanism to route\n    from the public Internet to "
                       "your vlans.  This mechanism is known as a\n    "
                       "cloudpipe.\n\n    At the time of creating this class, "
                       "only OpenVPN is supported.  Support for\n    a SSH "
                       "Bastion host is forthcoming.\n    ",
        "links": [],
        "name": "Cloudpipe",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-cloudpipe-update",
        "description": "Adds the ability to set the vpn ip/port for cloudpipe "
                       "instances.",
        "links": [],
        "name": "CloudpipeUpdate",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-config-drive",
        "description": "Config Drive Extension.",
        "links": [],
        "name": "ConfigDrive",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-console-auth-tokens",
        "description": "Console token authentication support.",
        "links": [],
        "name": "ConsoleAuthTokens",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-console-output",
        "description": "Console log output support, with tailing ability.",
        "links": [],
        "name": "ConsoleOutput",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-consoles",
        "description": "Interactive Console support.",
        "links": [],
        "name": "Consoles",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-create-backup",
        "description": "Create a backup of a server.",
        "links": [],
        "name": "CreateBackup",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-create-server-ext",
        "description": "Extended support to the Create Server v1.1 API.",
        "links": [],
        "name": "Createserverext",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-deferred-delete",
        "description": "Instance deferred delete.",
        "links": [],
        "name": "DeferredDelete",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-evacuate",
        "description": "Enables server evacuation.",
        "links": [],
        "name": "Evacuate",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-evacuate-find-host",
        "description": "Enables server evacuation without target host. "
                       "Scheduler will select one to target.",
        "links": [],
        "name": "ExtendedEvacuateFindHost",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-floating-ips",
        "description": "Adds optional fixed_address to the add floating IP "
                       "command.",
        "links": [],
        "name": "ExtendedFloatingIps",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-hypervisors",
        "description": "Extended hypervisors support.",
        "links": [],
        "name": "ExtendedHypervisors",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-networks",
        "description": "Adds additional fields to networks.",
        "links": [],
        "name": "ExtendedNetworks",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-quotas",
        "description": "Adds ability for admins to delete quota and "
                       "optionally force the update Quota command.",
        "links": [],
        "name": "ExtendedQuotas",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-rescue-with-image",
        "description": "Allow the user to specify the image to use for "
                       "rescue.",
        "links": [],
        "name": "ExtendedRescueWithImage",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-services",
        "description": "Extended services support.",
        "links": [],
        "name": "ExtendedServices",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-services-delete",
        "description": "Extended services deletion support.",
        "links": [],
        "name": "ExtendedServicesDelete",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-status",
        "description": "Extended Status support.",
        "links": [],
        "name": "ExtendedStatus",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-extended-volumes",
        "description": "Extended Volumes support.",
        "links": [],
        "name": "ExtendedVolumes",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-fixed-ips",
        "description": "Fixed IPs support.",
        "links": [],
        "name": "FixedIPs",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-flavor-access",
        "description": "Flavor access support.",
        "links": [],
        "name": "FlavorAccess",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-flavor-extra-specs",
        "description": "Flavors extra specs support.",
        "links": [],
        "name": "FlavorExtraSpecs",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-flavor-manage",
        "description": "Flavor create/delete API support.",
        "links": [],
        "name": "FlavorManage",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-flavor-rxtx",
        "description": "Support to show the rxtx status of a flavor.",
        "links": [],
        "name": "FlavorRxtx",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-flavor-swap",
        "description": "Support to show the swap status of a flavor.",
        "links": [],
        "name": "FlavorSwap",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-floating-ip-dns",
        "description": "Floating IP DNS support.",
        "links": [],
        "name": "FloatingIpDns",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-floating-ip-pools",
        "description": "Floating IPs support.",
        "links": [],
        "name": "FloatingIpPools",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-floating-ips",
        "description": "Floating IPs support.",
        "links": [],
        "name": "FloatingIps",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-floating-ips-bulk",
        "description": "Bulk handling of Floating IPs.",
        "links": [],
        "name": "FloatingIpsBulk",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-fping",
        "description": "Fping Management Extension.",
        "links": [],
        "name": "Fping",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-hide-server-addresses",
        "description": "Support hiding server addresses in certain states.",
        "links": [],
        "name": "HideServerAddresses",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-hosts",
        "description": "Admin-only host administration.",
        "links": [],
        "name": "Hosts",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-hypervisor-status",
        "description": "Show hypervisor status.",
        "links": [],
        "name": "HypervisorStatus",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-hypervisors",
        "description": "Admin-only hypervisor administration.",
        "links": [],
        "name": "Hypervisors",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-instance-actions",
        "description": "View a log of actions and events taken on an "
                       "instance.",
        "links": [],
        "name": "InstanceActions",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-instance_usage_audit_log",
        "description": "Admin-only Task Log Monitoring.",
        "links": [],
        "name": "OSInstanceUsageAuditLog",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-keypairs",
        "description": "Keypair Support.",
        "links": [],
        "name": "Keypairs",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-lock-server",
        "description": "Enable lock/unlock server actions.",
        "links": [],
        "name": "LockServer",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-migrate-server",
        "description": "Enable migrate and live-migrate server actions.",
        "links": [],
        "name": "MigrateServer",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-migrations",
        "description": "Provide data on migrations.",
        "links": [],
        "name": "Migrations",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-multiple-create",
        "description": "Allow multiple create in the Create Server v2.1 API.",
        "links": [],
        "name": "MultipleCreate",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-networks",
        "description": "Admin-only Network Management Extension.",
        "links": [],
        "name": "Networks",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-networks-associate",
        "description": "Network association support.",
        "links": [],
        "name": "NetworkAssociationSupport",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-pause-server",
        "description": "Enable pause/unpause server actions.",
        "links": [],
        "name": "PauseServer",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-personality",
        "description": "Personality support.",
        "links": [],
        "name": "Personality",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-preserve-ephemeral-rebuild",
        "description": "Allow preservation of the ephemeral partition on "
                       "rebuild.",
        "links": [],
        "name": "PreserveEphemeralOnRebuild",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-quota-class-sets",
        "description": "Quota classes management support.",
        "links": [],
        "name": "QuotaClasses",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-quota-sets",
        "description": "Quotas management support.",
        "links": [],
        "name": "Quotas",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-rescue",
        "description": "Instance rescue mode.",
        "links": [],
        "name": "Rescue",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-security-group-default-rules",
        "description": "Default rules for security group support.",
        "links": [],
        "name": "SecurityGroupDefaultRules",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-security-groups",
        "description": "Security group support.",
        "links": [],
        "name": "SecurityGroups",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-diagnostics",
        "description": "Allow Admins to view server diagnostics through "
                       "server action.",
        "links": [],
        "name": "ServerDiagnostics",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-external-events",
        "description": "Server External Event Triggers.",
        "links": [],
        "name": "ServerExternalEvents",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-group-quotas",
        "description": "Adds quota support to server groups.",
        "links": [],
        "name": "ServerGroupQuotas",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-groups",
        "description": "Server group support.",
        "links": [],
        "name": "ServerGroups",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-list-multi-status",
        "description": "Allow to filter the servers by a set of status "
                       "values.",
        "links": [],
        "name": "ServerListMultiStatus",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-password",
        "description": "Server password support.",
        "links": [],
        "name": "ServerPassword",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-sort-keys",
        "description": "Add sorting support in get Server v2 API.",
        "links": [],
        "name": "ServerSortKeys",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-server-start-stop",
        "description": "Start/Stop instance compute API support.",
        "links": [],
        "name": "ServerStartStop",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-services",
        "description": "Services support.",
        "links": [],
        "name": "Services",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-shelve",
        "description": "Instance shelve mode.",
        "links": [],
        "name": "Shelve",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-simple-tenant-usage",
        "description": "Simple tenant usage extension.",
        "links": [],
        "name": "SimpleTenantUsage",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-suspend-server",
        "description": "Enable suspend/resume server actions.",
        "links": [],
        "name": "SuspendServer",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-tenant-networks",
        "description": "Tenant-based Network Management Extension.",
        "links": [],
        "name": "OSTenantNetworks",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-used-limits",
        "description": "Provide data on limited resources that are being "
                       "used.",
        "links": [],
        "name": "UsedLimits",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-used-limits-for-admin",
        "description": "Provide data to admin on limited resources used by "
                       "other tenants.",
        "links": [],
        "name": "UsedLimitsForAdmin",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-user-data",
        "description": "Add user_data to the Create Server API.",
        "links": [],
        "name": "UserData",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-user-quotas",
        "description": "Project user quota support.",
        "links": [],
        "name": "UserQuotas",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-virtual-interfaces",
        "description": "Virtual interface support.",
        "links": [],
        "name": "VirtualInterfaces",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-volume-attachment-update",
        "description": "Support for updating a volume attachment.",
        "links": [],
        "name": "VolumeAttachmentUpdate",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    },
    {
        "alias": "os-volumes",
        "description": "Volumes support.",
        "links": [],
        "name": "Volumes",
        "namespace": "http://docs.openstack.org/compute/ext/fake_xml",
        "updated": "2014-12-03T00:00:00Z"
    }
]


EXTENSION_LIST_LEGACY_V2_COMPATIBLE = EXTENSION_LIST[:]
EXTENSION_LIST_LEGACY_V2_COMPATIBLE.append({
    'alias': 'OS-EXT-VIF-NET',
    'description': 'Adds network id parameter to the virtual interface list.',
    'links': [],
    'name': 'ExtendedVIFNet',
    'namespace': 'http://docs.openstack.org/compute/ext/fake_xml',
    "updated": "2014-12-03T00:00:00Z"
})
EXTENSION_LIST_LEGACY_V2_COMPATIBLE = sorted(
    EXTENSION_LIST_LEGACY_V2_COMPATIBLE, key=lambda x: x['alias'])


class ExtensionInfoController(wsgi.Controller):

    @wsgi.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        context.can(ext_policies.BASE_POLICY_NAME, target={})

        # NOTE(gmann): This is for v2.1 compatible mode where
        # extension list should show all extensions as shown by v2.
        if req.is_legacy_v2():
            return dict(extensions=EXTENSION_LIST_LEGACY_V2_COMPATIBLE)

        return dict(extensions=EXTENSION_LIST)

    @wsgi.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(ext_policies.BASE_POLICY_NAME, target={})
        all_exts = EXTENSION_LIST
        # NOTE(gmann): This is for v2.1 compatible mode where
        # extension list should show all extensions as shown by v2.
        if req.is_legacy_v2():
            all_exts = EXTENSION_LIST_LEGACY_V2_COMPATIBLE

        # NOTE(dprince): the extensions alias is used as the 'id' for show
        for ext in all_exts:
            if ext['alias'] == id:
                return dict(extension=ext)

        raise webob.exc.HTTPNotFound()

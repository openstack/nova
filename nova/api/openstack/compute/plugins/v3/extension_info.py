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

import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.openstack.common import log as logging

ALIAS = 'extensions'
LOG = logging.getLogger(__name__)

# NOTE(cyeoh): The following mappings are currently incomplete
# Having a v2.1 extension loaded can imply that several v2 extensions
# should also appear to be loaded (although they no longer do in v2.1)
v21_to_v2_extension_list_mapping = {
    'os-quota-sets': [{'name': 'UserQuotas', 'alias': 'os-user-quotas'},
                      {'name': 'ExtendedQuotas',
                       'alias': 'os-extended-quotas'}],
    'os-cells': [{'name': 'CellCapacities', 'alias': 'os-cell-capacities'}],
    'os-baremetal-nodes': [{'name': 'BareMetalExtStatus',
                            'alias': 'os-baremetal-ext-status'}],
    'os-block-device-mapping': [{'name': 'BlockDeviceMappingV2Boot',
                                 'alias': 'os-block-device-mapping-v2-boot'}],
    'os-cloudpipe': [{'name': 'CloudpipeUpdate',
                      'alias': 'os-cloudpipe-update'}],
    'servers': [{'name': 'Createserverext', 'alias': 'os-create-server-ext'},
                {'name': 'ExtendedIpsMac', 'alias': 'OS-EXT-IPS-MAC'},
                {'name': 'ExtendedIps', 'alias': 'OS-EXT-IPS'},
                {'name': 'ServerListMultiStatus',
                 'alias': 'os-server-list-multi-status'},
                {'name': 'ServerSortKeys', 'alias': 'os-server-sort-keys'},
                {'name': 'ServerStartStop', 'alias': 'os-server-start-stop'}],
    'flavors': [{'name': 'FlavorDisabled', 'alias': 'OS-FLV-DISABLED'},
                {'name': 'FlavorExtraData', 'alias': 'OS-FLV-EXT-DATA'},
                {'name': 'FlavorSwap', 'alias': 'os-flavor-swap'}],
    'os-services': [{'name': 'ExtendedServicesDelete',
                     'alias': 'os-extended-services-delete'},
                    {'name': 'ExtendedServices', 'alias':
                     'os-extended-services'}],
    'os-evacuate': [{'name': 'ExtendedEvacuateFindHost',
                     'alias': 'os-extended-evacuate-find-host'}],
    'os-floating-ips': [{'name': 'ExtendedFloatingIps',
                     'alias': 'os-extended-floating-ips'}],
    'os-hypervisors': [{'name': 'ExtendedHypervisors',
                     'alias': 'os-extended-hypervisors'},
                     {'name': 'HypervisorStatus',
                     'alias': 'os-hypervisor-status'}],
    'os-networks': [{'name': 'ExtendedNetworks',
                     'alias': 'os-extended-networks'}],
    'os-rescue': [{'name': 'ExtendedRescueWithImage',
                   'alias': 'os-extended-rescue-with-image'}],
    'os-extended-status': [{'name': 'ExtendedStatus',
                   'alias': 'OS-EXT-STS'}],
    'os-virtual-interfaces': [{'name': 'ExtendedVIFNet',
                               'alias': 'OS-EXT-VIF-NET'}],
    'os-used-limits': [{'name': 'UsedLimitsForAdmin',
                        'alias': 'os-used-limits-for-admin'}],
    'os-volumes': [{'name': 'VolumeAttachmentUpdate',
                    'alias': 'os-volume-attachment-update'}],
    'os-server-groups': [{'name': 'ServerGroupQuotas',
                    'alias': 'os-server-group-quotas'}],
}

# v2.1 plugins which should never appear in the v2 extension list
# This should be the v2.1 alias, not the V2.0 alias
v2_extension_suppress_list = ['servers', 'images', 'versions', 'flavors',
                              'os-block-device-mapping-v1', 'os-consoles',
                              'extensions', 'image-metadata', 'ips', 'limits',
                              'server-metadata'
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

# V2.1 does not support XML but we need to keep an entry in the
# /extensions information returned to the user for backwards
# compatibility
FAKE_XML_URL = "http://docs.openstack.org/compute/ext/fake_xml"
FAKE_UPDATED_DATE = "2014-12-03T00:00:00Z"


class FakeExtension(object):
    def __init__(self, name, alias):
        self.name = name
        self.alias = alias
        self.__doc__ = ""
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

    def _create_fake_ext(self, alias, name):
        return FakeExtension(alias, name)

    def _get_extensions(self, context):
        """Filter extensions list based on policy."""

        discoverable_extensions = dict()
        for alias, ext in self.extension_info.get_extensions().iteritems():
            authorize = extensions.soft_extension_authorizer(
                'compute', 'v3:' + alias)
            if authorize(context, action='discoverable'):
                discoverable_extensions[alias] = ext
            else:
                LOG.debug("Filter out extension %s from discover list",
                          alias)

        # Add fake v2 extensions to list
        extra_exts = {}
        for alias in discoverable_extensions:
            if alias in v21_to_v2_extension_list_mapping:
                for extra_ext in v21_to_v2_extension_list_mapping[alias]:
                    extra_exts[extra_ext["alias"]] = self._create_fake_ext(
                        extra_ext["name"], extra_ext["alias"])
        discoverable_extensions.update(extra_exts)

        # Supress extensions which we don't want to see in v2
        for supress_ext in v2_extension_suppress_list:
            try:
                del discoverable_extensions[supress_ext]
            except KeyError:
                pass

        # v2.1 to v2 extension name mapping
        for rename_ext in v21_to_v2_alias_mapping:
            if rename_ext in discoverable_extensions:
                new_name = v21_to_v2_alias_mapping[rename_ext]
                mod_ext = copy.deepcopy(
                    discoverable_extensions.pop(rename_ext))
                mod_ext.alias = new_name
                discoverable_extensions[new_name] = mod_ext

        return discoverable_extensions

    @extensions.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']

        sorted_ext_list = sorted(
            self._get_extensions(context).iteritems())

        extensions = []
        for _alias, ext in sorted_ext_list:
            extensions.append(self._translate(ext))

        return dict(extensions=extensions)

    @extensions.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        try:
            # NOTE(dprince): the extensions alias is used as the 'id' for show
            ext = self._get_extensions(context)[id]
        except KeyError:
            raise webob.exc.HTTPNotFound()

        return dict(extension=self._translate(ext))


class ExtensionInfo(extensions.V3APIExtensionBase):
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

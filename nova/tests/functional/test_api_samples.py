# Copyright 2012 Nebula, Inc.
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

import base64
import copy
import datetime
import inspect
import os
import re
import urllib
import uuid as uuid_lib

import mock
from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import importutils
from oslo.utils import timeutils

from nova.api.metadata import password
from nova.api.openstack.compute.contrib import fping
from nova.api.openstack.compute import extensions
# Import extensions to pull in osapi_compute_extension CONF option used below.
from nova.cells import rpcapi as cells_rpcapi
from nova.cells import state
from nova.cloudpipe import pipelib
from nova.compute import api as compute_api
from nova.compute import cells_api as cells_api
from nova.compute import manager as compute_manager
from nova.compute import rpcapi as compute_rpcapi
from nova.conductor import manager as conductor_manager
from nova.console import manager as console_manager  # noqa - only for cfg
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova.network import api as network_api
from nova.network.neutronv2 import api as neutron_api  # noqa - only for cfg
from nova import objects
from nova.openstack.common import log as logging
import nova.quota
from nova.servicegroup import api as service_group_api
from nova import test
from nova.tests.functional import api_samples_test_base
from nova.tests.functional import integrated_helpers
from nova.tests.unit.api.openstack.compute.contrib import test_fping
from nova.tests.unit.api.openstack.compute.contrib import test_networks
from nova.tests.unit.api.openstack.compute.contrib import test_services
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network
from nova.tests.unit import fake_network_cache_model
from nova.tests.unit import fake_server_actions
from nova.tests.unit import fake_utils
from nova.tests.unit.image import fake
from nova.tests.unit.objects import test_network
from nova.tests.unit import utils as test_utils
from nova import utils
from nova.volume import cinder

CONF = cfg.CONF
CONF.import_opt('allow_resize_to_same_host', 'nova.compute.api')
CONF.import_opt('shelved_offload_time', 'nova.compute.manager')
CONF.import_opt('enable_network_quota',
                'nova.api.openstack.compute.contrib.os_tenant_networks')
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.extensions')
CONF.import_opt('vpn_image_id', 'nova.cloudpipe.pipelib')
CONF.import_opt('osapi_compute_link_prefix', 'nova.api.openstack.common')
CONF.import_opt('osapi_glance_link_prefix', 'nova.api.openstack.common')
CONF.import_opt('enable', 'nova.cells.opts', group='cells')
CONF.import_opt('cell_type', 'nova.cells.opts', group='cells')
CONF.import_opt('db_check_interval', 'nova.cells.state', group='cells')
LOG = logging.getLogger(__name__)


class ApiSampleTestBaseV2(api_samples_test_base.ApiSampleTestBase):
    _api_version = 'v2'

    def setUp(self):
        extends = []
        self.flags(use_ipv6=False,
                   osapi_compute_link_prefix=self._get_host(),
                   osapi_glance_link_prefix=self._get_glance_host())
        if not self.all_extensions:
            if hasattr(self, 'extends_name'):
                extends = [self.extends_name]
            ext = [self.extension_name] if self.extension_name else []
            self.flags(osapi_compute_extension=ext + extends)
        super(ApiSampleTestBaseV2, self).setUp()
        self.useFixture(test.SampleNetworks(host=self.network.host))
        fake_network.stub_compute_with_ips(self.stubs)
        fake_utils.stub_out_utils_spawn_n(self.stubs)
        self.generate_samples = os.getenv('GENERATE_SAMPLES') is not None


class ApiSamplesTrap(ApiSampleTestBaseV2):
    """Make sure extensions don't get added without tests."""

    all_extensions = True

    def _get_extensions_tested(self):
        tests = []
        for attr in globals().values():
            if not inspect.isclass(attr):
                continue  # Skip non-class objects
            if not issubclass(attr, integrated_helpers._IntegratedTestBase):
                continue  # Skip non-test classes
            if attr.extension_name is None:
                continue  # Skip base tests
            cls = importutils.import_class(attr.extension_name)
            tests.append(cls.alias)
        return tests

    def _get_extensions(self):
        extensions = []
        response = self._do_get('extensions')
        for extension in jsonutils.loads(response.content)['extensions']:
            extensions.append(str(extension['alias']))
        return extensions

    def test_all_extensions_have_samples(self):
        # NOTE(danms): This is a list of extensions which are currently
        # in the tree but that don't (yet) have tests. This list should
        # NOT be allowed to grow, and should shrink to zero (and be
        # removed) soon.
        do_not_approve_additions = []
        do_not_approve_additions.append('os-create-server-ext')
        do_not_approve_additions.append('os-baremetal-ext-status')
        do_not_approve_additions.append('os-baremetal-nodes')

        tests = self._get_extensions_tested()
        extensions = self._get_extensions()
        missing_tests = []
        for extension in extensions:
            # NOTE(danms): if you add tests, remove it from the
            # exclusions list
            self.assertFalse(extension in do_not_approve_additions and
                             extension in tests)

            # NOTE(danms): if you add an extension, it must come with
            # api_samples tests!
            if (extension not in tests and
                    extension not in do_not_approve_additions):
                missing_tests.append(extension)

        if missing_tests:
            LOG.error("Extensions are missing tests: %s" % missing_tests)
        self.assertEqual(missing_tests, [])


class VersionsSampleJsonTest(ApiSampleTestBaseV2):
    def test_versions_get(self):
        response = self._do_get('', strip_version=True)
        subs = self._get_regexes()
        self._verify_response('versions-get-resp', subs, response, 200)


class ServersSampleBase(ApiSampleTestBaseV2):
    def _post_server(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        response = self._do_post('servers', 'server-post-req', subs)
        subs = self._get_regexes()
        return self._verify_response('server-post-resp', subs, response, 202)


class ServersSampleJsonTest(ServersSampleBase):
    def test_servers_post(self):
        return self._post_server()

    def test_servers_get(self):
        uuid = self.test_servers_post()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers')
        subs = self._get_regexes()
        subs['id'] = uuid
        self._verify_response('servers-list-resp', subs, response, 200)

    def test_servers_details(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        self._verify_response('servers-details-resp', subs, response, 200)


class ServersSampleAllExtensionJsonTest(ServersSampleJsonTest):
    all_extensions = True


class ServersSampleHideAddressesJsonTest(ServersSampleJsonTest):
    extension_name = '.'.join(('nova.api.openstack.compute.contrib',
                               'hide_server_addresses',
                               'Hide_server_addresses'))


class ServersSampleMultiStatusJsonTest(ServersSampleBase):
    extension_name = '.'.join(('nova.api.openstack.compute.contrib',
                               'server_list_multi_status',
                               'Server_list_multi_status'))

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers?status=active&status=error')
        subs = self._get_regexes()
        subs['id'] = uuid
        self._verify_response('servers-list-resp', subs, response, 200)


class ServersMetadataJsonTest(ServersSampleBase):
    def _create_and_set(self, subs):
        uuid = self._post_server()
        response = self._do_put('servers/%s/metadata' % uuid,
                                'server-metadata-all-req',
                                subs)
        self._verify_response('server-metadata-all-resp', subs, response, 200)
        return uuid

    def generalize_subs(self, subs, vanilla_regexes):
        subs['value'] = '(Foo|Bar) Value'
        return subs

    def test_metadata_put_all(self):
        # Test setting all metadata for a server.
        subs = {'value': 'Foo Value'}
        self._create_and_set(subs)

    def test_metadata_post_all(self):
        # Test updating all metadata for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        subs['value'] = 'Bar Value'
        response = self._do_post('servers/%s/metadata' % uuid,
                                 'server-metadata-all-req',
                                 subs)
        self._verify_response('server-metadata-all-resp', subs, response, 200)

    def test_metadata_get_all(self):
        # Test getting all metadata for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_get('servers/%s/metadata' % uuid)
        self._verify_response('server-metadata-all-resp', subs, response, 200)

    def test_metadata_put(self):
        # Test putting an individual metadata item for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        subs['value'] = 'Bar Value'
        response = self._do_put('servers/%s/metadata/foo' % uuid,
                                'server-metadata-req',
                                subs)
        self._verify_response('server-metadata-resp', subs, response, 200)

    def test_metadata_get(self):
        # Test getting an individual metadata item for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_get('servers/%s/metadata/foo' % uuid)
        self._verify_response('server-metadata-resp', subs, response, 200)

    def test_metadata_delete(self):
        # Test deleting an individual metadata item for a server.
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_delete('servers/%s/metadata/foo' % uuid)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, '')


class ServersIpsJsonTest(ServersSampleBase):
    def test_get(self):
        # Test getting a server's IP information.
        uuid = self._post_server()
        response = self._do_get('servers/%s/ips' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-ips-resp', subs, response, 200)

    def test_get_by_network(self):
        # Test getting a server's IP information by network id.
        uuid = self._post_server()
        response = self._do_get('servers/%s/ips/private' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-ips-network-resp', subs, response, 200)


class ExtensionsSampleJsonTest(ApiSampleTestBaseV2):
    all_extensions = True

    def test_extensions_get(self):
        response = self._do_get('extensions')
        subs = self._get_regexes()
        self._verify_response('extensions-get-resp', subs, response, 200)


class FlavorsSampleJsonTest(ApiSampleTestBaseV2):

    def test_flavors_get(self):
        response = self._do_get('flavors/1')
        subs = self._get_regexes()
        self._verify_response('flavor-get-resp', subs, response, 200)

    def test_flavors_list(self):
        response = self._do_get('flavors')
        subs = self._get_regexes()
        self._verify_response('flavors-list-resp', subs, response, 200)


class HostsSampleJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.hosts.Hosts"

    def test_host_startup(self):
        response = self._do_get('os-hosts/%s/startup' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-startup', subs, response, 200)

    def test_host_reboot(self):
        response = self._do_get('os-hosts/%s/reboot' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-reboot', subs, response, 200)

    def test_host_shutdown(self):
        response = self._do_get('os-hosts/%s/shutdown' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-shutdown', subs, response, 200)

    def test_host_maintenance(self):
        response = self._do_put('os-hosts/%s' % self.compute.host,
                                'host-put-maintenance-req', {})
        subs = self._get_regexes()
        self._verify_response('host-put-maintenance-resp', subs, response, 200)

    def test_host_get(self):
        response = self._do_get('os-hosts/%s' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-resp', subs, response, 200)

    def test_hosts_list(self):
        response = self._do_get('os-hosts')
        subs = self._get_regexes()
        self._verify_response('hosts-list-resp', subs, response, 200)


class FlavorsSampleAllExtensionJsonTest(FlavorsSampleJsonTest):
    all_extensions = True


class ImagesSampleJsonTest(ApiSampleTestBaseV2):
    def test_images_list(self):
        # Get api sample of images get list request.
        response = self._do_get('images')
        subs = self._get_regexes()
        self._verify_response('images-list-get-resp', subs, response, 200)

    def test_image_get(self):
        # Get api sample of one single image details request.
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s' % image_id)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        self._verify_response('image-get-resp', subs, response, 200)

    def test_images_details(self):
        # Get api sample of all images details request.
        response = self._do_get('images/detail')
        subs = self._get_regexes()
        self._verify_response('images-details-get-resp', subs, response, 200)

    def test_image_metadata_get(self):
        # Get api sample of an image metadata request.
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s/metadata' % image_id)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        self._verify_response('image-metadata-get-resp', subs, response, 200)

    def test_image_metadata_post(self):
        # Get api sample to update metadata of an image metadata request.
        image_id = fake.get_valid_image_id()
        response = self._do_post(
                'images/%s/metadata' % image_id,
                'image-metadata-post-req', {})
        subs = self._get_regexes()
        self._verify_response('image-metadata-post-resp', subs, response, 200)

    def test_image_metadata_put(self):
        # Get api sample of image metadata put request.
        image_id = fake.get_valid_image_id()
        response = self._do_put('images/%s/metadata' % image_id,
                                'image-metadata-put-req', {})
        subs = self._get_regexes()
        self._verify_response('image-metadata-put-resp', subs, response, 200)

    def test_image_meta_key_get(self):
        # Get api sample of an image metadata key request.
        image_id = fake.get_valid_image_id()
        key = "kernel_id"
        response = self._do_get('images/%s/metadata/%s' % (image_id, key))
        subs = self._get_regexes()
        self._verify_response('image-meta-key-get', subs, response, 200)

    def test_image_meta_key_put(self):
        # Get api sample of image metadata key put request.
        image_id = fake.get_valid_image_id()
        key = "auto_disk_config"
        response = self._do_put('images/%s/metadata/%s' % (image_id, key),
                                'image-meta-key-put-req', {})
        subs = self._get_regexes()
        self._verify_response('image-meta-key-put-resp', subs, response, 200)


class LimitsSampleJsonTest(ApiSampleTestBaseV2):
    def test_limits_get(self):
        response = self._do_get('limits')
        subs = self._get_regexes()
        self._verify_response('limit-get-resp', subs, response, 200)


class ServersActionsJsonTest(ServersSampleBase):
    def _test_server_action(self, uuid, action,
                            subs=None, resp_tpl=None, code=202):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-%s' % action.lower(),
                                 subs)
        if resp_tpl:
            subs.update(self._get_regexes())
            self._verify_response(resp_tpl, subs, response, code)
        else:
            self.assertEqual(response.status_code, code)
            self.assertEqual(response.content, "")

    def test_server_password(self):
        uuid = self._post_server()
        self._test_server_action(uuid, "changePassword",
                                 {"password": "foo"})

    def test_server_reboot_hard(self):
        uuid = self._post_server()
        self._test_server_action(uuid, "reboot",
                                 {"type": "HARD"})

    def test_server_reboot_soft(self):
        uuid = self._post_server()
        self._test_server_action(uuid, "reboot",
                                 {"type": "SOFT"})

    def test_server_rebuild(self):
        uuid = self._post_server()
        image = self.api.get_images()[0]['id']
        subs = {'host': self._get_host(),
                'uuid': image,
                'name': 'foobar',
                'pass': 'seekr3t',
                'ip': '1.2.3.4',
                'ip6': 'fe80::100',
                'hostid': '[a-f0-9]+',
                }
        self._test_server_action(uuid, 'rebuild', subs,
                                 'server-action-rebuild-resp')

    def test_server_resize(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server()
        self._test_server_action(uuid, "resize",
                                 {"id": 2,
                                  "host": self._get_host()})
        return uuid

    def test_server_revert_resize(self):
        uuid = self.test_server_resize()
        self._test_server_action(uuid, "revertResize")

    def test_server_confirm_resize(self):
        uuid = self.test_server_resize()
        self._test_server_action(uuid, "confirmResize", code=204)

    def test_server_create_image(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'createImage',
                                 {'name': 'foo-image',
                                  'meta_var': 'myvar',
                                  'meta_val': 'foobar'})


class ServersActionsAllJsonTest(ServersActionsJsonTest):
    all_extensions = True


class ServerStartStopJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
        ".server_start_stop.Server_start_stop"

    def _test_server_action(self, uuid, action):
        response = self._do_post('servers/%s/action' % uuid,
                                 'server_start_stop',
                                 {'action': action})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_server_start(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop')
        self._test_server_action(uuid, 'os-start')

    def test_server_stop(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop')


class UserDataJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.user_data.User_data"

    def test_user_data_post(self):
        user_data_contents = '#!/bin/bash\n/bin/su\necho "I am in you!"\n'
        user_data = base64.b64encode(user_data_contents)
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'user_data': user_data
            }
        response = self._do_post('servers', 'userdata-post-req', subs)

        subs.update(self._get_regexes())
        self._verify_response('userdata-post-resp', subs, response, 202)


class FlavorsExtraDataJsonTest(ApiSampleTestBaseV2):
    extension_name = ('nova.api.openstack.compute.contrib.flavorextradata.'
                      'Flavorextradata')

    def _get_flags(self):
        f = super(FlavorsExtraDataJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # Flavorextradata extension also needs Flavormanage to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavormanage.Flavormanage')
        return f

    def test_flavors_extra_data_get(self):
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        subs = {
            'flavor_id': flavor_id,
            'flavor_name': 'm1.tiny'
        }
        subs.update(self._get_regexes())
        self._verify_response('flavors-extra-data-get-resp',
                              subs, response, 200)

    def test_flavors_extra_data_list(self):
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        self._verify_response('flavors-extra-data-list-resp',
                              subs, response, 200)

    def test_flavors_extra_data_create(self):
        subs = {
            'flavor_id': 666,
            'flavor_name': 'flavortest'
        }
        response = self._do_post('flavors',
                                 'flavors-extra-data-post-req',
                                 subs)
        subs.update(self._get_regexes())
        self._verify_response('flavors-extra-data-post-resp',
                              subs, response, 200)


class FlavorRxtxJsonTest(ApiSampleTestBaseV2):
    extension_name = ('nova.api.openstack.compute.contrib.flavor_rxtx.'
                      'Flavor_rxtx')

    def _get_flags(self):
        f = super(FlavorRxtxJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # FlavorRxtx extension also needs Flavormanage to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavormanage.Flavormanage')
        return f

    def test_flavor_rxtx_get(self):
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        subs = {
            'flavor_id': flavor_id,
            'flavor_name': 'm1.tiny'
        }
        subs.update(self._get_regexes())
        self._verify_response('flavor-rxtx-get-resp', subs, response, 200)

    def test_flavors_rxtx_list(self):
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        self._verify_response('flavor-rxtx-list-resp', subs, response, 200)

    def test_flavors_rxtx_create(self):
        subs = {
            'flavor_id': 100,
            'flavor_name': 'flavortest'
        }
        response = self._do_post('flavors',
                                 'flavor-rxtx-post-req',
                                 subs)
        subs.update(self._get_regexes())
        self._verify_response('flavor-rxtx-post-resp', subs, response, 200)


class FlavorSwapJsonTest(ApiSampleTestBaseV2):
    extension_name = ('nova.api.openstack.compute.contrib.flavor_swap.'
                      'Flavor_swap')

    def _get_flags(self):
        f = super(FlavorSwapJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # FlavorSwap extension also needs Flavormanage to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavormanage.Flavormanage')
        return f

    def test_flavor_swap_get(self):
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        subs = {
            'flavor_id': flavor_id,
            'flavor_name': 'm1.tiny'
        }
        subs.update(self._get_regexes())
        self._verify_response('flavor-swap-get-resp', subs, response, 200)

    def test_flavor_swap_list(self):
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        self._verify_response('flavor-swap-list-resp', subs, response, 200)

    def test_flavor_swap_create(self):
        subs = {
            'flavor_id': 100,
            'flavor_name': 'flavortest'
        }
        response = self._do_post('flavors',
                                 'flavor-swap-post-req',
                                 subs)
        subs.update(self._get_regexes())
        self._verify_response('flavor-swap-post-resp', subs, response, 200)


class SecurityGroupsSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                     ".security_groups.Security_groups"

    def _get_create_subs(self):
        return {
                'group_name': 'test',
                "description": "description",
        }

    def _create_security_group(self):
        subs = self._get_create_subs()
        return self._do_post('os-security-groups',
                             'security-group-post-req', subs)

    def _add_group(self, uuid):
        subs = {
                'group_name': 'test'
        }
        return self._do_post('servers/%s/action' % uuid,
                             'security-group-add-post-req', subs)

    def test_security_group_create(self):
        response = self._create_security_group()
        subs = self._get_create_subs()
        self._verify_response('security-groups-create-resp', subs,
                              response, 200)

    def test_security_groups_list(self):
        # Get api sample of security groups get list request.
        response = self._do_get('os-security-groups')
        subs = self._get_regexes()
        self._verify_response('security-groups-list-get-resp',
                              subs, response, 200)

    def test_security_groups_get(self):
        # Get api sample of security groups get request.
        security_group_id = '1'
        response = self._do_get('os-security-groups/%s' % security_group_id)
        subs = self._get_regexes()
        self._verify_response('security-groups-get-resp', subs, response, 200)

    def test_security_groups_list_server(self):
        # Get api sample of security groups for a specific server.
        uuid = self._post_server()
        response = self._do_get('servers/%s/os-security-groups' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-security-groups-list-resp',
                              subs, response, 200)

    def test_security_groups_add(self):
        self._create_security_group()
        uuid = self._post_server()
        response = self._add_group(uuid)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_security_groups_remove(self):
        self._create_security_group()
        uuid = self._post_server()
        self._add_group(uuid)
        subs = {
                'group_name': 'test'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'security-group-remove-post-req', subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class SecurityGroupDefaultRulesSampleJsonTest(ServersSampleBase):
    extension_name = ('nova.api.openstack.compute.contrib'
                      '.security_group_default_rules'
                      '.Security_group_default_rules')

    def test_security_group_default_rules_create(self):
        response = self._do_post('os-security-group-default-rules',
                                 'security-group-default-rules-create-req',
                                 {})
        self._verify_response('security-group-default-rules-create-resp',
                              {}, response, 200)

    def test_security_group_default_rules_list(self):
        self.test_security_group_default_rules_create()
        response = self._do_get('os-security-group-default-rules')
        self._verify_response('security-group-default-rules-list-resp',
                              {}, response, 200)

    def test_security_group_default_rules_show(self):
        self.test_security_group_default_rules_create()
        rule_id = '1'
        response = self._do_get('os-security-group-default-rules/%s' % rule_id)
        self._verify_response('security-group-default-rules-show-resp',
                              {}, response, 200)


class SchedulerHintsJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.scheduler_hints."
                     "Scheduler_hints")

    def test_scheduler_hints_post(self):
        # Get api sample of scheduler hint post request.
        hints = {'image_id': fake.get_valid_image_id(),
                 'image_near': str(uuid_lib.uuid4())
        }
        response = self._do_post('servers', 'scheduler-hints-post-req',
                                 hints)
        subs = self._get_regexes()
        self._verify_response('scheduler-hints-post-resp', subs, response, 202)


class ConsoleOutputSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                                     ".console_output.Console_output"

    def test_get_console_output(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'console-output-post-req',
                                {'action': 'os-getConsoleOutput'})
        subs = self._get_regexes()
        self._verify_response('console-output-post-resp', subs, response, 200)


class ExtendedServerAttributesJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                     ".extended_server_attributes" + \
                     ".Extended_server_attributes"

    def test_show(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['instance_name'] = 'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()

        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['instance_name'] = 'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class FloatingIpsJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib." \
        "floating_ips.Floating_ips"

    def setUp(self):
        super(FloatingIpsJsonTest, self).setUp()
        pool = CONF.default_floating_pool
        interface = CONF.public_interface

        self.ip_pool = [
            {
                'address': "10.10.10.1",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.2",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.3",
                'pool': pool,
                'interface': interface
                },
            ]
        self.compute.db.floating_ip_bulk_create(
            context.get_admin_context(), self.ip_pool)

    def tearDown(self):
        self.compute.db.floating_ip_bulk_destroy(
            context.get_admin_context(), self.ip_pool)
        super(FloatingIpsJsonTest, self).tearDown()

    def test_floating_ips_list_empty(self):
        response = self._do_get('os-floating-ips')

        subs = self._get_regexes()
        self._verify_response('floating-ips-list-empty-resp',
                              subs, response, 200)

    def test_floating_ips_list(self):
        self._do_post('os-floating-ips',
                      'floating-ips-create-nopool-req',
                      {})
        self._do_post('os-floating-ips',
                      'floating-ips-create-nopool-req',
                      {})

        response = self._do_get('os-floating-ips')
        subs = self._get_regexes()
        self._verify_response('floating-ips-list-resp',
                              subs, response, 200)

    def test_floating_ips_create_nopool(self):
        response = self._do_post('os-floating-ips',
                                 'floating-ips-create-nopool-req',
                                 {})
        subs = self._get_regexes()
        self._verify_response('floating-ips-create-resp',
                              subs, response, 200)

    def test_floating_ips_create(self):
        response = self._do_post('os-floating-ips',
                                 'floating-ips-create-req',
                                 {"pool": CONF.default_floating_pool})
        subs = self._get_regexes()
        self._verify_response('floating-ips-create-resp', subs, response, 200)

    def test_floating_ips_get(self):
        self.test_floating_ips_create()
        # NOTE(sdague): the first floating ip will always have 1 as an id,
        # but it would be better if we could get this from the create
        response = self._do_get('os-floating-ips/%d' % 1)
        subs = self._get_regexes()
        self._verify_response('floating-ips-create-resp', subs, response, 200)

    def test_floating_ips_delete(self):
        self.test_floating_ips_create()
        response = self._do_delete('os-floating-ips/%d' % 1)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")


class ExtendedFloatingIpsJsonTest(FloatingIpsJsonTest):
    extends_name = ("nova.api.openstack.compute.contrib."
                         "floating_ips.Floating_ips")
    extension_name = ("nova.api.openstack.compute.contrib."
                         "extended_floating_ips.Extended_floating_ips")


class FloatingIpsBulkJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib." \
        "floating_ips_bulk.Floating_ips_bulk"

    def setUp(self):
        super(FloatingIpsBulkJsonTest, self).setUp()
        pool = CONF.default_floating_pool
        interface = CONF.public_interface

        self.ip_pool = [
            {
                'address': "10.10.10.1",
                'pool': pool,
                'interface': interface,
                'host': None
                },
            {
                'address': "10.10.10.2",
                'pool': pool,
                'interface': interface,
                'host': None
                },
            {
                'address': "10.10.10.3",
                'pool': pool,
                'interface': interface,
                'host': "testHost"
                },
            ]
        self.compute.db.floating_ip_bulk_create(
            context.get_admin_context(), self.ip_pool)

    def tearDown(self):
        self.compute.db.floating_ip_bulk_destroy(
            context.get_admin_context(), self.ip_pool)
        super(FloatingIpsBulkJsonTest, self).tearDown()

    def test_floating_ips_bulk_list(self):
        response = self._do_get('os-floating-ips-bulk')
        subs = self._get_regexes()
        self._verify_response('floating-ips-bulk-list-resp',
                              subs, response, 200)

    def test_floating_ips_bulk_list_by_host(self):
        response = self._do_get('os-floating-ips-bulk/testHost')
        subs = self._get_regexes()
        self._verify_response('floating-ips-bulk-list-by-host-resp',
                              subs, response, 200)

    def test_floating_ips_bulk_create(self):
        response = self._do_post('os-floating-ips-bulk',
                                 'floating-ips-bulk-create-req',
                                 {"ip_range": "192.168.1.0/24",
                                  "pool": CONF.default_floating_pool,
                                  "interface": CONF.public_interface})
        subs = self._get_regexes()
        self._verify_response('floating-ips-bulk-create-resp', subs,
                              response, 200)

    def test_floating_ips_bulk_delete(self):
        response = self._do_put('os-floating-ips-bulk/delete',
                                'floating-ips-bulk-delete-req',
                                {"ip_range": "192.168.1.0/24"})
        subs = self._get_regexes()
        self._verify_response('floating-ips-bulk-delete-resp', subs,
                              response, 200)


class KeyPairsSampleJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.keypairs.Keypairs"

    def generalize_subs(self, subs, vanilla_regexes):
        subs['keypair_name'] = 'keypair-[0-9a-f-]+'
        return subs

    def test_keypairs_post(self, public_key=None):
        """Get api sample of key pairs post request."""
        key_name = 'keypair-' + str(uuid_lib.uuid4())
        response = self._do_post('os-keypairs', 'keypairs-post-req',
                                 {'keypair_name': key_name})
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-post-resp', subs, response, 200)
        # NOTE(maurosr): return the key_name is necessary cause the
        # verification returns the label of the last compared information in
        # the response, not necessarily the key name.
        return key_name

    def test_keypairs_import_key_post(self):
        # Get api sample of key pairs post to import user's key.
        key_name = 'keypair-' + str(uuid_lib.uuid4())
        subs = {
            'keypair_name': key_name,
            'public_key': "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDx8nkQv/zgGg"
                          "B4rMYmIf+6A4l6Rr+o/6lHBQdW5aYd44bd8JttDCE/F/pNRr0l"
                          "RE+PiqSPO8nDPHw0010JeMH9gYgnnFlyY3/OcJ02RhIPyyxYpv"
                          "9FhY+2YiUkpwFOcLImyrxEsYXpD/0d3ac30bNH6Sw9JD9UZHYc"
                          "pSxsIbECHw== Generated-by-Nova"
        }
        response = self._do_post('os-keypairs', 'keypairs-import-post-req',
                                 subs)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-import-post-resp', subs, response, 200)

    def test_keypairs_list(self):
        # Get api sample of key pairs list request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs')
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-list-resp', subs, response, 200)

    def test_keypairs_get(self):
        # Get api sample of key pairs get request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs/%s' % key_name)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-get-resp', subs, response, 200)


class RescueJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                     ".rescue.Rescue")

    def _rescue(self, uuid):
        req_subs = {
            'password': 'MySecretPass'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-rescue-req', req_subs)
        self._verify_response('server-rescue', req_subs, response, 200)

    def _unrescue(self, uuid):
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-unrescue-req', {})
        self.assertEqual(response.status_code, 202)

    def test_server_rescue(self):
        uuid = self._post_server()

        self._rescue(uuid)

        # Do a server get to make sure that the 'RESCUE' state is set
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'RESCUE'

        self._verify_response('server-get-resp-rescue', subs, response, 200)

    def test_server_unrescue(self):
        uuid = self._post_server()

        self._rescue(uuid)
        self._unrescue(uuid)

        # Do a server get to make sure that the 'ACTIVE' state is back
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'ACTIVE'

        self._verify_response('server-get-resp-unrescue', subs, response, 200)


class ExtendedRescueWithImageJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_rescue_with_image.Extended_rescue_with_image")

    def _get_flags(self):
        f = super(ExtendedRescueWithImageJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # ExtendedRescueWithImage extension also needs Rescue to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.rescue.Rescue')
        return f

    def _rescue(self, uuid):
        req_subs = {
            'password': 'MySecretPass',
            'rescue_image_ref': fake.get_valid_image_id()
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-rescue-req', req_subs)
        self._verify_response('server-rescue', req_subs, response, 200)

    def test_server_rescue(self):
        uuid = self._post_server()

        self._rescue(uuid)

        # Do a server get to make sure that the 'RESCUE' state is set
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'RESCUE'

        self._verify_response('server-get-resp-rescue', subs, response, 200)


class ShelveJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib.shelve.Shelve"

    def setUp(self):
        super(ShelveJsonTest, self).setUp()
        # Don't offload instance, so we can test the offload call.
        CONF.set_override('shelved_offload_time', -1)

    def _test_server_action(self, uuid, template, action):
        response = self._do_post('servers/%s/action' % uuid,
                                 template, {'action': action})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_shelve(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')

    def test_shelve_offload(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-shelve-offload', 'shelveOffload')

    def test_unshelve(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-unshelve', 'unshelve')


class VirtualInterfacesJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                     ".virtual_interfaces.Virtual_interfaces")

    def test_vifs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s/os-virtual-interfaces' % uuid)

        subs = self._get_regexes()
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'

        self._verify_response('vifs-list-resp', subs, response, 200)


class CloudPipeSampleJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.cloudpipe.Cloudpipe"

    def setUp(self):
        super(CloudPipeSampleJsonTest, self).setUp()

        def get_user_data(self, project_id):
            """Stub method to generate user data for cloudpipe tests."""
            return "VVNFUiBEQVRB\n"

        def network_api_get(self, context, network_uuid):
            """Stub to get a valid network and its information."""
            return {'vpn_public_address': '127.0.0.1',
                    'vpn_public_port': 22}

        self.stubs.Set(pipelib.CloudPipe, 'get_encoded_zip', get_user_data)
        self.stubs.Set(network_api.API, "get",
                       network_api_get)

    def generalize_subs(self, subs, vanilla_regexes):
        subs['project_id'] = 'cloudpipe-[0-9a-f-]+'
        return subs

    def test_cloud_pipe_create(self):
        # Get api samples of cloud pipe extension creation.
        self.flags(vpn_image_id=fake.get_valid_image_id())
        project = {'project_id': 'cloudpipe-' + str(uuid_lib.uuid4())}
        response = self._do_post('os-cloudpipe', 'cloud-pipe-create-req',
                                 project)
        subs = self._get_regexes()
        subs.update(project)
        subs['image_id'] = CONF.vpn_image_id
        self._verify_response('cloud-pipe-create-resp', subs, response, 200)
        return project

    def test_cloud_pipe_list(self):
        # Get api samples of cloud pipe extension get request.
        project = self.test_cloud_pipe_create()
        response = self._do_get('os-cloudpipe')
        subs = self._get_regexes()
        subs.update(project)
        subs['image_id'] = CONF.vpn_image_id
        self._verify_response('cloud-pipe-get-resp', subs, response, 200)


class CloudPipeUpdateJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".cloudpipe_update.Cloudpipe_update")

    def _get_flags(self):
        f = super(CloudPipeUpdateJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # Cloudpipe_update also needs cloudpipe to be loaded
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.cloudpipe.Cloudpipe')
        return f

    def test_cloud_pipe_update(self):
        subs = {'vpn_ip': '192.168.1.1',
                'vpn_port': 2000}
        response = self._do_put('os-cloudpipe/configure-project',
                                'cloud-pipe-update-req',
                                subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")


class AgentsJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.agents.Agents"

    def _get_flags(self):
        f = super(AgentsJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        return f

    def setUp(self):
        super(AgentsJsonTest, self).setUp()

        fake_agents_list = [{'url': 'http://example.com/path/to/resource',
                             'hypervisor': 'hypervisor',
                             'architecture': 'x86',
                             'os': 'os',
                             'version': '8.0',
                             'md5hash': 'add6bb58e139be103324d04d82d8f545',
                             'id': 1}]

        def fake_agent_build_create(context, values):
            values['id'] = 1
            agent_build_ref = models.AgentBuild()
            agent_build_ref.update(values)
            return agent_build_ref

        def fake_agent_build_get_all(context, hypervisor):
            agent_build_all = []
            for agent in fake_agents_list:
                if hypervisor and hypervisor != agent['hypervisor']:
                    continue
                agent_build_ref = models.AgentBuild()
                agent_build_ref.update(agent)
                agent_build_all.append(agent_build_ref)
            return agent_build_all

        def fake_agent_build_update(context, agent_build_id, values):
            pass

        def fake_agent_build_destroy(context, agent_update_id):
            pass

        self.stubs.Set(db, "agent_build_create",
                       fake_agent_build_create)
        self.stubs.Set(db, "agent_build_get_all",
                       fake_agent_build_get_all)
        self.stubs.Set(db, "agent_build_update",
                       fake_agent_build_update)
        self.stubs.Set(db, "agent_build_destroy",
                       fake_agent_build_destroy)

    def test_agent_create(self):
        # Creates a new agent build.
        project = {'url': 'http://example.com/path/to/resource',
                'hypervisor': 'hypervisor',
                'architecture': 'x86',
                'os': 'os',
                'version': '8.0',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'
                }
        response = self._do_post('os-agents', 'agent-post-req',
                                 project)
        project['agent_id'] = 1
        self._verify_response('agent-post-resp', project, response, 200)
        return project

    def test_agent_list(self):
        # Return a list of all agent builds.
        response = self._do_get('os-agents')
        project = {'url': 'http://example.com/path/to/resource',
                'hypervisor': 'hypervisor',
                'architecture': 'x86',
                'os': 'os',
                'version': '8.0',
                'md5hash': 'add6bb58e139be103324d04d82d8f545',
                'agent_id': 1
                }
        self._verify_response('agents-get-resp', project, response, 200)

    def test_agent_update(self):
        # Update an existing agent build.
        agent_id = 1
        subs = {'version': '7.0',
                'url': 'http://example.com/path/to/resource',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}
        response = self._do_put('os-agents/%s' % agent_id,
                                'agent-update-put-req', subs)
        subs['agent_id'] = 1
        self._verify_response('agent-update-put-resp', subs, response, 200)

    def test_agent_delete(self):
        # Deletes an existing agent build.
        agent_id = 1
        response = self._do_delete('os-agents/%s' % agent_id)
        self.assertEqual(response.status_code, 200)


class FixedIpJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.fixed_ips.Fixed_ips"

    def _get_flags(self):
        f = super(FixedIpJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        return f

    def setUp(self):
        super(FixedIpJsonTest, self).setUp()

        instance = dict(test_utils.get_test_instance(),
                        hostname='openstack', host='host')
        fake_fixed_ips = [{'id': 1,
                   'address': '192.168.1.1',
                   'network_id': 1,
                   'virtual_interface_id': 1,
                   'instance_uuid': '1',
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'created_at': None,
                   'deleted_at': None,
                   'updated_at': None,
                   'deleted': None,
                   'instance': instance,
                   'network': test_network.fake_network,
                   'host': None},
                  {'id': 2,
                   'address': '192.168.1.2',
                   'network_id': 1,
                   'virtual_interface_id': 2,
                   'instance_uuid': '2',
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'created_at': None,
                   'deleted_at': None,
                   'updated_at': None,
                   'deleted': None,
                   'instance': instance,
                   'network': test_network.fake_network,
                   'host': None},
                  ]

        def fake_fixed_ip_get_by_address(context, address,
                                         columns_to_join=None):
            for fixed_ip in fake_fixed_ips:
                if fixed_ip['address'] == address:
                    return fixed_ip
            raise exception.FixedIpNotFoundForAddress(address=address)

        def fake_fixed_ip_update(context, address, values):
            fixed_ip = fake_fixed_ip_get_by_address(context, address)
            if fixed_ip is None:
                raise exception.FixedIpNotFoundForAddress(address=address)
            else:
                for key in values:
                    fixed_ip[key] = values[key]

        self.stubs.Set(db, "fixed_ip_get_by_address",
                       fake_fixed_ip_get_by_address)
        self.stubs.Set(db, "fixed_ip_update", fake_fixed_ip_update)

    def test_fixed_ip_reserve(self):
        # Reserve a Fixed IP.
        project = {'reserve': None}
        response = self._do_post('os-fixed-ips/192.168.1.1/action',
                                 'fixedip-post-req',
                                 project)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_get_fixed_ip(self):
        # Return data about the given fixed ip.
        response = self._do_get('os-fixed-ips/192.168.1.1')
        project = {'cidr': '192.168.1.0/24',
                   'hostname': 'openstack',
                   'host': 'host',
                   'address': '192.168.1.1'}
        self._verify_response('fixedips-get-resp', project, response, 200)


class AggregatesSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                                     ".aggregates.Aggregates"
    create_subs = {
            "aggregate_id": '(?P<id>\d+)'
    }

    def _create_aggregate(self):
        return self._do_post('os-aggregates', 'aggregate-post-req',
                             self.create_subs)

    def test_aggregate_create(self):
        response = self._create_aggregate()
        subs = self.create_subs
        subs.update(self._get_regexes())
        return self._verify_response('aggregate-post-resp',
                                     subs, response, 200)

    def test_list_aggregates(self):
        self._create_aggregate()
        response = self._do_get('os-aggregates')
        subs = self._get_regexes()
        self._verify_response('aggregates-list-get-resp', subs, response, 200)

    def test_aggregate_get(self):
        self._create_aggregate()
        response = self._do_get('os-aggregates/%s' % 1)
        subs = self._get_regexes()
        self._verify_response('aggregates-get-resp', subs, response, 200)

    def test_add_metadata(self):
        self._create_aggregate()
        response = self._do_post('os-aggregates/%s/action' % 1,
                                 'aggregate-metadata-post-req',
                                 {'action': 'set_metadata'})
        subs = self._get_regexes()
        self._verify_response('aggregates-metadata-post-resp', subs,
                              response, 200)

    def test_add_host(self):
        self._create_aggregate()
        subs = {
            "host_name": self.compute.host,
        }
        response = self._do_post('os-aggregates/%s/action' % 1,
                                 'aggregate-add-host-post-req', subs)
        subs.update(self._get_regexes())
        self._verify_response('aggregates-add-host-post-resp', subs,
                              response, 200)

    def test_remove_host(self):
        self.test_add_host()
        subs = {
            "host_name": self.compute.host,
        }
        response = self._do_post('os-aggregates/1/action',
                                 'aggregate-remove-host-post-req', subs)
        subs.update(self._get_regexes())
        self._verify_response('aggregates-remove-host-post-resp',
                              subs, response, 200)

    def test_update_aggregate(self):
        self._create_aggregate()
        response = self._do_put('os-aggregates/%s' % 1,
                                  'aggregate-update-post-req', {})
        subs = self._get_regexes()
        self._verify_response('aggregate-update-post-resp',
                              subs, response, 200)


class CertificatesSamplesJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.certificates."
                      "Certificates")

    def test_create_certificates(self):
        response = self._do_post('os-certificates',
                                 'certificate-create-req', {})
        subs = self._get_regexes()
        self._verify_response('certificate-create-resp', subs, response, 200)

    def test_get_root_certificate(self):
        response = self._do_get('os-certificates/root')
        subs = self._get_regexes()
        self._verify_response('certificate-get-root-resp', subs, response, 200)


class UsedLimitsSamplesJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.used_limits."
                      "Used_limits")

    def test_get_used_limits(self):
        # Get api sample to used limits.
        response = self._do_get('limits')
        subs = self._get_regexes()
        self._verify_response('usedlimits-get-resp', subs, response, 200)


class UsedLimitsForAdminSamplesJsonTest(ApiSampleTestBaseV2):
    extends_name = ("nova.api.openstack.compute.contrib.used_limits."
                    "Used_limits")
    extension_name = (
        "nova.api.openstack.compute.contrib.used_limits_for_admin."
        "Used_limits_for_admin")

    def test_get_used_limits_for_admin(self):
        tenant_id = 'openstack'
        response = self._do_get('limits?tenant_id=%s' % tenant_id)
        subs = self._get_regexes()
        return self._verify_response('usedlimitsforadmin-get-resp', subs,
                                     response, 200)


class MultipleCreateJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.multiple_create."
                      "Multiple_create")

    def test_multiple_create(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-post-req', subs)
        subs.update(self._get_regexes())
        self._verify_response('multiple-create-post-resp', subs, response, 202)

    def test_multiple_create_without_reservation_id(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-no-resv-post-req',
                                  subs)
        subs.update(self._get_regexes())
        self._verify_response('multiple-create-no-resv-post-resp', subs,
                              response, 202)


class ServicesJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.services.Services"

    def setUp(self):
        super(ServicesJsonTest, self).setUp()
        self.stubs.Set(db, "service_get_all",
                       test_services.fake_db_api_service_get_all)
        self.stubs.Set(timeutils, "utcnow", test_services.fake_utcnow)
        self.stubs.Set(timeutils, "utcnow_ts", test_services.fake_utcnow_ts)
        self.stubs.Set(db, "service_get_by_args",
                       test_services.fake_service_get_by_host_binary)
        self.stubs.Set(db, "service_update",
                       test_services.fake_service_update)

    def tearDown(self):
        super(ServicesJsonTest, self).tearDown()
        timeutils.clear_time_override()

    def fake_load(self, service_name):
        return service_name == 'os-extended-services'

    def test_services_list(self):
        """Return a list of all agent builds."""
        response = self._do_get('os-services')
        subs = {'binary': 'nova-compute',
                'host': 'host1',
                'zone': 'nova',
                'status': 'disabled',
                'state': 'up'}
        subs.update(self._get_regexes())
        self._verify_response('services-list-get-resp', subs, response, 200)

    def test_service_enable(self):
        """Enable an existing agent build."""
        subs = {"host": "host1",
                'binary': 'nova-compute'}
        response = self._do_put('os-services/enable',
                                'service-enable-put-req', subs)
        subs = {"host": "host1",
                "binary": "nova-compute"}
        self._verify_response('service-enable-put-resp', subs, response, 200)

    def test_service_disable(self):
        """Disable an existing agent build."""
        subs = {"host": "host1",
                'binary': 'nova-compute'}
        response = self._do_put('os-services/disable',
                                'service-disable-put-req', subs)
        subs = {"host": "host1",
                "binary": "nova-compute"}
        self._verify_response('service-disable-put-resp', subs, response, 200)

    def test_service_detail(self):
        """Return a list of all running services with the disable reason
        information if that exists.
        """
        self.stubs.Set(extensions.ExtensionManager, "is_loaded",
                self.fake_load)
        response = self._do_get('os-services')
        self.assertEqual(response.status_code, 200)
        subs = {'binary': 'nova-compute',
                'host': 'host1',
                'zone': 'nova',
                'status': 'disabled',
                'state': 'up'}
        subs.update(self._get_regexes())
        self._verify_response('services-get-resp',
                                     subs, response, 200)

    def test_service_disable_log_reason(self):
        """Disable an existing service and log the reason."""
        self.stubs.Set(extensions.ExtensionManager, "is_loaded",
                self.fake_load)
        subs = {"host": "host1",
                'binary': 'nova-compute',
                'disabled_reason': 'test2'}
        response = self._do_put('os-services/disable-log-reason',
                                'service-disable-log-put-req', subs)
        return self._verify_response('service-disable-log-put-resp',
                                     subs, response, 200)


class ExtendedServicesJsonTest(ApiSampleTestBaseV2):
    """This extension is extending the functionalities of the
    Services extension so the funcionalities introduced by this extension
    are tested in the ServicesJsonTest and ServicesXmlTest classes.
    """

    extension_name = ("nova.api.openstack.compute.contrib."
                      "extended_services.Extended_services")


@mock.patch.object(db, 'service_get_all',
                   side_effect=test_services.fake_db_api_service_get_all)
@mock.patch.object(db, 'service_get_by_args',
                   side_effect=test_services.fake_service_get_by_host_binary)
class ExtendedServicesDeleteJsonTest(ApiSampleTestBaseV2):
    extends_name = ("nova.api.openstack.compute.contrib.services.Services")
    extension_name = ("nova.api.openstack.compute.contrib."
                      "extended_services_delete.Extended_services_delete")

    def setUp(self):
        super(ExtendedServicesDeleteJsonTest, self).setUp()
        timeutils.set_time_override(test_services.fake_utcnow())

    def tearDown(self):
        super(ExtendedServicesDeleteJsonTest, self).tearDown()
        timeutils.clear_time_override()

    def test_service_detail(self, *mocks):
        """Return a list of all running services with the disable reason
        information if that exists.
        """
        response = self._do_get('os-services')
        self.assertEqual(response.status_code, 200)
        subs = {'id': 1,
                'binary': 'nova-compute',
                'host': 'host1',
                'zone': 'nova',
                'status': 'disabled',
                'state': 'up'}
        subs.update(self._get_regexes())
        return self._verify_response('services-get-resp',
                                     subs, response, 200)

    def test_service_delete(self, *mocks):
        response = self._do_delete('os-services/1')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, "")


class SimpleTenantUsageSampleJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.simple_tenant_usage."
                      "Simple_tenant_usage")

    def setUp(self):
        """setUp method for simple tenant usage."""
        super(SimpleTenantUsageSampleJsonTest, self).setUp()

        started = timeutils.utcnow()
        now = started + datetime.timedelta(hours=1)

        timeutils.set_time_override(started)
        self._post_server()
        timeutils.set_time_override(now)

        self.query = {
            'start': str(started),
            'end': str(now)
        }

    def tearDown(self):
        """tearDown method for simple tenant usage."""
        super(SimpleTenantUsageSampleJsonTest, self).tearDown()
        timeutils.clear_time_override()

    def test_get_tenants_usage(self):
        # Get api sample to get all tenants usage request.
        response = self._do_get('os-simple-tenant-usage?%s' % (
                                                urllib.urlencode(self.query)))
        subs = self._get_regexes()
        self._verify_response('simple-tenant-usage-get', subs, response, 200)

    def test_get_tenant_usage_details(self):
        # Get api sample to get specific tenant usage request.
        tenant_id = 'openstack'
        response = self._do_get('os-simple-tenant-usage/%s?%s' % (tenant_id,
                                                urllib.urlencode(self.query)))
        subs = self._get_regexes()
        self._verify_response('simple-tenant-usage-get-specific', subs,
                              response, 200)


class ServerDiagnosticsSamplesJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.server_diagnostics."
                      "Server_diagnostics")

    def test_server_diagnostics_get(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s/diagnostics' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-diagnostics-get-resp', subs,
                              response, 200)


class AvailabilityZoneJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.availability_zone."
                      "Availability_zone")

    def test_create_availability_zone(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            "availability_zone": "nova"
        }
        response = self._do_post('servers', 'availability-zone-post-req', subs)
        subs.update(self._get_regexes())
        self._verify_response('availability-zone-post-resp', subs,
                              response, 202)


class AdminActionsSamplesJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.admin_actions."
                      "Admin_actions")

    def setUp(self):
        """setUp Method for AdminActions api samples extension

        This method creates the server that will be used in each tests
        """
        super(AdminActionsSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()

    def test_post_pause(self):
        # Get api samples to pause server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-pause', {})
        self.assertEqual(response.status_code, 202)

    def test_post_unpause(self):
        # Get api samples to unpause server request.
        self.test_post_pause()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-unpause', {})
        self.assertEqual(response.status_code, 202)

    def test_post_suspend(self):
        # Get api samples to suspend server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-suspend', {})
        self.assertEqual(response.status_code, 202)

    def test_post_resume(self):
        # Get api samples to server resume request.
        self.test_post_suspend()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-resume', {})
        self.assertEqual(response.status_code, 202)

    @mock.patch('nova.conductor.manager.ComputeTaskManager._cold_migrate')
    def test_post_migrate(self, mock_cold_migrate):
        # Get api samples to migrate server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-migrate', {})
        self.assertEqual(response.status_code, 202)

    def test_post_reset_network(self):
        # Get api samples to reset server network request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-reset-network', {})
        self.assertEqual(response.status_code, 202)

    def test_post_inject_network_info(self):
        # Get api samples to inject network info request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-inject-network-info', {})
        self.assertEqual(response.status_code, 202)

    def test_post_lock_server(self):
        # Get api samples to lock server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-lock-server', {})
        self.assertEqual(response.status_code, 202)

    def test_post_unlock_server(self):
        # Get api samples to unlock server request.
        self.test_post_lock_server()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-unlock-server', {})
        self.assertEqual(response.status_code, 202)

    def test_post_backup_server(self):
        # Get api samples to backup server request.
        def image_details(self, context, **kwargs):
            """This stub is specifically used on the backup action."""
            # NOTE(maurosr): I've added this simple stub cause backup action
            # was trapped in infinite loop during fetch image phase since the
            # fake Image Service always returns the same set of images
            return []

        self.stubs.Set(fake._FakeImageService, 'detail', image_details)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-backup-server', {})
        self.assertEqual(response.status_code, 202)

    def test_post_live_migrate_server(self):
        # Get api samples to server live migrate request.
        def fake_live_migrate(_self, context, instance, scheduler_hint,
                              block_migration, disk_over_commit):
            self.assertEqual(self.uuid, instance["uuid"])
            host = scheduler_hint["host"]
            self.assertEqual(self.compute.host, host)

        self.stubs.Set(conductor_manager.ComputeTaskManager,
                       '_live_migrate',
                       fake_live_migrate)

        def fake_get_compute(context, host):
            service = dict(host=host,
                           binary='nova-compute',
                           topic='compute',
                           report_count=1,
                           updated_at='foo',
                           hypervisor_type='bar',
                           hypervisor_version=
                                utils.convert_version_to_int('1.0'),
                           disabled=False)
            return {'compute_node': [service]}
        self.stubs.Set(db, "service_get_by_compute_host", fake_get_compute)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-live-migrate',
                                 {'hostname': self.compute.host})
        self.assertEqual(response.status_code, 202)

    def test_post_reset_state(self):
        # get api samples to server reset state request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-reset-server-state', {})
        self.assertEqual(response.status_code, 202)


class ConsolesSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                     ".consoles.Consoles")

    def setUp(self):
        super(ConsolesSampleJsonTests, self).setUp()
        self.flags(vnc_enabled=True)
        self.flags(enabled=True, group='spice')
        self.flags(enabled=True, group='rdp')
        self.flags(enabled=True, group='serial_console')

    def test_get_vnc_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-vnc-console-post-req',
                                {'action': 'os-getVNCConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((https?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-vnc-console-post-resp', subs, response, 200)

    def test_get_spice_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-spice-console-post-req',
                                {'action': 'os-getSPICEConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((https?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-spice-console-post-resp', subs,
                              response, 200)

    def test_get_rdp_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-rdp-console-post-req',
                                {'action': 'os-getRDPConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((https?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-rdp-console-post-resp', subs,
                              response, 200)

    def test_get_serial_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-serial-console-post-req',
                                {'action': 'os-getSerialConsole'})
        subs = self._get_regexes()
        subs["url"] = \
            "((ws?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        self._verify_response('get-serial-console-post-resp', subs,
                              response, 200)


class ConsoleAuthTokensSampleJsonTests(ServersSampleBase):
    extends_name = ("nova.api.openstack.compute.contrib.consoles.Consoles")
    extension_name = ("nova.api.openstack.compute.contrib.console_auth_tokens."
                      "Console_auth_tokens")

    def _get_console_url(self, data):
        return jsonutils.loads(data)["console"]["url"]

    def _get_console_token(self, uuid):
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-rdp-console-post-req',
                                {'action': 'os-getRDPConsole'})

        url = self._get_console_url(response.content)
        return re.match('.+?token=([^&]+)', url).groups()[0]

    def test_get_console_connect_info(self):
        self.flags(enabled=True, group='rdp')

        uuid = self._post_server()
        token = self._get_console_token(uuid)

        response = self._do_get('os-console-auth-tokens/%s' % token)

        subs = self._get_regexes()
        subs["uuid"] = uuid
        subs["host"] = r"[\w\.\-]+"
        subs["port"] = "[0-9]+"
        subs["internal_access_path"] = ".*"
        self._verify_response('get-console-connect-info-get-resp', subs,
                              response, 200)


class DeferredDeleteSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                     ".deferred_delete.Deferred_delete")

    def setUp(self):
        super(DeferredDeleteSampleJsonTests, self).setUp()
        self.flags(reclaim_instance_interval=1)

    def test_restore(self):
        uuid = self._post_server()
        response = self._do_delete('servers/%s' % uuid)

        response = self._do_post('servers/%s/action' % uuid,
                                 'restore-post-req', {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_force_delete(self):
        uuid = self._post_server()
        response = self._do_delete('servers/%s' % uuid)

        response = self._do_post('servers/%s/action' % uuid,
                                 'force-delete-post-req', {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class QuotasSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.quotas.Quotas"

    def test_show_quotas(self):
        # Get api sample to show quotas.
        response = self._do_get('os-quota-sets/fake_tenant')
        self._verify_response('quotas-show-get-resp', {}, response, 200)

    def test_show_quotas_defaults(self):
        # Get api sample to show quotas defaults.
        response = self._do_get('os-quota-sets/fake_tenant/defaults')
        self._verify_response('quotas-show-defaults-get-resp',
                              {}, response, 200)

    def test_update_quotas(self):
        # Get api sample to update quotas.
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-post-req',
                                {})
        self._verify_response('quotas-update-post-resp', {}, response, 200)


class ExtendedQuotasSampleJsonTests(ApiSampleTestBaseV2):
    extends_name = "nova.api.openstack.compute.contrib.quotas.Quotas"
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_quotas.Extended_quotas")

    def test_delete_quotas(self):
        # Get api sample to delete quota.
        response = self._do_delete('os-quota-sets/fake_tenant')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_update_quotas(self):
        # Get api sample to update quotas.
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-post-req',
                                {})
        return self._verify_response('quotas-update-post-resp', {},
                                     response, 200)


class UserQuotasSampleJsonTests(ApiSampleTestBaseV2):
    extends_name = "nova.api.openstack.compute.contrib.quotas.Quotas"
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".user_quotas.User_quotas")

    def fake_load(self, *args):
        return True

    def test_show_quotas_for_user(self):
        # Get api sample to show quotas for user.
        response = self._do_get('os-quota-sets/fake_tenant?user_id=1')
        self._verify_response('user-quotas-show-get-resp', {}, response, 200)

    def test_delete_quotas_for_user(self):
        # Get api sample to delete quota for user.
        self.stubs.Set(extensions.ExtensionManager, "is_loaded",
                self.fake_load)
        response = self._do_delete('os-quota-sets/fake_tenant?user_id=1')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_update_quotas_for_user(self):
        # Get api sample to update quotas for user.
        response = self._do_put('os-quota-sets/fake_tenant?user_id=1',
                                'user-quotas-update-post-req',
                                {})
        return self._verify_response('user-quotas-update-post-resp', {},
                                     response, 200)


class ExtendedIpsSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_ips.Extended_ips")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ExtendedIpsMacSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_ips_mac.Extended_ips_mac")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        self.assertEqual(response.status_code, 200)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        self.assertEqual(response.status_code, 200)
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ExtendedStatusSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_status.Extended_status")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ExtendedVolumesSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_volumes.Extended_volumes")

    def test_show(self):
        uuid = self._post_server()
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fakes.stub_bdm_get_all_by_instance)
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fakes.stub_bdm_get_all_by_instance)
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ServerUsageSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".server_usage.Server_usage")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        return self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        return self._verify_response('servers-detail-resp', subs,
                                     response, 200)


class ExtendedVIFNetSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
          ".extended_virtual_interfaces_net.Extended_virtual_interfaces_net")

    def _get_flags(self):
        f = super(ExtendedVIFNetSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # extended_virtual_interfaces_net_update also
        # needs virtual_interfaces to be loaded
        f['osapi_compute_extension'].append(
            ('nova.api.openstack.compute.contrib'
             '.virtual_interfaces.Virtual_interfaces'))
        return f

    def test_vifs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s/os-virtual-interfaces' % uuid)
        self.assertEqual(response.status_code, 200)

        subs = self._get_regexes()
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'

        self._verify_response('vifs-list-resp', subs, response, 200)


class FlavorManageSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.flavormanage."
                      "Flavormanage")

    def _create_flavor(self):
        """Create a flavor."""
        subs = {
            'flavor_id': 10,
            'flavor_name': "test_flavor"
        }
        response = self._do_post("flavors",
                                 "flavor-create-post-req",
                                 subs)
        subs.update(self._get_regexes())
        self._verify_response("flavor-create-post-resp", subs, response, 200)

    def test_create_flavor(self):
        # Get api sample to create a flavor.
        self._create_flavor()

    def test_delete_flavor(self):
        # Get api sample to delete a flavor.
        self._create_flavor()
        response = self._do_delete("flavors/10")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class ServerPasswordSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.server_password."
                      "Server_password")

    def test_get_password(self):

        # Mock password since there is no api to set it
        def fake_ext_password(*args, **kwargs):
            return ("xlozO3wLCBRWAa2yDjCCVx8vwNPypxnypmRYDa/zErlQ+EzPe1S/"
                    "Gz6nfmC52mOlOSCRuUOmG7kqqgejPof6M7bOezS387zjq4LSvvwp"
                    "28zUknzy4YzfFGhnHAdai3TxUJ26pfQCYrq8UTzmKF2Bq8ioSEtV"
                    "VzM0A96pDh8W2i7BOz6MdoiVyiev/I1K2LsuipfxSJR7Wdke4zNX"
                    "JjHHP2RfYsVbZ/k9ANu+Nz4iIH8/7Cacud/pphH7EjrY6a4RZNrj"
                    "QskrhKYed0YERpotyjYk1eDtRe72GrSiXteqCM4biaQ5w3ruS+Ac"
                    "X//PXk3uJ5kC7d67fPXaVz4WaQRYMg==")
        self.stubs.Set(password, "extract_password", fake_ext_password)
        uuid = self._post_server()
        response = self._do_get('servers/%s/os-server-password' % uuid)
        subs = self._get_regexes()
        subs['encrypted_password'] = fake_ext_password().replace('+', '\\+')
        self._verify_response('get-password-resp', subs, response, 200)

    def test_reset_password(self):
        uuid = self._post_server()
        response = self._do_delete('servers/%s/os-server-password' % uuid)
        self.assertEqual(response.status_code, 204)


class DiskConfigJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.disk_config."
                      "Disk_config")

    def test_list_servers_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        self._verify_response('list-servers-detail-get', subs, response, 200)

    def test_get_server(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_update_server(self):
        uuid = self._post_server()
        response = self._do_put('servers/%s' % uuid,
                                'server-update-put-req', {})
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-update-put-resp', subs, response, 200)

    def test_resize_server(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-resize-post-req', {})
        self.assertEqual(response.status_code, 202)
        # NOTE(tmello): Resize does not return response body
        # Bug #1085213.
        self.assertEqual(response.content, "")

    def test_rebuild_server(self):
        uuid = self._post_server()
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-rebuild-req', subs)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-action-rebuild-resp',
                              subs, response, 202)

    def test_get_image(self):
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s' % image_id)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        self._verify_response('image-get-resp', subs, response, 200)

    def test_list_images(self):
        response = self._do_get('images/detail')
        subs = self._get_regexes()
        self._verify_response('image-list-resp', subs, response, 200)


class OsNetworksJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.os_tenant_networks"
                      ".Os_tenant_networks")

    def setUp(self):
        super(OsNetworksJsonTests, self).setUp()
        CONF.set_override("enable_network_quota", True)

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(nova.quota.QUOTAS, "reserve", fake)
        self.stubs.Set(nova.quota.QUOTAS, "commit", fake)
        self.stubs.Set(nova.quota.QUOTAS, "rollback", fake)
        self.stubs.Set(nova.quota.QuotaEngine, "reserve", fake)
        self.stubs.Set(nova.quota.QuotaEngine, "commit", fake)
        self.stubs.Set(nova.quota.QuotaEngine, "rollback", fake)

    def test_list_networks(self):
        response = self._do_get('os-tenant-networks')
        subs = self._get_regexes()
        self._verify_response('networks-list-res', subs, response, 200)

    def test_create_network(self):
        response = self._do_post('os-tenant-networks', "networks-post-req", {})
        subs = self._get_regexes()
        self._verify_response('networks-post-res', subs, response, 200)

    def test_delete_network(self):
        response = self._do_post('os-tenant-networks', "networks-post-req", {})
        net = jsonutils.loads(response.content)
        response = self._do_delete('os-tenant-networks/%s' %
                                                net["network"]["id"])
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")


class NetworksJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".os_networks.Os_networks")

    def setUp(self):
        super(NetworksJsonTests, self).setUp()
        fake_network_api = test_networks.FakeNetworkAPI()
        self.stubs.Set(network_api.API, "get_all",
                       fake_network_api.get_all)
        self.stubs.Set(network_api.API, "get",
                       fake_network_api.get)
        self.stubs.Set(network_api.API, "associate",
                       fake_network_api.associate)
        self.stubs.Set(network_api.API, "delete",
                       fake_network_api.delete)
        self.stubs.Set(network_api.API, "create",
                       fake_network_api.create)
        self.stubs.Set(network_api.API, "add_network_to_project",
                       fake_network_api.add_network_to_project)

    def test_network_list(self):
        response = self._do_get('os-networks')
        subs = self._get_regexes()
        self._verify_response('networks-list-resp', subs, response, 200)

    def test_network_disassociate(self):
        uuid = test_networks.FAKE_NETWORKS[0]['uuid']
        response = self._do_post('os-networks/%s/action' % uuid,
                                 'networks-disassociate-req', {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_network_show(self):
        uuid = test_networks.FAKE_NETWORKS[0]['uuid']
        response = self._do_get('os-networks/%s' % uuid)
        subs = self._get_regexes()
        self._verify_response('network-show-resp', subs, response, 200)

    def test_network_create(self):
        response = self._do_post("os-networks",
                                 'network-create-req', {})
        subs = self._get_regexes()
        self._verify_response('network-create-resp', subs, response, 200)

    def test_network_add(self):
        response = self._do_post("os-networks/add",
                                 'network-add-req', {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_network_delete(self):
        response = self._do_delete('os-networks/always_delete')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")


class ExtendedNetworksJsonTests(ApiSampleTestBaseV2):
    extends_name = ("nova.api.openstack.compute.contrib."
                    "os_networks.Os_networks")
    extension_name = ("nova.api.openstack.compute.contrib."
                      "extended_networks.Extended_networks")

    def setUp(self):
        super(ExtendedNetworksJsonTests, self).setUp()
        fake_network_api = test_networks.FakeNetworkAPI()
        self.stubs.Set(network_api.API, "get_all",
                       fake_network_api.get_all)
        self.stubs.Set(network_api.API, "get",
                       fake_network_api.get)
        self.stubs.Set(network_api.API, "associate",
                       fake_network_api.associate)
        self.stubs.Set(network_api.API, "delete",
                       fake_network_api.delete)
        self.stubs.Set(network_api.API, "create",
                       fake_network_api.create)
        self.stubs.Set(network_api.API, "add_network_to_project",
                       fake_network_api.add_network_to_project)

    def test_network_list(self):
        response = self._do_get('os-networks')
        subs = self._get_regexes()
        self._verify_response('networks-list-resp', subs, response, 200)

    def test_network_show(self):
        uuid = test_networks.FAKE_NETWORKS[0]['uuid']
        response = self._do_get('os-networks/%s' % uuid)
        subs = self._get_regexes()
        self._verify_response('network-show-resp', subs, response, 200)

    def test_network_create(self):
        response = self._do_post("os-networks",
                                 'network-create-req', {})
        subs = self._get_regexes()
        self._verify_response('network-create-resp', subs, response, 200)


class NetworksAssociateJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib"
                                     ".networks_associate.Networks_associate")

    _sentinel = object()

    def _get_flags(self):
        f = super(NetworksAssociateJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # Networks_associate requires Networks to be update
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.os_networks.Os_networks')
        return f

    def setUp(self):
        super(NetworksAssociateJsonTests, self).setUp()

        def fake_associate(self, context, network_id,
                           host=NetworksAssociateJsonTests._sentinel,
                           project=NetworksAssociateJsonTests._sentinel):
            return True

        self.stubs.Set(network_api.API, "associate", fake_associate)

    def test_disassociate(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-req',
                                 {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_disassociate_host(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-host-req',
                                 {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_disassociate_project(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-project-req',
                                 {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")

    def test_associate_host(self):
        response = self._do_post('os-networks/1/action',
                                 'network-associate-host-req',
                                 {"host": "testHost"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")


class FlavorDisabledSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.flavor_disabled."
                      "Flavor_disabled")

    def test_show_flavor(self):
        # Get api sample to show flavor_disabled attr. of a flavor.
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        subs = self._get_regexes()
        subs['flavor_id'] = flavor_id
        self._verify_response('flavor-show-get-resp', subs, response, 200)

    def test_detail_flavor(self):
        # Get api sample to show details of a flavor.
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        self._verify_response('flavor-detail-get-resp', subs, response, 200)


class QuotaClassesSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.quota_classes."
                      "Quota_classes")
    set_id = 'test_class'

    def test_show_quota_classes(self):
        # Get api sample to show quota classes.
        response = self._do_get('os-quota-class-sets/%s' % self.set_id)
        subs = {'set_id': self.set_id}
        self._verify_response('quota-classes-show-get-resp', subs,
                              response, 200)

    def test_update_quota_classes(self):
        # Get api sample to update quota classes.
        response = self._do_put('os-quota-class-sets/%s' % self.set_id,
                                'quota-classes-update-post-req',
                                {})
        self._verify_response('quota-classes-update-post-resp',
                              {}, response, 200)


class CellsSampleJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.cells.Cells"

    def setUp(self):
        # db_check_interval < 0 makes cells manager always hit the DB
        self.flags(enable=True, db_check_interval=-1, group='cells')
        super(CellsSampleJsonTest, self).setUp()
        self._stub_cells()

    def _stub_cells(self, num_cells=5):
        self.cells = []
        self.cells_next_id = 1

        def _fake_cell_get_all(context):
            return self.cells

        def _fake_cell_get(inst, context, cell_name):
            for cell in self.cells:
                if cell['name'] == cell_name:
                    return cell
            raise exception.CellNotFound(cell_name=cell_name)

        for x in xrange(num_cells):
            cell = models.Cell()
            our_id = self.cells_next_id
            self.cells_next_id += 1
            cell.update({'id': our_id,
                         'name': 'cell%s' % our_id,
                         'transport_url': 'rabbit://username%s@/' % our_id,
                         'is_parent': our_id % 2 == 0})
            self.cells.append(cell)

        self.stubs.Set(db, 'cell_get_all', _fake_cell_get_all)
        self.stubs.Set(cells_rpcapi.CellsAPI, 'cell_get', _fake_cell_get)

    def test_cells_empty_list(self):
        # Override this
        self._stub_cells(num_cells=0)
        response = self._do_get('os-cells')
        subs = self._get_regexes()
        self._verify_response('cells-list-empty-resp', subs, response, 200)

    def test_cells_list(self):
        response = self._do_get('os-cells')
        subs = self._get_regexes()
        self._verify_response('cells-list-resp', subs, response, 200)

    def test_cells_get(self):
        response = self._do_get('os-cells/cell3')
        subs = self._get_regexes()
        self._verify_response('cells-get-resp', subs, response, 200)


class CellsCapacitySampleJsonTest(ApiSampleTestBaseV2):
    extends_name = ("nova.api.openstack.compute.contrib.cells.Cells")
    extension_name = ("nova.api.openstack.compute.contrib."
                         "cell_capacities.Cell_capacities")

    def setUp(self):
        self.flags(enable=True, db_check_interval=-1, group='cells')
        super(CellsCapacitySampleJsonTest, self).setUp()
        # (navneetk/kaushikc) : Mock cell capacity to avoid the capacity
        # being calculated from the compute nodes in the environment
        self._mock_cell_capacity()

    def test_get_cell_capacity(self):
        state_manager = state.CellStateManager()
        my_state = state_manager.get_my_state()
        response = self._do_get('os-cells/%s/capacities' %
                my_state.name)
        subs = self._get_regexes()
        return self._verify_response('cells-capacities-resp',
                                        subs, response, 200)

    def test_get_all_cells_capacity(self):
        response = self._do_get('os-cells/capacities')
        subs = self._get_regexes()
        return self._verify_response('cells-capacities-resp',
                                        subs, response, 200)

    def _mock_cell_capacity(self):
        self.mox.StubOutWithMock(self.cells.manager.state_manager,
                                 'get_our_capacities')
        response = {"ram_free":
                        {"units_by_mb": {"8192": 0, "512": 13,
                                         "4096": 1, "2048": 3, "16384": 0},
                         "total_mb": 7680},
                    "disk_free":
                        {"units_by_mb": {"81920": 11, "20480": 46,
                                         "40960": 23, "163840": 5, "0": 0},
                         "total_mb": 1052672}
        }
        self.cells.manager.state_manager.get_our_capacities(). \
            AndReturn(response)
        self.mox.ReplayAll()


class BlockDeviceMappingV2BootJsonTest(ServersSampleBase):
    extension_name = ('nova.api.openstack.compute.contrib.'
                      'block_device_mapping_v2_boot.'
                      'Block_device_mapping_v2_boot')

    def _get_flags(self):
        f = super(BlockDeviceMappingV2BootJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # We need the volumes extension as well
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.volumes.Volumes')
        return f

    def test_servers_post_with_bdm_v2(self):
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(cinder.API, 'check_attach',
                       fakes.stub_volume_check_attach)
        return self._post_server()


class FloatingIPPoolsSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.floating_ip_pools."
                      "Floating_ip_pools")

    def test_list_floatingippools(self):
        pool_list = ["pool1", "pool2"]

        def fake_get_floating_ip_pools(self, context):
            return pool_list

        self.stubs.Set(network_api.API, "get_floating_ip_pools",
                       fake_get_floating_ip_pools)
        response = self._do_get('os-floating-ip-pools')
        subs = {
            'pool1': pool_list[0],
            'pool2': pool_list[1]
        }
        self._verify_response('floatingippools-list-resp', subs, response, 200)


class MultinicSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib.multinic.Multinic"

    def _disable_instance_dns_manager(self):
        # NOTE(markmc): it looks like multinic and instance_dns_manager are
        #               incompatible. See:
        #               https://bugs.launchpad.net/nova/+bug/1213251
        self.flags(
            instance_dns_manager='nova.network.noop_dns_driver.NoopDNSDriver')

    def setUp(self):
        self._disable_instance_dns_manager()
        super(MultinicSampleJsonTest, self).setUp()
        self.uuid = self._post_server()

    def _add_fixed_ip(self):
        subs = {"networkId": 1}
        response = self._do_post('servers/%s/action' % (self.uuid),
                                 'multinic-add-fixed-ip-req', subs)
        self.assertEqual(response.status_code, 202)

    def test_add_fixed_ip(self):
        self._add_fixed_ip()

    def test_remove_fixed_ip(self):
        self._add_fixed_ip()

        subs = {"ip": "10.0.0.4"}
        response = self._do_post('servers/%s/action' % (self.uuid),
                                 'multinic-remove-fixed-ip-req', subs)
        self.assertEqual(response.status_code, 202)


class InstanceUsageAuditLogJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib."
                      "instance_usage_audit_log.Instance_usage_audit_log")

    def test_show_instance_usage_audit_log(self):
        response = self._do_get('os-instance_usage_audit_log/%s' %
                                urllib.quote('2012-07-05 10:00:00'))
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('inst-usage-audit-log-show-get-resp',
                              subs, response, 200)

    def test_index_instance_usage_audit_log(self):
        response = self._do_get('os-instance_usage_audit_log')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('inst-usage-audit-log-index-get-resp',
                              subs, response, 200)


class FlavorExtraSpecsSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.flavorextraspecs."
                      "Flavorextraspecs")

    def _flavor_extra_specs_create(self):
        subs = {'value1': 'value1',
                'value2': 'value2'
        }
        response = self._do_post('flavors/1/os-extra_specs',
                                 'flavor-extra-specs-create-req', subs)
        self._verify_response('flavor-extra-specs-create-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_get(self):
        subs = {'value1': 'value1'}
        self._flavor_extra_specs_create()
        response = self._do_get('flavors/1/os-extra_specs/key1')
        self._verify_response('flavor-extra-specs-get-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_list(self):
        subs = {'value1': 'value1',
                'value2': 'value2'
        }
        self._flavor_extra_specs_create()
        response = self._do_get('flavors/1/os-extra_specs')
        self._verify_response('flavor-extra-specs-list-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_create(self):
        self._flavor_extra_specs_create()

    def test_flavor_extra_specs_update(self):
        subs = {'value1': 'new_value1'}
        self._flavor_extra_specs_create()
        response = self._do_put('flavors/1/os-extra_specs/key1',
                                'flavor-extra-specs-update-req', subs)
        self._verify_response('flavor-extra-specs-update-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_delete(self):
        self._flavor_extra_specs_create()
        response = self._do_delete('flavors/1/os-extra_specs/key1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, '')


class FpingSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.fping.Fping")

    def setUp(self):
        super(FpingSampleJsonTests, self).setUp()

        def fake_check_fping(self):
            pass
        self.stubs.Set(utils, "execute", test_fping.execute)
        self.stubs.Set(fping.FpingController, "check_fping",
                       fake_check_fping)

    def test_get_fping(self):
        self._post_server()
        response = self._do_get('os-fping')
        subs = self._get_regexes()
        self._verify_response('fping-get-resp', subs, response, 200)

    def test_get_fping_details(self):
        uuid = self._post_server()
        response = self._do_get('os-fping/%s' % (uuid))
        subs = self._get_regexes()
        self._verify_response('fping-get-details-resp', subs, response, 200)


class ExtendedAvailabilityZoneJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                ".extended_availability_zone"
                                ".Extended_availability_zone")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class EvacuateJsonTest(ServersSampleBase):

    extension_name = ("nova.api.openstack.compute.contrib"
                      ".evacuate.Evacuate")

    def test_server_evacuate(self):
        uuid = self._post_server()

        req_subs = {
            'host': 'testHost',
            "adminPass": "MySecretPass",
            "onSharedStorage": 'False'
        }

        def fake_service_is_up(self, service):
            """Simulate validation of instance host is down."""
            return False

        def fake_service_get_by_compute_host(self, context, host):
            """Simulate that given host is a valid host."""
            return {
                    'host_name': host,
                    'service': 'compute',
                    'zone': 'nova'
                    }

        def fake_rebuild_instance(self, ctxt, instance, new_pass,
                                  injected_files, image_ref, orig_image_ref,
                                  orig_sys_metadata, bdms, recreate=False,
                                  on_shared_storage=False, host=None,
                                  preserve_ephemeral=False, kwargs=None):
            return {
                    'adminPass': new_pass
                    }

        self.stubs.Set(service_group_api.API, 'service_is_up',
                       fake_service_is_up)
        self.stubs.Set(compute_api.HostAPI, 'service_get_by_compute_host',
                       fake_service_get_by_compute_host)
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'rebuild_instance',
                       fake_rebuild_instance)

        response = self._do_post('servers/%s/action' % uuid,
                                 'server-evacuate-req', req_subs)
        subs = self._get_regexes()
        self._verify_response('server-evacuate-resp', subs, response, 200)


class EvacuateFindHostSampleJsonTest(ServersSampleBase):
    extends_name = ("nova.api.openstack.compute.contrib"
                      ".evacuate.Evacuate")

    extension_name = ("nova.api.openstack.compute.contrib"
                ".extended_evacuate_find_host.Extended_evacuate_find_host")

    @mock.patch('nova.compute.manager.ComputeManager._check_instance_exists')
    @mock.patch('nova.compute.api.HostAPI.service_get_by_compute_host')
    @mock.patch('nova.conductor.manager.ComputeTaskManager.rebuild_instance')
    def test_server_evacuate(self, rebuild_mock, service_get_mock,
                             check_instance_mock):
        self.uuid = self._post_server()

        req_subs = {
            "adminPass": "MySecretPass",
            "onSharedStorage": 'False'
        }

        check_instance_mock.return_value = False

        def fake_service_get_by_compute_host(self, context, host):
            return {
                    'host_name': host,
                    'service': 'compute',
                    'zone': 'nova'
                    }
        service_get_mock.side_effect = fake_service_get_by_compute_host
        with mock.patch.object(service_group_api.API, 'service_is_up',
                               return_value=False):
            response = self._do_post('servers/%s/action' % self.uuid,
                                     'server-evacuate-find-host-req', req_subs)
            subs = self._get_regexes()
            self._verify_response('server-evacuate-find-host-resp', subs,
                                  response, 200)
        rebuild_mock.assert_called_once_with(mock.ANY, instance=mock.ANY,
                orig_image_ref=mock.ANY, image_ref=mock.ANY,
                injected_files=mock.ANY, new_pass="MySecretPass",
                orig_sys_metadata=mock.ANY, bdms=mock.ANY, recreate=mock.ANY,
                on_shared_storage=False, preserve_ephemeral=mock.ANY,
                host=None)


class FloatingIpDNSJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.floating_ip_dns."
                      "Floating_ip_dns")

    domain = 'domain1.example.org'
    name = 'instance1'
    scope = 'public'
    project = 'project1'
    dns_type = 'A'
    ip = '192.168.1.1'

    def _create_or_update(self):
        subs = {'domain': self.domain,
                'project': self.project,
                'scope': self.scope}
        response = self._do_put('os-floating-ip-dns/%s' % self.domain,
                                'floating-ip-dns-create-or-update-req', subs)
        self._verify_response('floating-ip-dns-create-or-update-resp', subs,
                              response, 200)

    def _create_or_update_entry(self):
        subs = {'ip': self.ip, 'dns_type': self.dns_type}
        response = self._do_put('os-floating-ip-dns/%s/entries/%s'
                                % (self.domain, self.name),
                                'floating-ip-dns-create-or-update-entry-req',
                                subs)
        subs.update({'name': self.name, 'domain': self.domain})
        self._verify_response('floating-ip-dns-create-or-update-entry-resp',
                              subs, response, 200)

    def test_floating_ip_dns_list(self):
        self._create_or_update()
        response = self._do_get('os-floating-ip-dns')
        subs = {'domain': self.domain,
                'project': self.project,
                'scope': self.scope}
        self._verify_response('floating-ip-dns-list-resp', subs,
                              response, 200)

    def test_floating_ip_dns_create_or_update(self):
        self._create_or_update()

    def test_floating_ip_dns_delete(self):
        self._create_or_update()
        response = self._do_delete('os-floating-ip-dns/%s' % self.domain)
        self.assertEqual(response.status_code, 202)

    def test_floating_ip_dns_create_or_update_entry(self):
        self._create_or_update_entry()

    def test_floating_ip_dns_entry_get(self):
        self._create_or_update_entry()
        response = self._do_get('os-floating-ip-dns/%s/entries/%s'
                                % (self.domain, self.name))
        subs = {'domain': self.domain,
                'ip': self.ip,
                'name': self.name}
        self._verify_response('floating-ip-dns-entry-get-resp', subs,
                              response, 200)

    def test_floating_ip_dns_entry_delete(self):
        self._create_or_update_entry()
        response = self._do_delete('os-floating-ip-dns/%s/entries/%s'
                                   % (self.domain, self.name))
        self.assertEqual(response.status_code, 202)

    def test_floating_ip_dns_entry_list(self):
        self._create_or_update_entry()
        response = self._do_get('os-floating-ip-dns/%s/entries/%s'
                                % (self.domain, self.ip))
        subs = {'domain': self.domain,
                'ip': self.ip,
                'name': self.name}
        self._verify_response('floating-ip-dns-entry-list-resp', subs,
                              response, 200)


class InstanceActionsSampleJsonTest(ApiSampleTestBaseV2):
    extension_name = ('nova.api.openstack.compute.contrib.instance_actions.'
                      'Instance_actions')

    def setUp(self):
        super(InstanceActionsSampleJsonTest, self).setUp()
        self.actions = fake_server_actions.FAKE_ACTIONS
        self.events = fake_server_actions.FAKE_EVENTS
        self.instance = test_utils.get_test_instance()

        def fake_server_action_get_by_request_id(context, uuid, request_id):
            return copy.deepcopy(self.actions[uuid][request_id])

        def fake_server_actions_get(context, uuid):
            return [copy.deepcopy(value) for value in
                    self.actions[uuid].itervalues()]

        def fake_server_action_events_get(context, action_id):
            return copy.deepcopy(self.events[action_id])

        def fake_instance_get_by_uuid(context, instance_id):
            return self.instance

        def fake_get(self, context, instance_uuid, expected_attrs=None,
                     want_objects=True):
            return {'uuid': instance_uuid}

        self.stubs.Set(db, 'action_get_by_request_id',
                       fake_server_action_get_by_request_id)
        self.stubs.Set(db, 'actions_get', fake_server_actions_get)
        self.stubs.Set(db, 'action_events_get',
                       fake_server_action_events_get)
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(compute_api.API, 'get', fake_get)

    def test_instance_action_get(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        fake_request_id = fake_server_actions.FAKE_REQUEST_ID1
        fake_action = self.actions[fake_uuid][fake_request_id]

        response = self._do_get('servers/%s/os-instance-actions/%s' %
                                (fake_uuid, fake_request_id))
        subs = self._get_regexes()
        subs['action'] = '(reboot)|(resize)'
        subs['instance_uuid'] = fake_uuid
        subs['integer_id'] = '[0-9]+'
        subs['request_id'] = fake_action['request_id']
        subs['start_time'] = fake_action['start_time']
        subs['result'] = '(Success)|(Error)'
        subs['event'] = '(schedule)|(compute_create)'
        self._verify_response('instance-action-get-resp', subs, response, 200)

    def test_instance_actions_list(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        response = self._do_get('servers/%s/os-instance-actions' % (fake_uuid))
        subs = self._get_regexes()
        subs['action'] = '(reboot)|(resize)'
        subs['integer_id'] = '[0-9]+'
        subs['request_id'] = ('req-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                              '-[0-9a-f]{4}-[0-9a-f]{12}')
        self._verify_response('instance-actions-list-resp', subs,
                              response, 200)


class ImageSizeSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".image_size.Image_size")

    def test_show(self):
        # Get api sample of one single image details request.
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s' % image_id)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        self._verify_response('image-get-resp', subs, response, 200)

    def test_detail(self):
        # Get api sample of all images details request.
        response = self._do_get('images/detail')
        subs = self._get_regexes()
        self._verify_response('images-details-get-resp', subs, response, 200)


class ConfigDriveSampleJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.config_drive."
                      "Config_drive")

    def setUp(self):
        super(ConfigDriveSampleJsonTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fake.stub_out_image_service(self.stubs)

    def test_config_drive_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        self._verify_response('server-config-drive-get-resp', subs,
                              response, 200)

    def test_config_drive_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        self._verify_response('servers-config-drive-details-resp',
                              subs, response, 200)


class FlavorAccessSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.flavor_access."
                      "Flavor_access")

    def _get_flags(self):
        f = super(FlavorAccessSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # FlavorAccess extension also needs Flavormanage to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavormanage.Flavormanage')
        return f

    def _add_tenant(self):
        subs = {
            'tenant_id': 'fake_tenant',
            'flavor_id': 10
        }
        response = self._do_post('flavors/10/action',
                                 'flavor-access-add-tenant-req',
                                 subs)
        self._verify_response('flavor-access-add-tenant-resp',
                              subs, response, 200)

    def _create_flavor(self):
        subs = {
            'flavor_id': 10,
            'flavor_name': 'test_flavor'
        }
        response = self._do_post("flavors",
                                 "flavor-access-create-req",
                                 subs)
        subs.update(self._get_regexes())
        self._verify_response("flavor-access-create-resp", subs, response, 200)

    def test_flavor_access_create(self):
        self._create_flavor()

    def test_flavor_access_detail(self):
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        self._verify_response('flavor-access-detail-resp', subs, response, 200)

    def test_flavor_access_list(self):
        self._create_flavor()
        self._add_tenant()
        flavor_id = 10
        response = self._do_get('flavors/%s/os-flavor-access' % flavor_id)
        subs = {
            'flavor_id': flavor_id,
            'tenant_id': 'fake_tenant',
        }
        self._verify_response('flavor-access-list-resp', subs, response, 200)

    def test_flavor_access_show(self):
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        subs = {
            'flavor_id': flavor_id
        }
        subs.update(self._get_regexes())
        self._verify_response('flavor-access-show-resp', subs, response, 200)

    def test_flavor_access_add_tenant(self):
        self._create_flavor()
        self._add_tenant()

    def test_flavor_access_remove_tenant(self):
        self._create_flavor()
        self._add_tenant()
        subs = {
            'tenant_id': 'fake_tenant',
        }
        response = self._do_post('flavors/10/action',
                                 "flavor-access-remove-tenant-req",
                                 subs)
        exp_subs = {
            "tenant_id": self.api.project_id,
            "flavor_id": "10"
        }
        self._verify_response('flavor-access-remove-tenant-resp',
                              exp_subs, response, 200)


@mock.patch.object(service_group_api.API, "service_is_up", lambda _: True)
class HypervisorsSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.hypervisors."
                      "Hypervisors")

    def test_hypervisors_list(self):
        response = self._do_get('os-hypervisors')
        self._verify_response('hypervisors-list-resp', {}, response, 200)

    def test_hypervisors_search(self):
        response = self._do_get('os-hypervisors/fake/search')
        self._verify_response('hypervisors-search-resp', {}, response, 200)

    def test_hypervisors_servers(self):
        response = self._do_get('os-hypervisors/fake/servers')
        self._verify_response('hypervisors-servers-resp', {}, response, 200)

    def test_hypervisors_show(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-show-resp', subs, response, 200)

    def test_hypervisors_statistics(self):
        response = self._do_get('os-hypervisors/statistics')
        self._verify_response('hypervisors-statistics-resp', {}, response, 200)

    def test_hypervisors_uptime(self):
        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        self.stubs.Set(compute_api.HostAPI,
                       'get_host_uptime', fake_get_host_uptime)
        hypervisor_id = 1
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {
            'hypervisor_id': hypervisor_id,
        }
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)


class ExtendedHypervisorsJsonTest(ApiSampleTestBaseV2):
    extends_name = ("nova.api.openstack.compute.contrib."
                    "hypervisors.Hypervisors")
    extension_name = ("nova.api.openstack.compute.contrib."
                      "extended_hypervisors.Extended_hypervisors")

    def test_hypervisors_show_with_ip(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-show-with-ip-resp',
                              subs, response, 200)


class HypervisorStatusJsonTest(ApiSampleTestBaseV2):
    extends_name = ("nova.api.openstack.compute.contrib."
                    "hypervisors.Hypervisors")
    extension_name = ("nova.api.openstack.compute.contrib."
                      "hypervisor_status.Hypervisor_status")

    def test_hypervisors_show_with_status(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-show-with-status-resp',
                              subs, response, 200)


@mock.patch("nova.servicegroup.API.service_is_up", return_value=True)
class HypervisorsCellsSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.hypervisors."
                      "Hypervisors")

    def setUp(self):
        self.flags(enable=True, cell_type='api', group='cells')
        super(HypervisorsCellsSampleJsonTests, self).setUp()

    def test_hypervisor_uptime(self, mocks):
        fake_hypervisor = {'service': {'host': 'fake-mini',
                                       'disabled': False,
                                       'disabled_reason': None},
                           'id': 1, 'hypervisor_hostname': 'fake-mini'}

        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        def fake_compute_node_get(self, context, hyp):
            return fake_hypervisor

        self.stubs.Set(cells_api.HostAPI, 'compute_node_get',
                       fake_compute_node_get)

        self.stubs.Set(cells_api.HostAPI,
                       'get_host_uptime', fake_get_host_uptime)
        hypervisor_id = fake_hypervisor['id']
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {'hypervisor_id': hypervisor_id}
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)


class AttachInterfacesSampleJsonTest(ServersSampleBase):
    extension_name = ('nova.api.openstack.compute.contrib.attach_interfaces.'
                      'Attach_interfaces')

    def setUp(self):
        super(AttachInterfacesSampleJsonTest, self).setUp()

        def fake_list_ports(self, *args, **kwargs):
            uuid = kwargs.get('device_id', None)
            if not uuid:
                raise exception.InstanceNotFound(instance_id=None)
            port_data = {
                "id": "ce531f90-199f-48c0-816c-13e38010b442",
                "network_id": "3cb9bc59-5699-4588-a4b1-b87f96708bc6",
                "admin_state_up": True,
                "status": "ACTIVE",
                "mac_address": "fa:16:3e:4c:2c:30",
                "fixed_ips": [
                    {
                        "ip_address": "192.168.1.3",
                        "subnet_id": "f8a6e8f8-c2ec-497c-9f23-da9616de54ef"
                    }
                ],
                "device_id": uuid,
                }
            ports = {'ports': [port_data]}
            return ports

        def fake_show_port(self, context, port_id=None):
            if not port_id:
                raise exception.PortNotFound(port_id=None)
            port_data = {
                "id": port_id,
                "network_id": "3cb9bc59-5699-4588-a4b1-b87f96708bc6",
                "admin_state_up": True,
                "status": "ACTIVE",
                "mac_address": "fa:16:3e:4c:2c:30",
                "fixed_ips": [
                    {
                        "ip_address": "192.168.1.3",
                        "subnet_id": "f8a6e8f8-c2ec-497c-9f23-da9616de54ef"
                    }
                ],
                "device_id": 'bece68a3-2f8b-4e66-9092-244493d6aba7',
                }
            port = {'port': port_data}
            return port

        def fake_attach_interface(self, context, instance,
                                  network_id, port_id,
                                  requested_ip='192.168.1.3'):
            if not network_id:
                network_id = "fake_net_uuid"
            if not port_id:
                port_id = "fake_port_uuid"
            vif = fake_network_cache_model.new_vif()
            vif['id'] = port_id
            vif['network']['id'] = network_id
            vif['network']['subnets'][0]['ips'][0] = requested_ip
            return vif

        def fake_detach_interface(self, context, instance, port_id):
            pass

        self.stubs.Set(network_api.API, 'list_ports', fake_list_ports)
        self.stubs.Set(network_api.API, 'show_port', fake_show_port)
        self.stubs.Set(compute_api.API, 'attach_interface',
                       fake_attach_interface)
        self.stubs.Set(compute_api.API, 'detach_interface',
                       fake_detach_interface)
        self.flags(auth_strategy=None, group='neutron')
        self.flags(url='http://anyhost/', group='neutron')
        self.flags(url_timeout=30, group='neutron')

    def generalize_subs(self, subs, vanilla_regexes):
        subs['subnet_id'] = vanilla_regexes['uuid']
        subs['net_id'] = vanilla_regexes['uuid']
        subs['port_id'] = vanilla_regexes['uuid']
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        subs['ip_address'] = vanilla_regexes['ip']
        return subs

    def test_list_interfaces(self):
        instance_uuid = self._post_server()
        response = self._do_get('servers/%s/os-interface' % instance_uuid)
        subs = {
                'ip_address': '192.168.1.3',
                'subnet_id': 'f8a6e8f8-c2ec-497c-9f23-da9616de54ef',
                'mac_addr': 'fa:16:3e:4c:2c:30',
                'net_id': '3cb9bc59-5699-4588-a4b1-b87f96708bc6',
                'port_id': 'ce531f90-199f-48c0-816c-13e38010b442',
                'port_state': 'ACTIVE'
                }
        self._verify_response('attach-interfaces-list-resp', subs,
                              response, 200)

    def _stub_show_for_instance(self, instance_uuid, port_id):
        show_port = network_api.API().show_port(None, port_id)
        show_port['port']['device_id'] = instance_uuid
        self.stubs.Set(network_api.API, 'show_port', lambda *a, **k: show_port)

    def test_show_interfaces(self):
        instance_uuid = self._post_server()
        port_id = 'ce531f90-199f-48c0-816c-13e38010b442'
        self._stub_show_for_instance(instance_uuid, port_id)
        response = self._do_get('servers/%s/os-interface/%s' %
                                (instance_uuid, port_id))
        subs = {
                'ip_address': '192.168.1.3',
                'subnet_id': 'f8a6e8f8-c2ec-497c-9f23-da9616de54ef',
                'mac_addr': 'fa:16:3e:4c:2c:30',
                'net_id': '3cb9bc59-5699-4588-a4b1-b87f96708bc6',
                'port_id': port_id,
                'port_state': 'ACTIVE'
                }
        self._verify_response('attach-interfaces-show-resp', subs,
                              response, 200)

    def test_create_interfaces(self, instance_uuid=None):
        if instance_uuid is None:
            instance_uuid = self._post_server()
        subs = {
                'net_id': '3cb9bc59-5699-4588-a4b1-b87f96708bc6',
                'port_id': 'ce531f90-199f-48c0-816c-13e38010b442',
                'subnet_id': 'f8a6e8f8-c2ec-497c-9f23-da9616de54ef',
                'ip_address': '192.168.1.3',
                'port_state': 'ACTIVE',
                'mac_addr': 'fa:16:3e:4c:2c:30',
                }
        self._stub_show_for_instance(instance_uuid, subs['port_id'])
        response = self._do_post('servers/%s/os-interface' % instance_uuid,
                                 'attach-interfaces-create-req', subs)
        subs.update(self._get_regexes())
        self._verify_response('attach-interfaces-create-resp', subs,
                              response, 200)

    def test_delete_interfaces(self):
        instance_uuid = self._post_server()
        port_id = 'ce531f90-199f-48c0-816c-13e38010b442'
        response = self._do_delete('servers/%s/os-interface/%s' %
                                (instance_uuid, port_id))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class SnapshotsSampleJsonTests(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.volumes.Volumes"

    create_subs = {
            'snapshot_name': 'snap-001',
            'description': 'Daily backup',
            'volume_id': '521752a6-acf6-4b2d-bc7a-119f9148cd8c'
    }

    def setUp(self):
        super(SnapshotsSampleJsonTests, self).setUp()
        self.stubs.Set(cinder.API, "get_all_snapshots",
                       fakes.stub_snapshot_get_all)
        self.stubs.Set(cinder.API, "get_snapshot", fakes.stub_snapshot_get)

    def _create_snapshot(self):
        self.stubs.Set(cinder.API, "create_snapshot",
                       fakes.stub_snapshot_create)

        response = self._do_post("os-snapshots",
                                 "snapshot-create-req",
                                 self.create_subs)
        return response

    def test_snapshots_create(self):
        response = self._create_snapshot()
        self.create_subs.update(self._get_regexes())
        self._verify_response("snapshot-create-resp",
                              self.create_subs, response, 200)

    def test_snapshots_delete(self):
        self.stubs.Set(cinder.API, "delete_snapshot",
                       fakes.stub_snapshot_delete)
        self._create_snapshot()
        response = self._do_delete('os-snapshots/100')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_snapshots_detail(self):
        response = self._do_get('os-snapshots/detail')
        subs = self._get_regexes()
        self._verify_response('snapshots-detail-resp', subs, response, 200)

    def test_snapshots_list(self):
        response = self._do_get('os-snapshots')
        subs = self._get_regexes()
        self._verify_response('snapshots-list-resp', subs, response, 200)

    def test_snapshots_show(self):
        response = self._do_get('os-snapshots/100')
        subs = {
            'snapshot_name': 'Default name',
            'description': 'Default description'
        }
        subs.update(self._get_regexes())
        self._verify_response('snapshots-show-resp', subs, response, 200)


class AssistedVolumeSnapshotsJsonTest(ApiSampleTestBaseV2):
    """Assisted volume snapshots."""
    extension_name = ("nova.api.openstack.compute.contrib."
                      "assisted_volume_snapshots.Assisted_volume_snapshots")

    def _create_assisted_snapshot(self, subs):
        self.stubs.Set(compute_api.API, 'volume_snapshot_create',
                       fakes.stub_compute_volume_snapshot_create)

        response = self._do_post("os-assisted-volume-snapshots",
                                 "snapshot-create-assisted-req",
                                 subs)
        return response

    def test_snapshots_create_assisted(self):
        subs = {
            'snapshot_name': 'snap-001',
            'description': 'Daily backup',
            'volume_id': '521752a6-acf6-4b2d-bc7a-119f9148cd8c',
            'snapshot_id': '421752a6-acf6-4b2d-bc7a-119f9148cd8c',
            'type': 'qcow2',
            'new_file': 'new_file_name'
        }
        subs.update(self._get_regexes())
        response = self._create_assisted_snapshot(subs)
        self._verify_response("snapshot-create-assisted-resp",
                              subs, response, 200)

    def test_snapshots_delete_assisted(self):
        self.stubs.Set(compute_api.API, 'volume_snapshot_delete',
                       fakes.stub_compute_volume_snapshot_delete)
        snapshot_id = '100'
        response = self._do_delete(
                'os-assisted-volume-snapshots/%s?delete_info='
                '{"volume_id":"521752a6-acf6-4b2d-bc7a-119f9148cd8c"}'
                % snapshot_id)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, '')


class VolumeAttachmentsSampleBase(ServersSampleBase):
    def _stub_db_bdms_get_all_by_instance(self, server_id):

        def fake_bdms_get_all_by_instance(context, instance_uuid,
                                          use_slave=False):
            bdms = [
                fake_block_device.FakeDbBlockDeviceDict(
                {'id': 1, 'volume_id': 'a26887c6-c47b-4654-abb5-dfadf7d3f803',
                'instance_uuid': server_id, 'source_type': 'volume',
                'destination_type': 'volume', 'device_name': '/dev/sdd'}),
                fake_block_device.FakeDbBlockDeviceDict(
                {'id': 2, 'volume_id': 'a26887c6-c47b-4654-abb5-dfadf7d3f804',
                'instance_uuid': server_id, 'source_type': 'volume',
                'destination_type': 'volume', 'device_name': '/dev/sdc'})
            ]
            return bdms

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdms_get_all_by_instance)

    def _stub_compute_api_get(self):

        def fake_compute_api_get(self, context, instance_id,
                                 want_objects=False, expected_attrs=None):
            if want_objects:
                return fake_instance.fake_instance_obj(
                        context, **{'uuid': instance_id})
            else:
                return {'uuid': instance_id}

        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)


class VolumeAttachmentsSampleJsonTest(VolumeAttachmentsSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.volumes.Volumes")

    def test_attach_volume_to_server(self):
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(cinder.API, 'check_attach', lambda *a, **k: None)
        self.stubs.Set(cinder.API, 'reserve_volume', lambda *a, **k: None)
        device_name = '/dev/vdd'
        bdm = objects.BlockDeviceMapping()
        bdm['device_name'] = device_name
        self.stubs.Set(compute_manager.ComputeManager,
                       "reserve_block_device_name",
                       lambda *a, **k: bdm)
        self.stubs.Set(compute_manager.ComputeManager,
                       'attach_volume',
                       lambda *a, **k: None)
        self.stubs.Set(objects.BlockDeviceMapping, 'get_by_volume_id',
                       classmethod(lambda *a, **k: None))

        volume = fakes.stub_volume_get(None, context.get_admin_context(),
                                       'a26887c6-c47b-4654-abb5-dfadf7d3f803')
        subs = {
            'volume_id': volume['id'],
            'device': device_name
        }
        server_id = self._post_server()
        response = self._do_post('servers/%s/os-volume_attachments'
                                 % server_id,
                                 'attach-volume-to-server-req', subs)

        subs.update(self._get_regexes())
        self._verify_response('attach-volume-to-server-resp', subs,
                              response, 200)

    def test_list_volume_attachments(self):
        server_id = self._post_server()

        self._stub_db_bdms_get_all_by_instance(server_id)

        response = self._do_get('servers/%s/os-volume_attachments'
                                % server_id)
        subs = self._get_regexes()
        self._verify_response('list-volume-attachments-resp', subs,
                              response, 200)

    def test_volume_attachment_detail(self):
        server_id = self._post_server()
        attach_id = "a26887c6-c47b-4654-abb5-dfadf7d3f803"
        self._stub_db_bdms_get_all_by_instance(server_id)
        self._stub_compute_api_get()
        response = self._do_get('servers/%s/os-volume_attachments/%s'
                                % (server_id, attach_id))
        subs = self._get_regexes()
        self._verify_response('volume-attachment-detail-resp', subs,
                              response, 200)

    def test_volume_attachment_delete(self):
        server_id = self._post_server()
        attach_id = "a26887c6-c47b-4654-abb5-dfadf7d3f803"
        self._stub_db_bdms_get_all_by_instance(server_id)
        self._stub_compute_api_get()
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(compute_api.API, 'detach_volume', lambda *a, **k: None)
        response = self._do_delete('servers/%s/os-volume_attachments/%s'
                                   % (server_id, attach_id))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class VolumeAttachUpdateSampleJsonTest(VolumeAttachmentsSampleBase):
    extends_name = ("nova.api.openstack.compute.contrib.volumes.Volumes")
    extension_name = ("nova.api.openstack.compute.contrib."
                      "volume_attachment_update.Volume_attachment_update")

    def test_volume_attachment_update(self):
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        subs = {
            'volume_id': 'a26887c6-c47b-4654-abb5-dfadf7d3f805',
            'device': '/dev/sdd'
        }
        server_id = self._post_server()
        attach_id = 'a26887c6-c47b-4654-abb5-dfadf7d3f803'
        self._stub_db_bdms_get_all_by_instance(server_id)
        self._stub_compute_api_get()
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(compute_api.API, 'swap_volume', lambda *a, **k: None)
        response = self._do_put('servers/%s/os-volume_attachments/%s'
                                % (server_id, attach_id),
                                'update-volume-req',
                                subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class VolumesSampleJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.volumes.Volumes")

    def _get_volume_id(self):
        return 'a26887c6-c47b-4654-abb5-dfadf7d3f803'

    def _stub_volume(self, id, displayname="Volume Name",
                     displaydesc="Volume Description", size=100):
        volume = {
                  'id': id,
                  'size': size,
                  'availability_zone': 'zone1:host1',
                  'instance_uuid': '3912f2b4-c5ba-4aec-9165-872876fe202e',
                  'mountpoint': '/',
                  'status': 'in-use',
                  'attach_status': 'attached',
                  'name': 'vol name',
                  'display_name': displayname,
                  'display_description': displaydesc,
                  'created_at': datetime.datetime(2008, 12, 1, 11, 1, 55),
                  'snapshot_id': None,
                  'volume_type_id': 'fakevoltype',
                  'volume_metadata': [],
                  'volume_type': {'name': 'Backup'}
                  }
        return volume

    def _stub_volume_get(self, context, volume_id):
        return self._stub_volume(volume_id)

    def _stub_volume_delete(self, context, *args, **param):
        pass

    def _stub_volume_get_all(self, context, search_opts=None):
        id = self._get_volume_id()
        return [self._stub_volume(id)]

    def _stub_volume_create(self, context, size, name, description, snapshot,
                       **param):
        id = self._get_volume_id()
        return self._stub_volume(id)

    def setUp(self):
        super(VolumesSampleJsonTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)

        self.stubs.Set(cinder.API, "delete", self._stub_volume_delete)
        self.stubs.Set(cinder.API, "get", self._stub_volume_get)
        self.stubs.Set(cinder.API, "get_all", self._stub_volume_get_all)

    def _post_volume(self):
        subs_req = {
                'volume_name': "Volume Name",
                'volume_desc': "Volume Description",
        }

        self.stubs.Set(cinder.API, "create", self._stub_volume_create)
        response = self._do_post('os-volumes', 'os-volumes-post-req',
                                 subs_req)
        subs = self._get_regexes()
        subs.update(subs_req)
        self._verify_response('os-volumes-post-resp', subs, response, 200)

    def test_volumes_show(self):
        subs = {
                'volume_name': "Volume Name",
                'volume_desc': "Volume Description",
        }
        vol_id = self._get_volume_id()
        response = self._do_get('os-volumes/%s' % vol_id)
        subs.update(self._get_regexes())
        self._verify_response('os-volumes-get-resp', subs, response, 200)

    def test_volumes_index(self):
        subs = {
                'volume_name': "Volume Name",
                'volume_desc': "Volume Description",
        }
        response = self._do_get('os-volumes')
        subs.update(self._get_regexes())
        self._verify_response('os-volumes-index-resp', subs, response, 200)

    def test_volumes_detail(self):
        # For now, index and detail are the same.
        # See the volumes api
        subs = {
                'volume_name': "Volume Name",
                'volume_desc': "Volume Description",
        }
        response = self._do_get('os-volumes/detail')
        subs.update(self._get_regexes())
        self._verify_response('os-volumes-detail-resp', subs, response, 200)

    def test_volumes_create(self):
        self._post_volume()

    def test_volumes_delete(self):
        self._post_volume()
        vol_id = self._get_volume_id()
        response = self._do_delete('os-volumes/%s' % vol_id)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class MigrationsSamplesJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.migrations."
                      "Migrations")

    def _stub_migrations(self, context, filters):
        fake_migrations = [
            {
                'id': 1234,
                'source_node': 'node1',
                'dest_node': 'node2',
                'source_compute': 'compute1',
                'dest_compute': 'compute2',
                'dest_host': '1.2.3.4',
                'status': 'Done',
                'instance_uuid': 'instance_id_123',
                'old_instance_type_id': 1,
                'new_instance_type_id': 2,
                'created_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                'deleted_at': None,
                'deleted': False
            },
            {
                'id': 5678,
                'source_node': 'node10',
                'dest_node': 'node20',
                'source_compute': 'compute10',
                'dest_compute': 'compute20',
                'dest_host': '5.6.7.8',
                'status': 'Done',
                'instance_uuid': 'instance_id_456',
                'old_instance_type_id': 5,
                'new_instance_type_id': 6,
                'created_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
                'updated_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
                'deleted_at': None,
                'deleted': False
            }
        ]
        return fake_migrations

    def setUp(self):
        super(MigrationsSamplesJsonTest, self).setUp()
        self.stubs.Set(compute_api.API, 'get_migrations',
                       self._stub_migrations)

    def test_get_migrations(self):
        response = self._do_get('os-migrations')
        subs = self._get_regexes()

        self.assertEqual(response.status_code, 200)
        self._verify_response('migrations-get', subs, response, 200)


class PreserveEphemeralOnRebuildJsonTest(ServersSampleBase):
    extension_name = ('nova.api.openstack.compute.contrib.'
                      'preserve_ephemeral_rebuild.'
                      'Preserve_ephemeral_rebuild')

    def _test_server_action(self, uuid, action,
                            subs=None, resp_tpl=None, code=202):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-%s' % action.lower(),
                                 subs)
        if resp_tpl:
            subs.update(self._get_regexes())
            self._verify_response(resp_tpl, subs, response, code)
        else:
            self.assertEqual(response.status_code, code)
            self.assertEqual(response.content, "")

    def test_rebuild_server_preserve_ephemeral_false(self):
        uuid = self._post_server()
        image = self.api.get_images()[0]['id']
        subs = {'host': self._get_host(),
                'uuid': image,
                'name': 'foobar',
                'pass': 'seekr3t',
                'ip': '1.2.3.4',
                'ip6': 'fe80::100',
                'hostid': '[a-f0-9]+',
                'preserve_ephemeral': 'false'}
        self._test_server_action(uuid, 'rebuild', subs,
                                 'server-action-rebuild-resp')

    def test_rebuild_server_preserve_ephemeral_true(self):
        image = self.api.get_images()[0]['id']
        subs = {'host': self._get_host(),
                'uuid': image,
                'name': 'new-server-test',
                'pass': 'seekr3t',
                'ip': '1.2.3.4',
                'ip6': 'fe80::100',
                'hostid': '[a-f0-9]+',
                'preserve_ephemeral': 'true'}

        def fake_rebuild(self_, context, instance, image_href, admin_password,
                         **kwargs):
            self.assertTrue(kwargs['preserve_ephemeral'])
        self.stubs.Set(compute_api.API, 'rebuild', fake_rebuild)

        instance_uuid = self._post_server()
        response = self._do_post('servers/%s/action' % instance_uuid,
                                 'server-action-rebuild', subs)
        self.assertEqual(response.status_code, 202)


class ServerExternalEventsJsonTest(ServersSampleBase):
    extension_name = ('nova.api.openstack.compute.contrib.'
                      'server_external_events.Server_external_events')

    def test_create_event(self):
        instance_uuid = self._post_server()
        subs = {
            'uuid': instance_uuid,
            'name': 'network-changed',
            'status': 'completed',
            'tag': 'foo',
            }
        response = self._do_post('os-server-external-events',
                                 'event-create-req',
                                 subs)
        subs.update(self._get_regexes())
        self._verify_response('event-create-resp', subs, response, 200)


class ServerGroupsSampleJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                     ".server_groups.Server_groups")

    def _get_create_subs(self):
        return {'name': 'test'}

    def _post_server_group(self):
        """Verify the response status code and returns the UUID of the
        newly created server group.
        """
        subs = self._get_create_subs()
        response = self._do_post('os-server-groups',
                                 'server-groups-post-req', subs)
        subs = self._get_regexes()
        subs['name'] = 'test'
        return self._verify_response('server-groups-post-resp',
                                     subs, response, 200)

    def _create_server_group(self):
        subs = self._get_create_subs()
        return self._do_post('os-server-groups',
                             'server-groups-post-req', subs)

    def test_server_groups_post(self):
        return self._post_server_group()

    def test_server_groups_list(self):
        subs = self._get_create_subs()
        uuid = self._post_server_group()
        response = self._do_get('os-server-groups')
        subs.update(self._get_regexes())
        subs['id'] = uuid
        self._verify_response('server-groups-list-resp',
                              subs, response, 200)

    def test_server_groups_get(self):
        # Get api sample of server groups get request.
        subs = {'name': 'test'}
        uuid = self._post_server_group()
        subs['id'] = uuid
        response = self._do_get('os-server-groups/%s' % uuid)

        self._verify_response('server-groups-get-resp', subs, response, 200)

    def test_server_groups_delete(self):
        uuid = self._post_server_group()
        response = self._do_delete('os-server-groups/%s' % uuid)
        self.assertEqual(response.status_code, 204)


class ServerGroupQuotas_LimitsSampleJsonTest(LimitsSampleJsonTest):
    extension_name = ("nova.api.openstack.compute.contrib."
                      "server_group_quotas.Server_group_quotas")


class ServerGroupQuotas_UsedLimitsSamplesJsonTest(UsedLimitsSamplesJsonTest):
    extension_name = ("nova.api.openstack.compute.contrib."
               "server_group_quotas.Server_group_quotas")
    extends_name = ("nova.api.openstack.compute.contrib.used_limits."
                    "Used_limits")


class ServerGroupQuotas_QuotasSampleJsonTests(QuotasSampleJsonTests):
    extension_name = ("nova.api.openstack.compute.contrib."
               "server_group_quotas.Server_group_quotas")
    extends_name = "nova.api.openstack.compute.contrib.quotas.Quotas"


class ServerGroupQuotasQuota_ClassesSampleJsonTests(
           QuotaClassesSampleJsonTests):
    extension_name = ("nova.api.openstack.compute.contrib."
              "server_group_quotas.Server_group_quotas")
    extends_name = ("nova.api.openstack.compute.contrib.quota_classes."
                    "Quota_classes")


class ServerSortKeysJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.server_sort_keys"
                      ".Server_sort_keys")

    def test_servers_list(self):
        self._post_server()
        response = self._do_get('servers?sort_key=display_name&sort_dir=asc')
        subs = self._get_regexes()
        self._verify_response('server-sort-keys-list-resp', subs, response,
                              200)

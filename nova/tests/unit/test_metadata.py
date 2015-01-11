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

"""Tests for metadata service."""

import base64
import hashlib
import hmac
import re

try:
    import cPickle as pickle
except ImportError:
    import pickle

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
import webob

from nova.api.metadata import base
from nova.api.metadata import handler
from nova.api.metadata import password
from nova import block_device
from nova.compute import flavors
from nova.conductor import api as conductor_api
from nova import context
from nova import db
from nova.db.sqlalchemy import api
from nova import exception
from nova.network import api as network_api
from nova.network import model as network_model
from nova import objects
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_network
from nova.tests.unit.objects import test_security_group
from nova.virt import netutils

CONF = cfg.CONF

USER_DATA_STRING = ("This is an encoded string")
ENCODE_USER_DATA_STRING = base64.b64encode(USER_DATA_STRING)


def fake_inst_obj(context):
    inst = objects.Instance(
        context=context,
        id=1,
        uuid='b65cee2f-8c69-4aeb-be2f-f79742548fc2',
        project_id='test',
        key_name="mykey",
        key_data="ssh-rsa AAAAB3Nzai....N3NtHw== someuser@somehost",
        host='test',
        launch_index=1,
        reservation_id='r-xxxxxxxx',
        user_data=ENCODE_USER_DATA_STRING,
        image_ref=7,
        vcpus=1,
        fixed_ips=[],
        root_device_name='/dev/sda1',
        hostname='test.novadomain',
        display_name='my_displayname',
        metadata={},
        default_ephemeral_device=None,
        default_swap_device=None,
        system_metadata={})
    nwinfo = network_model.NetworkInfo([])
    inst.info_cache = objects.InstanceInfoCache(context=context,
                                                instance_uuid=inst.uuid,
                                                network_info=nwinfo)
    with mock.patch.object(inst, 'save'):
        inst.set_flavor(flavors.get_default_flavor())
    return inst


def return_non_existing_address(*args, **kwarg):
    raise exception.NotFound()


def fake_InstanceMetadata(stubs, inst_data, address=None,
                          sgroups=None, content=None, extra_md=None,
                          vd_driver=None, network_info=None):
    content = content or []
    extra_md = extra_md or {}
    if sgroups is None:
        sgroups = [dict(test_security_group.fake_secgroup,
                        name='default')]

    def sg_get(*args, **kwargs):
        return sgroups

    stubs.Set(api, 'security_group_get_by_instance', sg_get)
    return base.InstanceMetadata(inst_data, address=address,
        content=content, extra_md=extra_md,
        vd_driver=vd_driver, network_info=network_info)


def fake_request(stubs, mdinst, relpath, address="127.0.0.1",
                 fake_get_metadata=None, headers=None,
                 fake_get_metadata_by_instance_id=None):

    def get_metadata_by_remote_address(address):
        return mdinst

    app = handler.MetadataRequestHandler()

    if fake_get_metadata is None:
        fake_get_metadata = get_metadata_by_remote_address

    if stubs:
        stubs.Set(app, 'get_metadata_by_remote_address', fake_get_metadata)

        if fake_get_metadata_by_instance_id:
            stubs.Set(app, 'get_metadata_by_instance_id',
                      fake_get_metadata_by_instance_id)

    request = webob.Request.blank(relpath)
    request.remote_addr = address

    if headers is not None:
        request.headers.update(headers)

    response = request.get_response(app)
    return response


class MetadataTestCase(test.TestCase):
    def setUp(self):
        super(MetadataTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)
        self.flags(use_local=True, group='conductor')
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)

    def test_can_pickle_metadata(self):
        # Make sure that InstanceMetadata is possible to pickle. This is
        # required for memcache backend to work correctly.
        md = fake_InstanceMetadata(self.stubs, self.instance.obj_clone())
        pickle.dumps(md, protocol=0)

    def test_user_data(self):
        inst = self.instance.obj_clone()
        inst['user_data'] = base64.b64encode("happy")
        md = fake_InstanceMetadata(self.stubs, inst)
        self.assertEqual(
            md.get_ec2_metadata(version='2009-04-04')['user-data'], "happy")

    def test_no_user_data(self):
        inst = self.instance.obj_clone()
        inst.user_data = None
        md = fake_InstanceMetadata(self.stubs, inst)
        obj = object()
        self.assertEqual(
            md.get_ec2_metadata(version='2009-04-04').get('user-data', obj),
            obj)

    def test_security_groups(self):
        inst = self.instance.obj_clone()
        sgroups = [dict(test_security_group.fake_secgroup, name='default'),
                   dict(test_security_group.fake_secgroup, name='other')]
        expected = ['default', 'other']

        md = fake_InstanceMetadata(self.stubs, inst, sgroups=sgroups)
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['security-groups'], expected)

    def test_local_hostname_fqdn(self):
        md = fake_InstanceMetadata(self.stubs, self.instance.obj_clone())
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['local-hostname'],
            "%s.%s" % (self.instance['hostname'], CONF.dhcp_domain))

    def test_format_instance_mapping(self):
        # Make sure that _format_instance_mappings works.
        ctxt = None
        instance_ref0 = objects.Instance(**{'id': 0,
                         'uuid': 'e5fe5518-0288-4fa3-b0c4-c79764101b85',
                         'root_device_name': None,
                         'default_ephemeral_device': None,
                         'default_swap_device': None})
        instance_ref1 = objects.Instance(**{'id': 0,
                         'uuid': 'b65cee2f-8c69-4aeb-be2f-f79742548fc2',
                         'root_device_name': '/dev/sda1',
                         'default_ephemeral_device': None,
                         'default_swap_device': None})

        def fake_bdm_get(ctxt, uuid, use_slave=False):
            return [fake_block_device.FakeDbBlockDeviceDict(
                    {'volume_id': 87654321,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'delete_on_termination': True,
                     'device_name': '/dev/sdh'}),
                    fake_block_device.FakeDbBlockDeviceDict(
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': 'swap',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdc'}),
                    fake_block_device.FakeDbBlockDeviceDict(
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'source_type': 'blank',
                     'destination_type': 'local',
                     'guest_format': None,
                     'delete_on_termination': None,
                     'device_name': '/dev/sdb'})]

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdm_get)

        expected = {'ami': 'sda1',
                    'root': '/dev/sda1',
                    'ephemeral0': '/dev/sdb',
                    'swap': '/dev/sdc',
                    'ebs0': '/dev/sdh'}

        conductor_api.LocalAPI()

        self.assertEqual(base._format_instance_mapping(ctxt,
                         instance_ref0), block_device._DEFAULT_MAPPINGS)
        self.assertEqual(base._format_instance_mapping(ctxt,
                         instance_ref1), expected)

    def test_pubkey(self):
        md = fake_InstanceMetadata(self.stubs, self.instance.obj_clone())
        pubkey_ent = md.lookup("/2009-04-04/meta-data/public-keys")

        self.assertEqual(base.ec2_md_print(pubkey_ent),
            "0=%s" % self.instance['key_name'])
        self.assertEqual(base.ec2_md_print(pubkey_ent['0']['openssh-key']),
            self.instance['key_data'])

    def test_image_type_ramdisk(self):
        inst = self.instance.obj_clone()
        inst['ramdisk_id'] = 'ari-853667c0'
        md = fake_InstanceMetadata(self.stubs, inst)
        data = md.lookup("/latest/meta-data/ramdisk-id")

        self.assertIsNotNone(data)
        self.assertTrue(re.match('ari-[0-9a-f]{8}', data))

    def test_image_type_kernel(self):
        inst = self.instance.obj_clone()
        inst['kernel_id'] = 'aki-c2e26ff2'
        md = fake_InstanceMetadata(self.stubs, inst)
        data = md.lookup("/2009-04-04/meta-data/kernel-id")

        self.assertTrue(re.match('aki-[0-9a-f]{8}', data))

        self.assertEqual(
            md.lookup("/ec2/2009-04-04/meta-data/kernel-id"), data)

        inst.kernel_id = None
        md = fake_InstanceMetadata(self.stubs, inst)
        self.assertRaises(base.InvalidMetadataPath,
            md.lookup, "/2009-04-04/meta-data/kernel-id")

    def test_check_version(self):
        inst = self.instance.obj_clone()
        md = fake_InstanceMetadata(self.stubs, inst)

        self.assertTrue(md._check_version('1.0', '2009-04-04'))
        self.assertFalse(md._check_version('2009-04-04', '1.0'))

        self.assertFalse(md._check_version('2009-04-04', '2008-09-01'))
        self.assertTrue(md._check_version('2008-09-01', '2009-04-04'))

        self.assertTrue(md._check_version('2009-04-04', '2009-04-04'))

    def test_InstanceMetadata_uses_passed_network_info(self):
        network_info = []

        self.mox.StubOutWithMock(netutils, "get_injected_network_template")
        netutils.get_injected_network_template(network_info).AndReturn(False)
        self.mox.ReplayAll()

        base.InstanceMetadata(fake_inst_obj(self.context),
                              network_info=network_info)

    def test_InstanceMetadata_invoke_metadata_for_config_drive(self):
        inst = self.instance.obj_clone()
        inst_md = base.InstanceMetadata(inst)
        for (path, value) in inst_md.metadata_for_config_drive():
            self.assertIsNotNone(path)

    def test_InstanceMetadata_queries_network_API_when_needed(self):
        network_info_from_api = []

        self.mox.StubOutWithMock(netutils, "get_injected_network_template")

        netutils.get_injected_network_template(
            network_info_from_api).AndReturn(False)

        self.mox.ReplayAll()

        base.InstanceMetadata(fake_inst_obj(self.context))

    def test_local_ipv4(self):
        nw_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                          num_networks=2)
        expected_local = "192.168.1.100"
        md = fake_InstanceMetadata(self.stubs, self.instance,
                                   network_info=nw_info, address="fake")
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(expected_local, data['meta-data']['local-ipv4'])

    def test_local_ipv4_from_nw_info(self):
        nw_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                         num_networks=2)
        expected_local = "192.168.1.100"
        md = fake_InstanceMetadata(self.stubs, self.instance,
                                   network_info=nw_info)
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['local-ipv4'], expected_local)

    def test_local_ipv4_from_address(self):
        expected_local = "fake"
        md = fake_InstanceMetadata(self.stubs, self.instance,
                                   network_info=[], address="fake")
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['local-ipv4'], expected_local)


class OpenStackMetadataTestCase(test.TestCase):
    def setUp(self):
        super(OpenStackMetadataTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)
        self.flags(use_local=True, group='conductor')
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)

    def test_top_level_listing(self):
        # request for /openstack/<version>/ should show metadata.json
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        result = mdinst.lookup("/openstack")

        # trailing / should not affect anything
        self.assertEqual(result, mdinst.lookup("/openstack/"))

        # the 'content' should not show up in directory listing
        self.assertNotIn(base.CONTENT_DIR, result)
        self.assertIn('2012-08-10', result)
        self.assertIn('latest', result)

    def test_version_content_listing(self):
        # request for /openstack/<version>/ should show metadata.json
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        listing = mdinst.lookup("/openstack/2012-08-10")
        self.assertIn("meta_data.json", listing)

    def test_returns_apis_supported_in_havana_version(self):
        mdinst = fake_InstanceMetadata(self.stubs, self.instance)
        havana_supported_apis = mdinst.lookup("/openstack/2013-10-17")

        self.assertEqual([base.MD_JSON_NAME, base.UD_NAME, base.PASS_NAME,
                          base.VD_JSON_NAME], havana_supported_apis)

    def test_returns_apis_supported_in_folsom_version(self):
        mdinst = fake_InstanceMetadata(self.stubs, self.instance)
        folsom_supported_apis = mdinst.lookup("/openstack/2012-08-10")

        self.assertEqual([base.MD_JSON_NAME, base.UD_NAME],
                         folsom_supported_apis)

    def test_returns_apis_supported_in_grizzly_version(self):
        mdinst = fake_InstanceMetadata(self.stubs, self.instance)
        grizzly_supported_apis = mdinst.lookup("/openstack/2013-04-04")

        self.assertEqual([base.MD_JSON_NAME, base.UD_NAME, base.PASS_NAME],
                         grizzly_supported_apis)

    def test_metadata_json(self):
        inst = self.instance.obj_clone()
        content = [
            ('/etc/my.conf', "content of my.conf"),
            ('/root/hello', "content of /root/hello"),
        ]

        mdinst = fake_InstanceMetadata(self.stubs, inst,
            content=content)
        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        mdjson = mdinst.lookup("/openstack/latest/meta_data.json")

        mddict = jsonutils.loads(mdjson)

        self.assertEqual(mddict['uuid'], self.instance['uuid'])
        self.assertIn('files', mddict)

        self.assertIn('public_keys', mddict)
        self.assertEqual(mddict['public_keys'][self.instance['key_name']],
            self.instance['key_data'])

        self.assertIn('launch_index', mddict)
        self.assertEqual(mddict['launch_index'], self.instance['launch_index'])

        # verify that each of the things we put in content
        # resulted in an entry in 'files', that their content
        # there is as expected, and that /content lists them.
        for (path, content) in content:
            fent = [f for f in mddict['files'] if f['path'] == path]
            self.assertEqual(1, len(fent))
            fent = fent[0]
            found = mdinst.lookup("/openstack%s" % fent['content_path'])
            self.assertEqual(found, content)

    def test_extra_md(self):
        # make sure extra_md makes it through to metadata
        inst = self.instance.obj_clone()
        extra = {'foo': 'bar', 'mylist': [1, 2, 3],
                 'mydict': {"one": 1, "two": 2}}
        mdinst = fake_InstanceMetadata(self.stubs, inst, extra_md=extra)

        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        mddict = jsonutils.loads(mdjson)

        for key, val in extra.iteritems():
            self.assertEqual(mddict[key], val)

    def test_password(self):
        # make sure extra_md makes it through to metadata
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        result = mdinst.lookup("/openstack/latest/password")
        self.assertEqual(result, password.handle_password)

    def test_userdata(self):
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        userdata_found = mdinst.lookup("/openstack/2012-08-10/user_data")
        self.assertEqual(USER_DATA_STRING, userdata_found)

        # since we had user-data in this instance, it should be in listing
        self.assertIn('user_data', mdinst.lookup("/openstack/2012-08-10"))

        inst.user_data = None
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        # since this instance had no user-data it should not be there.
        self.assertNotIn('user_data', mdinst.lookup("/openstack/2012-08-10"))

        self.assertRaises(base.InvalidMetadataPath,
            mdinst.lookup, "/openstack/2012-08-10/user_data")

    def test_random_seed(self):
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        # verify that 2013-04-04 has the 'random' field
        mdjson = mdinst.lookup("/openstack/2013-04-04/meta_data.json")
        mddict = jsonutils.loads(mdjson)

        self.assertIn("random_seed", mddict)
        self.assertEqual(len(base64.b64decode(mddict["random_seed"])), 512)

        # verify that older version do not have it
        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        self.assertNotIn("random_seed", jsonutils.loads(mdjson))

    def test_no_dashes_in_metadata(self):
        # top level entries in meta_data should not contain '-' in their name
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self.stubs, inst)
        mdjson = jsonutils.loads(
            mdinst.lookup("/openstack/latest/meta_data.json"))

        self.assertEqual([], [k for k in mdjson.keys() if k.find("-") != -1])

    def test_vendor_data_presence(self):
        inst = self.instance.obj_clone()
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        # verify that 2013-10-17 has the vendor_data.json file
        result = mdinst.lookup("/openstack/2013-10-17")
        self.assertIn('vendor_data.json', result)

        # verify that older version do not have it
        result = mdinst.lookup("/openstack/2013-04-04")
        self.assertNotIn('vendor_data.json', result)

    def test_vendor_data_response(self):
        inst = self.instance.obj_clone()

        mydata = {'mykey1': 'value1', 'mykey2': 'value2'}

        class myVdriver(base.VendorDataDriver):
            def __init__(self, *args, **kwargs):
                super(myVdriver, self).__init__(*args, **kwargs)
                data = mydata.copy()
                uuid = kwargs['instance']['uuid']
                data.update({'inst_uuid': uuid})
                self.data = data

            def get(self):
                return self.data

        mdinst = fake_InstanceMetadata(self.stubs, inst, vd_driver=myVdriver)

        # verify that 2013-10-17 has the vendor_data.json file
        vdpath = "/openstack/2013-10-17/vendor_data.json"
        vd = jsonutils.loads(mdinst.lookup(vdpath))

        # the instance should be passed through, and our class copies the
        # uuid through to 'inst_uuid'.
        self.assertEqual(vd['inst_uuid'], inst['uuid'])

        # check the other expected values
        for k, v in mydata.items():
            self.assertEqual(vd[k], v)


class MetadataHandlerTestCase(test.TestCase):
    """Test that metadata is returning proper values."""

    def setUp(self):
        super(MetadataHandlerTestCase, self).setUp()

        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)
        self.flags(use_local=True, group='conductor')
        self.mdinst = fake_InstanceMetadata(self.stubs, self.instance,
            address=None, sgroups=None)

    def test_callable(self):

        def verify(req, meta_data):
            self.assertIsInstance(meta_data, CallableMD)
            return "foo"

        class CallableMD(object):
            def lookup(self, path_info):
                return verify

        response = fake_request(self.stubs, CallableMD(), "/bar")
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.body, "foo")

    def test_root(self):
        expected = "\n".join(base.VERSIONS) + "\nlatest"
        response = fake_request(self.stubs, self.mdinst, "/")
        self.assertEqual(response.body, expected)

        response = fake_request(self.stubs, self.mdinst, "/foo/../")
        self.assertEqual(response.body, expected)

    def test_root_metadata_proxy_enabled(self):
        self.flags(service_metadata_proxy=True,
                   group='neutron')

        expected = "\n".join(base.VERSIONS) + "\nlatest"
        response = fake_request(self.stubs, self.mdinst, "/")
        self.assertEqual(response.body, expected)

        response = fake_request(self.stubs, self.mdinst, "/foo/../")
        self.assertEqual(response.body, expected)

    def test_version_root(self):
        response = fake_request(self.stubs, self.mdinst, "/2009-04-04")
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("text/plain"))
        self.assertEqual(response.body, 'meta-data/\nuser-data')

        response = fake_request(self.stubs, self.mdinst, "/9999-99-99")
        self.assertEqual(response.status_int, 404)

    def test_json_data(self):
        response = fake_request(self.stubs, self.mdinst,
                                "/openstack/latest/meta_data.json")
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("application/json"))

        response = fake_request(self.stubs, self.mdinst,
                                "/openstack/latest/vendor_data.json")
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("application/json"))

    def test_user_data_non_existing_fixed_address(self):
        self.stubs.Set(network_api.API, 'get_fixed_ip_by_address',
                       return_non_existing_address)
        response = fake_request(None, self.mdinst, "/2009-04-04/user-data",
                                "127.1.1.1")
        self.assertEqual(response.status_int, 404)

    def test_fixed_address_none(self):
        response = fake_request(None, self.mdinst,
                                relpath="/2009-04-04/user-data", address=None)
        self.assertEqual(response.status_int, 500)

    def test_invalid_path_is_404(self):
        response = fake_request(self.stubs, self.mdinst,
                                relpath="/2009-04-04/user-data-invalid")
        self.assertEqual(response.status_int, 404)

    def test_user_data_with_use_forwarded_header(self):
        expected_addr = "192.192.192.2"

        def fake_get_metadata(address):
            if address == expected_addr:
                return self.mdinst
            else:
                raise Exception("Expected addr of %s, got %s" %
                                (expected_addr, address))

        self.flags(use_forwarded_for=True)
        response = fake_request(self.stubs, self.mdinst,
                                relpath="/2009-04-04/user-data",
                                address="168.168.168.1",
                                fake_get_metadata=fake_get_metadata,
                                headers={'X-Forwarded-For': expected_addr})

        self.assertEqual(response.status_int, 200)
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("text/plain"))
        self.assertEqual(response.body,
                         base64.b64decode(self.instance['user_data']))

        response = fake_request(self.stubs, self.mdinst,
                                relpath="/2009-04-04/user-data",
                                address="168.168.168.1",
                                fake_get_metadata=fake_get_metadata,
                                headers=None)
        self.assertEqual(response.status_int, 500)

    @mock.patch('nova.utils.constant_time_compare')
    def test_by_instance_id_uses_constant_time_compare(self, mock_compare):
        mock_compare.side_effect = test.TestingException

        req = webob.Request.blank('/')
        hnd = handler.MetadataRequestHandler()

        req.headers['X-Instance-ID'] = 'fake-inst'
        req.headers['X-Instance-ID-Signature'] = 'fake-sig'
        req.headers['X-Tenant-ID'] = 'fake-proj'

        self.assertRaises(test.TestingException,
                          hnd._handle_instance_id_request, req)

        self.assertEqual(1, mock_compare.call_count)

    def test_user_data_with_neutron_instance_id(self):
        expected_instance_id = 'a-b-c-d'

        def fake_get_metadata(instance_id, remote_address):
            if remote_address is None:
                raise Exception('Expected X-Forwared-For header')
            elif instance_id == expected_instance_id:
                return self.mdinst
            else:
                # raise the exception to aid with 500 response code test
                raise Exception("Expected instance_id of %s, got %s" %
                                (expected_instance_id, instance_id))

        signed = hmac.new(
            CONF.neutron.metadata_proxy_shared_secret,
            expected_instance_id,
            hashlib.sha256).hexdigest()

        # try a request with service disabled
        response = fake_request(
            self.stubs, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            headers={'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})
        self.assertEqual(response.status_int, 200)

        # now enable the service
        self.flags(service_metadata_proxy=True,
                   group='neutron')
        response = fake_request(
            self.stubs, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=fake_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 200)
        response_ctype = response.headers['Content-Type']
        self.assertTrue(response_ctype.startswith("text/plain"))
        self.assertEqual(response.body,
                         base64.b64decode(self.instance['user_data']))

        # mismatched signature
        response = fake_request(
            self.stubs, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=fake_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': ''})

        self.assertEqual(response.status_int, 403)

        # missing X-Tenant-ID from request
        response = fake_request(
            self.stubs, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=fake_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 400)

        # mismatched X-Tenant-ID
        response = fake_request(
            self.stubs, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=fake_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'FAKE',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 404)

        # without X-Forwarded-For
        response = fake_request(
            self.stubs, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=fake_get_metadata,
            headers={'X-Instance-ID': 'a-b-c-d',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})

        self.assertEqual(response.status_int, 500)

        # unexpected Instance-ID
        signed = hmac.new(
            CONF.neutron.metadata_proxy_shared_secret,
           'z-z-z-z',
           hashlib.sha256).hexdigest()

        response = fake_request(
            self.stubs, self.mdinst,
            relpath="/2009-04-04/user-data",
            address="192.192.192.2",
            fake_get_metadata_by_instance_id=fake_get_metadata,
            headers={'X-Forwarded-For': '192.192.192.2',
                     'X-Instance-ID': 'z-z-z-z',
                     'X-Tenant-ID': 'test',
                     'X-Instance-ID-Signature': signed})
        self.assertEqual(response.status_int, 500)

    def test_get_metadata(self):
        def _test_metadata_path(relpath):
            # recursively confirm a http 200 from all meta-data elements
            # available at relpath.
            response = fake_request(self.stubs, self.mdinst,
                                    relpath=relpath)
            for item in response.body.split('\n'):
                if 'public-keys' in relpath:
                    # meta-data/public-keys/0=keyname refers to
                    # meta-data/public-keys/0
                    item = item.split('=')[0]
                if item.endswith('/'):
                    path = relpath + '/' + item
                    _test_metadata_path(path)
                    continue

                path = relpath + '/' + item
                response = fake_request(self.stubs, self.mdinst, relpath=path)
                self.assertEqual(response.status_int, 200, message=path)

        _test_metadata_path('/2009-04-04/meta-data')


class MetadataPasswordTestCase(test.TestCase):
    def setUp(self):
        super(MetadataPasswordTestCase, self).setUp()
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)
        self.context = context.RequestContext('fake', 'fake')
        self.instance = fake_inst_obj(self.context)
        self.flags(use_local=True, group='conductor')
        self.mdinst = fake_InstanceMetadata(self.stubs, self.instance,
            address=None, sgroups=None)
        self.flags(use_local=True, group='conductor')

    def test_get_password(self):
        request = webob.Request.blank('')
        self.mdinst.password = 'foo'
        result = password.handle_password(request, self.mdinst)
        self.assertEqual(result, 'foo')

    def test_bad_method(self):
        request = webob.Request.blank('')
        request.method = 'PUT'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          password.handle_password, request, self.mdinst)

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def _try_set_password(self, get_by_uuid, val='bar'):
        request = webob.Request.blank('')
        request.method = 'POST'
        request.body = val
        get_by_uuid.return_value = self.instance

        with mock.patch.object(self.instance, 'save') as save:
            password.handle_password(request, self.mdinst)
            save.assert_called_once_with()

        self.assertIn('password_0', self.instance.system_metadata)

    def test_set_password(self):
        self.mdinst.password = ''
        self._try_set_password()

    def test_conflict(self):
        self.mdinst.password = 'foo'
        self.assertRaises(webob.exc.HTTPConflict,
                          self._try_set_password)

    def test_too_large(self):
        self.mdinst.password = ''
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._try_set_password,
                          val=('a' * (password.MAX_SIZE + 1)))

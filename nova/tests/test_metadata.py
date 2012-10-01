# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from copy import copy
import json
import re

import webob

from nova.api.metadata import base
from nova.api.metadata import handler
from nova import block_device
from nova import db
from nova.db.sqlalchemy import api
from nova import exception
from nova import flags
from nova.network import api as network_api
from nova import test
from nova.tests import fake_network

FLAGS = flags.FLAGS

USER_DATA_STRING = ("This is an encoded string")
ENCODE_USER_DATA_STRING = base64.b64encode(USER_DATA_STRING)

INSTANCES = (
    {'id': 1,
     'uuid': 'b65cee2f-8c69-4aeb-be2f-f79742548fc2',
     'name': 'fake',
     'project_id': 'test',
     'key_name': "mykey",
     'key_data': "ssh-rsa AAAAB3Nzai....N3NtHw== someuser@somehost",
     'host': 'test',
     'launch_index': 1,
     'instance_type': {'name': 'm1.tiny'},
     'reservation_id': 'r-xxxxxxxx',
     'user_data': ENCODE_USER_DATA_STRING,
     'image_ref': 7,
     'vcpus': 1,
     'fixed_ips': [],
     'root_device_name': '/dev/sda1',
     'info_cache': {'network_info': []},
     'hostname': 'test.novadomain',
     'display_name': 'my_displayname',
    },
)


def return_non_existing_address(*args, **kwarg):
    raise exception.NotFound()


def fake_InstanceMetadata(stubs, inst_data, address=None,
    sgroups=None, content=[], extra_md={}):

    if sgroups is None:
        sgroups = [{'name': 'default'}]

    def sg_get(*args, **kwargs):
        return sgroups

    stubs.Set(api, 'security_group_get_by_instance', sg_get)
    return base.InstanceMetadata(inst_data, address=address,
        content=content, extra_md=extra_md)


def fake_request(stubs, mdinst, relpath, address="127.0.0.1",
                 fake_get_metadata=None, headers=None):

    def get_metadata(address):
        return mdinst

    app = handler.MetadataRequestHandler()

    if fake_get_metadata is None:
        fake_get_metadata = get_metadata

    if stubs:
        stubs.Set(app, 'get_metadata', fake_get_metadata)

    request = webob.Request.blank(relpath)
    request.remote_addr = address

    if headers is not None:
        request.headers.update(headers)

    response = request.get_response(app)
    return response


class MetadataTestCase(test.TestCase):
    def setUp(self):
        super(MetadataTestCase, self).setUp()
        self.instance = INSTANCES[0]
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs,
                                                          spectacular=True)

    def test_user_data(self):
        inst = copy(self.instance)
        inst['user_data'] = base64.b64encode("happy")
        md = fake_InstanceMetadata(self.stubs, inst)
        self.assertEqual(
            md.get_ec2_metadata(version='2009-04-04')['user-data'], "happy")

    def test_no_user_data(self):
        inst = copy(self.instance)
        del inst['user_data']
        md = fake_InstanceMetadata(self.stubs, inst)
        obj = object()
        self.assertEqual(
            md.get_ec2_metadata(version='2009-04-04').get('user-data', obj),
            obj)

    def test_security_groups(self):
        inst = copy(self.instance)
        sgroups = [{'name': 'default'}, {'name': 'other'}]
        expected = ['default', 'other']

        md = fake_InstanceMetadata(self.stubs, inst, sgroups=sgroups)
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['security-groups'], expected)

    def test_local_hostname_fqdn(self):
        md = fake_InstanceMetadata(self.stubs, copy(self.instance))
        data = md.get_ec2_metadata(version='2009-04-04')
        self.assertEqual(data['meta-data']['local-hostname'],
            "%s.%s" % (self.instance['hostname'], FLAGS.dhcp_domain))

    def test_format_instance_mapping(self):
        """Make sure that _format_instance_mappings works"""
        ctxt = None
        instance_ref0 = {'id': 0,
                         'uuid': 'e5fe5518-0288-4fa3-b0c4-c79764101b85',
                         'root_device_name': None}
        instance_ref1 = {'id': 0,
                         'uuid': 'b65cee2f-8c69-4aeb-be2f-f79742548fc2',
                         'root_device_name': '/dev/sda1'}

        def fake_bdm_get(ctxt, uuid):
            return [{'volume_id': 87654321,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': None,
                     'delete_on_termination': True,
                     'device_name': '/dev/sdh'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'swap',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdc'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'ephemeral0',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdb'}]

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdm_get)

        expected = {'ami': 'sda1',
                    'root': '/dev/sda1',
                    'ephemeral0': '/dev/sdb',
                    'swap': '/dev/sdc',
                    'ebs0': '/dev/sdh'}

        self.assertEqual(base._format_instance_mapping(ctxt, instance_ref0),
                         block_device._DEFAULT_MAPPINGS)
        self.assertEqual(base._format_instance_mapping(ctxt, instance_ref1),
                         expected)

    def test_pubkey(self):
        md = fake_InstanceMetadata(self.stubs, copy(self.instance))
        pubkey_ent = md.lookup("/2009-04-04/meta-data/public-keys")

        self.assertEqual(base.ec2_md_print(pubkey_ent),
            "0=%s" % self.instance['key_name'])
        self.assertEqual(base.ec2_md_print(pubkey_ent['0']['openssh-key']),
            self.instance['key_data'])

    def test_image_type_ramdisk(self):
        inst = copy(self.instance)
        inst['ramdisk_id'] = 'ari-853667c0'
        md = fake_InstanceMetadata(self.stubs, inst)
        data = md.lookup("/latest/meta-data/ramdisk-id")

        self.assertTrue(data is not None)
        self.assertTrue(re.match('ari-[0-9a-f]{8}', data))

    def test_image_type_kernel(self):
        inst = copy(self.instance)
        inst['kernel_id'] = 'aki-c2e26ff2'
        md = fake_InstanceMetadata(self.stubs, inst)
        data = md.lookup("/2009-04-04/meta-data/kernel-id")

        self.assertTrue(re.match('aki-[0-9a-f]{8}', data))

        self.assertEqual(
            md.lookup("/ec2/2009-04-04/meta-data/kernel-id"), data)

        del inst['kernel_id']
        md = fake_InstanceMetadata(self.stubs, inst)
        self.assertRaises(base.InvalidMetadataPath,
            md.lookup, "/2009-04-04/meta-data/kernel-id")

    def test_check_version(self):
        inst = copy(self.instance)
        md = fake_InstanceMetadata(self.stubs, inst)

        self.assertTrue(md._check_version('1.0', '2009-04-04'))
        self.assertFalse(md._check_version('2009-04-04', '1.0'))

        self.assertFalse(md._check_version('2009-04-04', '2008-09-01'))
        self.assertTrue(md._check_version('2008-09-01', '2009-04-04'))

        self.assertTrue(md._check_version('2009-04-04', '2009-04-04'))


class OpenStackMetadataTestCase(test.TestCase):
    def setUp(self):
        super(OpenStackMetadataTestCase, self).setUp()
        self.instance = INSTANCES[0]
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs,
                                                          spectacular=True)

    def test_top_level_listing(self):
        # request for /openstack/<version>/ should show metadata.json
        inst = copy(self.instance)
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        listing = mdinst.lookup("/openstack/")

        result = mdinst.lookup("/openstack")

        # trailing / should not affect anything
        self.assertEqual(result, mdinst.lookup("/openstack"))

        # the 'content' should not show up in directory listing
        self.assertTrue(base.CONTENT_DIR not in result)
        self.assertTrue('2012-08-10' in result)
        self.assertTrue('latest' in result)

    def test_version_content_listing(self):
        # request for /openstack/<version>/ should show metadata.json
        inst = copy(self.instance)
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        listing = mdinst.lookup("/openstack/2012-08-10")
        self.assertTrue("meta_data.json" in listing)

    def test_metadata_json(self):
        inst = copy(self.instance)
        content = [
            ('/etc/my.conf', "content of my.conf"),
            ('/root/hello', "content of /root/hello"),
        ]

        mdinst = fake_InstanceMetadata(self.stubs, inst,
            content=content)
        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        mdjson = mdinst.lookup("/openstack/latest/meta_data.json")

        mddict = json.loads(mdjson)

        self.assertEqual(mddict['uuid'], self.instance['uuid'])
        self.assertTrue('files' in mddict)

        self.assertTrue('public_keys' in mddict)
        self.assertEqual(mddict['public_keys'][self.instance['key_name']],
            self.instance['key_data'])

        self.assertTrue('launch_index' in mddict)
        self.assertEqual(mddict['launch_index'], self.instance['launch_index'])

        # verify that each of the things we put in content
        # resulted in an entry in 'files', that their content
        # there is as expected, and that /content lists them.
        for (path, content) in content:
            fent = [f for f in mddict['files'] if f['path'] == path]
            self.assertTrue((len(fent) == 1))
            fent = fent[0]
            found = mdinst.lookup("/openstack%s" % fent['content_path'])
            self.assertEqual(found, content)

    def test_extra_md(self):
        # make sure extra_md makes it through to metadata
        inst = copy(self.instance)
        extra = {'foo': 'bar', 'mylist': [1, 2, 3],
                 'mydict': {"one": 1, "two": 2}}
        mdinst = fake_InstanceMetadata(self.stubs, inst, extra_md=extra)

        mdjson = mdinst.lookup("/openstack/2012-08-10/meta_data.json")
        mddict = json.loads(mdjson)

        for key, val in extra.iteritems():
            self.assertEqual(mddict[key], val)

    def test_userdata(self):
        inst = copy(self.instance)
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        userdata_found = mdinst.lookup("/openstack/2012-08-10/user_data")
        self.assertEqual(USER_DATA_STRING, userdata_found)

        # since we had user-data in this instance, it should be in listing
        self.assertTrue('user_data' in mdinst.lookup("/openstack/2012-08-10"))

        del inst['user_data']
        mdinst = fake_InstanceMetadata(self.stubs, inst)

        # since this instance had no user-data it should not be there.
        self.assertFalse('user-data' in mdinst.lookup("/openstack/2012-08-10"))

        self.assertRaises(base.InvalidMetadataPath,
            mdinst.lookup, "/openstack/2012-08-10/user_data")


class MetadataHandlerTestCase(test.TestCase):
    """Test that metadata is returning proper values."""

    def setUp(self):
        super(MetadataHandlerTestCase, self).setUp()

        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs,
                                                          spectacular=True)
        self.instance = INSTANCES[0]
        self.mdinst = fake_InstanceMetadata(self.stubs, self.instance,
            address=None, sgroups=None)

    def test_root(self):
        expected = "\n".join(base.VERSIONS) + "\nlatest"
        response = fake_request(self.stubs, self.mdinst, "/")
        self.assertEqual(response.body, expected)

        response = fake_request(self.stubs, self.mdinst, "/foo/../")
        self.assertEqual(response.body, expected)

    def test_version_root(self):
        response = fake_request(self.stubs, self.mdinst, "/2009-04-04")
        self.assertEqual(response.body, 'meta-data/\nuser-data')

        response = fake_request(self.stubs, self.mdinst, "/9999-99-99")
        self.assertEqual(response.status_int, 404)

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
        self.assertEqual(response.body,
                         base64.b64decode(self.instance['user_data']))

        response = fake_request(self.stubs, self.mdinst,
                                relpath="/2009-04-04/user-data",
                                address="168.168.168.1",
                                fake_get_metadata=fake_get_metadata,
                                headers=None)
        self.assertEqual(response.status_int, 500)

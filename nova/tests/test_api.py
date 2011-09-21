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

"""Unit tests for the API endpoint"""

import boto
from boto.ec2 import regioninfo
from boto.exception import EC2ResponseError
import datetime
import httplib
import random
import StringIO
import webob

from nova import block_device
from nova import context
from nova import exception
from nova import test
from nova import wsgi
from nova.api import auth
from nova.api import ec2
from nova.api.ec2 import apirequest
from nova.api.ec2 import cloud
from nova.api.ec2 import ec2utils


class FakeHttplibSocket(object):
    """a fake socket implementation for httplib.HTTPResponse, trivial"""
    def __init__(self, response_string):
        self.response_string = response_string
        self._buffer = StringIO.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer"""
        return self._buffer


class FakeHttplibConnection(object):
    """A fake httplib.HTTPConnection for boto to use

    requests made via this connection actually get translated and routed into
    our WSGI app, we then wait for the response and turn it back into
    the httplib.HTTPResponse that boto expects.
    """
    def __init__(self, app, host, is_secure=False):
        self.app = app
        self.host = host

    def request(self, method, path, data, headers):
        req = webob.Request.blank(path)
        req.method = method
        req.body = data
        req.headers = headers
        req.headers['Accept'] = 'text/html'
        req.host = self.host
        # Call the WSGI app, get the HTTP response
        resp = str(req.get_response(self.app))
        # For some reason, the response doesn't have "HTTP/1.0 " prepended; I
        # guess that's a function the web server usually provides.
        resp = "HTTP/1.0 %s" % resp
        self.sock = FakeHttplibSocket(resp)
        self.http_response = httplib.HTTPResponse(self.sock)
        self.http_response.begin()

    def getresponse(self):
        return self.http_response

    def getresponsebody(self):
        return self.sock.response_string

    def close(self):
        """Required for compatibility with boto/tornado"""
        pass


class XmlConversionTestCase(test.TestCase):
    """Unit test api xml conversion"""
    def test_number_conversion(self):
        conv = ec2utils._try_convert
        self.assertEqual(conv('None'), None)
        self.assertEqual(conv('True'), True)
        self.assertEqual(conv('true'), True)
        self.assertEqual(conv('False'), False)
        self.assertEqual(conv('false'), False)
        self.assertEqual(conv('0'), 0)
        self.assertEqual(conv('42'), 42)
        self.assertEqual(conv('3.14'), 3.14)
        self.assertEqual(conv('-57.12'), -57.12)
        self.assertEqual(conv('0x57'), 0x57)
        self.assertEqual(conv('-0x57'), -0x57)
        self.assertEqual(conv('-'), '-')
        self.assertEqual(conv('-0'), 0)


class Ec2utilsTestCase(test.TestCase):
    def test_ec2_id_to_id(self):
        self.assertEqual(ec2utils.ec2_id_to_id('i-0000001e'), 30)
        self.assertEqual(ec2utils.ec2_id_to_id('ami-1d'), 29)
        self.assertEqual(ec2utils.ec2_id_to_id('snap-0000001c'), 28)
        self.assertEqual(ec2utils.ec2_id_to_id('vol-0000001b'), 27)

    def test_bad_ec2_id(self):
        self.assertRaises(exception.InvalidEc2Id,
                          ec2utils.ec2_id_to_id,
                          'badone')

    def test_id_to_ec2_id(self):
        self.assertEqual(ec2utils.id_to_ec2_id(30), 'i-0000001e')
        self.assertEqual(ec2utils.id_to_ec2_id(29, 'ami-%08x'), 'ami-0000001d')
        self.assertEqual(ec2utils.id_to_ec2_snap_id(28), 'snap-0000001c')
        self.assertEqual(ec2utils.id_to_ec2_vol_id(27), 'vol-0000001b')

    def test_dict_from_dotted_str(self):
        in_str = [('BlockDeviceMapping.1.DeviceName', '/dev/sda1'),
                  ('BlockDeviceMapping.1.Ebs.SnapshotId', 'snap-0000001c'),
                  ('BlockDeviceMapping.1.Ebs.VolumeSize', '80'),
                  ('BlockDeviceMapping.1.Ebs.DeleteOnTermination', 'false'),
                  ('BlockDeviceMapping.2.DeviceName', '/dev/sdc'),
                  ('BlockDeviceMapping.2.VirtualName', 'ephemeral0')]
        expected_dict = {
            'block_device_mapping': {
            '1': {'device_name': '/dev/sda1',
                  'ebs': {'snapshot_id': 'snap-0000001c',
                          'volume_size': 80,
                          'delete_on_termination': False}},
            '2': {'device_name': '/dev/sdc',
                  'virtual_name': 'ephemeral0'}}}
        out_dict = ec2utils.dict_from_dotted_str(in_str)

        self.assertDictMatch(out_dict, expected_dict)

    def test_properties_root_defice_name(self):
        mappings = [{"device": "/dev/sda1", "virtual": "root"}]
        properties0 = {'mappings': mappings}
        properties1 = {'root_device_name': '/dev/sdb', 'mappings': mappings}

        root_device_name = block_device.properties_root_device_name(
            properties0)
        self.assertEqual(root_device_name, '/dev/sda1')

        root_device_name = block_device.properties_root_device_name(
            properties1)
        self.assertEqual(root_device_name, '/dev/sdb')

    def test_mapping_prepend_dev(self):
        mappings = [
            {'virtual': 'ami',
             'device': 'sda1'},
            {'virtual': 'root',
             'device': '/dev/sda1'},

            {'virtual': 'swap',
             'device': 'sdb1'},
            {'virtual': 'swap',
             'device': '/dev/sdb2'},

            {'virtual': 'ephemeral0',
            'device': 'sdc1'},
            {'virtual': 'ephemeral1',
             'device': '/dev/sdc1'}]
        expected_result = [
            {'virtual': 'ami',
             'device': 'sda1'},
            {'virtual': 'root',
             'device': '/dev/sda1'},

            {'virtual': 'swap',
             'device': '/dev/sdb1'},
            {'virtual': 'swap',
             'device': '/dev/sdb2'},

            {'virtual': 'ephemeral0',
             'device': '/dev/sdc1'},
            {'virtual': 'ephemeral1',
             'device': '/dev/sdc1'}]
        self.assertDictListMatch(block_device.mappings_prepend_dev(mappings),
                                 expected_result)


class ApiEc2TestCase(test.TestCase):
    """Unit test for the cloud controller on an EC2 API"""
    def setUp(self):
        super(ApiEc2TestCase, self).setUp()
        self.host = '127.0.0.1'
        # NOTE(vish): skipping the Authorizer
        roles = ['sysadmin', 'netadmin']
        ctxt = context.RequestContext('fake', 'fake', roles=roles)
        self.app = auth.InjectContext(ctxt,
                ec2.Requestify(ec2.Authorizer(ec2.Executor()),
                               'nova.api.ec2.cloud.CloudController'))

    def expect_http(self, host=None, is_secure=False, api_version=None):
        """Returns a new EC2 connection"""
        self.ec2 = boto.connect_ec2(
                aws_access_key_id='fake',
                aws_secret_access_key='fake',
                is_secure=False,
                region=regioninfo.RegionInfo(None, 'test', self.host),
                port=8773,
                path='/services/Cloud')
        if api_version:
            self.ec2.APIVersion = api_version

        self.mox.StubOutWithMock(self.ec2, 'new_http_connection')
        self.http = FakeHttplibConnection(
                self.app, '%s:8773' % (self.host), False)
        # pylint: disable=E1103
        if boto.Version >= '2':
            self.ec2.new_http_connection(host or '%s:8773' % (self.host),
                is_secure).AndReturn(self.http)
        else:
            self.ec2.new_http_connection(host, is_secure).AndReturn(self.http)
        return self.http

    def test_return_valid_isoformat(self):
        """
            Ensure that the ec2 api returns datetime in xs:dateTime
            (which apparently isn't datetime.isoformat())
            NOTE(ken-pepple): https://bugs.launchpad.net/nova/+bug/721297
        """
        conv = apirequest._database_to_isoformat
        # sqlite database representation with microseconds
        time_to_convert = datetime.datetime.strptime(
                            "2011-02-21 20:14:10.634276",
                            "%Y-%m-%d %H:%M:%S.%f")
        self.assertEqual(
                        conv(time_to_convert),
                        '2011-02-21T20:14:10Z')
        # mysqlite database representation
        time_to_convert = datetime.datetime.strptime(
                            "2011-02-21 19:56:18",
                            "%Y-%m-%d %H:%M:%S")
        self.assertEqual(
                        conv(time_to_convert),
                        '2011-02-21T19:56:18Z')

    def test_xmlns_version_matches_request_version(self):
        self.expect_http(api_version='2010-10-30')
        self.mox.ReplayAll()

        # Any request should be fine
        self.ec2.get_all_instances()
        self.assertTrue(self.ec2.APIVersion in self.http.getresponsebody(),
                       'The version in the xmlns of the response does '
                       'not match the API version given in the request.')

    def test_describe_instances(self):
        """Test that, after creating a user and a project, the describe
        instances call to the API works properly"""
        self.expect_http()
        self.mox.ReplayAll()
        self.assertEqual(self.ec2.get_all_instances(), [])

    def test_terminate_invalid_instance(self):
        """Attempt to terminate an invalid instance"""
        self.expect_http()
        self.mox.ReplayAll()
        self.assertRaises(EC2ResponseError, self.ec2.terminate_instances,
                            "i-00000005")

    def test_get_all_key_pairs(self):
        """Test that, after creating a user and project and generating
         a key pair, that the API call to list key pairs works properly"""
        self.expect_http()
        self.mox.ReplayAll()
        keyname = "".join(random.choice("sdiuisudfsdcnpaqwertasd") \
                          for x in range(random.randint(4, 8)))
        # NOTE(vish): create depends on pool, so call helper directly
        cloud._gen_key(context.get_admin_context(), 'fake', keyname)

        rv = self.ec2.get_all_key_pairs()
        results = [k for k in rv if k.name == keyname]
        self.assertEquals(len(results), 1)

    def test_create_duplicate_key_pair(self):
        """Test that, after successfully generating a keypair,
        requesting a second keypair with the same name fails sanely"""
        self.expect_http()
        self.mox.ReplayAll()
        keyname = "".join(random.choice("sdiuisudfsdcnpaqwertasd") \
                          for x in range(random.randint(4, 8)))
        # NOTE(vish): create depends on pool, so call helper directly
        self.ec2.create_key_pair('test')

        try:
            self.ec2.create_key_pair('test')
        except EC2ResponseError, e:
            if e.code == 'KeyPairExists':
                pass
            else:
                self.fail("Unexpected EC2ResponseError: %s "
                          "(expected KeyPairExists)" % e.code)
        else:
            self.fail('Exception not raised.')

    def test_get_all_security_groups(self):
        """Test that we can retrieve security groups"""
        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()

        self.assertEquals(len(rv), 1)
        self.assertEquals(rv[0].name, 'default')

    def test_create_delete_security_group(self):
        """Test that we can create a security group"""
        self.expect_http()
        self.mox.ReplayAll()

        security_group_name = "".join(random.choice("sdiuisudfsdcnpaqwertasd")
                                      for x in range(random.randint(4, 8)))

        self.ec2.create_security_group(security_group_name, 'test group')

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()
        self.assertEquals(len(rv), 2)
        self.assertTrue(security_group_name in [group.name for group in rv])

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

    def test_group_name_valid_chars_security_group(self):
        """ Test that we sanely handle invalid security group names.
         API Spec states we should only accept alphanumeric characters,
         spaces, dashes, and underscores. """
        self.expect_http()
        self.mox.ReplayAll()

        # Test block group_name of non alphanumeric characters, spaces,
        # dashes, and underscores.
        security_group_name = "aa #^% -=99"

        self.assertRaises(EC2ResponseError, self.ec2.create_security_group,
                          security_group_name, 'test group')

    def test_group_name_valid_length_security_group(self):
        """Test that we sanely handle invalid security group names.
         API Spec states that the length should not exceed 255 chars """
        self.expect_http()
        self.mox.ReplayAll()

        # Test block group_name > 255 chars
        security_group_name = "".join(random.choice("poiuytrewqasdfghjklmnbvc")
                                      for x in range(random.randint(256, 266)))

        self.assertRaises(EC2ResponseError, self.ec2.create_security_group,
                          security_group_name, 'test group')

    def test_authorize_revoke_security_group_cidr(self):
        """
        Test that we can add and remove CIDR based rules
        to a security group
        """
        self.expect_http()
        self.mox.ReplayAll()

        security_group_name = "".join(random.choice("sdiuisudfsdcnpaqwertasd")
                                      for x in range(random.randint(4, 8)))

        group = self.ec2.create_security_group(security_group_name,
                                               'test group')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.authorize('tcp', 80, 81, '0.0.0.0/0')

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()

        group = [grp for grp in rv if grp.name == security_group_name][0]

        self.assertEquals(len(group.rules), 1)
        self.assertEquals(int(group.rules[0].from_port), 80)
        self.assertEquals(int(group.rules[0].to_port), 81)
        self.assertEquals(len(group.rules[0].grants), 1)
        self.assertEquals(str(group.rules[0].grants[0]), '0.0.0.0/0')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.revoke('tcp', 80, 81, '0.0.0.0/0')

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        rv = self.ec2.get_all_security_groups()

        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0].name, 'default')

        return

    def test_authorize_revoke_security_group_cidr_v6(self):
        """
        Test that we can add and remove CIDR based rules
        to a security group for IPv6
        """
        self.expect_http()
        self.mox.ReplayAll()

        security_group_name = "".join(random.choice("sdiuisudfsdcnpaqwertasd")
                                      for x in range(random.randint(4, 8)))

        group = self.ec2.create_security_group(security_group_name,
                                               'test group')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.authorize('tcp', 80, 81, '::/0')

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()

        group = [grp for grp in rv if grp.name == security_group_name][0]
        self.assertEquals(len(group.rules), 1)
        self.assertEquals(int(group.rules[0].from_port), 80)
        self.assertEquals(int(group.rules[0].to_port), 81)
        self.assertEquals(len(group.rules[0].grants), 1)
        self.assertEquals(str(group.rules[0].grants[0]), '::/0')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.revoke('tcp', 80, 81, '::/0')

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        rv = self.ec2.get_all_security_groups()

        self.assertEqual(len(rv), 1)
        self.assertEqual(rv[0].name, 'default')

        return

    def test_authorize_revoke_security_group_foreign_group(self):
        """
        Test that we can grant and revoke another security group access
        to a security group
        """
        self.expect_http()
        self.mox.ReplayAll()

        rand_string = 'sdiuisudfsdcnpaqwertasd'
        security_group_name = "".join(random.choice(rand_string)
                                      for x in range(random.randint(4, 8)))
        other_security_group_name = "".join(random.choice(rand_string)
                                      for x in range(random.randint(4, 8)))

        group = self.ec2.create_security_group(security_group_name,
                                               'test group')

        self.expect_http()
        self.mox.ReplayAll()

        other_group = self.ec2.create_security_group(other_security_group_name,
                                                     'some other group')

        self.expect_http()
        self.mox.ReplayAll()
        group.connection = self.ec2

        group.authorize(src_group=other_group)

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()

        # I don't bother checkng that we actually find it here,
        # because the create/delete unit test further up should
        # be good enough for that.
        for group in rv:
            if group.name == security_group_name:
                self.assertEquals(len(group.rules), 3)
                self.assertEquals(len(group.rules[0].grants), 1)
                self.assertEquals(str(group.rules[0].grants[0]), '%s-%s' %
                                  (other_security_group_name, 'fake'))

        self.expect_http()
        self.mox.ReplayAll()

        rv = self.ec2.get_all_security_groups()

        for group in rv:
            if group.name == security_group_name:
                self.expect_http()
                self.mox.ReplayAll()
                group.connection = self.ec2
                group.revoke(src_group=other_group)

        self.expect_http()
        self.mox.ReplayAll()

        self.ec2.delete_security_group(security_group_name)

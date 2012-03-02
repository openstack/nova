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

"""Tests for Signer."""

from nova import exception
from nova import test
from nova.auth import signer


class ClassWithStrRepr(object):
    def __repr__(self):
        return 'A string representation'


class SignerTestCase(test.TestCase):
    def setUp(self):
        super(SignerTestCase, self).setUp()
        self.signer = signer.Signer('uV3F3YluFJax1cknvbcGwgjvx4QpvB+leU8dUj2o')

    # S3 Authorization Signing input & output examples taken from here:
    # http://docs.amazonwebservices.com/AmazonS3/latest/dev/
    def test_s3_authorization_get(self):
        self.assertEquals('xXjDGYUmKxnwqr5KXNPGldn5LbA=',
                          self.signer.s3_authorization(
                                {'Date': 'Tue, 27 Mar 2007 19:36:42 +0000'},
                                'GET',
                                '/johnsmith/photos/puppy.jpg'))

    def test_s3_authorization_put(self):
        self.assertEquals('hcicpDDvL9SsO6AkvxqmIWkmOuQ=',
                          self.signer.s3_authorization(
                                {'Date': 'Tue, 27 Mar 2007 21:15:45 +0000',
                                 'Content-Length': '94328',
                                 'Content-Type': 'image/jpeg'},
                                'PUT',
                                '/johnsmith/photos/puppy.jpg'))

    def test_generate_HmacSHA256(self):
        self.assertEquals('clXalhbLZXxEuI32OoX+OeXsN6Mr2q4jzGyIDAr4RZg=',
                          self.signer.generate(
                                {'SignatureMethod': 'HmacSHA256',
                                 'SignatureVersion': '2'},
                                'GET', 'server', '/foo'))

    def test_generate_HmacSHA1(self):
        self.assertEquals('uJTByiDIcgB65STrS5i2egQgd+U=',
                          self.signer.generate({'SignatureVersion': '2',
                                           'SignatureMethod': 'HmacSHA1'},
                                           'GET', 'server', '/foo'))

    def test_generate_invalid_signature_method_defined(self):
        self.assertRaises(exception.Error,
                          self.signer.generate,
                          {'SignatureVersion': '2',
                           'SignatureMethod': 'invalid_method'},
                          'GET', 'server', '/foo')

    def test_generate_no_signature_method_defined(self):
        self.assertRaises(exception.Error,
                          self.signer.generate,
                          {'SignatureVersion': '2'},
                          'GET', 'server', '/foo')

    def test_generate_HmacSHA256_missing_hashlib_sha256(self):
        # Stub out haslib.sha256
        import hashlib
        self.stubs.Set(hashlib, 'sha256', None)

        # Create Signer again now that hashlib.sha256 is None
        self.signer = signer.Signer(
                        'uV3F3YluFJax1cknvbcGwgjvx4QpvB+leU8dUj2o')
        self.assertRaises(exception.Error,
                          self.signer.generate,
                          {'SignatureVersion': '2',
                           'SignatureMethod': 'HmacSHA256'},
                          'GET', 'server', '/foo')

    def test_generate_with_unicode_param(self):
        self.assertEquals('clXalhbLZXxEuI32OoX+OeXsN6Mr2q4jzGyIDAr4RZg=',
                          self.signer.generate({'SignatureVersion': u'2',
                                            'SignatureMethod': 'HmacSHA256'},
                                            'GET', 'server', '/foo'))

    def test_generate_with_non_string_or_unicode_param(self):
        self.assertEquals('99IAgCkhTR2aMTgRobnzKGuNxVFSdb7vlQRvnj3Urqk=',
                          self.signer.generate(
                              {'AnotherParam': ClassWithStrRepr(),
                               'SignatureVersion': '2',
                               'SignatureMethod': 'HmacSHA256'},
                              'GET', 'server', '/foo'))

    def test_generate_unknown_version(self):
        self.assertRaises(exception.Error,
                self.signer.generate,
                {'SignatureMethod': 'HmacSHA256', 'SignatureVersion': '9'},
                'GET', 'server', '/foo')

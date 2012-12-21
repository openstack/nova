# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM
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
#    under the License

import telnetlib

from coverage import coverage
import webob

from nova.api.openstack.compute.contrib import coverage_ext
from nova import context
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


def fake_telnet(self, data):
    return


def fake_check_coverage(self):
    return False


def fake_xml_report(self, outfile):
    return


def fake_report(self, file):
    return


class CoverageExtensionTest(test.TestCase):

    def setUp(self):
        super(CoverageExtensionTest, self).setUp()
        self.stubs.Set(telnetlib.Telnet, 'write', fake_telnet)
        self.stubs.Set(telnetlib.Telnet, 'expect', fake_telnet)
        self.stubs.Set(coverage, 'report', fake_report)
        self.stubs.Set(coverage, 'xml_report', fake_xml_report)
        self.admin_context = context.RequestContext('fakeadmin_0',
                                                    'fake',
                                                     is_admin=True)
        self.user_context = context.RequestContext('fakeadmin_0',
                                                   'fake',
                                                    is_admin=False)

    def test_not_admin(self):
        body = {'start': {}}
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context))
        self.assertEqual(res.status_int, 403)

    def test_start_coverage_action(self):
        body = {'start': {}}
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 200)

    def test_stop_coverage_action(self):
        self.stubs.Set(coverage_ext.CoverageController,
                      '_check_coverage', fake_check_coverage)
        body = {'stop': {}}
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 200)

    def test_report_coverage_action_file(self):
        self.stubs.Set(coverage_ext.CoverageController,
                      '_check_coverage', fake_check_coverage)
        self.test_start_coverage_action()
        body = {
            'report': {
                'file': 'coverage-unit-test.report',
            },
        }
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 200)
        resp_dict = jsonutils.loads(res.body)
        self.assertTrue('path' in resp_dict)
        self.assertTrue('coverage-unit-test.report' in resp_dict['path'])

    def test_report_coverage_action_xml_file(self):
        self.stubs.Set(coverage_ext.CoverageController,
                      '_check_coverage', fake_check_coverage)
        body = {
            'report': {
                'file': 'coverage-xml-unit-test.report',
                'xml': 'True',
            },
        }
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 200)
        resp_dict = jsonutils.loads(res.body)
        self.assertTrue('path' in resp_dict)
        self.assertTrue('coverage-xml-unit-test.report' in resp_dict['path'])

    def test_report_coverage_action_nofile(self):
        self.stubs.Set(coverage_ext.CoverageController,
                      '_check_coverage', fake_check_coverage)
        body = {'report': {}}
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 400)

    def test_coverage_bad_body(self):
        body = {}
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 400)

    def test_coverage_report_bad_path(self):
        self.stubs.Set(coverage_ext.CoverageController,
                      '_check_coverage', fake_check_coverage)
        body = {
            'report': {
                'file': '/tmp/coverage-xml-unit-test.report',
            }
        }
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 400)

    def test_stop_coverage_action_nostart(self):
        body = {'stop': {}}
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 404)

    def test_report_coverage_action_nostart(self):
        body = {'stop': {}}
        req = webob.Request.blank('/v2/fake/os-coverage/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))
        self.assertEqual(res.status_int, 404)

# Copyright 2014 IBM Corp.
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

"""Microversions Test Extension"""
import functools

import webob

from nova.api.openstack.compute import routes
from nova.api.openstack import wsgi
from nova.api import validation
from nova.tests.unit.api.openstack.compute import dummy_schema


class MicroversionsController(wsgi.Controller):

    @wsgi.Controller.api_version("2.1")
    def index(self, req):
        data = {'param': 'val'}
        return data

    @wsgi.Controller.api_version("2.2")  # noqa
    def index(self, req):
        data = {'param': 'val2'}
        return data

    @wsgi.Controller.api_version("3.0")  # noqa
    def index(self, req):
        raise webob.exc.HTTPBadRequest()


# We have a second example controller here to help check
# for accidental dependencies between API controllers
# due to base class changes
class MicroversionsController2(wsgi.Controller):

    @wsgi.Controller.api_version("2.2", "2.5")
    def index(self, req):
        data = {'param': 'controller2_val1'}
        return data

    @wsgi.Controller.api_version("2.5", "3.1")  # noqa
    @wsgi.response(202)
    def index(self, req):
        data = {'param': 'controller2_val2'}
        return data


class MicroversionsController3(wsgi.Controller):

    @wsgi.Controller.api_version("2.1")
    @validation.schema(dummy_schema.dummy)
    def create(self, req, body):
        data = {'param': 'create_val1'}
        return data

    @wsgi.Controller.api_version("2.1")
    @validation.schema(dummy_schema.dummy, "2.3", "2.8")
    @validation.schema(dummy_schema.dummy2, "2.9")
    def update(self, req, id, body):
        data = {'param': 'update_val1'}
        return data

    @wsgi.Controller.api_version("2.1", "2.2")
    @wsgi.response(202)
    @wsgi.action('foo')
    def _foo(self, req, id, body):
        data = {'foo': 'bar'}
        return data


class MicroversionsController4(wsgi.Controller):

    @wsgi.Controller.api_version("2.1")
    def _create(self, req):
        data = {'param': 'controller4_val1'}
        return data

    @wsgi.Controller.api_version("2.2")  # noqa
    def _create(self, req):
        data = {'param': 'controller4_val2'}
        return data

    def create(self, req, body):
        return self._create(req)


class MicroversionsExtendsBaseController(wsgi.Controller):
    @wsgi.Controller.api_version("2.1")
    def show(self, req, id):
        return {'base_param': 'base_val'}


mv_controller = functools.partial(routes._create_controller,
    MicroversionsController, [])


mv2_controller = functools.partial(routes._create_controller,
    MicroversionsController2, [])


mv3_controller = functools.partial(routes._create_controller,
    MicroversionsController3, [])


mv4_controller = functools.partial(routes._create_controller,
    MicroversionsController4, [])


mv5_controller = functools.partial(routes._create_controller,
    MicroversionsExtendsBaseController, [])


ROUTES = (
    ('/microversions', {
        'GET': [mv_controller, 'index']
    }),
    ('/microversions2', {
        'GET': [mv2_controller, 'index']
    }),
    ('/microversions3', {
        'POST': [mv3_controller, 'create']
    }),
    ('/microversions3/{id}', {
        'PUT': [mv3_controller, 'update']
    }),
    ('/microversions3/{id}/action', {
        'POST': [mv3_controller, 'action']
    }),
    ('/microversions4', {
        'POST': [mv4_controller, 'create']
    }),
    ('/microversions5/{id}', {
        'GET': [mv5_controller, 'show']
    }),
)

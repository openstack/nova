# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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

"""Tests for the compute extra resources framework."""


from oslo.config import cfg
from stevedore import extension
from stevedore import named

from nova.compute import resources
from nova.compute.resources import base
from nova.compute.resources import vcpu
from nova import context
from nova.i18n import _
from nova.objects import flavor as flavor_obj
from nova import test
from nova.tests.unit import fake_instance

CONF = cfg.CONF


class FakeResourceHandler(resources.ResourceHandler):
    def __init__(self, extensions):
        self._mgr = \
            named.NamedExtensionManager.make_test_instance(extensions)


class FakeResource(base.Resource):

    def __init__(self):
        self.total_res = 0
        self.used_res = 0

    def _get_requested(self, usage):
        if 'extra_specs' not in usage:
            return
        if self.resource_name not in usage['extra_specs']:
            return
        req = usage['extra_specs'][self.resource_name]
        return int(req)

    def _get_limit(self, limits):
        if self.resource_name not in limits:
            return
        limit = limits[self.resource_name]
        return int(limit)

    def reset(self, resources, driver):
        self.total_res = 0
        self.used_res = 0

    def test(self, usage, limits):
        requested = self._get_requested(usage)
        if not requested:
            return

        limit = self._get_limit(limits)
        if not limit:
            return

        free = limit - self.used_res
        if requested <= free:
            return
        else:
            return (_('Free %(free)d < requested %(requested)d ') %
                    {'free': free, 'requested': requested})

    def add_instance(self, usage):
        requested = self._get_requested(usage)
        if requested:
            self.used_res += requested

    def remove_instance(self, usage):
        requested = self._get_requested(usage)
        if requested:
            self.used_res -= requested

    def write(self, resources):
        pass

    def report_free(self):
        return "Free %s" % (self.total_res - self.used_res)


class ResourceA(FakeResource):

    def reset(self, resources, driver):
        # ResourceA uses a configuration option
        self.total_res = int(CONF.resA)
        self.used_res = 0
        self.resource_name = 'resource:resA'

    def write(self, resources):
        resources['resA'] = self.total_res
        resources['used_resA'] = self.used_res


class ResourceB(FakeResource):

    def reset(self, resources, driver):
        # ResourceB uses resource details passed in parameter resources
        self.total_res = resources['resB']
        self.used_res = 0
        self.resource_name = 'resource:resB'

    def write(self, resources):
        resources['resB'] = self.total_res
        resources['used_resB'] = self.used_res


def fake_flavor_obj(**updates):
    flavor = flavor_obj.Flavor()
    flavor.id = 1
    flavor.name = 'fakeflavor'
    flavor.memory_mb = 8000
    flavor.vcpus = 3
    flavor.root_gb = 11
    flavor.ephemeral_gb = 4
    flavor.swap = 0
    flavor.rxtx_factor = 1.0
    flavor.vcpu_weight = 1
    if updates:
        flavor.update(updates)
    return flavor


class BaseTestCase(test.TestCase):

    def _initialize_used_res_counter(self):
        # Initialize the value for the used resource
        for ext in self.r_handler._mgr.extensions:
            ext.obj.used_res = 0

    def setUp(self):
        super(BaseTestCase, self).setUp()

        # initialize flavors and stub get_by_id to
        # get flavors from here
        self._flavors = {}
        self.ctxt = context.get_admin_context()

        # Create a flavor without extra_specs defined
        _flavor_id = 1
        _flavor = fake_flavor_obj(id=_flavor_id)
        self._flavors[_flavor_id] = _flavor

        # Create a flavor with extra_specs defined
        _flavor_id = 2
        requested_resA = 5
        requested_resB = 7
        requested_resC = 7
        _extra_specs = {'resource:resA': requested_resA,
                        'resource:resB': requested_resB,
                        'resource:resC': requested_resC}
        _flavor = fake_flavor_obj(id=_flavor_id,
                                  extra_specs=_extra_specs)
        self._flavors[_flavor_id] = _flavor

        # create fake resource extensions and resource handler
        _extensions = [
            extension.Extension('resA', None, ResourceA, ResourceA()),
            extension.Extension('resB', None, ResourceB, ResourceB()),
        ]
        self.r_handler = FakeResourceHandler(_extensions)

        # Resources details can be passed to each plugin or can be specified as
        # configuration options
        driver_resources = {'resB': 5}
        CONF.resA = '10'

        # initialise the resources
        self.r_handler.reset_resources(driver_resources, None)

    def test_update_from_instance_with_extra_specs(self):
        # Flavor with extra_specs
        _flavor_id = 2
        sign = 1
        self.r_handler.update_from_instance(self._flavors[_flavor_id], sign)

        expected_resA = self._flavors[_flavor_id].extra_specs['resource:resA']
        expected_resB = self._flavors[_flavor_id].extra_specs['resource:resB']
        self.assertEqual(int(expected_resA),
                         self.r_handler._mgr['resA'].obj.used_res)
        self.assertEqual(int(expected_resB),
                         self.r_handler._mgr['resB'].obj.used_res)

    def test_update_from_instance_without_extra_specs(self):
        # Flavor id without extra spec
        _flavor_id = 1
        self._initialize_used_res_counter()
        self.r_handler.resource_list = []
        sign = 1
        self.r_handler.update_from_instance(self._flavors[_flavor_id], sign)
        self.assertEqual(0, self.r_handler._mgr['resA'].obj.used_res)
        self.assertEqual(0, self.r_handler._mgr['resB'].obj.used_res)

    def test_write_resources(self):
        self._initialize_used_res_counter()
        extra_resources = {}
        expected = {'resA': 10, 'used_resA': 0, 'resB': 5, 'used_resB': 0}
        self.r_handler.write_resources(extra_resources)
        self.assertEqual(expected, extra_resources)

    def test_test_resources_without_extra_specs(self):
        limits = {}
        # Flavor id without extra_specs
        flavor = self._flavors[1]
        result = self.r_handler.test_resources(flavor, limits)
        self.assertEqual([None, None], result)

    def test_test_resources_with_limits_for_different_resource(self):
        limits = {'resource:resC': 20}
        # Flavor id with extra_specs
        flavor = self._flavors[2]
        result = self.r_handler.test_resources(flavor, limits)
        self.assertEqual([None, None], result)

    def test_passing_test_resources(self):
        limits = {'resource:resA': 10, 'resource:resB': 20}
        # Flavor id with extra_specs
        flavor = self._flavors[2]
        self._initialize_used_res_counter()
        result = self.r_handler.test_resources(flavor, limits)
        self.assertEqual([None, None], result)

    def test_failing_test_resources_for_single_resource(self):
        limits = {'resource:resA': 4, 'resource:resB': 20}
        # Flavor id with extra_specs
        flavor = self._flavors[2]
        self._initialize_used_res_counter()
        result = self.r_handler.test_resources(flavor, limits)
        expected = ['Free 4 < requested 5 ', None]
        self.assertEqual(sorted(expected),
                             sorted(result))

    def test_empty_resource_handler(self):
        """An empty resource handler has no resource extensions,
        should have no effect, and should raise no exceptions.
        """
        empty_r_handler = FakeResourceHandler([])

        resources = {}
        empty_r_handler.reset_resources(resources, None)

        flavor = self._flavors[1]
        sign = 1
        empty_r_handler.update_from_instance(flavor, sign)

        limits = {}
        test_result = empty_r_handler.test_resources(flavor, limits)
        self.assertEqual([], test_result)

        sign = -1
        empty_r_handler.update_from_instance(flavor, sign)

        extra_resources = {}
        expected_extra_resources = extra_resources
        empty_r_handler.write_resources(extra_resources)
        self.assertEqual(expected_extra_resources, extra_resources)

        empty_r_handler.report_free_resources()

    def test_vcpu_resource_load(self):
        # load the vcpu example
        names = ['vcpu']
        real_r_handler = resources.ResourceHandler(names)
        ext_names = real_r_handler._mgr.names()
        self.assertEqual(names, ext_names)

        # check the extension loaded is the one we expect
        # and an instance of the object has been created
        ext = real_r_handler._mgr['vcpu']
        self.assertIsInstance(ext.obj, vcpu.VCPU)


class TestVCPU(test.TestCase):

    def setUp(self):
        super(TestVCPU, self).setUp()
        self._vcpu = vcpu.VCPU()
        self._vcpu._total = 10
        self._vcpu._used = 0
        self._flavor = fake_flavor_obj(vcpus=5)
        self._big_flavor = fake_flavor_obj(vcpus=20)
        self._instance = fake_instance.fake_instance_obj(None)

    def test_reset(self):
        # set vcpu values to something different to test reset
        self._vcpu._total = 10
        self._vcpu._used = 5

        driver_resources = {'vcpus': 20}
        self._vcpu.reset(driver_resources, None)
        self.assertEqual(20, self._vcpu._total)
        self.assertEqual(0, self._vcpu._used)

    def test_add_and_remove_instance(self):
        self._vcpu.add_instance(self._flavor)
        self.assertEqual(10, self._vcpu._total)
        self.assertEqual(5, self._vcpu._used)

        self._vcpu.remove_instance(self._flavor)
        self.assertEqual(10, self._vcpu._total)
        self.assertEqual(0, self._vcpu._used)

    def test_test_pass_limited(self):
        result = self._vcpu.test(self._flavor, {'vcpu': 10})
        self.assertIsNone(result, 'vcpu test failed when it should pass')

    def test_test_pass_unlimited(self):
        result = self._vcpu.test(self._big_flavor, {})
        self.assertIsNone(result, 'vcpu test failed when it should pass')

    def test_test_fail(self):
        result = self._vcpu.test(self._flavor, {'vcpu': 2})
        expected = _('Free CPUs 2.00 VCPUs < requested 5 VCPUs')
        self.assertEqual(expected, result)

    def test_write(self):
        resources = {'stats': {}}
        self._vcpu.write(resources)
        expected = {
            'vcpus': 10,
            'vcpus_used': 0,
            'stats': {
                'num_vcpus': 10,
                'num_vcpus_used': 0
            }
        }
        self.assertEqual(sorted(expected),
                         sorted(resources))

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 VMware, Inc.
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

import fixtures

from nova import test
from nova.virt.vmwareapi import fake
from nova.virt.vmwareapi import vim_util


def _fake_get_object_properties(vim, collector, mobj,
                                type, properties):
    fake_objects = fake.FakeRetrieveResult()
    fake_objects.add_object(fake.ObjectContent(None))
    return fake_objects


def _fake_get_object_properties_missing(vim, collector, mobj,
                                type, properties):
    fake_objects = fake.FakeRetrieveResult()
    ml = [fake.MissingProperty()]
    fake_objects.add_object(fake.ObjectContent(None, missing_list=ml))
    return fake_objects


class VMwareVIMUtilTestCase(test.NoDBTestCase):

    def test_get_dynamic_properties_missing(self):
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.vmwareapi.vim_util.get_object_properties',
                _fake_get_object_properties))
        res = vim_util.get_dynamic_property('fake-vim', 'fake-obj',
                                            'fake-type', 'fake-property')
        self.assertIsNone(res)

    def test_get_dynamic_properties_missing_path_exists(self):
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.vmwareapi.vim_util.get_object_properties',
                _fake_get_object_properties_missing))
        res = vim_util.get_dynamic_property('fake-vim', 'fake-obj',
                                            'fake-type', 'fake-property')
        self.assertIsNone(res)

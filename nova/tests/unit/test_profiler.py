# Copyright 2016 OpenStack Foundation
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

import inspect
import os

from oslo_utils import importutils
import osprofiler.opts as profiler
import six.moves as six

from nova import conf
from nova import test


class TestProfiler(test.NoDBTestCase):
    def test_all_public_methods_are_traced(self):
        # NOTE(rpodolyaka): osprofiler only wraps class methods when option
        # CONF.profiler.enabled is set to True and the default value is False,
        # which means in our usual test run we use original, not patched
        # classes. In order to test, that we actually properly wrap methods
        # we are interested in, this test case sets CONF.profiler.enabled to
        # True and reloads all the affected Python modules (application of
        # decorators and metaclasses is performed at module import time).
        # Unfortunately, this leads to subtle failures of other test cases
        # (e.g. super() is performed on a "new" version of a class instance
        # created after a module reload while the class name is a reference to
        # an "old" version of the class). Thus, this test is run in isolation.
        if not os.getenv('TEST_OSPROFILER', False):
            self.skipTest('TEST_OSPROFILER env variable is not set. '
                          'Skipping osprofiler tests...')

        # reinitialize the metaclass after enabling osprofiler
        profiler.set_defaults(conf.CONF)
        self.flags(enabled=True, group='profiler')
        six.reload_module(importutils.import_module('nova.manager'))

        classes = [
            'nova.api.manager.MetadataManager',
            'nova.cells.manager.CellsManager',
            'nova.cells.rpcapi.CellsAPI',
            'nova.compute.api.API',
            'nova.compute.manager.ComputeManager',
            'nova.compute.rpcapi.ComputeAPI',
            'nova.conductor.manager.ComputeTaskManager',
            'nova.conductor.manager.ConductorManager',
            'nova.conductor.rpcapi.ComputeTaskAPI',
            'nova.conductor.rpcapi.ConductorAPI',
            'nova.console.manager.ConsoleProxyManager',
            'nova.console.rpcapi.ConsoleAPI',
            'nova.consoleauth.manager.ConsoleAuthManager',
            'nova.consoleauth.rpcapi.ConsoleAuthAPI',
            'nova.image.api.API',
            'nova.network.api.API',
            'nova.network.manager.FlatDHCPManager',
            'nova.network.manager.FlatManager',
            'nova.network.manager.VlanManager',
            'nova.network.neutronv2.api.ClientWrapper',
            'nova.network.rpcapi.NetworkAPI',
            'nova.scheduler.manager.SchedulerManager',
            'nova.scheduler.rpcapi.SchedulerAPI',
            'nova.virt.libvirt.vif.LibvirtGenericVIFDriver',
            'nova.virt.libvirt.volume.volume.LibvirtBaseVolumeDriver',
        ]
        for clsname in classes:
            # give the metaclass and trace_cls() decorator a chance to patch
            # methods of the classes above
            six.reload_module(
                importutils.import_module(clsname.rsplit('.', 1)[0]))
            cls = importutils.import_class(clsname)

            for attr, obj in cls.__dict__.items():
                # only public methods are traced
                if attr.startswith('_'):
                    continue
                # only checks callables
                if not (inspect.ismethod(obj) or inspect.isfunction(obj)):
                    continue
                # osprofiler skips static methods
                if isinstance(obj, staticmethod):
                    continue

                self.assertTrue(getattr(obj, '__traced__', False), obj)

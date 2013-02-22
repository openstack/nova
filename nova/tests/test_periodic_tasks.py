# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

import time

from testtools import matchers

from nova import manager
from nova import test


class ManagerMetaTestCase(test.TestCase):
    """Tests for the meta class which manages the creation of periodic tasks.
    """

    def test_meta(self):
        class Manager(object):
            __metaclass__ = manager.ManagerMeta

            @manager.periodic_task
            def foo(self):
                return 'foo'

            @manager.periodic_task(spacing=4)
            def bar(self):
                return 'bar'

            @manager.periodic_task(enabled=False)
            def baz(self):
                return 'baz'

        m = Manager()
        self.assertThat(m._periodic_tasks, matchers.HasLength(2))
        self.assertEqual(None, m._periodic_spacing['foo'])
        self.assertEqual(4, m._periodic_spacing['bar'])
        self.assertThat(
            m._periodic_spacing, matchers.Not(matchers.Contains('baz')))


class Manager(test.TestCase):
    """Tests the periodic tasks portion of the manager class."""

    def test_periodic_tasks_with_idle(self):
        class Manager(manager.Manager):
            @manager.periodic_task(spacing=200)
            def bar(self):
                return 'bar'

        m = Manager()
        self.assertThat(m._periodic_tasks, matchers.HasLength(1))
        self.assertEqual(200, m._periodic_spacing['bar'])

        # Now a single pass of the periodic tasks
        idle = m.periodic_tasks(None)
        self.assertAlmostEqual(60, idle, 1)

    def test_periodic_tasks_constant(self):
        class Manager(manager.Manager):
            @manager.periodic_task(spacing=0)
            def bar(self):
                return 'bar'

        m = Manager()
        idle = m.periodic_tasks(None)
        self.assertAlmostEqual(60, idle, 1)

    def test_periodic_tasks_idle_calculation(self):
        class Manager(manager.Manager):
            @manager.periodic_task(spacing=10)
            def bar(self):
                return 'bar'

        m = Manager()
        m.periodic_tasks(None)
        time.sleep(0.1)
        idle = m.periodic_tasks(None)
        self.assertThat(idle, matchers.GreaterThan(9.7))
        self.assertThat(idle, matchers.LessThan(9.9))

    def test_periodic_tasks_disabled(self):
        class Manager(manager.Manager):
            @manager.periodic_task(spacing=-1)
            def bar(self):
                return 'bar'

        m = Manager()
        idle = m.periodic_tasks(None)
        self.assertAlmostEqual(60, idle, 1)

    def test_external_running_here(self):
        self.flags(run_external_periodic_tasks=True)

        class Manager(manager.Manager):
            @manager.periodic_task(spacing=200, external_process_ok=True)
            def bar(self):
                return 'bar'

        m = Manager()
        self.assertThat(m._periodic_tasks, matchers.HasLength(1))

    def test_external_running_elsewhere(self):
        self.flags(run_external_periodic_tasks=False)

        class Manager(manager.Manager):
            @manager.periodic_task(spacing=200, external_process_ok=True)
            def bar(self):
                return 'bar'

        m = Manager()
        self.assertEqual([], m._periodic_tasks)

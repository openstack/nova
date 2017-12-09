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

from nova.cmd import manage
from nova import context
from nova import objects
from nova import test


class NovaManageDBIronicTest(test.TestCase):
    def setUp(self):
        super(NovaManageDBIronicTest, self).setUp()
        self.commands = manage.DbCommands()
        self.context = context.RequestContext('fake-user', 'fake-project')

        self.service1 = objects.Service(context=self.context,
                                       host='fake-host1',
                                       binary='nova-compute',
                                       topic='fake-host1',
                                       report_count=1,
                                       disabled=False,
                                       disabled_reason=None,
                                       availability_zone='nova',
                                       forced_down=False)
        self.service1.create()

        self.service2 = objects.Service(context=self.context,
                                       host='fake-host2',
                                       binary='nova-compute',
                                       topic='fake-host2',
                                       report_count=1,
                                       disabled=False,
                                       disabled_reason=None,
                                       availability_zone='nova',
                                       forced_down=False)
        self.service2.create()

        self.service3 = objects.Service(context=self.context,
                                       host='fake-host3',
                                       binary='nova-compute',
                                       topic='fake-host3',
                                       report_count=1,
                                       disabled=False,
                                       disabled_reason=None,
                                       availability_zone='nova',
                                       forced_down=False)
        self.service3.create()

        self.cn1 = objects.ComputeNode(context=self.context,
                                       service_id=self.service1.id,
                                       host='fake-host1',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node1',
                                       cpu_info='{}')
        self.cn1.create()

        self.cn2 = objects.ComputeNode(context=self.context,
                                       service_id=self.service1.id,
                                       host='fake-host1',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node2',
                                       cpu_info='{}')
        self.cn2.create()

        self.cn3 = objects.ComputeNode(context=self.context,
                                       service_id=self.service2.id,
                                       host='fake-host2',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node3',
                                       cpu_info='{}')
        self.cn3.create()

        self.cn4 = objects.ComputeNode(context=self.context,
                                       service_id=self.service3.id,
                                       host='fake-host3',
                                       hypervisor_type='libvirt',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node4',
                                       cpu_info='{}')
        self.cn4.create()

        self.cn5 = objects.ComputeNode(context=self.context,
                                       service_id=self.service2.id,
                                       host='fake-host2',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node5',
                                       cpu_info='{}')
        self.cn5.create()

        self.insts = []
        for cn in (self.cn1, self.cn2, self.cn3, self.cn4, self.cn4, self.cn5):
            flavor = objects.Flavor(extra_specs={})
            inst = objects.Instance(context=self.context,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id,
                                    flavor=flavor,
                                    node=cn.hypervisor_hostname)
            inst.create()
            self.insts.append(inst)

        self.ironic_insts = [i for i in self.insts
                             if i.node != self.cn4.hypervisor_hostname]
        self.virt_insts = [i for i in self.insts
                           if i.node == self.cn4.hypervisor_hostname]

    def test_ironic_flavor_migration_by_host_and_node(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-host1',
                                                    'fake-node2', False, False)
        self.assertEqual(0, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            if inst.node == 'fake-node2':
                self.assertIn(k, inst.flavor.extra_specs)
                self.assertEqual('1', inst.flavor.extra_specs[k])
            else:
                self.assertNotIn(k, inst.flavor.extra_specs)

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_by_host(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-host1', None,
                                                    False, False)
        self.assertEqual(0, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            if inst.node in ('fake-node1', 'fake-node2'):
                self.assertIn(k, inst.flavor.extra_specs)
                self.assertEqual('1', inst.flavor.extra_specs[k])
            else:
                self.assertNotIn(k, inst.flavor.extra_specs)

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_by_host_not_ironic(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-host3', None,
                                                    False, False)
        self.assertEqual(1, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_all_hosts(self):
        ret = self.commands.ironic_flavor_migration('test', None, None,
                                                    True, False)
        self.assertEqual(0, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            self.assertIn(k, inst.flavor.extra_specs)
            self.assertEqual('1', inst.flavor.extra_specs[k])

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_invalid(self):
        # No host or node and not "all"
        ret = self.commands.ironic_flavor_migration('test', None, None,
                                                    False, False)
        self.assertEqual(3, ret)

        # No host, only node
        ret = self.commands.ironic_flavor_migration('test', None, 'fake-node',
                                                    False, False)
        self.assertEqual(3, ret)

        # Asked for all but provided a node
        ret = self.commands.ironic_flavor_migration('test', None, 'fake-node',
                                                    True, False)
        self.assertEqual(3, ret)

        # Asked for all but provided a host
        ret = self.commands.ironic_flavor_migration('test', 'fake-host', None,
                                                    True, False)
        self.assertEqual(3, ret)

        # Asked for all but provided a host and node
        ret = self.commands.ironic_flavor_migration('test', 'fake-host',
                                                    'fake-node', True, False)
        self.assertEqual(3, ret)

        # Did not provide a resource_class
        ret = self.commands.ironic_flavor_migration(None, 'fake-host',
                                                    'fake-node', False, False)
        self.assertEqual(3, ret)

    def test_ironic_flavor_migration_no_match(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-nonexist',
                                                    None, False, False)
        self.assertEqual(1, ret)

        ret = self.commands.ironic_flavor_migration('test', 'fake-nonexist',
                                                    'fake-node', False, False)
        self.assertEqual(1, ret)

    def test_ironic_two_instances(self):
        # NOTE(danms): This shouldn't be possible, but simulate it like
        # someone hacked the database, which should also cover any other
        # way this could happen.

        # Since we created two instances on cn4 in setUp() we can convert that
        # to an ironic host and cause the two-instances-on-one-ironic paradox
        # to happen.
        self.cn4.hypervisor_type = 'ironic'
        self.cn4.save()
        ret = self.commands.ironic_flavor_migration('test', 'fake-host3',
                                                    'fake-node4', False, False)
        self.assertEqual(2, ret)


class NovaManageCellV2Test(test.TestCase):
    def setUp(self):
        super(NovaManageCellV2Test, self).setUp()
        self.commands = manage.CellV2Commands()
        self.context = context.RequestContext('fake-user', 'fake-project')

        self.service1 = objects.Service(context=self.context,
                                        host='fake-host1',
                                        binary='nova-compute',
                                        topic='fake-host1',
                                        report_count=1,
                                        disabled=False,
                                        disabled_reason=None,
                                        availability_zone='nova',
                                        forced_down=False)
        self.service1.create()

        self.cn1 = objects.ComputeNode(context=self.context,
                                       service_id=self.service1.id,
                                       host='fake-host1',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node1',
                                       cpu_info='{}')
        self.cn1.create()

    def test_delete_host(self):
        cells = objects.CellMappingList.get_all(self.context)

        self.commands.discover_hosts()

        # We should have one mapped node
        cns = objects.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(cns))
        self.assertEqual(1, cns[0].mapped)

        for cell in cells:
            r = self.commands.delete_host(cell.uuid, 'fake-host1')
            if r == 0:
                break

        # Our node should now be unmapped
        cns = objects.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(cns))
        self.assertEqual(0, cns[0].mapped)

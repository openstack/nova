#    Copyright 2015 Red Hat, Inc.
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

import mock
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
from oslo_versionedobjects import base as ovo_base

from nova import context
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import request_spec
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_request_spec
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


class _TestRequestSpecObject(object):

    def test_image_meta_from_image_as_object(self):
        # Just isolating the test for the from_dict() method
        image_meta = objects.ImageMeta(name='foo')

        spec = objects.RequestSpec()
        spec._image_meta_from_image(image_meta)
        self.assertEqual(image_meta, spec.image)

    @mock.patch.object(objects.ImageMeta, 'from_dict')
    def test_image_meta_from_image_as_dict(self, from_dict):
        # Just isolating the test for the from_dict() method
        image_meta = objects.ImageMeta(name='foo')
        from_dict.return_value = image_meta

        spec = objects.RequestSpec()
        spec._image_meta_from_image({'name': 'foo'})
        self.assertEqual(image_meta, spec.image)

    def test_image_meta_from_image_as_none(self):
        # just add a dumb check to have a full coverage
        spec = objects.RequestSpec()
        spec._image_meta_from_image(None)
        self.assertIsNone(spec.image)

    @mock.patch.object(base, 'obj_to_primitive')
    def test_to_legacy_image(self, obj_to_primitive):
        spec = objects.RequestSpec(image=objects.ImageMeta())
        fake_dict = mock.Mock()
        obj_to_primitive.return_value = fake_dict

        self.assertEqual(fake_dict, spec._to_legacy_image())
        obj_to_primitive.assert_called_once_with(spec.image)

    @mock.patch.object(base, 'obj_to_primitive')
    def test_to_legacy_image_with_none(self, obj_to_primitive):
        spec = objects.RequestSpec(image=None)

        self.assertEqual({}, spec._to_legacy_image())
        self.assertFalse(obj_to_primitive.called)

    def test_from_instance_as_object(self):
        instance = objects.Instance()
        instance.uuid = uuidutils.generate_uuid()
        instance.numa_topology = None
        instance.pci_requests = None
        instance.project_id = fakes.FAKE_PROJECT_ID
        instance.availability_zone = 'nova'

        spec = objects.RequestSpec()
        spec._from_instance(instance)
        instance_fields = ['numa_topology', 'pci_requests', 'uuid',
                           'project_id', 'availability_zone']
        for field in instance_fields:
            if field == 'uuid':
                self.assertEqual(getattr(instance, field),
                                 getattr(spec, 'instance_uuid'))
            else:
                self.assertEqual(getattr(instance, field),
                                 getattr(spec, field))

    def test_from_instance_as_dict(self):
        instance = dict(uuid=uuidutils.generate_uuid(),
                        numa_topology=None,
                        pci_requests=None,
                        project_id=fakes.FAKE_PROJECT_ID,
                        availability_zone='nova')

        spec = objects.RequestSpec()
        spec._from_instance(instance)
        instance_fields = ['numa_topology', 'pci_requests', 'uuid',
                           'project_id', 'availability_zone']
        for field in instance_fields:
            if field == 'uuid':
                self.assertEqual(instance.get(field),
                                 getattr(spec, 'instance_uuid'))
            else:
                self.assertEqual(instance.get(field), getattr(spec, field))

    @mock.patch.object(objects.InstancePCIRequests,
                       'from_request_spec_instance_props')
    def test_from_instance_with_pci_requests(self, pci_from_spec):
        fake_pci_requests = objects.InstancePCIRequests()
        pci_from_spec.return_value = fake_pci_requests

        instance = dict(
            uuid=uuidutils.generate_uuid(),
            root_gb=10,
            ephemeral_gb=0,
            memory_mb=10,
            vcpus=1,
            numa_topology=None,
            project_id=fakes.FAKE_PROJECT_ID,
            availability_zone='nova',
            pci_requests={
                'instance_uuid': 'fakeid',
                'requests': [{'count': 1, 'spec': [{'vendor_id': '8086'}]}]})
        spec = objects.RequestSpec()

        spec._from_instance(instance)
        pci_from_spec.assert_called_once_with(instance['pci_requests'])
        self.assertEqual(fake_pci_requests, spec.pci_requests)

    def test_from_instance_with_numa_stuff(self):
        instance = dict(
            uuid=uuidutils.generate_uuid(),
            root_gb=10,
            ephemeral_gb=0,
            memory_mb=10,
            vcpus=1,
            project_id=fakes.FAKE_PROJECT_ID,
            availability_zone='nova',
            pci_requests=None,
            numa_topology={'cells': [{'id': 1, 'cpuset': ['1'], 'memory': 8192,
                                      'pagesize': None, 'cpu_topology': None,
                                      'cpu_pinning_raw': None}]})
        spec = objects.RequestSpec()

        spec._from_instance(instance)
        self.assertIsInstance(spec.numa_topology, objects.InstanceNUMATopology)
        cells = spec.numa_topology.cells
        self.assertEqual(1, len(cells))
        self.assertIsInstance(cells[0], objects.InstanceNUMACell)

    def test_from_flavor_as_object(self):
        flavor = objects.Flavor()

        spec = objects.RequestSpec()
        spec._from_flavor(flavor)
        self.assertEqual(flavor, spec.flavor)

    def test_from_flavor_as_dict(self):
        flavor_dict = dict(id=1)
        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec(ctxt)

        spec._from_flavor(flavor_dict)
        self.assertIsInstance(spec.flavor, objects.Flavor)
        self.assertEqual({'id': 1}, spec.flavor.obj_get_changes())

    def test_to_legacy_instance(self):
        spec = objects.RequestSpec()
        spec.flavor = objects.Flavor(root_gb=10,
                                     ephemeral_gb=0,
                                     memory_mb=10,
                                     vcpus=1)
        spec.numa_topology = None
        spec.pci_requests = None
        spec.project_id = fakes.FAKE_PROJECT_ID
        spec.availability_zone = 'nova'

        instance = spec._to_legacy_instance()
        self.assertEqual({'root_gb': 10,
                          'ephemeral_gb': 0,
                          'memory_mb': 10,
                          'vcpus': 1,
                          'numa_topology': None,
                          'pci_requests': None,
                          'project_id': fakes.FAKE_PROJECT_ID,
                          'availability_zone': 'nova'}, instance)

    def test_to_legacy_instance_with_unset_values(self):
        spec = objects.RequestSpec()
        self.assertEqual({}, spec._to_legacy_instance())

    def test_from_retry(self):
        retry_dict = {'num_attempts': 1,
                      'hosts': [['fake1', 'node1']]}
        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec(ctxt)
        spec._from_retry(retry_dict)
        self.assertIsInstance(spec.retry, objects.SchedulerRetries)
        self.assertEqual(1, spec.retry.num_attempts)
        self.assertIsInstance(spec.retry.hosts, objects.ComputeNodeList)
        self.assertEqual(1, len(spec.retry.hosts))
        self.assertEqual('fake1', spec.retry.hosts[0].host)
        self.assertEqual('node1', spec.retry.hosts[0].hypervisor_hostname)

    def test_from_retry_missing_values(self):
        retry_dict = {}
        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec(ctxt)
        spec._from_retry(retry_dict)
        self.assertIsNone(spec.retry)

    def test_populate_group_info(self):
        filt_props = {}
        filt_props['group_updated'] = True
        filt_props['group_policies'] = set(['affinity'])
        filt_props['group_hosts'] = set(['fake1'])
        filt_props['group_members'] = set(['fake-instance1'])

        spec = objects.RequestSpec()
        spec._populate_group_info(filt_props)
        self.assertIsInstance(spec.instance_group, objects.InstanceGroup)
        self.assertEqual(['affinity'], spec.instance_group.policies)
        self.assertEqual(['fake1'], spec.instance_group.hosts)
        self.assertEqual(['fake-instance1'], spec.instance_group.members)

    def test_populate_group_info_missing_values(self):
        filt_props = {}
        spec = objects.RequestSpec()
        spec._populate_group_info(filt_props)
        self.assertIsNone(spec.instance_group)

    def test_from_limits(self):
        limits_dict = {'numa_topology': None,
                       'vcpu': 1.0,
                       'disk_gb': 1.0,
                       'memory_mb': 1.0}
        spec = objects.RequestSpec()
        spec._from_limits(limits_dict)
        self.assertIsInstance(spec.limits, objects.SchedulerLimits)
        self.assertIsNone(spec.limits.numa_topology)
        self.assertEqual(1, spec.limits.vcpu)
        self.assertEqual(1, spec.limits.disk_gb)
        self.assertEqual(1, spec.limits.memory_mb)

    def test_from_limits_missing_values(self):
        limits_dict = {}
        spec = objects.RequestSpec()
        spec._from_limits(limits_dict)
        self.assertIsInstance(spec.limits, objects.SchedulerLimits)
        self.assertIsNone(spec.limits.numa_topology)
        self.assertIsNone(spec.limits.vcpu)
        self.assertIsNone(spec.limits.disk_gb)
        self.assertIsNone(spec.limits.memory_mb)

    def test_from_hints(self):
        hints_dict = {'foo_str': '1',
                      'bar_list': ['2']}
        spec = objects.RequestSpec()
        spec._from_hints(hints_dict)
        expected = {'foo_str': ['1'],
                    'bar_list': ['2']}
        self.assertEqual(expected, spec.scheduler_hints)

    def test_from_hints_with_no_hints(self):
        spec = objects.RequestSpec()
        spec._from_hints(None)
        self.assertIsNone(spec.scheduler_hints)

    @mock.patch.object(objects.SchedulerLimits, 'from_dict')
    def test_from_primitives(self, mock_limits):
        spec_dict = {'instance_type': objects.Flavor(),
                     'instance_properties': objects.Instance(
                         uuid=uuidutils.generate_uuid(),
                         numa_topology=None,
                         pci_requests=None,
                         project_id=1,
                         availability_zone='nova')}
        filt_props = {}

        # We seriously don't care about the return values, we just want to make
        # sure that all the fields are set
        mock_limits.return_value = None

        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec.from_primitives(ctxt, spec_dict, filt_props)
        mock_limits.assert_called_once_with({})
        # Make sure that all fields are set using that helper method
        skip = ['id', 'security_groups']
        for field in [f for f in spec.obj_fields if f not in skip]:
            self.assertTrue(spec.obj_attr_is_set(field),
                             'Field: %s is not set' % field)
        # just making sure that the context is set by the method
        self.assertEqual(ctxt, spec._context)

    def test_from_primitives_with_requested_destination(self):
        destination = objects.Destination(host='foo')
        spec_dict = {}
        filt_props = {'requested_destination': destination}
        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec.from_primitives(ctxt, spec_dict, filt_props)
        self.assertEqual(destination, spec.requested_destination)

    def test_from_components(self):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        destination = objects.Destination(host='foo')
        instance = fake_instance.fake_instance_obj(ctxt)
        image = {'id': uuids.image_id, 'properties': {'mappings': []},
                 'status': 'fake-status', 'location': 'far-away'}
        flavor = fake_flavor.fake_flavor_obj(ctxt)
        filter_properties = {'requested_destination': destination}
        instance_group = None

        spec = objects.RequestSpec.from_components(ctxt, instance.uuid, image,
                flavor, instance.numa_topology, instance.pci_requests,
                filter_properties, instance_group, instance.availability_zone,
                objects.SecurityGroupList())
        # Make sure that all fields are set using that helper method
        for field in [f for f in spec.obj_fields if f != 'id']:
            self.assertTrue(spec.obj_attr_is_set(field),
                            'Field: %s is not set' % field)
        # just making sure that the context is set by the method
        self.assertEqual(ctxt, spec._context)
        self.assertEqual(destination, spec.requested_destination)

    @mock.patch('nova.objects.RequestSpec._populate_group_info')
    def test_from_components_with_instance_group(self, mock_pgi):
        # This test makes sure that we don't overwrite instance group passed
        # to from_components
        ctxt = context.RequestContext('fake-user', 'fake-project')
        instance = fake_instance.fake_instance_obj(ctxt)
        image = {'id': uuids.image_id, 'properties': {'mappings': []},
                 'status': 'fake-status', 'location': 'far-away'}
        flavor = fake_flavor.fake_flavor_obj(ctxt)
        filter_properties = {'fake': 'property'}
        instance_group = objects.InstanceGroup()

        objects.RequestSpec.from_components(ctxt, instance.uuid, image,
                flavor, instance.numa_topology, instance.pci_requests,
                filter_properties, instance_group, instance.availability_zone)

        self.assertFalse(mock_pgi.called)

    @mock.patch('nova.objects.RequestSpec._populate_group_info')
    def test_from_components_without_instance_group(self, mock_pgi):
        # This test makes sure that we populate instance group if not
        # present
        ctxt = context.RequestContext(fakes.FAKE_USER_ID,
                                      fakes.FAKE_PROJECT_ID)
        instance = fake_instance.fake_instance_obj(ctxt)
        image = {'id': uuids.image_id, 'properties': {'mappings': []},
                 'status': 'fake-status', 'location': 'far-away'}
        flavor = fake_flavor.fake_flavor_obj(ctxt)
        filter_properties = {'fake': 'property'}

        objects.RequestSpec.from_components(ctxt, instance.uuid, image,
                flavor, instance.numa_topology, instance.pci_requests,
                filter_properties, None, instance.availability_zone)

        mock_pgi.assert_called_once_with(filter_properties)

    @mock.patch('nova.objects.RequestSpec._populate_group_info')
    def test_from_components_without_security_groups(self, mock_pgi):
        # This test makes sure that we populate instance group if not
        # present
        ctxt = context.RequestContext(fakes.FAKE_USER_ID,
                                      fakes.FAKE_PROJECT_ID)
        instance = fake_instance.fake_instance_obj(ctxt)
        image = {'id': uuids.image_id, 'properties': {'mappings': []},
                 'status': 'fake-status', 'location': 'far-away'}
        flavor = fake_flavor.fake_flavor_obj(ctxt)
        filter_properties = {'fake': 'property'}

        spec = objects.RequestSpec.from_components(ctxt, instance.uuid, image,
                flavor, instance.numa_topology, instance.pci_requests,
                filter_properties, None, instance.availability_zone)
        self.assertNotIn('security_groups', spec)

    def test_get_scheduler_hint(self):
        spec_obj = objects.RequestSpec(scheduler_hints={'foo_single': ['1'],
                                                        'foo_mul': ['1', '2']})
        self.assertEqual('1', spec_obj.get_scheduler_hint('foo_single'))
        self.assertEqual(['1', '2'], spec_obj.get_scheduler_hint('foo_mul'))
        self.assertIsNone(spec_obj.get_scheduler_hint('oops'))
        self.assertEqual('bar', spec_obj.get_scheduler_hint('oops',
                                                            default='bar'))

    def test_get_scheduler_hint_with_no_hints(self):
        spec_obj = objects.RequestSpec()
        self.assertEqual('bar', spec_obj.get_scheduler_hint('oops',
                                                            default='bar'))

    @mock.patch.object(objects.RequestSpec, '_to_legacy_instance')
    @mock.patch.object(base, 'obj_to_primitive')
    def test_to_legacy_request_spec_dict(self, image_to_primitive,
                                         spec_to_legacy_instance):
        fake_image_dict = mock.Mock()
        image_to_primitive.return_value = fake_image_dict
        fake_instance = {'root_gb': 1.0,
                         'ephemeral_gb': 1.0,
                         'memory_mb': 1.0,
                         'vcpus': 1,
                         'numa_topology': None,
                         'pci_requests': None,
                         'project_id': fakes.FAKE_PROJECT_ID,
                         'availability_zone': 'nova',
                         'uuid': '1'}
        spec_to_legacy_instance.return_value = fake_instance

        fake_flavor = objects.Flavor(root_gb=10,
                                     ephemeral_gb=0,
                                     memory_mb=512,
                                     vcpus=1)
        spec = objects.RequestSpec(num_instances=1,
                                   image=objects.ImageMeta(),
                                   # instance properties
                                   numa_topology=None,
                                   pci_requests=None,
                                   project_id=1,
                                   availability_zone='nova',
                                   instance_uuid=uuids.instance,
                                   flavor=fake_flavor)
        spec_dict = spec.to_legacy_request_spec_dict()
        expected = {'num_instances': 1,
                    'image': fake_image_dict,
                    'instance_properties': fake_instance,
                    'instance_type': fake_flavor}
        self.assertEqual(expected, spec_dict)

    def test_to_legacy_request_spec_dict_with_unset_values(self):
        spec = objects.RequestSpec()
        self.assertEqual({'num_instances': 1,
                          'image': {},
                          'instance_properties': {},
                          'instance_type': {}},
                         spec.to_legacy_request_spec_dict())

    def test_to_legacy_filter_properties_dict(self):
        fake_numa_limits = objects.NUMATopologyLimits()
        fake_computes_obj = objects.ComputeNodeList(
            objects=[objects.ComputeNode(host='fake1',
                                         hypervisor_hostname='node1')])
        fake_dest = objects.Destination(host='fakehost')
        spec = objects.RequestSpec(
            ignore_hosts=['ignoredhost'],
            force_hosts=['fakehost'],
            force_nodes=['fakenode'],
            retry=objects.SchedulerRetries(num_attempts=1,
                                           hosts=fake_computes_obj),
            limits=objects.SchedulerLimits(numa_topology=fake_numa_limits,
                                           vcpu=1.0,
                                           disk_gb=10.0,
                                           memory_mb=8192.0),
            instance_group=objects.InstanceGroup(hosts=['fake1'],
                                                 policies=['affinity'],
                                                 members=['inst1', 'inst2']),
            scheduler_hints={'foo': ['bar']},
            requested_destination=fake_dest)
        expected = {'ignore_hosts': ['ignoredhost'],
                    'force_hosts': ['fakehost'],
                    'force_nodes': ['fakenode'],
                    'retry': {'num_attempts': 1,
                              'hosts': [['fake1', 'node1']]},
                    'limits': {'numa_topology': fake_numa_limits,
                               'vcpu': 1.0,
                               'disk_gb': 10.0,
                               'memory_mb': 8192.0},
                    'group_updated': True,
                    'group_hosts': set(['fake1']),
                    'group_policies': set(['affinity']),
                    'group_members': set(['inst1', 'inst2']),
                    'scheduler_hints': {'foo': 'bar'},
                    'requested_destination': fake_dest}
        self.assertEqual(expected, spec.to_legacy_filter_properties_dict())

    def test_to_legacy_filter_properties_dict_with_nullable_values(self):
        spec = objects.RequestSpec(force_hosts=None,
                                   force_nodes=None,
                                   retry=None,
                                   limits=None,
                                   instance_group=None,
                                   scheduler_hints=None)
        self.assertEqual({}, spec.to_legacy_filter_properties_dict())

    def test_to_legacy_filter_properties_dict_with_unset_values(self):
        spec = objects.RequestSpec()
        self.assertEqual({}, spec.to_legacy_filter_properties_dict())

    @mock.patch.object(request_spec.RequestSpec,
            '_get_by_instance_uuid_from_db')
    @mock.patch('nova.objects.InstanceGroup.get_by_uuid')
    def test_get_by_instance_uuid(self, mock_get_ig, get_by_uuid):
        fake_spec = fake_request_spec.fake_db_spec()
        get_by_uuid.return_value = fake_spec
        mock_get_ig.return_value = objects.InstanceGroup(name='fresh')

        req_obj = request_spec.RequestSpec.get_by_instance_uuid(self.context,
                fake_spec['instance_uuid'])

        self.assertEqual(1, req_obj.num_instances)
        self.assertEqual(['host2', 'host4'], req_obj.ignore_hosts)
        self.assertEqual('fake', req_obj.project_id)
        self.assertEqual({'hint': ['over-there']}, req_obj.scheduler_hints)
        self.assertEqual(['host1', 'host3'], req_obj.force_hosts)
        self.assertIsNone(req_obj.availability_zone)
        self.assertEqual(['node1', 'node2'], req_obj.force_nodes)
        self.assertIsInstance(req_obj.image, objects.ImageMeta)
        self.assertIsInstance(req_obj.numa_topology,
                objects.InstanceNUMATopology)
        self.assertIsInstance(req_obj.pci_requests,
                objects.InstancePCIRequests)
        self.assertIsInstance(req_obj.flavor, objects.Flavor)
        self.assertIsInstance(req_obj.retry, objects.SchedulerRetries)
        self.assertIsInstance(req_obj.limits, objects.SchedulerLimits)
        self.assertIsInstance(req_obj.instance_group, objects.InstanceGroup)
        self.assertEqual('fresh', req_obj.instance_group.name)

    def _check_update_primitive(self, req_obj, changes):
        self.assertEqual(req_obj.instance_uuid, changes['instance_uuid'])
        serialized_obj = objects.RequestSpec.obj_from_primitive(
                jsonutils.loads(changes['spec']))

        # primitive fields
        for field in ['instance_uuid', 'num_instances', 'ignore_hosts',
                'project_id', 'scheduler_hints', 'force_hosts',
                'availability_zone', 'force_nodes']:
            self.assertEqual(getattr(req_obj, field),
                    getattr(serialized_obj, field))

        # object fields
        for field in ['image', 'numa_topology', 'pci_requests', 'flavor',
                      'limits']:
            self.assertEqual(
                    getattr(req_obj, field).obj_to_primitive(),
                    getattr(serialized_obj, field).obj_to_primitive())

        self.assertIsNone(serialized_obj.instance_group.members)
        self.assertIsNone(serialized_obj.instance_group.hosts)
        self.assertIsNone(serialized_obj.retry)
        self.assertIsNone(serialized_obj.requested_destination)

    def test_create(self):
        req_obj = fake_request_spec.fake_spec_obj(remove_id=True)

        def _test_create_args(self2, context, changes):
            self._check_update_primitive(req_obj, changes)
            # DB creation would have set an id
            changes['id'] = 42
            return changes

        with mock.patch.object(request_spec.RequestSpec, '_create_in_db',
                _test_create_args):
            req_obj.create()

    def test_create_id_set(self):
        req_obj = request_spec.RequestSpec(self.context)
        req_obj.id = 3

        self.assertRaises(exception.ObjectActionError, req_obj.create)

    def test_save(self):
        req_obj = fake_request_spec.fake_spec_obj()
        # Make sure the requested_destination is not persisted since it is
        # only valid per request/operation.
        req_obj.requested_destination = objects.Destination(host='fake')

        def _test_save_args(self2, context, instance_uuid, changes):
            self._check_update_primitive(req_obj, changes)
            # DB creation would have set an id
            changes['id'] = 42
            return changes

        with mock.patch.object(request_spec.RequestSpec, '_save_in_db',
                _test_save_args):
            req_obj.save()

    @mock.patch.object(request_spec.RequestSpec, '_destroy_in_db')
    def test_destroy(self, destroy_in_db):
        req_obj = fake_request_spec.fake_spec_obj()
        req_obj.destroy()

        destroy_in_db.assert_called_once_with(req_obj._context,
                                              req_obj.instance_uuid)

    @mock.patch.object(request_spec.RequestSpec, '_destroy_bulk_in_db')
    def test_destroy_bulk(self, destroy_bulk_in_db):
        uuids_to_be_deleted = []
        for i in range(0, 5):
            uuid = uuidutils.generate_uuid()
            uuids_to_be_deleted.append(uuid)
        destroy_bulk_in_db.return_value = 5
        result = objects.RequestSpec.destroy_bulk(self.context,
                                            uuids_to_be_deleted)
        destroy_bulk_in_db.assert_called_once_with(self.context,
                                            uuids_to_be_deleted)
        self.assertEqual(5, result)

    def test_reset_forced_destinations(self):
        req_obj = fake_request_spec.fake_spec_obj()
        # Making sure the fake object has forced hosts and nodes
        self.assertIsNotNone(req_obj.force_hosts)
        self.assertIsNotNone(req_obj.force_nodes)

        with mock.patch.object(req_obj, 'obj_reset_changes') as mock_reset:
            req_obj.reset_forced_destinations()
        self.assertIsNone(req_obj.force_hosts)
        self.assertIsNone(req_obj.force_nodes)
        mock_reset.assert_called_once_with(['force_hosts', 'force_nodes'])

    def test_compat_requested_destination(self):
        req_obj = objects.RequestSpec()
        versions = ovo_base.obj_tree_get_versions('RequestSpec')
        primitive = req_obj.obj_to_primitive(target_version='1.5',
                                             version_manifest=versions)
        self.assertNotIn('requested_destination', primitive)

    def test_compat_security_groups(self):
        sgl = objects.SecurityGroupList(objects=[])
        req_obj = objects.RequestSpec(security_groups=sgl)
        versions = ovo_base.obj_tree_get_versions('RequestSpec')
        primitive = req_obj.obj_to_primitive(target_version='1.7',
                                             version_manifest=versions)
        self.assertNotIn('security_groups', primitive)

    def test_default_requested_destination(self):
        req_obj = objects.RequestSpec()
        self.assertIsNone(req_obj.requested_destination)

    def test_security_groups_load(self):
        req_obj = objects.RequestSpec()
        self.assertNotIn('security_groups', req_obj)
        self.assertIsInstance(req_obj.security_groups,
                              objects.SecurityGroupList)
        self.assertIn('security_groups', req_obj)

    def test_create_raises_on_unchanged_object(self):
        ctxt = context.RequestContext(uuids.user_id, uuids.project_id)
        req_obj = request_spec.RequestSpec(context=ctxt)
        self.assertRaises(exception.ObjectActionError, req_obj.create)

    def test_save_can_be_called_on_unchanged_object(self):
        req_obj = fake_request_spec.fake_spec_obj(remove_id=True)
        req_obj.create()
        req_obj.save()


class TestRequestSpecObject(test_objects._LocalTest,
                            _TestRequestSpecObject):
    pass


class TestRemoteRequestSpecObject(test_objects._RemoteTest,
                                  _TestRequestSpecObject):
    pass

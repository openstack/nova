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
import collections

import mock
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
from oslo_versionedobjects import base as ovo_base

from nova import context
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.objects import base
from nova.objects import request_spec
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network_cache_model
from nova.tests.unit import fake_request_spec
from nova.tests.unit.objects import test_objects


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
        instance.user_id = fakes.FAKE_USER_ID
        instance.availability_zone = 'nova'

        spec = objects.RequestSpec()
        spec._from_instance(instance)
        instance_fields = ['numa_topology', 'pci_requests', 'uuid',
                           'project_id', 'user_id', 'availability_zone']
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
                        user_id=fakes.FAKE_USER_ID,
                        availability_zone='nova')

        spec = objects.RequestSpec()
        spec._from_instance(instance)
        instance_fields = ['numa_topology', 'pci_requests', 'uuid',
                           'project_id', 'user_id', 'availability_zone']
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
            user_id=fakes.FAKE_USER_ID,
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
            user_id=fakes.FAKE_USER_ID,
            availability_zone='nova',
            pci_requests=None,
            numa_topology=fake_request_spec.INSTANCE_NUMA_TOPOLOGY,
        )
        spec = objects.RequestSpec()

        spec._from_instance(instance)
        self.assertIsInstance(spec.numa_topology, objects.InstanceNUMATopology)
        cells = spec.numa_topology.cells
        self.assertEqual(2, len(cells))
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
        spec.user_id = fakes.FAKE_USER_ID
        spec.availability_zone = 'nova'

        instance = spec._to_legacy_instance()
        self.assertEqual({'root_gb': 10,
                          'ephemeral_gb': 0,
                          'memory_mb': 10,
                          'vcpus': 1,
                          'numa_topology': None,
                          'pci_requests': None,
                          'project_id': fakes.FAKE_PROJECT_ID,
                          'user_id': fakes.FAKE_USER_ID,
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
        # Make sure it can handle group uuid not being present.
        for group_uuid in (None, uuids.group_uuid):
            if group_uuid:
                filt_props['group_uuid'] = group_uuid
            spec = objects.RequestSpec()
            spec._populate_group_info(filt_props)
            self.assertIsInstance(spec.instance_group, objects.InstanceGroup)
            self.assertEqual('affinity', spec.instance_group.policy)
            self.assertEqual(['fake1'], spec.instance_group.hosts)
            self.assertEqual(['fake-instance1'], spec.instance_group.members)
            if group_uuid:
                self.assertEqual(uuids.group_uuid, spec.instance_group.uuid)

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
                         user_id=2,
                         availability_zone='nova')}
        filt_props = {}

        # We seriously don't care about the return values, we just want to make
        # sure that all the fields are set
        mock_limits.return_value = None

        ctxt = context.RequestContext('fake', 'fake')
        spec = objects.RequestSpec.from_primitives(ctxt, spec_dict, filt_props)
        mock_limits.assert_called_once_with({})
        # Make sure that all fields are set using that helper method
        skip = ['id', 'security_groups', 'network_metadata', 'is_bfv',
                'request_level_params']
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
        self.assertFalse(destination.allow_cross_cell_move)
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
        skip = ['id', 'network_metadata', 'is_bfv', 'request_level_params']
        for field in [f for f in spec.obj_fields if f not in skip]:
            self.assertTrue(spec.obj_attr_is_set(field),
                            'Field: %s is not set' % field)
        # just making sure that the context is set by the method
        self.assertEqual(ctxt, spec._context)
        self.assertEqual(destination, spec.requested_destination)
        self.assertFalse(spec.requested_destination.allow_cross_cell_move)

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

    def test_from_components_with_port_resource_request(self, ):
        ctxt = context.RequestContext(fakes.FAKE_USER_ID,
                                      fakes.FAKE_PROJECT_ID)
        instance = fake_instance.fake_instance_obj(ctxt)
        image = {'id': uuids.image_id, 'properties': {'mappings': []},
                 'status': 'fake-status', 'location': 'far-away'}
        flavor = fake_flavor.fake_flavor_obj(ctxt)
        filter_properties = {'fake': 'property'}

        rg = request_spec.RequestGroup()

        spec = objects.RequestSpec.from_components(ctxt, instance.uuid, image,
                flavor, instance.numa_topology, instance.pci_requests,
                filter_properties, None, instance.availability_zone,
                port_resource_requests=[rg])

        self.assertListEqual([rg], spec.requested_resources)

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
                                                 policy='affinity',
                                                 members=['inst1', 'inst2'],
                                                 uuid=uuids.group_uuid),
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
                    'group_uuid': uuids.group_uuid,
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

    def test_ensure_network_metadata(self):
        network_a = fake_network_cache_model.new_network({
            'physical_network': 'foo', 'tunneled': False})
        vif_a = fake_network_cache_model.new_vif({'network': network_a})
        network_b = fake_network_cache_model.new_network({
            'physical_network': 'foo', 'tunneled': False})
        vif_b = fake_network_cache_model.new_vif({'network': network_b})
        network_c = fake_network_cache_model.new_network({
            'physical_network': 'bar', 'tunneled': False})
        vif_c = fake_network_cache_model.new_vif({'network': network_c})
        network_d = fake_network_cache_model.new_network({
            'physical_network': None, 'tunneled': True})
        vif_d = fake_network_cache_model.new_vif({'network': network_d})
        nw_info = network_model.NetworkInfo([vif_a, vif_b, vif_c, vif_d])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=uuids.instance)
        instance = objects.Instance(id=3, uuid=uuids.instance,
                                    info_cache=info_cache)

        spec = objects.RequestSpec()
        self.assertNotIn('network_metadata', spec)

        spec.ensure_network_metadata(instance)
        self.assertIn('network_metadata', spec)
        self.assertIsInstance(spec.network_metadata, objects.NetworkMetadata)
        self.assertEqual(spec.network_metadata.physnets, set(['foo', 'bar']))
        self.assertTrue(spec.network_metadata.tunneled)

    def test_ensure_network_metadata_missing(self):
        nw_info = network_model.NetworkInfo([])
        info_cache = objects.InstanceInfoCache(network_info=nw_info,
                                               instance_uuid=uuids.instance)
        instance = objects.Instance(id=3, uuid=uuids.instance,
                                    info_cache=info_cache)

        spec = objects.RequestSpec()
        self.assertNotIn('network_metadata', spec)

        spec.ensure_network_metadata(instance)
        self.assertNotIn('network_metadata', spec)

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
        # ignore_hosts is not persisted
        self.assertIsNone(req_obj.ignore_hosts)
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
        # The 'retry' field is not persistent.
        self.assertIsNone(req_obj.retry)
        self.assertIsInstance(req_obj.limits, objects.SchedulerLimits)
        self.assertIsInstance(req_obj.instance_group, objects.InstanceGroup)
        self.assertEqual('fresh', req_obj.instance_group.name)

    def _check_update_primitive(self, req_obj, changes):
        self.assertEqual(req_obj.instance_uuid, changes['instance_uuid'])
        serialized_obj = objects.RequestSpec.obj_from_primitive(
                jsonutils.loads(changes['spec']))

        # primitive fields
        for field in ['instance_uuid', 'num_instances',
                'project_id', 'scheduler_hints', 'force_hosts',
                'availability_zone', 'force_nodes']:
            self.assertEqual(getattr(req_obj, field),
                    getattr(serialized_obj, field))

        # object fields
        for field in ['image', 'numa_topology', 'pci_requests', 'flavor',
                      'limits', 'network_metadata']:
            self.assertEqual(
                    getattr(req_obj, field).obj_to_primitive(),
                    getattr(serialized_obj, field).obj_to_primitive())

        self.assertIsNone(serialized_obj.instance_group.members)
        self.assertIsNone(serialized_obj.instance_group.hosts)
        self.assertIsNone(serialized_obj.retry)
        self.assertIsNone(serialized_obj.requested_destination)
        self.assertIsNone(serialized_obj.ignore_hosts)

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

    def test_create_does_not_persist_requested_fields(self):
        req_obj = fake_request_spec.fake_spec_obj(remove_id=True)

        expected_network_metadata = objects.NetworkMetadata(
            physnets=set(['foo', 'bar']), tunneled=True)
        req_obj.network_metadata = expected_network_metadata
        expected_destination = request_spec.Destination(host='sample-host')
        req_obj.requested_destination = expected_destination
        rg = request_spec.RequestGroup(resources={'fake-rc': 13})
        req_obj.requested_resources = [rg]
        expected_retry = objects.SchedulerRetries(
            num_attempts=2,
            hosts=objects.ComputeNodeList(objects=[
                objects.ComputeNode(host='host1', hypervisor_hostname='node1'),
                objects.ComputeNode(host='host2', hypervisor_hostname='node2'),
            ]))
        req_obj.retry = expected_retry

        orig_create_in_db = request_spec.RequestSpec._create_in_db
        with mock.patch.object(request_spec.RequestSpec, '_create_in_db') \
                as mock_create_in_db:
            mock_create_in_db.side_effect = orig_create_in_db
            req_obj.create()
            mock_create_in_db.assert_called_once()
            updates = mock_create_in_db.mock_calls[0][1][1]
            # assert that the following fields are not stored in the db
            # 1. network_metadata
            # 2. requested_destination
            # 3. requested_resources
            # 4. retry
            data = jsonutils.loads(updates['spec'])['nova_object.data']
            self.assertNotIn('network_metadata', data)
            self.assertIsNone(data['requested_destination'])
            self.assertIsNone(data['requested_resources'])
            self.assertIsNone(data['retry'])
            self.assertIsNotNone(data['instance_uuid'])

        # also we expect that the following fields are not reset after create
        # 1. network_metadata
        # 2. requested_destination
        # 3. requested_resources
        # 4. retry
        self.assertIsNotNone(req_obj.network_metadata)
        self.assertJsonEqual(expected_network_metadata.obj_to_primitive(),
                             req_obj.network_metadata.obj_to_primitive())
        self.assertIsNotNone(req_obj.requested_destination)
        self.assertJsonEqual(expected_destination.obj_to_primitive(),
                             req_obj.requested_destination.obj_to_primitive())
        self.assertIsNotNone(req_obj.requested_resources)
        self.assertEqual(
            13, req_obj.requested_resources[0].resources['fake-rc'])
        self.assertIsNotNone(req_obj.retry)
        self.assertJsonEqual(expected_retry.obj_to_primitive(),
                             req_obj.retry.obj_to_primitive())

    def test_save_does_not_persist_requested_fields(self):
        req_obj = fake_request_spec.fake_spec_obj(remove_id=True)
        req_obj.create()
        # change something to make sure _save_in_db is called
        expected_network_metadata = objects.NetworkMetadata(
            physnets=set(['foo', 'bar']), tunneled=True)
        req_obj.network_metadata = expected_network_metadata
        expected_destination = request_spec.Destination(host='sample-host')
        req_obj.requested_destination = expected_destination
        rg = request_spec.RequestGroup(resources={'fake-rc': 13})
        req_obj.requested_resources = [rg]
        expected_retry = objects.SchedulerRetries(
            num_attempts=2,
            hosts=objects.ComputeNodeList(objects=[
                objects.ComputeNode(host='host1', hypervisor_hostname='node1'),
                objects.ComputeNode(host='host2', hypervisor_hostname='node2'),
            ]))
        req_obj.retry = expected_retry
        req_obj.num_instances = 2
        req_obj.ignore_hosts = [uuids.ignored_host]

        orig_save_in_db = request_spec.RequestSpec._save_in_db
        with mock.patch.object(request_spec.RequestSpec, '_save_in_db') \
                as mock_save_in_db:
            mock_save_in_db.side_effect = orig_save_in_db
            req_obj.save()
            mock_save_in_db.assert_called_once()
            updates = mock_save_in_db.mock_calls[0][1][2]
            # assert that the following fields are not stored in the db
            # 1. network_metadata
            # 2. requested_destination
            # 3. requested_resources
            # 4. retry
            # 5. ignore_hosts
            data = jsonutils.loads(updates['spec'])['nova_object.data']
            self.assertNotIn('network_metadata', data)
            self.assertIsNone(data['requested_destination'])
            self.assertIsNone(data['requested_resources'])
            self.assertIsNone(data['retry'])
            self.assertIsNone(data['ignore_hosts'])
            self.assertIsNotNone(data['instance_uuid'])

        # also we expect that the following fields are not reset after save
        # 1. network_metadata
        # 2. requested_destination
        # 3. requested_resources
        # 4. retry
        # 5. ignore_hosts
        self.assertIsNotNone(req_obj.network_metadata)
        self.assertJsonEqual(expected_network_metadata.obj_to_primitive(),
                             req_obj.network_metadata.obj_to_primitive())
        self.assertIsNotNone(req_obj.requested_destination)
        self.assertJsonEqual(expected_destination.obj_to_primitive(),
                             req_obj.requested_destination.obj_to_primitive())
        self.assertIsNotNone(req_obj.requested_resources)
        self.assertEqual(13, req_obj.requested_resources[0].resources
                             ['fake-rc'])
        self.assertIsNotNone(req_obj.retry)
        self.assertJsonEqual(expected_retry.obj_to_primitive(),
                             req_obj.retry.obj_to_primitive())
        self.assertIsNotNone(req_obj.ignore_hosts)
        self.assertEqual([uuids.ignored_host], req_obj.ignore_hosts)

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
        req_obj = objects.RequestSpec(
            requested_destination=objects.Destination())
        versions = ovo_base.obj_tree_get_versions('RequestSpec')
        primitive = req_obj.obj_to_primitive(target_version='1.5',
                                             version_manifest=versions)
        self.assertNotIn(
            'requested_destination', primitive['nova_object.data'])

        primitive = req_obj.obj_to_primitive(target_version='1.6',
                                             version_manifest=versions)
        self.assertIn('requested_destination', primitive['nova_object.data'])

    def test_compat_security_groups(self):
        sgl = objects.SecurityGroupList(objects=[])
        req_obj = objects.RequestSpec(security_groups=sgl)
        versions = ovo_base.obj_tree_get_versions('RequestSpec')
        primitive = req_obj.obj_to_primitive(target_version='1.7',
                                             version_manifest=versions)
        self.assertNotIn('security_groups', primitive['nova_object.data'])

        primitive = req_obj.obj_to_primitive(target_version='1.8',
                                             version_manifest=versions)
        self.assertIn('security_groups', primitive['nova_object.data'])

    def test_compat_user_id(self):
        req_obj = objects.RequestSpec(project_id=fakes.FAKE_PROJECT_ID,
                                      user_id=fakes.FAKE_USER_ID)
        versions = ovo_base.obj_tree_get_versions('RequestSpec')
        primitive = req_obj.obj_to_primitive(target_version='1.8',
                                             version_manifest=versions)
        primitive = primitive['nova_object.data']
        self.assertNotIn('user_id', primitive)
        self.assertIn('project_id', primitive)

    def test_compat_network_metadata(self):
        network_metadata = objects.NetworkMetadata(physnets=set(),
                                                   tunneled=False)
        req_obj = objects.RequestSpec(network_metadata=network_metadata,
                                      user_id=fakes.FAKE_USER_ID)
        versions = ovo_base.obj_tree_get_versions('RequestSpec')
        primitive = req_obj.obj_to_primitive(target_version='1.9',
                                             version_manifest=versions)
        primitive = primitive['nova_object.data']
        self.assertNotIn('network_metadata', primitive)
        self.assertIn('user_id', primitive)

    def test_compat_requested_resources(self):
        req_obj = objects.RequestSpec(requested_resources=[],
                                      instance_uuid=uuids.instance)
        versions = ovo_base.obj_tree_get_versions('RequestSpec')
        primitive = req_obj.obj_to_primitive(target_version='1.11',
                                             version_manifest=versions)
        primitive = primitive['nova_object.data']
        self.assertNotIn('requested_resources', primitive)
        self.assertIn('instance_uuid', primitive)

    def test_default_requested_destination(self):
        req_obj = objects.RequestSpec()
        self.assertIsNone(req_obj.requested_destination)

    def test_security_groups_load(self):
        req_obj = objects.RequestSpec()
        self.assertNotIn('security_groups', req_obj)
        self.assertIsInstance(req_obj.security_groups,
                              objects.SecurityGroupList)
        self.assertIn('security_groups', req_obj)

    def test_network_requests_load(self):
        req_obj = objects.RequestSpec()
        self.assertNotIn('network_metadata', req_obj)
        self.assertIsInstance(req_obj.network_metadata,
                              objects.NetworkMetadata)
        self.assertIn('network_metadata', req_obj)

    def test_create_raises_on_unchanged_object(self):
        ctxt = context.RequestContext(uuids.user_id, uuids.project_id)
        req_obj = request_spec.RequestSpec(context=ctxt)
        self.assertRaises(exception.ObjectActionError, req_obj.create)

    def test_save_can_be_called_on_unchanged_object(self):
        req_obj = fake_request_spec.fake_spec_obj(remove_id=True)
        req_obj.create()
        req_obj.save()

    def test_get_request_group_mapping_no_request(self):
        req_obj = request_spec.RequestSpec()
        self.assertIsNone(req_obj.get_request_group_mapping())

    def test_get_request_group_mapping(self):
        req_obj = request_spec.RequestSpec(
            requested_resources=[
                request_spec.RequestGroup(
                    requester_id='requester1',
                    provider_uuids=[uuids.pr1, uuids.pr2]),
                request_spec.RequestGroup(
                    requester_id='requester2',
                    provider_uuids=[]),
            ])
        self.assertEqual(
            {'requester1': [uuids.pr1, uuids.pr2],
             'requester2': []},
            req_obj.get_request_group_mapping())


class TestRequestSpecObject(test_objects._LocalTest,
                            _TestRequestSpecObject):
    pass


class TestRemoteRequestSpecObject(test_objects._RemoteTest,
                                  _TestRequestSpecObject):
    pass


class TestRequestGroupObject(test.NoDBTestCase):
    def setUp(self):
        super(TestRequestGroupObject, self).setUp()
        self.user_id = uuids.user_id
        self.project_id = uuids.project_id
        self.context = context.RequestContext(uuids.user_id, uuids.project_id)

    def test_fields_defaulted_at_create(self):
        rg = request_spec.RequestGroup(self.context)
        self.assertTrue(rg.use_same_provider)
        self.assertEqual({}, rg.resources)
        self.assertEqual(set(), rg.required_traits)
        self.assertEqual(set(), rg.forbidden_traits)
        self.assertEqual([], rg.aggregates)
        self.assertIsNone(rg.requester_id)
        self.assertEqual([], rg.provider_uuids)
        self.assertIsNone(rg.in_tree)

    def test_from_port_request(self):
        port_resource_request = {
            "resources": {
                "NET_BW_IGR_KILOBIT_PER_SEC": 1000,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1000},
            "required": ["CUSTOM_PHYSNET_2",
                         "CUSTOM_VNIC_TYPE_NORMAL"]
        }
        rg = request_spec.RequestGroup.from_port_request(
            self.context, uuids.port_id, port_resource_request)

        self.assertTrue(rg.use_same_provider)
        self.assertEqual(
            {"NET_BW_IGR_KILOBIT_PER_SEC": 1000,
             "NET_BW_EGR_KILOBIT_PER_SEC": 1000},
            rg.resources)
        self.assertEqual({"CUSTOM_PHYSNET_2", "CUSTOM_VNIC_TYPE_NORMAL"},
                         rg.required_traits)
        self.assertEqual(uuids.port_id, rg.requester_id)
        # and the rest is defaulted
        self.assertEqual(set(), rg.forbidden_traits)
        self.assertEqual([], rg.aggregates)
        self.assertEqual([], rg.provider_uuids)

    def test_from_port_request_without_traits(self):
        port_resource_request = {
            "resources": {
                "NET_BW_IGR_KILOBIT_PER_SEC": 1000,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1000}}
        rg = request_spec.RequestGroup.from_port_request(
            self.context, uuids.port_id, port_resource_request)

        self.assertTrue(rg.use_same_provider)
        self.assertEqual(
            {"NET_BW_IGR_KILOBIT_PER_SEC": 1000,
             "NET_BW_EGR_KILOBIT_PER_SEC": 1000},
            rg.resources)
        self.assertEqual(uuids.port_id, rg.requester_id)
        # and the rest is defaulted
        self.assertEqual(set(), rg.required_traits)
        self.assertEqual(set(), rg.forbidden_traits)
        self.assertEqual([], rg.aggregates)
        self.assertEqual([], rg.provider_uuids)

    def test_compat_requester_and_provider(self):
        req_obj = objects.RequestGroup(
            requester_id=uuids.requester, provider_uuids=[uuids.rp1],
            required_traits=set(['CUSTOM_PHYSNET_2']),
            forbidden_aggregates=set(['agg3', 'agg4']))
        versions = ovo_base.obj_tree_get_versions('RequestGroup')
        primitive = req_obj.obj_to_primitive(
            target_version='1.3',
            version_manifest=versions)['nova_object.data']
        self.assertIn('forbidden_aggregates', primitive)
        self.assertIn('in_tree', primitive)
        self.assertIn('requester_id', primitive)
        self.assertIn('provider_uuids', primitive)
        self.assertIn('required_traits', primitive)
        self.assertItemsEqual(
                primitive['forbidden_aggregates'], set(['agg3', 'agg4']))
        primitive = req_obj.obj_to_primitive(
            target_version='1.2',
            version_manifest=versions)['nova_object.data']
        self.assertNotIn('forbidden_aggregates', primitive)
        self.assertIn('in_tree', primitive)
        self.assertIn('requester_id', primitive)
        self.assertIn('provider_uuids', primitive)
        self.assertIn('required_traits', primitive)
        primitive = req_obj.obj_to_primitive(
            target_version='1.1',
            version_manifest=versions)['nova_object.data']
        self.assertNotIn('forbidden_aggregates', primitive)
        self.assertNotIn('in_tree', primitive)
        self.assertIn('requester_id', primitive)
        self.assertIn('provider_uuids', primitive)
        self.assertIn('required_traits', primitive)
        primitive = req_obj.obj_to_primitive(
            target_version='1.0',
            version_manifest=versions)['nova_object.data']
        self.assertNotIn('forbidden_aggregates', primitive)
        self.assertNotIn('in_tree', primitive)
        self.assertNotIn('requester_id', primitive)
        self.assertNotIn('provider_uuids', primitive)
        self.assertIn('required_traits', primitive)


class TestDestinationObject(test.NoDBTestCase):
    def setUp(self):
        super(TestDestinationObject, self).setUp()
        self.user_id = uuids.user_id
        self.project_id = uuids.project_id
        self.context = context.RequestContext(uuids.user_id, uuids.project_id)

    def test_destination_aggregates_default(self):
        destination = objects.Destination()
        self.assertIsNone(destination.aggregates)

    def test_destination_require_aggregates(self):
        destination = objects.Destination()
        destination.require_aggregates(['foo', 'bar'])
        destination.require_aggregates(['baz'])
        self.assertEqual(['foo,bar', 'baz'], destination.aggregates)

    def test_destination_forbidden_aggregates_default(self):
        destination = objects.Destination()
        self.assertIsNone(destination.forbidden_aggregates)

    def test_destination_append_forbidden_aggregates(self):
        destination = objects.Destination()
        destination.append_forbidden_aggregates(set(['foo', 'bar']))
        self.assertEqual(
            set(['foo', 'bar']), destination.forbidden_aggregates)
        destination.append_forbidden_aggregates(set(['bar', 'baz']))
        self.assertEqual(
            set(['foo', 'bar', 'baz']), destination.forbidden_aggregates)

    def test_obj_make_compatible(self):
        values = {
            'host': 'fake_host',
            'node': 'fake_node',
            'cell': objects.CellMapping(uuid=uuids.cell1),
            'aggregates': ['agg1', 'agg2'],
            'allow_cross_cell_move': False,
            'forbidden_aggregates': set(['agg3', 'agg4'])}
        obj = objects.Destination(self.context, **values)
        data = lambda x: x['nova_object.data']
        manifest = ovo_base.obj_tree_get_versions(obj.obj_name())

        obj_primitive = data(obj.obj_to_primitive(target_version='1.4',
                                                  version_manifest=manifest))
        self.assertIn('forbidden_aggregates', obj_primitive)
        self.assertItemsEqual(obj_primitive['forbidden_aggregates'],
                              set(['agg3', 'agg4']))
        self.assertIn('aggregates', obj_primitive)

        obj_primitive = data(obj.obj_to_primitive(target_version='1.3',
                                                  version_manifest=manifest))
        self.assertNotIn('forbidden_aggregates', obj_primitive)
        self.assertIn('allow_cross_cell_move', obj_primitive)

        obj_primitive = data(obj.obj_to_primitive(target_version='1.2',
                                                  version_manifest=manifest))
        self.assertIn('aggregates', obj_primitive)
        self.assertNotIn('allow_cross_cell_move', obj_primitive)

        obj_primitive = data(obj.obj_to_primitive(target_version='1.1',
                                                  version_manifest=manifest))
        self.assertIn('cell', obj_primitive)
        self.assertNotIn('aggregates', obj_primitive)

        obj_primitive = data(obj.obj_to_primitive(target_version='1.0',
                                                  version_manifest=manifest))
        self.assertNotIn('forbidden_aggregates', obj_primitive)
        self.assertNotIn('cell', obj_primitive)
        self.assertEqual('fake_host', obj_primitive['host'])


class TestMappingRequestGroupsToProviders(test.NoDBTestCase):
    def setUp(self):
        super(TestMappingRequestGroupsToProviders, self).setUp()
        self.spec = request_spec.RequestSpec()

    def test_no_groups(self):
        allocations = None
        provider_traits = {}

        self.spec.map_requested_resources_to_providers(
            allocations, provider_traits)

        # we cannot assert much, at least we see that the above call doesn't
        # blow
        self.assertIsNone(self.spec.requested_resources)

    def test_unnumbered_group_not_supported(self):
        allocations = {}
        provider_traits = {}
        group1 = request_spec.RequestGroup(
            use_same_provider=False)
        self.spec.requested_resources = [group1]

        self.assertRaises(
            NotImplementedError,
            self.spec.map_requested_resources_to_providers, allocations,
            provider_traits)

    def test_forbidden_traits_not_supported(self):
        allocations = {}
        provider_traits = {}
        group1 = request_spec.RequestGroup(
            forbidden_traits={'STORAGE_DISK_HDD'})
        self.spec.requested_resources = [group1]

        self.assertRaises(
            NotImplementedError,
            self.spec.map_requested_resources_to_providers, allocations,
            provider_traits)

    def test_aggregates_not_supported(self):
        allocations = {}
        provider_traits = {}
        group1 = request_spec.RequestGroup(
            aggregates=[[uuids.agg1]])
        self.spec.requested_resources = [group1]

        self.assertRaises(
            NotImplementedError,
            self.spec.map_requested_resources_to_providers, allocations,
            provider_traits)

    def test_one_group(self):
        allocations = {
            uuids.compute1_rp: {
                "resources": {
                    'VCPU': 1
                }
            },
            uuids.net_dev1_rp: {
                "resources": {
                    'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                    'NET_BW_EGR_KILOBIT_PER_SEC': 1,
                }
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_rp: [
                'CUSTOM_PHYSNET_PHYSNET0',
                'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1]

        self.spec.map_requested_resources_to_providers(
            allocations, provider_traits)

        self.assertEqual([uuids.net_dev1_rp], group1.provider_uuids)

    def test_one_group_no_matching_allocation(self):
        # NOTE(gibi): This negative test scenario should not happen in real
        # end to end test as we assume that placement only returns candidates
        # that are valid. But still we want to cover the error case in our
        # implementation

        allocations = {
            uuids.compute1_rp: {
                "resources": {
                    'VCPU': 1
                }
            },
            uuids.net_dev1_rp: {
                "resources": {
                    'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                }
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1]

        self.assertRaises(
            ValueError, self.spec.map_requested_resources_to_providers,
            allocations, provider_traits)

    def test_one_group_no_matching_trait(self):
        # NOTE(gibi): This negative test scenario should not happen in real
        # end to end test as we assume that placement only returns candidates
        # that are valid. But still we want to cover the error case in our
        # implementation

        allocations = {
            uuids.compute1_rp: {
                "resources": {
                    'VCPU': 1
                }
            },
            uuids.net_dev1_rp: {
                "resources": {
                    'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                    'NET_BW_EGR_KILOBIT_PER_SEC': 1,
                }
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_rp: [
                'CUSTOM_PHYSNET_PHYSNET1',
                'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1]

        self.assertRaises(
            ValueError, self.spec.map_requested_resources_to_providers,
            allocations, provider_traits)

    def test_two_groups_same_provider(self):
        allocations = {
            uuids.compute1_rp: {
                "resources": {
                    'VCPU': 1
                }
            },
            uuids.net_dev1_rp: {
                "resources": {
                    'NET_BW_IGR_KILOBIT_PER_SEC': 3,
                    'NET_BW_EGR_KILOBIT_PER_SEC': 3,
                }
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_rp: [
                'CUSTOM_PHYSNET_PHYSNET0',
                'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }

        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        group2 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 2,
                "NET_BW_EGR_KILOBIT_PER_SEC": 2,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1, group2]

        self.spec.map_requested_resources_to_providers(
            allocations, provider_traits)

        self.assertEqual([uuids.net_dev1_rp], group1.provider_uuids)
        self.assertEqual([uuids.net_dev1_rp], group2.provider_uuids)

    def test_two_groups_different_providers(self):
        # NOTE(gibi): we use OrderedDict here to make the test deterministic
        allocations = collections.OrderedDict()
        allocations[uuids.compute1_rp] = {
            "resources": {
                    'VCPU': 1
                }
        }
        allocations[uuids.net_dev1_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 2,
                'NET_BW_EGR_KILOBIT_PER_SEC': 2,
            }
        }
        allocations[uuids.net_dev2_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                'NET_BW_EGR_KILOBIT_PER_SEC': 1,
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_rp: [
                'CUSTOM_PHYSNET_PHYSNET0',
                'CUSTOM_VNIC_TYPE_NORMAL'
            ],
            uuids.net_dev2_rp: [
                'CUSTOM_PHYSNET_PHYSNET0',
                'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        group2 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 2,
                "NET_BW_EGR_KILOBIT_PER_SEC": 2,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1, group2]

        self.spec.map_requested_resources_to_providers(
            allocations, provider_traits)

        self.assertEqual([uuids.net_dev2_rp], group1.provider_uuids)
        self.assertEqual([uuids.net_dev1_rp], group2.provider_uuids)

    def test_two_groups_different_providers_reverse(self):
        """Similar as test_two_groups_different_providers but reorder the
        groups to exercises another code path
        """
        # NOTE(gibi): we use OrderedDict here to make the test deterministic
        allocations = collections.OrderedDict()
        allocations[uuids.compute1_rp] = {
            "resources": {
                    'VCPU': 1
                }
        }
        allocations[uuids.net_dev1_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 2,
                'NET_BW_EGR_KILOBIT_PER_SEC': 2,
            }
        }
        allocations[uuids.net_dev2_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                'NET_BW_EGR_KILOBIT_PER_SEC': 1,
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
            uuids.net_dev2_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 2,
                "NET_BW_EGR_KILOBIT_PER_SEC": 2,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        group2 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1, group2]

        self.spec.map_requested_resources_to_providers(
            allocations, provider_traits)

        self.assertEqual([uuids.net_dev1_rp], group1.provider_uuids)
        self.assertEqual([uuids.net_dev2_rp], group2.provider_uuids)

    def test_two_groups_different_providers_different_traits(self):

        allocations = collections.OrderedDict()
        allocations[uuids.compute1_rp] = {
            "resources": {
                'VCPU': 1
            }
        }
        allocations[uuids.net_dev1_physnet1_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                'NET_BW_EGR_KILOBIT_PER_SEC': 1,
            }
        }
        allocations[uuids.net_dev2_physnet0_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                'NET_BW_EGR_KILOBIT_PER_SEC': 1,
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_physnet1_rp: [
                'CUSTOM_PHYSNET_PHYSNET1', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
            uuids.net_dev2_physnet0_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        group2 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET1",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1, group2]

        self.spec.map_requested_resources_to_providers(
            allocations, provider_traits)

        self.assertEqual([uuids.net_dev2_physnet0_rp], group1.provider_uuids)
        self.assertEqual([uuids.net_dev1_physnet1_rp], group2.provider_uuids)

    def test_three_groups(self):
        """A complex example where a lot of mappings are tried before the
        solution is found.
        """
        allocations = collections.OrderedDict()
        allocations[uuids.compute1_rp] = {
            "resources": {
                'VCPU': 1
            }
        }
        allocations[uuids.net_dev1_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 3,
                'NET_BW_EGR_KILOBIT_PER_SEC': 3,
            }
        }
        allocations[uuids.net_dev2_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 2,
                'NET_BW_EGR_KILOBIT_PER_SEC': 2,
            }
        }
        allocations[uuids.net_dev3_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                'NET_BW_EGR_KILOBIT_PER_SEC': 3,
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
            uuids.net_dev2_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
            uuids.net_dev3_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        # this fits to 2 RPs
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 3,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        # this fits to 2 RPs
        group2 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 2,
                "NET_BW_EGR_KILOBIT_PER_SEC": 2,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        # this fits to only one RPs
        group3 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 3,
                "NET_BW_EGR_KILOBIT_PER_SEC": 3,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1, group2, group3]

        orig_validator = self.spec._is_valid_group_rp_mapping
        with mock.patch.object(
                self.spec, '_is_valid_group_rp_mapping',
                side_effect=orig_validator
        ) as mock_validator:
            self.spec.map_requested_resources_to_providers(
                allocations, provider_traits)

        self.assertEqual([uuids.net_dev3_rp], group1.provider_uuids)
        self.assertEqual([uuids.net_dev2_rp], group2.provider_uuids)
        self.assertEqual([uuids.net_dev1_rp], group3.provider_uuids)

        # the algorithm tried out many possible mappings before found the
        # the solution
        self.assertEqual(58, mock_validator.call_count)

    @mock.patch.object(request_spec.LOG, 'debug')
    def test_two_groups_matches_but_allocation_leftover(self, mock_debug):
        # NOTE(gibi): This negative test scenario should not happen in real
        # end to end test as we assume that placement only returns candidates
        # that are valid and this candidate is not valid as it provides more
        # resources than the ports are requesting. Still we want to cover the
        # error case in our implementation

        allocations = collections.OrderedDict()
        allocations[uuids.compute1_rp] = {
            "resources": {
                'VCPU': 1
            }
        }
        allocations[uuids.net_dev1_physnet0_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 2,
                'NET_BW_EGR_KILOBIT_PER_SEC': 2,
            }
        }
        allocations[uuids.net_dev2_physnet0_rp] = {
            "resources": {
                'NET_BW_IGR_KILOBIT_PER_SEC': 1,
                'NET_BW_EGR_KILOBIT_PER_SEC': 1,
            }
        }
        provider_traits = {
            uuids.compute1_rp: [],
            uuids.net_dev1_physnet0_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
            uuids.net_dev2_physnet0_rp: [
                'CUSTOM_PHYSNET_PHYSNET0', 'CUSTOM_VNIC_TYPE_NORMAL'
            ],
        }
        group1 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        group2 = request_spec.RequestGroup(
            resources={
                "NET_BW_IGR_KILOBIT_PER_SEC": 1,
                "NET_BW_EGR_KILOBIT_PER_SEC": 1,
            },
            required_traits={
                "CUSTOM_PHYSNET_PHYSNET0",
                "CUSTOM_VNIC_TYPE_NORMAL",
            })
        self.spec.requested_resources = [group1, group2]

        self.assertRaises(
            ValueError, self.spec.map_requested_resources_to_providers,
            allocations, provider_traits)

        self.assertIn('allocations leftover', mock_debug.mock_calls[3][1][0])

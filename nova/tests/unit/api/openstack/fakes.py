# Copyright 2010 OpenStack Foundation
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

import datetime

from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import routes
import six
from six.moves import range
import webob.dec

from nova.api import auth as api_auth
from nova.api import openstack as openstack_api
from nova.api.openstack import api_version_request as api_version
from nova.api.openstack import compute
from nova.api.openstack.compute import versions
from nova.api.openstack import urlmap
from nova.api.openstack import wsgi as os_wsgi
from nova.api import wsgi
from nova.compute import flavors
from nova.compute import vm_states
import nova.conf
from nova import context
from nova.db.sqlalchemy import models
from nova import exception as exc
from nova.network.security_group import security_group_base
from nova import objects
from nova.objects import base
from nova import quota
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_network
from nova.tests.unit.objects import test_keypair
from nova import utils


CONF = nova.conf.CONF
QUOTAS = quota.QUOTAS


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_PROJECT_ID = '6a6a9c9eee154e9cb8cec487b98d36ab'
FAKE_USER_ID = '5fae60f5cf4642609ddd31f71748beac'
FAKE_UUIDS = {}


@webob.dec.wsgify
def fake_wsgi(self, req):
    return self.application


def wsgi_app_v21(fake_auth_context=None, v2_compatible=False,
                 custom_routes=None):

    inner_app_v21 = compute.APIRouterV21(custom_routes=custom_routes)

    if v2_compatible:
        inner_app_v21 = openstack_api.LegacyV2CompatibleWrapper(inner_app_v21)

    if fake_auth_context is not None:
        ctxt = fake_auth_context
    else:
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
    api_v21 = openstack_api.FaultWrapper(
          api_auth.InjectContext(ctxt, inner_app_v21))
    mapper = urlmap.URLMap()
    mapper['/v2'] = api_v21
    mapper['/v2.1'] = api_v21
    mapper['/'] = openstack_api.FaultWrapper(versions.Versions())
    return mapper


def stub_out_key_pair_funcs(testcase, have_key_pair=True, **kwargs):
    def key_pair(context, user_id):
        return [dict(test_keypair.fake_keypair,
                     name='key', public_key='public_key', **kwargs)]

    def one_key_pair(context, user_id, name):
        if name in ['key', 'new-key']:
            return dict(test_keypair.fake_keypair,
                        name=name, public_key='public_key', **kwargs)
        else:
            raise exc.KeypairNotFound(user_id=user_id, name=name)

    def no_key_pair(context, user_id):
        return []

    if have_key_pair:
        testcase.stub_out('nova.db.api.key_pair_get_all_by_user', key_pair)
        testcase.stub_out('nova.db.api.key_pair_get', one_key_pair)
    else:
        testcase.stub_out('nova.db.api.key_pair_get_all_by_user', no_key_pair)


def stub_out_trusted_certs(test, certs=None):
    def fake_trusted_certs(cls, context, instance_uuid):
        return objects.TrustedCerts(ids=trusted_certs)

    def fake_instance_extra(context, instance_uuid, columns):
        if columns is ['trusted_certs']:
            return {'trusted_certs': trusted_certs}
        else:
            return {'numa_topology': None,
                    'pci_requests': None,
                    'flavor': None,
                    'vcpu_model': None,
                    'trusted_certs': trusted_certs,
                    'migration_context': None}

    trusted_certs = []
    if certs:
        trusted_certs = certs
    test.stub_out('nova.objects.TrustedCerts.get_by_instance_uuid',
                  fake_trusted_certs)
    test.stub_out('nova.db.instance_extra_get_by_instance_uuid',
                  fake_instance_extra)


def stub_out_instance_quota(test, allowed, quota, resource='instances'):
    def fake_reserve(context, **deltas):
        requested = deltas.pop(resource, 0)
        if requested > allowed:
            quotas = dict(instances=1, cores=1, ram=1)
            quotas[resource] = quota
            usages = dict(instances=dict(in_use=0, reserved=0),
                          cores=dict(in_use=0, reserved=0),
                          ram=dict(in_use=0, reserved=0))
            usages[resource]['in_use'] = (quotas[resource] * 9 // 10 - allowed)
            usages[resource]['reserved'] = quotas[resource] // 10
            raise exc.OverQuota(overs=[resource], quotas=quotas,
                                usages=usages)
    test.stub_out('nova.quota.QUOTAS.reserve', fake_reserve)


def stub_out_networking(test):
    def get_my_ip():
        return '127.0.0.1'
    test.stub_out('oslo_utils.netutils.get_my_ipv4', get_my_ip)


def stub_out_compute_api_snapshot(test):

    def snapshot(self, context, instance, name, extra_properties=None):
        # emulate glance rejecting image names which are too long
        if len(name) > 256:
            raise exc.Invalid
        return dict(id='123', status='ACTIVE', name=name,
                    properties=extra_properties)

    test.stub_out('nova.compute.api.API.snapshot', snapshot)


class stub_out_compute_api_backup(object):

    def __init__(self, test):
        self.extra_props_last_call = None
        test.stub_out('nova.compute.api.API.backup', self.backup)

    def backup(self, context, instance, name, backup_type, rotation,
               extra_properties=None):
        self.extra_props_last_call = extra_properties
        props = dict(backup_type=backup_type,
                     rotation=rotation)
        props.update(extra_properties or {})
        return dict(id='123', status='ACTIVE', name=name, properties=props)


def stub_out_nw_api_get_instance_nw_info(test, num_networks=1, func=None):
    fake_network.stub_out_nw_api_get_instance_nw_info(test)


def stub_out_nw_api(test, cls=None, private=None, publics=None):
    if not private:
        private = '192.168.0.3'
    if not publics:
        publics = ['1.2.3.4']

    class Fake(object):
        def __init__(self):
            pass

        def get_instance_nw_info(*args, **kwargs):
            pass

        def get_floating_ips_by_fixed_address(*args, **kwargs):
            return publics

        def validate_networks(self, context, networks, max_count):
            return max_count

        def create_resource_requests(self, context, requested_networks,
                                     pci_requests):
            return None, []

    if cls is None:
        cls = Fake
    if CONF.use_neutron:
        test.stub_out('nova.network.neutronv2.api.API', cls)
    else:
        test.stub_out('nova.network.api.API', cls)
        fake_network.stub_out_nw_api_get_instance_nw_info(test)


def stub_out_secgroup_api(test, security_groups=None):

    class FakeSecurityGroupAPI(security_group_base.SecurityGroupBase):
        """This handles both nova-network and neutron style security group APIs
        """
        def get_instances_security_groups_bindings(
                self, context, servers, detailed=False):
            # This method shouldn't be called unless using neutron.
            if not CONF.use_neutron:
                raise Exception('Invalid security group API call for nova-net')
            instances_security_group_bindings = {}
            if servers:
                instances_security_group_bindings = {
                    server['id']: [] for server in servers
                }
            return instances_security_group_bindings

        def get_instance_security_groups(
                self, context, instance, detailed=False):
            return security_groups if security_groups is not None else []

    if CONF.use_neutron:
        test.stub_out(
            'nova.network.security_group.neutron_driver.SecurityGroupAPI',
            FakeSecurityGroupAPI)
    else:
        test.stub_out(
            'nova.compute.api.SecurityGroupAPI', FakeSecurityGroupAPI)


class FakeToken(object):
    id_count = 0

    def __getitem__(self, key):
        return getattr(self, key)

    def __init__(self, **kwargs):
        FakeToken.id_count += 1
        self.id = FakeToken.id_count
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeRequestContext(context.RequestContext):
    def __init__(self, *args, **kwargs):
        kwargs['auth_token'] = kwargs.get('auth_token', 'fake_auth_token')
        super(FakeRequestContext, self).__init__(*args, **kwargs)


class HTTPRequest(os_wsgi.Request):

    @classmethod
    def blank(cls, *args, **kwargs):
        defaults = {'base_url': 'http://localhost/v2'}
        use_admin_context = kwargs.pop('use_admin_context', False)
        project_id = kwargs.pop('project_id', 'fake')
        version = kwargs.pop('version', os_wsgi.DEFAULT_API_VERSION)
        defaults.update(kwargs)
        out = super(HTTPRequest, cls).blank(*args, **defaults)
        out.environ['nova.context'] = FakeRequestContext(
            user_id='fake_user',
            project_id=project_id,
            is_admin=use_admin_context)
        out.api_version_request = api_version.APIVersionRequest(version)
        return out


class HTTPRequestV21(HTTPRequest):
    pass


class TestRouter(wsgi.Router):
    def __init__(self, controller, mapper=None):
        if not mapper:
            mapper = routes.Mapper()
        mapper.resource("test", "tests",
                        controller=os_wsgi.Resource(controller))
        super(TestRouter, self).__init__(mapper)


class FakeAuthDatabase(object):
    data = {}

    @staticmethod
    def auth_token_get(context, token_hash):
        return FakeAuthDatabase.data.get(token_hash, None)

    @staticmethod
    def auth_token_create(context, token):
        fake_token = FakeToken(created_at=timeutils.utcnow(), **token)
        FakeAuthDatabase.data[fake_token.token_hash] = fake_token
        FakeAuthDatabase.data['id_%i' % fake_token.id] = fake_token
        return fake_token

    @staticmethod
    def auth_token_destroy(context, token_id):
        token = FakeAuthDatabase.data.get('id_%i' % token_id)
        if token and token.token_hash in FakeAuthDatabase.data:
            del FakeAuthDatabase.data[token.token_hash]
            del FakeAuthDatabase.data['id_%i' % token_id]


def create_info_cache(nw_cache):
    if nw_cache is None:
        pub0 = ('192.168.1.100',)
        pub1 = ('2001:db8:0:1::1',)

        def _ip(ip):
            return {'address': ip, 'type': 'fixed'}

        nw_cache = [
            {'address': 'aa:aa:aa:aa:aa:aa',
             'id': 1,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'test1',
                         'subnets': [{'cidr': '192.168.1.0/24',
                                      'ips': [_ip(ip) for ip in pub0]},
                                      {'cidr': 'b33f::/64',
                                       'ips': [_ip(ip) for ip in pub1]}]}}]

    if not isinstance(nw_cache, six.string_types):
        nw_cache = jsonutils.dumps(nw_cache)

    return {
        "info_cache": {
            "network_info": nw_cache,
            "deleted": False,
            "created_at": None,
            "deleted_at": None,
            "updated_at": None,
            }
        }


def get_fake_uuid(token=0):
    if token not in FAKE_UUIDS:
        FAKE_UUIDS[token] = uuidutils.generate_uuid()
    return FAKE_UUIDS[token]


def fake_instance_get(**kwargs):
    def _return_server(context, uuid, columns_to_join=None, use_slave=False):
        if 'project_id' not in kwargs:
            kwargs['project_id'] = 'fake'
        return stub_instance(1, **kwargs)
    return _return_server


def fake_compute_get(**kwargs):
    def _return_server_obj(context, *a, **kw):
        return stub_instance_obj(context, **kwargs)
    return _return_server_obj


def fake_actions_to_locked_server(self, context, instance, *args, **kwargs):
    raise exc.InstanceIsLocked(instance_uuid=instance['uuid'])


def fake_instance_get_all_by_filters(num_servers=5, **kwargs):
    def _return_servers(context, *args, **kwargs):
        servers_list = []
        marker = None
        limit = None
        found_marker = False
        if "marker" in kwargs:
            marker = kwargs["marker"]
        if "limit" in kwargs:
            limit = kwargs["limit"]

        if 'columns_to_join' in kwargs:
            kwargs.pop('columns_to_join')

        if 'use_slave' in kwargs:
            kwargs.pop('use_slave')

        if 'sort_keys' in kwargs:
            kwargs.pop('sort_keys')

        if 'sort_dirs' in kwargs:
            kwargs.pop('sort_dirs')

        if 'cell_mappings' in kwargs:
            kwargs.pop('cell_mappings')

        for i in range(num_servers):
            uuid = get_fake_uuid(i)
            server = stub_instance(id=i + 1, uuid=uuid,
                    **kwargs)
            servers_list.append(server)
            if marker is not None and uuid == marker:
                found_marker = True
                servers_list = []
        if marker is not None and not found_marker:
            raise exc.MarkerNotFound(marker=marker)
        if limit is not None:
            servers_list = servers_list[:limit]
        return servers_list
    return _return_servers


def fake_compute_get_all(num_servers=5, **kwargs):
    def _return_servers_objs(context, search_opts=None, limit=None,
                             marker=None, expected_attrs=None, sort_keys=None,
                             sort_dirs=None, cell_down_support=False,
                             all_tenants=False):
        db_insts = fake_instance_get_all_by_filters()(None,
                                                      limit=limit,
                                                      marker=marker)
        expected = ['metadata', 'system_metadata', 'flavor',
                    'info_cache', 'security_groups']
        return base.obj_make_list(context, objects.InstanceList(),
                                  objects.Instance, db_insts,
                                  expected_attrs=expected)
    return _return_servers_objs


def stub_instance(id=1, user_id=None, project_id=None, host=None,
                  node=None, vm_state=None, task_state=None,
                  reservation_id="", uuid=FAKE_UUID, image_ref="10",
                  flavor_id="1", name=None, key_name='',
                  access_ipv4=None, access_ipv6=None, progress=0,
                  auto_disk_config=False, display_name=None,
                  display_description=None,
                  include_fake_metadata=True, config_drive=None,
                  power_state=None, nw_cache=None, metadata=None,
                  security_groups=None, root_device_name=None,
                  limit=None, marker=None,
                  launched_at=timeutils.utcnow(),
                  terminated_at=timeutils.utcnow(),
                  availability_zone='', locked_by=None, cleaned=False,
                  memory_mb=0, vcpus=0, root_gb=0, ephemeral_gb=0,
                  instance_type=None, launch_index=0, kernel_id="",
                  ramdisk_id="", user_data=None, system_metadata=None,
                  services=None, trusted_certs=None, hidden=False):
    if user_id is None:
        user_id = 'fake_user'
    if project_id is None:
        project_id = 'fake_project'

    if metadata:
        metadata = [{'key': k, 'value': v} for k, v in metadata.items()]
    elif include_fake_metadata:
        metadata = [models.InstanceMetadata(key='seq', value=str(id))]
    else:
        metadata = []

    inst_type = flavors.get_flavor_by_flavor_id(int(flavor_id))
    sys_meta = flavors.save_flavor_info({}, inst_type)
    sys_meta.update(system_metadata or {})

    if host is not None:
        host = str(host)

    if key_name:
        key_data = 'FAKE'
    else:
        key_data = ''

    if security_groups is None:
        security_groups = [{"id": 1, "name": "test", "description": "Foo:",
                            "project_id": "project", "user_id": "user",
                            "created_at": None, "updated_at": None,
                            "deleted_at": None, "deleted": False}]

    # ReservationID isn't sent back, hack it in there.
    server_name = name or "server%s" % id
    if reservation_id != "":
        server_name = "reservation_%s" % (reservation_id, )

    info_cache = create_info_cache(nw_cache)

    if instance_type is None:
        instance_type = objects.Flavor.get_by_name(
            context.get_admin_context(), 'm1.small')
    flavorinfo = jsonutils.dumps({
        'cur': instance_type.obj_to_primitive(),
        'old': None,
        'new': None,
    })

    instance = {
        "id": int(id),
        "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
        "deleted_at": datetime.datetime(2010, 12, 12, 10, 0, 0),
        "deleted": None,
        "user_id": user_id,
        "project_id": project_id,
        "image_ref": image_ref,
        "kernel_id": kernel_id,
        "ramdisk_id": ramdisk_id,
        "launch_index": launch_index,
        "key_name": key_name,
        "key_data": key_data,
        "config_drive": config_drive,
        "vm_state": vm_state or vm_states.ACTIVE,
        "task_state": task_state,
        "power_state": power_state,
        "memory_mb": memory_mb,
        "vcpus": vcpus,
        "root_gb": root_gb,
        "ephemeral_gb": ephemeral_gb,
        "ephemeral_key_uuid": None,
        "hostname": display_name or server_name,
        "host": host,
        "node": node,
        "instance_type_id": 1,
        "instance_type": inst_type,
        "user_data": user_data,
        "reservation_id": reservation_id,
        "mac_address": "",
        "launched_at": launched_at,
        "terminated_at": terminated_at,
        "availability_zone": availability_zone,
        "display_name": display_name or server_name,
        "display_description": display_description,
        "locked": locked_by is not None,
        "locked_by": locked_by,
        "metadata": metadata,
        "access_ip_v4": access_ipv4,
        "access_ip_v6": access_ipv6,
        "uuid": uuid,
        "progress": progress,
        "auto_disk_config": auto_disk_config,
        "name": "instance-%s" % id,
        "shutdown_terminate": True,
        "disable_terminate": False,
        "security_groups": security_groups,
        "root_device_name": root_device_name,
        "system_metadata": utils.dict_to_metadata(sys_meta),
        "pci_devices": [],
        "vm_mode": "",
        "default_swap_device": "",
        "default_ephemeral_device": "",
        "launched_on": "",
        "cell_name": "",
        "architecture": "",
        "os_type": "",
        "extra": {"numa_topology": None,
                  "pci_requests": None,
                  "flavor": flavorinfo,
                  "trusted_certs": trusted_certs,
                  },
        "cleaned": cleaned,
        "services": services,
        "tags": [],
        "hidden": hidden,
    }

    instance.update(info_cache)
    instance['info_cache']['instance_uuid'] = instance['uuid']

    return instance


def stub_instance_obj(ctxt, *args, **kwargs):
    db_inst = stub_instance(*args, **kwargs)
    expected = ['metadata', 'system_metadata', 'flavor',
                'info_cache', 'security_groups', 'tags']
    inst = objects.Instance._from_db_object(ctxt, objects.Instance(),
                                            db_inst,
                                            expected_attrs=expected)
    inst.fault = None
    if db_inst["services"] is not None:
        #  This ensures services there if one wanted so
        inst.services = db_inst["services"]

    return inst


def stub_volume(id, **kwargs):
    volume = {
        'id': id,
        'user_id': 'fakeuser',
        'project_id': 'fakeproject',
        'host': 'fakehost',
        'size': 1,
        'availability_zone': 'fakeaz',
        'status': 'fakestatus',
        'attach_status': 'attached',
        'name': 'vol name',
        'display_name': 'displayname',
        'display_description': 'displaydesc',
        'created_at': datetime.datetime(1999, 1, 1, 1, 1, 1),
        'snapshot_id': None,
        'volume_type_id': 'fakevoltype',
        'volume_metadata': [],
        'volume_type': {'name': 'vol_type_name'},
        'multiattach': False,
        'attachments': {'fakeuuid': {'mountpoint': '/'},
                        'fakeuuid2': {'mountpoint': '/dev/sdb'}
                        }
              }

    volume.update(kwargs)
    return volume


def stub_volume_create(self, context, size, name, description, snapshot,
                       **param):
    vol = stub_volume('1')
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    try:
        vol['snapshot_id'] = snapshot['id']
    except (KeyError, TypeError):
        vol['snapshot_id'] = None
    vol['availability_zone'] = param.get('availability_zone', 'fakeaz')
    return vol


def stub_volume_update(self, context, *args, **param):
    pass


def stub_volume_get(self, context, volume_id):
    return stub_volume(volume_id)


def stub_volume_get_all(context, search_opts=None):
    return [stub_volume(100, project_id='fake'),
            stub_volume(101, project_id='superfake'),
            stub_volume(102, project_id='superduperfake')]


def stub_volume_check_attach(self, context, *args, **param):
    pass


def stub_snapshot(id, **kwargs):
    snapshot = {
        'id': id,
        'volume_id': 12,
        'status': 'available',
        'volume_size': 100,
        'created_at': timeutils.utcnow(),
        'display_name': 'Default name',
        'display_description': 'Default description',
        'project_id': 'fake'
        }

    snapshot.update(kwargs)
    return snapshot


def stub_snapshot_create(self, context, volume_id, name, description):
    return stub_snapshot(100, volume_id=volume_id, display_name=name,
                         display_description=description)


def stub_compute_volume_snapshot_create(self, context, volume_id, create_info):
    return {'snapshot': {'id': "421752a6-acf6-4b2d-bc7a-119f9148cd8c",
                         'volumeId': volume_id}}


def stub_snapshot_delete(self, context, snapshot_id):
    if snapshot_id == '-1':
        raise exc.SnapshotNotFound(snapshot_id=snapshot_id)


def stub_compute_volume_snapshot_delete(self, context, volume_id, snapshot_id,
        delete_info):
    pass


def stub_snapshot_get(self, context, snapshot_id):
    if snapshot_id == '-1':
        raise exc.SnapshotNotFound(snapshot_id=snapshot_id)
    return stub_snapshot(snapshot_id)


def stub_snapshot_get_all(self, context):
    return [stub_snapshot(100, project_id='fake'),
            stub_snapshot(101, project_id='superfake'),
            stub_snapshot(102, project_id='superduperfake')]


def stub_bdm_get_all_by_instance_uuids(context, instance_uuids,
                                       use_slave=False):
    i = 1
    result = []
    for instance_uuid in instance_uuids:
        for x in range(2):  # add two BDMs per instance
            result.append(fake_block_device.FakeDbBlockDeviceDict({
                'id': i,
                'source_type': 'volume',
                'destination_type': 'volume',
                'volume_id': 'volume_id%d' % (i),
                'instance_uuid': instance_uuid,
            }))
            i += 1
    return result


def fake_not_implemented(*args, **kwargs):
    raise NotImplementedError()


FLAVORS = {
    '1': objects.Flavor(
        id=1,
        name='flavor 1',
        memory_mb=256,
        vcpus=1,
        root_gb=10,
        ephemeral_gb=20,
        flavorid='1',
        swap=10,
        rxtx_factor=1.0,
        vcpu_weight=None,
        disabled=False,
        is_public=True,
        description=None,
        extra_specs={"key1": "value1", "key2": "value2"}
    ),
    '2': objects.Flavor(
        id=2,
        name='flavor 2',
        memory_mb=512,
        vcpus=1,
        root_gb=20,
        ephemeral_gb=10,
        flavorid='2',
        swap=5,
        rxtx_factor=None,
        vcpu_weight=None,
        disabled=True,
        is_public=True,
        description='flavor 2 description',
        extra_specs={}
    ),
}


def stub_out_flavor_get_by_flavor_id(test):
    @staticmethod
    def fake_get_by_flavor_id(context, flavor_id, read_deleted=None):
        return FLAVORS[flavor_id]

    test.stub_out('nova.objects.Flavor.get_by_flavor_id',
                  fake_get_by_flavor_id)


def stub_out_flavor_get_all(test):
    @staticmethod
    def fake_get_all(context, inactive=False, filters=None,
                     sort_key='flavorid', sort_dir='asc', limit=None,
                     marker=None):
        if marker in ['99999']:
            raise exc.MarkerNotFound(marker)

        def reject_min(db_attr, filter_attr):
            return (filter_attr in filters and
                    getattr(flavor, db_attr) < int(filters[filter_attr]))

        filters = filters or {}
        res = []
        for flavor in FLAVORS.values():
            if reject_min('memory_mb', 'min_memory_mb'):
                continue
            elif reject_min('root_gb', 'min_root_gb'):
                continue

            res.append(flavor)

        res = sorted(res, key=lambda item: getattr(item, sort_key))
        output = []
        marker_found = True if marker is None else False
        for flavor in res:
            if not marker_found and marker == flavor.flavorid:
                marker_found = True
            elif marker_found:
                if limit is None or len(output) < int(limit):
                    output.append(flavor)

        return objects.FlavorList(objects=output)

    test.stub_out('nova.objects.FlavorList.get_all', fake_get_all)

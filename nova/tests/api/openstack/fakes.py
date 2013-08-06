# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import uuid

import glanceclient.v1.images
import routes
import webob
import webob.dec
import webob.request

from nova.api import auth as api_auth
from nova.api import openstack as openstack_api
from nova.api.openstack import auth
from nova.api.openstack import compute
from nova.api.openstack.compute import limits
from nova.api.openstack.compute import versions
from nova.api.openstack import urlmap
from nova.api.openstack import wsgi as os_wsgi
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import vm_states
from nova import context
from nova.db.sqlalchemy import models
from nova import exception as exc
import nova.image.glance
from nova.network import api as network_api
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import quota
from nova.tests import fake_network
from nova.tests.glance import stubs as glance_stubs
from nova import utils
from nova import wsgi


QUOTAS = quota.QUOTAS


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_UUIDS = {}


class Context(object):
    pass


class FakeRouter(wsgi.Router):
    def __init__(self, ext_mgr=None):
        pass

    @webob.dec.wsgify
    def __call__(self, req):
        res = webob.Response()
        res.status = '200'
        res.headers['X-Test-Success'] = 'True'
        return res


@webob.dec.wsgify
def fake_wsgi(self, req):
    return self.application


def wsgi_app(inner_app_v2=None, fake_auth_context=None,
        use_no_auth=False, ext_mgr=None, init_only=None):
    if not inner_app_v2:
        inner_app_v2 = compute.APIRouter(ext_mgr, init_only)

    if use_no_auth:
        api_v2 = openstack_api.FaultWrapper(auth.NoAuthMiddleware(
              limits.RateLimitingMiddleware(inner_app_v2)))
    else:
        if fake_auth_context is not None:
            ctxt = fake_auth_context
        else:
            ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        api_v2 = openstack_api.FaultWrapper(api_auth.InjectContext(ctxt,
              limits.RateLimitingMiddleware(inner_app_v2)))

    mapper = urlmap.URLMap()
    mapper['/v2'] = api_v2
    mapper['/v1.1'] = api_v2
    mapper['/'] = openstack_api.FaultWrapper(versions.Versions())
    return mapper


def wsgi_app_v3(inner_app_v3=None, fake_auth_context=None,
        use_no_auth=False, ext_mgr=None, init_only=None):
    if not inner_app_v3:
        inner_app_v3 = compute.APIRouterV3(init_only)

    if use_no_auth:
        api_v3 = openstack_api.FaultWrapper(auth.NoAuthMiddlewareV3(
              limits.RateLimitingMiddleware(inner_app_v3)))
    else:
        if fake_auth_context is not None:
            ctxt = fake_auth_context
        else:
            ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        api_v3 = openstack_api.FaultWrapper(api_auth.InjectContext(ctxt,
              limits.RateLimitingMiddleware(inner_app_v3)))

    mapper = urlmap.URLMap()
    mapper['/v3'] = api_v3
    # TODO(cyeoh): bp nova-api-core-as-extensions
    # Still need to implement versions for v3 API
    #    mapper['/'] = openstack_api.FaultWrapper(versions.Versions())
    return mapper


def stub_out_key_pair_funcs(stubs, have_key_pair=True):
    def key_pair(context, user_id):
        return [dict(name='key', public_key='public_key')]

    def one_key_pair(context, user_id, name):
        if name == 'key':
            return dict(name='key', public_key='public_key')
        else:
            raise exc.KeypairNotFound(user_id=user_id, name=name)

    def no_key_pair(context, user_id):
        return []

    if have_key_pair:
        stubs.Set(nova.db, 'key_pair_get_all_by_user', key_pair)
        stubs.Set(nova.db, 'key_pair_get', one_key_pair)
    else:
        stubs.Set(nova.db, 'key_pair_get_all_by_user', no_key_pair)


def stub_out_rate_limiting(stubs):
    def fake_rate_init(self, app):
        super(limits.RateLimitingMiddleware, self).__init__(app)
        self.application = app

    stubs.Set(nova.api.openstack.compute.limits.RateLimitingMiddleware,
        '__init__', fake_rate_init)

    stubs.Set(nova.api.openstack.compute.limits.RateLimitingMiddleware,
        '__call__', fake_wsgi)


def stub_out_instance_quota(stubs, allowed, quota, resource='instances'):
    def fake_reserve(context, **deltas):
        requested = deltas.pop(resource, 0)
        if requested > allowed:
            quotas = dict(instances=1, cores=1, ram=1)
            quotas[resource] = quota
            usages = dict(instances=dict(in_use=0, reserved=0),
                          cores=dict(in_use=0, reserved=0),
                          ram=dict(in_use=0, reserved=0))
            usages[resource]['in_use'] = (quotas[resource] * 0.9 -
                                          allowed)
            usages[resource]['reserved'] = quotas[resource] * 0.1
            raise exc.OverQuota(overs=[resource], quotas=quotas,
                                usages=usages)
    stubs.Set(QUOTAS, 'reserve', fake_reserve)


def stub_out_networking(stubs):
    def get_my_ip():
        return '127.0.0.1'
    stubs.Set(nova.netconf, '_get_my_ip', get_my_ip)


def stub_out_compute_api_snapshot(stubs):

    def snapshot(self, context, instance, name, extra_properties=None):
        # emulate glance rejecting image names which are too long
        if len(name) > 256:
            raise exc.Invalid
        return dict(id='123', status='ACTIVE', name=name,
                    properties=extra_properties)

    stubs.Set(compute_api.API, 'snapshot', snapshot)


class stub_out_compute_api_backup(object):

    def __init__(self, stubs):
        self.stubs = stubs
        self.extra_props_last_call = None
        stubs.Set(compute_api.API, 'backup', self.backup)

    def backup(self, context, instance, name, backup_type, rotation,
               extra_properties=None):
        self.extra_props_last_call = extra_properties
        props = dict(backup_type=backup_type,
                     rotation=rotation)
        props.update(extra_properties or {})
        return dict(id='123', status='ACTIVE', name=name, properties=props)


def stub_out_nw_api_get_instance_nw_info(stubs, num_networks=1, func=None):
    fake_network.stub_out_nw_api_get_instance_nw_info(stubs,
                                                      spectacular=True)


def stub_out_nw_api_get_floating_ips_by_fixed_address(stubs, func=None):
    def get_floating_ips_by_fixed_address(self, context, fixed_ip):
        return ['1.2.3.4']

    if func is None:
        func = get_floating_ips_by_fixed_address
    stubs.Set(network_api.API, 'get_floating_ips_by_fixed_address', func)


def stub_out_nw_api(stubs, cls=None, private=None, publics=None):
    if not private:
        private = '192.168.0.3'
    if not publics:
        publics = ['1.2.3.4']

    class Fake:
        def get_instance_nw_info(*args, **kwargs):
            pass

        def get_floating_ips_by_fixed_address(*args, **kwargs):
            return publics

        def validate_networks(*args, **kwargs):
            pass

    if cls is None:
        cls = Fake
    stubs.Set(network_api, 'API', cls)
    fake_network.stub_out_nw_api_get_instance_nw_info(stubs, spectacular=True)


def _make_image_fixtures():
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"

    image_id = 123

    fixtures = []

    def add_fixture(**kwargs):
        fixtures.append(kwargs)

    # Public image
    add_fixture(id=image_id, name='public image', is_public=True,
                status='active', properties={'key1': 'value1'},
                min_ram="128", min_disk="10", size='25165824')
    image_id += 1

    # Snapshot for User 1
    uuid = 'aa640691-d1a7-4a67-9d3c-d35ee6b3cc74'
    server_ref = 'http://localhost/v2/servers/' + uuid
    snapshot_properties = {'instance_uuid': uuid, 'user_id': 'fake'}
    for status in ('queued', 'saving', 'active', 'killed',
                   'deleted', 'pending_delete'):
        deleted = False if status != 'deleted' else True
        add_fixture(id=image_id, name='%s snapshot' % status,
                    is_public=False, status=status,
                    properties=snapshot_properties, size='25165824',
                    deleted=deleted)
        image_id += 1

    # Image without a name
    add_fixture(id=image_id, is_public=True, status='active', properties={})
    # Image for permission tests
    image_id += 1
    add_fixture(id=image_id, is_public=True, status='active', properties={},
                owner='authorized_fake')

    return fixtures


def stub_out_glanceclient_create(stubs, sent_to_glance):
    """
    We return the metadata sent to glance by modifying the sent_to_glance dict
    in place.
    """
    orig_add_image = glanceclient.v1.images.ImageManager.create

    def fake_create(context, metadata, data=None):
        sent_to_glance['metadata'] = metadata
        sent_to_glance['data'] = data
        return orig_add_image(metadata, data)

    stubs.Set(glanceclient.v1.images.ImageManager, 'create', fake_create)


def stub_out_glance(stubs):
    def fake_get_remote_image_service():
        client = glance_stubs.StubGlanceClient(_make_image_fixtures())
        client_wrapper = nova.image.glance.GlanceClientWrapper()
        client_wrapper.host = 'fake_host'
        client_wrapper.port = 9292
        client_wrapper.client = client
        return nova.image.glance.GlanceImageService(client=client_wrapper)
    stubs.Set(nova.image.glance,
              'get_default_image_service',
              fake_get_remote_image_service)


class FakeToken(object):
    id_count = 0

    def __getitem__(self, key):
        return getattr(self, key)

    def __init__(self, **kwargs):
        FakeToken.id_count += 1
        self.id = FakeToken.id_count
        for k, v in kwargs.iteritems():
            setattr(self, k, v)


class FakeRequestContext(context.RequestContext):
    def __init__(self, *args, **kwargs):
        kwargs['auth_token'] = kwargs.get('auth_token', 'fake_auth_token')
        return super(FakeRequestContext, self).__init__(*args, **kwargs)


class HTTPRequest(os_wsgi.Request):

    @classmethod
    def blank(cls, *args, **kwargs):
        kwargs['base_url'] = 'http://localhost/v2'
        use_admin_context = kwargs.pop('use_admin_context', False)
        out = os_wsgi.Request.blank(*args, **kwargs)
        out.environ['nova.context'] = FakeRequestContext('fake_user', 'fake',
                is_admin=use_admin_context)
        return out


class HTTPRequestV3(os_wsgi.Request):

    @classmethod
    def blank(cls, *args, **kwargs):
        kwargs['base_url'] = 'http://localhost/v3'
        use_admin_context = kwargs.pop('use_admin_context', False)
        out = os_wsgi.Request.blank(*args, **kwargs)
        out.environ['nova.context'] = FakeRequestContext('fake_user', 'fake',
                is_admin=use_admin_context)
        return out


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


class FakeRateLimiter(object):
    def __init__(self, application):
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req):
        return self.application


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

    if not isinstance(nw_cache, basestring):
        nw_cache = jsonutils.dumps(nw_cache)

    return {"info_cache": {"network_info": nw_cache}}


def get_fake_uuid(token=0):
    if token not in FAKE_UUIDS:
        FAKE_UUIDS[token] = str(uuid.uuid4())
    return FAKE_UUIDS[token]


def fake_instance_get(**kwargs):
    def _return_server(context, uuid, columns_to_join=None):
        return stub_instance(1, **kwargs)
    return _return_server


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
        for i in xrange(num_servers):
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


def stub_instance(id, user_id=None, project_id=None, host=None,
                  node=None, vm_state=None, task_state=None,
                  reservation_id="", uuid=FAKE_UUID, image_ref="10",
                  flavor_id="1", name=None, key_name='',
                  access_ipv4=None, access_ipv6=None, progress=0,
                  auto_disk_config=False, display_name=None,
                  include_fake_metadata=True, config_drive=None,
                  power_state=None, nw_cache=None, metadata=None,
                  security_groups=None, root_device_name=None,
                  limit=None, marker=None,
                  launched_at=timeutils.utcnow(),
                  terminated_at=timeutils.utcnow(),
                  availability_zone='', locked_by=None, cleaned=False):

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

    instance = {
        "id": int(id),
        "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
        "deleted_at": datetime.datetime(2010, 12, 12, 10, 0, 0),
        "deleted": None,
        "user_id": user_id,
        "project_id": project_id,
        "image_ref": image_ref,
        "kernel_id": "",
        "ramdisk_id": "",
        "launch_index": 0,
        "key_name": key_name,
        "key_data": key_data,
        "config_drive": config_drive,
        "vm_state": vm_state or vm_states.BUILDING,
        "task_state": task_state,
        "power_state": power_state,
        "memory_mb": 0,
        "vcpus": 0,
        "root_gb": 0,
        "ephemeral_gb": 0,
        "hostname": display_name or server_name,
        "host": host,
        "node": node,
        "instance_type_id": 1,
        "instance_type": dict(inst_type),
        "user_data": "",
        "reservation_id": reservation_id,
        "mac_address": "",
        "scheduled_at": timeutils.utcnow(),
        "launched_at": launched_at,
        "terminated_at": terminated_at,
        "availability_zone": availability_zone,
        "display_name": display_name or server_name,
        "display_description": "",
        "locked": locked_by != None,
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
        "vm_mode": "",
        "default_swap_device": "",
        "default_ephemeral_device": "",
        "launched_on": "",
        "cell_name": "",
        "architecture": "",
        "os_type": "",
        "cleaned": cleaned}

    instance.update(info_cache)
    instance['info_cache']['instance_uuid'] = instance['uuid']

    return instance


def stub_volume(id, **kwargs):
    volume = {
        'id': id,
        'user_id': 'fakeuser',
        'project_id': 'fakeproject',
        'host': 'fakehost',
        'size': 1,
        'availability_zone': 'fakeaz',
        'instance_uuid': 'fakeuuid',
        'mountpoint': '/',
        'status': 'fakestatus',
        'attach_status': 'attached',
        'name': 'vol name',
        'display_name': 'displayname',
        'display_description': 'displaydesc',
        'created_at': datetime.datetime(1999, 1, 1, 1, 1, 1),
        'snapshot_id': None,
        'volume_type_id': 'fakevoltype',
        'volume_metadata': [],
        'volume_type': {'name': 'vol_type_name'}}

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


def stub_volume_create_from_image(self, context, size, name, description,
                                  snapshot, volume_type, metadata,
                                  availability_zone):
    vol = stub_volume('1')
    vol['status'] = 'creating'
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    vol['availability_zone'] = 'nova'
    return vol


def stub_volume_update(self, context, *args, **param):
    pass


def stub_volume_delete(self, context, *args, **param):
    pass


def stub_volume_get(self, context, volume_id):
    return stub_volume(volume_id)


def stub_volume_notfound(self, context, volume_id):
    raise exc.VolumeNotFound(volume_id=volume_id)


def stub_volume_get_all(context, search_opts=None):
    return [stub_volume(100, project_id='fake'),
            stub_volume(101, project_id='superfake'),
            stub_volume(102, project_id='superduperfake')]


def stub_volume_get_all_by_project(self, context, search_opts=None):
    return [stub_volume_get(self, context, '1')]


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


def stub_snapshot_delete(self, context, snapshot_id):
    if snapshot_id == '-1':
        raise exc.NotFound


def stub_snapshot_get(self, context, snapshot_id):
    if snapshot_id == '-1':
        raise exc.NotFound
    return stub_snapshot(snapshot_id)


def stub_snapshot_get_all(self, context):
    return [stub_snapshot(100, project_id='fake'),
            stub_snapshot(101, project_id='superfake'),
            stub_snapshot(102, project_id='superduperfake')]


def stub_bdm_get_all_by_instance(context, instance_uuid):
    return [{'source_type': 'volume', 'volume_id': 'volume_id1'},
            {'source_type': 'volume', 'volume_id': 'volume_id2'}]

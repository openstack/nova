#    Copyright (c) 2010 Citrix Systems, Inc.
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
#


# Parts of this file are based upon xmlrpclib.py, the XML-RPC client
# interface included in the Python distribution.
#
# Copyright (c) 1999-2002 by Secret Labs AB
# Copyright (c) 1999-2002 by Fredrik Lundh
#
# By obtaining, using, and/or copying this software and/or its
# associated documentation, you agree that you have read, understood,
# and will comply with the following terms and conditions:
#
# Permission to use, copy, modify, and distribute this software and
# its associated documentation for any purpose and without fee is
# hereby granted, provided that the above copyright notice appears in
# all copies, and that both that copyright notice and this permission
# notice appear in supporting documentation, and that the name of
# Secret Labs AB or the author not be used in advertising or publicity
# pertaining to distribution of the software without specific, written
# prior permission.
#
# SECRET LABS AB AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD
# TO THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANT-
# ABILITY AND FITNESS.  IN NO EVENT SHALL SECRET LABS AB OR THE AUTHOR
# BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY
# DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
# WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
# ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
# OF THIS SOFTWARE.
# --------------------------------------------------------------------


"""
A fake XenAPI SDK.
"""

import base64
import pickle
import random
from xml.sax import saxutils
import zlib

from os_xenapi.client import session as xenapi_session
from os_xenapi.client import XenAPI
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import units
from oslo_utils import uuidutils


from nova import exception
from nova.i18n import _


_CLASSES = ['host', 'network', 'session', 'pool', 'SR', 'VBD',
            'PBD', 'VDI', 'VIF', 'PIF', 'VM', 'VLAN', 'task',
            'GPU_group', 'PGPU', 'VGPU_type']
_after_create_functions = {}
_destroy_functions = {}

_db_content = {}

LOG = logging.getLogger(__name__)


def add_to_dict(functions):
    """A decorator that adds a function to dictionary."""

    def decorator(func):
        functions[func.__name__] = func
        return func
    return decorator


def reset():
    for c in _CLASSES:
        _db_content[c] = {}
    create_host('fake')
    create_vm('fake dom 0',
              'Running',
              is_a_template=False,
              is_control_domain=True,
              domid='0')


def reset_table(table):
    if table not in _CLASSES:
        return
    _db_content[table] = {}


def _create_pool(name_label):
    return _create_object('pool',
                          {'name_label': name_label})


def create_host(name_label, hostname='fake_name', address='fake_addr'):
    host_ref = _create_object('host',
                               {'name_label': name_label,
                                'hostname': hostname,
                                'address': address})
    host_default_sr_ref = _create_local_srs(host_ref)
    _create_local_pif(host_ref)

    # Create a pool if we don't have one already
    if len(_db_content['pool']) == 0:
        pool_ref = _create_pool('')
        _db_content['pool'][pool_ref]['master'] = host_ref
        _db_content['pool'][pool_ref]['default-SR'] = host_default_sr_ref
        _db_content['pool'][pool_ref]['suspend-image-SR'] = host_default_sr_ref


def create_network(name_label, bridge):
    return _create_object('network',
                          {'name_label': name_label,
                           'bridge': bridge})


def create_vm(name_label, status, **kwargs):
    if status == 'Running':
        domid = "%d" % random.randrange(1, 1 << 16)
        resident_on = list(_db_content['host'])[0]
    else:
        domid = "-1"
        resident_on = ''

    vm_rec = {'name_label': name_label,
              'domid': domid,
              'power_state': status,
              'blocked_operations': {},
              'resident_on': resident_on}
    vm_rec.update(kwargs.copy())
    vm_ref = _create_object('VM', vm_rec)
    after_VM_create(vm_ref, vm_rec)
    return vm_ref


@add_to_dict(_destroy_functions)
def destroy_vm(vm_ref):
    vm_rec = _db_content['VM'][vm_ref]

    vbd_refs = vm_rec['VBDs']
    # NOTE(johannes): Shallow copy since destroy_vbd will remove itself
    # from the list
    for vbd_ref in vbd_refs[:]:
        destroy_vbd(vbd_ref)

    del _db_content['VM'][vm_ref]


@add_to_dict(_destroy_functions)
def destroy_vbd(vbd_ref):
    vbd_rec = _db_content['VBD'][vbd_ref]

    vm_ref = vbd_rec['VM']
    vm_rec = _db_content['VM'][vm_ref]
    vm_rec['VBDs'].remove(vbd_ref)

    vdi_ref = vbd_rec['VDI']
    vdi_rec = _db_content['VDI'][vdi_ref]
    vdi_rec['VBDs'].remove(vbd_ref)

    del _db_content['VBD'][vbd_ref]


@add_to_dict(_destroy_functions)
def destroy_vdi(vdi_ref):
    vdi_rec = _db_content['VDI'][vdi_ref]

    vbd_refs = vdi_rec['VBDs']
    # NOTE(johannes): Shallow copy since destroy_vbd will remove itself
    # from the list
    for vbd_ref in vbd_refs[:]:
        destroy_vbd(vbd_ref)

    del _db_content['VDI'][vdi_ref]


def create_vdi(name_label, sr_ref, **kwargs):
    vdi_rec = {
        'SR': sr_ref,
        'read_only': False,
        'type': '',
        'name_label': name_label,
        'name_description': '',
        'sharable': False,
        'other_config': {},
        'location': '',
        'xenstore_data': {},
        'sm_config': {'vhd-parent': None},
        'physical_utilisation': '123',
        'managed': True,
    }
    vdi_rec.update(kwargs)
    vdi_ref = _create_object('VDI', vdi_rec)
    after_VDI_create(vdi_ref, vdi_rec)
    return vdi_ref


@add_to_dict(_after_create_functions)
def after_VDI_create(vdi_ref, vdi_rec):
    vdi_rec.setdefault('VBDs', [])


def create_vbd(vm_ref, vdi_ref, userdevice=0, other_config=None):
    if other_config is None:
        other_config = {}

    vbd_rec = {'VM': vm_ref,
               'VDI': vdi_ref,
               'userdevice': str(userdevice),
               'currently_attached': False,
               'other_config': other_config}
    vbd_ref = _create_object('VBD', vbd_rec)
    after_VBD_create(vbd_ref, vbd_rec)
    return vbd_ref


@add_to_dict(_after_create_functions)
def after_VBD_create(vbd_ref, vbd_rec):
    """Create read-only fields and backref from VM and VDI to VBD when VBD
    is created.
    """
    vbd_rec['currently_attached'] = False

    # TODO(snikitin): Find a better way for generating of device name.
    # Usually 'userdevice' has numeric values like '1', '2', '3', etc.
    # Ideally they should be transformed to something like 'xvda', 'xvdb',
    # 'xvdx', etc. But 'userdevice' also may be 'autodetect', 'fake' or even
    # unset. We should handle it in future.
    vbd_rec['device'] = vbd_rec.get('userdevice', '')
    vbd_rec.setdefault('other_config', {})

    vm_ref = vbd_rec['VM']
    vm_rec = _db_content['VM'][vm_ref]
    vm_rec['VBDs'].append(vbd_ref)

    vm_name_label = _db_content['VM'][vm_ref]['name_label']
    vbd_rec['vm_name_label'] = vm_name_label

    vdi_ref = vbd_rec['VDI']
    if vdi_ref and vdi_ref != "OpaqueRef:NULL":
        vdi_rec = _db_content['VDI'][vdi_ref]
        vdi_rec['VBDs'].append(vbd_ref)


@add_to_dict(_after_create_functions)
def after_VIF_create(vif_ref, vif_rec):
    """Create backref from VM to VIF when VIF is created.
    """
    vm_ref = vif_rec['VM']
    vm_rec = _db_content['VM'][vm_ref]
    vm_rec['VIFs'].append(vif_ref)


@add_to_dict(_after_create_functions)
def after_VM_create(vm_ref, vm_rec):
    """Create read-only fields in the VM record."""
    vm_rec.setdefault('domid', "-1")
    vm_rec.setdefault('is_control_domain', False)
    vm_rec.setdefault('is_a_template', False)
    vm_rec.setdefault('memory_static_max', str(8 * units.Gi))
    vm_rec.setdefault('memory_dynamic_max', str(8 * units.Gi))
    vm_rec.setdefault('VCPUs_max', str(4))
    vm_rec.setdefault('VBDs', [])
    vm_rec.setdefault('VIFs', [])
    vm_rec.setdefault('resident_on', '')


def create_pbd(host_ref, sr_ref, attached):
    config = {'path': '/var/run/sr-mount/%s' % sr_ref}
    return _create_object('PBD',
                          {'device_config': config,
                           'host': host_ref,
                           'SR': sr_ref,
                           'currently_attached': attached})


def create_task(name_label):
    return _create_object('task',
                          {'name_label': name_label,
                           'status': 'pending'})


def _create_local_srs(host_ref):
    """Create an SR that looks like the one created on the local disk by
    default by the XenServer installer.  Also, fake the installation of
    an ISO SR.
    """
    create_sr(name_label='Local storage ISO',
              type='iso',
              other_config={'i18n-original-value-name_label':
                            'Local storage ISO',
                            'i18n-key': 'local-storage-iso'},
              physical_size=80000,
              physical_utilisation=40000,
              virtual_allocation=80000,
              host_ref=host_ref)
    return create_sr(name_label='Local storage',
                     type='ext',
                     other_config={'i18n-original-value-name_label':
                                   'Local storage',
                                   'i18n-key': 'local-storage'},
                     physical_size=40000,
                     physical_utilisation=20000,
                     virtual_allocation=10000,
                     host_ref=host_ref)


def create_sr(**kwargs):
    sr_ref = _create_object(
             'SR',
             {'name_label': kwargs.get('name_label'),
              'type': kwargs.get('type'),
              'content_type': kwargs.get('type', 'user'),
              'shared': kwargs.get('shared', False),
              'physical_size': kwargs.get('physical_size', str(1 << 30)),
              'physical_utilisation': str(
                                        kwargs.get('physical_utilisation', 0)),
              'virtual_allocation': str(kwargs.get('virtual_allocation', 0)),
              'other_config': kwargs.get('other_config', {}),
              'VDIs': kwargs.get('VDIs', [])})
    pbd_ref = create_pbd(kwargs.get('host_ref'), sr_ref, True)
    _db_content['SR'][sr_ref]['PBDs'] = [pbd_ref]
    return sr_ref


def _create_local_pif(host_ref):
    pif_ref = _create_object('PIF',
                             {'name-label': 'Fake PIF',
                              'MAC': '00:11:22:33:44:55',
                              'physical': True,
                              'VLAN': -1,
                              'device': 'fake0',
                              'host_uuid': host_ref,
                              'network': '',
                              'IP': '10.1.1.1',
                              'IPv6': '',
                              'uuid': '',
                              'management': 'true'})
    _db_content['PIF'][pif_ref]['uuid'] = pif_ref
    return pif_ref


def _create_object(table, obj):
    ref = uuidutils.generate_uuid()
    obj['uuid'] = uuidutils.generate_uuid()
    obj['ref'] = ref
    _db_content[table][ref] = obj
    return ref


def _create_sr(table, obj):
    sr_type = obj[6]
    # Forces fake to support iscsi only
    if sr_type != 'iscsi' and sr_type != 'nfs':
        raise XenAPI.Failure(['SR_UNKNOWN_DRIVER', sr_type])
    host_ref = list(_db_content['host'])[0]
    sr_ref = _create_object(table, obj[2])
    if sr_type == 'iscsi':
        vdi_ref = create_vdi('', sr_ref)
        pbd_ref = create_pbd(host_ref, sr_ref, True)
        _db_content['SR'][sr_ref]['VDIs'] = [vdi_ref]
        _db_content['SR'][sr_ref]['PBDs'] = [pbd_ref]
        _db_content['VDI'][vdi_ref]['SR'] = sr_ref
        _db_content['PBD'][pbd_ref]['SR'] = sr_ref
    return sr_ref


def _create_vlan(pif_ref, vlan_num, network_ref):
    pif_rec = get_record('PIF', pif_ref)
    vlan_pif_ref = _create_object('PIF',
                                  {'name-label': 'Fake VLAN PIF',
                                   'MAC': '00:11:22:33:44:55',
                                   'physical': True,
                                   'VLAN': vlan_num,
                                   'device': pif_rec['device'],
                                   'host_uuid': pif_rec['host_uuid']})
    return _create_object('VLAN',
                          {'tagged-pif': pif_ref,
                           'untagged-pif': vlan_pif_ref,
                           'tag': vlan_num})


def get_all(table):
    return list(_db_content[table].keys())


def get_all_records(table):
    return _db_content[table]


def _query_matches(record, query):
    # Simple support for the XenServer query language:
    # 'field "host"="<uuid>" and field "SR"="<sr uuid>"'
    # Tested through existing tests (e.g. calls to find_network_with_bridge)

    and_clauses = query.split(" and ")
    if len(and_clauses) > 1:
        matches = True
        for clause in and_clauses:
            matches = matches and _query_matches(record, clause)
        return matches

    or_clauses = query.split(" or ")
    if len(or_clauses) > 1:
        matches = False
        for clause in or_clauses:
            matches = matches or _query_matches(record, clause)
        return matches

    if query.startswith('not '):
        return not _query_matches(record, query[4:])

    # Now it must be a single field - bad queries never match
    if not query.startswith('field'):
        return False
    (field, value) = query[6:].split('=', 1)

    # Some fields (e.g. name_label, memory_overhead) have double
    # underscores in the DB, but only single underscores when querying

    field = field.replace("__", "_").strip(" \"'")
    value = value.strip(" \"'")

    # Strings should be directly compared
    if isinstance(record[field], str):
        return record[field] == value

    # But for all other value-checks, convert to a string first
    # (Notably used for booleans - which can be lower or camel
    # case and are interpreted/sanitised by XAPI)
    return str(record[field]).lower() == value.lower()


def get_all_records_where(table_name, query):
    matching_records = {}
    table = _db_content[table_name]
    for record in table:
        if _query_matches(table[record], query):
            matching_records[record] = table[record]
    return matching_records


def get_record(table, ref):
    if ref in _db_content[table]:
        return _db_content[table].get(ref)
    else:
        raise XenAPI.Failure(['HANDLE_INVALID', table, ref])


def check_for_session_leaks():
    if len(_db_content['session']) > 0:
        raise exception.NovaException('Sessions have leaked: %s' %
                              _db_content['session'])


def as_value(s):
    """Helper function for simulating XenAPI plugin responses.  It
    escapes and wraps the given argument.
    """
    return '<value>%s</value>' % saxutils.escape(s)


def as_json(*args, **kwargs):
    """Helper function for simulating XenAPI plugin responses for those
    that are returning JSON.  If this function is given plain arguments,
    then these are rendered as a JSON list.  If it's given keyword
    arguments then these are rendered as a JSON dict.
    """
    arg = args or kwargs
    return jsonutils.dumps(arg)


class Failure(Exception):
    def __init__(self, details):
        self.details = details

    def __str__(self):
        try:
            return str(self.details)
        except Exception:
            return "XenAPI Fake Failure: %s" % str(self.details)

    def _details_map(self):
        return {str(i): self.details[i] for i in range(len(self.details))}


class SessionBase(object):
    """Base class for Fake Sessions."""

    def __init__(self, uri, user=None, passwd=None):
        self._session = None
        xenapi_session.apply_session_helpers(self)
        if user is not None:
            self.xenapi.login_with_password(user, passwd)

    def pool_get_default_SR(self, _1, pool_ref):
        return list(_db_content['pool'].values())[0]['default-SR']

    def VBD_insert(self, _1, vbd_ref, vdi_ref):
        vbd_rec = get_record('VBD', vbd_ref)
        get_record('VDI', vdi_ref)
        vbd_rec['empty'] = False
        vbd_rec['VDI'] = vdi_ref

    def VBD_plug(self, _1, ref):
        rec = get_record('VBD', ref)
        if rec['currently_attached']:
            raise XenAPI.Failure(['DEVICE_ALREADY_ATTACHED', ref])
        rec['currently_attached'] = True
        rec['device'] = 'fakedev'

    def VBD_unplug(self, _1, ref):
        rec = get_record('VBD', ref)
        if not rec['currently_attached']:
            raise XenAPI.Failure(['DEVICE_ALREADY_DETACHED', ref])
        rec['currently_attached'] = False
        rec['device'] = ''

    def VBD_add_to_other_config(self, _1, vbd_ref, key, value):
        db_ref = _db_content['VBD'][vbd_ref]
        if 'other_config' not in db_ref:
            db_ref['other_config'] = {}
        if key in db_ref['other_config']:
            raise XenAPI.Failure(
                ['MAP_DUPLICATE_KEY', 'VBD', 'other_config', vbd_ref, key])
        db_ref['other_config'][key] = value

    def VBD_get_other_config(self, _1, vbd_ref):
        db_ref = _db_content['VBD'][vbd_ref]
        if 'other_config' not in db_ref:
            return {}
        return db_ref['other_config']

    def PBD_create(self, _1, pbd_rec):
        pbd_ref = _create_object('PBD', pbd_rec)
        _db_content['PBD'][pbd_ref]['currently_attached'] = False
        return pbd_ref

    def PBD_plug(self, _1, pbd_ref):
        rec = get_record('PBD', pbd_ref)
        if rec['currently_attached']:
            raise XenAPI.Failure(['DEVICE_ALREADY_ATTACHED', rec])
        rec['currently_attached'] = True
        sr_ref = rec['SR']
        _db_content['SR'][sr_ref]['PBDs'] = [pbd_ref]

    def PBD_unplug(self, _1, pbd_ref):
        rec = get_record('PBD', pbd_ref)
        if not rec['currently_attached']:
            raise XenAPI.Failure(['DEVICE_ALREADY_DETACHED', rec])
        rec['currently_attached'] = False
        sr_ref = rec['SR']
        _db_content['SR'][sr_ref]['PBDs'].remove(pbd_ref)

    def SR_introduce(self, _1, sr_uuid, label, desc, type, content_type,
                     shared, sm_config):
        for ref, rec in _db_content['SR'].items():
            if rec.get('uuid') == sr_uuid:
                # make forgotten = 0 and return ref
                _db_content['SR'][ref]['forgotten'] = 0
                return ref
        # SR not found in db, so we create one
        params = {'sr_uuid': sr_uuid,
                  'label': label,
                  'desc': desc,
                  'type': type,
                  'content_type': content_type,
                  'shared': shared,
                  'sm_config': sm_config}
        sr_ref = _create_object('SR', params)
        _db_content['SR'][sr_ref]['uuid'] = sr_uuid
        _db_content['SR'][sr_ref]['forgotten'] = 0
        vdi_per_lun = False
        if type == 'iscsi':
            # Just to be clear
            vdi_per_lun = True
        if vdi_per_lun:
            # we need to create a vdi because this introduce
            # is likely meant for a single vdi
            vdi_ref = create_vdi('', sr_ref)
            _db_content['SR'][sr_ref]['VDIs'] = [vdi_ref]
            _db_content['VDI'][vdi_ref]['SR'] = sr_ref
        return sr_ref

    def SR_forget(self, _1, sr_ref):
        _db_content['SR'][sr_ref]['forgotten'] = 1

    def SR_scan(self, _1, sr_ref):
        return

    def VM_get_xenstore_data(self, _1, vm_ref):
        return _db_content['VM'][vm_ref].get('xenstore_data', {})

    def VM_remove_from_xenstore_data(self, _1, vm_ref, key):
        db_ref = _db_content['VM'][vm_ref]
        if 'xenstore_data' not in db_ref:
            return
        if key in db_ref['xenstore_data']:
            del db_ref['xenstore_data'][key]

    def VM_add_to_xenstore_data(self, _1, vm_ref, key, value):
        db_ref = _db_content['VM'][vm_ref]
        if 'xenstore_data' not in db_ref:
            db_ref['xenstore_data'] = {}
        db_ref['xenstore_data'][key] = value

    def VM_pool_migrate(self, _1, vm_ref, host_ref, options):
        pass

    def VDI_remove_from_other_config(self, _1, vdi_ref, key):
        db_ref = _db_content['VDI'][vdi_ref]
        if 'other_config' not in db_ref:
            return
        if key in db_ref['other_config']:
            del db_ref['other_config'][key]

    def VDI_add_to_other_config(self, _1, vdi_ref, key, value):
        db_ref = _db_content['VDI'][vdi_ref]
        if 'other_config' not in db_ref:
            db_ref['other_config'] = {}
        if key in db_ref['other_config']:
            raise XenAPI.Failure(
                ['MAP_DUPLICATE_KEY', 'VDI', 'other_config', vdi_ref, key])
        db_ref['other_config'][key] = value

    def VDI_copy(self, _1, vdi_to_copy_ref, sr_ref):
        db_ref = _db_content['VDI'][vdi_to_copy_ref]
        name_label = db_ref['name_label']
        read_only = db_ref['read_only']
        sharable = db_ref['sharable']
        other_config = db_ref['other_config'].copy()
        return create_vdi(name_label, sr_ref, sharable=sharable,
                          read_only=read_only, other_config=other_config)

    def VDI_clone(self, _1, vdi_to_clone_ref):
        db_ref = _db_content['VDI'][vdi_to_clone_ref]
        sr_ref = db_ref['SR']
        return self.VDI_copy(_1, vdi_to_clone_ref, sr_ref)

    def host_compute_free_memory(self, _1, ref):
        # Always return 12GB available
        return 12 * units.Gi

    def _plugin_agent_version(self, method, args):
        return as_json(returncode='0', message='1.0\\r\\n')

    def _plugin_agent_key_init(self, method, args):
        return as_json(returncode='D0', message='1')

    def _plugin_agent_password(self, method, args):
        return as_json(returncode='0', message='success')

    def _plugin_agent_inject_file(self, method, args):
        return as_json(returncode='0', message='success')

    def _plugin_agent_resetnetwork(self, method, args):
        return as_json(returncode='0', message='success')

    def _plugin_agent_agentupdate(self, method, args):
        url = args["url"]
        md5 = args["md5sum"]
        message = "success with %(url)s and hash:%(md5)s" % dict(url=url,
                                                                 md5=md5)
        return as_json(returncode='0', message=message)

    def _plugin_noop(self, method, args):
        return ''

    def _plugin_pickle_noop(self, method, args):
        return pickle.dumps(None)

    def _plugin_migration_transfer_vhd(self, method, args):
        kwargs = pickle.loads(args['params'])['kwargs']
        vdi_ref = self.xenapi_request('VDI.get_by_uuid',
                (kwargs['vdi_uuid'], ))
        assert vdi_ref
        return pickle.dumps(None)

    _plugin_glance_upload_vhd2 = _plugin_pickle_noop
    _plugin_kernel_copy_vdi = _plugin_noop
    _plugin_kernel_create_kernel_ramdisk = _plugin_noop
    _plugin_kernel_remove_kernel_ramdisk = _plugin_noop
    _plugin_migration_move_vhds_into_sr = _plugin_noop

    def _plugin_xenhost_host_data(self, method, args):
        return jsonutils.dumps({
            'host_memory': {'total': 10,
                            'overhead': 20,
                            'free': 30,
                            'free-computed': 40},
            'host_uuid': 'fb97583b-baa1-452d-850e-819d95285def',
            'host_name-label': 'fake-xenhost',
            'host_name-description': 'Default install of XenServer',
            'host_hostname': 'fake-xenhost',
            'host_ip_address': '10.219.10.24',
            'enabled': 'true',
            'host_capabilities': ['xen-3.0-x86_64',
                                  'xen-3.0-x86_32p',
                                  'hvm-3.0-x86_32',
                                  'hvm-3.0-x86_32p',
                                  'hvm-3.0-x86_64'],
            'host_other-config': {
                'agent_start_time': '1412774967.',
                'iscsi_iqn': 'iqn.2014-10.org.example:39fa9ee3',
                'boot_time': '1412774885.',
            },
            'host_cpu_info': {
                'physical_features': '0098e3fd-bfebfbff-00000001-28100800',
                'modelname': 'Intel(R) Xeon(R) CPU           X3430  @ 2.40GHz',
                'vendor': 'GenuineIntel',
                'features': '0098e3fd-bfebfbff-00000001-28100800',
                'family': 6,
                'maskable': 'full',
                'cpu_count': 4,
                'socket_count': '1',
                'flags': 'fpu de tsc msr pae mce cx8 apic sep mtrr mca '
                         'cmov pat clflush acpi mmx fxsr sse sse2 ss ht '
                         'nx constant_tsc nonstop_tsc aperfmperf pni vmx '
                         'est ssse3 sse4_1 sse4_2 popcnt hypervisor ida '
                         'tpr_shadow vnmi flexpriority ept vpid',
                'stepping': 5,
                'model': 30,
                'features_after_reboot': '0098e3fd-bfebfbff-00000001-28100800',
                'speed': '2394.086'
            },
        })

    def _plugin_poweraction(self, method, args):
        return jsonutils.dumps({"power_action": method[5:]})

    _plugin_xenhost_host_reboot = _plugin_poweraction
    _plugin_xenhost_host_startup = _plugin_poweraction
    _plugin_xenhost_host_shutdown = _plugin_poweraction

    def _plugin_xenhost_set_host_enabled(self, method, args):
        enabled = 'enabled' if args.get('enabled') == 'true' else 'disabled'
        return jsonutils.dumps({"status": enabled})

    def _plugin_xenhost_host_uptime(self, method, args):
        return jsonutils.dumps({"uptime": "fake uptime"})

    def _plugin_xenhost_get_pci_device_details(self, method, args):
        """Simulate the ouput of three pci devices.

        Both of those devices are available for pci passtrough but
        only one will match with the pci whitelist used in the
        method test_pci_passthrough_devices_*().
        Return a single list.

        """
        # Driver is not pciback
        dev_bad1 = ["Slot:\t0000:86:10.0", "Class:\t0604", "Vendor:\t10b5",
                    "Device:\t8747", "Rev:\tba", "Driver:\tpcieport", "\n"]
        # Driver is pciback but vendor and device are bad
        dev_bad2 = ["Slot:\t0000:88:00.0", "Class:\t0300", "Vendor:\t0bad",
                    "Device:\tcafe", "SVendor:\t10de", "SDevice:\t100d",
                    "Rev:\ta1", "Driver:\tpciback", "\n"]
        # Driver is pciback and vendor, device are used for matching
        dev_good = ["Slot:\t0000:87:00.0", "Class:\t0300", "Vendor:\t10de",
                    "Device:\t11bf", "SVendor:\t10de", "SDevice:\t100d",
                    "Rev:\ta1", "Driver:\tpciback", "\n"]

        lspci_output = "\n".join(dev_bad1 + dev_bad2 + dev_good)
        return pickle.dumps(lspci_output)

    def _plugin_xenhost_get_pci_type(self, method, args):
        return pickle.dumps("type-PCI")

    def _plugin_console_get_console_log(self, method, args):
        dom_id = args["dom_id"]
        if dom_id == 0:
            raise XenAPI.Failure('Guest does not have a console')
        return base64.b64encode(
            zlib.compress(("dom_id: %s" % dom_id).encode('utf-8')))

    def _plugin_dom0_plugin_version_get_version(self, method, args):
        return pickle.dumps(
            xenapi_session.XenAPISession.PLUGIN_REQUIRED_VERSION)

    def _plugin_xenhost_query_gc(self, method, args):
        return pickle.dumps("False")

    def _plugin_partition_utils_make_partition(self, method, args):
        return pickle.dumps(None)

    def host_call_plugin(self, _1, _2, plugin, method, args):
        plugin = plugin.rstrip('.py')

        func = getattr(self, '_plugin_%s_%s' % (plugin, method), None)
        if not func:
            raise Exception('No simulation in host_call_plugin for %s,%s' %
                            (plugin, method))

        return func(method, args)

    def VDI_get_virtual_size(self, *args):
        return 1 * units.Gi

    def VDI_resize_online(self, *args):
        return 'derp'

    VDI_resize = VDI_resize_online

    def _VM_reboot(self, session, vm_ref):
        db_ref = _db_content['VM'][vm_ref]
        if db_ref['power_state'] != 'Running':
            raise XenAPI.Failure(['VM_BAD_POWER_STATE', 'fake-opaque-ref',
                 db_ref['power_state'].lower(), 'halted'])
        db_ref['power_state'] = 'Running'
        db_ref['domid'] = '%d' % (random.randrange(1, 1 << 16))

    def VM_clean_reboot(self, session, vm_ref):
        return self._VM_reboot(session, vm_ref)

    def VM_hard_reboot(self, session, vm_ref):
        return self._VM_reboot(session, vm_ref)

    def VM_hard_shutdown(self, session, vm_ref):
        db_ref = _db_content['VM'][vm_ref]
        db_ref['power_state'] = 'Halted'
        db_ref['domid'] = "-1"
    VM_clean_shutdown = VM_hard_shutdown

    def VM_suspend(self, session, vm_ref):
        db_ref = _db_content['VM'][vm_ref]
        db_ref['power_state'] = 'Suspended'

    def VM_pause(self, session, vm_ref):
        db_ref = _db_content['VM'][vm_ref]
        db_ref['power_state'] = 'Paused'

    def VM_query_data_source(self, session, vm_ref, field):
        vm = {'cpu0': 0.11,
              'cpu1': 0.22,
              'cpu2': 0.33,
              'cpu3': 0.44,
              'memory': 8 * units.Gi,                # 8GB in bytes
              'memory_internal_free': 5 * units.Mi,  # 5GB in kilobytes
              'vif_0_rx': 50,
              'vif_0_tx': 100,
              'vbd_0_read': 50,
              'vbd_0_write': 100}
        return vm.get(field, 0)

    def pool_eject(self, session, host_ref):
        pass

    def pool_join(self, session, hostname, username, password):
        pass

    def pool_set_name_label(self, session, pool_ref, name):
        pass

    def host_migrate_receive(self, session, destref, nwref, options):
        return {"value": "fake_migrate_data"}

    def VM_assert_can_migrate(self, session, vmref, migrate_data, live,
                              vdi_map, vif_map, options):
        pass

    def VM_migrate_send(self, session, mref, migrate_data, live, vdi_map,
                        vif_map, options):
        pass

    def VM_remove_from_blocked_operations(self, session, vm_ref, key):
        # operation is idempotent, XenServer doesn't care if the key exists
        _db_content['VM'][vm_ref]['blocked_operations'].pop(key, None)

    def xenapi_request(self, methodname, params):
        if methodname.startswith('login'):
            self._login(methodname, params)
            return None
        elif methodname == 'logout' or methodname == 'session.logout':
            self._logout()
            return None
        else:
            full_params = (self._session,) + params
            meth = getattr(self, methodname, None)
            if meth is None:
                LOG.debug('Raising NotImplemented')
                raise NotImplementedError(
                    _('xenapi.fake does not have an implementation for %s') %
                    methodname)
            return meth(*full_params)

    def call_xenapi(self, *args):
        return self.xenapi_request(args[0], args[1:])

    def get_all_refs_and_recs(self, cls):
        return get_all_records(cls).items()

    def get_rec(self, cls, ref):
        return _db_content[cls].get(ref, None)

    def _login(self, method, params):
        self._session = uuidutils.generate_uuid()
        _session_info = {'uuid': uuidutils.generate_uuid(),
                         'this_host': list(_db_content['host'])[0]}
        _db_content['session'][self._session] = _session_info
        self.host_ref = list(_db_content['host'])[0]

    def _logout(self):
        s = self._session
        self._session = None
        if s not in _db_content['session']:
            raise exception.NovaException(
                "Logging out a session that is invalid or already logged "
                "out: %s" % s)
        del _db_content['session'][s]

    def __getattr__(self, name):
        if name == 'handle':
            return self._session
        elif name == 'xenapi':
            return _Dispatcher(self.xenapi_request, None)
        elif name.startswith('login') or name.startswith('slave_local'):
            return lambda *params: self._login(name, params)
        elif name.startswith('Async'):
            return lambda *params: self._async(name, params)
        elif '.' in name:
            impl = getattr(self, name.replace('.', '_'))
            if impl is not None:

                def callit(*params):
                    LOG.debug('Calling %(name)s %(impl)s',
                              {'name': name, 'impl': impl})
                    self._check_session(params)
                    return impl(*params)
                return callit
        if self._is_gettersetter(name, True):
            LOG.debug('Calling getter %s', name)
            return lambda *params: self._getter(name, params)
        elif self._is_gettersetter(name, False):
            LOG.debug('Calling setter %s', name)
            return lambda *params: self._setter(name, params)
        elif self._is_create(name):
            return lambda *params: self._create(name, params)
        elif self._is_destroy(name):
            return lambda *params: self._destroy(name, params)
        elif name == 'XenAPI':
            return FakeXenAPI()
        else:
            return None

    def _is_gettersetter(self, name, getter):
        bits = name.split('.')
        return (len(bits) == 2 and
                bits[0] in _CLASSES and
                bits[1].startswith(getter and 'get_' or 'set_'))

    def _is_create(self, name):
        return self._is_method(name, 'create')

    def _is_destroy(self, name):
        return self._is_method(name, 'destroy')

    def _is_method(self, name, meth):
        bits = name.split('.')
        return (len(bits) == 2 and
                bits[0] in _CLASSES and
                bits[1] == meth)

    def _getter(self, name, params):
        self._check_session(params)
        (cls, func) = name.split('.')
        if func == 'get_all':
            self._check_arg_count(params, 1)
            return get_all(cls)

        if func == 'get_all_records':
            self._check_arg_count(params, 1)
            return get_all_records(cls)

        if func == 'get_all_records_where':
            self._check_arg_count(params, 2)
            return get_all_records_where(cls, params[1])

        if func == 'get_record':
            self._check_arg_count(params, 2)
            return get_record(cls, params[1])

        if func in ('get_by_name_label', 'get_by_uuid'):
            self._check_arg_count(params, 2)
            return_singleton = (func == 'get_by_uuid')
            return self._get_by_field(
                _db_content[cls], func[len('get_by_'):], params[1],
                return_singleton=return_singleton)

        if len(params) == 2:
            field = func[len('get_'):]
            ref = params[1]
            if (ref in _db_content[cls]):
                if (field in _db_content[cls][ref]):
                    return _db_content[cls][ref][field]
            else:
                raise XenAPI.Failure(['HANDLE_INVALID', cls, ref])

        LOG.debug('Raising NotImplemented')
        raise NotImplementedError(
            _('xenapi.fake does not have an implementation for %s or it has '
            'been called with the wrong number of arguments') % name)

    def _setter(self, name, params):
        self._check_session(params)
        (cls, func) = name.split('.')

        if len(params) == 3:
            field = func[len('set_'):]
            ref = params[1]
            val = params[2]

            if (ref in _db_content[cls] and
                    field in _db_content[cls][ref]):
                _db_content[cls][ref][field] = val
                return

        LOG.debug('Raising NotImplemented')
        raise NotImplementedError(
            'xenapi.fake does not have an implementation for %s or it has '
            'been called with the wrong number of arguments or the database '
            'is missing that field' % name)

    def _create(self, name, params):
        self._check_session(params)
        is_sr_create = name == 'SR.create'
        is_vlan_create = name == 'VLAN.create'
        # Storage Repositories have a different API
        expected = is_sr_create and 10 or is_vlan_create and 4 or 2
        self._check_arg_count(params, expected)
        (cls, _) = name.split('.')
        ref = (is_sr_create and
               _create_sr(cls, params) or
               is_vlan_create and
               _create_vlan(params[1], params[2], params[3]) or
               _create_object(cls, params[1]))

        # Call hook to provide any fixups needed (ex. creating backrefs)
        after_hook = 'after_%s_create' % cls
        try:
            func = _after_create_functions[after_hook]
        except KeyError:
            pass
        else:
            func(ref, params[1])

        obj = get_record(cls, ref)

        # Add RO fields
        if cls == 'VM':
            obj['power_state'] = 'Halted'
        return ref

    def _destroy(self, name, params):
        self._check_session(params)
        self._check_arg_count(params, 2)
        table = name.split('.')[0]
        ref = params[1]
        if ref not in _db_content[table]:
            raise XenAPI.Failure(['HANDLE_INVALID', table, ref])

        # Call destroy function (if exists)
        destroy_func = _destroy_functions.get('destroy_%s' % table.lower())
        if destroy_func:
            destroy_func(ref)
        else:
            del _db_content[table][ref]

    def _async(self, name, params):
        task_ref = create_task(name)
        task = _db_content['task'][task_ref]
        func = name[len('Async.'):]
        try:
            result = self.xenapi_request(func, params[1:])
            if result:
                result = as_value(result)
            task['result'] = result
            task['status'] = 'success'
        except XenAPI.Failure as exc:
            task['error_info'] = exc.details
            task['status'] = 'failed'
        task['finished'] = timeutils.utcnow()
        return task_ref

    def _check_session(self, params):
        if (self._session is None or
                self._session not in _db_content['session']):
            raise XenAPI.Failure(
                ['HANDLE_INVALID', 'session', self._session])
        if len(params) == 0 or params[0] != self._session:
            LOG.debug('Raising NotImplemented')
            raise NotImplementedError('Call to XenAPI without using .xenapi')

    def _check_arg_count(self, params, expected):
        actual = len(params)
        if actual != expected:
            raise XenAPI.Failure(
                ['MESSAGE_PARAMETER_COUNT_MISMATCH', expected, actual])

    def _get_by_field(self, recs, k, v, return_singleton):
        result = []
        for ref, rec in recs.items():
            if rec.get(k) == v:
                result.append(ref)

        if return_singleton:
            try:
                return result[0]
            except IndexError:
                raise XenAPI.Failure(['UUID_INVALID', v, result, recs, k])

        return result


class FakeXenAPI(object):
    def __init__(self):
        self.Failure = XenAPI.Failure


# Based upon _Method from xmlrpclib.
class _Dispatcher(object):
    def __init__(self, send, name):
        self.__send = send
        self.__name = name

    def __repr__(self):
        if self.__name:
            return '<xenapi.fake._Dispatcher for %s>' % self.__name
        else:
            return '<xenapi.fake._Dispatcher>'

    def __getattr__(self, name):
        if self.__name is None:
            return _Dispatcher(self.__send, name)
        else:
            return _Dispatcher(self.__send, "%s.%s" % (self.__name, name))

    def __call__(self, *args):
        return self.__send(self.__name, args)

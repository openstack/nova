# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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
#============================================================================
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


import json
import random
import uuid
from xml.sax.saxutils import escape

from pprint import pformat

from nova import exception
from nova import log as logging
from nova import utils


_CLASSES = ['host', 'network', 'session', 'SR', 'VBD',
            'PBD', 'VDI', 'VIF', 'PIF', 'VM', 'VLAN', 'task']

_db_content = {}

LOG = logging.getLogger("nova.virt.xenapi.fake")


def log_db_contents(msg=None):
    text = msg or ""
    content = pformat(_db_content)
    LOG.debug(_("%(text)s: _db_content => %(content)s") % locals())


def reset():
    for c in _CLASSES:
        _db_content[c] = {}
    create_host('fake')
    create_vm('fake',
              'Running',
              is_a_template=False,
              is_control_domain=True)


def reset_table(table):
    if not table in _CLASSES:
        return
    _db_content[table] = {}


def create_host(name_label):
    return _create_object('host',
                          {'name_label': name_label})


def create_network(name_label, bridge):
    return _create_object('network',
                          {'name_label': name_label,
                           'bridge': bridge})


def create_vm(name_label, status,
              is_a_template=False, is_control_domain=False):
    domid = status == 'Running' and random.randrange(1, 1 << 16) or -1
    return _create_object('VM',
                          {'name_label': name_label,
                           'domid': domid,
                           'power-state': status,
                           'is_a_template': is_a_template,
                           'is_control_domain': is_control_domain})


def destroy_vm(vm_ref):
    vm_rec = _db_content['VM'][vm_ref]

    vbd_refs = vm_rec['VBDs']
    for vbd_ref in vbd_refs:
        destroy_vbd(vbd_ref)

    del _db_content['VM'][vm_ref]


def destroy_vbd(vbd_ref):
    del _db_content['VBD'][vbd_ref]


def destroy_vdi(vdi_ref):
    del _db_content['VDI'][vdi_ref]


def create_vdi(name_label, read_only, sr_ref, sharable):
    return _create_object('VDI',
                          {'name_label': name_label,
                           'read_only': read_only,
                           'SR': sr_ref,
                           'type': '',
                           'name_description': '',
                           'sharable': sharable,
                           'other_config': {},
                           'location': '',
                           'xenstore_data': '',
                           'sm_config': {},
                           'physical_utilisation': '123',
                           'managed': True,
                           'VBDs': {}})


def create_vbd(vm_ref, vdi_ref):
    vbd_rec = {'VM': vm_ref,
               'VDI': vdi_ref,
               'userdevice': '0',
               'currently_attached': False}
    vbd_ref = _create_object('VBD', vbd_rec)
    after_VBD_create(vbd_ref, vbd_rec)
    return vbd_ref


def after_VBD_create(vbd_ref, vbd_rec):
    """Create read-only fields and backref from VM to VBD when VBD is
    created."""
    vbd_rec['currently_attached'] = False
    vbd_rec['device'] = ''
    vm_ref = vbd_rec['VM']
    vm_rec = _db_content['VM'][vm_ref]
    if vm_rec.get('VBDs', None):
        vm_rec['VBDs'].append(vbd_ref)
    else:
        vm_rec['VBDs'] = [vbd_ref]

    vm_name_label = _db_content['VM'][vm_ref]['name_label']
    vbd_rec['vm_name_label'] = vm_name_label


def after_VM_create(vm_ref, vm_rec):
    """Create read-only fields in the VM record."""
    if 'is_control_domain' not in vm_rec:
        vm_rec['is_control_domain'] = False


def create_pbd(config, host_ref, sr_ref, attached):
    return _create_object('PBD',
                          {'device-config': config,
                           'host': host_ref,
                           'SR': sr_ref,
                           'currently-attached': attached})


def create_task(name_label):
    return _create_object('task',
                          {'name_label': name_label,
                           'status': 'pending'})


def create_local_pifs():
    """Adds a PIF for each to the local database with VLAN=-1.
       Do this one per host."""
    for host_ref in _db_content['host'].keys():
        _create_local_pif(host_ref)
        _create_local_sr_iso(host_ref)


def create_local_srs():
    """Create an SR that looks like the one created on the local disk by
    default by the XenServer installer.  Do this one per host."""
    for host_ref in _db_content['host'].keys():
        _create_local_sr(host_ref)


def _create_local_sr(host_ref):
    sr_ref = _create_object(
             'SR',
             {'name_label': 'Local storage',
              'type': 'lvm',
              'content_type': 'user',
              'shared': False,
              'physical_size': str(1 << 30),
              'physical_utilisation': str(0),
              'virtual_allocation': str(0),
              'other_config': {
                     'i18n-original-value-name_label': 'Local storage',
                     'i18n-key': 'local-storage'},
              'VDIs': []})
    pbd_ref = create_pbd('', host_ref, sr_ref, True)
    _db_content['SR'][sr_ref]['PBDs'] = [pbd_ref]
    return sr_ref


def _create_local_sr_iso(host_ref):
    sr_ref = _create_object(
             'SR',
             {'name_label': 'Local storage ISO',
              'type': 'lvm',
              'content_type': 'iso',
              'shared': False,
              'physical_size': str(1 << 30),
              'physical_utilisation': str(0),
              'virtual_allocation': str(0),
              'other_config': {
                     'i18n-original-value-name_label': 'Local storage ISO',
                     'i18n-key': 'local-storage-iso'},
              'VDIs': []})
    pbd_ref = create_pbd('', host_ref, sr_ref, True)
    _db_content['SR'][sr_ref]['PBDs'] = [pbd_ref]
    return sr_ref


def _create_local_pif(host_ref):
    pif_ref = _create_object('PIF',
                             {'name-label': 'Fake PIF',
                              'MAC': '00:11:22:33:44:55',
                              'physical': True,
                              'VLAN': -1,
                              'device': 'fake0',
                              'host_uuid': host_ref})


def _create_object(table, obj):
    ref = str(uuid.uuid4())
    obj['uuid'] = str(uuid.uuid4())
    _db_content[table][ref] = obj
    return ref


def _create_sr(table, obj):
    sr_type = obj[6]
    # Forces fake to support iscsi only
    if sr_type != 'iscsi':
        raise Failure(['SR_UNKNOWN_DRIVER', sr_type])
    host_ref = _db_content['host'].keys()[0]
    sr_ref = _create_object(table, obj[2])
    vdi_ref = create_vdi('', False, sr_ref, False)
    pbd_ref = create_pbd('', host_ref, sr_ref, True)
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
    return _db_content[table].keys()


def get_all_records(table):
    return _db_content[table]


def get_record(table, ref):
    if ref in _db_content[table]:
        return _db_content[table].get(ref)
    else:
        raise Failure(['HANDLE_INVALID', table, ref])


def check_for_session_leaks():
    if len(_db_content['session']) > 0:
        raise exception.Error('Sessions have leaked: %s' %
                              _db_content['session'])


def as_value(s):
    """Helper function for simulating XenAPI plugin responses.  It
    escapes and wraps the given argument."""
    return '<value>%s</value>' % escape(s)


def as_json(*args, **kwargs):
    """Helper function for simulating XenAPI plugin responses for those
    that are returning JSON.  If this function is given plain arguments,
    then these are rendered as a JSON list.  If it's given keyword
    arguments then these are rendered as a JSON dict."""
    arg = args or kwargs
    return json.dumps(arg)


class Failure(Exception):
    def __init__(self, details):
        self.details = details

    def __str__(self):
        try:
            return str(self.details)
        except Exception:
            return "XenAPI Fake Failure: %s" % str(self.details)

    def _details_map(self):
        return dict([(str(i), self.details[i])
                     for i in range(len(self.details))])


class SessionBase(object):
    """
    Base class for Fake Sessions
    """

    def __init__(self, uri):
        self._session = None

    def VBD_plug(self, _1, ref):
        rec = get_record('VBD', ref)
        if rec['currently_attached']:
            raise Failure(['DEVICE_ALREADY_ATTACHED', ref])
        rec['currently_attached'] = True
        rec['device'] = rec['userdevice']

    def VBD_unplug(self, _1, ref):
        rec = get_record('VBD', ref)
        if not rec['currently_attached']:
            raise Failure(['DEVICE_ALREADY_DETACHED', ref])
        rec['currently_attached'] = False
        rec['device'] = ''

    def PBD_create(self, _1, pbd_rec):
        pbd_ref = _create_object('PBD', pbd_rec)
        _db_content['PBD'][pbd_ref]['currently_attached'] = False
        return pbd_ref

    def PBD_plug(self, _1, pbd_ref):
        rec = get_record('PBD', pbd_ref)
        if rec['currently_attached']:
            raise Failure(['DEVICE_ALREADY_ATTACHED', rec])
        rec['currently_attached'] = True
        sr_ref = rec['SR']
        _db_content['SR'][sr_ref]['PBDs'] = [pbd_ref]

    def PBD_unplug(self, _1, pbd_ref):
        rec = get_record('PBD', pbd_ref)
        if not rec['currently_attached']:
            raise Failure(['DEVICE_ALREADY_DETACHED', rec])
        rec['currently_attached'] = False
        sr_ref = pbd_ref['SR']
        _db_content['SR'][sr_ref]['PBDs'].remove(pbd_ref)

    def SR_introduce(self, _1, sr_uuid, label, desc, type, content_type,
                     shared, sm_config):
        host_ref = _db_content['host'].keys()[0]

        ref = None
        rec = None
        for ref, rec in _db_content['SR'].iteritems():
            if rec.get('uuid') == sr_uuid:
                break
        if rec:
            # make forgotten = 0 and return ref
            _db_content['SR'][ref]['forgotten'] = 0
            return ref
        else:
            # SR not found in db, so we create one
            params = {}
            params.update(locals())
            del params['self']
            sr_ref = _create_object('SR', params)
            _db_content['SR'][sr_ref]['uuid'] = sr_uuid
            _db_content['SR'][sr_ref]['forgotten'] = 0
            if type in ('iscsi'):
                # Just to be clear
                vdi_per_lun = True
            if vdi_per_lun:
                # we need to create a vdi because this introduce
                # is likely meant for a single vdi
                vdi_ref = create_vdi('', False, sr_ref, False)
                _db_content['SR'][sr_ref]['VDIs'] = [vdi_ref]
                _db_content['VDI'][vdi_ref]['SR'] = sr_ref
            return sr_ref

    def SR_forget(self, _1, sr_ref):
        _db_content['SR'][sr_ref]['forgotten'] = 1

    def SR_scan(self, _1, sr_ref):
        return

    def PIF_get_all_records_where(self, _1, _2):
        # TODO (salvatore-orlando): filter table on _2
        return _db_content['PIF']

    def VM_get_xenstore_data(self, _1, vm_ref):
        return _db_content['VM'][vm_ref].get('xenstore_data', '')

    def VM_remove_from_xenstore_data(self, _1, vm_ref, key):
        db_ref = _db_content['VM'][vm_ref]
        if not 'xenstore_data' in db_ref:
            return
        db_ref['xenstore_data'][key] = None

    def VM_add_to_xenstore_data(self, _1, vm_ref, key, value):
        db_ref = _db_content['VM'][vm_ref]
        if not 'xenstore_data' in db_ref:
            db_ref['xenstore_data'] = {}
        db_ref['xenstore_data'][key] = value

    def host_compute_free_memory(self, _1, ref):
        #Always return 12GB available
        return 12 * 1024 * 1024 * 1024

    def host_call_plugin(self, _1, _2, plugin, method, _5):
        if (plugin, method) == ('agent', 'version'):
            return as_json(returncode='0', message='1.0')
        elif (plugin, method) == ('glance', 'copy_kernel_vdi'):
            return ''
        elif (plugin, method) == ('glance', 'upload_vhd'):
            return ''
        elif (plugin, method) == ('migration', 'move_vhds_into_sr'):
            return ''
        elif (plugin, method) == ('migration', 'transfer_vhd'):
            return ''
        else:
            raise Exception('No simulation in host_call_plugin for %s,%s' %
                            (plugin, method))

    def VDI_get_virtual_size(self, *args):
        return 1 * 1024 * 1024 * 1024

    def VDI_resize_online(self, *args):
        return 'derp'

    VDI_resize = VDI_resize_online

    def VM_clean_reboot(self, *args):
        return 'burp'

    def network_get_all_records_where(self, _1, filter):
        return self.xenapi.network.get_all_records()

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
                LOG.debug(_('Raising NotImplemented'))
                raise NotImplementedError(
                    _('xenapi.fake does not have an implementation for %s') %
                    methodname)
            return meth(*full_params)

    def _login(self, method, params):
        self._session = str(uuid.uuid4())
        _db_content['session'][self._session] = \
                                {'uuid': str(uuid.uuid4()),
                                 'this_host': _db_content['host'].keys()[0]}

    def _logout(self):
        s = self._session
        self._session = None
        if s not in _db_content['session']:
            raise exception.Error(
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
                    localname = name
                    LOG.debug(_('Calling %(localname)s %(impl)s') % locals())
                    self._check_session(params)
                    return impl(*params)
                return callit
        if self._is_gettersetter(name, True):
            LOG.debug(_('Calling getter %s'), name)
            return lambda *params: self._getter(name, params)
        elif self._is_create(name):
            return lambda *params: self._create(name, params)
        elif self._is_destroy(name):
            return lambda *params: self._destroy(name, params)
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
                raise Failure(['HANDLE_INVALID', cls, ref])

        LOG.debug(_('Raising NotImplemented'))
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

        LOG.debug(_('Raising NotImplemented'))
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
        ref = is_sr_create and \
              _create_sr(cls, params) or \
              is_vlan_create and \
              _create_vlan(params[1], params[2], params[3]) or \
              _create_object(cls, params[1])

        # Call hook to provide any fixups needed (ex. creating backrefs)
        after_hook = 'after_%s_create' % cls
        if after_hook in globals():
            globals()[after_hook](ref, params[1])

        obj = get_record(cls, ref)

        # Add RO fields
        if cls == 'VM':
            obj['power_state'] = 'Halted'

        return ref

    def _destroy(self, name, params):
        self._check_session(params)
        self._check_arg_count(params, 2)
        table, _ = name.split('.')
        ref = params[1]
        if ref not in _db_content[table]:
            raise Failure(['HANDLE_INVALID', table, ref])
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
        except Failure, exc:
            task['error_info'] = exc.details
            task['status'] = 'failed'
        task['finished'] = utils.utcnow()
        return task_ref

    def _check_session(self, params):
        if (self._session is None or
            self._session not in _db_content['session']):
            raise Failure(['HANDLE_INVALID', 'session', self._session])
        if len(params) == 0 or params[0] != self._session:
            LOG.debug(_('Raising NotImplemented'))
            raise NotImplementedError('Call to XenAPI without using .xenapi')

    def _check_arg_count(self, params, expected):
        actual = len(params)
        if actual != expected:
            raise Failure(['MESSAGE_PARAMETER_COUNT_MISMATCH',
                                  expected, actual])

    def _get_by_field(self, recs, k, v, return_singleton):
        result = []
        for ref, rec in recs.iteritems():
            if rec.get(k) == v:
                result.append(ref)

        if return_singleton:
            try:
                return result[0]
            except IndexError:
                raise Failure(['UUID_INVALID', v, result, recs, k])

        return result


# Based upon _Method from xmlrpclib.
class _Dispatcher:
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

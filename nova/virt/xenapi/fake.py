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


import datetime
import logging
import uuid

from nova import exception


_CLASSES = ['host', 'network', 'session', 'SR', 'VBD',\
            'PBD', 'VDI', 'VIF', 'VM', 'task']

_db_content = {}


def reset():
    for c in _CLASSES:
        _db_content[c] = {}
    create_host('fake')


def create_host(name_label):
    return _create_object('host', {
        'name_label': name_label,
        })


def create_network(name_label, bridge):
    return _create_object('network', {
        'name_label': name_label,
        'bridge': bridge,
        })


def create_vm(name_label, status,
              is_a_template=False, is_control_domain=False):
    return _create_object('VM', {
        'name_label': name_label,
        'power-state': status,
        'is_a_template': is_a_template,
        'is_control_domain': is_control_domain,
        })


def create_vdi(name_label, read_only, sr_ref, sharable):
    return _create_object('VDI', {
        'name_label': name_label,
        'read_only': read_only,
        'SR': sr_ref,
        'type': '',
        'name_description': '',
        'sharable': sharable,
        'other_config': {},
        'location': '',
        'xenstore_data': '',
        'sm_config': {},
        'VBDs': {},
        })


def create_pbd(config, sr_ref, attached):
    return _create_object('PBD', {
        'device-config': config,
        'SR': sr_ref,
        'currently-attached': attached,
        })


def create_task(name_label):
    return _create_object('task', {
        'name_label': name_label,
        'status': 'pending',
        })


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
    sr_ref = _create_object(table, obj[2])
    vdi_ref = create_vdi('', False, sr_ref, False)
    pbd_ref = create_pbd('', sr_ref, True)
    _db_content['SR'][sr_ref]['VDIs'] = [vdi_ref]
    _db_content['SR'][sr_ref]['PBDs'] = [pbd_ref]
    _db_content['VDI'][vdi_ref]['SR'] = sr_ref
    _db_content['PBD'][pbd_ref]['SR'] = sr_ref
    return sr_ref


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


class Failure(Exception):
    def __init__(self, details):
        self.details = details

    def __str__(self):
        try:
            return str(self.details)
        except Exception, exc:
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
                logging.warn('Raising NotImplemented')
                raise NotImplementedError(
                    'xenapi.fake does not have an implementation for %s' %
                    methodname)
            return meth(*full_params)

    def _login(self, method, params):
        self._session = str(uuid.uuid4())
        _db_content['session'][self._session] = {
            'uuid': str(uuid.uuid4()),
            'this_host': _db_content['host'].keys()[0],
            }

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
                    logging.warn('Calling %s %s', name, impl)
                    self._check_session(params)
                    return impl(*params)
                return callit
        if self._is_gettersetter(name, True):
            logging.warn('Calling getter %s', name)
            return lambda *params: self._getter(name, params)
        elif self._is_create(name):
            return lambda *params: self._create(name, params)
        else:
            return None

    def _is_gettersetter(self, name, getter):
        bits = name.split('.')
        return (len(bits) == 2 and
                bits[0] in _CLASSES and
                bits[1].startswith(getter and 'get_' or 'set_'))

    def _is_create(self, name):
        bits = name.split('.')
        return (len(bits) == 2 and
                bits[0] in _CLASSES and
                bits[1] == 'create')

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

        if (func == 'get_by_name_label' or
            func == 'get_by_uuid'):
            self._check_arg_count(params, 2)
            return self._get_by_field(
                _db_content[cls], func[len('get_by_'):], params[1])

        if len(params) == 2:
            field = func[len('get_'):]
            ref = params[1]

            if (ref in _db_content[cls] and
                field in _db_content[cls][ref]):
                return _db_content[cls][ref][field]

        logging.error('Raising NotImplemented')
        raise NotImplementedError(
            'xenapi.fake does not have an implementation for %s or it has '
            'been called with the wrong number of arguments' % name)

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

        logging.warn('Raising NotImplemented')
        raise NotImplementedError(
            'xenapi.fake does not have an implementation for %s or it has '
            'been called with the wrong number of arguments or the database '
            'is missing that field' % name)

    def _create(self, name, params):
        self._check_session(params)
        is_sr_create = name == 'SR.create'
        # Storage Repositories have a different API
        expected = is_sr_create and 10 or 2
        self._check_arg_count(params, expected)
        (cls, _) = name.split('.')
        ref = is_sr_create and \
            _create_sr(cls, params) or _create_object(cls, params[1])
        obj = get_record(cls, ref)

        # Add RO fields
        if cls == 'VM':
            obj['power_state'] = 'Halted'

        return ref

    def _async(self, name, params):
        task_ref = create_task(name)
        task = _db_content['task'][task_ref]
        func = name[len('Async.'):]
        try:
            task['result'] = self.xenapi_request(func, params[1:])
            task['status'] = 'success'
        except Failure, exc:
            task['error_info'] = exc.details
            task['status'] = 'failed'
        task['finished'] = datetime.datetime.now()
        return task_ref

    def _check_session(self, params):
        if (self._session is None or
            self._session not in _db_content['session']):
            raise Failure(['HANDLE_INVALID', 'session', self._session])
        if len(params) == 0 or params[0] != self._session:
            logging.warn('Raising NotImplemented')
            raise NotImplementedError('Call to XenAPI without using .xenapi')

    def _check_arg_count(self, params, expected):
        actual = len(params)
        if actual != expected:
            raise Failure(['MESSAGE_PARAMETER_COUNT_MISMATCH',
                                  expected, actual])

    def _get_by_field(self, recs, k, v):
        result = []
        for ref, rec in recs.iteritems():
            if rec.get(k) == v:
                result.append(ref)
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

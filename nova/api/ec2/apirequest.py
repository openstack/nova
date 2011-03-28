# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
APIRequest class
"""

import datetime
import re
# TODO(termie): replace minidom with etree
from xml.dom import minidom

from nova import log as logging

LOG = logging.getLogger("nova.api.request")


_c2u = re.compile('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))')


def _camelcase_to_underscore(str):
    return _c2u.sub(r'_\1', str).lower().strip('_')


def _underscore_to_camelcase(str):
    return ''.join([x[:1].upper() + x[1:] for x in str.split('_')])


def _underscore_to_xmlcase(str):
    res = _underscore_to_camelcase(str)
    return res[:1].lower() + res[1:]


def _database_to_isoformat(datetimeobj):
    """Return a xs:dateTime parsable string from datatime"""
    return datetimeobj.strftime("%Y-%m-%dT%H:%M:%SZ")


def _try_convert(value):
    """Return a non-string from a string or unicode, if possible.

    ============= =====================================================
    When value is returns
    ============= =====================================================
    zero-length   ''
    'None'        None
    'True'        True
    'False'       False
    '0', '-0'     0
    0xN, -0xN     int from hex (postitive) (N is any number)
    0bN, -0bN     int from binary (positive) (N is any number)
    *             try conversion to int, float, complex, fallback value

    """
    if len(value) == 0:
        return ''
    if value == 'None':
        return None
    if value == 'True':
        return True
    if value == 'False':
        return False
    valueneg = value[1:] if value[0] == '-' else value
    if valueneg == '0':
        return 0
    if valueneg == '':
        return value
    if valueneg[0] == '0':
        if valueneg[1] in 'xX':
            return int(value, 16)
        elif valueneg[1] in 'bB':
            return int(value, 2)
        else:
            try:
                return int(value, 8)
            except ValueError:
                pass
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return complex(value)
    except ValueError:
        return value


class APIRequest(object):
    def __init__(self, controller, action, version, args):
        self.controller = controller
        self.action = action
        self.version = version
        self.args = args

    def invoke(self, context):
        try:
            method = getattr(self.controller,
                             _camelcase_to_underscore(self.action))
        except AttributeError:
            controller = self.controller
            action = self.action
            _error = _('Unsupported API request: controller = %(controller)s,'
                    ' action = %(action)s') % locals()
            LOG.exception(_error)
            # TODO: Raise custom exception, trap in apiserver,
            #       and reraise as 400 error.
            raise Exception(_error)

        args = {}
        for key, value in self.args.items():
            parts = key.split(".")
            key = _camelcase_to_underscore(parts[0])
            if isinstance(value, str) or isinstance(value, unicode):
                # NOTE(vish): Automatically convert strings back
                #             into their respective values
                value = _try_convert(value)
            if len(parts) > 1:
                d = args.get(key, {})
                d[parts[1]] = value
                value = d
            args[key] = value

        for key in args.keys():
            # NOTE(vish): Turn numeric dict keys into lists
            if isinstance(args[key], dict):
                if args[key] != {} and args[key].keys()[0].isdigit():
                    s = args[key].items()
                    s.sort()
                    args[key] = [v for k, v in s]

        result = method(context, **args)
        return self._render_response(result, context.request_id)

    def _render_response(self, response_data, request_id):
        xml = minidom.Document()

        response_el = xml.createElement(self.action + 'Response')
        response_el.setAttribute('xmlns',
                             'http://ec2.amazonaws.com/doc/%s/' % self.version)
        request_id_el = xml.createElement('requestId')
        request_id_el.appendChild(xml.createTextNode(request_id))
        response_el.appendChild(request_id_el)
        if(response_data == True):
            self._render_dict(xml, response_el, {'return': 'true'})
        else:
            self._render_dict(xml, response_el, response_data)

        xml.appendChild(response_el)

        response = xml.toxml()
        xml.unlink()
        LOG.debug(response)
        return response

    def _render_dict(self, xml, el, data):
        try:
            for key in data.keys():
                val = data[key]
                el.appendChild(self._render_data(xml, key, val))
        except:
            LOG.debug(data)
            raise

    def _render_data(self, xml, el_name, data):
        el_name = _underscore_to_xmlcase(el_name)
        data_el = xml.createElement(el_name)

        if isinstance(data, list):
            for item in data:
                data_el.appendChild(self._render_data(xml, 'item', item))
        elif isinstance(data, dict):
            self._render_dict(xml, data_el, data)
        elif hasattr(data, '__dict__'):
            self._render_dict(xml, data_el, data.__dict__)
        elif isinstance(data, bool):
            data_el.appendChild(xml.createTextNode(str(data).lower()))
        elif isinstance(data, datetime.datetime):
            data_el.appendChild(
                  xml.createTextNode(_database_to_isoformat(data)))
        elif data != None:
            data_el.appendChild(xml.createTextNode(str(data)))

        return data_el

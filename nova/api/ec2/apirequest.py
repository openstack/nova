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

# TODO(termie): replace minidom with etree
from xml.dom import minidom

from twisted.internet import defer


_c2u = re.compile('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))')


def _camelcase_to_underscore(str):
    return _c2u.sub(r'_\1', str).lower().strip('_')


def _underscore_to_camelcase(str):
    return ''.join([x[:1].upper() + x[1:] for x in str.split('_')])


def _underscore_to_xmlcase(str):
    res = _underscore_to_camelcase(str)
    return res[:1].lower() + res[1:]


class APIRequest(object):
    def __init__(self, controller, action):
        self.controller = controller
        self.action = action

    def send(self, context, **kwargs):

        try:
            method = getattr(self.controller,
                             _camelcase_to_underscore(self.action))
        except AttributeError:
            _error = ('Unsupported API request: controller = %s,'
                      'action = %s') % (self.controller, self.action)
            _log.warning(_error)
            # TODO: Raise custom exception, trap in apiserver,
            #       and reraise as 400 error.
            raise Exception(_error)

        args = {}
        for key, value in kwargs.items():
            parts = key.split(".")
            key = _camelcase_to_underscore(parts[0])
            if len(parts) > 1:
                d = args.get(key, {})
                d[parts[1]] = value[0]
                value = d
            else:
                value = value[0]
            args[key] = value

        for key in args.keys():
            if isinstance(args[key], dict):
                if args[key] != {} and args[key].keys()[0].isdigit():
                    s = args[key].items()
                    s.sort()
                    args[key] = [v for k, v in s]

        result = method(context, **args)

        req.headers['Content-Type'] = 'text/xml'
        return self._render_response(result, context.request_id)

    def _render_response(self, response_data, request_id):
        xml = minidom.Document()

        response_el = xml.createElement(self.action + 'Response')
        response_el.setAttribute('xmlns',
                                 'http://ec2.amazonaws.com/doc/2009-11-30/')
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
        _log.debug(response)
        return response

    def _render_dict(self, xml, el, data):
        try:
            for key in data.keys():
                val = data[key]
                el.appendChild(self._render_data(xml, key, val))
        except:
            _log.debug(data)
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
        elif data != None:
            data_el.appendChild(xml.createTextNode(str(data)))

        return data_el

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
Tornado REST API Request Handlers for Nova functions
Most calls are proxied into the responsible controller.
"""

import multiprocessing
import re
import urllib

import tornado.web

from nova import crypto
from nova import flags
import nova.cloudpipe.api
from nova.endpoint import cloud


FLAGS = flags.FLAGS
flags.DEFINE_integer('cc_port', 8773, 'cloud controller port')


class RootRequestHandler(tornado.web.RequestHandler):
    def get(self):
        # available api versions
        versions = [
            '1.0',
            '2007-01-19',
            '2007-03-01',
            '2007-08-29',
            '2007-10-10',
            '2007-12-15',
            '2008-02-01',
            '2008-09-01',
            '2009-04-04',
        ]
        for version in versions:
            self.write('%s\n' % version)
        self.finish()


class MetadataRequestHandler(tornado.web.RequestHandler):
    def print_data(self, data):
        if isinstance(data, dict):
            output = ''
            for key in data:
                if key == '_name':
                    continue
                output += key
                if isinstance(data[key], dict):
                    if '_name' in data[key]:
                        output += '=' + str(data[key]['_name'])
                    else:
                        output += '/'
                output += '\n'
            self.write(output[:-1]) # cut off last \n
        elif isinstance(data, list):
            self.write('\n'.join(data))
        else:
            self.write(str(data))

    def lookup(self, path, data):
        items = path.split('/')
        for item in items:
            if item:
                if not isinstance(data, dict):
                    return data
                if not item in data:
                    return None
                data = data[item]
        return data

    def get(self, path):
        cc = self.application.controllers['Cloud']
        meta_data = cc.get_metadata(self.request.remote_ip)
        if meta_data is None:
            _log.error('Failed to get metadata for ip: %s' %
                        self.request.remote_ip)
            raise tornado.web.HTTPError(404)
        data = self.lookup(path, meta_data)
        if data is None:
            raise tornado.web.HTTPError(404)
        self.print_data(data)
        self.finish()


class APIServerApplication(tornado.web.Application):
    def __init__(self, controllers):
        tornado.web.Application.__init__(self, [
            (r'/', RootRequestHandler),
            (r'/cloudpipe/(.*)', nova.cloudpipe.api.CloudPipeRequestHandler),
            (r'/cloudpipe', nova.cloudpipe.api.CloudPipeRequestHandler),
            (r'/services/([A-Za-z0-9]+)/', APIRequestHandler),
            (r'/latest/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2009-04-04/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2008-09-01/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2008-02-01/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2007-12-15/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2007-10-10/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2007-08-29/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2007-03-01/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/2007-01-19/([-A-Za-z0-9/]*)', MetadataRequestHandler),
            (r'/1.0/([-A-Za-z0-9/]*)', MetadataRequestHandler),
        ], pool=multiprocessing.Pool(4))
        self.controllers = controllers

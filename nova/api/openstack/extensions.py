# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import imp
import os
import sys
import routes
import webob.dec
import webob.exc

from nova import flags
from nova import log as logging
from nova import wsgi


LOG = logging.getLogger('extensions')


FLAGS = flags.FLAGS


class ExtensionActionController(wsgi.Controller):

    def __init__(self, application, action_name, handler):

        self.application = application
        self.action_name = action_name
        self.handler = handler

    def action(self, req, id):

        input_dict = self._deserialize(req.body, req.get_content_type())
        if self.action_name in input_dict:
            return self.handler(input_dict, req, id)
        # no action handler found (bump to downstream application)
        res = self.application
        return res


class ExtensionMiddleware(wsgi.Middleware):
    """
    Extensions middleware that intercepts configured routes for extensions.
    """
    @classmethod
    def factory(cls, global_config, **local_config):
        """ paste factory """
        def _factory(app):
            return cls(app, **local_config)
        return _factory

    def __init__(self, application, ext_mgr=None):
        mapper = routes.Mapper()

        if ext_mgr is None:
            ext_mgr = ExtensionManager(FLAGS.osapi_extensions_path)

        # create custom mapper connections for extended actions
        for action in ext_mgr.get_actions():
            controller = ExtensionActionController(application, action.name,
                                                    action.handler)
            mapper.connect("/%s/{id}/action.:(format)" % action.collection,
                            action='action',
                            controller=controller,
                            conditions=dict(method=['POST']))
            mapper.connect("/%s/{id}/action" % action.collection,
                            action='action',
                            controller=controller,
                            conditions=dict(method=['POST']))

        self._router = routes.middleware.RoutesMiddleware(self._dispatch,
                                                          mapper)

        super(ExtensionMiddleware, self).__init__(application)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """
        Route the incoming request with router.
        """
        req.environ['extended.app'] = self.application
        return self._router

    @staticmethod
    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def _dispatch(req):
        """
        Called by self._router after matching the incoming request to a route
        and putting the information into req.environ.  Either returns the
        routed WSGI app's response or defers to the extended application.
        """
        match = req.environ['wsgiorg.routing_args'][1]
        if not match:
            return req.environ['extended.app']
        app = match['controller']
        return app


class ExtensionManager(object):

    def __init__(self, path):
        LOG.audit(_('Initializing extension manager.'))

        self.path = path
        self.extensions = []
        self._load_extensions()

    def get_resources(self):
        """
        returns a list of ExtensionResource objects
        """
        resources = []
        for ext in self.extensions:
            resources.append(ext.get_resources())
        return resources

    def get_actions(self):
        actions = []
        for ext in self.extensions:
            actions.extend(ext.get_actions())
        return actions

    def _load_extensions(self):
        """
        Load extensions from the configured path. The extension name is
        constructed from the camel cased module_name + 'Extension'. If your
        extension module was named widgets.py the extension class within that
        module should be 'WidgetsExtension'.
        """
        if not os.path.exists(self.path):
            return

        for f in os.listdir(self.path):
            LOG.audit(_('Loading extension file: %s'), f)
            mod_name, file_ext = os.path.splitext(os.path.split(f)[-1])
            ext_path = os.path.join(self.path, f)
            if file_ext.lower() == '.py':
                mod = imp.load_source(mod_name, ext_path)
                ext_name = mod_name[0].upper() + mod_name[1:] + 'Extension'
                self.extensions.append(getattr(mod, ext_name)())


class ExtensionAction(object):

    def __init__(self, member, collection, name, handler):
        self.member = member
        self.collection = collection
        self.name = name
        self.handler = handler


class ExtensionResource(object):
    """
    Example ExtensionResource object. All ExtensionResource objects should
    adhere to this interface.
    """

    def add_routes(self, mapper):
        pass

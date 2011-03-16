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


class ActionExtensionController(wsgi.Controller):

    def __init__(self, application):

        self.application = application
        self.action_handlers = {}

    def add_action(self, action_name, handler):
        self.action_handlers[action_name] = handler

    def action(self, req, id):

        input_dict = self._deserialize(req.body, req.get_content_type())
        for action_name, handler in self.action_handlers.iteritems():
            if action_name in input_dict:
                return handler(input_dict, req, id)
        # no action handler found (bump to downstream application)
        res = self.application
        return res


class ResponseExtensionController(wsgi.Controller):

    def __init__(self, application):
        self.application = application
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)

    def process(self, req, *args, **kwargs):
        res = req.get_response(self.application)
        # currently response handlers are un-ordered
        for handler in self.handlers:
            return handler(res)


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

    def _actions_by_collection(self, application, ext_mgr):
        """
        Return a dict of ActionExtensionController objects by collection
        """
        action_controllers = {}
        for action in ext_mgr.get_actions():
            if not action.collection in action_controllers.keys():
                controller = ActionExtensionController(application)
                action_controllers[action.collection] = controller
        return action_controllers

    def _responses_by_collection(self, application, ext_mgr):
        """
        Return a dict of ResponseExtensionController objects by collection
        """
        response_ext_controllers = {}
        for resp_ext in ext_mgr.get_response_extensions():
            if not resp_ext.url_route in response_ext_controllers.keys():
                controller = ResponseExtensionController(application)
                response_ext_controllers[resp_ext.url_route] = controller
        return response_ext_controllers

    def __init__(self, application, ext_mgr=None):

        if ext_mgr is None:
            ext_mgr = ExtensionManager(FLAGS.osapi_extensions_path)
        self.ext_mgr = ext_mgr

        mapper = routes.Mapper()

        # extended resources
        for resource in ext_mgr.get_resources():
            LOG.debug(_('Extended resource: %s'),
                        resource.collection)
            mapper.resource(resource.collection, resource.collection,
                            controller=resource.controller,
                            collection=resource.collection_actions,
                            member=resource.member_actions,
                            parent_resource=resource.parent)

        # extended actions
        action_controllers = self._actions_by_collection(application, ext_mgr)
        for action in ext_mgr.get_actions():
            LOG.debug(_('Extended collection/action: %s/%s'),
                        action.collection,
                        action.action_name)
            controller = action_controllers[action.collection]
            controller.add_action(action.action_name, action.handler)

            mapper.connect("/%s/:(id)/action.:(format)" % action.collection,
                            action='action',
                            controller=controller,
                            conditions=dict(method=['POST']))
            mapper.connect("/%s/:(id)/action" % action.collection,
                            action='action',
                            controller=controller,
                            conditions=dict(method=['POST']))

        # extended responses
        resp_controllers = self._responses_by_collection(application, ext_mgr)
        for response_ext in ext_mgr.get_response_extensions():
            LOG.debug(_('Extended response: %s'), response_ext.url_route)
            controller = resp_controllers[response_ext.url_route]
            controller.add_handler(response_ext.handler)
            mapper.connect(response_ext.url_route + '.:(format)',
                            action='process',
                            controller=controller,
                            conditions=response_ext.conditions)

            mapper.connect(response_ext.url_route,
                            action='process',
                            controller=controller,
                            conditions=response_ext.conditions)

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
        Returns the routed WSGI app's response or defers to the extended
        application.
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
        returns a list of ResourceExtension objects
        """
        resources = []
        for ext in self.extensions:
            resources.extend(ext.get_resources())
        return resources

    def get_actions(self):
        """
        returns a list of ActionExtension objects
        """
        actions = []
        for ext in self.extensions:
            actions.extend(ext.get_actions())
        return actions

    def get_response_extensions(self):
        """
        returns a list of ResponseExtension objects
        """
        response_exts = []
        for ext in self.extensions:
            response_exts.extend(ext.get_response_extensions())
        return response_exts

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
                ext_name = mod_name[0].upper() + mod_name[1:]
                self.extensions.append(getattr(mod, ext_name)())


class ResponseExtension(object):
    """
    ResponseExtension objects can be used to add data to responses from
    core nova OpenStack API controllers.
    """

    def __init__(self, url_route, method, handler):
        self.url_route = url_route
        self.conditions = dict(method=[method])
        self.handler = handler


class ActionExtension(object):
    """
    ActionExtension objects can be used to add custom actions to core nova
    nova OpenStack API controllers.
    """

    def __init__(self, collection, action_name, handler):
        self.collection = collection
        self.action_name = action_name
        self.handler = handler


class ResourceExtension(object):
    """
    ResourceExtension objects can be used to add add top level resources
    to the OpenStack API in nova.
    """

    def __init__(self, collection, controller, parent=None,
                 collection_actions={}, member_actions={}):
        self.collection = collection
        self.controller = controller
        self.parent = parent
        self.collection_actions = collection_actions
        self.member_actions = member_actions

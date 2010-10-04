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

"""Starting point for routing EC2 requests"""

import logging
import routes
import webob
import webob.dec
import webob.exc

from nova import exception
from nova import flags
from nova import wsgi
from nova.api import context
from nova.api.ec2 import apirequest
from nova.api.ec2 import admin
from nova.api.ec2 import cloud
from nova.auth import manager


FLAGS = flags.FLAGS
_log = logging.getLogger("api")
_log.setLevel(logging.DEBUG)


class API(wsgi.Middleware):

    """Routing for all EC2 API requests."""

    def __init__(self):
        self.application = Authenticate(Router(Authorizer(Executor())))


class Authenticate(wsgi.Middleware):

    """Authenticate an EC2 request and add 'ec2.context' to WSGI environ."""

    @webob.dec.wsgify
    def __call__(self, req):
        # Read request signature and access id.
        try:
            signature = req.params['Signature']
            access = req.params['AWSAccessKeyId']
        except:
            raise webob.exc.HTTPBadRequest()

        # Make a copy of args for authentication and signature verification.
        auth_params = dict(req.params)
        auth_params.pop('Signature') # not part of authentication args

        # Authenticate the request.
        try:
            (user, project) = manager.AuthManager().authenticate(
                    access,
                    signature,
                    auth_params,
                    req.method,
                    req.host,
                    req.path)
        except exception.Error, ex:
            logging.debug("Authentication Failure: %s" % ex)
            raise webob.exc.HTTPForbidden()

        # Authenticated!
        req.environ['ec2.context'] = context.APIRequestContext(user, project)
        return self.application


class Router(wsgi.Middleware):

    """Add ec2.'controller', .'action', and .'action_args' to WSGI environ."""

    def __init__(self, application):
        super(Router, self).__init__(application)
        self.map = routes.Mapper()
        self.map.connect("/{controller_name}/")
        self.controllers = dict(Cloud=cloud.CloudController(),
                                Admin=admin.AdminController())

    @webob.dec.wsgify
    def __call__(self, req):
        # Obtain the appropriate controller and action for this request.
        try:
            match = self.map.match(req.path_info)
            controller_name = match['controller_name']
            controller = self.controllers[controller_name]
        except:
            raise webob.exc.HTTPNotFound()
        non_args = ['Action', 'Signature', 'AWSAccessKeyId', 'SignatureMethod',
                    'SignatureVersion', 'Version', 'Timestamp']
        args = dict(req.params)
        try:
            action = req.params['Action'] # raise KeyError if omitted
            for non_arg in non_args:
                args.pop(non_arg) # remove, but raise KeyError if omitted
        except:
            raise webob.exc.HTTPBadRequest()

        _log.debug('action: %s' % action)
        for key, value in args.items():
            _log.debug('arg: %s\t\tval: %s' % (key, value))

        # Success!
        req.environ['ec2.controller'] = controller
        req.environ['ec2.action'] = action
        req.environ['ec2.action_args'] = args
        return self.application


class Authorizer(wsgi.Middleware):

    """Authorize an EC2 API request.

    Return a 401 if ec2.controller and ec2.action in WSGI environ may not be
    executed in ec2.context.
    """

    def __init__(self, application):
        super(Authorizer, self).__init__(application)
        self.action_roles = {
            'CloudController': {
                'DescribeAvailabilityzones': ['all'],
                'DescribeRegions': ['all'],
                'DescribeSnapshots': ['all'],
                'DescribeKeyPairs': ['all'],
                'CreateKeyPair': ['all'],
                'DeleteKeyPair': ['all'],
                'DescribeSecurityGroups': ['all'],
                'AuthorizeSecurityGroupIngress': ['netadmin'],
                'RevokeSecurityGroupIngress': ['netadmin'],
                'CreateSecurityGroup': ['netadmin'],
                'DeleteSecurityGroup': ['netadmin'],
                'GetConsoleOutput': ['projectmanager', 'sysadmin'],
                'DescribeVolumes': ['projectmanager', 'sysadmin'],
                'CreateVolume': ['projectmanager', 'sysadmin'],
                'AttachVolume': ['projectmanager', 'sysadmin'],
                'DetachVolume': ['projectmanager', 'sysadmin'],
                'DescribeInstances': ['all'],
                'DescribeAddresses': ['all'],
                'AllocateAddress': ['netadmin'],
                'ReleaseAddress': ['netadmin'],
                'AssociateAddress': ['netadmin'],
                'DisassociateAddress': ['netadmin'],
                'RunInstances': ['projectmanager', 'sysadmin'],
                'TerminateInstances': ['projectmanager', 'sysadmin'],
                'RebootInstances': ['projectmanager', 'sysadmin'],
                'UpdateInstance': ['projectmanager', 'sysadmin'],
                'DeleteVolume': ['projectmanager', 'sysadmin'],
                'DescribeImages': ['all'],
                'DeregisterImage': ['projectmanager', 'sysadmin'],
                'RegisterImage': ['projectmanager', 'sysadmin'],
                'DescribeImageAttribute': ['all'],
                'ModifyImageAttribute': ['projectmanager', 'sysadmin'],
                'UpdateImage': ['projectmanager', 'sysadmin'],
            },
            'AdminController': {
                # All actions have the same permission: ['none'] (the default)
                # superusers will be allowed to run them
                # all others will get HTTPUnauthorized.
            },
        }

    @webob.dec.wsgify
    def __call__(self, req):
        context = req.environ['ec2.context']
        controller_name = req.environ['ec2.controller'].__class__.__name__
        action = req.environ['ec2.action']
        allowed_roles = self.action_roles[controller_name].get(action, ['none'])
        if self._matches_any_role(context, allowed_roles):
            return self.application
        else:
            raise webob.exc.HTTPUnauthorized()

    def _matches_any_role(self, context, roles):
        """Return True if any role in roles is allowed in context."""
        if context.user.is_superuser():
            return True
        if 'all' in roles:
            return True
        if 'none' in roles:
            return False
        return any(context.project.has_role(context.user.id, role)
                   for role in roles)


class Executor(wsgi.Application):

    """Execute an EC2 API request.

    Executes 'ec2.action' upon 'ec2.controller', passing 'ec2.context' and
    'ec2.action_args' (all variables in WSGI environ.)  Returns an XML
    response, or a 400 upon failure.
    """

    @webob.dec.wsgify
    def __call__(self, req):
        context = req.environ['ec2.context']
        controller = req.environ['ec2.controller']
        action = req.environ['ec2.action']
        args = req.environ['ec2.action_args']

        api_request = apirequest.APIRequest(controller, action)
        try:
            result = api_request.send(context, **args)
            req.headers['Content-Type'] = 'text/xml'
            return result
        except exception.ApiError as ex:

            if ex.code:
                return self._error(req, ex.code, ex.message)
            else:
                return self._error(req, type(ex).__name__, ex.message)
        # TODO(vish): do something more useful with unknown exceptions
        except Exception as ex:
            return self._error(req, type(ex).__name__, str(ex))

    def _error(self, req, code, message):
        resp = webob.Response()
        resp.status = 400
        resp.headers['Content-Type'] = 'text/xml'
        resp.body = ('<?xml version="1.0"?>\n'
                     '<Response><Errors><Error><Code>%s</Code>'
                     '<Message>%s</Message></Error></Errors>'
                     '<RequestID>?</RequestID></Response>') % (code, message)
        return resp


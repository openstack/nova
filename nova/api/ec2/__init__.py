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
Starting point for routing EC2 requests.

"""

from urlparse import urlparse

import eventlet
from eventlet.green import httplib
import webob
import webob.dec
import webob.exc

from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova import wsgi
from nova.api.ec2 import apirequest
from nova.api.ec2 import ec2utils
from nova.auth import manager

FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api")
flags.DEFINE_integer('lockout_attempts', 5,
                     'Number of failed auths before lockout.')
flags.DEFINE_integer('lockout_minutes', 15,
                     'Number of minutes to lockout if triggered.')
flags.DEFINE_integer('lockout_window', 15,
                     'Number of minutes for lockout window.')
flags.DECLARE('use_forwarded_for', 'nova.api.auth')


class RequestLogging(wsgi.Middleware):
    """Access-Log akin logging for all EC2 API requests."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        start = utils.utcnow()
        rv = req.get_response(self.application)
        self.log_request_completion(rv, req, start)
        return rv

    def log_request_completion(self, response, request, start):
        apireq = request.environ.get('ec2.request', None)
        if apireq:
            controller = apireq.controller
            action = apireq.action
        else:
            controller = None
            action = None
        ctxt = request.environ.get('nova.context', None)
        delta = utils.utcnow() - start
        seconds = delta.seconds
        microseconds = delta.microseconds
        LOG.info(
            "%s.%ss %s %s %s %s:%s %s [%s] %s %s",
            seconds,
            microseconds,
            request.remote_addr,
            request.method,
            "%s%s" % (request.script_name, request.path_info),
            controller,
            action,
            response.status_int,
            request.user_agent,
            request.content_type,
            response.content_type,
            context=ctxt)


class Lockout(wsgi.Middleware):
    """Lockout for x minutes on y failed auths in a z minute period.

    x = lockout_timeout flag
    y = lockout_window flag
    z = lockout_attempts flag

    Uses memcached if lockout_memcached_servers flag is set, otherwise it
    uses a very simple in-proccess cache. Due to the simplicity of
    the implementation, the timeout window is started with the first
    failed request, so it will block if there are x failed logins within
    that period.

    There is a possible race condition where simultaneous requests could
    sneak in before the lockout hits, but this is extremely rare and would
    only result in a couple of extra failed attempts."""

    def __init__(self, application):
        """middleware can use fake for testing."""
        if FLAGS.memcached_servers:
            import memcache
        else:
            from nova import fakememcache as memcache
        self.mc = memcache.Client(FLAGS.memcached_servers,
                                  debug=0)
        super(Lockout, self).__init__(application)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        access_key = str(req.params['AWSAccessKeyId'])
        failures_key = "authfailures-%s" % access_key
        failures = int(self.mc.get(failures_key) or 0)
        if failures >= FLAGS.lockout_attempts:
            detail = _("Too many failed authentications.")
            raise webob.exc.HTTPForbidden(detail=detail)
        res = req.get_response(self.application)
        if res.status_int == 403:
            failures = self.mc.incr(failures_key)
            if failures is None:
                # NOTE(vish): To use incr, failures has to be a string.
                self.mc.set(failures_key, '1', time=FLAGS.lockout_window * 60)
            elif failures >= FLAGS.lockout_attempts:
                lock_mins = FLAGS.lockout_minutes
                msg = _('Access key %(access_key)s has had %(failures)d'
                        ' failed authentications and will be locked out'
                        ' for %(lock_mins)d minutes.') % locals()
                LOG.warn(msg)
                self.mc.set(failures_key, str(failures),
                            time=FLAGS.lockout_minutes * 60)
        return res


class NoAuth(wsgi.Middleware):
    """Add user:project as 'nova.context' to WSGI environ."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if 'AWSAccessKeyId' not in req.params:
            raise webob.exc.HTTPBadRequest()
        user_id, _sep, project_id = req.params['AWSAccessKeyId'].partition(':')
        project_id = project_id or user_id
        remote_address = getattr(req, 'remote_address', '127.0.0.1')
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)
        ctx = context.RequestContext(user_id,
                                     project_id,
                                     is_admin=True,
                                     remote_address=remote_address)

        req.environ['nova.context'] = ctx
        return self.application


class Authenticate(wsgi.Middleware):
    """Authenticate an EC2 request and add 'nova.context' to WSGI environ."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        # Read request signature and access id.
        try:
            signature = req.params['Signature']
            access = req.params['AWSAccessKeyId']
        except KeyError:
            raise webob.exc.HTTPBadRequest()

        # Make a copy of args for authentication and signature verification.
        auth_params = dict(req.params)
        # Not part of authentication args
        auth_params.pop('Signature')

        # Authenticate the request.
        authman = manager.AuthManager()
        try:
            (user, project) = authman.authenticate(
                    access,
                    signature,
                    auth_params,
                    req.method,
                    req.host,
                    req.path)
        # Be explicit for what exceptions are 403, the rest bubble as 500
        except (exception.NotFound, exception.NotAuthorized,
                exception.InvalidSignature) as ex:
            LOG.audit(_("Authentication Failure: %s"), unicode(ex))
            raise webob.exc.HTTPForbidden()

        # Authenticated!
        remote_address = req.remote_addr
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)
        roles = authman.get_active_roles(user, project)
        ctxt = context.RequestContext(user_id=user.id,
                                      project_id=project.id,
                                      is_admin=user.is_admin(),
                                      roles=roles,
                                      remote_address=remote_address)
        req.environ['nova.context'] = ctxt
        uname = user.name
        pname = project.name
        msg = _('Authenticated Request For %(uname)s:%(pname)s)') % locals()
        LOG.audit(msg, context=req.environ['nova.context'])
        return self.application


class Requestify(wsgi.Middleware):

    def __init__(self, app, controller):
        super(Requestify, self).__init__(app)
        self.controller = utils.import_class(controller)()

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        non_args = ['Action', 'Signature', 'AWSAccessKeyId', 'SignatureMethod',
                    'SignatureVersion', 'Version', 'Timestamp']
        args = dict(req.params)
        try:
            # Raise KeyError if omitted
            action = req.params['Action']
            # Fix bug lp:720157 for older (version 1) clients
            version = req.params['SignatureVersion']
            if int(version) == 1:
                non_args.remove('SignatureMethod')
                if 'SignatureMethod' in args:
                    args.pop('SignatureMethod')
            for non_arg in non_args:
                # Remove, but raise KeyError if omitted
                args.pop(non_arg)
        except KeyError, e:
            raise webob.exc.HTTPBadRequest()

        LOG.debug(_('action: %s'), action)
        for key, value in args.items():
            LOG.debug(_('arg: %(key)s\t\tval: %(value)s') % locals())

        # Success!
        api_request = apirequest.APIRequest(self.controller, action,
                                            req.params['Version'], args)
        req.environ['ec2.request'] = api_request
        req.environ['ec2.action_args'] = args
        return self.application


class Authorizer(wsgi.Middleware):

    """Authorize an EC2 API request.

    Return a 401 if ec2.controller and ec2.action in WSGI environ may not be
    executed in nova.context.
    """

    def __init__(self, application):
        super(Authorizer, self).__init__(application)
        self.action_roles = {
            'CloudController': {
                'DescribeAvailabilityZones': ['all'],
                'DescribeRegions': ['all'],
                'DescribeSnapshots': ['all'],
                'DescribeKeyPairs': ['all'],
                'CreateKeyPair': ['all'],
                'DeleteKeyPair': ['all'],
                'DescribeSecurityGroups': ['all'],
                'ImportPublicKey': ['all'],
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
                'StartInstances': ['projectmanager', 'sysadmin'],
                'StopInstances': ['projectmanager', 'sysadmin'],
                'DeleteVolume': ['projectmanager', 'sysadmin'],
                'DescribeImages': ['all'],
                'DeregisterImage': ['projectmanager', 'sysadmin'],
                'RegisterImage': ['projectmanager', 'sysadmin'],
                'DescribeImageAttribute': ['all'],
                'ModifyImageAttribute': ['projectmanager', 'sysadmin'],
                'UpdateImage': ['projectmanager', 'sysadmin'],
                'CreateImage': ['projectmanager', 'sysadmin'],
            },
            'AdminController': {
                # All actions have the same permission: ['none'] (the default)
                # superusers will be allowed to run them
                # all others will get HTTPUnauthorized.
            },
        }

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        context = req.environ['nova.context']
        controller = req.environ['ec2.request'].controller.__class__.__name__
        action = req.environ['ec2.request'].action
        allowed_roles = self.action_roles[controller].get(action, ['none'])
        if self._matches_any_role(context, allowed_roles):
            return self.application
        else:
            LOG.audit(_('Unauthorized request for controller=%(controller)s '
                        'and action=%(action)s') % locals(), context=context)
            raise webob.exc.HTTPUnauthorized()

    def _matches_any_role(self, context, roles):
        """Return True if any role in roles is allowed in context."""
        if context.is_admin:
            return True
        if 'all' in roles:
            return True
        if 'none' in roles:
            return False
        return any(role in context.roles for role in roles)


class Executor(wsgi.Application):

    """Execute an EC2 API request.

    Executes 'ec2.action' upon 'ec2.controller', passing 'nova.context' and
    'ec2.action_args' (all variables in WSGI environ.)  Returns an XML
    response, or a 400 upon failure.
    """

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        context = req.environ['nova.context']
        api_request = req.environ['ec2.request']
        result = None
        try:
            result = api_request.invoke(context)
        except exception.InstanceNotFound as ex:
            LOG.info(_('InstanceNotFound raised: %s'), unicode(ex),
                     context=context)
            ec2_id = ec2utils.id_to_ec2_id(ex.kwargs['instance_id'])
            message = ex.message % {'instance_id': ec2_id}
            return self._error(req, context, type(ex).__name__, message)
        except exception.VolumeNotFound as ex:
            LOG.info(_('VolumeNotFound raised: %s'), unicode(ex),
                     context=context)
            ec2_id = ec2utils.id_to_ec2_vol_id(ex.kwargs['volume_id'])
            message = ex.message % {'volume_id': ec2_id}
            return self._error(req, context, type(ex).__name__, message)
        except exception.SnapshotNotFound as ex:
            LOG.info(_('SnapshotNotFound raised: %s'), unicode(ex),
                     context=context)
            ec2_id = ec2utils.id_to_ec2_snap_id(ex.kwargs['snapshot_id'])
            message = ex.message % {'snapshot_id': ec2_id}
            return self._error(req, context, type(ex).__name__, message)
        except exception.NotFound as ex:
            LOG.info(_('NotFound raised: %s'), unicode(ex), context=context)
            return self._error(req, context, type(ex).__name__, unicode(ex))
        except exception.ApiError as ex:
            LOG.exception(_('ApiError raised: %s'), unicode(ex),
                          context=context)
            if ex.code:
                return self._error(req, context, ex.code, unicode(ex))
            else:
                return self._error(req, context, type(ex).__name__,
                                   unicode(ex))
        except exception.KeyPairExists as ex:
            LOG.debug(_('KeyPairExists raised: %s'), unicode(ex),
                     context=context)
            return self._error(req, context, type(ex).__name__, unicode(ex))
        except exception.InvalidParameterValue as ex:
            LOG.debug(_('InvalidParameterValue raised: %s'), unicode(ex),
                     context=context)
            return self._error(req, context, type(ex).__name__, unicode(ex))
        except exception.InvalidPortRange as ex:
            LOG.debug(_('InvalidPortRange raised: %s'), unicode(ex),
                     context=context)
            return self._error(req, context, type(ex).__name__, unicode(ex))
        except exception.NotAuthorized as ex:
            LOG.info(_('NotAuthorized raised: %s'), unicode(ex),
                    context=context)
            return self._error(req, context, type(ex).__name__, unicode(ex))
        except Exception as ex:
            extra = {'environment': req.environ}
            LOG.exception(_('Unexpected error raised: %s'), unicode(ex),
                          extra=extra, context=context)
            return self._error(req,
                               context,
                               'UnknownError',
                               _('An unknown error has occurred. '
                               'Please try your request again.'))
        else:
            resp = webob.Response()
            resp.status = 200
            resp.headers['Content-Type'] = 'text/xml'
            resp.body = str(result)
            return resp

    def _error(self, req, context, code, message):
        LOG.error("%s: %s", code, message, context=context)
        resp = webob.Response()
        resp.status = 400
        resp.headers['Content-Type'] = 'text/xml'
        resp.body = str('<?xml version="1.0"?>\n'
                         '<Response><Errors><Error><Code>%s</Code>'
                         '<Message>%s</Message></Error></Errors>'
                         '<RequestID>%s</RequestID></Response>' %
                         (utils.utf8(code), utils.utf8(message),
                         utils.utf8(context.request_id)))
        return resp


class Versions(wsgi.Application):

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """Respond to a request for all EC2 versions."""
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
        return ''.join('%s\n' % v for v in versions)

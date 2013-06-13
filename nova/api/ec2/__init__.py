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

import urlparse

from eventlet.green import httplib
from oslo.config import cfg
import webob
import webob.dec
import webob.exc

from nova.api.ec2 import apirequest
from nova.api.ec2 import ec2utils
from nova.api.ec2 import faults
from nova.api import validator
from nova import context
from nova import exception
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import memorycache
from nova.openstack.common import timeutils
from nova import utils
from nova import wsgi


LOG = logging.getLogger(__name__)

ec2_opts = [
    cfg.IntOpt('lockout_attempts',
               default=5,
               help='Number of failed auths before lockout.'),
    cfg.IntOpt('lockout_minutes',
               default=15,
               help='Number of minutes to lockout if triggered.'),
    cfg.IntOpt('lockout_window',
               default=15,
               help='Number of minutes for lockout window.'),
    cfg.StrOpt('keystone_ec2_url',
               default='http://localhost:5000/v2.0/ec2tokens',
               help='URL to get token from ec2 request.'),
    cfg.BoolOpt('ec2_private_dns_show_ip',
                default=False,
                help='Return the IP address as private dns hostname in '
                     'describe instances'),
    cfg.BoolOpt('ec2_strict_validation',
                default=True,
                help='Validate security group names'
                     ' according to EC2 specification'),
    cfg.IntOpt('ec2_timestamp_expiry',
               default=300,
               help='Time in seconds before ec2 timestamp expires'),
    ]

CONF = cfg.CONF
CONF.register_opts(ec2_opts)
CONF.import_opt('use_forwarded_for', 'nova.api.auth')


def ec2_error(req, request_id, code, message):
    """Helper to send an ec2_compatible error."""
    LOG.error(_('%(code)s: %(message)s'), {'code': code, 'message': message})
    resp = webob.Response()
    resp.status = 400
    resp.headers['Content-Type'] = 'text/xml'
    resp.body = str('<?xml version="1.0"?>\n'
                     '<Response><Errors><Error><Code>%s</Code>'
                     '<Message>%s</Message></Error></Errors>'
                     '<RequestID>%s</RequestID></Response>' %
                     (utils.xhtml_escape(utils.utf8(code)),
                      utils.xhtml_escape(utils.utf8(message)),
                      utils.xhtml_escape(utils.utf8(request_id))))
    return resp


## Fault Wrapper around all EC2 requests ##
class FaultWrapper(wsgi.Middleware):
    """Calls the middleware stack, captures any exceptions into faults."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except Exception as ex:
            LOG.exception(_("FaultWrapper: %s"), unicode(ex))
            return faults.Fault(webob.exc.HTTPInternalServerError())


class RequestLogging(wsgi.Middleware):
    """Access-Log akin logging for all EC2 API requests."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        start = timeutils.utcnow()
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
        delta = timeutils.utcnow() - start
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
    uses a very simple in-process cache. Due to the simplicity of
    the implementation, the timeout window is started with the first
    failed request, so it will block if there are x failed logins within
    that period.

    There is a possible race condition where simultaneous requests could
    sneak in before the lockout hits, but this is extremely rare and would
    only result in a couple of extra failed attempts.
    """

    def __init__(self, application):
        """middleware can use fake for testing."""
        self.mc = memorycache.get_client()
        super(Lockout, self).__init__(application)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        access_key = str(req.params['AWSAccessKeyId'])
        failures_key = "authfailures-%s" % access_key
        failures = int(self.mc.get(failures_key) or 0)
        if failures >= CONF.lockout_attempts:
            detail = _("Too many failed authentications.")
            raise webob.exc.HTTPForbidden(detail=detail)
        res = req.get_response(self.application)
        if res.status_int == 403:
            failures = self.mc.incr(failures_key)
            if failures is None:
                # NOTE(vish): To use incr, failures has to be a string.
                self.mc.set(failures_key, '1', time=CONF.lockout_window * 60)
            elif failures >= CONF.lockout_attempts:
                LOG.warn(_('Access key %(access_key)s has had %(failures)d '
                           'failed authentications and will be locked out '
                           'for %(lock_mins)d minutes.'),
                         {'access_key': access_key,
                          'failures': failures,
                          'lock_mins': CONF.lockout_minutes})
                self.mc.set(failures_key, str(failures),
                            time=CONF.lockout_minutes * 60)
        return res


class EC2KeystoneAuth(wsgi.Middleware):
    """Authenticate an EC2 request with keystone and convert to context."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        request_id = context.generate_request_id()
        signature = req.params.get('Signature')
        if not signature:
            msg = _("Signature not provided")
            return ec2_error(req, request_id, "Unauthorized", msg)
        access = req.params.get('AWSAccessKeyId')
        if not access:
            msg = _("Access key not provided")
            return ec2_error(req, request_id, "Unauthorized", msg)

        # Make a copy of args for authentication and signature verification.
        auth_params = dict(req.params)
        # Not part of authentication args
        auth_params.pop('Signature')

        cred_dict = {
            'access': access,
            'signature': signature,
            'host': req.host,
            'verb': req.method,
            'path': req.path,
            'params': auth_params,
        }
        if "ec2" in CONF.keystone_ec2_url:
            creds = {'ec2Credentials': cred_dict}
        else:
            creds = {'auth': {'OS-KSEC2:ec2Credentials': cred_dict}}
        creds_json = jsonutils.dumps(creds)
        headers = {'Content-Type': 'application/json'}

        o = urlparse.urlparse(CONF.keystone_ec2_url)
        if o.scheme == "http":
            conn = httplib.HTTPConnection(o.netloc)
        else:
            conn = httplib.HTTPSConnection(o.netloc)
        conn.request('POST', o.path, body=creds_json, headers=headers)
        response = conn.getresponse()
        data = response.read()
        if response.status != 200:
            if response.status == 401:
                msg = response.reason
            else:
                msg = _("Failure communicating with keystone")
            return ec2_error(req, request_id, "Unauthorized", msg)
        result = jsonutils.loads(data)
        conn.close()

        try:
            token_id = result['access']['token']['id']
            user_id = result['access']['user']['id']
            project_id = result['access']['token']['tenant']['id']
            user_name = result['access']['user'].get('name')
            project_name = result['access']['token']['tenant'].get('name')
            roles = [role['name'] for role
                     in result['access']['user']['roles']]
        except (AttributeError, KeyError) as e:
            LOG.exception(_("Keystone failure: %s") % e)
            msg = _("Failure communicating with keystone")
            return ec2_error(req, request_id, "Unauthorized", msg)

        remote_address = req.remote_addr
        if CONF.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For',
                                             remote_address)

        catalog = result['access']['serviceCatalog']
        ctxt = context.RequestContext(user_id,
                                      project_id,
                                      user_name=user_name,
                                      project_name=project_name,
                                      roles=roles,
                                      auth_token=token_id,
                                      remote_address=remote_address,
                                      service_catalog=catalog)

        req.environ['nova.context'] = ctxt

        return self.application


class NoAuth(wsgi.Middleware):
    """Add user:project as 'nova.context' to WSGI environ."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if 'AWSAccessKeyId' not in req.params:
            raise webob.exc.HTTPBadRequest()
        user_id, _sep, project_id = req.params['AWSAccessKeyId'].partition(':')
        project_id = project_id or user_id
        remote_address = req.remote_addr
        if CONF.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)
        ctx = context.RequestContext(user_id,
                                     project_id,
                                     is_admin=True,
                                     remote_address=remote_address)

        req.environ['nova.context'] = ctx
        return self.application


class Requestify(wsgi.Middleware):

    def __init__(self, app, controller):
        super(Requestify, self).__init__(app)
        self.controller = importutils.import_object(controller)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        non_args = ['Action', 'Signature', 'AWSAccessKeyId', 'SignatureMethod',
                    'SignatureVersion', 'Version', 'Timestamp']
        args = dict(req.params)
        try:
            expired = ec2utils.is_ec2_timestamp_expired(req.params,
                            expires=CONF.ec2_timestamp_expiry)
            if expired:
                msg = _("Timestamp failed validation.")
                LOG.exception(msg)
                raise webob.exc.HTTPForbidden(detail=msg)

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
        except KeyError:
            raise webob.exc.HTTPBadRequest()
        except exception.InvalidRequest as err:
            raise webob.exc.HTTPBadRequest(explanation=unicode(err))

        LOG.debug(_('action: %s'), action)
        for key, value in args.items():
            LOG.debug(_('arg: %(key)s\t\tval: %(value)s'),
                      {'key': key, 'value': value})

        # Success!
        api_request = apirequest.APIRequest(self.controller, action,
                                            req.params['Version'], args)
        req.environ['ec2.request'] = api_request
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
                'ImportKeyPair': ['all'],
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
                        'and action=%(action)s'),
                      {'controller': controller, 'action': action},
                      context=context)
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


class Validator(wsgi.Middleware):

    def validate_ec2_id(val):
        if not validator.validate_str()(val):
            return False
        try:
            ec2utils.ec2_id_to_id(val)
        except exception.InvalidEc2Id:
            return False
        return True

    validator.validate_ec2_id = validate_ec2_id

    validator.DEFAULT_VALIDATOR = {
        'instance_id': validator.validate_ec2_id,
        'volume_id': validator.validate_ec2_id,
        'image_id': validator.validate_ec2_id,
        'attribute': validator.validate_str(),
        'image_location': validator.validate_image_path,
        'public_ip': utils.is_valid_ipv4,
        'region_name': validator.validate_str(),
        'group_name': validator.validate_str(max_length=255),
        'group_description': validator.validate_str(max_length=255),
        'size': validator.validate_int(),
        'user_data': validator.validate_user_data
    }

    def __init__(self, application):
        super(Validator, self).__init__(application)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if validator.validate(req.environ['ec2.request'].args,
                              validator.DEFAULT_VALIDATOR):
            return self.application
        else:
            raise webob.exc.HTTPBadRequest()


class Executor(wsgi.Application):

    """Execute an EC2 API request.

    Executes 'ec2.action' upon 'ec2.controller', passing 'nova.context' and
    'ec2.action_args' (all variables in WSGI environ.)  Returns an XML
    response, or a 400 upon failure.
    """

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        context = req.environ['nova.context']
        request_id = context.request_id
        api_request = req.environ['ec2.request']
        result = None
        try:
            result = api_request.invoke(context)
        except exception.InstanceNotFound as ex:
            LOG.info(_('InstanceNotFound raised: %s'), unicode(ex),
                     context=context)
            ec2_id = ec2utils.id_to_ec2_inst_id(ex.kwargs['instance_id'])
            message = ex.message % {'instance_id': ec2_id}
            return ec2_error(req, request_id, type(ex).__name__, message)
        except exception.VolumeNotFound as ex:
            LOG.info(_('VolumeNotFound raised: %s'), unicode(ex),
                     context=context)
            ec2_id = ec2utils.id_to_ec2_vol_id(ex.kwargs['volume_id'])
            message = ex.message % {'volume_id': ec2_id}
            return ec2_error(req, request_id, type(ex).__name__, message)
        except exception.SnapshotNotFound as ex:
            LOG.info(_('SnapshotNotFound raised: %s'), unicode(ex),
                     context=context)
            ec2_id = ec2utils.id_to_ec2_snap_id(ex.kwargs['snapshot_id'])
            message = ex.message % {'snapshot_id': ec2_id}
            return ec2_error(req, request_id, type(ex).__name__, message)
        except exception.NotFound as ex:
            LOG.info(_('NotFound raised: %s'), unicode(ex), context=context)
            return ec2_error(req, request_id, type(ex).__name__, unicode(ex))
        except exception.EC2APIError as ex:
            if ex.code:
                return ec2_error(req, request_id, ex.code, unicode(ex))
            else:
                return ec2_error(req, request_id, type(ex).__name__,
                                   unicode(ex))
        except exception.KeyPairExists as ex:
            LOG.debug(_('KeyPairExists raised: %s'), unicode(ex),
                     context=context)
            code = 'InvalidKeyPair.Duplicate'
            return ec2_error(req, request_id, code, unicode(ex))
        except exception.InvalidKeypair as ex:
            LOG.debug(_('InvalidKeypair raised: %s'), unicode(ex),
                        context)
            code = 'InvalidKeyPair.Format'
            return ec2_error(req, request_id, code, unicode(ex))
        except exception.InvalidParameterValue as ex:
            LOG.debug(_('InvalidParameterValue raised: %s'), unicode(ex),
                     context=context)
            return ec2_error(req, request_id, type(ex).__name__, unicode(ex))
        except exception.InvalidPortRange as ex:
            LOG.debug(_('InvalidPortRange raised: %s'), unicode(ex),
                     context=context)
            return ec2_error(req, request_id, type(ex).__name__, unicode(ex))
        except exception.NotAuthorized as ex:
            LOG.info(_('NotAuthorized raised: %s'), unicode(ex),
                    context=context)
            return ec2_error(req, request_id, type(ex).__name__, unicode(ex))
        except exception.InvalidRequest as ex:
            LOG.debug(_('InvalidRequest raised: %s'), unicode(ex),
                     context=context)
            return ec2_error(req, request_id, type(ex).__name__, unicode(ex))
        except exception.QuotaError as ex:
            LOG.debug(_('QuotaError raised: %s'), unicode(ex),
                      context=context)
            return ec2_error(req, request_id, type(ex).__name__, unicode(ex))
        except exception.InvalidInstanceIDMalformed as ex:
            LOG.debug(_('Invalid id: bogus (expecting "i-..."): %s'),
                        unicode(ex), context=context)
            return ec2_error(req, request_id, type(ex).__name__, unicode(ex))
        except Exception as ex:
            env = req.environ.copy()
            for k in env.keys():
                if not isinstance(env[k], basestring):
                    env.pop(k)

            LOG.exception(_('Unexpected error raised: %s'), unicode(ex))
            LOG.error(_('Environment: %s') % jsonutils.dumps(env))
            return ec2_error(req, request_id, 'UnknownError',
                             _('An unknown error has occurred. '
                               'Please try your request again.'))
        else:
            resp = webob.Response()
            resp.status = 200
            resp.headers['Content-Type'] = 'text/xml'
            resp.body = str(result)
            return resp

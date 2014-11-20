# Copyright 2013 OpenStack Foundation
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

import contextlib
import cPickle as pickle
import errno
import socket
import time
import xmlrpclib

from eventlet import queue
from eventlet import timeout
from oslo.config import cfg

from nova import context
from nova import exception
from nova.i18n import _, _LE, _LW
from nova import objects
from nova.openstack.common import log as logging
from nova.openstack.common import versionutils
from nova import utils
from nova import version
from nova.virt.xenapi.client import objects as cli_objects
from nova.virt.xenapi import pool
from nova.virt.xenapi import pool_states

LOG = logging.getLogger(__name__)

xenapi_session_opts = [
    cfg.IntOpt('login_timeout',
               default=10,
               help='Timeout in seconds for XenAPI login.'),
    cfg.IntOpt('connection_concurrent',
               default=5,
               help='Maximum number of concurrent XenAPI connections. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    ]

CONF = cfg.CONF
CONF.register_opts(xenapi_session_opts, 'xenserver')
CONF.import_opt('host', 'nova.netconf')


def apply_session_helpers(session):
    session.VM = cli_objects.VM(session)
    session.SR = cli_objects.SR(session)
    session.VDI = cli_objects.VDI(session)
    session.VBD = cli_objects.VBD(session)
    session.PBD = cli_objects.PBD(session)
    session.PIF = cli_objects.PIF(session)
    session.VLAN = cli_objects.VLAN(session)
    session.host = cli_objects.Host(session)
    session.network = cli_objects.Network(session)
    session.pool = cli_objects.Pool(session)


class XenAPISession(object):
    """The session to invoke XenAPI SDK calls."""

    # This is not a config option as it should only ever be
    # changed in development environments.
    # MAJOR VERSION: Incompatible changes with the plugins
    # MINOR VERSION: Compatible changes, new plguins, etc
    PLUGIN_REQUIRED_VERSION = '1.2'

    def __init__(self, url, user, pw):
        version_string = version.version_string_with_package()
        self.nova_version = _('%(vendor)s %(product)s %(version)s') % \
                              {'vendor': version.vendor_string(),
                               'product': version.product_string(),
                               'version': version_string}
        import XenAPI
        self.XenAPI = XenAPI
        self._sessions = queue.Queue()
        self.is_slave = False
        exception = self.XenAPI.Failure(_("Unable to log in to XenAPI "
                                          "(is the Dom0 disk full?)"))
        url = self._create_first_session(url, user, pw, exception)
        self._populate_session_pool(url, user, pw, exception)
        self.host_uuid = self._get_host_uuid()
        self.host_ref = self._get_host_ref()
        self.product_version, self.product_brand = \
            self._get_product_version_and_brand()

        self._verify_plugin_version()

        apply_session_helpers(self)

    def _verify_plugin_version(self):
        requested_version = self.PLUGIN_REQUIRED_VERSION
        current_version = self.call_plugin_serialized(
            'nova_plugin_version', 'get_version')

        if not versionutils.is_compatible(requested_version, current_version):
            raise self.XenAPI.Failure(
                _("Plugin version mismatch (Expected %(exp)s, got %(got)s)") %
                {'exp': requested_version, 'got': current_version})

    def _create_first_session(self, url, user, pw, exception):
        try:
            session = self._create_session(url)
            with timeout.Timeout(CONF.xenserver.login_timeout, exception):
                session.login_with_password(user, pw,
                                            self.nova_version, 'OpenStack')
        except self.XenAPI.Failure as e:
            # if user and pw of the master are different, we're doomed!
            if e.details[0] == 'HOST_IS_SLAVE':
                master = e.details[1]
                url = pool.swap_xapi_host(url, master)
                session = self.XenAPI.Session(url)
                session.login_with_password(user, pw,
                                            self.nova_version, 'OpenStack')
                self.is_slave = True
            else:
                raise
        self._sessions.put(session)
        return url

    def _populate_session_pool(self, url, user, pw, exception):
        for i in xrange(CONF.xenserver.connection_concurrent - 1):
            session = self._create_session(url)
            with timeout.Timeout(CONF.xenserver.login_timeout, exception):
                session.login_with_password(user, pw,
                                            self.nova_version, 'OpenStack')
            self._sessions.put(session)

    def _get_host_uuid(self):
        if self.is_slave:
            aggr = objects.AggregateList.get_by_host(
                context.get_admin_context(),
                CONF.host, key=pool_states.POOL_FLAG)[0]
            if not aggr:
                LOG.error(_LE('Host is member of a pool, but DB '
                              'says otherwise'))
                raise exception.AggregateHostNotFound()
            return aggr.metadetails[CONF.host]
        else:
            with self._get_session() as session:
                host_ref = session.xenapi.session.get_this_host(session.handle)
                return session.xenapi.host.get_uuid(host_ref)

    def _get_product_version_and_brand(self):
        """Return a tuple of (major, minor, rev) for the host version and
        a string of the product brand.
        """
        software_version = self._get_software_version()

        product_version_str = software_version.get('product_version')
        # Product version is only set in some cases (e.g. XCP, XenServer) and
        # not in others (e.g. xenserver-core, XAPI-XCP).
        # In these cases, the platform version is the best number to use.
        if product_version_str is None:
            product_version_str = software_version.get('platform_version',
                                                       '0.0.0')
        product_brand = software_version.get('product_brand')
        product_version = utils.convert_version_to_tuple(product_version_str)

        return product_version, product_brand

    def _get_software_version(self):
        return self.call_xenapi('host.get_software_version', self.host_ref)

    def get_session_id(self):
        """Return a string session_id.  Used for vnc consoles."""
        with self._get_session() as session:
            return str(session._session)

    @contextlib.contextmanager
    def _get_session(self):
        """Return exclusive session for scope of with statement."""
        session = self._sessions.get()
        try:
            yield session
        finally:
            self._sessions.put(session)

    def _get_host_ref(self):
        """Return the xenapi host on which nova-compute runs on."""
        with self._get_session() as session:
            return session.xenapi.host.get_by_uuid(self.host_uuid)

    def call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread."""
        with self._get_session() as session:
            return session.xenapi_request(method, args)

    def call_plugin(self, plugin, fn, args):
        """Call host.call_plugin on a background thread."""
        # NOTE(armando): pass the host uuid along with the args so that
        # the plugin gets executed on the right host when using XS pools
        args['host_uuid'] = self.host_uuid

        with self._get_session() as session:
            return self._unwrap_plugin_exceptions(
                                 session.xenapi.host.call_plugin,
                                 self.host_ref, plugin, fn, args)

    def call_plugin_serialized(self, plugin, fn, *args, **kwargs):
        params = {'params': pickle.dumps(dict(args=args, kwargs=kwargs))}
        rv = self.call_plugin(plugin, fn, params)
        return pickle.loads(rv)

    def call_plugin_serialized_with_retry(self, plugin, fn, num_retries,
                                          callback, retry_cb=None, *args,
                                          **kwargs):
        """Allows a plugin to raise RetryableError so we can try again."""
        attempts = num_retries + 1
        sleep_time = 0.5
        for attempt in xrange(1, attempts + 1):
            try:
                if attempt > 1:
                    time.sleep(sleep_time)
                    sleep_time = min(2 * sleep_time, 15)

                callback_result = None
                if callback:
                    callback_result = callback(kwargs)

                msg = ('%(plugin)s.%(fn)s attempt %(attempt)d/%(attempts)d, '
                       'callback_result: %(callback_result)s')
                LOG.debug(msg,
                          {'plugin': plugin, 'fn': fn, 'attempt': attempt,
                           'attempts': attempts,
                           'callback_result': callback_result})
                return self.call_plugin_serialized(plugin, fn, *args, **kwargs)
            except self.XenAPI.Failure as exc:
                if self._is_retryable_exception(exc, fn):
                    LOG.warning(_LW('%(plugin)s.%(fn)s failed. '
                                    'Retrying call.'),
                                {'plugin': plugin, 'fn': fn})
                    if retry_cb:
                        retry_cb(exc=exc)
                else:
                    raise
            except socket.error as exc:
                if exc.errno == errno.ECONNRESET:
                    LOG.warning(_LW('Lost connection to XenAPI during call to '
                                    '%(plugin)s.%(fn)s.  Retrying call.'),
                                {'plugin': plugin, 'fn': fn})
                    if retry_cb:
                        retry_cb(exc=exc)
                else:
                    raise

        raise exception.PluginRetriesExceeded(num_retries=num_retries)

    def _is_retryable_exception(self, exc, fn):
        _type, method, error = exc.details[:3]
        if error == 'RetryableError':
            LOG.debug("RetryableError, so retrying %(fn)s", {'fn': fn},
                      exc_info=True)
            return True
        elif "signal" in method:
            LOG.debug("Error due to a signal, retrying %(fn)s", {'fn': fn},
                      exc_info=True)
            return True
        else:
            return False

    def _create_session(self, url):
        """Stubout point. This can be replaced with a mock session."""
        self.is_local_connection = url == "unix://local"
        if self.is_local_connection:
            return self.XenAPI.xapi_local()
        return self.XenAPI.Session(url)

    def _unwrap_plugin_exceptions(self, func, *args, **kwargs):
        """Parse exception details."""
        try:
            return func(*args, **kwargs)
        except self.XenAPI.Failure as exc:
            LOG.debug("Got exception: %s", exc)
            if (len(exc.details) == 4 and
                exc.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
                    exc.details[2] == 'Failure'):
                params = None
                try:
                    # FIXME(comstud): eval is evil.
                    params = eval(exc.details[3])
                except Exception:
                    raise exc
                raise self.XenAPI.Failure(params)
            else:
                raise
        except xmlrpclib.ProtocolError as exc:
            LOG.debug("Got exception: %s", exc)
            raise

    def get_rec(self, record_type, ref):
        try:
            return self.call_xenapi('%s.get_record' % record_type, ref)
        except self.XenAPI.Failure as e:
            if e.details[0] != 'HANDLE_INVALID':
                raise

        return None

    def get_all_refs_and_recs(self, record_type):
        """Retrieve all refs and recs for a Xen record type.

        Handles race-conditions where the record may be deleted between
        the `get_all` call and the `get_record` call.
        """

        return self.call_xenapi('%s.get_all_records' % record_type).items()

# Copyright 2012 Grid Dynamics
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

try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None

from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import units
from nova import utils

LOG = logging.getLogger(__name__)


class RBDVolumeProxy(object):
    """Context manager for dealing with an existing rbd volume.

    This handles connecting to rados and opening an ioctx automatically, and
    otherwise acts like a librbd Image object.

    The underlying librados client and ioctx can be accessed as the attributes
    'client' and 'ioctx'.
    """
    def __init__(self, driver, name, pool=None):
        client, ioctx = driver._connect_to_rados(pool)
        try:
            self.volume = driver.rbd.Image(ioctx, str(name), snapshot=None)
        except driver.rbd.Error:
            LOG.exception(_("error opening rbd image %s"), name)
            driver._disconnect_from_rados(client, ioctx)
            raise
        self.driver = driver
        self.client = client
        self.ioctx = ioctx

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        try:
            self.volume.close()
        finally:
            self.driver._disconnect_from_rados(self.client, self.ioctx)

    def __getattr__(self, attrib):
        return getattr(self.volume, attrib)


def ascii_str(s):
    """Convert a string to ascii, or return None if the input is None.

    This is useful when a parameter is None by default, or a string. LibRBD
    only accepts ascii, hence the need for conversion.
    """
    if s is None:
        return s
    return str(s)


class RBDDriver(object):

    def __init__(self, pool, ceph_conf, rbd_user,
                 rbd_lib=None, rados_lib=None):
        self.pool = pool.encode('utf8')
        self.ceph_conf = ceph_conf.encode('utf8') if ceph_conf else None
        self.rbd_user = rbd_user.encode('utf8') if rbd_user else None
        self.rbd = rbd_lib or rbd
        self.rados = rados_lib or rados
        if self.rbd is None:
            raise RuntimeError(_('rbd python libraries not found'))

    def _connect_to_rados(self, pool=None):
        client = self.rados.Rados(rados_id=self.rbd_user,
                                  conffile=self.ceph_conf)
        try:
            client.connect()
            pool_to_open = str(pool or self.pool)
            ioctx = client.open_ioctx(pool_to_open)
            return client, ioctx
        except self.rados.Error:
            # shutdown cannot raise an exception
            client.shutdown()
            raise

    def _disconnect_from_rados(self, client, ioctx):
        # closing an ioctx cannot raise an exception
        ioctx.close()
        client.shutdown()

    def supports_layering(self):
        return hasattr(self.rbd, 'RBD_FEATURE_LAYERING')

    def ceph_args(self):
        args = []
        if self.rbd_user:
            args.extend(['--id', self.rbd_user])
        if self.ceph_conf:
            args.extend(['--conf', self.ceph_conf])
        return args

    def get_mon_addrs(self):
        args = ['ceph', 'mon', 'dump', '--format=json'] + self.ceph_args()
        out, _ = utils.execute(*args)
        lines = out.split('\n')
        if lines[0].startswith('dumped monmap epoch'):
            lines = lines[1:]
        monmap = jsonutils.loads('\n'.join(lines))
        addrs = [mon['addr'] for mon in monmap['mons']]
        hosts = []
        ports = []
        for addr in addrs:
            host_port = addr[:addr.rindex('/')]
            host, port = host_port.rsplit(':', 1)
            hosts.append(host.strip('[]'))
            ports.append(port)
        return hosts, ports

    def size(self, name):
        with RBDVolumeProxy(self, name) as vol:
            return vol.size()

    def resize(self, volume_name, size):
        size = int(size) * units.Ki

        with RBDVolumeProxy(self, volume_name) as vol:
            vol.resize(size)

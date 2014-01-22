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

import urllib

try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None

from nova import exception
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)


class RBDVolumeProxy(object):
    """Context manager for dealing with an existing rbd volume.

    This handles connecting to rados and opening an ioctx automatically, and
    otherwise acts like a librbd Image object.

    The underlying librados client and ioctx can be accessed as the attributes
    'client' and 'ioctx'.
    """
    def __init__(self, driver, name, pool=None, snapshot=None,
                 read_only=False):
        client, ioctx = driver._connect_to_rados(pool)
        try:
            snap_name = snapshot.encode('utf8') if snapshot else None
            self.volume = driver.rbd.Image(ioctx, name.encode('utf8'),
                                           snapshot=snap_name,
                                           read_only=read_only)
        except driver.rbd.ImageNotFound:
            with excutils.save_and_reraise_exception():
                LOG.debug("rbd image %s does not exist", name)
                driver._disconnect_from_rados(client, ioctx)
        except driver.rbd.Error:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("error opening rbd image %s"), name)
                driver._disconnect_from_rados(client, ioctx)

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


class RADOSClient(object):
    """Context manager to simplify error handling for connecting to ceph."""
    def __init__(self, driver, pool=None):
        self.driver = driver
        self.cluster, self.ioctx = driver._connect_to_rados(pool)

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        self.driver._disconnect_from_rados(self.cluster, self.ioctx)


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
            pool_to_open = pool or self.pool
            ioctx = client.open_ioctx(pool_to_open.encode('utf-8'))
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

    def parse_location(self, location):
        prefix = 'rbd://'
        if not location.startswith(prefix):
            reason = _('Not stored in rbd')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        pieces = map(urllib.unquote, location[len(prefix):].split('/'))
        if '' in pieces:
            reason = _('Blank components')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        if len(pieces) != 4:
            reason = _('Not an rbd snapshot')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        return pieces

    def _get_fsid(self):
        with RADOSClient(self) as client:
            return client.cluster.get_fsid()

    def is_cloneable(self, image_location, image_meta):
        try:
            fsid, pool, image, snapshot = self.parse_location(image_location)
        except exception.ImageUnacceptable as e:
            LOG.debug(_('not cloneable: %s'), e)
            return False

        if self._get_fsid() != fsid:
            reason = _('%s is in a different ceph cluster') % image_location
            LOG.debug(reason)
            return False

        if image_meta['disk_format'] != 'raw':
            reason = _("rbd image clone requires image format to be "
                       "'raw' but image {0} is '{1}'").format(
                           image_location, image_meta['disk_format'])
            LOG.debug(reason)
            return False

        # check that we can read the image
        try:
            return self.exists(image, pool=pool, snapshot=snapshot)
        except self.rbd.Error as e:
            LOG.debug(_('Unable to open image %(loc)s: %(err)s') %
                      dict(loc=image_location, err=e))
            return False

    def clone(self, dest_pool, dest_image, src_pool, src_image, src_snap):
        LOG.debug(_('cloning %(pool)s/%(img)s@%(snap)s to %(dstpl)s/%(dst)s') %
                  dict(pool=src_pool, img=src_image, snap=src_snap,
                       dst=dest_image, dstpl=dest_pool))
        with RADOSClient(self, src_pool) as src_client:
            with RADOSClient(self, dest_pool) as dest_client:
                self.rbd.RBD().clone(src_client.ioctx,
                                     src_image.encode('utf-8'),
                                     src_snap.encode('utf-8'),
                                     dest_client.ioctx,
                                     dest_image.encode('utf-8'),
                                     features=self.rbd.RBD_FEATURE_LAYERING)

    def size(self, name):
        with RBDVolumeProxy(self, name) as vol:
            return vol.size()

    def resize(self, name, size_bytes):
        LOG.debug('resizing rbd image %s to %d', name, size_bytes)
        with RBDVolumeProxy(self, name) as vol:
            vol.resize(size_bytes)

    def exists(self, name, pool=None, snapshot=None):
        try:
            with RBDVolumeProxy(self, name,
                                pool=pool,
                                snapshot=snapshot,
                                read_only=True):
                return True
        except self.rbd.ImageNotFound:
            return False

    def remove(self, name):
        LOG.debug('removing rbd image %s', name)
        with RBDVolumeProxy(self, name) as vol:
            vol.remove()

    def rename(self, name, new_name):
        LOG.debug('renaming rbd image %s to %s', name, new_name)
        with RADOSClient(self) as client:
            self.rbd.RBD().rename(client.ioctx,
                                  name.encode('utf-8'),
                                  new_name.encode('utf-8'))

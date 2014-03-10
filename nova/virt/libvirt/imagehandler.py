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
RBD clone image handler for libvirt hypervisors.
"""

from oslo.config import cfg

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.imagehandler import base
from nova.virt.libvirt import rbd_utils

CONF = cfg.CONF
CONF.import_opt('images_rbd_pool', 'nova.virt.libvirt.imagebackend',
                group='libvirt')
CONF.import_opt('images_rbd_ceph_conf', 'nova.virt.libvirt.imagebackend',
                group='libvirt')
CONF.import_opt('rbd_user', 'nova.virt.libvirt.volume', group='libvirt')

LOG = logging.getLogger(__name__)


class RBDCloneImageHandler(base.ImageHandler):
    """Handler for rbd-backed images.

    If libvirt is using rbd for ephemeral/root disks, this handler
    will clone images already stored in rbd instead of downloading
    them locally and importing them into rbd.

    If rbd is not the image backend type, this handler does nothing.
    """
    def __init__(self, driver=None, *args, **kwargs):
        super(RBDCloneImageHandler, self).__init__(driver, *args, **kwargs)
        if not CONF.libvirt.images_rbd_pool:
            raise RuntimeError(_('You should specify images_rbd_pool flag in '
                                 'the libvirt section to use rbd images.'))
        self.driver = rbd_utils.RBDDriver(
            pool=CONF.libvirt.images_rbd_pool,
            ceph_conf=CONF.libvirt.images_rbd_ceph_conf,
            rbd_user=CONF.libvirt.rbd_user,
            rbd_lib=kwargs.get('rbd'),
            rados_lib=kwargs.get('rados'))

    def get_schemes(self):
        return ('rbd')

    def is_local(self):
        return False

    def _can_handle_image(self, context, image_meta, location, **kwargs):
        """Returns whether it makes sense to clone the image.

        - The glance image and libvirt image backend must be rbd.
        - The image must be readable by the rados user available to nova.
        - The image must be in raw format.
        """
        backend_type = kwargs.get('backend_type')
        backend_location = kwargs.get('backend_location')
        if backend_type != 'rbd' or not backend_location:
            LOG.debug('backend type is not rbd or backend_location is not set')
            return False

        return self.driver.is_cloneable(location['url'], image_meta)

    def _fetch_image(self, context, image_id, image_meta, path,
                     user_id=None, project_id=None, location=None,
                     **kwargs):
        if not self._can_handle_image(context, image_meta, location, **kwargs):
            return False

        dest_pool, dest_image = kwargs['backend_location']
        url = location['url']
        _fsid, pool, image, snapshot = self.driver.parse_location(url)
        self.driver.clone(dest_pool, dest_image, pool, image, snapshot)
        return True

    def _remove_image(self, context, image_id, image_meta, path,
                      user_id=None, project_id=None, location=None,
                      **kwargs):
        if not self._can_handle_image(context, image_meta, location, **kwargs):
            return False

        pool, image = kwargs['backend_location']
        self.driver.remove(image)
        return True

    def _move_image(self, context, image_id, image_meta, src_path, dst_path,
                    user_id=None, project_id=None, location=None,
                    **kwargs):
        if not self._can_handle_image(context, image_meta, location, **kwargs):
            return False

        src_pool, src_image = kwargs['backend_location']
        dest_image = kwargs.get('backend_dest')
        self.driver.rename(src_image, dest_image)
        return True

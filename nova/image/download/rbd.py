# Copyright 2013 Red Hat, Inc.
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

from oslo_config import cfg
from oslo_log import log as logging

from nova import exception
from nova.i18n import _, _LI
import nova.image.download.base as xfer_base
from nova.virt.libvirt import imagebackend

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

class RBDTransfer(xfer_base.TransferBase):

    def download(self, context, url_parts, dst_file, metadata, **kwargs):
        Rbd = imagebackend.Rbd(path = url_parts.path)
        Rbd.export_image(url_parts, dst_file)

def get_download_handler(**kwargs):
    return RBDTransfer()


def get_schemes():
    return ['rbd']

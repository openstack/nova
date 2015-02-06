# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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


from oslo_utils import importutils

from nova.i18n import _LE
from nova.openstack.common import log as logging
from nova.volume.encryptors import nop


LOG = logging.getLogger(__name__)


def get_volume_encryptor(connection_info, **kwargs):
    """Creates a VolumeEncryptor used to encrypt the specified volume.

    :param: the connection information used to attach the volume
    :returns VolumeEncryptor: the VolumeEncryptor for the volume
    """
    encryptor = nop.NoOpEncryptor(connection_info, **kwargs)

    location = kwargs.get('control_location', None)
    if location and location.lower() == 'front-end':  # case insensitive
        provider = kwargs.get('provider')

        try:
            encryptor = importutils.import_object(provider, connection_info,
                                                  **kwargs)
        except Exception as e:
            LOG.error(_LE("Error instantiating %(provider)s: %(exception)s"),
                      {'provider': provider, 'exception': e})
            raise

    return encryptor


def get_encryption_metadata(context, volume_api, volume_id, connection_info):
    metadata = {}
    if ('data' in connection_info and
            connection_info['data'].get('encrypted', False)):
        try:
            metadata = volume_api.get_volume_encryption_metadata(context,
                                                                 volume_id)
        except Exception as e:
            LOG.error(_LE("Failed to retrieve encryption metadata for "
                          "volume %(volume_id)s: %(exception)s"),
                      {'volume_id': volume_id, 'exception': e})
            raise

    return metadata

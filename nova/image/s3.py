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

"""Proxy AMI-related calls from cloud controller to objectstore service."""

import base64
import binascii
import os
import shutil
import tarfile
import tempfile

import boto.s3.connection
import eventlet
from lxml import etree
from oslo.config import cfg
from oslo_concurrency import processutils

from nova.api.ec2 import ec2utils
import nova.cert.rpcapi
from nova.compute import arch
from nova import exception
from nova.i18n import _, _LE, _LI
from nova.image import glance
from nova.openstack.common import log as logging
from nova import utils


LOG = logging.getLogger(__name__)

s3_opts = [
    cfg.StrOpt('image_decryption_dir',
               default='/tmp',
               help='Parent directory for tempdir used for image decryption'),
    cfg.StrOpt('s3_host',
               default='$my_ip',
               help='Hostname or IP for OpenStack to use when accessing '
                    'the S3 api'),
    cfg.IntOpt('s3_port',
               default=3333,
               help='Port used when accessing the S3 api'),
    cfg.StrOpt('s3_access_key',
               default='notchecked',
               help='Access key to use for S3 server for images'),
    cfg.StrOpt('s3_secret_key',
               default='notchecked',
               help='Secret key to use for S3 server for images'),
    cfg.BoolOpt('s3_use_ssl',
               default=False,
               help='Whether to use SSL when talking to S3'),
    cfg.BoolOpt('s3_affix_tenant',
               default=False,
               help='Whether to affix the tenant id to the access key '
                    'when downloading from S3'),
    ]

CONF = cfg.CONF
CONF.register_opts(s3_opts)
CONF.import_opt('my_ip', 'nova.netconf')


class S3ImageService(object):
    """Wraps an existing image service to support s3 based register."""
    # translate our internal state to states valid by the EC2 API documentation
    image_state_map = {'downloading': 'pending',
                       'failed_download': 'failed',
                       'decrypting': 'pending',
                       'failed_decrypt': 'failed',
                       'untarring': 'pending',
                       'failed_untar': 'failed',
                       'uploading': 'pending',
                       'failed_upload': 'failed',
                       'available': 'available'}

    def __init__(self, service=None, *args, **kwargs):
        self.cert_rpcapi = nova.cert.rpcapi.CertAPI()
        self.service = service or glance.get_default_image_service()
        self.service.__init__(*args, **kwargs)

    def _translate_uuids_to_ids(self, context, images):
        return [self._translate_uuid_to_id(context, img) for img in images]

    def _translate_uuid_to_id(self, context, image):
        image_copy = image.copy()

        try:
            image_uuid = image_copy['id']
        except KeyError:
            pass
        else:
            image_copy['id'] = ec2utils.glance_id_to_id(context, image_uuid)

        for prop in ['kernel_id', 'ramdisk_id']:
            try:
                image_uuid = image_copy['properties'][prop]
            except (KeyError, ValueError):
                pass
            else:
                image_id = ec2utils.glance_id_to_id(context, image_uuid)
                image_copy['properties'][prop] = image_id

        try:
            image_copy['properties']['image_state'] = self.image_state_map[
                image['properties']['image_state']]
        except (KeyError, ValueError):
            pass

        return image_copy

    def _translate_id_to_uuid(self, context, image):
        image_copy = image.copy()

        try:
            image_id = image_copy['id']
        except KeyError:
            pass
        else:
            image_copy['id'] = ec2utils.id_to_glance_id(context, image_id)

        for prop in ['kernel_id', 'ramdisk_id']:
            try:
                image_id = image_copy['properties'][prop]
            except (KeyError, ValueError):
                pass
            else:
                image_uuid = ec2utils.id_to_glance_id(context, image_id)
                image_copy['properties'][prop] = image_uuid

        return image_copy

    def create(self, context, metadata, data=None):
        """Create an image.

        metadata['properties'] should contain image_location.

        """
        image = self._s3_create(context, metadata)
        return image

    def delete(self, context, image_id):
        image_uuid = ec2utils.id_to_glance_id(context, image_id)
        self.service.delete(context, image_uuid)

    def update(self, context, image_id, metadata, data=None):
        image_uuid = ec2utils.id_to_glance_id(context, image_id)
        metadata = self._translate_id_to_uuid(context, metadata)
        image = self.service.update(context, image_uuid, metadata, data)
        return self._translate_uuid_to_id(context, image)

    def detail(self, context, **kwargs):
        # NOTE(bcwaldon): sort asc to make sure we assign lower ids
        # to older images
        kwargs.setdefault('sort_dir', 'asc')
        images = self.service.detail(context, **kwargs)
        return self._translate_uuids_to_ids(context, images)

    def show(self, context, image_id):
        image_uuid = ec2utils.id_to_glance_id(context, image_id)
        image = self.service.show(context, image_uuid)
        return self._translate_uuid_to_id(context, image)

    @staticmethod
    def _conn(context):
        # NOTE(vish): access and secret keys for s3 server are not
        #             checked in nova-objectstore
        access = CONF.s3_access_key
        if CONF.s3_affix_tenant:
            access = '%s:%s' % (access, context.project_id)
        secret = CONF.s3_secret_key
        calling = boto.s3.connection.OrdinaryCallingFormat()
        return boto.s3.connection.S3Connection(aws_access_key_id=access,
                                               aws_secret_access_key=secret,
                                               is_secure=CONF.s3_use_ssl,
                                               calling_format=calling,
                                               port=CONF.s3_port,
                                               host=CONF.s3_host)

    @staticmethod
    def _download_file(bucket, filename, local_dir):
        key = bucket.get_key(filename)
        local_filename = os.path.join(local_dir, os.path.basename(filename))
        key.get_contents_to_filename(local_filename)
        return local_filename

    def _s3_parse_manifest(self, context, metadata, manifest):
        manifest = etree.fromstring(manifest)
        image_format = 'ami'

        try:
            kernel_id = manifest.find('machine_configuration/kernel_id').text
            if kernel_id == 'true':
                image_format = 'aki'
                kernel_id = None
        except Exception:
            kernel_id = None

        try:
            ramdisk_id = manifest.find('machine_configuration/ramdisk_id').text
            if ramdisk_id == 'true':
                image_format = 'ari'
                ramdisk_id = None
        except Exception:
            ramdisk_id = None

        try:
            guestarch = manifest.find(
                'machine_configuration/architecture').text
        except Exception:
            guestarch = arch.X86_64

        if not arch.is_valid(guestarch):
            raise exception.InvalidArchitectureName(arch=guestarch)

        # NOTE(yamahata):
        # EC2 ec2-budlne-image --block-device-mapping accepts
        # <virtual name>=<device name> where
        # virtual name = {ami, root, swap, ephemeral<N>}
        #                where N is no negative integer
        # device name = the device name seen by guest kernel.
        # They are converted into
        # block_device_mapping/mapping/{virtual, device}
        #
        # Do NOT confuse this with ec2-register's block device mapping
        # argument.
        mappings = []
        try:
            block_device_mapping = manifest.findall('machine_configuration/'
                                                    'block_device_mapping/'
                                                    'mapping')
            for bdm in block_device_mapping:
                mappings.append({'virtual': bdm.find('virtual').text,
                                 'device': bdm.find('device').text})
        except Exception:
            mappings = []

        properties = metadata['properties']
        properties['architecture'] = guestarch

        def _translate_dependent_image_id(image_key, image_id):
            image_uuid = ec2utils.ec2_id_to_glance_id(context, image_id)
            properties[image_key] = image_uuid

        if kernel_id:
            _translate_dependent_image_id('kernel_id', kernel_id)

        if ramdisk_id:
            _translate_dependent_image_id('ramdisk_id', ramdisk_id)

        if mappings:
            properties['mappings'] = mappings

        metadata.update({'disk_format': image_format,
                         'container_format': image_format,
                         'status': 'queued',
                         'is_public': False,
                         'properties': properties})
        metadata['properties']['image_state'] = 'pending'

        # TODO(bcwaldon): right now, this removes user-defined ids.
        # We need to re-enable this.
        metadata.pop('id', None)

        image = self.service.create(context, metadata)

        # extract the new uuid and generate an int id to present back to user
        image_uuid = image['id']
        image['id'] = ec2utils.glance_id_to_id(context, image_uuid)

        # return image_uuid so the caller can still make use of image_service
        return manifest, image, image_uuid

    def _s3_create(self, context, metadata):
        """Gets a manifest from s3 and makes an image."""
        image_path = tempfile.mkdtemp(dir=CONF.image_decryption_dir)

        image_location = metadata['properties']['image_location'].lstrip('/')
        bucket_name = image_location.split('/')[0]
        manifest_path = image_location[len(bucket_name) + 1:]
        bucket = self._conn(context).get_bucket(bucket_name)
        key = bucket.get_key(manifest_path)
        manifest = key.get_contents_as_string()

        manifest, image, image_uuid = self._s3_parse_manifest(context,
                                                              metadata,
                                                              manifest)

        def delayed_create():
            """This handles the fetching and decrypting of the part files."""
            context.update_store()
            log_vars = {'image_location': image_location,
                        'image_path': image_path}

            def _update_image_state(context, image_uuid, image_state):
                metadata = {'properties': {'image_state': image_state}}
                self.service.update(context, image_uuid, metadata,
                                    purge_props=False)

            def _update_image_data(context, image_uuid, image_data):
                metadata = {}
                self.service.update(context, image_uuid, metadata, image_data,
                                    purge_props=False)

            try:
                _update_image_state(context, image_uuid, 'downloading')

                try:
                    parts = []
                    elements = manifest.find('image').getiterator('filename')
                    for fn_element in elements:
                        part = self._download_file(bucket,
                                                   fn_element.text,
                                                   image_path)
                        parts.append(part)

                    # NOTE(vish): this may be suboptimal, should we use cat?
                    enc_filename = os.path.join(image_path, 'image.encrypted')
                    with open(enc_filename, 'w') as combined:
                        for filename in parts:
                            with open(filename) as part:
                                shutil.copyfileobj(part, combined)

                except Exception:
                    LOG.exception(_LE("Failed to download %(image_location)s "
                                      "to %(image_path)s"), log_vars)
                    _update_image_state(context, image_uuid, 'failed_download')
                    return

                _update_image_state(context, image_uuid, 'decrypting')

                try:
                    hex_key = manifest.find('image/ec2_encrypted_key').text
                    encrypted_key = binascii.a2b_hex(hex_key)
                    hex_iv = manifest.find('image/ec2_encrypted_iv').text
                    encrypted_iv = binascii.a2b_hex(hex_iv)

                    dec_filename = os.path.join(image_path, 'image.tar.gz')
                    self._decrypt_image(context, enc_filename, encrypted_key,
                                        encrypted_iv, dec_filename)
                except Exception:
                    LOG.exception(_LE("Failed to decrypt %(image_location)s "
                                      "to %(image_path)s"), log_vars)
                    _update_image_state(context, image_uuid, 'failed_decrypt')
                    return

                _update_image_state(context, image_uuid, 'untarring')

                try:
                    unz_filename = self._untarzip_image(image_path,
                                                        dec_filename)
                except Exception:
                    LOG.exception(_LE("Failed to untar %(image_location)s "
                                      "to %(image_path)s"), log_vars)
                    _update_image_state(context, image_uuid, 'failed_untar')
                    return

                _update_image_state(context, image_uuid, 'uploading')
                try:
                    with open(unz_filename) as image_file:
                        _update_image_data(context, image_uuid, image_file)
                except Exception:
                    LOG.exception(_LE("Failed to upload %(image_location)s "
                                      "to %(image_path)s"), log_vars)
                    _update_image_state(context, image_uuid, 'failed_upload')
                    return

                metadata = {'status': 'active',
                            'properties': {'image_state': 'available'}}
                self.service.update(context, image_uuid, metadata,
                        purge_props=False)

                shutil.rmtree(image_path)
            except exception.ImageNotFound:
                LOG.info(_LI("Image %s was deleted underneath us"), image_uuid)
                return

        eventlet.spawn_n(delayed_create)

        return image

    def _decrypt_image(self, context, encrypted_filename, encrypted_key,
                       encrypted_iv, decrypted_filename):
        elevated = context.elevated()
        try:
            key = self.cert_rpcapi.decrypt_text(elevated,
                    project_id=context.project_id,
                    text=base64.b64encode(encrypted_key))
        except Exception as exc:
            msg = _('Failed to decrypt private key: %s') % exc
            raise exception.NovaException(msg)
        try:
            iv = self.cert_rpcapi.decrypt_text(elevated,
                    project_id=context.project_id,
                    text=base64.b64encode(encrypted_iv))
        except Exception as exc:
            raise exception.NovaException(_('Failed to decrypt initialization '
                                    'vector: %s') % exc)

        try:
            utils.execute('openssl', 'enc',
                          '-d', '-aes-128-cbc',
                          '-in', '%s' % (encrypted_filename,),
                          '-K', '%s' % (key,),
                          '-iv', '%s' % (iv,),
                          '-out', '%s' % (decrypted_filename,))
        except processutils.ProcessExecutionError as exc:
            raise exception.NovaException(_('Failed to decrypt image file '
                                    '%(image_file)s: %(err)s') %
                                    {'image_file': encrypted_filename,
                                     'err': exc.stdout})

    @staticmethod
    def _test_for_malicious_tarball(path, filename):
        """Raises exception if extracting tarball would escape extract path."""
        tar_file = tarfile.open(filename, 'r|gz')
        for n in tar_file.getnames():
            if not os.path.abspath(os.path.join(path, n)).startswith(path):
                tar_file.close()
                raise exception.NovaException(_('Unsafe filenames in image'))
        tar_file.close()

    @staticmethod
    def _untarzip_image(path, filename):
        S3ImageService._test_for_malicious_tarball(path, filename)
        tar_file = tarfile.open(filename, 'r|gz')
        tar_file.extractall(path)
        image_file = tar_file.getnames()[0]
        tar_file.close()
        return os.path.join(path, image_file)

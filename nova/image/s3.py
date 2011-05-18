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

"""Proxy AMI-related calls from cloud controller to objectstore service."""

import binascii
import os
import shutil
import tarfile
import tempfile
from xml.etree import ElementTree

import boto.s3.connection
import eventlet

from nova import crypto
from nova import exception
from nova import flags
from nova import utils
from nova.auth import manager
from nova.image import service
from nova.api.ec2 import ec2utils


FLAGS = flags.FLAGS
flags.DEFINE_string('image_decryption_dir', '/tmp',
                    'parent dir for tempdir used for image decryption')


class S3ImageService(service.BaseImageService):
    """Wraps an existing image service to support s3 based register."""

    def __init__(self, service=None, *args, **kwargs):
        self.service = service or utils.get_default_image_service()
        self.service.__init__(*args, **kwargs)

    def create(self, context, metadata, data=None):
        """Create an image.

        metadata['properties'] should contain image_location.

        """
        image = self._s3_create(context, metadata)
        return image

    def delete(self, context, image_id):
        self.service.delete(context, image_id)

    def update(self, context, image_id, metadata, data=None):
        image = self.service.update(context, image_id, metadata, data)
        return image

    def index(self, context):
        return self.service.index(context)

    def detail(self, context):
        return self.service.detail(context)

    def show(self, context, image_id):
        return self.service.show(context, image_id)

    def show_by_name(self, context, name):
        return self.service.show_by_name(context, name)

    @staticmethod
    def _conn(context):
        # TODO(vish): is there a better way to get creds to sign
        #             for the user?
        access = manager.AuthManager().get_access_key(context.user,
                                                      context.project)
        secret = str(context.user.secret)
        calling = boto.s3.connection.OrdinaryCallingFormat()
        return boto.s3.connection.S3Connection(aws_access_key_id=access,
                                               aws_secret_access_key=secret,
                                               is_secure=False,
                                               calling_format=calling,
                                               port=FLAGS.s3_port,
                                               host=FLAGS.s3_host)

    @staticmethod
    def _download_file(bucket, filename, local_dir):
        key = bucket.get_key(filename)
        local_filename = os.path.join(local_dir, filename)
        key.get_contents_to_filename(local_filename)
        return local_filename

    def _s3_create(self, context, metadata):
        """Gets a manifext from s3 and makes an image."""

        image_path = tempfile.mkdtemp(dir=FLAGS.image_decryption_dir)

        image_location = metadata['properties']['image_location']
        bucket_name = image_location.split('/')[0]
        manifest_path = image_location[len(bucket_name) + 1:]
        bucket = self._conn(context).get_bucket(bucket_name)
        key = bucket.get_key(manifest_path)
        manifest = key.get_contents_as_string()

        manifest = ElementTree.fromstring(manifest)
        image_format = 'ami'
        image_type = 'machine'

        try:
            kernel_id = manifest.find('machine_configuration/kernel_id').text
            if kernel_id == 'true':
                image_format = 'aki'
                image_type = 'kernel'
                kernel_id = None
        except Exception:
            kernel_id = None

        try:
            ramdisk_id = manifest.find('machine_configuration/ramdisk_id').text
            if ramdisk_id == 'true':
                image_format = 'ari'
                image_type = 'ramdisk'
                ramdisk_id = None
        except Exception:
            ramdisk_id = None

        try:
            arch = manifest.find('machine_configuration/architecture').text
        except Exception:
            arch = 'x86_64'

        properties = metadata['properties']
        properties['project_id'] = context.project_id
        properties['architecture'] = arch

        if kernel_id:
            properties['kernel_id'] = ec2utils.ec2_id_to_id(kernel_id)

        if ramdisk_id:
            properties['ramdisk_id'] = ec2utils.ec2_id_to_id(ramdisk_id)

        metadata.update({'disk_format': image_format,
                         'container_format': image_format,
                         'status': 'queued',
                         'is_public': True,
                         'properties': properties})
        metadata['properties']['image_state'] = 'pending'
        image = self.service.create(context, metadata)
        image_id = image['id']

        def delayed_create():
            """This handles the fetching and decrypting of the part files."""
            parts = []
            for fn_element in manifest.find('image').getiterator('filename'):
                part = self._download_file(bucket, fn_element.text, image_path)
                parts.append(part)

            # NOTE(vish): this may be suboptimal, should we use cat?
            encrypted_filename = os.path.join(image_path, 'image.encrypted')
            with open(encrypted_filename, 'w') as combined:
                for filename in parts:
                    with open(filename) as part:
                        shutil.copyfileobj(part, combined)

            metadata['properties']['image_state'] = 'decrypting'
            self.service.update(context, image_id, metadata)

            hex_key = manifest.find('image/ec2_encrypted_key').text
            encrypted_key = binascii.a2b_hex(hex_key)
            hex_iv = manifest.find('image/ec2_encrypted_iv').text
            encrypted_iv = binascii.a2b_hex(hex_iv)

            # FIXME(vish): grab key from common service so this can run on
            #              any host.
            cloud_pk = crypto.key_path(context.project_id)

            decrypted_filename = os.path.join(image_path, 'image.tar.gz')
            self._decrypt_image(encrypted_filename, encrypted_key,
                                encrypted_iv, cloud_pk, decrypted_filename)

            metadata['properties']['image_state'] = 'untarring'
            self.service.update(context, image_id, metadata)

            unz_filename = self._untarzip_image(image_path, decrypted_filename)

            metadata['properties']['image_state'] = 'uploading'
            with open(unz_filename) as image_file:
                self.service.update(context, image_id, metadata, image_file)
            metadata['properties']['image_state'] = 'available'
            self.service.update(context, image_id, metadata)

            shutil.rmtree(image_path)

        eventlet.spawn_n(delayed_create)

        return image

    @staticmethod
    def _decrypt_image(encrypted_filename, encrypted_key, encrypted_iv,
                       cloud_private_key, decrypted_filename):
        key, err = utils.execute('openssl',
                                 'rsautl',
                                 '-decrypt',
                                 '-inkey', '%s' % cloud_private_key,
                                 process_input=encrypted_key,
                                 check_exit_code=False)
        if err:
            raise exception.Error(_('Failed to decrypt private key: %s')
                                  % err)
        iv, err = utils.execute('openssl',
                                'rsautl',
                                '-decrypt',
                                '-inkey', '%s' % cloud_private_key,
                                process_input=encrypted_iv,
                                check_exit_code=False)
        if err:
            raise exception.Error(_('Failed to decrypt initialization '
                                    'vector: %s') % err)

        _out, err = utils.execute('openssl', 'enc',
                                  '-d', '-aes-128-cbc',
                                  '-in', '%s' % (encrypted_filename,),
                                  '-K', '%s' % (key,),
                                  '-iv', '%s' % (iv,),
                                  '-out', '%s' % (decrypted_filename,),
                                  check_exit_code=False)
        if err:
            raise exception.Error(_('Failed to decrypt image file '
                                    '%(image_file)s: %(err)s') %
                                    {'image_file': encrypted_filename,
                                     'err': err})

    @staticmethod
    def _untarzip_image(path, filename):
        tar_file = tarfile.open(filename, 'r|gz')
        tar_file.extractall(path)
        image_file = tar_file.getnames()[0]
        tar_file.close()
        return os.path.join(path, image_file)

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration. 
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
Take uploaded bucket contents and register them as disk images (AMIs).
Requires decryption using keys in the manifest.
"""

# TODO(jesse): Got these from Euca2ools, will need to revisit them

import binascii
import glob
import json
import os
import shutil
import tarfile
import tempfile
from xml.etree import ElementTree

from nova import exception
from nova import flags
from nova import utils
from nova.objectstore import bucket


FLAGS = flags.FLAGS
flags.DEFINE_string('images_path', utils.abspath('../images'),
                        'path to decrypted images')

class Image(object):
    def __init__(self, image_id):
        self.image_id = image_id
        self.path = os.path.abspath(os.path.join(FLAGS.images_path, image_id))
        if not self.path.startswith(os.path.abspath(FLAGS.images_path)) or \
           not os.path.isdir(self.path):
             raise exception.NotFound

    @property
    def image_path(self):
        return os.path.join(self.path, 'image')

    def delete(self):
        for fn in ['info.json', 'image']:
            try:
                os.unlink(os.path.join(self.path, fn))
            except:
                pass
        try:
            os.rmdir(self.path)
        except:
            pass

    def is_authorized(self, context):
        try:
            return self.metadata['isPublic'] or context.user.is_admin() or self.metadata['imageOwnerId'] == context.project.id
        except:
            return False

    def set_public(self, state):
        md = self.metadata
        md['isPublic'] = state
        with open(os.path.join(self.path, 'info.json'), 'w') as f:
            json.dump(md, f)

    @staticmethod
    def all():
        images = []
        for fn in glob.glob("%s/*/info.json" % FLAGS.images_path):
            try:
                image_id = fn.split('/')[-2]
                images.append(Image(image_id))
            except:
                pass
        return images

    @property
    def owner_id(self):
        return self.metadata['imageOwnerId']

    @property
    def metadata(self):
        with open(os.path.join(self.path, 'info.json')) as f:
            return json.load(f)

    @staticmethod
    def create(image_id, image_location, context):
        image_path = os.path.join(FLAGS.images_path, image_id)
        os.makedirs(image_path)

        bucket_name = image_location.split("/")[0]
        manifest_path = image_location[len(bucket_name)+1:]
        bucket_object = bucket.Bucket(bucket_name)

        manifest = ElementTree.fromstring(bucket_object[manifest_path].read())
        image_type = 'machine'

        try:
            kernel_id = manifest.find("machine_configuration/kernel_id").text
            if kernel_id == 'true':
                image_type = 'kernel'
        except:
            pass

        try:
            ramdisk_id = manifest.find("machine_configuration/ramdisk_id").text
            if ramdisk_id == 'true':
                image_type = 'ramdisk'
        except:
            pass

        info = {
            'imageId': image_id,
            'imageLocation': image_location,
            'imageOwnerId': context.project.id,
            'isPublic': False, # FIXME: grab public from manifest
            'architecture': 'x86_64', # FIXME: grab architecture from manifest
            'type' : image_type
        }

        def write_state(state):
            info['imageState'] = state
            with open(os.path.join(image_path, 'info.json'), "w") as f:
                json.dump(info, f)

        write_state('pending')

        encrypted_filename = os.path.join(image_path, 'image.encrypted')
        with open(encrypted_filename, 'w') as f:
            for filename in manifest.find("image").getiterator("filename"):
                shutil.copyfileobj(bucket_object[filename.text].file, f)

        write_state('decrypting')

        # FIXME: grab kernelId and ramdiskId from bundle manifest
        encrypted_key = binascii.a2b_hex(manifest.find("image/ec2_encrypted_key").text)
        encrypted_iv = binascii.a2b_hex(manifest.find("image/ec2_encrypted_iv").text)
        cloud_private_key = os.path.join(FLAGS.ca_path, "private/cakey.pem")

        decrypted_filename = os.path.join(image_path, 'image.tar.gz')
        Image.decrypt_image(encrypted_filename, encrypted_key, encrypted_iv, cloud_private_key, decrypted_filename)

        write_state('untarring')

        image_file = Image.untarzip_image(image_path, decrypted_filename)
        shutil.move(os.path.join(image_path, image_file), os.path.join(image_path, 'image'))

        write_state('available')
        os.unlink(decrypted_filename)
        os.unlink(encrypted_filename)

    @staticmethod
    def decrypt_image(encrypted_filename, encrypted_key, encrypted_iv, cloud_private_key, decrypted_filename):
        key, err = utils.execute('openssl rsautl -decrypt -inkey %s' % cloud_private_key, encrypted_key)
        if err:
            raise exception.Error("Failed to decrypt private key: %s" % err)
        iv, err = utils.execute('openssl rsautl -decrypt -inkey %s' % cloud_private_key, encrypted_iv)
        if err:
            raise exception.Error("Failed to decrypt initialization vector: %s" % err)
        out, err = utils.execute('openssl enc -d -aes-128-cbc -in %s -K %s -iv %s -out %s' % (encrypted_filename, key, iv, decrypted_filename))
        if err:
            raise exception.Error("Failed to decrypt image file %s : %s" % (encrypted_filename, err))

    @staticmethod
    def untarzip_image(path, filename):
        tar_file = tarfile.open(filename, "r|gz")
        tar_file.extractall(path)
        image_file = tar_file.getnames()[0]
        tar_file.close()
        return image_file

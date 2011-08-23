# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

""" Keypair management extension"""

import os
import shutil
import tempfile

from webob import exc

from nova import crypto
from nova import db
from nova import exception
from nova.api.openstack import extensions


class KeypairController(object):
    """ Keypair API controller for the Openstack API """

    # TODO(ja): both this file and nova.api.ec2.cloud.py have similar logic.
    # move the common keypair logic to nova.compute.API?

    def _gen_key(self):
        """
        Generate a key
        """
        private_key, public_key, fingerprint = crypto.generate_key_pair()
        return {'private_key': private_key,
                'public_key': public_key,
                'fingerprint': fingerprint}

    def create(self, req, body):
        """
        Create or import keypair.

        Sending name will generate a key and return private_key
        and fingerprint.

        You can send a public_key to add an existing ssh key

        params: keypair object with:
            name (required) - string
            public_key (optional) - string
        """

        context = req.environ['nova.context']
        params = body['keypair']
        name = params['name']

        # NOTE(ja): generation is slow, so shortcut invalid name exception
        try:
            db.key_pair_get(context, context.user_id, name)
            raise exception.KeyPairExists(key_name=name)
        except exception.NotFound:
            pass

        keypair = {'user_id': context.user_id,
                   'name': name}

        # import if public_key is sent
        if 'public_key' in params:
            tmpdir = tempfile.mkdtemp()
            fn = os.path.join(tmpdir, 'import.pub')
            with open(fn, 'w') as pub:
                pub.write(params['public_key'])
            fingerprint = crypto.generate_fingerprint(fn)
            shutil.rmtree(tmpdir)
            keypair['public_key'] = params['public_key']
            keypair['fingerprint'] = fingerprint
        else:
            generated_key = self._gen_key()
            keypair['private_key'] = generated_key['private_key']
            keypair['public_key'] = generated_key['public_key']
            keypair['fingerprint'] = generated_key['fingerprint']

        db.key_pair_create(context, keypair)
        return {'keypair': keypair}

    def delete(self, req, id):
        """
        Delete a keypair with a given name
        """
        context = req.environ['nova.context']
        db.key_pair_destroy(context, context.user_id, id)
        return exc.HTTPAccepted()

    def index(self, req):
        """
        List of keypairs for a user
        """
        context = req.environ['nova.context']
        key_pairs = db.key_pair_get_all_by_user(context, context.user_id)
        rval = []
        for key_pair in key_pairs:
            rval.append({'keypair': {
                'name': key_pair['name'],
                'public_key': key_pair['public_key'],
                'fingerprint': key_pair['fingerprint'],
            }})

        return {'keypairs': rval}


class Keypairs(extensions.ExtensionDescriptor):

    def get_name(self):
        return "Keypairs"

    def get_alias(self):
        return "os-keypairs"

    def get_description(self):
        return "Keypair Support"

    def get_namespace(self):
        return \
         "http://docs.openstack.org/ext/keypairs/api/v1.1"

    def get_updated(self):
        return "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
                'os-keypairs',
                KeypairController())

        resources.append(res)
        return resources

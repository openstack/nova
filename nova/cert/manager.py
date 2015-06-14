# Copyright 2012 OpenStack Foundation
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
Cert manager manages x509 certificates.

**Related Flags**

:cert_topic:  What :mod:`rpc` topic to listen to (default: `cert`).
:cert_manager:  The module name of a class derived from
                :class:`manager.Manager` (default:
                :class:`nova.cert.manager.Manager`).
"""

import base64

import oslo_messaging as messaging

from nova import crypto
from nova import manager


class CertManager(manager.Manager):

    target = messaging.Target(version='2.0')

    def __init__(self, *args, **kwargs):
        super(CertManager, self).__init__(service_name='cert',
                                          *args, **kwargs)

    def init_host(self):
        crypto.ensure_ca_filesystem()

    def revoke_certs_by_user(self, context, user_id):
        """Revoke all user certs."""
        return crypto.revoke_certs_by_user(user_id)

    def revoke_certs_by_project(self, context, project_id):
        """Revoke all project certs."""
        return crypto.revoke_certs_by_project(project_id)

    def revoke_certs_by_user_and_project(self, context, user_id, project_id):
        """Revoke certs for user in project."""
        return crypto.revoke_certs_by_user_and_project(user_id, project_id)

    def generate_x509_cert(self, context, user_id, project_id):
        """Generate and sign a cert for user in project."""
        return crypto.generate_x509_cert(user_id, project_id)

    def fetch_ca(self, context, project_id):
        """Get root ca for a project."""
        return crypto.fetch_ca(project_id)

    def fetch_crl(self, context, project_id):
        """Get crl for a project."""
        return crypto.fetch_crl(project_id)

    def decrypt_text(self, context, project_id, text):
        """Decrypt base64 encoded text using the projects private key."""
        return crypto.decrypt_text(project_id, base64.b64decode(text))

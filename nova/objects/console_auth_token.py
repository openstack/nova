#    Copyright 2015 Intel Corp
#    Copyright 2016 Hewlett Packard Enterprise Development Company LP
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

from oslo_db.exception import DBDuplicateEntry
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils

import nova.conf
from nova import db
from nova import exception
from nova.i18n import _
from nova.objects import base
from nova.objects import fields
from nova import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class ConsoleAuthToken(base.NovaTimestampObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'console_type': fields.StringField(nullable=False),
        'host': fields.StringField(nullable=False),
        'port': fields.IntegerField(nullable=False),
        'internal_access_path': fields.StringField(nullable=True),
        'instance_uuid': fields.UUIDField(nullable=False),
        'access_url_base': fields.StringField(nullable=True),
        # NOTE(PaulMurray): The unhashed token field is not stored in the
        # database. A hash of the token is stored instead and is not a
        # field on the object.
        'token': fields.StringField(nullable=False),
    }

    @property
    def access_url(self):
        """The access url with token parameter.

        :returns: the access url with credential parameters

        access_url_base is the base url used to access a console.
        Adding the unhashed token as a parameter in a query string makes it
        specific to this authorization.
        """
        if self.obj_attr_is_set('id'):
            return '%s?token=%s' % (self.access_url_base, self.token)

    @staticmethod
    def _from_db_object(context, obj, db_obj):
        # NOTE(PaulMurray): token is not stored in the database but
        # this function assumes it is in db_obj. The unhashed token
        # field is populated in the authorize method after the token
        # authorization is created in the database.
        for field in obj.fields:
            setattr(obj, field, db_obj[field])
        obj._context = context
        obj.obj_reset_changes()
        return obj

    @base.remotable
    def authorize(self, ttl):
        """Authorise the console token and store in the database.

        :param ttl: time to live in seconds
        :returns: an authorized token

        The expires value is set for ttl seconds in the future and the token
        hash is stored in the database. This function can only succeed if the
        token is unique and the object has not already been stored.
        """
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(
                action='authorize',
                reason=_('must be a new object to authorize'))

        token = uuidutils.generate_uuid()
        token_hash = utils.get_sha256_str(token)
        expires = timeutils.utcnow_ts() + ttl

        updates = self.obj_get_changes()
        # NOTE(melwitt): token could be in the updates if authorize() has been
        # called twice on the same object. 'token' is not a database column and
        # should not be included in the call to create the database record.
        if 'token' in updates:
            del updates['token']
        updates['token_hash'] = token_hash
        updates['expires'] = expires

        try:
            db_obj = db.console_auth_token_create(self._context, updates)
            db_obj['token'] = token
            self._from_db_object(self._context, self, db_obj)
        except DBDuplicateEntry:
            # NOTE(PaulMurray) we are generating the token above so this
            # should almost never happen - but technically its possible
            raise exception.TokenInUse()

        LOG.debug("Authorized token with expiry %(expires)s for console "
                  "connection %(console)s",
                  {'expires': expires,
                   'console': strutils.mask_password(self)})
        return token

    @base.remotable_classmethod
    def validate(cls, context, token):
        """Validate the token.

        :param context: the context
        :param token: the token for the authorization
        :returns: The ConsoleAuthToken object if valid

        The token is valid if the token is in the database and the expires
        time has not passed.
        """
        token_hash = utils.get_sha256_str(token)
        db_obj = db.console_auth_token_get_valid(context, token_hash)

        if db_obj is not None:
            db_obj['token'] = token
            obj = cls._from_db_object(context, cls(), db_obj)
            LOG.debug("Validated token - console connection is "
                      "%(console)s",
                      {'console': strutils.mask_password(obj)})
            return obj
        else:
            LOG.debug("Token validation failed")
            raise exception.InvalidToken(token='***')

    @base.remotable_classmethod
    def clean_console_auths_for_instance(cls, context, instance_uuid):
        """Remove all console authorizations for the instance.

        :param context: the context
        :param instance_uuid: the instance to be cleaned

        All authorizations related to the specified instance will be
        removed from the database.
        """
        db.console_auth_token_destroy_all_by_instance(context, instance_uuid)

    @base.remotable_classmethod
    def clean_expired_console_auths_for_host(cls, context, host):
        """Remove all expired console authorizations for the host.

        :param context: the context
        :param host: the host name

        All expired authorizations related to the specified host
        will be removed. Tokens that have not expired will
        remain.
        """
        db.console_auth_token_destroy_expired_by_host(context, host)

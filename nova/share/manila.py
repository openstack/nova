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
Handles all requests relating to shares + manila.
"""

from dataclasses import dataclass
import functools
from typing import Optional

from openstack import exceptions as sdk_exc
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
MIN_SHARE_FILE_SYSTEM_MICROVERSION = "2.82"


def _manilaclient(context, admin=False):
    """Constructs a manila client object for making API requests.

    :return: An openstack.proxy.Proxy object for the specified service_type.
    :raise: ConfGroupForServiceTypeNotFound If no conf group name could be
            found for the specified service_type.
    :raise: ServiceUnavailable if the service is down
    """

    return utils.get_sdk_adapter(
        "shared-file-system",
        admin=admin,
        check_service=True,
        context=context,
        shared_file_system_api_version=MIN_SHARE_FILE_SYSTEM_MICROVERSION,
        global_request_id=context.global_id
    )


@dataclass(frozen=True)
class Share():
    id: str
    size: int
    availability_zone: Optional[str]
    created_at: str
    status: str
    name: Optional[str]
    description: Optional[str]
    project_id: str
    snapshot_id: Optional[str]
    share_network_id: Optional[str]
    share_proto: str
    export_location: str
    metadata: dict
    share_type: Optional[str]
    is_public: bool

    @classmethod
    def from_manila_share(cls, manila_share, export_location):
        return cls(
            id=manila_share.id,
            size=manila_share.size,
            availability_zone=manila_share.availability_zone,
            created_at=manila_share.created_at,
            status=manila_share.status,
            name=manila_share.name,
            description=manila_share.description,
            project_id=manila_share.project_id,
            snapshot_id=manila_share.snapshot_id,
            share_network_id=manila_share.share_network_id,
            share_proto=manila_share.share_protocol,
            export_location=export_location,
            metadata=manila_share.metadata,
            share_type=manila_share.share_type,
            is_public=manila_share.is_public,
        )


@dataclass(frozen=True)
class Access():
    id: str
    access_level: str
    state: str
    access_type: str
    access_to: str
    access_key: Optional[str]

    @classmethod
    def from_manila_access(cls, manila_access):
        return cls(
            id=manila_access.id,
            access_level=manila_access.access_level,
            state=manila_access.state,
            access_type=manila_access.access_type,
            access_to=manila_access.access_to,
            access_key= getattr(manila_access, 'access_key', None)
        )

    @classmethod
    def from_dict(cls, manila_access):
        return cls(
            id=manila_access['id'],
            access_level=manila_access['access_level'],
            state=manila_access['state'],
            access_type=manila_access['access_type'],
            access_to=manila_access['access_to'],
            access_key=manila_access['access_key'],
        )


def translate_sdk_exception(method):
    """Transforms a manila exception but keeps its traceback intact."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            res = method(self, *args, **kwargs)
        except (exception.ServiceUnavailable,
                exception.ConfGroupForServiceTypeNotFound) as exc:
            raise exception.ManilaConnectionFailed(reason=str(exc)) from exc
        except (sdk_exc.BadRequestException) as exc:
            raise exception.InvalidInput(reason=str(exc)) from exc
        except (sdk_exc.ForbiddenException) as exc:
            raise exception.Forbidden(str(exc)) from exc
        return res
    return wrapper


def translate_share_exception(method):
    """Transforms the exception for the share but keeps its traceback intact.
    """

    def wrapper(self, *args, **kwargs):
        try:
            res = method(self, *args, **kwargs)
        except (sdk_exc.ResourceNotFound) as exc:
            raise exception.ShareNotFound(
                share_id=args[1], reason=exc) from exc
        except (sdk_exc.BadRequestException) as exc:
            raise exception.ShareNotFound(
                share_id=args[1], reason=exc) from exc
        return res
    return translate_sdk_exception(wrapper)


def translate_allow_exception(method):
    """Transforms the exception for allow but keeps its traceback intact.
    """

    def wrapper(self, *args, **kwargs):
        try:
            res = method(self, *args, **kwargs)
        except (sdk_exc.BadRequestException) as exc:
            raise exception.ShareAccessGrantError(
                share_id=args[1], reason=exc) from exc
        except (sdk_exc.ResourceNotFound) as exc:
            raise exception.ShareNotFound(
                share_id=args[1], reason=exc) from exc
        return res
    return translate_sdk_exception(wrapper)


def translate_deny_exception(method):
    """Transforms the exception for deny but keeps its traceback intact.
    """

    def wrapper(self, *args, **kwargs):
        try:
            res = method(self, *args, **kwargs)
        except (sdk_exc.BadRequestException) as exc:
            raise exception.ShareAccessRemovalError(
                share_id=args[1], reason=exc) from exc
        except (sdk_exc.ResourceNotFound) as exc:
            raise exception.ShareNotFound(
                share_id=args[1], reason=exc) from exc
        return res
    return translate_sdk_exception(wrapper)


class API(object):
    """API for interacting with the share manager."""

    @translate_share_exception
    def get(self, context, share_id):
        """Get the details about a share given its ID.

        :param share_id: the id of the share to get
        :raises: ShareNotFound if the share_id specified is not available.
        :returns: Share object.
        """

        def filter_export_locations(export_locations):
            # Return the preferred path otherwise choose the first one
            paths = []
            try:
                for export_location in export_locations:
                    if export_location.is_preferred:
                        return export_location.path
                    else:
                        paths.append(export_location.path)
                return paths[0]
            except (IndexError, NameError):
                return None

        client = _manilaclient(context, admin=False)
        LOG.debug("Get share id:'%s' data from manila", share_id)
        share = client.get_share(share_id)
        export_locations = client.export_locations(share.id)
        export_location = filter_export_locations(export_locations)

        return Share.from_manila_share(share, export_location)

    @translate_share_exception
    def get_access(
        self,
        context,
        share_id,
        access_type,
        access_to,
    ):
        """Get share access

        :param share_id: the id of the share to get
        :param access_type: the type of access ("ip", "cert", "user")
        :param access_to: ip:cidr or cert:cn or user:group or user name
        :raises: ShareNotFound if the share_id specified is not available.
        :returns: Access object or None if there is no access granted to this
            share.
        """

        LOG.debug("Get share access id for share id:'%s'",
                  share_id)
        access_list = _manilaclient(
            context, admin=True).access_rules(share_id)

        for access in access_list:
            if (
                access.access_type == access_type and
                access.access_to == access_to
            ):
                return Access.from_manila_access(access)
        return None

    @translate_allow_exception
    def allow(
        self,
        context,
        share_id,
        access_type,
        access_to,
        access_level,
    ):
        """Allow share access

        :param share_id: the id of the share
        :param access_type: the type of access ("ip", "cert", "user")
        :param access_to: ip:cidr or cert:cn or user:group or user name
        :param access_level: "ro" for read only or "rw" for read/write
        :raises: ShareNotFound if the share_id specified is not available.
        :raises: BadRequest if the share already exists.
        :raises: ShareAccessGrantError if the answer from manila allow API is
            not the one expected.
        """

        def check_manila_access_response(access):
            if not (
                isinstance(access, Access) and
                access.access_type == access_type and
                access.access_to == access_to and
                access.access_level == access_level
            ):
                raise exception.ShareAccessGrantError(share_id=share_id)

        LOG.debug("Allow host access to share id:'%s'",
                  share_id)

        access = _manilaclient(context, admin=True).create_access_rule(
            share_id,
            access_type=access_type,
            access_to=access_to,
            access_level=access_level,
            lock_visibility=True,
            lock_deletion=True,
            lock_reason="Lock by nova",
        )

        access = Access.from_manila_access(access)
        check_manila_access_response(access)
        return access

    @translate_deny_exception
    def deny(
        self,
        context,
        share_id,
        access_type,
        access_to,
    ):
        """Deny share access
        :param share_id: the id of the share
        :param access_type: the type of access ("ip", "cert", "user")
        :param access_to: ip:cidr or cert:cn or user:group or user name
        :raises: ShareAccessNotFound if the access_id specified is not
            available.
        :raises: ShareAccessRemovalError if the manila deny API does not
            respond with a status code 202.
        """

        access = self.get_access(
            context,
            share_id,
            access_type,
            access_to,
            )

        if access:
            client = _manilaclient(context, admin=True)
            LOG.debug("Deny host access to share id:'%s'", share_id)
            resp = client.delete_access_rule(
                access.id, share_id, unrestrict=True
            )
            if resp.status_code != 202:
                raise exception.ShareAccessRemovalError(
                    share_id=share_id, reason=resp.reason
                )
        else:
            raise exception.ShareAccessNotFound(share_id=share_id)

    def has_access(self, context, share_id, access_type, access_to):
        """Helper method to check if a policy is applied to a share
        :param context: The request context.
        :param share_id: the id of the share
        :param access_type: the type of access ("ip", "cert", "user")
        :param access_to: ip:cidr or cert:cn or user:group or user name
        :returns: boolean, true means the policy is applied.
        """
        access = self.get_access(
            context,
            share_id,
            access_type,
            access_to
        )
        return access is not None and access.state == 'active'

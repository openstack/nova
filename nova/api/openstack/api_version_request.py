# Copyright 2014 IBM Corp.
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

import re

from nova import exception
from nova.i18n import _

# Define the minimum and maximum version of the API across all of the
# REST API. The format of the version is:
# X.Y where:
#
# - X will only be changed if a significant backwards incompatible API
# change is made which affects the API as whole. That is, something
# that is only very very rarely incremented.
#
# - Y when you make any change to the API. Note that this includes
# semantic changes which may not affect the input or output formats or
# even originate in the API code layer. We are not distinguishing
# between backwards compatible and backwards incompatible changes in
# the versioning system. It must be made clear in the documentation as
# to what is a backwards compatible change and what is a backwards
# incompatible one.

#
# You must update the API version history string below with a one or
# two line description as well as update rest_api_version_history.rst
REST_API_VERSION_HISTORY = """REST API Version History:

    * 2.1 - Initial version. Equivalent to v2.0 code
    * 2.2 - Adds (keypair) type parameter for os-keypairs plugin
            Fixes success status code for create/delete a keypair method
    * 2.3 - Exposes additional os-extended-server-attributes
            Exposes delete_on_termination for os-extended-volumes
    * 2.4 - Exposes reserved field in os-fixed-ips.
    * 2.5 - Allow server search option ip6 for non-admin
    * 2.6 - Consolidate the APIs for getting remote consoles
    * 2.7 - Check flavor type before add tenant access.
    * 2.8 - Add new protocol for VM console (mks)
    * 2.9 - Exposes lock information in server details.
    * 2.10 - Allow admins to query, create and delete keypairs owned by any
             user.
    * 2.11 - Exposes forced_down attribute for os-services
    * 2.12 - Exposes VIF net_id in os-virtual-interfaces
    * 2.13 - Add project id and user id information for os-server-groups API
    * 2.14 - Remove onSharedStorage from evacuate request body and remove
             adminPass from the response body
    * 2.15 - Add soft-affinity and soft-anti-affinity policies
    * 2.16 - Exposes host_status for servers/detail and servers/{server_id}
    * 2.17 - Add trigger_crash_dump to server actions
    * 2.18 - Makes project_id optional in v2.1
    * 2.19 - Allow user to set and get the server description
    * 2.20 - Add attach and detach volume operations for instances in shelved
             and shelved_offloaded state
    * 2.21 - Make os-instance-actions read deleted instances
    * 2.22 - Add API to force live migration to complete
    * 2.23 - Add index/show API for server migrations.
             Also add migration_type for /os-migrations and add ref link for it
             when the migration is an in progress live migration.
    * 2.24 - Add API to cancel a running live migration
    * 2.25 - Make block_migration support 'auto' and remove
             disk_over_commit for os-migrateLive.
    * 2.26 - Adds support of server tags
    * 2.27 - Adds support for new-style microversion headers while
             keeping support for the original style.
    * 2.28 - Changes compute_node.cpu_info from string to object
    * 2.29 - Add a force flag in evacuate request body and change the
             behaviour for the host flag by calling the scheduler.
    * 2.30 - Add a force flag in live-migrate request body and change the
             behaviour for the host flag by calling the scheduler.
    * 2.31 - Fix os-console-auth-tokens to work for all console types.
    * 2.32 - Add tag to networks and block_device_mapping_v2 in server boot
             request body.
    * 2.33 - Add pagination support for hypervisors.
    * 2.34 - Checks before live-migration are made in asynchronous way.
             os-Migratelive Action does not throw badRequest in case of
             pre-checks failure. Verification result is available over
             instance-actions.
    * 2.35 - Adds keypairs pagination support.
    * 2.36 - Deprecates all the API which proxy to another service and fping
             API.
    * 2.37 - Adds support for auto-allocating networking, otherwise known as
             "Get me a Network". Also enforces server.networks.uuid to be in
             UUID format.
    * 2.38 - Add a condition to return HTTPBadRequest if invalid status is
             provided for listing servers.
    * 2.39 - Deprecates image-metadata proxy API
    * 2.40 - Adds simple tenant usage pagination support.
    * 2.41 - Return uuid attribute for aggregates.
    * 2.42 - In the context of device tagging at instance boot time,
             re-introduce the tag attribute that, due to bugs, was lost
             starting with version 2.33 for block devices and starting with
             version 2.37 for network interfaces.
    * 2.43 - Deprecate os-hosts API
    * 2.44 - The servers action addFixedIp, removeFixedIp, addFloatingIp,
             removeFloatingIp and os-virtual-interfaces APIs are deprecated.
    * 2.45 - The createImage and createBackup APIs no longer return a Location
             header in the response for the snapshot image, they now return a
             json dict in the response body with an image_id key and uuid
             value.
    * 2.46 - Return ``X-OpenStack-Request-ID`` header on requests.
    * 2.47 - When displaying server details, display the flavor as a dict
             rather than a link.  If the user is prevented from retrieving
             the flavor extra-specs by policy, simply omit the field from
             the output.
    * 2.48 - Standardize VM diagnostics info.
    * 2.49 - Support tagged attachment of network interfaces and block devices.
    * 2.50 - Exposes ``server_groups`` and ``server_group_members`` keys in
             GET & PUT ``os-quota-class-sets`` APIs response.
             Also filter out Network related quotas from
             ``os-quota-class-sets`` API
    * 2.51 - Adds new event name to external-events (volume-extended). Also,
             non-admins can see instance action event details except for the
             traceback field.
    * 2.52 - Adds support for applying tags when creating a server.
    * 2.53 - Service and compute node (hypervisor) database ids are hidden.
             The os-services and os-hypervisors APIs now return a uuid in the
             id field, and takes a uuid in requests. PUT and GET requests
             and responses are also changed.
    * 2.54 - Enable reset key pair while rebuilding instance.
    * 2.55 - Added flavor.description to GET/POST/PUT flavors APIs.
    * 2.56 - Add a host parameter in migrate request body in order to
             enable users to specify a target host in cold migration.
             The target host is checked by the scheduler.
    * 2.57 - Deprecated personality files from POST /servers and the rebuild
             server action APIs. Added the ability to pass new user_data to
             the rebuild server action API. Personality / file injection
             related limits and quota resources are also removed.
    * 2.58 - Add pagination support and changes-since filter for
             os-instance-actions API.
    * 2.59 - Add pagination support and changes-since filter for os-migrations
             API. And the os-migrations API now returns both the id and the
             uuid in response.
    * 2.60 - Add support for attaching a single volume to multiple instances.
    * 2.61 - Exposes flavor extra_specs in the flavor representation. Flavor
             extra_specs will be included in Response body of GET, POST, PUT
             /flavors APIs.
    * 2.62 - Add ``host`` and ``hostId`` fields to instance action detail API
             responses.
    * 2.63 - Add support for applying trusted certificates when creating or
             rebuilding a server.
    * 2.64 - Add support for the "max_server_per_host" policy rule for
             ``anti-affinity`` server group policy, the ``policies`` and
             ``metadata`` fields are removed and the ``policy`` (required)
             and ``rules`` (optional) fields are added in response body of
             GET, POST /os-server-groups APIs and GET
             /os-server-groups/{group_id} API.
    * 2.65 - Add support for abort live migrations in ``queued`` and
             ``preparing`` status.
    * 2.66 - Add ``changes-before`` to support users to specify the
             ``updated_at`` time to filter nova resources, the resources
             include the servers API, os-instance-action API and
             os-migrations API.
    * 2.67 - Adds the optional ``volume_type`` field to the
             ``block_device_mapping_v2`` parameter when creating a server.
    * 2.68 - Remove support for forced live migration and evacuate server
             actions.
    * 2.69 - Add support for returning minimal constructs for ``GET /servers``,
             ``GET /servers/detail``, ``GET /servers/{server_id}`` and
             ``GET /os-services`` when there is a transient unavailability
             condition in the deployment like an infrastructure failure.
    * 2.70 - Exposes virtual device tags in the response of the
             ``os-volume_attachments`` and ``os-interface`` APIs.
    * 2.71 - Adds the ``server_groups`` field to ``GET /servers/{id}``,
            ``PUT /servers/{server_id}`` and
            ``POST /servers/{server_id}/action`` (rebuild) responses.
    * 2.72 - Add support for neutron ports with resource request during server
             create. Server move operations are not yet supported for servers
             with such ports.
    * 2.73 - Adds support for specifying a reason when locking the server and
             exposes this via the response from ``GET /servers/detail``,
             ``GET /servers/{server_id}``, ``PUT servers/{server_id}`` and
             ``POST /servers/{server_id}/action`` where the action is rebuild.
             It also supports ``locked`` as a filter/sort parameter for
             ``GET /servers/detail`` and ``GET /servers``.
    * 2.74 - Add support for specifying ``host`` and/or ``hypervisor_hostname``
             in request body to ``POST /servers``. Allow users to specify which
             host/node they want their servers to land on and still be
             validated by the scheduler.
    * 2.75 - Multiple API cleanup listed below:
             - 400 for unknown param for query param and for request body.
             - Making server representation always consistent among GET, PUT
               and Rebuild serevr APIs response.
             - Change the default return value of swap field from the empty
               string to 0 (integer) in flavor APIs.
             - Return ``servers`` field always in the response of GET
               hypervisors API even there are no servers on hypervisor.
    * 2.76 - Adds ``power-update`` event to ``os-server-external-events`` API.
             The changes to the power state of an instance caused by this event
             can be viewed through
             ``GET /servers/{server_id}/os-instance-actions`` and
             ``GET /servers/{server_id}/os-instance-actions/{request_id}``.
    * 2.77 - Add support for specifying ``availability_zone`` to unshelve of a
             shelved offload server.
    * 2.78 - Adds new API ``GET /servers/{server_id}/topology`` which shows
             NUMA topology of a given server.
    * 2.79 - Adds support for specifying ``delete_on_termination`` field in the
             request body to
             ``POST /servers/{server_id}/os-volume_attachments`` and exposes
             this via the response from
             ``GET /servers/{server_id}/os-volume_attachments`` and
             ``GET /servers/{server_id}/os-volume_attachments/{volume_id}``.
"""

# The minimum and maximum versions of the API supported
# The default api version request is defined to be the
# minimum version of the API supported.
# Note(cyeoh): This only applies for the v2.1 API once microversions
# support is fully merged. It does not affect the V2 API.
_MIN_API_VERSION = "2.1"
_MAX_API_VERSION = "2.79"
DEFAULT_API_VERSION = _MIN_API_VERSION

# Almost all proxy APIs which are related to network, images and baremetal
# were deprecated from 2.36.
MAX_PROXY_API_SUPPORT_VERSION = '2.35'
MIN_WITHOUT_PROXY_API_SUPPORT_VERSION = '2.36'

# Starting from microversion 2.39 also image-metadata proxy API is deprecated.
MAX_IMAGE_META_PROXY_API_VERSION = '2.38'
MIN_WITHOUT_IMAGE_META_PROXY_API_VERSION = '2.39'


# NOTE(cyeoh): min and max versions declared as functions so we can
# mock them for unittests. Do not use the constants directly anywhere
# else.
def min_api_version():
    return APIVersionRequest(_MIN_API_VERSION)


def max_api_version():
    return APIVersionRequest(_MAX_API_VERSION)


def is_supported(req, min_version=_MIN_API_VERSION,
                 max_version=_MAX_API_VERSION):
    """Check if API request version satisfies version restrictions.

    :param req: request object
    :param min_version: minimal version of API needed for correct
           request processing
    :param max_version: maximum version of API needed for correct
           request processing

    :returns: True if request satisfies minimal and maximum API version
             requirements. False in other case.
    """

    return (APIVersionRequest(max_version) >= req.api_version_request >=
            APIVersionRequest(min_version))


class APIVersionRequest(object):
    """This class represents an API Version Request with convenience
    methods for manipulation and comparison of version
    numbers that we need to do to implement microversions.
    """

    def __init__(self, version_string=None):
        """Create an API version request object.

        :param version_string: String representation of APIVersionRequest.
            Correct format is 'X.Y', where 'X' and 'Y' are int values.
            None value should be used to create Null APIVersionRequest,
            which is equal to 0.0
        """
        self.ver_major = 0
        self.ver_minor = 0

        if version_string is not None:
            match = re.match(r"^([1-9]\d*)\.([1-9]\d*|0)$",
                             version_string)
            if match:
                self.ver_major = int(match.group(1))
                self.ver_minor = int(match.group(2))
            else:
                raise exception.InvalidAPIVersionString(version=version_string)

    def __str__(self):
        """Debug/Logging representation of object."""
        return ("API Version Request Major: %s, Minor: %s"
                % (self.ver_major, self.ver_minor))

    def is_null(self):
        return self.ver_major == 0 and self.ver_minor == 0

    def _format_type_error(self, other):
        return TypeError(_("'%(other)s' should be an instance of '%(cls)s'") %
                         {"other": other, "cls": self.__class__})

    def __lt__(self, other):
        if not isinstance(other, APIVersionRequest):
            raise self._format_type_error(other)

        return ((self.ver_major, self.ver_minor) <
                (other.ver_major, other.ver_minor))

    def __eq__(self, other):
        if not isinstance(other, APIVersionRequest):
            raise self._format_type_error(other)

        return ((self.ver_major, self.ver_minor) ==
                (other.ver_major, other.ver_minor))

    def __gt__(self, other):
        if not isinstance(other, APIVersionRequest):
            raise self._format_type_error(other)

        return ((self.ver_major, self.ver_minor) >
                (other.ver_major, other.ver_minor))

    def __le__(self, other):
        return self < other or self == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __ge__(self, other):
        return self > other or self == other

    def matches(self, min_version, max_version):
        """Returns whether the version object represents a version
        greater than or equal to the minimum version and less than
        or equal to the maximum version.

        @param min_version: Minimum acceptable version.
        @param max_version: Maximum acceptable version.
        @returns: boolean

        If min_version is null then there is no minimum limit.
        If max_version is null then there is no maximum limit.
        If self is null then raise ValueError
        """

        if self.is_null():
            raise ValueError
        if max_version.is_null() and min_version.is_null():
            return True
        elif max_version.is_null():
            return min_version <= self
        elif min_version.is_null():
            return self <= max_version
        else:
            return min_version <= self <= max_version

    def get_string(self):
        """Converts object to string representation which if used to create
        an APIVersionRequest object results in the same version request.
        """
        if self.is_null():
            raise ValueError
        return "%s.%s" % (self.ver_major, self.ver_minor)

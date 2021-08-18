# Copyright 2011 OpenStack Foundation
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

"""Custom SQLAlchemy types."""

import netaddr
from oslo_utils import netutils
import sqlalchemy as sa
import sqlalchemy.dialects.mysql
import sqlalchemy.dialects.postgresql
from sqlalchemy import types

from nova import utils


# NOTE(dprince): This wrapper allows us to easily match the Folsom MySQL
# Schema. In Folsom we created tables as latin1 and converted them to utf8
# later. This conversion causes some of the Text columns on MySQL to get
# created as mediumtext instead of just text.
def MediumText():
    return sa.Text().with_variant(
        sqlalchemy.dialects.mysql.MEDIUMTEXT(), 'mysql')


class IPAddress(types.TypeDecorator):
    """An SQLAlchemy type representing an IP-address."""

    impl = types.String

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(
                sqlalchemy.dialects.postgresql.INET())

        return dialect.type_descriptor(types.String(39))

    def process_bind_param(self, value, dialect):
        """Process/Formats the value before insert it into the db."""
        if dialect.name == 'postgresql':
            return value
        # NOTE(maurosr): The purpose here is to convert ipv6 to the shortened
        # form, not validate it.
        if netutils.is_valid_ipv6(value):
            return utils.get_shortened_ipv6(value)
        return value


class CIDR(types.TypeDecorator):
    """An SQLAlchemy type representing a CIDR definition."""

    impl = types.String

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(
                sqlalchemy.dialects.postgresql.INET())

        return dialect.type_descriptor(types.String(43))

    def process_bind_param(self, value, dialect):
        """Process/Formats the value before insert it into the db."""
        # NOTE(sdague): normalize all the inserts
        if netutils.is_valid_ipv6_cidr(value):
            return utils.get_shortened_ipv6_cidr(value)
        return value

    def process_result_value(self, value, dialect):
        try:
            return str(netaddr.IPNetwork(value, version=4).cidr)
        except netaddr.AddrFormatError:
            return str(netaddr.IPNetwork(value, version=6).cidr)
        except TypeError:
            return None

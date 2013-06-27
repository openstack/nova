# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
# Copyright 2012 Cloudscaling Group, Inc.
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
"""
SQLAlchemy models.
"""

import six

from sqlalchemy import Column, Integer
from sqlalchemy import DateTime
from sqlalchemy.orm import object_mapper

from nova.openstack.common.db.sqlalchemy import session as sa
from nova.openstack.common import timeutils


class ModelBase(object):
    """Base class for models."""
    __table_initialized__ = False

    def save(self, session=None):
        """Save this object."""
        if not session:
            session = sa.get_session()
        # NOTE(boris-42): This part of code should be look like:
        #                       sesssion.add(self)
        #                       session.flush()
        #                 But there is a bug in sqlalchemy and eventlet that
        #                 raises NoneType exception if there is no running
        #                 transaction and rollback is called. As long as
        #                 sqlalchemy has this bug we have to create transaction
        #                 explicity.
        with session.begin(subtransactions=True):
            session.add(self)
            session.flush()

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __iter__(self):
        columns = dict(object_mapper(self).columns).keys()
        # NOTE(russellb): Allow models to specify other keys that can be looked
        # up, beyond the actual db columns.  An example would be the 'name'
        # property for an Instance.
        if hasattr(self, '_extra_keys'):
            columns.extend(self._extra_keys())
        self._i = iter(columns)
        return self

    def next(self):
        n = six.advance_iterator(self._i)
        return n, getattr(self, n)

    def update(self, values):
        """Make the model object behave like a dict."""
        for k, v in six.iteritems(values):
            setattr(self, k, v)

    def iteritems(self):
        """Make the model object behave like a dict.

        Includes attributes from joins.
        """
        local = dict(self)
        joined = dict([(k, v) for k, v in six.iteritems(self.__dict__)
                      if not k[0] == '_'])
        local.update(joined)
        return local.iteritems()


class TimestampMixin(object):
    created_at = Column(DateTime, default=timeutils.utcnow)
    updated_at = Column(DateTime, onupdate=timeutils.utcnow)


class SoftDeleteMixin(object):
    deleted_at = Column(DateTime)
    deleted = Column(Integer, default=0)

    def soft_delete(self, session=None):
        """Mark this object as deleted."""
        self.deleted = self.id
        self.deleted_at = timeutils.utcnow()
        self.save(session=session)

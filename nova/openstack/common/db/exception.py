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

"""DB related custom exceptions."""

import six

from nova.openstack.common.gettextutils import _


class DBError(Exception):
    """Wraps an implementation specific exception."""
    def __init__(self, inner_exception=None):
        self.inner_exception = inner_exception
        super(DBError, self).__init__(six.text_type(inner_exception))


class DBDuplicateEntry(DBError):
    """Wraps an implementation specific exception."""
    def __init__(self, columns=[], inner_exception=None):
        self.columns = columns
        super(DBDuplicateEntry, self).__init__(inner_exception)


class DBDeadlock(DBError):
    def __init__(self, inner_exception=None):
        super(DBDeadlock, self).__init__(inner_exception)


class DBInvalidUnicodeParameter(Exception):
    message = _("Invalid Parameter: "
                "Unicode is not supported by the current database.")


class DbMigrationError(DBError):
    """Wraps migration specific exception."""
    def __init__(self, message=None):
        super(DbMigrationError, self).__init__(message)


class DBConnectionError(DBError):
    """Wraps connection specific exception."""
    pass

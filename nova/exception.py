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

"""
Nova base exception handling, including decorator for re-raising
Nova-type exceptions. SHOULD include dedicated exception logging.
"""

from nova import log as logging
LOG = logging.getLogger('nova.exception')


class ProcessExecutionError(IOError):

    def __init__(self, stdout=None, stderr=None, exit_code=None, cmd=None,
                 description=None):
        if description is None:
            description = _("Unexpected error while running command.")
        if exit_code is None:
            exit_code = '-'
        message = _("%(description)s\nCommand: %(cmd)s\n"
                "Exit code: %(exit_code)s\nStdout: %(stdout)r\n"
                "Stderr: %(stderr)r") % locals()
        IOError.__init__(self, message)


class Error(Exception):

    def __init__(self, message=None):
        super(Error, self).__init__(message)


class ApiError(Error):
    def __init__(self, message='Unknown', code=None):
        self.message = message
        self.code = code
        if code:
            outstr = '%s: %s' % (code, message)
        else:
            outstr = '%s' % message
        super(ApiError, self).__init__(outstr)


class NotFound(Error):
    pass


class InstanceNotFound(NotFound):
    def __init__(self, message, instance_id):
        self.instance_id = instance_id
        super(InstanceNotFound, self).__init__(message)


class VolumeNotFound(NotFound):
    def __init__(self, message, volume_id):
        self.volume_id = volume_id
        super(VolumeNotFound, self).__init__(message)


class Duplicate(Error):
    pass


class NotAuthorized(Error):
    pass


class NotEmpty(Error):
    pass


class Invalid(Error):
    pass


class InvalidInputException(Error):
    pass


class InvalidContentType(Error):
    pass


class TimeoutException(Error):
    pass


class DBError(Error):
    """Wraps an implementation specific exception"""
    def __init__(self, inner_exception):
        self.inner_exception = inner_exception
        super(DBError, self).__init__(str(inner_exception))


def wrap_db_error(f):
    def _wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception, e:
            LOG.exception(_('DB exception wrapped'))
            raise DBError(e)
    return _wrap
    _wrap.func_name = f.func_name


def wrap_exception(f):
    def _wrap(*args, **kw):
        try:
            return f(*args, **kw)
        except Exception, e:
            if not isinstance(e, Error):
                #exc_type, exc_value, exc_traceback = sys.exc_info()
                LOG.exception(_('Uncaught exception'))
                #logging.error(traceback.extract_stack(exc_traceback))
                raise Error(str(e))
            raise
    _wrap.func_name = f.func_name
    return _wrap

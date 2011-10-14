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

"""Nova logging handler.

This module adds to logging functionality by adding the option to specify
a context object when calling the various log methods.  If the context object
is not specified, default formatting is used.

It also allows setting of formatting information through flags.

"""

import cStringIO
import inspect
import json
import logging
import logging.handlers
import os
import stat
import sys
import traceback

import nova
from nova import flags
from nova import version


FLAGS = flags.FLAGS
flags.DEFINE_string('logging_context_format_string',
                    '%(asctime)s %(levelname)s %(name)s '
                    '[%(request_id)s %(user_id)s '
                    '%(project_id)s] %(message)s',
                    'format string to use for log messages with context')
flags.DEFINE_string('logging_default_format_string',
                    '%(asctime)s %(levelname)s %(name)s [-] '
                    '%(message)s',
                    'format string to use for log messages without context')
flags.DEFINE_string('logging_debug_format_suffix',
                    'from (pid=%(process)d) %(funcName)s'
                    ' %(pathname)s:%(lineno)d',
                    'data to append to log format when level is DEBUG')
flags.DEFINE_string('logging_exception_prefix',
                    '(%(name)s): TRACE: ',
                    'prefix each line of exception output with this format')
flags.DEFINE_list('default_log_levels',
                  ['amqplib=WARN',
                   'sqlalchemy=WARN',
                   'boto=WARN',
                   'eventlet.wsgi.server=WARN'],
                  'list of logger=LEVEL pairs')
flags.DEFINE_bool('use_syslog', False, 'output to syslog')
flags.DEFINE_bool('publish_errors', False, 'publish error events')
flags.DEFINE_string('logfile', None, 'output to named file')


# A list of things we want to replicate from logging.
# levels
CRITICAL = logging.CRITICAL
FATAL = logging.FATAL
ERROR = logging.ERROR
WARNING = logging.WARNING
WARN = logging.WARN
INFO = logging.INFO
DEBUG = logging.DEBUG
NOTSET = logging.NOTSET


# methods
getLogger = logging.getLogger
debug = logging.debug
info = logging.info
warning = logging.warning
warn = logging.warn
error = logging.error
exception = logging.exception
critical = logging.critical
log = logging.log


# handlers
StreamHandler = logging.StreamHandler
WatchedFileHandler = logging.handlers.WatchedFileHandler
# logging.SysLogHandler is nicer than logging.logging.handler.SysLogHandler.
SysLogHandler = logging.handlers.SysLogHandler


# our new audit level
AUDIT = logging.INFO + 1
logging.addLevelName(AUDIT, 'AUDIT')


def _dictify_context(context):
    if context is None:
        return None
    if not isinstance(context, dict) \
    and getattr(context, 'to_dict', None):
        context = context.to_dict()
    return context


def _get_binary_name():
    return os.path.basename(inspect.stack()[-1][1])


def _get_log_file_path(binary=None):
    if FLAGS.logfile:
        return FLAGS.logfile
    if FLAGS.logdir:
        binary = binary or _get_binary_name()
        return '%s.log' % (os.path.join(FLAGS.logdir, binary),)


class NovaLogger(logging.Logger):
    """NovaLogger manages request context and formatting.

    This becomes the class that is instanciated by logging.getLogger.

    """

    def __init__(self, name, level=NOTSET):
        logging.Logger.__init__(self, name, level)
        self.setup_from_flags()

    def setup_from_flags(self):
        """Setup logger from flags."""
        level = NOTSET
        for pair in FLAGS.default_log_levels:
            logger, _sep, level_name = pair.partition('=')
            # NOTE(todd): if we set a.b, we want a.b.c to have the same level
            #             (but not a.bc, so we check the dot)
            if self.name == logger or self.name.startswith("%s." % logger):
                level = globals()[level_name]
        self.setLevel(level)

    def _log(self, level, msg, args, exc_info=None, extra=None, context=None):
        """Extract context from any log call."""
        if not extra:
            extra = {}
        if context:
            extra.update(_dictify_context(context))
        extra.update({"nova_version": version.version_string_with_vcs()})
        return logging.Logger._log(self, level, msg, args, exc_info, extra)

    def addHandler(self, handler):
        """Each handler gets our custom formatter."""
        handler.setFormatter(_formatter)
        return logging.Logger.addHandler(self, handler)

    def audit(self, msg, *args, **kwargs):
        """Shortcut for our AUDIT level."""
        if self.isEnabledFor(AUDIT):
            self._log(AUDIT, msg, args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        """Logging.exception doesn't handle kwargs, so breaks context."""
        if not kwargs.get('exc_info'):
            kwargs['exc_info'] = 1
        self.error(msg, *args, **kwargs)
        # NOTE(todd): does this really go here, or in _log ?
        extra = kwargs.get('extra')
        if not extra:
            return
        env = extra.get('environment')
        if env:
            env = env.copy()
            for k in env.keys():
                if not isinstance(env[k], str):
                    env.pop(k)
            message = 'Environment: %s' % json.dumps(env)
            kwargs.pop('exc_info')
            self.error(message, **kwargs)


class NovaFormatter(logging.Formatter):
    """A nova.context.RequestContext aware formatter configured through flags.

    The flags used to set format strings are: logging_context_foramt_string
    and logging_default_format_string.  You can also specify
    logging_debug_format_suffix to append extra formatting if the log level is
    debug.

    For information about what variables are available for the formatter see:
    http://docs.python.org/library/logging.html#formatter

    """

    def format(self, record):
        """Uses contextstring if request_id is set, otherwise default."""
        if record.__dict__.get('request_id', None):
            self._fmt = FLAGS.logging_context_format_string
        else:
            self._fmt = FLAGS.logging_default_format_string
        if record.levelno == logging.DEBUG \
        and FLAGS.logging_debug_format_suffix:
            self._fmt += " " + FLAGS.logging_debug_format_suffix
        # Cache this on the record, Logger will respect our formated copy
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info, record)
        return logging.Formatter.format(self, record)

    def formatException(self, exc_info, record=None):
        """Format exception output with FLAGS.logging_exception_prefix."""
        if not record:
            return logging.Formatter.formatException(self, exc_info)
        stringbuffer = cStringIO.StringIO()
        traceback.print_exception(exc_info[0], exc_info[1], exc_info[2],
                                  None, stringbuffer)
        lines = stringbuffer.getvalue().split('\n')
        stringbuffer.close()
        formatted_lines = []
        for line in lines:
            pl = FLAGS.logging_exception_prefix % record.__dict__
            fl = '%s%s' % (pl, line)
            formatted_lines.append(fl)
        return '\n'.join(formatted_lines)


_formatter = NovaFormatter()


class NovaRootLogger(NovaLogger):
    def __init__(self, name, level=NOTSET):
        self.logpath = None
        self.filelog = None
        self.streamlog = StreamHandler()
        self.syslog = None
        NovaLogger.__init__(self, name, level)

    def setup_from_flags(self):
        """Setup logger from flags."""
        global _filelog
        if FLAGS.use_syslog:
            self.syslog = SysLogHandler(address='/dev/log')
            self.addHandler(self.syslog)
        elif self.syslog:
            self.removeHandler(self.syslog)
        logpath = _get_log_file_path()
        if logpath:
            self.removeHandler(self.streamlog)
            if logpath != self.logpath:
                self.removeHandler(self.filelog)
                self.filelog = WatchedFileHandler(logpath)
                self.addHandler(self.filelog)
                self.logpath = logpath

                mode = int(FLAGS.logfile_mode, 8)
                st = os.stat(self.logpath)
                if st.st_mode != (stat.S_IFREG | mode):
                    os.chmod(self.logpath, mode)
        else:
            self.removeHandler(self.filelog)
            self.addHandler(self.streamlog)
        if FLAGS.publish_errors:
            self.addHandler(PublishErrorsHandler(ERROR))
        if FLAGS.verbose:
            self.setLevel(DEBUG)
        else:
            self.setLevel(INFO)


class PublishErrorsHandler(logging.Handler):
    def emit(self, record):
        nova.notifier.api.notify('nova.error.publisher', 'error_notification',
            nova.notifier.api.ERROR, dict(error=record.msg))


def handle_exception(type, value, tb):
    extra = {}
    if FLAGS.verbose:
        extra['exc_info'] = (type, value, tb)
    logging.root.critical(str(value), **extra)


def reset():
    """Resets logging handlers.  Should be called if FLAGS changes."""
    for logger in NovaLogger.manager.loggerDict.itervalues():
        if isinstance(logger, NovaLogger):
            logger.setup_from_flags()


def setup():
    """Setup nova logging."""
    if not isinstance(logging.root, NovaRootLogger):
        logging._acquireLock()
        for handler in logging.root.handlers:
            logging.root.removeHandler(handler)
        logging.root = NovaRootLogger("nova")
        NovaLogger.root = logging.root
        NovaLogger.manager.root = logging.root
        for logger in NovaLogger.manager.loggerDict.itervalues():
            logger.root = logging.root
            if isinstance(logger, logging.Logger):
                NovaLogger.manager._fixupParents(logger)
        NovaLogger.manager.loggerDict["nova"] = logging.root
        logging._releaseLock()
        sys.excepthook = handle_exception
        reset()


root = logging.root
logging.setLoggerClass(NovaLogger)


def audit(msg, *args, **kwargs):
    """Shortcut for logging to root log with sevrity 'AUDIT'."""
    logging.root.log(AUDIT, msg, *args, **kwargs)


class WritableLogger(object):
    """A thin wrapper that responds to `write` and logs."""

    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level

    def write(self, msg):
        self.logger.log(self.level, msg)

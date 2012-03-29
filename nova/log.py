# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
is not specified, default formatting is used. Additionally, an instance uuid
may be passed as part of the log message, which is intended to make it easier
for admins to find messages related to a specific instance.

It also allows setting of formatting information through flags.

"""

import cStringIO
import inspect
import itertools
import json
import logging
import logging.config
import logging.handlers
import os
import stat
import sys
import traceback

import nova
from nova import flags
from nova import local
from nova.openstack.common import cfg
from nova import version


log_opts = [
    cfg.StrOpt('logging_context_format_string',
               default='%(asctime)s %(levelname)s %(name)s [%(request_id)s '
                       '%(user_id)s %(project_id)s] %(instance)s'
                       '%(message)s',
               help='format string to use for log messages with context'),
    cfg.StrOpt('logging_default_format_string',
               default='%(asctime)s %(levelname)s %(name)s [-] %(instance)s'
                       '%(message)s',
               help='format string to use for log messages without context'),
    cfg.StrOpt('logging_debug_format_suffix',
               default='from (pid=%(process)d) %(funcName)s '
                       '%(pathname)s:%(lineno)d',
               help='data to append to log format when level is DEBUG'),
    cfg.StrOpt('logging_exception_prefix',
               default='%(asctime)s TRACE %(name)s %(instance)s',
               help='prefix each line of exception output with this format'),
    cfg.StrOpt('instance_format',
               default='[instance: %(uuid)s] ',
               help='If an instance is passed with the log message, format '
                    'it like this'),
    cfg.ListOpt('default_log_levels',
                default=[
                  'amqplib=WARN',
                  'sqlalchemy=WARN',
                  'boto=WARN',
                  'suds=INFO',
                  'eventlet.wsgi.server=WARN'
                  ],
                help='list of logger=LEVEL pairs'),
    cfg.BoolOpt('publish_errors',
                default=False,
                help='publish error events'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(log_opts)

# our new audit level
# NOTE(jkoelker) Since we synthesized an audit level, make the logging
#                module aware of it so it acts like other levels.
logging.AUDIT = logging.INFO + 1
logging.addLevelName(logging.AUDIT, 'AUDIT')


try:
    NullHandler = logging.NullHandler
except AttributeError:  # NOTE(jkoelker) NullHandler added in Python 2.7
    class NullHandler(logging.Handler):
        def handle(self, record):
            pass

        def emit(self, record):
            pass

        def createLock(self):
            self.lock = None


def _dictify_context(context):
    if context is None:
        return None
    if not isinstance(context, dict) and getattr(context, 'to_dict', None):
        context = context.to_dict()
    return context


def _get_binary_name():
    return os.path.basename(inspect.stack()[-1][1])


def _get_log_file_path(binary=None):
    logfile = FLAGS.log_file or FLAGS.logfile
    logdir = FLAGS.log_dir or FLAGS.logdir

    if logfile and not logdir:
        return logfile

    if logfile and logdir:
        return os.path.join(logdir, logfile)

    if logdir:
        binary = binary or _get_binary_name()
        return '%s.log' % (os.path.join(logdir, binary),)


class NovaContextAdapter(logging.LoggerAdapter):
    warn = logging.LoggerAdapter.warning

    def __init__(self, logger):
        self.logger = logger

    def audit(self, msg, *args, **kwargs):
        self.log(logging.AUDIT, msg, *args, **kwargs)

    def process(self, msg, kwargs):
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        extra = kwargs['extra']

        context = kwargs.pop('context', None)
        if not context:
            context = getattr(local.store, 'context', None)
        if context:
            extra.update(_dictify_context(context))

        instance = kwargs.pop('instance', None)
        instance_extra = ''
        if instance:
            instance_extra = FLAGS.instance_format % instance
        extra.update({'instance': instance_extra})

        extra.update({"nova_version": version.version_string_with_vcs()})
        extra['extra'] = extra.copy()
        return msg, kwargs


class JSONFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None):
        # NOTE(jkoelker) we ignore the fmt argument, but its still there
        #                since logging.config.fileConfig passes it.
        self.datefmt = datefmt

    def formatException(self, ei, strip_newlines=True):
        lines = traceback.format_exception(*ei)
        if strip_newlines:
            lines = [itertools.ifilter(lambda x: x,
                                      line.rstrip().splitlines())
                    for line in lines]
            lines = list(itertools.chain(*lines))
        return lines

    def format(self, record):
        message = {'message': record.getMessage(),
                   'asctime': self.formatTime(record, self.datefmt),
                   'name': record.name,
                   'msg': record.msg,
                   'args': record.args,
                   'levelname': record.levelname,
                   'levelno': record.levelno,
                   'pathname': record.pathname,
                   'filename': record.filename,
                   'module': record.module,
                   'lineno': record.lineno,
                   'funcname': record.funcName,
                   'created': record.created,
                   'msecs': record.msecs,
                   'relative_created': record.relativeCreated,
                   'thread': record.thread,
                   'thread_name': record.threadName,
                   'process_name': record.processName,
                   'process': record.process,
                   'traceback': None}

        if hasattr(record, 'extra'):
            message['extra'] = record.extra

        if record.exc_info:
            message['traceback'] = self.formatException(record.exc_info)

        return json.dumps(message)


class LegacyNovaFormatter(logging.Formatter):
    """A nova.context.RequestContext aware formatter configured through flags.

    The flags used to set format strings are: logging_context_format_string
    and logging_default_format_string.  You can also specify
    logging_debug_format_suffix to append extra formatting if the log level is
    debug.

    For information about what variables are available for the formatter see:
    http://docs.python.org/library/logging.html#formatter

    """

    def format(self, record):
        """Uses contextstring if request_id is set, otherwise default."""
        if 'instance' not in record.__dict__:
            record.__dict__['instance'] = ''

        if record.__dict__.get('request_id', None):
            self._fmt = FLAGS.logging_context_format_string
        else:
            self._fmt = FLAGS.logging_default_format_string

        if (record.levelno == logging.DEBUG and
            FLAGS.logging_debug_format_suffix):
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

        if FLAGS.logging_exception_prefix.find('%(asctime)') != -1:
            record.asctime = self.formatTime(record, self.datefmt)

        formatted_lines = []
        for line in lines:
            pl = FLAGS.logging_exception_prefix % record.__dict__
            fl = '%s%s' % (pl, line)
            formatted_lines.append(fl)
        return '\n'.join(formatted_lines)


class PublishErrorsHandler(logging.Handler):
    def emit(self, record):
        if 'list_notifier_drivers' in FLAGS:
            if 'nova.notifier.log_notifier' in FLAGS.list_notifier_drivers:
                return
        nova.notifier.api.notify('nova.error.publisher', 'error_notification',
            nova.notifier.api.ERROR, dict(error=record.msg))


def handle_exception(type, value, tb):
    extra = {}
    if FLAGS.verbose:
        extra['exc_info'] = (type, value, tb)
    getLogger().critical(str(value), **extra)


def setup():
    """Setup nova logging."""
    sys.excepthook = handle_exception

    if FLAGS.log_config:
        try:
            logging.config.fileConfig(FLAGS.log_config)
        except Exception:
            traceback.print_exc()
            raise
    else:
        _setup_logging_from_flags()


def _find_facility_from_flags():
    facility_names = logging.handlers.SysLogHandler.facility_names
    facility = getattr(logging.handlers.SysLogHandler,
                       FLAGS.syslog_log_facility,
                       None)

    if facility is None and FLAGS.syslog_log_facility in facility_names:
        facility = facility_names.get(FLAGS.syslog_log_facility)

    if facility is None:
        valid_facilities = facility_names.keys()
        consts = ['LOG_AUTH', 'LOG_AUTHPRIV', 'LOG_CRON', 'LOG_DAEMON',
                  'LOG_FTP', 'LOG_KERN', 'LOG_LPR', 'LOG_MAIL', 'LOG_NEWS',
                  'LOG_AUTH', 'LOG_SYSLOG', 'LOG_USER', 'LOG_UUCP',
                  'LOG_LOCAL0', 'LOG_LOCAL1', 'LOG_LOCAL2', 'LOG_LOCAL3',
                  'LOG_LOCAL4', 'LOG_LOCAL5', 'LOG_LOCAL6', 'LOG_LOCAL7']
        valid_facilities.extend(consts)
        raise TypeError(_('syslog facility must be one of: %s') %
                        ', '.join("'%s'" % fac
                                  for fac in valid_facilities))

    return facility


def _setup_logging_from_flags():
    nova_root = getLogger().logger
    for handler in nova_root.handlers:
        nova_root.removeHandler(handler)

    if FLAGS.use_syslog:
        facility = _find_facility_from_flags()
        syslog = logging.handlers.SysLogHandler(address='/dev/log',
                                                facility=facility)
        nova_root.addHandler(syslog)

    logpath = _get_log_file_path()
    if logpath:
        filelog = logging.handlers.WatchedFileHandler(logpath)
        nova_root.addHandler(filelog)

        mode = int(FLAGS.logfile_mode, 8)
        st = os.stat(logpath)
        if st.st_mode != (stat.S_IFREG | mode):
            os.chmod(logpath, mode)

    if FLAGS.use_stderr:
        streamlog = logging.StreamHandler()
        nova_root.addHandler(streamlog)

    elif not FLAGS.log_file:
        streamlog = logging.StreamHandler(stream=sys.stdout)
        nova_root.addHandler(streamlog)

    if FLAGS.publish_errors:
        nova_root.addHandler(PublishErrorsHandler(logging.ERROR))

    for handler in nova_root.handlers:
        datefmt = FLAGS.log_date_format
        if FLAGS.log_format:
            handler.setFormatter(logging.Formatter(fmt=FLAGS.log_format,
                                                   datefmt=datefmt))
        handler.setFormatter(LegacyNovaFormatter(datefmt=datefmt))

    if FLAGS.verbose or FLAGS.debug:
        nova_root.setLevel(logging.DEBUG)
    else:
        nova_root.setLevel(logging.INFO)

    level = logging.NOTSET
    for pair in FLAGS.default_log_levels:
        mod, _sep, level_name = pair.partition('=')
        level = logging.getLevelName(level_name)
        logger = logging.getLogger(mod)
        logger.setLevel(level)

    # NOTE(jkoelker) Clear the handlers for the root logger that was setup
    #                by basicConfig in nova/__init__.py and install the
    #                NullHandler.
    root = logging.getLogger()
    for handler in root.handlers:
        root.removeHandler(handler)
    handler = NullHandler()
    handler.setFormatter(logging.Formatter())
    root.addHandler(handler)


_loggers = {}


def getLogger(name='nova'):
    if name not in _loggers:
        _loggers[name] = NovaContextAdapter(logging.getLogger(name))
    return _loggers[name]


class WritableLogger(object):
    """A thin wrapper that responds to `write` and logs."""

    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level

    def write(self, msg):
        self.logger.log(self.level, msg)

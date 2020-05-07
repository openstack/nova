.. option:: --config-dir DIR

    Path to a config directory to pull `*.conf` files from. This file set is
    sorted, so as to provide a predictable parse order if individual options
    are over-ridden. The set is parsed after the file(s) specified via previous
    --config-file, arguments hence over-ridden options in the directory take
    precedence.  This option must be set from the command-line.

.. option:: --config-file PATH

    Path to a config file to use. Multiple config files can be specified, with
    values in later files taking precedence. Defaults to None. This option must
    be set from the command-line.

.. option:: --debug, -d

    Set the logging level to DEBUG instead of the default INFO level.

.. option:: --log-config-append PATH, --log-config PATH, --log_config PATH

    The name of a logging configuration file. This file is appended to any
    existing logging configuration files.  For details about logging
    configuration files, see the Python logging module documentation. Note that
    when logging configuration files are used then all logging configuration is
    set in the configuration file and other logging configuration options are
    ignored (for example, log-date-format).

.. option:: --log-date-format DATE_FORMAT

    Defines the format string for %(asctime)s in log records. Default: None .
    This option is ignored if log_config_append is set.

.. option:: --log-dir LOG_DIR, --logdir LOG_DIR

    (Optional) The base directory used for relative log_file paths. This option
    is ignored if log_config_append is set.

.. option:: --log-file PATH, --logfile PATH

    (Optional) Name of log file to send logging output to.  If no default is
    set, logging will go to stderr as defined by use_stderr. This option is
    ignored if log_config_append is set.

.. option:: --nodebug

    The inverse of :option:`--debug`.

.. option:: --nouse-journal

    The inverse of :option:`--use-journal`.

.. option:: --nouse-json

    The inverse of :option:`--use-json`.

.. option:: --nouse-syslog

    The inverse of :option:`--use-syslog`.

.. option:: --nowatch-log-file

    The inverse of :option:`--watch-log-file`.

.. option:: --syslog-log-facility SYSLOG_LOG_FACILITY

    Syslog facility to receive log lines. This option is ignored if
    log_config_append is set.

.. option:: --use-journal

    Enable journald for logging. If running in a systemd environment you may
    wish to enable journal support.  Doing so will use the journal native
    protocol which includes structured metadata in addition to log
    messages.This option is ignored if log_config_append is set.

.. option:: --use-json

    Use JSON formatting for logging. This option is ignored if
    log_config_append is set.

.. option:: --use-syslog

    Use syslog for logging. Existing syslog format is DEPRECATED and will be
    changed later to honor RFC5424.  This option is ignored if
    log_config_append is set.

.. option:: --version

    Show program's version number and exit

.. option:: --watch-log-file

    Uses logging handler designed to watch file system.  When log file is moved
    or removed this handler will open a new log file with specified path
    instantaneously. It makes sense only if log_file option is specified and
    Linux platform is used. This option is ignored if log_config_append is set.

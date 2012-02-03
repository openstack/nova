# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Red Hat, Inc.
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

r"""
Configuration options which may be set on the command line or in config files.

The schema for each option is defined using the Opt sub-classes e.g.

    common_opts = [
        cfg.StrOpt('bind_host',
                   default='0.0.0.0',
                   help='IP address to listen on'),
        cfg.IntOpt('bind_port',
                   default=9292,
                   help='Port number to listen on')
    ]

Options can be strings, integers, floats, booleans, lists or 'multi strings':

    enabled_apis_opt = \
        cfg.ListOpt('enabled_apis',
                    default=['ec2', 'osapi_compute'],
                    help='List of APIs to enable by default')

    DEFAULT_EXTENSIONS = [
        'nova.api.openstack.contrib.standard_extensions'
    ]
    osapi_compute_extension_opt = \
        cfg.MultiStrOpt('osapi_compute_extension',
                        default=DEFAULT_EXTENSIONS)

Option schemas are registered with with the config manager at runtime, but
before the option is referenced:

    class ExtensionManager(object):

        enabled_apis_opt = cfg.ListOpt(...)

        def __init__(self, conf):
            self.conf = conf
            self.conf.register_opt(enabled_apis_opt)
            ...

        def _load_extensions(self):
            for ext_factory in self.conf.osapi_compute_extension:
                ....

A common usage pattern is for each option schema to be defined in the module or
class which uses the option:

    opts = ...

    def add_common_opts(conf):
        conf.register_opts(opts)

    def get_bind_host(conf):
        return conf.bind_host

    def get_bind_port(conf):
        return conf.bind_port

An option may optionally be made available via the command line. Such options
must registered with the config manager before the command line is parsed (for
the purposes of --help and CLI arg validation):

    cli_opts = [
        cfg.BoolOpt('verbose',
                    short='v',
                    default=False,
                    help='Print more verbose output'),
        cfg.BoolOpt('debug',
                    short='d',
                    default=False,
                    help='Print debugging output'),
    ]

    def add_common_opts(conf):
        conf.register_cli_opts(cli_opts)

The config manager has a single CLI option defined by default, --config-file:

    class ConfigOpts(object):

        config_file_opt = \
            MultiStrOpt('config-file',
                        ...

        def __init__(self, ...):
            ...
            self.register_cli_opt(self.config_file_opt)

Option values are parsed from any supplied config files using SafeConfigParser.
If none are specified, a default set is used e.g. glance-api.conf and
glance-common.conf:

    glance-api.conf:
      [DEFAULT]
      bind_port = 9292

    glance-common.conf:
      [DEFAULT]
      bind_host = 0.0.0.0

Option values in config files override those on the command line. Config files
are parsed in order, with values in later files overriding those in earlier
files.

The parsing of CLI args and config files is initiated by invoking the config
manager e.g.

    conf = ConfigOpts()
    conf.register_opt(BoolOpt('verbose', ...))
    conf(sys.argv[1:])
    if conf.verbose:
        ...

Options can be registered as belonging to a group:

    rabbit_group = cfg.OptionGroup(name='rabbit',
                                   title='RabbitMQ options')

    rabbit_host_opt = \
        cfg.StrOpt('host',
                   group='rabbit',
                   default='localhost',
                   help='IP/hostname to listen on'),
    rabbit_port_opt = \
        cfg.IntOpt('port',
                   default=5672,
                   help='Port number to listen on')
    rabbit_ssl_opt = \
        conf.BoolOpt('use_ssl',
                     default=False,
                     help='Whether to support SSL connections')

    def register_rabbit_opts(conf):
        conf.register_group(rabbit_group)
        # options can be registered under a group in any of these ways:
        conf.register_opt(rabbit_host_opt)
        conf.register_opt(rabbit_port_opt, group='rabbit')
        conf.register_opt(rabbit_ssl_opt, group=rabbit_group)

If no group is specified, options belong to the 'DEFAULT' section of config
files:

    glance-api.conf:
      [DEFAULT]
      bind_port = 9292
      ...

      [rabbit]
      host = localhost
      port = 5672
      use_ssl = False
      userid = guest
      password = guest
      virtual_host = /

Command-line options in a group are automatically prefixed with the group name:

    --rabbit-host localhost --rabbit-use-ssl False

Option values in the default group are referenced as attributes/properties on
the config manager; groups are also attributes on the config manager, with
attributes for each of the options associated with the group:

    server.start(app, conf.bind_port, conf.bind_host, conf)

    self.connection = kombu.connection.BrokerConnection(
        hostname=conf.rabbit.host,
        port=conf.rabbit.port,
        ...)

Option values may reference other values using PEP 292 string substitution:

    opts = [
        cfg.StrOpt('state_path',
                   default=os.path.join(os.path.dirname(__file__), '../'),
                   help='Top-level directory for maintaining nova state'),
        cfg.StrOpt('sqlite_db',
                   default='nova.sqlite',
                   help='file name for sqlite'),
        cfg.StrOpt('sql_connection',
                   default='sqlite:///$state_path/$sqlite_db',
                   help='connection string for sql database'),
    ]

Note that interpolation can be avoided by using '$$'.
"""

import sys
import ConfigParser
import copy
import optparse
import os
import string


class Error(Exception):
    """Base class for cfg exceptions."""

    def __init__(self, msg=None):
        self.msg = msg

    def __str__(self):
        return self.msg


class ArgsAlreadyParsedError(Error):
    """Raised if a CLI opt is registered after parsing."""

    def __str__(self):
        ret = "arguments already parsed"
        if self.msg:
            ret += ": " + self.msg
        return ret


class NoSuchOptError(Error, AttributeError):
    """Raised if an opt which doesn't exist is referenced."""

    def __init__(self, opt_name, group=None):
        self.opt_name = opt_name
        self.group = group

    def __str__(self):
        if self.group is None:
            return "no such option: %s" % self.opt_name
        else:
            return "no such option in group %s: %s" % (self.group.name,
                                                       self.opt_name)


class NoSuchGroupError(Error):
    """Raised if a group which doesn't exist is referenced."""

    def __init__(self, group_name):
        self.group_name = group_name

    def __str__(self):
        return "no such group: %s" % self.group_name


class DuplicateOptError(Error):
    """Raised if multiple opts with the same name are registered."""

    def __init__(self, opt_name):
        self.opt_name = opt_name

    def __str__(self):
        return "duplicate option: %s" % self.opt_name


class TemplateSubstitutionError(Error):
    """Raised if an error occurs substituting a variable in an opt value."""

    def __str__(self):
        return "template substitution error: %s" % self.msg


class ConfigFilesNotFoundError(Error):
    """Raised if one or more config files are not found."""

    def __init__(self, config_files):
        self.config_files = config_files

    def __str__(self):
        return 'Failed to read some config files: %s' % \
            string.join(self.config_files, ',')


class ConfigFileParseError(Error):
    """Raised if there is an error parsing a config file."""

    def __init__(self, config_file, msg):
        self.config_file = config_file
        self.msg = msg

    def __str__(self):
        return 'Failed to parse %s: %s' % (self.config_file, self.msg)


class ConfigFileValueError(Error):
    """Raised if a config file value does not match its opt type."""
    pass


def find_config_files(project=None, prog=None):
    """Return a list of default configuration files.

    We default to two config files: [${project}.conf, ${prog}.conf]

    And we look for those config files in the following directories:

      ~/.${project}/
      ~/
      /etc/${project}/
      /etc/

    We return an absolute path for (at most) one of each the default config
    files, for the topmost directory it exists in.

    For example, if project=foo, prog=bar and /etc/foo/foo.conf, /etc/bar.conf
    and ~/.foo/bar.conf all exist, then we return ['/etc/foo/foo.conf',
    '~/.foo/bar.conf']

    If no project name is supplied, we only look for ${prog.conf}.

    :param project: an optional project name
    :param prog: the program name, defaulting to the basename of sys.argv[0]
    """
    if prog is None:
        prog = os.path.basename(sys.argv[0])

    fix_path = lambda p: os.path.abspath(os.path.expanduser(p))

    cfg_dirs = [
        fix_path(os.path.join('~', '.' + project)) if project else None,
        fix_path('~'),
        os.path.join('/etc', project) if project else None,
        '/etc'
        ]
    cfg_dirs = filter(bool, cfg_dirs)

    def search_dirs(dirs, basename):
        for d in dirs:
            path = os.path.join(d, basename)
            if os.path.exists(path):
                return path

    config_files = []
    if project:
        config_files.append(search_dirs(cfg_dirs, '%s.conf' % project))
    config_files.append(search_dirs(cfg_dirs, '%s.conf' % prog))

    return filter(bool, config_files)


def _is_opt_registered(opts, opt):
    """Check whether an opt with the same name is already registered.

    The same opt may be registered multiple times, with only the first
    registration having any effect. However, it is an error to attempt
    to register a different opt with the same name.

    :param opts: the set of opts already registered
    :param opt: the opt to be registered
    :returns: True if the opt was previously registered, False otherwise
    :raises: DuplicateOptError if a naming conflict is detected
    """
    if opt.dest in opts:
        if opts[opt.dest]['opt'] is not opt:
            raise DuplicateOptError(opt.name)
        return True
    else:
        return False


class Opt(object):

    """Base class for all configuration options.

    An Opt object has no public methods, but has a number of public string
    properties:

      name:
        the name of the option, which may include hyphens
      dest:
        the (hyphen-less) ConfigOpts property which contains the option value
      short:
        a single character CLI option name
      default:
        the default value of the option
      metavar:
        the name shown as the argument to a CLI option in --help output
      help:
        an string explaining how the options value is used
    """

    def __init__(self, name, dest=None, short=None,
                 default=None, metavar=None, help=None):
        """Construct an Opt object.

        The only required parameter is the option's name. However, it is
        common to also supply a default and help string for all options.

        :param name: the option's name
        :param dest: the name of the corresponding ConfigOpts property
        :param short: a single character CLI option name
        :param default: the default value of the option
        :param metavar: the option argument to show in --help
        :param help: an explanation of how the option is used
        """
        self.name = name
        if dest is None:
            self.dest = self.name.replace('-', '_')
        else:
            self.dest = dest
        self.short = short
        self.default = default
        self.metavar = metavar
        self.help = help

    def _get_from_config_parser(self, cparser, section):
        """Retrieves the option value from a ConfigParser object.

        This is the method ConfigOpts uses to look up the option value from
        config files. Most opt types override this method in order to perform
        type appropriate conversion of the returned value.

        :param cparser: a ConfigParser object
        :param section: a section name
        """
        return cparser.get(section, self.dest)

    def _add_to_cli(self, parser, group=None):
        """Makes the option available in the command line interface.

        This is the method ConfigOpts uses to add the opt to the CLI interface
        as appropriate for the opt type. Some opt types may extend this method,
        others may just extend the helper methods it uses.

        :param parser: the CLI option parser
        :param group: an optional OptGroup object
        """
        container = self._get_optparse_container(parser, group)
        kwargs = self._get_optparse_kwargs(group)
        prefix = self._get_optparse_prefix('', group)
        self._add_to_optparse(container, self.name, self.short, kwargs, prefix)

    def _add_to_optparse(self, container, name, short, kwargs, prefix=''):
        """Add an option to an optparse parser or group.

        :param container: an optparse.OptionContainer object
        :param name: the opt name
        :param short: the short opt name
        :param kwargs: the keyword arguments for add_option()
        :param prefix: an optional prefix to prepend to the opt name
        :raises: DuplicateOptError if a naming confict is detected
        """
        args = ['--' + prefix + name]
        if short:
            args += ['-' + short]
        for a in args:
            if container.has_option(a):
                raise DuplicateOptError(a)
        container.add_option(*args, **kwargs)

    def _get_optparse_container(self, parser, group):
        """Returns an optparse.OptionContainer.

        :param parser: an optparse.OptionParser
        :param group: an (optional) OptGroup object
        :returns: an optparse.OptionGroup if a group is given, else the parser
        """
        if group is not None:
            return group._get_optparse_group(parser)
        else:
            return parser

    def _get_optparse_kwargs(self, group, **kwargs):
        """Build a dict of keyword arguments for optparse's add_option().

        Most opt types extend this method to customize the behaviour of the
        options added to optparse.

        :param group: an optional group
        :param kwargs: optional keyword arguments to add to
        :returns: a dict of keyword arguments
        """
        dest = self.dest
        if group is not None:
            dest = group.name + '_' + dest
        kwargs.update({
                'dest': dest,
                'metavar': self.metavar,
                'help': self.help,
                })
        return kwargs

    def _get_optparse_prefix(self, prefix, group):
        """Build a prefix for the CLI option name, if required.

        CLI options in a group are prefixed with the group's name in order
        to avoid conflicts between similarly named options in different
        groups.

        :param prefix: an existing prefix to append to (e.g. 'no' or '')
        :param group: an optional OptGroup object
        :returns: a CLI option prefix including the group name, if appropriate
        """
        if group is not None:
            return group.name + '-' + prefix
        else:
            return prefix


class StrOpt(Opt):
    """
    String opts do not have their values transformed and are returned as
    str objects.
    """
    pass


class BoolOpt(Opt):

    """
    Bool opts are set to True or False on the command line using --optname or
    --noopttname respectively.

    In config files, boolean values are case insensitive and can be set using
    1/0, yes/no, true/false or on/off.
    """

    def _get_from_config_parser(self, cparser, section):
        """Retrieve the opt value as a boolean from ConfigParser."""
        return cparser.getboolean(section, self.dest)

    def _add_to_cli(self, parser, group=None):
        """Extends the base class method to add the --nooptname option."""
        super(BoolOpt, self)._add_to_cli(parser, group)
        self._add_inverse_to_optparse(parser, group)

    def _add_inverse_to_optparse(self, parser, group):
        """Add the --nooptname option to the option parser."""
        container = self._get_optparse_container(parser, group)
        kwargs = self._get_optparse_kwargs(group, action='store_false')
        prefix = self._get_optparse_prefix('no', group)
        self._add_to_optparse(container, self.name, None, kwargs, prefix)

    def _get_optparse_kwargs(self, group, action='store_true', **kwargs):
        """Extends the base optparse keyword dict for boolean options."""
        return super(BoolOpt,
                     self)._get_optparse_kwargs(group, action=action, **kwargs)


class IntOpt(Opt):

    """Int opt values are converted to integers using the int() builtin."""

    def _get_from_config_parser(self, cparser, section):
        """Retrieve the opt value as a integer from ConfigParser."""
        return cparser.getint(section, self.dest)

    def _get_optparse_kwargs(self, group, **kwargs):
        """Extends the base optparse keyword dict for integer options."""
        return super(IntOpt,
                     self)._get_optparse_kwargs(group, type='int', **kwargs)


class FloatOpt(Opt):

    """Float opt values are converted to floats using the float() builtin."""

    def _get_from_config_parser(self, cparser, section):
        """Retrieve the opt value as a float from ConfigParser."""
        return cparser.getfloat(section, self.dest)

    def _get_optparse_kwargs(self, group, **kwargs):
        """Extends the base optparse keyword dict for float options."""
        return super(FloatOpt,
                     self)._get_optparse_kwargs(group, type='float', **kwargs)


class ListOpt(Opt):

    """
    List opt values are simple string values separated by commas. The opt value
    is a list containing these strings.
    """

    def _get_from_config_parser(self, cparser, section):
        """Retrieve the opt value as a list from ConfigParser."""
        return cparser.get(section, self.dest).split(',')

    def _get_optparse_kwargs(self, group, **kwargs):
        """Extends the base optparse keyword dict for list options."""
        return super(ListOpt,
                     self)._get_optparse_kwargs(group,
                                                type='string',
                                                action='callback',
                                                callback=self._parse_list,
                                                **kwargs)

    def _parse_list(self, option, opt, value, parser):
        """An optparse callback for parsing an option value into a list."""
        setattr(parser.values, self.dest, value.split(','))


class MultiStrOpt(Opt):

    """
    Multistr opt values are string opts which may be specified multiple times.
    The opt value is a list containing all the string values specified.
    """

    def _get_from_config_parser(self, cparser, section):
        """Retrieve the opt value as a multistr from ConfigParser."""
        # FIXME(markmc): values spread across the CLI and multiple
        #                config files should be appended
        value = \
            super(MultiStrOpt, self)._get_from_config_parser(cparser, section)
        return value if value is None else [value]

    def _get_optparse_kwargs(self, group, **kwargs):
        """Extends the base optparse keyword dict for multi str options."""
        return super(MultiStrOpt,
                     self)._get_optparse_kwargs(group, action='append')


class OptGroup(object):

    """
    Represents a group of opts.

    CLI opts in the group are automatically prefixed with the group name.

    Each group corresponds to a section in config files.

    An OptGroup object has no public methods, but has a number of public string
    properties:

      name:
        the name of the group
      title:
        the group title as displayed in --help
      help:
        the group description as displayed in --help
    """

    def __init__(self, name, title=None, help=None):
        """Constructs an OptGroup object.

        :param name: the group name
        :param title: the group title for --help
        :param help: the group description for --help
        """
        self.name = name
        if title is None:
            self.title = "%s options" % title
        else:
            self.title = title
        self.help = help

        self._opts = {}  # dict of dicts of {opt:, override:, default:)
        self._optparse_group = None

    def _register_opt(self, opt):
        """Add an opt to this group.

        :param opt: an Opt object
        :returns: False if previously registered, True otherwise
        :raises: DuplicateOptError if a naming conflict is detected
        """
        if _is_opt_registered(self._opts, opt):
            return False

        self._opts[opt.dest] = {'opt': opt, 'override': None, 'default': None}

        return True

    def _get_optparse_group(self, parser):
        """Build an optparse.OptionGroup for this group."""
        if self._optparse_group is None:
            self._optparse_group = \
                optparse.OptionGroup(parser, self.title, self.help)
        return self._optparse_group


class ConfigOpts(object):

    """
    Config options which may be set on the command line or in config files.

    ConfigOpts is a configuration option manager with APIs for registering
    option schemas, grouping options, parsing option values and retrieving
    the values of options.
    """

    def __init__(self,
                 project=None,
                 prog=None,
                 version=None,
                 usage=None,
                 default_config_files=None):
        """Construct a ConfigOpts object.

        Automatically registers the --config-file option with either a supplied
        list of default config files, or a list from find_config_files().

        :param project: the toplevel project name, used to locate config files
        :param prog: the name of the program (defaults to sys.argv[0] basename)
        :param version: the program version (for --version)
        :param usage: a usage string (%prog will be expanded)
        :param default_config_files: config files to use by default
        """
        if prog is None:
            prog = os.path.basename(sys.argv[0])

        if default_config_files is None:
            default_config_files = find_config_files(project, prog)

        self.project = project
        self.prog = prog
        self.version = version
        self.usage = usage
        self.default_config_files = default_config_files

        self._opts = {}  # dict of dicts of (opt:, override:, default:)
        self._groups = {}

        self._args = None
        self._cli_values = {}

        self._oparser = optparse.OptionParser(prog=self.prog,
                                              version=self.version,
                                              usage=self.usage)
        self._cparser = None

        self.register_cli_opt(\
            MultiStrOpt('config-file',
                        default=self.default_config_files,
                        metavar='PATH',
                        help='Path to a config file to use. Multiple config '
                             'files can be specified, with values in later '
                             'files taking precedence. The default files used '
                             'are: %s' % (self.default_config_files, )))

    def __call__(self, args=None):
        """Parse command line arguments and config files.

        Calling a ConfigOpts object causes the supplied command line arguments
        and config files to be parsed, causing opt values to be made available
        as attributes of the object.

        The object may be called multiple times, each time causing the previous
        set of values to be overwritten.

        :params args: command line arguments (defaults to sys.argv[1:])
        :returns: the list of arguments left over after parsing options
        :raises: SystemExit, ConfigFilesNotFoundError, ConfigFileParseError
        """
        self.reset()

        self._args = args

        (values, args) = self._oparser.parse_args(self._args)

        self._cli_values = vars(values)

        if self.config_file:
            self._parse_config_files(self.config_file)

        return args

    def __getattr__(self, name):
        """Look up an option value and perform string substitution.

        :param name: the opt name (or 'dest', more precisely)
        :returns: the option value (after string subsititution) or a GroupAttr
        :raises: NoSuchOptError,ConfigFileValueError,TemplateSubstitutionError
        """
        return self._substitute(self._get(name))

    def reset(self):
        """Reset the state of the object to before it was called."""
        self._args = None
        self._cli_values = None
        self._cparser = None

    def register_opt(self, opt, group=None):
        """Register an option schema.

        Registering an option schema makes any option value which is previously
        or subsequently parsed from the command line or config files available
        as an attribute of this object.

        :param opt: an instance of an Opt sub-class
        :param group: an optional OptGroup object or group name
        :return: False if the opt was already register, True otherwise
        :raises: DuplicateOptError
        """
        if group is not None:
            return self._get_group(group)._register_opt(opt)

        if _is_opt_registered(self._opts, opt):
            return False

        self._opts[opt.dest] = {'opt': opt, 'override': None, 'default': None}

        return True

    def register_opts(self, opts, group=None):
        """Register multiple option schemas at once."""
        for opt in opts:
            self.register_opt(opt, group)

    def register_cli_opt(self, opt, group=None):
        """Register a CLI option schema.

        CLI option schemas must be registered before the command line and
        config files are parsed. This is to ensure that all CLI options are
        show in --help and option validation works as expected.

        :param opt: an instance of an Opt sub-class
        :param group: an optional OptGroup object or group name
        :return: False if the opt was already register, True otherwise
        :raises: DuplicateOptError, ArgsAlreadyParsedError
        """
        if self._args is not None:
            raise ArgsAlreadyParsedError("cannot register CLI option")

        if not self.register_opt(opt, group):
            return False

        if group is not None:
            group = self._get_group(group)

        opt._add_to_cli(self._oparser, group)

        return True

    def register_cli_opts(self, opts, group=None):
        """Register multiple CLI option schemas at once."""
        for opt in opts:
            self.register_cli_opt(opt, group)

    def register_group(self, group):
        """Register an option group.

        An option group must be registered before options can be registered
        with the group.

        :param group: an OptGroup object
        """
        if group.name in self._groups:
            return

        self._groups[group.name] = copy.copy(group)

    def set_override(self, name, override, group=None):
        """Override an opt value.

        Override the command line, config file and default values of a
        given option.

        :param name: the name/dest of the opt
        :param override: the override value
        :param group: an option OptGroup object or group name
        :raises: NoSuchOptError, NoSuchGroupError
        """
        opt_info = self._get_opt_info(name, group)
        opt_info['override'] = override

    def set_default(self, name, default, group=None):
        """Override an opt's default value.

        Override the default value of given option. A command line or
        config file value will still take precedence over this default.

        :param name: the name/dest of the opt
        :param default: the default value
        :param group: an option OptGroup object or group name
        :raises: NoSuchOptError, NoSuchGroupError
        """
        opt_info = self._get_opt_info(name, group)
        opt_info['default'] = default

    def log_opt_values(self, logger, lvl):
        """Log the value of all registered opts.

        It's often useful for an app to log its configuration to a log file at
        startup for debugging. This method dumps to the entire config state to
        the supplied logger at a given log level.

        :param logger: a logging.Logger object
        :param lvl: the log level (e.g. logging.DEBUG) arg to logger.log()
        """
        logger.log(lvl, "*" * 80)
        logger.log(lvl, "Configuration options gathered from:")
        logger.log(lvl, "command line args: %s", self._args)
        logger.log(lvl, "config files: %s", self.config_file)
        logger.log(lvl, "=" * 80)

        for opt_name in sorted(self._opts):
            logger.log(lvl, "%-30s = %s", opt_name, getattr(self, opt_name))

        for group_name in self._groups:
            group_attr = self.GroupAttr(self, group_name)
            for opt_name in sorted(self._groups[group_name]._opts):
                logger.log(lvl, "%-30s = %s",
                           "%s.%s" % (group_name, opt_name),
                           getattr(group_attr, opt_name))

        logger.log(lvl, "*" * 80)

    def print_usage(self, file=None):
        """Print the usage message for the current program."""
        self._oparser.print_usage(file)

    def _get(self, name, group=None):
        """Look up an option value.

        :param name: the opt name (or 'dest', more precisely)
        :param group: an option OptGroup
        :returns: the option value, or a GroupAttr object
        :raises: NoSuchOptError, NoSuchGroupError, ConfigFileValueError,
                 TemplateSubstitutionError
        """
        if group is None and name in self._groups:
            return self.GroupAttr(self, name)

        if group is not None:
            group = self._get_group(group)

        info = self._get_opt_info(name, group)
        default, opt, override = map(lambda k: info[k], sorted(info.keys()))

        if override is not None:
            return override

        if self._cparser is not None:
            section = group.name if group is not None else 'DEFAULT'
            try:
                return opt._get_from_config_parser(self._cparser, section)
            except (ConfigParser.NoOptionError,
                    ConfigParser.NoSectionError):
                pass
            except ValueError, ve:
                raise ConfigFileValueError(str(ve))

        name = name if group is None else group.name + '_' + name
        value = self._cli_values.get(name, None)
        if value is not None:
            return value

        if default is not None:
            return default

        return opt.default

    def _substitute(self, value):
        """Perform string template substitution.

        Substititue any template variables (e.g. $foo, ${bar}) in the supplied
        string value(s) with opt values.

        :param value: the string value, or list of string values
        :returns: the substituted string(s)
        """
        if isinstance(value, list):
            return [self._substitute(i) for i in value]
        elif isinstance(value, str):
            tmpl = string.Template(value)
            return tmpl.safe_substitute(self.StrSubWrapper(self))
        else:
            return value

    def _get_group(self, group_or_name):
        """Looks up a OptGroup object.

        Helper function to return an OptGroup given a parameter which can
        either be the group's name or an OptGroup object.

        The OptGroup object returned is from the internal dict of OptGroup
        objects, which will be a copy of any OptGroup object that users of
        the API have access to.

        :param group_or_name: the group's name or the OptGroup object itself
        :raises: NoSuchGroupError
        """
        if isinstance(group_or_name, OptGroup):
            group_name = group_or_name.name
        else:
            group_name = group_or_name

        if not group_name in self._groups:
            raise NoSuchGroupError(group_name)

        return self._groups[group_name]

    def _get_opt_info(self, opt_name, group=None):
        """Return the (opt, override, default) dict for an opt.

        :param opt_name: an opt name/dest
        :param group: an optional group name or OptGroup object
        :raises: NoSuchOptError, NoSuchGroupError
        """
        if group is None:
            opts = self._opts
        else:
            group = self._get_group(group)
            opts = group._opts

        if not opt_name in opts:
            raise NoSuchOptError(opt_name, group)

        return opts[opt_name]

    def _parse_config_files(self, config_files):
        """Parse the supplied configuration files.

        :raises: ConfigFilesNotFoundError, ConfigFileParseError
        """
        self._cparser = ConfigParser.SafeConfigParser()

        try:
            read_ok = self._cparser.read(config_files)
        except ConfigParser.ParsingError, cpe:
            raise ConfigFileParseError(cpe.filename, cpe.message)

        if read_ok != config_files:
            not_read_ok = filter(lambda f: f not in read_ok, config_files)
            raise ConfigFilesNotFoundError(not_read_ok)

    class GroupAttr(object):

        """
        A helper class representing the option values of a group as attributes.
        """

        def __init__(self, conf, group):
            """Construct a GroupAttr object.

            :param conf: a ConfigOpts object
            :param group: a group name or OptGroup object
            """
            self.conf = conf
            self.group = group

        def __getattr__(self, name):
            """Look up an option value and perform template substitution."""
            return self.conf._substitute(self.conf._get(name, self.group))

    class StrSubWrapper(object):

        """
        A helper class exposing opt values as a dict for string substitution.
        """

        def __init__(self, conf):
            """Construct a StrSubWrapper object.

            :param conf: a ConfigOpts object
            """
            self.conf = conf

        def __getitem__(self, key):
            """Look up an opt value from the ConfigOpts object.

            :param key: an opt name
            :returns: an opt value
            :raises: TemplateSubstitutionError if attribute is a group
            """
            value = getattr(self.conf, key)
            if isinstance(value, self.conf.GroupAttr):
                raise TemplateSubstitutionError(
                    'substituting group %s not supported' % key)
            return value


class CommonConfigOpts(ConfigOpts):

    DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)8s [%(name)s] %(message)s"
    DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    common_cli_opts = [
        BoolOpt('debug',
                short='d',
                default=False,
                help='Print debugging output'),
        BoolOpt('verbose',
                short='v',
                default=False,
                help='Print more verbose output'),
        ]

    logging_cli_opts = [
        StrOpt('log-config',
               metavar='PATH',
               help='If this option is specified, the logging configuration '
                    'file specified is used and overrides any other logging '
                    'options specified. Please see the Python logging module '
                    'documentation for details on logging configuration '
                    'files.'),
        StrOpt('log-format',
               default=DEFAULT_LOG_FORMAT,
               metavar='FORMAT',
               help='A logging.Formatter log message format string which may '
                    'use any of the available logging.LogRecord attributes. '
                    'Default: %default'),
        StrOpt('log-date-format',
               default=DEFAULT_LOG_DATE_FORMAT,
               metavar='DATE_FORMAT',
               help='Format string for %(asctime)s in log records. '
                    'Default: %default'),
        StrOpt('log-file',
               metavar='PATH',
               help='(Optional) Name of log file to output to. '
                    'If not set, logging will go to stdout.'),
        StrOpt('log-dir',
               help='(Optional) The directory to keep log files in '
                    '(will be prepended to --logfile)'),
        BoolOpt('use-syslog',
                default=False,
                help='Use syslog for logging.'),
        ]

    def __init__(self, **kwargs):
        super(CommonConfigOpts, self).__init__(**kwargs)
        self.register_cli_opts(self.common_cli_opts)
        self.register_cli_opts(self.logging_cli_opts)

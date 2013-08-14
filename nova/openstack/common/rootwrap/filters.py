# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack Foundation.
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

import os
import re


class CommandFilter(object):
    """Command filter only checking that the 1st argument matches exec_path."""

    def __init__(self, exec_path, run_as, *args):
        self.name = ''
        self.exec_path = exec_path
        self.run_as = run_as
        self.args = args
        self.real_exec = None

    def get_exec(self, exec_dirs=[]):
        """Returns existing executable, or empty string if none found."""
        if self.real_exec is not None:
            return self.real_exec
        self.real_exec = ""
        if os.path.isabs(self.exec_path):
            if os.access(self.exec_path, os.X_OK):
                self.real_exec = self.exec_path
        else:
            for binary_path in exec_dirs:
                expanded_path = os.path.join(binary_path, self.exec_path)
                if os.access(expanded_path, os.X_OK):
                    self.real_exec = expanded_path
                    break
        return self.real_exec

    def match(self, userargs):
        """Only check that the first argument (command) matches exec_path."""
        return userargs and os.path.basename(self.exec_path) == userargs[0]

    def get_command(self, userargs, exec_dirs=[]):
        """Returns command to execute (with sudo -u if run_as != root)."""
        to_exec = self.get_exec(exec_dirs=exec_dirs) or self.exec_path
        if (self.run_as != 'root'):
            # Used to run commands at lesser privileges
            return ['sudo', '-u', self.run_as, to_exec] + userargs[1:]
        return [to_exec] + userargs[1:]

    def get_environment(self, userargs):
        """Returns specific environment to set, None if none."""
        return None


class RegExpFilter(CommandFilter):
    """Command filter doing regexp matching for every argument."""

    def match(self, userargs):
        # Early skip if command or number of args don't match
        if (not userargs or len(self.args) != len(userargs)):
            # DENY: argument numbers don't match
            return False
        # Compare each arg (anchoring pattern explicitly at end of string)
        for (pattern, arg) in zip(self.args, userargs):
            try:
                if not re.match(pattern + '$', arg):
                    break
            except re.error:
                # DENY: Badly-formed filter
                return False
        else:
            # ALLOW: All arguments matched
            return True

        # DENY: Some arguments did not match
        return False


class PathFilter(CommandFilter):
    """Command filter checking that path arguments are within given dirs

        One can specify the following constraints for command arguments:
            1) pass     - pass an argument as is to the resulting command
            2) some_str - check if an argument is equal to the given string
            3) abs path - check if a path argument is within the given base dir

        A typical rootwrapper filter entry looks like this:
            # cmdname: filter name, raw command, user, arg_i_constraint [, ...]
            chown: PathFilter, /bin/chown, root, nova, /var/lib/images

    """

    def match(self, userargs):
        if not userargs or len(userargs) < 2:
            return False

        command, arguments = userargs[0], userargs[1:]

        equal_args_num = len(self.args) == len(arguments)
        exec_is_valid = super(PathFilter, self).match(userargs)
        args_equal_or_pass = all(
            arg == 'pass' or arg == value
            for arg, value in zip(self.args, arguments)
            if not os.path.isabs(arg)  # arguments not specifying abs paths
        )
        paths_are_within_base_dirs = all(
            os.path.commonprefix([arg, os.path.realpath(value)]) == arg
            for arg, value in zip(self.args, arguments)
            if os.path.isabs(arg)  # arguments specifying abs paths
        )

        return (equal_args_num and
                exec_is_valid and
                args_equal_or_pass and
                paths_are_within_base_dirs)

    def get_command(self, userargs, exec_dirs=[]):
        command, arguments = userargs[0], userargs[1:]

        # convert path values to canonical ones; copy other args as is
        args = [os.path.realpath(value) if os.path.isabs(arg) else value
                for arg, value in zip(self.args, arguments)]

        return super(PathFilter, self).get_command([command] + args,
                                                   exec_dirs)


class KillFilter(CommandFilter):
    """Specific filter for the kill calls.

       1st argument is the user to run /bin/kill under
       2nd argument is the location of the affected executable
           if the argument is not absolute, it is checked against $PATH
       Subsequent arguments list the accepted signals (if any)

       This filter relies on /proc to accurately determine affected
       executable, so it will only work on procfs-capable systems (not OSX).
    """

    def __init__(self, *args):
        super(KillFilter, self).__init__("/bin/kill", *args)

    def match(self, userargs):
        if not userargs or userargs[0] != "kill":
            return False
        args = list(userargs)
        if len(args) == 3:
            # A specific signal is requested
            signal = args.pop(1)
            if signal not in self.args[1:]:
                # Requested signal not in accepted list
                return False
        else:
            if len(args) != 2:
                # Incorrect number of arguments
                return False
            if len(self.args) > 1:
                # No signal requested, but filter requires specific signal
                return False
        try:
            command = os.readlink("/proc/%d/exe" % int(args[1]))
        except (ValueError, OSError):
            # Incorrect PID
            return False

        # NOTE(yufang521247): /proc/PID/exe may have '\0' on the
        # end, because python doen't stop at '\0' when read the
        # target path.
        command = command.partition('\0')[0]

        # NOTE(dprince): /proc/PID/exe may have ' (deleted)' on
        # the end if an executable is updated or deleted
        if command.endswith(" (deleted)"):
            command = command[:-len(" (deleted)")]

        kill_command = self.args[0]

        if os.path.isabs(kill_command):
            return kill_command == command

        return (os.path.isabs(command) and
                kill_command == os.path.basename(command) and
                os.path.dirname(command) in os.environ.get('PATH', ''
                                                           ).split(':'))


class ReadFileFilter(CommandFilter):
    """Specific filter for the utils.read_file_as_root call."""

    def __init__(self, file_path, *args):
        self.file_path = file_path
        super(ReadFileFilter, self).__init__("/bin/cat", "root", *args)

    def match(self, userargs):
        return (userargs == ['cat', self.file_path])


class IpFilter(CommandFilter):
    """Specific filter for the ip utility to that does not match exec."""

    def match(self, userargs):
        if userargs[0] == 'ip':
            if userargs[1] == 'netns':
                return (userargs[2] in ('list', 'add', 'delete'))
            else:
                return True


class EnvFilter(CommandFilter):
    """Specific filter for the env utility.

    Behaves like CommandFilter, except that it handles
    leading env A=B.. strings appropriately.
    """

    def _extract_env(self, arglist):
        """Extract all leading NAME=VALUE arguments from arglist."""

        envs = set()
        for arg in arglist:
            if '=' not in arg:
                break
            envs.add(arg.partition('=')[0])
        return envs

    def __init__(self, exec_path, run_as, *args):
        super(EnvFilter, self).__init__(exec_path, run_as, *args)

        env_list = self._extract_env(self.args)
        # Set exec_path to X when args are in the form of
        # env A=a B=b C=c X Y Z
        if "env" in exec_path and len(env_list) < len(self.args):
            self.exec_path = self.args[len(env_list)]

    def match(self, userargs):
        # ignore leading 'env'
        if userargs[0] == 'env':
            userargs.pop(0)

        # require one additional argument after configured ones
        if len(userargs) < len(self.args):
            return False

        # extract all env args
        user_envs = self._extract_env(userargs)
        filter_envs = self._extract_env(self.args)
        user_command = userargs[len(user_envs):len(user_envs) + 1]

        # match first non-env argument with CommandFilter
        return (super(EnvFilter, self).match(user_command)
                and len(filter_envs) and user_envs == filter_envs)

    def exec_args(self, userargs):
        args = userargs[:]

        # ignore leading 'env'
        if args[0] == 'env':
            args.pop(0)

        # Throw away leading NAME=VALUE arguments
        while args and '=' in args[0]:
            args.pop(0)

        return args

    def get_command(self, userargs, exec_dirs=[]):
        to_exec = self.get_exec(exec_dirs=exec_dirs) or self.exec_path
        return [to_exec] + self.exec_args(userargs)[1:]

    def get_environment(self, userargs):
        env = os.environ.copy()

        # ignore leading 'env'
        if userargs[0] == 'env':
            userargs.pop(0)

        # Handle leading NAME=VALUE pairs
        for a in userargs:
            env_name, equals, env_value = a.partition('=')
            if not equals:
                break
            if env_name and env_value:
                env[env_name] = env_value

        return env


class ChainingFilter(CommandFilter):
    def exec_args(self, userargs):
        return []


class IpNetnsExecFilter(ChainingFilter):
    """Specific filter for the ip utility to that does match exec."""

    def match(self, userargs):
        # Network namespaces currently require root
        # require <ns> argument
        if self.run_as != "root" or len(userargs) < 4:
            return False

        return (userargs[:3] == ['ip', 'netns', 'exec'])

    def exec_args(self, userargs):
        args = userargs[4:]
        if args:
            args[0] = os.path.basename(args[0])
        return args

#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012, Cloudscaling
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

"""nova HACKING file compliance testing

built on top of pep8.py
"""

import fnmatch
import inspect
import logging
import os
import re
import subprocess
import sys
import tokenize
import warnings

import pep8

# Don't need this for testing
logging.disable('LOG')

#N1xx comments
#N2xx except
#N3xx imports
#N4xx docstrings
#N5xx dictionaries/lists
#N6xx calling methods
#N7xx localization
#N8xx git commit messages

IMPORT_EXCEPTIONS = ['sqlalchemy', 'migrate', 'nova.db.sqlalchemy.session']
DOCSTRING_TRIPLE = ['"""', "'''"]
VERBOSE_MISSING_IMPORT = os.getenv('HACKING_VERBOSE_MISSING_IMPORT', 'False')


# Monkey patch broken excluded filter in pep8
def filename_match(filename, patterns, default=True):
    """
    Check if patterns contains a pattern that matches filename.
    If patterns is unspecified, this always returns True.
    """
    if not patterns:
        return default
    return any(fnmatch.fnmatch(filename, pattern) for pattern in patterns)


def excluded(filename):
    """
    Check if options.exclude contains a pattern that matches filename.
    """
    basename = os.path.basename(filename)
    return any((filename_match(filename, pep8.options.exclude,
                               default=False),
                filename_match(basename, pep8.options.exclude,
                               default=False)))


def input_dir(dirname, runner=None):
    """
    Check all Python source files in this directory and all subdirectories.
    """
    dirname = dirname.rstrip('/')
    if excluded(dirname):
        return
    if runner is None:
        runner = pep8.input_file
    for root, dirs, files in os.walk(dirname):
        if pep8.options.verbose:
            print('directory ' + root)
        pep8.options.counters['directories'] += 1
        dirs.sort()
        for subdir in dirs[:]:
            if excluded(os.path.join(root, subdir)):
                dirs.remove(subdir)
        files.sort()
        for filename in files:
            if pep8.filename_match(filename) and not excluded(filename):
                pep8.options.counters['files'] += 1
                runner(os.path.join(root, filename))


def is_import_exception(mod):
    return (mod in IMPORT_EXCEPTIONS or
            any(mod.startswith(m + '.') for m in IMPORT_EXCEPTIONS))


def import_normalize(line):
    # convert "from x import y" to "import x.y"
    # handle "from x import y as z" to "import x.y as z"
    split_line = line.split()
    if (line.startswith("from ") and "," not in line and
           split_line[2] == "import" and split_line[3] != "*" and
           split_line[1] != "__future__" and
           (len(split_line) == 4 or
           (len(split_line) == 6 and split_line[4] == "as"))):
        return "import %s.%s" % (split_line[1], split_line[3])
    else:
        return line


def nova_todo_format(physical_line):
    """Check for 'TODO()'.

    nova HACKING guide recommendation for TODO:
    Include your name with TODOs as in "#TODO(termie)"
    N101
    """
    pos = physical_line.find('TODO')
    pos1 = physical_line.find('TODO(')
    pos2 = physical_line.find('#')  # make sure it's a comment
    if (pos != pos1 and pos2 >= 0 and pos2 < pos):
        return pos, "NOVA N101: Use TODO(NAME)"


def nova_except_format(logical_line):
    """Check for 'except:'.

    nova HACKING guide recommends not using except:
    Do not write "except:", use "except Exception:" at the very least
    N201
    """
    if logical_line.startswith("except:"):
        return 6, "NOVA N201: no 'except:' at least use 'except Exception:'"


def nova_except_format_assert(logical_line):
    """Check for 'assertRaises(Exception'.

    nova HACKING guide recommends not using assertRaises(Exception...):
    Do not use overly broad Exception type
    N202
    """
    if logical_line.startswith("self.assertRaises(Exception"):
        return 1, "NOVA N202: assertRaises Exception too broad"


def nova_one_import_per_line(logical_line):
    """Check for import format.

    nova HACKING guide recommends one import per line:
    Do not import more than one module per line

    Examples:
    BAD: from nova.rpc.common import RemoteError, LOG
    N301
    """
    pos = logical_line.find(',')
    parts = logical_line.split()
    if (pos > -1 and (parts[0] == "import" or
                      parts[0] == "from" and parts[2] == "import") and
        not is_import_exception(parts[1])):
        return pos, "NOVA N301: one import per line"

_missingImport = set([])


def nova_import_module_only(logical_line):
    """Check for import module only.

    nova HACKING guide recommends importing only modules:
    Do not import objects, only modules
    N302 import only modules
    N303 Invalid Import
    N304 Relative Import
    """
    def importModuleCheck(mod, parent=None, added=False):
        """
        If can't find module on first try, recursively check for relative
        imports
        """
        current_path = os.path.dirname(pep8.current_file)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                valid = True
                if parent:
                    if is_import_exception(parent):
                        return
                    parent_mod = __import__(parent, globals(), locals(),
                        [mod], -1)
                    valid = inspect.ismodule(getattr(parent_mod, mod))
                else:
                    __import__(mod, globals(), locals(), [], -1)
                    valid = inspect.ismodule(sys.modules[mod])
                if not valid:
                    if added:
                        sys.path.pop()
                        added = False
                        return logical_line.find(mod), ("NOVA N304: No "
                            "relative  imports. '%s' is a relative import"
                            % logical_line)
                    return logical_line.find(mod), ("NOVA N302: import only "
                        "modules. '%s' does not import a module"
                        % logical_line)

        except (ImportError, NameError) as exc:
            if not added:
                added = True
                sys.path.append(current_path)
                return importModuleCheck(mod, parent, added)
            else:
                name = logical_line.split()[1]
                if name not in _missingImport:
                    if VERBOSE_MISSING_IMPORT != 'False':
                        print >> sys.stderr, ("ERROR: import '%s' in %s "
                                              "failed: %s" %
                            (name, pep8.current_file, exc))
                    _missingImport.add(name)
                added = False
                sys.path.pop()
                return

        except AttributeError:
            # Invalid import
            return logical_line.find(mod), ("NOVA N303: Invalid import, "
                "AttributeError raised")

    # convert "from x import y" to " import x.y"
    # convert "from x import y as z" to " import x.y"
    import_normalize(logical_line)
    split_line = logical_line.split()

    if (logical_line.startswith("import ") and "," not in logical_line and
            (len(split_line) == 2 or
            (len(split_line) == 4 and split_line[2] == "as"))):
        mod = split_line[1]
        return importModuleCheck(mod)

    # TODO(jogo) handle "from x import *"

#TODO(jogo): import template: N305


def nova_import_alphabetical(physical_line, line_number, lines):
    """Check for imports in alphabetical order.

    nova HACKING guide recommendation for imports:
    imports in human alphabetical order
    N306
    """
    # handle import x
    # use .lower since capitalization shouldn't dictate order
    split_line = import_normalize(physical_line.strip()).lower().split()
    split_previous = import_normalize(lines[line_number - 2]
            ).strip().lower().split()
    # with or without "as y"
    length = [2, 4]
    if (len(split_line) in length and len(split_previous) in length and
        split_line[0] == "import" and split_previous[0] == "import"):
        if split_line[1] < split_previous[1]:
            return (0, "NOVA N306: imports not in alphabetical order (%s, %s)"
                % (split_previous[1], split_line[1]))


def nova_docstring_start_space(physical_line):
    """Check for docstring not start with space.

    nova HACKING guide recommendation for docstring:
    Docstring should not start with space
    N401
    """
    pos = max([physical_line.find(i) for i in DOCSTRING_TRIPLE])  # start
    if (pos != -1 and len(physical_line) > pos + 1):
        if (physical_line[pos + 3] == ' '):
            return (pos, "NOVA N401: one line docstring should not start with"
                " a space")


def nova_docstring_one_line(physical_line):
    """Check one line docstring end.

    nova HACKING guide recommendation for one line docstring:
    A one line docstring looks like this and ends in a period.
    N402
    """
    pos = max([physical_line.find(i) for i in DOCSTRING_TRIPLE])  # start
    end = max([physical_line[-4:-1] == i for i in DOCSTRING_TRIPLE])  # end
    if (pos != -1 and end and len(physical_line) > pos + 4):
        if (physical_line[-5] != '.'):
            return pos, "NOVA N402: one line docstring needs a period"


def nova_docstring_multiline_end(physical_line):
    """Check multi line docstring end.

    nova HACKING guide recommendation for docstring:
    Docstring should end on a new line
    N403
    """
    pos = max([physical_line.find(i) for i in DOCSTRING_TRIPLE])  # start
    if (pos != -1 and len(physical_line) == pos):
        print physical_line
        if (physical_line[pos + 3] == ' '):
            return (pos, "NOVA N403: multi line docstring end on new line")


FORMAT_RE = re.compile("%(?:"
                            "%|"           # Ignore plain percents
                            "(\(\w+\))?"   # mapping key
                            "([#0 +-]?"    # flag
                             "(?:\d+|\*)?"  # width
                             "(?:\.\d+)?"   # precision
                             "[hlL]?"       # length mod
                             "\w))")        # type


class LocalizationError(Exception):
    pass


def check_i18n():
    """Generator that checks token stream for localization errors.

    Expects tokens to be ``send``ed one by one.
    Raises LocalizationError if some error is found.
    """
    while True:
        try:
            token_type, text, _, _, line = yield
        except GeneratorExit:
            return
        if (token_type == tokenize.NAME and text == "_" and
            not line.startswith('def _(msg):')):

            while True:
                token_type, text, start, _, _ = yield
                if token_type != tokenize.NL:
                    break
            if token_type != tokenize.OP or text != "(":
                continue  # not a localization call

            format_string = ''
            while True:
                token_type, text, start, _, _ = yield
                if token_type == tokenize.STRING:
                    format_string += eval(text)
                elif token_type == tokenize.NL:
                    pass
                else:
                    break

            if not format_string:
                raise LocalizationError(start,
                    "NOVA N701: Empty localization string")
            if token_type != tokenize.OP:
                raise LocalizationError(start,
                    "NOVA N701: Invalid localization call")
            if text != ")":
                if text == "%":
                    raise LocalizationError(start,
                        "NOVA N702: Formatting operation should be outside"
                        " of localization method call")
                elif text == "+":
                    raise LocalizationError(start,
                        "NOVA N702: Use bare string concatenation instead"
                        " of +")
                else:
                    raise LocalizationError(start,
                        "NOVA N702: Argument to _ must be just a string")

            format_specs = FORMAT_RE.findall(format_string)
            positional_specs = [(key, spec) for key, spec in format_specs
                                            if not key and spec]
            # not spec means %%, key means %(smth)s
            if len(positional_specs) > 1:
                raise LocalizationError(start,
                    "NOVA N703: Multiple positional placeholders")


def nova_localization_strings(logical_line, tokens):
    """Check localization in line.

    N701: bad localization call
    N702: complex expression instead of string as argument to _()
    N703: multiple positional placeholders
    """

    gen = check_i18n()
    next(gen)
    try:
        map(gen.send, tokens)
        gen.close()
    except LocalizationError as e:
        return e.args

#TODO(jogo) Dict and list objects

current_file = ""


def readlines(filename):
    """Record the current file being tested."""
    pep8.current_file = filename
    return open(filename).readlines()


def add_nova():
    """Monkey patch in nova guidelines.

    Look for functions that start with nova_  and have arguments
    and add them to pep8 module
    Assumes you know how to write pep8.py checks
    """
    for name, function in globals().items():
        if not inspect.isfunction(function):
            continue
        args = inspect.getargspec(function)[0]
        if args and name.startswith("nova"):
            exec("pep8.%s = %s" % (name, name))


def once_git_check_commit_title():
    """Check git commit messages.

    nova HACKING recommends not referencing a bug or blueprint in first line,
    it should provide an accurate description of the change
    N801
    N802 Title limited to 50 chars
    """
    #Get title of most recent commit

    subp = subprocess.Popen(['git', 'log', '--no-merges', '--pretty=%s', '-1'],
            stdout=subprocess.PIPE)
    title = subp.communicate()[0]
    if subp.returncode:
        raise Exception("git log failed with code %s" % subp.returncode)

    #From https://github.com/openstack/openstack-ci-puppet
    #       /blob/master/modules/gerrit/manifests/init.pp#L74
    #Changeid|bug|blueprint
    git_keywords = (r'(I[0-9a-f]{8,40})|'
                    '([Bb]ug|[Ll][Pp])[\s\#:]*(\d+)|'
                    '([Bb]lue[Pp]rint|[Bb][Pp])[\s\#:]*([A-Za-z0-9\\-]+)')
    GIT_REGEX = re.compile(git_keywords)

    error = False
    #NOTE(jogo) if match regex but over 3 words, acceptable title
    if GIT_REGEX.search(title) is not None and len(title.split()) <= 3:
        print ("N801: git commit title ('%s') should provide an accurate "
               "description of the change, not just a reference to a bug "
               "or blueprint" % title.strip())
        error = True
    if len(title.decode('utf-8')) > 72:
        print ("N802: git commit title ('%s') should be under 50 chars"
                % title.strip())
        error = True
    return error

if __name__ == "__main__":
    #include nova path
    sys.path.append(os.getcwd())
    #Run once tests (not per line)
    once_error = once_git_check_commit_title()
    #NOVA error codes start with an N
    pep8.ERRORCODE_REGEX = re.compile(r'[EWN]\d{3}')
    add_nova()
    pep8.current_file = current_file
    pep8.readlines = readlines
    pep8.excluded = excluded
    pep8.input_dir = input_dir
    try:
        pep8._main()
        sys.exit(once_error)
    finally:
        if len(_missingImport) > 0:
            print >> sys.stderr, ("%i imports missing in this test environment"
                    % len(_missingImport))

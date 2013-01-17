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
START_DOCSTRING_TRIPLE = ['u"""', 'r"""', '"""', "u'''", "r'''", "'''"]
END_DOCSTRING_TRIPLE = ['"""', "'''"]
VERBOSE_MISSING_IMPORT = os.getenv('HACKING_VERBOSE_MISSING_IMPORT', 'False')


# Monkey patch broken excluded filter in pep8
# See https://github.com/jcrocholl/pep8/pull/111
def excluded(self, filename):
    """Check if options.exclude contains a pattern that matches filename."""
    basename = os.path.basename(filename)
    return any((pep8.filename_match(filename, self.options.exclude,
                               default=False),
                pep8.filename_match(basename, self.options.exclude,
                               default=False)))


def input_dir(self, dirname):
    """Check all files in this directory and all subdirectories."""
    dirname = dirname.rstrip('/')
    if self.excluded(dirname):
        return 0
    counters = self.options.report.counters
    verbose = self.options.verbose
    filepatterns = self.options.filename
    runner = self.runner
    for root, dirs, files in os.walk(dirname):
        if verbose:
            print('directory ' + root)
        counters['directories'] += 1
        for subdir in sorted(dirs):
            if self.excluded(os.path.join(root, subdir)):
                dirs.remove(subdir)
        for filename in sorted(files):
            # contain a pattern that matches?
            if ((pep8.filename_match(filename, filepatterns) and
                 not self.excluded(filename))):
                runner(os.path.join(root, filename))


def is_import_exception(mod):
    return (mod in IMPORT_EXCEPTIONS or
            any(mod.startswith(m + '.') for m in IMPORT_EXCEPTIONS))


def import_normalize(line):
    # convert "from x import y" to "import x.y"
    # handle "from x import y as z" to "import x.y as z"
    split_line = line.split()
    if ("import" in line and line.startswith("from ") and "," not in line and
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

    Okay: #TODO(sdague)
    N101: #TODO fail
    """
    # TODO(sdague): TODO check shouldn't fail inside of space
    pos = physical_line.find('TODO')
    pos1 = physical_line.find('TODO(')
    pos2 = physical_line.find('#')  # make sure it's a comment
    # TODO(sdague): should be smarter on this test
    this_test = physical_line.find('N101: #TODO fail')
    if pos != pos1 and pos2 >= 0 and pos2 < pos and this_test == -1:
        return pos, "N101: Use TODO(NAME)"


def nova_except_format(logical_line):
    r"""Check for 'except:'.

    nova HACKING guide recommends not using except:
    Do not write "except:", use "except Exception:" at the very least

    Okay: except Exception:
    N201: except:
    """
    if logical_line.startswith("except:"):
        yield 6, "N201: no 'except:' at least use 'except Exception:'"


def nova_except_format_assert(logical_line):
    r"""Check for 'assertRaises(Exception'.

    nova HACKING guide recommends not using assertRaises(Exception...):
    Do not use overly broad Exception type

    Okay: self.assertRaises(NovaException)
    N202: self.assertRaises(Exception)
    """
    if logical_line.startswith("self.assertRaises(Exception"):
        yield 1, "N202: assertRaises Exception too broad"


def nova_one_import_per_line(logical_line):
    r"""Check for import format.

    nova HACKING guide recommends one import per line:
    Do not import more than one module per line

    Examples:
    Okay: from nova.rpc.common import RemoteError
    N301: from nova.rpc.common import RemoteError, LOG
    """
    pos = logical_line.find(',')
    parts = logical_line.split()
    if (pos > -1 and (parts[0] == "import" or
                      parts[0] == "from" and parts[2] == "import") and
        not is_import_exception(parts[1])):
        yield pos, "N301: one import per line"

_missingImport = set([])


def nova_import_module_only(logical_line):
    r"""Check for import module only.

    nova HACKING guide recommends importing only modules:
    Do not import objects, only modules

    Okay: from os import path
    N302  from os.path import mkdir as mkdir2
    N303  import bubba
    N304  import blueblue
    """
    # N302 import only modules
    # N303 Invalid Import
    # N304 Relative Import

    # TODO(sdague) actually get these tests working
    def importModuleCheck(mod, parent=None, added=False):
        """Import Module helper function.

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
                        return logical_line.find(mod), ("N304: No "
                            "relative  imports. '%s' is a relative import"
                            % logical_line)
                    return logical_line.find(mod), ("N302: import only "
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
            return logical_line.find(mod), ("N303: Invalid import, "
                "AttributeError raised")

    # convert "from x import y" to " import x.y"
    # convert "from x import y as z" to " import x.y"
    import_normalize(logical_line)
    split_line = logical_line.split()

    if (logical_line.startswith("import ") and "," not in logical_line and
            (len(split_line) == 2 or
            (len(split_line) == 4 and split_line[2] == "as"))):
        mod = split_line[1]
        rval = importModuleCheck(mod)
        if rval is not None:
            yield rval

    # TODO(jogo) handle "from x import *"

#TODO(jogo): import template: N305


def nova_import_alphabetical(logical_line, blank_lines, previous_logical,
                             indent_level, previous_indent_level):
    r"""Check for imports in alphabetical order.

    nova HACKING guide recommendation for imports:
    imports in human alphabetical order

    Okay: import os\nimport sys\n\nimport nova\nfrom nova import test
    N306: import sys\nimport os
    """
    # handle import x
    # use .lower since capitalization shouldn't dictate order
    split_line = import_normalize(logical_line.strip()).lower().split()
    split_previous = import_normalize(previous_logical.strip()).lower().split()

    if blank_lines < 1 and indent_level == previous_indent_level:
        length = [2, 4]
        if (len(split_line) in length and len(split_previous) in length and
            split_line[0] == "import" and split_previous[0] == "import"):
            if split_line[1] < split_previous[1]:
                yield (0, "N306: imports not in alphabetical order (%s, %s)"
                       % (split_previous[1], split_line[1]))


def nova_import_no_db_in_virt(logical_line, filename):
    """Check for db calls from nova/virt

    As of grizzly-2 all the database calls have been removed from
    nova/virt, and we want to keep it that way.

    N307
    """
    if "nova/virt" in filename and not filename.endswith("fake.py"):
        if logical_line.startswith("from nova import db"):
            yield (0, "N307: nova.db import not allowed in nova/virt/*")


def in_docstring_position(previous_logical):
    return (previous_logical.startswith("def ") or
        previous_logical.startswith("class "))


def nova_docstring_start_space(physical_line, previous_logical):
    r"""Check for docstring not start with space.

    nova HACKING guide recommendation for docstring:
    Docstring should not start with space

    Okay: def foo():\n    '''This is good.'''
    N401: def foo():\n    ''' This is not.'''
    """
    # short circuit so that we don't fail on our own fail test
    # when running under external pep8
    if physical_line.find("N401: def foo()") != -1:
        return

    # it's important that we determine this is actually a docstring,
    # and not a doc block used somewhere after the first line of a
    # function def
    if in_docstring_position(previous_logical):
        pos = max([physical_line.find(i) for i in START_DOCSTRING_TRIPLE])
        if pos != -1 and len(physical_line) > pos + 4:
            if physical_line[pos + 3] == ' ':
                return (pos, "N401: docstring should not start with"
                        " a space")


def nova_docstring_one_line(physical_line):
    r"""Check one line docstring end.

    nova HACKING guide recommendation for one line docstring:
    A one line docstring looks like this and ends in punctuation.

    Okay: '''This is good.'''
    N402: '''This is not'''
    N402: '''Bad punctuation,'''
    """
    #TODO(jogo) make this apply to multi line docstrings as well
    line = physical_line.lstrip()

    if line.startswith('"') or line.startswith("'"):
        pos = max([line.find(i) for i in START_DOCSTRING_TRIPLE])  # start
        end = max([line[-4:-1] == i for i in END_DOCSTRING_TRIPLE])  # end

        if pos != -1 and end and len(line) > pos + 4:
            if line[-5] not in ['.', '?', '!']:
                return pos, "N402: one line docstring needs punctuation."


def nova_docstring_multiline_end(physical_line, previous_logical):
    r"""Check multi line docstring end.

    nova HACKING guide recommendation for docstring:
    Docstring should end on a new line

    Okay: '''foobar\nfoo\nbar\n'''
    N403: def foo():\n'''foobar\nfoo\nbar\n   d'''\n\n
    """
    if in_docstring_position(previous_logical):
        pos = max(physical_line.find(i) for i in END_DOCSTRING_TRIPLE)
        if pos != -1 and len(physical_line) == pos + 4:
            if physical_line.strip() not in START_DOCSTRING_TRIPLE:
                return (pos, "N403: multi line docstring end on new line")


def nova_docstring_multiline_start(physical_line, previous_logical, tokens):
    r"""Check multi line docstring start with summary.

    nova HACKING guide recommendation for docstring:
    Docstring should start with A multi line docstring has a one-line summary

    Okay: '''foobar\nfoo\nbar\n'''
    N404: def foo():\n'''\nfoo\nbar\n''' \n\n
    """
    if in_docstring_position(previous_logical):
        pos = max([physical_line.find(i) for i in START_DOCSTRING_TRIPLE])
        # start of docstring when len(tokens)==0
        if len(tokens) == 0 and pos != -1 and len(physical_line) == pos + 4:
            if physical_line.strip() in START_DOCSTRING_TRIPLE:
                return (pos, "N404: multi line docstring "
                        "should start with a summary")


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
                    "N701: Empty localization string")
            if token_type != tokenize.OP:
                raise LocalizationError(start,
                    "N701: Invalid localization call")
            if text != ")":
                if text == "%":
                    raise LocalizationError(start,
                        "N702: Formatting operation should be outside"
                        " of localization method call")
                elif text == "+":
                    raise LocalizationError(start,
                        "N702: Use bare string concatenation instead"
                        " of +")
                else:
                    raise LocalizationError(start,
                        "N702: Argument to _ must be just a string")

            format_specs = FORMAT_RE.findall(format_string)
            positional_specs = [(key, spec) for key, spec in format_specs
                                            if not key and spec]
            # not spec means %%, key means %(smth)s
            if len(positional_specs) > 1:
                raise LocalizationError(start,
                    "N703: Multiple positional placeholders")


def nova_localization_strings(logical_line, tokens):
    r"""Check localization in line.

    Okay: _("This is fine")
    Okay: _("This is also fine %s")
    N701: _('')
    N702: _("Bob" + " foo")
    N702: _("Bob %s" % foo)
    # N703 check is not quite right, disabled by removing colon
    N703 _("%s %s" % (foo, bar))
    """
    # TODO(sdague) actually get these tests working
    gen = check_i18n()
    next(gen)
    try:
        map(gen.send, tokens)
        gen.close()
    except LocalizationError as e:
        yield e.args

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

imports_on_separate_lines_N301_compliant = r"""
    Imports should usually be on separate lines.

    Okay: import os\nimport sys
    E401: import sys, os

    N301: from subprocess import Popen, PIPE
    Okay: from myclas import MyClass
    Okay: from foo.bar.yourclass import YourClass
    Okay: import myclass
    Okay: import foo.bar.yourclass
    """

if __name__ == "__main__":
    #include nova path
    sys.path.append(os.getcwd())
    #Run once tests (not per line)
    once_error = once_git_check_commit_title()
    #NOVA error codes start with an N
    pep8.SELFTEST_REGEX = re.compile(r'(Okay|[EWN]\d{3}):\s(.*)')
    pep8.ERRORCODE_REGEX = re.compile(r'[EWN]\d{3}')
    add_nova()
    pep8.current_file = current_file
    pep8.readlines = readlines
    pep8.StyleGuide.excluded = excluded
    pep8.StyleGuide.input_dir = input_dir
    # we need to kill this doctring otherwise the self tests fail
    pep8.imports_on_separate_lines.__doc__ = \
        imports_on_separate_lines_N301_compliant

    try:
        pep8._main()
        sys.exit(once_error)
    finally:
        if len(_missingImport) > 0:
            print >> sys.stderr, ("%i imports missing in this test environment"
                    % len(_missingImport))

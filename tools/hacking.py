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
import os
import re
import sys
import tokenize
import traceback

import pep8


#N1xx comments
#N2xx except
#N3xx imports
#N4xx docstrings
#N5xx dictionaries/lists
#N6xx Calling methods
#N7xx localization

IMPORT_EXCEPTIONS = ['sqlalchemy', 'migrate', 'nova.db.sqlalchemy.session']


def is_import_exception(mod):
    return mod in IMPORT_EXCEPTIONS or \
        any(mod.startswith(m + '.') for m in IMPORT_EXCEPTIONS)


def nova_todo_format(physical_line):
    """
    nova HACKING guide recommendation for TODO:
    Include your name with TODOs as in "#TODO(termie)"
    N101
    """
    pos = physical_line.find('TODO')
    pos1 = physical_line.find('TODO(')
    pos2 = physical_line.find('#')  # make sure its a comment
    if (pos != pos1 and pos2 >= 0 and pos2 < pos):
        return pos, "NOVA N101: Use TODO(NAME)"


def nova_except_format(logical_line):
    """
    nova HACKING guide recommends not using except:
    Do not write "except:", use "except Exception:" at the very least
    N201
    """
    if logical_line.startswith("except:"):
        return 6, "NOVA N201: no 'except:' at least use 'except Exception:'"


def nova_except_format(logical_line):
    """
    nova HACKING guide recommends not using assertRaises(Exception...):
    Do not use overly broad Exception type
    N202
    """
    if logical_line.startswith("self.assertRaises(Exception"):
        return 1, "NOVA N202: assertRaises Exception too broad"


def nova_one_import_per_line(logical_line):
    """
    nova HACKING guide recommends one import per line:
    Do not import more than one module per line

    Examples:
    BAD: from nova.rpc.common import RemoteError, LOG
    N301
    """
    pos = logical_line.find(',')
    parts = logical_line.split()
    if pos > -1 and (parts[0] == "import" or
       parts[0] == "from" and parts[2] == "import") and \
       not is_import_exception(parts[1]):
        return pos, "NOVA N301: one import per line"


def nova_import_module_only(logical_line):
    """
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
            valid = True
            if parent:
                if is_import_exception(parent):
                    return
                parent_mod = __import__(parent, globals(), locals(), [mod], -1)
                valid = inspect.ismodule(getattr(parent_mod, mod))
            else:
                __import__(mod, globals(), locals(), [], -1)
                valid = inspect.ismodule(sys.modules[mod])
            if not valid:
                if added:
                    sys.path.pop()
                    added = False
                    return logical_line.find(mod), ("NOVA N304: No relative "
                        "imports. '%s' is a relative import" % logical_line)

                return logical_line.find(mod), ("NOVA N302: import only "
                    "modules. '%s' does not import a module" % logical_line)

        except (ImportError, NameError) as exc:
            if not added:
                added = True
                sys.path.append(current_path)
                return importModuleCheck(mod, parent, added)
            else:
                print >> sys.stderr, ("ERROR: import '%s' failed: %s" %
                                                       (logical_line, exc))
                added = False
                sys.path.pop()
                return

        except AttributeError:
            # Invalid import
            return logical_line.find(mod), ("NOVA N303: Invalid import, "
                "AttributeError raised")

    split_line = logical_line.split()

    # handle "import x"
    # handle "import x as y"
    if (logical_line.startswith("import ") and "," not in logical_line and
            (len(split_line) == 2 or
            (len(split_line) == 4 and split_line[2] == "as"))):
        mod = split_line[1]
        return importModuleCheck(mod)

    # handle "from x import y"
    # handle "from x import y as z"
    elif (logical_line.startswith("from ") and "," not in logical_line and
           split_line[2] == "import" and split_line[3] != "*" and
           split_line[1] != "__future__" and
           (len(split_line) == 4 or
           (len(split_line) == 6  and split_line[4] == "as"))):
        mod = split_line[3]
        return importModuleCheck(mod, split_line[1])

    # TODO(jogo) handle "from x import *"


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


def check_l18n():
    """Generator that checks token stream for localization errors.

    Expects tokens to be ``send``ed one by one.
    Raises LocalizationError if some error is found.
    """
    while True:
        try:
            token_type, text, _, _, _ = yield
        except GeneratorExit:
            return
        if token_type == tokenize.NAME and text == "_":
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

    gen = check_l18n()
    next(gen)
    try:
        map(gen.send, tokens)
        gen.close()
    except LocalizationError as e:
        return e.args

#TODO(jogo) Dict and list objects

current_file = ""


def readlines(filename):
    """
    record the current file being tested
    """
    pep8.current_file = filename
    return open(filename).readlines()


def add_nova():
    """
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

if __name__ == "__main__":
    #include nova path
    sys.path.append(os.getcwd())
    #NOVA error codes start with an N
    pep8.ERRORCODE_REGEX = re.compile(r'[EWN]\d{3}')
    add_nova()
    pep8.current_file = current_file
    pep8.readlines = readlines
    pep8._main()

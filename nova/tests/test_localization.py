#!/usr/bin/env python
# -*- coding: utf-8 -*-

import glob
import logging
import os
import re
import sys

import nova
from nova import test

LOG = logging.getLogger('nova.tests.localization_unittest')


class LocalizationTestCase(test.TestCase):
    def setUp(self):
        super(LocalizationTestCase, self).setUp()

    def tearDown(self):
        super(LocalizationTestCase, self).tearDown()

    def test_multiple_positional_format_placeholders(self):
        pat = re.compile("\W_\(")
        single_pat = re.compile("\W%\W")
        root_path = os.path.dirname(nova.__file__)
        problems = {}
        for root, dirs, files in os.walk(root_path):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                pth = os.path.join(root, fname)
                txt = fulltext = file(pth).read()
                txt_lines = fulltext.splitlines()
                if not pat.search(txt):
                    continue
                problems[pth] = []
                pos = txt.find("_(")
                while pos > -1:
                    # Make sure that this isn't part of a dunder;
                    # e.g., __init__(...
                    # or something like 'self.assert_(...'
                    test_txt = txt[pos - 1: pos + 10]
                    if not (pat.search(test_txt)):
                        txt = txt[pos + 2:]
                        pos = txt.find("_(")
                        continue
                    pos += 2
                    txt = txt[pos:]
                    innerChars = []
                    # Count pairs of open/close parens until _() closing
                    # paren is found.
                    parenCount = 1
                    pos = 0
                    while parenCount > 0:
                        char = txt[pos]
                        if char == "(":
                            parenCount += 1
                        elif char == ")":
                            parenCount -= 1
                        innerChars.append(char)
                        pos += 1
                    inner_all = "".join(innerChars)
                    # Filter out '%%' and '%('
                    inner = inner_all.replace("%%", "").replace("%(", "")
                    # Filter out the single '%' operators
                    inner = single_pat.sub("", inner)
                    # Within the remaining content, count %
                    fmtCount = inner.count("%")
                    if fmtCount > 1:
                        inner_first = inner_all.splitlines()[0]
                        lns = ["%s" % (p + 1)
                                for p, t in enumerate(txt_lines)
                                if inner_first in t]
                        lnums = ", ".join(lns)
                        # Using ugly string concatenation to avoid having
                        # this test fail itself.
                        inner_all = "_" + "(" + "%s" % inner_all
                        problems[pth].append("Line: %s Text: %s" %
                                (lnums, inner_all))
                    # Look for more
                    pos = txt.find("_(")
                if not problems[pth]:
                    del problems[pth]
        if problems:
            out = ["Problem(s) found in localized string formatting",
                    "(see http://www.gnu.org/software/hello/manual/"
                    "gettext/Python.html for more information)",
                    "",
                    "    ------------ Files to fix ------------"]
            for pth in problems:
                out.append("    %s:" % pth)
                for val in set(problems[pth]):
                    out.append("        %s" % val)
            raise AssertionError("\n".join(out))

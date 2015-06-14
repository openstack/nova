# Copyright 2013 Red Hat, Inc.
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

"""Provides Jinja Views

This module provides views that utilize the Jinja templating
system for serialization.  For more information on Jinja, please
see http://jinja.pocoo.org/ .
"""

import copy

import jinja2


class JinjaView(object):
    """A Jinja View

    This view renders the given model using the provided Jinja
    template.  The template can be given in various ways.
    If the `VIEw_TEXT` property is defined, that is used as template.
    Othewise, if a `path` parameter is passed to the constructor, that
    is used to load a file containing the template.  If the `path`
    parameter is None, the `text` parameter is used as the template.

    The leading newline character and trailing newline character are stripped
    from the template (provided they exist).  Baseline indentation is
    also stripped from each line.  The baseline indentation is determined by
    checking the indentation of the first line, after stripping off the leading
    newline (if any).

    :param str path: the path to the Jinja template
    :param str text: the text of the Jinja template
    """

    def __init__(self, path=None, text=None):
        try:
            self._text = self.VIEW_TEXT
        except AttributeError:
            if path is not None:
                with open(path, 'r') as f:
                    self._text = f.read()
            elif text is not None:
                self._text = text
            else:
                self._text = ""

        if self._text[0] == "\n":
            self._text = self._text[1:]

        newtext = self._text.lstrip()
        amt = len(self._text) - len(newtext)
        if (amt > 0):
            base_indent = self._text[0:amt]
            lines = self._text.splitlines()
            newlines = []
            for line in lines:
                if line.startswith(base_indent):
                    newlines.append(line[amt:])
                else:
                    newlines.append(line)
            self._text = "\n".join(newlines)

        if self._text[-1] == "\n":
            self._text = self._text[:-1]

        self._regentemplate = True
        self._templatecache = None

    def __call__(self, model):
        return self.template.render(**model)

    def __deepcopy__(self, memodict):
        res = object.__new__(JinjaView)
        res._text = copy.deepcopy(self._text, memodict)

        # regenerate the template on a deepcopy
        res._regentemplate = True
        res._templatecache = None

        return res

    @property
    def template(self):
        """Get the Compiled Template

        Gets the compiled template, using a cached copy if possible
        (stored in attr:`_templatecache`) or otherwise recompiling
        the template if the compiled template is not present or is
        invalid (due to attr:`_regentemplate` being set to True).

        :returns: the compiled Jinja template
        :rtype: :class:`jinja2.Template`
        """

        if self._templatecache is None or self._regentemplate:
            self._templatecache = jinja2.Template(self._text)
            self._regentemplate = False

        return self._templatecache

    def _gettext(self):
        """Get the Template Text

        Gets the text of the current template

        :returns: the text of the Jinja template
        :rtype: str
        """

        return self._text

    def _settext(self, textval):
        """Set the Template Text

        Sets the text of the current template, marking it
        for recompilation next time the compiled template
        is retrived via attr:`template` .

        :param str textval: the new text of the Jinja template
        """

        self._text = textval
        self.regentemplate = True

    text = property(_gettext, _settext)

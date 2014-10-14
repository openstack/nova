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

"""Provides Report classes

This module defines various classes representing reports and report sections.
All reports take the form of a report class containing various report
sections.
"""

from nova.openstack.common.report.views.text import header as header_views


class BasicReport(object):
    """A Basic Report

    A Basic Report consists of a collection of :class:`ReportSection`
    objects, each of which contains a top-level model and generator.
    It collects these sections into a cohesive report which may then
    be serialized by calling :func:`run`.
    """

    def __init__(self):
        self.sections = []
        self._state = 0

    def add_section(self, view, generator, index=None):
        """Add a section to the report

        This method adds a section with the given view and
        generator to the report.  An index may be specified to
        insert the section at a given location in the list;
        If no index is specified, the section is appended to the
        list.  The view is called on the model which results from
        the generator when the report is run.  A generator is simply
        a method or callable object which takes no arguments and
        returns a :class:`openstack.common.report.models.base.ReportModel`
        or similar object.

        :param view: the top-level view for the section
        :param generator: the method or class which generates the model
        :param index: the index at which to insert the section
                      (or None to append it)
        :type index: int or None
        """

        if index is None:
            self.sections.append(ReportSection(view, generator))
        else:
            self.sections.insert(index, ReportSection(view, generator))

    def run(self):
        """Run the report

        This method runs the report, having each section generate
        its data and serialize itself before joining the sections
        together.  The BasicReport accomplishes the joining
        by joining the serialized sections together with newlines.

        :rtype: str
        :returns: the serialized report
        """

        return "\n".join(str(sect) for sect in self.sections)


class ReportSection(object):
    """A Report Section

    A report section contains a generator and a top-level view. When something
    attempts to serialize the section by calling str() on it, the section runs
    the generator and calls the view on the resulting model.

    .. seealso::

       Class :class:`BasicReport`
           :func:`BasicReport.add_section`

    :param view: the top-level view for this section
    :param generator: the generator for this section
      (any callable object which takes no parameters and returns a data model)
    """

    def __init__(self, view, generator):
        self.view = view
        self.generator = generator

    def __str__(self):
        return self.view(self.generator())


class ReportOfType(BasicReport):
    """A Report of a Certain Type

    A ReportOfType has a predefined type associated with it.
    This type is automatically propagated down to the each of
    the sections upon serialization by wrapping the generator
    for each section.

    .. seealso::

       Class :class:`openstack.common.report.models.with_default_view.ModelWithDefaultView` # noqa
          (the entire class)

       Class :class:`openstack.common.report.models.base.ReportModel`
           :func:`openstack.common.report.models.base.ReportModel.set_current_view_type` # noqa

    :param str tp: the type of the report
    """

    def __init__(self, tp):
        self.output_type = tp
        super(ReportOfType, self).__init__()

    def add_section(self, view, generator, index=None):
        def with_type(gen):
            def newgen():
                res = gen()
                try:
                    res.set_current_view_type(self.output_type)
                except AttributeError:
                    pass

                return res
            return newgen

        super(ReportOfType, self).add_section(
            view,
            with_type(generator),
            index
        )


class TextReport(ReportOfType):
    """A Human-Readable Text Report

    This class defines a report that is designed to be read by a human
    being.  It has nice section headers, and a formatted title.

    :param str name: the title of the report
    """

    def __init__(self, name):
        super(TextReport, self).__init__('text')
        self.name = name
        # add a title with a generator that creates an empty result model
        self.add_section(name, lambda: ('|' * 72) + "\n\n")

    def add_section(self, heading, generator, index=None):
        """Add a section to the report

        This method adds a section with the given title, and
        generator to the report.  An index may be specified to
        insert the section at a given location in the list;
        If no index is specified, the section is appended to the
        list.  The view is called on the model which results from
        the generator when the report is run.  A generator is simply
        a method or callable object which takes no arguments and
        returns a :class:`openstack.common.report.models.base.ReportModel`
        or similar object.

        The model is told to serialize as text (if possible) at serialization
        time by wrapping the generator.  The view model's attached view
        (if any) is wrapped in a
        :class:`openstack.common.report.views.text.header.TitledView`

        :param str heading: the title for the section
        :param generator: the method or class which generates the model
        :param index: the index at which to insert the section
                      (or None to append)
        :type index: int or None
        """

        super(TextReport, self).add_section(header_views.TitledView(heading),
                                            generator,
                                            index)

# Copyright (C) 2014 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
This provides a sphinx extension able to render the source/support-matrix.ini
file into the developer documentation.

It is used via a single directive in the .rst file

  .. support_matrix::

"""

import re

from six.moves import configparser

from docutils import nodes
from docutils.parsers import rst


class SupportMatrix(object):
    """Represents the entire support matrix for Nova virt drivers
    """

    def __init__(self):
        # List of SupportMatrixFeature instances, describing
        # all the features present in Nova virt drivers
        self.features = []

        # Dict of (name, SupportMatrixTarget) enumerating
        # all the hypervisor drivers that have data recorded
        # for them in self.features. The 'name' dict key is
        # the value from the SupportMatrixTarget.key attribute
        self.targets = {}


class SupportMatrixFeature(object):

    STATUS_MANDATORY = "mandatory"
    STATUS_CHOICE = "choice"
    STATUS_CONDITION = "condition"
    STATUS_OPTIONAL = "optional"

    STATUS_ALL = [STATUS_MANDATORY, STATUS_CHOICE,
                  STATUS_CONDITION, STATUS_OPTIONAL]

    def __init__(self, key, title, status=STATUS_OPTIONAL,
                 group=None, notes=None):
        # A unique key (eg 'foo.bar.wizz') to identify the feature
        self.key = key
        # A human friendly short title for the feature
        self.title = title
        # One of the status constants
        self.status = status
        # Detail string if status was choice/condition
        self.group = group
        # Arbitrarily long string describing the feature in detail
        self.notes = notes
        # Dict of (name, SupportMatrixImplementation) detailing
        # the implementation for each hypervisor driver. The
        # 'name' dict key is the value from SupportMatrixTarget.key
        # for the hypervisor in question
        self.implementations = {}


class SupportMatrixImplementation(object):

    STATUS_COMPLETE = "complete"
    STATUS_PARTIAL = "partial"
    STATUS_MISSING = "missing"

    STATUS_ALL = [STATUS_COMPLETE, STATUS_PARTIAL, STATUS_MISSING]

    def __init__(self, status=STATUS_MISSING, notes=None):
        # One of the status constants detailing the implementation
        # level
        self.status = status
        # Arbitrary string describing any caveats of the implementation.
        # Mandatory if status is 'partial', optional otherwise.
        self.notes = notes


class SupportMatrixTarget(object):

    def __init__(self, key, title, driver, hypervisor=None, architecture=None):
        """:param key: Unique identifier for the hypervisor driver
        :param title: Human friendly name of the hypervisor
        :param driver: Name of the Nova driver
        :param hypervisor: (optional) Name of the hypervisor, if many
        :param architecture: (optional) Name of the architecture, if many
        """
        self.key = key
        self.title = title
        self.driver = driver
        self.hypervisor = hypervisor
        self.architecture = architecture


class SupportMatrixDirective(rst.Directive):

    option_spec = {
        'support-matrix': unicode,
    }

    def run(self):
        matrix = self._load_support_matrix()
        return self._build_markup(matrix)

    def _load_support_matrix(self):
        """Reads the support-matrix.ini file and populates an instance
        of the SupportMatrix class with all the data.

        :returns: SupportMatrix instance
        """

        cfg = configparser.SafeConfigParser()
        env = self.state.document.settings.env
        fname = self.options.get("support-matrix",
                                 "support-matrix.ini")
        rel_fpath, fpath = env.relfn2path(fname)
        with open(fpath) as fp:
            cfg.readfp(fp)

        # This ensures that the docs are rebuilt whenever the
        # .ini file changes
        env.note_dependency(rel_fpath)

        matrix = SupportMatrix()

        # The 'targets' section is special - it lists all the
        # hypervisors that this file records data for
        for item in cfg.options("targets"):
            if not item.startswith("driver-impl-"):
                continue

            # The driver string will optionally contain
            # a hypervisor and architecture qualifier
            # so we expect between 1 and 3 components
            # in the name
            key = item[12:]
            title = cfg.get("targets", item)
            name = key.split("-")
            if len(name) == 1:
                target = SupportMatrixTarget(key,
                                             title,
                                             name[0])
            elif len(name) == 2:
                target = SupportMatrixTarget(key,
                                             title,
                                             name[0],
                                             name[1])
            elif len(name) == 3:
                target = SupportMatrixTarget(key,
                                             title,
                                             name[0],
                                             name[1],
                                             name[2])
            else:
                raise Exception("'%s' field is malformed in '[%s]' section" %
                                (item, "DEFAULT"))

            matrix.targets[key] = target

        # All sections except 'targets' describe some feature of
        # the Nova hypervisor driver implementation
        for section in cfg.sections():
            if section == "targets":
                continue
            if not cfg.has_option(section, "title"):
                raise Exception(
                    "'title' field missing in '[%s]' section" % section)

            title = cfg.get(section, "title")

            status = SupportMatrixFeature.STATUS_OPTIONAL
            if cfg.has_option(section, "status"):
                # The value is a string  "status(group)" where
                # the 'group' part is optional
                status = cfg.get(section, "status")
                offset = status.find("(")
                group = None
                if offset != -1:
                    group = status[offset + 1:-1]
                    status = status[0:offset]

                if status not in SupportMatrixFeature.STATUS_ALL:
                    raise Exception(
                        "'status' field value '%s' in ['%s']"
                        "section must be %s" %
                        (status, section,
                         ",".join(SupportMatrixFeature.STATUS_ALL)))

            notes = None
            if cfg.has_option(section, "notes"):
                notes = cfg.get(section, "notes")
            feature = SupportMatrixFeature(section,
                                           title,
                                           status,
                                           group,
                                           notes)

            # Now we've got the basic feature details, we must process
            # the hypervisor driver implementation for each feature
            for item in cfg.options(section):
                if not item.startswith("driver-impl-"):
                    continue

                key = item[12:]
                if key not in matrix.targets:
                    raise Exception(
                        "Driver impl '%s' in '[%s]' not declared" %
                        (item, section))

                status = cfg.get(section, item)
                if status not in SupportMatrixImplementation.STATUS_ALL:
                    raise Exception(
                        "'%s' value '%s' in '[%s]' section must be %s" %
                        (item, status, section,
                         ",".join(SupportMatrixImplementation.STATUS_ALL)))

                noteskey = "driver-notes-" + item[12:]
                notes = None
                if cfg.has_option(section, noteskey):
                    notes = cfg.get(section, noteskey)

                target = matrix.targets[key]
                impl = SupportMatrixImplementation(status,
                                                   notes)
                feature.implementations[target.key] = impl

            for key in matrix.targets:
                if key not in feature.implementations:
                    raise Exception("'%s' missing in '[%s]' section" %
                                    (target.key, section))

            matrix.features.append(feature)

        return matrix

    def _build_markup(self, matrix):
        """Constructs the docutils content for the support matrix
        """
        content = []
        self._build_summary(matrix, content)
        self._build_details(matrix, content)
        return content

    def _build_summary(self, matrix, content):
        """Constructs the docutils content for the summary of
        the support matrix.

        The summary consists of a giant table, with one row
        for each feature, and a column for each hypervisor
        driver. It provides an 'at a glance' summary of the
        status of each driver
        """

        summarytitle = nodes.subtitle(text="Summary")
        summary = nodes.table()
        cols = len(matrix.targets.keys())
        cols += 2
        summarygroup = nodes.tgroup(cols=cols)
        summarybody = nodes.tbody()
        summaryhead = nodes.thead()

        for i in range(cols):
            summarygroup.append(nodes.colspec(colwidth=1))
        summarygroup.append(summaryhead)
        summarygroup.append(summarybody)
        summary.append(summarygroup)
        content.append(summarytitle)
        content.append(summary)

        # This sets up all the column headers - two fixed
        # columns for feature name & status
        header = nodes.row()
        blank = nodes.entry()
        blank.append(nodes.emphasis(text="Feature"))
        header.append(blank)
        blank = nodes.entry()
        blank.append(nodes.emphasis(text="Status"))
        header.append(blank)
        summaryhead.append(header)

        # then one column for each hypervisor driver
        impls = matrix.targets.keys()
        impls.sort()
        for key in impls:
            target = matrix.targets[key]
            implcol = nodes.entry()
            header.append(implcol)
            implcol.append(nodes.strong(text=target.title))

        # We now produce the body of the table, one row for
        # each feature to report on
        for feature in matrix.features:
            item = nodes.row()

            # the hyperlink target name linking to details
            id = re.sub("[^a-zA-Z0-9_]", "_",
                        feature.key)

            # first the to fixed columns for title/status
            keycol = nodes.entry()
            item.append(keycol)
            keyref = nodes.reference(refid=id)
            keytxt = nodes.inline()
            keycol.append(keytxt)
            keytxt.append(keyref)
            keyref.append(nodes.strong(text=feature.title))

            statuscol = nodes.entry()
            item.append(statuscol)
            statuscol.append(nodes.inline(
                text=feature.status,
                classes=["sp_feature_" + feature.status]))

            # and then one column for each hypervisor driver
            impls = matrix.targets.keys()
            impls.sort()
            for key in impls:
                target = matrix.targets[key]
                impl = feature.implementations[key]
                implcol = nodes.entry()
                item.append(implcol)

                id = re.sub("[^a-zA-Z0-9_]", "_",
                            feature.key + "_" + key)

                implref = nodes.reference(refid=id)
                impltxt = nodes.inline()
                implcol.append(impltxt)
                impltxt.append(implref)

                status = ""
                if impl.status == "complete":
                    status = u"\u2714"
                elif impl.status == "missing":
                    status = u"\u2716"
                elif impl.status == "partial":
                    status = u"\u2714"

                implref.append(nodes.literal(
                    text=status,
                    classes=["sp_impl_summary", "sp_impl_" + impl.status]))

            summarybody.append(item)

    def _build_details(self, matrix, content):
        """Constructs the docutils content for the details of
        the support matrix.

        This is generated as a bullet list of features.
        Against each feature we provide the description of
        the feature and then the details of the hypervisor
        impls, with any driver specific notes that exist
        """

        detailstitle = nodes.subtitle(text="Details")
        details = nodes.bullet_list()

        content.append(detailstitle)
        content.append(details)

        # One list entry for each feature we're reporting on
        for feature in matrix.features:
            item = nodes.list_item()

            status = feature.status
            if feature.group is not None:
                status += "(" + feature.group + ")"

            # The hypervisor target name linked from summary table
            id = re.sub("[^a-zA-Z0-9_]", "_",
                        feature.key)

            # Highlight the feature title name
            item.append(nodes.strong(text=feature.title,
                                     ids=[id]))

            para = nodes.paragraph()
            para.append(nodes.strong(text="Status: " + status + ". "))
            if feature.notes is not None:
                para.append(nodes.inline(text=feature.notes))
            item.append(para)

            # A sub-list giving details of each hypervisor target
            impls = nodes.bullet_list()
            for key in feature.implementations:
                target = matrix.targets[key]
                impl = feature.implementations[key]
                subitem = nodes.list_item()

                id = re.sub("[^a-zA-Z0-9_]", "_",
                            feature.key + "_" + key)
                subitem += [
                    nodes.strong(text=target.title + ": "),
                    nodes.literal(text=impl.status,
                                  classes=["sp_impl_" + impl.status],
                                  ids=[id]),
                ]
                if impl.notes is not None:
                    subitem.append(nodes.paragraph(text=impl.notes))
                impls.append(subitem)

            item.append(impls)
            details.append(item)


def setup(app):
    app.add_directive('support_matrix', SupportMatrixDirective)
    app.add_stylesheet('support-matrix.css')

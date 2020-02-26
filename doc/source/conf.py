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
#
#  nova documentation build configuration file
#
# Refer to the Sphinx documentation for advice on configuring this file:
#
#   http://www.sphinx-doc.org/en/stable/config.html

import os
import sys

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
sys.path.insert(0, os.path.abspath('../'))

# -- General configuration ----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.todo',
    'sphinx.ext.graphviz',
    'openstackdocstheme',
    'sphinx_feature_classification.support_matrix',
    'oslo_config.sphinxconfiggen',
    'oslo_config.sphinxext',
    'oslo_policy.sphinxpolicygen',
    'oslo_policy.sphinxext',
    'ext.versioned_notifications',
    'ext.feature_matrix',
    'ext.extra_specs',
    'sphinxcontrib.actdiag',
    'sphinxcontrib.seqdiag',
    'sphinxcontrib.rsvgconverter',
]

# openstackdocstheme options
repository_name = 'openstack/nova'
bug_project = 'nova'
bug_tag = 'doc'

config_generator_config_file = '../../etc/nova/nova-config-generator.conf'
sample_config_basename = '_static/nova'

policy_generator_config_file = [
    ('../../etc/nova/nova-policy-generator.conf', '_static/nova'),
]

actdiag_html_image_format = 'SVG'
actdiag_antialias = True

seqdiag_html_image_format = 'SVG'
seqdiag_antialias = True

todo_include_todos = True

# The master toctree document.
master_doc = 'index'

# General information about the project.
copyright = u'2010-present, OpenStack Foundation'

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# -- Options for man page output ----------------------------------------------

# Grouping the document tree for man pages.
# List of tuples 'sourcefile', 'target', u'title', u'Authors name', 'manual'

_man_pages = [
    ('nova-api', u'Cloud controller fabric'),
    ('nova-api-metadata', u'Cloud controller fabric'),
    ('nova-api-os-compute', u'Cloud controller fabric'),
    ('nova-compute', u'Cloud controller fabric'),
    ('nova-conductor', u'Cloud controller fabric'),
    ('nova-manage', u'Cloud controller fabric'),
    ('nova-novncproxy', u'Cloud controller fabric'),
    ('nova-rootwrap', u'Cloud controller fabric'),
    ('nova-scheduler', u'Cloud controller fabric'),
    ('nova-serialproxy', u'Cloud controller fabric'),
    ('nova-spicehtml5proxy', u'Cloud controller fabric'),
    ('nova-status', u'Cloud controller fabric'),
]

man_pages = [
    ('cli/%s' % name, name, description, [u'OpenStack'], 1)
    for name, description in _man_pages]

# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
html_theme = 'openstackdocs'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# Add any paths that contain "extra" files, such as .htaccess or
# robots.txt.
html_extra_path = ['_extra']


# -- Options for LaTeX output -------------------------------------------------

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    ('index', 'doc-nova.tex', u'Nova Documentation',
     u'OpenStack Foundation', 'manual'),
]

# Allow deeper levels of nesting for \begin...\end stanzas
latex_elements = {
    'maxlistdepth': 10,
    'extraclassoptions': 'openany,oneside',
    'preamble': r'''
\setcounter{tocdepth}{3}
\setcounter{secnumdepth}{3}
''',
}

# Disable use of xindy since that's another binary dependency that's not
# available on all platforms
latex_use_xindy = False

# -- Options for openstackdocstheme -------------------------------------------

# keep this ordered to keep mriedem happy
#
# NOTE(stephenfin): Projects that don't have a release branch, like TripleO and
# reno, should not be included here
openstack_projects = [
    'ceilometer',
    'cinder',
    'cyborg',
    'glance',
    'horizon',
    'ironic',
    'keystone',
    'neutron',
    'nova',
    'oslo.log',
    'oslo.messaging',
    'oslo.i18n',
    'oslo.versionedobjects',
    'placement',
    'python-novaclient',
    'python-openstackclient',
    'watcher',
]
# -- Custom extensions --------------------------------------------------------

# NOTE(mdbooth): (2019-03-20) Sphinx loads policies defined in setup.cfg, which
# includes the placement policy at nova/api/openstack/placement/policies.py.
# Loading this imports nova/api/openstack/__init__.py, which imports
# nova.monkey_patch, which will do eventlet monkey patching to the sphinx
# process. As well as being unnecessary and a bad idea, this breaks on
# python3.6 (but not python3.7), so don't do that.
os.environ['OS_NOVA_DISABLE_EVENTLET_PATCHING'] = '1'


def monkey_patch_blockdiag():
    """Monkey patch the blockdiag library.

    The default word wrapping in blockdiag is poor, and breaks on a fixed
    text width rather than on word boundaries. There's a patch submitted to
    resolve this [1]_ but it's unlikely to merge anytime soon.

    In addition, blockdiag monkey patches a core library function,
    ``codecs.getreader`` [2]_, to work around some Python 3 issues. Because
    this operates in the same environment as other code that uses this library,
    it ends up causing issues elsewhere. We undo these destructive changes
    pending a fix.

    TODO: Remove this once blockdiag is bumped to 1.6, which will hopefully
    include the fix.

    .. [1] https://bitbucket.org/blockdiag/blockdiag/pull-requests/16/
    .. [2] https://bitbucket.org/blockdiag/blockdiag/src/1.5.3/src/blockdiag/utils/compat.py # noqa
    """
    import codecs
    from codecs import getreader

    from blockdiag.imagedraw import textfolder
    from blockdiag.utils import compat  # noqa

    # oh, blockdiag. Let's undo the mess you made.
    codecs.getreader = getreader

    def splitlabel(text):
        """Split text to lines as generator.

        Every line will be stripped. If text includes characters "\n\n", treat
        as line separator. Ignore '\n' to allow line wrapping.
        """
        lines = [x.strip() for x in text.splitlines()]
        out = []

        for line in lines:
            if line:
                out.append(line)
            else:
                yield ' '.join(out)
                out = []

        yield ' '.join(out)

    def splittext(metrics, text, bound, measure='width'):
        folded = [' ']
        for word in text.split():
            # Try appending the word to the last line
            tryline = ' '.join([folded[-1], word]).strip()
            textsize = metrics.textsize(tryline)
            if getattr(textsize, measure) > bound:
                # Start a new line. Appends `word` even if > bound.
                folded.append(word)
            else:
                folded[-1] = tryline
        return folded

    # monkey patch those babies
    textfolder.splitlabel = splitlabel
    textfolder.splittext = splittext


monkey_patch_blockdiag()

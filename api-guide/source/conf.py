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

# Compute API Guide documentation build configuration file

# Refer to the Sphinx documentation for advice on configuring this file:
#
#   http://www.sphinx-doc.org/en/stable/config.html

# -- General configuration ------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'openstackdocstheme',
    'sphinx.ext.todo',
]

# The suffix of source filenames.
source_suffix = '.rst'

# The 'todo' and 'todolist' directive produce output.
todo_include_todos = True

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = 'Compute API Guide'

copyright = '2015-present, OpenStack contributors'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The short X.Y version.
version = '2.1.0'
# The full version, including alpha/beta/rc tags.
release = '2.1.0'

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'native'


# -- Options for HTML output ----------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
html_theme = 'openstackdocs'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []

# If false, no index is generated.
html_use_index = True


# -- Options for LaTeX output ---------------------------------------------

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (
        'index',
        'ComputeAPI.tex',
        'Compute API Documentation',
        'OpenStack contributors',
        'manual',
    ),
]


# -- Options for Internationalization output ------------------------------

locale_dirs = ['locale/']


# -- Options for PDF output --------------------------------------------------

pdf_documents = [
    (
        'index',
        'ComputeAPIGuide',
        'Compute API Guide',
        'OpenStack contributors',
    )
]

# -- Options for openstackdocstheme -------------------------------------------

openstackdocs_projects = [
    'glance',
    'nova',
    'neutron',
    'placement',
]

openstackdocs_bug_tag = 'api-guide'
openstackdocs_repo_name = 'openstack/nova'
openstackdocs_bug_project = 'nova'
openstackdocs_auto_version = False
openstackdocs_auto_name = False

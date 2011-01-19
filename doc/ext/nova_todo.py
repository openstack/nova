# -*- coding: utf-8 -*-
# This is a hack of the builtin todo extension, to make the todo_list more user friendly

from sphinx.ext.todo import *
from docutils.parsers.rst import directives
import re

def _(s):
    return s


def process_todo_nodes(app, doctree, fromdocname):
    if not app.config['todo_include_todos']:
        for node in doctree.traverse(todo_node):
            node.parent.remove(node)

    # Replace all todolist nodes with a list of the collected todos.
    # Augment each todo with a backlink to the original location.
    env = app.builder.env

    if not hasattr(env, 'todo_all_todos'):
        env.todo_all_todos = []


    # remove the item that was added in the constructor, since I'm tired of 
    # reading through docutils for the proper way to construct an empty list
    lists = []
    for i in xrange(5):
        lists.append(nodes.bullet_list("", nodes.Text('','')))
        lists[i].remove(lists[i][0]) 
        lists[i].set_class('todo_list')

    for node in doctree.traverse(todolist):
        if not app.config['todo_include_todos']:
            node.replace_self([])
            continue

        for todo_info in env.todo_all_todos:
            para = nodes.paragraph()
            filename = env.doc2path(todo_info['docname'], base=None)

            # Create a reference
            newnode = nodes.reference('', '')

            line_info = todo_info['lineno']
            link = _('%(filename)s, line %(line_info)d') % locals()
            innernode = nodes.emphasis(link, link)
            newnode['refdocname'] = todo_info['docname']

            try:
                newnode['refuri'] = app.builder.get_relative_uri(
                    fromdocname, todo_info['docname'])
                newnode['refuri'] += '#' + todo_info['target']['refid']
            except NoUri:
                # ignore if no URI can be determined, e.g. for LaTeX output
                pass

            newnode.append(innernode)
            para += newnode
            para.set_class('todo_link')

            todo_entry = todo_info['todo']
                
            env.resolve_references(todo_entry, todo_info['docname'], app.builder)

            item = nodes.list_item('', para)
            todo_entry[1].set_class('details')

            comment = todo_entry[1]
        
            m = re.match(r"^P(\d)", comment.astext())
            priority = 5
            if m:
                priority = int(m.group(1))
                if (priority < 0): priority = 1
                if (priority > 5): priority = 5

            item.set_class('todo_p' + str(priority))
            todo_entry.set_class('todo_p' + str(priority))

            item.append(comment)

            lists[priority-1].insert(0, item)


        node.replace_self(lists)

def setup(app):
    app.add_config_value('todo_include_todos', False, False)

    app.add_node(todolist)
    app.add_node(todo_node,
                 html=(visit_todo_node, depart_todo_node),
                 latex=(visit_todo_node, depart_todo_node),
                 text=(visit_todo_node, depart_todo_node))

    app.add_directive('todo', Todo)
    app.add_directive('todolist', TodoList)
    app.connect('doctree-read', process_todos)
    app.connect('doctree-resolved', process_todo_nodes)
    app.connect('env-purge-doc', purge_todos)


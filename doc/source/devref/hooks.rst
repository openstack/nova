Hooks
=====

Hooks provide a mechanism to extend Nova with custom code through a plugin
mechanism.

Named hooks are added to nova code via a decorator that will lazily load
plugin code matching the name.  The loading works via setuptools
`entry points`_.

.. _`entry points`: http://pythonhosted.org/setuptools/pkg_resources.html#entry-points

What are hooks good for?
------------------------

Hooks are good for anchoring your custom code to Nova internal APIs.

What are hooks NOT good for?
----------------------------

Hooks should not be used when API stability is a key factor.  Internal APIs may
change.  Consider using a notification driver if this is important to you.

Declaring hooks in the Nova codebase
------------------------------------

The following example declares a *resize_hook* around the *resize_instance* method::

    from nova import hooks

    @hooks.add_hook("resize_hook")
    def resize_instance(self, context, instance, a=1, b=2):
        ...

Hook objects can now be attached via entry points to the *resize_hook*.

Adding hook object code
-----------------------

1. Setup a Python package with a setup.py file.
2. Add the following to the setup.py setup call::

    entry_points = {
        'nova.hooks': [
            'resize_hook=your_package.hooks:YourHookClass',
        ]
    },

3. *YourHookClass* should be an object with *pre* and/or *post* methods::

    class YourHookClass(object):

        def pre(self, *args, **kwargs):
            ....

        def post(self, rv, *args, **kwargs):
            ....

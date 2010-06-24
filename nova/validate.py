# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
  Decorators for argument validation, courtesy of 
  http://rmi.net/~lutz/rangetest.html
"""

def rangetest(**argchecks):                 # validate ranges for both+defaults
    def onDecorator(func):                  # onCall remembers func and argchecks
        import sys
        code = func.__code__ if sys.version_info[0] == 3 else func.func_code
        allargs  = code.co_varnames[:code.co_argcount]
        funcname = func.__name__
        
        def onCall(*pargs, **kargs):
            # all pargs match first N args by position
            # the rest must be in kargs or omitted defaults
            positionals = list(allargs)
            positionals = positionals[:len(pargs)]

            for (argname, (low, high)) in argchecks.items():
                # for all args to be checked
                if argname in kargs:
                    # was passed by name
                    if kargs[argname] < low or kargs[argname] > high:
                        errmsg = '{0} argument "{1}" not in {2}..{3}'
                        errmsg = errmsg.format(funcname, argname, low, high)
                        raise TypeError(errmsg)

                elif argname in positionals:
                    # was passed by position
                    position = positionals.index(argname)
                    if pargs[position] < low or pargs[position] > high:
                        errmsg = '{0} argument "{1}" not in {2}..{3}'
                        errmsg = errmsg.format(funcname, argname, low, high)
                        raise TypeError(errmsg)
                else:
                    pass

            return func(*pargs, **kargs)    # okay: run original call
        return onCall
    return onDecorator

def typetest(**argchecks):
    def onDecorator(func):
        import sys
        code = func.__code__ if sys.version_info[0] == 3 else func.func_code
        allargs  = code.co_varnames[:code.co_argcount]
        funcname = func.__name__
    
        def onCall(*pargs, **kargs):
            positionals = list(allargs)[:len(pargs)]
            for (argname, type) in argchecks.items():
                 if argname in kargs:
                    if not isinstance(kargs[argname], type):
                        errmsg = '{0} argument "{1}" not of type {2}'
                        errmsg = errmsg.format(funcname, argname, type)
                        raise TypeError(errmsg)
                elif argname in positionals:
                    position = positionals.index(argname)
                    if not isinstance(pargs[position], type):
                        errmsg = '{0} argument "{1}" not of type {2}'
                        errmsg = errmsg.format(funcname, argname, type)
                        raise TypeError(errmsg)
                else:
                    pass
            return func(*pargs, **kargs)
        return onCall
    return onDecorator


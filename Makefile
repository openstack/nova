venv=.venv
with_venv=source $(venv)/bin/activate
installed=$(venv)/lib/python2.6/site-packages
twisted=$(installed)/twisted/__init__.py


test: python-dependencies $(twisted)
	$(with_venv) && python run_tests.py

clean:
	rm -rf _trial_temp
	rm -rf keys
	rm -rf instances
	rm -rf networks

clean-all: clean
	rm -rf $(venv)

python-dependencies: $(venv)
	pip install -q -E $(venv) -r tools/pip-requires

$(venv):
	pip install -q virtualenv
	virtualenv -q --no-site-packages $(venv)

$(twisted):
	pip install -q -E $(venv) http://nova.openstack.org/Twisted-10.0.0Nova.tar.gz

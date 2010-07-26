venv=.nova-venv
with_venv=tools/with_venv.sh

build:
	# Nothing to do

test: $(venv)
	$(with_venv) python run_tests.py

test-system:
	python run_tests.py

clean:
	rm -rf _trial_temp
	rm -rf keys
	rm -rf instances
	rm -rf networks
	rm run_tests.err.log

clean-all: clean
	rm -rf $(venv)

$(venv):
	@echo "You need to install the Nova virtualenv before you can run this."
	@echo ""
	@echo "Please run tools/install_venv.py"
	@exit 1

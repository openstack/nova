Api Samples
===========

Samples in this directory are automatically generated from the api samples
integration tests. To regenerate the samples, simply set GENERATE_SAMPLES
in the environment before running the tests. For example:

  GENERATE_SAMPLES=True tox -epy27 nova.tests.integrated

If new tests are added or the .tpl files are changed due to bug fixes, the
samples should be regenerated so they are in sync with the templates.

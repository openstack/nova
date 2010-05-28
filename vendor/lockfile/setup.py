#!/usr/bin/env python

V = "0.9"

from distutils.core import setup
setup(name='lockfile',
      author='Skip Montanaro',
      author_email='skip@pobox.com',
      url='http://smontanaro.dyndns.org/python/',
      download_url=('http://smontanaro.dyndns.org/python/lockfile-%s.tar.gz' %
                    V),
      version=V,
      description="Platform-independent file locking module",
      long_description=open("README").read(),
      packages=['lockfile'],
      license='MIT License',
      classifiers=[
          'Development Status :: 4 - Beta',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Operating System :: MacOS',
          'Operating System :: Microsoft :: Windows :: Windows NT/2000',
          'Operating System :: POSIX',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2.4',
          'Programming Language :: Python :: 2.5',
          'Programming Language :: Python :: 2.6',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3.0',
          'Topic :: Software Development :: Libraries :: Python Modules',
          ]
      )

*************
Installation
*************


It is an explicit goal of the openEO Python client library to be as easy to install as possible,
unlocking the openEO ecosystem to a broad audience.
The package is a pure Python implementation and its dependencies are carefully considered .


Basic install
=============

``pip`` install
---------------

The openEO Python client library is available from `PyPI <https://pypi.org/project/openeo/>`_
and can be easily installed with a tool like ``pip``, for example::

    pip install openeo


At least *Python 3.6* is recommended.
Also, it is recommended to work in a *virtual environment* of some kind (``venv``, ``conda``, ...)
to avoid polluting the base install of Python on your operating system
or introducing conflicts with other applications.
How you organize your virtual environments heavily depends on your use case and workflow,
and is out of scope of this documentation.

Conda install
-------------

This is work in progress. See `openeo-python-client#176 <https://github.com/Open-EO/openeo-python-client/issues/176>`_ for more information.


Verifying and troubleshooting
-----------------------------

You can check if the installation worked properly
by trying to import the ``openeo`` package in a Python script, interactive shell or notebook::

    import openeo

    print(openeo.client_version())

This should print the installed version of the ``openeo`` package.

If the first line gives an error like ``ModuleNotFoundError: No module named 'openeo'``,
some troubleshooting tips:

-   Restart you Python shell or notebook (or start a fresh one).
-   Double check that the installation went well,
    e.g. try re-installing and keep an eye out for error/warning messages.
-   Make sure that you are working in the same (virtual) environment you installed the package in.

If you still have troubles installing and importing ``openeo``,
feel free to reach out in the `community forum <https://forums.openeo.cloud/>`_
or the `project's issue tracker <https://github.com/Open-EO/openeo-python-client/issues>`_.
Try to describe your setup in enough detail: your operating system,
which virtual environment system you use,
the installation tool (``pip``, ``conda`` or something else), ...



Source or development install
==============================

If you closely track the development of the ``openeo`` package at
`github.com/Open-EO/openeo-python-client <https://github.com/Open-EO/openeo-python-client>`_
and want to work with unreleased features or contribute to the development of the package,
you can install it as follows from the root of a git source checkout::

    pip install -e .[dev]

The ``-e`` option enables "development mode", which makes sure that changes you make to the source code
happen directly on the installed package, so that you don't have to re-install the package each time
you make a change.

The ``[dev]`` (a so-called "extra") installs additional development related dependencies,
for example to run the unit tests.


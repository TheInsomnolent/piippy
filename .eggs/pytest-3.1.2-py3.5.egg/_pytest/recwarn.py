""" recording warnings during test function execution. """
from __future__ import absolute_import, division, print_function

import inspect

import _pytest._code
import py
import sys
import warnings
from _pytest.fixtures import yield_fixture


@yield_fixture
def recwarn():
    """Return a WarningsRecorder instance that provides these methods:

    * ``pop(category=None)``: return last warning matching the category.
    * ``clear()``: clear list of warnings

    See http://docs.python.org/library/warnings.html for information
    on warning categories.
    """
    wrec = WarningsRecorder()
    with wrec:
        warnings.simplefilter('default')
        yield wrec


def deprecated_call(func=None, *args, **kwargs):
    """ assert that calling ``func(*args, **kwargs)`` triggers a
    ``DeprecationWarning`` or ``PendingDeprecationWarning``.

    This function can be used as a context manager::

        >>> import warnings
        >>> def api_call_v2():
        ...     warnings.warn('use v3 of this api', DeprecationWarning)
        ...     return 200

        >>> with deprecated_call():
        ...    assert api_call_v2() == 200

    Note: we cannot use WarningsRecorder here because it is still subject
    to the mechanism that prevents warnings of the same type from being
    triggered twice for the same module. See #1190.
    """
    if not func:
        return WarningsChecker(expected_warning=(DeprecationWarning, PendingDeprecationWarning))

    categories = []

    def warn_explicit(message, category, *args, **kwargs):
        categories.append(category)

    def warn(message, category=None, *args, **kwargs):
        if isinstance(message, Warning):
            categories.append(message.__class__)
        else:
            categories.append(category)

    old_warn = warnings.warn
    old_warn_explicit = warnings.warn_explicit
    warnings.warn_explicit = warn_explicit
    warnings.warn = warn
    try:
        ret = func(*args, **kwargs)
    finally:
        warnings.warn_explicit = old_warn_explicit
        warnings.warn = old_warn
    deprecation_categories = (DeprecationWarning, PendingDeprecationWarning)
    if not any(issubclass(c, deprecation_categories) for c in categories):
        __tracebackhide__ = True
        raise AssertionError("%r did not produce DeprecationWarning" % (func,))
    return ret


def warns(expected_warning, *args, **kwargs):
    """Assert that code raises a particular class of warning.

    Specifically, the input @expected_warning can be a warning class or
    tuple of warning classes, and the code must return that warning
    (if a single class) or one of those warnings (if a tuple).

    This helper produces a list of ``warnings.WarningMessage`` objects,
    one for each warning raised.

    This function can be used as a context manager, or any of the other ways
    ``pytest.raises`` can be used::

        >>> with warns(RuntimeWarning):
        ...    warnings.warn("my warning", RuntimeWarning)
    """
    wcheck = WarningsChecker(expected_warning)
    if not args:
        return wcheck
    elif isinstance(args[0], str):
        code, = args
        assert isinstance(code, str)
        frame = sys._getframe(1)
        loc = frame.f_locals.copy()
        loc.update(kwargs)

        with wcheck:
            code = _pytest._code.Source(code).compile()
            py.builtin.exec_(code, frame.f_globals, loc)
    else:
        func = args[0]
        with wcheck:
            return func(*args[1:], **kwargs)


class WarningsRecorder(warnings.catch_warnings):
    """A context manager to record raised warnings.

    Adapted from `warnings.catch_warnings`.
    """

    def __init__(self):
        super(WarningsRecorder, self).__init__(record=True)
        self._entered = False
        self._list = []

    @property
    def list(self):
        """The list of recorded warnings."""
        return self._list

    def __getitem__(self, i):
        """Get a recorded warning by index."""
        return self._list[i]

    def __iter__(self):
        """Iterate through the recorded warnings."""
        return iter(self._list)

    def __len__(self):
        """The number of recorded warnings."""
        return len(self._list)

    def pop(self, cls=Warning):
        """Pop the first recorded warning, raise exception if not exists."""
        for i, w in enumerate(self._list):
            if issubclass(w.category, cls):
                return self._list.pop(i)
        __tracebackhide__ = True
        raise AssertionError("%r not found in warning list" % cls)

    def clear(self):
        """Clear the list of recorded warnings."""
        self._list[:] = []

    def __enter__(self):
        if self._entered:
            __tracebackhide__ = True
            raise RuntimeError("Cannot enter %r twice" % self)
        self._list = super(WarningsRecorder, self).__enter__()
        warnings.simplefilter('always')
        return self

    def __exit__(self, *exc_info):
        if not self._entered:
            __tracebackhide__ = True
            raise RuntimeError("Cannot exit %r without entering first" % self)
        super(WarningsRecorder, self).__exit__(*exc_info)


class WarningsChecker(WarningsRecorder):
    def __init__(self, expected_warning=None):
        super(WarningsChecker, self).__init__()

        msg = ("exceptions must be old-style classes or "
               "derived from Warning, not %s")
        if isinstance(expected_warning, tuple):
            for exc in expected_warning:
                if not inspect.isclass(exc):
                    raise TypeError(msg % type(exc))
        elif inspect.isclass(expected_warning):
            expected_warning = (expected_warning,)
        elif expected_warning is not None:
            raise TypeError(msg % type(expected_warning))

        self.expected_warning = expected_warning

    def __exit__(self, *exc_info):
        super(WarningsChecker, self).__exit__(*exc_info)

        # only check if we're not currently handling an exception
        if all(a is None for a in exc_info):
            if self.expected_warning is not None:
                if not any(issubclass(r.category, self.expected_warning)
                           for r in self):
                    __tracebackhide__ = True
                    from _pytest.runner import fail
                    fail("DID NOT WARN. No warnings of type {0} was emitted. "
                         "The list of emitted warnings is: {1}.".format(
                            self.expected_warning,
                            [each.message for each in self]))
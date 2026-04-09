"""Span helper: thin wrapper around ``tracer.start_as_current_span`` that
degrades to a no-op when the SDK has not been initialized.

Callers use this unconditionally::

    from forge.main.observability.tracing import span
    with span('forge.launch', template_id=123) as s:
        s.set_attribute('result', 'allowed')
        ...
"""

from contextlib import contextmanager

_initialized = False
_tracer = None


class _NoopSpan:
    def set_attribute(self, *_a, **_kw):
        pass

    def set_attributes(self, *_a, **_kw):
        pass

    def add_event(self, *_a, **_kw):
        pass

    def record_exception(self, *_a, **_kw):
        pass

    def set_status(self, *_a, **_kw):
        pass

    def end(self):
        pass


@contextmanager
def span(name, **attributes):
    if not _initialized or _tracer is None:
        yield _NoopSpan()
        return
    try:
        with _tracer.start_as_current_span(name) as s:
            for k, v in attributes.items():
                if v is None:
                    continue
                try:
                    s.set_attribute(k, v)
                except Exception:
                    pass
            yield s
    except Exception:
        yield _NoopSpan()


def tracer():
    """Return the raw OpenTelemetry tracer, or None if not initialized."""
    return _tracer if _initialized else None

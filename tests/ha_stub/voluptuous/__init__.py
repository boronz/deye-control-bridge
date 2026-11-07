class _Any:
    def __init__(self, *a, **k): pass
def Schema(x, **k): return x
def Required(x, **k): return x
def Optional(x, **k): return x
def All(*a, **k): return a[0] if a else None
def Coerce(t): return t
def Range(**k): return None
def In(x): return x

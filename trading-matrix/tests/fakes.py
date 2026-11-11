class Result:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, name: str, store: dict):
        self.name = name
        self.store = store
        self.payload = None
        self.filters = []
        self.order_col = None
        self.limit_n = None
        self.op = "select"
        self.on_conflict = None

    def upsert(self, payload, on_conflict=None):
        self.op = "upsert"
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def select(self, *args, **kwargs):
        self.op = "select"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, col, desc=False):
        self.order_col = (col, desc)
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self.op in ("upsert", "insert"):
            if self.op == "upsert" and self.on_conflict:
                keys = [k.strip() for k in self.on_conflict.split(",")]

                def same(row):
                    return all(row.get(k) == self.payload.get(k) for k in keys)

                self.store[self.name] = [r for r in rows if not same(r)]
                rows = self.store[self.name]
            rows.append(dict(self.payload))
            return Result([dict(self.payload)])
        if self.op == "update":
            for row in rows:
                if all(row.get(k) == v for k, v in self.filters):
                    row.update(self.payload)
            return Result([])
        out = list(rows)
        for key, value in self.filters:
            out = [r for r in out if r.get(key) == value]
        if self.order_col:
            col, desc = self.order_col
            out = sorted(out, key=lambda r: r.get(col), reverse=desc)
        if self.limit_n is not None:
            out = out[: self.limit_n]
        return Result([dict(r) for r in out])


class FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return FakeTable(name, self.tables)

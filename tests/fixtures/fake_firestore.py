"""An in-memory stand-in for the slice of the Firestore client League Lab uses:
collection/document get, set (with merge), delete, stream, and where(filter=
FieldFilter(field, "==", value))."""

import copy


class Snapshot:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class DocumentRef:
    def __init__(self, store, id):
        self._store, self.id = store, id

    def get(self):
        return Snapshot(self, self._store.get(self.id))

    def set(self, data, merge=False):
        current = self._store.get(self.id) if merge else None
        self._store[self.id] = {**(current or {}), **copy.deepcopy(data)}

    def delete(self):
        self._store.pop(self.id, None)


class Query:
    def __init__(self, store, filters=()):
        self._store, self._filters = store, list(filters)

    def where(self, filter):
        assert filter.op_string == "=="
        return Query(self._store, [*self._filters, filter])

    def stream(self):
        for id, data in list(self._store.items()):
            if all(data.get(f.field_path) == f.value for f in self._filters):
                yield Snapshot(DocumentRef(self._store, id), data)


class Collection(Query):
    def document(self, id):
        return DocumentRef(self._store, str(id))


class FakeFirestore:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return Collection(self.data.setdefault(name, {}))

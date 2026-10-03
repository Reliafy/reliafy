"""A small, data-only reader for MS-NRBF (.NET ``BinaryFormatter``) streams.

BlockSim stores each diagram's drawing (the blocks' connections) and its
container membership as gzip-compressed ``BinaryFormatter`` blobs. This module
decodes those blobs into plain Python values so the importer can pick out the
few fields it needs. It is a *reader of data*, never a deserialiser: class
names are just strings, nothing is instantiated, imported or executed, and
method-call records are refused.

Uploads are untrusted, so the parser is bounded: a cap on records, on nesting
depth, on array/string sizes (never more than the bytes that remain), and on
the total number of array elements. Any malformed input raises
:class:`NrbfError`.

Reference: [MS-NRBF] .NET Remoting: Binary Format Data Structure.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Iterator

MAX_RECORDS = 500_000
MAX_DEPTH = 64
MAX_ELEMENTS = 2_000_000
MAX_STRING = 16 * 1024 * 1024


class NrbfError(ValueError):
    """The blob isn't a well-formed (or supported) NRBF stream."""


@dataclass
class Obj:
    """A serialised class instance: its .NET class name and member values."""

    class_name: str
    members: dict = field(default_factory=dict)

    def get(self, name: str, default=None):
        return self.members.get(name, default)


@dataclass(frozen=True)
class Ref:
    """A reference to another object in the same stream (by object id)."""

    id: int


class _Nulls:
    """ObjectNullMultiple: ``count`` consecutive nulls."""

    __slots__ = ("count",)

    def __init__(self, count: int):
        self.count = count


_END = object()
_HEADER = object()

# PrimitiveTypeEnum -> struct format (fixed-size ones).
_PRIM = {
    1: "<?", 2: "<B", 6: "<d", 7: "<h", 8: "<i", 9: "<q", 10: "<b", 11: "<f",
    12: "<q", 13: "<Q", 14: "<H", 15: "<I", 16: "<Q",
}


class Stream:
    """One decoded NRBF stream: its objects by id and its root value."""

    def __init__(self, objects: dict, root: Any):
        self.objects = objects
        self.root = root

    def deref(self, value):
        """Follow a :class:`Ref` (one level) to the object it points at."""
        seen = 0
        while isinstance(value, Ref):
            value = self.objects.get(value.id)
            seen += 1
            if seen > 16:
                return None
        return value

    def iter_objects(self, suffix: str, contains: str = "") -> Iterator[Obj]:
        """Every class instance whose class name ends with ``suffix`` (and
        contains ``contains`` — generic type names carry their arguments)."""
        for v in self.objects.values():
            if isinstance(v, Obj) and v.class_name.endswith(suffix) and contains in v.class_name:
                yield v

    def list_items(self, value) -> list:
        """The live items of a serialised ``List<T>`` (honours ``_size``)."""
        lst = self.deref(value)
        if not isinstance(lst, Obj):
            return []
        items = self.deref(lst.get("_items"))
        size = lst.get("_size")
        if not isinstance(items, (list, tuple)):
            return []
        if isinstance(size, int) and 0 <= size <= len(items):
            items = items[:size]
        return [self.deref(x) for x in items]


class _Parser:
    def __init__(self, data: bytes):
        self.b = data
        self.p = 0
        self.records = 0
        self.elements = 0
        self.objects: dict[int, Any] = {}
        self.classes: dict[int, tuple] = {}

    # -- primitives ------------------------------------------------------
    def _need(self, n: int):
        if n < 0 or self.p + n > len(self.b):
            raise NrbfError("unexpected end of data")

    def u8(self) -> int:
        self._need(1)
        v = self.b[self.p]
        self.p += 1
        return v

    def i32(self) -> int:
        self._need(4)
        v = struct.unpack_from("<i", self.b, self.p)[0]
        self.p += 4
        return v

    def string(self) -> str:
        n = 0
        for shift in (0, 7, 14, 21, 28):
            c = self.u8()
            n |= (c & 0x7F) << shift
            if not c & 0x80:
                break
        else:
            raise NrbfError("bad string length")
        if n > MAX_STRING:
            raise NrbfError("string too long")
        self._need(n)
        v = self.b[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return v

    def prim(self, t: int):
        fmt = _PRIM.get(t)
        if fmt:
            size = struct.calcsize(fmt)
            self._need(size)
            v = struct.unpack_from(fmt, self.b, self.p)[0]
            self.p += size
            return v
        if t == 3:  # Char: one UTF-8 encoded character
            c = self.u8()
            n = 1 if c < 0x80 else 2 if c < 0xE0 else 3 if c < 0xF0 else 4
            self._need(n - 1)
            v = self.b[self.p - 1:self.p - 1 + n].decode("utf-8", "replace")
            self.p += n - 1
            return v
        if t in (5, 18):  # Decimal (as text), String
            return self.string()
        if t == 17:
            return None
        raise NrbfError(f"unsupported primitive type {t}")

    def _count(self, n: int):
        """Count array elements against the global cap."""
        if n < 0:
            raise NrbfError("negative length")
        self.elements += n
        if self.elements > MAX_ELEMENTS:
            raise NrbfError("too many array elements")

    # -- structure -------------------------------------------------------
    def class_info(self):
        oid = self.i32()
        name = self.string()
        count = self.i32()
        if count < 0 or count > 10_000:
            raise NrbfError("bad member count")
        names = [self.string() for _ in range(count)]
        return oid, name, names

    def member_types(self, count: int):
        kinds = [self.u8() for _ in range(count)]
        out = []
        for bt in kinds:
            if bt in (0, 7):
                out.append((bt, self.u8()))
            elif bt == 3:
                out.append((bt, self.string()))
            elif bt == 4:
                out.append((bt, (self.string(), self.i32())))
            elif bt in (1, 2, 5, 6):
                out.append((bt, None))
            else:
                raise NrbfError(f"bad binary type {bt}")
        return out

    def _values(self, types, depth: int) -> list:
        out: list = []
        pending_nulls = 0
        for bt, extra in types:
            if pending_nulls:
                out.append(None)
                pending_nulls -= 1
                continue
            if bt == 0:
                out.append(self.prim(extra))
                continue
            v = self.record(depth + 1)
            if isinstance(v, _Nulls):
                out.append(None)
                pending_nulls = v.count - 1
            elif v is _END or v is _HEADER:
                raise NrbfError("unexpected record inside an object")
            else:
                out.append(v)
        if pending_nulls:
            raise NrbfError("null run overflows the object's members")
        return out

    def _object(self, oid: int, name: str, names: list, types, depth: int) -> Ref:
        self.classes[oid] = (name, names, types)
        obj = Obj(name)
        self.objects[oid] = obj  # register first so self-references resolve
        obj.members = dict(zip(names, self._values(types, depth)))
        return Ref(oid)

    def _elements(self, n: int, bt: int, extra, depth: int) -> list:
        self._count(n)
        if bt == 0:
            if extra == 2:  # byte[]: take it as one slice
                self._need(n)
                v = bytes(self.b[self.p:self.p + n])
                self.p += n
                return v  # type: ignore[return-value]
            return [self.prim(extra) for _ in range(n)]
        out: list = []
        while len(out) < n:
            v = self.record(depth + 1)
            if isinstance(v, _Nulls):
                if len(out) + v.count > n:
                    raise NrbfError("null run overflows the array")
                out.extend([None] * v.count)
            elif v is _END or v is _HEADER:
                raise NrbfError("unexpected record inside an array")
            else:
                out.append(v)
        return out

    def record(self, depth: int = 0):
        if depth > MAX_DEPTH:
            raise NrbfError("nesting too deep")
        self.records += 1
        if self.records > MAX_RECORDS:
            raise NrbfError("too many records")
        t = self.u8()
        if t == 0:  # SerializedStreamHeader
            self._need(16)
            self.p += 16
            return _HEADER
        if t == 1:  # ClassWithId
            oid, meta = self.i32(), self.i32()
            if meta not in self.classes:
                raise NrbfError("reference to unknown class metadata")
            name, names, types = self.classes[meta]
            return self._object(oid, name, names, types, depth)
        if t in (2, 3):  # (System)ClassWithMembers: untyped members
            oid, name, names = self.class_info()
            if t == 3:
                self.i32()  # library id
            return self._object(oid, name, names, [(2, None)] * len(names), depth)
        if t in (4, 5):  # (System)ClassWithMembersAndTypes
            oid, name, names = self.class_info()
            types = self.member_types(len(names))
            if t == 5:
                self.i32()  # library id
            return self._object(oid, name, names, types, depth)
        if t == 6:  # BinaryObjectString
            oid = self.i32()
            v = self.string()
            self.objects[oid] = v
            return v
        if t == 7:  # BinaryArray
            oid = self.i32()
            kind = self.u8()
            rank = self.i32()
            if rank < 1 or rank > 32:
                raise NrbfError("bad array rank")
            lengths = [self.i32() for _ in range(rank)]
            if kind in (3, 4, 5):
                for _ in range(rank):
                    self.i32()  # lower bounds
            (bt, extra), = self.member_types(1)
            n = 1
            for ln in lengths:
                if ln < 0:
                    raise NrbfError("negative array length")
                n *= ln
                if n > MAX_ELEMENTS:
                    raise NrbfError("array too large")
            v = self._elements(n, bt, extra, depth)
            self.objects[oid] = v
            return Ref(oid)
        if t == 8:  # MemberPrimitiveTyped
            return self.prim(self.u8())
        if t == 9:  # MemberReference
            return Ref(self.i32())
        if t == 10:  # ObjectNull
            return None
        if t == 11:  # MessageEnd
            return _END
        if t == 12:  # BinaryLibrary, then the record it prefixes
            self.i32()
            self.string()
            return self.record(depth)
        if t == 13:
            return _Nulls(self.u8())
        if t == 14:
            n = self.i32()
            self._count(n)
            return _Nulls(n)
        if t == 15:  # ArraySinglePrimitive
            oid, n, pt = self.i32(), self.i32(), self.u8()
            v = self._elements(n, 0, pt, depth)
            self.objects[oid] = v
            return Ref(oid)
        if t in (16, 17):  # ArraySingleObject / ArraySingleString
            oid, n = self.i32(), self.i32()
            v = self._elements(n, 2, None, depth)
            self.objects[oid] = v
            return Ref(oid)
        if t in (21, 22):
            raise NrbfError("remoting method records are not supported")
        raise NrbfError(f"unknown record type {t}")

    def stream(self) -> Stream:
        self.objects, self.classes = {}, {}
        first = self.record()
        if first is not _HEADER:
            raise NrbfError("missing stream header")
        root = None
        while True:
            v = self.record()
            if v is _END:
                break
            if v is _HEADER:
                raise NrbfError("nested stream header")
            if root is None:
                root = v
        return Stream(self.objects, root)


def parse_streams(data: bytes, max_streams: int = 1000) -> list[Stream]:
    """Decode every NRBF stream concatenated in ``data``."""
    p = _Parser(bytes(data))
    out: list[Stream] = []
    while p.p < len(p.b):
        if len(out) >= max_streams:
            raise NrbfError("too many streams")
        out.append(p.stream())
    return out


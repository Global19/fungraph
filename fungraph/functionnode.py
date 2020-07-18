import itertools
from contextlib import suppress
from copy import deepcopy
from types import MappingProxyType
from typing import Callable, Any, Tuple, Optional, Union, Iterator, Mapping

import graphchain
import dask
from dask import delayed

from fungraph.internal import scan
from fungraph.internal.util import rsplitornone, splitornone, toint


def _context() -> dask.config.set:
    return dask.config.set(scheduler="sync",
                           delayed_optimize=graphchain.optimize)


class FunctionNode:

    def __init__(self, f: Callable[..., Any], *args: Any, **kwargs: Any):
        self._f = f
        self._args = list(args)
        self._kwargs = dict(kwargs)

    @property
    def args(self) -> Tuple[Any]:
        return tuple(self._args)

    @property
    def kwargs(self) -> MappingProxyType:
        return MappingProxyType(self._kwargs)

    @property
    def f(self) -> Callable[..., Any]:
        return self._f

    def __getitem__(self, item: Union[str, int]):
        return self.get(item)

    def __setitem__(self, key: Union[str, int], value: Any):
        return self.set(key, value)

    def get(self, item: Union[str, int]) -> Any:
        item, continuation = map(toint, splitornone(item))
        item = self._justget(item)
        return item if continuation is None else item.get(continuation)

    def _justget(self, item: Union[str, int]) -> Any:
        try:
            return self._getarg(item)
        except (KeyError, IndexError):
            return self._getnamed(item, recursive=False)

    def set(self, item: Union[str, int], value: Any) -> None:
        getfirst, item = map(toint, rsplitornone(item))
        node = self if getfirst is None else self._justget(getfirst)
        return node._justset(item, value)
        return item if continuation is None else item.get(continuation)

    def _justset(self, item: Union[str, int], value: Any) -> None:
        try:
            return self._setarg(item, value)
        except (KeyError, IndexError):
            return self._setnamed(item, value, recursive=False)

    def _getarg(self, item: Union[str, int]):
        try:
            return self._args[item]
        except TypeError:
            try:
                return self._kwargs[item]
            except KeyError:
                raise KeyError(f"{self} has no argument {item}")

    def _setarg(self, key: Union[str, int], value: Any):
        try:
            self._args[key] = value
            return
        except TypeError:
            if key in self._kwargs:
                self._kwargs[key] = value
                return
        raise KeyError(f"{self} has no argument {key}")

    def _iterchildnodes(self) -> Iterator[Tuple[Union[str, int], "FunctionNode"]]:
        return ((k, n) for k, n in itertools.chain(enumerate(self.args), self.kwargs.items())
                if isinstance(n, FunctionNode)
                )

    def _getnamed(self, name: str, recursive: bool = True) -> "FunctionNode":
        for _, a in self._iterchildnodes():
            with suppress(Exception):
                if name == a.name:
                    return a
        if recursive:
            for _, a in self._iterchildnodes():
                with suppress(Exception):
                    return a._getnamed(name, recursive=recursive)
        raise KeyError(f"{self} does not contain \"{name}\"")

    def _setnamed(self, name: str, value: Any, recursive: bool = True):
        found = False
        for index, a in self._iterchildnodes():
            with suppress(Exception):
                if name == a.name:
                    found = True
                    self[index] = value
        if recursive:
            for index, a in self._iterchildnodes():
                with suppress(Exception):
                    a._setnamed(name, value, recursive=recursive)
                    found = True
        if not found:
            raise KeyError(f"{self} does not contain \"{name}\"")

    def todelayed(self) -> delayed:
        args = []
        for a in self.args:
            with suppress(AttributeError):
                a = a.todelayed()
            args.append(a)
        args = tuple(args)
        kwargs = {}
        for key, a in self.kwargs.items():
            with suppress(AttributeError):
                a = a.todelayed()
            kwargs[key] = a
        result = delayed(self.f)(*args, **kwargs)
        return result

    def __call__(self):
        return self.compute()

    def compute(self, cachedir: str = ".fungraphcache") -> Any:
        with _context():
            return self.todelayed().compute(location=cachedir)

    def __repr__(self):
        return f"FunctionNode({self.f.__name__}, args={self.args}, kwargs={self.kwargs})"

    def clone(self):
        return deepcopy(self)

    def scan(self, arguments: Mapping[str, Any], name: Optional[str] = None):
        return scan.scan(self, arguments, name)

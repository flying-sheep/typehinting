# TODO:
# [done] Any
# [done] TypeVar (type variables)
# [done] T, KT, VT, AnyStr
# [done] Union, Optional
# [done] Tuple
# [done] Callable
# [done] Generic
# Protocol (similar to Generic, but for structural matching)
# All the collections ABCs (with Set renamed to AbstractSet):
#   Hashable, Iterable, Iterator,
#   Sized, Container, *Abstract*Set, MutableSet, Mapping, MutableMapping,
#   MappingView, KeysView, ItemsView, ValuesView,
#   Sequence, MutableSequence
#   ByteString
# List, Dict, Set; FrozenSet?
# Other things from mypy's typing.py:
# - [done] Undefined
# - IO, BinaryIO, TextIO (?)
# - Match, Pattern (?)
# - [done] cast
# - forwardref
# - overload
# - [done] typevar (alias for TypeVar)
# Even more things from mypy's typing.py (that aren't in its __all__)

# TODO nits:
# Get rid of asserts that are the caller's fault.
# Docstrings.
# Make it pep8-clean.

import abc
import collections.abc
import inspect
import sys
import types


class TypingMeta(type):
    """Base class for every type defined below.

    This overrides __new__() to require an extra keyword parameter
    '_root', which serves as a guard against naive subclassing of the
    typing classes.  Any legitimate class defined using a metaclass
    derived from TypingMeta (including internal subclasses created by
    e.g.  Union[X, Y]) must pass _root=True.

    This also defines a dummy constructor (all the work is done in
    __new__) and a nicer repr().
    """

    def __new__(cls, name, bases, namespace, *, _root=False):
        if not _root:
            raise TypeError("Cannot subclass %s" %
                            (', '.join(map(_type_repr, bases)) or '()'))
        return super().__new__(cls, name, bases, namespace)

    def __init__(self, *args, **kwds):
        pass

    def __repr__(self):
        return '%s.%s' % (self.__module__, self.__qualname__)


class Final:
    """Mix-in class to prevent instantiation."""

    def __new__(self, *args, **kwds):
        raise TypeError("Cannot instantiate %r" % self.__class__)


def _type_check(arg, msg):
    """Check that the argument is a type, and return it.

    As a special case, accept None and return type(None) instead.
    The msg argument is a human-readable error message, e.g.

        "Union[arg, ...]: arg should be a type."

    We append the repr() of the actual value (truncated to 100 chars).
    """
    if arg is None:
        return type(None)
    if not isinstance(arg, type):
        raise TypeError(msg + " Got %.100r." % (arg,))
    return arg


def _type_repr(obj):
    """Return the repr() of an object, special-casing types.

    If obj is a type, we return a shorter version than the default
    type.__repr__, based on the module and qualified name, which is
    typically enough to uniquely identify a type.  For everything
    else, we fall back on repr(obj).
    """
    if isinstance(obj, type) and not isinstance(obj, TypingMeta):
        if obj.__module__ == 'builtins':
            return obj.__qualname__
        else:
            return '%s.%s' % (obj.__module__, obj.__qualname__)
    else:
        return repr(obj)


class AnyMeta(TypingMeta):
    """Metaclass for Any."""

    def __new__(cls, name, bases, namespace, _root=False):
        self = super().__new__(cls, name, bases, namespace, _root=_root)
        return self

    def __instancecheck__(self, instance):
        return True

    def __subclasscheck__(self, cls):
        if not isinstance(cls, type):
            return super().__subclasscheck__(cls)  # To TypeError.
        return True


class Any(Final, metaclass=AnyMeta, _root=True):
    """Special type indicating an unconstrained type.

    - Any object is an instance of Any.
    - Any class is a subclass of Any.
    - As a special case, Any and object are subclasses of each other.
    """


class TypeVar(TypingMeta, metaclass=TypingMeta, _root=True):
    """Type variable.

    Usage::

      T1 = TypeVar('T1')  # Unconstrained
      T2 = TypeVar('T2', t1, t2, ...)  # Constrained to any of (t1, t2, ...)

    For an unconstrained type variable T, isinstance(x, T) is false
    for all x, and similar for issubclass(cls, T).  Example::

      T = TypeVar('T')
      assert not isinstance(42, T)
      assert not issubclass(int, T)

    For a constrained type variable T, isinstance(x, T) is true for
    any x that is an instance of at least one of T's constraints,
    and similar for issubclass(cls, T).  Example::

      AnyStr = TypeVar('AnyStr', str, bytes)
      # AnyStr behaves similar to Union[str, bytes] (but not exactly!)
      assert not isinstance(42, AnyStr)
      assert isinstance('', AnyStr)
      assert isinstance(b'', AnyStr)
      assert not issubclass(int, AnyStr)
      assert issubclass(str, AnyStr)
      assert issubclass(bytes, AnyStr)

    Type variables that are distinct objects are never equal (even if
    created with the same parameters).

    You can temporarily *bind* a type variable to a specific type by
    calling its bind() method and using the result as a context
    manager (i.e., in a with-statement).  Example::

      with T.bind(int):
          # In this block, T is nearly an alias for int.
          assert isinstance(42, T)
          assert issubclass(int, T)

    There is still a difference between T and int; issubclass(T, int)
    is False.  However, issubclass(int, T) is true.

    Binding a constrained type variable will replace the binding type
    with the most derived of its constraints that matches.  Example::

      class MyStr(str):
          pass

      with AnyStr.bind(MyStr):
          # In this block, AnyStr is an alias for str, not for MyStr.
          assert isinstance('', AnyStr)
          assert issubclass(str, AnyStr)
          assert not isinstance(b'', AnyStr)
          assert not issubclass(bytes, AnyStr)

    """

    def __new__(cls, name, *constraints):
        self = super().__new__(cls, name, (Final,), {}, _root=True)
        msg = "TypeVar(name, constraint, ...): constraints must be types."
        self.__constraints__ = tuple(_type_check(t, msg) for t in constraints)
        self.__binding__ = None
        return self

    def __repr__(self):
        return '~' + self.__name__

    def __instancecheck__(self, instance):
        if self.__binding__ is not None:
            return isinstance(instance, self.__binding__)
        elif not self.__constraints__:
            return False
        else:
            return isinstance(instance, Union[self.__constraints__])

    def __subclasscheck__(self, cls):
        if cls is self:
            return True
        elif self.__binding__ is not None:
            return issubclass(cls, self.__binding__)
        elif not self.__constraints__:
            return False
        else:
            return issubclass(cls, Union[self.__constraints__])

    def bind(self, binding):
        binding = _type_check(binding, "TypeVar.bind(t): t must be a type.")
        if self.__constraints__:
            best = None
            for t in self.__constraints__:
                if (issubclass(binding, t) and
                    (best is None or issubclass(t, best))):
                    best = t
            if best is None:
                raise TypeError(
                    "TypeVar.bind(t): t must match one of the constraints.")
            binding = best
        return VarBinding(self, binding)

    def _bind(self, binding):
        old_binding = self.__binding__
        self.__binding__ = binding
        return old_binding

    def _unbind(self, binding, old_binding):
        assert self.__binding__ is binding, (self.__binding__,
                                             binding, old_binding)
        self.__binding__ = old_binding


# Compatibility for for mypy's typevar().
def typevar(name, values=()):
    return TypeVar(name, *values)


class VarBinding:
    """TypeVariable binding returned by TypeVar.bind()."""

    # TODO: This is not thread-safe.  We could solve this in one of
    # two ways: by using a lock or by using thread-local state.  But
    # either of these feels overly heavy, and still doesn't work
    # e.g. in an asyncio Task.

    def __init__(self, var, binding):
        assert isinstance(var, TypeVar), (var, binding)
        assert isinstance(binding, type), (var, binding)
        self._var = var
        self._binding = binding
        self._old_binding = None
        self._entered = False

    def __enter__(self):
        if self._entered:
            # This checks for the following scenario:
            # bv = T.bind(<some_type>)
            # with bv:
            #     with bv:  # Will raise here.
            #         ...
            # However, the following scenario is OK (if somewhat odd):
            # bv = T.bind(<some_type>)
            # with bv:
            #     ...
            # with bv:
            #     ...
            # The following scenario is also fine:
            # with T.bind(<some_type>):
            #     with T.bind(<some_other_type>):
            #         ...
            raise TypeError("Cannot reuse variable binding recursively.")
        self._old_binding = self._var._bind(self._binding)
        self._entered = True

    def __exit__(self, *args):
        try:
            self._var._unbind(self._binding, self._old_binding)
        finally:
            self._entered = False
            self._old_binding = None


# Some unconstrained type variables.  These are used by the container types.
T = TypeVar('T')  # Any type.
KT = TypeVar('KT')  # Key type.
VT = TypeVar('VT')  # Value type.

# A useful type variable with constraints.  This represents string types.
# TODO: What about bytearray, memoryview?
AnyStr = TypeVar('AnyStr', bytes, str)


class UnionMeta(TypingMeta):
    """Metaclass for Union."""

    def __new__(cls, name, bases, namespace, parameters=None, _root=False):
        if parameters is None:
            return super().__new__(cls, name, bases, namespace, _root=_root)
        if not isinstance(parameters, tuple):
            raise TypeError("Expected parameters=<tuple>")
        # Flatten out Union[Union[...], ...] and type-check non-Union args.
        params = []
        msg = "Union[arg, ...]: each arg must be a type."
        for p in parameters:
            if isinstance(p, UnionMeta):
                params.extend(p.__union_params__)
            else:
                params.append(_type_check(p, msg))
        # Weed out strict duplicates, preserving the first of each occurrence.
        all_params = set(params)
        if len(all_params) < len(params):
            new_params = []
            for t in params:
                if t in all_params:
                    new_params.append(t)
                    all_params.remove(t)
            params = new_params
            assert not all_params, all_params
        # Weed out subclasses.
        # E.g. Union[int, Employee, Manager] == Union[int, Employee].
        # If Any or object is present it will be the sole survivor.
        # If both Any and object are present, Any wins.
        all_params = set(params)
        for t1 in params:
            if t1 is Any:
                return Any
            if any(issubclass(t1, t2) for t2 in all_params - {t1}):
                all_params.remove(t1)
        # It's not a union if there's only one type left.
        if len(all_params) == 1:
            return all_params.pop()
        # Create a new class with these params.
        self = super().__new__(cls, name, bases, namespace, _root=True)
        self.__union_params__ = tuple(t for t in params if t in all_params)
        self.__union_set_params__ = frozenset(self.__union_params__)
        return self

    def __repr__(self):
        r = super().__repr__()
        if self.__union_params__:
            r += '[%s]' % (', '.join(_type_repr(t)
                                     for t in self.__union_params__))
        return r

    def __getitem__(self, parameters):
        if self.__union_params__ is not None:
            raise TypeError(
                "Cannot subscript an existing Union. Use Union[u, t] instead.")
        if parameters == ():
            raise TypeError("Cannot take a Union of no types.")
        if not isinstance(parameters, tuple):
            parameters = (parameters,)
        return self.__class__(self.__name__, self.__bases__,
                              dict(self.__dict__), parameters, _root=True)

    def __eq__(self, other):
        if not isinstance(other, UnionMeta):
            return NotImplemented
        return self.__union_set_params__ == other.__union_set_params__

    def __hash__(self):
        return hash(self.__union_set_params__)

    def __instancecheck__(self, instance):
        return any(isinstance(instance, t) for t in self.__union_params__)

    def __subclasscheck__(self, cls):
        if self.__union_params__ is None:
            return isinstance(cls, UnionMeta)
        elif isinstance(cls, UnionMeta):
            if cls.__union_params__ is None:
                return False
            return all(issubclass(c, self) for c in (cls.__union_params__))
        elif isinstance(cls, TypeVar):
            if cls in self.__union_params__:
                return True
            if cls.__constraints__:
                return issubclass(Union[cls.__constraints__], self)
            return False
        else:
            return any(issubclass(cls, t) for t in self.__union_params__)


class Union(Final, metaclass=UnionMeta, _root=True):
    """Union type; Union[X, Y] means either X or Y.

    To define a union, use e.g. Union[int, str].  Details:

    - The arguments must be types and there must be at least one.

    - None as an argument is a special case and is replaced by
      type(None).

    - Unions of unions are flattened, e.g.::

        Union[Union[int, str], float] == Union[int, str, float]

    - Unions of a single argument vanish, e.g.::

        Union[int] == int  # The constructore actually returns int

    - Redundant arguments are skipped, e.g.::

        Union[int, str, int] == Union[int, str]

    - When comparing unions, the argument order is ignored, e.g.::

        Union[int, str] == Union[str, int]

    - When two arguments have a subclass relationship, the least
      derived argument is kept, e.g.::

        class Employee: pass
        class Manager(Employee): pass
        Union[int, Employee, Manager] == Union[int, Employee]
        Union[Manager, int, Employee] == Union[int, Employee]
        Union[Employee, Manager] == Employee

    - Corollary: if Any is present it is the sole survivor, e.g.::

        Union[int, Any] == Any

    - Similar for object::

        Union[int, object] == object

    - To cut a tie: Union[object, Any] == Union[Any, object] == Any.

    - You cannot subclass or instantiate a union.

    - You cannot write Union[X][Y] (what would it mean?).

    - You can use Optional[X] as a shorthand for Union[X, None].
    """

    # Unsubscripted Union type has params set to None.
    __union_params__ = None
    __union_set_params__ = None


class OptionalMeta(TypingMeta):
    """Metaclass for Optional."""

    def __new__(cls, name, bases, namespace, _root=False):
        return super().__new__(cls, name, bases, namespace, _root=_root)

    def __getitem__(self, arg):
        if not isinstance(arg, type):
            raise TypeError("Optional[t] requires a single type.")
        return Union[arg, type(None)]


class Optional(Final, metaclass=OptionalMeta, _root=True):
    """Optional type.

    Optional[X] is equivalent to Union[X, type(None)].
    """


class TupleMeta(TypingMeta):
    """Metaclass for Tuple."""

    def __new__(cls, name, bases, namespace, parameters=None, _root=False):
        self = super().__new__(cls, name, bases, namespace, _root=_root)
        self.__tuple_params__ = parameters
        return self

    def __repr__(self):
        r = super().__repr__()
        if self.__tuple_params__ is not None:
            r += '[%s]' % (
                ', '.join(_type_repr(p) for p in self.__tuple_params__))
        return r

    def __getitem__(self, parameters):
        if self.__tuple_params__ is not None:
            raise TypeError("Cannot re-parameterize %r" % (self,))
        if not isinstance(parameters, tuple):
            parameters = (parameters,)
        msg = "Class[arg, ...]: each arg must be a type."
        parameters = tuple(_type_check(p, msg) for p in parameters)
        return self.__class__(self.__name__, self.__bases__,
                              dict(self.__dict__), parameters, _root=True)

    def __instancecheck__(self, t):
        if not isinstance(t, tuple):
            return False
        if self.__tuple_params__ is None:
            return True
        return (len(t) == len(self.__tuple_params__) and
                all(isinstance(x, p)
                    for x, p in zip(t, self.__tuple_params__)))

    def __subclasscheck__(self, cls):
        if not isinstance(cls, type):
            return super().__subclasscheck__(cls)  # To TypeError.
        if issubclass(cls, tuple):
            return True  # Special case.
        if not isinstance(cls, TupleMeta):
            return super().__subclasscheck__(cls)  # False.
        if self.__tuple_params__ is None:
            return True
        if cls.__tuple_params__ is None:
            return False  # ???
        # Covariance.
        return (len(self.__tuple_params__) == len(cls.__tuple_params__) and
                all(issubclass(x, p)
                    for x, p in zip(cls.__tuple_params__,
                                    self.__tuple_params__)))


class Tuple(Final, metaclass=TupleMeta, _root=True):
    """Tuple type; Tuple[X, Y] is the cross-product type of X and Y.

    Example: Tuple[T1, T2] is a tuple of two elements corresponding
    to type variables T1 and T2.  Tuple[int, float, str] is a tuple
    of an int, a float and a string.

    To specify a variable-length tuple of homogeneous type, use Sequence[T].
    """


class CallableMeta(TypingMeta):
    """Metaclass for Callable."""

    def __new__(cls, name, bases, namespace, _root=False,
                args=None, result=None):
        if args is None and result is None:
            pass  # Must be 'class Callable'.
        else:
            if not isinstance(args, list):
                TypeError("Callable[args, result]: args must be a list." +
                          " Got %.100r." % (args,))
            msg = "Callable[[arg, ...], result]: each arg must be a type."
            args = tuple(_type_check(arg, msg) for arg in args)
            msg = "Callable[args, result]: result must be a type."
            result = _type_check(result, msg)
        self = super().__new__(cls, name, bases, namespace, _root=_root)
        self.__args__ = args
        self.__result__ = result
        return self

    def __repr__(self):
        r = super().__repr__()
        if self.__args__ is not None or self.__result__ is not None:
            r += '%s[[%s], %s]' % (self.__qualname__,
                                   ', '.join(_type_repr(t)
                                             for t in self.__args__),
                                   _type_repr(self.__result__))
        return r

    def __getitem__(self, parameters):
        if self.__args__ is not None or self.__result__ is not None:
            raise TypeError("This Callable type is already parameterized.")
        if not isinstance(parameters, tuple) or len(parameters) != 2:
            raise TypeError(
                "Callable must be used as Callable[[arg, ...], result].")
        args, result = parameters
        return self.__class__(self.__name__, self.__bases__,
                              dict(self.__dict__), _root=True,
                              args=args, result=result)

    def __eq__(self, other):
        if not isinstance(other, CallableMeta):
            return NotImplemented
        return (self.__args__ == other.__args__ and
                self.__result__ == other.__result__)

    def __hash__(self):
        return hash(self.__args__) ^ hash(self.__result__)

    def __instancecheck__(self, instance):
        if not callable(instance):
            return False
        if self.__args__ is None and self.__result__ is None:
            return True
        assert self.__args__ is not None
        assert self.__result__ is not None
        my_args, my_result = self.__args__, self.__result__
        # Would it be better to use Signature objects?
        try:
            (args, varargs, varkw, defaults, kwonlyargs, kwonlydefaults,
             annotations) = inspect.getfullargspec(instance)
        except TypeError:
            return False  # We can't find the signature.  Give up.
        if kwonlyargs and (not kwonlydefaults or
                           len(kwonlydefaults) < len(kwonlyargs)):
            return False
        if isinstance(instance, types.MethodType):
            # For methods, getfullargspec() includes self/cls,
            # but it's not part of the call signature, so drop it.
            del args[0]
        min_call_args = len(args)
        if defaults:
            min_call_args -= len(defaults)
        if varargs:
            max_call_args = 999999999
            if len(args) < len(my_args):
                args += [varargs] * (len(my_args) - len(args))
        else:
            max_call_args = len(args)
        if not min_call_args <= len(my_args) <= max_call_args:
            return False
        msg = ("When testing isinstance(<callable>, Callable[...], " +
               "<calleble>'s annotations must be types.")
        for my_arg_type, name in zip(my_args, args):
            if name in annotations:
                annot_type = _type_check(annotations[name], msg)
            else:
                annot_type = Any
            if not issubclass(my_arg_type, annot_type):
                return False
            # TODO: If mutable type, check invariance?
        if 'return' in annotations:
            annot_return_type = _type_check(annotations['return'], msg)
            # Note contravariance here!
            if not issubclass(annot_return_type, my_result):
                return False
        # Can't find anything wrong...
        return True

    def __subclasscheck__(self, cls):
        # Compute issubclass(cls, self).
        if not isinstance(cls, CallableMeta):
            return super().__subclasscheck__(cls)
        if self.__args__ is None and self.__result__ is None:
            return True
        # We're not doing covariance or contravariance -- this is *invariance*.
        return self == cls


class Callable(Final, metaclass=CallableMeta, _root=True):
    """Callable type; Callable[[int], str] is a function of (int) -> str.

    The subscription syntax must always be used with exactly two
    values: the argument list and the return type.  The argument list
    must be a list of types; the return type must be a single type.

    There is no syntax to indicate optional or keyword arguments,
    such function types are rarely used as callback types.
    """


class GenericMeta(TypingMeta, abc.ABCMeta):
    """Metaclass for generic types."""

    # TODO: Constrain more how Generic is used; only a few
    # standard patterns should be allowed.

    # TODO: Somehow repr() of a subclass parameterized comes out with
    # module=typing.

    def __new__(cls, name, bases, namespace, parameters=None):
        if parameters is None:
            # Extract parameters from direct base classes.  Only
            # direct bases are considered and only those that are
            # themselves generic, and parameterized with type
            # variables.  Don't use bases like Any, Union, Tuple,
            # Callable or type variables.
            params = None
            for base in bases:
                if isinstance(base, TypingMeta):
                    if not isinstance(base, GenericMeta):
                        raise TypeError(
                            "You cannot inherit from magic class %s" %
                            repr(base))
                    if base.__parameters__ is None:
                        continue
                    if params is None:
                        params = []
                    for bp in base.__parameters__:
                        if isinstance(bp, TypingMeta):
                            if not isinstance(bp, TypeVar):
                                raise TypeError(
                                    "Cannot inherit from a generic class "
                                    "parameterized with a "
                                    "non-type-variable %s" % bp)
                        if bp not in params:
                            params.append(bp)
            if params is not None:
                parameters = tuple(params)

        # Check the caller's locals to see if we're overriding a
        # forward reference.  If so, update the class in place.
        f = sys._getframe(1)
        if f.f_locals and name in f.f_locals:
            overriding = f.f_locals[name]
            if (isinstance(overriding, cls) and
                overriding.__bases__ == bases and
                overriding.__parameters__ == parameters):
                self = overriding
                for k, v in namespace.items():
                    setattr(self, k, v)
                return self
        self = super().__new__(cls, name, bases, namespace, _root=True)
        self.__parameters__ = parameters
        return self

    def __repr__(self):
        r = super().__repr__()
        if self.__parameters__ is not None:
            r += '[%s]' % (
                ', '.join(_type_repr(p) for p in self.__parameters__))
        return r

    def __eq__(self, other):
        if not isinstance(other, GenericMeta):
            return NotImplemented
        return (self.__name__ == other.__name__ and
                self.__parameters__ == other.__parameters__)

    def __hash__(self):
        return hash((self.__name__, self.__parameters__))

    def __getitem__(self, params):
        if not isinstance(params, tuple):
            params = (params,)
        if not params:
            raise TypeError("Cannot have empty parameter list")
        msg = "Parameters to generic types must be types."
        params = tuple(_type_check(p, msg) for p in params)
        if self.__parameters__ is None:
            for p in params:
                if not isinstance(p, TypeVar):
                    raise TypeError("Initial parameters must be "
                                    "type variables; got %s" % p)
        else:
            if len(params) != len(self.__parameters__):
                raise TypeError("Cannot change parameter count from %d to %d" %
                                (len(self.__parameters__), len(params)))
            for new, old in zip(params, self.__parameters__):
                if isinstance(old, TypeVar) and not old.__constraints__:
                    # Substituting for an unconstrained TypeVar is always OK.
                    continue
                if not issubclass(new, old):
                    raise TypeError(
                        "Cannot substitute %s for %s in %s" %
                        (_type_repr(new), _type_repr(old), self))
        return self.__class__(self.__name__, self.__bases__,
                              dict(self.__dict__),
                              parameters=params)


class Generic(metaclass=GenericMeta):
    """Abstract base class for generic types.

    A generic type is typically declared by inheriting from an
    instantiation of this class with one or more type variables.
    For example, a generic mapping type might be defined as::

      class Mapping(Generic[KT, VT]):
          def __getitem__(self, key: KT) -> VT:
              ...
          # Etc.

    This class can then be used as follows::

      def lookup_name(mapping: Mapping, key: KT, default: VT) -> VT:
          try:
              return mapping[key]
          except KeyError:
              return default

    For clarity the type variables may be redefined, e.g.::

      X = TypeVar('X')
      Y = TypeVar('Y')
      def lookup_name(mapping: Mapping[X, Y], key: X, default: Y) -> Y:
          # Same body as above.
    """


class Undefined:
    """An undefined value.

    Example::

      x = Undefined(typ)

    This tells the type checker that x has the given type but its
    value should be considered undefined.  At runtime x is an instance
    of Undefined.  The actual type can be introspected by looking at
    x.__type__ and its str() and repr() are defined, but any other
    operations or attributes will raise an exception.
    """

    __slots__ = ['__type__']

    def __new__(cls, typ):
        typ = _type_check(typ, "Undefined(t): t must be a type.")
        self = super().__new__(cls)
        self.__type__ = typ
        return self

    __hash__ = None

    def __repr__(self):
        return '%s(%s)' % (_type_repr(self.__class__),
                           _type_repr(self.__type__))


def cast(typ, val):
    """Cast a value to a type.

    This returns the value unchanged.  To the type checker this
    signals that the return value has the designated type, but at
    runtime we intentionally don't check this.  However, we do
    insist that the first argument is a type.
    """
    _type_check(typ, "cast(t, v): t must be a type.")
    return val

from xml.dom import minidom
import weakref
import re
import logging

from intermine.util import openAnything, ReadableException

try:
    from functools import reduce
except ImportError:
    pass

logging.basicConfig()

"""
Classes representing the data model
===================================

Representations of tables and columns, and behaviour
for validating connections between them.

"""

__author__ = "Alex Kalderimis"
__organization__ = "InterMine"
__license__ = "LGPL"
__contact__ = "dev@intermine.org"


class Field(object):
    """
    A class representing columns on database tables
    ===============================================

    The base class for attributes, references and collections. All
    columns in DB tables are represented by fields

    SYNOPSIS
    --------

        >>> service = Service("http://www.flymine.org/query/service")
        >>> model = service.model
        >>> cd = model.get_class("Gene")
        >>> print "Gene has", len(cd.fields), "fields"
        >>> for field in gene_cd.fields:
        ...        print " - ", field
        Gene has 45 fields
            -  CDSs is a group of CDS objects, which link back to this as gene
            -  GLEANRsymbol is a String
            -  UTRs is a group of UTR objects, which link back to this as gene
            -  alleles is a group of Allele objects, which link back 
               to this as gene
            -  chromosome is a Chromosome
            -  chromosomeLocation is a Location
            -  clones is a group of CDNAClone objects, which link 
               back to this as gene
            -  crossReferences is a group of CrossReference objects,
                which link back to this as subject
            -  cytoLocation is a String
            -  dataSets is a group of DataSet objects,
                which link back to this as bioEntities
            -  downstreamIntergenicRegion is a IntergenicRegion
            -  exons is a group of Exon objects,
                which link back to this as gene
            -  flankingRegions is a group of GeneFlankingRegion objects,
                which link back to this as gene 
            -  goAnnotation is a group of GOAnnotation objects
            -  homologues is a group of Homologue objects,
                which link back to this as gene
            -  id is a Integer
            -  interactions is a group of Interaction objects,
                which link back to this as gene
            -  length is a Integer
            ...

    @see: L{Attribute}
    @see: L{Reference}
    @see: L{Collection}
    """

    def __init__(self, name, type_name, class_origin):
        """
        Constructor - DO NOT USE
        ========================

        THIS CLASS IS NOT MEANT TO BE INSTANTIATED DIRECTLY

        you are unlikely to need to do
        so anyway: it is recommended you access fields
        through the classes generated by the model

        @param name: The name of the reference
        @param type_name: The name of the model.Class this refers to
        @param class_origin: The model.Class this was declared in

        """
        self.name = name
        self.type_name = type_name
        self.type_class = None
        self.declared_in = class_origin

    def __repr__(self):
        return self.name + " is a " + self.type_name

    def __str__(self):
        return self.name

    @property
    def fieldtype(self):
        raise Exception("Fields should never be directly instantiated")


class Attribute(Field):
    """
    Attributes represent columns that contain actual data
    =====================================================

    The Attribute class inherits all the behaviour of L{intermine.model.Field}
    """

    @property
    def fieldtype(self):
        return "attribute"


class Reference(Field):
    """
    References represent columns that refer to records in other tables
    ==================================================================

    In addition the the behaviour and properties of Field, references
    may also have a reverse reference, if the other record points
    back to this one as well. And all references will have their
    type upgraded to a type_class during parsing
    """

    def __init__(self, name, type_name, class_origin, reverse_ref=None):
        """
        Constructor
        ===========

        In addition to the a parameters of Field, Reference also
        takes an optional reverse reference name (str)

        @param name: The name of the reference
        @param type_name: The name of the model.Class this refers to
        @param class_origin: The model.Class this was declared in
        @param reverse_ref: The name of the reverse reference (default: None)

        """
        self.reverse_reference_name = reverse_ref
        super(Reference, self).__init__(name, type_name, class_origin)
        self.reverse_reference = None

    def __repr__(self):
        """
        Return a string representation
        ==============================

        @rtype: str
        """
        s = super(Reference, self).__repr__()
        if self.reverse_reference is None:
            return s
        else:
            return (s + ", which links back to this as " +
                   self.reverse_reference.name)

    @property
    def fieldtype(self):
        return "reference"


class Collection(Reference):
    """
    Collections are references which refer to groups of objects
    ===========================================================

    Collections have all the same behaviour and properties as References
    """

    def __repr__(self):
        """Return a string representation"""
        ret = super(Collection, self).__repr__().replace(
            " is a ", " is a group of ")
        if self.reverse_reference is None:
            return ret + " objects"
        else:
            return ret.replace(", which links", " objects, which link")

    @property
    def fieldtype(self):
        return "collection"


class Class(object):
    """
    An abstraction of database tables in the data model
    ===================================================

    These objects refer to the table objects in the
    InterMine ORM layer.

    SYNOPSIS
    --------

    >>>  service = Service("http://www.flymine.org/query/service")
    >>>  model = service.model
    >>>
    >>>  if "Gene" in model.classes:
    ...      gene_cd = model.get_class("Gene")
    ...      print "Gene has", len(gene_cd.fields), "fields"
    ...      for field in gene_cd.fields:
    ...          print " - ", field.name

    OVERVIEW
    --------

    Each class can have attributes (columns) of various types,
    and can have references to other classes (tables), on either
    a one-to-one (references) or one-to-many (collections) basis

    Classes should not be instantiated by hand, but rather used
    as part of the model they belong to.

    """

    def __init__(self, name, parents, model, interface=True):
        """
        Constructor - Creates a new Class descriptor
        ============================================

        >>> cd = intermine.model.Class("Gene", ["SequenceFeature"])
        <intermine.model.Class: Gene>

        This constructor is called when deserialising the
        model - you should have no need to create Classes by hand

        @param name: The name of this class
        @param parents: a list of parental names

        """
        self.name = name
        self.parents = parents
        self.model = model
        self.parent_classes = []
        self.is_interface = interface
        self.field_dict = {}
        self.has_id = "Object" not in parents
        if self.has_id:
            # All InterMineObject classes have an id attribute.
            id_field = Attribute("id", "Integer", self)
            self.field_dict["id"] = id_field

    def __repr__(self):
        return "<%s.%s %s.%s>" % (self.__module__, self.__class__.__name__,
                                  self.model.package_name if
                                  hasattr(self.model, 'package_name')
                                  else "__test__", self.name)

    @property
    def fields(self):
        """
        The fields of this class
        ========================

        The fields are returned sorted by name. Fields
        includes all Attributes, References and Collections

        @rtype: list(L{Field})
        """
        return sorted(list(self.field_dict.values()),
                      key=lambda field: field.name)

    def __iter__(self):
        for f in list(self.field_dict.values()):
            yield f

    def __contains__(self, item):
        if isinstance(item, Field):
            return item in list(self.field_dict.values())
        else:
            return str(item) in self.field_dict

    @property
    def attributes(self):
        """
        The fields of this class which contain data
        ===========================================

        @rtype: list(L{Attribute})
        """
        return [x for x in self.fields if isinstance(x, Attribute)]

    @property
    def references(self):
        """
        fields which reference other objects
        ====================================

        @rtype: list(L{Reference})
        """
        def isRef(x): return isinstance(
            x, Reference) and not isinstance(x, Collection)
        return list(filter(isRef, self.fields))

    @property
    def collections(self):
        """
        fields which reference many other objects
        =========================================

        @rtype: list(L{Collection})
        """
        return [x for x in self.fields if isinstance(x, Collection)]

    def get_field(self, name):
        """
        Get a field by name
        ===================

        The standard way of retrieving a field

        @raise ModelError: if the Class does not have such a field

        @rtype: subclass of L{intermine.model.Field}
        """
        if name in self.field_dict:
            return self.field_dict[name]
        else:
            raise ModelError("There is no field called %s in %s" %
                             (name, self.name))

    def isa(self, other):
        """
        Check if self is, or inherits from other
        ========================================

        This method validates statements about inheritance.
        Returns true if the "other" is, or is within the
        ancestry of, this class

        Other can be passed as a name (str), or as the class object itself

        @rtype: boolean
        """
        if isinstance(other, Class):
            other_name = other.name
        else:
            other_name = other
        if self.name == other_name:
            return True
        if other_name in self.parents:
            return True
        for p in self.parent_classes:
            if p.isa(other):
                return True
        return False


class ComposedClass(Class):
    """
    An abstraction of dynamic objects that are in two classes
    ==========================================================

    These objects are structural unions of two or more different data-types.
    """

    def __init__(self, parts, model):
        self.is_interface = True
        self.parts = parts
        self.model = weakref.proxy(model)

    @property
    def parents(self):
        return reduce(lambda ps, cls: ps + cls.parents, self.parts, [])

    @property
    def name(self):
        return '_'.join(c.name for c in self.parts)

    @property
    def has_id(self):
        return "Object" not in self.parents

    @property
    def field_dict(self):
        """The combined field dictionary of all parts"""
        fields = {}
        if self.has_id:
            # All InterMineObject classes have an id attribute.
            fields["id"] = Attribute("id", "Integer", self)
        for p in self.parts:
            fields.update(p.field_dict)
        return fields

    @property
    def parent_classes(self):
        """The flattened list of parent classes, with the parts"""
        all_parents = [pc for pc in p.parent_classes for p in self.parts]
        return all_parents + self.parts


class Path(object):
    """
    A class representing a validated dotted string path
    ===================================================

    A path represents a connection between records and fields

    SYNOPSIS
    --------

        >>> service = Service("http://www.flymine.org/query/service")
            model = service.model
            path = model.make_path("Gene.organism.name")
            path.is_attribute()
        ... True
        >>> path2 = model.make_path("Gene.proteins")
            path2.is_attribute()
        ... False
        >>> path2.is_reference()
        ... True
        >>> path2.get_class()
        ... <intermine.model.Class: gene>

    OVERVIEW
    --------

    This class is used for performing validation on dotted path strings.
    The simple act of parsing it into existence will validate the path
    to some extent, but there are additional methods for verifying certain
    relationships as well
    """

    def __init__(self, path, model, subclasses={}):
        """
        Constructor
        ===========

          >>> path = Path("Gene.name", model)

        You will not need to use this constructor directly. Instead,
        use the "make_path" method on the model to construct paths for you.

        @param path: the dotted path string (eg: Gene.proteins.name)
        @type path: str
        @param model: the model to validate the path against
        @type model: L{Model}
        @param subclasses: a dict which maps
                           subclasses (defaults to an empty dict)
        @type subclasses: dict
        """
        self.model = weakref.proxy(model)
        self.subclasses = subclasses
        if isinstance(path, Class):
            self._string = path.name
            self.parts = [path]
        else:
            self._string = str(path)
            self.parts = model.parse_path_string(str(path), subclasses)

    def __str__(self):
        return self._string

    def __repr__(self):
        return ('<' + self.__module__ + "." + self.__class__.__name__ + 
                ": " + self._string + '>')

    def prefix(self):
        """
        The path one step above this path.
        ==================================

          >>> p1 = Path("Gene.exons.name", model)
          >>> p2 = p1.prefix()
          >>> print p2
          ... Gene.exons

        """
        parts = list(self.parts)
        parts.pop()
        if len(parts) < 1:
            raise PathParseError(str(self) + " does not have a prefix")
        s = ".".join([x.name for x in parts])
        return Path(s, self.model._unproxied(), self.subclasses)

    def append(self, *elements):
        """
        Construct a new path by adding elements to the end of this one.
        ===============================================================

          >>> p1 = Path("Gene.exons", model)
          >>> p2 = p1.append("name")
          >>> print p2
          ... Gene.exons.name

        This is the inverse of prefix.
        """
        s = str(self) + "." + ".".join(elements)
        return Path(s, self.model._unproxied(), self.subclasses)

    @property
    def root(self):
        """
        The descriptor for the first part of the string.
        This should always a class descriptor.

        @rtype: L{intermine.model.Class}
        """
        return self.parts[0]

    @property
    def end(self):
        """
        The descriptor for the last part of the string.

        @rtype: L{model.Class} or L{model.Field}
        """
        return self.parts[-1]

    def get_class(self):
        """
        Return the class object for this path, if it refers to a class
        or a reference. Attribute paths return None

        @rtype: L{model.Class}
        """
        if self.is_class():
            return self.end
        elif self.is_reference():
            if str(self) in self.subclasses:
                return self.model.get_class(self.subclasses[str(self)])
            return self.end.type_class
        else:
            return None

    end_class = property(get_class)

    def is_reference(self):
        """
        Return true if the path is a reference,
        eg: Gene.organism or Gene.proteins
        Note: Collections are ALSO references

        @rtype: boolean
        """
        return isinstance(self.end, Reference)

    def is_class(self):
        """
        Return true if the path just refers to a class, eg: Gene

        @rtype: boolean
        """
        return isinstance(self.end, Class)

    def is_attribute(self):
        """
        Return true if the path refers to an attribute, eg: Gene.length

        @rtype: boolean
        """
        return isinstance(self.end, Attribute)

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        i = hash(str(self))
        return (reduce(lambda a, b: a ^ b, [hash(k) ^ hash(v) 
                for k, v in list(self.subclasses.items())], i))


class ConstraintTree(object):

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def __and__(self, other):
        return ConstraintTree('AND', self, other)

    def __or__(self, other):
        return ConstraintTree('OR', self, other)

    def __iter__(self):
        for n in [self.left, self.right]:
            for subn in n:
                yield subn

    def as_logic(self, codes=None, start='A'):
        if codes is None:
            codes = (chr(c) for c in range(ord(start), ord('Z')))
        return ("(%s %s %s)" % (self.left.as_logic(codes),
                self.op, self.right.as_logic(codes)))


class ConstraintNode(ConstraintTree):

    def __init__(self, *args, **kwargs):
        self.vargs = args
        self.kwargs = kwargs

    def __iter__(self):
        yield self

    def as_logic(self, codes=None, start='A'):
        if codes is None:
            codes = (chr(c) for c in range(ord(start), ord('Z')))
        return next(codes)


class CodelessNode(ConstraintNode):

    def as_logic(self, code=None, start='A'):
        return ''


class Column(object):
    """
    A representation of a path in a query that can be constrained
    =============================================================

    Column objects allow constraints to be constructed in something
    close to a declarative style
    """

    def __init__(self, path, model, subclasses={}, query=None, parent=None):
        self._model = model
        self._query = query
        self._subclasses = subclasses
        self._parent = parent
        self.filter = self.where  # alias
        if isinstance(path, Path):
            self._path = path
        else:
            self._path = model.make_path(path, subclasses)
        self._branches = {}

    def select(self, *cols):
        """
        Create a new query with this column as the base class,
        selecting the given fields.

        If no fields are given, then just this column will be selected.
        """
        q = self._model.service.new_query(str(self))
        if len(cols):
            q.select(*cols)
        else:
            q.select(self)
        return q

    def where(self, *args, **kwargs):
        """
        Create a new query based on this column,
        filtered with the given constraint.

        also available as "filter"
        """
        q = self.select()
        return q.where(*args, **kwargs)

    def __len__(self):
        """
        Return the number of values in this column.
        """
        return self.select().count()

    def __iter__(self):
        """
        Iterate over the things this column represents.

        In the case of an attribute column, that is the values it may have.
        In the caseof a reference or class column,
        it is the objects that this path may refer to.
        """
        q = self.select()
        if self._path.is_attribute():
            for row in q.rows():
                yield row[0]
        else:
            for obj in q:
                yield obj

    def __getattr__(self, name):
        if name in self._branches:
            return self._branches[name]
        cld = self._path.get_class()
        if cld is not None:
            try:
                fld = cld.get_field(name)
                branch = Column(str(self) + "." + name, self._model,
                                self._subclasses, self._query, self)
                self._branches[name] = branch
                return branch
            except ModelError as e:
                raise AttributeError(str(e))
        raise AttributeError("No attribute '" + name + "'")

    def __str__(self):
        return str(self._path)

    def __mod__(self, other):
        if isinstance(other, tuple):
            return ConstraintNode(str(self), 'LOOKUP', *other)
        else:
            return ConstraintNode(str(self), 'LOOKUP', str(other))

    def __rshift__(self, other):
        return CodelessNode(str(self), str(other))

    __lshift__ = __rshift__

    def __eq__(self, other):
        if other is None:
            return ConstraintNode(str(self), "IS NULL")
        elif isinstance(other, Column):
            return ConstraintNode(str(self), "IS", str(other))
        elif hasattr(other, "make_list_constraint"):
            return other.make_list_constraint(str(self), "IN")
        elif isinstance(other, list):
            return ConstraintNode(str(self), "ONE OF", other)
        else:
            return ConstraintNode(str(self), "=", other)

    def __ne__(self, other):
        if other is None:
            return ConstraintNode(str(self), "IS NOT NULL")
        elif isinstance(other, Column):
            return ConstraintNode(str(self), "IS NOT", str(other))
        elif hasattr(other, "make_list_constraint"):
            return other.make_list_constraint(str(self), "NOT IN")
        elif isinstance(other, list):
            return ConstraintNode(str(self), "NONE OF", other)
        else:
            return ConstraintNode(str(self), "!=", other)

    def __xor__(self, other):
        if hasattr(other, "make_list_constraint"):
            return other.make_list_constraint(str(self), "NOT IN")
        elif isinstance(other, list):
            return ConstraintNode(str(self), "NONE OF", other)
        raise TypeError("Invalid argument for xor: %r" % other)

    def in_(self, other):
        if hasattr(other, "make_list_constraint"):
            return other.make_list_constraint(str(self), "IN")
        elif isinstance(other, list):
            return ConstraintNode(str(self), "ONE OF", other)
        raise TypeError("Invalid argument for in_: %r" % other)

    def __lt__(self, other):
        if isinstance(other, Column):
            self._parent._subclasses[str(self)] = str(other)
            self._parent._branches = {}
            return CodelessNode(str(self), str(other))
        try:
            return self.in_(other)
        except TypeError:
            return ConstraintNode(str(self), "<", other)

    def __le__(self, other):
        if isinstance(other, Column):
            return CodelessNode(str(self), str(other))
        try:
            return self.in_(other)
        except TypeError:
            return ConstraintNode(str(self), "<=", other)

    def __gt__(self, other):
        return ConstraintNode(str(self), ">", other)

    def __ge__(self, other):
        return ConstraintNode(str(self), ">=", other)


class Model(object):
    """
    A class for representing the data model of an InterMine datawarehouse
    =====================================================================

    An abstraction of the database schema

    SYNOPSIS
    --------

        >>> service = Service("http://www.flymine.org/query/service")
        >>> model = service.model
        >>> model.get_class("Gene")
        <intermine.model.Class: Gene>

    OVERVIEW
    --------

    This class represents the data model  - ie. an abstraction
    of the database schema. It can be used to introspect what
    data is available and how it is inter-related
    """

    NUMERIC_TYPES = frozenset(["int", "Integer", "float", "Float",
                               "double", "Double", "long",
                               "Long", "short", "Short"])

    LOG = logging.getLogger('Model')

    def __init__(self, source, service=None):
        """
        Constructor
        ===========

          >>> model = Model(xml)

        You will most like not need to create a model directly,
        instead get one from the Service object:

        @see: L{intermine.webservice.Service}

        @param source: the model.xml, as a local file, string, or url
        """
        assert source is not None
        self.source = source

        if service is not None:
            self.service = weakref.proxy(service)
        else:
            self.service = None

        self.classes = {}
        self.parse_model(source)
        self.vivify()

        # Make sugary aliases
        self.table = self.column

    def parse_model(self, source):
        """
        Create classes, attributes, references and 
        collections from the model.xml
        =====================================================================

        The xml can be provided as a file, url or string. This method
        is called during instantiation - it does not need to be called
        directly.

        @param source:  the model.xml, as a local file, string, or url
        @raise ModelParseError: if there is a problem parsing the source
        """
        try:
            io = openAnything(source)
            src = io.read()
            # Handle binary and text streams equally.
            if hasattr(src, 'decode'):
                src = src.decode('utf8')
            self.LOG.debug("model = [{0}]".format(src))
            doc = minidom.parseString(src)
            for node in doc.getElementsByTagName('model'):
                self.name = node.getAttribute('name')
                self.package_name = node.getAttribute('package')
                assert node.nextSibling is None, "More than one model element"
                assert (self.name and self.package_name,
                        "No model name or package name")

            for c in doc.getElementsByTagName('class'):
                class_name = c.getAttribute('name')
                assert class_name, "Name not defined in" + c.toxml()

                def strip_java_prefix(x):
                    return re.sub(r'.*\.', '', x)
                parents = [strip_java_prefix(p) for p in c.getAttribute(
                    'extends').split(' ') if len(p)]
                interface = c.getAttribute('is-interface') == 'true'
                cl = Class(class_name, parents, self, interface)
                self.LOG.debug('Created {0}'.format(cl.name))
                for a in c.getElementsByTagName('attribute'):
                    name = a.getAttribute('name')
                    type_name = strip_java_prefix(a.getAttribute('type'))
                    at = Attribute(name, type_name, cl)
                    cl.field_dict[name] = at
                    self.LOG.debug('set {0}.{1}'.format(cl.name, at.name))
                for r in c.getElementsByTagName('reference'):
                    name = r.getAttribute('name')
                    type_name = r.getAttribute('referenced-type')
                    linked_field_name = r.getAttribute('reverse-reference')
                    ref = Reference(name, type_name, cl, linked_field_name)
                    cl.field_dict[name] = ref
                    self.LOG.debug('set {0}.{1}'.format(cl.name, ref.name))
                for co in c.getElementsByTagName('collection'):
                    name = co.getAttribute('name')
                    type_name = co.getAttribute('referenced-type')
                    linked_field_name = co.getAttribute('reverse-reference')
                    col = Collection(name, type_name, cl, linked_field_name)
                    cl.field_dict[name] = col
                    self.LOG.debug('set {0}.{1}'.format(cl.name, col.name))
                self.classes[class_name] = cl
        except Exception as error:
            model_src = src if src is not None else source
            raise ModelParseError("Error parsing model", model_src, error)
        finally:
            if io is not None:
                io.close()

    def vivify(self):
        """
        Make names point to instances and insert inherited fields
        =========================================================

        This method ensures the model is internally consistent. This method
        is called during instantiaton. It does not need to be called
        directly.

        @raise ModelError: if the names point to non-existent objects
        """
        for c in list(self.classes.values()):
            c.parent_classes = self.to_ancestry(c)
            self.LOG.debug("{0.name} < {0.parent_classes}".format(c))
            for pc in c.parent_classes:
                c.field_dict.update(pc.field_dict)
            for f in c.fields:
                f.type_class = self.classes.get(f.type_name)
                if (hasattr(f, 'reverse_reference_name') and 
                    f.reverse_reference_name != ''):
                    rrn = f.reverse_reference_name
                    f.reverse_reference = f.type_class.field_dict[rrn]

    def to_ancestry(self, cd):
        """
        Returns the lineage of the class
        ================================

            >>> classes = Model.to_ancestry(cd)

        Returns the class' parents, and all the class' parents' parents

        @rtype: list(L{intermine.model.Class})
        """
        parents = cd.parents
        self.LOG.debug('{0} < {1}'.format(cd.name, cd.parents))
        def defined(x): return x is not None  # weeds out the java classes
        def to_class(x): return self.classes.get(x)
        ancestry = list(filter(defined, list(map(to_class, parents))))
        for ancestor in ancestry:
            self.LOG.debug('{0} is ancestor of {1}'.format(ancestor, cd.name))
            ancestry.extend(self.to_ancestry(ancestor))
        return ancestry

    def to_classes(self, classnames):
        """
        take a list of class names and return a list of classes
        =======================================================

            >>> classes = model.to_classes(["Gene", "Protein", "Organism"])

        This simply maps from a list of strings to a list of
        classes in the calling model.

        @raise ModelError: if the list of class names
                           includes ones that don't exist

        @rtype: list(L{intermine.model.Class})
        """
        return list(map(self.get_class, classnames))

    def column(self, path, *rest):
        return Column(path, self, *rest)

    def __getattr__(self, name):
        return self.column(name)

    def get_class(self, name):
        """
        Get a class by its name, or by a dotted path
        ============================================

            >>> model = Model("http://www.flymine.org/query/service/model")
            >>> model.get_class("Gene")
            <intermine.model.Class: Gene>
            >>> model.get_class("Gene.proteins")
            <intermine.model.Class: Protein>

        This is the recommended way of retrieving a class from
        the model. As well as handling class names, you can also
        pass in a path such as "Gene.proteins" and get the
        corresponding class back (<intermine.model.Class: Protein>)

        @raise ModelError: if the class name refers to a non-existant object

        @rtype: L{intermine.model.Class}
        """
        if name.find(',') != -1:
            names = name.split(',')
            classes = [self.get_class(n) for n in names]
            return ComposedClass(classes, self)
        elif name.find(".") != -1:
            path = self.make_path(name)
            if path.is_attribute():
                raise ModelError("'" + str(path) + "' is not a class")
            else:
                return path.get_class()
        elif name in self.classes:
            return self.classes[name]
        else:
            raise ModelError("'" + name + "' is not a class in this model")

    def make_path(self, path, subclasses={}):
        """
        Return a path object for the given path string
        ==============================================

            >>> path = model.make_path("Gene.organism.name")
            <intermine.model.Path: Gene.organism.name>

        This is recommended manner of constructing path objects.

        @type path: str
        @type subclasses: dict

        @raise PathParseError: if there is a problem parsing the path string

        @rtype: L{intermine.model.Path}
        """
        return Path(path, self, subclasses)

    def validate_path(self, path_string, subclasses={}):
        """
        Validate a path
        ===============

            >>> try:
            ...     model.validate_path("Gene.symbol")
            ...     return "path is valid"
            ... except PathParseError:
            ...     return "path is invalid"
            "path is valid"

        When you don't need to interrogate relationships
        between paths, simply using this method to validate
        a path string is enough. It guarantees that there
        is a descriptor for each section of the string,
        with the appropriate relationships

        @raise PathParseError: if there is a problem parsing the path string
        """
        try:
            self.parse_path_string(path_string, subclasses)
            return True
        except PathParseError as e:
            raise PathParseError("Error parsing '%s' (subclasses: %s)"
                                 % (path_string, str(subclasses)), e)

    def parse_path_string(self, path_string, subclasses={}):
        """
        Parse a path string into a list of descriptors - one for each section
        =====================================================================

            >>> parts = Model.parse_path_string(string)

        This method is used when making paths from a model, and
        when validating path strings. It probably won't need to
        be called directly.

        @see: L{intermine.model.Model.make_path}
        @see: L{intermine.model.Model.validate_path}
        @see: L{intermine.model.Path}
        """
        descriptors = []
        names = path_string.split('.')
        root_name = names.pop(0)

        root_descriptor = self.get_class(root_name)
        descriptors.append(root_descriptor)

        if root_name in subclasses:
            current_class = self.get_class(subclasses[root_name])
        else:
            current_class = root_descriptor

        for field_name in names:
            field = current_class.get_field(field_name)
            descriptors.append(field)

            if isinstance(field, Reference):
                key = '.'.join([x.name for x in descriptors])
                if key in subclasses:
                    current_class = self.get_class(subclasses[key])
                else:
                    current_class = field.type_class
            else:
                current_class = None

        return descriptors

    def _unproxied(self):
        return self


class ModelError(ReadableException):
    pass


class PathParseError(ModelError):
    pass


class ModelParseError(ModelError):

    def __init__(self, message, source, cause=None):
        self.source = source
        super(ModelParseError, self).__init__(message, cause)

    def __str__(self):
        base = repr(self.message) + ":" + repr(self.source)
        if self.cause is None:
            return base
        else:
            return base + repr(self.cause)

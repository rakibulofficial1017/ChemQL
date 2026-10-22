import chemql
import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document


def test_enum_members_support_auto_values_and_explicit_values(monkeypatch):
    monkeypatch.delitem(chemql.python_globals, "TestLevels", raising=False)
    monkeypatch.delitem(chemql.ENUMS, "TestLevels", raising=False)

    chemql.process_lines(
        [
            "enum TestLevels",
            "    LOW",
            "    MEDIUM = 50",
            "    HIGH",
            "endenum",
        ]
    )

    levels = chemql.python_globals["TestLevels"]
    assert [member.value for member in levels] == [1, 50, 51]
    assert chemql.process_inline("TestLevels.HIGH") is levels.HIGH


def test_struct_inherits_fields_defaults_and_methods(monkeypatch):
    for name in ("TestAnimal", "TestDog"):
        monkeypatch.delitem(chemql.python_globals, name, raising=False)
        monkeypatch.delitem(chemql.STRUCTS, name, raising=False)

    chemql.process_lines(
        [
            "struct TestAnimal",
            "    name!",
            "endstruct",
            "struct TestDog from TestAnimal",
            "    color!",
            "    isSmall = False",
            "endstruct",
        ]
    )

    animal = chemql.python_globals["TestAnimal"]
    dog_type = chemql.python_globals["TestDog"]
    dog = chemql.process_inline('TestDog{"Rex", "brown"}')
    assert isinstance(dog, animal)
    assert (dog.name, dog.color, dog.isSmall) == ("Rex", "brown", False)
    assert "name='Rex'" in repr(dog)
    cat_type_name = "TestCat"
    monkeypatch.delitem(chemql.python_globals, cat_type_name, raising=False)
    monkeypatch.delitem(chemql.STRUCTS, cat_type_name, raising=False)
    chemql.process_lines(
        ["struct TestCat from TestAnimal", "endstruct"]
    )
    cat = chemql.python_globals[cat_type_name]("Milo")
    assert isinstance(cat, animal)
    assert cat.name == "Milo"
    with pytest.raises(TypeError, match="missing required field"):
        dog_type("Rex")


def test_record_inherits_from_record_and_remains_a_tuple(monkeypatch):
    for name in ("TestIdentity", "TestProduct"):
        monkeypatch.delitem(chemql.python_globals, name, raising=False)
        monkeypatch.delitem(chemql.RECORDS, name, raising=False)

    chemql.process_lines(
        [
            "record TestIdentity",
            "    id = 1",
            "endrecord",
            "record TestProduct from TestIdentity",
            "    name",
            "endrecord",
        ]
    )

    identity = chemql.python_globals["TestIdentity"]
    product = chemql.process_inline('TestProduct{7, "Copper"}')
    assert isinstance(product, identity)
    assert tuple(product) == (7, "Copper")
    assert (product.id, product.name) == (7, "Copper")
    defaulted_product = chemql.process_inline('TestProduct{name="Copper"}')
    assert tuple(defaulted_product) == (1, "Copper")


def test_struct_can_inherit_a_record(monkeypatch):
    for name in ("TestRecordBase", "TestStructFromRecord"):
        monkeypatch.delitem(chemql.python_globals, name, raising=False)
    monkeypatch.delitem(chemql.RECORDS, "TestRecordBase", raising=False)
    monkeypatch.delitem(chemql.STRUCTS, "TestStructFromRecord", raising=False)

    chemql.process_lines(
        [
            "record TestRecordBase",
            "    id",
            "endrecord",
            "struct TestStructFromRecord from TestRecordBase",
            "    name!",
            "endstruct",
        ]
    )

    record_base = chemql.python_globals["TestRecordBase"]
    instance = chemql.python_globals["TestStructFromRecord"](3, "Oxygen")
    assert isinstance(instance, record_base)
    assert (instance.id, instance.name) == (3, "Oxygen")


def test_struct_can_inherit_python_constructor(monkeypatch):
    class PythonAnimal:
        def __init__(self, name):
            self.name = name

    monkeypatch.setitem(chemql.python_globals, "TestPythonAnimal", PythonAnimal)
    monkeypatch.delitem(chemql.python_globals, "TestPet", raising=False)
    monkeypatch.delitem(chemql.STRUCTS, "TestPet", raising=False)

    chemql.process_lines(
        [
            "struct TestPet from TestPythonAnimal",
            '    species = "unknown"',
            "endstruct",
        ]
    )

    pet = chemql.python_globals["TestPet"]("Milo", "cat")
    assert isinstance(pet, PythonAnimal)
    assert (pet.name, pet.species) == ("Milo", "cat")
    completions = {
        item.text
        for item in chemql.ChemqlCompleter().get_completions(
            Document("struct TestOther from "), CompleteEvent()
        )
    }
    assert "TestPythonAnimal" in completions


@pytest.mark.parametrize("base_expression", ["int", "[int]"])
def test_struct_can_inherit_builtin_int(base_expression, monkeypatch):
    monkeypatch.delitem(chemql.python_globals, "TestInteger", raising=False)
    monkeypatch.delitem(chemql.STRUCTS, "TestInteger", raising=False)

    chemql.process_lines(
        [
            f"struct TestInteger from {base_expression}",
            "endstruct",
        ]
    )

    integer_type = chemql.python_globals["TestInteger"]
    assert issubclass(integer_type, int)
    value = chemql.process_inline("TestInteger{42}")
    assert type(value) is integer_type
    assert value == 42


def test_record_rejects_non_record_base():
    with pytest.raises(SyntaxError, match="only inherit from another record"):
        chemql.process_lines(["record InvalidRecord from TestAnimal", "endrecord"])


def test_cli_help_describes_v1_5_features(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["chemql", "--help"])

    with pytest.raises(SystemExit) as exception:
        chemql.main()

    assert exception.value.code == 0
    output = capsys.readouterr().out
    assert "Version 1.5.0 adds enums and inheritance" in output


def test_builtin_help_documents_enums_and_inheritance():
    help_text = chemql.strip_ansi(chemql.HELP)
    syntax_help = chemql._help_text("syntax")

    assert "enum Name" in help_text
    assert "inherit from structs, records, or Python classes" in syntax_help
    assert "omitted values are generated automatically" in syntax_help
    assert "enums" in chemql.ChemqlCompleter._names()

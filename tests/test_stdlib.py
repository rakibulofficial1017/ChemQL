from decimal import Decimal
from fractions import Fraction

import chemql


def test_stdlib_help_lists_modules_and_documents_unloaded_functions():
    index = chemql.process_inline("help{stdlib}")
    decimal_help = chemql.process_inline("help{decimal}")
    function_help = chemql.process_inline("help{fractions::create}")
    math_function_help = chemql.process_inline("help{math::sqrt}")

    assert "pathlib" in index
    assert "random" in index
    assert "Base-10 decimal arithmetic" in decimal_help
    assert "create{value} or create{numerator, denominator}" in function_help
    assert "sqrt{number}" in math_function_help


def test_decimal_and_fraction_stdlib_arithmetic():
    chemql._execute_load_statement("load decimal")
    chemql._execute_load_statement("load fractions")

    assert chemql.process_inline('decimal::add{"0.1", "0.2"}') == Decimal("0.3")
    assert chemql.process_inline('fractions::add{"1/3", "1/6"}') == Fraction(1, 2)
    assert chemql.process_inline('fractions::numerator{"2/3"}') == 2


def test_random_module_can_be_seeded_for_repeatable_values():
    chemql._execute_load_statement("load random")

    chemql.process_inline("random::seed{42}")
    first = chemql.process_inline("random::randint{1, 100}")
    chemql.process_inline("random::seed{42}")

    assert chemql.process_inline("random::randint{1, 100}") == first


def test_pathlib_reads_and_writes_text_under_given_path(tmp_path):
    chemql._execute_load_statement("load pathlib")
    path = tmp_path / "stdlib-test.txt"

    written = chemql.process_inline(
        f'pathlib::write_text{{"{path}", "ChemQL"}}'
    )

    assert written == len("ChemQL")
    assert chemql.process_inline(f'pathlib::read_text{{"{path}"}}') == "ChemQL"
    assert chemql.process_inline(f'pathlib::name{{"{path}"}}') == path.name

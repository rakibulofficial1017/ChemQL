# from importlib import import_module


# chempy5 = import_module("chempy5")


# v = chempy5.execute_query("search elements name like '*h*' sort number desc")

# print(v)

from chemql import Reaction

v = Reaction("haber-process", "Haber process", "synthesis", True, [
            {"molecule": "N2", "stoichiometric_coefficient": 1, "phase": "g"},
            {"molecule": "H2", "stoichiometric_coefficient": 3, "phase": "g"}
        ],
        [
            {"molecule": "NH3", "stoichiometric_coefficient": 2, "phase": "g"}
        ],
        {
            "temperature_k": 723.15,
            "pressure_pa": 20265000,
            "catalysts": ["iron"],
            "atmosphere": "hydrogen and nitrogen"
        }, "The ammonia is typically cooled and condensed to shift the equilibrium toward products.")
print(v.equation)
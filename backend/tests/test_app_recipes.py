"""The local app lists every workflow recipe before the backend answers, and puts each one in a named group."""

import re
from pathlib import Path

from app.services.workflows import RECIPES

HOME = Path(__file__).resolve().parents[2] / "frontend" / "src" / "views" / "Home.vue"


def test_offline_recipe_list_and_groups_match_the_backend():
    vue = HOME.read_text(encoding="utf-8")
    block = vue.split("const recipes = ref(")[1].split(".map(")[0]
    fallback = re.findall(r"\['(\w+)', '([^']+)', '([^']+)'\]", block)
    assert {i for i, _, _ in fallback} == {r["id"] for r in RECIPES}
    by_id = {r["id"]: r for r in RECIPES}
    for rid, name, question in fallback:
        assert (name, question) == (by_id[rid]["name"], by_id[rid]["question"])
    groups = dict(re.findall(r"^  (\w+): '([^']+)',?$", vue.split("const groupOf = {")[1].split("}")[0], re.M))
    assert set(groups) == {r["id"] for r in RECIPES}
    symbols = vue.split("const symbols = {")[1].split("}")[0]
    assert all(re.search(rf"^\s+{rid}:", symbols, re.M) for rid in by_id)

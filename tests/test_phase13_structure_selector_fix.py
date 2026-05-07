from scripts.phase13_structure_selector_fix import refined_recipe_vectors


def test_refined_recipe_vectors_include_light_branch_wall_intermediates() -> None:
    vectors = refined_recipe_vectors()

    assert (1.0, 1.0, 1.0, 1.0, 0.0) in vectors
    assert (1.0, 1.0, 1.0, 1.0, 0.03) in vectors
    assert (0.0, 0.0, 0.0, 0.0, 1.0) in vectors


def test_refined_recipe_vectors_are_unique_and_sorted() -> None:
    vectors = refined_recipe_vectors()

    assert len(vectors) == len(set(vectors))
    assert vectors == tuple(sorted(vectors))

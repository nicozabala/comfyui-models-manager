from rich.console import Console

from comfy_network_tools.models_repo import Model
from comfy_network_tools.ui import render


def _model(category, filename, size=1, source="local"):
    return Model(
        id=0, category=category, filename=filename, size_bytes=size,
        indexed_at="t", source=source,
    )


def _rendered(table):
    console = Console(record=True, width=200)
    console.print(table)
    return console.export_text()


def test_model_table_groups_rows_under_a_category_heading_each():
    models = [
        _model("loras", "a.safetensors"),
        _model("loras", "b.safetensors"),
        _model("vae", "c.safetensors"),
    ]
    text = _rendered(render.model_table(models))

    assert text.index("loras") < text.index("a.safetensors") < text.index("b.safetensors")
    assert text.index("b.safetensors") < text.index("vae") < text.index("c.safetensors")
    # No per-row repetition of the category value once inside its group.
    assert text.count("loras") == 1
    assert text.count("vae") == 1


def test_model_table_omits_headings_for_categories_with_no_models():
    text = _rendered(render.model_table([_model("loras", "a.safetensors")]))
    assert "vae" not in text
    assert "checkpoints" not in text


def test_model_table_empty_input_has_no_category_headings():
    table = render.model_table([])
    assert table.row_count == 0

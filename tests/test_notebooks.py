from pathlib import Path
import ast
import nbformat
from nbclient import NotebookClient


def test_public_notebooks_are_clean_and_valid():
    for path in Path("notebooks").glob("*.ipynb"):
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        for cell in notebook.cells:
            if cell.cell_type == "code":
                assert cell.outputs == []
                assert cell.execution_count is None
                ast.parse(cell.source)


def test_fresh_kernel_synthetic_notebook():
    notebook = nbformat.read("notebooks/synthetic_study.ipynb", as_version=4)
    NotebookClient(
        notebook, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(Path.cwd())}}
    ).execute()
    assert not any(
        output.output_type == "error"
        for cell in notebook.cells
        if cell.cell_type == "code"
        for output in cell.outputs
    )

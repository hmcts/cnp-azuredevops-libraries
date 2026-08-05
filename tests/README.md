# Tests

This folder contains test files for scripts under `scripts/`.

## Python

### Run All Tests

From repository root:

```bash
python3 -m py_compile scripts/*.py tests/test_*.py
python3 -m unittest discover -s tests -p "test_*.py"
```

### Run One Test File

```bash
python3 -m unittest tests/test_<name>.py
```


### Run With Verbose Output
```bash
python3 -m unittest -v tests/test_<name>.py
```

### Notes

- Tests use Python standard library `unittest`.
- Keep test files named `test_*.py` so discovery works.
- If a test needs third-party packages, document and install them in project dependency files.

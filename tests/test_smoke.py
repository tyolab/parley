def test_package_imports_and_has_version():
    import parley
    assert isinstance(parley.__version__, str)
    assert parley.__version__

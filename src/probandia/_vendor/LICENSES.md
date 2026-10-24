# Vendored libraries

Pure-Python copies of the engine's dependencies, so that Probandia runs on a bare
Python 3.11 or later with no `pip install`.
Compiled accelerators (the `_yaml` extension of PyYAML) are left out.
Versions are pinned in `vendor.txt`.

| Distribution | Version | Import name | Licence | Licence text | Project |
|---|---|---|---|---|---|
| PyYAML | 6.0.3 | `yaml` | MIT | `licenses/PyYAML-LICENSE` | https://pyyaml.org/ |
| tomlkit | 0.15.1 | `tomlkit` | MIT | `licenses/tomlkit-LICENSE` | https://github.com/python-poetry/tomlkit |
| markdown-it-py | 4.2.0 | `markdown_it` | MIT | `licenses/markdown-it-py-LICENSE`, `licenses/markdown-it-py-LICENSE.markdown-it` | https://github.com/executablebooks/markdown-it-py |
| mdurl | 0.1.2 | `mdurl` | MIT | `licenses/mdurl-LICENSE` | https://github.com/executablebooks/mdurl |
